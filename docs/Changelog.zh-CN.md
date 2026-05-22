# Changelog - OmniPack

## [v9] - WinGet 系统级与用户级包管理支持 (WinGet System & User Package Management)

本次更新新加入了 Windows 系统内置包管理器 **WinGet** 的完整集成，支持对系统全局以及当前用户级别的软件进行可视化扫描、自动更新、锁定（Pin）、卸载与安装。同时完成了 UI 面板注册架构重构，支持在不同操作系统下动态加载对应管理器。

### 🚀 WinGet 深度整合 (WinGet Support)

- **环境双 Scope 扫描 (Dual Scope Scanning)**：
  - 支持 **系统范围 (System/Machine)** 与 **用户范围 (User)** 的独立环境扫描，分别对应虚拟路径 `winget://machine` 和 `winget://user`。
  - **智能跨范围数据迁移与去重 (Smart Package Redistribution)**：读取 Windows 注册表 `Uninstall` 键下的 `InstallLocation`（支持 32/64 位及 HKLM/HKCU 注册表路径，支持 %USERPROFILE% 等前缀分析），将物理路径在用户目录下的软件智能划归为 User 范围，将 Program Files 等目录下的软件划归为 Machine 范围；若同一应用在两个范围重复安装，卡片上会自动显示 `[Also Installed In User/Machine]` 徽章标记，防重复探测。
- **等宽列切片命令行解析 (Console Tabular Parser)**：
  - 使用字符渲染宽度解析机制（自动对东亚宽字符进行 `padding/restore`），通过固定列宽切片，彻底解决了 Winget 本地化（多语言）输出以及部分列数据为空时导致的列错位、合并漂移等解析难题。
- **生命周期完整管控 (Full Lifecycle Actions)**：
  - **安装 (Install)**：支持直接输入 WinGet ID 进行精准安装，支持自动推荐及静默安装。
  - **更新 (Update & Batch Update)**：支持对单款应用更新，或勾选多款应用进行 **批量并发升级**。
  - **静默/交互卸载 (Uninstall/Remove)**：支持单款及批量并发静默卸载，带有安全确认对话框。
  - **锁定更新 (Blocking Pin)**：原生集成 `winget pin`。用户可以在 UI 界面通过 ⚙ 按钮直接锁定软件更新，锁定后显示 `[Pinned]` 徽章，同时不会被 "Outdated" 全局选项自动勾选。
  - **版本异常与降级保护**：当本地安装版本新于 Registry 注册表最新版本时，自动显示 `[⚠ Newer]` 徽章并阻止误升级。
  - **多层 Scope 自动回退 (Scope Fallback)**：当安装或升级因权限/路径冲突在 Machine 范围失败时，会自动回退尝试以 `user` 范围（如 `winget install --scope user`）再次运行，最大程度保障操作成功率。

### ⚙️ 后端设置与实时诊断 (WinGet Settings & Diagnostics)

- **WinGet 后端管理 (Backend Settings)**：
  - Settings 页面新增 WinGet 后端设置（仅在 Windows 操作系统下可见）。
  - **自定义引擎路径**：支持自动探测系统 PATH 上的 `winget.exe`，也支持用户手动浏览并指定特定路径。
  - **安装模式选择**：支持配置默认的安装模式：静默模式 (`silent`)、交互模式 (`interactive`)、默认模式 (`default`)。
  - **实时诊断面板**：可在 Settings 界面实时查看 WinGet 可用状态、绝对路径、当前版本号、已开启的 Registry 源个数以及详细的源状态错误。

### 🏗️ UI 面板注册重构 (Unified Panel Registration)

- **动态面板系统**：
  - 重构了主窗口 `ui/main_window.py` 内部结构，将写死的 Pip/Npm 面板完全抽象，改为基于配置字典的 `_register_panel()` 动态面板注册机制。
  - **按平台加载**：仅当检测到 Windows 系统时才注册 WinGet 面板，其他系统自动隐藏，消除了跨平台冗余。
  - 统一了动态 Splitter 尺寸联动同步、首屏卡片防抖懒加载扫描、状态栏 counts 更新以及当前活动 Tab 的持久化记忆逻辑。

### 📦 通用控件与编译增强 (General Widget & Script Improvements)

- **徽章渲染系统扩展**：`PackageCard` 增加元数据 Badge 渲染机制，支持带有悬停提示 (ToolTip) 与自定义 QSS 样式的多种彩色徽章（如 `[Pinned]`、`[Also Installed]`、`[⚠ Newer]`、`[Unknown]`）。
- **可配置化 gear 动作按钮**：当包 metadata 标记 `supports_config` 为 True 时，卡片上会自动渲染 `⚙` 配置图标并绑定专属弹窗（如 Python/Npm 显示 tag/版本，WinGet 显示 Pin/卸载路径等）。
- **跨平台 Nuitka 编译缓存清理补丁**：
  - 优化了 `scripts/patch_nuitka_msvc.py` 中的 pyc 缓存清理机制，使用 `importlib.util.cache_from_source(path)` 进行动态缓存路径解析，不再依赖硬编码的 Python 版本后缀，自动清理全平台/多版本 `__pycache__` 缓存。

---

## [v8] - 编译器加固、运行时安装回退与交互增强 (Compiler Hardening, Installer Fallback & UX)

本次更新围绕三大主题：构建系统从单一 Zig 编译器升级为 MSVC 优先的智能编译链（兼顾缓存与性能）、winget 不可用时自动回退至官方安装器下载、以及一键展开/折叠等多项 UI 交互改进。

### 🛠️ 构建系统 MSVC 编译器支持 (MSVC Compiler Toolchain)

此前构建仅使用 Zig 编译器后端，无法利用 MSVC 的跨构建缓存（clcache）加速。本轮实现完整 MSVC 自动检测链：

