"""
NpmAppCard — PySide6 version of AppCard for npm packages.
"""
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QCheckBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from managers.npm_manager import NpmApp


class NpmAppCard(QFrame):
    """
    Compact card for a single npm application.
    [☑] [Name]  [version ➜ latest]  [Channel]  [⚙ ⇧ ✕]
    """
    action_requested = Signal(str, str)   # name, action
    select_toggled = Signal(str, bool)    # name, selected

    def __init__(self, app: NpmApp, channels: dict):
        super().__init__()
        self.app = app
        self.channels = channels  # {name: {label, suffix, color}}
        self.setObjectName("AppCard")
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        # Checkbox
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self.app.is_selected)
        self.checkbox.stateChanged.connect(self._on_toggle)
        layout.addWidget(self.checkbox)

        # Name + Version column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)

        name_text = self.app.display_name or self.app.name
        self.name_lbl = QLabel(name_text)
        self.name_lbl.setObjectName("CardTitle")
        info_layout.addWidget(self.name_lbl)

        # Version line
        ver_text, ver_color = self._format_version()
        self.ver_lbl = QLabel(ver_text)
        self.ver_lbl.setObjectName("CardVersion")
        # Color specific injected inline over base if needed.
        self.ver_lbl.setStyleSheet(f"color: {ver_color};")
        info_layout.addWidget(self.ver_lbl)

        layout.addLayout(info_layout)
        layout.addStretch()

        # Channel tag
        ch_data = self.channels.get(self.app.channel, {})
        ch_label = ch_data.get("label", self.app.channel.capitalize())
        ch_color = ch_data.get("color", "#888") if self.app.channel != "latest" else "#888"

        self.channel_lbl = QLabel(f"[{ch_label}]")
        self.channel_lbl.setObjectName("CardChannel")
        self.channel_lbl.setStyleSheet(f"color: {ch_color};")
        layout.addWidget(self.channel_lbl)

        # Removed base styling string, now in QSS

        # Config
        cfg_btn = QPushButton("⚙")
        cfg_btn.setObjectName("ActionBtnOutline")
        cfg_btn.setToolTip(f"Configure {self.app.name}")
        cfg_btn.clicked.connect(lambda: self.action_requested.emit(self.app.name, "config"))
        layout.addWidget(cfg_btn)

        if self.app.is_installed:
            # Update
            upd_btn = QPushButton("⇧")
            upd_btn.setObjectName("ActionBtnUpdate")
            upd_btn.setToolTip(f"Update {self.app.name}")
            upd_btn.clicked.connect(lambda: self.action_requested.emit(self.app.name, "update"))
            layout.addWidget(upd_btn)

            # Uninstall
            rm_btn = QPushButton("✕")
            rm_btn.setObjectName("ActionBtnRemove")
            rm_btn.setToolTip(f"Uninstall {self.app.name}")
            rm_btn.clicked.connect(lambda: self.action_requested.emit(self.app.name, "uninstall"))
            layout.addWidget(rm_btn)
        else:
            # Install
            inst_btn = QPushButton("⇩")
            inst_btn.setObjectName("ActionBtnInstall")
            inst_btn.setToolTip(f"Install {self.app.name}")
            inst_btn.clicked.connect(lambda: self.action_requested.emit(self.app.name, "install"))
            layout.addWidget(inst_btn)

    def _format_version(self) -> tuple[str, str]:
        """Return (display_text, color_hex)."""
        if not self.app.is_installed:
            return "Not installed", "#666"

        ch_data = self.channels.get(self.app.channel, {})
        ver_text = self.app.version
        ver_color = "#bbb"

        if self.app.channel != "latest":
            ver_color = ch_data.get("color", "#bbb")

        if self.app.latest_version and self.app.latest_version != self.app.version:
            ver_text = f"{self.app.version} ➜ {self.app.latest_version}"
            if self.app.channel != "latest":
                label = ch_data.get("label", self.app.channel)
                ver_text += f" ({label})"
                ver_color = ch_data.get("color", "#4cc9f0")
            else:
                ver_color = "#4cc9f0"

        return ver_text, ver_color

    def _on_toggle(self, state):
        self.app.is_selected = (state == Qt.Checked.value or state == Qt.Checked)
        self.select_toggled.emit(self.app.name, self.app.is_selected)

    def set_selected(self, selected: bool):
        self.app.is_selected = selected
        self.checkbox.setChecked(selected)
