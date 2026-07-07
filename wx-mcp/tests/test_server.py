"""
单元测试：MCP Server

模拟 reader 和 sender 模块，验证 MCP 工具定义的正确性和错误处理。
"""
import json
import unittest
from unittest.mock import MagicMock, patch

from wx_mcp.server import (
    mcp,
    list_contacts,
    get_recent_sessions,
    read_messages,
    send_wechat_message,
    batch_send_messages,
    wechat_status,
)


class TestListContacts(unittest.TestCase):
    """list_contacts 工具测试"""

    @patch('wx_mcp.server.get_reader')
    def test_list_all_contacts(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.get_contacts.return_value = [
            {'username': 'wxid_a', 'remark': '张三', 'nick_name': '阿三', 'alias': 'zhangsan'},
            {'username': 'wxid_b', 'remark': '', 'nick_name': '李四', 'alias': ''},
        ]
        mock_get_reader.return_value = mock_reader

        result = list_contacts()
        self.assertIn('张三', result)
        self.assertIn('wxid_a', result)
        self.assertIn('李四', result)
        self.assertNotIn('❌', result)

    @patch('wx_mcp.server.get_reader')
    def test_list_contacts_with_keyword(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.get_contacts.return_value = [
            {'username': 'wxid_a', 'remark': '张三', 'nick_name': '阿三', 'alias': ''},
        ]
        mock_get_reader.return_value = mock_reader

        result = list_contacts(keyword='张三', limit=5)
        self.assertIn('张三', result)

    @patch('wx_mcp.server.get_reader')
    def test_no_contacts_returns_message(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.get_contacts.return_value = []
        mock_get_reader.return_value = mock_reader

        result = list_contacts()
        self.assertIn('未找到联系人', result)

    @patch('wx_mcp.server.get_reader')
    def test_error_returns_error_message(self, mock_get_reader):
        mock_get_reader.side_effect = RuntimeError('模拟错误')

        result = list_contacts()
        self.assertIn('❌', result)


class TestGetRecentSessions(unittest.TestCase):
    """get_recent_sessions 工具测试"""

    @patch('wx_mcp.server.get_reader')
    def test_sessions_success(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.get_sessions.return_value = [
            {'strNickName': '张三', 'strContent': '你好'},
            {'strNickName': '李四', 'strContent': '收到'},
        ]
        mock_get_reader.return_value = mock_reader

        result = get_recent_sessions()
        self.assertIn('张三', result)
        self.assertIn('李四', result)
        self.assertNotIn('❌', result)

    @patch('wx_mcp.server.get_reader')
    def test_no_sessions(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.get_sessions.return_value = []
        mock_get_reader.return_value = mock_reader

        result = get_recent_sessions()
        self.assertIn('未找到会话', result)

    @patch('wx_mcp.server.get_reader')
    def test_error_handling(self, mock_get_reader):
        mock_get_reader.side_effect = RuntimeError('模拟错误')

        result = get_recent_sessions()
        self.assertIn('❌', result)


class TestReadMessages(unittest.TestCase):
    """read_messages 工具测试"""

    @patch('wx_mcp.server.get_reader')
    def test_read_messages_success(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.get_contacts.return_value = [
            {'username': 'wxid_test1', 'remark': '张三', 'nick_name': '阿三'},
        ]
        mock_reader.get_messages.return_value = [
            {'type': 1, 'content': '你好', 'time': '2024-01-01T12:00:00'},
            {'type': 1, 'content': '在吗', 'time': '2024-01-01T12:01:00'},
        ]
        mock_get_reader.return_value = mock_reader

        result = read_messages(talker='张三')
        self.assertIn('你好', result)
        self.assertIn('在吗', result)
        self.assertNotIn('❌', result)

    @patch('wx_mcp.server.get_reader')
    def test_no_messages(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.get_contacts.return_value = []
        mock_reader.get_messages.return_value = []
        mock_get_reader.return_value = mock_reader

        result = read_messages(talker='unknown')
        self.assertIn('未找到', result)

    @patch('wx_mcp.server.get_reader')
    def test_different_message_types(self, mock_get_reader):
        mock_reader = MagicMock()
        mock_reader.get_contacts.return_value = [
            {'username': 'wxid_t', 'remark': '测试', 'nick_name': ''},
        ]
        mock_reader.get_messages.return_value = [
            {'type': 1, 'content': '文本消息', 'time': '12:00'},
            {'type': 3, 'content': '', 'time': '12:01'},
            {'type': 34, 'content': '', 'time': '12:02'},
            {'type': 47, 'content': '', 'time': '12:03'},
            {'type': 49, 'content': '分享链接', 'time': '12:04'},
        ]
        mock_get_reader.return_value = mock_reader

        result = read_messages(talker='测试')
        self.assertIn('文本', result)
        self.assertIn('[图片]', result)
        self.assertIn('[语音]', result)
        self.assertIn('[表情]', result)
        self.assertIn('[分享]', result)


class TestSendWechatMessage(unittest.TestCase):
    """send_wechat_message 工具测试"""

    @patch('wx_mcp.server.send_message')
    def test_send_success(self, mock_send):
        mock_send.return_value = True

        result = send_wechat_message('张三', '你好')
        self.assertIn('✅', result)
        self.assertIn('张三', result)

    @patch('wx_mcp.server.send_message')
    def test_send_failure(self, mock_send):
        mock_send.return_value = False

        result = send_wechat_message('张三', '你好')
        self.assertIn('❌', result)

    @patch('wx_mcp.server.send_message')
    def test_send_exception(self, mock_send):
        mock_send.side_effect = RuntimeError('发送异常')

        result = send_wechat_message('张三', '你好')
        self.assertIn('❌', result)


class TestBatchSendMessages(unittest.TestCase):
    """batch_send_messages 工具测试"""

    @patch('wx_mcp.server.send_batch')
    def test_batch_all_success(self, mock_batch):
        mock_batch.return_value = [('张三', True), ('李四', True)]

        result = batch_send_messages(['张三', '李四'], '群发')
        self.assertIn('2/2', result)

    @patch('wx_mcp.server.send_batch')
    def test_batch_partial_failure(self, mock_batch):
        mock_batch.return_value = [('张三', True), ('李四', False)]

        result = batch_send_messages(['张三', '李四'], '群发')
        self.assertIn('1/2', result)


class TestWechatStatus(unittest.TestCase):
    """wechat_status 工具测试"""

    @patch('wx_mcp.server.load_keys')
    @patch('wx_mcp.server.find_wechat_pid')
    @patch('wx_mcp.server.find_db_storage')
    @patch('wx_mcp.server.os.path.exists')
    def test_status_all_ok(self, mock_exists, mock_find_db, mock_find_pid, mock_load_keys):
        mock_find_pid.return_value = 1234
        mock_find_db.return_value = 'C:\\data\\db_storage'
        mock_exists.return_value = True
        mock_load_keys.return_value = {'salt1': 'key1'}

        result = wechat_status()
        self.assertIn('✅', result)
        self.assertIn('数据目录', result)
        self.assertIn('密钥数量', result)

    @patch('wx_mcp.server.find_wechat_pid')
    def test_wechat_not_running(self, mock_find_pid):
        mock_find_pid.return_value = None

        result = wechat_status()
        self.assertIn('❌', result)
        self.assertIn('未运行', result)

    @patch('wx_mcp.server.wechat_status')
    def test_status_resource(self, mock_status):
        """验证 wechat://status 资源返回状态字符串"""
        mock_status.return_value = 'status ok'

        from wx_mcp.server import status_resource
        result = status_resource()
        self.assertEqual(result, 'status ok')


if __name__ == '__main__':
    unittest.main()
