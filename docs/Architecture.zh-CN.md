# OmniPack 架构与开发指南 (Architecture & AI Dev Guide)

本文档是一份详尽的系统架构说明。**如果你是正在协助人类开发者 AI 编程助手**，在进行任何代码重构或功能添加之前，请**务必仔细阅读本文件**，以理解项目的核心设计哲学和代码边界。

## 1. 核心设计原则

1. **薄窗口模式 (Thin Shell)**：主程序 `OmniPack.pyw` 仅作为最高层容器，处理标签页切换、UI 主题、以及全局状态恢复。它绝不能包含特定包管理器的业务逻辑。
2. **环境中心化 (Environment-Centric)**：所有的包管理逻辑均围绕“环境”展开。
   - **Python (Pip)**：管理系统 Python 环境和用户定义的虚拟环境 (venv)。
   - **NPM (Node)**：管理全局环境 (Global) 和用户定义的项目环境 (Local Projects)。
   - **WinGet (Windows)**：管理 Windows 操作系统的应用程序（合并为统一环境展示，支持系统级与用户级 Scope 标记与混合纳管）。
3. **架构对称性与环境大一统 (Symmetry & Unification)**：Pip、NPM 与 WinGet 模块在代码结构、逻辑流、数据模型和 UI 表现上必须保持高度对称。
   - **命名规范**: 遵循 `Subsystem -> Manager -> Panel -> Card` 的命名链路。
   - **环境同权**: 所有自动发现或手动添加的环境在配置文件中均作为等价项处理。程序仅在首次启动时推荐环境。用户拥有对所有环境（包括自动扫描出的）进行重命名、排序和永久删除的绝对权力。
   - **内核自管 (Engine Self-Management)**: 为了实现“零依赖”运行，程序采用级联式的 `uv` 引擎寻找策略（用户指定 > bin/uv > 系统 PATH），并通过异步 Worker 实现 Github API 版本比对，输出支持 HTML 富文本状态展示。
   - **更新语义分离 (Update Semantics Separation)**: “包更新”与“运行时更新”必须是两条独立链路。`⇧` 仅用于包更新，解释器/Node Runtime 更新必须通过独立动作触发（如 Python 的 `Py`、Node 的 `Nd` 以及 WinGet 自身的 `Wg` 一键升级按钮）。
   - **版本来源一致性 (Version Source Consistency)**: Python 虚拟环境显示版本优先读取 `pyvenv.cfg`（`version` / `version_info`），避免系统解释器补丁升级后导致卡片误显示。
   - **逻辑归一与工厂化**: 为了降低维护成本，复杂的 UI 交互逻辑（如环境管理页）采用工厂函数 (`_build_env_tab`) 配合**底层的元数据映射驱动 (Metadata-driven logic)**。通过 `_get_env_map` 模式将 Pip 与 NPM 的 Load、Sync、Remove、Process 操作彻底抽象归一。
   - **体验归一**: 用户在任何包管理标签页下的操作直觉应该是完全一致的（如：Outdated Only 过滤器、直接拖拽排序、右键快速管理）。
   - **设置页归一化与快捷操作**: 所有的设置项均通过统一的窗口管理。同时为了操作的高效性，主界面列表提供了底部的快速添加（➕ Add Environment）、环境卡片拖拽重排与右键菜单快速删除/编辑，设置页与主界面在此类操作上使用同一套底层的配置管理器逻辑，确保视觉平衡与交互动作的高度对称。
4. **跨平台原生倾向与运行时自愈 (Platform Agnostic & Auto-Setup)**：
   - **路径中立**: 禁止硬编码 `Scripts` 或 `python.exe`，必须通过 `core/utils.py` 的工具函数进行动态拼接（适配 `bin/python`）。
   - **跨平台运行时安装自愈**: 内置多平台运行时自动下载与静默/交互式部署逻辑。Windows 下支持通过 PowerShell 自动拉取 WinGet 及其安全依赖包；Linux 下支持使用 `uv` 极速安装 Python 并自动配置 Node.js 物理路径软链接；macOS 下支持下载官方 `.pkg` 安装包并流式拉起 GUI 安装器，实现运行环境的无感搭建。
   - **执行安全**: 调用 subprocess 时必须手动处理 `creationflags`，确保在 Unix 下不会因为 Windows 特有常量导致 `AttributeError`。
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
- `core/config.py` - 全局配置管理器。通过 `ConfigManager` 加载/保存 `AppConfig`，包含所有持久化配置字段及其默认值，含调试调试标记 `force_show_setup`。
- `core/utils.py` - **跨平台工具函数集**。提供 `get_app_root()`、`is_admin()`、`get_persistent_root()`、`find_system_pythons()`、`get_python_version()`、`get_uv_path()` 等基础能力。
- `core/env_detector.py` - **环境探测引擎**。负责 Python/NPM 环境的智能识别、跨平台路径修正（`Scripts` vs `bin`）及环境名称生成。
- `core/manager_base.py` - **核心协议层**。定义了 `Environment`、`Package`、`DepRequirement` 等标准数据模型以及 `PackageManager` 基类。
- `core/runtime_update.py` - **运行时版本与多平台安装层**。封装 Python/Node 的版本解析、同周期最新补丁检测，以及跨平台 (Windows/macOS/Linux) 安装命令的生成、下载与调用逻辑（如 uv 安装脚本、macOS `.pkg` 交互安装、Windows 的 PowerShell 后台 WinGet 一键修复函数）。支持 3 次网络异常重试与退避保护。
- `core/dep_resolver.py` - **依赖拓扑解析引擎**。构建完整依赖图（requires/required_by），并自动创建幽灵依赖包条目，针对同名多重路径依赖进行树重构与就近路由。
- `core/network_proxy.py` - **代理路由与注入层**。提供 `urlopen()` 自定义 opener 以及将全局代理配置注入子进程与内置 PTY 的逻辑。
- `core/winget_helpers.py` - **WinGet 本地化解析器与辅助工具**。实现针对 WinGet 命令行等宽输出表格的精准分割，完全免疫控制字符与进度条动画的干扰。
- `core/terminal/` - **真实 PTY 交互终端引擎**。支持跨平台（Windows `pywinpty` 与 Unix `pty`）的后端接入，底层集成 `pyte` 虚拟屏幕解析 ANSI 颜色。
  - **任务终态追踪 (File-based Markers)**: 采用临时状态标记文件 (`.done`) 物理检测机制，保证异步 PTY 任务完成后 100% 触发 UI 刷新回调。
