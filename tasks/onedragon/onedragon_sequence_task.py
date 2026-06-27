import ctypes
import ctypes.wintypes
import os
import subprocess
import sys
import time
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
        ONEDRAGON_EXE = _target_path
        ONEDRAGON_DIR = _target_path.parent
    else:
        ONEDRAGON_DIR = _target_path
        ONEDRAGON_EXE = ONEDRAGON_DIR / "OneDragon-Launcher.exe"
else:
    ONEDRAGON_DIR = Path(r"C:\Tools\OneDragon-ZZZ")
    ONEDRAGON_EXE = ONEDRAGON_DIR / "OneDragon-Launcher.exe"
LOG_FILE = ONEDRAGON_DIR / ".log" / "log.txt"

GAME_PROCESS_NAMES = ["ZenlessZoneZero.exe"]

STARTUP_TIMEOUT_SECONDS = 300
START_BUTTON_RETRY_SECONDS = 10
START_DETECT_TIMEOUT_SECONDS = 240
TASK_TIMEOUT_SECONDS = 10 * 60 * 60
GAME_CLOSE_TIMEOUT_SECONDS = 20 * 60
POLL_SECONDS = 1

SUCCESS_MARKERS = [
    "指令[ 一条龙 ] 执行成功",
    "指令[一条龙] 执行成功",
]

MANUAL_STOP_MARKERS = [
    "停止运行",
    "人工结束",
]

STARTED_MARKERS = [
    "指令[ 一条龙 ]",
    "指令[一条龙]",
    "执行应用组 one_dragon",
]

