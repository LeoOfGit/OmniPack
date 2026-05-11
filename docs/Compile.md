# OmniPack Compilation Guide

This guide will walk you through the process of building the **OmniPack** executable from source.

## 1. Prerequisites

Before you begin, ensure your system has the following software installed:

### Required Tools
- **Python 3.10+**: Latest stable version recommended.
- **C Compiler**: Nuitka requires a C compiler to generate binary files.
    - **Windows**: [Visual Studio 2022](https://visualstudio.microsoft.com/downloads/) (with "Desktop development with C++" workload) is recommended.
    - **macOS**: Install Xcode or run `xcode-select --install`.
    - **Linux**: Install `gcc` or `clang`.

### Recommended Tools
- **uv**: An extremely fast Python package and project manager. If `uv` is found in your system PATH, the build script will automatically bundle it into the generated program.
    - Install command: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows)

## 2. Install Dependencies

The project uses Nuitka for compilation and depends on several specific libraries.

1. **Create and Activate a Virtual Environment (Optional but recommended)**:
   ```bash
   python -m venv .venv
   # Windows
   .\.venv\Scripts\activate
   # macOS/Linux
   source .venv/bin/activate
   ```

2. **Install Runtime Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Install Build Tools**:
   The build script `build_app.py` will automatically check for and install the following dependencies:
   - `nuitka`: The core compiler. (Only Nuitka version 4.1+ fully support Python 3.14's garbage collection mechanism.)
   - `zstandard`: Used to speed up the Nuitka compilation process.
   - `Pillow`: Used for icon conversion.

## 3. Start Compilation

OmniPack provides an automated build script `build_app.py`. It handles icon conversion, resource bundling, and OS-specific configurations.

Run the following in the project root:

```bash
python build_app.py
```

### Main script execution flow:
1. **Cleanup**: Deletes the old `dist` directory.
2. **Environment Check**: Checks and installs necessary Python compilation packages.
3. **Icon Handling**: 
   - Automatically searches for `resources/OmniPack.png`.
   - Converts it to `.ico` on Windows.
   - Processes it as `.icns` on macOS.
4. **Resource Bundling**: Packages `resources`, `ui/styles`, documentation, and the `uv` engine into the binary.
5. **Nuitka Compilation**: Generates a standalone executable using `--onefile` mode.

## 4. Build Output

Once compilation is complete, you can find the generated files in the `dist` directory:

- **Windows**: `dist/OmniPack.exe`
- **macOS**: `dist/OmniPack.app`
- **Linux**: `dist/OmniPack`

## 5. FAQ

### Q: Why is `uv` not found?
**A**: The script will warn you if `uv` is missing. If you want OmniPack to manage environments efficiently, ensure `uv` is in your system PATH. The program will still run without it, but some features may be limited.

### Q: Why is compilation so slow?
**A**: Nuitka's `--onefile` compilation involves significant C code generation and linking, typically taking several minutes. Installing `zstandard` can speed up the bundling process.

### Q: Anti-virus false positives?
**A**: Nuitka-generated standalone programs are sometimes flagged by Windows Defender. It's recommended to temporarily disable real-time protection or add the `dist` directory as an exclusion during compilation.

### Q: How to enable admin privileges?
**A**: On Windows, the build script defaults to using `--windows-uac-admin`. The generated `.exe` will automatically request administrator rights when launched.
