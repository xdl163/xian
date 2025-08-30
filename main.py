from PyQt5.QtWidgets import QApplication

from Page.VideoApp import VideoApp
from activate import AuthorizationValidator,activate_if_needed
import sys
import settings
import Utils
from detect_xian import VideoProcessorThread


def start_background_thread():
    print('开始识别线程')
    app = QApplication(sys.argv)
    is_first = False
    if settings.window is None:
        is_first=True
        settings.window = VideoApp(settings.video_list)
    if settings.video_thread is None:
        settings.video_thread = VideoProcessorThread(settings.video_list,window=settings.window)
        settings.video_thread.start()
    if is_first:
        settings.window.show()
        sys.exit(app.exec_())




if __name__ == '__main__':
    config_path = "config.yaml"
    print(config_path)
    info_type=None
    try:
        validator = AuthorizationValidator()
        info = validator.validate()  # 验证授权
        info_type=info['type']
        print(f"授权成功，类型: {info['type']}，到期时间: {info['expires']}")
    except Exception as e:
        print(f"授权失败: {e}")
        # 触发激活流程
        if not activate_if_needed():
            print("激活失败，程序终止。")
            sys.exit(1)
    Utils.load_config(config_path)
    print(settings.xiandb)
    print(len(settings.video_list))
    start_background_thread()



#pyinstaller --onefile  src/main.py

# Machine ID: 'm4e56344694c2d643f17351508632caaa'
# Default Harddisk Serial Number: '6479_A79D_3A30_20B0'
# Default Mac address: '68:ed:a4:78:b3:4e'
# Default IPv4 address: '169.254.249.64'
# Multiple Mac addresses: <68:ed:a4:78:b3:4e,68:ed:a4:78:b3:4f>


'''
pyarmor gen --period 1 -e 2025-07-20 -b "m4e56344694c2d643f17351508632caaa" -O dist5 --pack onefile src3/main.py
pyarmor gen  -O dist4 --pack onefile src/main.py
pyinstaller --onefile  src/main.py
pyarmor gen --enable-rft main.py activate/ CamMoveDetector/ datatypes/ detect_xian/ light_cls/ modbus/ mysql_def/ Page/ settings/ Utils/ Video_diff/  
pyarmor gen --enable-bcc --pack onefile  main.py activate/ CamMoveDetector/ datatypes/ detect_xian/ light_cls/ modbus/ mysql_def/ Page/ settings/ Utils/ Video_diff/  

'''