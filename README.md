# Claude Dynamic Island 🏝️

Mac Dynamic Island 风格的 Claude Code 工作状态悬浮窗，实时可视化 Claude 的工作状态。

> 灵感来自 [claude-traffic-light](https://github.com/fansea0/claude-traffic-light) 的红绿灯设计，采用更现代的灵动岛交互风格。

## ✨ 功能特性

- 🖥️ **Mac 灵动岛风格** — 纯黑药丸胶囊 UI，悬停展开/离开收起
- 🎨 **Apple 设计语言** — 紫/绿/红/橙/灰五色状态指示
- ⚡ **60fps 流畅动画** — PIL 高清渲染 + 呼吸灯 + 光晕效果
- 👁️ **即时响应** — watchdog 文件监听，无防抖延迟
- 📌 **窗口位置记忆** — 退出保存，启动恢复
- 🔔 **Windows 通知** — 需要确认/有问题时弹窗提醒
- 🖱️ **系统托盘菜单** — 显隐/重置位置/切换置顶/退出
- 🔄 **多 Session 感知** — 支持多个 Claude Code 实例

## 📸 效果预览

| 状态 | 颜色 | 说明 |
|------|------|------|
| 🟣 思考中 | `#5E5CE6` | Claude 正在思考 |
| 🟢 工作中 | `#30D158` | Claude 正在处理任务 |
| 🔴 需要确认 | `#FF453A` | 等待用户授权确认 |
| 🟠 有问题 | `#FF9F0A` | Claude 有问题要问你 |
| ⚫ 空闲 | `#636366` | 等待你的指令 |

<img width="549" height="157" alt="image" src="https://github.com/user-attachments/assets/ab6a07dd-59a6-4d13-805a-b89c29067325" />


## 📦 安装

### 前置要求

- Python 3.9+
- Windows 10/11

### 安装依赖

```bash
pip install -r requirements.txt
```

依赖列表：
- `Pillow` — 图像渲染
- `pystray` — 系统托盘图标
- `watchdog` — 文件系统监听
- `winotify` — Windows 通知

## ⚙️ 配置 Claude Code Hooks

编辑 `~/.claude/settings.json`，添加以下 hooks 配置：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python -c \"import pathlib; pathlib.Path(r'F:\\工作悬浮窗\\status.txt').write_text('thinking', encoding='utf-8')\""
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python -c \"import pathlib; pathlib.Path(r'F:\\工作悬浮窗\\status.txt').write_text('working', encoding='utf-8')\""
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python -c \"import pathlib; pathlib.Path(r'F:\\工作悬浮窗\\status.txt').write_text('thinking', encoding='utf-8')\""
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "permission_prompt",
        "hooks": [
          {
            "type": "command",
            "command": "python -c \"import pathlib; pathlib.Path(r'F:\\工作悬浮窗\\status.txt').write_text('confirm', encoding='utf-8')\""
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python -c \"import pathlib; pathlib.Path(r'F:\\工作悬浮窗\\status.txt').write_text('idle', encoding='utf-8')\""
          }
        ]
      }
    ]
  }
}
```

> ⚠️ 请将路径 `F:\工作悬浮窗\status.txt` 替换为你的实际安装路径。

## 🚀 使用方法

### 启动

```bash
# 方式一：双击启动脚本
启动悬浮窗.bat

# 方式二：命令行
python status-bar.py
```

### 交互操作

| 操作 | 效果 |
|------|------|
| 鼠标悬停 | 展开显示详细信息 |
| 鼠标离开 | 收起为紧凑胶囊 |
| 右键点击 | 打开退出菜单 |
| 托盘图标 | 右键打开管理菜单 |

### 托盘菜单

- **显示/隐藏窗口** — 切换灵动岛可见性
- **重置位置** — 恢复到屏幕顶部居中
- **切换置顶** — 开关窗口始终置顶
- **退出** — 关闭程序（自动保存位置）

## 📁 状态格式

支持两种状态文件格式：

**纯文本格式**（简单）：
```
working
```

**JSON 格式**（支持多 Session）：
```json
{
  "state": "working",
  "session_id": "abc-123-def"
}
```

## 🛠️ 故障排查

检查状态文件是否正常写入：

```bash
cat F:\工作悬浮窗\status.txt
```

手动设置状态：

```bash
# 纯文本
echo idle > F:\工作悬浮窗\status.txt

# JSON 格式
echo {"state":"idle","session_id":"test"} > F:\工作悬浮窗\status.txt
```

## 📄 License

[MIT](LICENSE)
