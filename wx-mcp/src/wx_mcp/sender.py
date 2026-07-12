"""
微信消息发送器

使用 Win32 API + SendInput 直接与微信窗口交互：
  ✅ 不依赖 UIA 控件树（WeChat 4.x 的 Qt/QML 渲染不暴露标准 UIA 控件）
  ✅ 通过键盘快捷键操作：输入联系人名 → Enter → Ctrl+Enter 发送
  ✅ 发送后恢复前台窗口焦点
"""
import logging
import time
from typing import List, Optional, Tuple

import ctypes
import ctypes.wintypes

import uiautomation as auto

log = logging.getLogger('wx-mcp.sender')

# 微信窗口标题
_WECHAT_WINDOW_TITLE = '微信'

# 共享的 user32 实例
_user32 = ctypes.windll.user32


def _find_window_handle() -> Optional[int]:
    """通过 FindWindowW 查找微信主窗口句柄（比 UIA 更可靠）"""
    handle = _user32.FindWindowW(None, _WECHAT_WINDOW_TITLE)
    if handle:
        return handle
    return None


def _restore_and_foreground(hwnd: int) -> bool:
    """恢复并前台显示窗口，返回是否成功"""
    # 检查窗口是否最小化
    is_iconic = _user32.IsIconic(hwnd)
    if is_iconic:
        _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.2)

    # 带到前台
    _user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)

    # 验证
    foreground = _user32.GetForegroundWindow()
    if foreground != hwnd:
        # 重试一次
        _user32.ShowWindow(hwnd, 5)  # SW_SHOW
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)

    return _user32.GetForegroundWindow() == hwnd


def _minimize_window(hwnd: int):
    """最小化窗口"""
    _user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE


def _restore_previous_focus(prev_hwnd: int):
    """恢复之前的前台窗口"""
    if prev_hwnd and _user32.IsWindow(prev_hwnd):
        _user32.SetForegroundWindow(prev_hwnd)


def send_message(chat_name: str, text: str, minimize: bool = True) -> bool:
    """
    发送微信消息

    用 Win32 API 定位微信窗口，用 SendInput 模拟键盘操作：
      Step 1: 恢复窗口 → 前台
      Step 2: 输入联系人名（微信搜索框自动聚焦）
      Step 3: Enter 打开聊天
      Step 4: 输入消息
      Step 5: Ctrl+Enter 发送

    Args:
        chat_name: 联系人名称、备注或 wxid
        text: 消息内容
        minimize: 发送后是否最小化窗口

    Returns:
        是否成功
    """
    if not chat_name or not text:
        log.warning("send_message 收到空参数: chat_name=%r, text=%r", chat_name, text)
        return False

    # 找窗口
    hwnd = _find_window_handle()
    if not hwnd:
        log.warning("找不到微信窗口（标题='%s'）", _WECHAT_WINDOW_TITLE)
        return False

    # 记录当前前台窗口
    prev_hwnd = _user32.GetForegroundWindow()
    is_same_window = (prev_hwnd == hwnd)

    # ---- Step 1: 恢复 + 前台 ----
    log.info("Step 1: 恢复微信窗口到前台")
    if not _restore_and_foreground(hwnd):
        log.warning("无法将微信窗口带到前台")
        # 仍然尝试继续 — 键盘输入可能仍有效
    time.sleep(0.3)

    # ---- Step 2: 聚焦搜索框 ----
    log.info("Step 2: 聚焦搜索框")
    # Ctrl+F 将焦点定位到微信搜索框（确保不在聊天输入框里输入）
    auto.SendKeys('{Ctrl}f', waitTime=0.2)
    time.sleep(0.3)

    # ---- Step 3: 输入联系人名 ----
    log.info("Step 3: 搜索联系人 '%s'", chat_name)
    # 全选 + Delete 清空搜索框
    auto.SendKeys('{Ctrl}a', waitTime=0.1)
    auto.SendKeys('{Delete}', waitTime=0.1)
    # 输入联系人名
    auto.SendKeys(chat_name, waitTime=0.3)
    # 等待搜索结果加载
    time.sleep(0.8)

    # ---- Step 4: 打开聊天 ----
    log.info("Step 4: 打开聊天窗口")
    auto.SendKeys('{Enter}', waitTime=0.5)
    # 等待聊天窗口加载
    time.sleep(0.5)

    # ---- Step 5: 输入消息 ----
    log.info("Step 5: 输入消息")
    # 全选 + Delete 清空输入框（防止残留内容）
    auto.SendKeys('{Ctrl}a', waitTime=0.1)
    auto.SendKeys('{Delete}', waitTime=0.1)
    # 输入消息
    auto.SendKeys(text, waitTime=0.2)
    time.sleep(0.2)

    # ---- Step 6: 发送 ----
    log.info("Step 6: 发送消息")
    auto.SendKeys('{Enter}', waitTime=0.3)
    # 等待发送完成
    time.sleep(0.3)
    log.info("Step 6: 消息已发送")

    # ---- Step 6: 最小化（可选） ----
    if minimize:
        _minimize_window(hwnd)

    # 恢复之前的前台窗口（仅当不是同一个窗口时）
    if not is_same_window:
        _restore_previous_focus(prev_hwnd)

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
