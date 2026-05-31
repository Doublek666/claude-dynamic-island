"""
Claude Code 灵动岛状态指示器 v11

Mac Dynamic Island 风格的 Claude Code 工作状态悬浮窗。
通过 watchdog 监听状态文件变化，实时切换 UI 状态和颜色。

功能特性：
  - Mac 灵动岛风格 UI（纯黑药丸胶囊，悬停展开/离开收起）
  - 60fps PIL 高清渲染 + 呼吸灯动画
  - watchdog 文件系统事件监听（无防抖，立即响应）
  - 系统托盘图标（显隐/重置位置/切换置顶/退出）
  - 窗口位置记忆（跨启动保持）
  - 多 Session 感知（JSON 格式 session_id 支持）
  - Windows 通知提醒（需确认/有问题时弹窗）

状态颜色（Apple 风格）：
  🟣 thinking  思考中   #5E5CE6
  🟢 working   工作中   #30D158
  🔴 confirm   需要确认  #FF453A
  🟠 question  有问题   #FF9F0A
  ⚫ idle      空闲     #636366

GitHub: https://github.com/anthropics/claude-dynamic-island
License: MIT
"""

from __future__ import annotations

import ctypes
import json
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont, ImageTk
from pystray import Icon, Menu, MenuItem
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from winotify import Notification, audio


# ══════════════════════════════════════════════════════
# 配置常量
# ══════════════════════════════════════════════════════

# 文件路径（相对于脚本所在目录）
SCRIPT_DIR = Path(__file__).parent
STATUS_FILE = SCRIPT_DIR / "status.txt"
CONFIG_FILE = SCRIPT_DIR / "island-config.json"

# 状态定义
# toast_msg: 不为空时触发 Windows 通知
STATES: dict[str, dict[str, Any]] = {
    "working": {
        "color": "#30D158",
        "rgb": (48, 209, 88),
        "label": "工作中",
        "sub": "Claude 正在处理任务",
        "toast_msg": "",
    },
    "thinking": {
        "color": "#5E5CE6",
        "rgb": (94, 92, 230),
        "label": "思考中",
        "sub": "Claude 正在思考...",
        "toast_msg": "",
    },
    "confirm": {
        "color": "#FF453A",
        "rgb": (255, 69, 58),
        "label": "需要确认",
        "sub": "请回到终端确认操作",
        "toast_msg": "Claude 需要你的确认，请回到终端查看。",
    },
    "question": {
        "color": "#FF9F0A",
        "rgb": (255, 159, 10),
        "label": "有问题",
        "sub": "Claude 有问题要问你",
        "toast_msg": "Claude 有问题要问你，请回到终端查看。",
    },
    "idle": {
        "color": "#636366",
        "rgb": (99, 99, 102),
        "label": "空闲",
        "sub": "等待你的指令",
        "toast_msg": "",
    },
}

# ── 灵动岛尺寸 ─────────────────────────────────────
COMPACT_W, COMPACT_H, COMPACT_R = 180, 48, 24
EXPANDED_W, EXPANDED_H, EXPANDED_R = 300, 120, 28

# 状态指示灯
DOT_SIZE = 10
DOT_MARGIN = 16

# ── 颜色（RGBA）─────────────────────────────────────
BG_BLACK = (0, 0, 0, 255)
BORDER_COLOR = (44, 44, 46, 255)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_SECONDARY = (174, 174, 178, 255)
TEXT_TERTIARY = (99, 99, 102, 255)

# ── 动画参数 ────────────────────────────────────────
BREATHE_MIN = 0.3
BREATHE_MAX = 1.0
BREATHE_SPEED = 0.04
ANIM_LERP = 0.15
TARGET_FPS = 60
FRAME_MS = 1000 // TARGET_FPS

# ── 字体大小 ────────────────────────────────────────
FONT_LABEL = 16
FONT_SUB = 12
FONT_TIMER = 14


# ══════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════

