from PySide6.QtWidgets import QLabel, QPushButton, QDialog

from core.manager_base import Environment
from ui.widgets.add_package_dialog import AddPackageDialog
from ui.widgets.env_card_base import BaseEnvCard


class WingetEnvCard(BaseEnvCard):
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

        self.badge_lbl = QLabel()
        self.badge_lbl.setObjectName("EnvBadge")
        self.badge_lbl.setVisible(False)
        self.h_layout.addWidget(self.badge_lbl)

        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("EnvCount")
        self.h_layout.addWidget(self.count_lbl)

        refresh_btn = QPushButton("↻")
        refresh_btn.setObjectName("EnvRefreshBtn")
        refresh_btn.setToolTip("Refresh applications")
        refresh_btn.clicked.connect(lambda: self.refresh_requested.emit(self.env.path))
        self.h_layout.addWidget(refresh_btn)

        self.up_all_btn = QPushButton("⇧")
        self.up_all_btn.setObjectName("EnvUpdateAllBtn")
        self.up_all_btn.setToolTip("Update all selected applications")
        self.up_all_btn.clicked.connect(lambda: self.update_all_requested.emit(self.env.path))
        self.h_layout.addWidget(self.up_all_btn)

        self.add_pkg_btn = QPushButton("+")
        self.add_pkg_btn.setObjectName("ActionBtnInstall")
        self.add_pkg_btn.setToolTip("Install application from winget")
        self.add_pkg_btn.clicked.connect(self._on_add_package_clicked)
        self.h_layout.addWidget(self.add_pkg_btn)

        self.update_ui()

    def _on_add_package_clicked(self):
        dialog = AddPackageDialog("winget", self)
        if dialog.exec() == QDialog.Accepted:
            package_ref, _force = dialog.get_data()
            if package_ref:
                self.add_package_requested.emit(self.env.path, package_ref, False)

    def update_ui(self):
        self.name_lbl.setText(self.env.name)
        env_type = str(getattr(self.env, "type", "") or "").lower()
        if env_type == "machine":
            self.ver_lbl.setText("(System-wide)")
            self.type_lbl.setText("[Machine]")
            self.type_lbl.setStyleSheet("color: #FF9800;")
        else:
            self.ver_lbl.setText("(Per-user)")
            self.type_lbl.setText("[User]")
            self.type_lbl.setStyleSheet("color: #42A5F5;")

        pkg_list = self.env.packages if self.env.packages is not None else []
        real_pkgs = [pkg for pkg in pkg_list if getattr(pkg, "is_missing", False) is False]
        pkg_count = len(real_pkgs) if getattr(self.env, "is_scanned", False) else "?"
        outdated_count = sum(1 for pkg in real_pkgs if getattr(pkg, "has_update", False)) if getattr(self.env, "is_scanned", False) else 0
        pinned_count = sum(1 for pkg in real_pkgs if (getattr(pkg, "metadata", {}) or {}).get("pinned_blocking")) if getattr(self.env, "is_scanned", False) else 0

        self.count_lbl.setText(f"{pkg_count} apps")
        if outdated_count > 0:
            tail = f" · 📌 {pinned_count}" if pinned_count > 0 else ""
            self.badge_lbl.setText(f"⬆ {outdated_count}{tail}")
            self.badge_lbl.setVisible(True)
            self.up_all_btn.setVisible(True)
        else:
            self.badge_lbl.setVisible(False)
            self.up_all_btn.setVisible(False)

        if self.is_expanded and getattr(self.env, "is_scanned", False):
            self._start_lazy_load()
