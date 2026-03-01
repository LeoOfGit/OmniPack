"""
NpmAppEditDialog — Dialog for adding or editing an NPM application.
Ported from AppEditDialog in npm_manager.pyw to PySide6.
"""
import re
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QTextEdit, QLineEdit, QPushButton, QGridLayout, QMessageBox,
    QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor

from managers.npm_manager import NpmApp


class NpmAppEditDialog(QDialog):
    """Dialog for adding or editing an application via command line"""

    def __init__(self, app: NpmApp | None, channels: dict, parent=None):
        super().__init__(parent)
        self.app = app
        self.channels = channels
        
        # State
        self.parsed_name = ""
        self.parsed_channel = "latest"
        
        # Results to return
        self.result_app: NpmApp | None = None
        self.is_delete = False

        self._build_ui()
        self._setup_window()
        
        if self.app:
            self._init_from_app()
        else:
            self._update_preview()

    def _setup_window(self):
        title = f"Configure {self.app.name}" if self.app else "Add New App"
        self.setWindowTitle(title)
        self.setMinimumSize(580, 520)
        self.setModal(True)
        self.setStyleSheet("")

    def _build_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Install Command Section ──
        cmd_lbl = QLabel("Install Command:")
        cmd_lbl.setObjectName("DialogLabelBold")
        layout.addWidget(cmd_lbl)

        self.cmd_text = QTextEdit()
        self.cmd_text.setFixedHeight(60)
        self.cmd_text.setFont(QFont("Consolas", 10))
        self.cmd_text.textChanged.connect(self._on_cmd_change)
        layout.addWidget(self.cmd_text)

        # ── Preview Section ──
        preview_frame = QFrame()
        preview_frame.setObjectName("PreviewFrame")
        pv_layout = QVBoxLayout(preview_frame)
        pv_layout.setContentsMargins(8, 8, 8, 8)
        
        self.lbl_name = QLabel("Package: -")
        self.lbl_name.setObjectName("DialogLabelBold")
        pv_layout.addWidget(self.lbl_name)
        
        self.lbl_channel = QLabel("Channel: -")
        pv_layout.addWidget(self.lbl_channel)
        
        self.lbl_status = QLabel("Waiting for command...")
        self.lbl_status.setObjectName("DialogLabelMuted")
        pv_layout.addWidget(self.lbl_status)
        
        layout.addWidget(preview_frame)

        # ── Dynamic Tags Frame ──
        self.tags_frame = QFrame()
        self.tags_layout = QVBoxLayout(self.tags_frame)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tags_frame)

        # ── Metadata Section ──
        meta_layout = QGridLayout()
        meta_layout.setColumnStretch(1, 1)

        meta_layout.addWidget(QLabel("Display:"), 0, 0)
        self.display_entry = QLineEdit()
        meta_layout.addWidget(self.display_entry, 0, 1)

        meta_layout.addWidget(QLabel("Desc:"), 1, 0)
        self.desc_entry = QLineEdit()
        meta_layout.addWidget(self.desc_entry, 1, 1)

        layout.addLayout(meta_layout)
        layout.addStretch()

        # ── Bottom Buttons ──
        btn_layout = QHBoxLayout()
        
        if self.app:
            del_btn = QPushButton("Delete")
            del_btn.setObjectName("ActionBtnRemove")
            del_btn.clicked.connect(self._on_delete)
            btn_layout.addWidget(del_btn)
            
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save & Apply")
        save_btn.setObjectName("ActionBtnBatchUpdate")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _init_from_app(self):
        tag = self.app.channel if self.app.channel != "latest" else "latest"
        cmd = f"npm install -g {self.app.name}@{tag}"
        
        # Disable signals while setting
        self.cmd_text.blockSignals(True)
        self.cmd_text.setPlainText(cmd)
        self.cmd_text.blockSignals(False)
        
        self.display_entry.setText(self.app.display_name)
        self.desc_entry.setText(self.app.description)
        
        self._parse_cmd()
        self._update_preview()

    def _on_cmd_change(self):
        self._parse_cmd()
        self._update_preview()

    def _parse_cmd(self):
        text = self.cmd_text.toPlainText().strip()
        pattern = re.compile(r"(?:npm\s+(?:i|install|un|uninstall|rm|remove)\s+(?:-g\s+)?)(?P<name>@?[\w\-\.\/]+)(?:@(?P<tag>[\w\-\.]+))?", re.IGNORECASE)
        match = pattern.search(text)
        
        if not match:
             pattern_simple = re.compile(r"^(?P<name>@?[\w\-\.\/]+)(?:@(?P<tag>[\w\-\.]+))?$")
             match = pattern_simple.match(text)

        if match:
            self.parsed_name = match.group("name")
            raw_tag = match.group("tag")
            self.parsed_channel = raw_tag if raw_tag else "latest"
        else:
             self.parsed_name = ""
             self.parsed_channel = "latest"

    def _update_preview(self):
        if self.parsed_name:
            self.lbl_name.setText(f"Package: {self.parsed_name}")
            ch_obj = self.channels.get(self.parsed_channel)
            ch_label = ch_obj.get("label", self.parsed_channel) if ch_obj else self.parsed_channel
            ch_color = ch_obj.get("color", "gray") if ch_obj else "gray"
            
            self.lbl_channel.setText(f"Channel: {ch_label}")
            self.lbl_channel.setStyleSheet(f"color: {ch_color}; font-weight: bold;")
            
            self.lbl_status.setText("✓ Valid Install & Update Command")
            self.lbl_status.setObjectName("DialogLabelSuccess")
            
            if not self.display_entry.text():
                self.display_entry.setText(self.parsed_name)
                
            self._update_tags_display()
        else:
            self.lbl_name.setText("Package: -")
            self.lbl_channel.setText("Channel: -")
            self.lbl_channel.setStyleSheet("")
            self.lbl_status.setText("Waiting for command...")
            self.lbl_status.setObjectName("DialogLabelMuted")
            self._clear_tags_display()

    def _clear_tags_display(self):
        """Recursively clear all widgets and layouts from tags_layout."""
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout):
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    self._clear_layout(item.layout())

    def _update_tags_display(self):
        self._clear_tags_display()
        
        if not self.app or self.app.name != self.parsed_name:
            return

        if not self.app.channels_available:
            lbl = QLabel("No channel info (run Refresh first)")
            lbl.setObjectName("DialogLabelMuted")
            self.tags_layout.addWidget(lbl)
            return

        lbl = QLabel("Select Channel to Install/Update:")
        lbl.setObjectName("DialogLabelBold")
        self.tags_layout.addWidget(lbl)
        
        grid = QGridLayout()
        grid.setSpacing(12)  # Increased spacing to prevent overlap
        grid.setVerticalSpacing(16) # Explicit vertical spacing
        self.tags_layout.addLayout(grid)
        
        col, row = 0, 0
        for ch in self.app.channels_available:
            label = ch
            if ch == "latest":
                label = "Latest"
            
            version = self.app.channel_versions.get(ch, "")
            latest_ver = self.app.channel_versions.get("latest", "")
            match_suffix = ""
            if ch != "latest" and version and version == latest_ver:
                match_suffix = " (Same as Latest)"

            btn_text = f"{label}{match_suffix}\n{version}" if version else label
            
            btn = QPushButton(btn_text)
            btn.setObjectName("ChannelTag")
            btn.setMinimumSize(160, 46)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            installed_ch = self.app.channel if self.app else None
            target_ch = self.parsed_channel

            # Determine state property for QSS
            state = "normal"
            if installed_ch == target_ch == ch:
                state = "both"
            elif ch == installed_ch:
                state = "installed"
            elif ch == target_ch:
                state = "target"
            
            btn.setProperty("state", state)
            
            btn.clicked.connect(lambda checked=False, c=ch: self._apply_tag(c))
            
            grid.addWidget(btn, row, col)
            col += 1
            if col > 2:
                col = 0
                row += 1

    def _apply_tag(self, channel: str):
        if not self.parsed_name:
            return
        new_cmd = f"npm install -g {self.parsed_name}@{channel}"
        self.cmd_text.setPlainText(new_cmd)

    def _on_save(self):
        if not self.parsed_name:
            return
            
        current_avail = self.app.channels_available[:] if self.app else []
        if "latest" not in current_avail:
            current_avail.insert(0, "latest")
        if self.parsed_channel not in current_avail:
            current_avail.append(self.parsed_channel)
            
        self.result_app = NpmApp(
            name=self.parsed_name,
            display_name=self.display_entry.text().strip() or self.parsed_name,
            description=self.desc_entry.text().strip(),
            channel=self.parsed_channel,
            channels_available=current_avail,
        )
        self.accept()

    def _on_delete(self):
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Remove configuration for {self.app.name}?\n(This does not uninstall the package)",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.is_delete = True
            self.accept()
