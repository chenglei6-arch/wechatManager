"""
WeChat MCP 工具函数

提供时间戳处理、ZSTD 解压等共享工具函数。
"""
import logging
from datetime import datetime
from typing import Union

import zstandard as zstd

log = logging.getLogger('wx-mcp.utils')

# 微信时间戳阈值：>1e15 微秒级，>1e12 毫秒级，其余秒级
_TS_THRESHOLD_US = 1_000_000_000_000_000  # 1e15
_TS_THRESHOLD_MS = 1_000_000_000_000      # 1e12


def normalize_timestamp(ts: Union[int, float]) -> float:
    """
    统一微信时间戳为秒级浮点数

    微信数据库中时间戳可能有三种精度：
      - 微秒级（16位数字，> 1e15）
      - 毫秒级（13位数字，> 1e12）
      - 秒级（10位数字）

    Args:
        ts: 微信原始时间戳

    Returns:
        秒级时间戳（float）

    Raises:
        ValueError: 时间戳为负数或超出合理范围
    """
    if not isinstance(ts, (int, float)):
        raise ValueError(f"时间戳类型错误: {type(ts)}")
    if ts < 0:
        raise ValueError(f"时间戳不能为负数: {ts}")
    if ts > 1e18:
        raise ValueError(f"时间戳超出合理范围: {ts}")

    if ts >= _TS_THRESHOLD_US:
        return ts / 1_000_000
    elif ts >= _TS_THRESHOLD_MS:
        return ts / 1_000
    return float(ts)


def timestamp_to_iso(ts: Union[int, float]) -> str:
    """
    将微信时间戳转为 ISO 格式字符串

    Args:
        ts: 微信原始时间戳

    Returns:
        ISO 格式时间字符串，转换失败返回原始输入字符串
    """
    try:
        seconds = normalize_timestamp(ts)
        return datetime.fromtimestamp(seconds).isoformat()
    except (OSError, ValueError, OverflowError) as e:
        log.warning("时间戳 %s 转换失败: %s", ts, e)
        return str(ts)


def decompress(content: bytes) -> str:
    """
    解压消息内容（ZSTD 压缩）

    微信使用 ZSTD 压缩部分消息内容（以 \\x28\\xb5\\x2f\\xfd 开头），
    未压缩时直接按 UTF-8 解码。

    Args:
        content: 原始字节内容

    Returns:
        解码后的文本字符串
    """
    if not content:
        return ""

    # ZSTD magic number: 0x28B52FFD
    if content[:4] == b'\x28\xb5\x2f\xfd':
        try:
            return zstd.decompress(content).decode('utf-8', errors='replace')
        except Exception as e:
            log.warning("ZSTD 解压失败 (%d bytes): %s", len(content), e)

    try:
        return content.decode('utf-8', errors='replace')
    except Exception as e:
        log.warning("字节解码失败 (%d bytes): %s", len(content), e)
        return str(content)
