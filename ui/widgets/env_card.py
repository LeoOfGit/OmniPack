from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QScrollArea, QSizePolicy, QCheckBox,
    QDialog, QLineEdit, QDialogButtonBox
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QFont
from core.manager_base import Environment, Package
from ui.widgets.package_card import PackageCard

class AddPackageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Dependency")
        self.setMinimumWidth(350)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        layout.addWidget(QLabel("Enter package name(s):"))
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText("vtk or vtk==9.5.2 or vtk gmsh")
        layout.addWidget(self.line_edit)
        
        self.force_check = QCheckBox("--force-reinstall")
        self.force_check.setToolTip("Force reinstallation of all packages even if they are already up-to-date.")
        layout.addWidget(self.force_check)
        
        layout.addSpacing(10)
        
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def get_data(self):
        return self.line_edit.text().strip(), self.force_check.isChecked()

class EnvCard(QFrame):
    """
    Component: Environment Header + Collapsible Package List
    [>] [Env Icon] [Env Name] (3.12) | [50 pkgs] [Update All] [Refresh]
    [ ----- Checkbox Package List ----- ]
    """
    
    refresh_requested = Signal(str)       # env_path
    update_all_requested = Signal(str)    # env_path
    select_all_requested = Signal(str, bool) # env_path, is_selected
    update_package_requested = Signal(str, str) # pkg_name, env_path
    remove_package_requested = Signal(str, str) # pkg_name, env_path
    add_package_requested = Signal(str, str, bool)    # env_path, pkg_names, force_reinstall
    
    def __init__(self, env: Environment):
        super().__init__()
        self.env = env
        self.is_expanded = False
        self._pkgs_loaded = False
        self._pkg_load_queue = []
        
        self.setObjectName("EnvCard")
        # Style embedded here or global QSS
        
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        main_layout.setContentsMargins(0, 0, 0, 4)
        main_layout.setSpacing(0)
        
        # --- Header ---
        self.header_frame = QFrame()
        self.header_frame.setObjectName("EnvHeaderFrame")
        
        # Make header clickable
        self.header_frame.mousePressEvent = lambda e: self._toggle_collapse()
        
        h_layout = QHBoxLayout(self.header_frame)
        h_layout.setContentsMargins(8, 6, 8, 6)
        h_layout.setSpacing(10)
        
        # Toggle Arrow (Chevron)
        self.toggle_lbl = QLabel("▶")
        self.toggle_lbl.setObjectName("ToggleArrow")
        h_layout.addWidget(self.toggle_lbl)
        
        h_layout.addSpacing(5)

        # Environment Checkbox (for select all in env)
        self.env_checkbox = QCheckBox()
        self.env_checkbox.stateChanged.connect(self._on_env_check_changed)
        h_layout.addWidget(self.env_checkbox)
        
        # Env Name
        self.name_lbl = QLabel(f"{env.name}")
        self.name_lbl.setObjectName("CardTitle")
        h_layout.addWidget(self.name_lbl)
        
        # Python Version
        self.ver_lbl = QLabel()
        self.ver_lbl.setObjectName("EnvVersion")
        h_layout.addWidget(self.ver_lbl)
        
        h_layout.addStretch()
        
        # Status Badges
        self.badge_lbl = QLabel()
        self.badge_lbl.setObjectName("EnvBadge")
        self.badge_lbl.setVisible(False)
        h_layout.addWidget(self.badge_lbl)
        
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("EnvCount")
        h_layout.addWidget(self.count_lbl)
        
        # Action Buttons
        refresh_btn = QPushButton("↻")
        refresh_btn.setObjectName("EnvRefreshBtn")
        refresh_btn.setToolTip("Refresh Environment")
        refresh_btn.clicked.connect(lambda: self.refresh_requested.emit(env.path))
        h_layout.addWidget(refresh_btn)

        self.up_all_btn = QPushButton("⇧")
        self.up_all_btn.setObjectName("EnvUpdateAllBtn")
        self.up_all_btn.clicked.connect(lambda: self.update_all_requested.emit(env.path))
        h_layout.addWidget(self.up_all_btn)

        self.add_pkg_btn = QPushButton("➕")
        self.add_pkg_btn.setObjectName("EnvRefreshBtn")
        self.add_pkg_btn.setToolTip("Add dependency (e.g., vtk, gmsh vtk==9.5.2)")
        self.add_pkg_btn.clicked.connect(self._on_add_package_clicked)
        h_layout.addWidget(self.add_pkg_btn)

        self.update_ui()

        main_layout.addWidget(self.header_frame)
        
        # --- Content Area (Collapsible) ---
        self.content_container = QWidget()
        self.content_container.setVisible(False)
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(30, 0, 0, 0) # Indent
        self.content_layout.setSpacing(2)
        
        main_layout.addWidget(self.content_container)

    def _on_add_package_clicked(self):
        dialog = AddPackageDialog(self)
        if dialog.exec() == QDialog.Accepted:
            pkg_names, force = dialog.get_data()
            if pkg_names:
                self.add_package_requested.emit(self.env.path, pkg_names, force)

    def _on_env_check_changed(self, state):
        self.set_all_selected(state == Qt.Checked, from_checkbox=True)
        self.select_all_requested.emit(self.env.path, state == Qt.Checked)

    def set_all_selected(self, checked: bool, from_checkbox=False):
        """Set all outdated packages to selected/deselected."""
        if not from_checkbox:
            self.env_checkbox.blockSignals(True)
            self.env_checkbox.setChecked(checked)
            self.env_checkbox.blockSignals(False)

        for pkg in self.env.packages:
            if pkg.has_update:
                pkg.is_selected = checked
        
        # Also update child cards if they are loaded
        for i in range(self.content_layout.count()):
            widget = self.content_layout.itemAt(i).widget()
            if isinstance(widget, PackageCard):
                if widget.pkg.has_update:
                    widget.set_checked(checked)

    def set_checked(self, checked: bool):
        self.env_checkbox.setChecked(checked)

    def _toggle_collapse(self):
        self.is_expanded = not self.is_expanded
        self.content_container.setVisible(self.is_expanded)
        self.toggle_lbl.setText("▼" if self.is_expanded else "▶")
        
        if self.is_expanded and not self._pkgs_loaded:
            self._start_lazy_load()

    def _start_lazy_load(self):
        # Clear loading label if any
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        if not self.env.is_scanned:
            lbl = QLabel("Scanning packages...")
            lbl.setObjectName("EnvLoadingLbl")
            self.content_layout.addWidget(lbl)
            return

        if not self.env.packages:
            lbl = QLabel("No packages found.")
            lbl.setObjectName("EnvEmptyLbl")
            self.content_layout.addWidget(lbl)
            return

        self._pkgs_loaded = True
            
        # Prioritize outdated packages at top
        sorted_pkgs = sorted(
            self.env.packages, 
            key=lambda p: (not p.has_update, p.name.lower())
        )
        
        self._pkg_load_queue = list(sorted_pkgs)
        QTimer.singleShot(0, self._process_load_queue)

    def set_outdated_only(self, outdated_only: bool):
        self._outdated_only = outdated_only
        self._apply_filters()

    def filter_packages(self, query: str):
        self._search_query = query.lower()
        self._apply_filters()
        
    def _apply_filters(self):
        if self._pkgs_loaded:
            for i in range(self.content_layout.count()):
                widget = self.content_layout.itemAt(i).widget()
                if hasattr(widget, 'pkg'):
                    pkg = widget.pkg
                    matches_search = not getattr(self, '_search_query', '') or getattr(self, '_search_query', '') in pkg.name.lower()
                    matches_outdated = not self._outdated_only or pkg.has_update
                    if matches_search and matches_outdated:
                        widget.show()
                    else:
                        widget.hide()

    _outdated_only = True
    _search_query = ""

    def _process_load_queue(self):
        # Process 10 items per frame
        batch_size = 10
        count = 0
        while self._pkg_load_queue and count < batch_size:
            pkg = self._pkg_load_queue.pop(0)
            card = PackageCard(pkg)
            card.update_requested.connect(lambda p: self.update_package_requested.emit(p, self.env.path))
            card.remove_requested.connect(lambda p: self.remove_package_requested.emit(p, self.env.path))
            
            matches_search = not getattr(self, '_search_query', '') or getattr(self, '_search_query', '') in pkg.name.lower()
            matches_outdated = not self._outdated_only or pkg.has_update
            if not (matches_search and matches_outdated):
                card.hide()
            self.content_layout.addWidget(card)
            count += 1
            
        if self._pkg_load_queue:
            QTimer.singleShot(5, self._process_load_queue)

    def update_ui(self):
        """Refresh header info from env object"""
        self.name_lbl.setText(f"{self.env.name}")
        if self.env.python_version:
            self.ver_lbl.setText(f"(Python {self.env.python_version})")
        
        pkg_list = self.env.packages if self.env.packages is not None else []
        pkg_count = len(pkg_list) if self.env.is_scanned else "?"
        outdated_count = sum(1 for p in pkg_list if p.has_update) if self.env.is_scanned else 0
        
        self.count_lbl.setText(f"{pkg_count} pkgs")
        
        if outdated_count > 0:
            self.badge_lbl.setText(f"⬆ {outdated_count}")
            self.badge_lbl.setVisible(True)
            self.up_all_btn.setVisible(True)
        else:
            self.badge_lbl.setVisible(False)
            self.up_all_btn.setVisible(False)
            
        # If expanded, reload list
        if self.is_expanded and self.env.is_scanned:
            self._start_lazy_load()
