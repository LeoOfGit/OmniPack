from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QCheckBox,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer, Signal
import os
import subprocess
import uuid

from managers.winget_manager import WingetManager
from core.terminal.command_renderer import ShellCommandRenderer
from core.utils import StreamingAnsiStripper
from ui.panels.base_panel import BasePanel
from core.winget_helpers import find_uninstall_location
from managers.base_worker import BaseCmdWorker

class WingetInstallerWorker(BaseCmdWorker):
    """Download and run the WinGet installer from GitHub."""
    installer_done = Signal(bool, str)

    def __init__(self, proxy_settings=None):
        super().__init__()
        self.proxy_settings = proxy_settings or {}

    def run(self):
        try:
            self._log("Downloading WinGet from GitHub...", "system")
            from core.runtime_update import install_winget
            
            def _progress(msg):
                self._log(msg, "system")

            success, err = install_winget(
                proxy_settings=self.proxy_settings,
                log_callback=_progress
            )
            
            if not success:
                self.success = False
                self._log(f"✗ Installation failed: {err}", "error")
                self.installer_done.emit(False, err)
                return

            self.success = True
            self._log("✓ WinGet installation completed successfully", "success")
            self.installer_done.emit(True, "")
        except Exception as exc:
            self.success = False
            self._log(f"✗ Installer error: {exc}", "error")
            self.installer_done.emit(False, str(exc))
        finally:
            self._flush_logs()