- **`detect_msvc_env()` 自动检测引擎**：支持三层搜索策略——① 显式路径（`msvc_path.cfg` 配置文件 → `MSVC_VCVARS_PATH` 环境变量 → VS Insiders 默认路径）；② VS Insiders 扁平布局（`Microsoft Visual Studio\18\Insiders\VC\Auxiliary\Build\vcvars64.bat`）；③ 传统布局（`<year>\<edition>\VC\Auxiliary\Build\vcvars64.bat`）。找到 `vcvars64.bat` 后通过 `_capture_vcvars_env()` 捕获完整环境变量并通过 `MSVC_USE_SCRIPT` 传递给 SCons。
- **`_capture_vcvars_env()` 路径空格修复**：使用 `shell=True` + `cmd /V:ON /C "call \"<path>\" && set"` 替代手动拼接命令串，彻底解决 Visual Studio 路径含空格时 `subprocess.run` 参数解析失败的问题。
- **编译器优先级**：`detect_msvc_env()` 成功 → 使用 MSVC（`--msvc=X.Y`）；失败 → 回退 Zig。MSVC 模式下可复用 clcache 跨构建缓存，大幅加速重复编译。
- **`build_app.py` 命令行参数**：新增 `--clean` 选项（清理 dist 目录后全量重编译），不带参数时默认增量构建复用缓存。
- **Nuitka MSVC 补丁脚本**：新增 `scripts/patch_nuitka_msvc.py`，为 Nuitka 的 `SconsUtils.py` 注入 `MSVC_USE_SCRIPT` 环境变量支持，使得 SCons 能通过环境变量而非注册表/vswhere 发现非标准安装的 Visual Studio（如 Insiders 版）。支持 `--check` / `--revert` 操作，自动清理 `.pyc` 缓存。
- **入口点重命名**：`OmniPack.pyw` → `OmniPack.py`，构建与调试入口统一。

### 🔄 运行时安装器回退：winget 不可用时的自动救援 (Runtime Installer Fallback)

`winget` 在某些系统/网络环境下源不可用（`failed when opening source` / `0x8d15000f`），导致 Python/Node.js 运行时更新完全失败。本轮新增从官方源下载安装器的完整回退链路：

- **下载引擎**：`download_runtime_installer()` 从 `python.org` / `nodejs.org` 下载官方安装器到临时目录，支持断点监控（每 ~0.8s 或每 5 MiB 回调进度），下载不完整自动清理。
- **静默安装命令生成**：`build_installer_run_command()` — Python 使用 `/quiet InstallAllUsers=1 PrependPath=1`；Node.js 使用 `msiexec /i <msi> /quiet /norestart`。
- **winget 失败检测**：`RuntimeUpdateWorker` (pip/npm) 检测子进程输出中的 `failed when opening source` 或 `0x8d15000f`，区分 "winget 源不可用" 与 "其他命令失败"。
- **`runtime_update_done` 信号扩展**：从 3 参数 (`env_path, success, message`) 扩展为 5 参数 (`env_path, success, message, winget_failed, target_version`)，下游 Panel 可判断是否需要触发安装器回退。
- **用户交互对话框**：`_offer_installer_fallback()` 弹出三选项对话框 — "Download & Install" 自动下载并静默安装、"Open Download Page" 在浏览器中打开下载页、"Cancel" 跳过。
- **`RuntimeInstallerWorker`**：在 `pip_panel.py` / `npm_panel.py` 中分别实现，基于 `BaseCmdWorker` 共享基类，实时输出下载进度与安装状态到控制台。

### 🖥️ UI 交互增强 (UI/UX Improvements)

- **一键展开/折叠所有环境卡片**：工具栏新增 `Expand` 三态复选框。部分展开时显示半选态（`PartiallyChecked`），点击后统一展开；全展开时显示勾选态，点击后全部折叠。每个环境卡片展开/折叠时通过 `expand_toggled` 信号驱动复选框状态同步。
- **Settings 环境列表增强**：拖拽排序保存后，主界面卡片顺序即时同步重排（`_reorder_env_cards()`）；双击编辑已有环境；按 `Delete` 键快捷删除选中项（`eventFilter` 监听 `Qt.Key_Delete`）；提示文案更新为 "Drag to reorder; Double click to edit; Del key to remove"。
- **Settings Auto Detect 重构**：Python 自动扫描从内联路径遍历重构为调用 `find_system_pythons()` 统一函数，利用带标签的扫描结果（`py_info["name"]` / `py_info["tags"]`）通过 `config_mgr.add_pip_env()` 正式接口添加，消除重复代码。

### 🧠 依赖解析增强 (Dependency Resolution)

- **PEP 508 环境标记求值引擎**：`dep_resolver.py` 新增完整的 marker 解析与求值链 — `split_requirement_marker()` 分离 requirement 与 marker → `marker_applies()` 优先使用 `packaging.markers.Marker.evaluate()`（若可用）→ `_evaluate_marker_fallback()` 内置回退求值器。支持 `python_version`、`sys_platform`、`os_name`、`platform_machine` 等全部标准 marker 变量，自动跳过不适用于当前平台/环境的依赖项（如 `sys_platform != "win32"` 的条件依赖不再污染 Windows 上的依赖树）。
- **版本约束智能简化**：`simplify_constraint()` 合并冗余约束 — `>=1.0, >=1.5` → `>=1.5`；`<2.0, <=1.9` → `<=1.9` — 使依赖树中显示的需求更清晰精简。
- **`_restore_package_state()` 新参数**：新增 `restore_update_state` 开关。完整后台扫描（`--outdated` 已重新查询）时设为 `False`，不再从旧包状态恢复过期的 `has_update` / `latest_version`，避免陈旧数据污染新扫描结果。

### 📦 NPM 环境路径解析修正 (NPM Path Resolution)

- **`resolve_env_command_context()` 统一方法**：替代此前分散在各 Worker 中的 `is_global = (env.type == "global" or env.path == "global")` 判断。正确识别三种场景：
  - 标记为 global → `-g` 标志，无 cwd
  - 路径为 `%APPDATA%\npm\node_modules`（Roaming 全局包）→ `-g --prefix <dir>`，确保更新包文件同时刷新同级 CLI shims
  - 路径以 `node_modules` 结尾 → cwd 为其父目录，支持本地项目
