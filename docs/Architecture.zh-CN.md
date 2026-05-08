# OmniPack 架构与开发指南 (Architecture & AI Dev Guide)

本文档是一份详尽的系统架构说明。**如果你是正在协助人类开发者 AI 编程助手**，在进行任何代码重构或功能添加之前，请**务必仔细阅读本文件**，以理解项目的核心设计哲学和代码边界。

## 1. 核心设计原则

1. **薄窗口模式 (Thin Shell)**：主程序 `OmniPack.pyw` 仅作为最高层容器，处理标签页切换、UI 主题、以及全局状态恢复。它绝不能包含特定包管理器的业务逻辑。
2. **环境中心化 (Environment-Centric)**：所有的包管理逻辑均围绕“环境”展开。
   - **Python (Pip)**：管理系统 Python 环境和用户定义的虚拟环境 (venv)。
   - **NPM (Node)**：管理全局环境 (Global) 和用户定义的项目环境 (Local Projects)。
3. **架构对称性与环境大一统 (Symmetry & Unification)**：Pip 模块与 NPM 模块在代码结构、逻辑流、数据模型和 UI 表现上必须保持高度对称。
   - **命名规范**: 遵循 `Subsystem -> Manager -> Panel -> Card` 的命名链路。
    - **环境同权**: 所有自动发现或手动添加的环境在配置文件中均作为等价项处理。程序仅在首次启动时推荐环境。用户拥有对所有环境（包括自动扫描出的）进行重命名、排序和永久删除的绝对权力。
    - **内核自管 (Engine Self-Management)**: 为了实现“零依赖”运行，程序采用级联式的 `uv` 引擎寻找策略（用户指定 > bin/uv > 系统 PATH），并通过异步 Worker 实现 Github API 版本比对，输出支持 HTML 富文本状态展示。
    - **更新语义分离 (Update Semantics Separation)**: “包更新”与“运行时更新”必须是两条独立链路。`⇧` 仅用于包更新，解释器/Node Runtime 更新必须通过独立动作触发。
    - **版本来源一致性 (Version Source Consistency)**: Python 虚拟环境显示版本优先读取 `pyvenv.cfg`（`version` / `version_info`），避免系统解释器补丁升级后导致卡片误显示。
    - **逻辑归一与工厂化**: 为了降低维护成本，复杂的 UI 交互逻辑（如环境管理页）采用工厂函数 (`_build_env_tab`) 配合**底层的元数据映射驱动 (Metadata-driven logic)**。通过 `_get_env_map` 模式将 Pip 与 NPM 的 Load、Sync、Remove、Process 操作彻底抽象归一。
    - **体验归一**: 用户在任何包管理标签页下的操作直觉应该是完全一致的（如：Outdated Only 过滤器、统一环境管理、拖拽排序）。
    - **设置页归一化模式 (Settings Unification Pattern)**: 所有的设置项均通过统一的窗口管理。环境管理采用 Row 1 (Input: Auto/Manual/Batch) 和 Row 2 (Actions: Edit/Remove) 的全宽按钮布局，确保视觉平衡与交互动作的高度对称。
4. **跨平台原生倾向 (Platform Agnostic)**：
   - **路径中立**: 禁止硬编码 `Scripts` 或 `python.exe`，必须通过 `core/utils.py` 的工具函数进行动态拼接（适配 `bin/python`）。
   - **执行安全**: 调用 subprocess 时必须手动处理 `creationflags`，确保在 Unix 下不会因为 Windows 特有常量导致 `AttributeError`。
    - **开发提效**: `StyleReloader` 仅在开发环境下通过 `QFileSystemWatcher` 监听 QSS，在 Frozen 编译发布包中自动物理屏蔽（仅保留二进制指令流，不加载内存），以极低成本换取极高的调试像素效率。
   - **配置合规**:
     - Linux 优先遵循 `XDG_CONFIG_HOME`，缺省回退到 `~/.config/OmniPack`。
     - macOS 使用 `~/Library/Application Support/OmniPack`。
     - Windows：
       - **开发模式**：源码运行（.pyw）时配置写入工程根目录（仅 Windows）。
       - **便携模式** (Frozen)：默认写入 EXE 同级目录。
       - **安装模式** (Frozen)：若位于 `Program Files` 则自动切到 `AppData\\Roaming`。
       - 可通过 `OMNIPACK_PORTABLE_CONFIG=1/0` 强制覆盖 Frozen 运行状态下的落点。
