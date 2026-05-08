import os
import json
import subprocess
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt, QTimer, QThread, Signal

from core.manager_base import Environment, Package
from core.network_proxy import merge_env_for_command
from core.npm_spec import split_npm_spec
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


class NpmPanel(BasePanel):
    """Complete npm management panel with left (env list) + right (console) split."""

    def __init__(self, config_mgr, parent=None):
        super().__init__(config_mgr, parent)
        self.npm_mgr = NpmManager(config_mgr)
        self._env_cards = {}
        self._update_queue = []
        self._update_running = False
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
            manage_envs_callback=self._open_settings
        )

    def _connect_signals(self):
        self.npm_mgr.log_msg.connect(self._log)
        self.npm_mgr.log_batch.connect(self._log_batch)
        self.npm_mgr.env_scanned.connect(self._on_env_scanned)
        self.npm_mgr.updates_checked.connect(self._on_updates_checked)
        self.npm_mgr.update_done.connect(self._on_update_done)
        self.npm_mgr.remove_done.connect(self._on_remove_done)
        self.npm_mgr.install_done.connect(self._on_install_done)
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

        self._clear_env_card_widgets()

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
            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)

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

            self.npm_mgr.scan_environment(env)

        self._log("All environments queued for scan.", "system")

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

    def _check_all_tasks_done(self):
        if not self.npm_mgr._active_workers:
            self.refresh_btn.setEnabled(True)
            self._log("All tasks completed.", "system")
            self._update_status_counts()

    def _update_status_counts(self):
        self._emit_status_counts(self.npm_mgr.environments)

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
        latest_ver = getattr(env, "runtime_latest_version", "") or "latest patch"
        if not getattr(env, "runtime_has_update", False):
            self._log(f"No Node.js runtime update available (triggered by {env.name}).", "system")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Runtime Update",
            f"Update Node.js runtime?\n\n{current_ver} -> {latest_ver}\n\nTriggered by environment: {env.name}\nThis does not update npm packages.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.console.log_divider(f"RUNTIME UPDATE (Node.js) via {env.name}")
        self.npm_mgr.update_runtime(env)

    def _on_runtime_update_done(self, env_path: str, success: bool, message: str):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        env_name = env.name if env else env_path
        if success:
            self._log(f"Node.js runtime update finished (triggered by {env_name}).", "success")
        else:
            self._log(f"Node.js runtime update failed (triggered by {env_name}): {message}", "error")
            QMessageBox.warning(self, "Runtime Update Failed", message or "Runtime update command failed.")

        # Node runtime is global in practice; refresh all env cards.
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
            names = [p.name for p in outdated]
            self._log(f"Updating: {', '.join(names)}", "system")
            # For NPM, channel is determined by metadata or defaults to "latest"
            for pkg in outdated:
                channel = pkg.metadata.get("channel", "latest") if getattr(pkg, "metadata", None) else "latest"
                self._update_queue.append((pkg.name, channel, env))
            
            if not self._update_running:
                self._process_update_queue()

    def _start_pkg_update(self, pkg_name: str, channel: str, env_path: str):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        if env:
            self.console.log_divider(f"UPDATE {pkg_name}@{channel}")
            self._update_queue.append((pkg_name, channel, env))
            if not self._update_running:
                self._process_update_queue()

    def _process_update_queue(self):
        if not self._update_queue:
            self._update_running = False
            return
        self._update_running = True
        pkg_name, channel, env = self._update_queue.pop(0)
        
        # Package to pass to NpmManager (it needs Package object)
        pkg = next((p for p in env.packages if p.name == pkg_name), None)
        if not pkg:
             # create a dummy
             pkg = Package(name=pkg_name, version="")

        self.npm_mgr.update_package(pkg, env, channel=channel)

    def _on_update_done(self, env_path: str, pkg_name: str, success: bool):
        if not hasattr(self, '_affected_envs_update'):
            self._affected_envs_update = set()
        self._affected_envs_update.add(env_path)

        if self._update_queue:
            self._process_update_queue()
        else:
            self._update_running = False
            for p in self._affected_envs_update:
                self._refresh_single_env(p)
            self._affected_envs_update.clear()

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
                self.npm_mgr.remove_package(env, pkg_name)

    def _on_remove_done(self, env_path: str, pkg_name: str, success: bool):
        if not hasattr(self, '_affected_envs_remove'):
            self._affected_envs_remove = set()
        self._affected_envs_remove.add(env_path)

        if hasattr(self, '_remove_queue') and self._remove_queue:
            self._process_remove_queue()
        else:
            self._remove_running = False
            for p in self._affected_envs_remove:
                self._refresh_single_env(p)
            self._affected_envs_remove.clear()

    def _start_pkg_install(self, env_path: str, pkg_names: str, _force_reinstall: bool = False):
        env = self._find_env_by_path(self.npm_mgr.environments, env_path)
        if env:
            self.console.log_divider(f"INSTALL {pkg_names}")
            
            if not hasattr(self, '_install_queue'):
                self._install_queue = []
                self._install_running = False

            name, channel = split_npm_spec(pkg_names)
            if not name:
                self._log("Invalid npm package spec.", "error")
                return

            self._install_queue.append((name, channel or "latest", env))
            if not self._install_running:
                self._process_install_queue()

    def _process_install_queue(self):
        if not hasattr(self, '_install_queue') or not self._install_queue:
            self._install_running = False
            return
        self._install_running = True
        pkg_names, channel, env = self._install_queue.pop(0)
        self.npm_mgr.install_package(env, pkg_names, channel=channel)

    def _on_install_done(self, env_path: str, pkg_names: str, success: bool):
        if not hasattr(self, '_affected_envs_install'):
            self._affected_envs_install = set()
        self._affected_envs_install.add(env_path)

        if success:
            self._log(f"Successfully installed '{pkg_names}' in {env_path}", "success")
        else:
            self._log(f"Failed to install '{pkg_names}' in {env_path}", "error")
            QMessageBox.warning(self, "Installation Failure", f"Failed to install {pkg_names}.\nCheck the console for details.")

        if hasattr(self, '_install_queue') and self._install_queue:
            self._process_install_queue()
        else:
            self._install_running = False
            for p in self._affected_envs_install:
                self._refresh_single_env(p)
            self._affected_envs_install.clear()
            if success:
                QMessageBox.information(self, "Success", f"Installation of '{pkg_names}' completed.")

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

        checked_val = Qt.Checked.value if hasattr(Qt.Checked, "value") else 2
        partial_val = Qt.PartiallyChecked.value if hasattr(Qt.PartiallyChecked, "value") else 1
        unchecked_val = Qt.Unchecked.value if hasattr(Qt.Unchecked, "value") else 0
        raw_state = state.value if hasattr(state, "value") else int(state)

        if raw_state == unchecked_val:
            self._outdated_filter_enabled = False
            is_checked = False
            selection_mode = "clear_all"
        elif raw_state == checked_val:
            self._outdated_filter_enabled = True
            is_checked = True
            selection_mode = "select_all"
        elif raw_state == partial_val:
            # Treat user-entered partial clicks as "checked"; partial is for display feedback only.
            self._outdated_filter_enabled = True
            is_checked = True
            selection_mode = "select_all"
        else:
            self._outdated_filter_enabled = bool(raw_state)
            is_checked = self._outdated_filter_enabled
            selection_mode = "keep"

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
        update_list = []
        for env_path, card in self._env_cards.items():
            env = card.env
            if getattr(env, "is_scanned", False):
                for pkg in env.packages:
                    if getattr(pkg, "is_selected", False) and getattr(pkg, "has_update", False):
                        channel = pkg.metadata.get("channel", "latest") if getattr(pkg, "metadata", None) else "latest"
                        update_list.append((pkg.name, channel, env))

        if not update_list:
            self._log("No updatable packages selected.", "system")
            return

        self.console.log_divider(f"BATCH UPDATE ({len(update_list)} packages)")
        self._log(f"Batch updating: {', '.join(n for n, _, _ in update_list)}", "system")

        self._update_queue.extend(update_list)
        if not self._update_running:
            self._process_update_queue()

    # ── Batch Remove ─────────────────────────────────────────────────────

    def _batch_remove(self):
        remove_list = []
        for env_path, card in self._env_cards.items():
            env = card.env
            if getattr(env, "is_scanned", False):
                for pkg in env.packages:
                    if getattr(pkg, "is_selected", False):
                        remove_list.append((pkg.name, env))

        if not remove_list:
            self._log("No packages selected for batch remove.", "system")
            return

        reply = QMessageBox.question(
            self, "Confirm Batch Uninstall",
            f"Are you sure you want to uninstall {len(remove_list)} packages?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.console.log_divider(f"BATCH UNINSTALL ({len(remove_list)} packages)")
        self._log(f"Batch uninstalling: {', '.join(n for n, _ in remove_list)}", "system")

        if not hasattr(self, '_remove_queue'):
            self._remove_queue = []
            self._remove_running = False

        self._remove_queue.extend(remove_list)
        if not self._remove_running:
            self._process_remove_queue()

    def _process_remove_queue(self):
        if not hasattr(self, '_remove_queue') or not self._remove_queue:
            self._remove_running = False
            return
        self._remove_running = True
        pkg_name, env = self._remove_queue.pop(0)
        self.npm_mgr.remove_package(env, pkg_name)

    # ── Settings ─────────────────────────────────────────────────────────

    def _open_settings(self):
        from ui.panels.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.config_mgr, initial_tab="npm", parent=self)

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
                self.npm_mgr.scan_environment(env)

            # Existing: force UI refresh
            for key in (old_keys & new_keys):
                self._env_cards[key].update_ui()

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
            btn.setProperty("state", state)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

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
                if not any(q[0] == pkg_name for q in self._update_queue):
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
