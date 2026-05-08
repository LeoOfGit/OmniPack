"""
PipPanel — Self-contained QWidget for managing Python (pip/uv) environments.
Extracted from OmniPack.pyw to keep the main window thin.
"""
import os
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt, QTimer

from core.manager_base import Environment
from managers.pip_manager import PipManager
from ui.panels.base_panel import BasePanel
from core.trace_logger import trace_event, is_trace_enabled, get_trace_path

class PipPanel(BasePanel):
    """Complete pip management panel with left (env list) + right (console) split."""

    def __init__(self, config_mgr, parent=None):
        super().__init__(config_mgr, parent)
        self.pip_mgr = PipManager(config_mgr)
        self._env_cards = {}
        self._update_queue = []
        self._update_running = False
        self._outdated_filter_enabled = False

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
        self.pip_mgr.update_done.connect(self._on_update_done)
        self.pip_mgr.remove_done.connect(self._on_remove_done)
        self.pip_mgr.install_done.connect(self._on_install_done)
        self.pip_mgr.runtime_update_done.connect(self._on_runtime_update_done)

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

            self.pip_mgr.scan_environment(env)

        self._log("All environments queued for scan.", "system")

    def _on_env_scanned(self, env: Environment):
        norm_key = self._path_key(env.path)
        if norm_key in self._env_cards:
            card = self._env_cards[norm_key]
            card.update_ui()
            self._apply_outdated_state_to_card(card)
        QTimer.singleShot(200, self._check_all_tasks_done)

    def _check_all_tasks_done(self):
        if not self.pip_mgr._active_workers:
            self.refresh_btn.setEnabled(True)
            self._log("All tasks completed.", "system")
            self._update_status_counts()

    def _update_status_counts(self):
        self._emit_status_counts(self.pip_mgr.environments)

    # ── Single Env ───────────────────────────────────────────────────────

    def _refresh_single_env(self, env_path: str):
        target_key = self._path_key(env_path)
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env:
            self._log(f"Refreshing {env.name}...", "system")
            env.is_scanned = False
            if target_key in self._env_cards:
                self._env_cards[target_key]._pkgs_loaded = False
            self.pip_mgr.scan_environment(env)

    def _update_runtime_in_env(self, env_path: str):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if not env:
            return

        current_ver = getattr(env, "runtime_version", "") or getattr(env, "python_version", "") or "Unknown"
        latest_ver = getattr(env, "runtime_latest_version", "") or "latest patch"
        if not getattr(env, "runtime_has_update", False):
            self._log(f"No Python runtime update available in {env.name}.", "system")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Runtime Update",
            f"Update Python runtime in {env.name}?\n\n{current_ver} -> {latest_ver}\n\nThis does not update packages.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.console.log_divider(f"RUNTIME UPDATE in {env.name}")
        self.pip_mgr.update_runtime(env)

    def _on_runtime_update_done(self, env_path: str, success: bool, message: str):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        env_name = env.name if env else env_path
        if success:
            self._log(f"Python runtime update finished for {env_name}.", "success")
        else:
            self._log(f"Python runtime update failed for {env_name}: {message}", "error")
            QMessageBox.warning(self, "Runtime Update Failed", message or "Runtime update command failed.")
        self._refresh_single_env(env_path)

    def _update_all_in_env(self, env_path: str):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env and env.is_scanned:
            outdated = [p.name for p in env.packages if p.has_update]
            if not outdated:
                self._log(f"No updatable packages in {env.name}.", "system")
                return
            self.console.log_divider(f"UPDATE ALL in {env.name}")
            self._log(f"Updating: {', '.join(outdated)}", "system")
            self._update_queue.extend([(pkg_name, env) for pkg_name in outdated])
            if not self._update_running:
                self._process_update_queue()

    def _start_pkg_update(self, pkg_name: str, env_path: str):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env:
            self.console.log_divider(f"UPDATE {pkg_name}")
            self._update_queue.append((pkg_name, env))
            if not self._update_running:
                self._process_update_queue()

    def _process_update_queue(self):
        if not self._update_queue:
            self._update_running = False
            return
        self._update_running = True
        pkg_name, env = self._update_queue.pop(0)
        self.pip_mgr.update_package(env, pkg_name)

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
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env:
            reply = QMessageBox.question(
                self, "Confirm Uninstall",
                f"Uninstall {pkg_name} from {env.name}?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.console.log_divider(f"UNINSTALL {pkg_name}")
                self.pip_mgr.remove_package(env, pkg_name)

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

    def _start_pkg_install(self, env_path: str, pkg_names: str, force_reinstall: bool = False):
        env = self._find_env_by_path(self.pip_mgr.environments, env_path)
        if env:
            self.console.log_divider(f"INSTALL {pkg_names}")
            
            if not hasattr(self, '_install_queue'):
                self._install_queue = []
                self._install_running = False

            self._install_queue.append((pkg_names, env, force_reinstall))
            if not self._install_running:
                self._process_install_queue()

    def _process_install_queue(self):
        if not hasattr(self, '_install_queue') or not self._install_queue:
            self._install_running = False
            return
        self._install_running = True
        pkg_names, env, force = self._install_queue.pop(0)
        self.pip_mgr.install_package(env, pkg_names, force)

    def _on_install_done(self, env_path: str, pkg_names: str, success: bool):
        if not hasattr(self, '_affected_envs_install'):
            self._affected_envs_install = set()
        self._affected_envs_install.add(env_path)

        if success:
            self._log(f"Successfully installed {pkg_names} in {env_path}", "success")
        else:
            self._log(f"Failed to install {pkg_names} in {env_path}", "error")
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
        update_list = []
        for env_path, card in self._env_cards.items():
            env = card.env
            if env.is_scanned:
                for pkg in env.packages:
                    if pkg.is_selected and pkg.has_update:
                        update_list.append((pkg.name, env))

        if not update_list:
            self._log("No updatable packages selected.", "system")
            return

        self.console.log_divider(f"BATCH UPDATE ({len(update_list)} packages)")
        self._log(f"Batch updating: {', '.join(n for n, _ in update_list)}", "system")

        self._update_queue.extend(update_list)
        if not self._update_running:
            self._process_update_queue()

    # ── Batch Remove ─────────────────────────────────────────────────────

    def _batch_remove(self):
        remove_list = []
        for env_path, card in self._env_cards.items():
            env = card.env
            if env.is_scanned:
                for pkg in env.packages:
                    if pkg.is_selected:
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
        self.pip_mgr.remove_package(env, pkg_name)

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
                self.pip_mgr.scan_environment(env)

            # Existing: force UI refresh (name changes, etc.)
            for key in (old_keys & new_keys):
                self._env_cards[key].update_ui()

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
