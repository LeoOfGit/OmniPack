from PySide6.QtWidgets import (
    QLabel, QPushButton, QCheckBox, QDialog, QLineEdit, QDialogButtonBox, QVBoxLayout
)
from core.manager_base import Environment
from ui.widgets.add_package_dialog import AddPackageDialog
from ui.widgets.env_card_base import BaseEnvCard


class PipEnvCard(BaseEnvCard):
    def __init__(self, env: Environment):
        super().__init__(env)

    def _build_header_ui(self):
        super()._build_header_ui()

        # Python Version
        self.ver_lbl = QLabel()
        self.ver_lbl.setObjectName("EnvVersion")
        if self.env.python_version:
            self.ver_lbl.setText(f"(Python {self.env.python_version})")
        self.h_layout.addWidget(self.ver_lbl)

        self.h_layout.addStretch()

        # Status Badges
        self.badge_lbl = QLabel()
        self.badge_lbl.setObjectName("EnvBadge")
        self.badge_lbl.setVisible(False)
        self.h_layout.addWidget(self.badge_lbl)

        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("EnvCount")
        self.h_layout.addWidget(self.count_lbl)

        # Action Buttons
        refresh_btn = QPushButton("↻")
        refresh_btn.setObjectName("EnvRefreshBtn")
        refresh_btn.setToolTip("Refresh Environment")
        refresh_btn.clicked.connect(lambda: self.refresh_requested.emit(self.env.path))
        self.h_layout.addWidget(refresh_btn)

        self.runtime_up_btn = QPushButton("Py")
        self.runtime_up_btn.setObjectName("EnvRuntimeUpdateBtn")
        self.runtime_up_btn.setToolTip("Update Python runtime")
        self.runtime_up_btn.clicked.connect(lambda: self.runtime_update_requested.emit(self.env.path))
        self.h_layout.addWidget(self.runtime_up_btn)

        self.up_all_btn = QPushButton("⇧")
        self.up_all_btn.setObjectName("EnvUpdateAllBtn")
        self.up_all_btn.setToolTip("Update all packages")
        self.up_all_btn.clicked.connect(lambda: self.update_all_requested.emit(self.env.path))
        self.h_layout.addWidget(self.up_all_btn)

        self.add_pkg_btn = QPushButton("+")
        self.add_pkg_btn.setObjectName("ActionBtnInstall")
        self.add_pkg_btn.setToolTip("Add dependency (e.g., vtk, gmsh vtk==9.5.2)")
        self.add_pkg_btn.clicked.connect(self._on_add_package_clicked)
        self.h_layout.addWidget(self.add_pkg_btn)

        self.update_ui()

    def _on_add_package_clicked(self):
        dialog = AddPackageDialog('pip', self)
        if dialog.exec() == QDialog.Accepted:
            pkg_names, force = dialog.get_data()
            if pkg_names:
                self.add_package_requested.emit(self.env.path, pkg_names, force)

    def update_ui(self):
        title = f"{self.env.name}"
        if "path" in getattr(self.env, "tags", []):
            title += " [PATH]"
            
        self.name_lbl.setText(title)
        runtime_ver = getattr(self.env, "runtime_version", "") or self.env.python_version
        runtime_latest = getattr(self.env, "runtime_latest_version", "")
        runtime_has_update = bool(getattr(self.env, "runtime_has_update", False))
        if runtime_ver:
            if runtime_has_update and runtime_latest:
                self.ver_lbl.setText(f"(Python {runtime_ver} -> {runtime_latest})")
            else:
                self.ver_lbl.setText(f"(Python {runtime_ver})")

        pkg_list = self.env.packages if self.env.packages is not None else []
        real_pkgs = [p for p in pkg_list if getattr(p, "is_missing", False) is False]
        pkg_count = len(real_pkgs) if getattr(self.env, "is_scanned", False) else "?"
        outdated_count = sum(1 for p in real_pkgs if p.has_update) if getattr(self.env, "is_scanned", False) else 0

        self.count_lbl.setText(f"{pkg_count} pkgs")

        if outdated_count > 0:
            self.badge_lbl.setText(f"⬆ {outdated_count}")
            self.badge_lbl.setVisible(True)
            self.up_all_btn.setVisible(True)
        else:
            self.badge_lbl.setVisible(False)
            self.up_all_btn.setVisible(False)

        if runtime_has_update:
            self.runtime_up_btn.setVisible(True)
            self.runtime_up_btn.setToolTip(f"Update Python runtime: {runtime_ver} -> {runtime_latest}")
        else:
            self.runtime_up_btn.setVisible(False)
            self.runtime_up_btn.setToolTip("Python runtime is up to date")

        if self.is_expanded and getattr(self.env, "is_scanned", False):
            self._start_lazy_load()
