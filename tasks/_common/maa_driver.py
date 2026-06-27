"""
MaaFramework 识别点击驱动（共享模块）。

解决各任务脚本"靠硬编码比例坐标点按钮、点不准"的问题：
用 MaaFramework 的 OCR 在助手窗口截图里识别按钮文字 → 拿到按钮在客户区的
box [x,y,w,h] → 换算成屏幕坐标 → 用【真实前台鼠标】点击中心。

满足用户硬约束：一定是鼠标点击，点击之前先把窗口切到前台。
识别失败时回落到原来的比例坐标兜底（不会比现状更差）。

只做"识别 + 点击"。窗口查找、日志监控、收尾等仍由各任务脚本自己负责。
任务脚本用法：
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_common"))
    from maa_driver import find_window, click_button, recognize
"""

import ctypes
import ctypes.wintypes
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if os.name == "nt":
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from maa.toolkit import Toolkit
from maa.controller import (
    Win32Controller,
    MaaWin32ScreencapMethodEnum,
    MaaWin32InputMethodEnum,
)
from maa.resource import Resource
from maa.tasker import Tasker

# 路径：本文件在 tasks/_common/ 下，往上两层是 TaskRunner 根。
ROOT = Path(__file__).resolve().parents[2]
RESOURCE = ROOT / "resource"          # image/ model/ocr/ pipeline/
USER = ROOT / ".maafw"                # Maa 配置/日志目录

_inited = False
_resource = None


def _init():
    """初始化 Toolkit（只需一次）。"""
    global _inited
    if _inited:
        return
    USER.mkdir(parents=True, exist_ok=True)
    Toolkit.init_option(str(USER))
    _inited = True


def _get_resource():
    """复用同一个 Resource（OCR 模型只加载一次）。

    默认强制 CPU 推理（use_cpu）。原因：DirectML 在多 GPU 笔记本上枚举 DXGI 适配器
    时会偶发访问冲突（0xC0000005），整个进程直接崩溃——2026-06-27 的 MAA 任务就是
    在 OCR/DML 初始化阶段崩的，连 Link Start 都没点到就死了（同一段代码 30 分钟后
    跑 march7th/maaend 又没事，典型的 native flake）。CPU 推理对“识别几个按钮”绰绰
    有余，且彻底绕开这条崩溃路径，精度不变。
    想切回 GPU（DirectML）提速：设环境变量 TASKRUNNER_MAA_GPU=1。
    """
    global _resource
    if _resource is None:
        _init()
        _resource = Resource()
        if (os.environ.get("TASKRUNNER_MAA_GPU") or "").strip() not in ("1", "true", "True", "TRUE"):
            _resource.use_cpu()
        _resource.post_bundle(str(RESOURCE)).wait()
    return _resource


# ===== Windows 窗口/鼠标工具（从各任务脚本沉淀下来的已验证实现） =====


def activate_window(hwnd):
    """把窗口拉到最前台（满足"点击前先切前台"的约束）。"""
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SW_RESTORE = 9
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.2)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.4)
    return True


