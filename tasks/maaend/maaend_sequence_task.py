import ctypes
import ctypes.wintypes
import json
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
    from maa_driver import click_button as _maa_click_button, find_window as _maa_find_window
except Exception as _maa_exc:
    _maa_click_button = None
    _maa_find_window = None
    print(f"[maa_driver] 加载失败，将只用兜底坐标：{_maa_exc}", flush=True)


def _is_admin():
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin():
    if os.name != "nt":
        return False
    script_path = os.path.abspath(__file__)
    python_exe = sys.executable
    if Path(python_exe).name.lower() == "pythonw.exe":
        normal = Path(python_exe).with_name("python.exe")
        if normal.exists():
            python_exe = str(normal)
    params = f'"{script_path}"'
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", python_exe, params, None, 1)
        if ret <= 32:
            print(f"以管理员重新启动失败，ShellExecute 返回 {ret}", flush=True)
            return False
        print("已以管理员身份重新启动任务脚本，请在新弹出的窗口里查看进度。", flush=True)
        return True
    except Exception as exc:
        print(f"以管理员重新启动异常：{exc}", flush=True)
        return False


if os.name == "nt" and not _is_admin():
    print("检测到当前不是管理员，MaaEnd 是管理员运行，将以管理员身份重新启动本任务。", flush=True)
    if _relaunch_as_admin():
        sys.exit(0)
    else:
        print("请右键“以管理员身份运行” 桌面的“脚本任务运行器.bat”，否则鼠标点击不会生效。", flush=True)

MAAEND_DIR = Path(os.environ.get("TASKRUNNER_PATH_MAAEND", "").strip() or r"C:\Tools\MaaEnd")
MAAEND_EXE = MAAEND_DIR / "MaaEnd.exe"
CONFIG_PATH = MAAEND_DIR / "config" / "mxu-MaaEnd.json"
BACKUP_PATH = CONFIG_PATH.with_suffix(".automation-backup.json")
DEBUG_DIR = MAAEND_DIR / "debug"
TASKRUNNER_ROOT = Path(__file__).resolve().parents[2]
ENDFIELD_WINDOW_TOOL = TASKRUNNER_ROOT / "tools" / "set_endfield_1080p_window.ps1"

ENDFIELD_EXE = Path((os.environ.get("TASKRUNNER_PATH_ENDFIELD") or os.environ.get("TASKRUNNER_TARGET_PATH") or "").strip() or r"D:\Hypergryph Launcher\games\Endfield Game\Endfield.exe")
ENDFIELD_REG_KEY = r"HKCU\Software\Hypergryph\Endfield"
ENDFIELD_TARGET_WIDTH = 1920
ENDFIELD_TARGET_HEIGHT = 1080
# Unity Screenmanager Fullscreen mode 取值：0=独占全屏, 1=全屏窗口, 2=最大化窗口, 3=窗口化
ENDFIELD_TARGET_FULLSCREEN_MODE = 3
ENDFIELD_WAIT_WINDOW_SECONDS = 180

INSTANCE_SEQUENCE = ["基质刷取", "全套日常"]
MAX_ATTEMPTS_PER_INSTANCE = 20
ATTEMPT_TIMEOUT_SECONDS = 8 * 60 * 60
POLL_SECONDS = 1
START_DELAY_SECONDS = 12

SUCCESS_MARKERS = [
    "kind: tasks-completed",
    "任务完成",
    "全部任务完成",
    "tasks-completed",
]

FAILURE_MARKERS = [
    "ERROR [Task]",
    "任务启动异常",
    "任务失败",
    "执行失败",
    "连接失败",
    "加载资源失败",
    "tasks-failed",
]

VK_F10 = 0x79
KEYEVENTF_KEYUP = 0x0002
# 注意：开始按钮统一用鼠标点击（click_maaend_start_button），不再用 F10 快捷键。
SW_RESTORE = 9


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


def taskkill(image_name, kill_tree=True):
    args = ["taskkill", "/IM", image_name, "/F"]
    if kill_tree:
        args.insert(-1, "/T")
    run_command(args)


def close_maaend():
    # 关 MaaEnd 时不要带上 /T，避免连带杀掉 Endfield 这种被 MaaEnd 拉起来的子进程。
    taskkill("MaaEnd.exe", kill_tree=False)
    time.sleep(2)


