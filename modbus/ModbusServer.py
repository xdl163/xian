#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Modbus 从站（只读）——同时支持
1) Modbus-TCP  (端口 502 / 1502 等)
2) Modbus-RTU  (串口 COM3、/dev/ttyUSB0 …)

* 仅功能码 0x03：读取保持寄存器
* 不实现任何写操作
"""

import socket, struct, threading, logging, time, sys
from typing import List, Optional, Tuple
import yaml, time
from pathlib import Path
import serial

# ---------- 日志 ----------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)s  %(message)s")

# ---------- 常量 ----------
READ_HOLDING_REGISTERS = 0x03


# ---------- CRC16(Modbus) ----------
def crc16(data: bytes) -> int:
    """返回 Modbus CRC16 (低字节在前，高字节在后)"""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            carry = crc & 0x0001
            crc >>= 1
            if carry:
                crc ^= 0xA001
    return crc & 0xFFFF


class ModbusServer:
    """
    同时支持 TCP 与 RTU（只读）
    """
    # ------------------------------------------------------------
    def __init__(
            self,
            host: str = "0.0.0.0",
            tcp_port: int = 502,
            holding_size: int = 100,

            # --- 新增: 只响应这个 Unit ID；None=接受任何地址 ---
            unit_id: Optional[int] = None,

            # ---------- RTU 串口参数 ----------
            rtu_port: Optional[str] = None,
            baudrate: int = 9600,
            bytesize: int = 8,
            parity: str = "N",
            stopbits: int = 1,
            rtu_timeout: float = 1.0,

            backlog: int = 5,
            com_cfg={}

    ):
        self.host, self.tcp_port = host, tcp_port
        self.backlog   = backlog
        self._unit_id  = unit_id            # ← 保存 Unit ID

        self.com_cfg=com_cfg
        # 数据区：保持寄存器
        self.holding_registers: List[int] = [0] * holding_size
        self._lock = threading.Lock()          # ★ 线程安全锁

        # ---------- 运行状态 & 句柄 ----------
        self._running = False
        self._tcp_sock: Optional[socket.socket] = None
        # 串口
        self._rtu_port_name = rtu_port
        self._serial: Optional["serial.Serial"] = None
        self._rtu_cfg = dict(baudrate=baudrate, bytesize=bytesize,
                             parity=parity, stopbits=stopbits,
                             timeout=rtu_timeout)

    # ------------------------------------------------------------
    # 外部 API
    def start(self):
        """后台启动 TCP 与（可选）RTU 监听"""
        if self._running:
            return
        self._running = True
        self._init_tcp()
        if self._rtu_port_name:
            if serial is None:
                logging.error("未安装 pyserial，无法启用 RTU")
            else:
                self._init_rtu()
        logging.info("Modbus 服务器已启动 (TCP%s)",
                     " + RTU" if self._serial else "")

    def stop(self):
        """停止全部监听"""
        self._running = False
        if self._tcp_sock:
            self._tcp_sock.close()
        if self._serial:
            self._serial.close()
        logging.info("Modbus 服务器已停止")

    # ------------------------------------------------------------
    # TCP 通道
    def _init_tcp(self):
        self._tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp_sock.bind((self.host, self.tcp_port))
        self._tcp_sock.listen(self.backlog)
        threading.Thread(target=self._tcp_accept_loop, daemon=True).start()
        logging.info("TCP 监听 %s:%d", self.host, self.tcp_port)

    def _tcp_accept_loop(self):
        while self._running:
            try:
                cli_sock, cli_addr = self._tcp_sock.accept()
            except OSError:
                break
            threading.Thread(target=self._tcp_client_loop,
                             args=(cli_sock, cli_addr),
                             daemon=True).start()

    def _tcp_client_loop(self, sock: socket.socket, addr):
        with sock:
            try:
                while self._running:
                    frame = sock.recv(260)
                    if not frame:
                        break
                    rsp = self._handle_tcp_request(frame)
                    if rsp:
                        sock.sendall(rsp)
            except Exception as e:
                logging.error("TCP %s: %s", addr, e)

    # ------------------------------------------------------------
    # RTU 通道
    def _init_rtu(self):
        self._serial = serial.Serial(
            port=self._rtu_port_name,
            **self._rtu_cfg)
        threading.Thread(target=self._rtu_loop, daemon=True).start()
        logging.info("RTU 监听 %s  (%s, %d,%s,%d)",
                     self._serial.port, self._rtu_cfg["baudrate"],
                     self._rtu_cfg["bytesize"],
                     self._rtu_cfg["parity"], self._rtu_cfg["stopbits"])

    def _rtu_loop(self):
        """
        读取 RTU 帧：简单做法——按字节流不断填缓冲区，
        检测静默时间间隔 > 3.5 字符后判定一帧结束。
        为简洁起见：这里直接用串口的 timeout 特性，
        每次读到数据就尝试解析一帧。
        """
        buf = bytearray()
        while self._running:
            try:
                chunk = self._serial.read(256)
            except serial.SerialException:
                break
            if not chunk:
                continue
            buf.extend(chunk)

            # 简易帧拆分：最短 8 字节 (addr+func+2*2+crc)
            while len(buf) >= 8:
                # 尝试解析前 N 字节为一帧
                frame, used = self._try_parse_rtu_frame(buf)
                if frame:
                    rsp = self._handle_rtu_request(frame)
                    if rsp:
                        self._serial.write(rsp)
                    del buf[:used]          # 删除已解析部分
                else:
                    # 无法解析，丢弃一个字节重试
                    buf.pop(0)

    def _try_parse_rtu_frame(self, buf: bytearray) -> Tuple[bytes, int]:
        """
        尝试把 buf 前部解析为完整 RTU 帧
        返回 (frame_bytes, used_len) 或 (None, 0)
        """
        if len(buf) < 8:
            return None, 0
        # 数据长度 = addr(1)+func(1)+len  (读寄存器请求固定 6B)
        frame_len = 8
        frame = bytes(buf[:frame_len])
        # 校验 CRC
        if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
            return None, 0
        return frame, frame_len

    # ------------------------------------------------------------
    # 协议处理 —— TCP (带 MBAP)
    def _handle_tcp_request(self, frame: bytes) -> Optional[bytes]:
        try:
            tid, proto, length = struct.unpack(">HHH", frame[:6])
            uid = frame[6]
            fcode = frame[7]
            pdu = frame[8:]
            if length != len(pdu) + 2:
                return None
        except struct.error:
            return None

        if fcode != READ_HOLDING_REGISTERS or len(pdu) < 4:
            return None

        # ⇩ 只回应目标地址匹配的请求
        if self._unit_id is not None and uid != self._unit_id:
            return None

        addr, qty = struct.unpack(">HH", pdu[:4])
        data = self._read_holding(addr, qty)
        if data is None:
            return None
        payload = struct.pack("B", len(data)) + data
        length_resp = len(payload) + 2
        mbap = struct.pack(">HHHB", tid, 0, length_resp, uid)
        return mbap + struct.pack("B", fcode) + payload

    # 协议处理 —— RTU
    def _handle_rtu_request(self, frame: bytes) -> Optional[bytes]:
        """ frame = addr(1) + func(1) + pdu + crc(2) """
        addr = frame[0]
        fcode = frame[1]
        pdu = frame[2:-2]

        if self._unit_id is not None and addr != self._unit_id:
            return None

        if fcode != READ_HOLDING_REGISTERS or len(pdu) < 4:
            return None
        start, qty = struct.unpack(">HH", pdu[:4])
        data = self._read_holding(start, qty)
        if data is None:
            return None
        payload = struct.pack("B", len(data)) + data
        rsp = bytes([addr, fcode]) + payload
        crc = crc16(rsp).to_bytes(2, "little")
        return rsp + crc

    # ------------------------------------------------------------
    def _read_holding(self, addr: int, qty: int) -> Optional[bytes]:
        if not (0 <= addr < len(self.holding_registers)) or addr + qty > len(self.holding_registers):
            return None
        with self._lock:                              # ★
            regs = self.holding_registers[addr: addr + qty]
        return struct.pack(">" + "H" * qty, *regs)

    # ========= 用户可调用的写接口 =========
    def write_register(self, addr: int, value: int) -> bool:
        """
        把保持寄存器 addr 写成 value (低 16bit)。
        返回 True=成功 / False=越界
        server.write_register(10, 1234)         # 把寄存器 10 写成 0x04D2
        """
        if not (0 <= addr < len(self.holding_registers)):
            return False
        with self._lock:
            self.holding_registers[addr] = value & 0xFFFF
        return True

    def write_register_bit(self, addr: int, bit: int, bit_val: int) -> bool:
        """
        把保持寄存器 addr 的第 bit 位改成 bit_val (0/1)。
        bit 取 0~15；返回 True=成功 / False=参数非法
        server.write_register_bit(10, 3, 1)     # 把寄存器 10 的 bit3 置 1
        server.write_register_bit(10, 0, 0)     # 清掉 bit0
        """
        if not (0 <= bit < 16):
            return False
        if not (0 <= addr < len(self.holding_registers)):
            return False
        with self._lock:
            if bit_val:
                self.holding_registers[addr] |=  (1 << bit)
            else:
                self.holding_registers[addr] &= ~(1 << bit)
        return True


    def update_video_xian(self,video_id,xian_light):
        plc_adds=self.com_cfg[int(video_id)]
        xian_status = ''.join([str(0 if light else 1) for light in xian_light])
        # 拆分成前16位和后面部分
        first_part = xian_status[:16]  # 前16位
        second_part = xian_status[16:]  # 剩余部分

        # 如果后面部分不足16位，右侧补0
        second_part = second_part.ljust(16, '0')
        second_part=second_part[::-1]
        first_part=first_part[::-1]
        xian_status1 = int(first_part, 2)
        xian_status2 = int(second_part, 2)
        self.write_register(plc_adds[0],xian_status1)
        self.write_register(plc_adds[1],xian_status2)



    def update_video_abnormal(self,video_id, video_type):
        plc_adds = self.com_cfg[int(video_id)]
        if video_type:
            self.write_register_bit(plc_adds[2],plc_adds[3], 1)
        else:
            self.write_register_bit(plc_adds[2],plc_adds[3], 0)

        # 写回新的值

    def update_video_online(self,video_id: int, value: int):
        plc_adds = self.com_cfg[int(video_id)]
        self.write_register_bit(plc_adds[4],plc_adds[5], value)


    def update_video(self,video_id,xian_light,video_type):
        self.update_video_xian(video_id,xian_light)
        self.update_video_abnormal(video_id,video_type)


# def load_yaml(cfg_path):
#     cfg_path = Path(cfg_path)
#     cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["modbus"]
#     com_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["videos"]
#
#     # ---------- 创建服务器 ----------
#     server = ModbusServer(
#         host        = cfg.get("host", "0.0.0.0"),
#         tcp_port    = cfg.get("port", 502),
#         holding_size= cfg.get("num", 100),
#         unit_id     = cfg.get("unit_id"),          # 新增参数
#         rtu_port    = cfg.get("rtu_port",None),
#         baudrate    = cfg.get("baudrate", 9600),
#         bytesize    = cfg.get("bytesize", 8),
#         parity      = cfg.get("parity", "N"),
#         stopbits    = cfg.get("stopbits", 1),
#         rtu_timeout = cfg.get("timeout", 1.0),
#         com_cfg = com_cfg,
#     )
#     server.start()
#     return server

# # ------------------ 示例 ------------------
# if __name__ == "__main__":
#     # ---------- 读取 YAML ----------
#     server=load_yaml("../PLC_add.yaml")
#     try:
#         while True:
#             time.sleep(1)
#     except KeyboardInterrupt:
#         server.stop()