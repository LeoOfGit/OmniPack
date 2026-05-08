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
        self.setWindowTitle(f"OmniPack - Developer Package Manager{admin_suffix}")
        self.resize(1100, 700)

        # Config
        self.config_mgr = ConfigManager()

        # Icon and Taskbar Fix
        self._set_app_icon()

        # Central Stack
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

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

        self._add_app_tab("Python", 0)
        self.switcher_layout.addSpacing(2)
        self._add_app_tab("Node.js", 1)
        
        # Double Line Separator
        self.switcher_layout.addSpacing(10)
        for _ in range(2):
            line = QFrame()
            line.setFrameShape(QFrame.VLine)
            line.setFrameShadow(QFrame.Plain)
            line.setStyleSheet("background-color: #666;") # Muted color
            line.setFixedWidth(1)
            line.setFixedHeight(21) # Shorter for elegance
            self.switcher_layout.addWidget(line)
            self.switcher_layout.addSpacing(5) # Gap between the two lines
        self.switcher_layout.addSpacing(7) # Combined with 3 to keep roughly 10 offset

        self.help_btn = QPushButton("💡 Guide")
        self.help_btn.setObjectName("HelpButton")
        self.help_btn.setFixedHeight(22)
        self.help_btn.clicked.connect(self._show_help)
        self.switcher_layout.addWidget(self.help_btn)

        self.status_bar.addPermanentWidget(self.switcher_widget)

        # Theme
        self._apply_dark_theme()

        # Panels
        self._init_pip_panel()
        self._init_npm_panel()

        # Sync splitters dynamically
        self.pip_panel.splitter.splitterMoved.connect(lambda: self._sync_splitters(self.pip_panel, self.npm_panel))
        self.npm_panel.splitter.splitterMoved.connect(lambda: self._sync_splitters(self.npm_panel, self.pip_panel))

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

    def _sync_splitters(self, source_panel, target_panel):
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
        
        # Immediately update status bar to reflect the new active panel
        if index == 0 and hasattr(self.pip_panel, "_update_status_counts"):
            self.pip_panel._update_status_counts()
        elif index == 1 and hasattr(self.npm_panel, "_update_status_counts"):
            self.npm_panel._update_status_counts()

        # Auto-scan the first time user switches to it
        if index == 1 and not getattr(self, '_npm_scanned', False):
            self._npm_scanned = True
            if self.config_mgr.config.npm_settings.get("auto_refresh_on_start", True):
                QTimer.singleShot(200, self.npm_panel.start_scan)
        elif index == 0 and not getattr(self, '_pip_scanned', False):
            self._pip_scanned = True
            QTimer.singleShot(200, self.pip_panel.start_scan)

    # ── Panel Init ───────────────────────────────────────────────────────

    def _init_pip_panel(self):
        from ui.panels.pip_panel import PipPanel
        self.pip_panel = PipPanel(self.config_mgr, self)
        self.pip_panel.status_changed.connect(self._on_status_changed)
        self.stack.addWidget(self.pip_panel)

    def _init_npm_panel(self):
        from ui.panels.npm_panel import NpmPanel
        self.npm_panel = NpmPanel(self.config_mgr, self)
        self.npm_panel.status_changed.connect(self._on_status_changed)
        self.stack.addWidget(self.npm_panel)

    # ── UI State Persistence ─────────────────────────────────────────────

    def _restore_ui_state(self):
        if self.config_mgr.config.window_geometry:
            self.restoreGeometry(bytes.fromhex(self.config_mgr.config.window_geometry))
        if self.config_mgr.config.window_state:
            self.restoreState(bytes.fromhex(self.config_mgr.config.window_state))
        self._ensure_visible_on_screen()
        if self.config_mgr.config.pip_splitter_state:
            state_bytes = bytes.fromhex(self.config_mgr.config.pip_splitter_state)
            self.pip_panel.splitter.restoreState(state_bytes)
            self.npm_panel.splitter.restoreState(state_bytes)

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
        # Save splitter from the currently active panel
        active_panel = self.pip_panel if self.stack.currentIndex() == 0 else self.npm_panel
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
