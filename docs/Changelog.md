# Changelog - OmniPack

## 🇺🇸 [v15] - Cross-Platform Runtime Installers (macOS/Linux), WinGet Automated Setup (Windows), Runtime Setup Guide UI, Virtual Environment File-Lock Guard & Resilient Network API

<details>
<summary><b>🇨🇳 [v15] - 跨平台运行时一键安装（macOS/Linux）、WinGet 系统级全自动安装（Windows）、运行环境引导界面、虚拟环境升级文件锁防御与高可用 API (中文说明)</b></summary>

<br>

本次更新大幅扩展了 OmniPack 的运行环境自愈与安装能力，正式引入对 macOS 和 Linux 平台的运行时一键下载与自动配置支持，并在 Windows 平台上实现了缺失 WinGet 时的后台全自动下载及安装。此外，在 UI 层面引入了常驻且直观的“运行环境安装引导界面”（RuntimeSetupWidget），同时增强了 Pip 虚拟环境升级时的进程文件锁静默冲突保护，避免因 IDE 占用导致环境受损，并进一步优化了网络 API 容灾重试逻辑。

### 🚀 跨平台运行环境一键自愈与安装引导 (Auto-Setup & Guide UI)

为了给缺失运行环境的用户提供无痛的起步体验，本次更新将底层的一键自愈链路与上层的智能引导界面进行了深度整合：

- **智能缺失引导界面**：当在 Pip 面板、Npm 面板或 WinGet 面板中未检测到任何可用环境时，UI 底部会自动展现精美的“运行环境安装引导”卡片（RuntimeSetupWidget）。支持强制调试标志（`force_show_setup: true`），优化了窗口拉伸时的固定高度及按钮字符渲染，并集成跳转至官网下载历史版本的 "Other Version" 链接。
- **Windows 系统级一键修复 WinGet**：若当前系统缺失或损坏了 WinGet 客户端，OmniPack 将通过 PowerShell 自动从 GitHub 抓取最新官方 `.msixbundle`，并后台静默部署其必须的 `Microsoft.VCLibs` 与 `Microsoft.UI.Xaml` 依赖组件，实现 WinGet 从无到有的全自动安装（支持代理与进度回传）。
- **macOS/Linux 运行时一键安装**：
  - **Linux 自动极速部署**：缺失 Python 时自动通过极速 Python 工具 `uv` 进行一键下载安装；缺失 Node.js 时，则会自动下载对应架构（x64/arm64）的官方二进制包，全自动解压并软链接（symlink）至用户本地 `~/.local/bin`。
  - **macOS 官方包静默流式安装**：支持一键下载官方 Python/Node.js 的 `.pkg` 安装包，并调用系统 `open -W` 指令拉起系统 GUI 安装器并同步等待其完成。

### 🔒 虚拟环境升级文件锁冲突防御 (Venv File-Lock Guard)

针对 Python 虚拟环境升级（`python -m venv --upgrade`）时易被外部进程锁定导致损坏的痛点，引入了文件锁静默拦截与诊断机制：

- **占用锁精准诊断**：一旦检测到由于 PyCharm、VSCode 或 OmniPack 自身等进程锁定了 `python.exe` 文件导致复制失败，程序将静默拦截原始命令行的乱码输出，转而向用户抛出极其清晰易懂的错误引导，提醒其关闭所有可能占用该环境的程序后再试，从根本上防止虚拟环境损坏。

### ⚙️ 稳定性提升与底层解析优化 (Stability & Parsing Optimizations)

对网络 API 交互、配置文件解析以及测试套件生命周期进行了全方位的健壮性加固：

- **高可用 API 容灾重试**：重构了 `_fetch_runtime_index` 获取机制，增加了最多 3 次的网络连接重试及退避延迟，并在多线程并发访问时引入 0.3 秒睡眠保护，完美解决了因 Cloudflare 防御导致的 SSL 握手超时（<urlopen error _ssl.c:1063...>）和高达 50% 的 API 获取失败率。
- **解析与配置容错**：优化了 `pyvenv.cfg` 的读取兼容性，对缺失 `Python` 关键字的前缀版本行进行自动修正，确保各种非标准虚拟环境的版本号均能被精准读取；同时为 `msvc_path.cfg` 增加了详细的说明注释，明确了 Nuitka 编译器的查找和回退逻辑。
- **测试框架进程级崩溃修复**：修复了在自动化测试（`pytest`）环境下，由于底层拉取版本的异步 `QThread` 仍处于运行状态而导致 C++ Fatal Error 强制掐断测试进程的生命周期 Bug，自动化测试恢复 100% 通过率。

</details>

This release expands OmniPack's environment self-healing capabilities by introducing official runtime installers for macOS and Linux, as well as a fully automated, proxy-supported background install process for WinGet on Windows. A new dedicated setup guide UI (RuntimeSetupWidget) automatically assists users in bootstrapping missing runtimes. Furthermore, this update introduces robust file-lock guards for virtual environment upgrades to prevent IDE-locked process failures, optimizes pyvenv.cfg reading tolerances, and integrates exponential backoff retries for network runtime API indexes.

### 🚀 Cross-Platform Runtime Auto-Setup & Guide UI
- **Contextual Setup Prompts**: Displays a beautifully styled setup card (`RuntimeSetupWidget`) at the bottom of the scroll view when Pip, Npm, or WinGet panels have zero loaded environments, allowing users to trigger installation pipelines instantly. Fixed vertical stretching bugs by applying Fixed size policies, corrected missing `&` ampersand bugs in buttons, and added a custom `force_show_setup` debugging flag.
- **External Legacy Version Links**: Added a convenient "Other Version" hyperlink next to the version selector, allowing users to quickly access the official Python/Node.js download pages for specific legacy versions.
- **Zero-Dependency WinGet Deployment**: If WinGet is missing or broken on Windows, OmniPack runs a proxy-aware PowerShell worker to fetch the latest `.msixbundle` directly from the official GitHub repository and install it alongside necessary Microsoft Appx dependencies (VCLibs and UI.Xaml).
- **One-Click macOS & Linux Installers**:
  - **Linux Automated Deployments**: If a Python runtime is missing, the application installs it using `uv`; for missing Node.js runtimes, it pulls the official tar.xz binary pack (tailored for x64/arm64) and symlinks the binary links (`node`, `npm`, `npx`) to the user's local path.
  - **macOS Official Installer Execution**: Automatically fetches the official `.pkg` packages for macOS Darwin and executes them using the interactive `open -W` system installer pipeline, pausing runtime updates until completion.

### 🔒 Virtual Environment Upgrade File-Lock Guard
- **Silent File-Lock Diagnostics**: Detects if virtual environment upgrades fail due to locked executable files (`python.exe` occupied by IDEs, running scripts, or OmniPack itself). Intercepts console errors and warns the user with clear instructions, preventing environment corruption.

### ⚙️ Stability, API Resilience & Parsing Optimizations
- **Resilient Retry Pipeline**: Rewrote `_fetch_runtime_index` to protect network indexing queries with a 3-pass retry fallback and connection sleep offsets. This completely mitigates SSL handshake timeouts caused by aggressive CDN rate-limiting, resolving a ~50% failure rate anomaly.
- **Robust Config Parsing**: Automatically normalizes and prepends missing "Python" keywords when parsing version lines inside `pyvenv.cfg` configs, ensuring correct local scans. Also documented the compiler discovery order and Zig backup routes directly within `msvc_path.cfg`.
- **Pytest QThread Fatal Error Fix**: Isolated and bypassed asynchronous `QThread` instantiations during automated `pytest` lifecycles to prevent premature garbage collection from triggering C++ fatal aborts, restoring the test suite to a 100% green passing state.

---

## 🇺🇸 [v14] - Environment Editing & Renaming, Winget Self-Upgrade, Winget Diagnostics & Enhancements, Copyable Dialogs & Package Details

<details>
<summary><b>🇨🇳 [v14] - 环境编辑与重命名、Winget自身升级、Winget细节增强与去重优化、可复制对话框文本与包详情 (中文说明)</b></summary>

<br>

本次更新引入了对虚拟环境的直接编辑与重命名支持，提供了 Winget 包管理器自身（App Installer）的一键检测与升级能力，并极大提升了界面文本的可交互性，支持全局对话框文本复制和一键复制包详细信息。同时，对 Winget 扫描结果进行了架构识别与去重优化，并对底层 UI 工具函数进行了清理和重构。

### ✏️ 环境编辑与重命名

- **右键直接管理**：现在可以在 Pip 和 Npm 面板的环境卡片上，右键菜单中直接选择 **“✏️ Rename Environment”** 来修改环境展示名称，或选择 **“⚙️ Edit Settings”** 来编辑该环境的路径等详细设置。
- **智能高亮跳转**：点击“编辑设置”后，程序会自动打开统一设置对话框，并以极高精度自动定位高亮到该环境，提供无缝的使用体验。

### 🚀 Winget 包管理器自身升级支持

- **版本实时展示**：在 Winget 机器和用户卡片上，现在会显示 Winget 当前的具体版本号（如 `Winget v1.9.25200`）。
- **一键升级自身**：若检测到 Winget 有可用更新，卡片头部会显示闪烁的 **`Wg`** 按钮并显示升级路径（如 `v1.9.25200 -> v1.10.x`）。用户点击后会弹出确认框，确认后通过内置终端执行 `winget upgrade --id Microsoft.AppInstaller` 升级。

### 📋 可复制对话框与包详情一键复制

- **全局文本可复制**：安装了全局事件过滤器，使主程序中弹出的所有 `QMessageBox` 和 `QDialog` 的标签文本均支持鼠标选中和复制（Ctrl+C），便于用户在遇到报错时复制异常信息进行排查。
- **包配置一键复制**：在包的“配置包”对话框中，新增了 **“Copy Details”**（复制详情）按钮。一键即可将该包的名称、ID、安装源、已安装版本、可用版本以及安装路径（如有）拷贝至剪贴板。

### 🔍 Winget 细节增强与去重优化

- **安装位置标记**：在包卡片和配置对话框中，对通过传统注册表安装的包增加 `[Win32]` 标记，对通过现代包管理器安装的包增加 `[MSIX]` 标记。
- **架构信息自动追加**：智能从包 ID 中使用正则抓取 `x64`、`x86`、`arm64` 等架构信息，自动追加在 UI 展示 of 包名后（如 `Python 3.10 (x64)`），避免同名多架构包造成视觉混淆。
- **扫描去重机制**：对具有相同 ID、源和版本的包进行去重过滤，避免重复显示。

### ⚙️ NPM 与其他细节优化

- **NPM 全局路径展示**：在设置面板中，不再单一显示 "global" 字样，而是会自动扫描并缓存呈现真实的 NPM 全局安装路径（如 System Global 对应的系统实际 node_modules 根目录）。
- **代码重构与清理**：抽象并复用了 `update_widget_style_property` 和 `clear_layout` 辅助函数，避免冗余样式刷新的 boilerplate 代码。彻底移除了未使用的临时测试脚本 `test_winpty.py`。

</details>

This release introduces direct support for editing and renaming environments from context menus, enables one-click detection and upgrading of the Winget package manager itself (App Installer), and significantly improves UI text interactivity with copyable dialog text and package detail export buttons. Furthermore, it refactors core UI utilities and enhances Winget operations with automatic architecture appending, installation source tagging, and scan deduplication.

### ✏️ Environment Renaming & Settings Editing
- **ContextMenu Integration**: Pip and Npm environment card headers now support right-click context options: **"✏️ Rename Environment"** to quickly modify the alias, and **"⚙️ Edit Settings"** to modify the environment parameters.
- **Automatic Highlighting**: Editing an environment automatically launches the Settings Dialog and focuses directly on the selected environment row for seamless adjustments.

