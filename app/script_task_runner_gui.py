import ctypes
import json
import random
import os
import py_compile
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "博士舰长绳匠的跨游打卡机"
CONFIG_FILE = Path(__file__).with_suffix(".json")
HISTORY_FILE = Path(__file__).with_name("script_task_runner_history.json")

# 颜色全部由下面两套调色板驱动：深色 / 明亮。
# 切换主题时 apply_theme(name) 会重新给这些模块级常量赋值，再重建整个 UI。
THEMES = {
    "dark": {
        "bg": "#0b1220", "panel": "#131c2f", "panel_2": "#1c2740", "panel_hover": "#22304c",
        "border": "#283449", "border_soft": "#1d2841", "text": "#e8edf5", "muted": "#8a98b4",
        "accent": "#10b981", "accent_hover": "#34d399", "accent_bg": "#063626", "accent_text": "#04241a",
        "accent_disabled_bg": "#14532d",
        "danger": "#ef4444", "danger_bg": "#3b1f2a", "danger_text": "#fecaca",
        "danger_hover_bg": "#7f1d1d", "danger_hover_text": "#fee2e2", "danger_outline": "#7f1d1d",
        "disabled_bg": "#1f2937", "disabled_text": "#64748b", "ghost_disabled_text": "#475569",
        "warn": "#f59e0b", "info": "#60a5fa",
        "selected_fg": "#ecfdf5", "status_bar_bg": "#070d18", "field_bg": "#070e1c", "field_fg": "#cbd5e1",
    },
    "light": {
        "bg": "#eef2f8", "panel": "#ffffff", "panel_2": "#eef1f7", "panel_hover": "#e2e8f2",
        "border": "#d4dae6", "border_soft": "#e6ebf3", "text": "#1f2733", "muted": "#6b7280",
        "accent": "#059669", "accent_hover": "#047857", "accent_bg": "#d1fae5", "accent_text": "#ffffff",
        "accent_disabled_bg": "#a7f3d0",
        "danger": "#dc2626", "danger_bg": "#fee2e2", "danger_text": "#991b1b",
        "danger_hover_bg": "#fecaca", "danger_hover_text": "#7f1d1d", "danger_outline": "#fca5a5",
        "disabled_bg": "#e5e7eb", "disabled_text": "#9ca3af", "ghost_disabled_text": "#9ca3af",
        "warn": "#d97706", "info": "#2563eb",
        "selected_fg": "#064e3b", "status_bar_bg": "#e7ebf2", "field_bg": "#ffffff", "field_fg": "#374151",
    },
}


def apply_theme(name):
    global BG, PANEL, PANEL_2, PANEL_HOVER, BORDER, BORDER_SOFT, TEXT, MUTED
    global ACCENT, ACCENT_HOVER, ACCENT_BG, ACCENT_TEXT, ACCENT_DISABLED_BG
    global DANGER, DANGER_BG, DANGER_TEXT, DANGER_HOVER_BG, DANGER_HOVER_TEXT, DANGER_OUTLINE
    global DISABLED_BG, DISABLED_TEXT, GHOST_DISABLED_TEXT, WARN, INFO
    global SELECTED_FG, STATUS_BAR_BG, FIELD_BG, FIELD_FG
    p = THEMES[name]
    BG = p["bg"]; PANEL = p["panel"]; PANEL_2 = p["panel_2"]; PANEL_HOVER = p["panel_hover"]
    BORDER = p["border"]; BORDER_SOFT = p["border_soft"]; TEXT = p["text"]; MUTED = p["muted"]
    ACCENT = p["accent"]; ACCENT_HOVER = p["accent_hover"]; ACCENT_BG = p["accent_bg"]
    ACCENT_TEXT = p["accent_text"]; ACCENT_DISABLED_BG = p["accent_disabled_bg"]
    DANGER = p["danger"]; DANGER_BG = p["danger_bg"]; DANGER_TEXT = p["danger_text"]
    DANGER_HOVER_BG = p["danger_hover_bg"]; DANGER_HOVER_TEXT = p["danger_hover_text"]
    DANGER_OUTLINE = p["danger_outline"]
    DISABLED_BG = p["disabled_bg"]; DISABLED_TEXT = p["disabled_text"]
    GHOST_DISABLED_TEXT = p["ghost_disabled_text"]; WARN = p["warn"]; INFO = p["info"]
    SELECTED_FG = p["selected_fg"]; STATUS_BAR_BG = p["status_bar_bg"]
    FIELD_BG = p["field_bg"]; FIELD_FG = p["field_fg"]


apply_theme("dark")
FONT_CN = "Microsoft YaHei UI"
FONT_EN = "Segoe UI"
FONT_MONO = "Consolas"
# Tkinter on Windows links fonts at draw time, so emoji glyphs that aren't in
# Microsoft YaHei UI still render via Segoe UI Symbol/Emoji. We pick mostly
# geometric symbols so this stays reliable across the codepoints used below.
FONT_ICON = "Segoe UI Symbol"
CIALLO_COLORS = [
    "#ff7ab6", "#8b5cf6", "#60a5fa", "#34d399", "#facc15",
    "#fb7185", "#22d3ee", "#c084fc", "#f97316", "#a3e635",
]

if os.name == "nt":
    # 必须在创建 Tk 窗口前设置 DPI awareness，否则 Windows 会把界面缩放成低分辨率位图，文字会发糊。
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# TaskRunner 目录结构：
# app/   主程序
# tasks/ 所有任务脚本
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASKS_ROOT = PROJECT_ROOT / "tasks"
SETTINGS_FILE = PROJECT_ROOT / "config" / "task_settings.json"


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text="", command=None, variant="normal", width=None, height=32, icon="", radius=10, tooltip=""):
        self.text = text
        self.icon = icon
        self.command = command
        self.variant = variant
        self.state = tk.NORMAL
        self.hover = False
        self.pressed = False
        self.height = height
        self.radius = radius
        self.tooltip = tooltip
        # Auto-size: icon + space (when both icon and text exist) + text.
        display_len = len(text) + (2 if icon and text else 0) + (1 if icon else 0)
        self.width = width or max(64, display_len * 10 + 24)
        try:
            parent_bg = parent.cget("bg")
        except Exception:
            parent_bg = BG
        super().__init__(parent, width=self.width, height=self.height, bg=parent_bg, highlightthickness=0, bd=0)
        self.configure(cursor="hand2")
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    def _colors(self):
        if self.variant == "accent":
            normal = (ACCENT, ACCENT_TEXT)
            hover = (ACCENT_HOVER, ACCENT_TEXT)
            disabled = (ACCENT_DISABLED_BG, DISABLED_TEXT)
            outline = ACCENT
        elif self.variant == "danger":
            normal = (DANGER_BG, DANGER_TEXT)
            hover = (DANGER_HOVER_BG, DANGER_HOVER_TEXT)
            disabled = (DISABLED_BG, DISABLED_TEXT)
            outline = DANGER_OUTLINE
        elif self.variant == "ghost":
            normal = (PANEL, MUTED)
            hover = (PANEL_HOVER, TEXT)
            disabled = (PANEL, GHOST_DISABLED_TEXT)
            outline = BORDER_SOFT
        else:
            normal = (PANEL_2, TEXT)
            hover = (PANEL_HOVER, TEXT)
            disabled = (DISABLED_BG, DISABLED_TEXT)
            outline = BORDER
        if self.state == tk.DISABLED:
            return disabled + (outline,)
        if self.pressed:
            # Slightly darker on press for tactile feedback.
            fill, fg = hover
            return (fill, fg, outline)
        return (hover[0], hover[1], outline) if self.hover else (normal[0], normal[1], outline)

    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _draw(self):
        self.delete("all")
        fill, fg, outline = self._colors()
        self._round_rect(1, 1, self.width - 1, self.height - 1, self.radius, fill=fill, outline=outline)
        bold = self.variant == "accent"
        font_text = (FONT_CN, 10, "bold" if bold else "normal")
        if self.icon and self.text:
            label = f"{self.icon}  {self.text}"
        elif self.icon:
            label = self.icon
        else:
            label = self.text
        self.create_text(self.width / 2, self.height / 2 + 1, text=label, fill=fg, font=font_text)

    def _on_enter(self, event=None):
        self.hover = True
        self._draw()

    def _on_leave(self, event=None):
        self.hover = False
        self.pressed = False
        self._draw()

    def _on_press(self, event=None):
        if self.state == tk.DISABLED:
            return
        self.pressed = True
        self._draw()

    def _on_release(self, event=None):
        if self.state == tk.DISABLED:
            self.pressed = False
            return
        was_pressed = self.pressed
        self.pressed = False
        self._draw()
        if was_pressed and self.command:
            self.command()

    def configure(self, cnf=None, **kwargs):
        if "state" in kwargs:
            self.state = kwargs.pop("state")
            self._draw()
        if "text" in kwargs:
            self.text = kwargs.pop("text")
            self._draw()
        if kwargs:
            super().configure(cnf or {}, **kwargs)

    config = configure


