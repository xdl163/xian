import base64
import json
import hashlib
from Crypto.Cipher import AES
from .machine_id import get_machine_id
from Crypto.Random import get_random_bytes

SALT = "XIAN-SALT-2025"
LICENSE_PATH = "activate.lic"

def load_license_file():
    with open(LICENSE_PATH, "rb") as f:
        encoded = f.read()
    raw = base64.b64decode(encoded)
    iv = raw[:16]
    encrypted = raw[16:]

    key = hashlib.sha256((get_machine_id() + SALT).encode()).digest()
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(encrypted)
    json_str = decrypted.rstrip(b"\x00").decode("utf-8")
    return json.loads(json_str)

def save_license_file(data: dict):
    json_str = json.dumps(data)
    raw_bytes = json_str.encode()
    iv = get_random_bytes(16)
    key = hashlib.sha256((get_machine_id() + SALT).encode()).digest()
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = raw_bytes + b"\x00" * ((16 - len(raw_bytes) % 16) or 16)
    encrypted = cipher.encrypt(padded)
    with open(LICENSE_PATH, "wb") as f:
        f.write(base64.b64encode(iv + encrypted))
