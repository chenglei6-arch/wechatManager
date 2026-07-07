"""
从微信进程内存中提取数据库解密密钥

使用 pymem 扫描 Weixin.exe 进程内存，
搜索 SQLCipher 密钥模式 (x'<64hex><32hex>')。

密钥文件 (keys.json) 使用 Windows DPAPI 加密存储，
确保磁盘上的密钥数据只有当前用户能解密。
"""
import json
import logging
import os
import re
from typing import Dict, Optional

import psutil
import pymem

from wx_mcp import crypto

log = logging.getLogger('wx-mcp.key')


# keys.json 加密标识：文件以该前缀开头表示已加密
_DPAPI_MAGIC = b'DPAPI\x00'


def find_wechat_pid() -> Optional[int]:
    """查找 Weixin.exe 主进程 PID"""
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            if proc.info['name'] == 'Weixin.exe' and proc.info['exe'] and 'crashpad' not in proc.info['exe']:
                return proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log.debug(f"psutil 跳过进程: {e}")
            continue
    return None


def extract_keys(target_pid: Optional[int] = None) -> Dict[str, str]:
    """
    从微信进程内存提取所有密钥对

    返回: {salt_hex: key_hex}
    """
    if target_pid is None:
        target_pid = find_wechat_pid()
        if target_pid is None:
            raise RuntimeError("找不到微信进程 (Weixin.exe)，请先登录微信")

    log.info(f"正在扫描进程 {target_pid} 内存, 模式: x'<64hex><32hex>'")
    pm = pymem.Pymem()
    pm.open_process_from_id(target_pid)

    pattern = b"x'[0-9a-f]{64}[0-9a-f]{32}'"
    addrs = pm.pattern_scan_all(pattern, return_multiple=True)
    log.info(f"内存扫描完成, 发现 {len(addrs)} 个候选地址")

    keys: Dict[str, str] = {}
    for addr in addrs:
        try:
            data = pm.read_bytes(addr, 100)
            text = data.decode('utf-8', errors='ignore')
            match = re.search(r"x'([0-9a-f]{64})([0-9a-f]{32})'", text)
            if match:
                key = match.group(1)
                salt = match.group(2)
                keys[salt] = key
        except Exception as e:
            log.debug(f"读取地址 0x{addr:x} 失败: {e}")
            continue

    log.info(f"提取到 {len(keys)} 个有效密钥对")
    return keys


def save_keys(keys: Dict[str, str], filepath: str):
    """
    保存密钥到文件（DPAPI 加密）

    加密格式: DPAPI\x00 + DPAPI_encrypted(json_blob)
    """
    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
    plaintext = json.dumps(keys, indent=2).encode('utf-8')
    encrypted = crypto.encrypt(plaintext)
    with open(filepath, 'wb') as f:
        f.write(_DPAPI_MAGIC + encrypted)
    log.info(f"密钥已加密保存到 {filepath}")


def load_keys(filepath: str) -> Dict[str, str]:
    """
    从文件加载密钥（自动检测 DPAPI 加密或明文 JSON）

    兼容旧版明文格式，检测到 DPAPI_MAGIC 前缀时自动解密。
    """
    with open(filepath, 'rb') as f:
        raw = f.read()

    if raw.startswith(_DPAPI_MAGIC):
        encrypted = raw[len(_DPAPI_MAGIC):]
        plaintext = crypto.decrypt(encrypted)
        log.info(f"密钥已从加密文件加载: {filepath}")
    else:
        # 兼容旧版明文格式
        log.warning(f"密钥文件未加密，建议删除后重新提取以启用 DPAPI 加密: {filepath}")
        plaintext = raw

    return json.loads(plaintext.decode('utf-8'))
