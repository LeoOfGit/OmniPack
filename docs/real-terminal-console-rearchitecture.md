# OmniPack 右侧控制台重构与真实 PTY 终端架构设计方案

## 1. 背景与核心决策

### 现状分析
当前 OmniPack 的右侧区域是一个**“模拟控制台”**（由 `ui/widgets/console_panel.py` 实现）。它本质上是一个被动的日志查看器（基于 `QTextEdit`），工作方式是：
1. 启动包管理子进程并重定向 `stdout` / `stderr`。
2. 在 Python 侧使用正则表达式过滤掉所有 ANSI 转义字符（丢失了彩色文字和动态进度条）。
3. 单向流式写入富文本框，且无法接收任何用户输入（如安装过程中的交互式确认 `y/n` 会直接导致死锁）。

### 核心决策：采用【方案 C（PTY 伪终端）】
经过多维度评估（包括打包体积、跨平台渲染速度、交互一致性、双向深度控制），我们决定采用**基于 PTY（Pseudo-Terminal）的伪终端引擎方案（即方案 C）**作为重构路线。

#### 为什么放弃方案 A（窗口跟随）与方案 B（窗口吞噬）？
*   **跨平台硬伤**：方案 A 和 B 在 Windows 下依赖大量的 `ctypes` 调用和 `Win32 API`，而在 macOS（由于沙箱与 Accessibility 权限限制）和现代 Linux（由于 Wayland 的强窗口隔离机制）上**几乎完全失效或无法被吞噬**。
*   **交互盲区**：主程序对外部终端窗口的字符输出是“失明”的，无法实现“检测到安装成功自动刷新包列表”等深度 UI 联动。

#### 方案 C（PTY 伪终端）的压倒性优势
1.  **极轻的体积增量**：
    *   **macOS / Linux**：完全免安装！直接使用 Python 原生的标准库 `import pty` 和 `os.fork()`，**0 MB 体积增量**。
    *   **Windows**：通过 Nuitka 编译时引入轻量级的 `pywinpty`（`winpty.dll` 的 C 语言封装），体积增量仅 **+2 ~ 5 MB**，相较于 Chromium 浏览器内核方案（100MB+）极为轻量。
2.  **完美的跨平台代码共享**：
    *   **90% 代码全平台共享**：前端 PyQt 终端渲染组件、键盘事件捕获、色彩解析器（如 `pyte` 库）100% 共享。
    *   **10% 底层分支**：仅通过一个简单的接口类，在 Windows 下调用 `pywinpty`，在类 Unix 系统下调用标准库 `pty`。
3.  **强大的双向交互能力**：
    *   **命令主动注入**：主程序可以在后台静默输入指令（例如自动切换目录、激活代理、自动执行安装）。
    *   **输出流实时监控**：流经的每一行文本都可以被正则扫描。可实时截获 `"Successfully installed"` 触发 UI 列表自动刷新，或拦截 `"Connection timed out"` 触发智能代理引导。
    *   **全互动支持**：支持 Tab 自动补全、方向键历史记录、`Ctrl+C` 中断任务、动态进度条以及密码隐形输入。

---

## 2. 架构设计

重构后的系统将遵循“高内聚、低耦合”的模块化设计，主要分为三层：**UI 渲染层**、**平台适配层**和**交互联动层**。

### 2.1 模块分层关系

```mermaid
graph TD
    subgraph UI 渲染层 (100% 跨平台共享)
        A[TerminalPanel QPlainTextEdit] -->|1. 捕获按键并编码| B(终端输入处理器)
        C[ANSI 染色器 pyte] -->|4. 转换富文本| A
    end

    subgraph 平台适配层 (抽象工厂隐藏差异)
        B -->|2. terminal.write| D[PtyBackend 抽象基类]
        D -->|Windows 适配器| E[WinPtyAdapter winpty]
        D -->|macOS/Linux 适配器| F[UnixPtyAdapter stdlib pty]
    end

    subgraph 进程执行与交互联动
        E -->|3. 读取标准输出| G(PtyOutputThread 后台读线程)
        F -->|3. 读取标准输出| G
        G -->|过滤/正则匹配| H(交互联动调度器)
        H -->|信号触发 UI 刷新| I[OmniPack 主界面]
        G -->|5. 发送 ANSI 原始数据流| C
    end
```

### 2.2 双入口并存设计（开发阶段）
为了保证重构期间系统的绝对稳定，我们采用**双入口设计（Dual-Entry Points）**。在开发和 Beta 测试阶段，新旧两种控制台同时存在，且可随时热切换。

