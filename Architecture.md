# OmniPack 架构与开发指南 (Architecture & AI Dev Guide)

本文档是一份详尽的系统架构说明。**如果你是正在协助人类开发者的 AI 编程助手**，在进行任何代码重构或功能添加之前，请**务必仔细阅读本文件**，以理解项目的核心设计哲学和代码边界。

## 1. 核心设计原则

1. **薄窗口模式 (Thin Shell)**：主程序 `OmniPack.pyw` 仅作为最高层容器，处理标签页切换、UI 主题、以及全局状态恢复（如窗口几何尺寸、分割线比例）。它绝不能包含特定包管理器的业务逻辑。
2. **基类统一 UI (BasePanel Inheritance)**：所有的包管理器面板（如 Pip 面板、Npm 面板）都必须继承自 `ui/panels/base_panel.py`。这保证了左右分割比例、最小宽度边界、以及共享结构的工具栏/控制台在整个软件视觉和物理层面上的绝对一致性。
3. **隔离解耦 (Decoupled Logic)**：`ui/` 下的代码只负责视觉、事件绑定和信号分发；底层的命令执行、终端输出解析全部交给 `managers/` 下的对应类，两者通过 **Qt Signals/Slots** 异步通信，从而保证主 GUI 线程永远不被阻断或卡死。
4. **配置驱动 (Config-Driven)**：一切受控环境（如零散的 venv 路径）和应用清单（指定的 npm 核心工具）都以 `omnipack_config.json` 为单一事实来源 (Single Source of Truth)，通过 `core/config.py` 管理并在启动时加载。**在 v3 架构中，配置被强制要求与可执行文件同级存放以实现完全便携化。**

---

## 2. 完整目录结构与职责说明

本项目采用清晰的代码分层，以下为所有 `.py/.pyw` 文件的详细作用：

### 根目录
- `OmniPack.pyw` - **进程薄外壳 (Thin Shell)**。负责 Windows 管理员权限提升、全局未捕获异常拦截（弹窗提示）以及应用程序的极简启动引导。在打包模式下，它会自动适配 Nuitka 的 UAC 清单。
- `build_exe.py` - **高性能构建脚本**。基于 Nuitka 架构，集成了 Zig 编译器后端，负责将项目编译为无需 Python 环境的 C++ 原生 Portable 目录，并处理清理与目录重命名逻辑。
- `clean_cache.py` - **独立运维脚本**。用于快速清理 Python 缓存及工具留存数据。

### /core - 数据模型与基础抽象
处理与 UI 毫无相干的底层数据结构模型、环境抽象与 JSON 持久化逻辑。
- `core/config.py` - 全局配置管理器 `ConfigManager`。具备**目录自动创建**与**异常日志回退**机制，确保在各种文件权限环境下配置保存的鲁棒性。
- `core/manager_base.py` - 提供高度抽象的环境（`Environment`）和基础包状态（`Package` 基类）等协议级抽象。
- `core/models.py` - 包管理器的进一步数据类定义支持。
- `core/dep_resolver.py` - **拓扑依赖解析引擎**。核心资产。通过子进程在目标环境中运行 `importlib.metadata` 扫描，构建 `{requires, required_by}` 双向图。支持合并多重版本约束，并精准识别 Top-level 包。
- `core/utils.py` - **便携化工具集**。包含 `get_persistent_root()` 核心逻辑，通过对 `sys.frozen` 和 `sys.executable` 的多重校验，确保程序在打包/单文件模式下依然能精准定位原始 EXE 物理路径，彻底解决临时文件夹路径漂移问题。

### /managers - 业务逻辑执行引擎
直接应对各自底层子系统或命令行的“脏活累活”，对接上游抛出符合 PyQt 事件协议的结构化数据信号。
- `managers/pip_manager.py` - **Pip / uv 核心引擎**。负责定位底层指令，扫描所有虚拟环境目录内配置的 `python` 工具，获取包更新列表 `list --outdated`，并采用极度提升性能的后台队列执行拆解安装和更新逻辑。
- `managers/npm_manager.py` - **Node/Npm 核心引擎**。支持 **Corepack** 自动感应。除了 `dist-tags` API 发现外，v3 引入了 **局部刷新 (Partial Update)** 机制，允许仅针对特定应用触发版本检查，显著优化性能。

### /ui - 图形界面组件
所有的 PySide6 图形构建集结点，按“主窗体”、“面板”和“细粒度卡片”分级。
- `ui/main_window.py` - **界面司令部 (Top-Level Coordinator)**。继承自 `QMainWindow`，作为 `QStackedWidget` 的宿主，负责全局 Panel 调度、Tab 切换、状态栏同步、主题应用及窗口状态/分割线比例的持久化。

