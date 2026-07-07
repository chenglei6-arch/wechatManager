"""
微信消息发送器

使用窗口自动化（非 API）发送消息到指定的联系人或群聊。
通过 SendInput 模拟键盘鼠标输入，取代已弃用的 keybd_event/mouse_event。
"""
import sys, os, time, ctypes, logging
from ctypes import wintypes

log = logging.getLogger('wx-mcp.sender')

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ---- SendInput 类型定义 ----
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# dwExtraInfo 是指针大小（64位=8字节, 32位=4字节）
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ('wVk', wintypes.WORD),
        ('wScan', wintypes.WORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ('dx', wintypes.LONG),
        ('dy', wintypes.LONG),
        ('mouseData', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ('mi', MOUSEINPUT),
        ('ki', KEYBDINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ('type', wintypes.DWORD),
        ('union', INPUT_UNION),
    ]


def _send_key(vk: int, down: bool):
    """通过 SendInput 发送单个键盘事件"""
    flags = KEYEVENTF_KEYDOWN if down else KEYEVENTF_KEYUP
    ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    inp = INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=ki))
    result = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if result != 1:
        log.warning(f"SendInput key=0x{vk:02X} down={down} 返回 {result}")


def _press(vk: int):
    _send_key(vk, True)
    time.sleep(0.02)
    _send_key(vk, False)


def _ctrl(vk: int):
    _send_key(0x11, True)   # Ctrl down
    time.sleep(0.01)
    _send_key(vk, True)     # key down
    time.sleep(0.03)
    _send_key(vk, False)    # key up
    time.sleep(0.01)
    _send_key(0x11, False)  # Ctrl up


def _click(x: int, y: int):
    """通过 SendInput 在指定坐标点击鼠标左键"""
    user32.SetCursorPos(x, y)
    time.sleep(0.02)

    # 左键按下
    mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)
    inp = INPUT(INPUT_MOUSE, INPUT_UNION(mi=mi))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    time.sleep(0.02)

    # 左键抬起
    mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)
    inp = INPUT(INPUT_MOUSE, INPUT_UNION(mi=mi))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


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
    def enum_close_floats(h, lp):
        try:
            b = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, b, 256)
            if b.value == 'Qt51514QWindowIcon':
                t = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(h, t, 256)
                if t.value and t.value != '微信' and user32.IsWindowVisible(h):
                    user32.PostMessageW(h, 0x0010, 0, 0)
        except Exception as e:
            log.warning(f"enum_close_floats hwnd={h}: {e}")
        return True
    user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_int)(enum_close_floats), 0)

    # 找主窗口
    hwnds = []

    def enum_find_main(h, lp):
        try:
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
        except Exception as e:
            log.warning(f"enum_find_main hwnd={h}: {e}")
        return True
    user32.EnumWindows(
        ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, ctypes.c_int)(enum_find_main), 0)

    if not hwnds:
        log.warning("找不到微信主窗口")
        return False
    hwnd = hwnds[0]

    wx_tid = user32.GetWindowThreadProcessId(hwnd, None)
    cur_tid = kernel32.GetCurrentThreadId()
    prev_fg = user32.GetForegroundWindow()

    attached = False
    try:
        user32.AttachThreadInput(cur_tid, wx_tid, True)
        attached = True
    except Exception as e:
        log.warning(f"AttachThreadInput 失败: {e}")

    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
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
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE

        return True
    finally:
        if attached:
            try:
                user32.AttachThreadInput(cur_tid, wx_tid, False)
            except Exception as e:
                log.warning(f"AttachThreadInput(Detach) 失败: {e}")
        try:
            if prev_fg and prev_fg != hwnd:
                user32.SetForegroundWindow(prev_fg)
        except Exception as e:
            log.warning(f"恢复前台窗口失败: {e}")


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

        try:
            is_last = (i == total - 1)
            ok = send_message(contact, msg, minimize=is_last)
            results.append((contact, ok))
        except Exception as e:
            log.error(f"发送给 {contact} 失败: {e}", exc_info=True)
            results.append((contact, False))
        time.sleep(0.1)

    return results
