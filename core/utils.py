import os
import shutil
import platform
import subprocess
import sys
import re
import tempfile
from pathlib import Path


def _get_real_exe_path():
    """Return the real path of the running executable.

    For Nuitka onefile builds, sys.executable points to the temp extraction
    directory, NOT the original .exe on disk.  The Nuitka-recommended way to
    find the original executable is sys.argv[0].

    We also try GetModuleFileNameW as a secondary check on Windows, but note
    that in Nuitka onefile mode it may also return a temp path, so we prefer
    sys.argv[0] when it resolves to an existing file.
    """
    # 1. Nuitka onefile: sys.argv[0] reliably points to the original .exe
    if sys.argv and sys.argv[0]:
        candidate = os.path.abspath(sys.argv[0])
        if os.path.isfile(candidate):
            return candidate

    # 2. Windows: GetModuleFileNameW (with a properly-sized buffer)
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(32768)
            n = ctypes.windll.kernel32.GetModuleFileNameW(None, buf, 32768)
            if n > 0:
                return os.path.abspath(buf.value)
        except Exception:
            pass

    return os.path.abspath(sys.executable)


def _is_frozen():
    """Returns True when running as a compiled executable (PyInstaller or Nuitka)."""
    if getattr(sys, "frozen", False):  # PyInstaller
        return True
    # Nuitka: the __compiled__ variable is injected into every compiled module.
    if "__compiled__" in globals():
        return True
    # Nuitka onefile fallback: __file__ is extracted to a temp directory
    file_dir = os.path.abspath(os.path.dirname(__file__))
    temp_dir = os.path.abspath(tempfile.gettempdir())
    return file_dir.lower().startswith(temp_dir.lower())


def get_app_root():
    """
    Returns the root directory of the application source/resources.
    In both development and frozen (Nuitka/PyInstaller) environments, 
    this reliably points to the directory containing 'resources', 'ui', etc.
    by calculating it relative to this source file.
    """
    return Path(__file__).parent.parent.absolute()

def is_admin():
    """Check if the current process has administrator privileges."""
    try:
        if os.name == "nt":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.getuid() == 0
    except Exception:
        return False

def get_persistent_root():
    """
    Returns the directory where persistent data (config) should be stored.
    Windows:
      - Portable frozen builds default to the executable directory.
      - Installed builds under Program Files use `AppData\\Roaming`.
      - Can be overridden by OMNIPACK_PORTABLE_CONFIG=1/0.
    Linux/macOS:
      - Use standard application data folders.
      - Linux respects XDG_CONFIG_HOME when provided.
    """
    app_name = "OmniPack"
    if sys.platform == "win32":
        if not _is_frozen():
            # Development mode: always use the root project folder directly.
            return get_app_root()

        exe_dir = os.path.dirname(_get_real_exe_path())

        override = os.environ.get("OMNIPACK_PORTABLE_CONFIG", "").strip().lower()
        if override in {"1", "true", "yes", "on"}:
            return Path(exe_dir)
        if override in {"0", "false", "no", "off"}:
            root = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
            return Path(root) / app_name

        exe_key = os.path.normcase(os.path.normpath(exe_dir))
        program_roots = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
        ]
        under_program_files = False
        for root in program_roots:
            if not root:
                continue
            root_key = os.path.normcase(os.path.normpath(str(root))).rstrip("\\/")
            if exe_key == root_key or exe_key.startswith(root_key + os.sep):
                under_program_files = True
                break
        if not under_program_files:
            return Path(exe_dir)

        root = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
        return Path(root) / app_name
    elif sys.platform == "darwin":
        return Path(os.path.expanduser("~/Library/Application Support")) / app_name
    else:
        xdg_root = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if xdg_root:
            return Path(xdg_root) / app_name
        return Path(os.path.expanduser("~/.config")) / app_name

