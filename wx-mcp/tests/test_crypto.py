"""
单元测试：Windows DPAPI 加密工具

验证 DATA_BLOB 结构、encrypt/decrypt 接口调用和错误处理。
注意：真正的 DPAPI 加密/解密仅限 Windows 系统。在 CI 中跑在 windows-latest 上。
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from wx_mcp import crypto


class TestDataBlob(unittest.TestCase):
    """DATA_BLOB 结构测试"""

    def test_blob_from_bytes(self):
        """从 bytes 构造 DATA_BLOB"""
        blob = crypto.DATA_BLOB(b'hello')
        self.assertEqual(blob.cbData, 5)
        self.assertIsNotNone(blob.pbData)

    def test_blob_empty(self):
        """空数据构造 DATA_BLOB"""
        blob = crypto.DATA_BLOB()
        self.assertEqual(blob.cbData, 0)


class TestEncrypt(unittest.TestCase):
    """DPAPI 加密测试"""

    @unittest.skipIf(not sys.platform.startswith('win'), 'DPAPI 仅在 Windows 可用')
    def test_encrypt_decrypt_roundtrip(self):
        """在 Windows 上，同一用户应能解密自己的加密数据"""
        plaintext = 'hello world 你好'.encode('utf-8')
        encrypted = crypto.encrypt(plaintext)
        decrypted = crypto.decrypt(encrypted)
        self.assertEqual(decrypted, plaintext)

    @unittest.skipIf(not sys.platform.startswith('win'), 'DPAPI 仅在 Windows 可用')
    def test_encrypt_returns_different_data(self):
        """加密后的数据不应与原文相同"""
        plaintext = b'test data'
        encrypted = crypto.encrypt(plaintext)
        self.assertNotEqual(encrypted, plaintext)
        self.assertGreater(len(encrypted), 0)

    @patch('wx_mcp.crypto._crypt32.CryptProtectData')
    def test_encrypt_failure_raises(self, mock_protect):
        """CryptProtectData 失败时抛出 WindowsError"""
        mock_protect.return_value = False

        with self.assertRaises(OSError):
            crypto.encrypt(b'test')


class TestDecrypt(unittest.TestCase):
    """DPAPI 解密测试"""

    @patch('wx_mcp.crypto._crypt32.CryptUnprotectData')
    def test_decrypt_failure_raises(self, mock_unprotect):
        """CryptUnprotectData 失败时抛出 WindowsError"""
        mock_unprotect.return_value = False

        with self.assertRaises(OSError):
            crypto.decrypt(b'test')

    @unittest.skipIf(not sys.platform.startswith('win'), 'DPAPI 仅在 Windows 可用')
    def test_decrypt_invalid_data_raises(self):
        """解密非法数据应抛出异常"""
        with self.assertRaises(OSError):
            crypto.decrypt(b'\x00' * 100)


class TestEncryptDecryptFile(unittest.TestCase):
    """文件加密解密测试"""

    def setUp(self):
        self.tmpfile = tempfile.mktemp(suffix='.enc')

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.unlink(self.tmpfile)

    @unittest.skipIf(not sys.platform.startswith('win'), 'DPAPI 仅在 Windows 可用')
    def test_encrypt_decrypt_file_roundtrip(self):
        """encrypt_to_file + decrypt_from_file 应返回原文"""
        plaintext = 'sensitive data 敏感数据'.encode('utf-8')
        crypto.encrypt_to_file(plaintext, self.tmpfile)

        self.assertTrue(os.path.exists(self.tmpfile))
        self.assertGreater(os.path.getsize(self.tmpfile), 0)

        decrypted = crypto.decrypt_from_file(self.tmpfile)
        self.assertEqual(decrypted, plaintext)


if __name__ == '__main__':
    unittest.main()
