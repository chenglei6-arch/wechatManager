# wx-mcp: WeChat MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)

A Model Context Protocol (MCP) server that gives Claude the ability to read and send WeChat messages. Works with **WeChat 4.x** on Windows.

> ⚠️ **Windows only** — relies on WeChat 4.x (Weixin.exe) and Windows window automation for sending messages.

---

## Features

| Capability | Description |
|-----------|-------------|
| ✅ **Read contacts** | List and search WeChat contacts by name or remark |
| ✅ **Read messages** | Retrieve chat history with any contact |
| ✅ **View sessions** | List recent chat sessions |
| ✅ **Send messages** | Send text messages to any contact |
| ✅ **Batch send** | Send the same message to multiple contacts at once |
| ✅ **Auto key extraction** | Automatically extracts decryption keys from WeChat process |

## How It Works

WeChat 4.x stores its data in **SQLCipher 4** encrypted SQLite databases. wx-mcp works entirely offline by:

1. **Key Extraction** — Reads the database encryption keys from Weixin.exe process memory via `pymem`
2. **Database Decryption** — Decrypts the SQLCipher 4 databases (AES-256-CBC, HMAC-SHA512 verification) to standard SQLite
3. **Data Reading** — Queries the decrypted databases for contacts, sessions, and message content (with ZSTD decompression)
4. **Message Sending** — Uses Windows window automation (`SendMessage`/`keybd_event`) to interact with the WeChat UI

No network API, no reverse-engineered protocol — purely local data decryption and UI automation.

## Prerequisites

- **Windows OS** (10 or 11)
- **WeChat 4.x** (Weixin.exe) installed and logged in
- **Python 3.10+**
- Administrator privileges (for reading WeChat process memory)

## Installation

```bash
# Clone the repository
git clone https://github.com/chenglei6-arch/wechatManager.git
cd wechatManager/wx-mcp

# Install dependencies
pip install mcp pycryptodome pymem psutil pyperclip zstandard
```

## Usage

### Run as standalone server

```bash
python -m wx_mcp.server
```

### Configure with Claude Desktop

Add to your `claude.json` (Claude Desktop settings):

```json
{
  "mcpServers": {
    "wechat": {
      "command": "python",
      "args": ["-m", "wx_mcp.server"],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### Configure with Claude Code

```bash
claude mcp add wechat -- python -m wx_mcp.server
```

## MCP Tools

| Tool | Arguments | Description |
|------|-----------|-------------|
| `list_contacts` | `keyword?` `limit=50` | Search and list contacts |
| `read_messages` | `talker` `limit=30` | Read chat history (supports name or wxid) |
| `get_recent_sessions` | `limit=20` | List recent conversations |
| `send_wechat_message` | `contact` `message` | Send a text message |
| `batch_send_messages` | `contacts[]` `message` | Send message to multiple contacts |
| `wechat_status` | — | Check WeChat connection status |

## MCP Resources

| Resource | Description |
|----------|-------------|
| `wechat://contacts` | Full contact list |
| `wechat://contacts/search/{keyword}` | Search results |
| `wechat://messages/{talker}` | Recent messages with a contact |
| `wechat://status` | Server status |

## Project Structure

```
wx-mcp/
├── pyproject.toml          # Python project metadata
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── .gitignore              # Ignore rules (keys, decrypted data, etc.)
│
├── keys.json               # ⚠️ Auto-generated decryption keys (local only)
├── decrypted/              # ⚠️ Auto-generated decrypted databases (local only)
│
└── src/wx_mcp/
    ├── __init__.py          # Package init
    ├── __main__.py          # CLI entry: python -m wx_mcp
    ├── server.py            # FastMCP server — tools & resources
    ├── key.py               # Key extraction from WeChat process memory
    ├── decrypt.py           # SQLCipher 4 decryption engine
    ├── reader.py            # Contacts, sessions, message reader
    └── sender.py            # Window automation message sender
```

### Module Overview

| Module | Role |
|--------|------|
| `server.py` | FastMCP server, defines all tools and resources |
| `key.py` | Scans Weixin.exe memory for SQLCipher key patterns |
| `decrypt.py` | Decrypts SQLCipher 4 pages (AES-256-CBC + HMAC-SHA512) |
| `reader.py` | Reads from decrypted SQLite databases |
| `sender.py` | Sends messages via Windows window automation |

## Security & Privacy

**Your privacy is the top priority.** By design:

- ✅ **Everything runs locally** — no data leaves your machine
- ✅ **Keys stay on disk** — extracted keys are cached in `keys.json` (gitignored)
- ✅ **Decrypted DBs stay local** — cached in `decrypted/` (gitignored)
- ✅ **No network calls** — all decryption and reading is offline
- ✅ **No uploads** — the server communicates with Claude via local stdio

The `.gitignore` ensures `keys.json` and `decrypted/` are never committed to git.

## Why This Approach?

WeChat 4.x stores data in **WCDB** (WeChat Core DataBase), which uses SQLCipher 4 for encryption. Unlike the mobile versions, the Windows desktop client keeps the encryption keys in its process memory — making local decryption possible.

For sending, WeChat 4.x's UI is built with Qt, not Chromium, which means standard Windows window messages work reliably for automation.

## License

MIT
