"""
微信消息发送器

使用 UI Automation (uiautomation) 与微信窗口交互，发送消息。
相比旧版（SendInput + 硬编码坐标）：
  ✅ 不抢焦点 — 优先通过 UIA 模式接口操作，不强制激活窗口
  ✅ 不劫持剪贴板 — 用 SetValuePattern / SendKeys 直接输入文本
  ✅ 无硬编码坐标 — 通过控件树定位元素
"""
import logging
import time
from typing import List, Optional, Tuple

import uiautomation as auto

log = logging.getLogger('wx-mcp.sender')

# 控件搜索深度（Qt 嵌套层级较深）
_SEARCH_DEPTH = 8


def _find_send_button(window: auto.WindowControl) -> Optional[auto.Control]:
    """找发送按钮 — 尝试多种查找策略"""
    # 策略1: 按名称查找
    btn = window.ButtonControl(Name='发送', searchDepth=_SEARCH_DEPTH)
    if btn.Exists(maxSearchSeconds=0.5):
        return btn
    # 策略2: 按 AutomationId (部分 Qt 版本)
    btn = window.Control(AutomationId='SendButton', searchDepth=_SEARCH_DEPTH)
    if btn.Exists(maxSearchSeconds=0.5):
        return btn
    return None


def _find_input_area(window: auto.WindowControl) -> Optional[auto.Control]:
    """找消息输入框 — 尝试多种控件类型"""
    # 策略1: EditControl
    edit = window.EditControl(searchDepth=_SEARCH_DEPTH)
    if edit.Exists(maxSearchSeconds=0.5):
        return edit
    # 策略2: DocumentControl (Qt QTextEdit/QTextDocument)
    doc = window.DocumentControl(searchDepth=_SEARCH_DEPTH)
    if doc.Exists(maxSearchSeconds=0.5):
        return doc
    # 策略3: 直接找最后一个可编辑的控件
    all_edits = window.GetChildren()
    for c in all_edits:
        if c.ControlType in (auto.ControlType.EditControl, auto.ControlType.DocumentControl):
            return c
    return None


def _set_text_via_value_pattern(control: auto.Control, text: str) -> bool:
    """通过 ValuePattern 设置文本（不抢焦点、不碰剪贴板）"""
    try:
        pattern = control.GetValuePattern()
        if pattern:
            pattern.SetValue(text)
            return True
    except Exception as e:
        log.debug(f"ValuePattern 失败: {e}")
    return False


def _set_text_via_sendkeys(control: auto.Control, text: str) -> bool:
    """通过 SendKeys 设置文本（可能抢焦点，作为备选）"""
    try:
        control.SendKeys('{Ctrl}a', waitTime=0.05)
        control.SendKeys(text, waitTime=0.05)
        return True
    except Exception as e:
        log.debug(f"SendKeys 失败: {e}")
    return False


def _invoke_button(btn: auto.Control) -> bool:
    """通过 InvokePattern 点击按钮（不抢焦点）"""
    try:
        pattern = btn.GetInvokePattern()
        if pattern:
            pattern.Invoke()
            return True
    except Exception as e:
        log.debug(f"InvokePattern 失败: {e}")

    # 备选：Click（可能抢焦点）
    try:
        btn.Click()
        return True
    except Exception:
        return False