### 🚀 Winget Package Manager Self-Upgrade
- **Version Display**: Automatically queries and displays the version of the `winget` executable directly on the Machine and User environment cards.
- **One-Click Upgrade**: Detects if `Microsoft.AppInstaller` has an update available, displaying the upgrade path (e.g. `Winget v1.9.25200 -> v1.10.x`) and showing a dedicated **`Wg`** update button. Clicking it prompts for confirmation and triggers the CLI upgrade pipeline.

### 📋 Copyable Dialog Labels & Package Details Export
- **Selectable Dialog Labels**: Registered a global event filter to make text labels inside all `QMessageBox` and `QDialog` selectable and copyable, allowing users to easily capture error tracebacks.
- **Copy Package Details**: Added a **"Copy Details"** button in package configuration dialogs, enabling users to copy all metadata (Name, ID, Source, Versions, and Install Location) to the clipboard.

### 🔍 Winget Diagnostics & Enhancements
- **Type Badge Tagging**: Displays `[Win32]` badges for classic desktop registry installations and `[MSIX]` badges for modern app package formats in details and lists.
- **Architecture Identification**: Automatically extracts architecture descriptors (x64, x86, arm64, arm) from package IDs and appends them to package names (e.g., `Python 3.10 (x64)`) to avoid name collisions.
- **Deduplication**: Filters out duplicate items carrying identical IDs, sources, and versions.

### ⚙️ NPM & Miscellaneous Optimizations
- **NPM Global Path Resolution**: Replaced the generic "global" keyword in Settings with a dynamically queried and cached physical prefix path (or "System Global") for NPM global installations.
- **Refactoring & Cleanups**: Unified UI updates with modular `update_widget_style_property` and `clear_layout` functions. Deleted the obsolete `test_winpty.py` script.

---

## 🇺🇸 [v13] - User site-packages Integration, Drag-and-Drop Reordering, Batch Import & Proxy Sync

<details>
<summary><b>🇨🇳 [v13] - 用户目录包融合、拖拽排序、批量导入与代理同步 (中文说明)</b></summary>

<br>

本次更新支持了对系统 Python 用户站点包（User site-packages）的自动探测与深度融合管理。完美解决了第三方包安装在用户漫游目录下导致主程序遗漏读取的问题，并提供鼠标悬停物理路径提示，保障了在任何权限场景下的平滑运行。同时引入了主界面环境卡片拖拽重排、右键删除、快捷批量导入，以及代理配置同源同步等提升用户体验的重大改进。

### 📦 用户目录包（User-Site）深度融合与并列展示

- **双路径并发扫描**：全面打破系统 site-packages 和 用户 user-site 之间的壁垒。程序在扫描系统环境包时，会自动探测其 `site.getusersitepackages()` 物理路径，并执行并发读取与合并。
- **支持并列展示与冗余可见**：彻底去除了对包名的强制去重合并字典。如果系统全局和用户目录下同时安装了同名包，OmniPack 将并列完整展示，让用户轻松发现冗余并自主决策。
- **特异性依赖树组装**：重构了 `merge_dependency_info` 依赖树合并机制。现在，即便存在同名冗余包，所有的实例实体均能正确绑定并展现出各自完备的依赖拓扑图，不存在任何依赖项丢失。
- **树状就近定位路由**：当展开父卡片懒加载子依赖时，算法会根据父节点的安装位置（系统/用户）执行就近匹配；如果只有单方安装，则安全跨目录跨路由关联。

### 🔄 主界面拖拽重排与右键管理

- **直观的环境卡片拖拽**：在 Pip 和 Npm 环境列表中，用户可以直接使用鼠标拖动环境卡片进行排序。在拖动过程中提供了亮蓝色的放置指示线，调整后的顺序会自动同步保存至配置文件（`omnipack_config.json`）。
- **右键上下文菜单删除**：在环境卡片 Header 上点击右键可快速唤出上下文菜单，一键删除/移除该环境，无需再进入设置对话框进行繁琐操作。

### ➕ 列表底部快捷添加环境与批量导入

- **常驻快捷按钮**：在 Pip 和 Npm 面板环境列表底部新增了“➕ Add Environment”常驻按钮，使添加环境更加便捷。
- **多通道添加与批量导入 (Batch Paste)**：支持选择“项目/虚拟环境文件夹”、“python.exe/package.json 配置文件”、或“手动输入路径”。此外，新增了**“Batch Paste... (批量粘贴)”**功能，允许用户直接从 Windows 资源管理器或 Everything 中复制多行路径一键导入，极大提升了多项目导入的效率。

### 🎨 包名高亮染色与悬停物理路径

- **亮黄字体染色**：去除了原有的 `[User]` 徽章，改用精美的亮黄色（`#ffb703`）直接对用户目录包的包名进行高亮染色，保持了极简清爽的现代暗黑 UI 美学。
- **悬停 Tooltip 物理路径**：无论在何层级、何深度的依赖卡片，只要将鼠标悬停在包名上，Tooltip 就会瞬间呈现出包在硬盘上的具体物理安装路径（如系统包显示为 `C:\Program Files\...`，用户包显示为 `C:\Users\Leo\...`），让物理布局一目了然。

### 🖥️ 系统/用户环境变量卡片 Tooltip 悬停显示

- **移除 ` [PATH]` 后缀**：清理了 Python 与 Node.js 环境卡片标题后原本追加的 ` [PATH]` 后缀。
- **智能系统/用户变量识别**：通过 Windows 注册表精确判断 Python 与 npm 路径归属：
  - 如果在系统环境变量中找到（无论用户变量中是否也存在），鼠标悬停在卡片名称上时会通过 Tooltip 提示 `"In the System Variables"`。
  - 如果仅在用户环境变量中找到，Tooltip 会提示 `"In the User Variables"`。

### ⚙️ 智能 PTY 命令分流与权限安全兜底 & 代理配置优化

- **带位置标签的 Target 传输**：UI 层与 PTY 交互时，包卡片将向操作队列注入如 `numpy:user` 或 `numpy:system` 等位置标签，命令行构建器根据标签智能生成卸载/升级命令（分流为 `--target <user-site-path>` 或 `--system --python ...`）。
- **无特权安装 Fallback 兜底**：在系统 Python 下安装或升级新包时，一旦探测到主程序运行在普通用户特权下（无管理员特权），会自动降级并使用 `--target <user-site-path>` 将包安装到用户目录中，彻底规避因写保护引起的 `Permission Denied` 错误，实现零报错流畅体验。
- **代理配置同源同步 (Same for HTTP and HTTPS)**：在 Settings -> Proxy 设置中，增加了 “Same for HTTP and HTTPS” 复选框。勾选后，HTTPS 代理配置将自动同步并锁定为 HTTP 代理配置的值，避免了重复输入的冗余操作。

</details>

This release integrates full support for Python user site-packages (`--user` installs) into OmniPack's ecosystem. It resolves the problem where packages installed in the user's roaming directory were hidden from the UI, introducing a clean, badge-free color-highlighting scheme, hover-based physical path tooltips, and non-deduped parallel dependency chains for perfect environment visualization and smart permissions fallback. Furthermore, it introduces major user experience enhancements, including direct drag-and-drop reordering, right-click environment deletion, multi-channel batch path paste import, and unified HTTP/HTTPS proxy synchronization.

### 📦 Deep User-Site Integration & Dual-Path Parallel Scan
- **Bilingual Parallel Detection**: OmniPack now automatically queries `site.getusersitepackages()` for system Python environments and launches concurrent listings of global site-packages and user site-packages.
- **Deduplication Removal for Redundant Visibility**: Eliminated the dictionary-based name deduplication. When a package is installed in both system and user directories (possibly at different versions), OmniPack lists them side-by-side, allowing users to spot redundancies and choose which one to manage.
- **Instance-Level Dependency Merger**: Refactored `merge_dependency_info` to enrich all concurrent instances of a package with tree dependencies, avoiding the issue where one of the duplicates appeared as a leaf or isolated node.
- **Location-Aware Child Resolution**: When lazy-loading dependencies, child cards prioritize matching the parent node's location (system vs. user). If a mismatch occurs, the tree safely links across paths and inherits the correct style and path.

### 🔄 In-App Drag-and-Drop Reordering & Quick Management
- **Visual Drag-and-Drop**: Users can now drag environment cards within Pip and Npm lists to reorder them directly. A bright-blue position indicator line assists during sorting, and the updated order is dynamically written to `omnipack_config.json`.
- **Right-Click Context Menu**: Right-clicking the header of any environment card now opens a context menu allowing users to instantly delete/remove the environment, eliminating the need to use the settings dialog.

### ➕ Add Environment Shortcuts & Batch Paste
- **On-Panel Add Button**: A permanent "➕ Add Environment" button is integrated at the bottom of the environment lists in Pip and Npm panels for easier management.
- **Multi-Channel Import with Batch Paste**: Added options to add environments via folder picker, file browser (e.g., python.exe or package.json), or raw manual path input. Additionally, a new **"Batch Paste..."** option is introduced, permitting users to paste multiple paths (e.g. copied from File Explorer or Everything) to import them in a single batch.

### 🎨 Hover-to-Path Tooltips & Clean Color Highlight
- **Bespoke Yellow Highlighting**: Replaced the `[User]` badge with an elegant bright-yellow (`#ffb703`) styling directly on the package name label for user-site installations, keeping the modern dark-themed aesthetic clean.
- **Physical Path Hover Tooltips**: Hovering over any package name in the list displays its exact installation path (e.g., `C:\Program Files\...` for system packages and `C:\Users\<User>\...` for user packages) at any level of the dependency tree.

### 🖥️ Smart System/User PATH Environment Variable Tooltips
- **Removed ` [PATH]` Suffixes**: Removed the legacy ` [PATH]` string appended to the title of Python and Node.js environment cards for a cleaner dark UI.
- **Dynamic Registry/PATH Tooltips**: Uses dynamic Windows Registry validation to intelligently identify if a Python or npm executable is globally available:
  - If located in the System Environment Variables (even if duplicated in the User space), the card's title hover tooltip will display `"In the System Variables"`.
  - If isolated only to the User Environment Variables, the tooltip will display `"In the User Variables"`.

### ⚙️ Location-Aware PTY Commands & Permissions Fallback & Proxy Sync
- **Target Location Tagging**: Package rows now generate target actions containing position markers (like `numpy:user` vs. `numpy:system`). The command builder parses these to automatically select `--target <user-site-path>` or `--system --python <path>`.
- **Non-Admin Installation Fallback**: When installing or updating packages on a system Python without administrator privileges, OmniPack automatically routes the install command to the user site-packages directory via `--target`, resolving `Permission Denied` write errors on protected directories.
- **Unified Proxy Option**: Added a "Same for HTTP and HTTPS" checkbox in Settings -> Proxy. When checked, the HTTPS proxy input is disabled and locked to automatically synchronize with the HTTP proxy value, simplifying the proxy configuration.

---

## 🇺🇸 [v12] - Intelligent Constraint-Safe Updates, FS Watcher & Marker Redesign

<details>
<summary><b>🇨🇳 [v12] - 智能依赖约束更新、文件系统联动同步与终端状态检测重构 (中文说明)</b></summary>

<br>

本次更新显著增强了包管理的智能化程度，引入了自动探测安全中间版本的能力，并实现了 UI 与物理硬盘状态的实时同步。同时，底层终端状态追踪机制进行了重构，极大地提升了在高压力输出场景下的任务可靠性。

### 🛡️ 智能依赖约束更新

