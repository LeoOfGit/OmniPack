"""
NpmManager — NPM backend for OmniPack.
Ported from npm_manager.pyw NpmExecutor + data models.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Dict, Callable, Optional

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    pass

# ── Constants ────────────────────────────────────────────────────────────────

CHANNEL_PATTERNS = {
    "nightly": re.compile(r"[-.@]nightly|nightly[-.]?", re.IGNORECASE),
    "preview": re.compile(r"[-.@]preview|preview[-.]?", re.IGNORECASE),
    "beta":    re.compile(r"[-.@]beta|beta[-.]?",       re.IGNORECASE),
    "canary":  re.compile(r"[-.@]canary|canary[-.]?",   re.IGNORECASE),
    "next":    re.compile(r"[-.@]next(?!\w)|next[-.]?",  re.IGNORECASE),
    "rc":      re.compile(r"[-.@]rc\d*|rc[-.]?",        re.IGNORECASE),
}

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\r")
SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class NpmApp:
    """Represents an npm global package (application)."""
    name: str
    version: str = ""
    display_name: str = ""
    description: str = ""
    channel: str = "latest"
    channels_available: List[str] = field(default_factory=lambda: ["latest"])
    is_installed: bool = False
    is_selected: bool = False
    latest_version: str = ""
    channel_versions: Dict[str, str] = field(default_factory=dict)


# ── NpmExecutor ──────────────────────────────────────────────────────────────

class NpmExecutor:
    """NPM command executor with streaming output."""

    NPM_COMMANDS = ["npm.cmd", "npm"]

    @classmethod
    def find_npm(cls) -> Optional[str]:
        """Find npm command path, prioritizing system installation."""
        system_paths = [
            os.path.expandvars(r"%ProgramFiles%\nodejs\npm.cmd"),
            os.path.expandvars(r"%ProgramFiles(x86)%\nodejs\npm.cmd"),
        ]
        for path in system_paths:
            if os.path.exists(path):
                return path

        for cmd in cls.NPM_COMMANDS:
            npm_path = shutil.which(cmd)
            if npm_path:
                return npm_path

        common_paths = [
            os.path.expandvars(r"%APPDATA%\npm\npm.cmd"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
        return None

    @classmethod
    def run_command(
        cls,
        cmd: list[str],
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> tuple[bool, str]:
        """Run a command with streaming output."""
        cmd_str = " ".join(cmd)
        if log_callback:
            log_callback(f"> {cmd_str}", "cmd")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=SUBPROCESS_FLAGS,
                shell=True,
            )
        except FileNotFoundError:
            msg = f"Command not found: {cmd[0]}"
            if log_callback:
                log_callback(msg, "error")
            return False, msg
        except OSError as e:
            msg = f"Failed to start process: {e}"
            if log_callback:
                log_callback(msg, "error")
            return False, msg

        output_lines: list[str] = []

        def read_stream(stream, tag):
            try:
                for raw_line in stream:
                    line = ANSI_ESCAPE.sub("", raw_line).rstrip()
                    if line:
                        output_lines.append(line)
                        if log_callback:
                            log_callback(line, tag)
            except (ValueError, OSError):
                pass

        stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True)
        stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        success = process.returncode == 0
        full_output = "\n".join(output_lines)
        return success, full_output

    @classmethod
    def get_installed_packages(
        cls, log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> tuple[dict[str, str], str]:
        """Get installed npm global packages."""
        npm_path = cls.find_npm()
        if not npm_path:
            msg = "npm command not found. Please ensure Node.js is installed."
            if log_callback:
                log_callback(msg, "error")
            return {}, msg

        if log_callback:
            log_callback("Scanning global npm packages...", "system")

        # Get version first
        success, version_out = cls.run_command([npm_path, "--version"], log_callback)
        if not success:
            return {}, f"npm not responding: {version_out}"
        if log_callback:
            log_callback(f"npm version: {version_out.strip()}", "system")

        # Get global list as JSON
        success, output = cls.run_command(
            [npm_path, "list", "-g", "--depth=0", "--json"], log_callback=log_callback
        )
        if not output:
            return {}, "npm returned empty output."

        try:
            data = json.loads(output)
        except json.JSONDecodeError as e:
            msg = f"JSON parse failed: {e}"
            if log_callback:
                log_callback(msg, "error")
            return {}, msg

        packages = {}
        for name, info in data.get("dependencies", {}).items():
            if isinstance(info, dict):
                version = info.get("version", "")
                if version:
                    packages[name] = version
            elif isinstance(info, str):
                packages[name] = info

        # Detect npm itself
        if "npm" not in packages:
            npm_ver = version_out.strip()
            if npm_ver:
                packages["npm"] = npm_ver
                if log_callback:
                    log_callback(f"Detected system npm: {npm_ver}", "success")

        # Detect corepack
        if "corepack" not in packages:
            success_cp, cp_out = cls.run_command(["corepack", "--version"], log_callback=log_callback)
            if success_cp:
                ver = cp_out.strip()
                if re.match(r"^\d+\.\d+\.\d+", ver):
                    packages["corepack"] = ver
                    if log_callback:
                        log_callback(f"Detected system corepack: {ver}", "success")

        if log_callback:
            log_callback(f"Found {len(packages)} global package(s)", "success")
        return packages, ""

    @staticmethod
    def detect_channel(version: str) -> str:
        """Detect version channel from version string."""
        if not version:
            return "latest"
        for channel, pattern in CHANNEL_PATTERNS.items():
            if pattern.search(version):
                return channel
        return "latest"

    @classmethod
    def install_package(cls, name: str, channel: str = "latest",
                        log_callback=None) -> tuple[bool, str]:
        npm_path = cls.find_npm()
        if not npm_path:
            return False, "npm not found"
        pkg_spec = f"{name}@{channel}"
        if log_callback:
            log_callback(f"Installing {pkg_spec}...", "system")
        cmd = [npm_path, "install", "-g", pkg_spec, "--loglevel=http"]
        return cls.run_command(cmd, log_callback)

    @classmethod
    def uninstall_package(cls, name: str, log_callback=None) -> tuple[bool, str]:
        npm_path = cls.find_npm()
        if not npm_path:
            return False, "npm not found"
        if log_callback:
            log_callback(f"Uninstalling {name}...", "system")
        cmd = [npm_path, "uninstall", "-g", name]
        return cls.run_command(cmd, log_callback)

    @classmethod
    def update_package(cls, name: str, channel: str = "latest",
                       log_callback=None) -> tuple[bool, str]:
        npm_path = cls.find_npm()
        if not npm_path:
            return False, "npm not found"
        pkg_spec = f"{name}@{channel}"
        if log_callback:
            log_callback(f"Updating {pkg_spec}...", "system")
        cmd = [npm_path, "install", "-g", pkg_spec, "--loglevel=http"]
        return cls.run_command(cmd, log_callback)

    @classmethod
    def switch_channel(cls, name: str, new_channel: str,
                       log_callback=None) -> tuple[bool, str]:
        return cls.install_package(name, new_channel, log_callback)

    @classmethod
    def get_config(cls, key: str, log_callback=None) -> str:
        npm_path = cls.find_npm()
        if not npm_path:
            return ""
        success, out = cls.run_command([npm_path, "config", "get", key], log_callback)
        return out.strip() if success else ""

    @classmethod
    def set_config(cls, key: str, value: str, log_callback=None) -> bool:
        npm_path = cls.find_npm()
        if not npm_path:
            return False
        success, _ = cls.run_command([npm_path, "config", "set", key, value], log_callback)
        return success

    @classmethod
    def get_latest_versions(
        cls, apps: list[NpmApp],
        log_callback: Optional[Callable[[str, str], None]] = None
    ) -> dict[str, dict[str, str]]:
        """Get latest versions for all dist-tags of given packages."""
        npm_path = cls.find_npm()
        if not npm_path or not apps:
            return {}

        results: dict[str, dict[str, str]] = {}
        for app in apps:
            name = app.name
            cmd = [npm_path, "view", name, "dist-tags", "--json"]
            if log_callback:
                log_callback(f"> {' '.join(cmd)}", "cmd")
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=SUBPROCESS_FLAGS, shell=True,
                )
                stdout, stderr = process.communicate()

                if stderr and log_callback:
                    for line in stderr.split("\n"):
                        if line.strip() and "npm update" not in line:
                            log_callback(line, "stderr")

                if not stdout.strip():
                    if log_callback:
                        log_callback(f"No output for {name}", "system")
                    continue

                data = json.loads(stdout)
                if isinstance(data, dict):
                    results[name] = data
                    if log_callback:
                        tags = list(data.keys())
                        log_callback(f"✔ {name}: {len(tags)} tags found {tags}", "success")

            except json.JSONDecodeError as e:
                if log_callback:
                    log_callback(f"JSON error for {name}: {e}", "error")
            except Exception as e:
                if log_callback:
                    log_callback(f"Error checking {name}: {e}", "error")

        return results


# ── NpmManager (Qt-based orchestrator) ───────────────────────────────────────

class NpmManager(QObject):
    """
    Manages npm global packages. Wraps NpmExecutor with Qt signals.
    """
    log_msg = Signal(str, str)          # text, tag
    scan_done = Signal(dict, str)       # packages, error
    updates_checked = Signal(dict)      # all_tags
    action_done = Signal(str, str, bool)  # name, action, success

    def __init__(self, config_mgr):
        super().__init__()
        self.config_mgr = config_mgr
        self.installed_packages: dict[str, str] = {}
        self._is_busy = False
        self._task_queue: list[tuple[str, str]] = []

        # Build NpmApp objects from config
        self.apps: Dict[str, NpmApp] = {}
        self._load_apps()

    def _load_apps(self):
        """Load NpmApp objects from config dict."""
        self.apps.clear()
        for name, app_data in self.config_mgr.config.npm_apps.items():
            self.apps[name] = NpmApp(
                name=name,
                display_name=app_data.get("display_name", name),
                description=app_data.get("description", ""),
                channel=app_data.get("channel", "latest"),
                channels_available=app_data.get("channels_available", ["latest"]),
            )

    def _log(self, msg: str, tag: str = "system"):
        self.log_msg.emit(msg, tag)

    # ── Scan ──

    def start_scan(self):
        if self._is_busy:
            return
        self._is_busy = True

        def do_scan():
            pkgs, error = NpmExecutor.get_installed_packages(self._log)
            self.scan_done.emit(pkgs, error)

        threading.Thread(target=do_scan, daemon=True).start()

    def on_scan_done(self, packages: dict[str, str], error: str):
        """Call from UI thread after scan_done signal."""
        self._is_busy = False
        if error:
            return

        self.installed_packages = packages

        # Discover new packages
        for pkg, ver in packages.items():
            if pkg not in self.apps:
                detected = NpmExecutor.detect_channel(ver)
                avail = ["latest"]
                if detected != "latest":
                    avail.append(detected)
                self.apps[pkg] = NpmApp(
                    name=pkg, version=ver, display_name=pkg,
                    channel=detected, channels_available=avail,
                    is_installed=True,
                )

        # Sync installed status
        for name, app in self.apps.items():
            if name in packages:
                app.version = packages[name]
                app.is_installed = True
            else:
                app.version = ""
                app.is_installed = False

        self._save_apps()

    # ── Update Check ──

    def check_updates(self):
        apps_to_check = list(self.apps.values())
        if not apps_to_check:
            return

        def do_check():
            self._log("Checking latest channel versions from npm registry...", "system")
            all_tags = NpmExecutor.get_latest_versions(apps_to_check, log_callback=self._log)
            self.updates_checked.emit(all_tags)

        threading.Thread(target=do_check, daemon=True).start()

    def on_updates_checked(self, all_tags: dict[str, dict[str, str]]):
        """Call from UI thread after updates_checked signal."""
        update_found_count = 0
        for name, app in self.apps.items():
            if name in all_tags:
                tags = all_tags[name]
                target_tag = app.channel
                registry_latest = tags.get(target_tag)

                if registry_latest:
                    app.latest_version = registry_latest
                    if registry_latest != app.version:
                        update_found_count += 1

                # Dynamic channel discovery
                discovered = list(tags.keys())
                channel_vers = dict(tags)
                app.channel_versions = channel_vers

                others = [c for c in discovered if c != "latest"]
                others.sort()
                final_channels = (["latest"] if "latest" in discovered else []) + others

                if final_channels != app.channels_available:
                    app.channels_available = final_channels
                    if app.channel not in app.channels_available:
                        app.channel = "latest" if "latest" in app.channels_available else (app.channels_available[0] if app.channels_available else "latest")

        self._save_apps()
        if update_found_count > 0:
            self._log(f"Found {update_found_count} update(s) available.", "success")
        else:
            self._log("All packages are up to date.", "success")

    # ── Actions ──

    def run_action(self, name: str, action: str, channel_override: str = None):
        if self._is_busy:
            self._task_queue.append((name, action))
            self._log(f"Queued: {action} {name}", "system")
            return

        app = self.apps.get(name)
        if not app:
            return

        channel = channel_override or app.channel
        self._is_busy = True

        def worker():
            success = False
            if action == "install":
                success, _ = NpmExecutor.install_package(name, channel, self._log)
            elif action == "update":
                success, _ = NpmExecutor.update_package(name, channel, self._log)
            elif action == "uninstall":
                success, _ = NpmExecutor.uninstall_package(name, self._log)
            elif action == "switch":
                success, _ = NpmExecutor.switch_channel(name, channel, self._log)
                if success:
                    app.channel = channel
            self.action_done.emit(name, action, success)

        threading.Thread(target=worker, daemon=True).start()

    def on_action_done(self, name: str, action: str, success: bool):
        self._is_busy = False
        display = self.apps[name].display_name if name in self.apps else name
        if success:
            self._log(f"✓ {action.title()} {display} completed", "success")
        else:
            self._log(f"✗ {action.title()} {display} failed", "error")

        if self._task_queue:
            next_name, next_action = self._task_queue.pop(0)
            self.run_action(next_name, next_action)

    # ── Config Persistence ──

    def _save_apps(self):
        npm_apps = {}
        for name, app in self.apps.items():
            npm_apps[name] = {
                "display_name": app.display_name,
                "description": app.description,
                "channel": app.channel,
                "channels_available": app.channels_available,
            }
        self.config_mgr.config.npm_apps = npm_apps
        self.config_mgr.save_config()

    def add_app(self, app: NpmApp):
        self.apps[app.name] = app
        self._save_apps()

    def update_app(self, name: str, **kwargs):
        if name in self.apps:
            for key, value in kwargs.items():
                if hasattr(self.apps[name], key):
                    setattr(self.apps[name], key, value)
            self._save_apps()

    def remove_app(self, name: str):
        if name in self.apps:
            del self.apps[name]
            self._save_apps()
