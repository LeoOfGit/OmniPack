import json
import os
import re
import shutil
import unicodedata
from typing import Optional


def find_winget_executable(custom_path: str = "") -> str:
    # 1. Try system PATH first - it's the most reliable for aliases
    system_winget = shutil.which("winget") or shutil.which("winget.exe")
    if system_winget:
        # If it is a WindowsApps stub, it's better to use it than a hardcoded versioned path
        return system_winget

    # 2. Try custom path if provided
    if custom_path and os.path.exists(custom_path):
        return custom_path
        
    return ""


def normalize_source_name(source_name: str) -> str:
    source = str(source_name or "").strip()
    return "" if source.lower() in {"", "all", "(all sources)"} else source


def normalize_scope_value(scope_value: str) -> str:
    scope = str(scope_value or "all").strip().lower()
    return scope if scope in {"user", "machine"} else "all"


def normalize_install_mode(mode_value: str) -> str:
    mode = str(mode_value or "default").strip().lower()
    return mode if mode in {"default", "silent", "interactive"} else "default"


def apply_scope_option(cmd: list[str], scope_value: str) -> None:
    scope = normalize_scope_value(scope_value)
    if scope in {"user", "machine"}:
        cmd.extend(["--scope", scope])


def apply_source_option(cmd: list[str], source_name: str) -> None:
    source = normalize_source_name(source_name)
    if source:
        cmd.extend(["--source", source])


def apply_install_mode_option(cmd: list[str], mode_value: str) -> None:
    mode = normalize_install_mode(mode_value)
    if mode == "silent":
        cmd.append("--silent")
    elif mode == "interactive":
        cmd.append("--interactive")
    else:
        cmd.append("--disable-interactivity")


def build_winget_command(
    *args: str,
    source_name: str = "",
    scope_value: str = "all",
    include_unknown: bool = False,
    include_pinned: bool = False,
    count: int = 0,
    install_mode: str = "default",
    accept_package_agreements: bool = False,
    accept_source_agreements: bool = True,
    exact: bool = False,
    winget_path: str = "",
    proxy_url: str = "",
) -> list[str]:
    winget = find_winget_executable(winget_path)
    cmd = [winget or "winget"]
    if proxy_url:
        # Wrap proxy in quotes to ensure WinGet parses credentials (@, :) correctly
        cmd.extend(["--proxy", f'"{proxy_url}"'])
    cmd.extend(args)
    root_cmd = str(args[0]).strip().lower() if args else ""
    if accept_package_agreements and root_cmd in {"install", "upgrade"}:
        cmd.append("--accept-package-agreements")
    if accept_source_agreements and root_cmd in {"install", "upgrade", "list", "search"}:
        cmd.append("--accept-source-agreements")
    if exact:
        cmd.append("--exact")
    if include_unknown:
        # Some winget versions require --upgrade-available to use --include-unknown with the 'list' command.
        if root_cmd != "list" or "--upgrade-available" in args:
            cmd.append("--include-unknown")
    if include_pinned:
        # Some winget versions require --upgrade-available to use --include-pinned with the 'list' command.
        if root_cmd != "list" or "--upgrade-available" in args:
            cmd.append("--include-pinned")
    if count > 0:
        cmd.extend(["--count", str(count)])
    apply_source_option(cmd, source_name)
    apply_scope_option(cmd, scope_value)
    if args and args[0] in {"install", "upgrade", "uninstall"}:
        apply_install_mode_option(cmd, install_mode)
    elif args and args[0] in {"list", "search", "source", "pin"}:
        cmd.append("--disable-interactivity")
    return cmd


_SUMMARY_LINE_RE = re.compile(r"^\d+\s+(upgrade|update|package|app|have version numbers)", re.IGNORECASE)


def _normalize_display_string(text: str) -> str:
    """Pad double-width characters with \x00 so that string length matches console display width."""
    res = []
    for c in text:
        res.append(c)
        if unicodedata.east_asian_width(c) in ('W', 'F'):
            res.append('\x00')
    return "".join(res)


def _restore_display_string(text: str) -> str:
    """Remove \x00 padding and strip whitespace."""
    return text.replace('\x00', '').strip()


