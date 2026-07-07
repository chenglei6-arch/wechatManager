"""
单元测试：微信密钥提取模块

使用 unittest.mock 模拟 psutil 和 pymem，验证进程查找和密钥提取逻辑。
"""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import psutil

from wx_mcp import key


class TestFindWechatPid(unittest.TestCase):
    """查找微信进程 PID 测试"""

    def _make_proc(self, pid: int, name: str, exe: str):
        """创建模拟进程对象"""
        proc = MagicMock()
        proc.info = {'pid': pid, 'name': name, 'exe': exe}
        return proc

    @patch('wx_mcp.key.psutil.process_iter')
    def test_find_wechat_main_process(self, mock_iter):
        """应找到主 Weixin.exe 进程，排除 crashpad"""
        procs = [
            self._make_proc(100, 'Weixin.exe', r'C:\Program Files\WeChat\Weixin.exe'),
            self._make_proc(101, 'Weixin.exe', r'C:\Program Files\WeChat\crashpad\Weixin.exe'),
        ]
        mock_iter.return_value = procs

        pid = key.find_wechat_pid()
        self.assertEqual(pid, 100)

    @patch('wx_mcp.key.psutil.process_iter')
    def test_no_wechat_returns_none(self, mock_iter):
        mock_iter.return_value = []

        pid = key.find_wechat_pid()
        self.assertIsNone(pid)

    @patch('wx_mcp.key.psutil.process_iter')
    def test_skips_inaccessible_processes(self, mock_iter):
        good_proc = self._make_proc(200, 'Weixin.exe', r'C:\WeChat\Weixin.exe')
        bad_proc = MagicMock()
        bad_proc.info = {'pid': 0}
        type(bad_proc).info = PropertyMock(side_effect=psutil.AccessDenied())

        mock_iter.return_value = [bad_proc, good_proc]

        pid = key.find_wechat_pid()
        self.assertEqual(pid, 200)

    @patch('wx_mcp.key.psutil.process_iter')
    def test_wechat_no_exe_skipped(self, mock_iter):
        """name 匹配但 exe 为 None 的进程应跳过"""
        proc = self._make_proc(300, 'Weixin.exe', None)
        mock_iter.return_value = [proc]

        pid = key.find_wechat_pid()
        self.assertIsNone(pid)


class TestExtractKeys(unittest.TestCase):
    """从进程内存提取密钥测试"""

    @patch('wx_mcp.key.pymem.Pymem')
    def test_extract_keys_success(self, mock_pymem_class):
        mock_pm = MagicMock()
        mock_pymem_class.return_value = mock_pm

        # 模拟内存扫描结果：一个密钥对
        raw_data = b"x'8eb5dc3f0697db96c151dd768dd34e85552f80820ff543e16115e244199c2371" \
                   b"0ad62a412425fef8938a2677ed3bc173'"
        mock_pm.pattern_scan_all.return_value = [0x1000]
        mock_pm.read_bytes.return_value = raw_data

        keys = key.extract_keys(target_pid=1234)

        self.assertEqual(len(keys), 1)
        self.assertIn('0ad62a412425fef8938a2677ed3bc173', keys)
        self.assertEqual(
            keys['0ad62a412425fef8938a2677ed3bc173'],
            '8eb5dc3f0697db96c151dd768dd34e85552f80820ff543e16115e244199c2371',
        )

    @patch('wx_mcp.key.pymem.Pymem')
    def test_extract_keys_no_matches(self, mock_pymem_class):
        mock_pm = MagicMock()
        mock_pymem_class.return_value = mock_pm
        mock_pm.pattern_scan_all.return_value = []

        keys = key.extract_keys(target_pid=1234)
        self.assertEqual(keys, {})

    @patch('wx_mcp.key.pymem.Pymem')
    def test_extract_keys_skips_garbage_addresses(self, mock_pymem_class):
        """第一个地址读取失败被跳过，第二个成功提取"""
        mock_pm = MagicMock()
        mock_pymem_class.return_value = mock_pm
        mock_pm.pattern_scan_all.return_value = [0x1000, 0x2000]

        valid_entry = ("x'" + "a" * 64 + "b" * 32 + "'").encode('utf-8')
        mock_pm.read_bytes.side_effect = [
            Exception('读取失败'),
            valid_entry,
        ]

        keys = key.extract_keys(target_pid=1234)
        self.assertEqual(len(keys), 1)
        self.assertIn("b" * 32, keys)  # salt 是 key
        self.assertEqual(keys["b" * 32], "a" * 64)

    @patch('wx_mcp.key.find_wechat_pid')
    @patch('wx_mcp.key.pymem.Pymem')
    def test_extract_keys_auto_pid(self, mock_pymem_class, mock_find_pid):
        """不传 PID 时自动查找"""
        mock_find_pid.return_value = 5678
        mock_pm = MagicMock()
        mock_pymem_class.return_value = mock_pm
        mock_pm.pattern_scan_all.return_value = []

        keys = key.extract_keys()
        self.assertEqual(keys, {})

    @patch('wx_mcp.key.find_wechat_pid')
    def test_extract_keys_no_pid_raises(self, mock_find_pid):
        """微信未运行时抛出 RuntimeError"""
        mock_find_pid.return_value = None

        with self.assertRaises(RuntimeError) as ctx:
            key.extract_keys()
        self.assertIn('微信', str(ctx.exception))


class TestSaveLoadKeys(unittest.TestCase):
    """密钥持久化测试"""

    def setUp(self):
        self.tmpfile = tempfile.mktemp(suffix='.json')
        self.keys = {
            'salt1': 'key1' * 32,
            'salt2': 'key2' * 32,
        }

    def tearDown(self):
        if os.path.exists(self.tmpfile):
            os.unlink(self.tmpfile)

    @patch('wx_mcp.key.crypto.encrypt')
    def test_save_keys_encrypted(self, mock_encrypt):
        """保存时用 DPAPI 加密"""
        mock_encrypt.return_value = b'encrypted_blob'

        key.save_keys(self.keys, self.tmpfile)

        self.assertTrue(os.path.exists(self.tmpfile))
        with open(self.tmpfile, 'rb') as f:
            content = f.read()
        self.assertTrue(content.startswith(key._DPAPI_MAGIC))
        self.assertIn(b'encrypted_blob', content)

    @patch('wx_mcp.key.crypto.decrypt')
    def test_load_keys_encrypted(self, mock_decrypt):
        """加载加密密钥文件"""
        plaintext = json.dumps(self.keys).encode('utf-8')
        mock_decrypt.return_value = plaintext

        with open(self.tmpfile, 'wb') as f:
            f.write(key._DPAPI_MAGIC + b'encrypted_blob')

        loaded = key.load_keys(self.tmpfile)
        self.assertEqual(loaded, self.keys)

    def test_load_keys_plaintext_compat(self):
        """兼容旧版明文格式"""
        with open(self.tmpfile, 'w') as f:
            json.dump(self.keys, f)

        loaded = key.load_keys(self.tmpfile)
        self.assertEqual(loaded, self.keys)


if __name__ == '__main__':
    import psutil
    unittest.main()
