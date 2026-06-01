<img src="./resources/OmniPack.png" alt="OmniPack Hero Banner" height="120" /> 

# OmniPack - Developer Package Manager

[English](./README.md) | [简体中文](./README.zh-CN.md)

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?logo=python)
![Node.js](https://img.shields.io/badge/Node.js-NPM-green.svg?logo=nodedotjs)
![WinGet](https://img.shields.io/badge/WinGet-Windows-blue.svg?logo=windows)
![PySide6](https://img.shields.io/badge/UI-PySide6-brightgreen.svg?logo=qt)
![License](https://img.shields.io/badge/License-GPLv3-blue.svg)

*The ultimate **sandbox environment & system package manager** for modern developers.*
> **OmniPack is a high-performance GUI wrapper for Python (uv/pip), Node.js (npm), and Windows Package Manager (WinGet).** It helps you manage scattered virtualenvs, explore deep dependency trees, handle local packages, and seamlessly control system-wide applications with unprecedented visual efficiency.

---
![OmniPack Node.js View](./resources/Node.js.png)

## 💡 Why OmniPack?

There are already excellent global app stores like UniGetUI and powerful native CLI tools like `pip`, `npm`, and `winget`. **What pain power does OmniPack solve?**

If you're a seasoned developer, your disk is likely scattered with **dozens** of legacy project folders containing `.venv` or `node_modules`.
- Every time you want to check or update dependencies for a project, you have to find the path -> open terminal -> `cd` -> `activate` -> type long commands... 
- When facing a hundred-line flat `pip list` error, you have no easy way to know which **top-level dependency** introduced that conflicting version.

OmniPack was born for this: **It's not a system app store; it's your environment isolation micro-manager in a sea of engineering code.**

---

## ✨ Core Features

### 🖥️ Built-in Interactive PTY Terminal (New in v10)
Say goodbye to the "blind" read-only simulated console! OmniPack v10 features a full-fledged Pseudo-Terminal (PTY) engine integrated directly into the UI:
- **True PTY Integration**: Uses `pywinpty` on Windows and native `pty`/`os.fork()` on macOS/Linux to run real interactive shells with 0 MB size overhead.
- **Rich ANSI Capabilities**: Streamed output is parsed by the lightweight `pyte` library, supporting full ANSI color palette mapping and dynamic progress bars (e.g. `uv` / `pip` / `npm` downloads).
- **Silent Synchronization & Marker Interceptor**: Changing environments or working directories on the left instantly and silently switches directories (`cd`) or activates virtualenvs in the terminal. When performing package actions, OmniPack writes CLI commands to the terminal and monitors operation success via a unique UUID marker, triggering an incremental **Fast Refresh** on completion.
- **Highly Customizable**: Choose your preferred default shell (`cmd.exe`, `powershell.exe`, `pwsh.exe`, or custom shell binaries) and switch console modes instantly under the new Terminal settings tab.

### 🚀 High-Speed Engine: Native `uv` Power
It's not just fast; it’s fast even in a GUI! OmniPack natively integrates [Astral sh](https://github.com/astral-sh/uv)'s acclaimed `uv` engine. Enjoy order-of-magnitude faster downloads and resolution compared to traditional pip.

### 🌳 Crystal Clear: Hierarchical Dependency Tree
Break free from the command-line’s flat list black box.
- **Top-Level View**: Filters out noise and reveals the dependency tree you actually manually installed.
- **Infinite Hierarchy**: Who pulled in what? It’s clear at a glance.
- **Ghost Deps Capture**: Automatically identifies libraries called in your code but never officially declared.

![OmniPack Python View](./resources/Python.png)

### 🗂️ Zero-Friction Management: Batch Environment Import
We know you have dozens of projects. Just select those folders in [Everything] or File Explorer, **Ctrl+C to copy paths**, and **Batch Paste** them into OmniPack with one click. Its detection engine automatically strips away `.venv` noise to extract clean project names.

![OmniPack Batch Import](./resources/Settings-Environments.png)

### 🎯 Ultimate Node.js Version Control
More than just `npm install`. OmniPack dynamically pulls **Dist-Tags** from the cloud, allowing second-level switching and previewing between channels like `latest`, `beta`, or `rc`.

![OmniPack Dependency Tree](./resources/SelectTag.png)

### 🪟 Windows Native WinGet Deep Integration (Windows Only)
No need to launch a convoluted CLI or a cluttered third-party app store. OmniPack natively manages the built-in Windows Package Manager **WinGet**:
- **Dual-Scope Scanning**: Separates system-wide global software (Machine scope) from user-specific software (User scope) for comprehensive app detection.
- **Smart Path Redistribution & De-duplication**: Automatically parses Windows registry and audits physical install paths (e.g. `%USERPROFILE%`). User-installed apps are intelligently relocated from Machine to User scopes to eliminate overlap; double-installed apps display a `[Also Installed In User/Machine]` badge.
- **Fixed-Width Column Slicing Console Parser**: Built with an East-Asian character-rendering width-padding calculation engine, making the table parser completely immune to column merging, empty values, or language-specific localized formatting.
- **Ignore Updates with Blocking Pin**: Integrated with the native `winget pin` command. Toggle Blocking Pins on specific apps via a ⚙ button, showing a `[Pinned]` badge, and automatically skipping updates in the global "Outdated" filter.
- **Intelligent Scope Fallback**: If an install or upgrade fails due to write permissions, locked folders, or path mismatch, OmniPack automatically attempts fallback installation with `--scope user` to ensure high success rates.

### 🧭 Runtime Patch Awareness & Update
OmniPack distinguishes **package updates** from **runtime updates**:
- **Accurate runtime version display**: cards display Python/Node runtime version per environment, and Python venv cards prioritize `pyvenv.cfg` metadata to avoid being confused by a newly patched system interpreter.
- **Patch update detection**: for Python (`3.14.x`) and Node (`25.x`), OmniPack checks the latest patch in the same cycle and shows `current -> latest` directly on cards.
- **Dedicated runtime update action**: runtime update uses a separate card action (`Py` / `Nd`), while `⇧` remains **package update only**.

### ⛑️ Safe Update Intelligence: Constraint-Aware & Variant-Aware
OmniPack knows which updates are **safe** and which need a **second look**.
- **Constraint-Aware Auto-Selection**: When "Outdated" is checked, packages whose latest version violates dependent version constraints (e.g., mpmath `1.4.1` breaks sympy's `<1.4` rule) are **not auto-selected**. A visual `⚠` indicator explains why.
- **Build Variant Detection**: Automatically recognizes PEP 440 local version suffixes (`+cu132`, `+cpu`, `+rocm5.6`). If updating would switch your package between different hardware builds (CUDA → CPU), a `🔀` indicator warns you.
- **Confirmation dialogs**: Clicking update on a flagged package triggers a detailed risk dialog. You can still proceed — but only after being fully informed.

![OmniPack Version Limits](./resources/VersionLimits.png)

### ⚡ Compiler-Grade Performance: Smooth Native Experience
Built with PySide6 and support for [Nuitka](https://nuitka.net/) compilation into a C++ level native single executable (`.exe` / ELF binary). It doesn't just respond instantly; it also supports one-click mirror source switching.

![OmniPack Settings Sources](./resources/Settings-Sources.png)

---

## 🚀 Quick Start

### Method 1: Download Portable Version (Recommended)
Go to the GitHub Releases area to get the latest pre-built single-file package (supports Windows/Linux/macOS). Double-click to run; all configuration and operation data will be recorded locally.

### Method 2: Run from Source
1. Ensure Python 3.10+ is installed.
2. Clone the repository and install dependencies:
   ```bash
   git clone https://github.com/LeoOfGit/OmniPack.git
   cd OmniPack
   pip install -r requirements.txt
   ```
3. Run:
   ```bash
   python OmniPack.py
   ```

---

## 📚 Detailed Documentation & Guides

- Questions? Shortcuts? Advanced features? 👉 [**《OmniPack User Guide》**](./docs/UserGuide.zh-CN.md)
- Low-level `QThread` synchronization and configuration details? 👉 [**《OmniPack Architecture Guide》**](./docs/Architecture.zh-CN.md)
- How to compile from source to a single-file executable? 👉 [**《OmniPack Compilation Guide》**](./docs/Compile.md)

---

## 🤝 Contributing

**OmniPack aims to be the most elegant cross-language developer package management center.**
Thanks to the highly decoupled `Panel <-> Manager` architecture, even with minimal UI experience, you can quickly write a Backend to integrate **Rust (Cargo), Go, Ruby (Gems)**, and more by reading the [Architecture Guide](./docs/Architecture.zh-CN.md)!

Pull Requests and Issues are more than welcome!

---

## 📄 License
This project is licensed under the [GPL v3.0 License](./LICENSE).