def parse_winget_table(output: str, mode: str = "") -> list[dict]:
    """Parse winget's tabular output.

    Uses console display width to find the exact column start positions from the header,
    then slices each row using those fixed positions. This handles empty columns and
    variable column widths perfectly, correctly accounting for East-Asian characters.
    """
    text = str(output or "").replace("\ufeff", "")
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    header_idx = -1
    for idx, line in enumerate(lines):
        if re.match(r"^\s*-{3,}\s*$", line):
            header_idx = idx - 1
            break
    if header_idx < 0 or header_idx >= len(lines):
        return []

    header_line = lines[header_idx]
    norm_header = _normalize_display_string(header_line.rstrip())
    
    # In installed and search modes, Winget headers are always single words (e.g. Name, Id, Version, Available, Source).
    # If the column content is exactly the same width as the header, Winget may pad with only 1 space.
    # Therefore, we simply split by any whitespace for these modes to avoid merging columns like "Available Source".
    if mode in ("installed", "search"):
        col_matches = list(re.finditer(r"[^\s\x00]+", norm_header))
    else:
        # Fallback for modes like "pin" where headers (e.g. "Pin type") contain spaces.
        col_matches = list(re.finditer(r"(?!\s)[^\s\x00].*?(?=\s{2,}|\Z)", norm_header))
        
    if not col_matches:
        return []
    
    col_starts = [m.start() for m in col_matches]
    col_count = len(col_starts)

    rows = []
    for line in lines[header_idx + 2:]:
        if re.match(r"^\s*-{3,}\s*$", line):
            continue
        if _SUMMARY_LINE_RE.match(line.strip()):
            continue
            
        norm_line = _normalize_display_string(line.rstrip())
        if not norm_line.strip():
            continue
            
        fields = []
        for i in range(col_count):
            start = col_starts[i]
            end = col_starts[i+1] if i + 1 < col_count else len(norm_line)
            fields.append(_restore_display_string(norm_line[start:end]))
            
        row = _map_winget_fields(fields, mode, col_count)
        if row:
            rows.append(row)
    return rows


_KNOWN_WINGET_SOURCES = {"winget", "msstore", "steam"}
# Extract version: optionally led by >/≥, then digit.digit.digit...
_VERSION_EXTRACT_RE = re.compile(r"^[>≥\s]*(\d+\.\d+(?:\.\d+)*(?:[.\-_][a-zA-Z0-9]+)*)")
# Fallback: first run of digits possibly with dots
_VERSION_FALLBACK_RE = re.compile(r"(\d+(?:\.\d+)+)")


def _clean_version_field(raw: str, source: str = "") -> str:
    """Clean a version field: extract version pattern, discard source leakage and garbage."""
    v = str(raw or "").strip()
    if not v:
        return v
    if v.lower() in {"unknown", ""}:
        return v
    # Try structured version pattern first
    m = _VERSION_EXTRACT_RE.match(v)
    if m:
        return m.group(1)
    # Try any digit.digit pattern
    m = _VERSION_FALLBACK_RE.search(v)
    if m:
        return m.group(1)
    # Strip > prefix and trailing source names
    v = v.lstrip(">≥").strip()
    src = str(source or "").strip().lower()
    for kw in _KNOWN_WINGET_SOURCES:
        if v.lower().endswith(kw):
            v = v[:-len(kw)].strip()
            break
    if src and v.lower().endswith(src):
        v = v[:-len(src)].strip()
    return v


def _clean_source_field(raw: str) -> str:
    """Normalize weird source names like MSIX\\Micr; strip control chars."""
    s = str(raw or "").strip()
    if not s:
        return s
    s = s.splitlines()[0] if s.splitlines() else s
    s = s.replace("\\", " / ")
    s = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", s)
    return s.strip()


def is_default_source(source_name: str) -> bool:
    """Check if a source name is the default 'winget' source (should not get a badge)."""
    s = str(source_name or "").strip().lower()
    return s == "winget" or s.startswith("winget")


def _map_winget_fields(fields: list[str], mode: str, col_count: int) -> dict:
    """Map raw column-split fields to named keys using the *header* column count.

    Uses col_count (from the header) rather than len(fields) so that empty
    intermediate columns don't shift the key alignment.
    """
    if col_count < 2:
        return {}

    if mode == "search":
        keys = ["name", "id", "version", "match", "source"] if col_count >= 5 else ["name", "id", "version", "source"]
    elif mode == "source":
        keys = ["name", "arg", "explicit"] if col_count >= 3 else []
    elif mode == "pin":
        if col_count >= 6:
            keys = ["name", "id", "version", "source", "pin_type", "pinned_version"]
        elif col_count == 5:
            keys = ["name", "id", "version", "source", "pin_type"]
        elif col_count == 4:
            keys = ["name", "id", "source", "pin_type"]
        else:
            keys = []
    else:
        keys = ["name", "id", "version", "available", "source"] if col_count >= 5 else ["name", "id", "version", "source"]

    if not keys:
        return {}

    values = fields[:len(keys)]
    # Pad with empty strings for trailing missing columns
    while len(values) < len(keys):
        values.append("")
    row = dict(zip(keys, [str(v or "").strip() for v in values]))
    if "explicit" in row:
        row["explicit"] = str(row["explicit"]).strip().lower() == "true"

    row["source"] = _clean_source_field(row.get("source", ""))
    row["version"] = _clean_version_field(row.get("version", ""), row.get("source", ""))
    if "available" in row:
        row["available"] = _clean_version_field(row.get("available", ""), row.get("source", ""))

    return row


