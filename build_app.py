import os
import subprocess
import sys
import shutil
import platform
import fnmatch
from pathlib import Path

from version import __version__

# --- 配置信息 ---
APP_NAME = "OmniPack"
VERSION = __version__
COMPANY = "LeoOfGit"
COPYRIGHT = f"Copyright (c) 2026 {COMPANY}"
DESCRIPTION = "Developer Packages Manager for Python & Node.js"
IGNORE_FILE = "packaging_ignore.txt"

def run_command(cmd):
    print(f"\n[EXEC] {' '.join(cmd)}")
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

def load_ignore_patterns():
    """加载忽略规则"""
    if not os.path.exists(IGNORE_FILE):
        return []
    with open(IGNORE_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

def should_ignore(path, patterns):
    """检查路径是否应该被忽略"""
    path_str = str(path).replace(os.sep, "/")
    name = os.path.basename(path_str)
    for pattern in patterns:
        if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path_str + "/", pattern):
            return True
        if fnmatch.fnmatch(name, pattern):
            return True
        if pattern.endswith("/") and path_str.startswith(pattern[:-1]):
            return True
    return False

def get_data_files():
    """自动扫描并收集文件，跳过忽略列表，排除 Nuitka 已编译的 Python 源码"""
    patterns = load_ignore_patterns()
    data_files = []

    # 基础要包含的目录
    base_dirs = ["resources", "docs", "ui"]

    # Nuitka 已将 .py 编译为机器码，作为数据文件再打包一份只会泄露源码
    _SKIP_SUFFIXES = {".py", ".pyc", ".pyo"}

    for base in base_dirs:
        if not os.path.exists(base): continue

        for root, dirs, files in os.walk(base):
            # 过滤目录
            dirs[:] = [d for d in dirs if not should_ignore(Path(root) / d, patterns)]

            for file in files:
                file_path = Path(root) / file
                if should_ignore(file_path, patterns):
                    continue
                if file_path.suffix in _SKIP_SUFFIXES:
                    continue
                data_files.append(f"--include-data-file={file_path}={file_path}")
    
    # 手动添加根目录重要文件
    root_files = ["LICENSE", "README.md", "pypi_search_cache.json"]
    for f in root_files:
        if os.path.exists(f) and not should_ignore(f, patterns):
            data_files.append(f"--include-data-file={f}={f}")
            
    return data_files

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

    main_script = "OmniPack.pyw"
    if not os.path.exists(main_script):
        print(f"Error: Main script {main_script} not found!")
        return

    # 收集需内嵌的数据文件
    data_files = get_data_files()
    
    # 捆绑 uv 引擎
    uv_path = shutil.which("uv")
    if uv_path:
        data_files.append(f"--include-data-file={uv_path}=bin/uv.exe")
        print(f"Bundling uv: {uv_path}")
    
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
