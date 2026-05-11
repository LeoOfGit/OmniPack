# OmniPack 编译指南

本指南将指导你如何从源代码构建 **OmniPack** 可执行文件。

## 1. 环境准备

在开始编译之前，请确保你的系统已安装以下软件：

### 必备工具
- **Python 3.10+**: 建议使用最新稳定版。
- **C 编译器**: Nuitka 需要 C 编译器来生成二进制文件。
    - **Windows**: 建议安装 [Visual Studio](https://visualstudio.microsoft.com/zh-hans/downloads/) (包含 "使用 C++ 的桌面开发" 工作负载)。
    - **macOS**: 安装 Xcode 或运行 `xcode-select --install`。
    - **Linux**: 安装 `gcc` 或 `clang`。

### 推荐工具
- **uv**: 一个极快的 Python 包和项目管理器。如果系统 PATH 中存在 `uv`，编译脚本会自动将其捆绑到生成的程序中。
    - 安装命令: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows)

## 2. 安装依赖

项目使用 Nuitka 进行编译，并依赖一些特定的库。

1. **创建并激活虚拟环境 (可选但推荐)**:
   ```bash
   python -m venv .venv
   # Windows
   .\.venv\Scripts\activate
   # macOS/Linux
   source .venv/bin/activate
   ```

2. **安装运行依赖**:
   ```bash
   pip install -r requirements.txt
   ```

3. **安装编译工具**:
   编译脚本 `build_app.py` 会自动检查并安装以下依赖：
   - `nuitka`: 核心编译器（最新版 `Nuitka 4.1+` 才能完整支持 `Python 3.14` 的垃圾回收机制）
   - `zstandard`: 用于加速 Nuitka 编译过程
   - `Pillow`: 用于图标转换

## 3. 开始编译

OmniPack 提供了一个自动化的编译脚本 `build_app.py`。它会自动处理图标转换、资源打包以及针对不同操作系统的特定配置。

在项目根目录下运行：

```bash
python build_app.py
```

### 脚本主要执行流程：
1. **清理**: 删除旧的 `dist` 目录。
2. **环境检测**: 检查并安装必要的 Python 编译包。
3. **图标处理**: 
   - 自动寻找 `resources/OmniPack.png`。
   - 在 Windows 上将其转换为 `.ico`。
   - 在 macOS 上处理为 `.icns`。
4. **资源捆绑**: 将 `resources`、`ui/styles`、文档和 `uv` 引擎打包进二进制文件。
5. **Nuitka 编译**: 使用 `--onefile` 模式生成单文件可执行程序。

## 4. 输出产物

编译完成后，你可以在 `dist` 目录下找到生成的文件：

- **Windows**: `dist/OmniPack.exe`
- **macOS**: `dist/OmniPack.app`
- **Linux**: `dist/OmniPack`

## 5. 常见问题 (FAQ)

### Q: 提示找不到 `uv`？
**A**: 脚本会警告 `uv` 未找到。如果你希望 OmniPack 能够管理环境，请确保 `uv` 已安装在系统路径中。如果没有安装，程序仍能运行，但相关功能可能会受限。

### Q: 编译速度很慢？
**A**: Nuitka 的 `--onefile` 编译过程涉及大量 C 代码生成和链接，通常需要几分钟。安装 `zstandard` 可以加快打包速度。

### Q: 杀毒软件误报？
**A**: Nuitka 生成的单文件程序有时会被 Windows Defender 误报。建议在编译时临时关闭实时保护，或将 `dist` 目录设为排除项。

### Q: 如何开启管理员权限？
**A**: 在 Windows 上，编译脚本已默认开启 `--windows-uac-admin`。生成的 `.exe` 在运行时会自动请求管理员权限。
