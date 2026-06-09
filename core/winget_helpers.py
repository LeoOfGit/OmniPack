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

    # 3. Try standard WindowsApps location which might be missing from PATH during UAC elevation
    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            fallback = os.path.join(local_appdata, "Microsoft", "WindowsApps", "winget.exe")
            if os.path.exists(fallback):
                return fallback
        
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
    if proxy_url:
        # Wrap proxy in quotes to ensure WinGet parses credentials (@, :) correctly
        cmd.extend(["--proxy", proxy_url])
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


def _sanitize_terminal_output(text: str) -> str:
    """Remove ANSI escapes and simulate terminal processing of \r and \b."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)
    
    lines = []
    for line in text.split('\n'):
        buf = []
        cursor = 0
        for char in line:
            if char == '\r':
                cursor = 0
            elif char == '\b':
                cursor = max(0, cursor - 1)
            elif char == '\t':
                spaces = 4 - (cursor % 4)
                buf.extend([' '] * spaces)
                cursor += spaces
            elif ord(char) < 32:
                # ignore other control characters
                pass
            else:
                if cursor >= len(buf):
                    buf.extend([' '] * (cursor - len(buf)))
                    buf.append(char)
                else:
                    buf[cursor] = char
                cursor += 1
        lines.append("".join(buf).rstrip())
    return "\n".join(lines)


def parse_winget_table(output: str, mode: str = "") -> list[dict]:
    """Parse winget's tabular output.

    Uses console display width to find the exact column start positions from the header,
    then slices each row using those fixed positions. This handles empty columns and
    variable column widths perfectly, correctly accounting for East-Asian characters.
    """
    text = str(output or "").replace("\ufeff", "")
    text = _sanitize_terminal_output(text)
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    header_idx = -1
    for idx, line in enumerate(lines):
        clean_line = line.strip()
        if clean_line.count('-') >= 5 and len(re.sub(r'[-\s]', '', clean_line)) < 5:
            header_idx = idx - 1
            break
            
    if header_idx < 0:
        # Ultimate fallback: Find the line with Name and Id
        for idx, line in enumerate(lines):
            if re.search(r'\b(Name|名称)\b', line, re.IGNORECASE) and re.search(r'\b(Id|ID)\b', line):
                header_idx = idx
                break

    if header_idx < 0 or header_idx >= len(lines):
        return []

    header_line = lines[header_idx]
    norm_header = _normalize_display_string(header_line.rstrip())
    
    # In installed and search modes, Winget headers are always single words (e.g. Name, Id, Version, Available, Source).
    # If the column content is exactly the same width as the header, Winget may pad with only 1 space.
    # Therefore, we simply split by any whitespace for these modes to avoid merging columns like "Available Source".
    if mode in ("installed", "search"):
        raw_matches = list(re.finditer(r"[^\s]+", norm_header))
    else:
        # Fallback for modes like "pin" where headers (e.g. "Pin type") contain spaces.
        raw_matches = list(re.finditer(r"(?!\s)[^\s].*?(?=\s{2,}|\Z)", norm_header))
        
    # Filter out spinner artifacts (e.g., `-`, `\`, `|`, `/`) by requiring at least one word character.
    col_matches = [m for m in raw_matches if re.search(r'\w', m.group(0))]

    if not col_matches:
        return []
    
    # If there was a garbage prefix (e.g., "   -    -    \ Name"), the true start of the first column
    # is shifted. We subtract this shift from all column starts so that the first column is mapped to index 0,
    # which accurately aligns with the data rows below the separator line.
    first_col_start = col_matches[0].start()
    col_starts = [max(0, m.start() - first_col_start) for m in col_matches]
    col_count = len(col_starts)

    rows = []
    # If we used the ultimate fallback, the data might start immediately after the header
    data_start_idx = header_idx + 2
    if data_start_idx < len(lines) and re.search(r'\b(Name|名称)\b', lines[data_start_idx - 1], re.IGNORECASE):
        # The line after header is data, not a separator
        data_start_idx = header_idx + 1

    for line in lines[data_start_idx:]:
        if re.match(r"^\s*(?:-+\s*)+$", line):
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
        if re.match(r"^\s*(?:-+\s*)+$", line):
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
    id_lower = str(package_id or "").strip().lower()
    
    # Check for UWP packages first to retrieve their dynamic WindowsApps staged/registered path
    is_uwp = id_lower.startswith("msix\\") or id_lower == "microsoft.appinstaller"
    if is_uwp:
        manifest = find_uwp_manifest_path(package_id)
        if manifest:
            return os.path.dirname(manifest)

    un_map = _get_uninstall_map()
    name_lower = str(package_name or "").strip().lower()
    
    if name_lower in un_map:
        return un_map[name_lower]
    if id_lower in un_map:
        return un_map[id_lower]
    
    # Fallback for partial matches
    for k, v in un_map.items():
        if name_lower and (name_lower in k or k in name_lower):
            return v
            
    return ""


_WINGET_VERSION_CACHE = None

def get_winget_version(winget_path: str = "") -> str:
    """Return the winget version string (e.g. 'v1.9.25200'), or empty string on failure."""
    global _WINGET_VERSION_CACHE
    if _WINGET_VERSION_CACHE is not None:
        return _WINGET_VERSION_CACHE
        
    winget = find_winget_executable(winget_path)
    if not winget:
        return ""
        
    import subprocess
    try:
        # Prevent showing a command window on Windows when calling winget
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        result = subprocess.run(
            [winget, "--version"], 
            capture_output=True, 
            text=True, 
            timeout=5,
            startupinfo=startupinfo
        )
        if result.returncode == 0:
            version_str = result.stdout.strip()
            _WINGET_VERSION_CACHE = version_str
            return version_str
    except Exception:
        pass
    return ""


_NON_REMOVABLE_UWP_CACHE = None

CORE_PROTECTED_UWP = {
    "microsoft.windowsstore",
    "microsoft.desktopappinstaller",
    "microsoft.appinstaller",
    "microsoft.microsoftedge",
    "microsoft.microsoftedge.stable",
    "microsoft.windows.shellexperiencehost",
    "microsoft.windows.startmenuexperiencehost",
    "windows.immersivecontrolpanel",
    "microsoft.accountscontrol",
    "microsoft.aad.brokerplugin",
    "microsoft.bioenrollment",
    "microsoft.creddialoghost",
    "microsoft.windows.contentdeliverymanager",
}

def get_non_removable_uwp_packages() -> set:
    """Query HKLM registry to read all system-protected, non-removable UWP packages without admin rights."""
    global _NON_REMOVABLE_UWP_CACHE
    if _NON_REMOVABLE_UWP_CACHE is not None:
        return _NON_REMOVABLE_UWP_CACHE
    
    res = set()
    registry_success = False
    
    try:
        import winreg
        path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\Applications"
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, access=winreg.KEY_READ)
        idx = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, idx)
                # subkey_name is PackageFullName like Microsoft.WindowsStore_22403.1401.9.0_x64__8wekyb3d8bbwe
                with winreg.OpenKey(key, subkey_name, access=winreg.KEY_READ) as sub:
                    try:
                        non_rem, _ = winreg.QueryValueEx(sub, "NonRemovable")
                        if non_rem == 1:
                            parts = subkey_name.split("_")
                            if parts:
                                res.add(parts[0].lower())
                    except OSError:
                        pass
                idx += 1
            except OSError:
                break
        winreg.CloseKey(key)
        registry_success = True
    except Exception:
        pass
        
    # Fallback to hardcoded list if registry query couldn't be executed at all or returned empty
    if not registry_success or not res:
        res = set(CORE_PROTECTED_UWP)
        
    _NON_REMOVABLE_UWP_CACHE = res
    return res


UWP_FRIENDLY_NAMES = {
    "microsoft.windowsstore": "Microsoft Store",
    "microsoft.windowscamera": "Windows Camera",
    "microsoft.windows.photos": "Microsoft Photos",
    "microsoft.paint": "Paint",
    "microsoft.windowscalculator": "Windows Calculator",
    "microsoft.screensketch": "Snipping Tool",
    "microsoft.microsoftstickynotes": "Microsoft Sticky Notes",
    "microsoft.xboxgamingoverlay": "Game Bar",
    "microsoft.xboxspeechtotextoverlay": "Game Speech Window",
    "microsoft.yourphone": "Phone Link",
    "microsoft.todos": "Microsoft To Do",
    "microsoft.powerautomatedesktop": "Power Automate",
    "microsoft.people": "Microsoft People",
    "microsoft.gethelp": "Get Help",
    "microsoft.gamingapp": "Xbox",
    "microsoft.bingweather": "Weather",
    "microsoft.bingnews": "News",
    "microsoft.copilot": "Microsoft Copilot",
    "microsoft.desktopappinstaller": "App Installer",
    "microsoft.windowsappruntime.cbs.1.8": "Windows App Runtime 1.8",
    "microsoft.windowsappruntime.cbs.1.6": "Windows App Runtime 1.6",
    "microsoft.windows.devhome": "Dev Home",
    "clipchamp.clipchamp": "Clipchamp",
    "msteams": "Microsoft Teams",
    "microsoft.zunevideo": "Movies & TV",
    "microsoft.zunemusic": "Media Player",
    "microsoft.windowsfeedbackhub": "Feedback Hub",
    "microsoft.windowsmaps": "Windows Maps",
    "microsoft.skypeapp": "Skype",
    "microsoft.onenote": "OneNote",
    "microsoft.office.onenote": "OneNote for Windows 10",
    "microsoft.3dbuilder": "3D Builder",
    "microsoft.microsoftsolitairecollection": "Microsoft Solitaire Collection",
}

CONSUMER_UWP_WHITELIST = set(UWP_FRIENDLY_NAMES.keys())


def detect_uwp_package_info(pkg_base_name: str, manifest_path: Optional[str]) -> tuple[bool, Optional[str]]:
    """Determine if a UWP package is a user-facing application and get its DisplayName.
    Returns (is_user_facing_app, display_name)."""
    import xml.etree.ElementTree as ET
    
    base_lower = pkg_base_name.lower()
    
    # Fallback/whitelist values
    fallback_name = UWP_FRIENDLY_NAMES.get(base_lower)
    is_whitelisted = base_lower in CONSUMER_UWP_WHITELIST
    
    if not manifest_path or not os.path.exists(manifest_path):
        return is_whitelisted, fallback_name
        
    manifest_lower = manifest_path.lower()
    if manifest_lower.startswith("c:\\windows") or "\\systemapps\\" in manifest_lower:
        return False, fallback_name

    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        ns = root.tag.split('}')[0] + '}' if '}' in root.tag else ''
        
        is_app = False
        display_name = None
        
        if "Bundle" in root.tag:
            packages_elem = root.find(f"./{ns}Packages")
            if packages_elem is not None:
                packages = packages_elem.findall(f"./{ns}Package")
                for p in packages:
                    if p.attrib.get('Type') == 'application':
                        is_app = True
                        break
        else:
            apps_elem = root.find(f"./{ns}Applications")
            if apps_elem is not None:
                apps = apps_elem.findall(f"./{ns}Application")
                if len(apps) > 0:
                    is_app = True

        # Try to read DisplayName from manifest
        props = root.find(f"./{ns}Properties")
        if props is not None:
            disp_elem = props.find(f"./{ns}DisplayName")
            if disp_elem is not None and disp_elem.text:
                text = disp_elem.text.strip()
                if text and not text.startswith("ms-resource:"):
                    display_name = text

        # Final decision on is_app
        final_is_app = is_app or is_whitelisted
        
        # Determine display name: use manifest plain text name, or fallback, or format base name
        final_name = display_name or fallback_name
        if not final_name:
            # Capitalize base name words nicely: e.g. "microsoft.windowscamera" -> "Windows Camera"
            clean_base = pkg_base_name
            if clean_base.lower().startswith("microsoft."):
                clean_base = clean_base[10:]
            words = clean_base.replace(".", " ").replace("_", " ").split()
            final_name = " ".join(w.capitalize() for w in words)
            
        return final_is_app, final_name
    except Exception:
        return is_whitelisted, fallback_name


_UWP_REG_PATHS = [
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\Applications",
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\InboxApplications",
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\Staged",
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\Frameworks",
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Appx\AppxAllUserStore\ResourcePackages",
]


def get_provisioned_uwp_packages(include_all: bool = False) -> dict:
    """Read all provisioned/staged UWP applications from HKLM registry to persist [sys] state even after user unregistration."""
    res = {}
    
    # Pre-seed res with friendly names of default consumer packages as fallback
    for base_lower, friendly_name in UWP_FRIENDLY_NAMES.items():
        winget_id = f"MSIX\\{base_lower}"
        res[winget_id.lower()] = {
            "name": friendly_name,
            "source": "msstore"
        }
        
    try:
        import winreg
    except ImportError:
        return res
        
    # Build a lookup map of base_name -> manifest_path in one pass
    manifest_map = {}
    path_apps = r"C:\Program Files\WindowsApps"
    
    for reg_path in _UWP_REG_PATHS:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path, access=winreg.KEY_READ)
            idx = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, idx)
                    subkey_lower = subkey_name.lower()
                    parts = subkey_lower.split("_")
                    if parts:
                        base = parts[0]
                        path_val = None
                        try:
                            with winreg.OpenKey(key, subkey_name, access=winreg.KEY_READ) as sub:
                                path_val, _ = winreg.QueryValueEx(sub, "Path")
                        except OSError:
                            pass
                            
                        if path_val:
                            manifest_map[base] = path_val
                        elif base not in manifest_map:
                            # Construct path
                            constructed = os.path.join(path_apps, subkey_name, "AppxManifest.xml")
                            manifest_map[base] = constructed
                    idx += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass

    # Now for each base, detect info
    for base, manifest_path in manifest_map.items():
        is_app, disp_name = detect_uwp_package_info(base, manifest_path)
        if include_all or is_app:
            winget_id = f"MSIX\\{base}"
            res[winget_id.lower()] = {
                "name": disp_name or UWP_FRIENDLY_NAMES.get(base, base),
                "source": "msstore"
            }
            
    return res


def find_uwp_manifest_path(pkg_id: str) -> Optional[str]:
    """Find the AppxManifest.xml absolute path for a staged UWP package by its ID."""
    clean_id = str(pkg_id or "").strip().lower()
    if clean_id.startswith("msix\\"):
        clean_id = clean_id[5:]
    if clean_id == "microsoft.appinstaller":
        clean_id = "microsoft.desktopappinstaller"
    
    # Extract base name to do a case-insensitive prefix match (e.g. "microsoft.windowscamera")
    base_name = clean_id.split("_")[0]
    path_apps = r"C:\Program Files\WindowsApps"
    
    # Strategy 1: Attempt direct WindowsApps folder scanning (if running elevated/accessible)
    try:
        if os.path.exists(path_apps):
            for entry in os.listdir(path_apps):
                entry_lower = entry.lower()
                if entry_lower.startswith(base_name + "_") or entry_lower == base_name:
                    manifest = os.path.join(path_apps, entry, "AppxManifest.xml")
                    if os.path.exists(manifest):
                        return manifest
    except Exception:
        pass
        
    # Strategy 2: Extract PackageFullName from registry (readable by non-admins)
    import winreg
    for reg_path in _UWP_REG_PATHS:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path, access=winreg.KEY_READ)
            idx = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, idx)
                    subkey_lower = subkey_name.lower()
                    if subkey_lower.startswith(base_name + "_") or subkey_lower.split("_")[0] == base_name:
                        # Try to read the "Path" value inside the subkey first
                        try:
                            with winreg.OpenKey(key, subkey_name, access=winreg.KEY_READ) as sub:
                                path_val, _ = winreg.QueryValueEx(sub, "Path")
                                if path_val:
                                    if path_val.lower().endswith(".xml"):
                                        return path_val
                                    else:
                                        return os.path.join(path_val, "AppxManifest.xml")
                        except OSError:
                            pass
                        
                        # Fallback to hardcoded C:\Program Files\WindowsApps path
                        manifest = os.path.join(path_apps, subkey_name, "AppxManifest.xml")
                        # Even if exists check fails due to permissions, return it since PowerShell has access
                        return manifest
                    idx += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass
            
    # Strategy 3: Query using PowerShell Get-AppxProvisionedPackage (non-elevated fallback)
    import subprocess
    try:
        keyword = base_name.split(".")[-1]
        cmd = [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            f"Get-AppxProvisionedPackage -Online | Where-Object {{$_.DisplayName -like '*{keyword}*' -or $_.PackageName -like '*{keyword}*'}} | Select-Object -ExpandProperty InstallLocation"
        ]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        if out:
            lines = [line.strip() for line in out.splitlines() if line.strip()]
            if lines:
                manifest = os.path.join(lines[0], "AppxManifest.xml")
                return manifest
    except Exception:
        pass
        
    return None

