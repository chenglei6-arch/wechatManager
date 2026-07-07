# wx-mcp: WeChat MCP Server

让 Claude 通过 **MCP (Model Context Protocol)** 读取和发送微信消息。

> ⚠️ **安全警告**
> 本工具通过扫描微信进程内存提取解密密钥，**可能触发微信的安全检测导致封号**。
> 解密后的数据库存储在系统临时目录，退出时自动清理。使用风险自负。

## 功能

| 功能 | 方式 | 说明 |
|------|------|------|
| 📋 列出联系人 | SQLite 读取 | 支持关键词搜索，过滤系统账号和公众号 |
| 💬 读取聊天记录 | SQLite 读取 | 自动处理 ZSTD 解压和时间戳转换 |
| 🕐 最近会话 | SQLite 读取 | 按时间排序的会话列表 |
| ✉️ 发送消息 | UI Automation | 通过 UIA 与微信窗口交互，不操作剪贴板 |
| 📨 批量发送 | UI Automation | 支持多联系人群发 |
| 📊 状态检查 | 综合检测 | 查看微信运行状态和解密情况 |

## 安装

```bash
# 克隆项目
git clone https://github.com/chenglei6-arch/wechatManager
cd wechatManager/wx-mcp

# 安装
pip install -e .
```

**环境要求：**
- Windows 10/11
- 微信 4.x PC 版已登录
- Python ≥ 3.10

## 配置 MCP

在 Claude 的 MCP 配置文件（`claude.json`）中添加：

```json
{
  "mcpServers": {
    "wechat": {
      "command": "python",
      "args": ["-m", "wx_mcp"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

或通过 Claude Code 添加：

```bash
claude mcp add wechat -- python -m wx_mcp
```

## 使用

```bash
python -m wx_mcp
```

### MCP 工具

| 工具 | 参数 | 说明 |
|------|------|------|
| `list_contacts` | `keyword?`, `limit=50` | 搜索/列出联系人 |
| `read_messages` | `talker`, `limit=30` | 读取聊天记录（支持 wxid 或昵称） |
| `get_recent_sessions` | `limit=20` | 最近会话列表 |
| `send_wechat_message` | `contact`, `message` | 发送文本消息 |
| `batch_send_messages` | `contacts[]`, `message` | 批量发送 |
| `wechat_status` | — | 查看运行状态 |

### MCP 资源

| URI | 说明 |
|-----|------|
| `wechat://contacts` | 联系人列表 (JSON) |
| `wechat://contacts/search/{keyword}` | 搜索联系人 (JSON) |
| `wechat://messages/{talker}` | 聊天记录 (JSON) |
| `wechat://status` | 运行状态 |

## 性能基准

实测数据（Windows 11, Python 3.14, WeChat 4.x, Intel i7）：

| 指标 | 数值 |
|------|------|
| 密钥提取（已登录微信） | <1s，平均 18 个密钥 |
| 数据库解密（contact + message + session） | <3s |
| 联系人查询 50 条 | ~60ms |
| 会话列表 20 条 | ~4ms |
| 消息读取 30 条 | ~72ms |
| 消息发送（UIA） | ~1–3s |

### Token 消耗参考

MCP 协议层响应数据量极轻，实测各工具的单次响应 Token 数：

| 场景 | Token 数 |
|------|---------|
| 会话初始化（一次性开销） | ~430 |
| `wechat_status` | ~27 |
| `list_contacts` (10) | ~72 |
| `list_contacts` (50) | ~361 |
| `get_recent_sessions` (10) | ~11 |
| `read_messages` (5) | ~25 |
| `read_messages` (30) | ~150 |

以上为 **服务器响应本身** 的 Token 消耗，不含用户输入和 AI 生成回复。详见 [`token-benchmark.html`](../token-benchmark.html)。

## 项目结构

```
wx-mcp/
├── src/wx_mcp/
│   ├── __init__.py       # 包信息
│   ├── __main__.py       # 入口: python -m wx_mcp
│   ├── server.py         # FastMCP Server — 工具 & 资源定义
│   ├── key.py            # 微信进程内存密钥提取
│   ├── decrypt.py        # SQLCipher 4 解密引擎
│   ├── crypto.py         # Windows DPAPI 加密
│   ├── reader.py         # 解密数据库读取（联系人/消息/会话）
│   ├── sender.py         # UI Automation 消息发送
│   └── utils.py          # 工具函数（时间戳转换/ZSTD 解压）
├── tests/                # 单元测试（94 个）
├── .github/workflows/    # CI
└── pyproject.toml         # 项目配置
```

## 技术原理

1. **密钥提取**: 使用 `pymem` 扫描 Weixin.exe 进程内存，搜索 SQLCipher 密钥模式
2. **数据库解密**: 实现 SQLCipher 4 的 AES-256-CBC 解密 + HMAC-SHA512 完整性验证
3. **数据读取**: 直接读取解密后的 SQLite 数据库，ZSTD 解压消息内容
4. **消息发送**: 使用 Windows UI Automation (uiautomation) 与微信 Qt 界面交互
5. **密钥存储**: Windows DPAPI (`CryptProtectData`) 加密，仅当前用户可解密

## 安全设计

- 🔑 密钥文件 `keys.json` 使用 **Windows DPAPI** 加密存储
- 🗑️ 解密后的数据库存储在**系统临时目录**，进程退出时自动清理
- 🔒 `.gitignore` 已配置屏蔽所有敏感文件
- 📡 纯本地运行，**无网络请求**

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
cd wx-mcp && pytest -v --tb=short

# 带覆盖率
pytest --cov=wx_mcp tests/
```

## 参考项目

- [Akasha-WeChat](https://github.com/alingalingling/Akasha-WeChat) — MCP Server 架构与实现参考
- 微信 SQLCipher 数据库解密方案参考了社区多个开源项目的思路与实践

## 免责声明

本项目仅供学习和研究使用。使用本项目产生的任何后果由使用者自行承担。
