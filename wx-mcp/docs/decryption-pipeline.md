# 解密流程 — 从内存到明文

> 本文档详细说明从微信进程内存提取密钥到最终读取聊天记录的全流程。
> 涉及文件：`key.py` → `crypto.py` → `decrypt.py` → `reader.py`

## 整体流程

```
Weixin.exe 进程内存
    │
    │  pymem 进程附加 + 内存扫描
    ▼
┌──────────────────┐
│  key.py          │  提取 SQLCipher 4 密钥
│  1. find_pid()   │  页密钥(32字节) × 18 页
│  2. extract()    │
│  3. save_keys()  │  ── DPAPI 加密 → keys.json
└──────┬───────────┘
       │  load_keys()
       ▼
┌──────────────────┐
│  decrypt.py      │  解密 SQLite 数据库
│  1. decrypt_db() │  AES-256-CBC + HMAC-SHA512
│  2. verify()     │  验证 SQLite Header
│  3. decrypt_page │  逐页解密
└──────┬───────────┘
       │  解密后 .db 文件
       ▼
┌──────────────────┐
│  reader.py       │  读取解密后的 SQLite
│  1. 连接         │  WAL 模式 + 连接池
│  2. 查询         │  LIKE 搜索 + 分页
│  3. 解压         │  ZSTD 解压消息内容
└──────┬───────────┘
       │  dict 列表
       ▼
  server.py → MCP Client
```

## 1. 密钥提取 (`key.py`)

### 原理

微信 PC 版使用 SQLCipher 4 加密本地 SQLite 数据库。SQLCipher 4 的加密密钥（32 字节，AES-256 密钥）在微信进程运行时必然存在于其内存空间中。

扫描策略：SQLCipher 4 密钥前后有固定的 HMAC 盐值（`0x3A` XOR 模式），形成可识别的内存指纹。

### 步骤

1. **`find_wechat_pid()`** — 通过 `psutil` 遍历进程，查找 `Weixin.exe`
2. **`extract_keys()`** — 使用 `pymem` 附加进程，扫描内存页，匹配密钥模式
3. **`save_keys()`** — 将提取到的密钥用 DPAPI 加密后写入 `keys.json`

```python
# 简化的扫描逻辑
wechat_pid = find_wechat_pid()          # psutil 查进程
pm = pymem.Pymem("Weixin.exe")           # 附加进程
for address in scan_memory(pm, pattern): # 匹配指纹
    key = pm.read_bytes(address, 32)     # 读 32 字节密钥
    keys.append(key)
save_keys(keys, path)                    # DPAPI 加密保存
```

### 密钥数量

实测提取到大约 **18 个密钥**，其中只有部分是对应的数据库密钥。`decrypt.py` 会逐个尝试，通过 HMAC 验证来确定正确的密钥。

## 2. 密钥存储 (`crypto.py`)

为防止密钥以明文形式保存在磁盘上，使用 Windows DPAPI 加密：

```python
# DPAPI 加密（仅当前 Windows 用户可解密）
import ctypes
from ctypes import wintypes

# CryptProtectData — 加密
# CryptUnprotectData — 解密
# 不需要密码参数，自动绑定当前 Windows 登录会话
```

DPAPI 的优势：不需要管理加密密码，系统自动绑定当前用户。其他 Windows 用户（或同一用户的其他设备）无法解密。

### 文件格式

`keys.json` 使用魔数 `WXMC`（4 字节）标识文件类型，后接 DPAPI 加密的 BLOB。

## 3. 数据库解密 (`decrypt.py`)

### SQLCipher 4 页面结构

SQLCipher 将 SQLite 数据库划分为 4096 字节的页面，每页独立加密：

```
┌──────────────────────────────────────────────────┐
│  Page 1 (首页)：                                    │
│  ┌──────┬──────────┬──────┬──────────────────┐    │
│  │ Salt │ Ciphered  │ IV   │ HMAC-SHA512      │    │
│  │ 16B  │ Plaintext │ 16B  │ 64B              │    │
│  │      │ (4016B)   │      │                  │    │
│  └──────┴──────────┴──────┴──────────────────┘    │
│                                                     │
│  Page N (非首页)：                                  │
│  ┌──────────────────┬──────┬──────────────────┐    │
│  │ Ciphered Text    │ IV   │ Padding*         │    │
│  │ 4016B            │ 16B  │ 64B              │    │
│  └──────────────────┴──────┴──────────────────┘    │
└──────────────────────────────────────────────────┘
```