def get_client_rect(hwnd):
    """返回客户区在屏幕上的 (left, top, right, bottom)。"""
    user32 = ctypes.windll.user32
    rect = ctypes.wintypes.RECT()
    point = ctypes.wintypes.POINT(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y, point.x + rect.right, point.y + rect.bottom


def _send_mouse_input(dx, dy, flags):
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", INPUT_UNION)]

    inp = INPUT(type=0, u=INPUT_UNION(mi=MOUSEINPUT(dx, dy, 0, flags, 0, 0)))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def click_screen(x, y):
    """真实鼠标点击屏幕坐标 (SetCursorPos + SendInput 左键)。"""
    user32 = ctypes.windll.user32
    x = int(x)
    y = int(y)
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    abs_x = int(x * 65535 / max(screen_w - 1, 1))
    abs_y = int(y * 65535 / max(screen_h - 1, 1))
    user32.SetCursorPos(x, y)
    time.sleep(0.12)
    _send_mouse_input(abs_x, abs_y, 0x0001 | 0x8000)  # MOVE | ABSOLUTE
    time.sleep(0.08)
    _send_mouse_input(0, 0, 0x0002)                    # LEFTDOWN
    time.sleep(0.08)
    _send_mouse_input(0, 0, 0x0004)                    # LEFTUP
    time.sleep(0.2)


# ===== 识别 + 点击 =====


def find_window(*title_keywords, class_keyword=None):
    """用 MaaToolkit 按窗口标题关键词找窗口，返回 hwnd(int)，找不到返回 0。

    标题命中任一关键词即可；class_keyword 可选，用于进一步过滤（例如区分同 class 的窗口）。
    """
    _init()
    for w in Toolkit.find_desktop_windows():
        title = w.window_name or ""
        cls = w.class_name or ""
        if class_keyword and class_keyword not in cls:
            continue
        if any(k in title for k in title_keywords):
            return int(w.hwnd) if w.hwnd else 0
    return 0


def recognize(hwnd, expected, roi=None, timeout_ms=20000):
    """OCR 识别按钮文字，返回命中的 box (x, y, w, h)（客户区像素），未命中返回 None。

    expected: 按钮上的文字（如 "日常"、"开始"、"Link Start!"）。
    roi: 可选，[x, y, w, h] 客户区像素，限定搜索区域；None 为整窗。
    """
    _init()
    if not hwnd:
        return None
    ctrl = Win32Controller(
        hWnd=hwnd,
        screencap_method=MaaWin32ScreencapMethodEnum.Background,
        mouse_method=MaaWin32InputMethodEnum.PostMessage,      # 只识别不点击，后台方式不抢前台
        keyboard_method=MaaWin32InputMethodEnum.PostMessage,
    )
    ctrl.set_screenshot_use_raw_size(True)                      # 原始分辨率，坐标才和客户区对得上
    ctrl.post_connection().wait()

    tk = Tasker()
    tk.bind(_get_resource(), ctrl)

    node = {"recognition": "OCR", "expected": [expected], "action": "DoNothing", "timeout": timeout_ms}
    if roi:
        node["roi"] = roi
    detail = tk.post_task("FindBtn", {"FindBtn": node}).wait().get()
    for nid in getattr(detail, "node_id_list", None) or []:
        nd = tk.get_node_detail(nid)
        if nd and nd.recognition and nd.recognition.hit:
            box = nd.recognition.box
            if box:
                return (int(box[0]), int(box[1]), int(box[2]), int(box[3]))
    return None


def click_button(hwnd, expected, fallback_xy, roi=None, log=print, dry_run=False, pre_delay=0.4):
    """识别按钮并点击。

    hwnd: 目标窗口句柄。
    expected: 按钮文字。
    fallback_xy: (fx, fy) 比例(0~1)，识别失败时点的兜底坐标（相对客户区）。
    roi: 可选搜索区域 [x,y,w,h] 客户区像素。
    dry_run: True 时只识别并打印目标坐标，不真的点击（用于校验）。
    返回 True=识别命中并点击/校验；False=用了兜底坐标。
    """
    activate_window(hwnd)
    time.sleep(pre_delay)
    rect = get_client_rect(hwnd)
    if not rect:
        log("maa_driver: 拿不到客户区，无法点击。")
        return False
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top

    box = recognize(hwnd, expected, roi)
    if box:
        bx, by, bw, bh = box
        cx = left + bx + bw // 2
        cy = top + by + bh // 2
        log(f'maa_driver: OCR 识别到「{expected}」box={box} → 屏幕({cx},{cy})')
        if dry_run:
            return True
        click_screen(cx, cy)
        return True

    fx, fy = fallback_xy
    cx = int(left + width * fx)
    cy = int(top + height * fy)
    tag = "校验(未点击)" if dry_run else "点击"
    log(f'maa_driver: OCR 未识别「{expected}」，兜底比例({fx},{fy}) → 屏幕({cx},{cy}) {tag}')
    if dry_run:
        return False
    click_screen(cx, cy)
    return False