class IconButton(RoundedButton):
    """Square icon-only button — used by the left navigation rail."""

    def __init__(self, parent, icon, command=None, size=40, variant="ghost", tooltip=""):
        super().__init__(parent, text="", icon=icon, command=command,
                         variant=variant, width=size, height=size,
                         radius=10, tooltip=tooltip)

    def _draw(self):
        self.delete("all")
        fill, fg, outline = self._colors()
        self._round_rect(1, 1, self.width - 1, self.height - 1, self.radius, fill=fill, outline=outline)
        self.create_text(self.width / 2, self.height / 2 + 1, text=self.icon, fill=fg, font=(FONT_ICON, 16))


def _build_task(task_id, name, description, script_path, paths=None, icon=""):
    # paths: 该任务需要用户配置的外部路径，每项 {key, label}。
    # 运行时通过环境变量 TASKRUNNER_PATH_<KEY大写> 传给脚本；脚本读不到则用内置默认。
    return {
        "id": task_id,
        "icon": icon,
        "name": name,
        "description": description,
        "path": str(script_path),
        "paths": paths or [],
        "args": "",
        "workdir": str(Path(script_path).parent),
    }


# 后续要新增任务，就在下面 list 里继续加一项。
# path 用 TASKS_ROOT 拼出来，避免硬编码绝对路径。
# icon 用 Unicode 几何/符号字符，靠系统字体链替换渲染，不依赖额外的图标库。
AVAILABLE_TASKS = [
    _build_task(
        task_id="maaend_essence_then_daily",
        icon="✦",
        name="MaaEnd 终末地",
        description="打开 MaaEnd，先执行基质刷取，完成后执行全套日常，最后关闭 MaaEnd 和终末地。",
        script_path=TASKS_ROOT / "maaend" / "maaend_sequence_task.py",
        paths=[
            {"key": "maaend", "label": "MaaEnd 目录或 MaaEnd.exe"},
            {"key": "endfield", "label": "终末地 Endfield.exe（可选，不填则跳过预启动）"},
        ],
    ),
    _build_task(
        task_id="onedragon_zzz_daily",
        icon="◈",
        name="ZZZ 一条龙",
        description="打开 OneDragon，点击启动一条龙，等待日志显示任务完成后关闭 OneDragon。",
        script_path=TASKS_ROOT / "onedragon" / "onedragon_sequence_task.py",
        paths=[
            {"key": "dir", "label": "OneDragon 目录或 OneDragon-Launcher.exe"},
        ],
    ),
    _build_task(
        task_id="maa_arknights_daily",
        icon="⛨",
        name="MAA 明日方舟",
        description="启动 MuMu 明日方舟和 MAA，点击 Link Start!；连接成功后队列继续，后台等待 MAA 完成后关闭。",
        script_path=TASKS_ROOT / "maa_arknights" / "maa_arknights_task.py",
        paths=[
            {"key": "maa", "label": "MAA 目录或 MAA.exe"},
            {"key": "arknights", "label": "明日方舟 MuMu 快捷方式 .lnk（可选，不填请先手动打开 MuMu）"},
        ],
    ),
    _build_task(
        task_id="maabbb_honkai3_daily",
        icon="☄",
        name="Maabbb 崩坏3",
        description="启动 Maa_bbb (MFW.exe)，等待识宝小助手窗口；鼠标点击绿色“开始”按钮触发任务；日志显示全部任务完成且游戏关闭后收尾。",
        script_path=TASKS_ROOT / "maabbb" / "maabbb_sequence_task.py",
        paths=[
            {"key": "dir", "label": "Maa_bbb 目录或 MFW.exe"},
        ],
    ),
    _build_task(
        task_id="march7th_starrail_daily",
        icon="✧",
        name="March7th 星穹铁道",
        description="启动 March7th Launcher，等待三月七小助手窗口；鼠标点击“日常”启动崩坏：星穹铁道日常；日志显示停止运行且游戏关闭后收尾。",
        script_path=TASKS_ROOT / "march7th" / "march7th_sequence_task.py",
        paths=[
            {"key": "dir", "label": "March7th 目录或 March7th Launcher.exe"},
        ],
    ),
]


# 队列里每种状态对应的图标 + Treeview tag。tag 决定颜色，图标贴在状态文字前。
# 失败码会拼回字符串（如 "失败(1)"），所以这里做前缀匹配，不要求完全相等。
STATUS_STYLE = {
    "等待":   {"icon": "◌", "tag": "waiting"},
    "运行中": {"icon": "⟳", "tag": "running"},
    "完成":   {"icon": "✓", "tag": "done"},
    "失败":   {"icon": "✕", "tag": "failed"},
    "已停止": {"icon": "⏸", "tag": "stopped"},
    "任务不存在": {"icon": "⚠", "tag": "failed"},
}

TASK_PERSONA = {
    "maa_arknights_daily": {"role": "博士", "running": "博士正在清理理智...", "done": "理智已清空", "failed": "博士，代理指挥失联了"},
    "maabbb_honkai3_daily": {"role": "舰长", "running": "舰长正在出击...", "done": "舰长日常收工", "failed": "舰长，识宝小助手摆烂了"},
    "march7th_starrail_daily": {"role": "开拓者", "running": "开拓者正在跑星穹日常...", "done": "开拓者日常收工", "failed": "开拓者，星穹列车脱轨了"},
    "onedragon_zzz_daily": {"role": "绳匠", "running": "绳匠正在接单...", "done": "录像店今日营业结束", "failed": "绳匠，空洞信号断了"},
    "maaend_essence_then_daily": {"role": "管理员", "running": "管理员正在基建巡检...", "done": "终末地巡检完成", "failed": "管理员，终末地信号异常"},
}

BACKGROUND_MARKERS = [
    "已启动后台 MAA 完成监控",
    "后台监控：开始等待 MAA 所有任务完成",
    "后台监控：检测到 MAA 所有任务完成",
    "后台监控：等待 MAA 完成超时",
]

FRIENDLY_FAILURE_RULES = [
    ("脚本文件不存在", "脚本路径不对：去任务设置里重新选择脚本。"),
    ("找不到 MAA.exe", "MAA 路径不对：检查 tools\\工具目录\\maa 或任务设置里的路径。"),
    ("等待 MAA 窗口超时", "MAA 没正常打开：可能被杀软拦截、路径错误，或窗口标题变了。"),
    ("等待 MAA 成功连接模拟器超时", "MAA 没连上 MuMu：可能 Link Start 没点中、模拟器没开完，或 adb 连接卡住。"),
    ("连接失败", "MAA 连接失败：优先看 MuMu 是否真正进游戏、MAA 连接配置是否还对。"),
    ("等待识宝小助手窗口超时", "Maa_bbb 没正常打开：检查 MFW.exe 路径和识宝小助手窗口。"),
    ("等待 Maabbb 任务流程启动超时", "Maa_bbb 点了开始但日志没出现「设备连接成功/执行任务」：可能窗口未加载完、点偏了，或 MFW 卡住。"),
    ("任务流程启动失败", "Maa_bbb 启动任务失败：打开识宝小助手看看任务配置/游戏连接状态。"),
    ("任务流程出错", "Maa_bbb 执行中报错：看识宝小助手日志，通常是游戏状态或脚本识别问题。"),
    ("等待三月七小助手窗口超时", "三月七小助手没正常打开：检查 March7th Launcher 路径，或它是否被杀软拦截。"),
    ("等待 March7th 任务启动超时", "点了「日常」但日志没出现「开始运行」：可能界面没加载完、点偏了，或停在某个弹窗/设置页。"),
    ("March7th 日常任务未能正常启动", "日志没看到“开始运行”：打开三月七小助手看看是不是停在某个弹窗/设置页。"),
    ("March7th 任务未成功完成", "日常没跑完就停了：看三月七小助手当天日志（logs/当天.log）定位卡点。"),
    ("超时", "任务等待超时：大概率卡在窗口、日志或游戏关闭检测上。"),
]

