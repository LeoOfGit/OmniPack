# OmniPack - 开发者全能包管理器

OmniPack 是一款专为开发者设计的通用包管理桌面客户端。它不同于系统级的应用商店，而是深度聚焦于 **Python (pip/uv)** 环境隔离管理与 **Node.js (npm)** 全局工具的高效运维。

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![PySide6](https://img.shields.io/badge/UI-PySide6-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## 🌟 核心价值

在 UniGetUI 等大而全的包管理器盛行的今天，OmniPack 依然存在的意义：
- **深耕环境隔离**：专为管理多个 Python 虚拟环境（venv/conda）而生，而非仅仅管理系统全局环境。
- **极致引擎支持**：原生深度集成 [uv](https://github.com/astral-sh/uv)，提供比传统 pip 快一个量级的包安装与更新体验。
- **配置驱动清单**：只关注你主动维护的工具清单，拒绝信息过载，保持开发环境纯净。
- **细粒度版本控制**：支持 npm 通道（dist-tags）的精准切换（latest, beta, rc, next），直观预览不同分支的版本演进。

## ✨ 主要功能

- **Python (Pip/uv) 面板**:
  - **层级依赖树**: 自动解析并展示环境内包的拓扑依赖关系，支持无限层级展开。
  - **Top-level 视图**: 默认仅显示顶级包，有效过滤干扰，还原真实开发依赖。
  - **幽灵依赖 (Ghost Deps)**: 智能识别缺失的必选依赖，支持一键补充安装。
  - **智能同步勾选**: 跨层级同名包状态自动同步，选中时自动展开隐藏路径。
  - **环境聚焦搜索**: 支持带防抖的深度搜索，仅在专注的环境中自动展开匹配路径。
  - 利用 `uv` 引擎实现闪电般的响应速度。
  - 支持“仅显示过时包”与搜索筛选。
- **Node.js (Npm) 面板**:
  - 管理 npm 全局安装的应用程序。
  - 智能解析安装命令，自动识别作用域包与通道。

  - 动态获取远端所有可用 Dist-Tags 及其版本。
  - 支持显示名与描述的自定义配置。
- **通用功能**:
  - **实时控制台**：透明化输出命令执行过程，方便调试。
  - **状态持久化**：自动保存窗口几何尺寸、分割比例及最后使用的标签页。
  - **动态底栏**：实时汇总展示各面板的安装总数与待更新数。

## 🚀 快速开始

### 环境要求
- Windows 10/11
- Python 3.10+ (已针对 Python 3.14 进行深度兼容性加固)
- Node.js (如需使用 npm 管理功能)
- [uv](https://github.com/astral-sh/uv) (推荐，用于加速 Python 模块管理)

### 💡 常见问题 (Troubleshooting)
- **启动无反应**：如果双击 `OmniPack.pyw` 无反应，请尝试以管理员身份运行。
- **环境隔离**：更多关于底层架构与已知崩溃的解决方案，请参阅 [Architecture.md](./Architecture.md)。

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行
```bash
python OmniPack.pyw
```

## 🏗️ 项目架构

项目采用模块化设计，易于扩展更多包管理器（如 WinGet, Cargo 等）：
- **Core**: 统一的配置管理与基础数据模型。
- **UI Coordinator**: `ui/main_window.py` 负责全局调度与状态同步。
- **Managers**: 封装各包管理器的后端执行逻辑与信号传递。
- **UI Panels**: 基于继承体系（BasePanel）构建一致性界面。