def close_endfield():
    taskkill("Endfield.exe", kill_tree=False)
    time.sleep(2)


def is_process_running(image_name):
    if os.name != "nt":
        return False
    result = run_command(["tasklist", "/FI", f"IMAGENAME eq {image_name}"], timeout=10)
    if not result or not result.stdout:
        return False
    return image_name.lower() in result.stdout.lower()


def is_endfield_running():
    return is_process_running("Endfield.exe")


def find_endfield_window_handle():
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
        if buffer.value.strip() == "Endfield":
            handles.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return handles[0] if handles else 0


def set_endfield_resolution_registry(width=ENDFIELD_TARGET_WIDTH,
                                     height=ENDFIELD_TARGET_HEIGHT,
                                     fullscreen_mode=ENDFIELD_TARGET_FULLSCREEN_MODE):
    """通过注册表写入 Unity 分辨率/窗口模式设置。必须在游戏启动前调用。"""
    if os.name != "nt":
        return
    video_fullscreen = 0 if fullscreen_mode in (2, 3) else 1
    pairs = [
        # ========== Unity PlayerPrefs 实际启动分辨率 ==========
        ("Screenmanager Resolution Width_h182942802", width),
        ("Screenmanager Resolution Height_h2627697771", height),
        ("Screenmanager Resolution Width Default_h680557497", width),
        ("Screenmanager Resolution Height Default_h1380706816", height),
        ("Screenmanager Resolution Window Width_h2524650974", width),
        ("Screenmanager Resolution Window Height_h1684712807", height),
        ("Screenmanager Fullscreen mode_h3630240806", fullscreen_mode),
        ("Screenmanager Fullscreen mode Default_h401710285", fullscreen_mode),
        ("Screenmanager Resolution Use Native_h1405027254", 0),
        ("Screenmanager Resolution Use Native Default_h1405981789", 0),
        # ========== 游戏设置 UI 里显示的分辨率 ==========
        ("video_resolution_width_h583690364", width),
        ("video_resolution_height_h2517654917", height),
        ("video_full_screen_h1998742411", video_fullscreen),
    ]
    for name, value in pairs:
        run_command(
            ["reg", "add", ENDFIELD_REG_KEY, "/v", name, "/t", "REG_DWORD",
             "/d", str(value), "/f"],
            timeout=10,
        )
    mode_text = {0: "独占全屏", 1: "全屏窗口", 2: "最大化窗口", 3: "窗口化"}.get(fullscreen_mode, str(fullscreen_mode))
    log(f"已写入终末地分辨率设置：{width}x{height}，模式：{mode_text}")


def wait_for_endfield_window(timeout_seconds=ENDFIELD_WAIT_WINDOW_SECONDS):
    started_at = time.time()
    while time.time() - started_at < timeout_seconds:
        if find_endfield_window_handle():
            return True
        time.sleep(2)
    return False


def run_endfield_window_tool():
    """只写入终末地窗口化配置，不主动启动游戏。"""
    if not ENDFIELD_WINDOW_TOOL.exists():
        log(f"找不到终末地窗口化脚本：{ENDFIELD_WINDOW_TOOL}，跳过。")
        return False
    log(f"运行终末地窗口化脚本：{ENDFIELD_WINDOW_TOOL}")
    result = run_command([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(ENDFIELD_WINDOW_TOOL),
    ], timeout=60)
    if result and result.stdout:
        for line in result.stdout.splitlines():
            if line.strip():
                log(f"[Endfield窗口化] {line}")
    return bool(result and result.returncode == 0)


