import base64
from datetime import datetime
from .license_handler import load_license_file
from .machine_id import get_machine_id
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import settings

class AuthorizationValidator:
    def __init__(self):
        self.license_data = load_license_file()
        settings.license_data=self.license_data
        settings.passwd = self.license_data['passwd']

    def validate(self):
        """
        主函数：验证授权许可是否合法，返回解密后的授权信息。
        如果验证失败，会抛出异常。
        """
        #print("[验证器] 加载授权文件...")
        #print("[验证器] 授权文件加载成功，内容如下：")
        #print(license_data)

        #print("[验证器] 检查签名...")
        self._check_signature(self.license_data)
        #print("[验证器] 签名校验通过")

        #print("[验证器] 校验设备绑定和应用名称...")
        self._check_binding(self.license_data)
        #print("[验证器] 设备和应用校验通过")

        #print("[验证器] 检查授权是否过期...")
        self._check_expiry(self.license_data)
        #print("[验证器] 授权仍在有效期内")

        return self.license_data

    def _check_signature(self, data: dict):
        """
        验证授权签名是否合法。
        使用公钥对签名原文进行验证。
        """
        version = data.get("sign_version")
        if version != "v2":
            raise ValueError("授权签名版本不受支持")

        # 构造公钥对象
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(data["public_key"])
        )

        # 构造签名原文，必须与服务器签名时完全一致
        raw = f"{data['id']}_{data['expires']}_{data['type']}_{data['app']}_{data['issued']}_{data['sign_version']}_{data['code']}"
        #print("[验证器] 签名原文：", raw)

        # 验证签名（若失败将抛出异常）
        public_key.verify(base64.b64decode(data["signature"]), raw.encode())

    def _check_binding(self, data: dict):
        """
        检查授权文件中的设备ID和应用名是否匹配本机。
        """
        local_id = get_machine_id()
        #print("[验证器] 本机 ID：", local_id)
        #print("[验证器] 授权 ID：", data["id"])

        if data["id"] != local_id:
            raise ValueError("授权不适用于本设备")

        if data["app"] != "xianv1":
            raise ValueError("授权应用不匹配")

    def _check_expiry(self, data: dict):
        """
        检查授权是否过期（使用 UTC 日期）。
        """
        expires_date = datetime.fromisoformat(data["expires"]).date()
        current_date = datetime.utcnow().date()
        #print(f"[验证器] 当前时间：{current_date}，授权到期时间：{expires_date}")

        if current_date > expires_date:
            raise ValueError("授权已过期")
