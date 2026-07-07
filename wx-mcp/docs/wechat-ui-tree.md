# WeChat 4.x PC 版 UI 控件树

> 本文档记录 WeChat 4.x PC 版的 UI Automation 控件树结构。
> 用于 sender 模块调试和版本适配参考。

## 获取控件树

运行以下命令查看微信窗口的完整 UIA 控件树：

```bash
python -c "
import uiautomation as auto
wechat = auto.WindowControl(Name='微信')
wechat.DumpTree()
"
```

或使用 `uiautomation` 自带的 Inspect 模式（选中微信窗口后按 `Ctrl+Alt+F5`）。

## 典型控件树结构 (WeChat 4.x)

```
WindowControl '微信' (F7B608F6)
├── TitleBarControl '微信'
│   └── ButtonControl '最小化' (MinimizeButton)
│   └── ButtonControl '最大化' (MaximizeButton)
│   └── ButtonControl '关闭' (CloseButton)
│
├── SplitButtonControl (MainTabBar) ← 左侧导航
│   ├── ButtonControl '聊天'
│   ├── ButtonControl '通讯录'
│   ├── ButtonControl '收藏'
│   └── ButtonControl '...'
│
├── PaneControl ''                     ← 搜索 + 会话列表
│   ├── EditControl '搜索'              ← 搜索框 (XValidatorTextEdit)
│   │   (searchDepth=12+, ControlType=EditControl)
│   │   (ValuePattern available)
│   │
│   └── ListControl ''                  ← 会话/搜索结果列表
│       ├── ListItemControl '张三 好的明天见' (ChatSessionCell)
│       ├── ListItemControl '李四 收到'
│       └── ...
│
├── PaneControl ''                     ← 聊天面板
│   ├── ListControl ''                  ← 聊天消息列表
│   │   ├── ListItemControl '张三'
│   │   ├── ListItemControl '你好'
│   │   └── ...
│   │
│   ├── EditControl '张三'              ← 消息输入框 (ChatInputField)
│   │   (searchDepth=14+, ControlType=EditControl)
│   │   (ValuePattern available)
│   │   (Name = 当前聊天对象名称)
│   │
│   └── ButtonControl '发送'            ← 发送按钮 (XOutlineButton)
│       (searchDepth=12+, ControlType=ButtonControl)
│       (InvokePattern available)
│       (Name='发送')
│
└── StatusBarControl ''
```

## 关键控件定位参数

### 搜索框

| 属性 | 值 |
|------|-----|
| Name | "搜索" |
| ControlType | EditControl |
| AutomationId | 无固定值 |
| ClassName | Qt 内部类名（如 `XValidatorTextEdit`） |
| 典型深度 | 12~15 |
| ValuePattern | ✅ 可用 |

**定位代码**: `window.EditControl(Name='搜索', searchDepth=20)`

> ⚠️ 注意：搜索框和聊天输入框都是 `EditControl`，通过 `Name` 区分。搜索框 `Name` 永远是 `"搜索"`，聊天输入框 `Name` 是当前联系人的名称。

### 聊天输入框

| 属性 | 值 |
|------|-----|
| Name | 当前聊天对象名称（如 "文件传输助手"、"张三"） |
| ControlType | EditControl |
| 典型深度 | 14~18 |
| ValuePattern | ✅ 可用 |

**定位代码**:
```python
# 找到所有 EditControl，排除 Name="搜索" 的那个
for ctrl in collect_all_edit_controls(window):
    if ctrl.Name != '搜索':
        return ctrl  # 这就是聊天输入框
```

### 发送按钮

| 属性 | 值 |
|------|-----|
| Name | "发送" |
| ControlType | ButtonControl |
| ClassName | `XOutlineButton` |
| 典型深度 | 12~15 |
| InvokePattern | ✅ 可用 |

**定位代码**: `window.ButtonControl(Name='发送', searchDepth=20)`

### 联系人列表项

| 属性 | 值 |
|------|-----|
| Name | `"{联系人名称} {最近消息预览}"` |
| ControlType | ListItemControl |
| 典型深度 | 8~12 |

**注意**: `Name` 包含额外文本，不能用精确匹配：

```python
# ❌ 不行（精确匹配失败）
item = window.ListItemControl(Name="张三")

# ✅ 可行（包含匹配）
item = window.ListItemControl(SubName="张三")
# 或在 children 中遍历检查
if "张三" in item.Name:
    ...
```

## 深度对比：传统 Win32 vs WeChat 4.x (Qt)

| 控件 | 传统 Win32 深度 | WeChat 4.x (Qt) 深度 |
|------|----------------|---------------------|
| 搜索框 | 3-5 | 12-15 |
| 列表项 | 3-4 | 8-12 |
| 输入框 | 3-5 | 14-18 |
| 按钮 | 2-3 | 10-14 |

WeChat 4.x 基于 Qt 框架，UI 控件嵌套在多个 Pane/Group 中，导致深度显著增加。

## 常见问题

### 搜索结果名称为空？

如果联系人列表项的 `Name` 为空，尝试用 `SubName` 匹配：

```python
item = window.ListItemControl(SubName=chat_name)
```

### 控件找不到？

逐步缩小范围：
1. 从窗口开始，逐级查找
2. 先定位 `PaneControl` 区域，再查找子控件
3. 检查是否在可见区域外（需要滚动或展开）
4. 检查微信版本是否更新导致控件树变化

### 版本差异记录

| 微信版本 | 控件结构变化 | 适配要点 |
|---------|-------------|----------|
| 4.0.0.x | 初始 Qt 版本 | `_SEARCH_DEPTH` 设为 12+ 即可 |
| 4.1.0.x | 搜索框嵌套加深 | `_SEARCH_DEPTH` 需 15+ |
| ... | ... | ... |

> 记录你遇到的版本变化，方便后续维护。
