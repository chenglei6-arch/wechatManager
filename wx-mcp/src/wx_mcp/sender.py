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
_user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
_user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]

# 剪贴板 API
_user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
_user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
_user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
_user32.SetFocus.argtypes = [ctypes.wintypes.HWND]
_user32.SetFocus.restype = ctypes.wintypes.HWND
_user32.SwitchToThisWindow.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.BOOL]
_user32.SwitchToThisWindow.restype = None
_user32.CloseClipboard.restype = ctypes.wintypes.BOOL
_user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
_user32.SetClipboardData.restype = ctypes.wintypes.HANDLE
_user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
_user32.GetClipboardData.restype = ctypes.wintypes.HANDLE
_user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
_kernel32 = ctypes.windll.kernel32
_kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
_kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalLock.restype = ctypes.wintypes.LPVOID
_kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
_kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
_kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
_kernel32.GlobalFree.restype = ctypes.wintypes.BOOL
_kernel32.GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]

# kernel32 额外函数
_kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD

_GMEM_MOVABLE = 0x0002


def _set_clipboard_text(text: str):
    """设置剪贴板文本（UTF-16）"""
    try:
        _user32.OpenClipboard(None)
        _user32.EmptyClipboard()
        data = (text + '\0').encode('utf-16-le')
        handle = _kernel32.GlobalAlloc(_GMEM_MOVABLE, len(data))
        ptr = _kernel32.GlobalLock(handle)
        if ptr:
            ctypes.memmove(ptr, data, len(data))
            _kernel32.GlobalUnlock(handle)
        _user32.SetClipboardData(_CF_UNICODETEXT, handle)
    except Exception as e:
        log.debug("设置剪贴板失败: %s", e)
    finally:
        try:
            _user32.CloseClipboard()
        except Exception:
            pass


def _get_clipboard_text() -> str:
    """读取剪贴板文本（失败返回空字符串）"""
    try:
        _user32.OpenClipboard(None)
        handle = _user32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ''
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            return ''
        try:
            chars = []
            offset = 0
            while True:
                addr = ptr if isinstance(ptr, int) else ptr.value
                char = ctypes.c_wchar.from_address(addr + offset)
                if char.value == '\0':
                    break
                chars.append(char.value)
                offset += 2
            return ''.join(chars)
        finally:
            _kernel32.GlobalUnlock(handle)
    except Exception as e:
        log.debug("读取剪贴板失败: %s", e)
        return ''
    finally:
        try:
            _user32.CloseClipboard()
        except Exception:
            pass

# CF_UNICODETEXT 格式常量
_CF_UNICODETEXT = 13


class _SafeForeground:
    """上下文管理器：确保微信窗口在前台期间执行操作

    进入时用 SwitchToThisWindow 将微信窗口带到前台
    （不受后台进程权限限制），退出时恢复之前的前台窗口。
    """
    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.prev_hwnd = 0

    def __enter__(self):
        self.prev_hwnd = _user32.GetForegroundWindow()

        # 最小化则恢复
        if _user32.IsIconic(self.hwnd):
            _user32.ShowWindow(self.hwnd, 9)
            _user32.SwitchToThisWindow(self.hwnd, True)
            time.sleep(0.2)

        # SwitchToThisWindow：不受前台权限限制，后台进程也能切前台
        _user32.SwitchToThisWindow(self.hwnd, True)
        time.sleep(0.2)

        # 再试一次（有时需要两次）
        if _user32.GetForegroundWindow() != self.hwnd:
            _user32.SwitchToThisWindow(self.hwnd, True)
            time.sleep(0.2)

        return self

    def __exit__(self, *args):
        # 恢复之前的前台窗口
        if self.prev_hwnd and self.prev_hwnd != self.hwnd and _user32.IsWindow(self.prev_hwnd):
            _user32.SwitchToThisWindow(self.prev_hwnd, True)


