# Changelog

## [0.1.0] — 2026-07-08

### Added

- 初始版本 MCP Server，支持 6 个工具和 4 个资源
- `list_contacts` — 搜索/列出联系人（支持关键词过滤）
- `read_messages` — 读取聊天记录（支持 wxid 或昵称）
- `get_recent_sessions` — 最近会话列表
- `send_wechat_message` — 通过 UI Automation 发送文本消息
- `batch_send_messages` — 多联系人群发
- `wechat_status` — 微信运行状态和解密状态检查
- Windows DPAPI 加密密钥存储
- SQLCipher 4 数据库解密（AES-256-CBC + HMAC-SHA512）

### Fixed

- **消息发送到搜索栏** — `_find_input_area` 重写，排除 Name="搜索" 的搜索框，定位聊天输入框
- **找不到搜索框** — `_SEARCH_DEPTH` 从 8 提升至 20，适配 WeChat 4.x 深 Qt 嵌套
- **联系人匹配失败** — 改用 `SubName`/`contains` 包含匹配替代精确 Name 匹配
- **`str.decode` 崩溃** — `decompress()` 增加 `isinstance(content, str)` 检查
- **WindowPattern API 兼容** — 多版本 uiautomation 属性名/方法名逐级降级处理

### Changed

- sender 模块全面重构：不抢焦点、不碰剪贴板、无硬编码坐标
- 搜索结果采用动态轮询等待替代固定 `sleep`
- 批量发送仅最后一轮最小化窗口