- **`roaming_modules_path()`**：返回 Windows Roaming npm 的 `node_modules` 路径。
- **`get_global_prefix_and_root()`**：通过 `npm prefix -g` / `npm root -g` 查询全局安装位置。
- 所有 NPM Worker（`NpmScanWorker`、`NpmUpdateCheckWorker`、`NpmActionWorker`、`NpmBatchUpdateWorker`）统一采用新方法并支持 `--prefix` 参数。

### ⚡ 控制台日志优化 (Console Log Refinements)

- **命令感知心跳标签**：`\r` 进度行与 `\n` 日志行分流处理 — `\r` 结尾的行视为进度条更新（按 ~0.8s 节流避免刷屏），`\n` 结尾的行即时输出。
- **上下文感知心跳**：长时间无输出时的心跳消息根据命令类型动态切换 — `uv/pip` → "downloading/installing packages..."，`npm` → "downloading npm packages..."，`winget` → "waiting for winget..."。
- **长静默提示精简**：30 秒无输出的提示从多行详细说明精简为一行 "still no output from subprocess — large download or build in progress"。
- **`uv -v` 详情标志**：`UpdateWorker`、`BatchUpdateWorker`、`InstallWorker` 中 `uv pip install` 命令统一添加 `-v` 标志，提供更丰富的下载/构建日志。

### 🐧 跨平台增强

- **macOS Python.org 框架路径**：`find_system_pythons()` 新增扫描 `/Library/Frameworks/Python.framework/Versions/X.Y/bin/python3`，自动发现通过官方 pkg 安装的 Python。

---

## [v7] - 打包加固与离线缓存 (Packaging Hardening & Offline Cache)

### 🔒 配置文件持久化修复 (Persistent Config)

