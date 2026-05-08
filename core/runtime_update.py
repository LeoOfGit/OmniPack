import os
import re
import shutil
import subprocess
import threading
import time
from typing import Optional

from core.network_proxy import urlopen, merge_env_for_command
from core.utils import find_system_pythons, get_python_version


PYTHON_EOL_API = "https://endoflife.date/api/python.json"
NODE_EOL_API = "https://endoflife.date/api/nodejs.json"

_CACHE_TTL_SECONDS = 60 * 60
_api_cache_lock = threading.Lock()
_api_cache: dict[str, tuple[float, list[dict]]] = {}
_latest_cache_lock = threading.Lock()
_latest_cycle_cache: dict[str, tuple[float, str]] = {}


def _parse_numeric_version(raw: str) -> str:
    m = re.search(r"([0-9]+(?:\.[0-9]+){1,3})", str(raw or ""))
    return m.group(1) if m else ""


def parse_python_version(raw: str) -> str:
    m = re.search(r"Python\s+([0-9]+(?:\.[0-9]+){1,3})", str(raw or ""))
    if m:
        return m.group(1)
    return _parse_numeric_version(raw)


def parse_node_version(raw: str) -> str:
    m = re.search(r"v([0-9]+(?:\.[0-9]+){1,3})", str(raw or "").strip())
    if m:
        return m.group(1)
    return _parse_numeric_version(raw)


def parse_cycle(runtime_kind: str, version: str) -> str:
    parts = [p for p in str(version or "").split(".") if p.isdigit()]
    if runtime_kind == "python":
        if len(parts) >= 2:
            return f"{parts[0]}.{parts[1]}"
        return ""
    if runtime_kind == "node":
        if parts:
            return parts[0]
        return ""
    return ""


def compare_versions(left: str, right: str) -> int:
    def _parts(v: str) -> list[int]:
        nums = [int(x) for x in re.findall(r"\d+", str(v or ""))]
        return nums[:4]

    a = _parts(left)
    b = _parts(right)
    max_len = max(len(a), len(b), 1)
    a.extend([0] * (max_len - len(a)))
    b.extend([0] * (max_len - len(b)))
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def is_newer_version(candidate: str, current: str) -> bool:
    if not candidate or not current:
        return False
    return compare_versions(candidate, current) > 0


def extract_local_version(version: str) -> str:
    """Extract the local version suffix (+xxx) from a PEP 440 version string.

    Returns the suffix including '+' (e.g. '+cu132', '+cpu'), or empty string if none.
    """
    m = re.search(r'(\+[^\s]+)', str(version or ""))
    return m.group(1) if m else ""


def has_build_variant_mismatch(installed_version: str, latest_version: str) -> bool:
    """Check if updating would change the build variant (e.g. CUDA -> CPU).

    True when the installed version has a local suffix (+cu132) but the latest
    version has a different suffix or none at all — meaning they are different
    build variants of the same package.
    """
    inst_local = extract_local_version(installed_version)
    latest_local = extract_local_version(latest_version)
    if not inst_local:
        return False  # No local version tag on installed, so no mismatch concern
    return inst_local != latest_local


def _widen_version_for_tilde(version: str) -> str:
    """~=1.4.0 → >=1.4.0, <1.5.0; ~=1.4 → >=1.4, <2.0"""
    parts = [int(x) for x in re.findall(r"\d+", str(version or ""))]
    if not parts:
        return ""
    # Drop last segment, increment the new last
    if len(parts) >= 2:
        parts[-2] += 1
        parts[-1] = 0
        upper = ".".join(str(x) for x in parts)
        return upper
    else:
        # ~=1 → <2
        parts[0] += 1
        return str(parts[0])


def check_version_satisfies_constraint(version: str, constraint: str) -> bool:
    """Parse PEP 440-style constraint string and check if version satisfies it.

    Handles >=, <=, >, <, ==, !=, ~= with comma-separated AND logic.
    Returns True if ALL specifiers are satisfied (or constraint is empty).
    """
    if not constraint or not version:
        return True

    raw = str(constraint).strip()
    # Strip outer parentheses
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1].strip()

    # Split by comma for AND logic
    specifiers = [s.strip() for s in raw.split(",") if s.strip()]
    if not specifiers:
        return True

    for spec in specifiers:
        # Match operator and version
        m = re.match(r'(~=|>=|<=|!=|==|>|<)\s*([\d\w.]+)', spec)
        if not m:
            continue

        op = m.group(1)
        ver = m.group(2)

        if op == "~=":
            upper = _widen_version_for_tilde(ver)
            if not upper:
                continue
            # >= ver AND < upper
            if compare_versions(version, ver) < 0:
                return False
            if compare_versions(version, upper) >= 0:
                return False
        elif op == ">=":
            if compare_versions(version, ver) < 0:
                return False
        elif op == "<=":
            if compare_versions(version, ver) > 0:
                return False
        elif op == ">":
            if compare_versions(version, ver) <= 0:
                return False
        elif op == "<":
            if compare_versions(version, ver) >= 0:
                return False
        elif op == "==":
            if compare_versions(version, ver) != 0:
                return False
        elif op == "!=":
            if compare_versions(version, ver) == 0:
                return False

    return True


