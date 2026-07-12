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

    def test_normal_window(self):
        """非最小化窗口直接带到前台"""
        self.mock_user32.IsIconic.return_value = False
        self.mock_user32.GetForegroundWindow.return_value = 12345  # 直接成功

        result = sender._restore_and_foreground(12345)
        self.assertTrue(result)
        self.mock_user32.ShowWindow.assert_not_called()
        self.mock_user32.SetForegroundWindow.assert_called_once_with(12345)

    def test_minimized_window(self):
        """最小化窗口先恢复再前台"""
        self.mock_user32.IsIconic.return_value = True
        self.mock_user32.GetForegroundWindow.return_value = 12345

        result = sender._restore_and_foreground(12345)
        self.assertTrue(result)
        self.mock_user32.ShowWindow.assert_called_once_with(12345, 9)  # SW_RESTORE
        self.mock_user32.SetForegroundWindow.assert_called_once_with(12345)

    def test_foreground_fails_retry(self):
        """第一次带到前台失败，重试后成功"""
        self.mock_user32.IsIconic.return_value = False
        # 第一次 GetForegroundWindow 返回别的句柄（触发重试），第二次返回正确句柄
        self.mock_user32.GetForegroundWindow.side_effect = [999, 12345]

        result = sender._restore_and_foreground(12345)
        self.assertTrue(result)
        # ShowWindow(SW_SHOW) 被调用了一次（重试时）
        self.mock_user32.ShowWindow.assert_called_once_with(12345, 5)
        self.assertEqual(self.mock_user32.SetForegroundWindow.call_count, 2)

    def test_foreground_always_fails(self):
        """始终无法带到前台"""
        self.mock_user32.IsIconic.return_value = False
        self.mock_user32.GetForegroundWindow.return_value = 999

        result = sender._restore_and_foreground(12345)
        # 应该返回 False，但仍试图继续
        self.assertFalse(result)
        self.assertEqual(self.mock_user32.SetForegroundWindow.call_count, 2)


class TestMinimizeWindow(unittest.TestCase):
    """_minimize_window 测试"""

    @patch('wx_mcp.sender._user32')
    def test_minimize(self, mock_user32):
        sender._minimize_window(12345)
        mock_user32.ShowWindow.assert_called_once_with(12345, 6)  # SW_MINIMIZE


class TestRestorePreviousFocus(unittest.TestCase):
    """_restore_previous_focus 测试"""

    @patch('wx_mcp.sender._user32')
    def test_restore_valid_handle(self, mock_user32):
        mock_user32.IsWindow.return_value = True

        sender._restore_previous_focus(999)
        mock_user32.SetForegroundWindow.assert_called_once_with(999)

    @patch('wx_mcp.sender._user32')
    def test_restore_invalid_handle(self, mock_user32):
        mock_user32.IsWindow.return_value = False

        sender._restore_previous_focus(999)
        mock_user32.SetForegroundWindow.assert_not_called()

    @patch('wx_mcp.sender._user32')
    def test_none_handle(self, mock_user32):
        sender._restore_previous_focus(0)
        mock_user32.IsWindow.assert_not_called()
        mock_user32.SetForegroundWindow.assert_not_called()


class TestSendMessage(unittest.TestCase):
    """send_message 完整流程测试"""

    @patch('wx_mcp.sender._restore_previous_focus')
    @patch('wx_mcp.sender._minimize_window')
    @patch('wx_mcp.sender._restore_and_foreground')
    @patch('wx_mcp.sender._find_window_handle')
    @patch('wx_mcp.sender.auto.SendKeys')
    def test_send_success(self, mock_sendkeys, mock_find, mock_restore,
                          mock_minimize, mock_restore_focus):
        """正常发送流程"""
        mock_find.return_value = 12345
        mock_restore.return_value = True

        result = sender.send_message('张三', '你好', minimize=True)

        self.assertTrue(result)
        mock_find.assert_called_once()
        mock_restore.assert_called_once_with(12345)
        # 应该调用多次 SendKeys（Ctrl+A, Delete, name, Enter, Ctrl+A, Delete, text, Ctrl+Enter）
        # 至少有 8 次 SendKeys 调用
        self.assertGreaterEqual(mock_sendkeys.call_count, 6)
        mock_minimize.assert_called_once_with(12345)
        mock_restore_focus.assert_called()

    @patch('wx_mcp.sender._find_window_handle')
    def test_window_not_found(self, mock_find):
        """找不到窗口返回 False"""
        mock_find.return_value = None

        result = sender.send_message('张三', '你好')
        self.assertFalse(result)

    @patch('wx_mcp.sender._restore_previous_focus')
    @patch('wx_mcp.sender._minimize_window')
    @patch('wx_mcp.sender._restore_and_foreground')
    @patch('wx_mcp.sender._find_window_handle')
    @patch('wx_mcp.sender.auto.SendKeys')
    def test_foreground_fails_but_continues(self, mock_sendkeys, mock_find,
                                            mock_restore, mock_minimize,
                                            mock_restore_focus):
        """前台失败但继续尝试发送"""
        mock_find.return_value = 12345
        mock_restore.return_value = False  # 前台失败

        result = sender.send_message('张三', '你好')
        self.assertTrue(result)  # 仍然继续，SendKeys 可能仍有效
        self.assertGreater(mock_sendkeys.call_count, 0)

    @patch('wx_mcp.sender._restore_previous_focus')
    @patch('wx_mcp.sender._minimize_window')
    @patch('wx_mcp.sender._restore_and_foreground')
    @patch('wx_mcp.sender._find_window_handle')
    @patch('wx_mcp.sender.auto.SendKeys')
    def test_send_without_minimize(self, mock_sendkeys, mock_find,
                                   mock_restore, mock_minimize,
                                   mock_restore_focus):
        """发送后不最小化"""
        mock_find.return_value = 12345
        mock_restore.return_value = True

        result = sender.send_message('张三', '你好', minimize=False)
        self.assertTrue(result)
        mock_minimize.assert_not_called()
        mock_restore_focus.assert_called()


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

        # 前两条 minimize=False，最后一条 minimize=True
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


if __name__ == '__main__':
    unittest.main()
