# 消息发送原理 — UI Automation

> 本文档详细说明通过 Windows UI Automation 与 WeChat 4.x 交互发送消息的实现细节。
> 涉及文件：`sender.py`

## 概述

`sender.py` 使用 `uiautomation` 库（Python 封装的 Windows UI Automation API）与微信 PC 版的 Qt 界面交互，模拟用户操作完成消息发送。

**核心原则：**
- ✅ 不抢焦点 — 优先 UIA 模式接口
- ✅ 不碰剪贴板 — `ValuePattern.SetValue()` 直接输入
- ✅ 无硬编码坐标 — 通过控件树定位

## WeChat 4.x 控件树

WeChat 4.x 基于 Qt（QWidget/QML），UI Automation 控件树如下：

```
WindowControl(Name="微信", Depth=0)
├── TitleBar
├── MainTabBar                              # 左侧导航栏
├── XSearchField (Depth=3~5)               # 搜索框区域
│   └── XValidatorTextEdit(Name="搜索")     # 实际 EditControl (Depth=12+)
├── ChatSessionList (Depth=4~6)            # 会话列表
│   └── ListItemControl(SubName="联系人")   # 每个会话项
├── ChatPanel                                # 聊天面板
│   ├── ChatHistoryList                     # 消息历史区域
│   │   └── ListItemControl                 # 每条消息
│   ├── ChatInputField(Name="联系人")       # 输入框 (EditControl) (Depth=14+)
│   └── XOutlineButton(Name="发送")         # 发送按钮 (Depth=12+)
└── StatusBar
```

### 关键控件属性

| 控件 | ControlType | Name | 深度 | UIA 模式 |
|------|------------|------|------|----------|
| 搜索框输入 | EditControl | "搜索" | ~12+ | ValuePattern |
| 聊天输入框 | EditControl | 联系人名称 | ~14+ | ValuePattern |
| 发送按钮 | Button | "发送" | ~12+ | InvokePattern |
| 联系人列表项 | ListItem | 含额外预览文本 | ~8+ | InvokePattern |

## 发送流程详解

### 第1步：查找微信窗口 (`_find_window`)

```python
wechat = auto.WindowControl(Name='微信', searchDepth=1)
```

- 通过窗口标题 `"微信"` 定位主窗口
- 带重试机制（默认 2 次），应对微信启动未完全加载的情况
- 设置 `searchDepth=1` 限制搜索深度，避免误匹配子窗口

### 第2步：恢复窗口 (`_ensure_window_restored`)

```python
pattern = wechat.GetWindowPattern()
if pattern.WindowVisualState == Minimized:
    pattern.SetVisualState(Normal)
```

- 检测窗口是否最小化
- 最小化时需调用 `SetVisualState` 恢复
- 兼容不同 `uiautomation` 版本的 API 差异（`WindowVisualState` vs `CurrentVisualState`，`SetVisualState` vs `SetWindowVisualState`）

### 第3步：搜索联系人 (`_search_contact`)

```python
search = wechat.EditControl(searchDepth=_SEARCH_DEPTH)  # _SEARCH_DEPTH = 20
```

- 在微信主窗口内搜索 `EditControl`
- 使用 `_SEARCH_DEPTH = 20`：WeChat 4.x 基于 Qt，控件嵌套深度远超传统 Win32 应用（可达 14+ 层），常规设置（5-8）无法找到深层控件
- 优先使用 `ValuePattern.SetValue(chat_name)` 输入搜索词
- 备选：`Click()` → `SendKeys('{Ctrl}a')` → `SendKeys(chat_name)`

### 第4步：确认搜索结果 (`_find_contact_in_children`)

```python
for item in list_control.GetChildren():
    if chat_name in item.Name:
        return True  # 匹配成功
```

WeChat 4.x 的列表项 `Name` 包含联系人名 + 最近消息预览（如 `"张三 好的明天见"`），因此用 **包含匹配** 而非精确匹配：