- **加密**: AES-256-CBC
- **密钥派生**: PBKDF2-HMAC-SHA512, 迭代 2 次（SQLCipher 4 默认）
- **完整性**: HMAC-SHA512（首页必须验证；非首页无 HMAC）
- **页面大小**: 4096 字节（4 KiB）

### 解密核心代码逻辑

```python
def decrypt_page(enc_key, page_data, pgno):
    if pgno == 1:
        # 首页: 前 16 字节是 salt
        salt = page_data[:16]
        encrypted = page_data[16:4032]   # 4016 字节密文
        iv = page_data[4032:4048]
        hmac_stored = page_data[4048:4112]
        
        # 派生 MAC 密钥（salt XOR 0x3a）
        mac_key = derive_mac_key(enc_key, salt)
        # 验证 HMAC
        if not verify_hmac(mac_key, encrypted, iv, pgno, hmac_stored):
            return None  # 密钥错误或数据损坏
        
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        return cipher.decrypt(encrypted)
    else:
        # 非首页: IV = pgno (4字节) + 0x00 * 12
        iv = struct.pack('<I', pgno) + b'\x00' * 12
        encrypted = page_data[:4016]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        return cipher.decrypt(encrypted)
```

### 密钥派生

```python
def derive_mac_key(enc_key, salt):
    # SQLCipher 4: salt 每个字节 XOR 0x3a
    xored = bytes(b ^ 0x3a for b in salt)
    # PBKDF2-HMAC-SHA512, 2 轮迭代
    return pbkdf2_hmac('sha512', enc_key, xored, 2, dklen=32)
```

### `decrypt_database()` 工作流程

1. 读取加密数据库文件
2. 从第一页获取 salt（前 16 字节）
3. 遍历所有密钥，对第一页尝试解密并验证 HMAC
4. 找到匹配密钥后，逐页解密所有页面
5. 写入临时的解密后 .db 文件（系统临时目录）
6. 返回解密文件路径

## 4. 数据读取 (`reader.py`)

### 连接池设计

```python
class WeChatReader:
    _connections: dict[str, sqlite3.Connection]
    _lock: threading.Lock
    
    def _get_connection(self, db_path):
        # 连接池缓存，避免重复建立连接
        # WAL 模式提升并发读取性能
```

- 使用 `dict` 缓存数据库连接，按路径复用
- `threading.Lock` 保证线程安全
- 开启 WAL 模式（`PRAGMA journal_mode=WAL`）提升并发性能

### 消息解压

微信使用 ZSTD 压缩部分消息内容（以 `0x28B52FFD` 魔数开头）：

```python
def decompress(content):
    if not content:
        return ""
    if isinstance(content, str):
        return content  # SQLite 可能返回 str
    if content[:4] == b'\x28\xb5\x2f\xfd':  # ZSTD magic
        return zstd.decompress(content)
    return content.decode('utf-8', errors='replace')
```

### 主要查询

| 功能 | SQL | 说明 |
|------|-----|------|
| 联系人搜索 | `SELECT * FROM Contact WHERE ... LIKE` | 关键词过滤，排除公众号/系统账号 |
| 消息读取 | `SELECT ... FROM MSG WHERE talkerId = ?` | strftime 时间格式化，ZSTD 解压 |
| 最近会话 | `SELECT ... FROM Session ORDER BY time` | 去重，取最近 N 条 |

## 常见问题

### Q: 密钥提取失败怎么办？
- 确认微信已登录且运行中
- 以管理员权限运行（某些系统需要）
- 检查微信版本更新（内存指纹可能变化）

### Q: 数据库解密后乱码？
- 可能是微信版本升级导致加密算法变化
- 尝试清除 `keys.json` 重新提取密钥

### Q: 找不到微信进程？
- 微信进程名为 `Weixin.exe`（不是 `Wechat.exe`）
- 确认微信已完全启动（登录完成）
