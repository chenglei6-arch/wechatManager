"""
单元测试：SQLCipher 4 解密引擎

使用已知明文/密钥对验证解密逻辑的正确性。
生成测试用 SQLCipher 4 加密页面并验证 decrypt_page / verify_page1。
"""
import hashlib
import hmac as hmac_mod
import os
import struct
import tempfile
import unittest
from Crypto.Cipher import AES

from wx_mcp.decrypt import (
    PAGE_SIZE,
    SQLITE_HEADER,
    decrypt_database,
    decrypt_page,
    derive_mac_key,
    get_db_salt,
    verify_page1,
)


def _make_test_page1(enc_key: bytes, salt: bytes) -> bytes:
    """
    构造一个测试用 SQLCipher 4 首页（第1页）

    结构: [salt(16)] [plaintext(4000)] [IV(16)] [HMAC(64)]
    """
    iv = b'\x01' * 16
    plaintext = b'\x00' * 4000

    cipher = AES.new(enc_key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(plaintext)

    # HMAC 计算: SQLCipher 4 对 encrypted + IV 做 HMAC，末尾追加页号
    mac_key = derive_mac_key(enc_key, salt)
    hm = hmac_mod.new(mac_key, encrypted + iv, hashlib.sha512)
    hm.update(struct.pack('<I', 1))
    hmac_val = hm.digest()

    return salt + encrypted + iv + hmac_val


def _make_test_pageN(enc_key: bytes, pgno: int) -> bytes:
    """构造测试用非首页页面"""
    iv = struct.pack('<I', pgno) + b'\x00' * 12
    plaintext = b'\xff' * 4016

    cipher = AES.new(enc_key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(plaintext)

    return encrypted + iv + b'\x00' * 64


class TestDecryptPage(unittest.TestCase):
    """页面解密测试"""

    def setUp(self):
        self.enc_key = bytes.fromhex('8eb5dc3f0697db96c151dd768dd34e85552f80820ff543e16115e244199c2371')
        self.salt = bytes.fromhex('0ad62a412425fef8938a2677ed3bc173')

    def test_decrypt_page1_returns_sqlite_header(self):
        """第1页解密后应以 SQLite header 开头"""
        page = _make_test_page1(self.enc_key, self.salt)
        result = decrypt_page(self.enc_key, page, pgno=1)
        self.assertTrue(result.startswith(SQLITE_HEADER),
                        f"预期以 {SQLITE_HEADER!r} 开头, 实际 {result[:18]!r}")

    def test_decrypt_page1_length(self):
        """第1页解密后应为完整 4096 字节"""
        page = _make_test_page1(self.enc_key, self.salt)
        result = decrypt_page(self.enc_key, page, pgno=1)
        self.assertEqual(len(result), PAGE_SIZE)

    def test_decrypt_pageN_length(self):
        """非首页解密后应为完整 4096 字节"""
        page = _make_test_pageN(self.enc_key, 5)
        result = decrypt_page(self.enc_key, page, pgno=5)
        self.assertEqual(len(result), PAGE_SIZE)

    def test_decrypt_pageN_returns_plaintext(self):
        """非首页解密后应恢复原始内容（尾部80字节为 '\0'）"""
        page = _make_test_pageN(self.enc_key, 3)
        result = decrypt_page(self.enc_key, page, pgno=3)
        # 前 4016 字节应为 0xff
        self.assertEqual(result[:4016], b'\xff' * 4016)


class TestVerifyPage1(unittest.TestCase):
    """HMAC 验证测试"""

    def setUp(self):
        self.enc_key = bytes.fromhex('8eb5dc3f0697db96c151dd768dd34e85552f80820ff543e16115e244199c2371')
        self.salt = bytes.fromhex('0ad62a412425fef8938a2677ed3bc173')

    def test_verify_valid_page1(self):
        """正确密钥应通过 HMAC 验证"""
        page = _make_test_page1(self.enc_key, self.salt)
        self.assertTrue(verify_page1(self.enc_key, page))

    def test_verify_wrong_key_fails(self):
        """错误密钥应不通过 HMAC 验证"""
        page = _make_test_page1(self.enc_key, self.salt)
        wrong_key = b'\x00' * 32
        self.assertFalse(verify_page1(wrong_key, page))

    def test_verify_corrupted_page_fails(self):
        """损坏的数据应不通过 HMAC 验证"""
        page = bytearray(_make_test_page1(self.enc_key, self.salt))
        page[50] ^= 0x01  # 篡改一个字节
        self.assertFalse(verify_page1(self.enc_key, bytes(page)))


class TestGetDbSalt(unittest.TestCase):
    """盐值读取测试"""

    def test_get_db_salt_returns_first_16_bytes(self):
        """get_db_salt 应返回文件前16字节"""
        salt = b'\xaa' * 16
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(salt + b'\xbb' * 100)
            path = f.name
        try:
            result = get_db_salt(path)
            self.assertEqual(result, salt)
        finally:
            os.unlink(path)


class TestDeriveMacKey(unittest.TestCase):
    """HMAC 密钥派生测试"""

    def test_derive_mac_key_xor_salt(self):
        """derive_mac_key 应对 salt 进行 0x3a XOR"""
        enc_key = b'\x11' * 32
        salt = b'\x00' * 16
        expected_salt = b'\x3a' * 16
        result = derive_mac_key(enc_key, salt)
        expected = hashlib.pbkdf2_hmac('sha512', enc_key, expected_salt, 2, dklen=32)
        self.assertEqual(result, expected)

    def test_derive_mac_key_returns_32_bytes(self):
        """派生密钥应为 32 字节"""
        result = derive_mac_key(b'\x22' * 32, b'\x33' * 16)
        self.assertEqual(len(result), 32)


class TestDecryptDatabase(unittest.TestCase):
    """完整数据库解密测试（单页）"""

    def test_decrypt_database_nonexistent_file(self):
        """不存在的文件应返回 False"""
        result = decrypt_database('/nonexistent/path.db', 'NUL', b'\x00' * 32)
        self.assertFalse(result)

    def test_decrypt_database_too_small(self):
        """过小的文件应返回 False"""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as f:
            f.write(b'\x00' * 100)
            path = f.name
        try:
            out = os.path.join(tempfile.gettempdir(), 'out.db')
            result = decrypt_database(path, out, b'\x00' * 32)
            self.assertFalse(result)
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
