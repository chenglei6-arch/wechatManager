"""
WeChat MCP Server

为 Claude 提供读取微信消息、联系人、会话和发送消息的能力。

安装:
  pip install -e wx-mcp/
  # 然后通过 MCP 配置:
  python -m wx_mcp

或通过 MCP 配置 (claude.json):
  "mcpServers": {
    "wechat": {
      "command": "python",
      "args": ["-m", "wx_mcp"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
"""
import json
import logging
import os
import threading
import time
from typing import Optional

import atexit

from wx_mcp.key import extract_keys, find_wechat_pid, save_keys, load_keys
from wx_mcp.decrypt import decrypt_database, get_db_salt, verify_page1, PAGE_SIZE
from wx_mcp.reader import WeChatReader
from wx_mcp.sender import send_message, send_batch

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, format='[wx-mcp] %(message)s')
log = logging.getLogger('wx-mcp')

# ---- 路径配置 ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)  # wx-mcp/
KEYS_FILE = os.path.join(PROJECT_DIR, 'keys.json')
DECRYPTED_DIR = os.path.join(PROJECT_DIR, 'decrypted')
WECHAT_DATA_DIR = os.path.expanduser('~/Documents/xwechat_files')
DB_STORAGE_DIR = None  # 自动检测

# ---- 模块级缓存 + 锁 ----
_reader_instance = None
_reader_decrypted_dir = None
_keys_cache = None
_db_storage_cache = None
_decrypt_lock = threading.Lock()
_reader_lock = threading.Lock()


def _cleanup():
    """退出时关闭数据库连接"""
    global _reader_instance
    if _reader_instance is not None:
        try:
            _reader_instance.close()
        except Exception as e:
            log.warning(f"reader 清理失败: {e}")
        _reader_instance = None


atexit.register(_cleanup)


def find_db_storage() -> Optional[str]:
    """自动检测 WeChat 4.x 数据库目录"""
    if not os.path.exists(WECHAT_DATA_DIR):
        return None
    for name in os.listdir(WECHAT_DATA_DIR):
        if name.startswith('wxid_'):
            db_storage = os.path.join(WECHAT_DATA_DIR, name, 'db_storage')
            if os.path.isdir(db_storage):
                return db_storage
    backup = os.path.join(WECHAT_DATA_DIR, 'Backup')
    if os.path.isdir(backup):
        for name in os.listdir(backup):
            if name.startswith('wxid_'):
                db_storage = os.path.join(backup, name, 'db_storage')
                if os.path.isdir(db_storage):
                    return db_storage
    return None


def _ensure_keys() -> dict:
    """获取密钥（带缓存）"""
    global _keys_cache
    if _keys_cache is not None:
        return _keys_cache
    if not os.path.exists(KEYS_FILE):
        log.info("正在从微信进程提取密钥...")
        pid = find_wechat_pid()
        if not pid:
            raise RuntimeError("微信未运行，请先启动微信")
        _keys_cache = extract_keys(pid)
        save_keys(_keys_cache, KEYS_FILE)
        log.info(f"已提取 {len(_keys_cache)} 个密钥")
    else:
        _keys_cache = load_keys(KEYS_FILE)
        log.info(f"已加载 {len(_keys_cache)} 个密钥")
    return _keys_cache


def get_key_for_db(keys: dict, db_path: str) -> Optional[bytes]:
    """获取特定数据库的密钥"""
    salt = get_db_salt(db_path)
    salt_hex = salt.hex()
    if salt_hex in keys:
        return bytes.fromhex(keys[salt_hex])
    return None