- **安全中间版本推荐**：引入 `safe_update_version` 逻辑。当包的最新版本因依赖关系被其他包锁定（Breaks Constraints）时，OmniPack 现在会自动探测版本历史，并推荐一个在约束范围内的“最高安全版本”。
- **可视化约束引导**：
    - 针对受限包引入全新的**蓝色 UI 主题** (`PkgVersionUpdateConstrained`)。
    - 悬停提示 大幅增强：不仅显示“可能导致冲突”，还会详细列出是哪些上游包施加了什么范围的约束（例如：`Django 要求 djangorestframework<3.15`），让用户对版本锁定原因一目了然。
    - “一键全选过时包”逻辑优化：会自动包含这些受限但可安全升级到中间版本的包，而彻底无法无损升级的包仍保持手动确认模式。
- **预发布版本智能过滤**：引入 `is_prerelease_version` 逻辑，在探测可用包版本及安全中间版本时自动排除 alpha、beta、rc 等非稳定的预发布版本，防止用户在自动升级中误入预览版分支。

### 🔄 实时文件系统联动

- **环境自愈同步**：在 `PipPanel` 和 `NpmPanel` 中集成了 `QFileSystemWatcher`。
- **命令行脱机联动**：当用户直接在系统终端或内置终端中运行 `pip install` 或 `npm install` 等命令导致本地文件变化时，OmniPack 会在静默期（Debounce）后自动触发环境刷新，确保 UI 状态始终与物理硬盘保持实时一致，无需手动点击刷新按钮。

### 🧩 终端状态检测重构

- **基于物理文件的 Marker 机制**：彻底重构了 PTY 终端任务结束的检测逻辑。由原来的“拦截输出流并正则匹配 UUID”改为“写入临时标记文件 (`.done`)”。
- **极致稳定性**：解决了在极高并发输出、ANSI 颜色代码干扰或终端自动换行时，正则匹配 UUID 标记位可能失效导致界面无限加载的问题。新机制完全免疫任何终端字符流干扰。

### ⚙️ 底层健壮性与代理优化

- **集成终端代理自动联动**：集成 PTY 终端在启动时会自动读取并继承全局代理配置。一旦软件的代理启用，PTY 进程将同步注入 `HTTP_PROXY`、`HTTPS_PROXY` 以及 NPM 专用的 `NPM_CONFIG_PROXY` 与忽略证书校验环境变量（如 `NODE_TLS_REJECT_UNAUTHORIZED=0`），从而保证内置命令行操作和主程序具备一致的网络穿透能力。
- **多级版本探测 API 容灾回退**：在 Pip 可用版本扫描中引入三级 Fallback 保护。当默认的 `pip index` 命令由于不支持或源限制无法查询时，会自动请求 PyPI 官方 JSON 接口；对于私有源则尝试拉取其 Simple API 的 JSON 响应，最终回退到直接请求 HTML 并以正则从链接名中解析提取版本号。这彻底解决了弱网、局域网或特定私有镜像源下无法探测更新的问题。
- **安装规范（Spec）智能清洗**：
  - 新增 `extract_npm_package_name` 智能包名提取算法，能自动在各种复杂的 npm 安装 spec（如本地路径、Workspace 符号链接、Git URL、别名包等）中剥离噪音并提取出最终注册到 `node_modules` 里的真实包名。
  - 在 Pip 局部扫描中，引入 `extract_pip_requirement_name` 对传入的包名先过滤约束条件等参数再扫描，双端齐下确保局部更新和扫描解析时不发生错位。
- **控制台 ANSI OSC 控制流净化**：升级了内置的流式 ANSI 剥离器，增加了对 OSC 控制序列（如终端改名、标题重设等 `\x1b]...` 指令）的过滤支持，有效规避了高彩 PTY 流在向只读日志投射时的字符杂音与乱码。

### 🏗️ 性能与细节改进

- **渲染精度修复**：修复了 `RealTerminalPanel` 在渲染 `pyte` 缓冲区时过度裁剪行尾空格导致交互式光标定位偏移的 Bug。
- **并发性能优化**：Pip 环境在计算依赖约束时引入了版本缓存池，大幅减少了重复查询 PyPI 元数据带来的网络开销。

</details>

This release significantly enhances package management intelligence by introducing constraint-safe intermediate version recommendations and real-time synchronization with physical disk states. Additionally, the underlying PTY terminal tracking mechanism has been refactored to achieve ultimate stability under heavy CLI output.

### 🛡️ Intelligent Constraint-Safe Updates
- **Safe Update Recommendations**: Introduced `safe_update_version` logic. When a package's latest version is locked by other packages (Breaks Constraints), OmniPack now automatically probes its version history to recommend the highest available version within the constraint range.
- **Visual Constraint Guidance**:
    - Applied a brand-new **blue UI theme** (`PkgVersionUpdateConstrained`) for constrained packages.
    - Greatly enhanced ToolTips: Instead of just displaying "may break version constraints," they now detail the exact upstream packages and constraint ranges (e.g., `Django requires djangorestframework<3.15`) for clear version locking diagnostics.
    - Optimized "Select Outdated" logic: Now automatically includes constrained packages that can be safely upgraded to an intermediate version, while packages that cannot be safely upgraded still require manual confirmation.
- **Prerelease Version Filtering**: Introduced `is_prerelease_version` logic to automatically exclude unstable pre-release versions (like alpha, beta, rc, pre, dev) during package version detection and safe intermediate recommendations, avoiding unintentional upgrades to unstable builds.

### 🔄 Real-time File System Watcher
- **Auto-Refresh on External Changes**: Integrated `QFileSystemWatcher` in `PipPanel` and `NpmPanel`.
- **Command-line Offline Synchronization**: When users run commands like `pip install` or `npm install` directly in an external system terminal or the built-in terminal, OmniPack automatically triggers environment scanning after a quiet debounce period, keeping the UI state consistent with the physical disk without manual refreshes.

### 🧩 Terminal Marker Redesign
- **File-based Marker Mechanism**: Completely refactored PTY terminal command completion detection. Shifted from "intercepting stdout and regex-matching UUID" to "writing a temporary marker file (`.done`)".
- **Ultimate Stability**: Resolved the issue where the UUID marker regex matching failed due to high-concurrency outputs, ANSI color code interference, or terminal line wrapping, which previously led to infinite UI loading. The new mechanism is entirely immune to any terminal stream text noise.

### ⚙️ Core Robustness & Proxy Enhancements
- **Terminal Proxy Auto-Sync**: The integrated PTY terminal now inherits global proxy configurations upon startup. When active, it automatically injects `HTTP_PROXY`, `HTTPS_PROXY`, npm-specific `NPM_CONFIG_PROXY`, and SSL certificate bypass variables (`NODE_TLS_REJECT_UNAUTHORIZED=0`), ensuring the terminal CLI commands share the same network penetration capabilities as the main UI.
- **Fallback Version Discovery**: Implemented a 3-level fallback version query pipeline for Pip. If the default `pip index` fails or is unsupported, OmniPack queries the official PyPI JSON API, falls back to simple repository API JSON endpoints, and ultimately parses simple HTML directories with regex to extract version numbers from wheel/sdist packages, safeguarding functionality on restricted, offline, or private index mirrors.
- **Smart Spec Extraction**:
  - Added the `extract_npm_package_name` algorithm to parse complex npm installation specs (local paths, workspaces, Git URLs, alias packages with `@npm:`) and isolate the clean package name registered in `node_modules`.
  - Added `extract_pip_requirement_name` in Pip partial scanning to strip constraint parameters before queries, ensuring alignment for partial sync operations.
- **OSC Sequence Filtering**: Upgraded the streaming ANSI stripper to filter out Operating System Command (OSC) sequences (such as terminal title changes like `\x1b]0;...`), keeping the read-only simulated console clean and free of control character noise.

### 🏗️ Performance & UI Refinement
- **Rendering Precision Fix**: Fixed a bug where `RealTerminalPanel` over-clipped trailing spaces when rendering `pyte` buffers, which previously led to interactive cursor offsets.
- **Concurrent Optimization**: Integrated a version caching pool in Pip dependency constraint resolution, dramatically reducing repetitive PyPI registry metadata queries.

---

## 🇺🇸 [v11] - Security Upgrades, Atomic Config & Bulletproof WinGet Parser

<details>
<summary><b>🇨🇳 [v11] - 安全防御升级、配置原子化写入与 WinGet 解析防弹重构 (中文说明)</b></summary>

<br>

本次更新不仅解决了 WinGet 复杂输出场景下的表格解析崩溃问题，还大幅增强了底层的运行稳定性和网络安全性。涵盖配置文件的断电保护、下载件的安全签名校验以及 HTTP 代理的忽略证书特性。

### 🛡️ 网络安全与下载防御

- **下载校验与数字签名防御**：
  - 在 `core/runtime_update.py` 中引入了 Windows 平台原生的 `Get-AuthenticodeSignature` 强校验机制。自动验证下载的解释器/运行时安装包的 SHA256 指纹。
  - 实施严格的**发行商白名单防御**：强制要求签名归属于 “Python Software Foundation”、“Node.js Foundation” 或 “OpenJS Foundation”，一旦签名无效或发行商不匹配，将立即销毁文件并阻断安装，杜绝了由于网络劫持造成的投毒攻击。
- **代理证书忽略特性**：
  - 在 `core/network_proxy.py` 中新增了 `insecure`（忽略证书校验）设置项支持。开启后，不仅 urllib 请求会降级使用非受信任上下文，向下游 NPM 子进程注入环境变量时也会同步附加 `NPM_CONFIG_STRICT_SSL=false` 及 `NODE_TLS_REJECT_UNAUTHORIZED=0`，大幅提升了对企业内网或中间人抓包代理（如 Fiddler/Charles）环境的连通兼容性。

### ⚙️ 核心稳定性改进

- **原子化配置写盘与损坏自愈**：
  - 彻底重构了 `core/config.py` 中的存盘策略，采用 `tmp` 文件双缓冲机制配合 `os.fsync` 强制刷盘后安全原子替换（`os.replace`），彻底终结了因为系统断电、蓝屏或强杀进程导致的 `omnipack_config.json` 内容变为空白进而丢失所有状态的致命 Bug。
  - 增加了防崩溃自愈机制：在解析 JSON 配置失败时，会自动将损坏文件备份为 `.corrupt.<timestamp>.json` 并回退至默认配置以确保软件正常启动。
- **精简发布包体积**：
  - 修正了 `build_app.py`，移除了将 `pypi_search_cache.json` 强行打包进应用根目录的行为，确保了发版程序的纯净与轻量化。
- **严格测试覆盖**：
  - 编写了 `test_winget_sanitize_output` 流水线测试，并且修复了旧代码里因不合规的 Python `invalid escape sequence` 产生的运行告警。

### 🧩 WinGet 解析引擎终极重构

- **控制字符与 ANSI 无伤过滤**：
  - 在 `core/winget_helpers.py` 的 `_sanitize_terminal_output` 中实现了严苛的流接管，一比一高仿终端退格符 (`\b`) 与回车符 (`\r`) 逻辑，直接无视乱码和隐形控制符，确保表格列头不被进度条动画吃掉。
- **动态列头坐标纠偏与 Ultimate Fallback**：
  - 引入表头坐标偏移探测算法应对加载条占位符，且增加了极限回退机制：当标准的 `------` 分隔线被完全截断抹除时，底层算法会退化为扫描 `Name` 与 `Id` 关键字强行锚定列坐标，实现真正的乱码免疫。

</details>

This update addresses table parsing crashes in complex WinGet output scenarios and significantly enhances underlying runtime stability and network security. Major highlights include power-loss protection for config files, publisher verification for runtime downloads, and SSL verification bypassing for HTTP proxies.

