import subprocess
import hashlib


# 执行 PowerShell 命令并返回输出结果
def run_powershell(cmd):
    result = subprocess.run(
        ["powershell", "-Command", cmd],  # 执行 PowerShell 命令
        capture_output=True,  # 捕获输出（stdout 和 stderr）
        text=True,  # 以文本模式返回结果
        shell=True  # 启用 shell（在某些环境中是必须的）
    )
    return result.stdout.strip()  # 返回去除空白字符的结果


# 获取机器唯一 ID
def get_machine_id():
    try:
        # 获取主板序列号
        serial = run_powershell(
            "Get-WmiObject Win32_BaseBoard | Select-Object -ExpandProperty SerialNumber") or "noserial"

        # 获取第一块物理磁盘的序列号（系统盘）
        disk = run_powershell("(Get-PhysicalDisk)[0].SerialNumber") or "nodisk"

        # 获取 CPU ID（ProcessorId）
        cpu_id = run_powershell("Get-WmiObject Win32_Processor | Select-Object -ExpandProperty ProcessorId") or "nocpu"

    except Exception as e:
        return f"Error: {e}"  # 如果有异常，返回错误信息

    # 拼接硬件信息作为原始字符串
    raw = f"{serial}-{disk}-{cpu_id}"
    # print("原始硬件信息:", raw)

    # 使用 SHA256 对原始信息进行哈希处理，生成唯一机器 ID
    return hashlib.sha256(raw.encode()).hexdigest()


# 主函数入口
if __name__ == "__main__":
    print("机器ID =", get_machine_id())