Nuitka onefile 模式下配置文件 (`omnipack_config.json`, `pypi_search_cache.json`) 此前被写入系统临时目录（`%TEMP%\.onefile_XXXXX\`），重启后丢失。根因是 Nuitka 不设 `sys.frozen`（PyInstaller 专属标志），导致应用误判为开发模式，通过 `__file__` 解析路径进而指向临时解压目录。

- **Nuitka 检测重构**：新增 `_is_frozen()` 双路径检测——PyInstaller 的 `sys.frozen` + Nuitka 的 temp 目录特征（`__file__` 位于 `%TEMP%` 下即为 onefile 解压运行）。
- **真实路径解析**：新增 `_get_real_exe_path()`，通过 Windows API `GetModuleFileNameW(NULL)` 向内核查询进程真实 exe 路径，彻底绕过 Nuitka/PyInstaller 对 `sys.executable` 和 `sys.argv[0]` 的路径改写。`get_persistent_root()` 与 `get_app_root()` 中所有 `sys.executable` 引用统一替换为此 API。
- **便携与安装模式不变**：便携模式（exe 不在 Program Files 下）仍将配置保存在 exe 同级目录；安装模式（Program Files 下）仍使用 `%APPDATA%\OmniPack`。

### 🛡️ 打包安全加固 (Package Security)

- **源码泄露堵漏**：`get_data_files()` 新增后缀过滤，跳过 `.py`、`.pyc`、`.pyo` 文件。Nuitka 已将所有 import 的 `.py` 编译为机器码，再通过 `--include-data-file` 附加一份原始源码纯属泄露风险且徒增体积。打包后 `ui/` 目录仅保留 `ui/styles/dark.qss`（Qt 样式表，运行时从文件路径加载），不含任何 Python 源码。
- **黑名单跨目录匹配修复**：`should_ignore()` 新增 basename 匹配——模式 `Architecture.zh-CN.md` 现在能正确命中 `docs/Architecture.zh-CN.md`。此前仅对完整路径做 `fnmatch`，无路径前缀的文件名模式无法匹配子目录下的同名文件。

### 📦 预装完整 PyPI 缓存 (Bundled PyPI Cache)

- **`pypi_search_cache.json` 打包**：构建时将此文件打入 exe 数据区（804,825 包索引）。`ensure_cache_exists()` 查找优先级调整为：持久化缓存 → 打包完整缓存 → 种子文件 → 硬编码 20 包默认。首次启动时自动将打包缓存复制到持久化目录，用户无需等待首次在线刷新即可搜索全部包名。

### ⚡ 批量更新链路与控制台可见性优化 (Batch Update Flow & Console Visibility)

本轮进一步把"点了 Update 像没反应"这一整条链路做了系统修复与提速，重点是：**批量更新不再静默失败、更新完成后先快刷界面、长时间子进程持续给出存活反馈**。

- **批量更新按钮无响应修复**：修正 `pip_panel` / `npm_panel` 中批量更新收集阶段将 `Environment` dataclass 作为字典键使用的问题。`Environment` 默认不可哈希，选中可更新包后会在内存中抛出 `TypeError: unhashable type: 'Environment'`，表现为工具栏 `Update` 点击后"没有任何反应"。现改为统一使用规范化环境路径作为键，并单独维护环境对象映射。
- **同环境合并、跨环境并行保持有效**：批量更新仍然维持"同环境合并为一条命令、不同环境并行执行"的策略；本次修复后，跨多个 Python / NPM 环境勾选更新时会稳定并发启动多个 worker，不再因为键错误中断。
- **控制台时间戳开关**：右侧控制台标题栏 `Clear` 右侧新增 `timestamp` 复选框。启用后，每行日志前缀显示绝对时间与相对耗时（`[HH:MM:SS.mmm | +X.XXXs]`），并在 `Clear` 或重新勾选时重置计时基准，便于定位瓶颈究竟在下载、刷新还是依赖树解析。
- **日志重复渲染移除**：此前 Worker 日志会先实时输出一次，任务结束后又通过 `log_batch` 整批重放到同一控制台，造成文本插入、重绘和 `processEvents()` 成本翻倍。现在保留逐行实时输出，移除结束后的重复回放，显著降低控制台造成的额外卡顿。
- **机器 JSON 输出静音**：`uv pip list --format json`、`uv pip list --outdated --format json`、`npm list --json`、`npm outdated --json`、`npm view dist-tags --json` 这类仅供程序解析的机器输出不再整段刷入控制台。控制台保留命令行、状态提示和摘要（如 `Loaded JSON for N packages.`），避免大段 JSON 本身拖慢 UI。
- **Python 更新后快速刷新 (Fast Refresh)**：Python 环境在包更新 / 安装 / 卸载 / 运行时升级完成后，不再立刻执行完整重扫。新流程改为：先做一次快速刷新，仅重新获取当前已安装包列表并立即恢复左侧界面；随后在后台补做 `--outdated` 查询与依赖树重建。这样用户先拿到可交互界面，再异步补齐完整更新状态与树形结构。
- **快刷状态复用**：快速刷新阶段会尽量复用旧的勾选状态、依赖树拓扑、版本风险标记与未变化包的更新状态，避免界面短暂掉成"0 updates"或丢失已展开/已选中的上下文。
- **仅刷新受影响环境**：Python 包更新、安装、卸载完成后只刷新真正发生变更的环境，不对未涉及的其他环境做重复扫描；运行时更新完成后同样优先走该环境的快速刷新，再后台补完整扫描。
- **后台完整刷新并行执行**：快速刷新结束后，后台完整刷新按环境并发启动。这样多个环境的 `uv pip list --outdated` 与依赖树解析可以并行跑，总墙钟时间更短，同时不会阻塞左侧第一时间恢复。
- **长任务心跳反馈（pip / npm 共用）**：在共享 `BaseCmdWorker` 中新增子进程心跳逻辑。任何通过该基类执行的命令（包括 `uv pip install`、`npm install`、`npm uninstall`、批量更新等）如果连续 5 秒无任何 stdout/stderr 输出，控制台会自动追加 `... still running (12.3s elapsed)` 一类状态行，显著降低大包下载、大项目安装或 registry 查询期间的"假死感"。由于该逻辑位于共享基类，NPM 安装与批量更新链路自动获得同等反馈，无需单独复制实现。
- **长静默原因提示与“无实际变更”说明**：若子进程持续约 30 秒没有任何输出，控制台会追加一条提示，明确说明可能原因包括大包下载/构建、索引或网络缓慢、以及等待其他包管理进程或文件锁释放。对于 `uv pip install -U ...` 成功退出但未报告 `Prepared / Installed / Uninstalled` 的情况，系统不再笼统显示“已更新”，而会改为提示“本次未报告包文件变更，可能先前一次中断的运行已经完成更新”，避免用户误判。

---

## [v6] - 性能、可靠性与可见性 (Performance, Reliability & Visibility)

v6 围绕四个主题系统性地提升日常使用体验：批量更新从串行变为并行（**更快**）、Windows venv 版本检测与升级链路彻底修复（**更准**）、控制台从"沉默黑盒"变为实时终端（**更透明**）。

### 🚀 批量更新性能跃升 (Batch Update Performance)

核心思路是**合并 + 并行**：同一环境的包合并为一条命令，不同环境之间并行执行。

- **同环境命令合并**：同一环境中选中的多个包不再逐个执行 `uv pip install -U <pkg>` / `npm install <pkg>`，而是合并为一条 `uv pip install -U pkg1 pkg2 ...` 或 `npm install pkg1@ch1 pkg2@ch2 ...`。`uv` 和 `npm` 内置异步 I/O 并行下载与解析，单命令多包即可获得数倍加速。npm 批量更新时保留各包的 dist-tag 通道信息，不丢失更新目标。
- **跨环境并行执行**：当批量更新涉及多个不同虚拟环境或项目目录时，系统同时启动多个 `BatchUpdateWorker` 并行执行——不同环境目录之间完全独立，无文件锁冲突。按环境路径分组调度，同一环境的所有包合并为一个 worker，不同环境的 worker 并行启动。`_active_update_envs` 集合替代了原有的单一 `_update_running` 布尔标志，支持同时追踪多个正在更新的环境，某环境忙时新请求自动回流队列等待。
- **架构支撑**：新增 `BatchUpdateWorker` (pip) 与 `NpmBatchUpdateWorker` (npm)，配套 `batch_update_done` 信号携带包名列表。单包 `update_package` 与 `update_done` 信号保留，`_on_update_done` 委托至 `_on_batch_update_done`，向下兼容。

| 场景 | v5 (串行) | v6 (并行批量) |
|------|-----------|--------------|
| 1 个环境选 5 个包 | 5 次 `uv pip install` | 1 次 `uv pip install pkg1 ... pkg5`，uv 内部并行 |
| 3 个环境各选 3 个包 | 9 次串行命令 | 3 条命令同时执行 |

### 🖥️ 控制台实时可见性 (Real-time Console Visibility)

此前控制台有两个层面的缓冲导致"假卡死"：输出信号从未实时发射；扫描 Worker 使用阻塞式 `subprocess.run()`。两者叠加，用户在长时间操作中完全看不到进展。

- **`log_msg` 信号激活**：`BaseCmdWorker._log()` 在追加内存 buffer 的同时立即发出 `log_msg` 信号——该信号虽早已声明并完整连接至 UI（Worker → Manager → Panel → ConsolePanel），但此前从未被 `emit`，所有输出仅在 `run()` 结束时通过 `_flush_logs()` 批量投递。修复后安装、卸载、更新等操作的输出逐行实时抵达控制台。
- **扫描 Worker 流式化**：`_run_command()` 新增 `capture_output` 参数——reader 线程在逐行流式输出的同时收集完整 stdout/stderr，以 `CompletedProcess` 返回供调用方解析 JSON，兼顾实时显示与结果捕获。`ScanWorker` (pip)、`NpmScanWorker` (npm)、`NpmUpdateCheckWorker` (npm) 中全部 `subprocess.run()` 替换为 `self._run_command(capture_output=True)`。最慢的 `uv pip list --outdated`（5-30 秒逐包查询 PyPI）执行前新增 "Checking for package updates..." 状态提示。
- **UI 即时刷新**：`ConsolePanel.log()` 在每条日志插入后调用 `QApplication.processEvents()`，强制 Qt 在子进程运行期间立即重绘控件。reader 线程中的 `Signal.emit()` 由 PySide6 自动排队投递至主线程事件循环，线程安全无需额外加锁。

### 🔧 Windows 虚拟环境：版本检测与运行时升级修复 (Venv Version Detection & Runtime Upgrade)

三个改动共同解决同一个问题链：Windows 上 venv 的版本显示、检测和升级曾经全线存在失真与空操作。

- **pyvenv.cfg 无条件优先**：移除了 `type != "system"` 的类型前提——现在**所有**环境扫描时均读取 `pyvenv.cfg`（若存在）的 `version` / `version_info` 字段。此前若 venv 被误标为 system 类型，会跳过 pyvenv.cfg 回退逻辑，直接使用 `python --version` 结果——而 Windows 上 venv 的 python.exe 是加载系统 Python DLL 的 redirector，在系统 Python 通过 winget 升级后即返回系统版本，导致所有 venv 卡片版本集体虚高。另：`read_venv_cfg_version()` 不再静默吞掉异常，`_on_env_scanned` 回调新增 `card.env = env` 显式赋值消除竞态。
- **虚拟环境两步式运行时升级**：点击 venv 卡片的 `Py` 按钮后，系统会**先**通过 winget 升级对应 major.minor 周期的系统 Python（如 `Python.Python.3.14`），**再**执行 `py -X.Y -m venv --upgrade <venv_root>` 升级虚拟环境本体。此前仅执行后一步，若系统 Python 尚未更新则 venv upgrade 实质为空操作。winget 步骤容错（非零退出码记录警告但继续），确认对话框差异化提示完整操作步骤。
- **构建命令返回类型统一**：`build_python_runtime_update_command`、`build_node_runtime_update_command`、`build_node_runtime_update_command_nvm` 返回类型从 `list[str]` 统一为 `tuple[Optional[list[list[str]]], str]`，支持多步命令序列。`RuntimeUpdateWorker` 与 `NpmRuntimeUpdateWorker` 同步适配——这正是两步式升级（winget 探测 → venv upgrade）的底层支撑。

### 🔧 版本号统一 (Single Version Source)

- 新增项目根目录 `version.py`（`__version__ = "6"`），消除此前 `build_app.py`、`config.py`、多处 User-Agent 字符串中各自硬编码版本号的问题。窗口标题栏现显示版本号（`OmniPack v6 - Developer Package Manager`），所有对外 HTTP 请求的 User-Agent 头统一为 `OmniPack/<version>`。

---

## [v5] - 约束感知更新与构建变体识别 (Constraint & Variant Awareness)

本次更新聚焦于提高包更新场景的安全性——系统智能判断哪些更新是安全的、哪些存在潜在风险，避免用户在不自知的情况下破坏环境。

### 🧠 智能更新过滤：约束感知的 "Outdated" 勾选
- **约束感知自动勾选**：开启“Outdated”过滤时，系统不再盲目全选所有可更新的包。若一个包的最新版本违反了其依赖者的版本约束（如 `sympy` 要求 `mpmath<1.4`，而最新版为 `1.4.1`），则该包**不会被自动选中**。
- **PEP 440 约束解析器**：新增 `check_version_satisfies_constraint()` 引擎，完整支持 `>=`, `<=`, `>`, `<`, `==`, `!=`, `~=` 运算符及逗号分隔的 AND 组合逻辑。
- **依赖拓扑审计**：扫描完成后自动遍历依赖树，检查每个包的最新版本与其 `required_by` 反向引用中所有约束的兼容性。

### 🔵 构建变体识别 (Build Variant Awareness)
- **本地版本后缀解析**：自动检测 PEP 440 本地版本标识（`+cu132`, `+cpu`, `+rocm5.6`, `+cu118` 等），识别包的硬件平台变体。
- **变体差异警报**：当已安装版本带有 `+xxx` 后缀而最新版本不带（或后缀不同），系统将该包标记为“构建变体切换”——更新将改变包的硬件兼容层（如 CUDA → CPU）。
- **跳过自动选中**：构建变体切换的包同样不会被 `Outdated` 自动选中，需用户手工确认。

### ✨ 风险可视化与交互升级
- **三级风险色系统**：
  | 场景 | 标识 | 文字颜色 | 含义 |
  |---|---|---|---|
  | 普通更新 | `➜` | 青绿 `#4dd4ac` | 安全可升 |
  | 构建切换 | `🔀` | 亮蓝 `#4cc9f0` | 可能切换平台 |
  | 约束冲突 | `⚠` | 橙黄 `#f0a040` | 可能破坏依赖 |
