from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QDialogButtonBox, QLineEdit, QDialog
)
from PySide6.QtCore import Qt, Signal, QTimer
import re
from core.manager_base import Environment
from core.trace_logger import trace_event, is_trace_enabled
from ui.widgets.package_card import PackageCard


class BaseEnvCard(QFrame):
    """
    Component: Environment Header + Collapsible Package Tree
    Provides core logic for filtering, selecting, and rendering child packages.
    """

    refresh_requested = Signal(str)       # env_path
    update_all_requested = Signal(str)    # env_path
    runtime_update_requested = Signal(str) # env_path
    select_all_requested = Signal(str, bool) # env_path, is_selected
    update_package_requested = Signal(str, str, str) # pkg_name, channel, env_path
    remove_package_requested = Signal(str, str) # pkg_name, env_path
    add_package_requested = Signal(str, str, bool)    # env_path, pkg_names, force_reinstall
    install_missing_requested = Signal(str, str)      # pkg_name, env_path (for ghost deps)
    config_package_requested = Signal(str, str)       # pkg_name, env_path
    selection_state_changed = Signal(str, int, int)   # env_path, outdated_selected, outdated_total

    def __init__(self, env: Environment):
        super().__init__()
        self.env = env
        self.is_expanded = False
        self._pkgs_loaded = False
        self._pkg_load_queue = []
        self._outdated_only = False
        self._search_query = ""
        self._search_timer = None

        self.setObjectName("EnvCard")

        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)
        self.main_layout.setContentsMargins(0, 0, 0, 4)
        self.main_layout.setSpacing(0)

        # Build Header UI (Children will override this to add custom badges)
        self.header_frame = QFrame()
        self.header_frame.setObjectName("EnvHeaderFrame")
        self.header_frame.mousePressEvent = lambda e: self._toggle_collapse()
        self.h_layout = QHBoxLayout(self.header_frame)
        self.h_layout.setContentsMargins(8, 6, 8, 6)
        self.h_layout.setSpacing(10)

        self._build_header_ui()

        self.main_layout.addWidget(self.header_frame)

        # Content Area (Collapsible)
        self.content_container = QWidget()
        self.content_container.setVisible(False)
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(15, 4, 0, 4)  # Indent for tree
        self.content_layout.setSpacing(2)

        self.main_layout.addWidget(self.content_container)

    def _build_header_ui(self):
        """Subclasses should implement this and append custom layout."""
        self.toggle_lbl = QLabel("▶")
        self.toggle_lbl.setObjectName("ToggleArrow")
        self.h_layout.addWidget(self.toggle_lbl)
        self.h_layout.addSpacing(5)

        self.env_checkbox = QCheckBox()
        self.env_checkbox.setTristate(True)
        self.env_checkbox.stateChanged.connect(self._on_env_check_changed)
        self.h_layout.addWidget(self.env_checkbox)

        self.name_lbl = QLabel(f"{self.env.name}")
        self.name_lbl.setObjectName("CardTitle")
        self.h_layout.addWidget(self.name_lbl)

    def _on_env_check_changed(self, state):
        partial_val = Qt.PartiallyChecked.value if hasattr(Qt.PartiallyChecked, "value") else 1
        if state == partial_val:
            # Keep header interaction binary; partial state is visual feedback only.
            self.env_checkbox.blockSignals(True)
            self.env_checkbox.setCheckState(Qt.Checked)
            self.env_checkbox.blockSignals(False)
            state = Qt.Checked.value if hasattr(Qt.Checked, "value") else 2

        is_checked = state == Qt.Checked.value or state == Qt.Checked
        self.set_all_selected(is_checked, from_checkbox=True)
        self.select_all_requested.emit(self.env.path, is_checked)
        if is_trace_enabled():
            trace_event(
                "env_card",
                "env_checkbox_change",
                env_path=self.env.path,
                state=int(state.value if hasattr(state, "value") else int(state)),
                is_checked=is_checked,
            )

    def set_all_selected(self, checked: bool, from_checkbox=False):
        if not from_checkbox:
            self.env_checkbox.blockSignals(True)
            self.env_checkbox.setChecked(checked)
            self.env_checkbox.blockSignals(False)

        for pkg in self.env.packages:
            if not getattr(pkg, "is_missing", False):
                pkg.is_selected = checked

        self._update_child_checks_recursive(self.content_layout, checked)
        self._refresh_selection_states()
        if is_trace_enabled():
            selected, total = self.get_outdated_selection_stats()
            trace_event(
                "env_card",
                "set_all_selected",
                env_path=self.env.path,
                checked=checked,
                outdated_selected=selected,
                outdated_total=total,
            )

    def _update_child_checks_recursive(self, layout, checked):
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, PackageCard):
                if not getattr(widget.pkg, 'is_missing', False):
                    widget.set_checked(checked)
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
            if self._search_query or self._outdated_only:
                self._apply_filters()

    def _start_lazy_load(self):
        """Standard loading logic. Subclasses can override."""
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not getattr(self.env, "is_scanned", False):
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
        
        # Determine top-level packages
        top_level_pkgs = [p for p in self.env.packages if getattr(p, "is_top_level", True) and not getattr(p, "is_missing", False)]
        top_level_pkgs.sort(key=lambda p: (not p.has_update, p.name.lower()))

        if not top_level_pkgs:
            top_level_pkgs = sorted(
                [p for p in self.env.packages if not getattr(p, "is_missing", False)],
                key=lambda p: (not p.has_update, p.name.lower())
            )

        self._add_summary_label(top_level_pkgs)

        self._pkg_load_queue = list(top_level_pkgs)
        QTimer.singleShot(0, self._process_load_queue)

    def _add_summary_label(self, top_level_pkgs):
        total = len(self.env.packages)
        top_count = len(top_level_pkgs)
        transitive_count = total - top_count
        missing = sum(1 for p in self.env.packages if getattr(p, "is_missing", False))

        summary_parts = [f"{top_count} top-level"]
        if transitive_count > 0:
            summary_parts.append(f"{transitive_count} dependencies")
        if missing > 0:
            summary_parts.append(f"{missing} missing")

        if sum([top_count, transitive_count, missing]) > 0:
            summary_lbl = QLabel(f"  📊 {' · '.join(summary_parts)}")
            summary_lbl.setObjectName("EnvTreeSummary")
            self.content_layout.addWidget(summary_lbl)


    def _process_load_queue(self):
        batch_size = 8
        count = 0
        while self._pkg_load_queue and count < batch_size:
            pkg = self._pkg_load_queue.pop(0)
            card = PackageCard(pkg, depth=0, env=self.env)
            card.update_requested.connect(lambda p_name, ch: self.update_package_requested.emit(p_name, ch, self.env.path))
            card.remove_requested.connect(lambda p_name: self.remove_package_requested.emit(p_name, self.env.path))
            card.install_requested.connect(lambda p_name: self._on_install_missing(p_name))
            card.selection_changed.connect(self._on_pkg_selection_changed)
            card.config_requested.connect(lambda p_name: self.config_package_requested.emit(p_name, self.env.path))

            self.content_layout.addWidget(card)
            count += 1

        if self._pkg_load_queue:
            QTimer.singleShot(5, self._process_load_queue)
        else:
            if self._outdated_only:
                self._expand_outdated_branches(self.content_layout)
            self._apply_filters()
            self._refresh_selection_states()

    def _on_install_missing(self, pkg_name: str):
        self.add_package_requested.emit(self.env.path, pkg_name, False)

    # --- Filtering Logic ---
    def set_outdated_only(self, outdated_only: bool, selection_mode: str = "keep"):
        self._outdated_only = outdated_only

        if selection_mode == "select_all":
            for pkg in self.env.packages:
                if pkg.has_update and not getattr(pkg, "is_missing", False):
                    if not getattr(pkg, "breaks_constraint", False) and not getattr(pkg, "build_variant_mismatch", False):
                        pkg.is_selected = True
        elif selection_mode == "clear_all":
            for pkg in self.env.packages:
                if pkg.has_update and not getattr(pkg, "is_missing", False):
                    pkg.is_selected = False

        self._ensure_filter_expanded()

        if outdated_only and self.is_expanded and self._pkgs_loaded:
            self._expand_outdated_branches(self.content_layout)

        self._apply_filters()
        self._refresh_selection_states()
        if is_trace_enabled():
            selected, total = self.get_outdated_selection_stats()
            trace_event(
                "env_card",
                "outdated_filter",
                env_path=self.env.path,
                enabled=outdated_only,
                selection_mode=selection_mode,
                outdated_selected=selected,
                outdated_total=total,
            )

    def filter_packages(self, query: str):
        self._search_query = query.strip().lower()
        self._ensure_filter_expanded()
        if self._search_timer is None:
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.timeout.connect(self._apply_filters)
        self._search_timer.start(300)

    def _ensure_filter_expanded(self):
        if not getattr(self.env, "is_scanned", False):
            return

        should_expand_for_search = bool(self._search_query) and any(
            self._search_query in getattr(pkg, "name", "").lower()
            or self._search_query in getattr(pkg, "version", "").lower()
            for pkg in getattr(self.env, "packages", []) or []
        )
        should_expand_for_outdated = bool(self._outdated_only) and any(
            getattr(pkg, "has_update", False) or getattr(pkg, "is_missing", False)
            for pkg in getattr(self.env, "packages", []) or []
        )

        if (should_expand_for_search or should_expand_for_outdated) and not self.is_expanded:
            self.is_expanded = True
            self.content_container.setVisible(True)
            self.toggle_lbl.setText("▼")
            if not self._pkgs_loaded:
                self._start_lazy_load()

    def _apply_filters(self):
        if not getattr(self.env, "is_scanned", False):
            return

        match_context = None
        if self.is_expanded and self._search_query:
            match_context = self._get_match_context(self._search_query)

        outdated_context = None
        if self.is_expanded and self._outdated_only:
            outdated_context = self._get_outdated_context()
        
        self._apply_filters_recursive(self.content_layout, match_context, outdated_context)

    def _get_outdated_context(self):
        outdated_names = set()
        for pkg in self.env.packages:
            if pkg.has_update or getattr(pkg, "is_missing", False):
                outdated_names.add(pkg.norm_name)
        
        ancestor_names = set()
        for o_norm in outdated_names:
            self._get_all_ancestors(o_norm, ancestor_names)
            
        return {'outdated': outdated_names, 'ancestors': ancestor_names}

    def _get_match_context(self, query: str):
        match_names = set()
        for pkg in self.env.packages:
            if query in getattr(pkg, "name", "").lower() or query in getattr(pkg, "version", "").lower():
                match_names.add(pkg.norm_name)
        
        ancestor_names = set()
        for m_norm in match_names:
            self._get_all_ancestors(m_norm, ancestor_names)
            
        return {'matches': match_names, 'ancestors': ancestor_names}

    def _apply_filters_recursive(self, layout, match_context, outdated_context=None):
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, PackageCard):
                pkg = widget.pkg
                
                is_outdated_visible = True
                is_outdated_branch = False
                if self._outdated_only:
                    if outdated_context:
                        is_self_outdated = pkg.norm_name in outdated_context['outdated']
                        is_outdated_ancestor = pkg.norm_name in outdated_context['ancestors']
                        
                        if is_self_outdated or is_outdated_ancestor:
                            is_outdated_visible = True
                            is_outdated_branch = is_outdated_ancestor
                        else:
                            is_outdated_visible = False
                    else:
                        is_outdated_visible = pkg.has_update or getattr(pkg, 'is_missing', False)

                is_search_visible = True
                is_search_branch = False
                if self._search_query:
                    if match_context:
                        is_self_match = pkg.norm_name in match_context['matches']
                        is_search_ancestor = pkg.norm_name in match_context['ancestors']
                        
                        if is_self_match or is_search_ancestor:
                            is_search_visible = True
                            is_search_branch = is_search_ancestor
                        else:
                            is_search_visible = False
                    else:
                        is_search_visible = self._search_query in pkg.name.lower() or self._search_query in pkg.version.lower()

                visible = is_outdated_visible and is_search_visible
                should_expand = visible and (is_outdated_branch or is_search_branch)

                if visible:
                    widget.show()
                    if should_expand:
                        widget.expand_sync()
                    if widget._children_loaded and widget.is_expanded:
                        self._apply_filters_recursive(widget.children_layout, match_context, outdated_context)
                else:
                    widget.hide()

    def _on_pkg_selection_changed(self, pkg_name, is_selected):
        if getattr(self, '_syncing_selection', False):
            return
        self._syncing_selection = True
        try:
            norm_name = re.sub(r'[-_.]+', '-', pkg_name).lower()

            for pkg in self.env.packages:
                if pkg.norm_name == norm_name and not getattr(pkg, "is_missing", False):
                    pkg.is_selected = is_selected
                    
            if not norm_name:
                return

            ancestors = set()
            if is_selected:
                ancestors = self._get_all_ancestors(norm_name)
                
            self._sync_and_expand_recursive(self.content_layout, norm_name, ancestors, is_selected)
            self._refresh_selection_states()
            if is_trace_enabled():
                selected, total = self.get_outdated_selection_stats()
                trace_event(
                    "env_card",
                    "pkg_selection_change",
                    env_path=self.env.path,
                    pkg_name=pkg_name,
                    is_selected=is_selected,
                    outdated_selected=selected,
                    outdated_total=total,
                )
        finally:
            self._syncing_selection = False

    def _get_all_ancestors(self, target_norm_name: str, visited=None) -> set:
        if visited is None:
            visited = set()
        if target_norm_name in visited:
            return visited
        visited.add(target_norm_name)
        
        target_pkg = self.env.get_package_by_norm_name(target_norm_name) if hasattr(self.env, "get_package_by_norm_name") else None
        if target_pkg:
            for parent_norm in getattr(target_pkg, "required_by", []):
                self._get_all_ancestors(parent_norm, visited)
        return visited

    def _sync_and_expand_recursive(self, layout, target_norm, ancestors, is_selected):
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if isinstance(widget, PackageCard):
                pkg = widget.pkg
                if is_selected and pkg.norm_name in ancestors and pkg.norm_name != target_norm:
                    widget.expand_sync()
                if pkg.norm_name == target_norm:
                    widget.set_checked(is_selected)
                if getattr(widget, "_children_loaded", False):
                    self._sync_and_expand_recursive(widget.children_layout, target_norm, ancestors, is_selected)

    def _expand_outdated_branches(self, layout):
        """Expand all branches that lead to outdated/missing packages."""
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if not isinstance(widget, PackageCard):
                continue

            if self._has_outdated_in_subtree(widget.pkg):
                widget.expand_sync()
                if widget._children_loaded:
                    self._expand_outdated_branches(widget.children_layout)

    def _has_outdated_in_subtree(self, pkg, visited=None):
        if visited is None:
            visited = set()
        if not pkg:
            return False

        norm_name = getattr(pkg, "norm_name", "")
        if norm_name and norm_name in visited:
            return False
        if norm_name:
            visited = set(visited)
            visited.add(norm_name)

        if getattr(pkg, "has_update", False) or getattr(pkg, "is_missing", False):
            return True

        for dep_req in getattr(pkg, "requires", []):
            child_pkg = self.env.get_package_by_norm_name(dep_req.norm_name) if hasattr(self.env, "get_package_by_norm_name") else None
            if child_pkg and self._has_outdated_in_subtree(child_pkg, visited):
                return True

        return False

    def _refresh_selection_states(self):
        """Refresh package checkboxes from model state and update env tri-state."""
        self._sync_package_checks_recursive(self.content_layout)
        self._refresh_env_checkbox_state()
        selected, total = self.get_outdated_selection_stats()
        self.selection_state_changed.emit(self.env.path, selected, total)
        if is_trace_enabled():
            trace_event(
                "env_card",
                "selection_state_sync",
                env_path=self.env.path,
                outdated_selected=selected,
                outdated_total=total,
                env_checkbox_state=int(self.env_checkbox.checkState().value if hasattr(self.env_checkbox.checkState(), "value") else int(self.env_checkbox.checkState())),
            )

    def _sync_package_checks_recursive(self, layout):
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if not isinstance(widget, PackageCard):
                continue

            base_pkg = self.env.get_package_by_norm_name(widget.pkg.norm_name) if hasattr(self.env, "get_package_by_norm_name") else None
            is_selected = getattr(base_pkg or widget.pkg, "is_selected", False)
            widget.set_checked(is_selected)

            if widget._children_loaded:
                self._sync_package_checks_recursive(widget.children_layout)

    def _refresh_env_checkbox_state(self):
        all_packages = [
            p for p in self.env.packages
            if not getattr(p, "is_missing", False)
        ]
        selected = sum(1 for p in all_packages if getattr(p, "is_selected", False))

        if not all_packages or selected == 0:
            state = Qt.Unchecked
        elif selected == len(all_packages):
            state = Qt.Checked
        else:
            state = Qt.PartiallyChecked

        self.env_checkbox.blockSignals(True)
        self.env_checkbox.setCheckState(state)
        self.env_checkbox.blockSignals(False)

    def get_outdated_selection_stats(self):
        outdated = [
            p for p in self.env.packages
            if getattr(p, "has_update", False) and not getattr(p, "is_missing", False)
        ]
        selected = sum(1 for p in outdated if getattr(p, "is_selected", False))
        return selected, len(outdated)