class WingetPanel(BasePanel):
    def __init__(self, config_mgr, parent=None):
        super().__init__(config_mgr, parent)
        self.winget_mgr = WingetManager(config_mgr)
        self._env_cards = {}
        self._outdated_filter_enabled = False
        self._active_operations = []
        
        self._marker_timer = QTimer(self)
        self._marker_timer.timeout.connect(self._check_marker_files)
        self._marker_timer.start(1000)

        self._pin_refresh_targets = set()
        self._first_winget_settings_ensured = False
        self._init_proxy_workers = set()

        self._build_winget_ui()
        self._connect_signals()

    def _build_winget_ui(self):
        self._setup_common_toolbar(
            search_callback=self._on_search_text_changed,
            outdated_callback=self._toggle_outdated_only,
            refresh_callback=self.start_scan,
            batch_update_callback=self._batch_update,
            batch_remove_callback=self._batch_remove,
            manage_envs_callback=self._open_settings,
        )
        if hasattr(self, "add_env_btn"):
            self.add_env_btn.setVisible(False)
            
        from ui.widgets.runtime_setup_widget import RuntimeSetupWidget
        self.setup_widget = RuntimeSetupWidget("winget")
        self.setup_widget.install_requested.connect(self._on_install_missing_runtime)
        self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, self.setup_widget)
        self.setup_widget.hide()

    def _on_install_missing_runtime(self, runtime_kind, version):
        self.console.log_divider(f"INSTALLING WINGET")
        self._installer_worker = WingetInstallerWorker(
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {}
        )
        self._installer_worker.log_msg.connect(self._log)
        self._installer_worker.log_batch.connect(self._log_batch)
        self._installer_worker.installer_done.connect(self._on_installer_done)
        self._installer_worker.start()

    def _on_installer_done(self, success: bool, message: str):
        if hasattr(self, "setup_widget"):
            self.setup_widget.reset_state()
            
        if success:
            self._log("WinGet installer completed. Refreshing...", "system")
            self.start_scan()
        elif message:
            QMessageBox.warning(self, "Installer Failed", message)

    def _connect_signals(self):
        self.winget_mgr.log_msg.connect(self._log)
        self.winget_mgr.log_batch.connect(self._log_batch)
        self.winget_mgr.env_scanned.connect(self._on_env_scanned)
        self.winget_mgr.pin_done.connect(self._on_pin_done)
        self.winget_mgr.pin_state_ready.connect(self._on_pin_state_ready)
        if hasattr(self.terminal, "pty_output_ready"):
            self.terminal.pty_output_ready.connect(self._on_pty_output_intercepted)
        self.winget_mgr.pin_done.connect(self._on_pin_done)
        self.winget_mgr.pin_state_ready.connect(self._on_pin_state_ready)

    def _log(self, msg: str, tag: str = "stdout"):
        self.console.log(msg, tag)

    def _log_batch(self, entries: list):
        self.console.log_batch(entries)

    def start_scan(self):
        self.console.log_divider("REFRESH WINGET")
        self._log("Starting WinGet scan...", "system")
        self.refresh_btn.setEnabled(False)

        # 稳健的 WinGet 代理自愈和首次状态确保机制
        if os.name == "nt" and not getattr(self, "_first_winget_settings_ensured", False):
            self._first_winget_settings_ensured = True
            proxy_cfg = getattr(self.config_mgr.config, "proxy_settings", {}) or {}
            enabled = proxy_cfg.get("enabled", False)
            targets = proxy_cfg.get("targets", {})
            winget_proxy_checked = enabled and targets.get("winget", False)
            
            if winget_proxy_checked:
                self._log("WinGet proxy is configured as ENABLED. Ensuring WinGet settings are active...", "system")
                self._log("Executing: winget settings --enable ProxyCommandLineOptions", "system")
                
                from ui.panels.winget_settings_page import WingetTaskWorker
                w_settings = getattr(self.config_mgr.config, "winget_settings", {}) or {}
                w_path = w_settings.get("winget_path", "") if isinstance(w_settings, dict) else ""
                
                worker = WingetTaskWorker(
                    "enable-proxy",
                    proxy_cfg,
                    winget_path=w_path
                )
                
                def on_init_proxy_done(task_name, payload, error):
                    if error:
                        self._log(f"Failed to ensure WinGet ProxyCommandLineOptions enabled: {error}", "error")
                    else:
                        self._log("WinGet ProxyCommandLineOptions ensured and enabled successfully on panel start.", "success")
                
                worker.finished_task.connect(on_init_proxy_done)
                worker.finished.connect(lambda w=worker: self._init_proxy_workers.discard(w))
                worker.finished.connect(worker.deleteLater)
                self._init_proxy_workers.add(worker)
                worker.start()

        try:
            self.winget_mgr.invalidate_scan_cache()

            self._clear_env_card_widgets()
            self.winget_mgr.reload_envs()
            envs = self.winget_mgr.list_environments()
            
            force_show = getattr(self.config_mgr.config, "force_show_setup", False)
            if force_show:
                self.setup_widget.show()
            else:
                self.setup_widget.hide()
                
            if not envs:
                self._log("WinGet is not installed on this system.", "error")
                self.setup_widget.show()
                self.refresh_btn.setEnabled(True)
                return

            self._env_cards = {}
            for env in envs:
                from ui.widgets.winget_env_card import WingetEnvCard

                card = WingetEnvCard(env)
                self._apply_current_filters_to_card(card)
                
                idx = self.scroll_layout.indexOf(self.setup_widget)
                if idx == -1:
                    idx = self.scroll_layout.count() - 2
                self.scroll_layout.insertWidget(idx, card)
                
                self._env_cards[self._path_key(env.path)] = card

                card.refresh_requested.connect(self._refresh_single_env)
                card.update_all_requested.connect(self._update_all_in_env)
                card.runtime_update_requested.connect(self._update_runtime_in_env)
                card.update_package_requested.connect(self._start_pkg_update)
                card.remove_package_requested.connect(self._start_pkg_remove)
                card.add_package_requested.connect(self._start_pkg_install)
                card.config_package_requested.connect(self._config_package)
                card.selection_state_changed.connect(self._on_selection_state_changed)
                card.expand_toggled.connect(lambda *_args: self._sync_expand_checkbox())

                self.winget_mgr.scan_environment(env)
        except Exception as e:
            import traceback
            self._log(f"Scan failed with error: {str(e)}", "error")
            self._log(traceback.format_exc(), "error")
            self.refresh_btn.setEnabled(True)

    def _on_env_scanned(self, env):
        self._refresh_duplicate_markers()
        norm_key = self._path_key(env.path)
        if norm_key in self._env_cards:
            card = self._env_cards[norm_key]
            card.update_ui()
            self._apply_outdated_state_to_card(card)
        for key, card in self._env_cards.items():
            if key != norm_key:
                card.update_ui()
        QTimer.singleShot(200, self._check_all_tasks_done)

    def _check_all_tasks_done(self):
        if not self.winget_mgr._active_workers:
            self.refresh_btn.setEnabled(True)
            self._log("All tasks completed.", "system")
            self._update_status_counts()

    def _on_pty_output_intercepted(self, text: str):
        pass  # Kept for backward compatibility with tests
        
    def _check_marker_files(self):
        import os
        import tempfile
        temp_dir = tempfile.gettempdir()
        
        remaining_ops = []
        for op in self._active_operations:
            marker = op.get("marker")
            if not marker:
                continue
                
            marker_file = os.path.join(temp_dir, f"{marker}.done")
            if os.path.exists(marker_file):
                try:
                    with open(marker_file, "r") as f:
                        exit_code_str = f.read().strip()
                    exit_code = int(exit_code_str) if exit_code_str.isdigit() or (exit_code_str.startswith("-") and exit_code_str[1:].isdigit()) else 0
                    
                    try:
                        os.remove(marker_file)
                    except OSError:
                        pass
                        
                    env = self._find_env_by_path(self.winget_mgr.environments, op["env_path"])
                    if env:
                        if exit_code != 0:
                            self._log(f"Command failed with exit code {exit_code}. Doing full refresh instead of optimistic.", "error")
                        self._refresh_single_env(env.path)
                except Exception as e:
                    self._log(f"Error reading marker file: {e}", "error")
                    env = self._find_env_by_path(self.winget_mgr.environments, op["env_path"])
                    if env:
                        self._refresh_single_env(env.path)
            else:
                remaining_ops.append(op)
                
        self._active_operations = remaining_ops

    def _build_terminal_command(self, cmd_list: list[str], marker: str) -> str:
        from core.terminal.command_renderer import ShellCommandRenderer
        shell_name = (
            os.path.basename(self.terminal._resolve_shell()).lower()
            if hasattr(self.terminal, "_resolve_shell")
            else "cmd.exe"
        )
        cmd_str = ShellCommandRenderer.render(cmd_list, shell_name)
        return ShellCommandRenderer.append_marker(cmd_str, marker, shell_name, include_exit_code=True)

    def _build_update_terminal_command(self, env, package_spec: dict, marker: str) -> str:
        from core.terminal.command_renderer import ShellCommandRenderer
        shell_name = (
            os.path.basename(self.terminal._resolve_shell()).lower()
            if hasattr(self.terminal, "_resolve_shell")
            else "cmd.exe"
        )
        primary = ShellCommandRenderer.render(self.winget_mgr.build_update_command(env, package_spec), shell_name)
        fallback = ShellCommandRenderer.render(self.winget_mgr.build_update_fallback_install_command(env, package_spec), shell_name)

        is_pwsh = "powershell" in shell_name or "pwsh" in shell_name
        is_posix = shell_name in {"sh", "bash", "zsh", "fish", "dash"}

        if is_pwsh:
            cmd = f"{primary}; if ($LASTEXITCODE -ne 0) {{ {fallback} }}"
        elif is_posix:
            cmd = f"{primary} || {fallback}"
        else:
            cmd = f"{primary} || {fallback}"
        return ShellCommandRenderer.append_marker(cmd, marker, shell_name, include_exit_code=True)

    def _update_status_counts(self):
        self._emit_status_counts(self.winget_mgr.environments)

    def _refresh_duplicate_markers(self):
        pass

    def _get_env(self, env_path: str):
        return self._find_env_by_path(self.winget_mgr.environments, env_path)

    def _find_package(self, env, target: str):
        target = str(target or "").strip()
        if not env or not target:
            return None
        
        parts = target.split(":")
        clean_target = parts[0]
        location = parts[1] if len(parts) > 1 else None
        version = parts[2] if len(parts) > 2 else None
        
        target_norm = clean_target.lower()
        for pkg in getattr(env, "packages", []):
            metadata = getattr(pkg, "metadata", {}) or {}
            candidates = {
                str(metadata.get("target_id", "")).strip().lower(),
                str(metadata.get("package_id", "")).strip().lower(),
                str(pkg.name).strip().lower(),
            }
            candidates.discard("")
            if target_norm in candidates:
                # Match version if specified
                if version and str(pkg.version).strip() != version:
                    continue
                # Match location scope if specified
                if location and location in {"user", "system"}:
                    pkg_loc = metadata.get("location")
                    if pkg_loc:
                        pkg_scope = pkg_loc
                        if "\\" in pkg_loc or "/" in pkg_loc or ":" in pkg_loc:
                            import os
                            user_profile = os.environ.get("USERPROFILE", "").lower()
                            if user_profile and pkg_loc.lower().startswith(user_profile):
                                pkg_scope = "user"
                            elif "c:\\users\\" in pkg_loc.lower():
                                pkg_scope = "user"
                            else:
                                pkg_scope = "system"
                        if pkg_scope != location:
                            continue
                return pkg
        return None

    @staticmethod
    def _package_spec(pkg) -> dict:
        metadata = getattr(pkg, "metadata", {}) or {}
        return {
            "name": pkg.name,
            "target_id": str(metadata.get("target_id", "")).strip() or pkg.name,
            "package_id": str(metadata.get("package_id", "")).strip() or pkg.name,
            "scope": str(metadata.get("scope", "")).strip(),
            "installed_scope": str(metadata.get("installed_scope", "")).strip(),
            "source": str(metadata.get("source", "")).strip(),
        }

    def _refresh_single_env(self, env_path: str):
        env = self._get_env(env_path)
        if not env:
            return
        self._log(f"Refreshing {env.name}...", "system")
        self.winget_mgr.invalidate_scan_cache()
        env.is_scanned = False
        key = self._path_key(env.path)
        if key in self._env_cards:
            self._env_cards[key]._pkgs_loaded = False
        self.winget_mgr.scan_environment(env)

    def _update_all_in_env(self, env_path: str):
        env = self._get_env(env_path)
        if not env or not getattr(env, "is_scanned", False):
            return
        package_specs = [
            self._package_spec(pkg)
            for pkg in env.packages
            if getattr(pkg, "has_update", False) and (getattr(pkg, "metadata", {}) or {}).get("can_update", True)
        ]
        if not package_specs:
            self._log(f"No updatable applications in {env.name}.", "system")
            return
        self.console.log_divider(f"UPDATE ALL in {env.name}")
        cmds = []
        for spec in package_specs:
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "marker": marker})
            cmds.append(self._build_update_terminal_command(env, spec, marker))
        cmd_str = "\n".join(cmds)
        ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _start_pkg_update(self, package_target: str, _channel: str, env_path: str):
        env = self._get_env(env_path)
        pkg = self._find_package(env, package_target)
        if not env or not pkg:
            return
        if not (getattr(pkg, "metadata", {}) or {}).get("can_update", True):
            self._config_package(package_target, env_path)
            return
        self.console.log_divider(f"UPDATE {pkg.name}")
        package_spec = self._package_spec(pkg)
        marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
        self._active_operations.append({"env_path": env.path, "marker": marker})
        cmd_str = self._build_update_terminal_command(env, package_spec, marker)
        ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _update_runtime_in_env(self, env_path: str):
        env = self._get_env(env_path)
        if not env:
            return

        current_ver = getattr(env, "runtime_version", "") or "Unknown"
        latest_ver = getattr(env, "runtime_latest_version", "") or "latest"
        if not getattr(env, "runtime_has_update", False):
            self._log("Winget (App Installer) is up to date.", "system")
            return

        msg = (
            f"Update Winget (App Installer)?\n\n"
            f"{current_ver} -> {latest_ver}\n\n"
            f"This will update Microsoft.AppInstaller which provides Winget."
        )

        reply = QMessageBox.question(
            self,
            "Confirm Runtime Update",
            msg,
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.console.log_divider("UPDATE WINGET RUNTIME")
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "marker": marker})
            
            winget = self.winget_mgr._current_settings().get("winget_path", "") or "winget"
            cmd_list = [
                winget, "upgrade", "--id", "Microsoft.AppInstaller",
                "--accept-package-agreements", "--accept-source-agreements", "--exact"
            ]
            cmd_str = self._build_terminal_command(cmd_list, marker)
            ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _start_pkg_remove(self, package_target: str, env_path: str):
        env = self._get_env(env_path)
        pkg = self._find_package(env, package_target)
        if not env or not pkg:
            return
        
        reply = QMessageBox.question(
            self,
            "Confirm Uninstall",
            f"Uninstall {pkg.name}?\n\nID: {(getattr(pkg, 'metadata', {}) or {}).get('package_id', pkg.name)}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.console.log_divider(f"UNINSTALL {pkg.name}")
            cmd_list = self.winget_mgr.build_remove_command(env, self._package_spec(pkg))
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "marker": marker})
            cmd_str = self._build_terminal_command(cmd_list, marker)
            ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _start_pkg_install(self, env_path: str, package_ref: str, _force: bool = False):
        env = self._get_env(env_path)
        if not env:
            return
        self.console.log_divider(f"INSTALL {package_ref}")
        cmd_list = self.winget_mgr.build_install_command(env, package_ref)
        marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
        self._active_operations.append({"env_path": env.path, "marker": marker})
        cmd_str = self._build_terminal_command(cmd_list, marker)
        ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _config_package(self, package_target: str, env_path: str):
        env = self._get_env(env_path)
        pkg = self._find_package(env, package_target)
        if not env or not pkg:
            return

        metadata = getattr(pkg, "metadata", {}) or {}
        if getattr(pkg, "is_missing", False):
            metadata["pin_state_known"] = True
            metadata["pinned_blocking"] = False

        if metadata.get("pin_state_known", False):
            self._open_package_config_dialog(env, pkg)
            return

        pkg_id = str(metadata.get("package_id", "")).strip() or pkg.name
        self._pin_refresh_targets.add((env.path, package_target))
        self._log(f"Querying pin state for {pkg.name}...", "system")
        self.winget_mgr.query_pin_state(env, pkg_id)

    def _on_pin_state_ready(self, env_path: str, package_id: str, is_pinned: bool):
        env = self._get_env(env_path)
        if not env:
            return

        # Find all pending targets for this package_id and open their dialogs
        for target in list(self._pin_refresh_targets):
            t_env_path, t_pkg_target = target
            if t_env_path == env_path:
                t_pkg_id = t_pkg_target.split(":", 1)[0]
                if t_pkg_id.lower() == package_id.lower():
                    self._pin_refresh_targets.discard(target)
                    pkg = self._find_package(env, t_pkg_target)
                    if pkg:
                        metadata = getattr(pkg, "metadata", {}) or {}
                        metadata["pin_state_known"] = True
                        metadata["pinned_blocking"] = is_pinned
                        metadata["can_update"] = not is_pinned
                        metadata["update_blocked_reason"] = "Pinned by winget" if is_pinned else ""
                        badges = [badge for badge in metadata.get("badges", []) if "[Pinned]" not in str(badge)]
                        if is_pinned:
                            badges.append({"text": "[Pinned]", "tooltip": "Update is blocked by a winget pin."})
                        metadata["badges"] = badges

                        self._open_package_config_dialog(env, pkg)

    @staticmethod
    def _find_uninstall_location(package_name: str, package_id: str = "") -> str:
        return find_uninstall_location(package_name, package_id)

    def _open_package_config_dialog(self, env, pkg):
        metadata = getattr(pkg, "metadata", {}) or {}
        is_pinned = bool(metadata.get("pinned_blocking", False))
        package_id = str(metadata.get("package_id", "")).strip() or pkg.name
        source_name = str(metadata.get("source", "")).strip() or "(auto)"

        install_location = self._find_uninstall_location(pkg.name, package_id)
        newer_than_server = bool(metadata.get("newer_than_server", False))

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Configure {pkg.name}")
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        form.addRow("Name:", QLabel(pkg.name))
        form.addRow("ID:", QLabel(package_id))
        form.addRow("Source:", QLabel(source_name))
        inst_ver = "Not Installed" if getattr(pkg, "is_missing", False) else pkg.version
        form.addRow("Installed:", QLabel(inst_ver))
        form.addRow("Available:", QLabel(pkg.latest_version or "-"))
        if install_location:
            loc_lbl = QLabel(install_location)
            loc_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            loc_lbl.setWordWrap(True)
            form.addRow("Location:", loc_lbl)
        layout.addLayout(form)

        if newer_than_server:
            warn = QLabel("Installed version is newer than the winget registry. Downgrading is not recommended.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #FFB74D;")
            layout.addWidget(warn)

        note = QLabel("Use a blocking pin to hide future WinGet updates for this application.")
        note.setWordWrap(True)
        layout.addWidget(note)

        pin_check = QCheckBox("Ignore updates for this application (winget blocking pin)")
        pin_check.setChecked(is_pinned)
        if getattr(pkg, "is_missing", False):
            pin_check.setEnabled(False)
            pin_check.setToolTip("Cannot ignore updates for an application that is not installed.")
        layout.addWidget(pin_check)

        if is_pinned and pkg.latest_version:
            warning = QLabel("This package currently has a newer version, but the update is blocked by a pin.")
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #FFB74D;")
            layout.addWidget(warning)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        def get_details():
            details = [
                f"Name: {pkg.name}",
                f"ID: {package_id}",
                f"Source: {source_name}",
                f"Installed: {inst_ver}",
                f"Available: {pkg.latest_version or '-'}"
            ]
            if install_location:
                details.append(f"Location: {install_location}")
            return "\n".join(details)

        from ui.utils import add_copy_details_button
        add_copy_details_button(dialog, get_details, buttons)

        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        if pin_check.isChecked() == is_pinned:
            return

        self.console.log_divider(f"{'PIN' if pin_check.isChecked() else 'UNPIN'} {pkg.name}")
        self.winget_mgr.set_pin_state(env, self._package_spec(pkg), pin_check.isChecked())

    def _on_pin_done(self, env_path: str, package_id: str, success: bool, enabled: bool):
        action = "Pinned" if enabled else "Unpinned"
        if success:
            self._log(f"{action} {package_id}.", "success")
        else:
            self._log(f"Failed to change pin state for {package_id}.", "error")
            QMessageBox.warning(self, "Pin Action Failed", f"Failed to change pin state for {package_id}.")
        self._refresh_single_env(env_path)

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

    def _on_search_text_changed(self, text):
        query = text.lower()
        for _env_path, card in self._env_cards.items():
            card.filter_packages(query)

    def _batch_update(self):
        env_specs = {}
        env_objects = {}
        for _env_path, card in self._env_cards.items():
            env = card.env
            if not getattr(env, "is_scanned", False):
                continue
            specs = []
            for pkg in env.packages:
                metadata = getattr(pkg, "metadata", {}) or {}
                if getattr(pkg, "is_selected", False) and getattr(pkg, "has_update", False) and metadata.get("can_update", True):
                    specs.append(self._package_spec(pkg))
            if specs:
                env_specs[self._path_key(env.path)] = specs
                env_objects[self._path_key(env.path)] = env

        if not env_specs:
            self._log("No updatable applications selected.", "system")
            return

        total = sum(len(specs) for specs in env_specs.values())
        self.console.log_divider(f"BATCH UPDATE ({total} applications)")
        for key, specs in env_specs.items():
            env = env_objects[key]
            cmds = []
            for spec in specs:
                marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
                self._active_operations.append({"env_path": env.path, "marker": marker})
                cmds.append(self._build_update_terminal_command(env, spec, marker))
            cmd_str = "\n".join(cmds)
            ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _batch_remove(self):
        env_specs = {}
        env_objects = {}
        for _env_path, card in self._env_cards.items():
            env = card.env
            if not getattr(env, "is_scanned", False):
                continue
            specs = []
            for pkg in env.packages:
                if getattr(pkg, "is_selected", False):
                    specs.append(self._package_spec(pkg))
            if specs:
                env_specs[self._path_key(env.path)] = specs
                env_objects[self._path_key(env.path)] = env

        if not env_specs:
            self._log("No applications selected for uninstall.", "system")
            return

        total = sum(len(specs) for specs in env_specs.values())
        reply = QMessageBox.question(
            self, "Confirm Batch Uninstall",
            f"Are you sure you want to uninstall {total} selected applications?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.console.log_divider(f"BATCH UNINSTALL ({total} applications)")
            for key, specs in env_specs.items():
                env = env_objects[key]
                cmds = []
                for spec in specs:
                    cmd_list = self.winget_mgr.build_remove_command(env, spec)
                    marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
                    self._active_operations.append({"env_path": env.path, "marker": marker})
                    cmds.append(self._build_terminal_command(cmd_list, marker))
                cmd_str = "\n".join(cmds)
                ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _open_settings(self):
        from ui.panels.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.config_mgr, initial_tab="backend", parent=self)
        dialog.settings_changed.connect(self.start_scan)
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
        for env in self.winget_mgr.environments:
            for pkg in env.packages:
                metadata = getattr(pkg, "metadata", {}) or {}
                if pkg.has_update and metadata.get("can_update", True):
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

    def _sync_selection_checkbox_state(self):
        total = 0
        selected = 0
        for env in self.winget_mgr.environments:
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