LOG_KEYWORDS = {
    "success": ("完成", "成功", "已启动", "已出现", "已关闭", "检测到", "OK"),
    "warning": ("等待", "重试", "第 ", "点击", "发送", "调到最前", "后台监控"),
    "error": ("失败", "超时", "找不到", "不存在", "异常", "出错"),
    "info": ("启动", "窗口", "Link Start", "Ctrl+F1", "gui.log", ">>>", "<<<"),
}


def _now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _display_time(value):
    if not value:
        return "从未"
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return value
    today = datetime.now().date()
    if dt.date() == today:
        return "今天 " + dt.strftime("%H:%M")
    if (today - dt.date()).days == 1:
        return "昨天 " + dt.strftime("%H:%M")
    return dt.strftime("%m-%d %H:%M")


def _task_persona(task_id, key, fallback=""):
    return TASK_PERSONA.get(task_id, {}).get(key, fallback)


def _friendly_failure_hint(text):
    for marker, hint in FRIENDLY_FAILURE_RULES:
        if marker in text:
            return hint
    return "可以先点“体检”检查路径，再查看本次日志定位卡点。"


def _status_decorate(status):
    """返回 (display_text, tag)。失败(N) 这种带括号的也能匹配上。"""
    for prefix, style in STATUS_STYLE.items():
        if status.startswith(prefix):
            return f"{style['icon']}  {status}", style["tag"]
    return status, "waiting"


class ScriptRunnerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self._setup_dpi_scaling()
        self.root.geometry("1040x660")
        self.root.minsize(900, 580)
        self.root.configure(bg=BG)
        self._enable_dark_title_bar()

        self.theme = "dark"
        self.task_settings = self._load_task_settings()
        self.task_catalog = self._build_task_catalog()
        self.history = self._load_history()
        self.queue = []
        self.current_process = None
        self.running = False
        self.stop_requested = False
        self.current_queue_index = -1
        self.current_stage = "就绪"
        self.background_tasks = {}
        self.timeline = []

        self.status_var = tk.StringVar(value="  ●  就绪")
        self.overview_var = tk.StringVar(value="今日进度：0 / 0")
        self.stage_var = tk.StringVar(value="当前卡点：就绪")
        self.background_var = tk.StringVar(value="后台监控：暂无")
        self.continue_on_error_var = tk.BooleanVar(value=False)

        self._load_config()
        self._apply_theme(self.theme)
        self.root.bind_all("<Button-1>", self._show_ciallo, add="+")
        self._register_global_hotkey()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_dpi_scaling(self):
        # DPI aware 后，Tk 默认 scaling 可能过小；按实际屏幕 DPI 设置，避免发糊同时保持可读大小。
        try:
            dpi = self.root.winfo_fpixels("1i")
            scaling = max(1.0, min(1.5, dpi / 96.0))
            self.root.tk.call("tk", "scaling", scaling)
        except Exception:
            pass

    def _enable_dark_title_bar(self, light=False):
        if os.name != "nt":
            return
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            value = ctypes.c_int(0 if light else 1)
            # Windows 11/10 title bar 明暗。Attribute 20 在较新版本生效，19 在旧版本生效。
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
            # Rounded window corners on Windows 11 when available.
            corner = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
        except Exception:
            pass

    def _toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self._apply_theme(self.theme)
        self._log(f"已切换到{'明亮' if self.theme == 'light' else '深色'}模式。")

    def _apply_theme(self, name):
        # 重新给模块级颜色常量赋值 -> 重配 ttk 样式 -> 重建整个 UI -> 刷新数据。
        apply_theme(name)
        self.theme = name
        self.root.configure(bg=BG)
        self._setup_style()
        self._build_ui()
        self._refresh_all()
        self._enable_dark_title_bar(light=(name == "light"))
        self._save_config()

    def _setup_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL, font=(FONT_CN, 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL, relief="flat")
        style.configure("Header.TFrame", background=BG)
        style.configure("Rail.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT_CN, 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=(FONT_EN, 19, "bold"))
        style.configure("Section.TLabel", background=PANEL, foreground=TEXT, font=(FONT_CN, 11, "bold"))
        style.configure("SectionHint.TLabel", background=PANEL, foreground=MUTED, font=(FONT_CN, 9))
        style.configure("TButton", background=PANEL_2, foreground=TEXT, bordercolor=BORDER, focusthickness=0, padding=(10, 5))
        style.map("TButton", background=[("active", BORDER), ("disabled", DISABLED_BG)], foreground=[("disabled", DISABLED_TEXT)])
        style.configure("Accent.TButton", background=ACCENT, foreground=ACCENT_TEXT, bordercolor=ACCENT, padding=(14, 6), font=(FONT_CN, 9, "bold"))
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("disabled", ACCENT_DISABLED_BG)])
        style.configure("Danger.TButton", background=DANGER_BG, foreground=DANGER_TEXT, bordercolor=DANGER_OUTLINE, padding=(12, 6))
        style.map("Danger.TButton", background=[("active", DANGER_HOVER_BG)])
        style.configure("TCheckbutton", background=BG, foreground=MUTED, focuscolor=BG)
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", TEXT)])
        style.configure("Treeview", background=PANEL, foreground=TEXT, fieldbackground=PANEL, bordercolor=BORDER, rowheight=30, font=(FONT_CN, 10), borderwidth=0)
        style.configure("Compact.Treeview", background=PANEL, foreground=TEXT, fieldbackground=PANEL, rowheight=30, font=(FONT_CN, 10), borderwidth=0)
        style.layout("Compact.Treeview", style.layout("Treeview"))
        style.configure("Treeview.Heading", background=PANEL_2, foreground=MUTED, relief="flat", font=(FONT_CN, 9, "bold"), padding=(8, 5))
        style.configure("Compact.Treeview.Heading", background=PANEL_2, foreground=MUTED, relief="flat", font=(FONT_CN, 9, "bold"), padding=(8, 5))
        style.map("Treeview", background=[("selected", ACCENT_BG)], foreground=[("selected", SELECTED_FG)])
        style.map("Compact.Treeview", background=[("selected", ACCENT_BG)], foreground=[("selected", SELECTED_FG)])
        style.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=PANEL, bordercolor=PANEL, arrowcolor=MUTED, gripcount=0)
        style.map("Vertical.TScrollbar", background=[("active", PANEL_HOVER)])
        style.configure("Status.TLabel", background=STATUS_BAR_BG, foreground=MUTED, padding=(12, 5), font=(FONT_CN, 9))

    def _build_ui(self):
        # 切换主题时整棵 UI 会被重建，先把上一次挂在 root 上的控件全部销毁。
        for child in list(self.root.pack_slaves()):
            child.destroy()
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True)

        # ── 左侧导航栏：app 标识 + 主要动作（设置 / 刷新）。
        # 借鉴 MFW 风格的窄竖排导航：icon-only 按钮，hover 时高亮，承担入口。
        rail = tk.Frame(outer, bg=PANEL, width=58)
        rail.pack(side=tk.LEFT, fill=tk.Y)
        rail.pack_propagate(False)
        tk.Label(rail, text="⚡", bg=PANEL, fg=ACCENT, font=(FONT_ICON, 22)).pack(pady=(14, 6))
        tk.Frame(rail, bg=BORDER_SOFT, height=1).pack(fill=tk.X, padx=12, pady=(4, 10))
        IconButton(rail, icon="↻", command=self._reload_catalog, tooltip="刷新任务库").pack(pady=4)
        # 底部齿轮：打开当前选中任务的设置（侧边栏最底）。
        IconButton(rail, icon="⚙", command=self._open_task_settings, tooltip="任务设置").pack(side=tk.BOTTOM, pady=(0, 14))
        # 月亮/太阳：切换深色/明亮模式，叠在齿轮正上方。
        theme_icon = "☀" if self.theme == "light" else "☾"
        IconButton(rail, icon=theme_icon, command=self._toggle_theme, tooltip="切换明亮/深色模式").pack(side=tk.BOTTOM, pady=(0, 8))

        # ── 主内容区
        main = tk.Frame(outer, bg=BG)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        content = tk.Frame(main, bg=BG)
        content.pack(fill=tk.BOTH, expand=True, padx=14, pady=(10, 6))

        # 保留任务设置入口，但不要重复摆太多：只在左下角齿轮里放一个。
        header = tk.Frame(content, bg=BG)
        header.pack(fill=tk.X, pady=(0, 10))
        title_wrap = tk.Frame(header, bg=BG)
        title_wrap.pack(side=tk.LEFT)
        tk.Label(title_wrap, text="TaskRunner", bg=BG, fg=TEXT, font=(FONT_EN, 19, "bold")).pack(side=tk.LEFT)
        tk.Label(title_wrap, text="  自动任务队列 · F12 / Ctrl+Alt+F12 / Pause 停止",
                 bg=BG, fg=MUTED, font=(FONT_CN, 9)).pack(side=tk.LEFT, padx=(2, 0), pady=(8, 0))

        # 顶部双栏：可用任务 | 运行队列
        top = tk.Frame(content, bg=BG)
        top.pack(fill=tk.BOTH, expand=True)

        dashboard = tk.Frame(top, bg=BG)
        dashboard.pack(side=tk.LEFT, fill=tk.Y)

        overview_frame = tk.Frame(dashboard, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        overview_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(overview_frame, text="今日跨游打卡", bg=PANEL, fg=TEXT, font=(FONT_CN, 11, "bold")).pack(anchor="w", padx=10, pady=(9, 1))
        tk.Label(overview_frame, textvariable=self.overview_var, bg=PANEL, fg=ACCENT, font=(FONT_CN, 10, "bold")).pack(anchor="w", padx=10, pady=(0, 2))
        tk.Label(overview_frame, textvariable=self.stage_var, bg=PANEL, fg=MUTED, font=(FONT_CN, 9), wraplength=245, justify=tk.LEFT).pack(anchor="w", padx=10, pady=(0, 8))

        background_frame = tk.Frame(dashboard, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        background_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(background_frame, text="后台监控", bg=PANEL, fg=TEXT, font=(FONT_CN, 11, "bold")).pack(anchor="w", padx=10, pady=(9, 1))
        tk.Label(background_frame, textvariable=self.background_var, bg=PANEL, fg=MUTED, font=(FONT_CN, 9), wraplength=245, justify=tk.LEFT).pack(anchor="w", padx=10, pady=(0, 8))

        catalog_frame = tk.Frame(dashboard, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        catalog_frame.pack(fill=tk.BOTH, expand=True)
        catalog_frame.configure(width=270)
        dashboard.configure(width=270)
        dashboard.pack_propagate(False)
        catalog_frame.pack_propagate(False)

        queue_frame = tk.Frame(top, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        queue_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))

        catalog_head = tk.Frame(catalog_frame, bg=PANEL)
        catalog_head.pack(fill=tk.X, padx=10, pady=(9, 6))
        ttk.Label(catalog_head, text="◆  可用任务", style="Section.TLabel").pack(side=tk.LEFT)
        ttk.Label(catalog_head, text="双击加入", style="SectionHint.TLabel").pack(side=tk.RIGHT)

        self.catalog_tree = self._create_tree(catalog_frame, ("name",), style="Compact.Treeview")
        self.catalog_tree.heading("name", text="任务")
        self.catalog_tree.column("name", width=285, anchor=tk.W, stretch=True)
        self.catalog_tree.bind("<Double-1>", self._add_selected_to_queue)

        catalog_buttons = tk.Frame(catalog_frame, bg=PANEL)
        catalog_buttons.pack(fill=tk.X, padx=10, pady=(10, 12))
        RoundedButton(catalog_buttons, text="加入", icon="＋", variant="accent", command=self._add_selected_to_queue).pack(side=tk.LEFT)
        RoundedButton(catalog_buttons, text="刷新", icon="↻", command=self._reload_catalog).pack(side=tk.LEFT, padx=(6, 0))
        RoundedButton(catalog_buttons, text="设置", icon="⚙", command=self._open_task_settings).pack(side=tk.LEFT, padx=(6, 0))

        queue_head = tk.Frame(queue_frame, bg=PANEL)
        queue_head.pack(fill=tk.X, padx=10, pady=(9, 6))
        ttk.Label(queue_head, text="≡  运行队列", style="Section.TLabel").pack(side=tk.LEFT)
        ttk.Label(queue_head, text="从上到下执行", style="SectionHint.TLabel").pack(side=tk.RIGHT)

        self.queue_tree = self._create_tree(queue_frame, ("name", "status", "last_run"), style="Compact.Treeview")
        self.queue_tree.heading("name", text="任务")
        self.queue_tree.heading("status", text="状态")
        self.queue_tree.heading("last_run", text="上次")
        self.queue_tree.column("name", width=330, anchor=tk.W)
        self.queue_tree.column("status", width=130, anchor=tk.W, stretch=False)
        self.queue_tree.column("last_run", width=105, anchor=tk.W, stretch=False)
        self.queue_tree.bind("<Double-1>", self._run_selected_queue_item)
        self.queue_tree.bind("<Delete>", self._remove_from_queue)
        self.queue_tree.bind("<BackSpace>", self._remove_from_queue)
        # 状态文字着色：Treeview tag 给整行上色，所以"等待"保持正常 TEXT 色，
        # 避免未跑过的任务整行发灰；其他状态需要强提示，整行染色反而能让眼睛先看到。
        self.queue_tree.tag_configure("waiting", foreground=TEXT)
        self.queue_tree.tag_configure("running", foreground=INFO)
        self.queue_tree.tag_configure("done", foreground=ACCENT)
        self.queue_tree.tag_configure("failed", foreground=DANGER)
        self.queue_tree.tag_configure("stopped", foreground=WARN)

        queue_buttons = tk.Frame(queue_frame, bg=PANEL)
        queue_buttons.pack(fill=tk.X, padx=10, pady=(10, 12))
        RoundedButton(queue_buttons, icon="↑", width=38, command=self._move_up).pack(side=tk.LEFT)
        RoundedButton(queue_buttons, icon="↓", width=38, command=self._move_down).pack(side=tk.LEFT, padx=(6, 0))
        RoundedButton(queue_buttons, text="移出", icon="✕", command=self._remove_from_queue).pack(side=tk.LEFT, padx=(6, 0))
        RoundedButton(queue_buttons, text="清空", icon="⌫", command=self._clear_queue).pack(side=tk.LEFT, padx=(6, 0))
        RoundedButton(queue_buttons, text="重跑失败", icon="↻", command=self._rerun_failed_tasks).pack(side=tk.LEFT, padx=(6, 0))
        RoundedButton(queue_buttons, text="体检", icon="🩺", command=self._health_check).pack(side=tk.LEFT, padx=(6, 0))

        # 运行控制栏
        run_frame = tk.Frame(content, bg=BG)
        run_frame.pack(fill=tk.X, pady=(10, 0))
        self.start_button = RoundedButton(run_frame, text="开始", icon="▶", width=92, height=36, variant="accent", command=self._start_run)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = RoundedButton(run_frame, text="停止", icon="■", width=88, height=36, variant="danger", command=self._stop_run)
        self.stop_button.configure(state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        RoundedButton(run_frame, text="运行选中", icon="▷", height=36, command=self._run_selected_queue_item).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(
            run_frame,
            text="失败后继续下一个",
            variable=self.continue_on_error_var,
            command=self._save_config,
        ).pack(side=tk.LEFT, padx=(16, 0))

        timeline_panel = tk.Frame(content, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        timeline_panel.pack(fill=tk.X, expand=False, pady=(10, 0))
        timeline_head = tk.Frame(timeline_panel, bg=PANEL)
        timeline_head.pack(fill=tk.X, padx=10, pady=(9, 4))
        ttk.Label(timeline_head, text="⌁  今日时间线", style="Section.TLabel").pack(side=tk.LEFT)
        ttk.Label(timeline_head, text="关键节点", style="SectionHint.TLabel").pack(side=tk.RIGHT)
        timeline_body = tk.Frame(timeline_panel, bg=PANEL)
        timeline_body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.timeline_text = tk.Text(
            timeline_body,
            height=4,
            wrap=tk.WORD,
            bg=FIELD_BG,
            fg=FIELD_FG,
            relief=tk.FLAT,
            padx=10,
            pady=7,
            font=(FONT_CN, 9),
            highlightthickness=0,
        )
        self.timeline_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        timeline_scrollbar = ttk.Scrollbar(timeline_body, orient=tk.VERTICAL, command=self.timeline_text.yview)
        timeline_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.timeline_text.configure(yscrollcommand=timeline_scrollbar.set)

        # 运行日志面板
        log_panel = tk.Frame(content, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        log_panel.pack(fill=tk.X, expand=False, pady=(10, 0))
        log_head = tk.Frame(log_panel, bg=PANEL)
        log_head.pack(fill=tk.X, padx=10, pady=(9, 4))
        ttk.Label(log_head, text="❯  运行日志", style="Section.TLabel").pack(side=tk.LEFT)
        ttk.Label(log_head, text="实时输出", style="SectionHint.TLabel").pack(side=tk.RIGHT)
        log_body = tk.Frame(log_panel, bg=PANEL)
        log_body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 12))
        self.log_text = tk.Text(
            log_body,
            height=6,
            wrap=tk.WORD,
            bg=FIELD_BG,
            fg=FIELD_FG,
            insertbackground=TEXT,
            relief=tk.FLAT,
            padx=10,
            pady=8,
            font=(FONT_MONO, 9),
            highlightthickness=0,
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar = ttk.Scrollbar(log_body, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.tag_configure("success", foreground=ACCENT)
        self.log_text.tag_configure("warning", foreground=WARN)
        self.log_text.tag_configure("error", foreground=DANGER)
        self.log_text.tag_configure("info", foreground=INFO)
        self.log_text.tag_configure("muted", foreground=MUTED)

        status = ttk.Label(self.root, textvariable=self.status_var, style="Status.TLabel", anchor=tk.W)
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.root.after(150, lambda: self._enable_dark_title_bar(light=(self.theme == "light")))

    def _show_ciallo(self, event):
        """每次左键点击时，在点击位置弹出一段彩色 Ciallo，并向右上角飘走。"""
        try:
            # 不在任务设置弹窗/文件选择器里乱飘，只响应主窗口自身和它的子控件。
            widget_root = event.widget.winfo_toplevel()
            if widget_root is not self.root:
                return
            magic_bg = "#010203"
            tip = tk.Toplevel(self.root)
            tip.overrideredirect(True)
            tip.configure(bg=magic_bg)
            try:
                tip.attributes("-topmost", True)
                if os.name == "nt":
                    tip.wm_attributes("-transparentcolor", magic_bg)
            except Exception:
                pass
            tk.Label(
                tip,
                text="Ciallo～(∠・ω< )⌒☆",
                bg=magic_bg,
                fg=random.choice(CIALLO_COLORS),
                font=(FONT_CN, 12, "bold"),
                bd=0,
                highlightthickness=0,
            ).pack()
            x = event.x_root + 8
            y = event.y_root - 12
            tip.geometry(f"+{x}+{y}")
            steps = 18

            def drift(step=0):
                if step >= steps:
                    tip.destroy()
                    return
                tip.geometry(f"+{x + step * 3}+{y - step * 2}")
                self.root.after(28, lambda: drift(step + 1))

            drift()
        except Exception:
            pass

    def _create_tree(self, parent, columns, style="Treeview"):
        body = tk.Frame(parent, bg=PANEL)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 2))
        tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse", style=style)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)
        return tree

    def _load_history(self):
        if not HISTORY_FILE.exists():
            return {}
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_history(self):
        try:
            HISTORY_FILE.write_text(json.dumps(self.history, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"保存历史记录失败：{exc}")

    def _history_for(self, task_id):
        return self.history.setdefault(task_id, {})

    def _record_task_result(self, task_id, ok, message=""):
        record = self._history_for(task_id)
        record["last_status"] = "完成" if ok else "失败"
        record["last_message"] = message
        if ok:
            record["last_success"] = _now_text()
        else:
            record["last_failure"] = _now_text()
        self._save_history()
        self._refresh_overview()

    def _last_run_text(self, task_id):
        record = self.history.get(task_id, {})
        if record.get("last_status") == "失败" and record.get("last_failure"):
            return "失败 " + _display_time(record.get("last_failure"))
        if record.get("last_success"):
            return _display_time(record.get("last_success"))
        if record.get("last_failure"):
            return "失败 " + _display_time(record.get("last_failure"))
        return "从未"

    def _load_task_settings(self):
        if not SETTINGS_FILE.exists():
            return {}
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_task_settings(self):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(self.task_settings, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_task_catalog(self):
        catalog = {}
        for task in AVAILABLE_TASKS:
            task_id = str(task.get("id") or task.get("name") or "")
            if not task_id:
                continue
            custom = self.task_settings.get(task_id, {})
            script_path = custom.get("script_path") or task.get("path", "")
            # paths 声明来自任务定义，具体值来自用户配置（task_settings[id].paths）。
            custom_paths = custom.get("paths", {}) or {}
            paths = []
            for p in task.get("paths", []):
                key = p.get("key", "")
                paths.append({
                    "key": key,
                    "label": p.get("label", key),
                    "value": custom_paths.get(key, "") or "",
                })
            catalog[task_id] = {
                "id": task_id,
                "icon": task.get("icon", ""),
                "name": task.get("name", task_id),
                "description": task.get("description", ""),
                "path": script_path,
                "args": task.get("args", ""),
                "workdir": str(Path(script_path).parent) if script_path else task.get("workdir", ""),
                "paths": paths,
                # 向后兼容旧 target_path：取第一个 path 的值。
                "target_path": paths[0]["value"] if paths else "",
            }
        return catalog

    def _reload_catalog(self):
        self.task_catalog = self._build_task_catalog()
        self._refresh_all()
        self._refresh_overview()
        self._refresh_background_panel()
        self._refresh_timeline()
        self._log("已刷新任务列表。")

    def _open_task_settings(self):
        task_id = self._selected_catalog_task_id()
        if not task_id:
            queue_index = self._selected_queue_index()
            if queue_index is not None and 0 <= queue_index < len(self.queue):
                task_id = self.queue[queue_index].get("task_id")
        if not task_id:
            messagebox.showinfo(APP_TITLE, "请先在左侧可用任务或右侧运行队列里选择一个任务。")
            return
        task = self.task_catalog.get(task_id)
        if not task:
            return

        win = tk.Toplevel(self.root)
        win.title(f"任务设置 - {task.get('name', task_id)}")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        try:
            win.tk.call("tk", "scaling", self.root.tk.call("tk", "scaling"))
        except Exception:
            pass

        title_text = f"{task.get('icon', '⚙')}   {task.get('name', task_id)}"
        tk.Label(win, text=title_text, bg=BG, fg=TEXT, font=(FONT_CN, 13, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(14, 4))
        if task.get("description"):
            tk.Label(win, text=task.get("description"), bg=BG, fg=MUTED, font=(FONT_CN, 9), wraplength=520, justify=tk.LEFT).grid(row=1, column=0, columnspan=3, sticky="w", padx=14, pady=(0, 8))

        label_opts = {"bg": BG, "fg": MUTED, "font": (FONT_CN, 10)}
        entry_opts = {"bg": FIELD_BG, "fg": TEXT, "insertbackground": TEXT, "relief": tk.FLAT, "font": (FONT_CN, 10), "width": 58, "highlightthickness": 1, "highlightbackground": BORDER, "highlightcolor": ACCENT}

        row = 2

        # 任务脚本位置
        script_var = tk.StringVar(value=task.get("path", ""))

        def choose_script():
            path = filedialog.askopenfilename(title="选择任务脚本", filetypes=[("Python 脚本", "*.py"), ("所有文件", "*.*")])
            if path:
                script_var.set(path)

        tk.Label(win, text="任务脚本位置", **label_opts).grid(row=row, column=0, sticky="w", padx=14, pady=(4, 3))
        row += 1
        tk.Entry(win, textvariable=script_var, **entry_opts).grid(row=row, column=0, columnspan=2, sticky="we", padx=14)
        RoundedButton(win, text="选择", icon="…", command=choose_script).grid(row=row, column=2, padx=(0, 14))
        row += 1

        # 各外部路径（按任务声明动态渲染）。填目录或 exe/lnk 均可，留空则脚本用内置默认。
        path_vars = {}
        for p in task.get("paths", []):
            key = p.get("key", "")
            plabel = p.get("label", key)
            var = tk.StringVar(value=p.get("value", ""))
            path_vars[key] = var
            tk.Label(win, text=plabel, **label_opts).grid(row=row, column=0, sticky="w", padx=14, pady=(10, 3))
            row += 1
            tk.Entry(win, textvariable=var, **entry_opts).grid(row=row, column=0, columnspan=2, sticky="we", padx=14)

            def _choose(_var=var, _title=plabel):
                path = filedialog.askopenfilename(title=_title, filetypes=[("程序/快捷方式", "*.exe *.lnk *.bat *.cmd"), ("所有文件", "*.*")])
                if path:
                    _var.set(path)

            RoundedButton(win, text="选择", icon="…", command=_choose).grid(row=row, column=2, padx=(0, 14))
            row += 1

        def save():
            self.task_settings[task_id] = {
                "script_path": script_var.get().strip(),
                "paths": {k: v.get().strip() for k, v in path_vars.items()},
            }
            self._save_task_settings()
            self.task_catalog = self._build_task_catalog()
            self._refresh_all()
            self._log(f"已保存任务设置：{task.get('name', task_id)}")
            win.destroy()

        def reset():
            if task_id in self.task_settings:
                del self.task_settings[task_id]
            self._save_task_settings()
            self.task_catalog = self._build_task_catalog()
            self._refresh_all()
            self._log(f"已恢复默认任务设置：{task.get('name', task_id)}")
            win.destroy()

        buttons = tk.Frame(win, bg=BG)
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", padx=14, pady=14)
        row += 1
        RoundedButton(buttons, text="恢复默认", icon="↺", command=reset).pack(side=tk.LEFT, padx=(0, 8))
        RoundedButton(buttons, text="保存", icon="✓", variant="accent", command=save).pack(side=tk.LEFT)

        win.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _add_selected_to_queue(self, event=None):
        task_id = self._selected_catalog_task_id()
        if not task_id:
            if not self.task_catalog:
                messagebox.showinfo(APP_TITLE, "当前还没有可用任务。后续你让我新增任务后，这里会出现任务。")
            else:
                messagebox.showinfo(APP_TITLE, "请先在左侧选择一个任务。")
            return
        self.queue.append({"task_id": task_id, "status": "等待"})
        self._refresh_queue()
        self._refresh_overview()
        self._save_config()
        self._select_queue_index(len(self.queue) - 1)

    def _selected_catalog_task_id(self):
        selected = self.catalog_tree.selection()
        if not selected:
            return None
        return selected[0]

    def _selected_queue_index(self):
        selected = self.queue_tree.selection()
        if not selected:
            return None
        return int(selected[0])

    def _select_queue_index(self, index):
        if 0 <= index < len(self.queue):
            item = str(index)
            self.queue_tree.selection_set(item)
            self.queue_tree.focus(item)
            self.queue_tree.see(item)

    def _move_up(self):
        index = self._selected_queue_index()
        if index is None or index == 0 or self.running:
            return
        self.queue[index - 1], self.queue[index] = self.queue[index], self.queue[index - 1]
        self._refresh_queue()
        self._refresh_overview()
        self._save_config()
        self._select_queue_index(index - 1)

    def _move_down(self):
        index = self._selected_queue_index()
        if index is None or index >= len(self.queue) - 1 or self.running:
            return
        self.queue[index + 1], self.queue[index] = self.queue[index], self.queue[index + 1]
        self._refresh_queue()
        self._refresh_overview()
        self._save_config()
        self._select_queue_index(index + 1)

    def _remove_from_queue(self, event=None):
        index = self._selected_queue_index()
        if index is None:
            return
        if self.running:
            messagebox.showinfo(APP_TITLE, "任务正在运行，请先停止再移除队列项。")
            return
        del self.queue[index]
        self._refresh_queue()
        self._refresh_overview()
        self._save_config()
        if self.queue:
            self._select_queue_index(min(index, len(self.queue) - 1))

    def _clear_queue(self):
        if self.running:
            return
        self.queue.clear()
        self._refresh_queue()
        self._refresh_overview()
        self._save_config()

    def _clear_status(self):
        if self.running:
            return
        for item in self.queue:
            item["status"] = "等待"
        self._refresh_queue()
        self._refresh_overview()
        self._save_config()

    def _rerun_failed_tasks(self):
        if self.running:
            messagebox.showinfo(APP_TITLE, "任务正在运行，请等这轮结束后再重跑失败项。")
            return
        failed_indexes = [i for i, item in enumerate(self.queue) if item.get("status", "").startswith("失败")]
        if not failed_indexes:
            messagebox.showinfo(APP_TITLE, "当前队列里没有失败任务。")
            return
        for index in failed_indexes:
            self.queue[index]["status"] = "等待"
        self._refresh_queue()
        self._refresh_overview()
        self._save_config()
        self._log(f"已准备重跑 {len(failed_indexes)} 个失败任务。")
        self._run_indexes(failed_indexes)

    def _health_check(self):
        lines = ["========== 任务体检 =========="]
        ok_count = 0
        bad_count = 0
        for task_id, task in self.task_catalog.items():
            name = task.get("name", task_id)
            path = task.get("path", "")
            target = task.get("target_path", "")
            task_ok = True
            if path and Path(path).exists():
                try:
                    if Path(path).suffix.lower() == ".py":
                        py_compile.compile(path, doraise=True)
                    lines.append(f"✓ {name}：脚本正常")
                except Exception as exc:
                    task_ok = False
                    lines.append(f"✕ {name}：脚本语法异常 - {exc}")
            else:
                task_ok = False
                lines.append(f"✕ {name}：找不到脚本 {path}")
            if target:
                if Path(target).exists():
                    lines.append(f"  ✓ 目标路径正常：{target}")
                else:
                    task_ok = False
                    lines.append(f"  ✕ 目标路径不存在：{target}")
            if task_ok:
                ok_count += 1
            else:
                bad_count += 1
        lines.append(f"体检完成：正常 {ok_count}，异常 {bad_count}")
        for line in lines:
            self._log(line)
        messagebox.showinfo(APP_TITLE, f"体检完成：正常 {ok_count}，异常 {bad_count}\n详情已写入运行日志。")

    def _start_run(self):
        if not self.queue:
            messagebox.showinfo(APP_TITLE, "运行队列为空，请先从左侧任务列表加入任务。")
            return
        indexes = list(range(len(self.queue)))
        self._run_indexes(indexes)

    def _run_selected_queue_item(self, event=None):
        index = self._selected_queue_index()
        if index is None:
            messagebox.showinfo(APP_TITLE, "请先在运行队列里选择一个任务。")
            return
        self._run_indexes([index])

    def _run_indexes(self, indexes):
        if self.running:
            messagebox.showinfo(APP_TITLE, "任务正在运行中，请等待结束或点击停止。")
            return
        self.running = True
        self.stop_requested = False
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        # 时间线保留整个会话累积（“今日”），后台监控标记按本次运行重置。
        self.background_tasks = {}
        self._refresh_timeline()
        self._refresh_background_panel()
        self._refresh_overview()
        self._add_timeline("开始运行任务队列")
        self._set_status("运行中")
        self._log("\n========== 开始运行任务队列 ==========")
        worker = threading.Thread(target=self._worker_run, args=(indexes,), daemon=True)
        worker.start()

    def _stop_run(self):
        if not self.running:
            return
        self.stop_requested = True
        self._set_status("正在停止...")
        self._log("收到停止请求：当前任务会被终止，后续任务不会继续运行。")
        if self.current_process and self.current_process.poll() is None:
            try:
                # 子任务还会 fork 出 MaaEnd、终末地等。/T 把整个进程树一起带走。
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(self.current_process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    self.current_process.terminate()
            except Exception as exc:
                self._log(f"终止进程失败：{exc}")

    def _register_global_hotkey(self):
        """注册全局热键 F12 用于随时停止当前任务。"""
        if os.name != "nt":
            self._log("当前系统不是 Windows，跳过全局热键注册。")
            return
        self._hotkey_stop_event = threading.Event()
        thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        thread.start()

    def _hotkey_loop(self):
        try:
            user32 = ctypes.windll.user32
            MOD_ALT = 0x0001
            MOD_CONTROL = 0x0002
            MOD_NOREPEAT = 0x4000
            VK_F12 = 0x7B
            VK_PAUSE = 0x13
            hotkey_id = 1
            hotkey_candidates = [
                ("F12", MOD_NOREPEAT, VK_F12),
                ("Ctrl+Alt+F12", MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_F12),
                ("Pause/Break", MOD_NOREPEAT, VK_PAUSE),
            ]
            registered_name = None
            for name, modifiers, vk in hotkey_candidates:
                if user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
                    registered_name = name
                    break
            if not registered_name:
                self.root.after(0, lambda: self._log(
                    "注册全局停止热键失败（F12、Ctrl+Alt+F12、Pause 都被占用），可继续用界面上的“停止”按钮。"))
                return
            self._hotkey_name = registered_name
            self.root.after(0, lambda: self._log(
                f"已注册全局停止热键 {registered_name}：任务运行时可立即停止。"))

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", ctypes.c_void_p),
                    ("message", ctypes.c_uint),
                    ("wParam", ctypes.c_void_p),
                    ("lParam", ctypes.c_void_p),
                    ("time", ctypes.c_uint),
                    ("pt_x", ctypes.c_long),
                    ("pt_y", ctypes.c_long),
                ]

            msg = MSG()
            WM_HOTKEY = 0x0312
            try:
                while True:
                    ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if ret == 0 or ret == -1:
                        break
                    if msg.message == WM_HOTKEY and int(msg.wParam or 0) == hotkey_id:
                        self.root.after(0, self._on_hotkey_stop)
            finally:
                user32.UnregisterHotKey(None, hotkey_id)
        except Exception as exc:
            self.root.after(0, lambda: self._log(f"全局热键监听异常：{exc}"))

    def _on_hotkey_stop(self):
        if not self.running:
            self._log("按下 F12，但当前没有任务在运行。")
            return
        self._log("收到全局热键 F12：开始停止任务。")
        self._stop_run()

    def _worker_run(self, indexes):
        try:
            for index in indexes:
                if self.stop_requested:
                    break
                if index >= len(self.queue):
                    continue
                queue_item = self.queue[index]
                task = self.task_catalog.get(queue_item.get("task_id"))
                self.current_queue_index = index
                if not task:
                    self._update_queue_status(index, "任务不存在")
                    self._log(f"找不到任务：{queue_item.get('task_id')}")
                    self._record_task_result(queue_item.get("task_id", ""), False, "任务不存在")
                    if not self.continue_on_error_var.get():
                        break
                    continue
                self._update_queue_status(index, "运行中")
                running_tip = _task_persona(task.get("id", ""), "running", "自动化运行中，请暂时不要操作鼠标键盘。")
                self._set_stage(running_tip)
                self._log(f"\n>>> 开始：{task.get('name')}\n    {task.get('path')}")
                return_code = self._run_task(task)
                if self.stop_requested:
                    self._update_queue_status(index, "已停止")
                    self._record_task_result(task.get("id", ""), False, "已停止")
                    break
                if return_code == 0:
                    self._update_queue_status(index, "完成")
                    done_tip = _task_persona(task.get("id", ""), "done", "任务完成")
                    self._record_task_result(task.get("id", ""), True, done_tip)
                    self._log(f"<<< 完成：{task.get('name')} · {done_tip}")
                else:
                    self._update_queue_status(index, f"失败({return_code})")
                    failed_tip = _task_persona(task.get("id", ""), "failed", "任务失败")
                    self._record_task_result(task.get("id", ""), False, failed_tip)
                    self._log(f"<<< 失败：{task.get('name')}，退出码 {return_code} · {failed_tip}")
                    if not self.continue_on_error_var.get():
                        self._log("已停止队列：如需失败后继续，请勾选“某个任务失败后继续下一个”。")
                        break
                time.sleep(0.2)
        finally:
            self.current_process = None
            self.current_queue_index = -1
            self.running = False
            self.stop_requested = False
            self.root.after(0, self._run_finished)

    def _run_task(self, task):
        path = task.get("path", "")
        if not path:
            self._log("这个任务还没有配置脚本路径。")
            return 1
        if not Path(path).exists():
            self._log(f"脚本文件不存在：{path}")
            return 1
        command = self._build_command(path, task.get("args", ""))
        workdir = task.get("workdir") or str(Path(path).parent)
        try:
            self.current_process = subprocess.Popen(
                command,
                cwd=workdir or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8-sig",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                env={
                    **os.environ,
                    "PYTHONIOENCODING": "utf-8",
                    "TASKRUNNER_TASK_ID": task.get("id", ""),
                    "TASKRUNNER_SCRIPT_PATH": task.get("path", ""),
                    "TASKRUNNER_TARGET_PATH": task.get("target_path", ""),
                    **{
                        f"TASKRUNNER_PATH_{p.get('key', '').upper()}": p.get("value", "")
                        for p in task.get("paths", [])
                    },
                },
            )
            for line in self.current_process.stdout:
                self._log(line.rstrip())
            return self.current_process.wait()
        except FileNotFoundError:
            self._log("找不到脚本或运行程序，请检查路径。")
            return 127
        except Exception as exc:
            self._log(f"运行异常：{exc}")
            return 1

    def _build_command(self, path, args):
        suffix = Path(path).suffix.lower()
        split_args = self._split_args(args)
        if suffix == ".py":
            python_exe = Path(sys.executable)
            if python_exe.name.lower() == "pythonw.exe":
                normal_python = python_exe.with_name("python.exe")
                if normal_python.exists():
                    python_exe = normal_python
            return [str(python_exe), path] + split_args
        if suffix == ".ps1":
            return ["powershell", "-ExecutionPolicy", "Bypass", "-File", path] + split_args
        if suffix in (".bat", ".cmd"):
            return ["cmd", "/c", path] + split_args
        return [path] + split_args

    def _split_args(self, args):
        if not args:
            return []
        try:
            import shlex

            return shlex.split(args, posix=False)
        except Exception:
            return args.split()

    def _run_finished(self):
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self._set_status("就绪")
        self._set_stage("就绪")
        self._add_timeline("任务队列结束")
        self._save_config()
        self._log("========== 任务队列结束 ==========\n")

    def _update_queue_status(self, index, status):
        def update():
            if 0 <= index < len(self.queue):
                self.queue[index]["status"] = status
                self._refresh_queue()
                self._select_queue_index(index)

        self.root.after(0, update)

    def _refresh_all(self):
        self._refresh_catalog()
        self._refresh_queue()
        self._refresh_overview()
        self._refresh_background_panel()
        self._refresh_timeline()

    def _refresh_catalog(self):
        for item in self.catalog_tree.get_children():
            self.catalog_tree.delete(item)
        for task_id, task in self.task_catalog.items():
            icon = task.get("icon", "")
            name = task.get("name", "")
            label = f"{icon}   {name}" if icon else name
            self.catalog_tree.insert(
                "",
                tk.END,
                iid=task_id,
                values=(label,),
            )

    def _refresh_queue(self):
        selected = self._selected_queue_index()
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        for index, queue_item in enumerate(self.queue):
            task = self.task_catalog.get(queue_item.get("task_id"))
            if task:
                icon = task.get("icon", "")
                base_name = task.get("name", queue_item.get("task_id", ""))
                name = f"{icon}   {base_name}" if icon else base_name
            else:
                name = f"⚠   任务不存在：{queue_item.get('task_id')}"
            status_raw = queue_item.get("status", "等待")
            status_text, status_tag = _status_decorate(status_raw)
            last_run = self._last_run_text(queue_item.get("task_id", ""))
            self.queue_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(name, status_text, last_run),
                tags=(status_tag,),
            )
        if selected is not None and selected < len(self.queue):
            self._select_queue_index(selected)

    def _add_timeline(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.timeline.append(f"{stamp}  {message}")
        if len(self.timeline) > 200:
            self.timeline = self.timeline[-200:]
        self._refresh_timeline()

    def _refresh_timeline(self):
        if not hasattr(self, "timeline_text"):
            return

        def update():
            self.timeline_text.delete("1.0", tk.END)
            if not self.timeline:
                self.timeline_text.insert(tk.END, "今天还没有关键节点，等队列开始打卡。")
            else:
                self.timeline_text.insert(tk.END, "\n".join(self.timeline[-80:]))
            self.timeline_text.see(tk.END)

        self.root.after(0, update)

    def _refresh_overview(self):
        if not hasattr(self, "overview_var"):
            return
        total = len(self.queue)
        done = sum(1 for item in self.queue if item.get("status", "").startswith("完成"))
        failed = sum(1 for item in self.queue if item.get("status", "").startswith("失败"))
        running_item = next((item for item in self.queue if item.get("status", "").startswith("运行中")), None)
        if running_item:
            task_id = running_item.get("task_id", "")
            stage = _task_persona(task_id, "running", "自动化运行中，请暂时不要操作鼠标键盘。")
        elif total and done == total:
            stage = "今日份电子打工结束，可以安心摸鱼了。"
        elif failed:
            stage = f"有 {failed} 个任务翻车，点“重跑失败”可以只补失败项。"
        else:
            stage = "当前卡点：" + self.current_stage
        self.root.after(0, lambda: self.overview_var.set(f"今日进度：{done} / {total}    失败：{failed}"))
        self.root.after(0, lambda: self.stage_var.set(stage))

    def _refresh_background_panel(self):
        if not hasattr(self, "background_var"):
            return
        active = [v for v in self.background_tasks.values() if v.get("status") == "运行中"]
        if active:
            lines = [f"⏳ {item.get('name', '后台任务')}：{item.get('stage', '等待完成')}" for item in active]
            text = "\n".join(lines)
        elif self.background_tasks:
            last = list(self.background_tasks.values())[-1]
            text = f"{last.get('status_icon', '✓')} {last.get('name', '后台任务')}：{last.get('stage', '已结束')}"
        else:
            text = "暂无后台监控。MAA 连接成功后会在这里继续盯完成。"
        self.root.after(0, lambda: self.background_var.set(text))

    def _set_stage(self, text):
        self.current_stage = text
        self._refresh_overview()

    def _classify_log_tag(self, message):
        for tag in ("error", "success", "warning", "info"):
            if any(keyword in message for keyword in LOG_KEYWORDS[tag]):
                return tag
        return "muted" if message.startswith("====") else None

    def _consume_log_signal(self, message):
        if ">>> 开始：" in message:
            name = message.split("：", 1)[-1].strip()
            self._add_timeline(f"开始任务：{name}")
            self._set_stage(f"正在运行：{name}")
        elif "<<< 完成：" in message:
            name = message.split("：", 1)[-1].strip()
            self._add_timeline(f"完成任务：{name}")
        elif "<<< 失败：" in message:
            name = message.split("：", 1)[-1].split("，", 1)[0].strip()
            self._add_timeline(f"任务失败：{name}")
            self._log_friendly_hint(message)
        elif any(marker in message for marker in BACKGROUND_MARKERS):
            self._track_background_signal(message)
        elif "等待 MAA 窗口" in message:
            self._set_stage("等待 MAA 窗口出现")
        elif "第 " in message and "点击 Link Start" in message:
            self._set_stage(message.strip())
        elif "等待识宝小助手窗口" in message:
            self._set_stage("等待识宝小助手窗口出现")
        elif "Ctrl+F1" in message:
            self._set_stage("发送 Ctrl+F1 启动 Maa_bbb")
        elif "超时" in message or "失败" in message or "找不到" in message:
            self._log_friendly_hint(message)

    def _log_friendly_hint(self, message):
        hint = _friendly_failure_hint(message)
        if hint:
            self._log_raw(f"建议：{hint}", "warning")

    def _track_background_signal(self, message):
        task_id = "maa_arknights_daily"
        name = self.task_catalog.get(task_id, {}).get("name", "MAA 明日方舟")
        item = self.background_tasks.setdefault(task_id, {"name": name})
        if "已启动后台 MAA 完成监控" in message or "开始等待" in message:
            item.update({"status": "运行中", "status_icon": "⏳", "stage": "等待全部任务完成"})
            self._add_timeline("MAA 转入后台监控")
        elif "检测到 MAA 所有任务完成" in message:
            item.update({"status": "完成", "status_icon": "✓", "stage": "后台已完成并关闭"})
            self._add_timeline("MAA 后台监控完成")
        elif "等待 MAA 完成超时" in message:
            item.update({"status": "失败", "status_icon": "✕", "stage": "后台等待超时"})
            self._add_timeline("MAA 后台监控超时")
        self._refresh_background_panel()

    def _log_raw(self, message, tag=None):
        def append():
            self.log_text.insert(tk.END, message + "\n", tag or ())
            self.log_text.see(tk.END)

        self.root.after(0, append)

    def _log(self, message):
        tag = self._classify_log_tag(message)
        self._consume_log_signal(message)
        self._log_raw(message, tag)

    def _set_status(self, text):
        prefix = "⟳" if "运行" in text else ("…" if "停止" in text else "●")
        self.root.after(0, lambda: self.status_var.set(f"  {prefix}  {text}"))

    def _load_config(self):
        if not CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            self.continue_on_error_var.set(bool(data.get("continue_on_error", False)))
            self.theme = data.get("theme", "dark")
            if "queue" in data:
                self.queue = data.get("queue", [])
            else:
                self.queue = []
            for item in self.queue:
                item.setdefault("status", "等待")
        except Exception as exc:
            messagebox.showwarning(APP_TITLE, f"读取配置失败：{exc}")

    def _save_config(self):
        data = {
            "continue_on_error": self.continue_on_error_var.get(),
            "theme": getattr(self, "theme", "dark"),
            "queue": self.queue,
        }
        try:
            CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"保存配置失败：{exc}")

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno(APP_TITLE, "任务还在运行，确定要停止并退出吗？"):
                return
            self._stop_run()
        self._save_config()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    ScriptRunnerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
