import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QFileDialog, QMessageBox, QInputDialog,
    QDialogButtonBox
)
from PySide6.QtCore import Qt, Signal

from core.config import ConfigManager

class SettingsDialog(QDialog):
    """Dialog for managing pip environments"""

    environments_changed = Signal()

    def __init__(self, config_mgr: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.setWindowTitle("Manage Environments")
        self.resize(500, 400)
        self._changed = False

        self._create_ui()
        self._load_envs()

    def _create_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        lbl = QLabel("Python Environments:")
        layout.addWidget(lbl)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        add_sys_btn = QPushButton("Add System Env")
        add_sys_btn.clicked.connect(self._add_system_env)
        btn_layout.addWidget(add_sys_btn)

        add_venv_btn = QPushButton("Add Virtual Env")
        add_venv_btn.clicked.connect(self._add_venv)
        btn_layout.addWidget(add_venv_btn)

        edit_btn = QPushButton("Edit Selected")
        edit_btn.clicked.connect(self._edit_env)
        btn_layout.addWidget(edit_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_env)
        btn_layout.addWidget(remove_btn)

        layout.addLayout(btn_layout)
        
        # Double click to edit
        self.list_widget.itemDoubleClicked.connect(self._edit_env)

        # Dialog Box Standard Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_accept(self):
        if self._changed:
            self.environments_changed.emit()
            self._changed = False
        self.accept()

    def _load_envs(self):
        self.list_widget.clear()
        for env in self.config_mgr.config.pip_environments:
            label = f"{env['name']} ({env['path']})"
            self.list_widget.addItem(label)
            # Store path in UserRole
            item = self.list_widget.item(self.list_widget.count() - 1)
            item.setData(Qt.UserRole, env["path"])

    def _add_system_env(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select python.exe", "", "Python Executable (python.exe);;All Files (*)"
        )
        if not path:
            return
        
        path = os.path.normpath(path) # Use backslashes on Windows
        
        # Ask for label
        default_name = f"Python {os.path.basename(os.path.dirname(path))}" if "Python" in path else "System Python"
        text, ok = QInputDialog.getText(self, "Environment Name", "Enter a name for this environment:", text=default_name)
        if ok and text:
            self.config_mgr.add_pip_env(path=path, name=text, env_type="system")
            self._changed = True
            self._load_envs()

    def _add_venv(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select virtual environment root directory")
        if not dir_path:
            return
        
        dir_path = os.path.normpath(dir_path) # Use backslashes on Windows
        
        # Determine python exe
        # Windows venv/Scripts/python.exe, Linux/macOS venv/bin/python
        py_path = os.path.join(dir_path, "Scripts", "python.exe")
        if not os.path.exists(py_path):
            py_path = os.path.join(dir_path, "bin", "python")
        
        py_path = os.path.normpath(py_path)

        if not os.path.exists(py_path):
            QMessageBox.warning(self, "Invalid Directory", f"Could not find python executable in:\n{dir_path}\nMake sure to select the root folder of the virtual environment.")
            return

        name = os.path.basename(dir_path)
        if name.lower() in [".venv", "venv"]:
            # Use parent directory name
            name = os.path.basename(os.path.dirname(dir_path)) or name

        text, ok = QInputDialog.getText(self, "Environment Name", "Enter a name for this virtual environment:", text=name)
        if ok and text:
            self.config_mgr.add_pip_env(path=py_path, name=text, env_type="venv")
            self._changed = True
            self._load_envs()

    def _remove_env(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        path = item.data(Qt.UserRole)
        self.config_mgr.remove_pip_env(path)
        self._changed = True
        self._load_envs()

    def _edit_env(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        
        old_path = item.data(Qt.UserRole)
        # Find environment in config
        env_index = -1
        for i, env in enumerate(self.config_mgr.config.pip_environments):
            if env["path"] == old_path:
                env_index = i
                break
        
        if env_index == -1:
            return
            
        current_env = self.config_mgr.config.pip_environments[env_index]
        
        # 1. Ask for name
        new_name, ok = QInputDialog.getText(
            self, "Edit Environment", "Environment Name:", 
            text=current_env["name"]
        )
        if not ok or not new_name:
            return
            
        # 2. Ask if they want to change path
        change_path = QMessageBox.question(
            self, "Change Path", 
            f"Current path:\n{current_env['path']}\n\nDo you want to change the path?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        new_path = current_env["path"]
        if change_path == QMessageBox.Yes:
            if current_env["type"] == "system":
                p, _ = QFileDialog.getOpenFileName(
                    self, "Select python.exe", current_env["path"], "Python Executable (python.exe);;All Files (*)"
                )
                if p: new_path = os.path.normpath(p)
            else:
                p = QFileDialog.getExistingDirectory(self, "Select virtual environment root", current_env["path"])
                if p:
                    p = os.path.normpath(p)
                    # Find python
                    py_path = os.path.join(p, "Scripts", "python.exe")
                    if not os.path.exists(py_path):
                        py_path = os.path.join(p, "bin", "python")
                    new_path = os.path.normpath(py_path)
                    
                    if not os.path.exists(new_path):
                        QMessageBox.warning(self, "Invalid Directory", "Could not find python executable in select directory.")
                        return

        # Update config directly
        current_env["name"] = new_name
        current_env["path"] = new_path
        self.config_mgr.save_config()
        
        self._changed = True
        self._load_envs()

    def closeEvent(self, event):
        if self._changed:
            self.environments_changed.emit()
        super().closeEvent(event)
