import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QScrollArea, QFrame, QHBoxLayout, QLineEdit, QPushButton, QCheckBox
from PySide6.QtCore import Qt, Signal

class BasePanel(QWidget):
    """
    Base class for all package management panels (Pip, Npm, etc.)
    Provides a consistent Layout: [Left (Toolbar + ScrollArea) | Right (Console)]
    """
    status_changed = Signal(str, str)
    
    # Common UI Constants
    LEFT_MIN_WIDTH = 400
    CONSOLE_MIN_WIDTH = 150
    STRETCH_LEFT = 2
    STRETCH_RIGHT = 1

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self._build_base_ui()

    def _build_base_ui(self):
        root_layout = QVBoxLayout()
        self.setLayout(root_layout)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(1)

        # ── Left Container ──
        self.left_container = QWidget()
        self.left_layout = QVBoxLayout(self.left_container)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(0)
        self.left_container.setMinimumWidth(self.LEFT_MIN_WIDTH)

        # Toolbar (Subclasses should add widgets here)
        self.toolbar = QWidget()
        self.toolbar.setObjectName("LeftToolbar")
        self.tb_layout = QHBoxLayout(self.toolbar)
        self.tb_layout.setContentsMargins(5, 5, 5, 5)
        self.left_layout.addWidget(self.toolbar)

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("BaseScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("BaseScrollContent")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.addStretch()

        self.scroll_area.setWidget(self.scroll_content)
        self.left_layout.addWidget(self.scroll_area)

        self.splitter.addWidget(self.left_container)

        # ── Right: Console ──
        from ui.widgets.console_panel import ConsolePanel
        self.console = ConsolePanel(self.splitter, self.config_mgr)
        self.console.setMinimumWidth(self.CONSOLE_MIN_WIDTH)
        self.splitter.addWidget(self.console)

        # Splitter behavior
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setStretchFactor(0, self.STRETCH_LEFT)
        self.splitter.setStretchFactor(1, self.STRETCH_RIGHT)

        root_layout.addWidget(self.splitter)

    def _log(self, msg: str, tag: str = "stdout"):
        self.console.log(msg, tag)

    def _setup_search_input(self, placeholder="Search & Filter"):
        search_input = QLineEdit()
        search_input.setPlaceholderText(placeholder)
        search_input.setFixedWidth(150)
        search_input.setObjectName("ToolbarSearch")
        return search_input

    def _setup_common_toolbar(
        self,
        search_callback,
        outdated_callback,
        refresh_callback,
        batch_update_callback,
        batch_remove_callback,
        manage_envs_callback,
        extra_widgets_before_search=None,
        extra_widgets_end=None
    ):
        """Builds the uniform toolbar layout with customizable injections."""
        # Batch Selection (Tri-state)
        self.selection_checkbox = QCheckBox("Select")
        self.selection_checkbox.setTristate(True)
        self.selection_checkbox.setCheckState(Qt.Unchecked)
        self.selection_checkbox.setObjectName("ToolbarCheckbox")
        self.selection_checkbox.setToolTip("Select/Clear all packages")
        self.selection_checkbox.stateChanged.connect(self._on_selection_checkbox_changed)
        self.tb_layout.addWidget(self.selection_checkbox)

        if extra_widgets_before_search:
            for w in extra_widgets_before_search:
                self.tb_layout.addWidget(w)

        # Search
        self.search_input = self._setup_search_input()
        self.search_input.textChanged.connect(search_callback)
        self.search_input.setToolTip("Search & Filter")
        self.tb_layout.addWidget(self.search_input)

        # Outdated Only
        self.outdated_checkbox = QCheckBox("Outdated")
        self.outdated_checkbox.setTristate(True)
        self.outdated_checkbox.setCheckState(Qt.Unchecked)
        self.outdated_checkbox.setObjectName("ToolbarCheckbox")
        self.outdated_checkbox.setToolTip("Only show packages that have updates available")
        self.outdated_checkbox.stateChanged.connect(outdated_callback)
        self.tb_layout.addWidget(self.outdated_checkbox)

        # Space before right-aligned buttons
        self.tb_layout.addStretch()

        # Settings
        self.manage_envs_btn = QPushButton("⚙ Settings")
        self.manage_envs_btn.setObjectName("ActionBtnRefresh")
        self.manage_envs_btn.clicked.connect(manage_envs_callback)
        self.tb_layout.addWidget(self.manage_envs_btn)

        # Refresh
        self.refresh_btn = QPushButton("↻ Refresh")
        self.refresh_btn.setObjectName("ActionBtnRefresh")
        self.refresh_btn.setFixedWidth(85)
        self.refresh_btn.clicked.connect(refresh_callback)
        self.refresh_btn.setToolTip("Refresh")
        self.tb_layout.addWidget(self.refresh_btn)

        # Actions
        batch_btn = QPushButton("⇧ Update")
        batch_btn.setObjectName("ActionBtnBatchUpdate")
        batch_btn.clicked.connect(batch_update_callback)
        batch_btn.setToolTip("Update all selected packages")
        self.tb_layout.addWidget(batch_btn)

        batch_rm_btn = QPushButton("- Remove")
        batch_rm_btn.setObjectName("ActionBtnBatchRemove")
        batch_rm_btn.clicked.connect(batch_remove_callback)
        batch_rm_btn.setToolTip("Remove all selected packages")
        self.tb_layout.addWidget(batch_rm_btn)

        if extra_widgets_end:
            for w in extra_widgets_end:
                self.tb_layout.addWidget(w)

    def _select_all(self):
        """Implemented by subclasses to handle 'Select All' action."""
        pass

    def _deselect_all(self):
        """Implemented by subclasses to handle 'Clear Selection' action."""
        pass

    def _on_selection_checkbox_changed(self, state):
        checked_val = Qt.Checked.value if hasattr(Qt.Checked, "value") else 2
        partial_val = Qt.PartiallyChecked.value if hasattr(Qt.PartiallyChecked, "value") else 1

        if state == partial_val:
            # Treat partial as checked when user clicks; partial is display-only.
            self.selection_checkbox.blockSignals(True)
            self.selection_checkbox.setCheckState(Qt.Checked)
            self.selection_checkbox.blockSignals(False)
            state = checked_val

        if state == checked_val or state == Qt.Checked:
            self._select_all()
        else:
            self._deselect_all()

    def _set_selection_checkbox_state(self, state):
        if not hasattr(self, "selection_checkbox"):
            return
        self.selection_checkbox.blockSignals(True)
        self.selection_checkbox.setCheckState(state)
        self.selection_checkbox.blockSignals(False)

    def _clear_env_card_widgets(self):
        """Clear all env cards while keeping the trailing stretch item."""
        while self.scroll_layout.count() > 1:
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _apply_current_filters_to_card(self, card):
        """Apply global toolbar filters to a card."""
        if hasattr(self, "outdated_checkbox"):
            state = self.outdated_checkbox.checkState()
            outdated_on = state != Qt.Unchecked
            card.set_outdated_only(outdated_on, selection_mode="keep")
        if hasattr(self, "search_input"):
            card.filter_packages(self.search_input.text())

    @staticmethod
    def _path_key(path: str) -> str:
        return os.path.normcase(os.path.normpath(str(path)))

    def _find_env_by_path(self, environments, env_path: str):
        target_key = self._path_key(env_path)
        return next((e for e in environments if self._path_key(e.path) == target_key), None)

    def _emit_status_counts(self, environments):
        total_envs = len(environments)
        scanned_envs = sum(1 for e in environments if getattr(e, "is_scanned", False))

        pkgs = 0
        updates = 0
        for env in environments:
            if getattr(env, "is_scanned", False):
                pkgs += len(getattr(env, "packages", []))
                updates += sum(1 for p in getattr(env, "packages", []) if getattr(p, "has_update", False))

        status = f"Scanned {scanned_envs}/{total_envs} Envs"
        counts = f"Packages: {pkgs} | Updates: {updates}"
        self.status_changed.emit(status, counts)
