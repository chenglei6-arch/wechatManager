"""
单元测试：微信消息发送器

测试新 sender 实现（Win32 API + SendInput 方式）。
使用 unittest.mock 模拟 ctypes 和 uiautomation。
"""
import unittest
from unittest.mock import MagicMock, patch

from wx_mcp import sender


class TestFindWindowHandle(unittest.TestCase):
    """_find_window_handle 测试"""

    @patch('wx_mcp.sender._user32.FindWindowW')
    def test_found(self, mock_find):
        mock_find.return_value = 123456

        hwnd = sender._find_window_handle()
        self.assertEqual(hwnd, 123456)
        mock_find.assert_called_once_with(None, '微信')

    @patch('wx_mcp.sender._user32.FindWindowW')
    def test_not_found(self, mock_find):
        mock_find.return_value = 0

        hwnd = sender._find_window_handle()
        self.assertIsNone(hwnd)


class TestRestoreAndForeground(unittest.TestCase):
    """_restore_and_foreground 测试"""

    def setUp(self):
        self.mock_user32 = patch('wx_mcp.sender._user32').start()
        self.addCleanup(patch.stopall)
        # 默认 GetWindowThreadProcessId 返回 0（使 AttachThreadInput 块被跳过）
        self.mock_user32.GetWindowThreadProcessId.return_value = 0
        self.mock_user32.GetCurrentThreadId.return_value = 1

    def test_normal_window(self):
        """非最小化窗口直接带到前台"""
        self.mock_user32.IsIconic.return_value = False
        self.mock_user32.GetForegroundWindow.return_value = 12345

        result = sender._restore_and_foreground(12345)
        self.assertTrue(result)
        self.mock_user32.ShowWindow.assert_not_called()

    def test_minimized_window(self):
        """最小化窗口先恢复再前台"""
        self.mock_user32.IsIconic.return_value = True
        self.mock_user32.GetForegroundWindow.return_value = 12345

        result = sender._restore_and_foreground(12345)
        self.assertTrue(result)
        self.mock_user32.ShowWindow.assert_called_once_with(12345, 9)
        self.mock_user32.SetForegroundWindow.assert_called_once_with(12345)

    def test_foreground_fails_retry(self):
        """第一次带到前台失败，重试后成功"""
        self.mock_user32.IsIconic.return_value = False
        self.mock_user32.GetForegroundWindow.side_effect = [999, 12345, 12345]

        result = sender._restore_and_foreground(12345)
        self.assertTrue(result)

    def test_foreground_always_fails(self):
        """始终无法带到前台"""
        self.mock_user32.IsIconic.return_value = False
        self.mock_user32.GetForegroundWindow.return_value = 999

        result = sender._restore_and_foreground(12345)
        self.assertFalse(result)
        self.assertEqual(self.mock_user32.SetForegroundWindow.call_count, 3)


class TestMinimizeWindow(unittest.TestCase):
    """_minimize_window 测试"""

    @patch('wx_mcp.sender._user32')
    def test_minimize(self, mock_user32):
        sender._minimize_window(12345)
        mock_user32.ShowWindow.assert_called_once_with(12345, 6)


