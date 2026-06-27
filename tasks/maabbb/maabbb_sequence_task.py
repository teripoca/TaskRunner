"""
Maabbb：崩三日常 任务脚本。

流程：
1. 启动 MFW.exe（Maa_bbb 的入口）。
2. 等待窗口标题包含 “识宝小助手” 的窗口出现，将其调到最前。
3. 先把识宝小助手窗口调到最前台，再用鼠标点“开始”按钮触发任务——
   之前用 Maa_bbb 自报的 Ctrl+F1 全局快捷键，但识宝小助手经常收不到、根本启动不了，
   所以改成和 MaaEnd 一样的做法：OCR 识别“开始”按钮点它，
   识别不到就用底部兜底坐标。点之前必须先把窗口拉到前台，点击才会落在对的窗口上。
4. 监控 debug/gui.log，确认日志显示“设备连接成功 / 执行任务:”——证明任务已经真正开始。
   （MFW 实际不输出“任务流程已启动”，2026-06-26 实测该词出现 0 次，曾导致永远判失败。）
5. 继续等待：MFW 跑完会执行“退出/关闭游戏”，崩坏3 游戏关闭即视为整体完成。
6. 关闭 MFW.exe，结束。
"""

import ctypes
import ctypes.wintypes
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
if os.name == "nt":
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# MaaFramework 识别点击驱动：OCR 找按钮替代硬编码坐标（maafw 不可用时降级为兜底坐标）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_common"))
try:
    from maa_driver import click_button as _maa_click_button
except Exception as _maa_exc:
    _maa_click_button = None
    print(f"[maa_driver] 加载失败，将只用兜底坐标：{_maa_exc}", flush=True)

_target = (os.environ.get("TASKRUNNER_PATH_DIR") or os.environ.get("TASKRUNNER_TARGET_PATH") or "").strip()
if _target:
    _target_path = Path(_target)
    if _target_path.is_file():
        MAABBB_EXE = _target_path
        MAABBB_DIR = _target_path.parent
    else:
        MAABBB_DIR = _target_path
        MAABBB_EXE = MAABBB_DIR / "MFW.exe"
else:
    MAABBB_DIR = Path(r"C:\Tools\Maa_bbb")
    MAABBB_EXE = MAABBB_DIR / "MFW.exe"
GUI_LOG = MAABBB_DIR / "debug" / "gui.log"

WINDOW_KEYWORDS = ["识宝小助手"]
GAME_WINDOW_REGEX = re.compile(r"崩坏3|崩坏3 Steam版|Honkai Impact 3|崩壊3rd")
GAME_PROCESS_NAMES = [
    "BH3.exe",
    "Honkai Impact 3.exe",
    "HonkaiImpact3.exe",
    "BH3Base.exe",
]
MAABBB_PROCESS_NAMES = ["MFW.exe"]

WINDOW_TIMEOUT_SECONDS = 240
START_DETECT_TIMEOUT_SECONDS = 240
START_HOTKEY_RETRY_SECONDS = 15
TASK_TIMEOUT_SECONDS = 8 * 60 * 60
POLL_SECONDS = 1

# 任务真正跑起来的日志标记（MFW 实际输出的；旧版写的“任务流程已启动”在日志里不存在）。
STARTED_MARKERS = [
    "设备连接成功",
    "执行任务:",
    "最快截图耗时",
]

FAILURE_MARKERS = [
    "任务流程错误",
    "启动任务流程失败",
    "任务流失败",
]


def log(message):
    print(message, flush=True)


def run_command(command, timeout=20):
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception:
        return None


def is_process_running(image_name):
    result = run_command(["tasklist", "/FI", f"IMAGENAME eq {image_name}"], timeout=10)
    if not result or not result.stdout:
        return False
    return image_name.lower() in result.stdout.lower()


def is_game_running():
    if any(is_process_running(name) for name in GAME_PROCESS_NAMES):
        return True
    # 进程名拿不准的情况下，再用窗口标题/类名兜底判断。
    return find_game_window_handle() != 0


def taskkill(image_name, tree=True):
    args = ["taskkill", "/IM", image_name, "/F"]
    if tree:
        args.insert(-1, "/T")
    run_command(args, timeout=10)


def close_maabbb():
    for name in MAABBB_PROCESS_NAMES:
        taskkill(name, tree=True)
    log("已关闭 MFW.exe。")


def close_game_if_running():
    closed_any = False
    for name in GAME_PROCESS_NAMES:
        if is_process_running(name):
            taskkill(name, tree=True)
            closed_any = True
    if closed_any:
        log("已强制关闭崩坏3 游戏进程。")


# ===== 日志读取 =====
# MFW 的 gui.log 是累积单文件，运行中可能被重写/缓冲，旧的 offset 增量读取不可靠
# （和 MAA 同一类问题）。改为读末尾窗口 + 时间戳过滤，只认本次启动后写入的行。


