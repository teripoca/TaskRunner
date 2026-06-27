"""
MaaFramework 截图连通性探针（只读，不点击）。

目的：
1. 验证 maafw 绑定能跑（init_option / find_desktop_windows）。
2. 找到任务要操控的助手窗口（三月七/识宝/一条龙/MAA/MaaEnd）。
3. 连 Win32Controller，抓一张原始分辨率截图存盘，确认 pywebview/Electron/Tauri
   这类助手窗口能被正常截图（本项目唯一的技术风险点）。
4. 顺便把抓到的图当参考图存进 assets/refs/。

用法：
    python tasks/_common/maa_probe.py            # 自动匹配所有助手窗口
    python tasks/_common/maa_probe.py 三月七      # 只匹配标题含“三月七”的窗口

先把对应助手的 GUI 打开（不用点开始），再跑探针。
"""

import ctypes
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 高 DPI 下窗口坐标/截图才准。
if os.name == "nt":
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from maa.toolkit import Toolkit
from maa.controller import Win32Controller, MaaWin32ScreencapMethodEnum, MaaWin32InputMethodEnum
import numpy
from PIL import Image

# 探针输出 / 资源根目录：本文件在 tasks/_common/ 下，往上两层是 TaskRunner 根。
TASKRUNNER_ROOT = Path(__file__).resolve().parents[2]
USER_PATH = TASKRUNNER_ROOT / ".maafw"          # init_option 的配置/日志目录
REFS_DIR = TASKRUNNER_ROOT / "assets" / "refs"
REFS_DIR.mkdir(parents=True, exist_ok=True)
USER_PATH.mkdir(parents=True, exist_ok=True)

# 各助手窗口标题关键词（命中任一即认为是该助手）。
ASSISTANT_KEYWORDS = {
    "march7th": ["三月七", "March7th", "March 7th"],
    "maabbb": ["识宝", "Maa_bbb", "MFW"],
    "onedragon": ["OneDragon", "一条龙", "绝区零", "Zenless"],
    "maa": ["明日方舟", "Arknights", "MaaAssistant"],
    "maaend": ["MaaEnd", "终末地", "Endfield"],
}


def safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z一-鿿._-]+", "_", text).strip("_") or "window"


def image_is_blank(img: numpy.ndarray) -> bool:
    """全黑/全白/几乎纯色判定（说明截图没抓到内容）。"""
    if img is None or img.size == 0:
        return True
    return float(img.std()) < 3.0


def save_png(img: numpy.ndarray, name: str) -> Path:
    """ndarray 是 OpenCV BGR，存 PNG 前转 RGB。"""
    path = REFS_DIR / f"{safe_name(name)}.png"
    if img.ndim == 3 and img.shape[2] == 3:
        rgb = img[:, :, ::-1]
    else:
        rgb = img
    Image.fromarray(rgb).save(path)
    return path


def try_screencap(hwnd, title: str, methods: int, label: str):
    """用指定截图方式连窗口抓图，返回 (ok, img_or_None, info_str)。"""
    try:
        ctrl = Win32Controller(
            hWnd=hwnd,
            screencap_method=methods,
            mouse_method=MaaWin32InputMethodEnum.PostMessage,   # 探针不点击，用后台方式不抢前台
            keyboard_method=MaaWin32InputMethodEnum.PostMessage,
        )
        ctrl.set_screenshot_use_raw_size(True)   # 原始分辨率，坐标才能和窗口对上
        ctrl.post_connection().wait()
        if not ctrl.connected:
            return False, None, f"{label}: 连接失败"
        img = ctrl.post_screencap().wait().get()
        if image_is_blank(img):
            return False, img, f"{label}: 截图为空/纯色（没抓到内容）"
        return True, img, f"{label}: OK shape={getattr(img,'shape',None)} std={float(img.std()):.1f}"
    except Exception as exc:
        return False, None, f"{label}: 异常 {exc!r}"


def main():
    Toolkit.init_option(str(USER_PATH))
    windows = Toolkit.find_desktop_windows()
    print(f"[probe] 枚举到 {len(windows)} 个窗口。")

    # 打印带标题的窗口，便于核对真实标题/类名（驱动里 find_window 要用）。
    titled = [w for w in windows if (w.window_name or "").strip()]
    print(f"[probe] 其中有标题的 {len(titled)} 个，前 60 个：")
    for w in titled[:60]:
        t = (w.window_name or "")[:40]
        c = (w.class_name or "")[:30]
        print(f"    hwnd={int(w.hwnd) if w.hwnd else 0:<12} class={c:<30} title={t}")

    # 筛选目标助手窗口。
    arg_kw = sys.argv[1] if len(sys.argv) > 1 else None
    targets = []
    for w in windows:
        hay = f"{w.window_name or ''} {w.class_name or ''}"
        if arg_kw:
            if arg_kw in hay:
                targets.append((w, arg_kw))
        else:
            for tag, kws in ASSISTANT_KEYWORDS.items():
                if any(k in hay for k in kws):
                    targets.append((w, tag))
                    break

    if not targets:
        print("\n[probe] 没匹配到任何助手窗口。请先把某个助手的 GUI 打开（不用点开始），再重跑。")
        if arg_kw:
            print(f"[probe] 本次只匹配关键词：{arg_kw}")
        return 0

    print(f"\n[probe] 匹配到 {len(targets)} 个助手窗口，开始截图测试：")
    background = MaaWin32ScreencapMethodEnum.Background   # FramePool | PrintWindow
    all_methods = MaaWin32ScreencapMethodEnum.All

    for w, tag in targets:
        title = w.window_name or "(无标题)"
        print(f"\n--- [{tag}] title={title!r} class={w.class_name!r} hwnd={int(w.hwnd) if w.hwnd else 0}")
        ok, img, info = try_screencap(w.hwnd, title, background, "Background(FramePool|PrintWindow)")
        print(f"    {info}")
        if not ok:
            # Background 没抓到，退一步把所有方式都试一遍，看哪种能抓到。
            ok, img, info = try_screencap(w.hwnd, title, all_methods, "All(全部方式)")
            print(f"    {info}")
        if ok and img is not None:
            path = save_png(img, f"probe_{tag}_{title}")
            print(f"    已存参考图：{path}")
        else:
            print(f"    [{tag}] 截图失败——该助手窗口当前截图方式抓不到，需换思路。")

    print("\n[probe] 完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