class TestSendMessage(unittest.TestCase):
    """send_message 完整流程测试"""

    @patch('wx_mcp.sender._set_clipboard_text')
    @patch('wx_mcp.sender._get_clipboard_text')
    @patch('wx_mcp.sender._SafeForeground')
    @patch('wx_mcp.sender._find_window_handle')
    @patch('wx_mcp.sender.auto.SendKeys')
    def test_send_success(self, mock_sendkeys, mock_find,
                          mock_safe, mock_get_cb, mock_set_cb):
        """正常发送流程"""
        mock_find.return_value = 12345
        mock_get_cb.return_value = ''
        ctx_mock = MagicMock()
        mock_safe.return_value.__enter__.return_value = ctx_mock

        with patch('wx_mcp.sender._user32.GetForegroundWindow', return_value=12345):
            with patch('wx_mcp.sender._minimize_window'):
                result = sender.send_message('张三', '你好', minimize=True)

        self.assertTrue(result)
        mock_find.assert_called_once()
        mock_get_cb.assert_called_once()
        mock_set_cb.assert_called_once_with('你好')
        self.assertGreaterEqual(mock_sendkeys.call_count, 6)

    @patch('wx_mcp.sender._direct_postmessage_send')
    @patch('wx_mcp.sender._set_clipboard_text')
    @patch('wx_mcp.sender._get_clipboard_text')
    @patch('wx_mcp.sender._SafeForeground')
    @patch('wx_mcp.sender._find_window_handle')
    @patch('wx_mcp.sender.auto.SendKeys')
    def test_foreground_fails_falls_back(self, mock_sendkeys, mock_find,
                                          mock_safe, mock_get_cb, mock_set_cb, mock_pm):
        """前台失败时回退到 PostMessage 方法"""
        mock_find.return_value = 12345
        mock_get_cb.return_value = ''
        mock_pm.return_value = True
        ctx_mock = MagicMock()
        mock_safe.return_value.__enter__.return_value = ctx_mock

        with patch('wx_mcp.sender._user32.GetForegroundWindow', return_value=999):
            result = sender.send_message('张三', '你好')

        self.assertTrue(result)
        mock_pm.assert_called_once()

    @patch('wx_mcp.sender._direct_postmessage_send')
    @patch('wx_mcp.sender._set_clipboard_text')
    @patch('wx_mcp.sender._get_clipboard_text')
    @patch('wx_mcp.sender._SafeForeground')
    @patch('wx_mcp.sender._find_window_handle')
    @patch('wx_mcp.sender.auto.SendKeys')
    def test_foreground_fails_and_fallback_fails(self, mock_sendkeys, mock_find,
                                                  mock_safe, mock_get_cb, mock_set_cb, mock_pm):
        """前台失败且 PostMessage 回退也失败"""
        mock_find.return_value = 12345
        mock_get_cb.return_value = ''
        mock_pm.return_value = False
        ctx_mock = MagicMock()
        mock_safe.return_value.__enter__.return_value = ctx_mock

        with patch('wx_mcp.sender._user32.GetForegroundWindow', return_value=999):
            result = sender.send_message('张三', '你好')

        self.assertFalse(result)
        mock_pm.assert_called_once()

    @patch('wx_mcp.sender._find_window_handle')
    def test_window_not_found(self, mock_find):
        """找不到窗口返回 False"""
        mock_find.return_value = None

        result = sender.send_message('张三', '你好')
        self.assertFalse(result)

    @patch('wx_mcp.sender._set_clipboard_text')
    @patch('wx_mcp.sender._get_clipboard_text')
    @patch('wx_mcp.sender._SafeForeground')
    @patch('wx_mcp.sender._find_window_handle')
    @patch('wx_mcp.sender.auto.SendKeys')
    def test_send_without_minimize(self, mock_sendkeys, mock_find,
                                   mock_safe, mock_get_cb, mock_set_cb):
        """发送后不最小化"""
        mock_find.return_value = 12345
        mock_get_cb.return_value = ''
        ctx_mock = MagicMock()
        mock_safe.return_value.__enter__.return_value = ctx_mock

        with patch('wx_mcp.sender._user32.GetForegroundWindow', return_value=12345):
            with patch('wx_mcp.sender._minimize_window') as mock_min:
                result = sender.send_message('张三', '你好', minimize=False)

        self.assertTrue(result)
        mock_min.assert_not_called()


class TestSendMessageValidation(unittest.TestCase):
    """send_message 参数校验测试"""

    def test_empty_chat_name(self):
        result = sender.send_message('', 'hello')
        self.assertFalse(result)

    def test_empty_text(self):
        result = sender.send_message('张三', '')
        self.assertFalse(result)


class TestSendBatch(unittest.TestCase):
    """批量发送测试"""

    @patch('wx_mcp.sender.send_message')
    def test_batch_with_pairs(self, mock_send):
        mock_send.return_value = True

        tasks = [('张三', '你好'), ('李四', '在吗')]
        results = sender.send_batch(tasks)

        self.assertEqual(len(results), 2)
        self.assertTrue(results[0][1])
        self.assertTrue(results[1][1])
        self.assertEqual(mock_send.call_count, 2)

    @patch('wx_mcp.sender.send_message')
    def test_batch_with_names_and_default_message(self, mock_send):
        mock_send.return_value = True

        results = sender.send_batch(['张三', '李四'], message='群发测试')
        self.assertEqual(len(results), 2)
        self.assertTrue(all(ok for _, ok in results))

    @patch('wx_mcp.sender.send_message')
    def test_batch_partial_failure(self, mock_send):
        mock_send.side_effect = [True, False, True]

        tasks = [('A', '1'), ('B', '2'), ('C', '3')]
        results = sender.send_batch(tasks)

        self.assertTrue(results[0][1])
        self.assertFalse(results[1][1])
        self.assertTrue(results[2][1])

    @patch('wx_mcp.sender.send_message')
    def test_batch_exception_handling(self, mock_send):
        mock_send.side_effect = Exception('意外错误')

        results = sender.send_batch([('A', '1')])
        self.assertFalse(results[0][1])

    def test_batch_empty_list(self):
        results = sender.send_batch([])
        self.assertEqual(results, [])


