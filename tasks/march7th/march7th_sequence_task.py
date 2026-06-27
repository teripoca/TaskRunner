"""
March7th：崩坏星穹铁道日常 任务脚本。

流程：
1. 启动 March7th Launcher.exe（它会拉起 “三月七小助手 / March7th Assistant” 主程序）。
2. 等待窗口标题包含 “三月七 / March7th” 的窗口出现，并把它调到最前台。
3. 用鼠标点击左侧栏的 “日常” 按钮（位于 “任务” 下方）启动日常流程——
   点之前必须先把三月七小助手切到前台，点击才会落在对的窗口上。
   每次点击后看日志有没有出现 “开始运行 / 游戏启动”，没有就重试（再点 “日常”，必要时补点
   日常页底部 “开始运行” 按钮的候选坐标），直到日志确认任务真的跑起来。
4. 继续监控当天日志（logs/YYYY-MM-DD.log），直到出现 “停止运行”——日常整体跑完。
5. 等待崩坏：星穹铁道游戏（StarRail.exe）关闭；超时未关就主动强关，再视为完成。
6. 关闭 March7th（Launcher / Assistant / Updater 一并结束）。

注意：开始方式统一走鼠标点击，不用任何快捷键。
"""

import ctypes
import ctypes.wintypes
import os
import re
import subprocess
import sys
import time
from datetime import date
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
        MARCH7TH_DIR = _target_path.parent
    else:
        MARCH7TH_DIR = _target_path
else:
    MARCH7TH_DIR = Path(r"C:\Tools\March7thAssistant")
LAUNCHER_EXE = MARCH7TH_DIR / "March7th Launcher.exe"
LOGS_DIR = MARCH7TH_DIR / "logs"

# 主窗口标题关键词（三月七小助手 / March7thAssistant）。匹配到任一即可。
WINDOW_KEYWORDS = ["三月七", "March7th", "March 7th"]
# 游戏进程名（崩坏：星穹铁道）。
GAME_PROCESS_NAMES = ["StarRail.exe", "StarRailBase.exe"]
# 游戏窗口标题正则（全角/半角冒号都兼容）。
GAME_WINDOW_REGEX = re.compile(r"崩坏[：:]?\s*星穹铁道|Honkai:?\s*Star\s*Rail|星穹铁道")
# 三月七相关进程，收尾时一并结束。
MARCH7TH_PROCESS_NAMES = [
    "March7th Launcher.exe",
    "March 7th Assistant.exe",
    "March7th Updater.exe",
]

WINDOW_TIMEOUT_SECONDS = 240
START_DETECT_TIMEOUT_SECONDS = 240
START_CLICK_RETRY_SECONDS = 12
TASK_TIMEOUT_SECONDS = 4 * 60 * 60
GAME_CLOSE_WAIT_SECONDS = 20 * 60
POLL_SECONDS = 1