def create_icon_image(color: tuple[int, ...], size: int = 64) -> Image.Image:
    """创建系统托盘用的圆形图标。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)
    return img


def read_status(retries: int = 3) -> tuple[str, str]:
    """读取状态文件，返回 (state, session_id)。

    支持两种格式：
    - JSON: {"state": "working", "session_id": "xxx"}
    - 纯文本: "working"
    """
    for i in range(retries):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8", buffering=1) as f:
                text = f.read().strip()
                # 尝试 JSON 格式
                try:
                    data = json.loads(text)
                    state = data.get("state", "idle").lower()
                    session_id = data.get("session_id", "")
                    return (state if state in STATES else "idle"), session_id
                except (json.JSONDecodeError, AttributeError):
                    pass
                # 回退到纯文本格式
                plain = text.lower()
                return (plain if plain in STATES else "idle"), ""
        except (FileNotFoundError, OSError):
            if i < retries - 1:
                time.sleep(0.01)
    return "idle", ""


def send_toast(title: str, message: str) -> None:
    """发送 Windows 桌面通知。"""
    try:
        toast = Notification(app_id="Claude Code", title=title, msg=message)
        toast.set_audio(audio.Default, loop=False)
        toast.show()
    except Exception:
        pass


def fmt_time(seconds: int) -> str:
    """将秒数格式化为可读时间字符串（s / m:ss / h:mm:ss）。"""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}:{seconds % 60:02d}"
    return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def blend_color(c1: tuple[int, ...], c2: tuple[int, ...], t: float) -> tuple[int, ...]:
    """在两个 RGBA 颜色之间线性插值。"""
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(4))


def lerp(a: float, b: float, t: float) -> float:
    """线性插值。"""
    return a + (b - a) * t


def draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    x1: int, y1: int, x2: int, y2: int,
    r: int, fill: tuple[int, ...],
    outline: tuple[int, ...] | None = None,
    width: int = 1,
) -> None:
    """绘制圆角矩形，可选描边。"""
    draw.rounded_rectangle([x1, y1, x2, y2], radius=r, fill=fill)
    if outline:
        draw.rounded_rectangle([x1, y1, x2, y2], radius=r, fill=None, outline=outline, width=width)


# ══════════════════════════════════════════════════════
# 配置管理
# ══════════════════════════════════════════════════════

def load_config() -> dict[str, Any]:
    """从 JSON 文件加载配置（窗口位置、置顶状态等）。"""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(cfg: dict[str, Any]) -> None:
    """保存配置到 JSON 文件。"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════
# 字体缓存
# ══════════════════════════════════════════════════════

class FontManager:
    """PIL TrueType 字体缓存，避免重复加载。"""

    _fonts: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    @classmethod
    def get(cls, name: str, size: int) -> ImageFont.FreeTypeFont:
        """获取或创建缓存的 PIL 字体。"""
        key = (name, size)
        if key not in cls._fonts:
            try:
                font_map = {
                    "bold": "msyhbd.ttc",
                    "normal": "msyh.ttc",
                    "mono": "consola.ttf",
                }
                font_file = font_map.get(name, "msyh.ttc")
                cls._fonts[key] = ImageFont.truetype(font_file, size)
            except Exception:
                cls._fonts[key] = ImageFont.load_default()
        return cls._fonts[key]


# ══════════════════════════════════════════════════════
# 文件监听
# ══════════════════════════════════════════════════════

class StatusFileHandler(FileSystemEventHandler):
    """监听状态文件变化，触发回调（无防抖，立即响应）。"""

    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback

    def on_modified(self, event: Any) -> None:
        if not event.is_directory and Path(event.src_path).resolve() == STATUS_FILE.resolve():
            self.callback()

    def on_created(self, event: Any) -> None:
        if not event.is_directory and Path(event.src_path).resolve() == STATUS_FILE.resolve():
            self.callback()


# ══════════════════════════════════════════════════════
# 灵动岛组件
# ══════════════════════════════════════════════════════