- `core/pypi_cache.py` - **PyPI 缓存层**。负责离线搜索索引，确保 `AddPackageDialog` 快速无网查询。

### /managers - 业务逻辑执行引擎
- `managers/pip_manager.py`、`managers/npm_manager.py` & `managers/winget_manager.py` - 子系统特定业务实现。提供异步扫描、命令生成与 Worker 通信。
  - `pip_manager.py` 支持 user site-packages 的双路径并发扫描、无管理员特权 Fallback 降级，以及 **虚拟环境升级文件锁冲突防御**（检测 `python.exe` 锁定并抛出精准提示）。
  - `winget_manager.py` 实现了包管理器自身（App Installer）升级检测、经典 Win32 软件智能去重、系统受保护应用（不可卸载）识别，以及 UWP 备置（Staged）应用的离线发现与提取。
- `managers/base_worker.py` - **共享 Worker 核心**。封装 QThread 的通用逻辑，处理 stdout/stderr 流拦截、ANSI 染色解析和进度状态上报。

### /ui - 图形界面组件

#### /ui/panels - 宏观面板
- `ui/panels/base_panel.py` - **极其神圣的界面基类**。负责渲染双栏布局，提供标准工具栏。支持 `_clear_env_card_widgets` 并保留常驻的缺失运行环境引导组件。
- `ui/panels/pip_panel.py`、`ui/panels/npm_panel.py` & `ui/panels/winget_panel.py` - 业务面板。负责环境卡片容器渲染、`QFileSystemWatcher` 目录变更自动刷新联动，以及集成了 `RuntimeSetupWidget` 缺失环境引导。
- `ui/panels/settings_dialog.py` - 统一设置页，用于管理 `uv`、离线缓存和 HTTP/HTTPS 代理。

#### /ui/widgets - 颗粒化卡片
- `ui/widgets/pip_env_card.py`、`ui/widgets/npm_env_card.py` & `ui/widgets/winget_env_card.py` - 镜像化的环境管理卡片。
- `ui/widgets/package_card.py` - 通用包条目。提供多通道选择、Outdated 警告与 Constraint 约束状态显示。
- `ui/widgets/terminal_panel.py` - **真实 PTY 交互终端组件 (`RealTerminalPanel`)**。支持全按键劫持，可由主程序根据设置进行热切换。
- `ui/widgets/runtime_setup_widget.py` - **缺失环境引导组件 (`RuntimeSetupWidget`)**。用于无环境可用时自动渲染并提供一键式引导安装入口。

---

## 3. UI 交互一致性标准

1. **标准过滤器 (Standard Filters)**：Search 过滤与 Outdated 过滤行为在各面板层面对齐。
2. **环境管理 (Environment Management)**：
   - **快速入口与多通道导入**: 底部常驻“➕ Add Environment”按钮，支持文件夹选择、文件选择、手动输入与 Batch Paste 批量路径粘贴。
   - **主界面拖拽排序 (UI Drag-and-Drop)**: 环境卡片支持鼠标拖动重新排序，指示线渲染，并同步更新配置文件。
   - **右键快速管理 (重命名/编辑)**: 卡片 Header 提供右键上下文菜单，支持快速重命名、定位并编辑设置与一键删除。
3. **批量操作 (Batch Operations)**：统一提供一键批量更新 Outdated 包的交互。
4. **运行时更新 (Runtime Update)**：包更新与运行时更新按钮（`Py`/`Nd`/`Wg`）严格解耦、并行存在。

---

## 4. 面向 AI 的修改范式 (For AI Assistant)

- 所有的包管理器查版本等 IO 密集行为**严禁阻塞主线程**，必须通过 `BaseWorker` 异步派生。
- 修改 NPM 相关逻辑时，优先检查 Pip 侧是否已有类似实现，并尽量复用或抽象。
- `Package` 对象的 `has_update` 属性是控制 UI 高亮和过滤的唯一事实来源。
- 保证配置文件的落盘原子性，任何修改配置落盘的行为必须遵循 `ConfigManager` 的双缓冲原子写盘策略。
