import csv
import os
import random
import re
import threading
import time

from collections import deque
import cv2
import numpy as np
import requests
import yaml
from CamMoveDetector import CamMoveDetector
from Video_diff import Video_diff
import  settings

def extract_ips(text):
    # 匹配 IPv4 地址的正则表达式
    ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
    ips = re.findall(ip_pattern, text)

    # 过滤掉数值超出范围的 IP（0-255）
    valid_ips = [ip for ip in ips if all(0 <= int(part) <= 255 for part in ip.split('.'))]
    if len(valid_ips) > 0:
        return valid_ips[0]
    else:
        return '0.0.0.0'

class Video:
    """统一封装文件 / HTTP / RTSP 视频源，并在内部维护 **最多 2 帧** 的缓冲区。

    * 独立后台线程 `_FrameFetcher` 持续抓取原始帧；
    * 当缓冲区已满 (2 帧) 时，线程休眠 0.3 s 不再抓取；
    * `next_frame()` 从缓冲区弹出 1 帧供外部使用；若缓冲区为空返回 `None`。
    """
    # -------------------- 内部常量 --------------------
    _SLEEP_WHEN_FULL = 0.5 # 缓冲区满时抓取线程休眠

    # -------------------- 构造 --------------------
    def __init__(self, video_path=None, http_url=None, rtsp_url=None,start_t=True):
        # ---------- 基本属性 ----------
        self.yaml_path = None
        self.last_time = None
        self.this_time = int(time.time())

        self.save_idx=0

        self.history_queue: deque[np.ndarray | None] = deque(maxlen=settings.HISTORY_LEN)


        self.plc_last_time = time.time()


        # --- 选择视频源类型 & 打开 ---
        if video_path:
            self.video_type = "file"
            self.cap = cv2.VideoCapture(video_path)
            self.video_id = os.path.splitext(os.path.basename(video_path))[0]
            self.video_path = video_path
            self.frame_index = 0
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps_update_num = max(int(self.fps * 0.3), 1)
            self.ip = '0.0.0.0'
        elif http_url:
            self.video_type = "http"
            self.http_url = http_url
            self.ip = extract_ips(self.http_url)
        elif rtsp_url:
            self.video_type = "rtsp"
            self.cap = None
            self.ip = extract_ips(rtsp_url)
            self.rtsp_url=rtsp_url
        else:
            raise ValueError("必须提供 video_path / http_url / rtsp_url 之一")
        self.link_time=time.time()
        # ---------- 运行时状态 ----------


        self.camMoveDetector=CamMoveDetector()#摄像头移动检测
        self.video_diff=Video_diff()

        # self.lock = threading.Lock()
        self.id = int(random.random() * 10000)

        self.last_base_mask =None
        # (其余检测 / 配置字段保持原样——此处省略，与原代码一致) --------------------
        self.xian_points = None
        self.laser_emitter = None
        self.laser_wall = None
        self.add_type = ''
        self.error_counts = None
        self.correct_counts = None
        self.xian_light = None
        self.hsv_lower = None
        self.hsv_upper = None
        self.have_abnormal = False
        self.abnormal_time = -1
        self.light_send_error = False
        self.light_send_error_time = -1
        self.laser_wall_error = False
        self.laser_wall_error_time = -1
        self.camMove = False
        self.this_frame = None
        self.roi = None
        self._fail_mask = None
        self._pass_mask = None
        self.bg_buffers_green=[]

        self.xian_allow_light=None

        self.bg_buffers=None
        self.white_num=None

        self.PLC_add1=1
        self.PLC_add2=2

        self.csvs=[]
        self.last_state=1
        self.frame_width,self.frame_height  =settings.IMAGE_SIZE
        if start_t:
            # ---------- 帧缓冲区 & 抓取线程 ----------
            self._frame_buffer: deque[np.ndarray] = deque(maxlen=settings.BUF_SIZE)
            self._buf_lock = threading.Lock()
            self._fetcher_stop = threading.Event()
            self._fetcher_thread = threading.Thread(target=self._fetcher_loop, daemon=True)
            self._fetcher_thread.start()

    # ---------------------------------------------------------------------
    #  公共接口
    # ---------------------------------------------------------------------
    def next_frame(self):
        """弹出 1 帧；若缓冲区为空则返回 `None`。"""
        if not self._fetcher_thread.is_alive():
            print("⚠️ 抓取线程已经死掉了！")
            # 可以选择重新启动线程
            self._fetcher_thread = threading.Thread(target=self._fetcher_loop, daemon=True)
            self._fetcher_thread.start()
            print("✅ 已重新启动抓取线程。")
        with self._buf_lock:
            if not self._frame_buffer:
                return None

            self.this_frame = self._frame_buffer.popleft()
            self.history_queue.append(self.this_frame)      # 最新帧入队
            return self.this_frame.copy()

    def last_img(self):          # 最老的一帧
        return self.history_queue[0] if self.history_queue else None

    def start(self):
        """兼容旧接口（已在构造时启动抓取线程）。"""
        pass

    def stop(self):
        """停止内部抓取线程。"""
        self._fetcher_stop.set()
        self._fetcher_thread.join(timeout=1)
        # 若使用 cv2.VideoCapture，需要在此释放
        if hasattr(self, 'cap') and self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass

    def save_img(self, img, path):
        # 生成图片文件名
        img_name = f"{self.save_idx}.jpg"

        # 拼接目录结构
        dir_path = os.path.join(path, f"{self.id}-{self.video_id}-{self.add_type}")

        # 确保目录存在，如果不存在则递归创建
        os.makedirs(dir_path, exist_ok=True)

        # 保存图片
        try:
            # 拼接最终保存路径并保存图片
            full_path = os.path.join(dir_path, img_name)
            success = cv2.imwrite(full_path, img)
            if success:
                pass
            else:
                print(f"Failed to save image at: {full_path}")
        except Exception as e:
            print(f"Error saving image: {e}")



        # 更新保存的图片索引（确保唯一性）
        self.save_idx += 1



    def save_img_csv(self,path):
        # 生成图片文件名
        img_name = f"{self.save_idx}.jpg"
        # 拼接目录结构
        dir_path = os.path.join(path, f"{self.id}-{self.video_id}-{self.add_type}")
        # 确保目录存在，如果不存在则递归创建
        os.makedirs(dir_path, exist_ok=True)
        csv_file=os.path.join(dir_path, settings.csv_name)
        # ---------- ① 创建 CSV（如果不存在） ----------
        if not os.path.exists(csv_file):
            with open(csv_file, mode='w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["video_id","time","img_path","xian", "type"])
            print("✅ CSV文件已创建:", csv_file)
        # 保存图片
        try:
            # 拼接最终保存路径并保存图片
            full_path = os.path.join(dir_path, img_name)
            success = cv2.imwrite(full_path, self.this_frame)
            if success:
                pass
            else:
                print(f"Failed to save image at: {full_path}")
            xian_status = ''.join([str(1 if light else 0) for light in self.xian_light])
            self.csvs.append([time.time(),self.id, img_name, xian_status,self.get_video_type()])
            if len(self.csvs) > 100:
                with open(csv_file, mode='a', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    for i in self.csvs:
                        writer.writerow(i)
                self.csvs=[]
        except Exception as e:
            print(f"Error saving image: {e}")
        # 更新保存的图片索引（确保唯一性）
        self.save_idx += 1


    # ---------------------------------------------------------------------
    #  内部实现
    # ---------------------------------------------------------------------
    def _fetcher_loop(self):
        # update_video_photo(self.id,1)
        """后台线程：不断抓帧填充缓冲区。"""
        session = requests.Session()

        while not self._fetcher_stop.is_set():
            # 缓冲区已满 -> 休眠
            with self._buf_lock:
                if len(self._frame_buffer) >= settings.BUF_SIZE:
                    need_sleep = True
                else:
                    need_sleep = False
            if need_sleep:
                time.sleep(Video._SLEEP_WHEN_FULL)
                continue

            frame = self._read_raw_frame(session)
            if frame is None:
                print('获取画面失败')
                # 文件视频到结尾直接退出循环
                if self.video_type == 'file':
                    break
                time.sleep(0.5)
                continue

            with self._buf_lock:
                self._frame_buffer.append(frame)
            time.sleep(0.2)

    # ---------------- 原始读取逻辑抽取 ----------------
    def _read_raw_frame(self,session):
        """按视频类型读取 1 原始帧 (同步调用)。"""
        self.last_time = self.this_time
        self.this_time = int(time.time())

        if self.video_type == 'file':
            self.frame_index += self.fps_update_num
            if self.frame_index >= self.total_frames:
                return None
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.frame_index)
            ret, frame = self.cap.read()
            if not ret:
                return None
            self.this_frame = frame.copy()
            return frame

        if self.video_type == 'http':
            frame = self._read_http_frame(session)
            return frame

        if self.video_type == 'rtsp':
            frame = self._read_rtsp_frame()
            return frame

        return None
    def _read_http_frame(self,session):
        """从HTTP流读取帧，并定期重新连接。"""
        if time.time()-self.plc_last_time>10:
            settings.modbusServer.update_video_online(self.id,self.last_state)
            self.plc_last_time = time.time()
        try:
            resp = session.get(self.http_url, timeout=10)
            if resp.status_code == 200:
                if self.last_state==0:
                    self.last_state=1
                settings.modbusServer.update_video_online(self.id,1)
                self.plc_last_time = time.time()
                img_array = np.frombuffer(resp.content, dtype=np.uint8)
                frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                return frame
            else:
                if self.last_state==1:
                    self.last_state=0
                    settings.modbusServer.update_video_online(self.id,0)
                    self.plc_last_time = time.time()
                print(f"[HTTP Error] url={self.http_url}  status={resp.status_code}  reason={resp.reason}")
        except Exception as e:
            print(f"HTTP 请求异常: {e}")
            if self.last_state==1:
                self.last_state=0
                settings.modbusServer.update_video_online(self.id,0)
                self.plc_last_time = time.time()

        print("HTTP连接丢失，尝试重新连接...")
        time.sleep(settings.HTTP_RECONNECT_INTERVAL)
        return None

    def _read_rtsp_frame(self):
        """从RTSP流读取帧，并定期重新连接。"""
        if self.cap is None:
            self._reconnect_rtsp()

        if time.time()-self.link_time>settings.RELINK_TIME:
            print('定时重新连接')
            self._reconnect_rtsp()

        if not self.cap.isOpened():
            print("RTSP连接丢失，尝试重新连接...")
            self._reconnect_rtsp()
        ret, frame = self.cap.read()
        if not ret:
            print("RTSP获取帧失败")
            self._reconnect_rtsp()
            return None
        frame=cv2.resize(frame,(self.frame_width,self.frame_height))
        self.this_frame = frame.copy()
        return frame
    def _reconnect_rtsp(self):
        """重新连接RTSP流。"""
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            print("RTSP连接失败，稍后再试...")
            time.sleep(settings.RTSP_RECONNECT_INTERVAL)
            self._reconnect_rtsp()  # 递归重连
        self.cap.set(cv2.CAP_PROP_HW_ACCELERATION, 2)  # 0: None, 1: CUDA, 2: QSV
        self.link_time = time.time()


    def load_yaml(self, yaml_path):
        try:
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f) or {}
            self.yaml_path = yaml_path
            self.video_id = data.get("video_id", "")
            self.add_type = data.get("add_type", "")
            self.id = data.get("id", "")
            self.hsv_range = data.get("hsv_range", {
                "h_min": 0, "h_max": 179,
                "s_min": 50, "s_max": 255,
                "v_min": 178, "v_max": 255
            })
            self.hsv_lower = np.array([self.hsv_range['h_min'], self.hsv_range['s_min'], self.hsv_range['v_min']])
            self.hsv_upper = np.array([self.hsv_range['h_max'], self.hsv_range['s_max'], self.hsv_range['v_max']])

            width = self.frame_width
            height = self.frame_height

            # 加载纱线点
            yarn_data = data.get("yarn", {})
            self.xian_points = {}

            # 对 yarn_data 的键（label）进行排序，将其转换为整数进行排序
            sorted_labels = sorted(yarn_data.keys(), key=int)

            for label in sorted_labels:
                point = yarn_data[label]
                if len(point) == 2:
                    x, y = point
                else:
                    x, y, conf = point

                # 处理坐标
                if x <= 1 and y <= 1:
                    x, y = int(x * width), int(y * height)

                x1 = max(x - settings.crap_w, 0)
                y1 = max(y - settings.crap_h, 0)
                x2 = min(x + settings.crap_w, width - 1)
                y2 = min(y + settings.crap_h, height - 1)

                self.xian_points[label] = (x, y, x1, y1, x2, y2)

            self.bg_buffers=[deque(maxlen=settings.bg_frames) for _ in self.xian_points]
            # 加载激光发射器
            emitter_data = data.get("laser_emitter", [])
            self.laser_emitter = []
            for x, y in emitter_data:
                if x <= 1 and y <= 1:
                    x, y = int(x * width), int(y * height)
                x1 = max(x - settings.crap_w, 0)
                y1 = max(y - settings.crap_h, 0)
                x2 = min(x + settings.crap_w, width - 1)
                y2 = min(y + settings.crap_h, height - 1)
                self.laser_emitter.append([x, y, x1, y1, x2, y2])

            # 加载激光墙
            wall_data = data.get("laser_wall", [])
            self.laser_wall = []
            for x, y in wall_data:
                if x <= 1 and y <= 1:
                    x, y = int(x * width), int(y * height)
                x1 = max(x - settings.crap_w, 0)
                y1 = max(y - settings.crap_h, 0)
                x2 = min(x + settings.crap_w, width - 1)
                y2 = min(y + settings.crap_h, height - 1)
                self.laser_wall.append([x, y, x1, y1, x2, y2])
            n=len(self.xian_points.keys())
            self.xian_light =  np.ones(n, dtype=bool)
            self.xian_allow_light = np.ones(len(self.xian_points), dtype=bool)
            self.error_counts = np.zeros(n, dtype=np.uint16)
            self.correct_counts = np.zeros(n, dtype=np.uint16)
            self._fail_mask     = np.empty(n, dtype=bool)
            self._pass_mask     = np.empty(n, dtype=bool)
            self.white_num      = np.zeros(n, dtype=np.uint16)
            # self.bg_buffers_green = [deque(maxlen=10) for _ in range(len(self.xian_points))]

            return True

        except Exception as e:
            print("load_yaml 解析失败：", e)
            return False


    def get_xian_num(self):
        num=0
        for i in self.xian_light:
            if i:
                num+=1
        return num


    def get_video_type(self):
        if self.have_abnormal:
            return 'abnormal'
        if self.light_send_error:
            return 'laser_emitter_error'
        if self.laser_wall_error:
            return 'laser_wall_error'
        return 'right'

    def getRoi(self):
        if self.roi is None:
            minx = -1
            miny = -1
            maxx = -1
            maxy = -1
            # 遍历 xian_points
            for idx, (x, y, _, _, _, _) in self.xian_points.items():
                if minx == -1 or x < minx:
                    minx = x
                if miny == -1 or y < miny:
                    miny = y
                if maxx == -1 or x > maxx:
                    maxx = x
                if maxy == -1 or y > maxy:
                    maxy = y

            # 遍历 laser_emitter
            for x, y, _, _, _, _ in self.laser_emitter:
                if minx == -1 or x < minx:
                    minx = x
                if miny == -1 or y < miny:
                    miny = y
                if maxx == -1 or x > maxx:
                    maxx = x
                if maxy == -1 or y > maxy:
                    maxy = y

            # 遍历 laser_wall
            for x, y, _, _, _, _ in self.laser_wall:
                if minx == -1 or x < minx:
                    minx = x
                if miny == -1 or y < miny:
                    miny = y
                if maxx == -1 or x > maxx:
                    maxx = x
                if maxy == -1 or y > maxy:
                    maxy = y

            # 原始宽高
            w = maxx - minx
            h = maxy - miny

            # 扩大 0.3 倍
            expand_w = int(w * 0.3 / 2)
            expand_h = int(h * 10 / 2)

            # 计算扩展后的位置，确保不超出边界
            minx = max(0, minx - expand_w)
            miny = max(0, miny - expand_h)
            maxx = min(self.frame_width - 1, maxx + expand_w)
            maxy = min(self.frame_height - 1, maxy + expand_h)

            self.roi = (minx, miny, maxx, maxy)
        return self.roi

    # Video 类中添加：
    def load_yaml_dict(self, yaml_data: dict) -> bool:
        try:
            # 你的原始 load_yaml 应该读文件，这里可以转换逻辑
            import tempfile
            import yaml
            with tempfile.NamedTemporaryFile(delete=False, suffix='.yaml') as tmp:
                yaml.dump(yaml_data, tmp)
                tmp.flush()
                return self.load_yaml(tmp.name)
        except Exception as e:
            print(f"[load_yaml_dict] YAML 加载失败: {e}")
            return False

    def to_dict(self):
        return {
            "id": self.id,
            "video_id": self.video_id,
            "add_type": self.add_type,
            "ip": self.ip
        }







class Zone:
    '''
    区域
    '''
    def __init__(self,name, videos=None):
        self.name = name
        if videos is None:
            videos = []
        self.videos = videos


    def add_video(self,video):
        self.videos.append(video)