def _parse_log_time(line):
    """解析行首 [YYYY-MM-DD HH:MM:SS（兼容 ,ms），返回 datetime 或 None。"""
    m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def read_log_tail(n=500):
    """读取 GUI_LOG 末尾 n 行（从文件尾向前回读一块，不依赖 offset）。"""
    if not GUI_LOG.exists():
        return []
    try:
        size = GUI_LOG.stat().st_size
        with GUI_LOG.open("rb") as f:
            block = 16384
            data = b""
            pos = size
            while pos > 0:
                pos = max(0, pos - block)
                f.seek(pos)
                data = f.read(min(block, size - pos)) + data
                if data.count(b"\n") > n:
                    break
        text = data.decode("utf-8", errors="replace")
        return text.splitlines()[-n:]
    except OSError:
        return []


# ===== Windows 窗口/鼠标工具函数 =====


def _enum_windows_by_predicate(predicate):
    if os.name != "nt":
        return 0
    user32 = ctypes.windll.user32
    handles = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        cls_name = cls_buf.value
        if predicate(title, cls_name):
            handles.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return handles[0] if handles else 0


def find_maabbb_window():
    def pred(title, _cls):
        return any(k in title for k in WINDOW_KEYWORDS)

    return _enum_windows_by_predicate(pred)


def find_game_window_handle():
    def pred(title, cls):
        if GAME_WINDOW_REGEX.search(title or ""):
            return True
        return False

    return _enum_windows_by_predicate(pred)


def wait_for_maabbb_window():
    started_at = time.time()
    while time.time() - started_at < WINDOW_TIMEOUT_SECONDS:
        hwnd = find_maabbb_window()
        if hwnd:
            return hwnd
        time.sleep(2)
    return 0


def activate_window(hwnd):
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


# ===== 鼠标点击工具：把识宝小助手调到最前，再用鼠标点“开始”按钮 =====


def get_client_rect(hwnd):
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
    user32 = ctypes.windll.user32
    x = int(x)
    y = int(y)
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    abs_x = int(x * 65535 / max(screen_w - 1, 1))
    abs_y = int(y * 65535 / max(screen_h - 1, 1))
    user32.SetCursorPos(x, y)
    time.sleep(0.12)
    _send_mouse_input(abs_x, abs_y, 0x0001 | 0x8000)  # MOVE | ABSOLUTE，确保光标先就位
    time.sleep(0.08)
    _send_mouse_input(0, 0, 0x0002)  # LEFTDOWN
    time.sleep(0.08)
    _send_mouse_input(0, 0, 0x0004)  # LEFTUP
    time.sleep(0.2)


def find_green_button_center(rect):
    """截取识宝小助手客户区，找那块绿色的“开始”按钮，返回屏幕坐标中心。找不到返回 None。"""
    try:
        from PIL import ImageGrab
    except Exception as exc:
        log(f"无法导入 PIL.ImageGrab，改用固定坐标点击：{exc}")
        return None

    left, top, right, bottom = [int(v) for v in rect]
    image = ImageGrab.grab(bbox=(left, top, right, bottom)).convert("RGB")
    width, height = image.size

    mask = set()
    # 开始按钮在窗口下半部分，只扫下半部分，避开顶部标题/状态区。
    for y in range(int(height * 0.55), height):
        for x in range(width):
            r, g, b = image.getpixel((x, y))
            # MFW 的开始按钮是绿色：g 明显大于 r、b。
            if g >= 90 and g >= r + 25 and g >= b + 15:
                mask.add((x, y))

    seen = set()
    best = None
    for point in list(mask):
        if point in seen:
            continue
        stack = [point]
        seen.add(point)
        xs = []
        ys = []
        while stack:
            x, y = stack.pop()
            xs.append(x)
            ys.append(y)
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) in mask and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        area = len(xs)
        if area < 400:
            continue
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        if (x2 - x1 + 1) < 60 or (y2 - y1 + 1) < 22:
            continue
        # 偏好靠近窗口底部、横向居中的大绿块。
        score = area + y2 * 2 - abs(((x1 + x2) / 2) - width * 0.5)
        if best is None or score > best[0]:
            best = (score, x1, y1, x2, y2, area)

    if not best:
        return None
    _, x1, y1, x2, y2, area = best
    cx = left + (x1 + x2) / 2
    cy = top + (y1 + y2) / 2
    log(f"识别到绿色开始按钮：窗口内({x1},{y1})-({x2},{y2})，面积 {area}，屏幕中心({int(cx)},{int(cy)})")
    return cx, cy


