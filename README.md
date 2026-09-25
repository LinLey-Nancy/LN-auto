# LN-auto

一个基于 MaaFramework 的 Windows 自动化通用框架。

当前已具备窗口发现与选择、Maa Win32Controller 连接、截图与模板识别、显式确认输入、画面变化验证，以及配置驱动的顺序工作流。正式业务模板和目标程序工作流仍需按实际界面制作。

当前开发状态、架构说明、已验证的输入兼容性结论和后续阶段计划见 [项目状态与路线图](docs/PROJECT_STATUS.md)。

## 运行自检

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m window_auto self-test
```

需要桌面工作流编辑器时安装 GUI 可选依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui]"
ln-auto-gui
```

桌面端当前支持新建、打开和保存 v2 工作流，添加及排序动作步骤，编辑步骤参数，只读选择目标窗口，选择 Win32 输入兼容策略，并在后台线程中运行或安全停止工作流。模板识别步骤可以选择已有模板，也可以按照引导从完整截图框选并创建本地模板；失败策略可设为“再次运行”，持续识别直到成功或用户停止；识别成功后可直接单击、双击或发送按键。延迟步骤支持固定时间和随机范围，键盘步骤支持配置按下持续时间，鼠标移动支持绝对坐标和相对距离。属性名称提供悬浮说明。运行前会再次显示目标窗口和输入策略确认，不会把 Maa Job 成功直接解释为目标应用已处理输入。

v2 工作流也可以从命令行运行：

```powershell
ln-auto workflow-run-v2 `
  --workflow config/workflow.v2.example.json `
  --input-profile foreground-precise
```

对于需要精确前台坐标的窗口，优先使用 `foreground-precise`：模板命中点会先从识别分辨率换算到原始客户区，再通过 `ClientToScreen` 得到实际屏幕像素；程序会恢复并置顶选中的目标窗口、校验最终鼠标位置，然后发送一次按下/抬起，避免 Maa `Seize` 在多显示器或特殊窗口布局中重复换算坐标。该策略会短暂占用物理鼠标。`background-window-message` 只适合已实测接受后台消息的目标程序；`foreground-compatible` 保留为 Maa 原生前台输入。目标程序以管理员权限运行时，自动化 GUI 也必须以管理员权限运行，否则 Windows 会以错误码 5 拒绝截图和输入消息。

也可在安装项目后使用：

```powershell
ln-auto self-test
```

只检查 MaaFramework 运行库版本：

```powershell
ln-auto maa-version
```

只读列出桌面窗口：

```powershell
ln-auto windows list
ln-auto windows list --title "窗口标题的一部分"
ln-auto windows list --class-name "窗口类名的一部分" --json
```

窗口枚举不会创建 Maa 控制器、截图或发送输入。

根据 `config/default.json` 唯一选择目标窗口：

```powershell
ln-auto windows select
ln-auto windows select --json
```

当前 `title_pattern` 按不区分大小写的标题子串匹配。匹配数量不是恰好一个时，选择会安全失败。

通用交互选择（推荐）：

```powershell
ln-auto windows choose
ln-auto windows choose --visible-only
ln-auto windows choose --title "标题的一部分"
```

程序会列出候选窗口并要求输入编号。`--index 0` 可用于非交互测试。当前步骤只返回本次选择，不保存配置。

运行最小控制器连接闭环：

```powershell
ln-auto run
ln-auto run --visible-only
ln-auto run --title "标题的一部分"
```

该命令会选择窗口、连接 Maa Win32Controller、按 `controller.capture_scope` 校验截图链路、加载资源包并执行 `FrameworkSelfTest`，然后安全释放。默认 `capture_scope: "window"` 仍会按 `expected_raw_resolution` / `expected_screenshot_resolution` 做严格检查；把这两个字段设为 `null` 可只检查截图长边，或把 `capture_scope` 设为 `"desktop"` 以整张桌面作为识别范围。任一分辨率不符合要求时会在发送输入前安全失败。自检 Pipeline 使用 `DirectHit + DoNothing`，不会发送输入。任务执行时间超过 `runtime.task_timeout_seconds` 时，程序会请求 Maa 停止任务并安全失败。

桌面为 1920×1080 时可使用 `"capture_scope": "desktop"`、`"expected_raw_resolution": null`、`"expected_screenshot_resolution": null`：识别范围是整张桌面，识别图仍按长边缩放到 `1280×720`；命中点会先换算到所选窗口 client，再交给 Maa 点击，命中点落在窗口外时不会发送输入。桌面范围模板要按桌面识别图制作；受权限或截图机制限制的目标仍可能需要窗口范围截图或管理员权限。

## 调试文件

所有运行时调试文件统一写入被 Git 忽略的 `debug/`：