- **确认对话框**：点击构建变体或约束冲突包的更新按钮时，会弹出风险提示对话框，告知用户具体的风险详情，确认后方可继续。
- **鼠标悬停提示**：风险包的文字标签鼠标悬停时显示详细的约束来源或变体切换信息。

### 🎨 UI 视觉统一
- **更新按钮双色对齐**：正常更新按钮（绿色）与风险更新按钮（蓝/棕黄色）视觉区分，避免误操作。
- **版本文本色彩重构**：重新梳理了版本文本的颜色语义，确保每种状态都能被快速视觉识别。

---

## [v4] - 环境管理统一与跨平台增强

本次更新聚焦于环境管理统一、跨平台路径与启动策略对齐、以及源配置的一致体验。以下内容以当前代码为准。

### 🆕 运行时版本检测与独立更新链路 (Python / Node Runtime)
- **虚拟环境版本显示修正**：Python venv 卡片版本显示优先读取 `pyvenv.cfg`（`version` / `version_info`），避免系统 Python 小版本升级后导致卡片误显示。
- **运行时元数据入模**：`Environment` 新增 `runtime_version`、`runtime_cycle`、`runtime_latest_version`、`runtime_has_update`、`runtime_update_error` 等字段，统一承载解释器级更新状态。
- **多源补丁检测回退**：运行时最新补丁检测采用多级策略（`endoflife.date` -> `winget` -> Python 本机已安装扫描回退），提升在网络波动和镜像差异下的稳定性。
- **Python / Node 对称实现**：Pip 与 Npm 扫描均会写入运行时版本信息，Node 卡片新增运行时版本展示（如 `Node 25.8.1 -> 25.9.0`）。
- **更新语义彻底解耦**：新增独立运行时更新按钮（`Py` / `Nd`）及独立 Worker 信号链路（`runtime_update_done`）；原有 `⇧` 继续仅负责包更新，不再混淆“环境本体更新”。