def click_start_button(hwnd):
    """把识宝小助手调到最前，再用鼠标点「开始」按钮启动任务（OCR 识别定位）。"""
    if _maa_click_button:
        return _maa_click_button(hwnd, "开始", (0.46, 0.67), log=log)

    # maa_driver 不可用时：绿色按钮颜色识别 + 底部兜底坐标（旧逻辑）。
    activate_window(hwnd)
    time.sleep(0.4)
    rect = get_client_rect(hwnd)
    if not rect:
        log("无法获取识宝小助手客户区位置，跳过本次点击。")
        return False

    center = find_green_button_center(rect)
    if center:
        x, y = center
        click_screen(x, y)
        log(f"已点击识别到的绿色开始按钮：({int(x)}, {int(y)})")
        return True

    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    for x, y in [
        (left + width * 0.46, top + height * 0.67),
        (left + width * 0.78, top + height * 0.90),
        (left + width * 0.85, top + height * 0.90),
    ]:
        click_screen(x, y)
        log(f"未识别到绿色按钮，已点击备用坐标（底部开始按钮区域）：({int(x)}, {int(y)})")
        time.sleep(0.4)
    return True


def start_maabbb_process():
    if not MAABBB_EXE.exists():
        raise FileNotFoundError(f"找不到 MFW.exe：{MAABBB_EXE}")
    log(f"启动 Maabbb：{MAABBB_EXE}")
    subprocess.Popen(
        [str(MAABBB_EXE)],
        cwd=str(MAABBB_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def trigger_start(hwnd):
    log("点击识宝小助手“开始”按钮启动任务（鼠标点击，不再用快捷键）。")
    click_start_button(hwnd)


# ===== 主流程 =====


def wait_for_started():
    """点击“开始”，等日志确认任务真的跑起来了。

    读末尾窗口 + 时间戳过滤（只认本次启动后写入的行），避免 offset 错位和历史标记误命中。
    """
    started_dt = datetime.now()
    started_at = started_dt.timestamp()
    last_press_at = 0.0
    attempts = 0
    while True:
        now = time.time()
        hwnd = find_maabbb_window()
        if hwnd and now - last_press_at >= START_HOTKEY_RETRY_SECONDS:
            attempts += 1
            last_press_at = now
            log(f"第 {attempts} 次触发开始任务。")
            trigger_start(hwnd)

        for line in read_log_tail(500):
            t = _parse_log_time(line)
            if t and t < started_dt - timedelta(seconds=30):
                continue
            if any(k in line for k in ("任务流程", "开始任务", "启动任务", "执行任务", "设备连接", "空闲")):
                log(f"[gui.log] {line}")
            if any(marker in line for marker in STARTED_MARKERS):
                log("检测到日志：设备连接成功 / 执行任务，任务已启动。")
                return True
            if any(marker in line for marker in FAILURE_MARKERS):
                log("检测到日志：任务流程启动失败。")
                return False

        if now - started_at > START_DETECT_TIMEOUT_SECONDS:
            log("等待 Maabbb 任务流程启动超时。")
            return False
        time.sleep(POLL_SECONDS)


def wait_for_all_done_and_game_closed():
    """任务已启动后，等 MFW 跑完执行“退出/关闭游戏”、崩坏3 游戏关闭，才算整体完成。

    MFW 没有“所有任务都已完成”这类文本标记（实测 0 次），所以靠游戏关闭判定。
    """
    log("等待 Maabbb 全部任务完成（检测崩坏3 游戏关闭）。")
    started_dt = datetime.now()
    started_at = time.time()
    saw_game_running = is_game_running()

    while True:
        now = time.time()
        for line in read_log_tail(500):
            t = _parse_log_time(line)
            if t and t < started_dt - timedelta(seconds=30):
                continue
            if any(marker in line for marker in FAILURE_MARKERS):
                log("检测到日志：任务流程出错。")
                return False

        if is_game_running():
            saw_game_running = True
        elif saw_game_running:
            log("崩坏3 游戏已关闭（MFW 执行了退出/关闭游戏），整体任务完成。")
            return True

        if now - started_at > TASK_TIMEOUT_SECONDS:
            log("等待 Maabbb 全部任务完成超时。")
            return False
        time.sleep(POLL_SECONDS)


def main():
    start_maabbb_process()
    log(f"等待识宝小助手窗口出现，最多 {WINDOW_TIMEOUT_SECONDS} 秒...")
    hwnd = wait_for_maabbb_window()
    if not hwnd:
        log("等待识宝小助手窗口超时。")
        close_maabbb()
        return 1

    log("识宝小助手窗口已出现，调到最前台并等待 5 秒让界面加载。")
    activate_window(hwnd)
    time.sleep(5)

    if not wait_for_started():
        log("Maabbb 任务未能正常启动。")
        close_maabbb()
        return 1

    ok = wait_for_all_done_and_game_closed()
    if ok:
        close_maabbb()
        log("Maabbb：崩三日常任务整体完成。")
        return 0

    log("Maabbb 任务未成功完成。")
    close_maabbb()
    return 1


if __name__ == "__main__":
    sys.exit(main())