class DynamicIsland:
    """Mac Dynamic Island 风格的浮动状态指示器。"""

    def __init__(self) -> None:
        self.state = "idle"
        self.root: tk.Tk | None = None
        self.canvas: tk.Canvas | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._after_id: str | None = None
        self._running = False

        # 呼吸动画
        self.breathe = 0.5
        self.breathe_dir = 1

        # 尺寸动画（当前值 → 目标值）
        self.current_w = COMPACT_W
        self.current_h = COMPACT_H
        self.current_r = COMPACT_R
        self.target_w = COMPACT_W
        self.target_h = COMPACT_H
        self.target_r = COMPACT_R

        # 展开状态
        self.expanded = False
        self.expand_progress = 0.0

        self.state_ts = time.time()

        # 窗口状态
        self.visible = True
        self.always_on_top = True

    def build(self) -> None:
        """构建窗口和 Canvas。"""
        self.root = tk.Tk()
        self.root.title("Claude Code")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.always_on_top)
        self.root.configure(bg="#000000")

        display_w = EXPANDED_W + 30
        display_h = EXPANDED_H + 30

        # 从配置恢复窗口位置
        cfg = load_config()
        if "window_x" in cfg and "window_y" in cfg:
            x, y = cfg["window_x"], cfg["window_y"]
        else:
            x = (self.root.winfo_screenwidth() - display_w) // 2
            y = 0

        self.root.geometry(f"{display_w}x{display_h}+{x}+{y}")
        self.root.wm_attributes("-transparentcolor", "#010101")

        self.canvas = tk.Canvas(
            self.root, width=display_w, height=display_h,
            bg="#010101", highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-3>", self._show_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="退出", command=self.destroy)
        self.root.bind("<FocusOut>", self._on_focus_out)

        self._running = True
        self._tick()

    # ── 渲染 ────────────────────────────────────────

    def _render_frame(self) -> Image.Image:
        """使用 PIL 渲染一帧灵动岛画面。"""
        canvas_w = EXPANDED_W + 30
        canvas_h = int(self.current_h) + 30
        img = Image.new("RGBA", (canvas_w, canvas_h), (1, 1, 1, 0))
        draw = ImageDraw.Draw(img)

        cx, cy = canvas_w // 2, canvas_h // 2

        # 胶囊位置
        w, h, r = int(self.current_w), int(self.current_h), int(self.current_r)
        x1, y1 = cx - w // 2, cy - h // 2
        x2, y2 = cx + w // 2, cy + h // 2

        # 胶囊背景
        draw_rounded_rect(draw, x1, y1, x2, y2, r, fill=BG_BLACK, outline=BORDER_COLOR, width=1)

        # 状态颜色（使用预计算的 RGB，避免每帧调用 hex_to_rgb）
        info = STATES[self.state]
        state_rgb: tuple[int, ...] = info["rgb"]
        state_color = state_rgb + (255,)
        breathe_color = blend_color(BG_BLACK, state_color, self.breathe)

        # 指示灯
        dot_cx = x1 + DOT_MARGIN + DOT_SIZE // 2
        dot_cy = cy

        # 光晕
        glow_size = DOT_SIZE + 10
        glow_alpha = int(self.breathe * 60)
        draw.ellipse(
            [dot_cx - glow_size // 2, dot_cy - glow_size // 2,
             dot_cx + glow_size // 2, dot_cy + glow_size // 2],
            fill=state_rgb + (glow_alpha,),
        )

        # 指示灯本体
        draw.ellipse(
            [dot_cx - DOT_SIZE // 2, dot_cy - DOT_SIZE // 2,
             dot_cx + DOT_SIZE // 2, dot_cy + DOT_SIZE // 2],
            fill=breathe_color,
        )

        font_label = FontManager.get("bold", FONT_LABEL)
        font_sub = FontManager.get("normal", FONT_SUB)
        font_timer = FontManager.get("mono", FONT_TIMER)

        if self.expand_progress > 0.5:
            self._render_expanded(draw, cx, cy, x1, x2, state_rgb, state_color, info, font_label, font_sub, font_timer)
        else:
            self._render_compact(draw, cx, cy, x1, x2, state_rgb, state_color, info, font_label, font_timer)

        return img

    def _render_expanded(
        self, draw: ImageDraw.ImageDraw,
        cx: int, cy: int, x1: int, x2: int,
        state_rgb: tuple[int, ...], state_color: tuple[int, ...],
        info: dict[str, Any],
        font_label: ImageFont.FreeTypeFont,
        font_sub: ImageFont.FreeTypeFont,
        font_timer: ImageFont.FreeTypeFont,
    ) -> None:
        """渲染展开模式的内容。"""
        dot_cx = x1 + DOT_MARGIN + DOT_SIZE // 2
        icon_x = dot_cx + DOT_SIZE // 2 + 16

        # 图标背景
        icon_bg_size = 32
        draw_rounded_rect(
            draw,
            icon_x - 4, cy - icon_bg_size // 2 - 20,
            icon_x + icon_bg_size - 4, cy + icon_bg_size // 2 - 20,
            8, fill=state_rgb + (50,),
        )
        draw.ellipse([icon_x + 8, cy - 28, icon_x + 20, cy - 16], fill=state_color)

        # 状态信息
        text_x = icon_x + icon_bg_size + 14
        draw.text((text_x, cy - 30), info["label"], fill=TEXT_WHITE, font=font_label)
        draw.text((text_x, cy + 2), info["sub"], fill=TEXT_SECONDARY, font=font_sub)

        # 计时器
        if self.state == "working":
            elapsed = int(time.time() - self.state_ts)
            timer_text = fmt_time(elapsed)
            bbox = draw.textbbox((0, 0), timer_text, font=font_timer)
            tw = bbox[2] - bbox[0]
            timer_x = x2 - 24 - tw
            draw_rounded_rect(
                draw,
                timer_x - 10, cy - 16, x2 - 16, cy + 16,
                10, fill=state_rgb + (40,),
            )
            draw.text((timer_x, cy - 9), timer_text, fill=state_color, font=font_timer)

    def _render_compact(
        self, draw: ImageDraw.ImageDraw,
        cx: int, cy: int, x1: int, x2: int,
        state_rgb: tuple[int, ...], state_color: tuple[int, ...],
        info: dict[str, Any],
        font_label: ImageFont.FreeTypeFont,
        font_timer: ImageFont.FreeTypeFont,
    ) -> None:
        """渲染紧凑模式的内容。"""
        dot_cx = x1 + DOT_MARGIN + DOT_SIZE // 2
        icon_x = dot_cx + DOT_SIZE // 2 + 14

        # 图标
        icon_bg_size = 28
        draw_rounded_rect(
            draw,
            icon_x, cy - icon_bg_size // 2,
            icon_x + icon_bg_size, cy + icon_bg_size // 2,
            7, fill=state_rgb + (50,),
        )
        draw.ellipse([icon_x + 7, cy - 7, icon_x + 21, cy + 7], fill=state_color)

        # 状态文字
        text_x = icon_x + icon_bg_size + 14
        draw.text((text_x, cy - 10), info["label"], fill=TEXT_WHITE, font=font_label)

        # 右侧：计时器或呼吸点
        if self.state == "working":
            elapsed = int(time.time() - self.state_ts)
            timer_text = fmt_time(elapsed)
            bbox = draw.textbbox((0, 0), timer_text, font=font_timer)
            tw = bbox[2] - bbox[0]
            draw.text((x2 - 18 - tw, cy - 9), timer_text, fill=TEXT_TERTIARY, font=font_timer)
        elif self.state != "idle":
            for i in range(3):
                dot_alpha = int(self.breathe * 255) if i == int(time.time() * 2) % 3 else 100
                dot_x = x2 - 36 + i * 10
                draw.ellipse([dot_x - 3, cy - 3, dot_x + 3, cy + 3], fill=state_rgb + (dot_alpha,))

    # ── 事件处理 ────────────────────────────────────

    def _on_enter(self, event: tk.Event) -> None:
        """鼠标进入：展开灵动岛。"""
        self.expanded = True
        self.target_w = EXPANDED_W
        self.target_h = EXPANDED_H
        self.target_r = EXPANDED_R

    def _on_leave(self, event: tk.Event) -> None:
        """鼠标离开：收起灵动岛。"""
        x, y = self.root.winfo_pointerxy()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        if not (rx <= x <= rx + rw and ry <= y <= ry + rh):
            self.expanded = False
            self.target_w = COMPACT_W
            self.target_h = COMPACT_H
            self.target_r = COMPACT_R

    def _on_focus_out(self, event: tk.Event | None = None) -> None:
        """窗口失焦：确保收起。"""
        if not self.expanded:
            self.target_w = COMPACT_W
            self.target_h = COMPACT_H
            self.target_r = COMPACT_R

    def _show_menu(self, event: tk.Event) -> None:
        """右键菜单。"""
        self.menu.tk_popup(event.x_root, event.y_root)

    # ── 动画循环 ────────────────────────────────────

    def _tick(self) -> None:
        """动画主循环：更新状态、渲染、调度下一帧。"""
        if not self._running or not self.root:
            return

        # 呼吸动画
        speed_mult = {"thinking": 1.2, "question": 1.5}.get(self.state, 1.0)
        if self.state == "idle":
            speed_mult = 0.3
        self.breathe += BREATHE_SPEED * speed_mult * self.breathe_dir

        if self.breathe >= BREATHE_MAX:
            self.breathe, self.breathe_dir = BREATHE_MAX, -1
        elif self.breathe <= BREATHE_MIN:
            self.breathe, self.breathe_dir = BREATHE_MIN, 1

        # 尺寸插值
        self.current_w = lerp(self.current_w, self.target_w, ANIM_LERP)
        self.current_h = lerp(self.current_h, self.target_h, ANIM_LERP)
        self.current_r = lerp(self.current_r, self.target_r, ANIM_LERP)

        # 展开进度
        target_progress = 1.0 if self.expanded else 0.0
        self.expand_progress = lerp(self.expand_progress, target_progress, ANIM_LERP)

        # 渲染
        img = self._render_frame()
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(img.width // 2, img.height // 2, image=self._photo, anchor="center")

        self._after_id = self.root.after(FRAME_MS, self._tick)

    # ── 状态 & 窗口操作 ────────────────────────────

    def update_state(self, state: str) -> None:
        """切换到新状态，重置呼吸动画。"""
        if state == self.state:
            return
        self.state = state
        self.state_ts = time.time()
        self.breathe = BREATHE_MAX
        self.breathe_dir = -1

    def save_position(self) -> None:
        """保存当前窗口位置到配置文件。"""
        if not self.root:
            return
        try:
            cfg = load_config()
            cfg["window_x"] = self.root.winfo_x()
            cfg["window_y"] = self.root.winfo_y()
            save_config(cfg)
        except Exception:
            pass

    def reset_position(self) -> None:
        """重置窗口到屏幕顶部居中。"""
        if not self.root:
            return
        try:
            x = (self.root.winfo_screenwidth() - (EXPANDED_W + 30)) // 2
            self.root.geometry(f"+{x}+0")
            cfg = load_config()
            cfg["window_x"], cfg["window_y"] = x, 0
            save_config(cfg)
        except Exception:
            pass

    def toggle_topmost(self) -> None:
        """切换窗口置顶状态。"""
        if not self.root:
            return
        self.always_on_top = not self.always_on_top
        self.root.attributes("-topmost", self.always_on_top)
        cfg = load_config()
        cfg["always_on_top"] = self.always_on_top
        save_config(cfg)

    def toggle_visibility(self) -> None:
        """切换窗口显示/隐藏。"""
        if not self.root:
            return
        if self.visible:
            self.root.withdraw()
        else:
            self.root.deiconify()
        self.visible = not self.visible

    def destroy(self) -> None:
        """保存位置并销毁窗口。"""
        self._running = False
        self.save_position()
        if self.root:
            if self._after_id:
                try:
                    self.root.after_cancel(self._after_id)
                except Exception:
                    pass
            self.root.destroy()
            self.root = None

    def run(self) -> None:
        """构建窗口并启动主循环。"""
        self.build()
        self.root.mainloop()


# ══════════════════════════════════════════════════════
# 系统托盘
# ══════════════════════════════════════════════════════

class TrayIcon:
    """系统托盘图标，通过队列与主线程通信。"""

    def __init__(self, cmd_queue: queue.Queue[str]) -> None:
        self.icon: Icon | None = None
        self.cmd_queue = cmd_queue

    def _send_cmd(self, cmd: str) -> None:
        """发送命令到主线程队列。"""
        self.cmd_queue.put(cmd)

    def run(self) -> None:
        """启动托盘图标（阻塞，应在子线程中运行）。"""
        menu = Menu(
            MenuItem("显示/隐藏窗口", lambda i, item: self._send_cmd("toggle_visibility"), default=True),
            MenuItem("重置位置", lambda i, item: self._send_cmd("reset_position")),
            MenuItem("切换置顶", lambda i, item: self._send_cmd("toggle_topmost")),
            Menu.SEPARATOR,
            MenuItem("退出", lambda i, item: self._send_cmd("quit")),
        )
        self.icon = Icon(
            "ClaudeCodeStatus",
            create_icon_image(STATES["idle"]["rgb"]),
            "Claude Code 灵动岛",
            menu,
        )
        self.icon.run()

    def update_icon(self, state: str) -> None:
        """更新托盘图标颜色。"""
        if self.icon:
            self.icon.icon = create_icon_image(STATES[state]["rgb"])

    def stop(self) -> None:
        """停止托盘图标。"""
        if self.icon:
            self.icon.stop()


# ══════════════════════════════════════════════════════
# 主控制器
# ══════════════════════════════════════════════════════

class App:
    """应用主控制器：协调 GUI、托盘、文件监听。"""

    def __init__(self) -> None:
        self.widget = DynamicIsland()
        self.cmd_queue: queue.Queue[str] = queue.Queue()
        self.tray = TrayIcon(cmd_queue=self.cmd_queue)
        self.current_state = "idle"
        self.current_session_id = ""
        self.observer = Observer()
        self._update_lock = threading.Lock()

    def _on_status_changed(self) -> None:
        """状态文件变化回调。"""
        s, session_id = read_status()
        with self._update_lock:
            if session_id and session_id != self.current_session_id:
                self.current_session_id = session_id

            if s != self.current_state:
                self.current_state = s
                try:
                    self.widget.root.after(0, self.widget.update_state, s)
                except Exception:
                    pass
                self.tray.update_icon(s)
                toast_msg = STATES[s].get("toast_msg", "")
                if toast_msg:
                    send_toast(f"Claude Code - {STATES[s]['label']}", toast_msg)

    def _process_cmd_queue(self) -> None:
        """处理来自托盘的命令（主线程轮询）。"""
        try:
            while True:
                cmd = self.cmd_queue.get_nowait()
                if cmd == "quit":
                    self.quit()
                    return
                elif cmd == "reset_position":
                    self.widget.reset_position()
                elif cmd == "toggle_topmost":
                    self.widget.toggle_topmost()
                elif cmd == "toggle_visibility":
                    self.widget.toggle_visibility()
        except queue.Empty:
            pass
        if self.widget.root:
            self.widget.root.after(100, self._process_cmd_queue)

    def _start_file_watch(self) -> None:
        """启动 watchdog 文件监听。"""
        if not STATUS_FILE.exists():
            STATUS_FILE.write_text("idle", encoding="utf-8")

        handler = StatusFileHandler(callback=self._on_status_changed)
        self.observer.schedule(handler, str(STATUS_FILE.parent), recursive=False)
        self.observer.start()

    def quit(self) -> None:
        """清理退出所有组件。"""
        self.widget.save_position()
        self.observer.stop()
        self.observer.join()
        self.tray.stop()
        self.widget.destroy()

    def run(self) -> None:
        """初始化配置并启动应用。"""
        self.current_state, self.current_session_id = read_status()

        # 恢复置顶配置
        cfg = load_config()
        if "always_on_top" in cfg:
            self.widget.always_on_top = cfg["always_on_top"]

        threading.Thread(target=self.tray.run, daemon=True).start()
        self._start_file_watch()

        print("Claude Code 灵动岛 v11 已启动")
        print("  悬停展开 | 托盘菜单: 显隐 / 重置 / 置顶 / 退出")

        self._process_cmd_queue()
        self.widget.run()


# ══════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    # DPI 感知（高分屏清晰渲染）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    App().run()
