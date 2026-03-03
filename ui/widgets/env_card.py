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
    Component: Environment Header + Collapsible Dependency Tree
    [>] [Env Icon] [Env Name] (3.12) | [50 pkgs] [Update All] [Refresh]
    [ ----- Tree of Top-level Packages with expandable dependencies ----- ]
    """

    refresh_requested = Signal(str)       # env_path
    update_all_requested = Signal(str)    # env_path
    select_all_requested = Signal(str, bool) # env_path, is_selected
    update_package_requested = Signal(str, str) # pkg_name, env_path
    remove_package_requested = Signal(str, str) # pkg_name, env_path
    add_package_requested = Signal(str, str, bool)    # env_path, pkg_names, force_reinstall
    install_missing_requested = Signal(str, str)      # pkg_name, env_path (for ghost deps)

    def __init__(self, env: Environment):
        super().__init__()
        self.env = env
        self.is_expanded = False
        self._pkgs_loaded = False
        self._pkg_load_queue = []

        self.setObjectName("EnvCard")

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

        # Tree mode indicator
        self.tree_badge = QLabel("🌲")
        self.tree_badge.setObjectName("TreeBadge")
        self.tree_badge.setToolTip("Dependency tree view")
        h_layout.addWidget(self.tree_badge)

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
        self.content_layout.setContentsMargins(15, 4, 0, 4)  # Indent for tree
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
        self._update_child_checks_recursive(self.content_layout, checked)

    def _update_child_checks_recursive(self, layout, checked):
        """Recursively update checkbox states in the tree."""
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, PackageCard):
                if widget.pkg.has_update and not widget.pkg.is_missing:
                    widget.set_checked(checked)
                # Also check nested children
                if widget._children_loaded:
                    self._update_child_checks_recursive(widget.children_layout, checked)

    def set_checked(self, checked: bool):
        self.env_checkbox.setChecked(checked)

    def _toggle_collapse(self):
        self.is_expanded = not self.is_expanded
        self.content_container.setVisible(self.is_expanded)
        self.toggle_lbl.setText("▼" if self.is_expanded else "▶")

        if self.is_expanded:
            if not self._pkgs_loaded:
                self._start_lazy_load()
            
            # Re-apply filters when expanding to ensure 
            # search context is correctly applied to the newly visible UI
            if self._search_query:
                self._apply_filters()

    def _start_lazy_load(self):
        """Load top-level packages into the tree."""
        # Clear loading label if any
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

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

        # Get top-level packages (not depended on by anyone)
        top_level_pkgs = [p for p in self.env.packages if p.is_top_level and not p.is_missing]

        # Sort: outdated first, then alphabetical
        top_level_pkgs.sort(key=lambda p: (not p.has_update, p.name.lower()))

        if not top_level_pkgs:
            # Fallback: if dep resolution failed, show all packages
            top_level_pkgs = sorted(
                [p for p in self.env.packages if not p.is_missing],
                key=lambda p: (not p.has_update, p.name.lower())
            )

        # Show summary
        total = len(self.env.packages)
        top_count = len(top_level_pkgs)
        transitive_count = total - top_count
        missing = sum(1 for p in self.env.packages if p.is_missing)

        summary_parts = [f"{top_count} top-level"]
        if transitive_count > 0:
            summary_parts.append(f"{transitive_count} dependencies")
        if missing > 0:
            summary_parts.append(f"{missing} missing")

        summary_lbl = QLabel(f"  📊 {' · '.join(summary_parts)}")
        summary_lbl.setObjectName("EnvTreeSummary")
        self.content_layout.addWidget(summary_lbl)

        self._pkg_load_queue = list(top_level_pkgs)
        QTimer.singleShot(0, self._process_load_queue)

    def set_outdated_only(self, outdated_only: bool):
        self._outdated_only = outdated_only
        self._apply_filters()

    _outdated_only = True
    _search_query = ""
    _search_timer = None

    def filter_packages(self, query: str):
        """Handle search query with debouncing."""
        self._search_query = query.strip().lower()
        
        if self._search_timer is None:
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.timeout.connect(self._apply_filters)
            
        # 300ms debounce
        self._search_timer.start(300)

    def _apply_filters(self):
        """Core filter application logic with focused deep search."""
        if not self.env.is_scanned:
            return

        # Optimization (Strategy 3): 
        # Only perform heavy deep-search context calculation if the card is expanded.
        # This prevents lag when multiple environments are present but only one is being focused.
        match_context = None
        if self.is_expanded and self._search_query:
            match_context = self._get_match_context(self._search_query)
        
        # Apply recursion (if match_context is None, it acts like a basic filter)
        self._apply_filters_recursive(self.content_layout, match_context)

    def _get_match_context(self, query: str):
        """
        Build a context dictionary identifying matches and their ancestors.
        Returns: { 'matches': set(norm_names), 'ancestors': set(norm_names) }
        """
        match_names = set()
        for pkg in self.env.packages:
            if query in pkg.name.lower() or query in pkg.version.lower():
                match_names.add(pkg.norm_name)
        
        # Traverse up from matches to find all ancestors
        ancestor_names = set()
        for m_norm in match_names:
            self._get_all_ancestors(m_norm, ancestor_names)
            
        return {
            'matches': match_names,
            'ancestors': ancestor_names
        }

    def _apply_filters_recursive(self, layout, match_context):
        """Recursively apply filters and handle auto-expansion."""
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, PackageCard):
                pkg = widget.pkg
                
                # Default visibility logic
                visible = True
                should_expand = False
                
                # Check Outdated Filter
                if self._outdated_only and not (pkg.has_update or pkg.is_missing):
                    visible = False
                
                # Check Search Filter (Apply Strategy 3 Logic)
                if self._search_query:
                    if match_context:
                        # Focused Search Mode: Use deep context
                        is_match = pkg.norm_name in match_context['matches']
                        is_ancestor = pkg.norm_name in match_context['ancestors']
                        
                        if is_match or is_ancestor:
                            visible = True
                            if is_ancestor and not is_match:
                                should_expand = True
                            elif is_match:
                                should_expand = is_ancestor
                        else:
                            visible = False
                    else:
                        # Silent/Collapsed Mode: Simple top-level match only
                        visible = self._search_query in pkg.name.lower() or self._search_query in pkg.version.lower()
                else:
                    # No active search query
                    visible = True

                if visible:
                    widget.show()
                    if should_expand:
                        # Heavy lifting only for the 'focused' environment
                        widget.expand_sync()
                        if widget._children_loaded:
                            self._apply_filters_recursive(widget.children_layout, match_context)
                else:
                    widget.hide()

    def _process_load_queue(self):
        """Process batch of top-level packages per frame."""
        batch_size = 8
        count = 0
        while self._pkg_load_queue and count < batch_size:
            pkg = self._pkg_load_queue.pop(0)
            card = PackageCard(pkg, depth=0, env=self.env)
            card.update_requested.connect(lambda p: self.update_package_requested.emit(p, self.env.path))
            card.remove_requested.connect(lambda p: self.remove_package_requested.emit(p, self.env.path))
            card.install_requested.connect(lambda p: self._on_install_missing(p))
            card.selection_changed.connect(self._on_pkg_selection_changed)

            matches_search = not getattr(self, '_search_query', '') or getattr(self, '_search_query', '') in pkg.name.lower()
            matches_outdated = not self._outdated_only or pkg.has_update or pkg.is_missing
            if not (matches_search and matches_outdated):
                card.hide()
            self.content_layout.addWidget(card)
            count += 1

        if self._pkg_load_queue:
            QTimer.singleShot(5, self._process_load_queue)

    def _on_pkg_selection_changed(self, pkg_name, is_selected):
        """Forward selection change for a specific package."""
        if getattr(self, '_syncing_selection', False):
            return
            
        self._syncing_selection = True
        try:
            # Update the source package object in the environment
            norm_name = ""
            for pkg in self.env.packages:
                if pkg.name == pkg_name and not pkg.is_missing:
                    pkg.is_selected = is_selected
                    norm_name = pkg.norm_name
                    break
                    
            if not norm_name:
                return

            # If checked, find all ancestors so we can expand them
            ancestors = set()
            if is_selected:
                ancestors = self._get_all_ancestors(norm_name)
                
            self._sync_and_expand_recursive(self.content_layout, norm_name, ancestors, is_selected)
        finally:
            self._syncing_selection = False

    def _get_all_ancestors(self, target_norm_name: str, visited=None) -> set:
        if visited is None:
            visited = set()
        if target_norm_name in visited:
            return visited
        visited.add(target_norm_name)
        
        target_pkg = self.env.get_package_by_norm_name(target_norm_name)
        if target_pkg:
            for parent_norm in target_pkg.required_by:
                self._get_all_ancestors(parent_norm, visited)
        return visited

    def _sync_and_expand_recursive(self, layout, target_norm, ancestors, is_selected):
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, PackageCard):
                pkg = widget.pkg
                
                # Expand if this is an ancestor
                if is_selected and pkg.norm_name in ancestors and pkg.norm_name != target_norm:
                    widget.expand_sync()
                
                # Sync checkbox if it's the exact package
                if pkg.norm_name == target_norm:
                    if widget.checkbox:
                        widget.checkbox.blockSignals(True)
                        widget.checkbox.setChecked(is_selected)
                        widget.checkbox.blockSignals(False)
                
                # Recurse into children
                if widget._children_loaded:
                    self._sync_and_expand_recursive(widget.children_layout, target_norm, ancestors, is_selected)

    def _on_install_missing(self, pkg_name: str):
        """Handle install request for a missing dependency."""
        self.add_package_requested.emit(self.env.path, pkg_name, False)

    def update_ui(self):
        """Refresh header info from env object"""
        self.name_lbl.setText(f"{self.env.name}")
        if self.env.python_version:
            self.ver_lbl.setText(f"(Python {self.env.python_version})")

        pkg_list = self.env.packages if self.env.packages is not None else []
        # Count only non-missing (real) packages
        real_pkgs = [p for p in pkg_list if not p.is_missing]
        pkg_count = len(real_pkgs) if self.env.is_scanned else "?"
        outdated_count = sum(1 for p in real_pkgs if p.has_update) if self.env.is_scanned else 0

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
