from PySide6.QtWidgets import (
    QLabel, QPushButton, QCheckBox, QDialog, QLineEdit, QDialogButtonBox, QVBoxLayout
)
from core.manager_base import Environment
from ui.widgets.add_package_dialog import AddPackageDialog
from ui.widgets.env_card_base import BaseEnvCard


class NpmEnvCard(BaseEnvCard):
    def __init__(self, env: Environment):
        super().__init__(env)

    def _build_header_ui(self):
        super()._build_header_ui()

        self.ver_lbl = QLabel()
        self.ver_lbl.setObjectName("EnvVersion")
        self.h_layout.addWidget(self.ver_lbl)

        self.type_lbl = QLabel()
        self.type_lbl.setObjectName("EnvTypeBadge")
        self.h_layout.addWidget(self.type_lbl)

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

        self.runtime_up_btn = QPushButton("Nd")
        self.runtime_up_btn.setObjectName("EnvRuntimeUpdateBtn")
        self.runtime_up_btn.setToolTip("Update Node.js runtime")
        self.runtime_up_btn.clicked.connect(lambda: self.runtime_update_requested.emit(self.env.path))
        self.h_layout.addWidget(self.runtime_up_btn)

        self.up_all_btn = QPushButton("⇧")
        self.up_all_btn.setObjectName("EnvUpdateAllBtn")
        self.up_all_btn.setToolTip("Update all packages")
        self.up_all_btn.clicked.connect(lambda: self.update_all_requested.emit(self.env.path))
        self.h_layout.addWidget(self.up_all_btn)

        self.add_pkg_btn = QPushButton("+")
        self.add_pkg_btn.setObjectName("ActionBtnInstall")
        self.add_pkg_btn.setToolTip("Add dependency")
        self.add_pkg_btn.clicked.connect(self._on_add_package_clicked)
        self.h_layout.addWidget(self.add_pkg_btn)

        self.update_ui()

    def _on_add_package_clicked(self):
        dialog = AddPackageDialog('npm', self)
        if dialog.exec() == QDialog.Accepted:
            pkg_names, _ = dialog.get_data()
            if pkg_names:
                self.add_package_requested.emit(self.env.path, pkg_names, False)

    def update_ui(self):
        title = f"{self.env.name}"
        if "path" in getattr(self.env, "tags", []):
            title += " [PATH]"
        self.name_lbl.setText(title)

        runtime_ver = getattr(self.env, "runtime_version", "")
        runtime_latest = getattr(self.env, "runtime_latest_version", "")
        runtime_has_update = bool(getattr(self.env, "runtime_has_update", False))
        runtime_has_major = bool(getattr(self.env, "runtime_has_major_update", False))
        runtime_major_latest = getattr(self.env, "runtime_major_latest_version", "")
        if runtime_ver:
            if runtime_has_major and runtime_major_latest:
                self.ver_lbl.setText(f"(Node {runtime_ver} → {runtime_major_latest} ⚠)")
                self.ver_lbl.setStyleSheet("color: #FFB74D;")
            elif runtime_has_update and runtime_latest:
                self.ver_lbl.setText(f"(Node {runtime_ver} -> {runtime_latest})")
                self.ver_lbl.setStyleSheet("")
            else:
                self.ver_lbl.setText(f"(Node {runtime_ver})")
                self.ver_lbl.setStyleSheet("")
        else:
            self.ver_lbl.setText("(Node ?)")
            self.ver_lbl.setStyleSheet("")

        env_type = str(getattr(self.env, "type", "") or "").lower()
        if env_type == "global":
            self.type_lbl.setText("[Global]")
            self.type_lbl.setStyleSheet("color: #FF9800;")
        elif env_type == "user_home_modules":
            self.type_lbl.setText("[Home Modules]")
            self.type_lbl.setStyleSheet("color: #42A5F5;")
        elif env_type == "user_roaming_modules":
            self.type_lbl.setText("[Roaming Modules]")
            self.type_lbl.setStyleSheet("color: #26A69A;")
        elif env_type == "standalone_modules":
            self.type_lbl.setText("[Standalone Modules]")
            self.type_lbl.setStyleSheet("color: #8D6E63;")
        else:
            self.type_lbl.setText("[Project]")
            self.type_lbl.setStyleSheet("color: #4CAF50;")

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

        if runtime_has_major:
            self.runtime_up_btn.setVisible(True)
            self.runtime_up_btn.setToolTip(
                f"Upgrade Node.js major version: {runtime_ver} → {runtime_major_latest}\n"
                "Major version upgrades may introduce breaking changes."
            )
            self.runtime_up_btn.setStyleSheet(
                "QPushButton { color: #FFB74D; border: 1px solid #FFB74D; }"
                "QPushButton:hover { background: rgba(255, 183, 77, 0.15); }"
            )
        elif runtime_has_update:
            self.runtime_up_btn.setVisible(True)
            self.runtime_up_btn.setStyleSheet("")
            self.runtime_up_btn.setToolTip(f"Update Node.js runtime: {runtime_ver} -> {runtime_latest}")
        else:
            self.runtime_up_btn.setVisible(False)
            self.runtime_up_btn.setStyleSheet("")
            self.runtime_up_btn.setToolTip("Node.js runtime is up to date")

        if self.is_expanded and getattr(self.env, "is_scanned", False):
            self._start_lazy_load()