### ⚙️ 环境管理与持久化 (Unified Environment Management)
- **首次扫描持久化**：系统 Python 自动发现仅在首次运行时执行，结果写入配置文件，后续以配置为单一事实来源。
- **用户可控排序**：Settings 中支持拖拽排序，顺序会实时回写到配置。
- **[PATH] 标签**：Python 环境若其可执行文件目录在 `PATH` 中，会显示 `[PATH]` 标签。
- **去重一致性**：路径比较统一使用 `normcase(normpath(path))`，避免 Windows 大小写/分隔符差异导致重复。
- **环境管理“逻辑大统一”**：重构 `SettingsDialog`，通过映射驱动实现了 Pip 环境与 NPM 项目管理逻辑的高度复用，成功消除数百行冗余代码。
- **手动添加 QMenu 模式**：点击 `Add Manually...` 弹出专业菜单，支持“选择目录”与“选择文件/可执行文件”双入口，操作指引更明确且一致。
- **Python 深度探测报告**：`Detect System` 重构为后台全量扫描（PATH + Programs + AppData），并新增可视化扫描报告弹窗。
- **废弃代码物理重构**：物理移除旧版 `pip_env_manage_dialog.py` 与 `npm_env_manage_dialog.py` 环境管理对话框。

### ⚙️ 核心引擎与自动化 (Kernel & Automation)
- **内置 uv 引擎**：构建脚本 (build_exe.py) 支持自动将系统 `uv` 引擎打包进 `bin/` 目录，实现分发版本的零依赖运行。
- **级联寻找逻辑**：实现 `User-defined > Bundled > System PATH` 三级级联寻址，确保在任何环境下都能找到最优的执行引擎。
- **异步自更新 UI**：设置界面新增 `Check for Update` 按钮，采用 QThread 异步执行 `uv self update`，并辅以动态“呼吸式”按钮动画提示。
- **版本智能比对**：通过 GitHub API 实时拉取 `uv` 最新版本，并与本地引擎版本进行精准比对（支持正则解析），高亮提示更新。
- **引擎状态富文本**：版本检测结果支持 HTML 格式化显示，直观展示更新差异。
- **打包自动化增强**：构建脚本 (`build_app.py` / `build_exe.py`) 自动同步 `resources/` 资源目录、捆绑 `uv` 引擎并拷贝文档文件至分发包目录。
- **共享 Worker 基类抽取**：将 Pip/Npm 两端重复的 QThread 子进程执行逻辑抽取为 `managers/base_worker.py` 的 `BaseCmdWorker`，统一处理 stdout/stderr 线程流式读取、ANSI 转义码剥离、日志缓冲批量发送，消除冗余代码。
- **跨平台构建脚本**：新增 `build_app.py`，支持 Windows/macOS/Linux 三平台一键 Nuitka 打包，自动处理图标格式转换（PNG→ICO/ICNS）、平台特定编译参数与 macOS .app Bundle 生成。


### 🧠 NPM 与包管理强化
- **路径感知**：自动在 PATH 与常见目录中寻找 `npm`，替代 Corepack 依赖描述。
- **批量更新检查**：使用 `npm outdated --json` 并按需查询 `dist-tags`，降低网络开销。
- **语义解析器**：提供 `split_npm_spec`，保障 `@scope` / `@tag` 的命令构造一致性。
- **环境类型智能分类**：`describe_npm_env()` 自动将 NPM 环境分为 5 种类型（Project / Home Modules / Roaming Modules / Standalone Modules / Global），NpmEnvCard 据此渲染不同颜色的类型徽章，方便在众多环境中快速定位。
- **独立 node_modules 自动纳管**：新增 `discover_user_node_modules()`，自动发现用户 home 目录与 Roaming npm 路径下的独立 `node_modules` 文件夹，首次启动即可纳管非标准位置的 NPM 环境。
- **通道自动检测引擎**：内置 `CHANNEL_PATTERNS` 正则引擎（nightly / preview / beta / canary / next / rc），结合 `detect_channel()` 自动从版本字符串中识别发布通道，PackageCard 同步渲染彩色通道徽章。

