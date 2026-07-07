"""
单元测试：微信消息发送器

使用 unittest.mock 模拟 uiautomation，验证发送逻辑和 fallback 策略。
"""
import unittest
from unittest.mock import MagicMock, PropertyMock, call, patch

from wx_mcp import sender


class MockUIA:
    """创建模拟的 uiautomation 控件树"""

    @staticmethod
    def make_control(
        exists: bool = True,
        name: str = '',
        automation_id: str = '',
        control_type=None,
    ) -> MagicMock:
        ctrl = MagicMock()
        ctrl.Name = name
        ctrl.AutomationId = automation_id
        ctrl.Exists.return_value = exists

        # 模拟 ControlType 比较
        type_mock = MagicMock()
        type_mock.EditControl = 1
        type_mock.DocumentControl = 2
        type_mock.ButtonControl = 3
        type_mock.ListItemControl = 4
        ctrl.ControlType = type_mock

        return ctrl

    @staticmethod
    def make_window(exists: bool = True) -> MagicMock:
        window = MockUIA.make_control(exists=exists, name='微信')
        # WindowPattern mock
        wp = MagicMock()
        wp.CurrentVisualState = 1  # Normal
        window.GetWindowPattern.return_value = wp

        # EditControl 搜索框
        search_box = MockUIA.make_control(exists=True)
        search_box.GetValuePattern.return_value = None  # ValuePattern 不可用，触发 SendKeys 备选

        def edit_control_side_effect(searchDepth=None):
            return search_box
        window.EditControl = MagicMock(side_effect=edit_control_side_effect)

        # 发送按钮
        send_btn = MockUIA.make_control(exists=True, name='发送')
        invoke_pattern = MagicMock()
        send_btn.GetInvokePattern.return_value = invoke_pattern

        def btn_control_side_effect(Name=None, AutomationId=None, ClassName=None, searchDepth=None):
            return send_btn
        window.ButtonControl = MagicMock(side_effect=btn_control_side_effect)

        # ListItemControl - 搜索结果
        list_item = MockUIA.make_control(exists=True)
        window.ListItemControl = MagicMock(return_value=list_item)

        # DocumentControl - 输入区域
        doc_control = MockUIA.make_control(exists=True)
        value_pattern = MagicMock()
        value_pattern.SetValue = MagicMock()
        doc_control.GetValuePattern.return_value = value_pattern
        window.DocumentControl = MagicMock(return_value=doc_control)

        # Window handle
        window.NativeWindowHandle = 12345

        return window


class TestFindWindow(unittest.TestCase):
    """查找微信窗口测试"""

    @patch('wx_mcp.sender.auto.WindowControl')
    def test_find_window_success(self, mock_window_ctrl):
        mock_window = MockUIA.make_window(exists=True)
        mock_window_ctrl.return_value = mock_window

        result = sender._find_window(retries=0)
        self.assertIsNotNone(result)

    @patch('wx_mcp.sender.auto.WindowControl')
    def test_find_window_retry_on_failure(self, mock_window_ctrl):
        """第一次找不到，第二次重试找到"""
        mock_window = MockUIA.make_window(exists=True)
        # 第一次 Exists 返回 False，第二次返回 True
        mock_window.Exists.side_effect = [False, True]
        mock_window_ctrl.return_value = mock_window

        result = sender._find_window(retries=1)
        self.assertIsNotNone(result)

    @patch('wx_mcp.sender.auto.WindowControl')
    def test_find_window_exhausted_retries(self, mock_window_ctrl):
        """重试耗尽仍未找到，返回 None"""
        mock_window = MockUIA.make_window(exists=False)
        mock_window_ctrl.return_value = mock_window

        result = sender._find_window(retries=1)
        self.assertIsNone(result)


class TestFindSendButton(unittest.TestCase):
    """查找发送按钮测试"""

    def setUp(self):
        self.window = MockUIA.make_window()

    def test_find_by_name(self):
        """按名称找发送按钮"""
        btn = MockUIA.make_control(exists=True, name='发送')
        self.window.ButtonControl = MagicMock(return_value=btn)

        result = sender._find_send_button(self.window)
        self.assertIsNotNone(result)

    def test_find_by_automation_id(self):
        """按 AutomationId 找发送按钮（备选）"""
        btn_name = MockUIA.make_control(exists=False)
        btn_aid = MockUIA.make_control(exists=True, automation_id='SendButton')
        self.window.ButtonControl = MagicMock(return_value=btn_name)

        def control_side_effect(AutomationId=None, searchDepth=None, Name=None, ClassName=None):
            if AutomationId == 'SendButton':
                return btn_aid
            if ClassName == 'QPushButton':
                return MockUIA.make_control(exists=False)
            return btn_name
        self.window.Control = MagicMock(side_effect=control_side_effect)

        result = sender._find_send_button(self.window)
        self.assertIsNotNone(result)

    def test_not_found_returns_none(self):
        """找不到发送按钮时返回 None"""
        btn = MockUIA.make_control(exists=False)
        self.window.ButtonControl = MagicMock(return_value=btn)
        self.window.Control = MagicMock(return_value=MockUIA.make_control(exists=False))

        result = sender._find_send_button(self.window)
        self.assertIsNone(result)


