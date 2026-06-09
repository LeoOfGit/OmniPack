import os
import shutil
from PySide6.QtCore import Signal

from core.manager_base import Environment, Package, PackageManager
from core.network_proxy import normalize_proxy_settings
from core.winget_helpers import (
    _parse_version_tuple,
    build_package_key,
    build_winget_command,
    extract_version_from_name,
    find_winget_executable,
    get_winget_version,
    is_default_source,
    parse_winget_table,
    versions_equivalent,
    find_uninstall_location,
)
from managers.base_worker import BaseCmdWorker


def _winget_settings_snapshot(config_mgr) -> dict:
    settings = getattr(config_mgr.config, "winget_settings", {}) or {}
    return {
        "enabled": True,
        "auto_refresh_on_start": True,
        "include_unknown_versions": True,
        "show_pinned_updates": True,
        "default_source": "",
        "default_scope": "machine",
        "install_mode": str(settings.get("install_mode", "silent") or "silent").strip().lower(),
        "winget_path": str(settings.get("winget_path", "") or "").strip(),
    }

class WingetScanWorker(BaseCmdWorker):
    env_scanned = Signal(Environment)

    # Global cache to prevent redundant scans when System and User environments are refreshed together
    _last_global_scan_time = 0.0
    _last_global_scan_data = None  # Tuple[list[dict], dict]

    def __init__(self, env: Environment, settings: dict, proxy_settings=None):
        super().__init__()
        self.env = env
        self.settings = settings
        self.proxy_settings = proxy_settings or {}
        p = normalize_proxy_settings(self.proxy_settings)
        self.proxy_url = p["https_proxy"] or p["http_proxy"] if p["enabled"] and p["targets"].get("winget") else ""

    def _capture_rows(self, cmd: list[str], mode: str, timeout: float = 25.0) -> list[dict]:
        result = self._run_command(cmd, capture_output=True, stream_stdout=False, stream_stderr=False, timeout=timeout)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        
        if "Failed when opening source(s)" in stdout or "Failed when opening source(s)" in stderr:
            self._log("WinGet error: Failed to connect to sources. Try running 'winget source reset --force' in an admin terminal.", "error")
            # If it's a source error, the output is likely garbage/empty
            return []

        if result.returncode != 0:
            stderr_strip = stderr.strip()
            if stderr_strip:
                self._log(stderr_strip, "stderr")
            return []
        
        rows = parse_winget_table(stdout, mode=mode)
        if not rows and stdout and stdout.strip():
            # Debug logging for empty results from non-empty output
            sample = stdout[:500].replace("\n", " ")
            self._log(f"Debug: Winget [code={result.returncode}] output no rows parsed. Raw sample: {sample}", "stderr")
        elif not rows:
             self._log(f"Debug: Winget [code={result.returncode}] returned completely empty output.", "stderr")
        return rows

    def run(self):
        try:
            winget = find_winget_executable(self.settings.get("winget_path", ""))
            if not winget:
                self._log("winget was not found on PATH.", "error")
                self.env.packages = []
                self.env.dep_graph = {}
                self.env.is_scanned = True
                self.env_scanned.emit(self.env)
                return

            import time
            now = time.monotonic()
            
            # Use cached results if available and fresh (within 30 seconds)
            if WingetScanWorker._last_global_scan_data and (now - WingetScanWorker._last_global_scan_time < 30):
                installed_rows, visible_update_map = WingetScanWorker._last_global_scan_data
                self._log("Using cached WinGet scan results.", "system")
            else:
                # Consolidate scans into one 'all' list to avoid missing packages and reduce lagginess
                # We remove --scope and use "all" to ensure we see every package installed on the system.
                installed_rows = self._capture_rows(
                    build_winget_command(
                        "list",
                        source_name=self.settings.get("default_source", ""),
                        scope_value="all", 
                        count=1000,
                        winget_path=self.settings.get("winget_path", ""),
                        proxy_url=self.proxy_url,
                    ),
                    mode="installed",
                )

                # We fetch the 'upgrade-available' list (without --include-pinned) to detect which 
                # updates are being blocked by a pin.
                visible_updates = self._capture_rows(
                    build_winget_command(
                        "list",
                        "--upgrade-available",
                        source_name=self.settings.get("default_source", ""),
                        scope_value="all",
                        include_unknown=self.settings.get("include_unknown_versions", False),
                        count=1000,
                        winget_path=self.settings.get("winget_path", ""),
                        proxy_url=self.proxy_url,
                    ),
                    mode="installed",
                )

                visible_update_map = {
                    build_package_key(row.get("id", ""), row.get("name", ""), row.get("source", "")): row
                    for row in visible_updates
                }
                
                
                # Update cache
                WingetScanWorker._last_global_scan_data = (installed_rows, visible_update_map)
                WingetScanWorker._last_global_scan_time = now

            # Check if Winget itself has an update available
            app_installer_update = None
            for key, row in visible_update_map.items():
                if "microsoft.appinstaller" in key or "microsoft.desktopappinstaller" in key:
                    app_installer_update = row
                    break
            
            if app_installer_update:
                self.env.runtime_has_update = True
                self.env.runtime_latest_version = str(app_installer_update.get("available", "")).strip()
            else:
                self.env.runtime_has_update = False

            from core.winget_helpers import get_non_removable_uwp_packages, get_provisioned_uwp_packages
            provisioned_map = get_provisioned_uwp_packages(include_all=False)
            all_staged_map = get_provisioned_uwp_packages(include_all=True)
            non_rem_sets = get_non_removable_uwp_packages()

            packages = []
            package_map = {}
            seen_keys = set()
            user_profile = os.environ.get("USERPROFILE", "").lower()
            scanned_uwp_ids = set()
            installed_uwp_families = set()
            installed_uwp_details = {}
            installed_uwp_non_removable = set()
            seen_arp_keys = set()
            try:
                import subprocess
                cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Get-AppxPackage | ForEach-Object { '{0};{1};{2};{3}' -f $_.PackageFamilyName, $_.NonRemovable, $_.Version, $_.InstallLocation }"]
                out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if ";" in line:
                        parts = line.split(";")
                        if len(parts) >= 4:
                            family = parts[0].strip().lower()
                            non_rem_val = parts[1].strip().lower()
                            ver_val = parts[2].strip()
                            loc_val = parts[3].strip()
                            if family:
                                installed_uwp_families.add(family)
                                installed_uwp_details[family] = {
                                    "version": ver_val,
                                    "location": loc_val,
                                    "non_removable": non_rem_val in ("true", "1")
                                }
                                if non_rem_val in ("true", "1"):
                                    installed_uwp_non_removable.add(family)
            except Exception:
                pass


            for row in installed_rows:
                pkg_name = str(row.get("name", "")).strip()
                pkg_id = str(row.get("id", "")).strip()
                current_version = str(row.get("version", "")).strip()
                available_version = str(row.get("available", "")).strip()
                source_name = str(row.get("source", "")).strip()
                if not pkg_name and not pkg_id:
                    continue

                version_was_unknown = current_version.lower() in {"unknown", ""}
                if version_was_unknown:
                    current_version = extract_version_from_name(pkg_name) or current_version

                key = build_package_key(pkg_id, pkg_name, source_name)
                
                # Deduplicate exact matches (same ID, Source, and Version)
                dedup_key = f"{key}|{current_version}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                # Extract architecture from IDs to distinguish variants in the UI
                import re
                arch_match = re.search(r'(?:^|[._\-\\])(x64|x86|arm64|arm)(?:[._\-\\]|$)', pkg_id, re.IGNORECASE)
                if arch_match and pkg_name:
                    arch_str = arch_match.group(1).lower()
                    # Only append if not already in the name
                    if arch_str not in pkg_name.lower():
                        pkg_name = f"{pkg_name} ({arch_str})"
                
                # An update exists if 'available' is set in the full list
                has_update = bool(available_version)
                latest_version = available_version
                
                # A pin is considered blocking if an update exists in the full list 
                # but it's NOT in the 'visible_updates' list.
                has_blocking_pin = has_update and (key not in visible_update_map)
                
                # If it's in visible_updates, use that for latest_version as it's more definitive
                if key in visible_update_map:
                    visible_row = visible_update_map[key]
                    latest_version = str(visible_row.get("available", "")).strip() or latest_version
                    has_update = True

                newer_than_server = False
                if has_update and not has_blocking_pin and current_version and latest_version:
                    cur_tup = _parse_version_tuple(current_version)
                    lat_tup = _parse_version_tuple(latest_version)
                    if cur_tup == lat_tup:
                        has_update = False
                    elif cur_tup > lat_tup:
                        has_update = False
                        newer_than_server = True

                s_lower = str(source_name or "").strip().lower()
                if s_lower == "winget":
                    prefix_code = "[w]"
                    prefix_html = '<span style="color: #29b6f6; font-weight: bold;">[W]</span>'
                elif s_lower == "msstore":
                    prefix_code = "[s]"
                    prefix_html = '<span style="color: #66bb6a; font-weight: bold;">[S]</span>'
                else:
                    prefix_code = "[l]"
                    prefix_html = '<span style="color: #ffa726; font-weight: bold;">[L]</span>'

                badges = []
                if source_name and not is_default_source(source_name):
                    badges.append({"text": f"[{source_name}]", "tooltip": f"Source: {source_name}"})
                if version_was_unknown and current_version.lower() in {"unknown", ""}:
                    badges.append({"text": "[Unknown]", "tooltip": "Installed version is not known to winget."})
                if has_blocking_pin:
                    badges.append({"text": "[Pinned]", "tooltip": "Update is blocked by a winget pin."})
                if newer_than_server:
                    badges.append({"text": "[⚠ Newer]", "tooltip": "Installed version is newer than the winget registry. Downgrading is not recommended."})

                # Determine scope / location (system vs user)
                loc = find_uninstall_location(pkg_name, pkg_id)
                
                # ARP Deduplication: prevent showing duplicate classic Win32 apps due to registry aliases
                is_arp = pkg_id.upper().startswith("ARP\\") or not source_name
                if is_arp:
                    import re
                    # Look for GUID in ID or Location
                    guid_match = re.search(r'\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}', pkg_id + "|" + loc)
                    guid = guid_match.group(0).lower() if guid_match else None
                    if guid:
                        arp_dedup_key = f"guid:{guid}"
                    else:
                        clean_name = pkg_name.lower().replace(" (x64)", "").replace(" (x86)", "").replace(" (arm64)", "").strip()
                        arp_dedup_key = f"name:{clean_name}|ver:{current_version}"
                    
                    if arp_dedup_key in seen_arp_keys:
                        continue
                    seen_arp_keys.add(arp_dedup_key)

                location = "system"
                
                # Check if UWP / MSIX
                is_uwp = pkg_id.upper().startswith("MSIX\\") or pkg_id.lower() == "microsoft.appinstaller"
                if is_uwp:
                    badges.append({"text": "[MSIX]", "tooltip": "Modern App Package (MSIX/Appx)"})
                    
                    pkg_id_lower = pkg_id.lower()
                    if pkg_id_lower.startswith("msix\\"):
                        parts = pkg_id_lower[5:].split("_")
                        base_name = parts[0] if parts else ""
                    else:
                        base_name = pkg_id_lower
                        
                    if base_name == "microsoft.appinstaller":
                        base_name = "microsoft.desktopappinstaller"
                        
                    match_key = f"msix\\{base_name}"
                    
                    scanned_uwp_ids.add(match_key)
                    
                    if (pkg_id_lower in all_staged_map) or (match_key in all_staged_map):
                        # UWP registered for user AND provisioned in system HKLM
                        location = "system_and_user"
                    else:
                        location = "user"
                else:
                    if pkg_id.upper().startswith("ARP\\"):
                        badges.append({"text": "[Win32]", "tooltip": "Classic Desktop App (Registry)"})
                    
                    # Traditional apps location check
                    if loc:
                        loc_lower = loc.lower()
                        if "\\package cache\\" in loc_lower:
                            location = "system"
                        elif user_profile and loc_lower.startswith(user_profile):
                            location = "user"
                        elif loc_lower.startswith("c:\\users\\"):
                            location = "user"
                        else:
                            location = "system"

                # Check if it is Python and physically in Program Files, treat it as a system installation
                is_system_python = False
                if "python.python.3.13" in pkg_id.lower() and os.path.exists("C:\\Program Files\\Python313"):
                    is_system_python = True
                elif "python.python.3.14" in pkg_id.lower() and os.path.exists("C:\\Program Files\\Python314"):
                    is_system_python = True
                if is_system_python:
                    location = "system"

                non_removable = False
                pkg_id_lower = pkg_id.lower()
                if is_uwp:
                    parts = pkg_id_lower[5:].split("_")
                    clean_id = parts[0] if parts else pkg_id_lower[5:]
                    family_lower = pkg_id_lower[5:]
                    
                    if (clean_id in non_rem_sets or 
                        family_lower in installed_uwp_non_removable or 
                        clean_id in installed_uwp_non_removable):
                        non_removable = True
                else:
                    clean_id = pkg_id_lower
                    if clean_id in non_rem_sets:
                        non_removable = True
                
                # Fallback check for winget core management packages
                if any(core_id in pkg_id_lower for core_id in {"microsoft.appinstaller", "microsoft.desktopappinstaller"}):
                    non_removable = True

                metadata = {
                    "manager": "winget",
                    "target_id": pkg_id or pkg_name,
                    "package_id": pkg_id,
                    "scope": location,
                    "installed_scope": location,
                    "location": location,
                    "source": source_name,
                    "display_name": f"{prefix_html} {pkg_name or pkg_id}",
                    "search_text": " ".join(part for part in [prefix_code, pkg_id, source_name, current_version, latest_version] if part),
                    "badges": badges,
                    "supports_config": True,
                    "can_update": not has_blocking_pin,
                    "update_blocked_reason": "Pinned by winget" if has_blocking_pin else "",
                    "pinned_blocking": has_blocking_pin,
                    "pin_state_known": has_blocking_pin,
                    "newer_than_server": newer_than_server,
                    "non_removable": non_removable,
                }
                description_parts = []
                if pkg_id:
                    description_parts.append(pkg_id)
                if source_name:
                    description_parts.append(source_name)
                description = " | ".join(description_parts)

                pkg = Package(
                    name=pkg_name or pkg_id,
                    version=current_version or "?",
                    latest_version=latest_version,
                    description=description,
                    has_update=has_update,
                    metadata=metadata,
                )
                packages.append(pkg)
                package_map[pkg.norm_name] = pkg

            # Inject provisioned UWP applications that remain on the system (both installed and staged)
            for cached_id, cached_info in provisioned_map.items():
                if cached_id in scanned_uwp_ids:
                    # Already handled in winget list
                    continue
                    
                basename = cached_id[5:] if cached_id.startswith("msix\\") else cached_id
                
                # Check if it is currently registered (installed) for the user
                is_installed = False
                matched_family = None
                for family in installed_uwp_families:
                    if family.startswith(basename + "_") or family == basename:
                        is_installed = True
                        matched_family = family
                        break
                        
                name = cached_info["name"]
                source_name = cached_info["source"]
                s_lower = str(source_name or "").strip().lower()
                if s_lower == "winget":
                    prefix_code = "[w]"
                    prefix_html = '<span style="color: #29b6f6; font-weight: bold;">[W]</span>'
                elif s_lower == "msstore":
                    prefix_code = "[s]"
                    prefix_html = '<span style="color: #66bb6a; font-weight: bold;">[S]</span>'
                else:
                    prefix_code = "[l]"
                    prefix_html = '<span style="color: #ffa726; font-weight: bold;">[L]</span>'
                
                if is_installed:
                    # It is installed, but winget list missed it. Add it as installed.
                    details = installed_uwp_details.get(matched_family, {})
                    version = details.get("version", "") or "?"
                    loc = details.get("location", "")
                    non_removable = details.get("non_removable", False)
                    
                    # If loc is empty, fallback to finding it
                    if not loc:
                        from core.winget_helpers import find_uwp_manifest_path
                        manifest = find_uwp_manifest_path(cached_id)
                        if manifest:
                            loc = os.path.dirname(manifest)
                    
                    badges = [{"text": "[MSIX]", "tooltip": "Modern App Package (MSIX/Appx)"}]
                    if source_name and not is_default_source(source_name):
                        badges.append({"text": f"[{source_name}]", "tooltip": f"Source: {source_name}"})

                    metadata = {
                        "manager": "winget",
                        "target_id": cached_id,
                        "package_id": cached_id,
                        "scope": "system",
                        "installed_scope": "system",
                        "location": loc or "system",
                        "source": source_name,
                        "display_name": f"{prefix_html} {name}",
                        "search_text": " ".join(part for part in [prefix_code, cached_id, source_name, version] if part),
                        "badges": badges,
                        "supports_config": True,
                        "can_update": False,
                        "newer_than_server": False,
                        "non_removable": non_removable,
                    }
                    
                    pkg = Package(
                        name=name,
                        version=version,
                        latest_version="",
                        description=cached_id,
                        has_update=False,
                        is_missing=False,
                        metadata=metadata,
                    )
                    packages.append(pkg)
                    package_map[pkg.norm_name] = pkg
                else:
                    # Not installed (Staged state)
                    badges = [
                        {"text": "[MSIX]", "tooltip": "Modern App Package (MSIX/Appx)"},
                        {"text": "[Staged]", "tooltip": "Provisioned in system but not registered for you."}
                    ]
                    if source_name and not is_default_source(source_name):
                        badges.append({"text": f"[{source_name}]", "tooltip": f"Source: {source_name}"})

                    metadata = {
                        "manager": "winget",
                        "target_id": cached_id,
                        "package_id": cached_id,
                        "scope": "system",
                        "installed_scope": "system",
                        "location": "system",
                        "source": source_name,
                        "display_name": f"{prefix_html} {name}",
                        "search_text": " ".join(part for part in [prefix_code, cached_id, source_name] if part),
                        "badges": badges,
                        "supports_config": False,
                        "can_update": False,
                        "newer_than_server": False,
                        "non_removable": False,
                    }
                    
                    pkg = Package(
                        name=name,
                        version="",
                        latest_version="",
                        description=cached_id,
                        has_update=False,
                        is_missing=True,
                        metadata=metadata,
                    )
                    packages.append(pkg)
                    package_map[pkg.norm_name] = pkg

            packages.sort(key=lambda item: (not item.has_update, item.name.lower()))
            self.env.raw_packages = list(packages)
            self.env.raw_dep_graph = dict(package_map)
            self.env.packages = packages
            self.env.dep_graph = package_map
            self.env.is_scanned = True
        except Exception as exc:
            self._log(f"WinGet scan error: {exc}", "error")
            self.env.packages = []
            self.env.dep_graph = {}
            self.env.is_scanned = True
        finally:
            self.env_scanned.emit(self.env)
            self._flush_logs()