def ensure_decrypted():
    """确保所有数据库已解密（线程安全，幂等）"""
    with _decrypt_lock:
        global DB_STORAGE_DIR, _db_storage_cache
        if DB_STORAGE_DIR is None:
            DB_STORAGE_DIR = find_db_storage()
            if DB_STORAGE_DIR is None:
                raise RuntimeError("找不到微信数据目录，请先登录微信")

        keys = _ensure_keys()

        needed_dbs = [
            'contact/contact.db',
            'message/message_0.db',
            'message/message_1.db',
            'session/session.db',
        ]
        os.makedirs(DECRYPTED_DIR, exist_ok=True)

        for rel in needed_dbs:
            src = os.path.join(DB_STORAGE_DIR, rel)
            dst = os.path.join(DECRYPTED_DIR, rel)
            if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                continue
            key = get_key_for_db(keys, src)
            if not key:
                log.warning(f"无密钥: {rel}")
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            ok = decrypt_database(src, dst, key)
            if ok:
                log.info(f"已解密: {rel}")
            else:
                log.warning(f"解密失败: {rel}")

        log.info(f"解密完成，数据在 {DECRYPTED_DIR}")


def get_reader() -> WeChatReader:
    """获取（缓存的）WeChatReader 实例（线程安全）"""
    global _reader_instance, _reader_decrypted_dir
    if _reader_instance is not None and _reader_decrypted_dir == DECRYPTED_DIR:
        return _reader_instance
    with _reader_lock:
        # 双重检查
        if _reader_instance is not None and _reader_decrypted_dir == DECRYPTED_DIR:
            return _reader_instance
        ensure_decrypted()
        _reader_instance = WeChatReader(DECRYPTED_DIR)
        _reader_decrypted_dir = DECRYPTED_DIR
        return _reader_instance


# ---- 初始化 MCP Server ----
mcp = FastMCP("WeChat MCP Server")


@mcp.resource("wechat://contacts")
def get_contacts_resource() -> str:
    """返回联系人列表"""
    return json.dumps(get_reader().get_contacts(limit=100), ensure_ascii=False, indent=2)


@mcp.resource("wechat://contacts/search/{keyword}")
def search_contacts_resource(keyword: str) -> str:
    """搜索联系人"""
    return json.dumps(get_reader().search_contacts(keyword), ensure_ascii=False, indent=2)


@mcp.resource("wechat://messages/{talker}")
def get_messages_resource(talker: str) -> str:
    """获取与某联系人的聊天记录"""
    return json.dumps(get_reader().get_messages(talker, limit=30), ensure_ascii=False, indent=2)


# ---- Tools ----

@mcp.tool()
def list_contacts(keyword: str = "", limit: int = 50) -> str:
    """
    列出微信联系人

    Args:
        keyword: 搜索关键词（可选）
        limit: 最大返回数量，默认50
    """
    try:
        reader = get_reader()
        contacts = reader.get_contacts(keyword=keyword, limit=limit)
        if not contacts:
            return "未找到联系人"
        lines = [f"联系人 ({len(contacts)}):", ""]
        for c in contacts:
            name = c.get('remark') or c.get('nick_name') or c.get('username', '')
            alias = c.get('alias', '') or ''
            username = c.get('username', '')
            suffix = f" ({alias})" if alias else ""
            lines.append(f"  {name}{suffix}")
            lines.append(f"    wxid: {username}")
        return "\n".join(lines)
    except Exception as e:
        log.error(f"list_contacts 失败: {e}", exc_info=True)
        return f"❌ 获取联系人失败: {e}"


@mcp.tool()
def get_recent_sessions(limit: int = 20) -> str:
    """
    获取最近会话列表

    Args:
        limit: 最大返回数量，默认20
    """
    try:
        reader = get_reader()
        sessions = reader.get_sessions(limit=limit)
        if not sessions:
            return "未找到会话"
        lines = [f"最近会话 ({len(sessions)}):", ""]
        for s in sessions:
            name = s.get('strNickName', '')
            content = s.get('strContent', '') or ''
            lines.append(f"  {name}")
            if content:
                lines.append(f"    {str(content)[:60]}")
        return "\n".join(lines)
    except Exception as e:
        log.error(f"get_recent_sessions 失败: {e}", exc_info=True)
        return f"❌ 获取会话失败: {e}"


