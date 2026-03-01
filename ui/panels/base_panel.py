from PySide6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QScrollArea, QFrame, QHBoxLayout, QLineEdit, QPushButton
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
        self.console = ConsolePanel(self.splitter)
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

    def _setup_search_input(self, placeholder="Search..."):
        search_input = QLineEdit()
        search_input.setPlaceholderText(placeholder)
        search_input.setFixedWidth(150)
        search_input.setObjectName("ToolbarSearch")
        return search_input

    def _setup_common_toolbar(
        self,
        search_callback,
        refresh_callback,
        batch_update_callback,
        batch_remove_callback,
        extra_widgets_before_search=None,
        extra_widgets_end=None
    ):
        """Builds the uniform toolbar layout with customizable injections."""
        # Batch Selection
        select_all_btn = QPushButton("☑")
        select_all_btn.setFixedWidth(28)
        select_all_btn.clicked.connect(self._select_all)
        self.tb_layout.addWidget(select_all_btn)

        clear_btn = QPushButton("☐")
        clear_btn.setFixedWidth(28)
        clear_btn.clicked.connect(self._deselect_all)
        self.tb_layout.addWidget(clear_btn)

        if extra_widgets_before_search:
            for w in extra_widgets_before_search:
                self.tb_layout.addWidget(w)

        # Search
        self.search_input = self._setup_search_input()
        self.search_input.textChanged.connect(search_callback)
        self.tb_layout.addWidget(self.search_input)

        # Refresh
        self.refresh_btn = QPushButton("↻ Refresh")
        self.refresh_btn.setFixedWidth(85)
        self.refresh_btn.clicked.connect(refresh_callback)
        self.tb_layout.addWidget(self.refresh_btn)

        # Actions
        batch_btn = QPushButton("📦 Batch Update")
        batch_btn.setObjectName("ActionBtnBatchUpdate")
        batch_btn.clicked.connect(batch_update_callback)
        self.tb_layout.addWidget(batch_btn)

        batch_rm_btn = QPushButton("🗑 Batch Remove")
        batch_rm_btn.setObjectName("ActionBtnBatchRemove")
        batch_rm_btn.clicked.connect(batch_remove_callback)
        self.tb_layout.addWidget(batch_rm_btn)

        if extra_widgets_end:
            for w in extra_widgets_end:
                self.tb_layout.addWidget(w)

        self.tb_layout.addStretch()

    def _select_all(self):
        """Implemented by subclasses to handle 'Select All' action."""
        pass

    def _deselect_all(self):
        """Implemented by subclasses to handle 'Clear Selection' action."""
        pass
