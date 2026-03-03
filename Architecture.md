# OmniPack 架构与开发指南 (Architecture & AI Dev Guide)

本文档是一份详尽的系统架构说明。**如果你是正在协助人类开发者的 AI 编程助手**，在进行任何代码重构或功能添加之前，请**务必仔细阅读本文件**，以理解项目的核心设计哲学和代码边界。

## 1. 核心设计原则

1. **薄窗口模式 (Thin Shell)**：主程序 `OmniPack.pyw` 仅作为最高层容器，处理标签页切换、UI 主题、以及全局状态恢复（如窗口几何尺寸、分割线比例）。它绝不能包含特定包管理器的业务逻辑。
2. **基类统一 UI (BasePanel Inheritance)**：所有的包管理器面板（如 Pip 面板、Npm 面板）都必须继承自 `ui/panels/base_panel.py`。这保证了左右分割比例、最小宽度边界、以及共享结构的工具栏/控制台在整个软件视觉和物理层面上的绝对一致性。
3. **隔离解耦 (Decoupled Logic)**：`ui/` 下的代码只负责视觉、事件绑定和信号分发；底层的命令执行、终端输出解析全部交给 `managers/` 下的对应类，两者通过 **Qt Signals/Slots** 异步通信，从而保证主 GUI 线程永远不被阻断或卡死。
4. **配置驱动 (Config-Driven)**：一切受控环境（如零散的 venv 路径）和应用清单（指定的 npm 核心工具）都以 `omnipack_config.json` 为单一事实来源 (Single Source of Truth)，通过 `core/config.py` 管理并在启动时加载。

---

## 2. 完整目录结构与职责说明

本项目采用清晰的代码分层，以下为所有 `.py/.pyw` 文件的详细作用：

### 根目录
- `OmniPack.pyw` - **进程薄外壳 (Thin Shell)**。负责 Windows 管理员权限提升、全局未捕获异常拦截（弹窗提示）以及应用程序的极简启动引导。不包含任何具体 UI 逻辑。
- `clean_cache.py` - **独立运维脚本**。用于快速清理 Python 缓存及工具留存数据。

### /core - 数据模型与基础抽象
处理与 UI 毫无相干的底层数据结构模型、环境抽象与 JSON 持久化逻辑。
- `core/config.py` - 全局配置管理器 `ConfigManager`，利用 `dataclasses` 保障 JSON 持久化的结构化和强类型安全。同时维护了界面留存的最后一次打开页面位置 (current_tab) 和相关组件尺寸状态。
- `core/manager_base.py` - 提供高度抽象的环境（`Environment`）和基础包状态（`Package` 基类）等协议级抽象。
- `core/models.py` - 包管理器的进一步数据类定义支持。
- `core/dep_resolver.py` - **拓扑依赖解析引擎**。核心资产。通过子进程在目标环境中运行 `importlib.metadata` 扫描，构建 `{requires, required_by}` 双向图。支持合并多重版本约束，并精准识别 Top-level 包。
- `core/utils.py` - 包含通用系统辅助函数，如通过系统注册表与路径扫描来快速探测系统内的基础 Python 及虚拟执行入口的环境探测等。

### /managers - 业务逻辑执行引擎
直接应对各自底层子系统或命令行的“脏活累活”，对接上游抛出符合 PyQt 事件协议的结构化数据信号。
- `managers/pip_manager.py` - **Pip / uv 核心引擎**。负责定位底层指令，扫描所有虚拟环境目录内配置的 `python` 工具，获取包更新列表 `list --outdated`，并采用极度提升性能的后台队列执行拆解安装和更新逻辑。
- `managers/npm_manager.py` - **Node/Npm 核心引擎**。负责调用 `npm list -g --json` 获取包配置详细清单。并在获取信息后能够通过 `dist-tags` API 获取如 (`beta`, `next`, `rc`) 等最新更新通道的分支信息。

### /ui - 图形界面组件
所有的 PySide6 图形构建集结点，按“主窗体”、“面板”和“细粒度卡片”分级。
- `ui/main_window.py` - **界面司令部 (Top-Level Coordinator)**。继承自 `QMainWindow`，作为 `QStackedWidget` 的宿主，负责全局 Panel 调度、Tab 切换、状态栏同步、主题应用及窗口状态/分割线比例的持久化。