class TestSendBatchLastMinimizes(unittest.TestCase):
    """批量发送最后一条才最小化"""

    @patch('wx_mcp.sender.send_message')
    def test_last_item_minimizes(self, mock_send):
        mock_send.return_value = True

        sender.send_batch([('A', '1'), ('B', '2'), ('C', '3')])

        self.assertEqual(mock_send.call_count, 3)
        call_args_list = mock_send.call_args_list
        self.assertFalse(call_args_list[0].kwargs.get('minimize', True))
        self.assertFalse(call_args_list[1].kwargs.get('minimize', True))
        self.assertTrue(call_args_list[2].kwargs.get('minimize', True))


class TestSendEmptyMessage(unittest.TestCase):
    """空消息测试"""

    def test_empty_batch_list(self):
        results = sender.send_batch([])
        self.assertEqual(results, [])


class TestPostMessageHelpers(unittest.TestCase):
    """PostMessage 辅助函数测试"""

    @patch('wx_mcp.sender._user32.PostMessageW')
    def test_post_key_down(self, mock_post):
        sender._post_key_down(12345, 0x11)  # VK_CONTROL
        mock_post.assert_called_once_with(12345, 0x0100, 0x11, 1)

    @patch('wx_mcp.sender._user32.PostMessageW')
    def test_post_key_up(self, mock_post):
        sender._post_key_up(12345, 0x0D)  # VK_RETURN
        mock_post.assert_called_once()
        args = mock_post.call_args
        self.assertEqual(args[0][0], 12345)
        self.assertEqual(args[0][1], 0x0101)  # WM_KEYUP
        self.assertEqual(args[0][2], 0x0D)
        # lparam should have bits 30 and 31 set

    @patch('wx_mcp.sender._user32.PostMessageW')
    def test_post_chars(self, mock_post):
        sender._post_chars(12345, '你好')
        self.assertEqual(mock_post.call_count, 2)
        calls = mock_post.call_args_list
        # '你' = U+4F60
        self.assertEqual(calls[0][0][1], 0x0102)  # WM_CHAR
        self.assertEqual(calls[0][0][2], 0x4F60)
        # '好' = U+597D
        self.assertEqual(calls[1][0][1], 0x0102)
        self.assertEqual(calls[1][0][2], 0x597D)

    @patch('wx_mcp.sender._post_key_down')
    @patch('wx_mcp.sender._post_key_up')
    def test_post_ctrl_combo(self, mock_up, mock_down):
        sender._post_ctrl_combo(12345, 0x56)  # VK_V
        # Ctrl down, V down, V up, Ctrl up
        self.assertEqual(mock_down.call_count, 2)
        self.assertEqual(mock_up.call_count, 2)
        mock_down.assert_any_call(12345, 0x11)  # Ctrl down
        mock_down.assert_any_call(12345, 0x56)  # V down

    @patch('wx_mcp.sender._user32.SendMessageW')
    @patch('wx_mcp.sender._user32.SetWindowPos')
    @patch('wx_mcp.sender._user32.PostMessageW')
    def test_direct_postmessage_send(self, mock_post, mock_swp, mock_send):
        result = sender._direct_postmessage_send(12345, '李皓镇', '你好')
        self.assertTrue(result)
        # Should have posted many key messages
        self.assertGreater(mock_post.call_count, 10)
        # Should have sent WM_ACTIVATE
        mock_send.assert_any_call(12345, 0x0006, 1, 0)  # WM_ACTIVATE, WA_ACTIVE


class TestSendMessagePostMessage(unittest.TestCase):
    """send_message_postmessage 公共 API 测试"""

    @patch('wx_mcp.sender._direct_postmessage_send')
    @patch('wx_mcp.sender._find_window_handle')
    def test_success(self, mock_find, mock_direct):
        mock_find.return_value = 12345
        mock_direct.return_value = True

        result = sender.send_message_postmessage('张三', '测试消息')
        self.assertTrue(result)
        mock_find.assert_called_once()
        mock_direct.assert_called_once_with(12345, '张三', '测试消息')

    @patch('wx_mcp.sender._find_window_handle')
    def test_window_not_found(self, mock_find):
        mock_find.return_value = None

        result = sender.send_message_postmessage('张三', '测试消息')
        self.assertFalse(result)

    def test_empty_params(self):
        self.assertFalse(sender.send_message_postmessage('', 'hello'))
        self.assertFalse(sender.send_message_postmessage('张三', ''))

    @patch('wx_mcp.sender._direct_postmessage_send')
    @patch('wx_mcp.sender._find_window_handle')
    def test_send_failure(self, mock_find, mock_direct):
        mock_find.return_value = 12345
        mock_direct.side_effect = Exception('发送异常')

        result = sender.send_message_postmessage('张三', '测试消息')
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