class TestFindInputArea(unittest.TestCase):
    """查找输入框测试"""

    def setUp(self):
        self.window = MockUIA.make_window()

    def test_find_edit_control(self):
        """优先找 EditControl"""
        edit = MockUIA.make_control(exists=True)
        self.window.EditControl = MagicMock(return_value=edit)

        result = sender._find_input_area(self.window)
        self.assertIsNotNone(result)

    def test_find_document_control_fallback(self):
        """EditControl 不存在时找 DocumentControl"""
        edit = MockUIA.make_control(exists=False)
        doc = MockUIA.make_control(exists=True)
        self.window.EditControl = MagicMock(return_value=edit)
        self.window.DocumentControl = MagicMock(return_value=doc)

        result = sender._find_input_area(self.window)
        self.assertIsNotNone(result)

    def test_not_found_returns_none(self):
        """所有控件都不存在时返回 None"""
        edit = MockUIA.make_control(exists=False)
        doc = MockUIA.make_control(exists=False)
        self.window.EditControl = MagicMock(return_value=edit)
        self.window.DocumentControl = MagicMock(return_value=doc)
        self.window.GetChildren = MagicMock(return_value=[])

        result = sender._find_input_area(self.window)
        self.assertIsNone(result)


class TestSetTextMethods(unittest.TestCase):
    """文本设置方法测试"""

    def test_value_pattern_success(self):
        control = MagicMock()
        pattern = MagicMock()
        pattern.SetValue = MagicMock()
        control.GetValuePattern.return_value = pattern

        result = sender._set_text_via_value_pattern(control, 'hello')
        self.assertTrue(result)
        pattern.SetValue.assert_called_once_with('hello')

    def test_value_pattern_failure(self):
        control = MagicMock()
        control.GetValuePattern.return_value = None

        result = sender._set_text_via_value_pattern(control, 'hello')
        self.assertFalse(result)

    def test_sendkeys_success(self):
        control = MagicMock()

        result = sender._set_text_via_sendkeys(control, 'hello')
        self.assertTrue(result)
        control.SendKeys.assert_any_call('{Ctrl}a', waitTime=0.05)
        control.SendKeys.assert_any_call('hello', waitTime=0.05)

    def test_sendkeys_failure(self):
        control = MagicMock()
        control.SendKeys.side_effect = Exception('sendkeys failed')

        result = sender._set_text_via_sendkeys(control, 'hello')
        self.assertFalse(result)


class TestInvokeButton(unittest.TestCase):
    """按钮点击测试"""

    def test_invoke_pattern_success(self):
        btn = MagicMock()
        pattern = MagicMock()
        pattern.Invoke = MagicMock()
        btn.GetInvokePattern.return_value = pattern

        result = sender._invoke_button(btn)
        self.assertTrue(result)
        pattern.Invoke.assert_called_once()

    def test_invoke_pattern_fallback_to_click(self):
        btn = MagicMock()
        btn.GetInvokePattern.return_value = None

        result = sender._invoke_button(btn)
        self.assertTrue(result)
        btn.Click.assert_called_once()

    def test_both_failures(self):
        btn = MagicMock()
        btn.GetInvokePattern.return_value = None
        btn.Click.side_effect = Exception('click failed')

        result = sender._invoke_button(btn)
        self.assertFalse(result)


class TestWaitFor(unittest.TestCase):
    """轮询等待测试"""

    def test_condition_met_immediately(self):
        result = sender._wait_for(lambda: True, timeout=1.0)
        self.assertTrue(result)

    def test_condition_never_met(self):
        result = sender._wait_for(lambda: False, timeout=0.1, interval=0.05)
        self.assertFalse(result)

    def test_condition_met_after_delay(self):
        state = [False]

        def delayed_condition():
            if not state[0]:
                state[0] = True
                return False
            return True

        result = sender._wait_for(delayed_condition, timeout=1.0, interval=0.01)
        self.assertTrue(result)


class TestSendMessageValidation(unittest.TestCase):
    """send_message 参数校验测试"""

    @patch('wx_mcp.sender._find_window')
    def test_empty_chat_name_returns_false(self, mock_find_window):
        result = sender.send_message('', 'hello')
        self.assertFalse(result)
        mock_find_window.assert_not_called()

    @patch('wx_mcp.sender._find_window')
    def test_empty_text_returns_false(self, mock_find_window):
        result = sender.send_message('张三', '')
        self.assertFalse(result)
        mock_find_window.assert_not_called()


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


class TestRestoreFocus(unittest.TestCase):
    """焦点恢复测试"""

    @patch('wx_mcp.sender.auto.ControlFromHandle')
    def test_restore_with_valid_handle(self, mock_from_handle):
        prev_control = MagicMock()
        prev_control.Exists.return_value = True
        mock_from_handle.return_value = prev_control

        sender._restore_previous_focus(999, 12345)
        prev_control.SetFocus.assert_called_once()

    @patch('wx_mcp.sender.auto.ControlFromHandle')
    def test_restore_same_handle_noop(self, mock_from_handle):
        sender._restore_previous_focus(12345, 12345)
        mock_from_handle.assert_not_called()

    def test_restore_none_handle_noop(self):
        try:
            sender._restore_previous_focus(None, 12345)
        except Exception:
            self.fail('_restore_previous_focus(None, ...) raised unexpectedly')


if __name__ == '__main__':
    unittest.main()
