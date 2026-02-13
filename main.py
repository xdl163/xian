import settings
import Utils
from detect_xian import VideoProcessorThread
from Page.web_app import run_web_server


def start_background_thread():
    print('开始识别线程')
    if settings.video_thread is None:
        settings.video_thread = VideoProcessorThread(settings.video_list,window=None)
        settings.video_thread.start()




if __name__ == '__main__':
    config_path = "config.yaml"
    print(config_path)
    info_type=None
    # try:
    #     validator = AuthorizationValidator()
    #     info = validator.validate()  # 验证授权
    #     info_type=info['type']
    #     print(f"授权成功，类型: {info['type']}，到期时间: {info['expires']}")
    # except Exception as e:
    #     print(f"授权失败: {e}")
    #     # 触发激活流程
    #     if not activate_if_needed():
    #         print("激活失败，程序终止。")
    #         sys.exit(1)
    Utils.load_config(config_path)
    print(settings.xiandb)
    print(len(settings.video_list))
    start_background_thread()
    run_web_server(host='0.0.0.0', port=5000)



#pyinstaller --onefile  src/main.py

# Machine ID: 'm4e56344694c2d643f17351508632caaa'
# Default Harddisk Serial Number: '6479_A79D_3A30_20B0'
# Default Mac address: '68:ed:a4:78:b3:4e'
# Default IPv4 address: '169.254.249.64'
# Multiple Mac addresses: <68:ed:a4:78:b3:4e,68:ed:a4:78:b3:4f>


'''
pyarmor gen  -O dist4 --pack onefile src/main.py
pyinstaller --onefile  src/main.py
可用：
pyarmor gen --enable-bcc --pack onefile  main.py activate/ CamMoveDetector/ datatypes/ detect_xian/ light_cls/ modbus/ mysql_def/ Page/ settings/ Utils/ Video_diff/  

set PYARMOR_CC=E:\\PycharmProjects\\xian\\clang.exe

pyarmor gen main.py activate/ CamMoveDetector/ datatypes/ detect_xian/ light_cls/ modbus/ mysql_def/ Page/ settings/ Utils/ Video_diff/  

'''