| 匹配方式 | 示例 | 结果 |
|----------|------|------|
| 精确 Name="张三" | Name="张三 好的明天见" | ❌ 不匹配 |
| contains "张三" | "张三" in "张三 好的明天见" | ✅ 匹配 |

### 第5步：打开聊天 (`_open_chat`)

```python
target = wechat.ListItemControl(SubName=chat_name, searchDepth=_SEARCH_DEPTH)
target.Click()
```

- 使用 `SubName` 参数（内部做包含匹配而非精确匹配）
- 备选：直接 `SendKeys('{Enter}')`（搜索结果默认选中第一个）

### 第6步：定位输入框 (`_find_input_area`)

**这是最容易出错的环节**，因为微信窗口中有两个 `EditControl`：

```
EditControl(Name="搜索")          ← 搜索框（需要排除）
EditControl(Name="文件传输助手")   ← 聊天输入框（目标）
```

`_find_input_area` 的解决策略：

```python
def _find_input_area(window):
    for ctrl in _collect_all_edit_controls(window):
        if ctrl.Name != '搜索':   # 排除搜索框
            return ctrl           # 返回聊天输入框
    # 备选：DocumentControl
    return window.DocumentControl(...)
```

`_collect_all_edit_controls` 递归收集所有层级的 `EditControl`（深度限制 15 层），确保不漏掉深层嵌套的聊天输入框。

### 第7步：输入消息 (`_set_text_via_value_pattern`)

```python
pattern = control.GetValuePattern()
pattern.SetValue(text)
```

- `ValuePattern.SetValue()` 是 UIA 标准接口，直接将文本设置到控件
- 不抢焦点、不碰剪贴板
- 备选：`SendKeys('{Ctrl}a')` + `SendKeys(text)`（需要控件获得焦点）

### 第8步：发送 (`_invoke_button` / Enter)

```python
# 方案A：找发送按钮
btn = window.ButtonControl(Name='发送')
pattern = btn.GetInvokePattern()
pattern.Invoke()

# 方案B：Enter 发送
input_area.SendKeys('{Enter}')
```

WeChat 4.x 使用 `XOutlineButton(Name="发送")`，可通过 `InvokePattern` 触发。找不到按钮时回退到 Enter 发送。

### 第9步：善后处理

1. **最小化窗口**（可选参数 `minimize=True`）：发送后最小化微信窗口，减少对用户干扰
2. **恢复焦点**：记录之前的前台窗口句柄，操作完成后恢复

## 多版本兼容

WeChat 的 UI Automation 结构在不同版本间可能变化。sender.py 通过以下机制应对：

| 兼容策略 | 实现 |
|----------|------|
| 多搜索深度 | `_SEARCH_DEPTH=20` 覆盖深层嵌套 |
| 多匹配模式 | `SubName` + `contains` + 精确匹配逐级降级 |
| 多 API 版本 | `WindowVisualState` → `CurrentVisualState` try/except |
| 多发送方式 | InvokePattern → Click → Enter 三级降级 |
| 多输入方式 | ValuePattern → Click+SendKeys → 报错 |
| 动态等待 | `_wait_for` 轮询替代固定 `time.sleep` |

## 调试技巧

### 用 inspect 工具分析控件树

```python
import uiautomation as auto

wechat = auto.WindowControl(Name='微信')
wechat.SendKeys('{Ctrl}i')   # 启动 Inspect 模式
```

或在项目目录运行：
```bash
python -c "import uiautomation as auto; auto.WindowControl(Name='微信').DumpTree()"
```

### 常见问题

| 现象 | 可能原因 | 解决方法 |
|------|----------|----------|
| 找不到搜索框 | `_SEARCH_DEPTH` 不够 | 调大深度（纯 Qt 版可能需要 20+） |
| 消息去了搜索栏 | 输入框定位找错了 | 检查 `_find_input_area` 排除逻辑 |
| 联系人找不到 | 精确匹配失败 | 改用 `SubName` / contains 匹配 |
| 发送按钮点不到 | 按钮超出可见区域 | 确保窗口足够大或先滚动 |
