from collections import deque
import hashlib

dir_path=None
IMAGE_SIZE=(1280,720)
crop_size=[6,6]
save=False
save_csv=False
save_interval=60
video_output_path='diff_results'
ERROR_WIN = 6
CORRECT_WIN = 6
video_output_paths=None
plc_conf_path=None,
RTSP_RECONNECT_INTERVAL = 5  # RTSP 连接重试间隔（秒）
HTTP_RECONNECT_INTERVAL = 5  # HTTP 连接重试间隔（秒）
RELINK_TIME=6*60*60#定时重连
crap_w=3
crap_h=3
HISTORY_LEN = 6          # 想保留多少帧历史就写多少
BUF_SIZE = 3          # 缓冲区大小
bg_frames=1      #好像没啥用
csv_name='video_csv.csv'
point_max_size=20#最大长度
model_size=40
model_threshold=0.9
model_path="model_int8.onnx"


label_video_id=-1
show_id=-1

video_list=[]
video_thread = None
window=None


config_path=None

passwd=hashlib.sha256("123457".encode('utf-8')).hexdigest()

license_data=None
recognition_fps=3.0
fetch_sleep_idle=0.2
fetch_sleep_full=0.5


def get_frame_interval():
    fps=max(float(recognition_fps),0.1)
    return 1.0/fps

def refresh_timing_by_fps():
    global fetch_sleep_idle,fetch_sleep_full
    base=get_frame_interval()
    fetch_sleep_idle=max(0.01,base*0.5)
    fetch_sleep_full=max(0.05,base)


def set_recognition_fps(value):
    global recognition_fps
    try:
        recognition_fps = max(0.1, float(value))
    except Exception:
        recognition_fps = 3.0
    refresh_timing_by_fps()

refresh_timing_by_fps()

perf_elapsed_queue = deque(maxlen=1000)


def push_elapsed(value):
    try:
        perf_elapsed_queue.append(float(value))
    except Exception:
        pass


def get_elapsed_series():
    return list(perf_elapsed_queue)
