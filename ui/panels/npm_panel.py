"""
NpmPanel — Self-contained QWidget for managing npm global packages.
Ported from NpmManagerApp in npm_manager.pyw → PySide6.
"""
import os
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QLineEdit, QScrollArea, QFrame, QSplitter, QLabel, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, Signal

from managers.npm_manager import NpmManager, NpmApp, NpmExecutor
from ui.widgets.console_panel import ConsolePanel
from ui.widgets.npm_app_card import NpmAppCard


from ui.panels.base_panel import BasePanel
from ui.widgets.npm_app_card import NpmAppCard
from ui.panels.npm_app_edit_dialog import NpmAppEditDialog

class NpmPanel(BasePanel):
    """Complete npm management panel with left (app list) + right (console) split."""

    def __init__(self, config_mgr, parent=None):
        super().__init__(config_mgr, parent)
        self.npm_mgr = NpmManager(config_mgr)
        self.app_cards: dict[str, NpmAppCard] = {}
        self._is_busy = False

        self._build_npm_ui()
        self._connect_signals()

    def _build_npm_ui(self):
        add_btn = QPushButton("＋ Add")
        add_btn.clicked.connect(self._add_app)

        self._setup_common_toolbar(
            search_callback=self._filter_apps,
            refresh_callback=self._refresh_apps,
            batch_update_callback=self._batch_update,
            batch_remove_callback=self._batch_remove,
            extra_widgets_end=[add_btn]
        )
        
        # Override spacing for npm cards
        self.scroll_layout.setSpacing(4)

    def _connect_signals(self):
        self.npm_mgr.log_msg.connect(self._log)
        self.npm_mgr.scan_done.connect(self._on_scan_done)
        self.npm_mgr.updates_checked.connect(self._on_updates_checked)
        self.npm_mgr.action_done.connect(self._on_action_done)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _log(self, msg: str, tag: str = "system"):
        self.console.log(msg, tag)

    def _set_busy(self, busy: bool, status: str = ""):
        self._is_busy = busy
        self.refresh_btn.setEnabled(not busy)
        if status:
            self._current_status = status
            self._update_status_counts()

    def _update_status_counts(self):
        apps = self.npm_mgr.apps
        installed = sum(1 for a in apps.values() if a.is_installed)
        updatable = sum(1 for a in apps.values()
                       if a.is_installed and a.latest_version and a.latest_version != a.version)
        counts = f"Installed: {installed} | Updates: {updatable}"
        status = getattr(self, '_current_status', 'Ready')
        self.status_changed.emit(status, counts)

    # ── Scan ─────────────────────────────────────────────────────────────

    def start_scan(self):
        """Auto-start scan. Called externally or from refresh button."""
        self._refresh_apps()

    def _refresh_apps(self):
        if self._is_busy:
            return
        self._set_busy(True, "Scanning...")
        self.console.log_divider("REFRESH")
        self.npm_mgr.start_scan()

    def _on_scan_done(self, packages: dict, error: str):
        self.npm_mgr.on_scan_done(packages, error)
        if error:
            self._set_busy(False, "Scan failed")
            self._log(error, "error")
            return

        self._rebuild_card_list()
        self._set_busy(False, "Ready")

        # Trigger update check
        self.npm_mgr.check_updates()

    def _on_updates_checked(self, all_tags: dict):
        self.npm_mgr.on_updates_checked(all_tags)
        self._rebuild_card_list()

    # ── Card List ────────────────────────────────────────────────────────

    def _rebuild_card_list(self):
        # Clear existing
        while self.scroll_layout.count() > 1:
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.app_cards.clear()

        apps = self.npm_mgr.apps
        channels = self.config_mgr.config.npm_channels

        # Sort: installed first, then alphabetical
        sorted_names = sorted(
            apps.keys(),
            key=lambda n: (0 if apps[n].is_installed else 1, n.lower()),
        )

        for name in sorted_names:
            app = apps[name]
            card = NpmAppCard(app, channels)
            card.action_requested.connect(self._on_action)
            card.select_toggled.connect(self._on_select)
            self.scroll_layout.insertWidget(self.scroll_layout.count() - 1, card)
            self.app_cards[name] = card

        self._update_status_counts()

    # ── Selection / Filter ───────────────────────────────────────────────

    def _on_select(self, name: str, selected: bool):
        pass  # Managed by card

    def _select_all(self):
        for card in self.app_cards.values():
            card.set_selected(True)

    def _deselect_all(self):
        for card in self.app_cards.values():
            card.set_selected(False)

    def _filter_apps(self, text: str):
        q = text.lower()
        for name, card in self.app_cards.items():
            app = card.app
            visible = q in app.name.lower() or q in app.display_name.lower() or q in app.description.lower()
            card.setVisible(visible)

    # ── Actions ──────────────────────────────────────────────────────────

    def _on_action(self, name: str, action: str):
        if action == "config":
            app = self.npm_mgr.apps.get(name)
            if not app:
                return
            from PySide6.QtWidgets import QDialog
            from ui.panels.npm_app_edit_dialog import NpmAppEditDialog
            
            dialog = NpmAppEditDialog(app, self.config_mgr.config.npm_channels, self)
            if dialog.exec() == QDialog.Accepted:
                if dialog.is_delete:
                    self.npm_mgr.remove_app(name)
                    self._log(f"Removed {name} from config (not uninstalled)", "system")
                elif dialog.result_app:
                    self.npm_mgr.update_app(
                        name,
                        display_name=dialog.result_app.display_name,
                        description=dialog.result_app.description,
                        channel=dialog.result_app.channel,
                        channels_available=dialog.result_app.channels_available,
                    )
                    self.npm_mgr.check_updates()
                self._rebuild_card_list()
            return

        if action == "uninstall":
            reply = QMessageBox.question(
                self, "Confirm Uninstall",
                f"Uninstall {name} globally?\nThis will run: npm uninstall -g {name}",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self.console.log_divider(f"{action.upper()} {name}")
        self.npm_mgr.run_action(name, action)

    def _on_action_done(self, name: str, action: str, success: bool):
        self.npm_mgr.on_action_done(name, action, success)

        if not self.npm_mgr._task_queue and not self.npm_mgr._is_busy:
            # Auto-refresh after last action
            self._set_busy(False, "Ready")
            QTimer.singleShot(300, self._refresh_apps)

    # ── Batch Update ─────────────────────────────────────────────────────

    def _batch_update(self):
        if self._is_busy:
            return

        selected = [
            name for name, card in self.app_cards.items()
            if card.app.is_selected and card.app.is_installed
        ]
        if not selected:
            self._log("No installed apps selected for batch update.", "system")
            self._current_status = "Select apps first"
            self._update_status_counts()
            return

        self.console.log_divider(f"BATCH UPDATE ({len(selected)} apps)")
        self._log(f"Starting batch update for: {', '.join(selected)}", "system")
        self._set_busy(True, "Updating...")

        first = selected[0]
        for name in selected[1:]:
            self.npm_mgr._task_queue.append((name, "update"))
        self.npm_mgr.run_action(first, "update")

    # ── Batch Remove ─────────────────────────────────────────────────────

    def _batch_remove(self):
        if self._is_busy:
            return

        selected = [
            name for name, card in self.app_cards.items()
            if card.app.is_selected and card.app.is_installed
        ]
        if not selected:
            self._log("No installed apps selected for batch remove.", "system")
            self._current_status = "Select apps first"
            self._update_status_counts()
            return

        reply = QMessageBox.question(
            self, "Confirm Batch Uninstall",
            f"Are you sure you want to globally uninstall {len(selected)} apps?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.console.log_divider(f"BATCH UNINSTALL ({len(selected)} apps)")
        self._log(f"Starting batch uninstall for: {', '.join(selected)}", "system")
        self._set_busy(True, "Uninstalling...")

        first = selected[0]
        for name in selected[1:]:
            self.npm_mgr._task_queue.append((name, "uninstall"))
        self.npm_mgr.run_action(first, "uninstall")

    # ── Add App ──────────────────────────────────────────────────────────

    def _add_app(self):
        from PySide6.QtWidgets import QDialog
        from ui.panels.npm_app_edit_dialog import NpmAppEditDialog
        
        dialog = NpmAppEditDialog(None, self.config_mgr.config.npm_channels, self)
        if dialog.exec() == QDialog.Accepted and dialog.result_app:
            self.npm_mgr.add_app(dialog.result_app)
            self._log(f"Added {dialog.result_app.name} to config", "system")
            self._rebuild_card_list()
            # Immediately trigger an update check to populate its channels
            self.npm_mgr.check_updates()