### 🛡️ Network Security & Verification
- **Authenticode Signature Verification**:
  - Introduced Windows native `Get-AuthenticodeSignature` strong verification in `core/runtime_update.py` to automatically verify SHA256 checksums of downloaded Python/Node.js installers.
  - Implemented strict **publisher whitelist defense**: Enforces signatures belonging to "Python Software Foundation", "Node.js Foundation", or "OpenJS Foundation". Installations are immediately aborted and files destroyed if signatures are invalid or publishers mismatch, preventing poisoning via network hijacking.
- **Insecure SSL/TLS Bypass**:
  - Added `insecure` option in `core/network_proxy.py`. When enabled, it downgrades urllib requests to an untrusted SSL context and injects environment variables `NPM_CONFIG_STRICT_SSL=false` and `NODE_TLS_REJECT_UNAUTHORIZED=0` to downstream NPM processes, improving compatibility with corporate intranets or proxy sniffers (e.g., Fiddler/Charles).

### ⚙️ Core Stability & Reliability
- **Atomic Config Writes & Auto-Recovery**:
  - Completely refactored the saving strategy in `core/config.py` using a double-buffer `tmp` file mechanism with `os.fsync` disk flushing before atomic replacement (`os.replace`). This prevents `omnipack_config.json` corruption from power outages, system crashes, or process terminations.
  - Added self-healing recovery: Automatically backs up corrupted configurations as `.corrupt.<timestamp>.json` and reverts to defaults to ensure a successful application launch.
- **Packaging Optimization**:
  - Corrected `build_app.py` to exclude `pypi_search_cache.json` from the application's root directory, ensuring a clean and lightweight package size.
- **Strict Test Coverage**:
  - Added pipeline testing for WinGet terminal output sanitization (`test_winget_sanitize_output`) and fixed running warnings regarding Python invalid escape sequences.

### 🧩 Bulletproof WinGet Parser
- **Zero-Damage Control Character Filtering**:
  - Implemented a strict stream filter in `_sanitize_terminal_output` (winget_helpers.py) that mimics backspace (`\b`) and carriage return (`\r`) terminal behaviors, filtering out progress animations and corrupt characters to preserve tabular columns.
- **Dynamic Offset & Ultimate Fallback**:
  - Introduced column-header coordinate offset detection to handle loading bars and implemented an ultimate fallback. If the standard `------` separator line is truncated, the engine falls back to scanning `Name` and `Id` keywords to anchor column boundaries.

---

## 🇺🇸 [v10] - Real PTY Terminal, WinGet Proxy Auto-Heal & Security Upgrades

<details>
<summary><b>🇨🇳 [v10] - 真实 PTY 交互终端集成、WinGet 代理自愈保障与安全机制升级 (中文说明)</b></summary>

<br>

本次更新新加入了真正的 **PTY 交互终端** 集成，彻底摒弃了此前纯文本模拟控制台的局限性。支持完整的 ANSI 渲染、键盘捕获、命令同步注入以及增量刷新；同时，重构了 WinGet 命令行代理切换机制，引入了稳健的“启动即自愈代理”及系统级崩溃弹窗屏蔽锁；此外，将高风险的环境卸载与冲突警告模态确认（QMessageBox）重新安全归位，全面实现了全防灾与高流畅度运行。

### 🚀 真实 PTY 伪终端整合与静默同步

- **跨平台 PTY 后端与 ANSI 高彩渲染**：
  - Windows 下动态引入 `pywinpty`，macOS/Linux 直接调用标准库 `pty` 实现 0 增量跨平台共享。底层引入 `pyte` 解析器，完美高亮流式呈现 `uv`、`pip`、`npm` 等包管理器的**动态字符进度条**，杜绝了乱码和刷屏。
- **按键劫持与双控制台热切换**：
  - 重构 `_TerminalTextEdit` 文本框实现全按键劫持（支持 Tab 补全、方向键历史、密码隐形及 Ctrl+C 中断）。右侧区域以 `QSplitter` 动态组合：上为 Simulated 只读日志，下为 Real Terminal 伪终端，支持热切换和首选项持久化。
- **环境静默同步与增量 Fast Refresh**：
  - 用户在界面跳转或激活虚拟环境时，主程序静默向 PTY 发送 `cd`/`activate` 命令实现终端联动。
  - 面板操作（如批量更新）直接转为命令行写入 PTY 终端，末尾拼接 UUID 标记（Marker）。后台正则检测 Marker，命令一结束即触发**增量快速刷新**，避免了界面长期锁定。

### ⚙️ WinGet 代理自愈保障与模拟控制台联动

- **启动自愈 WinGet 代理状态**：
  - 当软件启动并首次切入 WinGet 面板触发扫描刷新时，只要检测到配置文件中的代理为启用状态，系统会自动静默拉起 `winget settings --enable ProxyCommandLineOptions` 确保命令，彻底自愈因版本覆盖安装或先前配置丢失导致代理实际未生效的系统级问题。
- **诊断指示标签降噪与控制台投射**：
  - 移除了由于配置或开关 WinGet 代理而弹出的所有前台模态对话框，将其静默且纯文本地输出在 WinGet 设置最下方的诊断状态标签（`self.winget_diag_label`）中。
  - 引入 `_log_to_parent` 机制，在开始/结束执行 WinGet 代理或源设置时，向外层模拟控制台原样输出执行 of CLI 命令（如 `Executing: winget settings...`）与任务终态（Success/Error）。
- **防 GC 闪退与系统级弹窗完全封印**：
  - 采用活跃线程防收留集合，杜绝后台自愈 QThread 因局部变量被 Python 垃圾回收所引发的 PySide 经典闪退。
  - 主入口点 `run_main()` 注入 `SetErrorMode(0x0001 | 0x0002 | 0x8000)`，从根本上封锁并免除了管理员权限下执行商店别名 `winget` 偶发的 `0xc0000142` 系统级初始化崩溃弹窗。

### 🛡️ 高风险操作强模态确认安全归位

- **QMessageBox 强阻断避免误操作**：
  - 纠正了非模态提示所带来的潜在环境损坏风险，将涉及 Python/Node.js/WinGet 三大板块的**软件卸载**、**批量卸载**、**升级依赖约束警告**以及**构建分支切换提示**等高风险破坏性操作全部重新改回 `QMessageBox` 的强阻断式模态询问弹窗，坚决捍卫用户开发环境的安全性。

</details>

This release integrates a real **PTY (Pseudo-Terminal) interactive terminal**, shifting away from simple text-simulated consoles. It supports full ANSI rendering, keyboard capture, silent command injection, and incremental updates. WinGet agent management has been refactored to introduce start-up auto-healing and a system crash dialog blocker. High-risk environment actions also safely return to modal confirmations (QMessageBox).

### 🚀 Real PTY Terminal & Silent Sync
- **PTY Engine & ANSI Rendering**:
  - Dynamically imports `pywinpty` on Windows and utilizes the standard `pty` library on macOS/Linux for zero-dependency cross-platform support. Integrated the `pyte` rendering engine to present dynamic progress bars for `uv`, `pip`, and `npm` correctly.
- **Input Hijack & Coexistence**:
  - Refactored `_TerminalTextEdit` to capture inputs (Tab completion, history navigation, hidden passwords, and Ctrl+C interrupts). Combines simulated logs and PTY terminals using `QSplitter` for easy hot-switching.
- **Venv Sync & Fast Refresh**:
  - Silently feeds `cd`/`activate` commands to the PTY terminal upon environment switching.
  - Direct actions (e.g., batch updates) are written straight to the PTY terminal with a UUID marker appended. The backend detects this marker and triggers a **Fast Refresh** upon completion, avoiding long UI locks.

### ⚙️ WinGet Proxy Auto-Heal & Console Logging
- **Start-up Auto-Heal**:
  - When switching to the WinGet panel on startup, if a proxy is configured, the system silently triggers `winget settings --enable ProxyCommandLineOptions` to self-heal outdated or missing proxy states.
- **Settings Dialog Logging & Target Label**:
  - Replaced modal dialogs during WinGet settings updates with inline diagnostic logs in `self.winget_diag_label`.
  - Implemented `_log_to_parent` to pipe executed commands (e.g. `Executing: winget settings...`) and outcomes directly into the simulated logger.
- **Thread GC Protection & SetErrorMode**:
  - Keeps active references to background QThreads to prevent PySide application crashes caused by garbage collection of local thread variables.
  - Injected Windows `SetErrorMode(0x0001 | 0x0002 | 0x8000)` at launch to suppress `0xc0000142` system initialization crash popups when running WinGet under administrator privileges.

### 🛡️ Secure Action Recovery
- **QMessageBox Strong Blocks**:
  - Restored modal block dialogs (`QMessageBox`) for destructive operations (uninstallation, batch removals, dependency update warnings, and branch switching) to protect developer environment safety.

---

## 🇺🇸 [v9] - WinGet System & User Package Management

<details>
<summary><b>🇨🇳 [v9] - WinGet 系统级与用户级包管理支持 (中文说明)</b></summary>

<br>

本次更新新加入了 Windows 系统内置包管理器 **WinGet** 的完整集成，支持对系统全局以及当前用户级别的软件进行可视化扫描、自动更新、锁定（Pin）、卸载与安装。同时完成了 UI 面板注册架构重构，支持在不同操作系统下动态加载对应管理器。

### 🚀 WinGet 深度整合

- **环境双 Scope 扫描**：
  - 支持 **系统范围** 与 **用户范围 (User)** 的独立环境扫描，分别对应虚拟路径 `winget://machine` 和 `winget://user`。
  - **智能跨范围数据迁移与去重**：读取 Windows 注册表 `Uninstall` 键下的 `InstallLocation`（支持 32/64 位及 HKLM/HKCU 注册表路径，支持 %USERPROFILE% 等前缀分析），将物理路径在用户目录下的软件智能划归为 User 范围，将 Program Files 等目录下的软件划归为 Machine 范围；若同一应用在两个范围重复安装，卡片上会自动显示 `[Also Installed In User/Machine]` 徽章标记，防重复探测。
- **等宽列切片命令行解析**：
  - 使用字符渲染宽度解析机制（自动对东亚宽字符进行 `padding/restore`），通过固定列宽切片，彻底解决了 Winget 本地化（多语言）输出以及部分列数据为空时导致的列错位、合并漂移等解析难题。
- **生命周期完整管控**：
  - **安装**：支持直接输入 WinGet ID 进行精准安装，支持自动推荐及静默安装。
  - **更新**：支持对单款应用更新，或勾选多款应用进行 **批量并发升级**。
  - **静默/交互卸载**：支持单款及批量并发静默卸载，带有安全确认对话框。
  - **锁定更新**：原生集成 `winget pin`。用户可以在 UI 界面通过 ⚙ 按钮直接锁定软件更新，锁定后显示 `[Pinned]` 徽章，同时不会被 "Outdated" 全局选项自动勾选。
  - **版本异常与降级保护**：当本地安装版本新于 Registry 注册表最新版本时，自动显示 `[⚠ Newer]` 徽章并阻止误升级。
  - **多层 Scope 自动回退**：当安装或升级因权限/路径冲突在 Machine 范围失败时，会自动回退尝试以 `user` 范围（如 `winget install --scope user`）再次运行，最大程度保障操作成功率。

### ⚙️ 后端设置与实时诊断