def _find_window_handle() -> Optional[int]:
    """通过 FindWindowW 查找微信主窗口句柄（比 UIA 更可靠）"""
    handle = _user32.FindWindowW(None, _WECHAT_WINDOW_TITLE)
    if handle:
        return handle
    return None


def _get_window_thread_id(hwnd: int) -> int:
    """获取窗口所属的线程 ID，无效句柄返回 0"""
    if not hwnd:
        return 0
    pid = ctypes.wintypes.DWORD()
    tid = _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return tid


def _restore_and_foreground(hwnd: int) -> bool:
    """恢复并前台显示窗口（使用 AttachThreadInput 绕过 Windows 前台权限限制），返回是否成功"""
    # 检查窗口是否最小化
    is_iconic = _user32.IsIconic(hwnd)
    if is_iconic:
        _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.2)

    # AttachThreadInput：将调用线程附加到目标窗口的输入线程，
    # 这样 SetForegroundWindow 就能跨进程生效
    target_tid = _get_window_thread_id(hwnd)
    current_tid = _kernel32.GetCurrentThreadId()
    attached = False
    if target_tid and target_tid != current_tid:
        _user32.AttachThreadInput(current_tid, target_tid, True)
        attached = True

    # 多次尝试带到前台
    for attempt in range(3):
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        if _user32.GetForegroundWindow() == hwnd:
            break

    # 分离输入线程
    if attached:
        _user32.AttachThreadInput(current_tid, target_tid, False)

    result = _user32.GetForegroundWindow() == hwnd
    if not result:
        log.warning("无法将微信窗口带到前台（尝试 3 次）")
    return result


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

    # 保存当前剪贴板内容，后续恢复
    saved_clipboard = _get_clipboard_text()
    # 将要发送的消息写入剪贴板（用 Ctrl+V 粘贴比 SendKeys 打字更可靠）
    _set_clipboard_text(text)

    try:
        # 使用 SafeForeground 确保微信窗口在前台
        with _SafeForeground(hwnd) as ctx:
            if _user32.GetForegroundWindow() != hwnd:
                log.warning("微信窗口未成功前台，键盘输入可能打到其他窗口")
                return False

            # ---- Step 1: 聚焦搜索框 ----
            log.info("Step 1: Ctrl+F 聚焦搜索框")
            auto.SendKeys('{Ctrl}f', waitTime=0.2)
            time.sleep(0.3)

            # ---- Step 2: 输入联系人名 ----
            log.info("Step 2: 搜索联系人 '%s'", chat_name)
            auto.SendKeys('{Ctrl}a', waitTime=0.1)
            auto.SendKeys('{Delete}', waitTime=0.1)
            auto.SendKeys(chat_name, waitTime=0.3)
            time.sleep(0.8)

            # ---- Step 3: 打开聊天 ----
            log.info("Step 3: Enter 打开聊天窗口")
            auto.SendKeys('{Enter}', waitTime=0.5)
            time.sleep(0.5)

            # ---- Step 4: 粘贴消息 ----
            log.info("Step 4: Ctrl+V 粘贴消息")
            auto.SendKeys('{Ctrl}a', waitTime=0.1)
            auto.SendKeys('{Delete}', waitTime=0.1)
            auto.SendKeys('{Ctrl}v', waitTime=0.2)
            time.sleep(0.3)

            # ---- Step 5: 发送 ----
            log.info("Step 5: Enter 发送")
            auto.SendKeys('{Enter}', waitTime=0.3)
            time.sleep(0.3)
            log.info("消息已发送")

        # 最小化
        if minimize:
            _minimize_window(hwnd)

        return True
    finally:
        # 恢复剪贴板
        try:
            time.sleep(0.1)
            if saved_clipboard:
                _set_clipboard_text(saved_clipboard)
            else:
                _user32.OpenClipboard(None)
                _user32.EmptyClipboard()
                _user32.CloseClipboard()
        except Exception as e:
            log.debug("剪贴板恢复失败: %s", e)


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
