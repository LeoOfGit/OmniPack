import os
import json
import subprocess
import webbrowser
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt, QTimer, QThread, Signal

from core.manager_base import Environment, Package
from core.network_proxy import merge_env_for_command
from core.npm_spec import split_npm_spec
from core.runtime_update import (
    detect_nvm,
    download_runtime_installer,
    build_installer_run_command,
    get_node_installer_url,
)
from managers.base_worker import BaseCmdWorker
from managers.npm_manager import NpmManager, NpmBaseHelper, resolve_npm_registry_url
from ui.panels.base_panel import BasePanel
from core.trace_logger import trace_event, is_trace_enabled, get_trace_path


class NpmDistTagsWorker(QThread):
    tags_ready = Signal(str, object, str)

    def __init__(self, pkg_name: str, registry_url: str | None = None, proxy_settings=None, parent=None):
        super().__init__(parent)
        self.pkg_name = pkg_name
        self.registry_url = registry_url
        self.proxy_settings = proxy_settings or {}

    def run(self):
        npm_path = NpmBaseHelper.find_npm()
        if not npm_path:
            self.tags_ready.emit(self.pkg_name, {}, "npm not found")
            return

        try:
            cmd = [npm_path, "view", self.pkg_name, "dist-tags", "--json"]
            if self.registry_url:
                cmd.extend(["--registry", self.registry_url])
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                env=merge_env_for_command(cmd, proxy_settings=self.proxy_settings),
            )
            if res.returncode != 0 or not res.stdout.strip():
                error_text = (res.stderr or res.stdout or "").strip() or "npm view returned no data"
                self.tags_ready.emit(self.pkg_name, {}, error_text)
                return

            data = json.loads(res.stdout)
            if not isinstance(data, dict):
                self.tags_ready.emit(self.pkg_name, {}, "dist-tags response was not a JSON object")
                return
            self.tags_ready.emit(self.pkg_name, data, "")
        except Exception as exc:
            self.tags_ready.emit(self.pkg_name, {}, str(exc))


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