#### 配置管理
在 `omnipack_config.json` 中引入新的配置项：
```json
{
  "console_mode": "simulated" 
}
```
*   `"simulated"`：传统日志式模拟控制台（当前实现，绝对稳定，用于保底）。
*   `"real_terminal"`：全新的 PTY 真实交互式终端。

#### UI 组件动态切换 (`BasePanel`)
`BasePanel` 不再写死引用 `ConsolePanel`，而是设计为一个动态容器（`QStackedWidget` 或动态载入）：
*   在初始化时，根据 `ConfigManager` 的值实例化对应的面板：
    ```python
    def setup_right_panel(self):
        mode = self.config_mgr.config.get("console_mode", "simulated")
        if mode == "real_terminal":
            self.console_widget = RealTerminalPanel(self)
        else:
            self.console_widget = LegacyConsolePanel(self)
        self.right_layout.addWidget(self.console_widget)
    ```

---

## 3. 核心组件详细实现设计

### 3.1 平台抽象适配器 (`core/terminal/backend.py`)
定义一个轻量级的 PTY 抽象接口：

```python
import os

class BasePtyBackend:
    """PTY 后端抽象基类"""
    def write(self, data: str):
        raise NotImplementedError
        
    def read(self, max_bytes: int = 4096) -> str:
        raise NotImplementedError
        
    def resize(self, cols: int, rows: int):
        raise NotImplementedError
        
    def is_alive(self) -> bool:
        raise NotImplementedError

# 根据不同平台动态加载具体实现
if os.name == 'nt':
    from winpty import PtyProcess
    class PtyBackendImpl(BasePtyBackend):
        def __init__(self, cmd="powershell.exe", env=None, cwd=None):
            self.pty = PtyProcess.spawn(cmd, env=env, cwd=cwd)
        def write(self, data): self.pty.write(data)
        def read(self, max_bytes=4096): return self.pty.read(max_bytes)
        def resize(self, cols, rows): self.pty.set_size(cols, rows)
        def is_alive(self): return self.pty.isalive()
else:
    import pty
    import termios
    import struct
    import fcntl
    class PtyBackendImpl(BasePtyBackend):
        def __init__(self, cmd="/bin/zsh", env=None, cwd=None):
            # 获取当前系统默认 Shell
            shell = os.environ.get("SHELL", "/bin/bash")
            self.pid, self.fd = pty.fork()
            if self.pid == 0:  # 子进程
                if cwd: os.chdir(cwd)
                # 合并环境变量后执行
                run_env = os.environ.copy()
                if env: run_env.update(env)
                os.execvpe(shell, [shell], run_env)
        def write(self, data): os.write(self.fd, data.encode('utf-8'))
        def read(self, max_bytes=4096): return os.read(self.fd, max_bytes).decode('utf-8', errors='ignore')
        def resize(self, cols, rows):
            size = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, size)
        def is_alive(self):
            try:
                pid, status = os.waitpid(self.pid, os.WNOHANG)
                return pid == 0
            except ChildProcessError:
                return False
```

### 3.2 键盘输入与 UI 渲染 (`ui/widgets/terminal_panel.py`)
`RealTerminalPanel` 继承自 `QPlainTextEdit`，核心职责为拦截键盘事件并写入 PTY，同时读取 PTY 流配合 ANSI 染色解析器进行局部渲染。

```python
from PySide6.QtWidgets import QPlainTextEdit
from PySide6.QtCore import Qt, Signal

class RealTerminalPanel(QPlainTextEdit):
    input_received = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursorWidth(2)
        self.ensureCursorVisible()
        # 初始化色彩渲染解析器 (如 pyte.Screen)
        # self.screen = pyte.HistoryScreen(80, 24)
        # self.stream = pyte.ByteStream(self.screen)

    def keyPressEvent(self, event):
        """核心捕获：用户打字不直接入屏，而是发给 PTY"""
        key = event.key()
        text = event.text()

        # 转换特殊功能键为 ANSI 转义序列
        if key == Qt.Key_Return or key == Qt.Key_Enter:
            self.input_received.emit("\r")
        elif key == Qt.Key_Backspace:
            self.input_received.emit("\x7f")  # Unix Backspace
        elif key == Qt.Key_Tab:
            self.input_received.emit("\t")
        elif key == Qt.Key_Up:
            self.input_received.emit("\x1b[A")
        elif key == Qt.Key_Down:
            self.input_received.emit("\x1b[B")
        elif key == Qt.Key_Left:
            self.input_received.emit("\x1b[D")
        elif key == Qt.Key_Right:
            self.input_received.emit("\x1b[C")
        elif event.modifiers() & Qt.ControlModifier and key == Qt.Key_C:
            self.input_received.emit("\x03")  # SIGINT (Ctrl+C)
        elif text:
            self.input_received.emit(text)
        else:
            super().keyPressEvent(event)
```

