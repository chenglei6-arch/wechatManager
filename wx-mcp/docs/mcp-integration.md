# MCP 协议集成

> 本文档说明如何通过 FastMCP 框架将 WeChat 能力暴露为 MCP 工具和资源。
> 涉及文件：`server.py`

## MCP 协议简介

**MCP (Model Context Protocol)** 是一种开放协议，允许 AI 应用（如 Claude）通过标准化的接口与外部工具和数据源交互。类似于"AI 应用的 USB 协议"。

本项目使用 `fastmcp`（FastMCP）Python SDK 实现 MCP Server，通过 stdio 传输层与 Claude 通信。

## 通信架构

```
Claude Desktop / Claude Code
        │
        │ MCP Protocol (JSON-RPC over stdio)
        │
        ▼
┌─────────────────────────────┐
│     fastmcp Server          │
│                             │
│   ┌───────────────────┐    │
│   │ MCP 协议层         │    │  ← fastmcp 自动处理
│   │ - JSON-RPC 2.0    │    │
│   │ - 生命周期管理    │    │
│   │ - 错误处理        │    │
│   └───────────────────┘    │
│                             │
│   ┌───────────────────┐    │
│   │ 业务逻辑层         │    │  ← server.py 自定义
│   │  - 工具 (Tool)    │    │
│   │  - 资源 (Resource)│    │
│   │  - 生命周期钩子   │    │
│   └───────────────────┘    │
│                             │
│   ┌───────────────────┐    │
│   │ 数据访问层         │    │  ← key.py → decrypt.py → reader.py
│   │  - 密钥提取       │    │  ← sender.py
│   │  - 数据库解密     │    │
│   │  - 消息发送       │    │
│   └───────────────────┘    │
└─────────────────────────────┘
```

## Server 初始化

```python
app = FastMCP(
    "WeChat MCP Server",
    description="让 Claude 读取和发送微信消息",
)
```

### 生命周期

```python
@app.startup()
async def startup():
    """MCP Server 启动时自动执行"""
    # 1. 检查微信是否运行
    # 2. 加载/提取密钥
    # 3. 解密数据库
    # 4. 初始化 reader
    ...

@app.shutdown()
async def shutdown():
    """MCP Server 关闭时自动清理"""
    # 删除临时解密文件
    # 关闭数据库连接
    ...
```

## 工具定义 (Tools)

### `list_contacts`

搜索或列出微信联系人。

```python
@app.tool()
def list_contacts(keyword: str = "", limit: int = 50) -> str:
    """搜索联系人"""
    reader = get_reader()
    contacts = reader.search_contacts(keyword, limit)
    return json.dumps(contacts, ensure_ascii=False)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `keyword` | string | "" | 搜索关键词，为空则返回全部 |
| `limit` | integer | 50 | 最大返回数量 |

### `read_messages`

读取与某联系人的聊天记录。

```python
@app.tool()
def read_messages(talker: str, limit: int = 30) -> str:
    """读取聊天记录"""
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `talker` | string | — | 联系人 wxid 或昵称 |
| `limit` | integer | 30 | 消息数量上限 |

### `get_recent_sessions`

获取最近会话列表。

```python
@app.tool()
def get_recent_sessions(limit: int = 20) -> str:
    """最近会话列表"""
```

### `send_wechat_message`

发送文本消息。

```python
@app.tool()
def send_wechat_message(contact: str, message: str) -> str:
    """发送消息"""
```

### `batch_send_messages`

批量发送消息。

```python
@app.tool()
def batch_send_messages(contacts: list[str], message: str) -> str:
    """批量发送"""
```

### `wechat_status`

检查微信运行状态。

```python
@app.tool()
def wechat_status() -> str:
    """查看运行状态"""
```

## 资源定义 (Resources)

资源通过 `wechat://` URI scheme 暴露：

| URI | 返回内容 | 对应工具 |
|-----|----------|----------|
| `wechat://contacts` | 所有联系人 JSON | `list_contacts()` |
| `wechat://contacts/search/{keyword}` | 搜索联系人 JSON | `list_contacts(keyword)` |
| `wechat://messages/{talker}` | 聊天记录 JSON | `read_messages(talker)` |
| `wechat://status` | 运行状态 | `wechat_status()` |

```python
@app.resource("wechat://contacts")
def get_contacts() -> str:
    """联系人列表资源"""
    return list_contacts()

@app.resource("wechat://contacts/search/{keyword}")
def search_contacts_resource(keyword: str) -> str:
    """搜索联系人资源"""
    return list_contacts(keyword=keyword)
```

## 状态管理

`ServerState` 类管理全局状态：

```python
@dataclass
class ServerState:
    wechat_running: bool = False    # 微信是否在运行
    keys_loaded: bool = False       # 密钥是否已加载
    dbs_decrypted: bool = False     # 数据库是否已解密
    error: Optional[str] = None     # 错误信息
```

状态在 `wechat_status` 工具中返回，帮助 Claude 判断是否可以使用读写功能。

## 配置方式

### Claude Desktop / Claude Code

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

### Claude Code CLI

```bash
claude mcp add wechat -- python -m wx_mcp
```

## FastMCP vs 原生 MCP SDK

本项目选择 FastMCP 而非原生 `mcp` SDK，原因：

| 特性 | FastMCP | 原生 MCP SDK |
|------|---------|-------------|
| 工具装饰器 | `@app.tool()` | 需手动构建 Tool 对象 |
| 资源装饰器 | `@app.resource()` | 需手动处理 URI 路由 |
| 生命周期 | `@app.startup()` / `@app.shutdown()` | 需手动处理 |
| 错误处理 | 自动捕获异常返回错误 JSON | 需手动 try/except |
| JSON-RPC | 自动序列化/反序列化 | 需手动处理 |
| 代码量 | 少 60%+ | 较多样板代码 |

## Token 消耗

MCP 协议本身有少量开销，实测数据：

| 阶段 | Token 数 | 说明 |
|------|---------|------|
| 初始化 (Init) | ~430 | 一次性，建立连接时消耗 |
| 工具调用响应 | 11-361 | 每个工具返回数据量不同 |
| 资源读取 | 同对应工具 | 资源本质上是工具调用的包装 |

详细数据见 `token-benchmark.html`。