class NpmPanel(BasePanel):
    """Complete npm management panel with left (env list) + right (console) split."""

    def __init__(self, config_mgr, parent=None):
        super().__init__(config_mgr, parent)
        self.npm_mgr = NpmManager(config_mgr)
        self._env_cards = {}
        from core.utils import StreamingAnsiStripper
        self._ansi_stripper = StreamingAnsiStripper()
        self._interceptor_buffer = ""
        self._active_operations = []  # list of dicts: {"env_path": str, "type": str, "pkgs": list, "marker": str}
        
        from PySide6.QtCore import QTimer
        self._marker_timer = QTimer(self)
        self._marker_timer.timeout.connect(self._check_marker_files)
        self._marker_timer.start(1000)
        
        from PySide6.QtCore import QFileSystemWatcher
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_directory_changed)
        
        self._fs_debounce_timers = {}
        
        self._outdated_filter_enabled = False
        self._dist_tags_workers = []

        self._build_npm_ui()
        self._connect_signals()

    def _build_npm_ui(self):
        self._setup_common_toolbar(
            search_callback=self._on_search_text_changed,
            outdated_callback=self._toggle_outdated_only,
            refresh_callback=self.start_scan,
            batch_update_callback=self._batch_update,
            batch_remove_callback=self._batch_remove,
            manage_envs_callback=self._open_settings,
            add_env_callback=self._show_add_menu
        )

    def _show_add_menu(self):
        from PySide6.QtWidgets import QMenu, QFileDialog, QInputDialog, QMessageBox
        from core.env_detector import resolve_npm_env, describe_npm_env
        import os

        menu = QMenu(self)

        def process_path(path):
            res_val, res_type = resolve_npm_env(path)
            if not res_val:
                QMessageBox.warning(self, "Invalid Path", f"Could not detect valid NPM Project in:\n{path}")
                return
            res_val = os.path.normpath(res_val)
            existing_keys = {self._path_key(e.get("path", "")) for e in self.config_mgr.config.npm_environments}
            if self._path_key(res_val) in existing_keys:
                QMessageBox.information(self, "Info", "Already added.")
                return
            env_type, smart_name = describe_npm_env(res_val, res_type or "")
            text, ok = QInputDialog.getText(self, "Name", "Confirm name:", text=smart_name)
            if not ok or not text: return

            self.config_mgr.add_npm_env(path=res_val, name=text, env_type=env_type)
            self.start_scan()

        def add_dir():
            p = QFileDialog.getExistingDirectory(self, "Select NPM Root", "", QFileDialog.Option.ShowDirsOnly)
            if p: process_path(p)

        def add_file():
            p, _ = QFileDialog.getOpenFileName(self, "Select NPM Package Metadata", "", "NPM Entry (package.json);;All Files (*)")
            if p: process_path(p)

        def add_direct():
            text, ok = QInputDialog.getText(self, "Add NPM project by Path", "Enter full path:")
            if ok and text.strip():
                process_path(text.strip().strip('\"').strip('\''))

        def add_batch():
            text, ok = QInputDialog.getMultiLineText(self, "Batch Add", 
                "Paste multiple paths from Explorer/Everything:\nOne path per line.")
            if ok and text.strip():
                added_count = 0
                for line in text.strip().splitlines():
                    path_str = line.strip().strip('"').strip("'")
                    if path_str:
                        res_val, res_type = resolve_npm_env(path_str)
                        if res_val:
                            res_val = os.path.normpath(res_val)
                            existing_keys = {self._path_key(e.get("path", "")) for e in self.config_mgr.config.npm_environments}
                            if self._path_key(res_val) not in existing_keys:
                                env_type, smart_name = describe_npm_env(res_val, res_type or "")
                                self.config_mgr.add_npm_env(path=res_val, name=smart_name, env_type=env_type, save=False)
                                added_count += 1
                if added_count > 0:
                    self.config_mgr.save_config()
                    self.start_scan()
                    QMessageBox.information(self, "Success", f"Imported {added_count} new environments!")
                else:
                    QMessageBox.warning(self, "No Valid Paths", "Could not detect any new valid paths.")

        menu.addAction("📁 From Directory (Project root)...", add_dir)
        menu.addAction("📄 From File (package.json)...", add_file)
        menu.addAction("⌨️ Enter Path...", add_direct)
        menu.addAction("📋 Batch Paste...", add_batch)

        from PySide6.QtGui import QCursor
        menu.exec(QCursor.pos())

    def _connect_signals(self):
        self.npm_mgr.log_msg.connect(self._log)
        self.npm_mgr.log_batch.connect(self._log_batch)
        self.npm_mgr.env_scanned.connect(self._on_env_scanned)
        self.npm_mgr.updates_checked.connect(self._on_updates_checked)
        self.npm_mgr.specific_packages_scanned.connect(self._on_specific_packages_scanned)
        self.npm_mgr.runtime_update_done.connect(self._on_runtime_update_done)

    # ── Status bar helper ──

    def _log(self, msg: str, tag: str = "stdout"):
        self.console.log(msg, tag)

    def _log_batch(self, entries: list):
        self.console.log_batch(entries)

    # ── Scan ─────────────────────────────────────────────────────────────

    def start_scan(self):
        """Initial / Refresh all scan"""
        self.console.log_divider("REFRESH ALL")
        self._log("Starting NPM scan...", "system")
        self.refresh_btn.setEnabled(False)

        try:
            self._clear_env_card_widgets()
            
            # Clear existing file watchers
            if self._fs_watcher.directories():
                self._fs_watcher.removePaths(self._fs_watcher.directories())

            self.npm_mgr.reload_envs()
            envs = self.npm_mgr.list_environments()

            if not envs:
                self._log("No NPM environments found. Please add one.", "error")
                self.refresh_btn.setEnabled(True)
                return

            self._log(f"Loading {len(envs)} NPM environments...", "system")
            self._env_cards = {}

            for env in envs:
                from ui.widgets.npm_env_card import NpmEnvCard
                self._log(f"Initializing card for {env.name}...", "stdout")
                card = NpmEnvCard(env)
                self._apply_current_filters_to_card(card)
                self.scroll_layout.insertWidget(self.scroll_layout.count() - 2, card)

                norm_path = self._path_key(env.path)
                self._env_cards[norm_path] = card

                card.refresh_requested.connect(self._refresh_single_env)
                card.runtime_update_requested.connect(self._update_runtime_in_env)
                card.update_all_requested.connect(self._update_all_in_env)
                card.update_package_requested.connect(lambda p, c, e: self._start_pkg_update(p, c, e))
                card.remove_package_requested.connect(self._start_pkg_remove)
                card.add_package_requested.connect(self._start_pkg_install)
                card.config_package_requested.connect(self._config_package)
                card.selection_state_changed.connect(self._on_selection_state_changed)
                card.expand_toggled.connect(lambda *a: self._sync_expand_checkbox())
                card.activate_requested.connect(self._on_activate_requested)
                card.remove_env_requested.connect(self._on_remove_env_requested)
                card.rename_requested.connect(self._on_rename_env_requested)
                card.edit_requested.connect(self._on_edit_env_requested)
                card.reorder_requested.connect(self._on_reorder_requested)

                self.npm_mgr.scan_environment(env)
                
                # Watch node_modules for manual terminal command changes
                import os
                node_modules = os.path.join(env.path, "node_modules")
                if os.path.exists(node_modules):
                    self._fs_watcher.addPath(node_modules)
                elif os.path.exists(env.path):
                    self._fs_watcher.addPath(env.path)

            self._log("All npm environments queued for scan.", "system")
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
        QTimer.singleShot(200, self._check_all_tasks_done)

        # Trigger update check if it was a scan (not an update check itself)
        if getattr(env, "is_scanned", False):
             self.npm_mgr.check_updates(env)

    def _on_updates_checked(self, env: Environment):
        norm_key = self._path_key(env.path)
        if norm_key in self._env_cards:
            card = self._env_cards[norm_key]
            card.update_ui()
            self._apply_outdated_state_to_card(card)
        QTimer.singleShot(200, self._check_all_tasks_done)

    def _on_specific_packages_scanned(self, env_path: str, found_pkgs: list, requested_names: list):
        norm_key = self._path_key(env_path)
        manager_env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        if norm_key in self._env_cards and manager_env:
            card = self._env_cards[norm_key]
            env = manager_env
            card.env = env
            
            existing_pkg_map = {p.name: p for p in env.packages}
            found_names = set()
            
            for new_pkg in found_pkgs:
                found_names.add(new_pkg.name)
                if new_pkg.name in existing_pkg_map:
                    # Update existing
                    old_pkg = existing_pkg_map[new_pkg.name]
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
                if req_name not in found_names:
                    if req_name in existing_pkg_map:
                        env.packages.remove(existing_pkg_map[req_name])
                        card.remove_package_from_ui(req_name)

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
        
        QTimer.singleShot(200, self._check_all_tasks_done)

    def _check_all_tasks_done(self):
        if not self.npm_mgr._active_workers:
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
                        
                    env = self._find_env_by_path(self.npm_mgr.environments, op["env_path"])
                    if env:
                        if exit_code != 0:
                            self._log(f"Command failed with exit code {exit_code}. Doing full refresh instead of optimistic.", "error")
                            self._refresh_single_env(env.path)
                        else:
                            refresh_names = list(op.get("refresh_names") or [])
                            if op.get("force_full_refresh") or not refresh_names:
                                self._log("Fast refresh could not safely resolve npm package identities. Falling back to full refresh.", "system")
                                self._refresh_single_env(env.path)
                            else:
                                self.npm_mgr.scan_specific_packages(env, refresh_names)
                except Exception as e:
                    self._log(f"Error reading marker file: {e}", "error")
                    env = self._find_env_by_path(self.npm_mgr.environments, op["env_path"])
                    if env:
                        self._refresh_single_env(env.path)
            else:
                remaining_ops.append(op)
                
        self._active_operations = remaining_ops
        
    def _on_directory_changed(self, path: str):
        import os
        path = os.path.normpath(path)
        # Find which env this belongs to
        for env in self.npm_mgr.environments:
            node_modules = os.path.normpath(os.path.join(env.path, "node_modules"))
            norm_env_path = os.path.normpath(env.path)
            if path == node_modules or path == norm_env_path:
                norm_key = self._path_key(env.path)
                if norm_key not in self._fs_debounce_timers:
                    from PySide6.QtCore import QTimer
                    t = QTimer(self)
                    t.setSingleShot(True)
                    t.setInterval(2000) # 2 seconds debounce
                    t.timeout.connect(lambda e=env: self._on_fs_debounce_timeout(e))
                    self._fs_debounce_timers[norm_key] = t
                self._fs_debounce_timers[norm_key].start()

    def _on_fs_debounce_timeout(self, env):
        self._log(f"Detected file system changes in environment {env.name}. Auto-refreshing...", "system")
        self._refresh_single_env(env.path)

    def _update_status_counts(self):
        self._emit_status_counts(self.npm_mgr.environments)

    def _get_env(self, env_path: str):
        return self._find_env_by_path(self.npm_mgr.environments, env_path)

    def _on_remove_env_requested(self, env_path: str):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to remove the environment?\n\n{env_path}", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.config_mgr.remove_npm_env(env_path)
            self.start_scan()

    def _on_rename_env_requested(self, env_path: str):
        from PySide6.QtWidgets import QInputDialog
        envs = self.config_mgr.config.npm_environments
        for env in envs:
            if self._path_key(env.get("path", "")) == self._path_key(env_path):
                new_name, ok = QInputDialog.getText(self, "Rename", "New Name:", text=env.get("name", ""))
                if ok and new_name:
                    env["name"] = new_name
                    self.config_mgr.save_config()
                    self.start_scan()
                break

    def _on_edit_env_requested(self, env_path: str):
        self._open_settings(edit_env_path=env_path)

    def _on_reorder_requested(self, source_path: str, target_path: str, position: str):
        envs = self.config_mgr.config.npm_environments
        source_idx = next((i for i, e in enumerate(envs) if self._path_key(e.get("path", "")) == self._path_key(source_path)), -1)
        target_idx = next((i for i, e in enumerate(envs) if self._path_key(e.get("path", "")) == self._path_key(target_path)), -1)
        
        if source_idx >= 0 and target_idx >= 0 and source_idx != target_idx:
            env = envs.pop(source_idx)
            target_idx = next((i for i, e in enumerate(envs) if self._path_key(e.get("path", "")) == self._path_key(target_path)), -1)
            if position == "after":
                target_idx += 1
            envs.insert(target_idx, env)
            self.config_mgr.save_config()
            
            mgr_source_idx = next((i for i, e in enumerate(self.npm_mgr.environments) if self._path_key(e.path) == self._path_key(source_path)), -1)
            mgr_target_idx = next((i for i, e in enumerate(self.npm_mgr.environments) if self._path_key(e.path) == self._path_key(target_path)), -1)
            if mgr_source_idx >= 0 and mgr_target_idx >= 0:
                mgr_env = self.npm_mgr.environments.pop(mgr_source_idx)
                mgr_target_idx = next((i for i, e in enumerate(self.npm_mgr.environments) if self._path_key(e.path) == self._path_key(target_path)), -1)
                if position == "after":
                    mgr_target_idx += 1
                self.npm_mgr.environments.insert(mgr_target_idx, mgr_env)
            
            self._reorder_env_cards(self.npm_mgr.environments, self._env_cards)

    # ── Single Env ───────────────────────────────────────────────────────

    def _refresh_single_env(self, env_path: str):
        target_key = self._path_key(env_path)
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        if env:
            self._log(f"Refreshing {env.name}...", "system")
            env.is_scanned = False
            if target_key in self._env_cards:
                self._env_cards[target_key]._pkgs_loaded = False
            self.npm_mgr.scan_environment(env)

    def _update_runtime_in_env(self, env_path: str):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        if not env:
            return

        current_ver = getattr(env, "runtime_version", "") or "Unknown"
        is_major = bool(getattr(env, "runtime_has_major_update", False))
        is_patch = bool(getattr(env, "runtime_has_update", False))
        latest_ver = (
            getattr(env, "runtime_major_latest_version", "")
            or getattr(env, "runtime_latest_version", "")
            or "latest"
        )

        if not is_major and not is_patch:
            self._log(f"No Node.js runtime update available (triggered by {env.name}).", "system")
            return

        nvm_ok, _ = detect_nvm()

        if is_major:
            title = "Confirm Major Version Upgrade"
            base_msg = (
                f"Upgrade Node.js major version?\n\n"
                f"{current_ver} → {latest_ver}\n\n"
                f"⚠ This is a major version upgrade. While Node.js generally maintains\n"
                f"backward compatibility, some packages may be affected.\n\n"
                f"Triggered by environment: {env.name}"
            )
        else:
            title = "Confirm Runtime Update"
            base_msg = (
                f"Update Node.js runtime?\n\n"
                f"{current_ver} -> {latest_ver}\n\n"
                f"Triggered by environment: {env.name}\n"
                f"This does not update npm packages."
            )

        use_nvm = False
        if nvm_ok:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(title)
            msg_box.setText(
                base_msg + "\n\nnvm-windows is detected. How would you like to update?\n\n"
                "• nvm — use nvm to install the new version (keeps nvm management)\n"
                "• winget — use winget to install directly (may bypass nvm)"
            )
            nvm_btn = msg_box.addButton("nvm", QMessageBox.AcceptRole)
            winget_btn = msg_box.addButton("winget", QMessageBox.ActionRole)
            cancel_btn = msg_box.addButton("Cancel", QMessageBox.RejectRole)
            msg_box.exec()
            clicked = msg_box.clickedButton()
            if clicked == cancel_btn:
                return
            use_nvm = (clicked == nvm_btn)
        else:
            reply = QMessageBox.question(
                self,
                title,
                base_msg,
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        method = "nvm" if use_nvm else "winget"
        self.console.log_divider(f"RUNTIME UPDATE (Node.js) via {env.name} [{method}]")
        self.npm_mgr.update_runtime(env, use_nvm=use_nvm)

    def _on_runtime_update_done(self, env_path: str, success: bool, message: str,
                                 winget_failed: bool = False, target_version: str = ""):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        env_name = env.name if env else env_path
        if success:
            self._log(f"Node.js runtime update finished (triggered by {env_name}).", "success")
        elif winget_failed and target_version:
            self._log(
                f"Node.js runtime update failed (triggered by {env_name}): {message}",
                "error",
            )
            self._offer_installer_fallback("node", target_version, env_path)
        else:
            self._log(f"Node.js runtime update failed (triggered by {env_name}): {message}", "error")
            QMessageBox.warning(self, "Runtime Update Failed", message or "Runtime update command failed.")

        # Node runtime is global in practice; refresh all env cards.
        if not winget_failed:
            for item in self.npm_mgr.environments:
                self._refresh_single_env(item.path)

    def _offer_installer_fallback(self, runtime_kind: str, version: str, env_path: str):
        """Show a dialog offering to download and run the official installer."""
        label = "Node.js" if runtime_kind == "node" else "Python"
        url = get_node_installer_url(version) if runtime_kind == "node" else ""
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
            lambda success, msg: self._on_installer_done(success, msg)
        )
        self._installer_worker.start()

    def _on_installer_done(self, success: bool, message: str):
        if success:
            self._log("Runtime installer completed. Refreshing environments...", "system")
        elif message:
            QMessageBox.warning(self, "Installer Failed", message)
        # Refresh all env cards to pick up new runtime version
        for item in self.npm_mgr.environments:
            self._refresh_single_env(item.path)

    def _update_all_in_env(self, env_path: str):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        if env and getattr(env, "is_scanned", False):
            outdated = [p for p in env.packages if getattr(p, "has_update", False)]
            if not outdated:
                self._log(f"No updatable packages in {env.name}.", "system")
                return
            self.console.log_divider(f"UPDATE ALL in {env.name}")
            import uuid
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "type": "update", "pkgs": outdated, "marker": marker})
            specs = [f"{p.name}@{p.metadata.get('channel', 'latest')}" if getattr(p, "metadata", None) else p.name for p in outdated]
            cmd_list = self.npm_mgr.build_update_command(env, specs)
            from core.terminal.command_renderer import ShellCommandRenderer
            shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
            cmd_str = ShellCommandRenderer.render(cmd_list, shell_name)
            cmd_str = ShellCommandRenderer.append_marker(cmd_str, marker, shell_name, include_exit_code=True)
            ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _start_pkg_update(self, pkg_name: str, channel: str, env_path: str):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        if env:
            self.console.log_divider(f"UPDATE {pkg_name}@{channel}")
            import uuid
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "type": "update", "pkgs": [pkg_name], "marker": marker})
            spec = f"{pkg_name}@{channel}"
            cmd_list = self.npm_mgr.build_update_command(env, [spec])
            from core.terminal.command_renderer import ShellCommandRenderer
            shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
            cmd_str = ShellCommandRenderer.render(cmd_list, shell_name)
            cmd_str = ShellCommandRenderer.append_marker(cmd_str, marker, shell_name, include_exit_code=True)
            ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _start_pkg_remove(self, pkg_name: str, env_path: str):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
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
                cmd_list = self.npm_mgr.build_remove_command(env, [pkg_name])
                from core.terminal.command_renderer import ShellCommandRenderer
                shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
                cmd_str = ShellCommandRenderer.render(cmd_list, shell_name)
                cmd_str = ShellCommandRenderer.append_marker(cmd_str, marker, shell_name, include_exit_code=True)
                ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _start_pkg_install(self, env_path: str, pkg_names: str, force_reinstall: bool = False):
        env = self._get_env(env_path)
        if not env:
            return
        
        self.console.log_divider(f"INSTALL {pkg_names}")
        import uuid
        marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
        self._active_operations.append({"env_path": env.path, "type": "install", "pkgs": pkg_names.split(), "marker": marker})
        cmd_list = self.npm_mgr.build_install_command(env, pkg_names, channel="latest")
        from core.terminal.command_renderer import ShellCommandRenderer
        shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
        cmd_str = ShellCommandRenderer.render(cmd_list, shell_name)
        cmd_str = ShellCommandRenderer.append_marker(cmd_str, marker, shell_name, include_exit_code=True)
        ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    def _on_activate_requested(self, env_path: str):
        env = self._get_env(env_path)
        if not env:
            self._log("Failed to activate: environment not found.", "error")
            return
        
        self._log(f"Opening {env.name} in terminal...", "cmd")

        # Simulated mode: open external terminal since ConsolePanel can't execute commands
        if self.terminal is self.console:
            if getattr(env, "type", "") == "global" or env_path == "global":
                target_path = os.path.expanduser("~")
            else:
                target_path = env.path
            try:
                subprocess.Popen(f'start cmd /k "cd /d {target_path}"', shell=True, cwd=target_path)
            except Exception as e:
                self._log(f"Failed to open terminal: {e}", "error")
            return

        shell_name = "cmd.exe"
        if hasattr(self.terminal, "_resolve_shell"):
            shell_name = os.path.basename(self.terminal._resolve_shell()).lower()
            
        is_powershell = "powershell" in shell_name or "pwsh" in shell_name
        
        # For Global Packages, the path is "global" which is not a physical path
        if getattr(env, "type", "") == "global" or env_path == "global":
            target_path = os.path.expanduser("~")
        else:
            target_path = env.path
            
        if is_powershell:
            cmd = f'Set-Location -LiteralPath "{target_path}"'
        else:
            cmd = f'pushd "{target_path}"'
            
        self.terminal.write(cmd + "\r")


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
                "npm_panel",
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
                specs = []
                for pkg in env.packages:
                    if getattr(pkg, "is_selected", False) and getattr(pkg, "has_update", False):
                        channel = pkg.metadata.get("channel", "latest") if getattr(pkg, "metadata", None) else "latest"
                        specs.append(f"{pkg.name}@{channel}")
                if specs:
                    key = self._path_key(env.path)
                    env_packages[key] = specs
                    env_objects[key] = env

        if not env_packages:
            self._log("No updatable packages selected.", "system")
            return

        total = sum(len(v) for v in env_packages.values())
        self.console.log_divider(f"BATCH UPDATE ({total} packages across {len(env_packages)} environments)")
        for key, specs in env_packages.items():
            env = env_objects[key]
            self.console.log_divider(f"UPDATE ALL in {env.name}")
            import uuid
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            pkg_names = [split_npm_spec(s)[0] for s in specs]
            self._active_operations.append({"env_path": env.path, "type": "update", "pkgs": pkg_names, "marker": marker})
            cmd_list = self.npm_mgr.build_update_command(env, specs)
            from core.terminal.command_renderer import ShellCommandRenderer
            shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
            cmd_str = ShellCommandRenderer.render(cmd_list, shell_name)
            cmd_str = ShellCommandRenderer.append_marker(cmd_str, marker, shell_name, include_exit_code=True)
            ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

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
        if reply != QMessageBox.Yes:
            return

        self.console.log_divider(f"BATCH UNINSTALL ({total} packages across {len(env_packages)} environments)")
        for key, pkg_names in env_packages.items():
            env = env_objects[key]
            import uuid
            marker = f"__OMNIPACK_OP_DONE_{uuid.uuid4().hex}__"
            self._active_operations.append({"env_path": env.path, "type": "remove", "pkgs": pkg_names, "marker": marker})
            cmd_list = self.npm_mgr.build_remove_command(env, pkg_names)
            from core.terminal.command_renderer import ShellCommandRenderer
            shell_name = os.path.basename(self.terminal._resolve_shell()).lower() if hasattr(self.terminal, "_resolve_shell") else "cmd.exe"
            cmd_str = ShellCommandRenderer.render(cmd_list, shell_name)
            cmd_str = ShellCommandRenderer.append_marker(cmd_str, marker, shell_name, include_exit_code=True)
            ShellCommandRenderer.write_rendered_command(self.terminal, cmd_str)

    # ── Settings ─────────────────────────────────────────────────────────

    def _open_settings(self, edit_env_path=None):
        from ui.panels.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.config_mgr, initial_tab="npm", parent=self)

        if isinstance(edit_env_path, str) and edit_env_path:
            for i in range(dialog.npm_list.count()):
                if dialog.npm_list.item(i).data(Qt.UserRole) == edit_env_path:
                    dialog.npm_list.setCurrentRow(i)
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(10, lambda: dialog._edit_env("npm"))
                    break

        def on_envs_changed():
            self._log("NPM Environments changed. Syncing UI...", "system")
            old_keys = set(self._env_cards.keys())

            self.npm_mgr.reload_envs()
            new_envs = self.npm_mgr.list_environments()
            new_keys = {self._path_key(e.path) for e in new_envs}

            # Removals
            for key in (old_keys - new_keys):
                card = self._env_cards.pop(key)
                card.deleteLater()

            # Additions
            for key in (new_keys - old_keys):
                env = next(e for e in new_envs if self._path_key(e.path) == key)
                from ui.widgets.npm_env_card import NpmEnvCard
                card = NpmEnvCard(env)
                self._apply_current_filters_to_card(card)
                self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)
                self._env_cards[key] = card

                card.refresh_requested.connect(self._refresh_single_env)
                card.runtime_update_requested.connect(self._update_runtime_in_env)
                card.update_all_requested.connect(self._update_all_in_env)
                card.update_package_requested.connect(lambda p, c, e: self._start_pkg_update(p, c, e))
                card.remove_package_requested.connect(self._start_pkg_remove)
                card.add_package_requested.connect(self._start_pkg_install)
                card.config_package_requested.connect(self._config_package)
                card.selection_state_changed.connect(self._on_selection_state_changed)
                card.expand_toggled.connect(lambda *a: self._sync_expand_checkbox())
                card.activate_requested.connect(self._on_activate_requested)
                card.remove_env_requested.connect(self._on_remove_env_requested)
                card.rename_requested.connect(self._on_rename_env_requested)
                card.edit_requested.connect(self._on_edit_env_requested)
                card.reorder_requested.connect(self._on_reorder_requested)
                self.npm_mgr.scan_environment(env)

            # Existing: force UI refresh
            for key in (old_keys & new_keys):
                self._env_cards[key].update_ui()

            # Reorder cards to match new env order (no scanning)
            self._reorder_env_cards(new_envs, self._env_cards)
            self._sync_expand_checkbox()

        dialog.settings_changed.connect(on_envs_changed)
        dialog.exec()

    def _config_package(self, pkg_name: str, env_path: str):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        if not env:
            return
        pkg = next((p for p in env.packages if p.name == pkg_name), None)
        if not pkg:
            return

        if not getattr(pkg, "metadata", None):
            pkg.metadata = {}

        channel_versions = pkg.metadata.get("channel_versions") if getattr(pkg, "metadata", None) else None
        if not isinstance(channel_versions, dict) or not channel_versions:
            self._log(f"Loading dist-tags for {pkg.name}...", "system")
            self._fetch_pkg_channel_versions_async(pkg.name, env_path)
            return

        self._open_config_package_dialog(env, pkg, channel_versions)

    def _open_config_package_dialog(self, env: Environment, pkg: Package, channel_versions: dict | None = None):
        channel_versions = channel_versions or {}
        pkg_name = pkg.name

        channels = pkg.metadata.get("channels_available", ["latest"]) if getattr(pkg, "metadata", None) else ["latest"]
        if channel_versions:
            discovered = list(channel_versions.keys())
            others = [c for c in discovered if c != "latest"]
            others.sort()
            channels = (["latest"] if "latest" in discovered else []) + others
            pkg.metadata["channels_available"] = channels
        if not channels:
            channels = ["latest"]

        current_ch = pkg.metadata.get("channel", "latest") if getattr(pkg, "metadata", None) else "latest"
        if current_ch not in channels:
            channels = [current_ch] + [c for c in channels if c != current_ch]

        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDialogButtonBox,
            QLabel, QGridLayout, QWidget, QPushButton
        )
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Configure {pkg_name}")
        dialog.setMinimumWidth(540)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        
        disp_name_edit = QLineEdit(pkg.metadata.get("display_name", pkg.name) if getattr(pkg, "metadata", None) else pkg.name)
        desc_edit = QLineEdit(pkg.metadata.get("description", "") if getattr(pkg, "metadata", None) else "")
            
        form.addRow("Display Name:", disp_name_edit)
        form.addRow("Description:", desc_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("Target Tag (one-click):"))

        tag_cards = QWidget()
        tag_grid = QGridLayout(tag_cards)
        tag_grid.setContentsMargins(0, 0, 0, 0)
        tag_grid.setHorizontalSpacing(8)
        tag_grid.setVerticalSpacing(8)
        layout.addWidget(tag_cards)

        target_ch = {"value": current_ch}
        card_buttons = {}
        columns = 3

        def _set_card_state(btn: QPushButton, state: str):
            from ui.utils import update_widget_style_property
            update_widget_style_property(btn, "state", state)

        def _format_version(ch: str) -> str:
            if isinstance(channel_versions, dict):
                v = str(channel_versions.get(ch, "")).strip()
                if v:
                    return v
            if ch == current_ch and pkg.version:
                return str(pkg.version)
            return "-"

        for idx, ch in enumerate(channels):
            ver = _format_version(ch)
            card = QPushButton(f"{ch}\n{ver}")
            card.setObjectName("NpmTagCard")
            card.setCheckable(True)
            card.setMinimumHeight(56)
            card.clicked.connect(lambda _checked=False, c=ch: _select_target(c))
            card_buttons[ch] = card
            row = idx // columns
            col = idx % columns
            tag_grid.addWidget(card, row, col)

        is_global = env.type == "global"
        state_lbl = QLabel("")
        layout.addWidget(state_lbl)

        cmd_lbl = QLabel("")
        layout.addWidget(cmd_lbl)

        def _refresh_target_ui():
            selected = target_ch["value"]
            state_lbl.setText(f"Current: {current_ch}    Target: {selected}")
            cmd_lbl.setText(f"<b>Install Command:</b><br/>npm install {'-g ' if is_global else ''}{pkg_name}@{selected}")
            for ch, btn in card_buttons.items():
                btn.blockSignals(True)
                btn.setChecked(ch == selected)
                btn.blockSignals(False)
                if ch == current_ch and ch == selected:
                    _set_card_state(btn, "both")
                elif ch == current_ch:
                    _set_card_state(btn, "current")
                elif ch == selected:
                    _set_card_state(btn, "target")
                else:
                    _set_card_state(btn, "normal")

        def _select_target(ch):
            target_ch["value"] = ch
            _refresh_target_ui()

        _refresh_target_ui()
        
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dialog.accept)
        btns.rejected.connect(dialog.reject)
        layout.addWidget(btns)
        
        if dialog.exec() == QDialog.Accepted:
            new_disp = disp_name_edit.text()
            new_desc = desc_edit.text()
            new_ch = target_ch["value"]
            
            # Save to config if global app
            if is_global and hasattr(self.config_mgr.config, "npm_apps"):
                apps_dict = getattr(self.config_mgr.config, "npm_apps", None)
                if apps_dict is not None:
                    if pkg_name not in apps_dict:
                        apps_dict[pkg_name] = {}
                    apps_dict[pkg_name]["display_name"] = new_disp
                    apps_dict[pkg_name]["description"] = new_desc
                    apps_dict[pkg_name]["channel"] = new_ch
                    apps_dict[pkg_name]["channels_available"] = channels
                    if isinstance(channel_versions, dict):
                        apps_dict[pkg_name]["channel_versions"] = channel_versions
                    self.config_mgr.save_config()
            
            if not hasattr(pkg, "metadata") or pkg.metadata is None:
                pkg.metadata = {}
            pkg.metadata["display_name"] = new_disp
            pkg.metadata["description"] = new_desc
            pkg.metadata["channel"] = new_ch
            pkg.metadata["channels_available"] = channels
            if isinstance(channel_versions, dict):
                pkg.metadata["channel_versions"] = channel_versions
            
            if new_ch != current_ch:
                # Need to update because channel changed
                self._start_pkg_update(pkg_name, new_ch, env.path)
            else:
                self._refresh_single_env(env.path)

    def _fetch_pkg_channel_versions_async(self, pkg_name: str, env_path: str):
        for worker in self._dist_tags_workers:
            if getattr(worker, "_pkg_name", None) == pkg_name and getattr(worker, "_env_path", None) == env_path:
                return

        worker = NpmDistTagsWorker(
            pkg_name,
            registry_url=resolve_npm_registry_url(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
            parent=self,
        )
        worker._pkg_name = pkg_name
        worker._env_path = env_path
        worker.tags_ready.connect(lambda name, data, error, path=env_path: self._on_pkg_channel_versions_ready(path, name, data, error))
        worker.finished.connect(lambda w=worker: self._dist_tags_workers.remove(w) if w in self._dist_tags_workers else None)
        worker.finished.connect(worker.deleteLater)
        self._dist_tags_workers.append(worker)
        worker.start()

    def _on_pkg_channel_versions_ready(self, env_path: str, pkg_name: str, channel_versions, error: str):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        if not env:
            return
        pkg = next((p for p in env.packages if p.name == pkg_name), None)
        if not pkg:
            return
        if not getattr(pkg, "metadata", None):
            pkg.metadata = {}

        if isinstance(channel_versions, dict) and channel_versions:
            pkg.metadata["channel_versions"] = channel_versions
            discovered = list(channel_versions.keys())
            others = sorted(c for c in discovered if c != "latest")
            pkg.metadata["channels_available"] = (["latest"] if "latest" in discovered else []) + others
        else:
            self._log(f"Could not load dist-tags for {pkg_name}: {error or 'unknown error'}", "stderr")

        self._open_config_package_dialog(
            env,
            pkg,
            channel_versions if isinstance(channel_versions, dict) else {},
        )

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
        for env in self.npm_mgr.environments:
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
                "npm_panel",
                "toolbar_outdated_sync",
                total_outdated=total,
                selected_outdated=selected,
                state=int(target.value if hasattr(target, "value") else int(target)),
            )

    def _sync_selection_checkbox_state(self):
        total = 0
        selected = 0
        for env in self.npm_mgr.environments:
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