- **WinGet 后端管理**：
  - Settings 页面新增 WinGet 后端设置（仅在 Windows 操作系统下可见）。
  - **自定义引擎路径**：支持自动探测系统 PATH 上的 `winget.exe`，也支持用户手动浏览并指定特定路径。
  - **安装模式选择**：支持配置默认的安装模式：静默模式 (`silent`)、交互模式 (`interactive`)、默认模式 (`default`)。
  - **实时诊断面板**：可在 Settings 界面实时查看 WinGet 可用状态、绝对路径、当前版本号、已开启的 Registry 源个数以及详细的源状态错误。

### 🏗️ UI 面板注册重构

- **动态面板系统**：
  - 重构了主窗口 `ui/main_window.py` 内部结构，将写死的 Pip/Npm 面板完全抽象，改为基于配置字典的 `_register_panel()` 动态面板注册机制。
  - **按平台加载**：仅当检测到 Windows 系统时才注册 WinGet 面板，其他系统自动隐藏，消除了跨平台冗余。
  - 统一了动态 Splitter 尺寸联动同步、首屏卡片防抖懒加载扫描、状态栏 counts 更新以及当前活动 Tab 的持久化记忆逻辑。

### 📦 通用控件与编译增强

- **徽章渲染系统扩展**：`PackageCard` 增加元数据 Badge 渲染机制，支持带有悬停提示 与自定义 QSS 样式的多种彩色徽章（如 `[Pinned]`、`[Also Installed]`、`[⚠ Newer]`、`[Unknown]`）。
- **可配置化 gear 动作按钮**：当包 metadata 标记 `supports_config` 为 True 时，卡片上会自动渲染 `⚙` 配置图标并绑定专属弹窗（如 Python/Npm 显示 tag/版本，WinGet 显示 Pin/卸载路径等）。
- **跨平台 Nuitka 编译缓存清理补丁**：
  - 优化了 `scripts/patch_nuitka_msvc.py` 中的 pyc 缓存清理机制，使用 `importlib.util.cache_from_source(path)` 进行动态缓存路径解析，不再依赖硬编码的 Python 版本后缀，自动清理全平台/多版本 `__pycache__` 缓存。

</details>

This update integrates Windows Package Manager (**WinGet**), supporting visual scanning, updates, pins, installations, and removals at both system-wide and current-user scopes. Panel registration has been refactored to load panels dynamically based on the current operating system.

### 🚀 WinGet Support
- **Dual Scope Scanning**:
  - Supports scanning system/machine (`winget://machine`) and current user (`winget://user`) scopes independently.
  - **Smart Package Redistribution**: Probes the Windows Registry (`InstallLocation` in HKLM/HKCU, supporting 32/64-bit and %USERPROFILE% paths) to classify software scopes. Overlapping installations dynamically display `[Also Installed In User/Machine]` badges to prevent duplicates.
- **Console Tabular Parser**:
  - Employs a char-width calculation parser supporting East Asian double-width characters to align tables and prevent parsing offsets when columns are blank.
- **Full Lifecycle Actions**:
  - **Install**: Installs packages using precise WinGet IDs with support for silent install recommendations.
  - **Update & Batch Update**: Supports updating individual programs or checking multiple entries for concurrent batch updates.
  - **Uninstall**: Silent batch uninstall with safety confirmation popups.
  - **Blocking Pin**: Integrates `winget pin` to pin application versions. Pinned items show a `[Pinned]` badge and are skipped by automatic selection.
  - **Downgrade Warning**: Displays a `[⚠ Newer]` badge if the installed version is newer than the remote registry version, preventing unintentional downgrades.
  - **Scope Fallback**: If installing on the Machine scope fails due to permissions, the engine automatically attempts user-scope deployment (`--scope user`).

### ⚙️ WinGet Settings & Diagnostics
- **Backend Settings**:
  - Introduced WinGet settings (Windows only).
  - **Custom Paths**: Detects system PATH paths or allows manual configurations.
  - **Install Modes**: Select default modes: `silent`, `interactive`, or `default`.
  - **Diagnostics Panel**: Real-time inspection of WinGet availability, paths, versions, source numbers, and status errors.

### 🏗️ Unified Panel Registration
- **Dynamic Panel Loading**:
  - Refactored `ui/main_window.py` to register Pip/Npm panels dynamically.
  - **Platform-Aware Registration**: Registers the WinGet panel only on Windows, keeping other platforms clean.
  - Centralized Splitter sizing sync, lazy loading, status bar count updates, and tab selection persistence.

### 📦 General Widget & Script Improvements
- **Badge Rendering System**: Added customized QSS badges (e.g., `[Pinned]`, `[Also Installed]`, `[⚠ Newer]`, `[Unknown]`) on `PackageCard` with support for tooltips.
- **Configurable Action Gear**: Renders a `⚙` config button when packages mark `supports_config=True` to pop dialog actions (e.g., version pinning, uninstall paths).
- **Nuitka Cache Clean Patch**:
  - Optimized `scripts/patch_nuitka_msvc.py` to clean pyc caches dynamically using `importlib.util.cache_from_source(path)`, removing hardcoded Python version suffixes.

---

## 🇺🇸 [v8] - Compiler Hardening, Installer Fallback & UX

<details>
<summary><b>🇨🇳 [v8] - 编译器加固、运行时安装回退与交互增强 (中文说明)</b></summary>

<br>

本次更新围绕三大主题：构建系统从单一 Zig 编译器升级为 MSVC 优先的智能编译链（兼顾缓存与性能）、winget 不可用时自动回退至官方安装器下载、以及一键展开/折叠等多项 UI 交互改进。

### 🛠️ 构建系统 MSVC 编译器支持

此前构建仅使用 Zig 编译器后端，无法利用 MSVC 的跨构建缓存（clcache）加速。本轮实现完整 MSVC 自动检测链：

- **`detect_msvc_env()` 自动检测引擎**：支持三层搜索策略——① 显式路径（`msvc_path.cfg` 配置文件 → `MSVC_VCVARS_PATH` 环境变量 → VS Insiders 默认路径）；② VS Insiders 扁平布局（`Microsoft Visual Studio\18\Insiders\VC\Auxiliary\Build\vcvars64.bat`）；③ 传统布局（`<year>\<edition>\VC\Auxiliary\Build\vcvars64.bat`）。找到 `vcvars64.bat` 后通过 `_capture_vcvars_env()` 捕获完整环境变量并通过 `MSVC_USE_SCRIPT` 传递给 SCons。
- **`_capture_vcvars_env()` 路径空格修复**：使用 `shell=True` + `cmd /V:ON /C "call \"<path>\" && set"` 替代手动拼接命令串，彻底解决 Visual Studio 路径含空格时 `subprocess.run` 参数解析失败的问题。
- **编译器优先级**：`detect_msvc_env()` 成功 → 使用 MSVC（`--msvc=X.Y`）；失败 → 回退 Zig。MSVC 模式下可复用 clcache 跨构建缓存，大幅加速重复编译。
- **`build_app.py` 命令行参数**：新增 `--clean` 选项（清理 dist 目录后全量重编译），不带参数时默认增量构建复用缓存。
- **Nuitka MSVC 补丁脚本**：新增 `scripts/patch_nuitka_msvc.py`，为 Nuitka 的 `SconsUtils.py` 注入 `MSVC_USE_SCRIPT` 环境变量支持，使得 SCons 能通过环境变量而非注册表/vswhere 发现非标准安装的 Visual Studio（如 Insiders 版）。支持 `--check` / `--revert` 操作，自动清理 `.pyc` 缓存。
- **入口点重命名**：`OmniPack.pyw` → `OmniPack.py`，构建与调试入口统一。

### 🔄 运行时安装器回退：winget 不可用时的自动救援

`winget` 在某些系统/网络环境下源不可用（`failed when opening source` / `0x8d15000f`），导致 Python/Node.js 运行时更新完全失败。本轮新增从官方源下载安装器的完整回退链路：

- **下载引擎**：`download_runtime_installer()` 从 `python.org` / `nodejs.org` 下载官方安装器到临时目录，支持断点监控（每 ~0.8s 或每 5 MiB 回调进度），下载不完整自动清理。
- **静默安装命令生成**：`build_installer_run_command()` — Python 使用 `/quiet InstallAllUsers=1 PrependPath=1`；Node.js 使用 `msiexec /i <msi> /quiet /norestart`。
- **winget 失败检测**：`RuntimeUpdateWorker` 检测子进程输出中的 `failed when opening source` 或 `0x8d15000f`，区分 "winget 源不可用" 与 "其他命令失败"。
- **`runtime_update_done` 信号扩展**：从 3 参数 (`env_path, success, message`) 扩展为 5 参数 (`env_path, success, message, winget_failed, target_version`)，下游 Panel 可判断是否需要触发安装器回退。
- **用户交互对话框**：`_offer_installer_fallback()` 弹出三选项对话框 — "Download & Install" 自动下载并静默安装、"Open Download Page" 在浏览器中打开下载页、"Cancel" 跳过。
- **`RuntimeInstallerWorker`**：在 `pip_panel.py` / `npm_panel.py` 中分别实现，基于 `BaseCmdWorker` 共享基类，实时输出下载进度与安装状态到控制台。

### 🖥️ UI 交互增强

- **一键展开/折叠所有环境卡片**：工具栏新增 `Expand` 三态复选框。部分展开时显示半选态（`PartiallyChecked`），点击后统一展开；全展开时显示勾选态，点击后全部折叠。每个环境卡片展开/折叠时通过 `expand_toggled` 信号驱动复选框状态同步。
- **Settings 环境列表增强**：拖拽排序保存后，主界面卡片顺序即时同步重排（`_reorder_env_cards()`）；双击编辑已有环境；按 `Delete` 键快捷删除选中项（`eventFilter` 监听 `Qt.Key_Delete`）；提示文案更新为 "Drag to reorder; Double click to edit; Del key to remove"。
- **Settings Auto Detect 重构**：Python 自动扫描从内联路径遍历重构为调用 `find_system_pythons()` 统一函数，利用带标签的扫描结果（`py_info["name"]` / `py_info["tags"]`）通过 `config_mgr.add_pip_env()` 正式接口添加，消除重复代码。

### 🧠 依赖解析增强

- **PEP 508 环境标记求值引擎**：`dep_resolver.py` 新增完整的 marker 解析与求值链 — `split_requirement_marker()` 分离 requirement 与 marker → `marker_applies()` 优先使用 `packaging.markers.Marker.evaluate()`（若可用）→ `_evaluate_marker_fallback()` 内置回退求值器。支持 `python_version`、`sys_platform`、`os_name`、`platform_machine` 等全部标准 marker 变量，自动跳过不适用于当前平台/环境的依赖项（如 `sys_platform != "win32"` 的条件依赖不再污染 Windows 上的依赖树）。
- **版本约束智能简化**：`simplify_constraint()` 合并冗余约束 — `>=1.0, >=1.5` → `>=1.5`；`<2.0, <=1.9` → `<=1.9` — 使依赖树中显示的需求更清晰精简。
- **`_restore_package_state()` 新参数**：新增 `restore_update_state` 开关。完整后台扫描（`--outdated` 已重新查询）时设为 `False`，不再从旧包状态恢复过期的 `has_update` / `latest_version`，避免陈旧数据污染新扫描结果。

### 📦 NPM 环境路径解析修正

- **`resolve_env_command_context()` 统一方法**：替代此前分散在各 Worker 中的 `is_global = (env.type == "global" or env.path == "global")` 判断。正确识别三种场景：
  - 标记为 global → `-g` 标志，无 cwd
  - 路径为 `%APPDATA%\npm\node_modules`（Roaming 全局包）→ `-g --prefix <dir>`，确保更新包文件同时刷新同级 CLI shims
  - 路径以 `node_modules` 结尾 → cwd 为其父目录，支持本地项目
