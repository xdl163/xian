import requests
from .machine_id import get_machine_id
from .license_handler import save_license_file
import settings
import hashlib

def activate_if_needed():
    code = input("请输入激活码：").strip()
    payload = {
        "machine_id": get_machine_id(),
        "code": code,
        "app": "xianv1"
    }
    try:
        resp = requests.post("https://83.229.125.195:8343/activate", json=payload, verify=False)
        if resp.status_code == 200:
            resp_data = resp.json()  # 获取原始响应 JSON，通常是 dict
            resp_data['passwd'] = settings.passwd
            save_license_file(resp_data)
            settings.license_data=resp_data
            print("激活成功，授权信息已保存。")
            return True
        else:
            print(f"激活失败：{resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"激活异常：{e}")
    return False
