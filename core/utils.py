import os
import shutil
import platform
import subprocess
from pathlib import Path

def find_system_pythons():
    """
    Robustly find installed Python interpreters on Windows.
    Checks Program Files, LocalAppData, and PATH.
    """
    pythons = []
    seen_paths = set()

    def add_python(path, name):
        path = os.path.normpath(path)
        if path.lower() not in seen_paths and os.path.exists(path):
            pythons.append({"path": path, "name": name})
            seen_paths.add(path.lower())

    # 1. Check PATH
    py_in_path = shutil.which("python.exe")
    if py_in_path:
        add_python(py_in_path, "System Python (PATH)")

    if platform.system() == "Windows":
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
                        add_python(str(exe), f"Python {d.name.replace('Python', '')}")

        # 3. Check LocalAppData (User installs)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            p = Path(local_app_data) / "Programs" / "Python"
            if p.exists():
                for d in p.glob("Python*"):
                    exe = d / "python.exe"
                    if exe.exists():
                        add_python(str(exe), f"Python {d.name.replace('Python', '')} (User)")
            
            # Check Scripts folder in PATH for uv/pip if needed, but here we only want interpreters
            
    return pythons

def get_python_version(py_path):
    try:
        res = subprocess.run([py_path, "--version"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if res.returncode == 0:
            return res.stdout.strip().split(" ")[1]
    except:
        pass
    return "Unknown"