class WingetSingleActionWorker(BaseCmdWorker):
    def __init__(self, cmd: list[str], proxy_settings=None, fallback_cmd: list[str] = None):
        super().__init__()
        self.cmd = cmd
        self.fallback_cmd = fallback_cmd
        self.proxy_settings = proxy_settings or {}

    def run(self):
        try:
            result = self._run_command(self.cmd)
            if result.returncode == 0:
                self.success = True
                return

            if self.fallback_cmd:
                self._log("Primary scope failed, retrying with alternate scope...", "stderr")
                alt_result = self._run_command(self.fallback_cmd)
                if alt_result.returncode == 0:
                    self.success = True
                    return

            is_upgrade = len(self.cmd) > 1 and self.cmd[1] == "upgrade"
            if is_upgrade:
                self._log("Upgrade failed on both scopes. Retrying as 'winget install --scope user' to bypass scope mismatch lock...", "stderr")
                install_cmd = list(self.cmd)
                install_cmd[1] = "install"
                try:
                    scope_idx = install_cmd.index("--scope")
                    if scope_idx + 1 < len(install_cmd):
                        install_cmd[scope_idx + 1] = "user"
                except ValueError:
                    install_cmd.extend(["--scope", "user"])
                
                install_result = self._run_command(install_cmd)
                self.success = install_result.returncode == 0
            else:
                self.success = False
        except Exception as exc:
            self.success = False
            self._log(f"WinGet command failed: {exc}", "error")
        finally:
            self._flush_logs()