def find_system_pythons():
    """
    Robustly find installed Python interpreters.
    Matches paths on Windows, Linux, and MacOS.
    """
    pythons = []
    seen_paths = set()

    def _python_name_ok(name: str) -> bool:
        # Keep interpreters only, skip helper binaries such as python3-config.
        return re.match(r"^python(\d+(\.\d+)*)?(\.exe)?$", name, re.IGNORECASE) is not None

    def add_python(path, tags=None):
        path = os.path.normpath(path)
        key = os.path.normcase(path)
        
        # Filter out WindowsApps stub executables (always 0 bytes or trigger Store) and 0-byte stubs
        if "windowsapps" in key:
            return
            
        if key not in seen_paths and os.path.exists(path):
            try:
                if os.path.getsize(path) == 0:
                    return
            except Exception:
                return
            from core.env_detector import generate_smart_env_name
            name = generate_smart_env_name(path, "system")
            actual_tags = list(tags) if tags else []
            
            # Dynamically check if this python's folder is in PATH
            parent_dir = os.path.normcase(os.path.dirname(path))
            path_env = os.environ.get("PATH", "")
            for p in path_env.split(os.pathsep):
                if p and os.path.normcase(os.path.normpath(p)) == parent_dir:
                    if "path" not in actual_tags:
                        actual_tags.append("path")
                    break

            pythons.append({"path": path, "name": name, "tags": actual_tags})
            seen_paths.add(key)

    # 1. Check ALL entries in PATH
    path_env = os.environ.get("PATH", "")
    exe_name = "python.exe" if sys.platform == "win32" else "python3"
    fallback_exe_name = "python" if sys.platform != "win32" else None
    
    for p in path_env.split(os.pathsep):
        if not p:
            continue
            
        p_path = Path(p)
        if not p_path.exists() or not p_path.is_dir():
            continue
            
        exe = p_path / exe_name
        if exe.exists() and (exe.is_file() or exe.is_symlink()):
            add_python(str(exe))
        elif fallback_exe_name:
            fallback_exe = p_path / fallback_exe_name
            if fallback_exe.exists() and (fallback_exe.is_file() or fallback_exe.is_symlink()):
                add_python(str(fallback_exe))

    if sys.platform == "win32":
        # 2. Check Program Files and C:\
        prog_roots = [
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
            "C:\\"
        ]
        for root in prog_roots:
            p = Path(root)
            if p.exists():
                # Look for Python311, Python312, etc.
                for d in p.glob("Python*"):
                    exe = d / "python.exe"
                    if exe.exists():
                        add_python(str(exe))

        # 3. Check LocalAppData (User installs)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            p = Path(local_app_data) / "Programs" / "Python"
            if p.exists():
                for d in p.glob("Python*"):
                    exe = d / "python.exe"
                    if exe.exists():
                        add_python(str(exe))
    else:
        # Check common Mac/Linux paths
        search_paths = [
            Path("/usr/local/bin"),
            Path("/opt/homebrew/bin"),
            Path("/usr/bin"),
        ]
        for root in search_paths:
            if root.exists():
                for d in root.glob("python*"):
                    if (d.is_file() or d.is_symlink()) and _python_name_ok(d.name):
                        add_python(str(d))

        # pyenv layout: ~/.pyenv/versions/<version>/bin/python
        pyenv_root = Path(os.path.expanduser("~/.pyenv/versions"))
        if pyenv_root.exists():
            for ver_dir in pyenv_root.iterdir():
                if not ver_dir.is_dir():
                    continue
                for candidate in (ver_dir / "bin" / "python", ver_dir / "bin" / "python3"):
                    if candidate.exists() and (candidate.is_file() or candidate.is_symlink()):
                        add_python(str(candidate))
            
    return pythons

def get_python_version(py_path):
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        res = subprocess.run([py_path, "--version"], capture_output=True, text=True, creationflags=flags)
        if res.returncode == 0:
            raw = (res.stdout or "").strip() or (res.stderr or "").strip()
            m = re.search(r"Python\s+([0-9]+(?:\.[0-9]+){1,3})", raw)
            if m:
                return m.group(1)
    except:
        pass
    return "Unknown"

def get_uv_path(config_mgr=None):
    """
    Returns the path to the 'uv' executable following a priority list:
    1. User specified in config (if config_mgr provided).
    2. Built-in (bundled with OmniPack in the bin directory).
    3. System PATH.
    """
    # 1. User specified
    if config_mgr and hasattr(config_mgr, "config") and hasattr(config_mgr.config, "pip_settings"):
        uv_custom = str(config_mgr.config.pip_settings.get("uv_path", "")).strip()
        if uv_custom and os.path.exists(uv_custom):
            return uv_custom

    # 2. Built-in
    exe_name = "uv.exe" if sys.platform == "win32" else "uv"
    built_in = get_app_root() / "bin" / exe_name
    if built_in.exists():
        return str(built_in)

    # 3. System
    sys_uv = shutil.which("uv")
    if sys_uv:
        return sys_uv

    return "uv"

