"""
微信消息发送器

使用窗口自动化（非 API）发送消息到指定的联系人或群聊。
"""
import sys, os, time, ctypes
from ctypes import wintypes
import pyperclip


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def _press(vk):
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(vk, 0, 2, 0)


def _ctrl(vk):
    user32.keybd_event(0x11, 0, 0, 0)
    time.sleep(0.01)
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.01)
    user32.keybd_event(0x11, 0, 2, 0)


def _click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.02)
    user32.mouse_event(2, 0, 0, 0, 0)
    time.sleep(0.02)
    user32.mouse_event(4, 0, 0, 0, 0)


def send_message(chat_name: str, text: str, minimize: bool = True) -> bool:
    """
    发送微信消息

    Args:
        chat_name: 联系人名称或备注
        text: 消息内容
        minimize: 发送后是否最小化窗口

    Returns:
        是否成功
    """
    # 关闭浮动聊天窗口
    def enum(h, lp):
        b = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, b, 256)
        if b.value == 'Qt51514QWindowIcon':
            t = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, t, 256)
            if t.value and t.value != '微信' and user32.IsWindowVisible(h):
                user32.PostMessageW(h, 0x0010, 0, 0)
        return True
    user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_int)(enum), 0)

    # 找主窗口
    hwnds = []

    def enum2(h, lp):
        b = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, b, 256)
        if b.value != 'Qt51514QWindowIcon':
            return True
        t = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, t, 256)
        if t.value != '微信':
            return True
        if user32.IsWindowVisible(h):
            hwnds.append(h)
        return True
    user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_int)(enum2), 0)
    if not hwnds:
        return False
    hwnd = hwnds[0]

    wx_tid = user32.GetWindowThreadProcessId(hwnd, None)
    cur_tid = kernel32.GetCurrentThreadId()
    prev_fg = user32.GetForegroundWindow()

    user32.AttachThreadInput(cur_tid, wx_tid, True)
    try:
        # 激活窗口
        user32.ShowWindow(hwnd, 9)
        user32.SetWindowPos(hwnd, 0, 100, 100, 1000, 700, 0x0040)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        time.sleep(0.2)

        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        lx, ly, w, h = r.left, r.top, r.right - r.left, r.bottom - r.top

        # 点搜索栏 → Ctrl+F
        _click(lx + 150, ly + 55)
        time.sleep(0.15)
        _ctrl(0x46)
        time.sleep(0.2)

        # 粘贴联系人
        pyperclip.copy(chat_name)
        time.sleep(0.05)
        _ctrl(0x56)
        time.sleep(0.4)

        # Enter 打开聊天
        _press(0x0D)
        time.sleep(0.5)

        # 点输入框
        _click(lx + int(w * 0.3), ly + h - 60)
        time.sleep(0.15)

        # 粘贴消息
        pyperclip.copy(text)
        time.sleep(0.05)
        _ctrl(0x56)
        time.sleep(0.2)

        # Enter 发送
        _press(0x0D)
        time.sleep(0.15)

        if minimize:
            user32.ShowWindow(hwnd, 6)

        return True
    finally:
        try:
            user32.AttachThreadInput(cur_tid, wx_tid, False)
        except Exception:
            pass
        # 恢复前台
        try:
            if prev_fg and prev_fg != hwnd:
                user32.SetForegroundWindow(prev_fg)
        except Exception:
            pass


def send_batch(tasks: list, message: str = None) -> list:
    """
    批量发送消息

    Args:
        tasks: [(联系人, 消息), ...] 或 [联系人, ...]
        message: 当 tasks 为联系人列表时使用的默认消息

    Returns:
        [(联系人, 是否成功), ...]
    """
    results = []
    total = len(tasks)

    for i, task in enumerate(tasks):
        if isinstance(task, (list, tuple)):
            contact, msg = task
        else:
            contact, msg = task, message or f"测试{int(time.time())}"

        is_last = (i == total - 1)
        ok = send_message(contact, msg, minimize=is_last)
        results.append((contact, ok))
        time.sleep(0.1)

    return results
