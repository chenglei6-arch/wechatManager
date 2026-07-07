"""
从微信进程内存中提取数据库解密密钥

使用 pymem 扫描 Weixin.exe 进程内存，
搜索 SQLCipher 密钥模式 (x'<64hex><32hex>')。
"""
import re, json, os, logging
from typing import Dict, Optional

log = logging.getLogger('wx-mcp.key')


def find_wechat_pid() -> Optional[int]:
    """查找 Weixin.exe 主进程 PID"""
    import psutil
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            if proc.info['name'] == 'Weixin.exe' and proc.info['exe'] and 'crashpad' not in proc.info['exe']:
                return proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            log.debug(f"psutil 跳过进程: {e}")
            continue
    return None


def extract_keys(target_pid: int = None) -> Dict[str, str]:
    """
    从微信进程内存提取所有密钥对

    返回: {salt_hex: key_hex}
    """
    import pymem

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

    keys = {}  # salt -> key
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
    """保存密钥到JSON文件"""
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(keys, f, indent=2)
    log.info(f"密钥已保存到 {filepath}")


def load_keys(filepath: str) -> Dict[str, str]:
    """从JSON文件加载密钥"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)
