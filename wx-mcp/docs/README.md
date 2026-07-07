# wx-mcp 项目文档

> 项目根目录：[wx-mcp/](../)

本目录包含 wx-mcp (WeChat MCP Server) 的完整技术文档，涵盖架构设计、解密原理、消息发送机制、MCP 协议集成等内容，方便后续维护和 fork。

## 文档清单

| 文件 | 内容 | 适用读者 |
|------|------|----------|
| [architecture.md](architecture.md) | 整体架构、模块划分、数据流 | 所有开发者 |
| [decryption-pipeline.md](decryption-pipeline.md) | 密钥提取 → SQLCipher 解密 → 数据读取完整流程 | 解密相关维护者 |
| [sender-mechanism.md](sender-mechanism.md) | UI Automation 消息发送原理、WeChat 4.x 控件树分析 | sender 模块维护者 |
| [mcp-integration.md](mcp-integration.md) | FastMCP 工具/资源定义、协议层设计 | server 模块维护者 |
| [project-structure.md](project-structure.md) | 目录结构、各文件职责、依赖关系 | 新入项目开发者 |
| [wechat-ui-tree.md](wechat-ui-tree.md) | WeChat 4.x PC 版 UI 控件树结构 | sender 调试者 |

## 技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| MCP 框架 | `fastmcp` (Python SDK) | 暴露工具和资源给 Claude |
| UI 自动化 | `uiautomation` (Windows UIA) | 与微信 Qt 界面交互发消息 |
| 进程内存 | `pymem` | 扫描 Weixin.exe 提取 SQLCipher 密钥 |
| 解密引擎 | `pycryptodome` (AES-CBC) | 实现 SQLCipher 4 解密 |
| 密钥保护 | Windows DPAPI (`crypt32.dll`) | 加密存储提取的密钥 |
| 数据读取 | `sqlite3` | 读取解密后的 SQLite 数据库 |
| 压缩处理 | `zstandard` | 解压 ZSTD 压缩的消息内容 |

## 快速导航

```
wx-mcp/src/wx_mcp/
├── server.py      →  docs/mcp-integration.md
├── key.py         →  docs/decryption-pipeline.md
├── decrypt.py     →  docs/decryption-pipeline.md
├── reader.py      →  docs/decryption-pipeline.md
├── sender.py      →  docs/sender-mechanism.md
├── crypto.py      →  docs/decryption-pipeline.md
└── utils.py       →  docs/decryption-pipeline.md
```
