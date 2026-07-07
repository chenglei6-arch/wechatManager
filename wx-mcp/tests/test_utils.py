"""
单元测试：工具函数（utils.py）

测试时间戳转换、ZSTD 解压、错误处理等公共工具函数。
"""
import unittest

from wx_mcp.utils import normalize_timestamp, timestamp_to_iso, decompress


class TestNormalizeTimestamp(unittest.TestCase):
    """时间戳归一化测试"""

    def test_seconds(self):
        """秒级时间戳保持不变"""
        result = normalize_timestamp(1_700_000_000)
        self.assertEqual(result, 1_700_000_000.0)

    def test_milliseconds(self):
        """毫秒级时间戳转为秒"""
        result = normalize_timestamp(1_700_000_000_000)
        self.assertEqual(result, 1_700_000_000.0)

    def test_microseconds(self):
        """微秒级时间戳转为秒"""
        result = normalize_timestamp(1_700_000_000_000_000)
        self.assertEqual(result, 1_700_000_000.0)

    def test_zero(self):
        """零值时间戳"""
        result = normalize_timestamp(0)
        self.assertEqual(result, 0.0)

    def test_negative_raises(self):
        """负数应抛出 ValueError"""
        with self.assertRaises(ValueError):
            normalize_timestamp(-1)

    def test_too_large_raises(self):
        """超出 1e18 应抛出 ValueError"""
        with self.assertRaises(ValueError):
            normalize_timestamp(1e19)

    def test_invalid_type_raises(self):
        """非数字类型应抛出 ValueError"""
        with self.assertRaises(ValueError):
            normalize_timestamp("not_a_number")  # type: ignore

    def test_2033_boundary_seconds(self):
        """2033 年后的秒级时间戳（> 1e12）不被误判"""
        # 2033-05-18 的秒级时间戳约 2_000_000_000
        result = normalize_timestamp(2_000_000_000)
        self.assertEqual(result, 2_000_000_000.0)

    def test_boundary_between_seconds_and_ms(self):
        """接近 1e12 边界值的秒级时间戳"""
        # 2001-09-09 的秒级时间戳 1_000_000_000（10位）
        result = normalize_timestamp(1_000_000_000)
        self.assertEqual(result, 1_000_000_000.0)


class TestTimestampToIso(unittest.TestCase):
    """时间戳转 ISO 字符串测试"""

    def test_seconds_to_iso(self):
        """秒级时间戳转 ISO 格式"""
        result = timestamp_to_iso(1_700_000_000)
        self.assertIn('2023', result)
        self.assertIn('-11-', result)

    def test_milliseconds_to_iso(self):
        """毫秒级时间戳转 ISO 格式"""
        result = timestamp_to_iso(1_700_000_000_000)
        self.assertIn('2023', result)

    def test_zero_returns_epoch(self):
        """零值返回 1970-01-01"""
        result = timestamp_to_iso(0)
        self.assertIn('1970', result)

    def test_negative_returns_str(self):
        """负数返回原始输入字符串"""
        result = timestamp_to_iso(-1)
        self.assertEqual(result, '-1')

    def test_none_raises(self):
        """None 应导致 ValueError 并返回字符串"""
        result = timestamp_to_iso(None)  # type: ignore
        self.assertEqual(result, 'None')


class TestDecompress(unittest.TestCase):
    """消息解压测试"""

    def test_empty_content(self):
        """空内容返回空字符串"""
        result = decompress(b'')
        self.assertEqual(result, '')

    def test_none_content(self):
        """None 内容返回空字符串"""
        result = decompress(None)  # type: ignore
        self.assertEqual(result, '')

    def test_plain_utf8(self):
        """未压缩的 UTF-8 文本直接解码"""
        result = decompress('你好世界'.encode('utf-8'))
        self.assertEqual(result, '你好世界')

    def test_invalid_utf8_with_replacement(self):
        """无效 UTF-8 使用替换字符"""
        result = decompress(b'\xff\xfe\x00\x01')
        self.assertIsInstance(result, str)


if __name__ == '__main__':
    unittest.main()
