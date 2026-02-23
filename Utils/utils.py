import os
import time
from pathlib import Path
import cv2

import yaml
from PyQt5.QtGui import QImage

from datatypes.Video import Video
from mysql_def import XianDB

import settings


DOCKER_DEFAULT_VIDEO_PATH = "/app/videos"
DOCKER_DEFAULT_VIDEO_OUTPUT_PATH = "/app/video_output"
DOCKER_DEFAULT_SAVE_IMG_PATH = "/app/save_images"


def _is_docker_env() -> bool:
    if os.environ.get("RUNNING_IN_DOCKER", "") == "1":
        return True
    return os.path.exists("/.dockerenv")

def cv2_to_qimage(cv_img):
    """
    将 OpenCV 图像（numpy 数组）转换为 QImage。
    """
    # 如果是彩色图像 (BGR)，需要将其转换为 RGB
    if len(cv_img.shape) == 3:
        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)

    # 转换为 QImage
    h, w, ch = cv_img.shape
    bytes_per_line = ch * w
    qimg = QImage(cv_img.data, w, h, bytes_per_line, QImage.Format_RGB888)
    return qimg

def load_config(config_path):
    settings.config_path=config_path
    # 读取 YAML 配置文件
    with open(config_path, 'r', encoding='utf-8') as file:
        # with open("b.yaml", 'r', encoding='utf-8') as file:
        config = yaml.safe_load(file)

    if _is_docker_env():
        config['video_path'] = os.environ.get('VIDEO_PATH', DOCKER_DEFAULT_VIDEO_PATH)
        config['video_output_path'] = os.environ.get('VIDEO_OUTPUT_PATH', DOCKER_DEFAULT_VIDEO_OUTPUT_PATH)
        config['save_img_path'] = os.environ.get('SAVE_IMG_PATH', DOCKER_DEFAULT_SAVE_IMG_PATH)
        print('Docker 环境: 使用默认路径(忽略 YAML 中路径配置)')


    print(config)
    # 从配置中获取参数并加载视频
    load_all_video(
        config['video_path'],
        IMAGE_SIZE=tuple(config['image_size']),
        crop_size=tuple(config.get('crop_size', [config.get('roi_width', 40), config.get('roi_height', 40)])),
        save=config['save'],
        save_img=config['save_img'],
        save_csv=config['save_csv'],
        db_host=config['db_host'],
        db_port=config['db_port'],
        db_user=config['db_user'],
        db_password=config['db_password'],
        db_save_day=config['db_save_day'],
        ERROR_WIN=config['error_win'],
        CORRECT_WIN=config['correct_win'],
        video_output_path=config['video_output_path'],
        save_img_path=config['save_img_path'],
        BUF_SIZE=config['BUF_SIZE'],
        HISTORY_LEN=config['HISTORY_LEN'],
        plc_conf_path=config['PLC_yaml'],
        medianBlur_ksize=config['medianBlur_ksize'],
        threshold_thresh=config['threshold_thresh'],
        kernel_ksize=config['kernel_ksize'],
        kernel_ksize2=config['kernel_ksize2'],
        point_max_size=config['point_max_size'],
        model_threshold=config.get('model_threshold', 0.9),
        model_path=config.get('model_path', 'model_int8.onnx'),
        recognition_fps=float(config.get('recognition_fps', 3.0))

    )

def load_all_video(dir_path,IMAGE_SIZE=(1280,720),crop_size=[6,6],
                   save=False,save_img=False,save_csv=False,
                   db_host = '127.0.0.1',db_port = 3306,
                   ERROR_WIN = 6,CORRECT_WIN = 6,
                   db_user='root',db_password='xu12345678gh',
                   db_save_day=10,
                   save_img_path=r'C:\Users\10561\Pictures\xian',
                   video_output_path='diff_results',
                   BUF_SIZE=3,
                   HISTORY_LEN=6,
                   plc_conf_path=None,
                    medianBlur_ksize=11,
                    threshold_thresh=5,
                    kernel_ksize=(10, 14),
                    kernel_ksize2=(24, 100),
                    point_max_size=20,
                    model_threshold=0.9,
                    model_path="model_int8.onnx",
                   recognition_fps=3.0
                   ):

    settings.IMAGE_SIZE = IMAGE_SIZE
    settings.dir_path = dir_path
    settings.HISTORY_LEN = HISTORY_LEN
    settings.crap_w=int(crop_size[0]/2)
    settings.crap_h=int(crop_size[1]/2)
    settings.BUF_SIZE=BUF_SIZE
    settings.set_recognition_fps(recognition_fps)

    settings.db_host = db_host
    settings.db_port = db_port
    settings.db_user = db_user
    settings.db_password = db_password
    settings.save_img = save_img
    settings.save_img_path = save_img_path
    settings.db_save_day=db_save_day


    settings.medianBlur_ksize=medianBlur_ksize
    settings.threshold_thresh=threshold_thresh
    settings.kernel_ksize=kernel_ksize
    settings.kernel_ksize2=kernel_ksize2
    settings.model_threshold = float(model_threshold)
    settings.model_path = str(model_path)

    settings.save=save
    settings.save_csv=save_csv

    settings.ERROR_WIN = ERROR_WIN
    settings.CORRECT_WIN = CORRECT_WIN
    settings.modbusServer=modbus_load_yaml(plc_conf_path)
    if os.path.isdir(video_output_path):
        settings.video_output_path=os.path.join(video_output_path,f"{time.time()}")
    else:
        with open(video_output_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
            output_paths=config['videos']
            for video_id,path in output_paths.items():
                output_paths[video_id] = os.path.join(path,str(time.time()))
            settings.video_output_paths=output_paths
    settings.xiandb=XianDB(host=settings.db_host, port=settings.db_port, user=settings.db_user, password=settings.db_password,
                           save_img_path=settings.save_img_path,db_save_day=settings.db_save_day,save_img=settings.save_img)
    for filename in os.listdir(dir_path):
        print('加载',filename)
        yaml_path=os.path.join(dir_path, filename)
        video=load_video_yaml(yaml_path)
        if video:
            settings.video_list.append(video)
        else:
            print(f'{filename}加载失败')


def modbus_load_yaml(cfg_path):
    from modbus import ModbusServer
    cfg_path = Path(cfg_path)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["modbus"]
    com_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))["videos"]

    # ---------- 创建服务器 ----------
    modbusServer = ModbusServer(
        host        = cfg.get("host", "0.0.0.0"),
        tcp_port    = cfg.get("port", 502),
        holding_size= cfg.get("num", 100),
        unit_id     = cfg.get("unit_id"),          # 新增参数
        rtu_port    = cfg.get("rtu_port",None),
        baudrate    = cfg.get("baudrate", 9600),
        bytesize    = cfg.get("bytesize", 8),
        parity      = cfg.get("parity", "N"),
        stopbits    = cfg.get("stopbits", 1),
        rtu_timeout = cfg.get("timeout", 1.0),
        com_cfg = com_cfg,
    )
    modbusServer.start()
    return modbusServer

def load_video_yaml(yaml_path):
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        video_type = data.get("video_type", "")
        if video_type=='':
            print('video_type缺失')
            return None
        video_url=data.get("video_url", "")
        if video_url=='':
            print('video_url缺失')
            return None
        if video_type == "rtsp":
            video=Video(rtsp_url=video_url)
        elif video_type == "http":
            video=Video(http_url=video_url)
        else:
            print('未知类型')
            return None
        video.load_yaml(yaml_path)
        return video

    except Exception as e:
        print("load_yaml 解析失败：", e)
        return None
