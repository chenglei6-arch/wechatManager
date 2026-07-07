# wechatManager — WeChat MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](wx-mcp/pyproject.toml)
[![CI](https://github.com/chenglei6-arch/wechatManager/actions/workflows/test.yml/badge.svg)](https://github.com/chenglei6-arch/wechatManager/actions/workflows/test.yml)

> 让 Claude 拥有读写微信消息能力的 MCP Server。**Windows Only**，依赖 WeChat 4.x。

---

## 快速开始

```bash
cd wx-mcp
pip install -e .
python -m wx_mcp
```

然后配置到 Claude Desktop / Claude Code 即可。

详细文档见 [wx-mcp/README.md](wx-mcp/README.md)。

## 项目结构

```
wechatManager/
├── README.md              # 本文件
├── wx-mcp/                # MCP Server 主项目
│   ├── src/wx_mcp/        # Python 源码
│   │   ├── server.py      # FastMCP 服务入口（工具 & 资源定义）
│   │   ├── key.py         # 从微信进程内存提取 SQLCipher 密钥
│   │   ├── decrypt.py     # SQLCipher 4 数据库解密引擎
│   │   ├── reader.py      # 解密后的数据库读取（联系人/消息/会话）
│   │   ├── sender.py      # UI Automation 消息发送
│   │   └── crypto.py      # Windows DPAPI 加密工具
│   ├── tests/             # 单元测试
│   ├── pyproject.toml     # 项目元数据 & 依赖
│   └── README.md          # 详细使用说明
└── .claude/               # Claude 配置
```

## 能力

| 能力 | 说明 |
|------|------|
| 📖 读取联系人 | 搜索、列出微信联系人 |
| 💬 读取消息 | 获取与任意联系人的聊天记录 |
 | 📋 查看会话 | 最近聊天列表 |
| ✉️ 发送消息 | 向任意联系人发送文本消息 |
| 📨 批量发送 | 群发消息到多个联系人 |
| 🔑 自动密钥提取 | 自动从微信进程提取解密密钥 |

## 工作原理

1. **密钥提取** — 通过 `pymem` 扫描 Weixin.exe 进程内存，提取 SQLCipher 4 的数据库加密密钥
2. **数据库解密** — AES-256-CBC + HMAC-SHA512 解密微信的 WCDB 数据库
3. **数据读取** — 从解密后的 SQLite 数据库中查询联系人、消息、会话（含 ZSTD 解压）
4. **消息发送** — 通过 Windows UI Automation (`uiautomation`) 操作微信界面

全程本地运行，不涉及任何网络 API 或逆向协议。

## 安全 & 隐私

- ✅ 一切在本地运行——数据不离机
- ✅ 密钥经 Windows DPAPI 加密存储（仅当前用户可解密）
- ✅ 解密后的数据库缓存在 `decrypted/`（已 gitignore）
- ✅ 通过本地 stdio 与 Claude 通信，无网络调用

## License

MIT
