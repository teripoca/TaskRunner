# TaskRunner · 跨游打卡机

Windows 桌面任务队列运行器，用「鼠标点击 + 图像识别(OCR)」自动给多个游戏跑日常：
**明日方舟(MAA)、崩坏3(Maa_bbb)、崩坏：星穹铁道(March7th)、绝区零(OneDragon)、终末地(MaaEnd)**。

打开各游戏助手 → OCR 找到「开始/日常/Link Start!/启动一条龙」按钮 → 真实鼠标点击启动 → 等日志确认跑起来 → 跑完自动关掉。一个任务接一个任务排队跑。

---

## 一、环境要求

- **Windows 10 / 11（64 位）**
- **Python 3.11（64 位）**：安装时务必勾选 `Add Python to PATH`
  下载：<https://www.python.org/downloads/release/python-3119/>
- 你自己装好这些游戏自动化工具（放到任意目录都行）：
  - MAA（明日方舟）<https://github.com/MaaAssistantArknights/MaaAssistantArknights>
  - Maa_bbb（崩坏3，识宝小助手）
  - March7th（崩坏：星穹铁道，三月七小助手）
  - OneDragon（绝区零一条龙）
  - MaaEnd（终末地）
- 对应游戏本体；明日方舟还需 MuMu 模拟器

---

## 二、安装

1. **解压**本压缩包到一个**纯英文路径**目录，例如 `D:\TaskRunner`。
   > ⚠️ 整个路径不要含中文！否则 MaaFramework 加载 OCR 模型会报 `load_all_json failed`。

2. 装 Python 3.11（已装跳过）。

3. **装依赖**——打开「开始菜单」搜 `cmd` 或 `PowerShell`，执行：
   ```bat
   cd /d D:\TaskRunner
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
   ```
   这会安装 `maafw`（MaaFramework 的 Python 绑定，自带 onnxruntime/opencv/DirectML 等全部运行时 DLL）。国内必须加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 清华镜像，否则很容易超时失败。

---

## 三、配置各任务路径（首次必做）

不配置的话任务找不到你电脑上的工具，一定失败。

1. 双击 **`run.bat`** 打开界面（会弹 UAC，点「是」——必须以管理员身份运行，因为部分游戏助手是管理员权限，不提权鼠标点不动它）。
2. 左侧「可用任务」里**选中**一个任务，点左下角齿轮「设置」。
3. 在弹窗里填该任务需要的路径（可点「选择」浏览，也可直接粘贴；填**目录**或 **exe/lnk** 都行）：

   | 任务 | 需要填的路径 |
   |---|---|
   | March7th 星穹铁道 | March7th 目录 或 `March7th Launcher.exe` |
   | Maabbb 崩坏3 | Maa_bbb 目录 或 `MFW.exe` |
   | ZZZ 一条龙 | OneDragon 目录 或 `OneDragon-Launcher.exe` |
   | MAA 明日方舟 | ① MAA 目录 或 `MAA.exe`；② 明日方舟 MuMu 快捷方式 `.lnk`（可选，不填就请先手动打开 MuMu） |
   | MaaEnd 终末地 | ① MaaEnd 目录 或 `MaaEnd.exe`；② 终末地 `Endfield.exe`（可选，不填则跳过预启动） |

   留空的项，脚本会用内置默认路径（对不上你的电脑，所以能填就填）。「任务脚本位置」一般不用改。
4. 点「保存」。**每个任务都配一遍**。

---

## 四、运行

1. 双击 **`run.bat`**（管理员）。
2. 左侧「可用任务」**双击**任务，加入右侧「运行队列」，用 ↑↓ 调顺序。
3. 点「▶ 开始」。**运行期间不要动鼠标键盘**（脚本要操作鼠标点击）。
4. 想中途停：按 **F12**（或 Ctrl+Alt+F12），或点「■ 停止」。
5. 想某个任务失败后继续跑下一个：勾选「失败后继续下一个」。

---

## 五、常见问题

- **双击 run.bat 没反应 / 闪退**：多半是没装 Python 或 maafw。打开 cmd 手动跑看报错：
  `pythonw.exe app\script_task_runner_gui.py`（或 `python app\script_task_runner_gui.py`）。
- **界面能开但任务全失败**：先点界面上的「🩺 体检」检查脚本和路径；再看「运行日志」面板的失败原因和「建议」。
- **OCR 识别不到按钮 / 点击没反应**：① 确认是用管理员运行的 run.bat；② 运行某任务时，把对应助手窗口留在屏幕可见区域（脚本是真实鼠标点击，不是后台模拟）。
- **报 `load_all_json failed` / OCR 模型加载失败**：TaskRunner 所在路径含中文，移到纯英文路径。
- **pip install 超时**：确认加了清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

---

## 六、目录结构

```
TaskRunner/
├─ app/                  GUI 主程序（script_task_runner_gui.py）
├─ tasks/                5 个游戏的任务脚本
│  ├─ _common/           共用驱动：maa_driver.py（OCR 识别点击）
│  ├─ march7th/  maabbb/  onedragon/  maa_arknights/  maaend/
├─ resource/             OCR 模型（识别按钮用，勿删）
│  └─ model/ocr/         det.onnx / rec.onnx / keys.txt
├─ config/               配置
├─ tools/                辅助脚本（管理员启动、窗口调整）
├─ run.bat               启动器（以管理员身份打开 GUI）
├─ requirements.txt      依赖（maafw）
└─ README.md             本文件
```

> 首次运行时，`app/` 下会自动生成你的队列配置和历史记录文件；这些是你的本地数据，不随程序分发。