### 🧰 面板与交互一致性
- **管理员权限感知**：主窗口标题栏显示 `(Admin)`，提示当前权限。
- **公共逻辑上移**：环境查找、统计数更新等逻辑上移至 `BasePanel`。
- **三模式源策略**：`Sources` 支持 `Follow System` / `Official` / `Custom`，命令执行时动态注入。
- **系统源展示**：`Follow System` 模式下可探测并展示当前系统配置的源地址（pip/uv 与 npm）。
- **URL 联动**：源地址输入框会随模式切换联动展示系统值、官方值或自定义值。
- **三态勾选优化**：全选勾选框使用三态样式，“仅过时”开启时自动定位可更新路径。
- **设置面板大一统**：重构 `SettingsDialog`，通过统一的 `_build_env_tab` 工厂函数和元数据映射（Metadata Map），实现了 Python 坏境与 NPM 项目管理逻辑的高度统一。
- **动态样式重载**：引入 `StyleReloader` 实现 QSS 热更新，并在 Frozen (打包) 模式下通过 `sys.frozen` 自动静默屏蔽，支持 `OMNIPACK_LIVE_RELOAD` 环境变量手动控制。
- **HTML 用户指南**：状态栏新增 **Guide** 入口，通过系统默认浏览器打开内置的 `docs/UserGuide.html` 本地完整用户手册。
- **包卡片分批懒加载**：`PackageCard` 子依赖与 `BaseEnvCard` 顶层包均采用分批渲染（每批 8 个，间隔 5ms），避免大型环境下数百张卡片一次性创建导致 UI 假死。
- **环境卡片防抖搜索**：`filter_packages()` 内置 300ms 防抖计时器，快速连续输入时仅在停顿后触发深度递归搜索与自动展开，保证交互流畅不卡顿。
- **依赖树自动展开与选择同步**：选中包时自动递归展开所有闭合的祖先路径并同步同名分身勾选态；开启"仅过时"时自动展开所有通向过时包的祖先分支，确保过滤结果不遗漏隐藏在折叠层级中的过期项。

### ✨ UI 与交互优化 (UX & UI Refinements)
- **二段式全宽布局**：环境管理按钮重构为 Row 1 (Input) 与 Row 2 (Actions) 全宽布局，实现完美的视觉平衡与对称性。
- **状态栏玻璃感升级**：状态栏按钮引入蓝绿色玻璃感选中效 (`rgba(0, 255, 255, 0.4)`)，交互反馈更明确。
- **设置页容燥设计**：为 `SourceModeCard` 应用 `max-width` 约束并支持 WordWrap，彻底解决极长 URL 导致窗口布局崩溃的问题。
- **等宽一致性**：Python/Node.js 切换标签恢复 80px 固定宽度（已优化），确保界面切换时的稳定性。

- **选择轨迹记录**：`OMNIPACK_TRACE_SELECTION=1` 可生成选择轨迹日志。

### 🌀 Python 包搜索、缓存与设置重构
- **本地 PyPI 缓存驱动搜索**：`Add Package` 对话框现在只读取 `core/pypi_cache.py` 维护的本地索引，不再解析 PyPI HTML，保证搜索一致、无色块卡顿；缓存同时提供种子包列表以便“第一次就能搜到”核心包。缓存文件存储在 `pypi_search_cache.json`，并在后台异步刷新。
- **后台刷新与断点续传**：缓存刷新通过 `start_refresh_task` 运行在守护线程；刷新过程暴露在 Settings 的 Backend 页里，可实时查看百分比/日志，支持通过按钮取消、下载失败后自动续传。刷新配置遵循 Python Source 模式（System/Official/Custom），可以默认走清华、阿里等镜像。
- **Backend 标签页 + 代理梳理**：设置页新增 `Backend` 标签，集中展示 `uv` 引擎与 PyPI 缓存条目，`Sources` 仅保留源地址配置；同时 Proxy 页按钮更紧凑，连接测试面板默认收起细节，打开后查看对比。
- **npm Tag 交互对齐**：添加 npm 包对话框（第二页）用与 `npm_panel` 一致的 `NpmTagCard` 规则展示 dist-tags + 版本卡片，支持多列选择、当前/目标状态高亮，替代旧下拉框。
- **代理模块化重构**：将代理逻辑抽取为独立 `core/network_proxy.py` 模块，支持 PyPI / NPM / GitHub / winget 四通道独立代理开关、`HOST_TARGET_MAP` 按目标域名路由、自定义 `urlopen` opener 及子进程环境变量注入。
- **源配置模块化**：将 PyPI/NPM 官方源、常用镜像预设（清华/阿里/USTC/npmmirror/腾讯云）及系统源探测函数抽取为 `core/source_profiles.py`，Settings Sources 页支持一键快速填充预设。

### 🐧 跨平台与稳定性修复
- **WindowsApps 过滤**：过滤 `%LOCALAPPDATA%\\Microsoft\\WindowsApps` 下的 0 字节 Python stub。
- **系统 Python 发现增强**：扫描 PATH、常见目录与 `~/.pyenv/versions/*/bin/python*`，并过滤 `python3-config`。
- **XDG 合规增强**：Linux 配置目录优先 `XDG_CONFIG_HOME`，缺省回退 `~/.config/OmniPack`。
- **Windows 持久化策略**：Frozen 模式自动区分便携/安装；位于 `Program Files` 时默认使用 `%APPDATA%\\OmniPack`，可通过 `OMNIPACK_PORTABLE_CONFIG=1/0` 覆盖。
- **版本识别稳健性**：`python --version` 兼容 `stdout/stderr` 双通道输出。
- **批量导入优化**：批量粘贴改为一次性写盘与刷新，减少卡顿。
- **文件选择文案**：`Add From File` 提示兼容 `python.exe/python3/python`。

## [v3] - 构建架构升级与核心引擎加固 (Build & Engine Enhancement)

**本次更新聚焦于跨平台构建的稳健性、配置持久化的深度优化以及 Npm 管理引擎的高效协同。**

### 🏗️ 构建与部署：高性能原生分发
- **Nuitka 编译适配**：成功引入 Zig 编译器后端，完美解决了 Python 3.13 环境下传统 MinGW64 的兼容性难题，支持生成高性能原生 C++ 编译的可执行文件。
- **智能化路径追踪**：彻底重构了 `get_persistent_root` 逻辑。程序现在能精准识别 Standalone/Onefile 等各种打包模式，确保配置文件 `omnipack_config.json` 始终保存在 EXE 同级目录，而非遗落在系统临时文件夹中。
- **零负担 UAC 提权**：优化了打包后的管理员权限请求流程，跳过脚本层级的二次重启，避免了提权过程中环境变量丢失导致的路径识别失效。
- **自动化构建流**：`build_exe.py` 新增了“编译前自动清理”与“编译后自动重命名”机制，移除了冗余的 `.dist` 后缀，输出目录更加整洁。

