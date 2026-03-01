from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QCheckBox, QPushButton, QFrame, QVBoxLayout, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from core.manager_base import Package

class PackageCard(QFrame):
    """
    Component: Single Package Row
    [Checkbox] [Name] [Version -> Latest] [Update Button]
    """
    
    selection_changed = Signal(str, bool) # pkg_name, is_selected
    update_requested = Signal(str)        # pkg_name
    remove_requested = Signal(str)        # pkg_name
    
    def __init__(self, pkg: Package):
        super().__init__()
        self.pkg = pkg
        self.setObjectName("PackageCard")
        
        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(8, 4, 8, 4)
        
        # Checkbox
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(pkg.is_selected)
        self.checkbox.stateChanged.connect(self._on_check_changed)
        layout.addWidget(self.checkbox)
        
        # Name
        name_lbl = QLabel(pkg.name)
        name_lbl.setObjectName("PkgName")
        layout.addWidget(name_lbl, 1) # Stretch
        
        # Version
        if pkg.latest_version and pkg.is_outdated:
            ver_text = f"{pkg.version} ➜ {pkg.latest_version}"
            ver_lbl = QLabel(ver_text)
            ver_lbl.setObjectName("PkgVersionUpdate")
        else:
            ver_lbl = QLabel(pkg.version)
            ver_lbl.setObjectName("PkgVersionBase")
        layout.addWidget(ver_lbl)
        
        # Update Button (Only if update available)
        if pkg.is_outdated:
            up_btn = QPushButton("⇧")
            up_btn.setObjectName("PkgUpdateBtn")
            up_btn.setCursor(Qt.PointingHandCursor)
            up_btn.setToolTip(f"Update {pkg.name}")
            up_btn.setObjectName("PkgUpdateBtn")
            up_btn.clicked.connect(lambda: self.update_requested.emit(pkg.name))
            layout.addWidget(up_btn)
        else:
            # Spacer for alignment if no update button
            spacer = QWidget()
            spacer.setObjectName("ActionBtnSpacer")
            layout.addWidget(spacer)

        # Remove Button
        rm_btn = QPushButton("➖")
        rm_btn.setObjectName("ActionBtnRemove")
        rm_btn.setCursor(Qt.PointingHandCursor)
        rm_btn.setToolTip(f"Remove {pkg.name}")
        rm_btn.setObjectName("ActionBtnRemove")
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(pkg.name))
        layout.addWidget(rm_btn)

    def _on_check_changed(self, state):
        self.pkg.is_selected = (state == Qt.Checked.value if hasattr(Qt.Checked, 'value') else state == Qt.Checked or state == 2)
        self.selection_changed.emit(self.pkg.name, self.pkg.is_selected)

    def set_checked(self, checked: bool):
        self.checkbox.setChecked(checked)