- **`roaming_modules_path()`**：返回 Windows Roaming npm 的 `node_modules` 路径。
- **`get_global_prefix_and_root()`**：通过 `npm prefix -g` / `npm root -g` 查询全局安装位置。
- 所有 NPM Worker（`NpmScanWorker`、`NpmUpdateCheckWorker`、`NpmActionWorker`、`NpmBatchUpdateWorker`）统一采用新方法并支持 `--prefix` 参数。

### ⚡ 控制台日志优化

- **命令感知心跳标签**：`\r` 进度行与 `\n` 日志行分流处理 — `\r` 结尾的行视为进度条更新（按 ~0.8s 节流避免刷屏），`\n` 结尾的行即时输出。
- **上下文感知心跳**：长时间无输出时的心跳消息根据命令类型动态切换 — `uv/pip` → "downloading/installing packages..."，`npm` → "downloading npm packages..."，`winget` → "waiting for winget..."。
- **长静默提示精简**：30 秒无输出的提示从多行详细说明精简为一行 "still no output from subprocess — large download or build in progress"。
- **`uv -v` 详情标志**：`UpdateWorker`、`BatchUpdateWorker`、`InstallWorker` 中 `uv pip install` 命令统一添加 `-v` 标志，提供更丰富的下载/构建日志。

### 🐧 跨平台增强

- **macOS Python.org 框架路径**：`find_system_pythons()` 新增扫描 `/Library/Frameworks/Python.framework/Versions/X.Y/bin/python3`，自动发现通过官方 pkg 安装的 Python。

</details>

This release upgrades the build pipeline from Zig to a prioritized MSVC toolchain, supports automatic web-download fallback when WinGet sources fail, and enhances UI components like card accordion toggles and custom drag-and-drop settings.

### 🛠️ MSVC Compiler Toolchain
Integrates a robust MSVC auto-detection pipeline to leverage clcache for accelerated compilation:
- **`detect_msvc_env()` Engine**: Explores local configurations (`msvc_path.cfg`), environmental variables (`MSVC_VCVARS_PATH`), VS Insiders paths, and traditional VS layouts. Locates `vcvars64.bat` and runs `_capture_vcvars_env()` to pass variables to SCons.
- **Path Escaping Fix**: Runs `shell=True` with `cmd /V:ON /C "call ..."` to capture environment variables, resolving parameter parser issues for VS paths containing spaces.
- **Compiler Precedence**: Uses MSVC if detected, with fallback to Zig.
- **`build_app.py` Args**: Added `--clean` option to purge previous builds.
- **Nuitka MSVC Patch**: Injects `MSVC_USE_SCRIPT` support into Nuitka's `SconsUtils.py` via `scripts/patch_nuitka_msvc.py` to support VS Insiders.
- **Rename**: Renamed `OmniPack.pyw` to `OmniPack.py` for debugging symmetry.

### 🔄 Runtime Installer Fallback
Provides a web download pipeline when system `winget` sources fail (e.g., error code `0x8d15000f`):
- **Download Engine**: Downloads official packages from python.org/nodejs.org to temporary directories with progress callbacks.
- **Silent Arguments**: Generates `/quiet InstallAllUsers=1 PrependPath=1` for Python, and `msiexec /i <msi> /quiet /norestart` for Node.js.
- **Error Detection**: `RuntimeUpdateWorker` detects source failures (such as `failed when opening source`) to trigger fallback.
- **Dialog Fallback**: `_offer_installer_fallback()` triggers a dialog offering automated setup, redirecting to browser downloads, or canceling.

### 🖥️ UI/UX Improvements
- **Expand/Collapse All Cards**: Added a 3-state checkbox (`Expand`) to bulk toggle environment cards.
- **Drag-to-Reorder Environments**: Instantly reorders dashboard cards (`_reorder_env_cards()`) when dragging settings list items. Supports double-clicking to edit and deleting via `Delete` key.
- **Auto Detect Optimization**: Uses `find_system_pythons()` to scan local interpreters instead of hardcoded paths.

### 🧠 Dependency Resolution
- **PEP 508 Markers Engine**: Evaluates dependency requirements using `packaging.markers.Marker` with `_evaluate_marker_fallback()` as backup, filtering out incompatible platforms (e.g. non-Windows constraints).
- **Simplify Constraints**: Simplifies constraint ranges (e.g., `>=1.0, >=1.5` -> `>=1.5`).
- **Scan Isolation**: Disables outdated state inheritance during fresh scans (`restore_update_state=False`).

### 📦 NPM Path Resolution
- **`resolve_env_command_context()`**: Centralizes environment scoping:
  - Global scope -> `-g` flag.
  - Roaming directories -> `-g --prefix <dir>`.
  - Local folders -> CWD set to node_modules parent.
- **`roaming_modules_path()`** & **`get_global_prefix_and_root()`**: Resolves Windows Roaming npm locations.

### ⚡ Console Log Refinements
- **Command-Aware Heartbeats**: Limits progress line updates (e.g., `\r`) to ~0.8s intervals and logs target context status (e.g., "downloading packages...").
- **`uv -v` Flags**: Passes verbose flag `-v` to `uv pip install` command sequences.

### 🐧 Cross-Platform Upgrades
- **macOS framework paths**: Added `/Library/Frameworks/Python.framework` scanning in `find_system_pythons()`.

---

## 🇺🇸 [v7] - Packaging Hardening & Offline Cache

<details>
<summary><b>🇨🇳 [v7] - 打包加固与离线缓存 (中文说明)</b></summary>

<br>

### 🔒 配置文件持久化修复