#### /ui/panels - 宏观重型面板模块
宏观页面级容器组件，通常是一个标签页内部占据全部区域的大部件。
- `ui/panels/base_panel.py` - **极其神圣的统一界面基类**！定义了左侧容器列表工作流、右侧全高度日志打印区的逻辑，禁用并锁定了两者的拖拉折叠避免 Bug。后续任何新增工具（如 WinGetPanel）开发**都必须必须** 继承它。
- `ui/panels/pip_panel.py` - 继承于上面基类的 Python 包管理总视图栏，负责绑定 Python 工具独有特征配置，实例化列表区内的所有 `EnvCard` 和处理依赖关系过滤升级。
- `ui/panels/npm_panel.py` - 继承于上面基类搭建的 Npm 侧管理总视图栏，负责渲染应用区的 `NpmAppCard` 及提供各类状态添加/批量覆盖交互入口。
- `ui/panels/npm_app_edit_dialog.py` - **高级处理组件表单**。负责 NPM 全局包展示名 (`Display Name`)、动态通道 (`Channel`) 配置和正则解析拆解工具。用户只需要将含特征指令如 (`npm i -g app@rc`) 输入文本框，它就会解析提取出依赖名自动激活对应通道选框并染色高亮。
- `ui/panels/settings_dialog.py` - 全局设置总窗口。主要负责用户在此手持维护本机的各种 Python 配置，或是扫描导入其想托管监控隔离环境目录等。

#### /ui/widgets - 轻量复用卡块片
在重型面板的 Scroll 区中大量实例化的颗粒组件。
- `ui/widgets/console_panel.py` - 全应用右半边的伪终端文本框容器（嵌入在基类中），负责响应信号流并且提供了 ANSI 式的高亮染色标记规则（`system`, `success`, `error`, `divider`）。
- `ui/widgets/env_card.py` - 专属 Python 面板。重构为**层级树容器**。支持按需懒加载 Top-level 包。具备“环境聚焦搜索”逻辑：仅在展开状态下启动深度递归路径搜索，平衡性能与体验。
- `ui/widgets/package_card.py` - **递归树节点**。支持 `expand_sync()` 同步展开逻辑。集成了版本约束检测、幽灵依赖 (Ghost) 样式提示及跨实例 Checkbox 状态同步。
- `ui/widgets/npm_app_card.py` - 渲染于 `Npm 面板` 列表中的 NPM 工具项记录卡，集成了多频道智能展示文字色，并拥有能够快捷点出操作弹窗的入口按钮。

---

## 3. 面向 AI 的架构特性引导与修改范式 (For AI Assistant)

### 3.1 状态收集与底层日志上报的正确做法
所有的操作均设计为在后台队列的守护模式通过 `threading.Thread` 或 `subprocess.Popen` 完成非阻塞处理。
- 绝不能在 `Manager` 类体系代码里直接做类似于 `self.label.setText()` 这种跨线程违规行为。
- **最佳范式**: `managers/` 内均使用 `PySide6.QtCore.Signal` 构建消息抛发。当进程捕获了 `stdout/stderr` 的数据片段时发出（比如抛出 `log_msg.emit("成功", "success")`）。这些回调抛出被 `BasePanel` 的核心系统里的 `self._log()` 直接绑定截获，并在安全的 GUI 主循环中刷新至 `console_panel`。

### 3.2 深度依赖 NPM 的 Channel 发现逻辑系统
多数常见工具对于 Npm 包只获取 `latest` 的比对更新。在本作里，`NpmManager.check_updates()` 会通过 `npm view [pkg] dist-tags --json` 深钻并捕获一个库完整的云端多路可用分支（如同时带有 `stable`, `canary`等）。
配置会动态通过 `npm_app_edit_dialog.py` 中选好并且变更。如果您在代码重构中涉及到 Npm 部分，**请您必须注意**这部分从获取 -> 选中 -> 保存高亮逻辑是本项目与其他应用相区的核心差异，请勿用简单比等逻辑覆盖掉！