@mcp.tool()
def read_messages(talker: str, limit: int = 30) -> str:
    """
    读取与某联系人的聊天记录

    Args:
        talker: 联系人的 wxid 或昵称/备注
        limit: 最大返回条数，默认30
    """
    try:
        reader = get_reader()
        contacts = reader.get_contacts(keyword=talker, limit=5)
        if contacts and talker != contacts[0].get('username', ''):
            talker_id = contacts[0].get('username', talker)
        else:
            talker_id = talker

        msgs = reader.get_messages(talker_id, limit=limit)
        if not msgs:
            return f"未找到与 {talker} 的聊天记录"

        lines = [f"与 {talker} 的聊天记录 ({len(msgs)}):", ""]
        for m in reversed(msgs):
            msg_type = m.get('type', 0)
            content = str(m.get('content', '')) or ''
            msg_time = m.get('time', '')

            type_map = {1: '文本', 3: '图片', 34: '语音', 47: '表情', 49: '分享', 10000: '系统'}
            t = type_map.get(msg_type, f'type{msg_type}')

            if msg_type == 1:
                lines.append(f"  [{msg_time}] {content[:200]}")
            else:
                lines.append(f"  [{msg_time}] [{t}] {content[:100]}")
        return "\n".join(lines)
    except Exception as e:
        log.error(f"read_messages 失败: {e}", exc_info=True)
        return f"❌ 读取消息失败: {e}"


@mcp.tool()
def send_wechat_message(contact: str, message: str) -> str:
    """
    发送微信消息给指定联系人

    Args:
        contact: 联系人昵称、备注名
        message: 消息内容
    """
    try:
        ok = send_message(contact, message, minimize=True)
        if ok:
            return f"✅ 已发送给 {contact}: {message[:50]}"
        else:
            return f"❌ 发送失败: 未找到微信窗口或联系人 {contact}"
    except Exception as e:
        log.error(f"send_wechat_message 失败: {e}", exc_info=True)
        return f"❌ 发送失败: {e}"


@mcp.tool()
def batch_send_messages(contacts: list, message: str) -> str:
    """
    批量发送微信消息给多个联系人

    Args:
        contacts: 联系人列表
        message: 消息内容
    """
    try:
        results = send_batch(contacts, message)
        ok_count = sum(1 for _, ok in results if ok)
        lines = [f"批量发送完成: {ok_count}/{len(results)} 成功", ""]
        for contact, ok in results:
            lines.append(f"  {'✅' if ok else '❌'} {contact}")
        return "\n".join(lines)
    except Exception as e:
        log.error(f"batch_send_messages 失败: {e}", exc_info=True)
        return f"❌ 批量发送失败: {e}"


@mcp.tool()
def wechat_status() -> str:
    """获取微信连接状态"""
    try:
        pid = find_wechat_pid()
        db_dir = find_db_storage()
        keys_loaded = os.path.exists(KEYS_FILE)
        decrypted = os.path.exists(DECRYPTED_DIR)

        status = []
        status.append(f"微信进程: {'✅ 运行中' if pid else '❌ 未运行'}")
        status.append(f"数据目录: {'✅ ' + DB_STORAGE_DIR if db_dir else '❌ 未找到'}")
        status.append(f"密钥文件: {'✅ ' + KEYS_FILE if keys_loaded else '❌ 未提取'}")
        status.append(f"解密数据: {'✅ ' + DECRYPTED_DIR if decrypted else '❌ 未解密'}")

        if keys_loaded:
            keys = load_keys(KEYS_FILE)
            status.append(f"密钥数量: {len(keys)}")
        return "\n".join(status)
    except Exception as e:
        log.error(f"wechat_status 失败: {e}", exc_info=True)
        return f"❌ 状态检查失败: {e}"


@mcp.resource("wechat://status")
def status_resource() -> str:
    """微信状态"""
    return wechat_status()


# ---- 启动 ----
def main():
    """启动 MCP Server"""
    log.info("WeChat MCP Server 启动中...")
    try:
        ensure_decrypted()
    except Exception as e:
        log.warning(f"初始化失败: {e}")
        log.warning("启动后可使用 wechat_status 检查状态")

    log.info("WeChat MCP Server 已就绪")
    mcp.run()


if __name__ == '__main__':
    main()
