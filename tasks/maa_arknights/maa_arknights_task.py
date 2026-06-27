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

MAA_DIR = Path(os.environ.get("TASKRUNNER_PATH_MAA", "").strip() or r"C:\Tools\MAA")
MAA_EXE = MAA_DIR / "MAA.exe"
ARKNIGHTS_SHORTCUT = Path(
    (os.environ.get("TASKRUNNER_PATH_ARKNIGHTS") or os.environ.get("TASKRUNNER_TARGET_PATH") or "").strip()
    or r"C:\Tools\Arknights-MuMu.lnk"
)
GUI_LOG = MAA_DIR / "debug" / "gui.log"

MUMU_PROCESS_NAMES = [
    "MuMuNxMain.exe",
    "MuMuPlayer.exe",
    "MuMuVMMHeadless.exe",
    "MuMuVMMMSvc.exe",
    "NemuPlayer.exe",
    "NemuHeadless.exe",
]
MAA_PROCESS_NAMES = ["MAA.exe"]

EMULATOR_START_WAIT_SECONDS = 15
MAA_WINDOW_TIMEOUT_SECONDS = 180
LINK_START_TIMEOUT_SECONDS = 240
MONITOR_TIMEOUT_SECONDS = 8 * 60 * 60
POLL_SECONDS = 1

# 任务真正跑起来的日志标记（连上模拟器 / 开始第一个任务链）。
LINK_SUCCESS_MARKERS = [
    "最快截图耗时",
    "正在运行中",
    "Start Task Chain",
    "开始任务:",
]

ALL_DONE_MARKERS = [
    "任务已全部完成",
    "全部任务完成",
    "All tasks completed",
]

