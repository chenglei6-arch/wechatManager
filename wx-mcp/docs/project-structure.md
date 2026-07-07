# 项目结构与文件职责

> 本文档详细说明 wx-mcp 项目的目录结构、每个文件的职责和依赖关系。

## 目录树

```
wx-mcp/
├── CHANGELOG.md                   # 变更日志
├── README.md                      # 项目说明文档
├── pyproject.toml                 # 项目元数据、依赖、构建配置
│
├── src/wx_mcp/                   # 主源码目录
│   ├── __init__.py               # 包初始化 & 版本号
│   ├── __main__.py               # CLI 入口: python -m wx_mcp
│   ├── server.py                 # FastMCP Server (工具/资源定义)
│   ├── key.py                    # WeChat 进程内存密钥提取
│   ├── crypto.py                 # Windows DPAPI 加密/解密
│   ├── decrypt.py                # SQLCipher 4 数据库解密引擎
│   ├── reader.py                 # 解密后的 SQLite 数据库读取
│   ├── sender.py                 # UI Automation 消息发送
│   └── utils.py                  # 工具函数 (时间戳/ZSTD解压)
│
├── tests/                        # 单元测试
│   ├── test_crypto.py
│   ├── test_decrypt.py
│   ├── test_key.py
│   ├── test_reader.py
│   ├── test_sender.py
│   ├── test_server.py
│   └── test_utils.py
│
├── docs/                         # 项目文档 (本文档所在目录)
│   ├── README.md                 # 文档索引
│   ├── architecture.md           # 整体架构设计
│   ├── decryption-pipeline.md    # 解密流程
│   ├── sender-mechanism.md       # 消息发送原理
│   ├── mcp-integration.md        # MCP 协议集成
│   ├── project-structure.md      # 项目结构 (本文件)
│   └── wechat-ui-tree.md         # WeChat 4.x UI 控件树
│
├── .github/workflows/            # CI 配置
│   └── test.yml                  # GitHub Actions (lint + test)
│
└── token-benchmark.html          # Token 消耗可视化图表
```

## 各文件详细说明

### 核心源码 (`src/wx_mcp/`)

| 文件 | 职责 | 依赖 | 行数 |
|------|------|------|------|
| `__init__.py` | 包标识、`__version__` 导出 | 无 | ~3 |
| `__main__.py` | CLI 入口：支持 `--version`、`--debug` | `server.py` | ~30 |
| `server.py` | FastMCP Server：6 个工具 + 4 个资源 + 生命周期 | 所有下层模块 | ~180 |
| `key.py` | 微信进程内存扫描提取 SQLCipher 密钥 | `crypto.py`, `pymem`, `psutil` | ~150 |
| `crypto.py` | Windows DPAPI 加密/解密 (ctypes 封装) | 无 | ~80 |
| `decrypt.py` | SQLCipher 4 页面解密、HMAC 验证、完整性校验 | `pycryptodome` | ~200 |
| `reader.py` | 解密后 SQLite 读取、连接池、WAL 模式 | `decrypt.py` (间接) | ~200 |
| `sender.py` | UI Automation 消息发送：搜索→打开→输入→发送 | `uiautomation` | ~395 |
| `utils.py` | 时间戳归一化、ISO 格式化、ZSTD 解压 | `zstandard` | ~100 |

### 测试 (`tests/`)

| 文件 | 测试目标 | 测试数量 |
|------|----------|----------|
| `test_crypto.py` | DPAPI 加解密 | 6 |
| `test_decrypt.py` | SQLCipher 页面解密、HMAC 验证、流程测试 | 13 |
| `test_key.py` | 密钥提取 (mock pymem) | 8 |
| `test_reader.py` | 数据库读取、连接池 (mock sqlite3) | 17 |
| `test_sender.py` | 发送流程、控件查找、容错 (mock uiautomation) | 39 |
| `test_server.py` | MCP 工具/资源调用 (mock 下层模块) | 25 |
| `test_utils.py` | 时间戳、ZSTD 解压 | 12 |
| | **总计** | **120** |

### 测试策略

- **Mock 外部依赖**：所有涉及微信进程、UI 窗口、数据库的测试均使用 mock 对象
- **纯逻辑单元测试**：解密引擎使用构造的测试向量，不依赖真实微信环境
- **测试即文档**：测试用例如 `test_sender.py` 中的控件查找测试，也反映了 WeChat 4.x 的 UI 结构

## 数据流依赖

```
server.py  ←─── 用户请求入口
    │
    ├── key.py ──────── crypto.py     （读：密钥提取 + DPAPI 存储）
    │
    ├── decrypt.py ──── key.py        （读：用提取的密钥解密数据库）
    │
    ├── reader.py ───── utils.py      （读：从解密数据库查询数据）
    │
    └── sender.py                     （写：发送消息不依赖解密模块）
```

## 可信计算基 (TCB)

安全敏感的代码路径：

```
密钥提取路径：    key.py → crypto.py
解密核心路径：    decrypt.py
数据读取路径：    reader.py → utils.py
```

这些代码涉及进程内存扫描和加密解密，修改时需特别谨慎。DPAPI 加密确保密钥文件在磁盘上不是明文。

## 扩展指南

### 添加新工具

1. 在 `server.py` 中定义 `@app.tool()` 函数
2. 如果需要新数据，在 `reader.py` 中添加查询方法
3. 如果需要新 UI 操作，在 `sender.py` 中添加对应函数
4. 在 `README.md` 和 `docs/` 更新文档
5. 在 `tests/test_server.py` 添加测试用例

### 适配新版微信

主要影响 `sender.py`（UI Automation）和 `decrypt.py`（加密算法）：

- **UI 变化**：更新 `wechat-ui-tree.md` 中的控件结构，调整 `_SEARCH_DEPTH` 和查找策略
- **加密变化**：检查 SQLCipher 版本，更新解密参数