def ensure_endfield_running():
    """在启动 MaaEnd 之前，先按用户期望的分辨率/窗口模式启动终末地。"""
    if not ENDFIELD_EXE.exists():
        log(f"找不到终末地可执行文件：{ENDFIELD_EXE}，跳过预启动。")
        return False

    if is_endfield_running():
        log("终末地已在运行，跳过预启动。")
        return True

    # 先写注册表，让 Unity 在启动时读到目标分辨率/窗口模式
    set_endfield_resolution_registry()

    # 再叠加 Unity 命令行参数。命令行参数会覆盖注册表，是最可靠的方式。
    # -screen-fullscreen 0 强制非全屏，-popupwindow 让窗口可拖动
    cmd = [
        str(ENDFIELD_EXE),
        "-screen-width", str(ENDFIELD_TARGET_WIDTH),
        "-screen-height", str(ENDFIELD_TARGET_HEIGHT),
        "-screen-fullscreen", "0" if ENDFIELD_TARGET_FULLSCREEN_MODE in (2, 3) else "1",
        "-window-mode", "exclusive" if ENDFIELD_TARGET_FULLSCREEN_MODE == 0 else "borderless",
    ]
    log(f"正在启动终末地：{' '.join(cmd)}")
    try:
        subprocess.Popen(
            cmd,
            cwd=str(ENDFIELD_EXE.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        log(f"启动终末地失败：{exc}")
        return False

    log(f"等待终末地窗口出现，最多等 {ENDFIELD_WAIT_WINDOW_SECONDS} 秒...")
    if wait_for_endfield_window():
        log("终末地窗口已出现。等待 8 秒确认稳定。")
        time.sleep(8)
        # 启动后强制把窗口设回目标尺寸，以防游戏忽略命令行参数
        force_endfield_window_size()
        return True
    log("等待终末地窗口超时，仍然尝试继续启动 MaaEnd。")
    return False


def force_endfield_window_size(width=ENDFIELD_TARGET_WIDTH, height=ENDFIELD_TARGET_HEIGHT):
    """启动后强制把终末地窗口设置为目标尺寸（非全屏窗口模式有效）。"""
    if os.name != "nt":
        return
    if ENDFIELD_TARGET_FULLSCREEN_MODE not in (2, 3):
        return
    hwnd = find_endfield_window_handle()
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    SW_RESTORE_LOCAL = 9
    user32.ShowWindow(hwnd, SW_RESTORE_LOCAL)
    # 取屏幕尺寸把窗口居中
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    # SetWindowPos(hwnd, HWND_TOP=0, x, y, w, h, SWP_NOZORDER=4)
    user32.SetWindowPos(hwnd, 0, int(x), int(y), int(width), int(height), 0x0004)
    log(f"已把终末地窗口调整为 {width}x{height}，位置 ({x},{y})。")


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def restore_leftover_backup():
    if BACKUP_PATH.exists():
        log("发现上次自动化留下的 MaaEnd 配置备份，先恢复原配置。")
        CONFIG_PATH.write_text(BACKUP_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        BACKUP_PATH.unlink()


def backup_config():
    BACKUP_PATH.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")


def restore_config():
    if BACKUP_PATH.exists():
        CONFIG_PATH.write_text(BACKUP_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        BACKUP_PATH.unlink()
        log("已恢复 MaaEnd 原配置。")


def find_instance(config, instance_name):
    for instance in config.get("instances", []):
        if instance.get("name") == instance_name:
            return instance
    return None


def write_single_instance_config(original_config, instance_name):
    instance = find_instance(original_config, instance_name)
    if not instance:
        raise RuntimeError(f"在 MaaEnd 配置里找不到实例：{instance_name}")

    data = json.loads(json.dumps(original_config, ensure_ascii=False))
    data["instances"] = [json.loads(json.dumps(instance, ensure_ascii=False))]
    settings = data.setdefault("settings", {})
    settings["autoRunOnLaunch"] = True
    settings["minimizeToTray"] = False
    settings["autoClearLogsOnLaunch"] = False
    save_config(data)


def log_files():
    if not DEBUG_DIR.exists():
        return []
    files = []
    for path in DEBUG_DIR.glob("*.log"):
        if path.is_file() and ".bak." not in path.name:
            files.append(path)
    return files


def initial_log_offsets():
    offsets = {}
    for path in log_files():
        try:
            offsets[str(path)] = path.stat().st_size
        except OSError:
            pass
    return offsets


def read_new_log_lines(offsets):
    lines = []
    for path in log_files():
        key = str(path)
        old_offset = offsets.get(key, 0)
        try:
            size = path.stat().st_size
            if size < old_offset:
                old_offset = 0
            if size == old_offset:
                continue
            with path.open("rb") as file:
                file.seek(old_offset)
                chunk = file.read()
            offsets[key] = size
            text = chunk.decode("utf-8", errors="replace")
            for line in text.splitlines():
                lines.append((path.name, line))
        except OSError:
            continue
    return lines


def start_maaend():
    log(f"启动 MaaEnd：{MAAEND_EXE}")
    try:
        process = subprocess.Popen(
            [str(MAAEND_EXE)],
            cwd=str(MAAEND_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        raise RuntimeError(f"启动 MaaEnd.exe 失败：{exc}") from exc
    log(f"MaaEnd 启动命令已发出，PID={process.pid}")
    return process


def find_maaend_window_handle():
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
        if "MaaEnd" in title:
            handles.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return handles[0] if handles else 0


def has_maaend_window():
    return bool(find_maaend_window_handle())


def activate_maaend_window():
    hwnd = find_maaend_window_handle()
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    return True


def get_maaend_client_rect():
    hwnd = find_maaend_window_handle()
    if not hwnd:
        return None
    user32 = ctypes.windll.user32
    rect = ctypes.wintypes.RECT()
    point = ctypes.wintypes.POINT(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y, point.x + rect.right, point.y + rect.bottom


def _send_mouse_input(dx, dy, flags):
    user32 = ctypes.windll.user32

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
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _move_cursor_absolute(x, y):
    user32 = ctypes.windll.user32
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    abs_x = int(x * 65535 / max(screen_w - 1, 1))
    abs_y = int(y * 65535 / max(screen_h - 1, 1))
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_ABSOLUTE = 0x8000
    _send_mouse_input(abs_x, abs_y, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
    user32.SetCursorPos(int(x), int(y))


def click_screen(x, y):
    if os.name != "nt":
        return
    x = int(x)
    y = int(y)
    _move_cursor_absolute(x, y)
    time.sleep(0.2)
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    _send_mouse_input(0, 0, MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.1)
    _send_mouse_input(0, 0, MOUSEEVENTF_LEFTUP)
    time.sleep(0.2)


def find_green_button_center(rect):
    try:
        from PIL import ImageGrab
    except Exception as exc:
        log(f"无法导入 PIL.ImageGrab，改用固定坐标点击：{exc}")
        return None

    left, top, right, bottom = [int(v) for v in rect]
    image = ImageGrab.grab(bbox=(left, top, right, bottom)).convert("RGB")
    width, height = image.size

    mask = set()
    # 只找窗口下半部分的大块绿色按钮，避开左侧小图标和顶部状态条。
    for y in range(int(height * 0.45), height):
        for x in range(width):
            r, g, b = image.getpixel((x, y))
            if g >= 95 and g >= r + 25 and g >= b + 15:
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
        if area < 500:
            continue
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        comp_width = x2 - x1 + 1
        comp_height = y2 - y1 + 1
        if comp_width < 80 or comp_height < 25:
            continue
        # 优先选择靠近窗口底部中间的大绿色按钮。
        score = area + y2 * 2 - abs(((x1 + x2) / 2) - width * 0.6)
        if best is None or score > best[0]:
            best = (score, x1, y1, x2, y2, area)

    if not best:
        return None
    _, x1, y1, x2, y2, area = best
    cx = left + (x1 + x2) / 2
    cy = top + (y1 + y2) / 2
    log(f"识别到绿色按钮区域：窗口内({x1},{y1})-({x2},{y2})，面积 {area}，屏幕中心({int(cx)},{int(cy)})")
    return cx, cy


def click_maaend_start_button():
    """点击 MaaEnd「开始任务」按钮（OCR 识别定位，点之前先切前台）。"""
    if _maa_click_button:
        hwnd = _maa_find_window("MaaEnd") if _maa_find_window else 0
        if hwnd:
            return _maa_click_button(hwnd, "开始任务", (0.585, 0.945), log=log)
        log("OCR 模式：未找到 MaaEnd 窗口，回退颜色识别。")

    # maa_driver 不可用 / 找不到窗口时：绿色按钮颜色识别 + 兜底坐标（旧逻辑）。
    if not activate_maaend_window():
        log("未找到 MaaEnd 窗口，无法点击开始按钮。")
        return False
    rect = get_maaend_client_rect()
    if not rect:
        log("无法获取 MaaEnd 窗口客户区位置。")
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
    click_points = [
        (left + width * 0.585, top + height * 0.945),
        (left + width * 0.613, top + height * 0.957),
        (left + width * 0.645, top + height * 0.957),
    ]
    for x, y in click_points:
        click_screen(x, y)
        log(f"未识别到绿色按钮，已点击备用坐标：({int(x)}, {int(y)})")
        time.sleep(0.6)
    return True


def press_f10():
    # 保留函数签名兼容，但开始按钮已统一改用鼠标点击，不再发送 F10 快捷键。
    log("开始按钮已改用鼠标点击，跳过 F10 快捷键。")
    return


def monitor_until_finished(process, instance_name, offsets):
    started_at = time.time()
    last_start_press_at = 0
    start_press_count = 0
    saw_window = False
    saw_task_started = False
    while True:
        elapsed = time.time() - started_at
        if not saw_window and elapsed >= 3 and has_maaend_window():
            saw_window = True
            log("检测到 MaaEnd 窗口已打开。")

        if saw_window and not saw_task_started and elapsed >= START_DELAY_SECONDS and elapsed - last_start_press_at >= 10:
            start_press_count += 1
            last_start_press_at = elapsed
            log(f"第 {start_press_count} 次点击开始按钮，尝试开始 {instance_name}。")
            click_maaend_start_button()

        for file_name, line in read_new_log_lines(offsets):
            if "窗口已显示" in line or "加载完成" in line:
                saw_window = True
            if "task-started" in line or "开始执行任务" in line or "任务已提交" in line:
                saw_task_started = True
            if "INFO" in line or "ERROR" in line or "kind:" in line:
                if instance_name in line or "kind:" in line or "ERROR [Task]" in line or "窗口已显示" in line or "加载完成" in line:
                    log(f"[{file_name}] {line}")
            if any(marker in line for marker in SUCCESS_MARKERS):
                log(f"检测到 {instance_name} 任务完成。")
                return True
            if saw_task_started and any(marker in line for marker in FAILURE_MARKERS):
                log(f"检测到 {instance_name} 任务异常，将重启该任务。")
                return False

        # MaaEnd.exe 是 Tauri 启动器进程，退出码 0 可能只是窗口进程已接管，不能当成失败。
        if process.poll() is not None and process.returncode not in (0, None):
            log(f"MaaEnd 启动进程异常退出，退出码：{process.returncode}，将重启 {instance_name}。")
            return False

        if not saw_window and elapsed > 60:
            log(f"MaaEnd 启动 60 秒后仍没有写入窗口/加载日志，将重启 {instance_name}。")
            return False

        if start_press_count > 0 and not saw_task_started and elapsed > 120:
            log(f"已多次点击开始按钮，但 120 秒内没有检测到任务启动，将重启 {instance_name}。")
            return False

        if elapsed > ATTEMPT_TIMEOUT_SECONDS:
            log(f"{instance_name} 单次运行超过 {ATTEMPT_TIMEOUT_SECONDS // 3600} 小时未完成，将重启该任务。")
            return False

        time.sleep(POLL_SECONDS)


def run_instance_until_success(original_config, instance_name):
    for attempt in range(1, MAX_ATTEMPTS_PER_INSTANCE + 1):
        log(f"\n========== {instance_name}：第 {attempt} 次启动 ==========")
        close_maaend()
        write_single_instance_config(original_config, instance_name)
        offsets = initial_log_offsets()
        process = start_maaend()
        success = monitor_until_finished(process, instance_name, offsets)
        close_maaend()
        if success:
            return
        time.sleep(5)
    raise RuntimeError(f"{instance_name} 连续重试 {MAX_ATTEMPTS_PER_INSTANCE} 次仍未完成。")


def validate_paths():
    if not MAAEND_EXE.exists():
        raise FileNotFoundError(f"找不到 MaaEnd.exe：{MAAEND_EXE}")
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"找不到 MaaEnd 配置文件：{CONFIG_PATH}")


def main():
    validate_paths()
    restore_leftover_backup()
    original_config = load_config()
    backup_config()
    try:
        log("\n========== 启动前置：设置终末地 1080p 窗口化 ==========")
        run_endfield_window_tool()
        for instance_name in INSTANCE_SEQUENCE:
            run_instance_until_success(original_config, instance_name)
        log("\n========== MaaEnd 两个阶段都已完成，开始关闭 MaaEnd 和终末地 ==========")
        close_maaend()
        close_endfield()
        log("已关闭 MaaEnd 和 Endfield.exe。")
        return 0
    except Exception as exc:
        log(f"任务失败：{exc}")
        return 1
    finally:
        restore_config()


if __name__ == "__main__":
    sys.exit(main())
