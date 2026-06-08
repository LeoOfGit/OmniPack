import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QIcon

class VersionFetchWorker(QThread):
    versions_ready = Signal(list)

    def __init__(self, runtime_kind: str, parent=None):
        super().__init__(parent)
        self.runtime_kind = runtime_kind

    def run(self):
        import datetime
        try:
            from core.runtime_update import _fetch_runtime_index
            data, err = _fetch_runtime_index(self.runtime_kind, timeout=10)
            if err or not data:
                self.versions_ready.emit([])
                return
                
            valid_cycles = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                
                eol = row.get("eol", False)
                is_eol = False
                if isinstance(eol, str) and eol != "false":
                    try:
                        eol_date = datetime.datetime.strptime(eol, "%Y-%m-%d").date()
                        if eol_date < datetime.datetime.now().date():
                            is_eol = True
                    except Exception:
                        pass
                elif eol is True:
                    is_eol = True
                    
                if is_eol:
                    continue
                    
                latest = str(row.get("latest", "")).strip()
                if latest:
                    lts = row.get("lts", False)
                    is_lts = False
                    if isinstance(lts, str) and lts != "false":
                        try:
                            lts_date = datetime.datetime.strptime(lts, "%Y-%m-%d").date()
                            if lts_date <= datetime.datetime.now().date():
                                is_lts = True
                        except Exception:
                            is_lts = True
                    elif lts is True:
                        is_lts = True
                        
                    valid_cycles.append({
                        "version": latest,
                        "is_lts": is_lts
                    })
                    
            results = []
            for i, info in enumerate(valid_cycles[:3]):
                v = info["version"]
                suffix = []
                if i == 0:
                    suffix.append("Latest")
                if info["is_lts"]:
                    suffix.append("LTS")
                    
                if suffix:
                    results.append(f"{v} ({', '.join(suffix)})")
                else:
                    results.append(v)
                    
            self.versions_ready.emit(results)
        except Exception:
            self.versions_ready.emit([])

class RuntimeSetupWidget(QFrame):
    """
    An elegant widget displayed when a runtime (Python, Node.js, WinGet) is missing,
    offering a quick way to download and install it.
    """
    
    install_requested = Signal(str, str) # runtime_kind, version

    def __init__(self, runtime_kind: str, parent=None):
        super().__init__(parent)
        self.runtime_kind = runtime_kind.lower()
        self.setObjectName("RuntimeSetupWidget")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        
        # Style like a sleek card
        self.setStyleSheet("""
            QFrame#RuntimeSetupWidget {
                background-color: #252526;
                border: 1px solid #3E3E42;
                border-radius: 6px;
            }
            QLabel#TitleLabel {
                font-size: 16px;
                font-weight: bold;
                color: #FFFFFF;
            }
            QLabel#DescLabel {
                font-size: 13px;
                color: #AAAAAA;
            }
            QPushButton#InstallBtn {
                background-color: #007ACC;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton#InstallBtn:hover {
                background-color: #0098FF;
            }
            QPushButton#InstallBtn:disabled {
                background-color: #3E3E42;
                color: #888888;
            }
            QComboBox {
                background-color: #333337;
                color: white;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
        """)
        
        self._build_ui()
        self._populate_versions()
        
    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Header Row
        header_layout = QHBoxLayout()
        header_layout.setSpacing(15)
        
        # Icon (Simulated with emoji for now, or you can use resources if you have them)
        icon_label = QLabel()
        icon_label.setStyleSheet("font-size: 32px;")
        if self.runtime_kind == "python":
            icon_label.setText("🐍")
            title = "Python is missing"
            desc = "Python is required to manage packages via pip. Select a version to download and install."
        elif self.runtime_kind == "node":
            icon_label.setText("🧊")
            title = "Node.js is missing"
            desc = "Node.js is required to manage packages via npm. Select a version to download and install."
        elif self.runtime_kind == "winget":
            icon_label.setText("📦")
            title = "WinGet is missing"
            desc = "WinGet (Windows Package Manager) is missing on this system. Click install to fetch it from GitHub."
        else:
            icon_label.setText("⚙️")
            title = "Runtime missing"
            desc = "Select a version to download and install."
            
        header_layout.addWidget(icon_label)
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        
        title_label = QLabel(title)
        title_label.setObjectName("TitleLabel")
        
        desc_label = QLabel(desc)
        desc_label.setObjectName("DescLabel")
        desc_label.setWordWrap(True)
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(desc_label)
        text_layout.addStretch()
        
        header_layout.addLayout(text_layout)
        header_layout.addStretch()
        
        main_layout.addLayout(header_layout)
        
        # Controls Row
        controls_layout = QHBoxLayout()
        
        self.version_combo = QComboBox()
        if self.runtime_kind == "winget":
            self.version_combo.hide() # WinGet just installs latest
            
        self.install_btn = QPushButton("Download && Install")
        self.install_btn.setObjectName("InstallBtn")
        self.install_btn.setCursor(Qt.PointingHandCursor)
        self.install_btn.clicked.connect(self._on_install_clicked)
        
        version_label = QLabel("Version:")
        if self.runtime_kind == "winget":
            version_label.hide()
            
        controls_layout.addWidget(version_label)
        if self.runtime_kind != "winget":
            controls_layout.addWidget(self.version_combo)
            
            other_link = QLabel()
            other_link.setOpenExternalLinks(True)
            if self.runtime_kind == "python":
                url = "https://www.python.org/downloads/"
            else:
                url = "https://nodejs.org/en/download/"
            other_link.setText(f'<a href="{url}" style="color: #007ACC; text-decoration: none;">Other Version...</a>')
            controls_layout.addWidget(other_link)
            
        controls_layout.addStretch()
        controls_layout.addWidget(self.install_btn)
            
        main_layout.addLayout(controls_layout)
        
    def _populate_versions(self):
        if self.runtime_kind == "winget":
            return
            
        import sys
        if "pytest" in sys.modules:
            self._on_versions_ready([])
            return
            
        self.version_combo.setEnabled(False)
        self.version_combo.addItem("Fetching...")
        
        self._worker = VersionFetchWorker(self.runtime_kind, self)
        self._worker.versions_ready.connect(self._on_versions_ready)
        self._worker.start()
        
    def _on_versions_ready(self, versions: list):
        self.version_combo.clear()
        if not versions:
            if self.runtime_kind == "python":
                self.version_combo.addItems(["3.14.5", "3.13.3", "3.12.3"])
            elif self.runtime_kind == "node":
                self.version_combo.addItems(["26.3.0", "24.16.0 (LTS)", "22.22.3 (LTS)"])
        else:
            self.version_combo.addItems(versions)
            
        self.version_combo.setEnabled(True)
            
    def _on_install_clicked(self):
        version = ""
        if self.runtime_kind != "winget":
            raw_val = self.version_combo.currentText()
            version = raw_val.split()[0] # e.g. "3.12 (Latest)" -> "3.12"
            
        self.install_btn.setEnabled(False)
        self.install_btn.setText("Installing...")
        self.install_requested.emit(self.runtime_kind, version)
        
    def reset_state(self):
        self.install_btn.setEnabled(True)
        self.install_btn.setText("Download && Install")