5. **基类驱动 (Base-Driven Inheritance)**：
   - **UI 层**: 继承 `ui/panels/base_panel.py`，由基类统一提供标准工具栏（搜索、仅显示过时、环境管理按钮）。
   - **逻辑层**: 继承 `core/manager_base.py`，保持数据模型一致。共享 `managers/base_worker.py` 的异步指令执行逻辑。

---

## 2. 完整目录结构与职责说明

### /core - 数据模型与基础抽象
- `core/config.py` - 全局配置管理器。通过 `ConfigManager` 加载/保存 `AppConfig`，包含所有持久化配置字段及其默认值。
- `core/utils.py` - **跨平台工具函数集**。提供 `get_app_root()`、`is_admin()`、`get_persistent_root()`（XDG/APPDATA/便携三模式）、`find_system_pythons()`、`get_python_version()`、`get_uv_path()` 等基础能力。
- `core/env_detector.py` - **环境探测引擎**。负责 Python/NPM 环境的智能识别、跨平台路径修正（`Scripts` vs `bin`）及人类可读名称生成。
  - Python 分类采用”显式标记优先（`pyvenv.cfg` / `conda-meta` / activate）”策略，避免把 `/usr/bin/python3` 等系统解释器误判为 `venv`。
- `core/manager_base.py` - **核心协议层**。定义了 `Environment`、`Package`、`DepRequirement` 等标准数据模型以及 `PackageManager` 抽象基类；`Environment` 现包含 `runtime_version/runtime_cycle/runtime_latest_version/runtime_has_update` 等运行时字段，用于解释器级更新链路。
- `core/runtime_update.py` - **运行时版本与补丁更新策略层**。封装 Python/Node 的版本解析、同周期最新补丁检测（endoflife.date → winget → 本机扫描多源回退）与运行时更新命令构建。
- `core/dep_resolver.py` - **依赖拓扑解析引擎**。通过子进程运行 `importlib.metadata` 脚本，构建完整依赖图（requires/required_by），并合并到 `Package` 对象中；同时自动创建缺失依赖的”幽灵”包条目。
- `core/network_proxy.py` - **代理路由与注入层**。提供 `urlopen()` 自定义 opener（按目标域名启用代理）、`merge_env_for_command()` 将代理环境变量注入子进程、以及代理连通性测试。
- `core/npm_spec.py` - **NPM 规范解析器**。解析 `@scope/name@tag` 格式的包规范字符串，提取包名与 dist-tag。
- `core/source_profiles.py` - **源配置文件**。定义 PyPI/NPM 官方源及常用镜像列表，提供 `detect_system_pip_index_url()` / `detect_system_npm_registry_url()` 系统源探测函数。
- `core/trace_logger.py` - **调试轨迹记录器**。当 `OMNIPACK_TRACE_SELECTION=1` 时启用，以 JSONL 格式记录 UI 选择/过滤事件，用于调试。
- `core/pypi_cache.py` - **PyPI 缓存层**。负责 `pypi_search_cache.json` 的读写、种子引导、词条索引与排序，还封装了后台刷新线程、进度状态、取消/续传流以及 `resolve_refresh_source` 的镜像策略，确保 `AddPackageDialog` 100% 只从本地查询数据而不再解析 PyPI 网页。

### /managers - 业务逻辑执行引擎
- `managers/pip_manager.py` & `managers/npm_manager.py` - 子系统特定的逻辑实现。均需提供异步扫描和命令生成；同时包含运行时检测与 `RuntimeUpdateWorker`，通过 `runtime_update_done` 信号回传解释器/Node 更新结果。
- `managers/base_worker.py` - **共享 Worker 核心**。封装 QThread 的通用逻辑，处理 stdout/stderr 流拦截、ANSI 染色解析和进度状态上报。

### /ui - 图形界面组件

