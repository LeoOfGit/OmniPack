<img src="./resources/OmniPack.png" alt="OmniPack Hero Banner" height="120" /> 

# OmniPack - 开发者包管理工具

[English](./README.md) | [简体中文](./README.zh-CN.md)

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?logo=python)
![Node.js](https://img.shields.io/badge/Node.js-NPM-green.svg?logo=nodedotjs)
![PySide6](https://img.shields.io/badge/UI-PySide6-brightgreen.svg?logo=qt)
![License](https://img.shields.io/badge/License-GPLv3-blue.svg)

*专注于开发者所需的**隔离环境管家**。*
> **OmniPack 是一款专为 Python (uv/pip) 和 Node.js (npm) 设计的高性能图形化管理工具。** 旨在帮助开发者更直观地管控本地散乱的虚拟环境，深度透视依赖树，并显著提升包管理效率。
---
![OmniPack Node.js View](./resources/Node.js.png)

## 💡 为什么需要 OmniPack？

在市面上，我们已经有了像 UniGetUI 这样优秀的全局应用商店，也有了原生的强大命令行工具（如 `pip` 和 `npm`）。**那么，OmniPack 解决的是什么痛点？**

如果你是一名资深开发者，你的磁盘上肯定散落着**数十个**包含 `.venv` 或 `node_modules` 的历史项目文件夹。
- 每次想要检查或更新某个项目的依赖，你都需要经历：找路径 -> 打开终端 -> `cd` -> `activate` -> 敲击冗长的命令... 
- 当你面对一份数百行的 `pip list` 扁平报错列表时，你根本不知道到底是**哪个顶层依赖**引入了这个该死的冲突版本。

OmniPack 就是为此而生：**它不是系统应用商店，它是你在工程代码海洋中的环境隔离微观管家。**

---

## ✨ 核心特性

### 🚀 极速驱动层：原生的 `uv` 力量
不仅快，而且是在 GUI 下的快！OmniPack 底层深度整合了 [Astral sh](https://github.com/astral-sh/uv) 备受赞誉的 `uv` 引擎。享受比传统 pip 快一个量级的下载与解析速度。

### 🌳 洞若观火：层级依赖树透视
摆脱命令行的扁平列表黑盒。
- **Top-Level 视图**：过滤干扰，还原你真实手动安装的依赖树。
- **无限层级展开**：谁拉取了谁？一目了然。
- **幽灵依赖 (Ghost Deps) 捕获**：帮你智能抓取代码中调用了却没正式声明的“幽灵”库。

![OmniPack Python View](./resources/Python.png)

### 🗂️ 零摩擦纳管：一键批量导入项目环境
我们知道你有几十个项目。你只需要在 Everything 或文件管理器里全选这些文件夹，**Ctrl+C 复制路径**，然后到 OmniPack 中**一键大批量粘贴**（Batch Import）。它的内核探测器会自动替你扒开所有的 `.venv`，只提取出干净的项目代号。

![OmniPack Batch Import](./resources/Settings-Environments.png)

### 🎯 极致的 Node.js 版本掌控
不止于 `npm install`。OmniPack 会动态拉取云端模块的 **Dist-Tags**，让你能在 `latest`, `beta`, `rc` 等分支通道间进行秒级下拉切换与预览。

![OmniPack Dependency Tree](./resources/SelectTag.png)

### 🧭 运行时补丁感知与更新
OmniPack 现在明确区分了**包更新**与**运行时更新**：
- **版本显示更准确**：环境卡片会显示 Python/Node 运行时版本；Python 虚拟环境优先读取 `pyvenv.cfg` 元数据，避免系统解释器补丁升级后“误跟随”。
- **同周期补丁检测**：针对 Python（如 `3.14.x`）和 Node（如 `25.x`）检测同一周期的最新补丁版本，并在卡片上直接显示 `当前 -> 最新`。
- **独立更新入口**：运行时更新使用单独按钮（`Py` / `Nd`），而 `⇧` 仍然只负责**包更新**。

### ⚡ 编译级性能：跨平台原生丝滑体验
采用 PySide6 构建，并支持通过 [Nuitka](https://nuitka.net/) 编译为 C++ 级别的原生单一可执行文件（`.exe` / ELF binary）。它不仅具有极速响应，更能一键切换镜像源。

![OmniPack Settings Sources](./resources/Settings-Sources.png)

---

## 🚀 快速上手 (Quick Start)

### 方法 1：下载免安装便携版 (推荐)
前往 Github Releases 区域获取最新构建的单文件包（支持 Windows/Linux/macOS）。下载后双击即可运行，你的配置和操作数据均会自动记录，环境会随你而走。

### 方法 2：源码运行
1. 确保已安装 Python 3.10+
2. 克隆仓库并安装依赖：
   ```bash
   git clone https://github.com/LeoOfGit/OmniPack.git
   cd OmniPack
   pip install -r requirements.txt
   ```
3. 运行程序：
   ```bash
   python OmniPack.pyw
   ```

---

## 📚 详细文档与指南

- 使用中的疑问？快捷键？高级特性？ 👉 [**《OmniPack 用户指南 (UserGuide)》**](./docs/UserGuide.zh-CN.md)
- 关于底层 `QThread` 同步逻辑与配置落盘细节？ 👉 [**《OmniPack 架构说明 (Architecture)》**](./docs/Architecture.zh-CN.md)

---

## 🤝 参与贡献

**OmniPack 旨在成为最优雅的跨语言开发者包管理中心。**
得益于高度解耦的 `Panel <-> Manager` 双层架构，即便您只有极少的 UI 经验，您也可以通过阅读 [Architecture.zh-CN.md](./docs/Architecture.zh-CN.md)，快速地编写一个 Backend，将 **Rust (Cargo)、Go、Ruby (Gems)** 等更多包管理器轻松接入！

欢迎提交 Issues 或者是 Pull Requests，让我们共同改进这款工具！

---

## 📄 许可证
本项目采用 [GPL v3.0 License](./LICENSE) 授权。
