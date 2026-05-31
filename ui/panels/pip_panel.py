"""
PipPanel — Self-contained QWidget for managing Python (pip/uv) environments.
Extracted from OmniPack.pyw to keep the main window thin.
"""
import os
import subprocess
import webbrowser
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt, QTimer, Signal

from core.manager_base import Environment
from core.runtime_update import (
    download_runtime_installer,
    build_installer_run_command,
    get_python_installer_url,
)
from managers.base_worker import BaseCmdWorker
from managers.pip_manager import PipManager
from ui.panels.base_panel import BasePanel
from core.trace_logger import trace_event, is_trace_enabled, get_trace_path

class RuntimeInstallerWorker(BaseCmdWorker):
    """Download and run the official runtime installer as a winget fallback."""

    installer_done = Signal(bool, str)  # success, message

    def __init__(self, runtime_kind: str, version: str, proxy_settings=None):
        super().__init__()
        self.runtime_kind = runtime_kind
        self.version = version
        self.proxy_settings = proxy_settings or {}

    def run(self):
        try:
            label = "Node.js" if self.runtime_kind == "node" else "Python"
            self._log(
                f"Downloading {label} {self.version} installer...",
                "system",
            )

            def _progress(downloaded: int, total: int):
                if total:
                    pct = downloaded * 100 // total
                    self._log(
                        f"... {downloaded / 1_048_576:.1f} / {total / 1_048_576:.1f} MB ({pct}%)",
                        "system",
                    )
                else:
                    self._log(
                        f"... {downloaded / 1_048_576:.1f} MB downloaded",
                        "system",
                    )

            installer_path, err = download_runtime_installer(
                self.runtime_kind,
                self.version,
                proxy_settings=self.proxy_settings,
                progress_callback=_progress,
            )
            if err:
                self.success = False
                self._log(f"✗ Download failed: {err}", "error")
                self.installer_done.emit(False, err)
                return

            self._log(f"✓ Downloaded to {installer_path}", "success")

            cmd, cmd_err = build_installer_run_command(installer_path, self.runtime_kind)
            if cmd_err:
                self.success = False
                self._log(f"✗ {cmd_err}", "error")
                self.installer_done.emit(False, cmd_err)
                return

            self._log("Running installer (may require administrator privileges)...", "system")
            self._run_command(cmd)

            if self.success:
                self._log("✓ Installer completed successfully", "success")
            else:
                self._log(
                    "✗ Installer returned non-zero (try running as administrator, or "
                    "download and install manually)",
                    "error",
                )
            self.installer_done.emit(self.success, "")
        except Exception as exc:
            self.success = False
            self._log(f"✗ Installer error: {exc}", "error")
            self.installer_done.emit(False, str(exc))
        finally:
            self._flush_logs()