def _runtime_api_url(runtime_kind: str) -> Optional[str]:
    if runtime_kind == "python":
        return PYTHON_EOL_API
    if runtime_kind == "node":
        return NODE_EOL_API
    return None


def _fetch_runtime_index(runtime_kind: str, proxy_settings=None, timeout: int = 8) -> tuple[list[dict], str]:
    now = time.time()
    with _api_cache_lock:
        cached = _api_cache.get(runtime_kind)
        if cached and (now - cached[0]) <= _CACHE_TTL_SECONDS:
            return list(cached[1]), ""

    url = _runtime_api_url(runtime_kind)
    if not url:
        return [], f"Unsupported runtime kind: {runtime_kind}"

    try:
        import json

        with urlopen(
            url,
            timeout=timeout,
            headers={"User-Agent": "OmniPack/1.0"},
            proxy_settings=proxy_settings or {},
            force_proxy=True,
        ) as response:
            payload = response.read().decode("utf-8", errors="replace")
            data = json.loads(payload)
        if not isinstance(data, list):
            return [], "Invalid API response format."
        with _api_cache_lock:
            _api_cache[runtime_kind] = (time.time(), list(data))
        return data, ""
    except Exception as exc:
        return [], str(exc)


def _extract_versions_for_cycle(runtime_kind: str, cycle: str, text: str) -> list[str]:
    raw_versions = re.findall(r"\b\d+\.\d+(?:\.\d+){0,2}\b", str(text or ""))
    keep: list[str] = []
    if runtime_kind == "python":
        prefix = f"{cycle}."
        for v in raw_versions:
            if v.startswith(prefix):
                keep.append(v)
    elif runtime_kind == "node":
        prefix = f"{cycle}."
        for v in raw_versions:
            if v.startswith(prefix):
                keep.append(v)

    uniq = sorted(set(keep), key=lambda item: [int(x) for x in re.findall(r"\d+", item)])
    return uniq


def _pick_latest(candidates: list[str]) -> str:
    best = ""
    for item in candidates:
        if not best or compare_versions(item, best) > 0:
            best = item
    return best


def _get_cached_latest(runtime_kind: str, cycle: str) -> str:
    key = f"{runtime_kind}:{cycle}"
    with _latest_cache_lock:
        cached = _latest_cycle_cache.get(key)
        if not cached:
            return ""
        if (time.time() - cached[0]) > _CACHE_TTL_SECONDS:
            return ""
        return str(cached[1] or "")


def _set_cached_latest(runtime_kind: str, cycle: str, latest: str):
    if not latest:
        return
    key = f"{runtime_kind}:{cycle}"
    with _latest_cache_lock:
        _latest_cycle_cache[key] = (time.time(), latest)


def _get_latest_from_endoflife(runtime_kind: str, cycle: str, proxy_settings=None) -> tuple[str, str]:
    rows, err = _fetch_runtime_index(runtime_kind, proxy_settings=proxy_settings)
    if err:
        return "", err

    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("cycle", "")).strip() != str(cycle).strip():
            continue
        latest = _parse_numeric_version(str(row.get("latest", "")).strip())
        if latest:
            return latest, ""
        return "", "Missing latest version in API row."

    return "", f"No API row for cycle {cycle}."


def _winget_package_ids(runtime_kind: str, cycle: str) -> list[str]:
    if runtime_kind == "python":
        return [f"Python.Python.{cycle}"]
    if runtime_kind == "node":
        if not str(cycle).isdigit():
            return ["OpenJS.NodeJS", "OpenJS.NodeJS.LTS"]
        major = int(cycle)
        if major % 2 == 0:
            return ["OpenJS.NodeJS.LTS", "OpenJS.NodeJS"]
        return ["OpenJS.NodeJS", "OpenJS.NodeJS.LTS"]
    return []


def _get_latest_from_winget(runtime_kind: str, cycle: str, proxy_settings=None, timeout: int = 25) -> tuple[str, str]:
    if os.name != "nt":
        return "", "winget fallback is available on Windows only."
    winget = shutil.which("winget")
    if not winget:
        return "", "winget not found."

    errors: list[str] = []
    versions: list[str] = []
    for package_id in _winget_package_ids(runtime_kind, cycle):
        cmd = [
            winget,
            "show",
            "--id",
            package_id,
            "--exact",
            "--accept-source-agreements",
        ]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                env=merge_env_for_command(cmd, proxy_settings=proxy_settings),
            )
            text = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
            found = _extract_versions_for_cycle(runtime_kind, cycle, text)
            if found:
                versions.extend(found)
            elif res.returncode != 0:
                errors.append(f"{package_id}: exit {res.returncode}")
        except Exception as exc:
            errors.append(f"{package_id}: {exc}")

    best = _pick_latest(versions)
    if best:
        return best, ""

    if errors:
        return "", "; ".join(errors)
    return "", "winget did not return a matching version."


