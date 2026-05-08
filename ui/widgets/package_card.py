from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QCheckBox, QPushButton, QFrame, QSizePolicy, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QTimer
from core.manager_base import Package
from core.trace_logger import trace_event, is_trace_enabled


def _build_constraint_warning(pkg: Package) -> str:
    if not pkg.latest_version:
        return ""
    constraint_parts = sorted(set(getattr(pkg, "required_by", []) or []))
    if constraint_parts:
        return f"Latest version {pkg.latest_version} may break version constraints from:\n  " + "\n  ".join(constraint_parts)
    return f"Latest version {pkg.latest_version} may break version constraints."


def _build_variant_tooltip(pkg: Package) -> str:
    from core.runtime_update import extract_local_version
    inst_local = extract_local_version(pkg.version)
    latest_local = extract_local_version(pkg.latest_version)
    inst_display = inst_local if inst_local else "(none)"
    latest_display = latest_local if latest_local else "(none)"
    return f"Build variant may change: {inst_display} → {latest_display}\nUpgrading may switch to a different build type."


class PackageCard(QFrame):
    """
    Component: Single Package Row (Tree Node)
    [▶] [Checkbox] [Name] [Constraint] [Version -> Latest] [Channel] [Update/Install/Remove Button]
    Supports collapsible children for dependency tree display (Pip) and Channel badges (NPM).
    """

    selection_changed = Signal(str, bool)          # pkg_name, is_selected
    update_requested = Signal(str, str)            # pkg_name, channel
    remove_requested = Signal(str)                 # pkg_name
    install_requested = Signal(str)                # pkg_name (for missing deps)
    config_requested = Signal(str)                 # pkg_name

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
        display_name = pkg.metadata.get("display_name", pkg.name) if pkg.metadata else pkg.name
        name_lbl = QLabel(display_name)
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
        elif pkg.latest_version and pkg.has_update:
            if getattr(pkg, "breaks_constraint", False):
                ver_text = f"{pkg.version} ➜ {pkg.latest_version} ⚠"
                ver_lbl = QLabel(ver_text)
                ver_lbl.setObjectName("PkgVersionUpdateWarning")
                constraint_info = _build_constraint_warning(pkg)
                if constraint_info:
                    ver_lbl.setToolTip(constraint_info)
            elif getattr(pkg, "build_variant_mismatch", False):
                ver_text = f"{pkg.version} ➜ {pkg.latest_version} 🔀"
                ver_lbl = QLabel(ver_text)
                ver_lbl.setObjectName("PkgVersionUpdateVariant")
                variant_info = _build_variant_tooltip(pkg)
                if variant_info:
                    ver_lbl.setToolTip(variant_info)
            else:
                ver_text = f"{pkg.version} ➜ {pkg.latest_version}"
                ver_lbl = QLabel(ver_text)
                ver_lbl.setObjectName("PkgVersionUpdate")
            row_layout.addWidget(ver_lbl)
        else:
            ver_lbl = QLabel(pkg.version)
            ver_lbl.setObjectName("PkgVersionBase")
            row_layout.addWidget(ver_lbl)

        # NPM Channel Badge (if available in metadata)
        channel = pkg.metadata.get("channel") if pkg.metadata else None
        if channel:
            ch_lbl = QLabel(f"[{channel.capitalize()}]")
            ch_lbl.setObjectName(f"PkgChannelBadge_{channel}")
            # Color is typically handled by QSS based on object name or we can inline style later.
            if channel != "latest":
                ch_lbl.setStyleSheet("color: #4cc9f0; font-weight: bold;")
            else:
                ch_lbl.setStyleSheet("color: #888;")
            row_layout.addWidget(ch_lbl)

        # Action Buttons
        if pkg.is_missing:
            # Install button for missing deps
            install_btn = QPushButton("+")
            install_btn.setObjectName("ActionBtnInstall")
            install_btn.setCursor(Qt.PointingHandCursor)
            install_btn.setToolTip(f"Install {pkg.name}")
            install_btn.clicked.connect(lambda: self.install_requested.emit(pkg.name))
            row_layout.addWidget(install_btn)
        else:
            if pkg.metadata and "channels_available" in pkg.metadata:
                conf_btn = QPushButton("⚙")
                conf_btn.setObjectName("ActionBtnConfig")
                conf_btn.setToolTip(f"Configure {pkg.name}")
                conf_btn.setCursor(Qt.PointingHandCursor)
                conf_btn.clicked.connect(lambda: self.config_requested.emit(pkg.name))
                row_layout.addWidget(conf_btn)
            # Update Button (Only if update available)
            if pkg.has_update:
                if getattr(pkg, "breaks_constraint", False):
                    up_btn = QPushButton("⇧")
                    up_btn.setObjectName("PkgUpdateBtnWarning")
                    constraint_info = _build_constraint_warning(pkg)
                    up_btn.setToolTip(f"Update {pkg.name} (⚠ may break version constraints)")
                    up_btn.setCursor(Qt.PointingHandCursor)
                    target_channel = channel or "latest"
                    up_btn.clicked.connect(lambda: self._confirm_constraint_update(pkg, target_channel))
                    row_layout.addWidget(up_btn)
                elif getattr(pkg, "build_variant_mismatch", False):
                    up_btn = QPushButton("⇧")
                    up_btn.setObjectName("PkgUpdateBtnVariant")
                    variant_info = _build_variant_tooltip(pkg)
                    up_btn.setToolTip(f"Update {pkg.name} (🔀 build variant may change)")
                    up_btn.setCursor(Qt.PointingHandCursor)
                    target_channel = channel or "latest"
                    up_btn.clicked.connect(lambda: self._confirm_variant_update(pkg, target_channel))
                    row_layout.addWidget(up_btn)
                else:
                    up_btn = QPushButton("⇧")
                    up_btn.setObjectName("PkgUpdateBtn")
                    up_btn.setCursor(Qt.PointingHandCursor)
                    up_btn.setToolTip(f"Update {pkg.name}")
                    target_channel = channel or "latest"
                    up_btn.clicked.connect(lambda: self.update_requested.emit(pkg.name, target_channel))
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
        checked_val = Qt.Checked.value if hasattr(Qt.Checked, "value") else 2

        self.pkg.is_selected = (state == checked_val)
        self.selection_changed.emit(self.pkg.name, self.pkg.is_selected)
        if is_trace_enabled():
            trace_event(
                "package_card",
                "checkbox_change",
                pkg_name=self.pkg.name,
                norm_name=self.pkg.norm_name,
                state=int(state),
                is_selected=self.pkg.is_selected,
                has_update=getattr(self.pkg, "has_update", False),
                is_missing=getattr(self.pkg, "is_missing", False),
            )

    def set_checked(self, checked: bool):
        if self.checkbox:
            self.pkg.is_selected = checked
            self.checkbox.blockSignals(True)
            self.checkbox.setChecked(checked)
            self.checkbox.blockSignals(False)

    def set_check_state(self, state):
        if not self.checkbox:
            return

        checked_val = Qt.Checked.value if hasattr(Qt.Checked, "value") else 2
        self.set_checked(state == checked_val)

    def _confirm_constraint_update(self, pkg, target_channel):
        warning_text = _build_constraint_warning(pkg)
        reply = QMessageBox.warning(
            self,
            "Constraint Warning",
            f"Update {pkg.name} from {pkg.version} to {pkg.latest_version}?\n\n"
            f"{warning_text}\n\n"
            f"This may break packages that depend on {pkg.name}.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.update_requested.emit(pkg.name, target_channel)

    def _confirm_variant_update(self, pkg, target_channel):
        variant_info = _build_variant_tooltip(pkg)
        reply = QMessageBox.warning(
            self,
            "Build Variant Change",
            f"Update {pkg.name} from {pkg.version} to {pkg.latest_version}?\n\n"
            f"{variant_info}\n\n"
            f"This may switch to a different build type (e.g. CUDA → CPU).",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.update_requested.emit(pkg.name, target_channel)

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
        if not self.env or not getattr(self.pkg, 'requires', None):
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
            if hasattr(self.env, "get_package_by_norm_name"):
                child_pkg = self.env.get_package_by_norm_name(dep_req.norm_name)
            else:
                child_pkg = None

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
                    metadata=child_pkg.metadata,
                    breaks_constraint=getattr(child_pkg, "breaks_constraint", False),
                    build_variant_mismatch=getattr(child_pkg, "build_variant_mismatch", False),
                )

            card = PackageCard(child_pkg, depth=self.depth + 1, env=self.env)

            # Forward signals
            card.update_requested.connect(self.update_requested)
            card.remove_requested.connect(self.remove_requested)
            card.install_requested.connect(self.install_requested)
            card.selection_changed.connect(self.selection_changed)
            card.config_requested.connect(self.config_requested)

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
