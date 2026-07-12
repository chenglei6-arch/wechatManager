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


# ---- PostMessage 备用发送方法 ----
# 当 SwitchToThisWindow 因 UIPI 被阻止时，
# 使用 PostMessage 将键盘事件直接发送到微信窗口的消息队列。
# 不要求窗口在前台，但依赖 Qt 处理 Posted 消息。

# 窗口消息常量
_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_WM_CHAR = 0x0102
_WM_ACTIVATE = 0x0006
_WM_SETFOCUS = 0x0007
_WA_ACTIVE = 1

# 虚拟键码
_VK_CONTROL = 0x11
_VK_RETURN = 0x0D
_VK_F = 0x46
_VK_V = 0x56
_VK_A = 0x41
_VK_DELETE = 0x2E
_VK_BACK = 0x08
_VK_ESCAPE = 0x1B
_VK_TAB = 0x09

# User32 PostMessage/SendMessage for fallback
_user32.PostMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
_user32.PostMessageW.restype = ctypes.wintypes.BOOL
_user32.SendMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
_user32.SendMessageW.restype = ctypes.c_int64


def _post_key_down(hwnd: int, vk: int):
    """向窗口发送 WM_KEYDOWN"""
    _user32.PostMessageW(hwnd, _WM_KEYDOWN, vk, 1)


def _post_key_up(hwnd: int, vk: int):
    """向窗口发送 WM_KEYUP（prev state=down, transition=up）"""
    lparam = (1 << 31) | (1 << 30) | 1
    _user32.PostMessageW(hwnd, _WM_KEYUP, vk, lparam)


def _post_chars(hwnd: int, text: str):
    """向窗口发送一串字符（WM_CHAR），支持 UTF-16 代理对（emoji 等）"""
    encoded = text.encode('utf-16-le')
    for i in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[i:i+2], 'little')
        _user32.PostMessageW(hwnd, _WM_CHAR, code_unit, 1)


def _post_ctrl_combo(hwnd: int, vk: int):
    """发送 Ctrl+<key> 组合键"""
    _post_key_down(hwnd, _VK_CONTROL)
    _post_key_down(hwnd, vk)
    _post_key_up(hwnd, vk)
    _post_key_up(hwnd, _VK_CONTROL)


def _send_key_down(hwnd: int, vk: int):
    """向窗口发送 WM_KEYDOWN（同步，确保 Qt 立即处理）"""
    _user32.SendMessageW(hwnd, _WM_KEYDOWN, vk, 1)


def _send_key_up(hwnd: int, vk: int):
    """向窗口发送 WM_KEYUP（同步）"""
    lparam = (1 << 31) | (1 << 30) | 1
    _user32.SendMessageW(hwnd, _WM_KEYUP, vk, lparam)


def _send_chars(hwnd: int, text: str):
    """向窗口发送一串字符（WM_CHAR，同步），支持 UTF-16 代理对"""
    encoded = text.encode('utf-16-le')
    for i in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[i:i+2], 'little')
        _user32.SendMessageW(hwnd, _WM_CHAR, code_unit, 1)