def send_message(chat_name: str, text: str, minimize: bool = True) -> bool:
    """
    发送微信消息

    通过 UI Automation 与微信窗口交互，优先在不抢焦点、
    不操作剪贴板的前提下完成发送。

    Args:
        chat_name: 联系人名称或备注
        text: 消息内容
        minimize: 发送后是否最小化窗口

    Returns:
        是否成功
    """
    # 找微信主窗口
    wechat = auto.WindowControl(Name='微信', searchDepth=1)
    if not wechat.Exists(maxSearchSeconds=3):
        log.warning("找不到微信窗口")
        return False

    # 记录当前焦点窗口，以便后续恢复
    prev_focus = auto.GetForegroundWindow()

    # 如果窗口最小化，需要恢复才能交互
    try:
        pattern = wechat.GetWindowPattern()
        if pattern:
            visual_state = pattern.CurrentVisualState
            if visual_state == auto.VisualState.Minimized:
                log.info("微信窗口已最小化，尝试恢复")
                pattern.SetVisualState(auto.VisualState.Normal)
                time.sleep(0.3)
    except Exception as e:
        log.debug(f"WindowPattern 操作失败: {e}")

    # ---- 步骤1: 搜索联系人 ----
    search = wechat.EditControl(searchDepth=_SEARCH_DEPTH)
    if not search.Exists(maxSearchSeconds=2):
        log.warning("找不到搜索框")
        return False

    # 先尝试 ValuePattern 写入联系人名（不抢焦点）
    if not _set_text_via_value_pattern(search, chat_name):
        # 备选：Click + SendKeys
        try:
            search.Click()
            time.sleep(0.1)
            search.SendKeys('{Ctrl}a', waitTime=0.1)
            search.SendKeys(chat_name, waitTime=0.3)
        except Exception as e:
            log.error(f"搜索框输入失败: {e}")
            return False

    time.sleep(0.5)

    # ---- 步骤2: 打开聊天 ----
    # 尝试在搜索结果中找到对应联系人并点击
    try:
        target = wechat.ListItemControl(Name=chat_name, searchDepth=_SEARCH_DEPTH)
        if target.Exists(maxSearchSeconds=1):
            target.Click()
        else:
            # 备选：直接按 Enter（默认选择第一个结果）
            search.SendKeys('{Enter}', waitTime=0.5)
    except Exception as e:
        log.debug(f"联系人选择失败: {e}")
        search.SendKeys('{Enter}', waitTime=0.5)

    time.sleep(0.5)

    # ---- 步骤3: 在输入框中写入消息 ----
    input_area = _find_input_area(wechat)
    if input_area is None:
        log.warning("找不到消息输入框")
        return False

    # 尝试 ValuePattern（不碰剪贴板）
    if not _set_text_via_value_pattern(input_area, text):
        # 备选：SendKeys
        if not _set_text_via_sendkeys(input_area, text):
            log.error("消息输入失败")
            return False

    time.sleep(0.2)

    # ---- 步骤4: 发送 ----
    send_btn = _find_send_button(wechat)
    if send_btn is not None:
        _invoke_button(send_btn)
    else:
        # 备选：Enter 键发送
        try:
            input_area.SendKeys('{Enter}', waitTime=0.2)
        except Exception as e:
            log.error(f"发送失败: {e}")
            return False

    time.sleep(0.2)

    # ---- 步骤5: 最小化（可选） ----
    if minimize:
        try:
            pattern = wechat.GetWindowPattern()
            if pattern:
                pattern.SetVisualState(auto.VisualState.Minimized)
        except Exception as e:
            log.debug(f"最小化失败: {e}")

    # 恢复之前的前台窗口
    try:
        if prev_focus and prev_focus != wechat.NativeWindowHandle:
            prev_control = auto.ControlFromHandle(prev_focus)
            if prev_control.Exists(maxSearchSeconds=0):
                prev_control.SetFocus()
    except Exception:
        pass

    return True


def send_batch(tasks: list, message: Optional[str] = None) -> List[Tuple[str, bool]]:
    """
    批量发送消息

    Args:
        tasks: [(联系人, 消息), ...] 或 [联系人, ...]
        message: 当 tasks 为联系人列表时使用的默认消息

    Returns:
        [(联系人, 是否成功), ...]
    """
    results: List[Tuple[str, bool]] = []
    total = len(tasks)

    for i, task in enumerate(tasks):
        if isinstance(task, (list, tuple)):
            contact, msg = task
        else:
            contact, msg = task, message or f"测试{int(time.time())}"

        try:
            is_last = (i == total - 1)
            ok = send_message(contact, msg, minimize=is_last)
            results.append((contact, ok))
        except Exception as e:
            log.error(f"发送给 {contact} 失败: {e}", exc_info=True)
            results.append((contact, False))

        time.sleep(0.1)

    return results
