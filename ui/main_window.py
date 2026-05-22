"""
OmniPackWindow — The central application window.
Hosts the tab switcher, status bar, and manages Panel switching.
"""
import os
import ctypes
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QStackedWidget, QStatusBar, QLabel, QPushButton, QHBoxLayout,
    QApplication, QFrame
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QIcon, QDesktopServices

from core.config import ConfigManager
from core.pypi_cache import start_background_refresh_if_needed
from core.utils import get_app_root, is_admin


class OmniPackWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        admin_suffix = " (Admin)" if is_admin() else ""
        from version import __version__
        self.setWindowTitle(f"OmniPack v{__version__} - Developer Package Manager{admin_suffix}")
        self.resize(1100, 700)

        # Config
        self.config_mgr = ConfigManager()

        # Icon and Taskbar Fix
        self._set_app_icon()

        # Central Stack
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.panel_entries = []
        self.panel_scan_flags = {}

        # Tab button registry for state persistence
        self.tab_buttons = []

        # Status Bar + Tab Switcher
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.count_label = QLabel("")
        self.count_label.setObjectName("CountLabel")
        self.status_bar.addWidget(self.count_label, 0) # Fixed width on left

        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label, 1) # Stretching middle area

        self.switcher_widget = QWidget()
        self.switcher_layout = QHBoxLayout(self.switcher_widget)
        self.switcher_layout.setContentsMargins(0, 0, 10, 0)
        self.switcher_layout.setSpacing(0)

        # Panels
        self._init_panels()
        self._build_switcher_ui()

        self.status_bar.addPermanentWidget(self.switcher_widget)

        # Theme
        self._apply_dark_theme()

        # Restore UI State (this sets the active tab and triggers scan)
        self._restore_ui_state()
        self._schedule_pypi_cache_refresh()

    def _set_app_icon(self):
        icon_path = get_app_root() / "resources" / "OmniPack.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        # Ensure Windows taskbar displays the correct icon instead of Python's default
        try:
            my_appid = "leofgit.omnipack.v1"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(my_appid)
        except Exception:
            pass

    def _build_switcher_ui(self):
        for index, entry in enumerate(self.panel_entries):
            if index > 0:
                self.switcher_layout.addSpacing(2)
            self._add_app_tab(entry["label"], index)

        self.switcher_layout.addSpacing(10)
        for _ in range(2):
            line = QFrame()
            line.setFrameShape(QFrame.VLine)
            line.setFrameShadow(QFrame.Plain)
            line.setStyleSheet("background-color: #666;")
            line.setFixedWidth(1)
            line.setFixedHeight(21)
            self.switcher_layout.addWidget(line)
            self.switcher_layout.addSpacing(5)
        self.switcher_layout.addSpacing(7)

        self.help_btn = QPushButton("💡 Guide")
        self.help_btn.setObjectName("HelpButton")
        self.help_btn.setFixedHeight(22)
        self.help_btn.clicked.connect(self._show_help)
        self.switcher_layout.addWidget(self.help_btn)

    def _sync_splitters(self, source_panel):
        for entry in self.panel_entries:
            target_panel = entry["panel"]
            if target_panel is source_panel:
                continue
            target_panel.splitter.blockSignals(True)
            target_panel.splitter.setSizes(source_panel.splitter.sizes())
            target_panel.splitter.blockSignals(False)

    def _on_status_changed(self, msg: str, counts: str):
        self.status_label.setText(msg)
        self.count_label.setText(counts)

    # ── Tab Switching ────────────────────────────────────────────────────

    def _add_app_tab(self, name: str, index: int):
        btn = QPushButton(name)
        btn.setObjectName("AppTabButton")
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setFixedHeight(22) # Explicit common height
        btn.setFixedWidth(80) # Restoring fixed width for visual consistency
        btn.clicked.connect(lambda: self._switch_tab(index, btn))
        self.switcher_layout.addWidget(btn)
        self.tab_buttons.append(btn)

    def _switch_tab(self, index: int, btn: QPushButton):
        self.stack.setCurrentIndex(index)
        entry = self.panel_entries[index]
        panel = entry["panel"]

        if hasattr(panel, "_update_status_counts"):
            panel._update_status_counts()

        panel_key = entry["key"]
        if self.panel_scan_flags.get(panel_key):
            return

        should_scan = True
        auto_refresh_setting = entry.get("auto_refresh_setting")
        if auto_refresh_setting:
            settings_obj = getattr(self.config_mgr.config, auto_refresh_setting, {}) or {}
            should_scan = bool(settings_obj.get("auto_refresh_on_start", True))

        self.panel_scan_flags[panel_key] = True
        if should_scan:
            QTimer.singleShot(200, panel.start_scan)

    # ── Panel Init ───────────────────────────────────────────────────────

    def _register_panel(self, key: str, label: str, panel, auto_refresh_setting: str = ""):
        panel.status_changed.connect(self._on_status_changed)
        self.stack.addWidget(panel)
        self.panel_entries.append({
            "key": key,
            "label": label,
            "panel": panel,
            "auto_refresh_setting": auto_refresh_setting,
        })
        self.panel_scan_flags[key] = False
        panel.splitter.splitterMoved.connect(lambda *_args, source=panel: self._sync_splitters(source))
        return panel

    def _init_panels(self):
        from ui.panels.pip_panel import PipPanel
        from ui.panels.npm_panel import NpmPanel

        self.pip_panel = self._register_panel("pip", "Python", PipPanel(self.config_mgr, self))
        self.npm_panel = self._register_panel("npm", "Node.js", NpmPanel(self.config_mgr, self), auto_refresh_setting="npm_settings")

        if os.name == "nt":
            from ui.panels.winget_panel import WingetPanel
            self.winget_panel = self._register_panel(
                "winget",
                "WinGet",
                WingetPanel(self.config_mgr, self),
                auto_refresh_setting="winget_settings",
            )
        else:
            self.winget_panel = None

    # ── UI State Persistence ─────────────────────────────────────────────

    def _restore_ui_state(self):
        if self.config_mgr.config.window_geometry:
            self.restoreGeometry(bytes.fromhex(self.config_mgr.config.window_geometry))
        if self.config_mgr.config.window_state:
            self.restoreState(bytes.fromhex(self.config_mgr.config.window_state))
        self._ensure_visible_on_screen()
        if self.config_mgr.config.pip_splitter_state:
            state_bytes = bytes.fromhex(self.config_mgr.config.pip_splitter_state)
            for entry in self.panel_entries:
                entry["panel"].splitter.restoreState(state_bytes)

        saved_tab = self.config_mgr.config.current_tab
        if 0 <= saved_tab < len(self.tab_buttons):
            btn = self.tab_buttons[saved_tab]
            btn.setChecked(True)
            self._switch_tab(saved_tab, btn)
        else:
            # Fallback
            if self.tab_buttons:
                btn = self.tab_buttons[0]
                btn.setChecked(True)
                self._switch_tab(0, btn)

    def _save_ui_state(self):
        self.config_mgr.config.window_geometry = self.saveGeometry().toHex().data().decode()
        self.config_mgr.config.window_state = self.saveState().toHex().data().decode()
        active_panel = self.panel_entries[self.stack.currentIndex()]["panel"]
        self.config_mgr.config.pip_splitter_state = active_panel.splitter.saveState().toHex().data().decode()
        self.config_mgr.config.current_tab = self.stack.currentIndex()
        self.config_mgr.save_config()

    def _schedule_pypi_cache_refresh(self):
        cache_settings = getattr(self.config_mgr.config, "pypi_cache_settings", {}) or {}
        if not bool(cache_settings.get("auto_refresh_on_start", True)):
            return
        stale_after_hours = int(cache_settings.get("stale_after_hours", 24) or 24)
        proxy_settings = getattr(self.config_mgr.config, "proxy_settings", {}) or {}
        pip_settings = getattr(self.config_mgr.config, "pip_settings", {}) or {}
        QTimer.singleShot(
            1500,
            lambda: start_background_refresh_if_needed(
                proxy_settings=proxy_settings,
                stale_after_hours=stale_after_hours,
                timeout=None,
                pip_settings=pip_settings,
            ),
        )

    def _ensure_visible_on_screen(self):
        """Ensure window is visible and within screen bounds."""
        geom = self.frameGeometry()
        screens = QApplication.screens()

        on_screen = any(screen.availableGeometry().intersects(geom) for screen in screens)
        if not on_screen:
            primary = QApplication.primaryScreen().availableGeometry()
            self.move(primary.center() - self.rect().center())
        else:
            current_screen = QApplication.screenAt(geom.center()) or QApplication.primaryScreen()
            screen_geom = current_screen.availableGeometry()

            new_w = min(self.width(), int(screen_geom.width() * 0.95))
            new_h = min(self.height(), int(screen_geom.height() * 0.95))
            self.resize(new_w, new_h)

            if self.y() < screen_geom.y():
                self.move(self.x(), screen_geom.y())

    def closeEvent(self, event):
        self._save_ui_state()
        super().closeEvent(event)

    # ── Theme ────────────────────────────────────────────────────────────

    def _apply_dark_theme(self):
        from ui.styles.theme import load_theme
        
        # Load initially
        theme_str = load_theme("dark")
        self.setStyleSheet(theme_str)
        
        # Setup Hot Reloading (Dev only)
        import sys
        is_frozen = getattr(sys, "frozen", False)
        env_reload = os.environ.get("OMNIPACK_LIVE_RELOAD", "1") == "1"

        if not is_frozen and env_reload:
            from ui.styles.live_reload import StyleReloader
            qss_path = get_app_root() / "ui" / "styles" / "dark.qss"
            if qss_path.exists():
                self._style_watcher = StyleReloader(str(qss_path), parent=self)
                self._style_watcher.style_changed.connect(self.setStyleSheet)

    # ── Help System ──────────────────────────────────────────────────────

    def _show_help(self):
        # Open the local HTML guide directly in the system's default browser.
        # This keeps the binary light by avoiding heavy built-in browser engines.
        guide_path = get_app_root() / "./docs/UserGuide.html"
        if guide_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(guide_path.absolute())))