FAILURE_MARKERS = [
    "连接失败",
    "LinkStart Failed",
    "执行失败",
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


def taskkill(image_name, tree=True):
    args = ["taskkill", "/IM", image_name, "/F"]
    if tree:
        args.insert(-1, "/T")
    run_command(args, timeout=10)


def close_maa_and_mumu():
    for name in MAA_PROCESS_NAMES:
        taskkill(name, tree=True)
    for name in MUMU_PROCESS_NAMES:
        taskkill(name, tree=True)
    log("已关闭 MAA 和 MuMu 相关进程。")


# ===== 日志读取 =====
# MAA 的 gui.log 是累积单文件，且运行中可能被重写/缓冲，旧的 offset 增量读取会读不到新内容
# （2026-06-26 实测：07:04:34 已写入"正在运行中"等成功标记，脚本却没读到、超时判失败）。
# 改为读末尾窗口 + 时间戳过滤：只认本次启动后写入的行，既避开 offset 错位，也不会误命中历史标记。


def _parse_log_time(line):
    """解析行首 [YYYY-MM-DD HH:MM:SS（兼容 .ms 和 ,ms），返回 datetime 或 None。"""
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


def find_window_handle(keywords):
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
        if any(k.lower() in title.lower() for k in keywords):
            handles.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return handles[0] if handles else 0


def wait_for_window(keywords, timeout_seconds):
    started_at = time.time()
    while time.time() - started_at < timeout_seconds:
        hwnd = find_window_handle(keywords)
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


def click_link_start(hwnd):
    """鼠标点击「Link Start!」启动 MAA 任务（OCR 识别定位，点之前先切前台）。

    Link Start! 按钮在 MAA 左侧任务栏最下方——和运行中的「停止」是同一个位置，
    实测截图得其中心约在客户区 (0.17, 0.93)。OCR 对英文「Link Start!」不如中文
    按钮稳，所以兜底坐标必须精确指向这个按钮；旧兜底 (0.18, 0.86) 偏高，点到了
    任务列表区，是 MAA「点不到 Link Start」的直接原因之一。
    """
    if _maa_click_button:
        _maa_click_button(hwnd, "Link Start!", (0.17, 0.93), log=log)
        return

    # maa_driver 不可用时的纯坐标兜底：单点精确点按钮中心（连点多次可能误触「停止」）。
    activate_window(hwnd)
    left, top, right, bottom = get_client_rect(hwnd)
    width = right - left
    height = bottom - top
    x = left + width * 0.17
    y = top + height * 0.93
    click_screen(x, y)
    log(f"已点击 Link Start! 按钮（兜底坐标）：({int(x)}, {int(y)})")


def start_arknights_mumu():
    if not ARKNIGHTS_SHORTCUT.exists():
        raise FileNotFoundError(f"找不到快捷方式：{ARKNIGHTS_SHORTCUT}")
    log(f"启动明日方舟 MuMu 快捷方式：{ARKNIGHTS_SHORTCUT}")
    os.startfile(str(ARKNIGHTS_SHORTCUT))
    log(f"等待 MuMu/明日方舟启动稳定 {EMULATOR_START_WAIT_SECONDS} 秒...")
    time.sleep(EMULATOR_START_WAIT_SECONDS)


def start_maa():
    if not MAA_EXE.exists():
        raise FileNotFoundError(f"找不到 MAA.exe：{MAA_EXE}")
    log(f"启动 MAA：{MAA_EXE}")
    subprocess.Popen(
        [str(MAA_EXE)],
        cwd=str(MAA_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_background_monitor():
    python_exe = sys.executable
    if Path(python_exe).name.lower() == "pythonw.exe":
        normal = Path(python_exe).with_name("python.exe")
        if normal.exists():
            python_exe = str(normal)
    subprocess.Popen(
        [python_exe, str(Path(__file__).resolve()), "--monitor"],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    log("已启动后台 MAA 完成监控。")


def wait_until_linked():
    """点击 Link Start!，等 gui.log 确认连上模拟器/开始运行。

    读末尾窗口 + 时间戳过滤（只认本次启动后写入的行），避免 offset 错位和历史标记误命中。
    """
    started_dt = datetime.now()
    started_at = started_dt.timestamp()
    last_click_at = 0.0
    click_count = 0
    while True:
        now = time.time()
        hwnd = find_window_handle(["MAA", "MaaAssistant", "明日方舟小助手"])
        if hwnd and now - last_click_at > 8:
            click_count += 1
            last_click_at = now
            log(f"第 {click_count} 次点击 Link Start!。")
            click_link_start(hwnd)

        for line in read_log_tail(500):
            t = _parse_log_time(line)
            # 跳过本次启动前的旧行（留 30 秒余量），避免匹配到历史成功标记。
            if t and t < started_dt - timedelta(seconds=30):
                continue
            if "连接" in line or "模拟器" in line or "LinkStart" in line or "最快截图" in line or "正在运行" in line or "开始任务" in line:
                log(f"[gui.log] {line}")
            if any(marker in line for marker in LINK_SUCCESS_MARKERS):
                log("检测到 MAA 已成功连接模拟器/开始运行，主任务完成，队列可以继续。")
                return True
            if any(marker in line for marker in FAILURE_MARKERS):
                log("检测到 MAA 连接或任务启动失败。")
                return False

        if now - started_at > LINK_START_TIMEOUT_SECONDS:
            log("等待 MAA 成功连接模拟器超时。")
            return False
        time.sleep(POLL_SECONDS)


def monitor_until_all_done():
    log("后台监控：开始等待 MAA 所有任务完成。")
    started_dt = datetime.now()
    started_at = time.time()
    while True:
        for line in read_log_tail(500):
            t = _parse_log_time(line)
            if t and t < started_dt - timedelta(seconds=30):
                continue
            if "完成任务" in line or "任务已全部完成" in line or "Post actions" in line:
                log(f"[gui.log] {line}")
            if any(marker in line for marker in ALL_DONE_MARKERS):
                log("后台监控：检测到 MAA 所有任务完成，开始关闭 MAA 和 MuMu。")
                close_maa_and_mumu()
                return 0
        if time.time() - started_at > MONITOR_TIMEOUT_SECONDS:
            log("后台监控：等待 MAA 完成超时，开始关闭 MAA 和 MuMu。")
            close_maa_and_mumu()
            return 1
        time.sleep(5)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--monitor":
        return monitor_until_all_done()

    start_arknights_mumu()
    start_maa()
    log(f"等待 MAA 窗口出现，最多 {MAA_WINDOW_TIMEOUT_SECONDS} 秒...")
    hwnd = wait_for_window(["MAA", "MaaAssistant", "明日方舟小助手"], MAA_WINDOW_TIMEOUT_SECONDS)
    if not hwnd:
        log("等待 MAA 窗口超时。")
        return 1
    log("MAA 窗口已出现，调到最前台。")
    activate_window(hwnd)
    time.sleep(3)
    if wait_until_linked():
        start_background_monitor()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
