import os
import re
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

PYPI_OFFICIAL_INDEX = "https://pypi.org/simple"
NPM_OFFICIAL_REGISTRY = "https://registry.npmjs.org/"

COMMON_PIP_MIRRORS: List[Tuple[str, str]] = [
    ("Official", PYPI_OFFICIAL_INDEX),
    ("TUNA", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    ("Aliyun", "https://mirrors.aliyun.com/pypi/simple"),
    ("USTC", "https://pypi.mirrors.ustc.edu.cn/simple"),
]

COMMON_NPM_REGISTRIES: List[Tuple[str, str]] = [
    ("Official", NPM_OFFICIAL_REGISTRY),
    ("npmmirror", "https://registry.npmmirror.com/"),
    ("Tencent", "https://mirrors.cloud.tencent.com/npm/"),
]


def _clean_value(value: str) -> str:
    v = str(value or "").strip().strip("'\"")
    if v.lower() in {"", "none", "null", "undefined"}:
        return ""
    return v


def _run_quick(cmd: List[str], timeout: int = 3) -> str:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def detect_system_pip_index_url() -> str:
    for env_key in ("UV_INDEX_URL", "PIP_INDEX_URL"):
        value = _clean_value(os.environ.get(env_key, ""))
        if value:
            return value

    py = sys.executable or "python"
    for key in ("global.index-url", "user.index-url", "site.index-url"):
        output = _run_quick([py, "-m", "pip", "config", "get", key], timeout=2)
        value = _clean_value(output.splitlines()[0] if output else "")
        if value:
            return value

    output = _run_quick([py, "-m", "pip", "config", "list"], timeout=2)
    if output:
        match = re.search(r"index-url\s*=\s*['\"]?([^'\"\s]+)['\"]?", output)
        if match:
            return _clean_value(match.group(1))
    return ""


def _find_npm() -> Optional[str]:
    system_paths = [
        os.path.expandvars(r"%ProgramFiles%\nodejs\npm.cmd"),
        os.path.expandvars(r"%ProgramFiles(x86)%\nodejs\npm.cmd"),
    ]
    for p in system_paths:
        if p and os.path.exists(p):
            return p

    for cmd in ("npm.cmd", "npm"):
        p = shutil.which(cmd)
        if p:
            return p

    common_paths = [os.path.expandvars(r"%APPDATA%\npm\npm.cmd")]
    for p in common_paths:
        if p and os.path.exists(p):
            return p
    return None


def detect_system_npm_registry_url() -> str:
    env_value = _clean_value(os.environ.get("NPM_CONFIG_REGISTRY", ""))
    if env_value:
        return env_value

    npm_path = _find_npm()
    if not npm_path:
        return ""

    output = _run_quick([npm_path, "config", "get", "registry"], timeout=3)
    value = _clean_value(output.splitlines()[0] if output else "")
    return value
