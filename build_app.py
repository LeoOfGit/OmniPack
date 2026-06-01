import json
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

def run_command(cmd, env=None):
    print(f"\n[EXEC] {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env)
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
    root_files = ["LICENSE", "README.md"]
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

def _capture_vcvars_env(vcvars_path):
    """Run ``vcvars64.bat`` and return a dictionary of the environment variables it sets.

    The previous implementation built a single command string, which broke when the
    path contained spaces.  Using ``subprocess.run`` with a *list* argument lets the
    Windows API handle quoting correctly.
    """
    # ``call "<path>" && set`` prints the environment after the batch file runs.
    # Using ``shell=True`` lets ``cmd.exe`` handle the quoting for us, which works
    # reliably even when the path contains spaces.
    # The full command that ``cmd`` receives is:
    #   cmd /c "call \"C:\Path\To\vcvars64.bat\" && set"
    # ``subprocess.run`` with ``shell=True`` will invoke ``cmd.exe`` automatically.
    # ``/V:ON`` enables delayed expansion which some Visual Studio batch files rely on.
    # The command executed is equivalent to:
    #   cmd /V:ON /C "call \"<vcvars_path>\" && set"
    cmd = f'cmd /V:ON /C "call \"{vcvars_path}\" && set"'
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        return None
    env = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    return env


def _msvc_version_from_env(env):
    """Extract the MSVC toolchain version in Nuitka format (e.g. '14.5').

    ``vcvars64.bat`` sets ``VCToolsVersion`` to a full 3-part version like
    ``14.51.36231``.  Nuitka expects the major.minor prefix (``14.5``).
    """
    vctools = env.get("VCToolsVersion", "")
    parts = vctools.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return None


def detect_msvc_env():
    """Auto-detect MSVC toolchain via vcvars64.bat.

    Returns ``(env_dict, msvc_version)`` where *env_dict* is the augmented
    environment and *msvc_version* is the Nuitka-compatible version string
    (e.g. ``'14.5'``), or ``(None, None)`` on failure.

    Supports the **Visual Studio Insiders** edition layout as well as
    classic year/edition layouts.
    """
    # Primary search path – standard Visual Studio installations.
    primary_vs_base = r"C:\Program Files\Microsoft Visual Studio"
    # Secondary search path – Visual Studio Insiders (version 18).
    insiders_vs_base = r"C:\Program Files\Microsoft Visual Studio\18\Insiders"

    # Collect all bases that actually exist on the system.
    search_bases = []
    if os.path.isdir(primary_vs_base):
        search_bases.append(primary_vs_base)
    if os.path.isdir(insiders_vs_base):
        search_bases.append(insiders_vs_base)

    print(f"MSVC detection: search bases = {search_bases}")
    if not search_bases:
        return None, None

    # Allow user to explicitly point to a vcvars64.bat via environment variable.
    # 1️⃣ 先尝试读取项目根目录下的 ``msvc_path.cfg``，该文件只保存一行完整路径。
    cfg_path = os.path.join(os.path.dirname(__file__), "msvc_path.cfg")
    explicit_path = None
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                line = f.readline().strip()
                if line:
                    explicit_path = line
        except Exception as e:
            print(f"Warning: failed to read {cfg_path}: {e}")

    # 2️⃣ 若配置文件不存在或为空，回退到环境变量 ``MSVC_VCVARS_PATH``。
    if not explicit_path:
        explicit_path = os.getenv("MSVC_VCVARS_PATH")

    # 3️⃣ 若仍未得到路径，尝试已知的 Insiders 默认位置（保持兼容性）。
    if not explicit_path:
        possible = r"C:\Program Files\Microsoft Visual Studio\18\Insiders\VC\Auxiliary\Build\vcvars64.bat"
        if os.path.isfile(possible):
            explicit_path = possible

    def _finalize_env(env, vcvars_path):
        """Add ``MSVC_USE_SCRIPT`` so SCons bypasses registry/vswhere detection."""
        env["MSVC_USE_SCRIPT"] = vcvars_path
        ver = _msvc_version_from_env(env)
        return env, ver

    if explicit_path:
        if os.path.isfile(explicit_path):
            env = _capture_vcvars_env(explicit_path)
            if env is not None:
                env, ver = _finalize_env(env, explicit_path)
                print(f"MSVC toolchain found (explicit path): {explicit_path}  [version {ver}]")
                return env, ver
        else:
            print(f"Warning: MSVC path '{explicit_path}' does not exist.")

    for vs_base in search_bases:
        # -----------------------------------------------------------------
        # 0️⃣ 直接检查 ``vs_base`` 本身是否已经是一个完整的 VS edition
        #    （Insiders 版的结构正是如此）
        # -----------------------------------------------------------------
        direct_vcvars = os.path.join(vs_base, "VC", "Auxiliary", "Build", "vcvars64.bat")
        if os.path.isfile(direct_vcvars):
            env = _capture_vcvars_env(direct_vcvars)
            if env is not None:
                env, ver = _finalize_env(env, direct_vcvars)
                print(f"MSVC toolchain found: {direct_vcvars}  [version {ver}]")
                return env, ver

        # -----------------------------------------------------------------
        # 1️⃣ 检查 ``vs_base`` 下的子目录是否已经是一个 edition（例如
        #    C:\Program Files\Microsoft Visual Studio\18\Insiders\Community).
        # -----------------------------------------------------------------
        print(f"Scanning base: {vs_base}")
        for edition in sorted(os.listdir(vs_base)):
            edition_path = os.path.join(vs_base, edition)
            vcvars = os.path.join(edition_path, "VC", "Auxiliary", "Build", "vcvars64.bat")
            if os.path.isfile(vcvars):
                env = _capture_vcvars_env(vcvars)
                if env is not None:
                    env, ver = _finalize_env(env, vcvars)
                    print(f"MSVC toolchain found: {vcvars}  [version {ver}]")
                    return env, ver
                # Fall back to manually locating ``cl.exe``
                vc_root = os.path.abspath(os.path.join(vcvars, "..", ".."))
                cl_path = None
                for root, dirs, files in os.walk(vc_root):
                    if "cl.exe" in files:
                        cl_path = os.path.join(root, "cl.exe")
                        break
                if cl_path:
                    env = os.environ.copy()
                    cl_dir = os.path.dirname(cl_path)
                    env["PATH"] = cl_dir + os.pathsep + env.get("PATH", "")
                    print(f"MSVC toolchain fallback: using cl.exe at {cl_path}")
                    return env, None

        # -----------------------------------------------------------------
        # 2️⃣ 传统布局：<year>\<edition>\VC\Auxiliary\Build\vcvars64.bat
        # -----------------------------------------------------------------
        for year in sorted(os.listdir(vs_base), reverse=True):
            year_dir = os.path.join(vs_base, year)
            if not os.path.isdir(year_dir):
                continue
            for edition in sorted(os.listdir(year_dir)):
                vcvars = os.path.join(year_dir, edition, "VC", "Auxiliary", "Build", "vcvars64.bat")
                if not os.path.isfile(vcvars):
                    continue
                env = _capture_vcvars_env(vcvars)
                if env is not None:
                    env, ver = _finalize_env(env, vcvars)
                    print(f"MSVC toolchain found: {vcvars}  [version {ver}]")
                    return env, ver
    return None, None


def pack(clean=False):
    ensure_dependencies()

    system = platform.system()

    main_script = "OmniPack.py"
    if not os.path.exists(main_script):
        print(f"Error: Main script {main_script} not found!")
        return

    dist_dir = Path("dist")

    if clean:
        if dist_dir.exists():
            print(f"Cleaning {dist_dir} for a fresh build...")
            try:
                shutil.rmtree(dist_dir)
            except Exception as e:
                print(f"Warning: Could not remove {dist_dir}: {e}")

    dist_dir.mkdir(exist_ok=True)

    # 收集需内嵌的数据文件
    data_files = get_data_files()

    # 捆绑 uv 引擎
    uv_path = shutil.which("uv")
    if uv_path:
        data_files.append(f"--include-data-file={uv_path}=bin/uv.exe")
        print(f"Bundling uv: {uv_path}")

    # --- 编译器选择：优先 MSVC（可利用 clcache 跨构建缓存），不可用时回退 Zig ---
    msvc_env = None
    msvc_ver = None
    compiler_flags = []

    if os.name == "nt":
        msvc_env, msvc_ver = detect_msvc_env()

    if msvc_env:
        if msvc_ver:
            compiler_flags.append(f"--msvc={msvc_ver}")
            print(f"Using MSVC {msvc_ver} compiler (cl.exe) for this build.")
        else:
            print("Using MSVC compiler (cl.exe) for this build.")
    else:
        compiler_flags.append("--zig")
        print("MSVC not available, falling back to Zig compiler.")

    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        *compiler_flags,
        "--enable-plugin=pyside6",
        "--include-package=core",
        "--include-package=ui",
        "--include-package=managers",
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

    if run_command(cmd, env=msvc_env):
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
    import argparse

    parser = argparse.ArgumentParser(
        description=f"Build {APP_NAME} with Nuitka.",
        epilog="Without --clean, reuse caches from previous builds for faster compilation.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous build output before starting (full rebuild).",
    )
    args = parser.parse_args()

    pack(clean=args.clean)