---

## 4. 双向交互与深度联动设计

伪终端数据流经 Python 侧，允许我们进行**实时的内容模式匹配与行为决策**。

### 场景一：包安装完后自动刷新包列表
*   **传统痛点**：用户在模拟控制台下无法知道 `pip install` 何时真正结束，必须等待后台线程的返回码。如果用户在终端手动敲击 `pip install xxx`，主程序完全不知道包已经变动。
*   **重构方案**：
    在读取 PTY 的流数据时，运行以下实时正则过滤：
    ```python
    # 模式匹配器
    if "Successfully installed" in stdout_line or "added" in stdout_line and "package" in stdout_line:
        # 说明无论是由主程序按钮触发，还是用户手动在终端中安装了新包
        # 立即发出信号通知左侧面板静默刷新包列表
        self.sig_refresh_package_list.emit()
    ```

### 场景二：静默目录同步 (cwd) 与环境切换
*   **设计细节**：当用户在左侧的环境卡片中切换了虚拟环境（例如从 `.venv` 切换到了全局环境，或者从 npm 项目 A 切换到项目 B），右侧的真实终端应当**自动、无感地同步切换环境与目录**。
*   **重构方案**：
    每当左侧环境卡片或工作目录变化，主程序静默向 PTY 管道发送对应的控制指令：
    *   Windows: `terminal.write("cd /d 'D:/project/A' \r")`
    *   Unix: `terminal.write("cd 'D:/project/A' && source .venv/bin/activate \r")`
    *   配合清除屏显缓存（Clear Screen），让用户觉得终端与主程序是浑然一体的。

---

## 5. 迁移路线与验证计划

为确保 OmniPack 在长期的迭代中始终保持高可用，我们制定如下渐进式开发与验证步骤：

```text
【Phase 1: 预留开关与配置】 (配置管理重构)
      │
      ▼
【Phase 2: 建立核心 PTY 适配器】 (Unix/Windows 驱动隔离)
      │
      ▼
【Phase 3: 编写 TerminalPanel 视图】 (键盘劫持与 ANSI 流解析)
      │
      ▼
【Phase 4: 实现双入口动态注入与测试】 (用户可自由在配置中切换)
      │
      ▼
【Phase 5: 真实场景测试与性能优化】 (高吞吐日志压力测试)
      │
      ▼
【Phase 6: 废弃并彻底砍掉旧模拟终端】 (当新版本趋于完美)
```

### 验证方法与性能指标

#### 1. 压力与吞吐测试
*   **验证方法**：在真实终端模式下，执行大规模的输出任务，如 `pip install torch`（伴随巨大的下载条刷新）或 `npm list -g`。
*   **指标**：
    *   UI 界面在连续高频重绘时不出现假死或卡顿（主线程帧率保持在 30fps 以上）。
    *   文本缓冲区自动丢弃历史记录（保留最近 2000 行），内存增加不超过 20MB。

#### 2. 交互完整性测试
*   验证在安装库时，输入 `Ctrl+C` 能否顺畅中止后台 `pip` 或 `npm` 的下载线程。
*   验证在 `git clone` 交互询问时，能否在终端内顺利输入用户名与密码。

#### 3. 跨平台适配测试
*   **Windows 10/11**：验证使用 Nuitka 编译打包为单个 `.exe` 时，`winpty.dll` 是否能被完美打包，免受杀毒软件误报。
*   **macOS / Linux**：验证在没有安装任何外部 C++ 依赖库的情况下，仅依赖标准库 `pty` 是否能完美调起系统自带 of `zsh` / `bash` 并完美染色。

---

## 6. 结论
放弃“打补丁式”的模拟控制台方案，转而拥抱**方案 C（PTY 伪终端）**，是 OmniPack 走向高品质、专业包管理工具的必经之路。这种架构既保留了 Python 极简的跨平台特性，又在性能和体验上直接对齐了 VS Code 等主流 IDE，同时保证了开发周期的平滑过渡，是风险最小、收益最大的选择。