#### /ui/panels - 宏观面板
- `ui/panels/base_panel.py` - **极其神圣的界面基类**。负责渲染双栏布局，并提供**标准工具栏集**（含 Search 框、Outdated Only 勾选框、Manage Envs 按钮）。
- `ui/panels/pip_panel.py` & `ui/panels/npm_panel.py` - 镜像化的业务面板。负责将 Manager 的信号连接至对应的 EnvCard 容器。
- `ui/panels/settings_dialog.py` - 统一设置页；新增 `Backend` 标签聚焦 `uv` 与 PyPI 缓存控制，提供进度轮询/取消按钮；`Proxy` 页压缩布局、默认收起连接测试输出、并提供 `Start/Cancel` 双态按钮以控制后台刷新。

#### /ui/widgets - 颗粒化卡片
- `ui/widgets/env_card_base.py` - **通用环境容器基类**。处理折叠动画、标题与刷新按钮。
- `ui/widgets/pip_env_card.py` - **Python 环境卡片**。渲染 `pip/uv` 环境信息与标签，显示 `Python current -> latest`，并提供独立运行时更新按钮（`Py`）。
- `ui/widgets/npm_env_card.py` - **NPM 环境卡片**。渲染项目/全局环境信息与标签，显示 `Node current -> latest`，并提供独立运行时更新按钮（`Nd`）。
- `ui/widgets/package_card.py` - **通用包条目**。显示版本、更新状态、多通道选择。
- `ui/widgets/console_panel.py` - 控制台输出面板。
- `ui/widgets/add_package_dialog.py` - 添加包对话框；Python 搜索完全依赖 `core/pypi_cache.py` 的离线索引，Node 搜索在第二页使用与 `npm_panel` 等价的 `NpmTagCard` 展示 dist-tags，保持与主面板一致的视觉与交互状态。

---

## 3. UI 交互一致性标准

为了消除不同包管理器之间的割裂感，所有面板必须对齐以下功能：

1. **标准过滤器 (Standard Filters)**：
   - **Search**: 实时搜索环境名、包名及描述。
   - **Outdated Only**: 勾选后仅显示有更新版本的包。此逻辑应由 `BasePanel` 统筹处理，各 `EnvCard` 协作。
2. **环境管理 (Environment Management)**：
   - 统一入口按钮，打开路径添加对话框。支持“一键文件夹识别”与“手动文件指定”。
   - **智能识别 (Self-Aware)**: 添加环境时不再依赖用户精准选择，程序应能自动从文件夹中提取可执行文件位置，并自动向上溯源项目名称（避免 `.venv` 等重复命名）。
   - 能够精准区分“系统级/全局”与“用户级/虚拟”环境。
   - **批量导入 (Batch Import)**: 支持从剪贴板（如 Everything 搜索结果）粘贴多行路径，自动进行批量解析与去重入库。
   - **去重键规范**: 路径比对统一采用 `normcase(normpath(path))`，避免 Windows 下大小写与分隔符差异导致重复。
   - **自定义排序 (UI Drag-and-Drop)**: 在 Settings 中支持拖拽排序，并在 `rowsMoved` 时同步到配置文件。
   - **批处理提交**: 批量导入使用“一次性保存 + 一次性刷新”，避免逐条写盘与反复重绘导致卡顿。
3. **批量操作 (Batch Operations)**：
   - 统一提供“全选过时包”和“一键批量更新”的交互。
4. **运行时更新 (Runtime Update)**：
   - 运行时更新按钮与包更新按钮必须并行存在且语义严格分离。
   - 仅当检测到同周期补丁更新可用时显示运行时更新按钮（Python `Py` / Node `Nd`）。

---

## 4. 面向 AI 的修改范式 (For AI Assistant)

### 4.1 异步与并发
- 所有的 `npm list`, `pip list` 等查版本行为**严禁阻塞主线程**。
- 必须通过 `BaseWorker` 派生子类，配合信号机制回传数据。

### 4.2 数据一致性
- 修改 NPM 相关逻辑时，优先检查 Pip 侧是否已有类似实现，并尽量复用或抽象。
- `Package` 对象的 `has_update` 属性是控制 UI 高亮和过滤的唯一事实来源。

---

**OmniPack 旨在成为最优雅的跨语言包管理中心。阅读完本指南后，你应该已经掌握了如何安全地扩展它的能力。**