class WingetBatchUpdateWorker(BaseCmdWorker):
    def __init__(self, package_specs: list[dict], settings: dict, proxy_settings=None):
        super().__init__()
        self.package_specs = package_specs
        self.settings = settings
        self.proxy_settings = proxy_settings or {}
        p = normalize_proxy_settings(self.proxy_settings)
        self.proxy_url = p["https_proxy"] or p["http_proxy"] if p["enabled"] and p["targets"].get("winget") else ""

    def run(self):
        overall = True
        try:
            for spec in self.package_specs:
                pkg_id = str(spec.get("package_id", "") or spec.get("target_id", "") or spec.get("name", "")).strip()
                if not pkg_id:
                    continue
                cmd = build_winget_command(
                    "upgrade",
                    "--id",
                    pkg_id,
                    source_name=spec.get("source", "") or self.settings.get("default_source", ""),
                    scope_value=self.settings.get("default_scope", "all"),
                    install_mode=self.settings.get("install_mode", "default"),
                    accept_package_agreements=True,
                    exact=True,
                    winget_path=self.settings.get("winget_path", ""),
                    proxy_url=self.proxy_url,
                )
                result = self._run_command(cmd)
                if result.returncode != 0:
                    overall = False
            self.success = overall
        except Exception as exc:
            self.success = False
            self._log(f"WinGet batch update error: {exc}", "error")
        finally:
            self._flush_logs()