# 任务真正跑起来的日志标记（开始运行 / 游戏启动）。
STARTED_MARKERS = [
    "开始运行",
    "游戏启动",
]
# 日常整体跑完的标记：日志里的 “停止运行” 大框（暂停/收尾）。
RUN_FINISHED_MARKERS = [
    "停止运行",
]
# 失败标记（尽量宽泛，命中即判失败）。
FAILURE_MARKERS = [
    "运行错误",
    "任务失败",
    "执行失败",
    "发生错误",
    "Traceback",
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


def find_game_window_handle():
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
        if GAME_WINDOW_REGEX.search(title or ""):
            handles.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return handles[0] if handles else 0


def is_game_running():
    if any(is_process_running(name) for name in GAME_PROCESS_NAMES):
        return True
    return find_game_window_handle() != 0


def taskkill(image_name, tree=True):
    args = ["taskkill", "/IM", image_name, "/F"]
    if tree:
        args.insert(-1, "/T")
    run_command(args, timeout=10)


def close_march7th():
    for name in MARCH7TH_PROCESS_NAMES:
        taskkill(name, tree=True)
    log("已关闭 March7th（Launcher / Assistant / Updater）。")


def close_game_if_running():
    closed_any = False
    for name in GAME_PROCESS_NAMES:
        if is_process_running(name):
            taskkill(name, tree=True)
            closed_any = True
    if closed_any:
        log("已强制关闭崩坏：星穹铁道游戏进程。")


# ===== 日志读取（按当天日期文件，跨天自动切换） =====


def today_log_file():
    return LOGS_DIR / f"{date.today().isoformat()}.log"


def initial_log_state():
    """记录当前日志末尾位置，之后只读新增行。"""
    path = today_log_file()
    if not path.exists():
        return {"file": path, "offset": 0}
    try:
        return {"file": path, "offset": path.stat().st_size}
    except OSError:
        return {"file": path, "offset": 0}


def read_new_log_lines(state):
    """返回新增行列表，原地更新 state。跨天/日志轮转自动重置 offset。"""
    path = today_log_file()
    if state.get("file") != path:
        # 新的一天或首次调用：切换到当天日志，从头读起。
        state["file"] = path
        state["offset"] = 0
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        if size < state["offset"]:
            # 日志被截断/轮转，从头读。
            state["offset"] = 0
        if size == state["offset"]:
            return []
        with path.open("rb") as file:
            file.seek(state["offset"])
            chunk = file.read()
        state["offset"] = size
        return chunk.decode("utf-8", errors="replace").splitlines()
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


def find_march7th_window():
    def pred(title, _cls):
        return any(k in (title or "") for k in WINDOW_KEYWORDS)

    hwnd = _enum_windows_by_predicate(pred)
    if hwnd:
        return hwnd
    # 标题没匹配上时，按进程再兜底找一次主窗口（pywebview 偶尔标题加载晚）。
    return find_window_by_process()


def find_window_by_process():
    """通过进程名反查主窗口（找不到标题时的兜底）。"""
    if os.name != "nt":
        return 0
    user32 = ctypes.windll.user32
    try:
        import subprocess as _sp

        out = run_command(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Where-Object {$_.MainWindowTitle} | "
             "Select-Object Id,ProcessName,MainWindowTitle | ConvertTo-Json"],
            timeout=15,
        )
        if not out or not out.stdout:
            return 0
        import json as _json

        data = _json.loads(out.stdout)
        if isinstance(data, dict):
            data = [data]
        for item in data:
            title = item.get("MainWindowTitle") or ""
            proc = item.get("ProcessName") or ""
            if any(k in title for k in WINDOW_KEYWORDS) or "march7th" in proc.lower():
                pid = item.get("Id")
                hwnd = _hwnd_from_pid(user32, pid)
                if hwnd:
                    return hwnd
    except Exception:
        pass
    return 0


def _hwnd_from_pid(user32, pid):
    if not pid:
        return 0
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        p = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == int(pid):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return found[0] if found else 0


def wait_for_march7th_window():
    started_at = time.time()
    while time.time() - started_at < WINDOW_TIMEOUT_SECONDS:
        hwnd = find_march7th_window()
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
    _send_mouse_input(abs_x, abs_y, 0x0001 | 0x8000)  # MOVE | ABSOLUTE，光标先就位
    time.sleep(0.08)
    _send_mouse_input(0, 0, 0x0002)  # LEFTDOWN
    time.sleep(0.08)
    _send_mouse_input(0, 0, 0x0004)  # LEFTUP
    time.sleep(0.2)


def click_daily_and_start(hwnd, attempt):
    """鼠标点击左侧栏「日常」启动任务（点之前先切前台，OCR 识别定位）。

    点「日常」即直接启动日常任务并跳到日志页，不需要再点别的按钮（用户 2026-06-25 确认）。
    用 MaaFramework OCR 识别「日常」精确定位；识别失败或 maafw 不可用时回落比例坐标。
    """
    if _maa_click_button:
        _maa_click_button(hwnd, "日常", (0.075, 0.60), log=log)
        return

    # maa_driver 不可用时的纯坐标兜底（旧逻辑）。
    activate_window(hwnd)
    time.sleep(0.4)
    rect = get_client_rect(hwnd)
    if not rect:
        log("无法获取三月七小助手客户区位置，跳过本次点击。")
        return
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    daily_x = left + width * 0.075
    daily_y = top + height * 0.60
    click_screen(daily_x, daily_y)
    log(f"已点击左侧栏「日常」（兜底坐标）：({int(daily_x)}, {int(daily_y)})")