FAILURE_MARKERS = [
    "指令[ 一条龙 ] 执行失败",
    "指令[一条龙] 执行失败",
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
    return any(is_process_running(name) for name in GAME_PROCESS_NAMES)


def taskkill(image_name):
    run_command(["taskkill", "/IM", image_name, "/F"], timeout=10)


def close_onedragon():
    taskkill("OneDragon-Launcher.exe")
    time.sleep(2)


def initial_log_offset():
    if not LOG_FILE.exists():
        return 0
    try:
        return LOG_FILE.stat().st_size
    except OSError:
        return 0


def read_new_log_lines(offset):
    if not LOG_FILE.exists():
        return offset, []
    try:
        size = LOG_FILE.stat().st_size
        if size < offset:
            # OneDragon 启动时可能轮转日志：旧 log.txt 被改名，新 log.txt 从 0 开始。
            offset = 0
        if size == offset:
            return offset, []
        with LOG_FILE.open("rb") as file:
            file.seek(offset)
            chunk = file.read()
        offset = size
        text = chunk.decode("utf-8", errors="replace")
        return offset, text.splitlines()
    except OSError:
        return offset, []


def find_onedragon_window_handle():
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
        if "OneDragon" in title or "一条龙" in title or "绝区零" in title or "Zenless" in title:
            handles.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return handles[0] if handles else 0


def wait_for_onedragon_window():
    started_at = time.time()
    while time.time() - started_at < STARTUP_TIMEOUT_SECONDS:
        hwnd = find_onedragon_window_handle()
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
    time.sleep(0.5)
    return True


def get_client_rect(hwnd):
    user32 = ctypes.windll.user32
    rect = ctypes.wintypes.RECT()
    point = ctypes.wintypes.POINT(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y, point.x + rect.right, point.y + rect.bottom


def send_mouse_input(dx, dy, flags):
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
    send_mouse_input(abs_x, abs_y, 0x0001 | 0x8000)
    user32.SetCursorPos(x, y)
    time.sleep(0.15)
    send_mouse_input(0, 0, 0x0002)
    time.sleep(0.1)
    send_mouse_input(0, 0, 0x0004)
    time.sleep(0.2)


def click_start_button(hwnd):
    """鼠标点击「启动一条龙」启动任务（OCR 识别定位，点之前先切前台）。"""
    if _maa_click_button:
        _maa_click_button(hwnd, "启动一条龙", (0.85, 0.88), log=log)
        return

    # maa_driver 不可用时的纯坐标兜底（旧逻辑）。
    activate_window(hwnd)
    rect = get_client_rect(hwnd)
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    for x, y in [
        (left + width * 0.85, top + height * 0.88),
        (left + width * 0.82, top + height * 0.835),
        (left + width * 0.90, top + height * 0.90),
    ]:
        click_screen(x, y)
        log(f"已点击右下角启动一条龙区域（兜底）：({int(x)}, {int(y)})")
        time.sleep(0.5)


def start_onedragon():
    if not ONEDRAGON_EXE.exists():
        raise FileNotFoundError(f"找不到 OneDragon-Launcher.exe：{ONEDRAGON_EXE}")
    log(f"启动 OneDragon：{ONEDRAGON_EXE}")
    subprocess.Popen(
        [str(ONEDRAGON_EXE)],
        cwd=str(ONEDRAGON_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_completion(offset):
    started_at = time.time()
    last_click_at = 0
    click_count = 0
    one_dragon_started = False
    one_dragon_success = False
    manual_stop_success = False
    saw_game_running = is_game_running()
    success_at = None

    while True:
        now = time.time()
        hwnd = find_onedragon_window_handle()

        if hwnd and not one_dragon_started and now - last_click_at >= START_BUTTON_RETRY_SECONDS:
            click_count += 1
            last_click_at = now
            log(f"第 {click_count} 次点击「启动一条龙」。")
            activate_window(hwnd)
            click_start_button(hwnd)

        offset, lines = read_new_log_lines(offset)
        for line in lines:
            if "一条龙" in line or "体力刷本" in line or "关闭游戏" in line or "执行失败" in line or "停止运行" in line:
                log(f"[log.txt] {line}")
            if any(marker in line for marker in STARTED_MARKERS):
                one_dragon_started = True
            if any(marker in line for marker in SUCCESS_MARKERS):
                one_dragon_success = True
                success_at = now
                log("检测到日志：一条龙整体执行成功。继续等待游戏进程关闭。")
            elif any(marker in line for marker in MANUAL_STOP_MARKERS):
                one_dragon_success = True
                manual_stop_success = True
                success_at = now
                log("检测到日志：一条龙被主动停止，本次按完成处理。继续等待游戏进程关闭。")
            elif one_dragon_started and any(marker in line for marker in FAILURE_MARKERS):
                log("检测到日志：一条龙整体执行失败。")
                return False

        if is_game_running():
            saw_game_running = True

        if one_dragon_success:
            if manual_stop_success:
                log("一条龙已被主动停止，按任务完成处理。")
                return True
            if saw_game_running and not is_game_running():
                log("检测到游戏进程已关闭，且日志显示一条龙完成。任务完成。")
                return True
            if not saw_game_running:
                log("日志显示一条龙完成，且本次未检测到游戏进程运行，任务完成。")
                return True
            if success_at and now - success_at > GAME_CLOSE_TIMEOUT_SECONDS:
                log("日志已完成，但等待游戏自动关闭超时。")
                return False

        elapsed = now - started_at
        if not one_dragon_started and elapsed > START_DETECT_TIMEOUT_SECONDS:
            log("点击启动后一段时间仍未检测到一条龙开始运行，判定失败。")
            return False
        if elapsed > TASK_TIMEOUT_SECONDS:
            log("OneDragon 运行超时，判定失败。")
            return False

        time.sleep(POLL_SECONDS)


def main():
    offset = initial_log_offset()
    start_onedragon()
    log(f"等待 OneDragon 窗口出现，最多 {STARTUP_TIMEOUT_SECONDS} 秒...")
    hwnd = wait_for_onedragon_window()
    if not hwnd:
        log("等待 OneDragon 窗口超时。")
        return 1

    log("OneDragon 窗口已出现，正在调到最前台。")
    activate_window(hwnd)
    log("等待 8 秒让界面加载。")
    time.sleep(8)

    ok = wait_for_completion(offset)
    if ok:
        close_onedragon()
        log("已关闭 OneDragon。")
        return 0

    log("OneDragon 任务未成功完成。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