### 📦 Npm 管理引擎：Corepack 深度集成与局部刷新
- **Corepack 自动感应**：新增对 Node.js 官方 Corepack 的自动检测与集成，能够智能寻找并调用系统环境中的包管理核心。
- **高性能局部更新**：重构了 `NpmManager` 与 `NpmPanel` 的通信机制，支持对单个应用进行独立的版本检查与 UI 刷新（Partial Update），在大规模应用清单下显著降低了网络请求与界面重绘开销。
- **健壮性增强**：优化了 Npm 应用的添加与更新逻辑，支持属性平滑覆盖，并增强了 Registry 标签获取的稳定性。

### ✨ UI 与持久化安全
- **容错保存机制**：`ConfigManager` 现在具备目录自动创建功能，并在配置保存失败时会自动向系统临时目录（`AppData\Local\Temp`）写入详细的错误日志。
- **视觉风格进化**：对 `dark.qss` 进行了大规模样式微调，优化了 `EnvCard`、`ConsolePanel` 等核心组件的视觉层级与交互反馈。
- **控制台体验优化**：改进了控制台面板的日志流显示，提升了长任务执行时的响应速度。

---

## [v2] - 深度依赖拓扑重构 (Major Update)

**这是 OmniPack 的一次里程碑式更新，Pip 管理面板由平铺列表全面进化为智能拓扑依赖树。**

### 🧠 核心：拓扑依赖解析引擎
- **秒级拓扑扫描**：引入基于 `importlib.metadata` 的子进程扫描技术，1秒内即可完成百级规模包的 `{依赖库, 逆向引用}` 完整建模。
- **Top-level 降噪视图**：默认仅显示用户最关心的第一级入口包（不再受几百个底层依赖的干扰），极大提升了大型环境管理的可读性。
- **约束自动合并**：智能合并对同一依赖包的多重版本约束（如 `vtk >=9.2, <9.7`），不再产生重复冗余卡片。

### 🛡️ 稳健性：幽灵依赖 (Ghost Dependencies) 检测
- **隐形风险识别**：实时检测环境中被需要但“神秘失踪”的包，以红色虚线样式高亮标记。
- **一键补完计划**：侧边集成 `📥` 快捷安装入口，支持针对缺失依赖的垂直修复订阅。

### ✨ 交互：智慧同步与深度对焦
- **跨层级同步勾选**：勾选某一层级的包，全树所有同名分身即刻同步选中状态，逻辑统一。
- **路径逐级寻踪**：选中某个包时，若其存在于已关闭的支线中，系统将自动递归计算祖先路径并强制展开，确保搜索结果“无处遁形”。
- **环境聚焦搜索 (Strategy 3)**：引入带防抖的深度搜索逻辑。只有你“点开”的环境才会消耗 CPU 进行深度递归搜索及自动展开，折叠的环境保持静默，完美平衡了超大规模环境下的搜索性能。

---

## [v1] - 首个正式版发布

**欢迎使用 OmniPack 开发者全能包管理器首个正式版本！**
OmniPack 以环境隔离和极致纯净作为主旨，提供优于传统应用商店的系统服务支持。

### 🚀 架构与核心特性
- **双端整合外壳**：统一了 Pip / uv （局部多环境）与 NPM（系统全局模块）的管理，支持底层线程并发读取，不会造成界面假死卡顿。
- **配置化驱动管理**：不同于“读出本机几百款底层支撑包”，所有待管 Python 或 NPM 目录均遵循主动加入配置文件清单的方式，保持您的控制台绝对纯净。
- **动态状态同步机制**：切换开发环境管理器时（Pip <=> Npm）能完美共享控制面板拖拽的 Splitter 分割位与比例。
- **状态持久化与状态反馈**：能记住关闭前所使用的页面并且恢复尺寸状态；利用窗体最下边缘提供了非常详尽的 "Installed/Updates" 数字监控总览组件。

### 🐍 Python (Pip / uv) 管理模块
- 实现了同时关联、懒加载 N 个外部 Python `venv`、`conda` 等隔离环境的检测能力。
- 本地基于超高速的 `astral-sh/uv` 引擎提供对 Pip 工具的大幅提速，可以快速勾选多包并且自动使用 `uv` 并发安装更新。
- 提供了自动拆分与按搜索文字快速过滤单个大型隔离环境中冗长包的能力。

### 📦 Node.js (Npm) 管理模块
- 支持对于单个应用的精细配置：可以修改显示给用户侧的简称(Display Name)、自定义功能描述信息(Description)。
- **智能通道（Channels）扫描系统**：即便尚未安装某一全局模块，也能自动识别并罗列其线上的诸如 `beta`, `rc`, `next`, `nightly` 等 dist-tags 先行版通道，并支持动态在不同分支进行无缝更新。
- 全新的智能装配编辑对话框：只要把长长的诸如 `npm i -g @cli/tools@rc` 的正则字符复制进编辑面板，对话框就能自己萃取应用特征并展示对应的可选通道按键进行高亮覆盖。

### 🛠 稳定性与现代环境兼容性
- **现代 Python 全兼容**：针对 Python 3.13/3.14+ 及其高版本 PySide6 (6.10.2+) 进行了深度加固，解决了在高版本 Python 内存模型下可能出现的 `SystemError (NULL)` 启动崩溃。
- **健壮性 UI 架构**：重构了所有布局（Layout）初始化逻辑，采用解耦绑定方式，确保在多线程及动态主题切换下的界面鲁棒性。
- **全局异常捕捉器**：引入了基于 `ctypes` 的 Windows 消息框拦截机制，即使程序意外崩溃也能提供清晰的 Traceback 弹窗，拒绝“静默闪退”。
- **规范化事件处理**：修正了 PySide6 事件枚举（如 `QEvent.Type.Polish`）的引用路径，完全符合现代 Qt 6 标准。
- **UI 模块化拆分**：实现了“薄外壳”架构，将 `OmniPackWindow` 类从入口文件剥离至 `ui/main_window.py`，保持了项目结构的长期可维护性。