class WingetPinStateWorker(BaseCmdWorker):
    pin_state_ready = Signal(str, bool)  # package_id, is_pinned

    def __init__(self, package_id: str, proxy_settings=None, winget_path: str = ""):
        super().__init__()
        self.package_id = package_id
        self.proxy_settings = proxy_settings or {}
        self.winget_path = winget_path
        p = normalize_proxy_settings(self.proxy_settings)
        self.proxy_url = p["https_proxy"] or p["http_proxy"] if p["enabled"] and p["targets"].get("winget") else ""

    def run(self):
        is_pinned = False
        try:
            cmd = build_winget_command(
                "pin", "list", "--id", self.package_id, exact=True,
                winget_path=self.winget_path, proxy_url=self.proxy_url
            )
            result = self._run_command(cmd, capture_output=True, stream_stdout=False, stream_stderr=False)
            rows = parse_winget_table(result.stdout, mode="pin")
            is_pinned = bool(rows)
            self.success = result.returncode == 0
        except Exception as exc:
            self.success = False
            self._log(f"Failed to query winget pin state: {exc}", "error")
        finally:
            self.pin_state_ready.emit(self.package_id, is_pinned)
            self._flush_logs()


class WingetManager(PackageManager):
    log_msg = Signal(str, str)
    log_batch = Signal(list)
    update_done = Signal(str, str, bool)          # env_path, package_id, success
    batch_update_done = Signal(str, list, bool)   # env_path, package_specs, success
    remove_done = Signal(str, str, bool)          # env_path, package_id, success
    install_done = Signal(str, str, bool)         # env_path, package_ref, success
    pin_done = Signal(str, str, bool, bool)       # env_path, package_id, success, enabled
    pin_state_ready = Signal(str, str, bool)      # env_path, package_id, is_pinned

    def __init__(self, config_mgr):
        super().__init__()
        self.config_mgr = config_mgr
        self._active_workers = []
        self._load_envs()

    def _load_envs(self):
        if os.name != "nt":
            self.environments = []
            return
        old_envs = {env.path: env for env in self.environments}
        all_env = old_envs.get("winget://all") or Environment(
            path="winget://all",
            name="Applications",
            type="winget",
        )
        all_env.runtime_name = "winget"
        all_env.tags = ["system", "winget"]
        
        winget_ver = get_winget_version(self._current_settings().get("winget_path", ""))
        all_env.runtime_version = winget_ver
        
        self.environments = [all_env]

    def reload_envs(self):
        self._load_envs()

    @staticmethod
    def invalidate_scan_cache():
        WingetScanWorker._last_global_scan_time = 0.0
        WingetScanWorker._last_global_scan_data = None

    def _current_settings(self) -> dict:
        return _winget_settings_snapshot(self.config_mgr)

    def _proxy_settings(self) -> dict:
        return getattr(self.config_mgr.config, "proxy_settings", {}) or {}

    def _get_proxy_url(self) -> str:
        p = normalize_proxy_settings(self._proxy_settings())
        return p["https_proxy"] or p["http_proxy"] if p["enabled"] and p["targets"].get("winget") else ""

    @staticmethod
    def _resolve_scope(env: Environment, package_spec: dict, fallback_scope: str = "all") -> str:
        pkg_id = str(package_spec.get("package_id", "")).strip().lower()
        is_uwp = pkg_id.startswith("msix\\")
        
        inst_scope = str(package_spec.get("installed_scope", "")).strip().lower()
        spec_scope = str(package_spec.get("scope", "")).strip().lower()
        
        # 1. If explicitly requesting system/machine scope
        if inst_scope in {"system", "machine"} or spec_scope in {"system", "machine"}:
            return "machine"
            
        # 2. For UWP packages, default to 'user' scope for user registration/unregistration
        if is_uwp:
            return "user"
            
        # 3. Traditional Win32 environment-based checks
        if inst_scope in {"user", "machine"}:
            return inst_scope
        if spec_scope in {"user", "machine"}:
            return spec_scope
            
        env_scope = str(getattr(env, "type", "") or "").strip().lower()
        if env_scope in {"user", "machine"}:
            return env_scope
        return fallback_scope

    def _on_env_scanned(self, env: Environment):
        for idx, item in enumerate(self.environments):
            if item.path == env.path:
                self.environments[idx] = env
                break
        self.env_scanned.emit(env)

    def scan_environment(self, env: Environment):
        if not getattr(env, "is_scanned", False):
            self.invalidate_scan_cache()
        worker = WingetScanWorker(env, self._current_settings(), proxy_settings=self._proxy_settings())
        worker.env_scanned.connect(self._on_env_scanned)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._active_workers.remove(worker) if worker in self._active_workers else None)
        worker.start()

    def _start_action_worker(self, worker, on_finished):
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        self._active_workers.append(worker)
        def _on_finished():
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            on_finished()

        worker.finished.connect(_on_finished)
        worker.start()

    def build_update_fallback_install_command(self, env: Environment, package_spec: dict) -> list[str]:
        pkg_id = str(package_spec.get("package_id", "") or package_spec.get("target_id", "") or package_spec.get("name", "")).strip()
        scope = self._resolve_scope(env, package_spec, self._current_settings().get("default_scope", "all"))
        return build_winget_command(
            "install",
            "--id",
            pkg_id,
            source_name=package_spec.get("source", "") or self._current_settings().get("default_source", ""),
            scope_value=scope,
            install_mode=self._current_settings().get("install_mode", "default"),
            accept_package_agreements=True,
            exact=True,
            winget_path=self._current_settings().get("winget_path", ""),
            proxy_url=self._get_proxy_url(),
        )

    def build_update_command(self, env: Environment, package_spec: dict) -> list[str]:
        pkg_id = str(package_spec.get("package_id", "") or package_spec.get("target_id", "") or package_spec.get("name", "")).strip()
        scope = self._resolve_scope(env, package_spec, self._current_settings().get("default_scope", "all"))
        cmd = build_winget_command(
            "upgrade",
            "--id",
            pkg_id,
            source_name=package_spec.get("source", "") or self._current_settings().get("default_source", ""),
            scope_value=scope,
            install_mode=self._current_settings().get("install_mode", "default"),
            accept_package_agreements=True,
            exact=True,
            winget_path=self._current_settings().get("winget_path", ""),
            proxy_url=self._get_proxy_url(),
        )
        return cmd

    def build_remove_command(self, env: Environment, package_spec: dict) -> list[str]:
        pkg_id = str(package_spec.get("package_id", "") or package_spec.get("target_id", "") or package_spec.get("name", "")).strip()
        scope = self._resolve_scope(env, package_spec, self._current_settings().get("default_scope", "all"))
        cmd = build_winget_command(
            "uninstall",
            "--id",
            pkg_id,
            source_name=package_spec.get("source", "") or self._current_settings().get("default_source", ""),
            scope_value=scope,
            install_mode=self._current_settings().get("install_mode", "default"),
            accept_package_agreements=False,
            exact=True,
            winget_path=self._current_settings().get("winget_path", ""),
            proxy_url=self._get_proxy_url(),
        )
        return cmd

    def build_install_command(self, env: Environment, package_ref: str) -> list[str]:
        pkg_ref = str(package_ref or "").strip()
        
        # Parse scope suffix if present (e.g. "MSIX\Microsoft.WindowsCamera:user")
        pkg_id = pkg_ref
        scope = ""
        if ":" in pkg_ref:
            parts = pkg_ref.split(":", 1)
            pkg_id = parts[0]
            scope = parts[1]
            
        package_spec = {
            "package_id": pkg_id,
            "scope": scope,
            "installed_scope": scope
        }
        
        resolved_scope = self._resolve_scope(env, package_spec, self._current_settings().get("default_scope", "all"))
        
        # Strip local virtual type prefixes (e.g. 'msix\' or 'arp\') to match online manifests
        clean_id = pkg_id
        if clean_id.lower().startswith("msix\\"):
            # Check for local staged manifest to run instant PowerShell local registration
            from core.winget_helpers import find_uwp_manifest_path
            manifest_path = find_uwp_manifest_path(pkg_id)
            if manifest_path:
                return [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    f"Add-AppxPackage -DisableDevelopmentMode -Register '{manifest_path}'"
                ]
            clean_id = clean_id[5:]
            resolved_scope = "user"
        elif clean_id.lower().startswith("arp\\"):
            clean_id = clean_id[4:]

        cmd = build_winget_command(
            "install",
            "--id",
            clean_id,
            source_name=self._current_settings().get("default_source", ""),
            scope_value=resolved_scope,
            install_mode=self._current_settings().get("install_mode", "default"),
            accept_package_agreements=True,
            exact=True,
            winget_path=self._current_settings().get("winget_path", ""),
            proxy_url=self._get_proxy_url(),
        )
        return cmd

    def set_pin_state(self, env: Environment, package_spec: dict, enabled: bool):
        pkg_id = str(package_spec.get("package_id", "") or package_spec.get("target_id", "") or package_spec.get("name", "")).strip()
        winget_path = self._current_settings().get("winget_path", "")
        proxy_url = self._get_proxy_url()
        if enabled:
            cmd = build_winget_command("pin", "add", "--id", pkg_id, "--blocking", exact=True, winget_path=winget_path, proxy_url=proxy_url)
        else:
            cmd = build_winget_command("pin", "remove", "--id", pkg_id, exact=True, winget_path=winget_path, proxy_url=proxy_url)
        worker = WingetSingleActionWorker(cmd, proxy_settings=self._proxy_settings())
        self._start_action_worker(worker, lambda: self.pin_done.emit(env.path, pkg_id, worker.success, enabled))

    def query_pin_state(self, env: Environment, package_id: str):
        worker = WingetPinStateWorker(package_id, proxy_settings=self._proxy_settings(), winget_path=self._current_settings().get("winget_path", ""))
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.pin_state_ready.connect(lambda pkg_id, is_pinned: self.pin_state_ready.emit(env.path, pkg_id, is_pinned))
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._active_workers.remove(worker) if worker in self._active_workers else None)
        worker.start()
