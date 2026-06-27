"""
MaaFramework OCR 识别测试（只识别，不点击，安全）。

两种模式：
- 读图模式（不依赖实时窗口）：设环境变量 MAAFW_DEBUG_DIR=<只放参考图的目录>，
  用 DbgController 把图当截图。图和 resource 都必须在 ASCII 路径（MaaFramework 的
  C++ 核心在 Windows 上处理不了非 ASCII 路径）。
- 实时窗口模式：不设 MAAFW_DEBUG_DIR，按关键词找窗口截图。

resource 路径用 MAAFW_RESOURCE 指定（同样要 ASCII）。

用法：
    MAAFW_RESOURCE=... MAAFW_DEBUG_DIR=... python maa_ocr_test.py _ 日常
    MAAFW_RESOURCE=... python maa_ocr_test.py March7th 日常
"""

import ctypes
import os
import sys
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
    DbgController,
    Win32Controller,
    MaaWin32ScreencapMethodEnum,
    MaaWin32InputMethodEnum,
)
from maa.resource import Resource
from maa.tasker import Tasker

ROOT = Path(__file__).resolve().parents[2]
USER = ROOT / ".maafw"
USER.mkdir(parents=True, exist_ok=True)
RESOURCE = Path(os.environ.get("MAAFW_RESOURCE") or str(ROOT / "resource"))

kw = sys.argv[1] if len(sys.argv) > 1 else "March7th"
text = sys.argv[2] if len(sys.argv) > 2 else "日常"
debug_dir = os.environ.get("MAAFW_DEBUG_DIR")

Toolkit.init_option(str(USER))

if debug_dir:
    ctrl = DbgController(debug_dir)
    print(f"[ocr_test] 读图模式：DbgController({debug_dir})")
else:
    wins = Toolkit.find_desktop_windows()
    target = next(
        (w for w in wins if kw in (w.window_name or "") or kw in (w.class_name or "")),
        None,
    )
    if not target:
        print(f"[ocr_test] 没找到标题/类名含 {kw!r} 的窗口。")
        sys.exit(1)
    print(f"[ocr_test] 窗口: {target.window_name!r} class={target.class_name!r} hwnd={int(target.hwnd) if target.hwnd else 0}")
    ctrl = Win32Controller(
        hWnd=target.hwnd,
        screencap_method=MaaWin32ScreencapMethodEnum.Background,
        mouse_method=MaaWin32InputMethodEnum.PostMessage,
        keyboard_method=MaaWin32InputMethodEnum.PostMessage,
    )
    ctrl.set_screenshot_use_raw_size(True)

ctrl.post_connection().wait()
img = ctrl.post_screencap().wait().get()
print(f"[ocr_test] screencap shape={getattr(img, 'shape', None)}")

res = Resource()
res.post_bundle(str(RESOURCE)).wait()
print(f"[ocr_test] resource loaded={res.loaded} (path={RESOURCE})")

tk = Tasker()
tk.bind(res, ctrl)
print(f"[ocr_test] tasker inited={tk.inited}")

node = "FindBtn"
override = {node: {"recognition": "OCR", "expected": [text], "action": "DoNothing"}}
job = tk.post_task(node, override)
tdetail = job.wait().get()
st = getattr(tdetail, "status", None)
print(f"[ocr_test] task status={st} value={getattr(st, 'value', None)}")
print(f"[ocr_test] node_id_list={getattr(tdetail, 'node_id_list', None)}")

for nid in getattr(tdetail, "node_id_list", None) or []:
    nd = tk.get_node_detail(nid)
    if not nd:
        print(f"  node {nid}: None")
        continue
    r = nd.recognition
    hit = getattr(r, "hit", None) if r else None
    box = getattr(r, "box", None) if r else None
    print(f"  node {nid}: name={nd.name!r} completed={nd.completed} hit={hit} box={box}")
    if r and r.all_results:
        print(f"    all_results={r.all_results}")

