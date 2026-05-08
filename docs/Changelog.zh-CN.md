# Changelog - OmniPack

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

