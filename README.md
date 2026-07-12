# wechatManager — WeChat MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](wx-mcp/pyproject.toml)
[![CI](https://github.com/chenglei6-arch/wechatManager/actions/workflows/test.yml/badge.svg)](https://github.com/chenglei6-arch/wechatManager/actions/workflows/test.yml)

> 让 Claude 拥有读写微信消息能力的 MCP Server。**Windows Only**，依赖 WeChat 4.x。

全程本地运行，不涉及任何网络 API 或逆向协议。

你还在为每天要处理大量繁杂冗余的微信消息而发愁吗？这个mcp能让你的 AI 助手顺利连上微信。帮你整理发送消息。
可惜的是发送消息功能非常粗糙，如果有更好的方案请提供给我。

---

## 快速开始

```bash
cd wx-mcp
pip install -e .
python -m wx_mcp
```

然后配置到 Claude Desktop / Claude Code 即可。

## 文档

详细使用说明、功能列表、技术原理、安全设计、开发指南 → **[wx-mcp/README.md](wx-mcp/README.md)**

## 性能概况

| 操作 | 耗时 | 响应 Token 数 |
|------|------|-------------|
| 会话初始化（首次连接） | <1ms | ~430 |
| `wechat_status` | <1ms | ~27 |
| `list_contacts` (50 个) | ~60ms | ~361 |
| `get_recent_sessions` (20 个) | ~4ms | ~11 |
| `read_messages` (30 条) | ~72ms | ~150 |
| 典型完整工作流（初始化 + 5 次调用） | <200ms | ~1,940 |

> 详细性能数据和图表见 [`token-benchmark.html`](token-benchmark.html)。

## 项目结构

```
wechatManager/
├── LICENSE                  # MIT
├── wx-mcp/                  # MCP Server 主项目（详见 wx-mcp/README）
│   ├── src/wx_mcp/          # Python 源码
│   │   ├── server.py        # FastMCP 服务入口（工具 & 资源定义）
│   │   ├── key.py           # 从微信进程内存提取 SQLCipher 密钥
│   │   ├── decrypt.py       # SQLCipher 4 数据库解密引擎
│   │   ├── reader.py        # 解密后的数据库读取（联系人/消息/会话）
│   │   ├── sender.py        # UI Automation 消息发送
│   │   ├── crypto.py        # Windows DPAPI 加密工具
│   │   └── utils.py         # 工具函数（时间戳转换/ZSTD 解压）
│   ├── tests/               # 单元测试
│   └── pyproject.toml       # 项目元数据 & 依赖
└── .claude/                 # Claude 配置
```

## 参考项目

- [Akasha-WeChat](https://github.com/alingalingling/Akasha-WeChat) — MCP Server 架构参考
- 微信聊天记录解密方案参考了社区多个开源项目的实现

## License

[MIT](LICENSE)