```text
debug/
├─ logs/
├─ screenshots/
└─ reports/
```

截取一次所选窗口并保存到 `debug/screenshots/`：

```powershell
ln-auto capture
ln-auto capture --title "标题的一部分" --index 0
```

每次 `run` 或 `capture` 都会在 `debug/logs/` 生成独立日志。

裁剪临时模板并执行 Maa TemplateMatch：

```powershell
ln-auto template-match --title "示例应用" --index 0 --template-roi 20 10 200 35
```

临时模板只保留在内存中，不写入 `debug/`。匹配标注图和 JSON 报告分别写入 `debug/screenshots/` 和 `debug/reports/`；正式模板统一放在 `assets/resource/image/`。

执行一次明确坐标的双击并对比前后截图：

```powershell
ln-auto input-test --title "示例应用" --index 0 --point 280 205
```

默认需要输入 `YES` 才会发送双击，并明确提示目标可能被打开；自动化测试可显式传入 `--yes`。该诊断命令临时使用 MaaFramework 的 `Seize` 前台鼠标输入，以产生 Windows 能够识别的原生双击，因此执行时会短暂激活目标窗口并占用物理鼠标。两次点击间隔 100ms，前后截图、差异图和 JSON 报告均写入 `debug/`。

根据模板识别结果自动计算中心坐标并执行操作：

```powershell
ln-auto template-action --title "示例应用" --index 0 --template assets/resource/image/start.png --action click
```

正式模板统一存放在 `assets/resource/image/`。该目录中的本地模板已被 `.gitignore` 排除，不会提交到 GitHub；仓库只保留 `.gitkeep`。在尚未制作正式模板时，也可以从当前画面裁剪一块仅驻留内存的临时模板来验证完整流程：

```powershell
ln-auto template-action --title "示例应用" --index 0 --template-roi 200 190 150 32 --action double-click
```

执行器仅在 MaaFramework 模板匹配成功后发送输入，并使用匹配框中心而不是固定坐标。默认需要输入 `YES` 确认；可显式传入 `--yes`。目标标注图、操作前后截图、差异图和 JSON 报告均写入 `debug/`。

本地工作流保存在 `projects/`。上传 GitHub 时仓库保留 `projects/.gitkeep` 和 `assets/resource/image/.gitkeep`，但忽略这两个目录中的本地工作流与模板图片，避免上传目标程序配置和用户截图。

## 打包 Windows 安装包

打包脚本位于 `scripts/`，产物输出到 `dist/`：

```powershell
scripts\build_installer.bat
```

或直接用项目环境运行：

```powershell
.\.venv\Scripts\python.exe scripts\build_installer.py
```

脚本读取 `pyproject.toml` 中的版本号，先用 PyInstaller 把 GUI 打包为免 Python 环境的应用目录（`build/pyinstaller/dist/LN-auto/`），再调用 Inno Setup 生成安装包 `dist/LN-auto-v<版本号>-Setup.exe`（当前为 `LN-auto-v0.1.0-Setup.exe`）。

前置条件：

- 项目虚拟环境已安装 `packaging` 可选依赖：`uv pip install --python .venv\Scripts\python.exe -e ".[gui,packaging]"`（脚本检测到缺失时会尝试自动安装）。
- 已安装 Inno Setup 6：`winget install --id JRSoftware.InnoSetup -e`。脚本会自动查找常见安装位置；自定义位置可用环境变量 `LN_AUTO_ISCC` 指向 `ISCC.exe`。

安装包默认安装到 `%LOCALAPPDATA%\Programs\LN-auto`（免管理员权限），提供桌面快捷方式选项，覆盖安装会复用同一 AppId 直接升级。

## 配置驱动的顺序工作流

把 `config/workflow.example.json` 复制为被 Git 忽略的 `config/workflow.local.json`，将每一步的 `template` 指向 `assets/resource/image/` 下的本地模板，然后执行：

```powershell
ln-auto workflow-run --title "示例应用" --index 0 --workflow config/workflow.local.json
```

当前工作流是普通的顺序步骤列表，不是条件状态机。每一步支持以下配置：

- `template`：相对项目根目录或绝对路径的 PNG 模板。
- `threshold`：MaaFramework 模板匹配阈值。
- `action`：`click` 或 `double-click`。
- `recognition_attempts`：发送输入前的最大识别次数，范围为 1–100。
- `recognition_interval_ms`：识别失败后的重试间隔。
- `pre_delay_ms` / `post_delay_ms`：步骤执行前和操作后的等待时间。
- `require_visual_change`：操作后是否必须检测到画面变化。

只有“尚未识别到模板”会触发识别重试。输入一旦发出，即使后续截图或画面验证失败，也会立即停止工作流，不会自动重复点击。