### 3.3 创建新的包管理器指南 (以拓展 WinGet 集成为例)
由于采用了 `BasePanel` 收敛模型，系统扩展的健壮程度非常高并且拥有很强的范式复制规律：
1. **底层支持**：新建 `managers/winget_manager.py`。
    - 在抛出相同的基于 `action_done`、`log_msg` 的底层驱动。
2. **卡片定义**：新建 `ui/widgets/winget_card.py` 展示信息小部件，需要实现被主程序挂载或过滤的基本显示隐藏属性。
3. **视图面板**：新建 `ui/panels/winget_panel.py`。
    - 声明 `class WingetPanel(BasePanel):` 覆盖继承树。
    - 使用继承提供好的自带骨架，利用 `self.tb_layout.addWidget()` 对准左侧增加类似于 `WinGet` 的功能按钮，向 `self.scroll_layout` 里追加之前写的卡片列表组件。
    - 将 `winget_manager` 发出的标准日志信号直通给 `self._on_status_changed`/`self._log` 让右边界终端生效。
4. **注入入口激活**：在入口 `OmniPack.pyw` 增加几横行。
    - 将上述搭建出的面板通过 `.addWidget()` 添加至容器中。
    - 用左端菜单配置 `self._add_app_tab("WinGet 程序库", 2)` 追加页签激活通道。
    - 把此新加入面板内部自带的左右分屏器添加至顶层已经准备好的 `_sync_splitters` 双边映射处理机制逻辑下，搞定。

---

## 4. 故障排除与核心运维 (Troubleshooting & Maintenance)

在开发和使用过程中，如果遇到应用“无提示闪退”或无法启动，请参考以下已知问题及解决方法。

### 4.1 背景进程挂起导致冲突
- **现象**：修改代码后启动无反应，或日志显示端口/资源占用。
- **原因**：Windows 下使用 `pythonw.exe` 运行 GUI 应用时，如果程序因异常崩溃，父进程虽消失，但 `pythonw.exe` 子进程可能在后台挂起并锁定资源或配置文件。
- **解决**：在任务管理器中强制结束所有 `python.exe` 和 `pythonw.exe` 进程，然后重新启动。

### 4.2 PySide6 Layout 初始化引起的 SystemError
- **现象**：控制台报错 `SystemError: <class 'PySide6.QtWidgets.QVBoxLayout'> returned NULL without setting an exception`。
- **原因**：在 **Python 3.13/3.14+** 这种高性能、强约束的高版本环境下，对象创建机制（Reification）做了深度优化。使用 `layout = QVBoxLayout(self)` 这种 C++ 构造器语法在深层继承的 Widget 中会触发 **“对象初始化竞争”**。当 Python 层 `__init__` 尚未完成时，底层 C++ 绑定器（Shiboken）若无法即时获取完整的 C 引用，会直接抛出 NULL 指针。
- **解决**：采用 **“防御性初始化”** 写法，解耦 C++ 构造与父级绑定。**严禁**直接在构造函数中传入 `self`，必须写为：
  ```python
  layout = QVBoxLayout()
  self.setLayout(layout)
  ```

### 4.3 Qt 事件枚举命名空间错误
- **现象**：报错 `AttributeError: type object 'PySide6.QtCore.Qt' has no attribute 'ChildPolished'`。
- **原因**：在 **PySide6 6.10.2+** 等最新版中，为了代码纯正性，官方彻底移除了挂载在 `Qt` 命名空间下的旧版 Alias 枚举。
- **解决**：在拦截 `event()` 函数时，必须严格通过显式的 **`QEvent.Type`** 路径进行引用（如 `QEvent.Type.Polish`）。这是面向未来的现代化代码规范要求。

### 4.4 字节码缓存污染
- **现象**：修改了代码但运行结果不符合预期，或出现莫名的导入错误。
- **解决**：运行根目录下的 `clean_cache.py`。该脚本会递归清理所有 `__pycache__` 目录。项目维护者应在版本重大更新后习惯性运行此脚本。

---

**OmniPack 旨在成为最优雅的跨语言包管理中心。阅读完本指南后，你应该已经掌握了如何安全地扩展它的能力。**
