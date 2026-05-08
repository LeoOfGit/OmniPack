import os
import subprocess
import sys
import shutil
import platform
from pathlib import Path

# --- 配置信息 ---
APP_NAME = "OmniPack"
VERSION = "4"
COMPANY = "LeoOfGit"
COPYRIGHT = f"Copyright (c) 2026 {COMPANY}"
DESCRIPTION = "Developer Packages Manager for Python & Node.js"

def run_command(cmd):
    print(f"\n[EXEC] {' '.join(cmd)}")
    # Nuitka 输出较多，直接显示在控制台
    result = subprocess.run(cmd)
    return result.returncode == 0

def ensure_dependencies():
    """确保打包所需的 Python 库已安装"""
    required = ["nuitka", "zstandard", "Pillow"]
    try:
        import nuitka
        import zstandard
        from PIL import Image
    except ImportError:
        print("Installing build dependencies...")
        subprocess.run([sys.executable, "-m", "pip", "install", *required])

def handle_icons():
    """智能图标处理逻辑"""
    res_dir = Path("resources")
    png_source = res_dir / f"{APP_NAME}.png"

    target_icon = None
    system = platform.system()

    if system == "Windows":
        ico_file = res_dir / f"{APP_NAME}.ico"
        if ico_file.exists():
            print(f"Using existing Windows icon: {ico_file}")
            target_icon = ico_file
        elif png_source.exists():
            print("Generating .ico from .png...")
            try:
                from PIL import Image
                img = Image.open(png_source)
                img.save(ico_file, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
                target_icon = ico_file
            except Exception as e:
                print(f"Failed to generate .ico: {e}")

    elif system == "Darwin": # macOS
        icns_file = res_dir / f"{APP_NAME}.icns"
        if icns_file.exists():
            print(f"Using existing macOS icon: {icns_file}")
            target_icon = icns_file
        elif png_source.exists():
            # Nuitka 在 macOS 上通常能处理 PNG 到 ICNS 的转换
            print(f"Using PNG for macOS icon: {png_source}")
            target_icon = png_source

    elif system == "Linux":
        if png_source.exists():
            print(f"Using PNG for Linux icon: {png_source}")
            target_icon = png_source

    return target_icon

def pack():
    ensure_dependencies()

    # 0. 清理旧产物
    dist_dir = Path("dist")
    if dist_dir.exists():
        print(f"Cleaning up {dist_dir}...")
        try:
            shutil.rmtree(dist_dir)
        except Exception as e:
            print(f"Warning: Could not remove {dist_dir}: {e}")
    dist_dir.mkdir(exist_ok=True)

    system = platform.system()

    # 基础 Nuitka 编译命令 (使用 .pyw 避免 Windows 控制台)
    main_script = "OmniPack.pyw"
    if not os.path.exists(main_script):
        print(f"Error: Main script {main_script} not found!")
        return

    # 收集需内嵌的数据文件
    data_files = [
        "--include-data-dir=resources=resources",
        "--include-data-dir=ui/styles=ui/styles",
    ]
    # 捆绑 uv 引擎
    uv_path = shutil.which("uv")
    if uv_path:
        data_files.append(f"--include-data-file={uv_path}=bin/uv.exe")
        print(f"Bundling uv: {uv_path}")
    else:
        print("Warning: 'uv' not found in system PATH. It won't be bundled.")
    # 捆绑文档与许可证
    for doc in ["docs/UserGuide.html", "docs/UserGuide.zh-CN.md",
                "docs/Changelog.zh-CN.md", "docs/Architecture.zh-CN.md",
                "LICENSE", "README.md"]:
        if os.path.exists(doc):
            data_files.append(f"--include-data-file={doc}={doc}")
            print(f"Bundling doc: {doc}")

    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--zig",
        "--enable-plugin=pyside6",
        *data_files,
        "--output-dir=dist",
        "--remove-output",
        "--output-filename=" + APP_NAME,
        main_script
    ]

    # 不同平台的特定参数
    icon_path = handle_icons()

    if system == "Windows":
        cmd.extend([
            "--windows-console-mode=disable",
            "--windows-uac-admin",
            f"--company-name={COMPANY}",
            f"--product-name={APP_NAME}",
            f"--file-version={VERSION}",
            f"--product-version={VERSION}",
            f"--copyright={COPYRIGHT}",
            f"--file-description={DESCRIPTION}",
        ])
        if icon_path:
            cmd.append(f"--windows-icon-from-ico={os.path.abspath(icon_path)}")

    elif system == "Darwin": # macOS
        cmd.extend([
            "--macos-create-app-bundle",
            "--macos-disable-console",
            f"--macos-app-name={APP_NAME}",
            f"--macos-app-version={VERSION}",
        ])
        if icon_path:
            cmd.append(f"--macos-app-icon={os.path.abspath(icon_path)}")

    elif system == "Linux":
        pass

    print(f"\n{'='*60}")
    print(f"Building {APP_NAME} v{VERSION} on {system} (onefile)")
    print(f"{'='*60}\n")

    if run_command(cmd):
        if system == "Darwin":
            final_path = dist_dir / f"{APP_NAME}.app"
        else:
            final_path = dist_dir / f"{APP_NAME}.exe"

        if not final_path.exists():
            print(f"Error: Build completed but {final_path} not found.")
            return

        print(f"\n{'='*60}")
        print(f"Build Succeeded!")
        print(f"Output: {final_path}")
        print(f"{'='*60}")
    else:
        print("\nNuitka build failed.")

if __name__ == "__main__":
    pack()
