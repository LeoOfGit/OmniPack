<img src="./resources/OmniPack.png" alt="OmniPack Hero Banner" height="120" /> 

# OmniPack - 开发者包管理工具

[English](./README.md) | [简体中文](./README.zh-CN.md)

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?logo=python)
![Node.js](https://img.shields.io/badge/Node.js-NPM-green.svg?logo=nodedotjs)
![WinGet](https://img.shields.io/badge/WinGet-Windows-blue.svg?logo=windows)
![PySide6](https://img.shields.io/badge/UI-PySide6-brightgreen.svg?logo=qt)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
![Nuitka](https://img.shields.io/badge/Compiler-Nuitka-blue?logo=python)
![License](https://img.shields.io/badge/License-GPLv3-blue.svg)
[![DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/LeoOfGit/OmniPack)

*专注于开发者所需的**隔离环境与系统包管理管家**。*
> **OmniPack 是一款专为 Python (uv/pip)、Node.js (npm) 以及 Windows 系统包管理器 (WinGet) 设计的高性能图形化管理工具。** 旨在帮助开发者更直观地管控本地散乱的虚拟环境、深度透视依赖树，并在 Windows 下统一纳管系统应用，显著提升包管理效率。

---
![OmniPack Node.js View](./resources/Node.js.png)

## 💡 为什么需要 OmniPack？

在市面上，我们已经有了像 UniGetUI 这样优秀的全局应用商店，也有了原生的强大命令行工具（如 `pip`、`npm`、`winget`）。**那么，OmniPack 解决的是什么痛点？**

如果你名下有很多项目，你的磁盘上肯定散落着**数十个**包含 `.venv` 或 `node_modules` 的历史项目文件夹。
- 每次想要检查或更新某个项目的依赖，你都需要经历：找路径 -> 打开终端 -> `cd` -> `activate` -> 敲击冗长的命令... 
- 当你面对一份数百行的 `pip list` 扁平报错列表时，你根本不知道到底是**哪个顶层依赖**引入了这个该死的冲突版本。

OmniPack 就是为此而生：**它不是系统应用商店，它是你在工程代码海洋中的环境隔离微观管家。**

---

## ✨ 核心特性

### 🖥️ 内置交互式 PTY 终端
彻底告别只能看、不能动、甚至会因为交互性提问导致死锁的“模拟控制台”！OmniPack 将真正的伪终端 (PTY) 引擎直接整合到了 UI 界面中：
- **真正的 PTY 伪终端**：Windows 系统下通过 Nuitka 智能引入轻量级 `pywinpty`，编译体积增量极小；macOS / Linux 系统下直接调用 Python 原生标准库 `pty` 与 `os.fork()`，实现 **0 MB 额外体积开销** 的完美跨平台共享。
- **高色彩 ANSI 与动态进度条**：流式数据由轻量级色彩流解析库 `pyte` 强力驱动，完美支持终端 ANSI 转义字符序列的色彩染色（提供 VS Code 暗色调色盘），并且能完美流式呈现 `uv`、`pip`、`npm` 等包管理器的**动态字符进度条**。
- **静默环境同步与操作 Marker 拦截**：左侧环境卡片与工作目录变化时，主程序可无感地向 PTY 管道发送静默指令，在终端中实现自动 `cd` 切换目录和 `activate` 激活 venv。执行包安装、更新或卸载时，主程序将 CLI 语句写进终端执行，并通过唯一的 UUID 标记（Marker）进行结果过滤与成功捕获，结束后自动触发 UI 的**增量快速刷新 (Fast Refresh)**，响应极为迅速。
- **多壳程序支持与高度自定义**：可在设置页面中自主配置控制台默认的 Shell 解释器（内置 `cmd.exe`、`powershell.exe`、`pwsh.exe`，并支持指向任意自定义外部终端程序绝对路径），随时热切换只读模拟控制台（Simulated）与真实交互伪终端（Real Terminal）模式。

### 🐧 跨平台运行环境安装与 WinGet 自愈
OmniPack 实现了跨 Windows、macOS 和 Linux 系统的运行时环境自愈与全自动部署：
- **macOS 与 Linux 一键配置**：当本地缺失 Python/Node.js 运行时环境，Linux 下程序可自动使用极速 Python 工具 `uv` 进行自动安装，Node.js 则通过拉取二进制包解压并全自动创建软链接到本地 bin 路径；macOS (Darwin) 下可自动获取官方 `.pkg` 安装包并以 `open -W` 流式拉起系统图形安装器并等待完成。
- **WinGet 系统级智能修复 (Windows)**：若 Windows 系统没有安装 WinGet 客户端，OmniPack 可在后台借助 PowerShell 异步从 GitHub 获取官方最新 `.msixbundle` 安装包，并连同其必需的 `VCLibs` 与 `UI.Xaml` 系统依赖一并下载并安装，支持全局网络代理。
- **高可用网络 API**：运行时索引拉取重构，引入 3 次异常重试与退避机制，有效抵御网络波动。

### ⛑️ 安全更新智能：约束感知与安全中间版本推荐
OmniPack 能智能评估每个更新的安全性，并引导用户进行风险最小化的升级。
- **安全中间版本推荐 (Safe Update)**：当包的最新版本违反依赖约束时，OmniPack 会自动搜索版本历史，找到约束范围内的最高可用版本。受限但可安全升级的包将以**蓝色**高亮显示，并允许一键升级到该中间版本。
- **约束感知深度透视**：开启 "Outdated" 过滤时，若某个包完全没有可用的安全更新路径，该包将不会被自动选中，同时显示橙色 `⚠` 图标。悬停提示会详细列出哪些上游包施加了具体版本限制。
- **实时文件系统联动 (Real-time Sync)**：内置目录监听引擎。无论你是在系统终端还是内置 PTY 中手动运行安装命令，UI 都会在操作完成后自动感应并刷新，确保状态始终实时同步。
- **构建变体识别**：自动识别 PEP 440 本地版本后缀（`+cu132` 等）。若更新将改变硬件构建类型（如 CUDA 切到 CPU），会显示蓝色 `🔀` 图标提醒。

### 🌳 洞若观火：层级依赖树透视
摆脱命令行的扁平列表黑盒。
- **Top-Level 视图**：过滤干扰，还原你真实手动安装的依赖树。
- **无限层级展开**：谁拉取了谁？一目了然。
- **幽灵依赖 (Ghost Deps) 捕获**：帮你智能抓取代码中调用了却没正式声明的“幽灵”库。

![OmniPack Python View](./resources/Python.png)

### 🪟 Windows 内置 WinGet 深度集成 (Windows 特有)
无需打开复杂的命令行或第三方应用商店，OmniPack 原生纳管 Windows 内置包管理器 **WinGet**：
- **统一的应用管理与 Scope 智能标记**：合并原本独立的 Machine 与 User 环境卡片为统一的环境卡片，通过审计物理安装路径智能标注 `[sys]`（系统级）与 `[user]`（用户级）标签，当双端同时存在时并列展示双重标记。
- **UWP/MSIX 备置包离线感知与一键重注册**：支持离线解析注册表与 WindowsApps 清单，感知系统已备置（Staged）但当前用户未注册的 UWP 应用，在 UI 中以 Missing 并标注 `[Staged]` 形式展现，并提供一键后台注册安装（Add-AppxPackage）。
- **不可移除包安全拦截与经典 Win32 智能去重 (ARP Deduplication)**：自动探测并拦截系统核心受保护应用（如 App Installer, Edge, Store 等）的卸载按钮，同时基于 GUID 与哈希去重逻辑，完美消除传统注册表别名产生的重复条目。
- **命令行等宽解析**：针对 WinGet 繁琐的控制台本地化表格输出，自研基于东亚宽字符宽度 padding 的等宽解析引擎，彻底解决空值列与列错位漂移的问题。
- **锁定更新 (Blocking Pin)**：原生支持 `winget pin` 指令。可在 UI 中一键对特定应用开启 Blocking Pin，卡片展示 `[Pinned]` 徽章并在全局 "Outdated" 时阻止自动勾选，保护系统特定工具版本。
- **智能 Scope 自动回退 (Scope Fallback)**：在升级或安装因目录占用、特权写入受阻时，后台自动 fallback 回退执行 `--scope user` 权限进行补救重试，最大程度保障部署成功。

### 🔒 虚拟环境文件锁冲突防御
- **占用锁精准诊断**：在通过 PipPanel 对 Python 虚拟环境执行 `python -m venv --upgrade` 升级时，一旦检测到由于 IDE、后台脚本或 OmniPack 自身锁定 `python.exe` 导致复制失败，将静默拦截原始错误流，提醒用户关闭占用程序后再试，避免虚拟环境被损坏。

### 🎨 运行环境引导界面
- **智能缺失引导**：当在 Pip 面板、Npm 面板或 WinGet 面板中未检测到任何可用的运行环境时，UI 底部会自动展现精美的“运行环境安装引导”卡片（`RuntimeSetupWidget`），引导用户一键自动下载安装最新的 Python, Node.js 或 WinGet 客户端。

### 🚀 极速驱动层：原生的 `uv` 力量
不仅快，而且是在 GUI 下的快！OmniPack 底层深度整合了 [Astral sh](https://github.com/astral-sh/uv) 备受赞誉的 `uv` 引擎。享受比传统 pip 快一个量级的下载与解析速度。

### 🛠️ 开发者体验与 UI 细节打磨
- **环境重命名与设置编辑**：右键点击环境卡片即可重命名或修改设置，支持高亮定位跳转。
- **WinGet 自身一键升级**：直接审计并一键在 PTY 控制台中升级 WinGet 本身。
- **一键批量导入项目环境**：支持在文件管理器或 Everything 中复制多个目录直接粘贴导入。
- **可复制对话框文本与包详情导出**：所有 QMessageBox 和对话框均支持选择复制；包配置框提供 `Copy Details` 按钮一键导出。
- **极致的 Node.js 版本掌控**：动态拉取云端 Dist-Tags 并在 latest、beta 等分支间快速切换。
- **编译级性能**：支持利用 Nuitka 编译为原生的单文件程序。

---

## 🚀 快速上手 (Quick Start)

### 方法 1：下载免安装便携版
前往 Github Releases 区域获取最新构建的单文件包（支持 Windows/Linux/macOS）。下载后双击即可运行，你的配置和操作数据均会自动记录，环境会随你而走。

### Method 2：源码运行
1. 确保已安装 Python 3.10+
2. 克隆仓库并安装依赖：
   ```bash
   git clone https://github.com/LeoOfGit/OmniPack.git
   cd OmniPack
   pip install -r requirements.txt
   ```
3. 运行程序：
   ```bash
   python OmniPack.py
   ```

---

## 📚 详细文档与指南

- 使用中的疑问？快捷键？高级特性？ 👉 [**《OmniPack 用户指南 (UserGuide)》**](./docs/UserGuide.zh-CN.md)
- 关于底层 `QThread` 同步逻辑与配置落盘细节？ 👉 [**《OmniPack 架构说明 (Architecture)》**](./docs/Architecture.zh-CN.md)
- 如何从源码编译为单文件可执行程序？ 👉 [**《OmniPack 编译指南 (Compile)》**](./docs/Compile.zh-CN.md)
- 想要通过交互式 AI 了解本项目？👉 [**《OmniPack DeepWiki》**](https://deepwiki.com/LeoOfGit/OmniPack)

---

## 🤝 参与贡献

**OmniPack 旨在成为最优雅的跨语言开发者包管理中心。**
得益于高度解耦的 `Panel <-> Manager` 双层架构，即便您只有极少的 UI 经验，您也可以通过阅读 [Architecture.zh-CN.md](./docs/Architecture.zh-CN.md)，快速地编写一个 Backend，将 **Rust (Cargo)、Go、Ruby (Gems)** 等更多包管理器轻松接入！

欢迎提交 Issues 或者是 Pull Requests，让我们共同改进这款工具！

---

## 📄 许可证
本项目采用 [GPL v3.0 License](./LICENSE) 授权。
