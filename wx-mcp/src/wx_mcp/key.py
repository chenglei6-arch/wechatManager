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


def _scan_private_memory(pm: pymem.Pymem, pattern: bytes) -> list:
    """
    仅扫描进程的私有内存区域（堆/栈），跳过 DLL 镜像和内存映射文件

    微信 4.x 是 Electron 应用，SQLCipher 密钥字符串存放在 V8 堆（MEM_PRIVATE）中。
    跳过 MEM_IMAGE（DLL）和 MEM_MAPPED（文件映射）可减少 80%+ 扫描量，避免卡死。
    """
    import pymem.memory
    import pymem.ressources.structure as structs

    MEM_PRIVATE = 0x20000
    ALLOWED_PROTECTIONS = {
        structs.MEMORY_PROTECTION.PAGE_READWRITE,
        structs.MEMORY_PROTECTION.PAGE_READONLY,
        structs.MEMORY_PROTECTION.PAGE_EXECUTE_READ,
        structs.MEMORY_PROTECTION.PAGE_EXECUTE_READWRITE,
    }

    results: list = []
    address = 0
    user_space_limit = 0x7FFFFFFF0000 if sys.maxsize > 2**32 else 0x7fff0000
    region_count = 0
    total_bytes = 0

    while address < user_space_limit:
        try:
            mbi = pymem.memory.virtual_query(pm.process_handle, address)
        except Exception:
            break

        region_size = mbi.RegionSize
        if region_size == 0:
            break

        next_address = mbi.BaseAddress + region_size
        # 防溢出保护
        if next_address <= mbi.BaseAddress:
            break

        is_committed = mbi.State == structs.MEMORY_STATE.MEM_COMMIT
        is_private = mbi.Type == MEM_PRIVATE
        is_readable = mbi.Protect in ALLOWED_PROTECTIONS

        if is_committed and is_private and is_readable:
            region_count += 1
            total_bytes += region_size
            # 分块读取，防止单次 ReadProcessMemory 过大失败
            CHUNK_SIZE = 1024 * 1024  # 1 MB
            for offset in range(0, region_size, CHUNK_SIZE):
                chunk_len = min(CHUNK_SIZE, region_size - offset)
                try:
                    chunk = pymem.memory.read_bytes(
                        pm.process_handle, mbi.BaseAddress + offset, chunk_len
                    )
                    for match in re.finditer(pattern, chunk, re.DOTALL):
                        results.append(mbi.BaseAddress + offset + match.span()[0])
                except Exception:
                    continue

        address = next_address

    log.info(
        "内存扫描完成: 扫描 %d 个私有区域 (%d MB)，发现 %d 个候选地址",
        region_count, total_bytes // (1024 * 1024), len(results),
    )
    return results


def extract_keys(target_pid: Optional[int] = None) -> Dict[str, str]:
    """
    从微信进程内存提取所有密钥对

    返回: {salt_hex: key_hex}
    """
    if target_pid is None:
        target_pid = find_wechat_pid()
        if target_pid is None:
            raise RuntimeError("找不到微信进程 (Weixin.exe)，请先登录微信")

    log.info("正在从进程 %d 内存提取密钥 (x'<64hex><32hex>')", target_pid)
    pm = pymem.Pymem()
    pm.open_process_from_id(target_pid)

    pattern = b"x'[0-9a-f]{64}[0-9a-f]{32}'"
    addrs = _scan_private_memory(pm, pattern)

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
            log.debug("读取地址 0x%x 失败: %s", addr, e)
            continue

    log.info("提取到 %d 个有效密钥对", len(keys))
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
