# 整体架构设计

> 本文档描述 wx-mcp 的整体架构、模块职责和数据流。

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                     Claude (Desktop / Code)              │
│                      MCP Client                           │
└──────────────────────┬──────────────────────────────────┘
                       │ stdio JSON-RPC
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   wx-mcp (FastMCP Server)                 │
│                                                           │
│  ┌─────────────┐  ┌──────────┐  ┌─────────────────────┐ │
│  │  Tools       │  │ Resources│  │  Lifecycle Hooks     │ │
│  │  (6个)       │  │ (4个)    │  │  (init/cleanup)      │ │
│  └──────┬───────┘  └────┬─────┘  └─────────────────────┘ │
│         │               │                                  │
│         ▼               ▼                                  │
│  ┌──────────────────────────────────────────────────────┐ │
│  │                   Server State                         │ │
│  │  (wechat_running, keys_loaded, decrypted_dbs)          │ │
│  └──────┬──────────────────────┬────────────────────────┘ │
│         │                      │                            │
│  ┌──────▼──────┐    ┌─────────▼─────────┐                 │
│  │  Reader     │    │  Sender            │                 │
│  │  (读数据)   │    │  (发消息/UIA)      │                 │
│  └──────┬──────┘    └───────────────────┘                 │
│         │                                                    │
│  ┌──────▼──────┐                                           │
│  │  Decrypt    │                                           │
│  │  (解密)     │                                           │
│  └──────┬──────┘                                           │
│         │                                                    │
│  ┌──────▼──────┐                                           │
│  │  Key        │                                           │
│  │  (密钥提取) │                                           │
│  └─────────────┘                                           │
└─────────────────────────────────────────────────────────┘
```

## 模块依赖关系

```
server.py  ←─── 工具/资源入口，依赖所有下层模块
  ├── key.py      ── 进程内存扫描，提取 SQLCipher 密钥
  ├── crypto.py   ── DPAPI 加密/解密密钥文件
  ├── decrypt.py  ── SQLCipher 4 页面级解密
  ├── reader.py   ── 解密后 SQLite 数据库读取
  ├── sender.py   ── UI Automation 消息发送
  └── utils.py    ── 工具函数（供 reader.py 使用）
```

## 数据流

### 读消息流程

```
Weixin.exe 进程内存
    │ pymem 扫描
    ▼
key.py: 提取 18 个 SQLCipher 密钥
    │ DPAPI 加密存储 (keys.json)
    ▼
decrypt.py: 解密 3 个 SQLite 数据库
    ├── contact.db  (联系人)
    ├── message.db  (聊天记录)
    └── session.db  (最近会话)
    │
    ▼
reader.py: 连接解密后的数据库
    │ LIKE 查询 / 分页读取
    ▼
server.py → JSON → MCP Client → Claude
```

### 发消息流程

```
server.py: send_wechat_message(contact, message)
    │
    ▼
sender.py:
    1. FindWindow("微信") → 微信主窗口
    2. _search_contact() → 搜索框输入联系人名
    3. _find_contact_in_children() → 确认搜索结果
    4. _open_chat() → 点击联系人打开聊天
    5. _find_input_area() → 定位聊天输入框
    6. ValuePattern.SetValue() → 输入消息
    7. _find_send_button() → 找发送按钮
    8. InvokePattern.Invoke() / SendKeys Enter → 发送
    9. 可选最小化窗口
```

## 核心设计决策

### 1. 为什么不使用微信官方 API？
微信官方不提供 PC 端的公开 API。社区方案通常分三类：

| 方案 | 优缺点 |
|------|--------|
| **内存注入/HOOK** | 稳定但容易被检测封号 |
| **逆向协议** | 功能全但维护成本极高，需对抗加密协议 |
| **UI Automation (本项目)** | 不需要逆向协议、不注入进程，但依赖 UI 布局，微信版本更新可能失效 |

本项目选择 **UI Automation** + **数据库直读** 的组合方案：
- 读数据：解密 SQLite 数据库直接读取，速度快且不干扰微信运行
- 写数据（发消息）：通过 UIA 模拟用户操作，不开额外风险

### 2. 为什么不操作剪贴板？
旧版微信机器人常通过 `SetClipboard` + `SendKeys ^V` 粘贴消息。这种方式：
- 会破坏用户当前的剪贴板内容
- 被安全软件监控剪贴板操作
- 微信可能检测到非人类粘贴速度

本项目全程使用 `ValuePattern.SetValue()` 输入文本，不碰剪贴板。

### 3. 为什么不强制激活窗口？
旧版方案常 `SetForegroundWindow` 抢焦点，干扰用户正常使用。本项目优先：
- `ValuePattern` → 输入文本（不抢焦点）
- `InvokePattern` → 点击按钮（不抢焦点）
- 仅当上述 UIA 接口失效时才 fallback 到 `Click` / `SendKeys`
