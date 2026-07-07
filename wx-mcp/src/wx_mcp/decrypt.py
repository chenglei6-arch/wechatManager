"""
WeChat 4.x SQLCipher 4 数据库解密

使用从微信进程内存提取的密钥解密 SQLCipher 4 加密的数据库。
"""
import os, struct, hashlib, hmac as hmac_mod
from Crypto.Cipher import AES

PAGE_SIZE = 4096
SALT_SIZE = 16
IV_SIZE = 16
HMAC_SIZE = 64
RESERVE_SIZE = 80  # IV(16) + HMAC(64)
SQLITE_HEADER = b'SQLite format 3\x00'


def derive_mac_key(enc_key: bytes, salt: bytes) -> bytes:
    """从加密密钥和盐值派生HMAC密钥"""
    mac_salt = bytes(b ^ 0x3a for b in salt)
    return hashlib.pbkdf2_hmac('sha512', enc_key, mac_salt, 2, dklen=32)


def decrypt_page(enc_key: bytes, page_data: bytes, pgno: int) -> bytes:
    """
    解密单个 SQLCipher 4 页面，输出 4096 字节标准 SQLite 页面

    页面结构:
      Page 1: [salt(16)] [encrypted(4000)] [IV(16)] [HMAC(64)]
      Page N: [encrypted(4016)] [IV(16)] [HMAC(64)]
    """
    iv = page_data[PAGE_SIZE - RESERVE_SIZE : PAGE_SIZE - RESERVE_SIZE + IV_SIZE]

    if pgno == 1:
        encrypted = page_data[SALT_SIZE : PAGE_SIZE - RESERVE_SIZE]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted)
        return bytes(SQLITE_HEADER + decrypted + b'\x00' * RESERVE_SIZE)
    else:
        encrypted = page_data[:PAGE_SIZE - RESERVE_SIZE]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted)
        return decrypted + b'\x00' * RESERVE_SIZE


def verify_page1(enc_key: bytes, page_data: bytes) -> bool:
    """验证第一页的 HMAC，确认密钥正确"""
    salt = page_data[:SALT_SIZE]
    mac_key = derive_mac_key(enc_key, salt)

    p1_hmac_data = page_data[SALT_SIZE : PAGE_SIZE - RESERVE_SIZE + IV_SIZE]
    p1_stored_hmac = page_data[PAGE_SIZE - HMAC_SIZE : PAGE_SIZE]

    hm = hmac_mod.new(mac_key, p1_hmac_data, hashlib.sha512)
    hm.update(struct.pack('<I', 1))

    return hmac_mod.compare_digest(hm.digest(), p1_stored_hmac)


def decrypt_database(in_path: str, out_path: str, enc_key: bytes) -> bool:
    """解密整个数据库文件"""
    if not os.path.exists(in_path):
        return False

    with open(in_path, 'rb') as f:
        page1 = f.read(PAGE_SIZE)

    if len(page1) < PAGE_SIZE:
        return False

    # 验证 HMAC
    if not verify_page1(enc_key, page1):
        return False

    # 解密所有页面
    with open(in_path, 'rb') as fin, open(out_path, 'wb') as fout:
        pgno = 1
        while True:
            page = fin.read(PAGE_SIZE)
            if not page:
                break
            if len(page) < PAGE_SIZE:
                page = page + b'\x00' * (PAGE_SIZE - len(page))

            decrypted = decrypt_page(enc_key, page, pgno)
            fout.write(decrypted)
            pgno += 1

    return True


def get_db_salt(db_path: str) -> bytes:
    """读取数据库文件的盐值（前16字节）"""
    with open(db_path, 'rb') as f:
        return f.read(SALT_SIZE)


def load_keys(keys_file: str) -> dict:
    """加载密钥文件 {salt_hex: key_hex}"""
    import json
    with open(keys_file, 'r', encoding='utf-8') as f:
        return json.load(f)