def start_launcher():
    if not LAUNCHER_EXE.exists():
        raise FileNotFoundError(f"找不到 March7th Launcher.exe：{LAUNCHER_EXE}")
    # 窗口已在就不重复启动（避免重复拉起；非管理员去启动需提权的 Launcher 会 WinError 740）。
    if find_march7th_window():
        log("三月七小助手窗口已存在，跳过启动 Launcher。")
        return
    log(f"启动 March7th Launcher：{LAUNCHER_EXE}")
    try:
        subprocess.Popen(
            [str(LAUNCHER_EXE)],
            cwd=str(MARCH7TH_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        log(f"启动 Launcher 失败（可能需要管理员权限或已在运行）：{exc}")


def trigger_start(hwnd, attempt):
    log("鼠标点击 “日常” 启动崩坏：星穹铁道日常任务（不再用任何快捷键）。")
    click_daily_and_start(hwnd, attempt)


# ===== 主流程 =====


def wait_for_started(state):
    """点击 “日常”，等日志确认任务真的跑起来了。"""
    started_at = time.time()
    last_click_at = 0.0
    attempt = 0
    while True:
        now = time.time()
        hwnd = find_march7th_window()
        if hwnd and now - last_click_at >= START_CLICK_RETRY_SECONDS:
            attempt += 1
            last_click_at = now
            log(f"第 {attempt} 次触发开始任务。")
            trigger_start(hwnd, attempt)

        for line in read_new_log_lines(state):
            if any(k in line for k in ("开始运行", "游戏启动", "停止运行", "完成", "失败", "错误", "日常", "开拓力")):
                log(f"[log] {line}")
            if any(marker in line for marker in STARTED_MARKERS):
                log("检测到日志：开始运行 / 游戏启动，任务已启动。")
                return True, state
            if any(marker in line for marker in FAILURE_MARKERS):
                log("检测到日志：任务运行出错。")
                return False, state

        if now - started_at > START_DETECT_TIMEOUT_SECONDS:
            log("等待 March7th 任务启动超时。")
            return False, state
        time.sleep(POLL_SECONDS)


def wait_for_run_finished_and_game_closed(state):
    """日志显示日常整体跑完（停止运行），并且崩坏：星穹铁道关闭，才算整体完成。"""
    started_at = time.time()
    run_finished = False
    finished_at = None
    saw_game_running = is_game_running()

    while True:
        now = time.time()
        for line in read_new_log_lines(state):
            if any(k in line for k in ("停止运行", "开始运行", "完成", "失败", "错误", "退出", "开拓力", "winotify", "游戏")):
                log(f"[log] {line}")
            if not run_finished and any(marker in line for marker in RUN_FINISHED_MARKERS):
                run_finished = True
                finished_at = now
                log("检测到日志：停止运行，日常整体跑完。继续等待崩坏：星穹铁道关闭。")
            elif any(marker in line for marker in FAILURE_MARKERS):
                log("检测到日志：任务运行出错。")
                return False

        if is_game_running():
            saw_game_running = True

        if run_finished:
            if not is_game_running():
                log("崩坏：星穹铁道已关闭（或本次未启动过），整体任务完成。")
                return True
            if finished_at and now - finished_at > GAME_CLOSE_WAIT_SECONDS:
                log(
                    f"日志已显示完成，但等待游戏关闭超过 {GAME_CLOSE_WAIT_SECONDS // 60} 分钟，"
                    "主动强制关闭崩坏：星穹铁道。"
                )
                close_game_if_running()
                time.sleep(30)
                if not is_game_running():
                    return True
                log("强制关闭后仍能检测到游戏进程，按完成处理。")
                return True

        if now - started_at > TASK_TIMEOUT_SECONDS:
            log("等待 March7th 日常整体完成超时。")
            return False
        time.sleep(POLL_SECONDS)


def main():
    state = initial_log_state()
    start_launcher()
    log(f"等待三月七小助手窗口出现，最多 {WINDOW_TIMEOUT_SECONDS} 秒...")
    hwnd = wait_for_march7th_window()
    if not hwnd:
        log("等待三月七小助手窗口超时。")
        close_march7th()
        return 1

    log("三月七小助手窗口已出现，调到最前台并等待 6 秒让界面加载。")
    activate_window(hwnd)
    time.sleep(6)

    ok, state = wait_for_started(state)
    if not ok:
        log("March7th 日常任务未能正常启动。")
        close_march7th()
        return 1

    ok = wait_for_run_finished_and_game_closed(state)
    if ok:
        close_march7th()
        log("March7th：崩坏星穹铁道日常任务整体完成。")
        return 0

    log("March7th 任务未成功完成。")
    close_march7th()
    return 1


if __name__ == "__main__":
    sys.exit(main())
