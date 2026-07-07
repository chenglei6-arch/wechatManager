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

# 控件搜索深度（WeChat 4.x 基于 Qt，嵌套层级很深，需 >12）
_SEARCH_DEPTH = 20

# UI 操作等待超时（秒）
_WAIT_SHORT = 0.5
_WAIT_MEDIUM = 2.0
_WAIT_LONG = 5.0

# 轮询间隔（秒）
_POLL_INTERVAL = 0.1


def _wait_for(
    condition_fn,
    timeout: float = _WAIT_MEDIUM,
    interval: float = _POLL_INTERVAL,
) -> bool:
    """轮询等待直到 condition_fn() 返回真值，超时返回 False"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition_fn()
        if result:
            return True
        time.sleep(interval)
    return False


def _find_window(retries: int = 2) -> Optional[auto.WindowControl]:
    """查找微信主窗口，带重试"""
    for attempt in range(retries + 1):
        wechat = auto.WindowControl(Name='微信', searchDepth=1)
        if wechat.Exists(maxSearchSeconds=_WAIT_SHORT):
            return wechat
        if attempt < retries:
            log.info(f"未找到微信窗口，第 {attempt + 1} 次重试...")
            time.sleep(_WAIT_SHORT)
    log.warning("找不到微信窗口（已重试 %d 次）", retries)
    return None


def _ensure_window_restored(wechat: auto.WindowControl) -> bool:
    """如果窗口最小化则恢复窗口"""
    try:
        pattern = wechat.GetWindowPattern()
        if pattern:
            state = pattern.CurrentVisualState
            if state == auto.VisualState.Minimized:
                log.info("微信窗口已最小化，尝试恢复")
                pattern.SetVisualState(auto.VisualState.Normal)
                time.sleep(0.3)
        return True
    except Exception as e:
        log.debug(f"窗口状态操作失败: {e}")
        return False


def _search_contact(wechat: auto.WindowControl, chat_name: str) -> bool:
    """在微信搜索框中搜索联系人，返回是否成功"""
    search = wechat.EditControl(searchDepth=_SEARCH_DEPTH)
    if not search.Exists(maxSearchSeconds=_WAIT_MEDIUM):
        log.warning("找不到搜索框")
        return False

    # 优先 ValuePattern（不抢焦点）；备选 Click + SendKeys
    if not _set_text_via_value_pattern(search, chat_name):
        try:
            search.Click()
            time.sleep(_POLL_INTERVAL)
            search.SendKeys('{Ctrl}a', waitTime=0.1)
            search.SendKeys(chat_name, waitTime=0.3)
        except Exception as e:
            log.error(f"搜索框输入失败: {e}")
            return False

    # 等待搜索结果出现（动态等待取代固定 sleep）
    # WeChat 4.x 的列表项 Name 包含额外信息（如最近消息预览），因此用 SubName 匹配
    found = _wait_for(
        lambda: _find_contact_in_children(wechat, chat_name),
        timeout=2.0,
    )
    if not found:
        log.warning(f"搜索联系人 '{chat_name}' 未出现结果")
    return True


def _find_contact_in_children(wechat: auto.WindowControl, chat_name: str) -> bool:
    """遍历窗口内所有 ListItemControl，查找名称包含 chat_name 的联系人"""
    try:
        for item in wechat.ListControl(searchDepth=_SEARCH_DEPTH).GetChildren():
            if chat_name in (item.Name or ''):
                return True
    except Exception:
        pass
    # 备选：直接用 SubName 搜索
    try:
        item = wechat.ListItemControl(SubName=chat_name, searchDepth=_SEARCH_DEPTH)
        return item.Exists(maxSearchSeconds=0)
    except Exception:
        return False


def _open_chat(wechat: auto.WindowControl, chat_name: str) -> bool:
    """点击搜索结果中的联系人打开聊天窗口"""
    try:
        # WeChat 4.x ListItem Name 含额外信息，用 SubName 做包含匹配
        target = wechat.ListItemControl(SubName=chat_name, searchDepth=_SEARCH_DEPTH)
        if target.Exists(maxSearchSeconds=_WAIT_SHORT):
            target.Click()
            return True

        # 备选：直接按 Enter（默认选中第一个结果）
        search = wechat.EditControl(searchDepth=_SEARCH_DEPTH)
        if search.Exists(maxSearchSeconds=0):
            search.SendKeys('{Enter}', waitTime=0.5)
            return True
    except Exception as e:
        log.debug(f"联系人选择失败: {e}")
        # 最后的备选
        try:
            search = wechat.EditControl(searchDepth=_SEARCH_DEPTH)
            if search.Exists(maxSearchSeconds=0):
                search.SendKeys('{Enter}', waitTime=0.5)
                return True
        except Exception:
            pass
    return False


def _find_send_button(window: auto.WindowControl) -> Optional[auto.Control]:
    """找发送按钮 — 尝试多种查找策略"""
    # 策略1: 按名称查找
    btn = window.ButtonControl(Name='发送', searchDepth=_SEARCH_DEPTH)
    if btn.Exists(maxSearchSeconds=_WAIT_SHORT):
        return btn
    # 策略2: 按 AutomationId (部分 Qt 版本)
    btn = window.Control(AutomationId='SendButton', searchDepth=_SEARCH_DEPTH)
    if btn.Exists(maxSearchSeconds=_WAIT_SHORT):
        return btn
    # 策略3: 按 class name (某些微信版本)
    btn = window.Control(ClassName='QPushButton', searchDepth=_SEARCH_DEPTH)
    if btn.Exists(maxSearchSeconds=_WAIT_SHORT):
        return btn
    return None


def _find_input_area(window: auto.WindowControl) -> Optional[auto.Control]:
    """找消息输入框 — 排除搜索框，定位聊天输入区域"""
    # 搜索所有 EditControl，排除搜索框（WeChat 4.x 搜索框 Name="搜索"）
    try:
        for ctrl in _collect_all_edit_controls(window):
            name = ctrl.Name or ''
            # 搜索框的 Name 为"搜索"，聊天输入框的 Name 为联系人名称
            if name != '搜索':
                return ctrl
    except Exception:
        pass

    # 备选：DocumentControl (Qt QTextEdit/QTextDocument)
    doc = window.DocumentControl(searchDepth=_SEARCH_DEPTH)
    if doc.Exists(maxSearchSeconds=_WAIT_SHORT):
        return doc

    return None


def _collect_all_edit_controls(window: auto.WindowControl) -> list:
    """递归收集窗口内所有 EditControl（跳过搜索框）"""
    results = []
    try:
        for c in window.GetChildren():
            if c.ControlTypeName == 'EditControl':
                results.append(c)
            results.extend(_collect_all_edit_controls(c))
    except Exception:
        pass
    return results


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
    except Exception as e:
        log.debug(f"Click 备选也失败: {e}")
        return False


def _restore_previous_focus(prev_handle: Optional[int], wechat_handle: int):
    """恢复之前的前台窗口（静默失败）"""
    if prev_handle and prev_handle != wechat_handle:
        try:
            prev_control = auto.ControlFromHandle(prev_handle)
            if prev_control.Exists(maxSearchSeconds=0):
                prev_control.SetFocus()
        except Exception as e:
            log.debug(f"恢复焦点失败: {e}")


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
    if not chat_name or not text:
        log.warning("send_message 收到空参数: chat_name=%r, text=%r", chat_name, text)
        return False

    # 找微信主窗口（带重试）
    wechat = _find_window(retries=2)
    if wechat is None:
        return False

    # 记录当前焦点窗口，以便后续恢复
    prev_focus = auto.GetForegroundWindow()

    # 如果窗口最小化，需要恢复才能交互
    _ensure_window_restored(wechat)

    # ---- 步骤1: 搜索联系人 ----
    if not _search_contact(wechat, chat_name):
        return False

    # ---- 步骤2: 打开聊天 ----
    if not _open_chat(wechat, chat_name):
        return False

    # 等待聊天窗口加载
    time.sleep(0.3)

    # ---- 步骤3: 在输入框中写入消息 ----
    input_area = _find_input_area(wechat)
    if input_area is None:
        log.warning("找不到消息输入框")
        return False

    # 优先 ValuePattern（不碰剪贴板）；备选 SendKeys
    if not _set_text_via_value_pattern(input_area, text):
        if not _set_text_via_sendkeys(input_area, text):
            log.error("消息输入失败")
            return False

    time.sleep(0.2)

    # ---- 步骤4: 发送 ----
    send_btn = _find_send_button(wechat)
    if send_btn is not None:
        _invoke_button(send_btn)
    else:
        # 找不到发送按钮时用 Enter 发送
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
    _restore_previous_focus(prev_focus, wechat.NativeWindowHandle)

    return True


def send_batch(tasks: list, message: Optional[str] = None) -> List[Tuple[str, bool]]:
    """
    批量发送消息

    Args:
        tasks: 支持两种格式 —
              字符串列表: [联系人, ...] 配合 message 参数使用
              二元组列表: [(联系人, 消息), ...]
        message: 当 tasks 为字符串列表时使用的默认消息

    Returns:
        [(联系人, 是否成功), ...]
    """
    if not tasks:
        log.warning("send_batch 收到空列表")
        return []

    results: List[Tuple[str, bool]] = []
    total = len(tasks)
    default_msg = message or f"测试{int(time.time())}"

    for i, task in enumerate(tasks):
        if isinstance(task, str):
            contact, msg = task, default_msg
        else:
            try:
                contact, msg = task[0], task[1]
            except (IndexError, TypeError) as e:
                log.warning(f"跳过格式错误的任务: {task!r}: {e}")
                results.append((str(task), False))
                continue

        try:
            is_last = (i == total - 1)
            ok = send_message(contact, msg, minimize=is_last)
            results.append((contact, ok))
        except Exception as e:
            log.error(f"发送给 {contact} 失败: {e}", exc_info=True)
            results.append((contact, False))

        time.sleep(0.1)

    return results
