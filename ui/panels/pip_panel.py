"""
PipPanel — Self-contained QWidget for managing Python (pip/uv) environments.
Extracted from OmniPack.pyw to keep the main window thin.
"""
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QLineEdit, QScrollArea, QFrame, QSplitter, QLabel, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, Signal

from core.manager_base import Environment
from managers.pip_manager import PipManager
from ui.widgets.console_panel import ConsolePanel


from ui.panels.base_panel import BasePanel

class PipPanel(BasePanel):
    """Complete pip management panel with left (env list) + right (console) split."""

    def __init__(self, config_mgr, parent=None):
        super().__init__(config_mgr, parent)
        self.pip_mgr = PipManager(config_mgr)
        self._env_cards = {}
        self._update_queue = []
        self._update_running = False

        self._build_pip_ui()
        self._connect_signals()

    def _build_pip_ui(self):
        self.outdated_only_checkbox = QCheckBox("Outdated Only")
        self.outdated_only_checkbox.setToolTip("Show only outdated packages")
        self.outdated_only_checkbox.setChecked(False)
        self.outdated_only_checkbox.stateChanged.connect(self._toggle_outdated_only)

        settings_btn = QPushButton("⚙ Envs")
        settings_btn.setObjectName("ActionBtnRefresh")
        settings_btn.setToolTip("Add/Remove Environments")
        settings_btn.clicked.connect(self._open_settings)

        self._setup_common_toolbar(
            search_callback=self._on_search_text_changed,
            refresh_callback=self.start_scan,
            batch_update_callback=self._batch_update,
            batch_remove_callback=self._batch_remove,
            extra_widgets_before_search=[self.outdated_only_checkbox],
            extra_widgets_end=[settings_btn]
        )

    def _connect_signals(self):
        self.pip_mgr.log_msg.connect(self._log)
        self.pip_mgr.log_batch.connect(self._log_batch)
        self.pip_mgr.env_scanned.connect(self._on_env_scanned)
        self.pip_mgr.update_done.connect(self._on_update_done)
        self.pip_mgr.remove_done.connect(self._on_remove_done)
        self.pip_mgr.install_done.connect(self._on_install_done)

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

        # Clear current list
        while self.scroll_layout.count() > 1:
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.pip_mgr.reload_envs()
        envs = self.pip_mgr.list_environments()

        if not envs:
            self._log("No Python environments found. Please add one in Settings.", "error")
            self.refresh_btn.setEnabled(True)
            return

        self._log(f"Loading {len(envs)} environments...", "system")
        self._env_cards = {}

        for env in envs:
            from ui.widgets.env_card import EnvCard
            self._log(f"Initializing card for {env.name}...", "stdout")
            card = EnvCard(env)
            # Inherit current filters
            if hasattr(self, 'outdated_only_checkbox'):
                card.set_outdated_only(self.outdated_only_checkbox.isChecked())
            if hasattr(self, 'search_input'):
                card.filter_packages(self.search_input.text())
            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)

            norm_path = os.path.normpath(env.path).lower()
            self._env_cards[norm_path] = card

            card.refresh_requested.connect(self._refresh_single_env)
            card.update_all_requested.connect(self._update_all_in_env)
            card.update_package_requested.connect(self._start_pkg_update)
            card.remove_package_requested.connect(self._start_pkg_remove)
            card.add_package_requested.connect(self._start_pkg_install)

            self.pip_mgr.scan_environment(env)

        self._log("All environments queued for scan.", "system")

    def _on_env_scanned(self, env: Environment):
        norm_key = os.path.normpath(env.path).lower()
        if norm_key in self._env_cards:
            self._env_cards[norm_key].update_ui()
        QTimer.singleShot(200, self._check_all_tasks_done)

    def _check_all_tasks_done(self):
        if not self.pip_mgr._active_workers:
            self.refresh_btn.setEnabled(True)
            self._log("All tasks completed.", "system")
            self._update_status_counts()

    def _update_status_counts(self):
        total_envs = len(self.pip_mgr.environments)
        scanned_envs = sum(1 for e in self.pip_mgr.environments if getattr(e, 'is_scanned', False))
        
        pkgs = 0
        updates = 0
        for e in self.pip_mgr.environments:
            if getattr(e, 'is_scanned', False):
                pkgs += len(e.packages)
                updates += sum(1 for p in e.packages if p.has_update)

        status = f"Scanned {scanned_envs}/{total_envs} Envs"
        counts = f"Packages: {pkgs} | Updates: {updates}"
        self.status_changed.emit(status, counts)

    # ── Single Env ───────────────────────────────────────────────────────

    def _refresh_single_env(self, env_path: str):
        target_key = os.path.normpath(env_path).lower()
        env = next((e for e in self.pip_mgr.environments
                     if os.path.normpath(e.path).lower() == target_key), None)
        if env:
            self._log(f"Refreshing {env.name}...", "system")
            env.is_scanned = False
            if target_key in self._env_cards:
                self._env_cards[target_key]._pkgs_loaded = False
            self.pip_mgr.scan_environment(env)

    def _update_all_in_env(self, env_path: str):
        target_key = os.path.normpath(env_path).lower()
        env = next((e for e in self.pip_mgr.environments
                     if os.path.normpath(e.path).lower() == target_key), None)
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
        target_key = os.path.normpath(env_path).lower()
        env = next((e for e in self.pip_mgr.environments
                     if os.path.normpath(e.path).lower() == target_key), None)
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
        target_key = os.path.normpath(env_path).lower()
        env = next((e for e in self.pip_mgr.environments
                     if os.path.normpath(e.path).lower() == target_key), None)
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
        target_key = os.path.normpath(env_path).lower()
        env = next((e for e in self.pip_mgr.environments
                     if os.path.normpath(e.path).lower() == target_key), None)
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

        if hasattr(self, '_install_queue') and self._install_queue:
            self._process_install_queue()
        else:
            self._install_running = False
            for p in self._affected_envs_install:
                self._refresh_single_env(p)
            self._affected_envs_install.clear()

    # ── Selection / Filter ───────────────────────────────────────────────

    def _select_all(self):
        for card in self._env_cards.values():
            card.set_all_selected(True)

    def _deselect_all(self):
        for card in self._env_cards.values():
            card.set_all_selected(False)

    def _toggle_outdated_only(self, state):
        is_checked = (state == Qt.Checked.value or state == Qt.Checked)
        for card in self._env_cards.values():
            card.set_outdated_only(is_checked)

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
        dialog = SettingsDialog(self.config_mgr, self)

        def on_envs_changed():
            self._log("Config changed. Syncing UI...", "system")
            old_keys = set(self._env_cards.keys())

            self.pip_mgr.reload_envs()
            new_envs = self.pip_mgr.list_environments()
            new_keys = {os.path.normpath(e.path).lower() for e in new_envs}

            # Removals
            for key in (old_keys - new_keys):
                card = self._env_cards.pop(key)
                card.deleteLater()

            # Additions
            for key in (new_keys - old_keys):
                env = next(e for e in new_envs if os.path.normpath(e.path).lower() == key)
                from ui.widgets.env_card import EnvCard
                card = EnvCard(env)
                card.set_outdated_only(self.outdated_only_checkbox.isChecked())
                self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)
                self._env_cards[key] = card

                card.refresh_requested.connect(self._refresh_single_env)
                card.update_all_requested.connect(self._update_all_in_env)
                card.update_package_requested.connect(self._start_pkg_update)
                card.remove_package_requested.connect(self._start_pkg_remove)
                card.add_package_requested.connect(self._start_pkg_install)
                self.pip_mgr.scan_environment(env)

            # Existing: force UI refresh (name changes, etc.)
            for key in (old_keys & new_keys):
                self._env_cards[key].update_ui()

        dialog.environments_changed.connect(on_envs_changed)
        dialog.exec()
