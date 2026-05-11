"""
NpmManager — NPM backend for OmniPack using Environment-Centric architecture.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Optional

from PySide6.QtCore import Signal

from core.manager_base import PackageManager, Environment, Package
from core.network_proxy import merge_env_for_command
from core.npm_spec import has_explicit_tag
from core.runtime_update import (
    build_node_runtime_update_command,
    build_node_runtime_update_command_nvm,
    check_runtime_major_update,
    check_runtime_patch_update,
    parse_cycle,
    parse_node_version,
)
from core.source_profiles import NPM_OFFICIAL_REGISTRY
from managers.base_worker import BaseCmdWorker

CHANNEL_PATTERNS = {
    "nightly": re.compile(r"[-.@]nightly|nightly[-.]?", re.IGNORECASE),
    "preview": re.compile(r"[-.@]preview|preview[-.]?", re.IGNORECASE),
    "beta":    re.compile(r"[-.@]beta|beta[-.]?",       re.IGNORECASE),
    "canary":  re.compile(r"[-.@]canary|canary[-.]?",   re.IGNORECASE),
    "next":    re.compile(r"[-.@]next(?!\w)|next[-.]?",  re.IGNORECASE),
    "rc":      re.compile(r"[-.@]rc\d*|rc[-.]?",        re.IGNORECASE),
}
def resolve_npm_registry_url(config_mgr) -> Optional[str]:
    settings = getattr(config_mgr.config, "npm_settings", {}) or {}
    mode = str(settings.get("source_mode", "system")).strip().lower()
    if mode == "official":
        return NPM_OFFICIAL_REGISTRY
    if mode == "custom":
        url = str(settings.get("registry_url", "")).strip()
        if url:
            return url
    return None

def detect_channel(version: str) -> str:
    """Detect version channel from version string."""
    if not version:
        return "latest"
    for channel, pattern in CHANNEL_PATTERNS.items():
        if pattern.search(version):
            return channel
    return "latest"

class NpmBaseHelper:
    @classmethod
    def find_npm(cls) -> Optional[str]:
        cmd_names = ["npm.cmd", "npm"] if os.name == "nt" else ["npm"]
        for cmd in cmd_names:
            npm_path = shutil.which(cmd)
            if npm_path:
                return npm_path

        if os.name == "nt":
            system_paths = [
                os.path.expandvars(r"%ProgramFiles%\nodejs\npm.cmd"),
                os.path.expandvars(r"%ProgramFiles(x86)%\nodejs\npm.cmd"),
                os.path.expandvars(r"%APPDATA%\npm\npm.cmd"),
            ]
            for path in system_paths:
                if os.path.exists(path):
                    return path
        else:
            system_paths = [
                "/usr/local/bin/npm",
                "/opt/homebrew/bin/npm",
                "/usr/bin/npm"
            ]
            # Simple fallback expansions
            home = os.path.expanduser("~")
            nvm_path = os.path.join(home, ".nvm", "versions", "node")
            if os.path.exists(nvm_path):
                import glob
                matches = glob.glob(os.path.join(nvm_path, "*", "bin", "npm"))
                if matches:
                    return matches[0]

            for path in system_paths:
                if os.path.exists(path):
                    return path
                    
        return None

    @classmethod
    def find_node(cls, npm_path: Optional[str] = None) -> Optional[str]:
        cmd_names = ["node.exe", "node"] if os.name == "nt" else ["node"]
        for cmd in cmd_names:
            node_path = shutil.which(cmd)
            if node_path:
                return node_path

        # Fallback: try sibling to npm
        if npm_path:
            npm_dir = os.path.dirname(npm_path)
            candidate = os.path.join(npm_dir, "node.exe" if os.name == "nt" else "node")
            if os.path.exists(candidate):
                return candidate
        return None

    @classmethod
    def _probe_npm_output(cls, npm_path: str, args: list[str]) -> str:
        """Run a lightweight npm probe command and return stdout text."""
        try:
            cmd = [npm_path, *args]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return ""

    @classmethod
    def discover_user_node_modules(cls) -> list[str]:
        """
        Discover standalone user-level node_modules folders.
        Excludes npm global root (already represented by the Global card).
        """
        discovered = []
        seen = set()

        def _add_if_exists(path: str):
            if not path:
                return
            norm_path = os.path.normcase(os.path.normpath(path))
            if norm_path in seen:
                return
            if os.path.isdir(path):
                seen.add(norm_path)
                discovered.append(os.path.normpath(path))

        home = os.path.expanduser("~")
        _add_if_exists(os.path.join(home, "node_modules"))

        npm_path = cls.find_npm()
        if npm_path:
            # Some tools install by prefixing into user-writable folders.
            prefix_global = cls._probe_npm_output(npm_path, ["prefix", "-g"])
            if prefix_global:
                _add_if_exists(os.path.join(prefix_global, "node_modules"))

            global_root = cls._probe_npm_output(npm_path, ["root", "-g"])
            if global_root:
                global_root_key = os.path.normcase(os.path.normpath(global_root))
                discovered = [p for p in discovered if os.path.normcase(os.path.normpath(p)) != global_root_key]
                seen = {os.path.normcase(os.path.normpath(p)) for p in discovered}

        return discovered

class NpmScanWorker(BaseCmdWorker):
    env_scanned = Signal(Environment) 

    def __init__(self, env: Environment, config_mgr):
        super().__init__()
        self.env = env
        self.config_mgr = config_mgr
        self.proxy_settings = getattr(config_mgr.config, "proxy_settings", {}) or {}
    
    def _scan_standalone_node_modules(self, node_modules_path: str) -> list:
        """Scan a standalone node_modules directory directly."""
        pkgs = []
        try:
            if not os.path.isdir(node_modules_path):
                return pkgs
            
            # List top-level packages in node_modules
            for entry in os.listdir(node_modules_path):
                entry_path = os.path.join(node_modules_path, entry)
                
                # Skip nested node_modules and non-directories
                if not os.path.isdir(entry_path) or entry == "node_modules":
                    continue
                
                # Handle scoped packages (@scope/package)
                if entry.startswith("@"):
                    # This is a scope directory, scan its contents
                    for scoped_pkg in os.listdir(entry_path):
                        scoped_pkg_path = os.path.join(entry_path, scoped_pkg)
                        if os.path.isdir(scoped_pkg_path):
                            pkg_name = f"{entry}/{scoped_pkg}"
                            pkg_json_path = os.path.join(scoped_pkg_path, "package.json")
                            version = self._read_package_version(pkg_json_path)
                            if version:
                                meta = {
                                    "channel": detect_channel(version),
                                    "channels_available": ["latest"],
                                    "display_name": pkg_name,
                                    "description": ""
                                }
                                pkgs.append(Package(
                                    name=pkg_name,
                                    version=version,
                                    description=meta["description"],
                                    metadata=meta
                                ))
                else:
                    # Regular package
                    pkg_json_path = os.path.join(entry_path, "package.json")
                    version = self._read_package_version(pkg_json_path)
                    if version:
                        meta = {
                            "channel": detect_channel(version),
                            "channels_available": ["latest"],
                            "display_name": entry,
                            "description": ""
                        }
                        pkgs.append(Package(
                            name=entry,
                            version=version,
                            description=meta["description"],
                            metadata=meta
                        ))
        except Exception as e:
            self._log(f"Error scanning node_modules: {e}", "error")
        
        return pkgs
    
    def _read_package_version(self, package_json_path: str) -> str:
        """Read version from package.json file."""
        try:
            if os.path.exists(package_json_path):
                with open(package_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("version", "")
        except Exception:
            pass
        return ""
        
    def run(self):
        try:
            self._log(f"Scanning {self.env.name}...", "system")
            npm_path = NpmBaseHelper.find_npm()
            if not npm_path:
                self._log("Error: npm command not found. Please ensure Node.js is installed.", "error")
                return

            node_path = NpmBaseHelper.find_node(npm_path=npm_path)
            node_ver = ""
            if node_path:
                ver_cmd = [node_path, "--version"]
                ver_res = self._run_command(ver_cmd, capture_output=True)
                raw_node_ver = (ver_res.stdout or "").strip() or (ver_res.stderr or "").strip()
                node_ver = parse_node_version(raw_node_ver)
                if raw_node_ver:
                    self._log(raw_node_ver, "stdout")
            else:
                self._log("Warning: Node executable not found in PATH.", "stderr")

            cycle, latest_ver, runtime_has_update, runtime_err = check_runtime_patch_update(
                "node",
                node_ver,
                proxy_settings=self.proxy_settings,
            )
            if runtime_has_update:
                self._log(
                    f"Node runtime update available: {node_ver} -> {latest_ver}",
                    "system",
                )
            elif runtime_err and node_ver:
                self._log(f"Node runtime update check skipped: {runtime_err}", "stderr")

            major_latest_ver, runtime_has_major_update, major_err = check_runtime_major_update(
                "node",
                node_ver,
                proxy_settings=self.proxy_settings,
            )
            if runtime_has_major_update:
                self._log(
                    f"Node major version upgrade available: {node_ver} -> {major_latest_ver}",
                    "system",
                )

            is_global = (self.env.type == "global" or self.env.path == "global")
            
            # Check if this is a standalone node_modules directory
            is_standalone_node_modules = False
            if not is_global:
                env_path_name = os.path.basename(os.path.normpath(self.env.path))
                is_standalone_node_modules = (
                    env_path_name.lower() == "node_modules" and 
                    not os.path.exists(os.path.join(self.env.path, "package.json"))
                )
            
            pkgs = []
            
            # Handle standalone node_modules directory (e.g., C:\Users\Leo\node_modules\)
            if is_standalone_node_modules:
                self._log(f"Scanning standalone node_modules directory: {self.env.path}", "system")
                pkgs = self._scan_standalone_node_modules(self.env.path)
                self._log(f"✓ Found {len(pkgs)} package(s)", "success")
            else:
                # Standard npm project or global packages
                cmd = [npm_path, "list", "--depth=0", "--json"]
                cwd = None
                
                if is_global:
                    cmd.insert(2, "-g")
                else:
                    cwd = self.env.path
                    if not os.path.exists(os.path.join(cwd, "package.json")):
                        self._log(f"Warning: No package.json found in {cwd}. Is this an NPM project directory?", "error")

                res = self._run_command(cmd, cwd=cwd if not is_global else None, capture_output=True)

                output = (res.stdout or "").strip()

                # npm list might return 1 if there are missing peer dependencies, but stdout still has valid JSON
                if output:
                    try:
                        data = json.loads(output)
                        dependencies = data.get("dependencies", {})
                        for name, info in dependencies.items():
                            if isinstance(info, dict):
                                version = info.get("version", "")
                                if version:
                                    meta = {}
                                    meta["channel"] = detect_channel(version)
                                    meta["channels_available"] = ["latest"]
                                    meta["display_name"] = name
                                    meta["description"] = ""

                                    # Restore saved display names / descriptions if any
                                    if is_global and hasattr(self.config_mgr.config, "npm_apps"):
                                        saved_app = self.config_mgr.config.npm_apps.get(name)
                                        if saved_app:
                                            meta["display_name"] = saved_app.get("display_name", name)
                                            meta["description"] = saved_app.get("description", "")
                                            meta["channel"] = saved_app.get("channel", meta["channel"])
                                            meta["channels_available"] = saved_app.get("channels_available", ["latest"])

                                    pkgs.append(Package(
                                        name=name,
                                        version=version,
                                        description=meta["description"],
                                        metadata=meta
                                    ))
                    except json.JSONDecodeError as e:
                        self._log(f"JSON parse failed: {e}", "error")

                self._log(f"✓ Found {len(pkgs)} package(s)", "success")
                     
            self.env.packages = pkgs
            self.env.runtime_name = "Node.js"
            self.env.runtime_version = node_ver or "?"
            self.env.runtime_cycle = cycle or parse_cycle("node", node_ver)
            self.env.runtime_latest_version = latest_ver
            self.env.runtime_has_update = runtime_has_update
            self.env.runtime_has_major_update = runtime_has_major_update
            self.env.runtime_major_latest_version = major_latest_ver
            self.env.runtime_update_error = runtime_err
            self.env.is_scanned = True
            self._log(f"✓ Found {len(pkgs)} package(s)", "success")
            
        except Exception as e:
            self._log(f"Scan Error for {self.env.path}: {e}", "error")
            self.env.is_scanned = True 
            
        finally:
            self.env_scanned.emit(self.env)
            self._flush_logs()


class NpmUpdateCheckWorker(BaseCmdWorker):
    updates_checked = Signal(Environment)

    def __init__(self, env: Environment, registry_url: Optional[str] = None, proxy_settings=None):
        super().__init__()
        self.env = env
        self.registry_url = registry_url
        self.proxy_settings = proxy_settings or {}
        
    def run(self):
        try:
            if not self.env.packages:
                return
            
            npm_path = NpmBaseHelper.find_npm()
            if not npm_path:
                return
                
            self._log(f"Checking updates for {self.env.name} from npm registry...", "system")
            is_global = (self.env.type == "global" or self.env.path == "global")
            cwd = None if is_global else self.env.path

            outdated_cmd = [npm_path, "outdated", "--json"]
            if is_global:
                outdated_cmd.insert(2, "-g")
            if self.registry_url:
                outdated_cmd.extend(["--registry", self.registry_url])
            outdated_res = self._run_command(outdated_cmd, cwd=cwd, capture_output=True)

            outdated_map = {}
            if outdated_res.stdout and outdated_res.stdout.strip():
                try:
                    parsed = json.loads(outdated_res.stdout)
                    if isinstance(parsed, dict):
                        outdated_map = parsed
                except json.JSONDecodeError:
                    self._log("Warning: failed to parse npm outdated JSON output.", "stderr")

            tags_check_list = []
            for pkg in self.env.packages:
                if pkg.metadata is None:
                    pkg.metadata = {}

                pkg.has_update = False
                pkg.latest_version = ""

                outdated_info = outdated_map.get(pkg.name)
                latest_candidate = ""
                if isinstance(outdated_info, dict):
                    latest_candidate = str(outdated_info.get("latest") or outdated_info.get("wanted") or "").strip()
                elif isinstance(outdated_info, str):
                    latest_candidate = outdated_info.strip()

                if latest_candidate:
                    pkg.latest_version = latest_candidate
                    pkg.has_update = (latest_candidate != pkg.version)

                target_channel = pkg.metadata.get("channel", "latest")
                if pkg.has_update or target_channel != "latest":
                    tags_check_list.append(pkg)

            # Only fetch dist-tags for packages where it matters (outdated or non-latest channel).
            for pkg in tags_check_list:
                cmd = [npm_path, "view", pkg.name, "dist-tags", "--json"]
                if self.registry_url:
                    cmd.extend(["--registry", self.registry_url])
                res = self._run_command(cmd, capture_output=True)
                if res.returncode != 0 or not res.stdout.strip():
                    continue
                try:
                    data = json.loads(res.stdout)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue

                pkg.metadata["channel_versions"] = data
                discovered = list(data.keys())
                others = [c for c in discovered if c != "latest"]
                others.sort()
                final_channels = (["latest"] if "latest" in discovered else []) + others
                pkg.metadata["channels_available"] = final_channels

                target_channel = pkg.metadata.get("channel", "latest")
                registry_target = data.get(target_channel)
                if registry_target:
                    pkg.latest_version = registry_target
                    pkg.has_update = (registry_target != pkg.version)
                        
            updates_found = sum(1 for pkg in self.env.packages if pkg.has_update)
            if updates_found > 0:
                self._log(f"Found {updates_found} update(s) available in {self.env.name}.", "success")
            else:
                self._log(f"All packages in {self.env.name} are up to date.", "success")
                
        except Exception as e:
            self._log(f"Update Check Error: {e}", "error")
        finally:
            self.updates_checked.emit(self.env)
            self._flush_logs()


class NpmActionWorker(BaseCmdWorker):
    def __init__(self, env: Environment, action: str, pkg_name: str, channel: Optional[str] = None, registry_url: Optional[str] = None, proxy_settings=None):
        super().__init__()
        self.env = env
        self.action = action
        self.pkg_name = pkg_name
        self.channel = channel
        self.registry_url = registry_url
        self.proxy_settings = proxy_settings or {}

    def run(self):
        try:
            npm_path = NpmBaseHelper.find_npm()
            if not npm_path:
                self._log("npm not found", "error")
                return

            is_global = (self.env.type == "global" or self.env.path == "global")
            cwd = None if is_global else self.env.path
            
            pkg_spec = self.pkg_name
            if self.channel and self.action in ["install", "update"]:
                if not has_explicit_tag(self.pkg_name):
                    pkg_spec = f"{self.pkg_name}@{self.channel}"

            if self.action == "uninstall":
                action_word = "Uninstalling"
                verb = "uninstall"
            else:
                action_word = "Installing" if self.action == "install" else "Updating"
                verb = "install"

            self._log(f"{action_word} {pkg_spec} in {self.env.name}...", "system")
            
            cmd = [npm_path, verb, pkg_spec, "--loglevel=http"]
            if is_global:
                cmd.insert(2, "-g")
            if self.registry_url and verb == "install":
                cmd.extend(["--registry", self.registry_url])

            self._run_command(cmd, cwd=cwd)
            
            if self.success:
                self._log(f"✓ {action_word} completed for {pkg_spec}", "success")
            else:
                self._log(f"✗ {action_word} failed for {pkg_spec}", "error")
                
        except Exception as e:
            self._log(f"Error during {self.action}: {e}", "error")
            self.success = False
        finally:
            self._flush_logs()


class NpmBatchUpdateWorker(BaseCmdWorker):
    """Worker to run `npm install pkg1@ch1 pkg2@ch2 ...` for multiple packages at once."""

    def __init__(self, env: Environment, pkg_specs: list, registry_url=None, proxy_settings=None):
        super().__init__()
        self.env = env
        self.pkg_specs = pkg_specs  # list of (name, channel)
        self.registry_url = registry_url
        self.proxy_settings = proxy_settings or {}

    def run(self):
        try:
            npm_path = NpmBaseHelper.find_npm()
            if not npm_path:
                self._log("npm not found", "error")
                self.success = False
                return

            is_global = (self.env.type == "global" or self.env.path == "global")
            cwd = None if is_global else self.env.path

            install_specs = []
            names = []
            for name, channel in self.pkg_specs:
                names.append(name)
                if channel and channel != "latest" and not has_explicit_tag(name):
                    install_specs.append(f"{name}@{channel}")
                else:
                    install_specs.append(name)

            self._log(f"Batch updating {', '.join(names)} in {self.env.name}...", "system")

            cmd = [npm_path, "install"] + install_specs + ["--loglevel=http"]
            if is_global:
                cmd.insert(2, "-g")
            if self.registry_url:
                cmd.extend(["--registry", self.registry_url])

            self._run_command(cmd, cwd=cwd)

            if self.success:
                self._log(f"✓ Batch updated {len(self.pkg_specs)} packages in {self.env.name}", "success")
            else:
                self._log(f"✗ Batch update failed in {self.env.name}", "error")
        except Exception as e:
            self._log(f"Error during batch update: {e}", "error")
            self.success = False
        finally:
            self._flush_logs()


class NpmRuntimeUpdateWorker(BaseCmdWorker):
    """Worker to update Node.js runtime itself (not npm packages)."""

    def __init__(self, env: Environment, use_nvm: bool = False):
        super().__init__()
        self.env = env
        self.use_nvm = use_nvm
        self.result_message = ""

    def run(self):
        try:
            current_ver = self.env.runtime_version
            is_major = bool(getattr(self.env, "runtime_has_major_update", False))
            if is_major:
                cycle = parse_cycle("node", self.env.runtime_major_latest_version)
                target_ver = self.env.runtime_major_latest_version
            else:
                cycle = self.env.runtime_cycle or parse_cycle("node", current_ver)
                target_ver = self.env.runtime_latest_version
            method = "nvm" if self.use_nvm else "winget"
            self._log(
                f"Updating Node.js runtime from {current_ver or 'unknown'}"
                + (f" to {target_ver}" if target_ver else "")
                + (f" (major upgrade)" if is_major else "")
                + f" via {method}"
                + f" (triggered by {self.env.name})...",
                "system",
            )

            if self.use_nvm:
                commands, reason = build_node_runtime_update_command_nvm(
                    cycle, target_version=target_ver
                )
            else:
                commands, reason = build_node_runtime_update_command(
                    cycle, is_major_upgrade=is_major
                )
            if not commands:
                self.success = False
                self.result_message = reason or "No runnable command for Node.js runtime update."
                self._log(self.result_message, "error")
                return

            for cmd in commands:
                self._run_command(cmd)
                if not self.success:
                    self.result_message = "Node.js runtime update command failed."
                    self._log(f"✗ {self.result_message}", "error")
                    return

            self.success = True
            self.result_message = "Node.js runtime update command completed."
            self._log(f"✓ {self.result_message}", "success")
        except Exception as exc:
            self.success = False
            self.result_message = f"Node.js runtime update error: {exc}"
            self._log(self.result_message, "error")
        finally:
            self._flush_logs()


class NpmManager(PackageManager):
    """
    Manages NPM global and project environments.
    """
    log_msg = Signal(str, str)          # text, tag
    log_batch = Signal(list)
    update_done = Signal(str, str, bool) # env_path, pkg_name, success
    batch_update_done = Signal(str, list, bool) # env_path, pkg_specs, success
    remove_done = Signal(str, str, bool) # env_path, pkg_name, success
    install_done = Signal(str, str, bool) # env_path, pkg_names, success
    updates_checked = Signal(Environment)
    runtime_update_done = Signal(str, bool, str) # env_path, success, message

    def __init__(self, config_mgr):
        super().__init__()
        self.config_mgr = config_mgr
        self._active_workers = []
        self._load_envs()

    @staticmethod
    def _auto_env_identity_for_node_modules(path: str) -> tuple[str, str, list[str]]:
        """Build type/name/tags for auto-discovered standalone node_modules."""
        norm_path = os.path.normpath(path)
        norm_key = os.path.normcase(norm_path)
        home_modules = os.path.normcase(os.path.normpath(os.path.join(os.path.expanduser("~"), "node_modules")))
        appdata_modules = os.path.normcase(
            os.path.normpath(os.path.join(os.path.expandvars(r"%APPDATA%"), "npm", "node_modules"))
        ) if os.name == "nt" else ""

        tags = ["auto", "standalone-node_modules"]
        if norm_key == home_modules:
            return "user_home_modules", "User Home node_modules", tags + ["location:home"]
        if appdata_modules and norm_key == appdata_modules:
            return "user_roaming_modules", "Roaming npm node_modules", tags + ["location:appdata"]

        parent_dir = os.path.dirname(norm_path)
        return "standalone_modules", f"node_modules @ {parent_dir}", tags + ["location:custom"]

    def _ensure_auto_npm_envs(self) -> bool:
        """Auto-register standalone user-level node_modules folders."""
        env_cfg = getattr(self.config_mgr.config, "npm_environments", None)
        if not isinstance(env_cfg, list):
            return False

        existing_keys = {
            os.path.normcase(os.path.normpath(str(e.get("path", ""))))
            for e in env_cfg
            if isinstance(e, dict)
        }
        changed = False

        for modules_path in NpmBaseHelper.discover_user_node_modules():
            key = os.path.normcase(os.path.normpath(modules_path))
            if key in existing_keys:
                continue

            env_type, env_name, tags = self._auto_env_identity_for_node_modules(modules_path)
            self.config_mgr.add_npm_env(
                path=modules_path,
                name=env_name,
                env_type=env_type,
                tags=tags,
                save=False,
            )
            existing_keys.add(key)
            changed = True

        return changed

    def _load_envs(self):
        old_envs = {os.path.normcase(os.path.normpath(e.path)): e for e in self.environments}
        self.environments.clear()
        
        # 1. auto-setup Global Environment ONCE on first run
        if not getattr(self.config_mgr.config, "npm_scanned_once", False):
            import shutil
            tags = []
            if shutil.which("npm") or shutil.which("npm.cmd"):
                tags.append("path")
            self.config_mgr.add_npm_env(path="global", name="Global Packages", env_type="global", tags=tags, save=False)
            self.config_mgr.config.npm_scanned_once = True
            self.config_mgr.save_config()

        auto_added = self._ensure_auto_npm_envs()
        if auto_added:
            self.config_mgr.save_config()
        
        # 2. loads from config
        if hasattr(self.config_mgr.config, "npm_environments"):
            for env_dict in self.config_mgr.config.npm_environments:
                path = os.path.normpath(env_dict.get("path"))
                name = env_dict.get("name", os.path.basename(path))
                
                key = os.path.normcase(path)
                
                env_type = env_dict.get("type", "project")
                tags = env_dict.get("tags", [])
                
                if key in old_envs:
                    env = old_envs[key]
                    env.path = path
                    env.name = name
                    env.type = env_type
                    env.tags = tags
                    self.environments.append(env)
                else:
                    self.environments.append(Environment(path=path, name=name, type=env_type, tags=tags))

    def reload_envs(self):
        self._load_envs()

    def _on_env_scanned(self, env: Environment):
        for i, e in enumerate(self.environments):
            if e.path == env.path:
                self.environments[i] = env
                break
        self.env_scanned.emit(env)

    def scan_environment(self, env: Environment):
        worker = NpmScanWorker(env, self.config_mgr)
        worker.env_scanned.connect(self._on_env_scanned)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._active_workers.remove(worker) if worker in self._active_workers else None)
        
    def check_updates(self, env: Environment):
        worker = NpmUpdateCheckWorker(
            env,
            registry_url=resolve_npm_registry_url(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        worker.updates_checked.connect(self._on_updates_checked)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._active_workers.remove(worker) if worker in self._active_workers else None)

    def _on_updates_checked(self, env: Environment):
        for i, e in enumerate(self.environments):
            if e.path == env.path:
                self.environments[i] = env
                break
        self.updates_checked.emit(env)

    def update_package(self, pkg: Package, env: Environment, channel: str = "latest"):
        worker = NpmActionWorker(
            env,
            "update",
            pkg.name,
            channel,
            registry_url=resolve_npm_registry_url(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda: [self._active_workers.remove(worker) if worker in self._active_workers else None, self.update_done.emit(env.path, pkg.name, worker.success)])

    def batch_update_packages(self, env: Environment, pkg_specs: list):
        """pkg_specs: list of (pkg_name, channel) tuples"""
        worker = NpmBatchUpdateWorker(
            env,
            pkg_specs,
            registry_url=resolve_npm_registry_url(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda specs=pkg_specs: [
            self._active_workers.remove(worker) if worker in self._active_workers else None,
            self.batch_update_done.emit(env.path, specs, worker.success),
        ])

    def remove_package(self, env: Environment, pkg_name: str):
        worker = NpmActionWorker(
            env,
            "uninstall",
            pkg_name,
            None,
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda: [self._active_workers.remove(worker) if worker in self._active_workers else None, self.remove_done.emit(env.path, pkg_name, worker.success)])

    def install_package(self, env: Environment, pkg_names: str, channel: str = "latest"):
        worker = NpmActionWorker(
            env,
            "install",
            pkg_names,
            channel,
            registry_url=resolve_npm_registry_url(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda: [self._active_workers.remove(worker) if worker in self._active_workers else None, self.install_done.emit(env.path, pkg_names, worker.success)])

    def update_runtime(self, env: Environment, use_nvm: bool = False):
        worker = NpmRuntimeUpdateWorker(env, use_nvm=use_nvm)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(
            lambda: [
                self._active_workers.remove(worker) if worker in self._active_workers else None,
                self.runtime_update_done.emit(env.path, worker.success, worker.result_message),
            ]
        )