def parse_field_value_table(output: str) -> dict:
    text = str(output or "").replace("\ufeff", "")
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if not lines:
        return {}

    header_idx = -1
    for idx, line in enumerate(lines):
        if re.match(r"^\s*-{3,}\s*$", line):
            header_idx = idx - 1
            break
    if header_idx < 0:
        return {}

    header_line = lines[header_idx]
    parts = list(re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|\s*$)", header_line))
    if len(parts) < 2:
        return {}

    split_at = parts[1].start()
    data = {}
    for line in lines[header_idx + 2:]:
        key = line[:split_at].strip()
        value = line[split_at:].strip()
        if key:
            data[key] = value
    return data


def parse_json_line(output: str) -> dict:
    text = str(output or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


_VERSION_FROM_NAME_RE = re.compile(
    r"(?:\s|^)[vV]?(\d+\.\d+(?:\.\d+)*(?:[.\-_][a-zA-Z0-9]+)*)(?:\s|$)"
)


def extract_version_from_name(name: str) -> str:
    """Try to extract a version number embedded in the package display name."""
    text = str(name or "").strip()
    if not text:
        return ""
    matches = _VERSION_FROM_NAME_RE.findall(text)
    if not matches:
        return ""
    candidates = [
        m for m in matches
        if re.search(r"\d", m) and not re.match(r"^\d{1,2}$", m)
    ]
    candidates.sort(key=lambda v: len(v.split(".")), reverse=True)
    return candidates[0] if candidates else ""


def _parse_version_tuple(version: str) -> tuple:
    """Parse a version string into a comparable tuple of ints."""
    v = str(version or "").strip().lstrip("vV>≥").strip()
    parts = re.split(r"[.\-_]", v)
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    return tuple(result)


def versions_equivalent(a: str, b: str) -> bool:
    """Compare two version strings ignoring leading v/V and trailing noise."""
    if not a or not b:
        return False
    return _parse_version_tuple(a) == _parse_version_tuple(b)


def build_package_key(pkg_id: str, name: str, source: str = "") -> str:
    primary = str(pkg_id or "").strip()
    if primary:
        return primary.lower()
    combo = f"{name}|{source}"
    return combo.strip().lower()


def build_search_blurb(row: dict) -> str:
    parts = []
    pkg_id = str(row.get("id", "")).strip()
    source = str(row.get("source", "")).strip()
    match = str(row.get("match", "")).strip()
    if pkg_id:
        parts.append(pkg_id)
    if source:
        parts.append(source)
    if match:
        parts.append(f"match: {match}")
    return " | ".join(parts)


_UNINSTALL_CACHE = None

def _get_uninstall_map():
    global _UNINSTALL_CACHE
    if _UNINSTALL_CACHE is not None:
        return _UNINSTALL_CACHE
    
    try:
        import winreg
    except ImportError:
        return {}
        
    res = {}
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_READ | winreg.KEY_WOW64_32KEY, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, winreg.KEY_READ | winreg.KEY_WOW64_32KEY, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for root, flags, path in roots:
        try:
            key = winreg.OpenKey(root, path, access=flags)
        except OSError:
            continue
        idx = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, idx)
                with winreg.OpenKey(key, subkey_name, access=flags) as sub:
                    try:
                        disp = str(winreg.QueryValueEx(sub, "DisplayName")[0] or "").strip()
                    except OSError:
                        idx += 1
                        continue
                    
                    loc = ""
                    for val_name in ("InstallLocation", "DisplayIcon", "UninstallString"):
                        try:
                            val = str(winreg.QueryValueEx(sub, val_name)[0] or "").strip()
                            if val:
                                val = val.strip('"')
                                if os.path.isfile(val):
                                    val = os.path.dirname(val)
                                if os.path.isdir(val) or val:
                                    loc = val
                                    break
                        except OSError:
                            continue
                    
                    if disp:
                        res[disp.lower()] = loc
                    res[subkey_name.lower()] = loc
                idx += 1
            except OSError:
                break
        winreg.CloseKey(key)
    
    _UNINSTALL_CACHE = res
    return res

def find_uninstall_location(package_name: str, package_id: str = "") -> str:
    un_map = _get_uninstall_map()
    name_lower = str(package_name or "").strip().lower()
    id_lower = str(package_id or "").strip().lower()
    
    if name_lower in un_map:
        return un_map[name_lower]
    if id_lower in un_map:
        return un_map[id_lower]
    
    # Fallback for partial matches
    for k, v in un_map.items():
        if name_lower and (name_lower in k or k in name_lower):
            return v
            
    return ""
