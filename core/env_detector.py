import os
from pathlib import Path
from typing import Tuple, Optional

def _is_venv_root(root: Path) -> bool:
    """Best-effort virtual environment marker detection."""
    return any([
        (root / "pyvenv.cfg").exists(),
        (root / "conda-meta").exists(),
        (root / "Scripts" / "activate").exists(),
        (root / "bin" / "activate").exists(),
    ])

def generate_smart_env_name(executable_path: str, env_type: str, fallback_name: str = "Unknown Env") -> str:
    path = Path(executable_path)
    
    # Unify naming: Just use the folder name gracefully for everything.
    ignore_names = {"scripts", "bin", ".venv", "venv", "env", "envs", ".envs", "virtualenv", "python"}
    
    current_dir = path.parent
    # Walk up the tree to find a meaningful name
    for _ in range(5):
        if str(current_dir.parent) == str(current_dir): # reached root
            break
        name = current_dir.name
        if name.lower() not in ignore_names:
            return name
        current_dir = current_dir.parent
        
    return fallback_name

def resolve_python_env(input_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Intelligently resolves a Python path.
    Returns: (executable_path, env_type: "system" or "venv") or (None, None)
    """
    path = Path(input_path).resolve()
    
    if not path.exists():
        return None, None

    # 1. If user selected a python executable file directly
    if path.is_file() and path.name.lower() in ["python.exe", "python3.exe", "python", "python3"]:
        parent_name = path.parent.name.lower()
        if parent_name in ["scripts", "bin"]:
            env_root = path.parent.parent
            if _is_venv_root(env_root):
                return str(path), "venv"
            # Default to system when no virtual-env marker is found.
            # This avoids misclassifying system Python like /usr/bin/python3 as venv.
            return str(path), "system"
        return str(path), "system"

    # 2. If user selected a directory
    if path.is_dir():
        # Common Linux/macOS path
        unix_py = path / "bin" / "python"
        unix_py3 = path / "bin" / "python3"
        # Common Windows path
        win_py = path / "Scripts" / "python.exe"
        
        if win_py.exists():
            return str(win_py), ("venv" if _is_venv_root(path) else "system")
        elif unix_py.exists():
            return str(unix_py), ("venv" if _is_venv_root(path) else "system")
        elif unix_py3.exists():
            return str(unix_py3), ("venv" if _is_venv_root(path) else "system")
            
        # Maybe it's a system install root
        if (path / "python.exe").exists():
            return str(path / "python.exe"), "system"
        if (path / "python3").exists():
            return str(path / "python3"), "system"
        if (path / "python").exists():
            return str(path / "python"), "system"

    return None, None

def get_user_node_modules() -> Optional[Path]:
    """Returns the path to the user-specific global node_modules directory if it exists."""
    user_home = Path.home()
    node_modules = user_home / "node_modules"
    return node_modules if node_modules.exists() else None


def describe_npm_env(resolved_path: str, suggested_name: str = "") -> Tuple[str, str]:
    """
    Infer the saved env type and display name for an already-resolved npm path.
    Returns: (env_type, display_name)
    """
    path = Path(resolved_path)
    normalized_name = str(suggested_name or "").strip() or path.name or "NPM Project"

    if path.name.lower() != "node_modules" or (path / "package.json").exists():
        return "project", normalized_name

    path_key = os.path.normcase(os.path.normpath(str(path)))
    user_modules = get_user_node_modules()
    if user_modules:
        user_modules_key = os.path.normcase(os.path.normpath(str(user_modules)))
        if path_key == user_modules_key:
            return "user_home_modules", "User Home node_modules"

    if os.name == "nt":
        appdata_modules = Path(os.path.expandvars(r"%APPDATA%")) / "npm" / "node_modules"
        appdata_key = os.path.normcase(os.path.normpath(str(appdata_modules)))
        if path_key == appdata_key:
            return "user_roaming_modules", "Roaming npm node_modules"

    return "standalone_modules", f"node_modules @ {path.parent}"

def resolve_npm_env(input_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Intelligently resolves an NPM project path, including user-level global node_modules.
    Returns: (project_dir_path, project_name) or (None, None)
    """
    path = Path(input_path).resolve()
    
    if not path.exists():
        return None, None
        
    # Check for User-Level Global node_modules
    user_modules = get_user_node_modules()
    if user_modules:
        try:
            relative = path.relative_to(user_modules)
            if relative.parts:
                package_name = relative.parts[0]
                return str(path), f"UserGlobal_{package_name}"
        except ValueError:
            pass

    # If user selected a file (e.g., package.json)
    if path.is_file():
        if path.name.lower() == "package.json":
            project_dir = path.parent
            return str(project_dir), project_dir.name
        else:
            current_dir = path.parent
            for _ in range(5): # Limit depth search
                if (current_dir / "package.json").exists():
                    return str(current_dir), current_dir.name
                if str(current_dir.parent) == str(current_dir):
                    break
                current_dir = current_dir.parent
            return None, None
            
    # If user selected a directory
    if path.is_dir():
        if (path / "package.json").exists():
            return str(path), path.name
        
        # if they selected `node_modules`, handle standalone node_modules
        if path.name.lower() == "node_modules":
            # Case 1: node_modules with package.json in parent (standard project)
            if (path.parent / "package.json").exists():
                return str(path.parent), path.parent.name
            # Case 2: standalone node_modules directory (e.g., C:\Users\Leo\node_modules\)
            return str(path), path.parent.name + "_node_modules"
                
    return None, None