Nuitka onefile 模式下配置文件 (`omnipack_config.json`, `pypi_search_cache.json`) 此前被写入系统临时目录（`%TEMP%\.onefile_XXXXX\`），重启后丢失。根因是 Nuitka 不设 `sys.frozen`（PyInstaller 专属标志），导致应用误判为开发模式，通过 `__file__` 解析路径进而指向临时解压目录。

- **Nuitka 检测重构**：新增 `_is_frozen()` 双路径检测——PyInstaller 的 `sys.frozen` + Nuitka 的 temp 目录特征（`__file__` 位于 `%TEMP%` 下即为 onefile 解压运行）。
- **真实路径解析**：新增 `_get_real_exe_path()`，通过 Windows API `GetModuleFileNameW(NULL)` 向内核查询进程真实 exe 路径，彻底绕过 Nuitka/PyInstaller 对 `sys.executable` 和 `sys.argv[0]` 的路径改写。`get_persistent_root()` 与 `get_app_root()` 中所有 `sys.executable` 引用统一替换为此 API。
- **便携与安装模式不变**：便携模式（exe 不在 Program Files 下）仍将配置保存在 exe 同级目录；安装模式（Program Files 下）仍使用 `%APPDATA%\OmniPack`。

### 🛡️ 打包安全加固

- **源码泄露堵漏**：`get_data_files()` 新增后缀过滤，跳过 `.py`、`.pyc`、`.pyo` 文件。Nuitka 已将所有 import 的 `.py` 编译为机器码，再通过 `--include-data-file` 附加一份原始源码纯属泄露风险且徒增体积。打包后 `ui/` 目录仅保留 `ui/styles/dark.qss`（Qt 样式表，运行时从文件路径加载），不含任何 Python 源码。
- **黑名单跨目录匹配修复**：`should_ignore()` 新增 basename 匹配——模式 `Architecture.zh-CN.md` 现在能正确命中 `docs/Architecture.zh-CN.md`。此前仅对完整路径做 `fnmatch`，无路径前缀的文件名模式无法匹配子目录下的同名文件。

### 📦 预装完整 PyPI 缓存

- **`pypi_search_cache.json` 打包**：构建时将此文件打入 exe 数据区（804,825 包索引）。`ensure_cache_exists()` 查找优先级调整为：持久化缓存 → 打包完整缓存 → 种子文件 → 硬编码 20 包默认。首次启动时自动将打包缓存复制到持久化目录，用户无需等待首次在线刷新即可搜索全部包名。

### ⚡ 批量更新链路与控制台可见性优化

本轮进一步把"点了 Update 像没反应"这一整条链路做了系统修复与提速，重点是：**批量更新不再静默失败、更新完成后先快刷界面、长时间子进程持续给出存活反馈**。

- **批量更新按钮无响应修复**：修正 `pip_panel` / `npm_panel` 中批量更新收集阶段将 `Environment` dataclass 作为字典键使用的问题。`Environment` 默认不可哈希，选中可更新包后会在内存中抛出 `TypeError: unhashable type: 'Environment'`，表现为工具栏 `Update` 点击后"没有任何反应"。现改为统一使用规范化环境路径作为键，并单独维护环境对象映射。
- **同环境合并、跨环境并行保持有效**：批量更新仍然维持"同环境合并为一条命令、不同环境并行执行"的策略；本次修复后，跨多个 Python / NPM 环境勾选更新时会稳定并发启动多个 worker，不再因为键错误中断。
- **控制台时间戳开关**：右侧控制台标题栏 `Clear` 右侧新增 `timestamp` 复选框。启用后，每行日志前缀显示绝对时间与相对耗时（`[HH:MM:SS.mmm | +X.XXXs]`），并在 `Clear` 或重新勾选时重置计时基准，便于定位瓶颈究竟在下载、刷新还是依赖树解析。
- **日志重复渲染移除**：此前 Worker 日志会先实时输出一次，任务结束后又通过 `log_batch` 整批重放到同一控制台，造成文本插入、重绘和 `processEvents()` 成本翻倍。现在保留逐行实时输出，移除结束后的重复回放，显著降低控制台造成的额外卡顿。
- **机器 JSON 输出静音**：`uv pip list --format json`、`uv pip list --outdated --format json`、`npm list --json`、`npm outdated --json`、`npm view dist-tags --json` 这类仅供程序解析的机器输出不再整段刷入控制台。控制台保留命令行、状态提示和摘要（如 `Loaded JSON for N packages.`），避免大段 JSON 本身拖慢 UI。
- **Python 更新后快速刷新**：Python 环境在包更新 / 安装 / 卸载 / 运行时升级完成后，不再立刻执行完整重扫。新流程改为：先做一次快速刷新，仅重新获取当前已安装包列表并立即恢复左侧界面；随后在后台补做 `--outdated` 查询与依赖树重建。这样用户先拿到可交互界面，再异步补齐完整更新状态与树形结构。
- **快刷状态复用**：快速刷新阶段会尽量复用旧的勾选状态、依赖树拓扑、版本风险标记与未变化包的更新状态，避免界面短暂掉成"0 updates"或丢失已展开/已选中的上下文。
- **仅刷新受影响环境**：Python 包更新、安装、卸载完成后只刷新真正发生变更的环境，不对未涉及的其他环境做重复扫描；运行时更新完成后同样优先走该环境的快速刷新，再后台补完整扫描。
- **后台完整刷新并行执行**：快速刷新结束后，后台完整刷新按环境并发启动。这样多个环境的 `uv pip list --outdated` 与依赖树解析可以并行跑，总墙钟时间更短，同时不会阻塞左侧第一时间恢复。
- **长任务心跳反馈（pip / npm 共用）**：在共享 `BaseCmdWorker` 中新增子进程心跳逻辑。任何通过该基类执行的命令（包括 `uv pip install`、`npm install`、`npm uninstall`、批量更新等）如果连续 5 秒无任何 stdout/stderr 输出，控制台会自动追加 `... still running (12.3s elapsed)` 一类状态行，显著降低大包下载、大项目安装或 registry 查询期间的"假死感"。由于该逻辑位于共享基类，NPM 安装与批量更新链路自动获得同等反馈，无需单独复制实现。
- **长静默原因提示与“无实际变更”说明**：若子进程持续约 30 秒没有任何输出，控制台会追加一条提示，明确说明可能原因包括大包下载/构建、索引或网络缓慢、以及等待其他包管理进程或文件锁释放。对于 `uv pip install -U ...` 成功退出但未报告 `Prepared / Installed / Uninstalled` 的情况，系统不再笼统显示“已更新”，而会改为提示“本次未报告包文件变更，可能先前一次中断的运行已经完成更新”，避免用户误判。

</details>

This update addresses persistent settings issues on frozen executables, resolves packaging security risks, bundles a complete offline PyPI cache, and optimizes concurrent batch update workflows.

### 🔒 Persistent Config
- **Nuitka Detection**: Restructures `_is_frozen()` to accurately identify Nuitka single-file packing models.
- **Exe Path Resolution**: Added `_get_real_exe_path()` via Windows API `GetModuleFileNameW` to bypass redirection.
- **Location Alignment**: Portable mode stores configs in the EXE folder, while installed versions write to `%APPDATA%\OmniPack`.

### 🛡️ Package Security
- **Source Leak Prevention**: Filters out `.py`, `.pyc`, and `.pyo` extensions in `get_data_files()` to keep compilation units private.
- **Ignore Filter Fix**: Extends filename filtering to match basenames, allowing rule hits across nested project folders.

### 📦 Bundled PyPI Cache
- Bundles a comprehensive 800K package dataset (`pypi_search_cache.json`) into the executable data section.

### ⚡ Batch Update Flow & Console Visibility
- **Dictionary Key Correction**: Replaced unhashable Environment objects with normalized directory paths as dictionary keys, preventing `TypeError` crashes during batch update gathering.
- **Console Timestamps**: Added a toggle switch to prefix console outputs with absolute timestamps and relative offsets (`[HH:MM:SS.mmm | +X.XXXs]`).
- **JSON Output Muting**: Mutes machine-oriented JSON outputs (e.g. `uv pip list --format json`) from console logs to reduce UI redraw lag.
- **Fast Refresh for Python**: Quickly updates local inventories before executing long `--outdated` queries.
- **Subprocess Heartbeat**: Automatically writes status lines (e.g. `... still running (12s elapsed)`) if commands run silent for over 5 seconds.

---

## 🇺🇸 [v6] - Performance, Reliability & Visibility

<details>
<summary><b>🇨🇳 [v6] - 性能、可靠性与可见性 (中文说明)</b></summary>

<br>

v6 围绕四个主题系统性地提升日常使用体验：批量更新从串行变为并行（**更快**）、Windows venv 版本检测与升级链路彻底修复（**更准**）、控制台从"沉默黑盒"变为实时终端（**更透明**）。

### 🚀 批量更新性能跃升

核心思路是**合并 + 并行**：同一环境的包合并为一条命令，不同环境之间并行执行。

- **同环境命令合并**：同一环境中选中的多个包不再逐个执行 `uv pip install -U <pkg>` / `npm install <pkg>`，而是合并为一条 `uv pip install -U pkg1 pkg2 ...` 或 `npm install pkg1@ch1 pkg2@ch2 ...`。`uv` 和 `npm` 内置异步 I/O 并行下载与解析，单命令多包即可获得数倍加速。npm 批量更新时保留各包的 dist-tag 通道信息，不丢失更新目标。
- **跨环境并行执行**：当批量更新涉及多个不同虚拟环境或项目目录时，系统同时启动多个 `BatchUpdateWorker` 并行执行——不同环境目录之间完全独立，无文件锁冲突。按环境路径分组调度，同一环境的所有包合并为一个 worker，不同环境的 worker 并行启动。`_active_update_envs` 集合替代了原有的单一 `_update_running` 布尔标志，支持同时追踪多个正在更新的环境，某环境忙时新请求自动回流队列等待。
- **架构支撑**：新增 `BatchUpdateWorker` (pip) 与 `NpmBatchUpdateWorker` (npm)，配套 `batch_update_done` 信号携带包名列表。单包 `update_package` 与 `update_done` 信号保留，`_on_update_done` 委托至 `_on_batch_update_done`，向下兼容。

| 场景 | v5 (串行) | v6 (并行批量) |
|------|-----------|--------------|
| 1 个环境选 5 个包 | 5 次 `uv pip install` | 1 次 `uv pip install pkg1 ... pkg5`，uv 内部并行 |
| 3 个环境各选 3 个包 | 9 次串行命令 | 3 条命令同时执行 |

### 🖥️ 控制台实时可见性

此前控制台有两个层面的缓冲导致"假卡死"：输出信号从未实时发射；扫描 Worker 使用阻塞式 `subprocess.run()`。两者叠加，用户在长时间操作中完全看不到进展。

- **`log_msg` 信号激活**：`BaseCmdWorker._log()` 在追加内存 buffer 的同时立即发出 `log_msg` 信号——该信号虽早已声明并完整连接至 UI（Worker → Manager → Panel → ConsolePanel），但此前从未被 `emit`，所有输出仅在 `run()` 结束时通过 `_flush_logs()` 批量投递。修复后安装、卸载、更新等操作的输出逐行实时抵达控制台。
- **扫描 Worker 流式化**：`_run_command()` 新增 `capture_output` 参数——reader 线程在逐行流式输出的同时收集完整 stdout/stderr，以 `CompletedProcess` 返回供调用方解析 JSON，兼顾实时显示与结果捕获。`ScanWorker` (pip)、`NpmScanWorker` (npm)、`NpmUpdateCheckWorker` (npm) 中全部 `subprocess.run()` 替换为 `self._run_command(capture_output=True)`。最慢的 `uv pip list --outdated`（5-30 秒逐包查询 PyPI）执行前新增 "Checking for package updates..." 状态提示。
- **UI 即时刷新**：`ConsolePanel.log()` 在每条日志插入后调用 `QApplication.processEvents()`，强制 Qt 在子进程运行期间立即重绘控件。reader 线程中的 `Signal.emit()` 由 PySide6 自动排队投递至主线程事件循环，线程安全无需额外加锁。

### 🔧 Windows 虚拟环境：版本检测与运行时升级修复

三个改动共同解决同一个问题链：Windows 上 venv 的版本显示、检测和升级曾经全线存在失真与空操作。

- **pyvenv.cfg 无条件优先**：移除了 `type != "system"` 的类型前提——现在**所有**环境扫描时均读取 `pyvenv.cfg`（若存在）的 `version` / `version_info` 字段。此前若 venv 被误标为 system 类型，会跳过 pyvenv.cfg 回退逻辑，直接使用 `python --version` 结果——而 Windows 上 venv 的 python.exe 是加载系统 Python DLL 的 redirector，在系统 Python 通过 winget 升级后即返回系统版本，导致所有 venv 卡片版本集体虚高。另：`read_venv_cfg_version()` 不再静默吞掉异常，`_on_env_scanned` 回调新增 `card.env = env` 显式赋值消除竞态。
- **虚拟环境两步式运行时升级**：点击 venv 卡片的 `Py` 按钮后，系统会**先**通过 winget 升级对应 major.minor 周期的系统 Python（如 `Python.Python.3.14`），**再**执行 `py -X.Y -m venv --upgrade <venv_root>` 升级虚拟环境本体。此前仅执行后一步，若系统 Python 尚未更新则 venv upgrade 实质为空操作。winget 步骤容错（非零退出码记录警告但继续），确认对话框差异化提示完整操作步骤。
- **构建命令返回类型统一**：`build_python_runtime_update_command`、`build_node_runtime_update_command`、`build_node_runtime_update_command_nvm` 返回类型从 `list[str]` 统一为 `tuple[Optional[list[list[str]]], str]`，支持多步命令序列。`RuntimeUpdateWorker` 与 `NpmRuntimeUpdateWorker` 同步适配——这正是两步式升级（winget 探测 → venv upgrade）的底层支撑。

### 🔧 版本号统一

- 新增项目根目录 `version.py`（`__version__ = "6"`），消除此前 `build_app.py`、`config.py`、多处 User-Agent 字符串中各自硬编码版本号的问题。窗口标题栏现显示版本号（`OmniPack v6 - Developer Package Manager`），所有对外 HTTP 请求的 User-Agent 头统一为 `OmniPack/<version>`。

</details>

This release delivers concurrent batch updates across environments, streaming standard command outputs, version detection fixes for Windows venvs, and a unified version control layout.

### 🚀 Batch Update Performance
- **Command Merging**: Grouped multiple targets in the same directory into a single `uv pip install` or `npm install` sequence.
- **Multi-Environment Concurrency**: Runs concurrent updates in different environments simultaneously using `_active_update_envs` to prevent lock blockades.

### 🖥️ Real-time Console Visibility
- **Live Output Stream**: Fixed log emission issues, allowing standard process logs to pipe dynamically to the UI console during runtime.
- **Reader Stream Integration**: Replaced blocking `subprocess.run` executions with non-blocking stream readers.
- **UI Event Processing**: Forces UI repaint (`QApplication.processEvents()`) on log insertion.

### 🔧 Venv Version Detection & Runtime Upgrade
- **ConfigFile Priority**: Prioritizes `pyvenv.cfg` versions during local scans across all directories.
- **Two-Step Venv Upgrades**: Venv interpreter upgrades now first upgrade the underlying system Python registry before executing local migrations.

### 🔧 Single Version Source
- Centralized version constants in `version.py` (`__version__ = "6"`) and configured standard User-Agents to `OmniPack/<version>`.

---

## 🇺🇸 [v5] - Constraint & Variant Awareness

<details>
<summary><b>🇨🇳 [v5] - 约束感知更新与构建变体识别 (中文说明)</b></summary>

<br>

本次更新聚焦于提高包更新场景的安全性——系统智能判断哪些更新是安全的、哪些存在潜在风险，避免用户在不自知的情况下破坏环境。

### 🧠 智能更新过滤：约束感知的 "Outdated" 勾选
- **约束感知自动勾选**：开启“Outdated”过滤时，系统不再盲目全选所有可更新的包。若一个包的最新版本违反了其依赖者的版本约束（如 `sympy` 要求 `mpmath<1.4`，而最新版为 `1.4.1`），则该包**不会被自动选中**。
- **PEP 440 约束解析器**：新增 `check_version_satisfies_constraint()` 引擎，完整支持 `>=`, `<=`, `>`, `<`, `==`, `!=`, `~=` 运算符及逗号分隔的 AND 组合逻辑。
- **依赖拓扑审计**：扫描完成后自动遍历依赖树，检查每个包的最新版本与其 `required_by` 反向引用中所有约束的兼容性。

### 🔵 构建变体识别
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

</details>

This release enhances dependency safety by parsing PEP 440 constraints and platform build variants to avoid breaking system environments.

### 🧠 Constraint-Aware Selection
- **Constraint Resolution**: Skips automatic selection of packages whose updates violate dependent specifications.
- **PEP 440 Parser**: Added parser engine supporting `>=`, `<=`, `>`, `<`, `==`, `!=`, and `~=` constraints.

### 🔵 Build Variant Awareness
- **Hardware Suffixes**: Scans local builds for platform suffixes (e.g. `+cu132`, `+cpu`).
- **Variant Alerts**: Warns when updates would strip platform accelerators and blocks automatic selection.

### ✨ Risk Visualization
- **Risk Indicators**: Introduced safety badges: Green (`➜` safe), Blue (`🔀` variant change), and Yellow (`⚠` constraint conflict).

---

## 🇺🇸 [v4] - Unified Environment Management & Cross-platform Enhancements

<details>
<summary><b>🇨🇳 [v4] - 环境管理统一与跨平台增强 (中文说明)</b></summary>

<br>

本次更新聚焦于环境管理统一、跨平台路径与启动策略对齐、以及源配置的一致体验。以下内容以当前代码为准。

### 🆕 运行时版本检测与独立更新链路
- **虚拟环境版本显示修正**：Python venv 卡片版本显示优先读取 `pyvenv.cfg`（`version` / `version_info`），避免系统 Python 小版本升级后导致卡片误显示。
- **运行时元数据入模**：`Environment` 新增 `runtime_version`、`runtime_cycle`、`runtime_latest_version`、`runtime_has_update`、`runtime_update_error` 等字段，统一承载解释器级更新状态。
- **多源补丁检测回退**：运行时最新补丁检测采用多级策略（`endoflife.date` -> `winget` -> Python 本机已安装扫描回退），提升在网络波动和镜像差异下的稳定性。
- **Python / Node 对称实现**：Pip 与 Npm 扫描均会写入运行时版本信息，Node 卡片新增运行时版本展示（如 `Node 25.8.1 -> 25.9.0`）。
- **更新语义彻底解耦**：新增独立运行时更新按钮（`Py` / `Nd`）及独立 Worker 信号链路（`runtime_update_done`）；原有 `⇧` 继续仅负责包更新，不再混淆“环境本体更新”。

### ⚙️ 环境管理与持久化
- **首次扫描持久化**：系统 Python 自动发现仅在首次运行时执行，结果写入配置文件，后续以配置为单一事实来源。
- **用户可控排序**：Settings 中支持拖拽排序，顺序会实时回写到配置。
- **[PATH] 标签**：Python 环境若其可执行文件目录在 `PATH` 中，会显示 `[PATH]` 标签。
- **去重一致性**：路径比较统一使用 `normcase(normpath(path))`，避免 Windows 大小写/分隔符差异导致重复。
- **环境管理“逻辑大统一”**：重构 `SettingsDialog`，通过映射驱动实现了 Pip 环境与 NPM 项目管理逻辑的高度复用，成功消除数百行冗余代码。
- **手动添加 QMenu 模式**：点击 `Add Manually...` 弹出专业菜单，支持“选择目录”与“选择文件/可执行文件”双入口，操作指引更明确且一致。
- **Python 深度探测报告**：`Detect System` 重构为后台全量扫描（PATH + Programs + AppData），并新增可视化扫描报告弹窗。
- **废弃代码物理重构**：物理移除旧版 `pip_env_manage_dialog.py` 与 `npm_env_manage_dialog.py` 环境管理对话框。

### ⚙️ 核心引擎与自动化
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

### ✨ UI 与交互优化
- **二段式全宽布局**：环境管理按钮重构为 Row 1 (Input) 与 Row 2 全宽布局，实现完美的视觉平衡与对称性。
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

</details>

Focuses on unified environment administration, platform path alignment, and source configuration alignment.

### 🆕 Runtime & Environment Management
- **Runtime Metadata**: Tracks interpreter cycles and displays update tags (e.g., `Node 25.8.1 -> 25.9.0`).
- **Drag-to-Reorder**: Reorders environments in Settings and updates configs immediately.
- **Settings Refactoring**: Replaced duplicate logic blocks with metadata mappings.
- **uv Bundler Integration**: Bundles `uv` tools inside `bin/` directories to provide zero-dependency packaging.

### 🧠 NPM & Dependency Upgrades
- **Directory Detection**: Added scanning for local NPM `node_modules` folders.
- **Channel Detectors**: Classifies releases based on versions (e.g. beta, rc, nightly, canary) and attaches visual color tags.

### ✨ UI/UX Optimizations
- **Layout Overhaul**: Aligned layout controls with dual-row settings panels.
- **Card Lazy Rendering**: Renders package cards in batches to prevent UI freezes.
- **Local PyPI Cache**: Relies on a local cache file (`pypi_search_cache.json`) for quick package lookup actions.
- **Proxy Module Separation**: Moved proxy properties to an isolated `core/network_proxy.py` module.

---

## 🇺🇸 [v3] - Build & Engine Enhancement

<details>
<summary><b>🇨🇳 [v3] - 构建架构升级与核心引擎加固 (中文说明)</b></summary>

<br>

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

</details>

This release focuses on platform build reliability, persistence adjustments, and NPM execution enhancements.

### 🏗️ Build & Distribution
- **Nuitka Adapters**: Integrates the Zig compiler toolchain to compile C++ executables under Python 3.13.
- **Path Resolution**: Fixed config location tracking in standalone and onefile packages.
- **Clean SCons Pipeline**: Adds auto-clean scripts to strip executable output names.

### 📦 NPM Integration
- **Corepack Integration**: Detects Node.js Corepack properties automatically.
- **Partial Refreshes**: Refactores NPM query communication to check and update single cards in isolation.

### ✨ UI and Persistence
- **Diagnostics Logging**: Writes local error logs to temporary paths if config saving fails.
- **Visual Styles**: Refines styles for `EnvCard` and `ConsolePanel` objects in `dark.qss`.

---

## 🇺🇸 [v2] - Major Update

<details>
<summary><b>🇨🇳 [v2] - 深度依赖拓扑重构 (中文说明)</b></summary>

<br>

**这是 OmniPack 的一次里程碑式更新，Pip 管理面板由平铺列表全面进化为智能拓扑依赖树。**

### 🧠 核心：拓扑依赖解析引擎
- **秒级拓扑扫描**：引入基于 `importlib.metadata` 的子进程扫描技术，1秒内即可完成百级规模包的 `{依赖库, 逆向引用}` 完整建模。
- **Top-level 降噪视图**：默认仅显示用户最关心的第一级入口包（不再受几百个底层依赖的干扰），极大提升了大型环境管理的可读性。
- **约束自动合并**：智能合并对同一依赖包的多重版本约束（如 `vtk >=9.2, <9.7`），不再产生重复冗余卡片。

### 🛡️ 稳健性：幽灵依赖 检测
- **隐形风险识别**：实时检测环境中被需要但“神秘失踪”的包，以红色虚线样式高亮标记。
- **一键补完计划**：侧边集成 `📥` 快捷安装入口，支持针对缺失依赖的垂直修复订阅。

### ✨ 交互：智慧同步与深度对焦
- **跨层级同步勾选**：勾选某一层级的包，全树所有同名分身即刻同步选中状态，逻辑统一。
- **路径逐级寻踪**：选中某个包时，若其存在于已关闭的支线中，系统将自动递归计算祖先路径并强制展开，确保搜索结果“无处遁形”。
- **环境聚焦搜索 (Strategy 3)**：引入带防抖的深度搜索逻辑。只有你“点开”的环境才会消耗 CPU 进行深度递归搜索及自动展开，折叠的环境保持静默，完美平衡了超大规模环境下的搜索性能。

</details>

A major release introducing topological dependency trees to replace plain list dashboards.

### 🧠 Topological Dependency Engine
- **Subprocess Scans**: Resolves complex packages within 1s using `importlib.metadata`.
- **Top-Level Views**: Hides sub-dependencies by default to keep package lists tidy.
- **Combined Constraints**: Combines multiple constraints (e.g. `>=9.2, <9.7`) automatically.

### 🛡️ Ghost Dependencies
- **Risk Identification**: Highlighting uninstalled but required packages with red dashed lines.
- **Direct Resolve**: Added quick-install `📥` buttons to fix missing requirements.

### ✨ Interactive Sync
- **Cascade Checkboxes**: Checking targets automatically syncs checkboxes across matching name cards.
- **Ancestral Expansions**: Expands hidden tree folders automatically if target items are checked.

---

## 🇺🇸 [v1] - Initial Release

<details>
<summary><b>🇨🇳 [v1] - 首个正式版发布 (中文说明)</b></summary>

<br>

**欢迎使用 OmniPack 开发者全能包管理器首个正式版本！**
OmniPack 以环境隔离和极致纯净作为主旨，提供优于传统应用商店的系统服务支持。

### 🚀 架构与核心特性
- **双端整合外壳**：统一了 Pip / uv （局部多环境）与 NPM（系统全局模块）的管理，支持底层线程并发读取，不会造成界面假死卡顿。
- **配置化驱动管理**：不同于“读出本机几百款底层支撑包”，所有待管 Python 或 NPM 目录均遵循主动加入配置文件清单的方式，保持您的控制台绝对纯净。
- **动态状态同步机制**：切换开发环境管理器时（Pip <=> Npm）能完美共享控制面板拖拽的 Splitter 分割位与比例。
- **状态持久化与状态反馈**：能记住关闭前所使用的页面并且恢复尺寸状态；利用窗体最下边缘提供了非常详尽的 "Installed/Updates" 数字监控总览组件。

### 🐍 Python 管理模块
- 实现了同时关联、懒加载 N 个外部 Python `venv`、`conda` 等隔离环境的检测能力。
- 本地基于超高速的 `astral-sh/uv` 引擎提供对 Pip 工具的大幅提速，可以快速勾选多包并且自动使用 `uv` 并发安装更新。
- 提供了自动拆分与按搜索文字快速过滤单个大型隔离环境中冗长包的能力。

### 📦 Node.js (Npm) 管理模块
- 支持对于单个应用的精细配置：可以修改显示给用户侧的简称、自定义功能描述信息。
- **智能通道（Channels）扫描系统**：即便尚未安装某一全局模块，也能自动识别并罗列其线上的诸如 `beta`, `rc`, `next`, `nightly` 等 dist-tags 先行版通道，并支持动态在不同分支进行无缝更新。
- 全新的智能装配编辑对话框：只要把长长的诸如 `npm i -g @cli/tools@rc` 的正则字符复制进编辑面板，对话框就能自己萃取应用特征并展示对应的可选通道按键进行高亮覆盖。

### 🛠 稳定性与现代环境兼容性
- **现代 Python 全兼容**：针对 Python 3.13/3.14+ 及其高版本 PySide6 (6.10.2+) 进行了深度加固，解决了在高版本 Python 内存模型下可能出现的 `SystemError (NULL)` 启动崩溃。
- **健壮性 UI 架构**：重构了所有布局（Layout）初始化逻辑，采用解耦绑定方式，确保在多线程及动态主题切换下的界面鲁棒性。
- **全局异常捕捉器**：引入了基于 `ctypes` 的 Windows 消息框拦截机制，即使程序意外崩溃也能提供清晰的 Traceback 弹窗，拒绝“静默闪退”。
- **规范化事件处理**：修正了 PySide6 事件枚举（如 `QEvent.Type.Polish`）的引用路径，完全符合现代 Qt 6 标准。
- **UI 模块化拆分**：实现了“薄外壳”架构，将 `OmniPackWindow` 类从入口文件剥离至 `ui/main_window.py`，保持了项目结构的长期可维护性。

</details>

Welcome to the initial release of OmniPack!

### 🚀 Architecture & Core Features
- **Integrated Interface**: Combines Pip/uv environments and npm modules in a single thread-safe dashboard.
- **Configuration-Driven**: Shows environments added to the configuration list to keep lists clean.
- **State Synchronization**: Persists pane dimensions and window sizes.

### 🐍 Python (Pip / uv) Module
- Probes conda, system, and virtual environment paths.
- Optimizes installations using astral-sh/uv.

### 📦 Node.js (Npm) Module
- Configures customized display names and metadata for packages.
- Probes releases across channels (e.g. rc, beta, next).

### 🛠️ Stability & Modern Environment Support
- Fixed PySide6 initialization issues under Python 3.13.
- Captures system crashes using ctypes dialog overrides.
- Refactored panels into clean modules (`ui/main_window.py`).