def _is_weixin_url_registered() -> bool:
    """检查 weixin:// URL 协议是否已注册"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "weixin")
        return True
    except (FileNotFoundError, OSError):
        return False


def _send_via_url_protocol(wxid: str, text: str) -> bool:
    """
    通过 weixin://dl/chat URL 协议打开指定联系人的聊天窗口并发送消息。

    weixin:// 协议由 WeChat 安装时在 Windows 注册，
    调用后 WeChat 会激活对应聊天，可能将窗口带到前台。
    """
    import subprocess
    log.info("尝试 URL 协议: weixin://dl/chat?%s", wxid)
    url = f'weixin://dl/chat?{wxid}'
    try:
        subprocess.Popen(
            ['cmd', '/c', 'start', url],
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as e:
        log.warning("URL 协议调用失败: %s", e)
        return False

    time.sleep(1.2)

    # 尝试用 SwitchToThisWindow + SendInput 发送
    hwnd = _find_window_handle()
    if not hwnd:
        return False

    saved = _get_clipboard_text()
    _set_clipboard_text(text)

    try:
        with _SafeForeground(hwnd):
            if _user32.GetForegroundWindow() == hwnd:
                log.info("URL 协议后微信已前台，SendInput 发送")
                auto.SendKeys('{Ctrl}v', waitTime=0.3)
                time.sleep(0.3)
                auto.SendKeys('{Enter}', waitTime=0.3)
                return True
            else:
                log.info("URL 协议未前台，SendMessage 发送")
                _send_chars(hwnd, text)
                time.sleep(0.3)
                _send_key_down(hwnd, _VK_RETURN)
                _send_key_up(hwnd, _VK_RETURN)
                return True
    finally:
        time.sleep(0.1)
        if saved:
            _set_clipboard_text(saved)
        else:
            _user32.OpenClipboard(None)
            _user32.EmptyClipboard()
            _user32.CloseClipboard()


def _direct_postmessage_send(hwnd: int, chat_name: str, text: str) -> bool:
    """
    基于 SendMessage 的键盘输入方法（同步处理，不依赖前台）。

    关键发现：
      - WM_CHAR 中文在后台窗口正常工作 ✅
      - Ctrl 组合键在后台窗口被 Qt 忽略 ❌
      - Enterprise 键 (Enter) 在后台窗口会发送当前输入框内容

    策略：
      1. 用 WM_NEXTDLGCTL 尝试让 Qt 切换到搜索框
      2. SendMessage WM_CHAR 输联系人名 → Enter
      3. SendMessage WM_CHAR 输消息 → Enter 发送

    Args:
        hwnd: 微信主窗口句柄
        chat_name: 联系人名称
        text: 消息内容
    """
    _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                         0x0002 | 0x0001 | 0x0020)
    time.sleep(0.1)

    _WM_NEXTDLGCTL = 0x0028

    # ---- 第一步：尝试让焦点进入搜索框 ----
    # Escape × 2 → 尝试解除输入框焦点
    _send_key_down(hwnd, _VK_ESCAPE)
    _send_key_up(hwnd, _VK_ESCAPE)
    time.sleep(0.15)
    _send_key_down(hwnd, _VK_ESCAPE)
    _send_key_up(hwnd, _VK_ESCAPE)
    time.sleep(0.15)

    # WM_NEXTDLGCTL → 强制切换到下一个控件（可能不受 Qt 激活状态限制）
    for _ in range(6):
        _user32.SendMessageW(hwnd, _WM_NEXTDLGCTL, 1, 0)
        time.sleep(0.12)

    # ---- 第二步：输入联系人名 ----
    _send_chars(hwnd, chat_name)
    time.sleep(0.8)

    # ---- 第三步：Enter 打开聊天 ----
    _send_key_down(hwnd, _VK_RETURN)
    _send_key_up(hwnd, _VK_RETURN)
    time.sleep(0.6)

    # ---- 第四步：输入消息内容 ----
    _send_chars(hwnd, text)
    time.sleep(0.6)

    # ---- 第五步：Enter 发送 ----
    _send_key_down(hwnd, _VK_RETURN)
    _send_key_up(hwnd, _VK_RETURN)
    time.sleep(0.4)

    return True

    return True


def _get_contact_wxid(chat_name: str) -> Optional[str]:
    """从联系人数据库查询 chat_name 对应的 wxid"""
    try:
        from wx_mcp.reader import WeChatReader
        # 尝试从解密后的数据库获取 reader
        try:
            from wx_mcp.server import get_reader, _state
            reader = get_reader()
        except Exception:
            return None
        contacts = reader.get_contacts(keyword=chat_name, limit=1)
        if contacts:
            return contacts[0].get('username', '') or None
    except Exception as e:
        log.debug("获取 wxid 失败: %s", e)
    return None


def send_message_fallback(chat_name: str, text: str) -> bool:
    """
    多备用发送方法（当 SwitchToThisWindow 失败时）：
      1. weixin://dl/chat URL 协议
      2. SendMessage 直接键盘事件

    Args:
        chat_name: 联系人名称
        text: 消息内容
    """
    if not chat_name or not text:
        log.warning("send_message_fallback 收到空参数")
        return False

    # Fallback 1: weixin:// URL 协议
    wxid = _get_contact_wxid(chat_name)
    if wxid and _is_weixin_url_registered():
        log.info("Fallback 1: 尝试 weixin:// URL 协议")
        ok = _send_via_url_protocol(wxid, text)
        if ok:
            return True

    # Fallback 2: SendMessage 键盘事件
    hwnd = _find_window_handle()
    if hwnd:
        log.info("Fallback 2: 尝试 SendMessage 键盘事件")
        try:
            ok = _direct_postmessage_send(hwnd, chat_name, text)
            if ok:
                return True
        except Exception as e:
            log.warning("SendMessage 失败: %s", e)

    return False


def send_message(chat_name: str, text: str, minimize: bool = True) -> bool:
    """
    发送微信消息

    使用两阶段策略：
      方法 A — 优先通过 SwitchToThisWindow 将微信带到前台，再用 SendInput 模拟键盘操作
      （适用于微信与 MCP Server 在同一权限级别运行）
      方法 B — 若 SwitchToThisWindow 被 UIPI 拦截，改用 PostMessage 直接向微信窗口
      消息队列投递键盘事件（不依赖前台，但依赖 Qt 处理 Posted 消息）

    键盘操作流程：
      1. Ctrl+F → 聚焦搜索框
      2. 输入联系人名
      3. Enter → 打开聊天
      4. Ctrl+V → 粘贴消息（通过剪贴板）
      5. Enter → 发送

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
            foreground_ok = (_user32.GetForegroundWindow() == hwnd)

        if foreground_ok:
            # ---- 方法 A: 窗口已前台，使用 SendInput (SendKeys) ----
            log.info("方法A: 微信窗口已前台，使用 SendKeys")
            with _SafeForeground(hwnd) as ctx:
                if _user32.GetForegroundWindow() != hwnd:
                    log.warning("微信窗口未能保持前台")
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
        else:
            # ---- 方法 B: SwitchToThisWindow 被 UIPI 阻止，改用备用方法 ----
            log.info("方法B: SwitchToThisWindow 被拦截，改用备用方法")
            fb_ok = send_message_fallback(chat_name, text)
            if fb_ok:
                log.info("备用方法发送成功")
                return True
            else:
                log.warning("所有备用方法均失败")
                return False
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