class PipPanel(BasePanel):
    """Complete pip management panel with left (env list) + right (console) split."""

    def __init__(self, config_mgr, parent=None):
        super().__init__(config_mgr, parent)
        self.pip_mgr = PipManager(config_mgr)
        self._env_cards = {}
        self._update_queue = []
        self._active_update_envs = set()
        self._outdated_filter_enabled = False
        self._deferred_full_refresh_envs = set()
        self._scheduled_full_refresh_envs = set()
        from core.utils import StreamingAnsiStripper
        self._ansi_stripper = StreamingAnsiStripper()
        self._interceptor_buffer = ""
        self._active_operations = []  # list of dicts: {"env_path": str, "type": str, "pkgs": list, "marker": str}

        self._build_pip_ui()
        self._connect_signals()

    def _build_pip_ui(self):
        self._setup_common_toolbar(
            search_callback=self._on_search_text_changed,
            outdated_callback=self._toggle_outdated_only,
            refresh_callback=self.start_scan,
            batch_update_callback=self._batch_update,
            batch_remove_callback=self._batch_remove,
            manage_envs_callback=self._open_settings
        )

    def _connect_signals(self):
        self.pip_mgr.log_msg.connect(self._log)
        self.pip_mgr.log_batch.connect(self._log_batch)
        self.pip_mgr.env_scanned.connect(self._on_env_scanned)
        self.pip_mgr.specific_packages_scanned.connect(self._on_specific_packages_scanned)
        self.pip_mgr.runtime_update_done.connect(self._on_runtime_update_done)
        if hasattr(self.terminal, "pty_output_ready"):
            self.terminal.pty_output_ready.connect(self._on_pty_output_intercepted)

    # ── Status bar helper (delegated to parent window) ──

    def _log(self, msg: str, tag: str = "stdout"):
        self.console.log(msg, tag)

    def _log_batch(self, entries: list):
        self.console.log_batch(entries)

    # ── Scan ─────────────────────────────────────────────────────────────

    def start_scan(self):
        """Initial / Refresh all scan"""
        self.console.log_divider("REFRESH ALL")
        self._log("Starting global scan...", "system")
        self.refresh_btn.setEnabled(False)

        try:
            self._clear_env_card_widgets()

            self.pip_mgr.reload_envs()
            envs = self.pip_mgr.list_environments()

            if not envs:
                self._log("No Python environments found. Please add one in Settings.", "error")
                self.refresh_btn.setEnabled(True)
                return

            self._log(f"Loading {len(envs)} environments...", "system")
            self._env_cards = {}

            for env in envs:
                from ui.widgets.pip_env_card import PipEnvCard
                self._log(f"Initializing card for {env.name}...", "stdout")
                card = PipEnvCard(env)
                self._apply_current_filters_to_card(card)
                self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)

                norm_path = self._path_key(env.path)
                self._env_cards[norm_path] = card

                card.refresh_requested.connect(self._refresh_single_env)
                card.runtime_update_requested.connect(self._update_runtime_in_env)
                card.update_all_requested.connect(self._update_all_in_env)
                card.update_package_requested.connect(lambda p, c, e: self._start_pkg_update(p, e))
                card.remove_package_requested.connect(self._start_pkg_remove)
                card.add_package_requested.connect(self._start_pkg_install)
                card.selection_state_changed.connect(self._on_selection_state_changed)
                card.expand_toggled.connect(lambda *a: self._sync_expand_checkbox())
                card.activate_requested.connect(self._on_activate_requested)

                self.pip_mgr.scan_environment(env)

            self._log("All environments queued for scan.", "system")
        except Exception as e:
            import traceback
            self._log(f"Scan failed with error: {str(e)}", "error")
            self._log(traceback.format_exc(), "error")
            self.refresh_btn.setEnabled(True)

    def _on_env_scanned(self, env: Environment):
        norm_key = self._path_key(env.path)
        if norm_key in self._env_cards:
            card = self._env_cards[norm_key]
            card.update_ui()
            self._apply_outdated_state_to_card(card)

        if getattr(env, "_last_scan_mode", "full") == "fast" and norm_key in self._deferred_full_refresh_envs:
            self._deferred_full_refresh_envs.discard(norm_key)
            if norm_key not in self._scheduled_full_refresh_envs:
                self._scheduled_full_refresh_envs.add(norm_key)
                QTimer.singleShot(0, lambda path=env.path: self._start_background_full_refresh(path))
        QTimer.singleShot(200, self._check_all_tasks_done)

    def _check_all_tasks_done(self):
        if not self.pip_mgr._active_workers:
            self.refresh_btn.setEnabled(True)
            self._log("All tasks completed.", "system")
            self._update_status_counts()

    def _on_pty_output_intercepted(self, text: str):
        clean = self._ansi_stripper.feed(text)
        
        # Normalize carriage returns that might break regex matching
        clean = clean.replace("\r", "\n").replace("\x08", "")
        self._interceptor_buffer += clean
            
        if len(self._interceptor_buffer) > 64000:
            self._interceptor_buffer = self._interceptor_buffer[-64000:]
            
        import re
        
        while True:
            # Match only the evaluated output, not the echoed command which is preceded by 'echo '
            match = re.search(r"(?:^|[\r\n])(__OMNIPACK_OP_DONE_[a-f0-9]+__)", self._interceptor_buffer)
            if not match:
                break
                
            marker = match.group(1)
            
            # Find the corresponding operation
            op_index = next(
                (i for i, op in enumerate(self._active_operations) if op.get("marker") == marker),
                None
            )
            
            if op_index is None:
                # Marker from history or unknown, just discard up to this match
                self._interceptor_buffer = self._interceptor_buffer[match.end():]
                continue
                
            op = self._active_operations.pop(op_index)
            env = self._find_env_by_path(self.pip_mgr.environments, op["env_path"])
                
            if env:
                self.pip_mgr.scan_specific_packages(env, op["pkgs"])
                
            self._interceptor_buffer = self._interceptor_buffer[match.end():]

    def _on_specific_packages_scanned(self, env_path: str, found_pkgs: list, requested_names: list):
        norm_key = self._path_key(env_path)
        manager_env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if norm_key in self._env_cards and manager_env:
            card = self._env_cards[norm_key]
            env = manager_env
            card.env = env
            
            existing_pkg_map = {p.name.lower(): p for p in env.packages}
            found_names = set()
            
            for new_pkg in found_pkgs:
                found_names.add(new_pkg.name.lower())
                if new_pkg.name.lower() in existing_pkg_map:
                    # Update existing
                    old_pkg = existing_pkg_map[new_pkg.name.lower()]
                    old_pkg.version = new_pkg.version
                    old_pkg.latest_version = new_pkg.latest_version
                    old_pkg.has_update = new_pkg.has_update
                    old_pkg.metadata = new_pkg.metadata
                    old_pkg.requires = new_pkg.requires
                    old_pkg.required_by = new_pkg.required_by
                    old_pkg.is_top_level = new_pkg.is_top_level
                    old_pkg.is_missing = new_pkg.is_missing
                    old_pkg.version_constraint = new_pkg.version_constraint
                    old_pkg.norm_name = new_pkg.norm_name
                    old_pkg.breaks_constraint = getattr(new_pkg, "breaks_constraint", False)
                    old_pkg.build_variant_mismatch = getattr(new_pkg, "build_variant_mismatch", False)
                    card.update_package_in_ui(old_pkg)
                else:
                    # Add new
                    env.packages.append(new_pkg)
                    card.add_package_to_ui(new_pkg)
            
            # Remove packages that were requested but not found (uninstalled)
            for req_name in requested_names:
                req_lower = req_name.lower()
                if req_lower not in found_names:
                    if req_lower in existing_pkg_map:
                        env.packages.remove(existing_pkg_map[req_lower])
                        card.remove_package_from_ui(existing_pkg_map[req_lower].name)

            env.dep_graph = {
                getattr(pkg, "norm_name", ""): pkg
                for pkg in env.packages
                if getattr(pkg, "norm_name", "")
            }
            card.update_summary_label()
            card.update_ui()
            self._apply_outdated_state_to_card(card)
            card._refresh_selection_states()
            self._update_status_counts()

    def _update_status_counts(self):
        self._emit_status_counts(self.pip_mgr.environments)

    def _get_env(self, env_path: str):
        return self._find_env_by_path(self.pip_mgr.environments, env_path)

    # ── Single Env ───────────────────────────────────────────────────────

    def _refresh_single_env(self, env_path: str, scan_mode: str = "full", schedule_full: bool = False):
        target_key = self._path_key(env_path)
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env:
            self._log(f"Refreshing {env.name}...", "system")
            if schedule_full:
                self._deferred_full_refresh_envs.add(target_key)
            elif scan_mode == "full":
                self._deferred_full_refresh_envs.discard(target_key)
            env.is_scanned = False
            if target_key in self._env_cards:
                self._env_cards[target_key]._pkgs_loaded = False
            self.pip_mgr.scan_environment(env, scan_mode=scan_mode)

    def _start_background_full_refresh(self, env_path: str):
        target_key = self._path_key(env_path)
        self._scheduled_full_refresh_envs.discard(target_key)
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if not env:
            return

        self._log(f"Background refresh for {env.name}: checking updates and dependency tree...", "system")
        self.pip_mgr.scan_environment(env, scan_mode="full")

    def _update_runtime_in_env(self, env_path: str):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if not env:
            return

        current_ver = getattr(env, "runtime_version", "") or getattr(env, "python_version", "") or "Unknown"
        latest_ver = getattr(env, "runtime_latest_version", "") or "latest patch"
        if not getattr(env, "runtime_has_update", False):
            self._log(f"No Python runtime update available in {env.name}.", "system")
            return

        env_type = str(getattr(env, "type", "") or "").lower()
        cycle = getattr(env, "runtime_cycle", "") or ""
        cycle_display = f"Python {cycle}" if cycle else "Python"

        if env_type == "venv" and os.name == "nt":
            msg = (
                f"Update {cycle_display} runtime in {env.name}?\n\n"
                f"{current_ver} -> {latest_ver}\n\n"
                f"This will first update the system {cycle_display} installation\n"
                f"via winget, then upgrade this virtual environment.\n\n"
                f"This does not update packages."
            )
        else:
            msg = (
                f"Update {cycle_display} runtime in {env.name}?\n\n"
                f"{current_ver} -> {latest_ver}\n\n"
                f"This does not update packages."
            )

        reply = QMessageBox.question(
            self,
            title,
            msg,
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.console.log_divider(f"RUNTIME UPDATE in {env.name}")
            self.pip_mgr.update_runtime(env)

    def _on_runtime_update_done(self, env_path: str, success: bool, message: str,
                                 winget_failed: bool = False, target_version: str = ""):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        env_name = env.name if env else env_path
        if success:
            self._log(f"Python runtime update finished for {env_name}.", "success")
        elif winget_failed and target_version:
            self._log(
                f"Python runtime update failed for {env_name}: {message}", "error"
            )
            self._offer_installer_fallback("python", target_version, env_path)
        else:
            self._log(f"Python runtime update failed for {env_name}: {message}", "error")
            QMessageBox.warning(self, "Runtime Update Failed", message or "Runtime update command failed.")

        if not winget_failed:
            self._refresh_single_env(env_path, scan_mode="fast", schedule_full=True)

    def _offer_installer_fallback(self, runtime_kind: str, version: str, env_path: str):
        """Show a dialog offering to download and run the official installer."""
        label = "Node.js" if runtime_kind == "node" else "Python"
        url = get_python_installer_url(version) if runtime_kind == "python" else ""
        msg = (
            f"winget is unable to access its package source.\n\n"
            f"Would you like to download the official {label} {version} installer "
            f"and run it instead?\n\n"
            f"This will download ~30 MB and run the installer (may need admin rights)."
        )
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("winget Unavailable — Installer Fallback")
        msg_box.setText(msg)
        download_btn = msg_box.addButton("Download && Install", QMessageBox.AcceptRole)
        open_btn = msg_box.addButton("Open Download Page", QMessageBox.ActionRole)
        cancel_btn = msg_box.addButton("Cancel", QMessageBox.RejectRole)
        msg_box.exec()
        clicked = msg_box.clickedButton()

        if clicked == download_btn:
            self.console.log_divider(f"INSTALLER FALLBACK ({label} {version})")
            self._start_installer_download(runtime_kind, version, env_path)
        elif clicked == open_btn:
            if url:
                webbrowser.open(url)
                self._log(f"Opened download page for {label} {version}.", "system")
        # Cancel → nothing

    def _start_installer_download(self, runtime_kind: str, version: str, env_path: str):
        """Launch the installer download + run worker."""
        self._installer_worker = RuntimeInstallerWorker(
            runtime_kind,
            version,
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        self._installer_worker.log_msg.connect(self._log)
        self._installer_worker.log_batch.connect(self._log_batch)
        self._installer_worker.installer_done.connect(
            lambda success, msg: self._on_installer_done(env_path, success, msg)
        )
        self._installer_worker.start()

    def _on_installer_done(self, env_path: str, success: bool, message: str):
        if success:
            self._log("Runtime installer completed. Refreshing environment...", "system")
        elif message:
            QMessageBox.warning(self, "Installer Failed", message)
        self._refresh_single_env(env_path, scan_mode="fast", schedule_full=True)

    def _update_all_in_env(self, env_path: str):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env and env.is_scanned:
            outdated = [p.name for p in env.packages if p.has_update]
            if not outdated:
                self._log(f"No updatable packages in {env.name}.", "system")
                return
            self.console.log_divider(f"UPDATE ALL in {env.name}")
            import uuid
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "type": "update", "pkgs": outdated, "marker": marker})
            cmd_list = self.pip_mgr.build_update_command(env, outdated)
            cmd_str = __import__("subprocess").list2cmdline(cmd_list)
            
            shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
            if "powershell" in shell_name or "pwsh" in shell_name:
                cmd_str = f"{cmd_str} ; echo {marker}"
            else:
                cmd_str = f"{cmd_str} & echo {marker}"
                
            self.terminal.write(f'{cmd_str}\r')

    def _start_pkg_update(self, pkg_name: str, env_path: str):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env:
            self.console.log_divider(f"UPDATE {pkg_name}")
            import uuid
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "type": "update", "pkgs": [pkg_name], "marker": marker})
            cmd_list = self.pip_mgr.build_update_command(env, [pkg_name])
            cmd_str = __import__("subprocess").list2cmdline(cmd_list)
            
            shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
            if "powershell" in shell_name or "pwsh" in shell_name:
                cmd_str = f"{cmd_str} ; echo {marker}"
            else:
                cmd_str = f"{cmd_str} & echo {marker}"
                
            self.terminal.write(f'{cmd_str}\r')

    def _start_pkg_remove(self, pkg_name: str, env_path: str):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env:
            reply = QMessageBox.question(
                self, "Confirm Uninstall",
                f"Uninstall {pkg_name} from {env.name}?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.console.log_divider(f"UNINSTALL {pkg_name}")
                import uuid
                marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
                self._active_operations.append({"env_path": env.path, "type": "remove", "pkgs": [pkg_name], "marker": marker})
                
                cmd_list = self.pip_mgr.build_remove_command(env, [pkg_name])
                cmd_str = __import__("subprocess").list2cmdline(cmd_list)
                
                shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
                if "powershell" in shell_name or "pwsh" in shell_name:
                    cmd_str = f"{cmd_str} ; echo {marker}"
                else:
                    cmd_str = f"{cmd_str} & echo {marker}"
                    
                self.terminal.write(f'{cmd_str}\r')

    def _start_pkg_install(self, env_path: str, pkg_names: str, force_reinstall: bool = False):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env:
            import uuid
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "type": "install", "pkgs": pkg_names.split(), "marker": marker})
            
            cmd_list = self.pip_mgr.build_install_command(env, pkg_names, force_reinstall)
            cmd_str = __import__("subprocess").list2cmdline(cmd_list)
            
            shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
            if "powershell" in shell_name or "pwsh" in shell_name:
                cmd_str = f"{cmd_str} ; echo {marker}"
            else:
                cmd_str = f"{cmd_str} & echo {marker}"
                
            self.terminal.write(f'{cmd_str}\r')

    def _on_activate_requested(self, env_path: str):
        env = self._get_env(env_path)
        if not env:
            self._log("Failed to activate: environment not found.", "error")
            return
        
        from pathlib import Path
        from managers.pip_manager import resolve_python_executable
        
        exe_path = resolve_python_executable(env)
        if not exe_path:
            self._log(f"No executable path found for {env.name}, cannot activate.", "error")
            return
            
        executable = Path(exe_path)

        # Simulated mode: open external terminal since ConsolePanel can't execute commands
        if self.terminal is self.console:
            if getattr(env, "type", "") == "venv":
                target_dir = str(executable.parent.parent)
            else:
                target_dir = str(executable.parent)
            self._log(f"Opening external terminal at {target_dir}...", "cmd")
            try:
                subprocess.Popen(f'start cmd /k "cd /d {target_dir}"', shell=True, cwd=target_dir)
            except Exception as e:
                self._log(f"Failed to open terminal: {e}", "error")
            return

        shell_name = "cmd.exe"
        if hasattr(self.terminal, "_resolve_shell"):
            shell_name = os.path.basename(self.terminal._resolve_shell()).lower()
            
        is_powershell = "powershell" in shell_name or "pwsh" in shell_name
        
        if getattr(env, "type", "") == "venv":
            scripts_dir = executable.parent
            project_dir = scripts_dir.parent
            
            self._log(f"Activating {env.name} in terminal...", "cmd")
            
            # Change directory to the project root
            if is_powershell:
                self.terminal.write(f'Set-Location -LiteralPath "{project_dir}"\r')
            else:
                self.terminal.write(f'pushd "{project_dir}"\r')
            
            # Execute activate script based on shell
            if is_powershell:
                activate_script = scripts_dir / "Activate.ps1"
                if activate_script.exists():
                    cmd = f"(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -ErrorAction Ignore) ; (. '{activate_script}')"
                    self.terminal.write(cmd + "\r")
            else:
                activate_bat = scripts_dir / "activate.bat"
                if activate_bat.exists():
                    cmd = f'"{activate_bat}"'
                else:
                    activate_script = scripts_dir / "activate"
                    cmd = f'"{activate_script}"'
                self.terminal.write(cmd + "\r")
                
        else:
            self._log(f"Opening {env.name} in terminal...", "cmd")
            # For System environments (e.g., Blender Python, global Python), there is no activate script.
            # We just change directory to where the executable lives.
            target_dir = executable.parent
            if is_powershell:
                self.terminal.write(f'Set-Location -LiteralPath "{target_dir}"\r')
            else:
                self.terminal.write(f'pushd "{target_dir}"\r')

    # ── Selection / Filter ───────────────────────────────────────────────

    def _select_all(self):
        for card in self._env_cards.values():
            card.set_all_selected(True)
        self._sync_outdated_checkbox_state()
        self._sync_selection_checkbox_state()

    def _deselect_all(self):
        for card in self._env_cards.values():
            card.set_all_selected(False)
        self._sync_outdated_checkbox_state()
        self._sync_selection_checkbox_state()

    def _toggle_outdated_only(self, state):
        if isinstance(state, bool):
            state = Qt.Checked if state else Qt.Unchecked

        raw_state = state.value if hasattr(state, "value") else int(state)

        # Treat toolbar interaction as a binary toggle. The checkbox may display
        # a partial state as feedback, but user clicks should still behave as
        # simple on/off for the outdated filter.
        if self._outdated_filter_enabled:
            self._outdated_filter_enabled = False
            is_checked = False
            selection_mode = "clear_all"
        else:
            self._outdated_filter_enabled = True
            is_checked = True
            selection_mode = "select_all"

        for card in self._env_cards.values():
            card.set_outdated_only(is_checked, selection_mode=selection_mode)
        self._sync_outdated_checkbox_state()
        self._sync_selection_checkbox_state()
        if is_trace_enabled():
            trace_event(
                "pip_panel",
                "toolbar_outdated_change",
                state=int(raw_state),
                enabled=self._outdated_filter_enabled,
                selection_mode=selection_mode,
                trace_path=get_trace_path(),
            )

    def _on_search_text_changed(self, text):
        q = text.lower()
        for env_path, card in self._env_cards.items():
            card.filter_packages(q)

    # ── Batch Update ─────────────────────────────────────────────────────

    def _batch_update(self):
        env_packages = {}
        env_objects = {}
        for _env_path, card in self._env_cards.items():
            env = card.env
            if getattr(env, "is_scanned", False):
                pkgs = [pkg.name for pkg in env.packages if getattr(pkg, "is_selected", False) and getattr(pkg, "has_update", False)]
                if pkgs:
                    key = self._path_key(env.path)
                    env_packages[key] = pkgs
                    env_objects[key] = env

        if not env_packages:
            self._log("No updatable packages selected.", "system")
            return

        total = sum(len(v) for v in env_packages.values())
        self.console.log_divider(f"BATCH UPDATE ({total} packages across {len(env_packages)} environments)")
        for key, pkg_names in env_packages.items():
            env = env_objects[key]
            import uuid
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "type": "update", "pkgs": pkg_names, "marker": marker})
            cmd_list = self.pip_mgr.build_update_command(env, pkg_names)
            cmd_str = subprocess.list2cmdline(cmd_list)
            self.terminal.write(f'{cmd_str}\r')
            self.terminal.write(f'echo {marker}\r')

    # ── Batch Remove ─────────────────────────────────────────────────────

    def _batch_remove(self):
        env_packages = {}
        env_objects = {}
        for _env_path, card in self._env_cards.items():
            env = card.env
            if getattr(env, "is_scanned", False):
                pkgs = [pkg.name for pkg in env.packages if getattr(pkg, "is_selected", False)]
                if pkgs:
                    key = self._path_key(env.path)
                    env_packages[key] = pkgs
                    env_objects[key] = env

        if not env_packages:
            self._log("No packages selected for batch remove.", "system")
            return

        total = sum(len(v) for v in env_packages.values())
        reply = QMessageBox.question(
            self, "Confirm Batch Uninstall",
            f"Are you sure you want to uninstall {total} packages?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.console.log_divider(f"BATCH UNINSTALL ({total} packages across {len(env_packages)} environments)")
            for key, pkg_names in env_packages.items():
                env = env_objects[key]
                import uuid
                marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
                self._active_operations.append({"env_path": env.path, "type": "remove", "pkgs": pkg_names, "marker": marker})
                cmd_list = self.pip_mgr.build_remove_command(env, pkg_names)
                cmd_str = subprocess.list2cmdline(cmd_list)
                self.terminal.write(f'{cmd_str}\r')
                self.terminal.write(f'echo {marker}\r')

    # ── Settings ─────────────────────────────────────────────────────────

    def _open_settings(self):
        from ui.panels.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.config_mgr, initial_tab="pip", parent=self)

        def on_envs_changed():
            self._log("Config changed. Syncing UI...", "system")
            old_keys = set(self._env_cards.keys())

            self.pip_mgr.reload_envs()
            new_envs = self.pip_mgr.list_environments()
            new_keys = {self._path_key(e.path) for e in new_envs}

            # Removals
            for key in (old_keys - new_keys):
                card = self._env_cards.pop(key)
                card.deleteLater()

            # Additions
            for key in (new_keys - old_keys):
                env = next(e for e in new_envs if self._path_key(e.path) == key)
                from ui.widgets.pip_env_card import PipEnvCard
                card = PipEnvCard(env)
                self._apply_current_filters_to_card(card)
                self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)
                self._env_cards[key] = card

                card.refresh_requested.connect(self._refresh_single_env)
                card.runtime_update_requested.connect(self._update_runtime_in_env)
                card.update_all_requested.connect(self._update_all_in_env)
                card.update_package_requested.connect(lambda p, c, e: self._start_pkg_update(p, e))
                card.remove_package_requested.connect(self._start_pkg_remove)
                card.add_package_requested.connect(self._start_pkg_install)
                card.selection_state_changed.connect(self._on_selection_state_changed)
                card.expand_toggled.connect(lambda *a: self._sync_expand_checkbox())
                self.pip_mgr.scan_environment(env)

            # Existing: force UI refresh (name changes, etc.)
            for key in (old_keys & new_keys):
                self._env_cards[key].update_ui()

            # Reorder cards to match new env order (no scanning)
            self._reorder_env_cards(new_envs, self._env_cards)
            self._sync_expand_checkbox()

        dialog.settings_changed.connect(on_envs_changed)
        dialog.exec()

    def _apply_outdated_state_to_card(self, card):
        state = self.outdated_checkbox.checkState()
        checked_val = Qt.Checked.value if hasattr(Qt.Checked, "value") else 2
        partial_val = Qt.PartiallyChecked.value if hasattr(Qt.PartiallyChecked, "value") else 1
        raw_state = state.value if hasattr(state, "value") else int(state)

        if raw_state == checked_val:
            card.set_outdated_only(True, selection_mode="select_all")
            self._outdated_filter_enabled = True
        elif raw_state == partial_val:
            card.set_outdated_only(True, selection_mode="keep")
            self._outdated_filter_enabled = True
        else:
            card.set_outdated_only(False, selection_mode="clear_all")
            self._outdated_filter_enabled = False

    def _sync_outdated_checkbox_state(self):
        total = 0
        selected = 0
        for env in self.pip_mgr.environments:
            for pkg in env.packages:
                if pkg.has_update and not getattr(pkg, "is_missing", False):
                    total += 1
                    if pkg.is_selected:
                        selected += 1

        if not self._outdated_filter_enabled or selected == 0:
            target = Qt.Unchecked
        elif total == 0 or selected == total:
            target = Qt.Checked
        else:
            target = Qt.PartiallyChecked

        if target == Qt.Unchecked and self._outdated_filter_enabled:
            self._outdated_filter_enabled = False
            for card in self._env_cards.values():
                card.set_outdated_only(False, selection_mode="keep")

        self.outdated_checkbox.blockSignals(True)
        self.outdated_checkbox.setCheckState(target)
        self.outdated_checkbox.blockSignals(False)
        if is_trace_enabled():
            trace_event(
                "pip_panel",
                "toolbar_outdated_sync",
                total_outdated=total,
                selected_outdated=selected,
                state=int(target.value if hasattr(target, "value") else int(target)),
            )

    def _sync_selection_checkbox_state(self):
        total = 0
        selected = 0
        for env in self.pip_mgr.environments:
            if not getattr(env, "is_scanned", False):
                continue
            for pkg in getattr(env, "packages", []):
                if getattr(pkg, "is_missing", False):
                    continue
                total += 1
                if getattr(pkg, "is_selected", False):
                    selected += 1

        if total == 0 or selected == 0:
            target = Qt.Unchecked
        elif selected == total:
            target = Qt.Checked
        else:
            target = Qt.PartiallyChecked

        self._set_selection_checkbox_state(target)

    def _on_selection_state_changed(self, _env_path, _selected, _total):
        self._sync_outdated_checkbox_state()
        self._sync_selection_checkbox_state()
