import os
import urllib.parse
import urllib.request
from typing import Dict, Optional


HOST_TARGET_MAP = {
    "pypi": (
        "pypi.org",
        "files.pythonhosted.org",
        "pypi.tuna.tsinghua.edu.cn",
        "mirrors.aliyun.com",
        "pypi.mirrors.ustc.edu.cn",
    ),
    "npm": ("registry.npmjs.org", "npmjs.org", "npmjs.com"),
    "github": ("api.github.com", "github.com"),
    "winget": ("cdn.winget.microsoft.com", "endoflife.date"),
}


def _normalize_proxy_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        return f"http://{value}"
    return value


def normalize_proxy_settings(proxy_settings: Optional[dict]) -> dict:
    raw = proxy_settings or {}
    targets = raw.get("targets", {})
    if not isinstance(targets, dict):
        targets = {}
    return {
        "enabled": bool(raw.get("enabled", False)),
        "http_proxy": _normalize_proxy_url(raw.get("http_proxy", "")),
        "https_proxy": _normalize_proxy_url(raw.get("https_proxy", "")),
        "targets": {
            "pypi": bool(targets.get("pypi", True)),
            "npm": bool(targets.get("npm", False)),
            "pip": bool(targets.get("pip", False)),
            "github": bool(targets.get("github", False)),
            "winget": bool(targets.get("winget", True)),
        },
    }


def should_use_proxy_for_url(url: str, proxy_settings: Optional[dict]) -> bool:
    settings = normalize_proxy_settings(proxy_settings)
    if not settings["enabled"]:
        return False

    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False

    for target_key, hosts in HOST_TARGET_MAP.items():
        if not settings["targets"].get(target_key, False):
            continue
        for target_host in hosts:
            target_host = target_host.lower()
            if host == target_host or host.endswith(f".{target_host}"):
                return True
    return False


def _build_proxy_mapping(proxy_settings: Optional[dict]) -> Dict[str, str]:
    settings = normalize_proxy_settings(proxy_settings)
    proxies: Dict[str, str] = {}
    if settings["http_proxy"]:
        proxies["http"] = settings["http_proxy"]
    if settings["https_proxy"]:
        proxies["https"] = settings["https_proxy"]
    return proxies


def urlopen(
    url: str,
    *,
    timeout: Optional[int] = 10,
    headers: Optional[dict] = None,
    proxy_settings: Optional[dict] = None,
    force_proxy: bool = False,
):
    import ssl
    try:
        ctx = ssl._create_unverified_context()
    except Exception:
        ctx = None

    req = urllib.request.Request(url)
    for key, value in (headers or {}).items():
        req.add_header(key, value)

    proxies = _build_proxy_mapping(proxy_settings)
    if force_proxy and proxies:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            urllib.request.HTTPSHandler(context=ctx) if ctx else urllib.request.HTTPSHandler()
        )
        return opener.open(req, timeout=timeout)

    if should_use_proxy_for_url(url, proxy_settings) and proxies:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxies),
            urllib.request.HTTPSHandler(context=ctx) if ctx else urllib.request.HTTPSHandler()
        )
        return opener.open(req, timeout=timeout)

    if ctx:
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        return opener.open(req, timeout=timeout)
        
    return urllib.request.urlopen(req, timeout=timeout)


def _is_pip_command(cmd: list[str]) -> bool:
    if not cmd:
        return False
    first = os.path.basename(str(cmd[0])).lower()
    if first in {"pip", "pip3", "pip.exe", "uv", "uv.exe"}:
        return True
    if first in {"python", "python.exe", "python3", "python3.exe"}:
        joined = " ".join(str(x).lower() for x in cmd[1:])
        return "-m pip" in joined
    return False


def _is_npm_command(cmd: list[str]) -> bool:
    if not cmd:
        return False
    first = os.path.basename(str(cmd[0])).lower()
    return first in {"npm", "npm.cmd", "npx", "npx.cmd", "pnpm", "pnpm.cmd", "yarn", "yarn.cmd"}


def _is_winget_command(cmd: list[str]) -> bool:
    if not cmd:
        return False
    first = os.path.basename(str(cmd[0])).lower()
    return first in {"winget", "winget.exe"}


def proxy_env_for_command(cmd: list[str], proxy_settings: Optional[dict]) -> Dict[str, str]:
    settings = normalize_proxy_settings(proxy_settings)
    if not settings["enabled"]:
        return {}

    use_proxy = False
    if settings["targets"].get("pip", False) and _is_pip_command(cmd):
        use_proxy = True
    if settings["targets"].get("npm", False) and _is_npm_command(cmd):
        use_proxy = True
    if settings["targets"].get("winget", False) and _is_winget_command(cmd):
        use_proxy = True
    if not use_proxy:
        return {}

    proxies = _build_proxy_mapping(settings)
    if not proxies:
        return {}

    env = {}
    if "http" in proxies:
        env["HTTP_PROXY"] = proxies["http"]
        env["http_proxy"] = proxies["http"]
    if "https" in proxies:
        env["HTTPS_PROXY"] = proxies["https"]
        env["https_proxy"] = proxies["https"]
    return env


def merge_env_for_command(cmd: list[str], base_env: Optional[dict] = None, proxy_settings: Optional[dict] = None) -> dict:
    env = dict(base_env or os.environ)
    env.update(proxy_env_for_command(cmd, proxy_settings))
    return env