def _get_latest_from_local_python(cycle: str) -> tuple[str, str]:
    versions: list[str] = []
    try:
        for item in find_system_pythons():
            py_path = str(item.get("path", "")).strip()
            if not py_path:
                continue
            ver = _parse_numeric_version(get_python_version(py_path))
            if ver.startswith(f"{cycle}."):
                versions.append(ver)
    except Exception as exc:
        return "", str(exc)

    best = _pick_latest(versions)
    if best:
        return best, ""
    return "", "No local Python in target cycle."


def get_latest_patch_for_cycle(runtime_kind: str, cycle: str, proxy_settings=None) -> tuple[str, str]:
    if not cycle:
        return "", "Version cycle is empty."

    cached = _get_cached_latest(runtime_kind, cycle)
    if cached:
        return cached, ""

    latest, err_api = _get_latest_from_endoflife(runtime_kind, cycle, proxy_settings=proxy_settings)
    if latest:
        _set_cached_latest(runtime_kind, cycle, latest)
        return latest, ""

    latest, err_winget = _get_latest_from_winget(runtime_kind, cycle, proxy_settings=proxy_settings)
    if latest:
        _set_cached_latest(runtime_kind, cycle, latest)
        return latest, ""

    if runtime_kind == "python":
        latest, err_local = _get_latest_from_local_python(cycle)
        if latest:
            _set_cached_latest(runtime_kind, cycle, latest)
            return latest, ""
        return "", f"{err_api}; {err_winget}; {err_local}"

    return "", f"{err_api}; {err_winget}"


def check_runtime_patch_update(runtime_kind: str, current_version: str, proxy_settings=None) -> tuple[str, str, bool, str]:
    current = _parse_numeric_version(current_version)
    if not current:
        return "", "", False, "Current version unavailable."

    cycle = parse_cycle(runtime_kind, current)
    if not cycle:
        return "", "", False, "Unable to infer version cycle."

    latest, err = get_latest_patch_for_cycle(runtime_kind, cycle, proxy_settings=proxy_settings)
    if err:
        return cycle, "", False, err

    return cycle, latest, is_newer_version(latest, current), ""


def resolve_venv_root(env_path: str) -> str:
    norm = os.path.normpath(str(env_path or ""))
    if not norm:
        return norm
    if os.path.isdir(norm):
        return norm
    parent = os.path.dirname(norm)
    if os.path.basename(parent).lower() in {"scripts", "bin"}:
        return os.path.dirname(parent)
    return parent


def build_python_runtime_update_command(env_type: str, env_path: str, cycle: str) -> tuple[Optional[list[str]], str]:
    cycle = str(cycle or "").strip()
    if not cycle:
        return None, "Cannot update Python: missing major.minor cycle."

    if str(env_type or "").lower() == "system":
        if os.name != "nt":
            return None, "System Python auto-update is currently supported on Windows only."
        if not shutil.which("winget"):
            return None, "winget is required to update system Python."
        package_id = f"Python.Python.{cycle}"
        return [
            "winget",
            "upgrade",
            "--id",
            package_id,
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ], ""

    venv_root = resolve_venv_root(env_path)
    if not venv_root:
        return None, "Cannot locate virtual environment root."

    if os.name == "nt":
        py_launcher = shutil.which("py")
        if not py_launcher:
            return None, "Python launcher 'py' is required to upgrade venv interpreter."
        return [py_launcher, f"-{cycle}", "-m", "venv", "--upgrade", venv_root], ""

    py_cmd = shutil.which(f"python{cycle}")
    if not py_cmd:
        return None, f"python{cycle} is required to upgrade this virtual environment."
    return [py_cmd, "-m", "venv", "--upgrade", venv_root], ""


def build_node_runtime_update_command(cycle: str) -> tuple[Optional[list[str]], str]:
    if os.name != "nt":
        return None, "Node runtime auto-update is currently supported on Windows only."
    if not shutil.which("winget"):
        return None, "winget is required to update Node.js runtime."

    major_text = str(cycle or "").strip()
    if not major_text.isdigit():
        return None, "Cannot update Node.js: missing major version."

    major = int(major_text)
    package_id = "OpenJS.NodeJS.LTS" if major % 2 == 0 else "OpenJS.NodeJS"
    return [
        "winget",
        "upgrade",
        "--id",
        package_id,
        "--exact",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ], ""
