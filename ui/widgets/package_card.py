from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QCheckBox, QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer
from core.manager_base import Package


class PackageCard(QFrame):
    """
    Component: Single Package Row (Tree Node)
    [▶] [Checkbox] [Name] [Constraint] [Version -> Latest] [Update/Install/Remove Button]
    Supports collapsible children for dependency tree display.
    """

    selection_changed = Signal(str, bool)          # pkg_name, is_selected
    update_requested = Signal(str)                 # pkg_name
    remove_requested = Signal(str)                 # pkg_name
    install_requested = Signal(str)                # pkg_name (for missing deps)

    def __init__(self, pkg: Package, depth: int = 0, env=None):
        super().__init__()
        self.pkg = pkg
        self.depth = depth
        self.env = env  # Reference to Environment for child lookups
        self.is_expanded = False
        self._children_loaded = False
        self._child_cards = []

        self.setObjectName("MissingPackageCard" if pkg.is_missing else "PackageCard")

        main_layout = QVBoxLayout()
        self.setLayout(main_layout)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Row container ---
        row_widget = QWidget()
        row_widget.setObjectName("PackageCardRow")
        row_layout = QHBoxLayout()
        row_widget.setLayout(row_layout)
        indent = 8 + (depth * 20)
        row_layout.setContentsMargins(indent, 4, 8, 4)

        # Toggle Arrow (only if has children)
        if pkg.has_children and not pkg.is_missing:
            self.toggle_btn = QLabel("▶")
            self.toggle_btn.setObjectName("PkgToggleArrow")
            self.toggle_btn.setFixedWidth(16)
            self.toggle_btn.setCursor(Qt.PointingHandCursor)
            self.toggle_btn.mousePressEvent = lambda e: self._toggle_children()
            row_layout.addWidget(self.toggle_btn)
        else:
            spacer_lbl = QLabel(" ")
            spacer_lbl.setObjectName("PkgLeafDot")
            spacer_lbl.setFixedWidth(16)
            row_layout.addWidget(spacer_lbl)

        # Checkbox (not for missing packages)
        if not pkg.is_missing:
            self.checkbox = QCheckBox()
            self.checkbox.setChecked(pkg.is_selected)
            self.checkbox.stateChanged.connect(self._on_check_changed)
            row_layout.addWidget(self.checkbox)
        else:
            self.checkbox = None

        # Name
        name_lbl = QLabel(pkg.name)
        name_lbl.setObjectName("PkgNameMissing" if pkg.is_missing else "PkgName")
        row_layout.addWidget(name_lbl, 1)  # Stretch

        # Version constraint (shown for non-top-level items)
        if pkg.version_constraint:
            constraint_lbl = QLabel(pkg.version_constraint)
            constraint_lbl.setObjectName("PkgConstraint")
            row_layout.addWidget(constraint_lbl)

        # Version / Status
        if pkg.is_missing:
            status_lbl = QLabel("Not Installed")
            status_lbl.setObjectName("PkgMissingLabel")
            row_layout.addWidget(status_lbl)
        elif pkg.latest_version and pkg.is_outdated:
            ver_text = f"{pkg.version} ➜ {pkg.latest_version}"
            ver_lbl = QLabel(ver_text)
            ver_lbl.setObjectName("PkgVersionUpdate")
            row_layout.addWidget(ver_lbl)
        else:
            ver_lbl = QLabel(pkg.version)
            ver_lbl.setObjectName("PkgVersionBase")
            row_layout.addWidget(ver_lbl)

        # Action Buttons
        if pkg.is_missing:
            # Install button for missing deps
            install_btn = QPushButton("📥")
            install_btn.setObjectName("ActionBtnInstall")
            install_btn.setCursor(Qt.PointingHandCursor)
            install_btn.setToolTip(f"Install {pkg.name}")
            install_btn.clicked.connect(lambda: self.install_requested.emit(pkg.name))
            row_layout.addWidget(install_btn)
        else:
            # Update Button (Only if update available)
            if pkg.is_outdated:
                up_btn = QPushButton("⇧")
                up_btn.setObjectName("PkgUpdateBtn")
                up_btn.setCursor(Qt.PointingHandCursor)
                up_btn.setToolTip(f"Update {pkg.name}")
                up_btn.clicked.connect(lambda: self.update_requested.emit(pkg.name))
                row_layout.addWidget(up_btn)
            else:
                spacer = QWidget()
                spacer.setObjectName("ActionBtnSpacer")
                row_layout.addWidget(spacer)

            # Remove Button
            rm_btn = QPushButton("-")
            rm_btn.setObjectName("ActionBtnRemove")
            rm_btn.setCursor(Qt.PointingHandCursor)
            rm_btn.setToolTip(f"Remove {pkg.name}")
            rm_btn.clicked.connect(lambda: self.remove_requested.emit(pkg.name))
            row_layout.addWidget(rm_btn)

        main_layout.addWidget(row_widget)

        # --- Children container (collapsible) ---
        self.children_container = QWidget()
        self.children_container.setVisible(False)
        self.children_layout = QVBoxLayout()
        self.children_container.setLayout(self.children_layout)
        self.children_layout.setContentsMargins(0, 0, 0, 0)
        self.children_layout.setSpacing(1)
        main_layout.addWidget(self.children_container)

    def _on_check_changed(self, state):
        self.pkg.is_selected = (state == Qt.Checked.value if hasattr(Qt.Checked, 'value') else state == Qt.Checked or state == 2)
        self.selection_changed.emit(self.pkg.name, self.pkg.is_selected)

    def set_checked(self, checked: bool):
        if self.checkbox:
            self.checkbox.setChecked(checked)

    def _toggle_children(self):
        """Toggle expand/collapse of child dependencies."""
        self.is_expanded = not self.is_expanded
        self.children_container.setVisible(self.is_expanded)
        if hasattr(self, 'toggle_btn'):
            self.toggle_btn.setText("▼" if self.is_expanded else "▶")

        if self.is_expanded and not self._children_loaded:
            self._load_children()

    def expand_sync(self):
        """Synchronously expand and load children."""
        if not self.is_expanded:
            self.is_expanded = True
            self.children_container.setVisible(True)
            if hasattr(self, 'toggle_btn'):
                self.toggle_btn.setText("▼")
            if not self._children_loaded:
                self._load_children(sync=True)

    def _load_children(self, sync=False):
        """Lazy-load child dependency cards."""
        if not self.env or not self.pkg.requires:
            return

        self._children_loaded = True
        self._child_load_queue = list(self.pkg.requires)
        if sync:
            self._process_child_load_queue(batch_size=9999)
        else:
            QTimer.singleShot(0, self._process_child_load_queue)

    def _process_child_load_queue(self, batch_size=8):
        """Batch-load children to avoid UI freeze."""
        count = 0
        while self._child_load_queue and count < batch_size:
            dep_req = self._child_load_queue.pop(0)

            # Look up the actual package in the environment
            child_pkg = self.env.get_package_by_norm_name(dep_req.norm_name)

            if child_pkg is None:
                # Create a ghost/missing package for display
                child_pkg = Package(
                    name=dep_req.name,
                    version="",
                    norm_name=dep_req.norm_name,
                    is_missing=True,
                    is_top_level=False,
                    version_constraint=dep_req.constraint,
                )
            else:
                # Create a display copy with constraint from parent
                # We don't mutate the original, just set constraint for display
                child_pkg = Package(
                    name=child_pkg.name,
                    version=child_pkg.version,
                    latest_version=child_pkg.latest_version,
                    has_update=child_pkg.has_update,
                    is_selected=child_pkg.is_selected,
                    requires=child_pkg.requires,
                    required_by=child_pkg.required_by,
                    is_top_level=False,
                    is_missing=child_pkg.is_missing,
                    version_constraint=dep_req.constraint,
                    norm_name=child_pkg.norm_name,
                )

            card = PackageCard(child_pkg, depth=self.depth + 1, env=self.env)

            # Forward signals
            card.update_requested.connect(self.update_requested)
            card.remove_requested.connect(self.remove_requested)
            card.install_requested.connect(self.install_requested)
            card.selection_changed.connect(self.selection_changed)

            self._child_cards.append(card)
            self.children_layout.addWidget(card)
            count += 1

        if self._child_load_queue and batch_size != 9999:
            QTimer.singleShot(5, self._process_child_load_queue)

    def clear_children(self):
        """Remove all child cards (for refresh)."""
        self._children_loaded = False
        self._child_cards.clear()
        while self.children_layout.count():
            item = self.children_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