#### /ui/panels - 宏观重型面板模块
宏观页面级容器组件，通常是一个标签页内部占据全部区域的大部件。
- `ui/panels/base_panel.py` - **极其神圣的统一界面基类**！定义了左侧容器列表工作流、右侧全高度日志打印区的逻辑，禁用并锁定了两者的拖拉折叠避免 Bug。后续任何新增工具（如 WinGetPanel）开发**都必须必须** 继承它。
- `ui/panels/pip_panel.py` - 继承于上面基类的 Python 包管理总视图栏，负责绑定 Python 工具独有特征配置，实例化列表区内的所有 `EnvCard` 和处理依赖关系过滤升级。
- `ui/panels/npm_panel.py` - 继承于上面基类搭建的 Npm 侧管理总视图栏。v3 新增了 `_rebuild_single_card()` 逻辑，实现对单个应用卡片的动态销毁与重构，响应局部刷新信号。
- `ui/panels/npm_app_edit_dialog.py` - **高级处理组件表单**。负责 NPM 全局包展示名 (`Display Name`)、动态通道 (`Channel`) 配置和正则解析拆解工具。
- `ui/panels/settings_dialog.py` - 全局设置总窗口。主要负责用户在此手持维护本机的各种 Python 配置，或是扫描导入其想托管监控隔离环境目录等。

#### /ui/widgets - 轻量复用卡块片
在重型面板的 Scroll 区中大量实例化的颗粒组件。
- `ui/widgets/console_panel.py` - 全应用右半边的伪终端文本框容器（嵌入在基类中），负责响应信号流并且提供了 ANSI 式的高亮染色标记规则（`system`, `success`, `error`, `divider`）。
- `ui/widgets/env_card.py` - 专属 Python 面板。重构为**层级树容器**。支持按需懒加载 Top-level 包。具备“环境聚焦搜索”逻辑：仅在展开状态下启动深度递归路径搜索，平衡性能与体验。
- `ui/widgets/package_card.py` - **递归树节点**。支持 `expand_sync()` 同步展开逻辑。集成了版本约束检测、幽灵依赖 (Ghost) 样式提示及跨实例 Checkbox 状态同步。
- `ui/widgets/npm_app_card.py` - 渲染于 `Npm 面板` 列表中的 NPM 工具项记录卡，集成了多频道智能展示文字色，并拥有能够快捷点出操作弹窗的入口按钮。

---

## 3. 面向 AI 的架构特性引导与修改范式 (For AI Assistant)

### 3.1 跨环境路径持久化准则
在任何涉及文件读写的逻辑中，严禁直接使用 `os.getcwd()` 或简单的 `Path(__file__)`。
- **必须调用** `core.utils.get_persistent_root()` 来获取持久化存储路径。
- **必须调用** `core.utils.get_app_root()` 来获取内置资源（图标、样式）路径。
这是确保程序在 Nuitka 打包后不崩溃、配置不丢失的唯一红线。

### 3.2 高性能刷新范式
当数据模型变更时，优先考虑 **局部更新 (Partial Update)** 而非全局 `rebuild_list`。
- `NpmManager.updates_checked` 信号现在携带 `checked_app_names` 列表。
- `NpmPanel` 应通过 `_rebuild_single_card(name)` 仅操作受影响的小部件，以保持 UI 响应性能。

### 3.3 状态收集与底层日志上报的正确做法
所有的操作均设计为在后台队列的守护模式通过 `threading.Thread` 或 `subprocess.Popen` 完成非阻塞处理。
- 绝不能在 `Manager` 类体系代码里直接做类似于 `self.label.setText()` 这种跨线程违规行为。
- **最佳范式**: `managers/` 内均使用 `PySide6.QtCore.Signal` 构建消息抛发。这些回调抛出被 `BasePanel` 的核心系统里的 `self._log()` 直接绑定截获，并在安全的 GUI 主循环中刷新至 `console_panel`。

---

## 4. 故障排除与核心运维 (Troubleshooting & Maintenance)

### 4.5 Nuitka 编译与 Python 3.13 兼容性
- **问题**：在 Python 3.13 环境下使用 Nuitka 编译，默认的 MinGW64 编译器可能会因 Python 内部结构变动而报错。
- **解决**：在 `build_exe.py` 中强制指定使用 `--zig` 编译器后端。Zig 能够更好地适配 3.13 的 C-API 变更，确保编译通过并生成稳定的原生代码。

### 4.6 打包模式下的 UAC 冲突
- **问题**：打包为 EXE 后，如果内部脚本又执行了一次 `ShellExecuteW("runas", ...)`，可能会导致新进程失去 Nuitka 设置的环境变量，从而导致路径识别退化到 Temp 目录。
- **解决**：在 `OmniPack.pyw` 入口中，检测到 `sys.frozen` 状态时，应跳过手动提权逻辑，完全交由构建时嵌入的 UAC Manifest 处理。

---

**OmniPack 旨在成为最优雅的跨语言包管理中心。阅读完本指南后，你应该已经掌握了如何安全地扩展它的能力。**
