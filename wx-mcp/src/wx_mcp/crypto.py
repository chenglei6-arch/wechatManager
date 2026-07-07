"""
Windows DPAPI 加密工具

使用 CryptProtectData / CryptUnprotectData 对敏感数据进行加密存储。
加密后的数据只能由同一 Windows 用户在同一台机器上解密。
"""
import ctypes
from ctypes import wintypes


CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ('cbData', wintypes.DWORD),
        ('pbData', ctypes.POINTER(ctypes.c_byte)),
    ]


_crypt32 = ctypes.windll.crypt32


def encrypt(data: bytes) -> bytes:
    """
    使用 DPAPI 加密数据

    Args:
        data: 明文数据

    Returns:
        密文（二进制 blob，只能由同一用户解密）
    """
    blob_in = DATA_BLOB(len(data), ctypes.cast(data, ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()
    if not _crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,     # szDataDescr
        None,     # optional entropy
        None,     # reserved
        None,     # prompt struct
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError(f"CryptProtectData 失败 (error={ctypes.get_last_error()})")

    result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    _crypt32.LocalFree(blob_out.pbData)
    return result


def decrypt(data: bytes) -> bytes:
    """
    使用 DPAPI 解密数据

    Args:
        data: DPAPI 加密的密文

    Returns:
        明文数据
    """
    blob_in = DATA_BLOB(len(data), ctypes.cast(data, ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()
    if not _crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,     # ppszDataDescr
        None,     # optional entropy
        None,     # reserved
        None,     # prompt struct
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError(f"CryptUnprotectData 失败 (error={ctypes.get_last_error()})")

    result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    _crypt32.LocalFree(blob_out.pbData)
    return result


def encrypt_to_file(data: bytes, filepath: str):
    """加密数据并写入文件"""
    encrypted = encrypt(data)
    with open(filepath, 'wb') as f:
        f.write(encrypted)


def decrypt_from_file(filepath: str) -> bytes:
    """从文件读取并解密"""
    with open(filepath, 'rb') as f:
        encrypted = f.read()
    return decrypt(encrypted)
