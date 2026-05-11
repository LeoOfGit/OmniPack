import os
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QFileDialog, QMessageBox, QInputDialog, QDialogButtonBox, QWidget,
    QTabWidget, QGroupBox, QLineEdit, QButtonGroup, QAbstractItemView, QCheckBox, QPlainTextEdit,
    QTextEdit, QSizePolicy, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer

from core.config import ConfigManager
from core.network_proxy import normalize_proxy_settings
from core.pypi_cache import (
    get_cache_status,
    cache_file_path,
    start_refresh_task,
    cancel_refresh_task,
    get_refresh_state,
    resolve_refresh_source,
)
from version import __version__
from core.env_detector import resolve_python_env, generate_smart_env_name, resolve_npm_env, describe_npm_env
from core.source_profiles import (
    PYPI_OFFICIAL_INDEX,
    NPM_OFFICIAL_REGISTRY,
    COMMON_PIP_MIRRORS,
    COMMON_NPM_REGISTRIES,
    detect_system_pip_index_url,
    detect_system_npm_registry_url,
)


class SettingsDialog(QDialog):
    """Unified settings dialog for environments and source mirrors."""

    settings_changed = Signal()

    def __init__(self, config_mgr: ConfigManager, initial_tab: str = "pip", parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self._changed = False
        self._initial_tab = initial_tab

        self._pip_system_url = ""
        self._npm_system_url = ""
        self._pip_custom_url = ""
        self._npm_custom_url = ""
        self._pypi_cache_log_cursor = 0
        self._pypi_progress_timer = QTimer(self)
        self._pypi_progress_timer.setInterval(500)
        self._pypi_progress_timer.timeout.connect(self._on_pypi_progress_tick)

        self.setWindowTitle("Settings")
        self.resize(640, 480)

        self._create_ui()
        self._load_envs("pip")
        self._load_envs("npm")
        self._load_source_settings()
        self._load_proxy_settings()
        self._load_pypi_cache_settings()
        self._set_initial_tab()

    def _create_ui(self):
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_env_tab("pip"), "Python Environments")
        self.tabs.addTab(self._build_env_tab("npm"), "NPM Environments")
        self.tabs.addTab(self._build_sources_tab(), "Sources")
        self.tabs.addTab(self._build_backend_tab(), "Backend")
        self.tabs.addTab(self._build_proxy_tab(), "Proxy")
        layout.addWidget(self.tabs)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _build_env_tab(self, kind: str):
        """Unified builder for Pip and NPM environment management tabs."""
        page = QWidget()
        layout = QVBoxLayout(page)

        is_pip = (kind == "pip")
        title = "Python Environments" if is_pip else "NPM Environments"
        layout.addWidget(QLabel(f"{title} (Drag items to reorder):"))

        list_w = QListWidget()
        list_w.setDragDropMode(QAbstractItemView.InternalMove)
        
        if is_pip:
            self.pip_list = list_w
        else:
            self.npm_list = list_w
            
        list_w.model().rowsMoved.connect(lambda *a, k=kind: self._sync_order(k))
        list_w.itemDoubleClicked.connect(lambda _i, k=kind: self._edit_env(k))
        # list_w.setMinimumHeight(80)
        layout.addWidget(list_w)

        # Row 1: The "Input" actions (Auto / Manual / Batch)
        row1 = QHBoxLayout()
        btn1 = QPushButton("Detect System")
        btn1.clicked.connect(self._on_auto_add_clicked if is_pip else self._add_global_env)
        row1.addWidget(btn1)

        btn2 = QPushButton("Add Manually...")
        btn2.clicked.connect(lambda _checked=False, k=kind: self._add_specific(k))
        row1.addWidget(btn2)

        btn3 = QPushButton("Batch Paste...")
        btn3.clicked.connect(lambda _checked=False, k=kind: self._batch_add(k))
        row1.addWidget(btn3)
        layout.addLayout(row1)

        # Row 2: The "Edit/Remove" actions
        row2 = QHBoxLayout()
        edit_btn = QPushButton("Edit Selected")
        edit_btn.clicked.connect(lambda _checked=False, k=kind: self._edit_env(k))
        row2.addWidget(edit_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(lambda _checked=False, k=kind: self._remove_env(k))
        row2.addWidget(remove_btn)
        layout.addLayout(row2)

        return page

    def _set_initial_tab(self):
        tab_map = {"pip": 0, "npm": 1, "sources": 2, "backend": 3, "proxy": 4}
        self.tabs.setCurrentIndex(tab_map.get(self._initial_tab, 0))

    @staticmethod
    def _norm_key(path: str) -> str:
        return os.path.normcase(os.path.normpath(str(path)))

    def _pick_existing_directory(self, title: str, start_dir: str = "") -> str:
        options = QFileDialog.Option.ShowDirsOnly
        return QFileDialog.getExistingDirectory(self, title, start_dir, options)

    def _pick_open_file(self, title: str, file_filter: str, start_dir: str = "") -> str:
        path, _ = QFileDialog.getOpenFileName(self, title, start_dir, file_filter)
        return path

    def _add_path_direct(self, kind: str):
        label = "Python environment" if kind == "pip" else "NPM project"
        text, ok = QInputDialog.getText(
            self,
            f"Add {label} by Path",
            "Enter full path (supports mapped drive like S:\\ and UNC path like \\\\server\\share\\...):",
        )
        if not ok:
            return
        path = text.strip().strip('"').strip("'")
        if path:
            self._process_path(kind, path)

    def _add_specific(self, kind: str):
        """Unified 'Add Manually' logic."""
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        if kind == "pip":
            menu.addAction("📁 From Directory (Project/Venv)...", self._add_pip_folder)
            menu.addAction("📄 From Executable (python.exe)...", self._add_pip_file)
            menu.addAction("⌨️ Enter Path...", lambda: self._add_path_direct("pip"))
        else:
            menu.addAction("📁 From Directory (Project root)...", self._add_npm_folder)
            menu.addAction("📄 From File (package.json)...", self._add_npm_file)
            menu.addAction("⌨️ Enter Path...", lambda: self._add_path_direct("npm"))

        btn = self.sender()
        if btn:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            menu.exec(self.cursor().pos())

    def _get_env_map(self, kind: str):
        """Metadata map to drive generic logic."""
        if kind == "pip":
            return {
                "list": self.pip_list,
                "config_list": self.config_mgr.config.pip_environments,
                "add_fn": self.config_mgr.add_pip_env,
                "remove_fn": self.config_mgr.remove_pip_env,
                "resolve_fn": resolve_python_env,
                "name": "Python Environment",
                "label_fn": lambda e: f"{e['name']} ({e['path']})",
                "set_cfg_fn": lambda val: setattr(self.config_mgr.config, "pip_environments", val)
            }
        else:
            return {
                "list": self.npm_list,
                "config_list": self.config_mgr.config.npm_environments,
                "add_fn": self.config_mgr.add_npm_env,
                "remove_fn": self.config_mgr.remove_npm_env,
                "resolve_fn": resolve_npm_env,
                "name": "NPM Project",
                "label_fn": lambda e: f"[{str(e.get('type', 'unknown')).replace('_', ' ').title()}] {e['name']} ({e['path']})",
                "set_cfg_fn": lambda val: setattr(self.config_mgr.config, "npm_environments", val)
            }

    def _load_envs(self, kind: str):
        m = self._get_env_map(kind)
        m["list"].clear()
        for env in m["config_list"]:
            m["list"].addItem(m["label_fn"](env))
            m["list"].item(m["list"].count() - 1).setData(Qt.UserRole, env["path"])

    def _remove_env(self, kind: str):
        m = self._get_env_map(kind)
        item = m["list"].currentItem()
        if not item: return
        m["remove_fn"](item.data(Qt.UserRole))
        self._changed = True
        self._load_envs(kind)

    def _sync_order(self, kind: str):
        m = self._get_env_map(kind)
        new_envs = []
        for i in range(m["list"].count()):
            path = m["list"].item(i).data(Qt.UserRole)
            for env in m["config_list"]:
                if self._norm_key(env.get("path", "")) == self._norm_key(path):
                    new_envs.append(env)
                    break
        m["set_cfg_fn"](new_envs)
        self.config_mgr.save_config()
        self._changed = True

    def _batch_add(self, kind: str):
        m = self._get_env_map(kind)
        text, ok = QInputDialog.getMultiLineText(self, f"Batch Add {m['name']}s", 
            f"Paste multiple paths from Explorer/Everything:\nOne path per line.")
        if not ok or not text.strip(): return
        
        existing_keys = {self._norm_key(e.get("path", "")) for e in m["config_list"]}
        added_count = 0
        for line in text.strip().splitlines():
            path_str = line.strip().strip('"').strip("'")
            if path_str and self._process_path(kind, path_str, silent=True, save=False, reload=False, existing_keys=existing_keys):
                added_count += 1
        
        if added_count > 0:
            self.config_mgr.save_config()
            self._load_envs(kind)
            QMessageBox.information(self, "Success", f"Imported {added_count} new {m['name']}s!")
        else:
            QMessageBox.warning(self, "No Valid Paths", "Could not detect any new valid paths.")

    def _process_path(self, kind: str, input_path: str, silent=False, save=True, reload=True, existing_keys=None) -> bool:
        m = self._get_env_map(kind)
        res_val, res_type = m["resolve_fn"](input_path)
        if not res_val:
            if not silent: QMessageBox.warning(self, "Invalid Path", f"Could not detect valid {m['name']} in:\n{input_path}")
            return False
             
        res_val = os.path.normpath(res_val)
        norm_key = self._norm_key(res_val)
        if existing_keys is None:
            existing_keys = {self._norm_key(e.get("path", "")) for e in m["config_list"]}

        if norm_key in existing_keys:
            if not silent: QMessageBox.information(self, "Info", "Already added.")
            return False
            
        if kind == "pip":
            env_type = res_type
            smart_name = generate_smart_env_name(res_val, env_type)
        else:
            env_type, smart_name = describe_npm_env(res_val, res_type or "")
        if not silent:
            text, ok = QInputDialog.getText(self, "Name", "Confirm name:", text=smart_name)
            if not ok or not text: return False
            smart_name = text
            
        m["add_fn"](path=res_val, name=smart_name, env_type=env_type, save=save)
        existing_keys.add(norm_key)
        self._changed = True
        if reload: self._load_envs(kind)
        return True

    def _edit_env(self, kind: str):
        m = self._get_env_map(kind)
        item = m["list"].currentItem()
        if not item: return

        old_path = item.data(Qt.UserRole)
        env_index = next((i for i, e in enumerate(m["config_list"]) if e["path"] == old_path), -1)
        if env_index == -1: return

        current_env = m["config_list"][env_index]
        new_name, ok = QInputDialog.getText(self, "Edit", "Name:", text=current_env["name"])
        if not ok or not new_name: return

        if QMessageBox.question(self, "Change Path", f"Current:\n{current_env['path']}\n\nChange path?", 
                                QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
            p = self._pick_existing_directory("Select Folder", os.path.dirname(current_env["path"]))
            if p:
                res_val, res_type = m["resolve_fn"](p)
                if res_val:
                    current_env["path"] = os.path.normpath(res_val)
                    current_env["type"] = res_type
                else:
                    QMessageBox.warning(self, "Invalid", "Invalid directory.")
                    return

        current_env["name"] = new_name
        self.config_mgr.save_config()
        self._changed = True
        self._load_envs(kind)

    # ---------- Unified logic ----------

    def _on_auto_add_clicked(self):
        """Perform a real background scan for system Python environments."""
        import sys
        found_paths = set()
        
        try:
            # 1. Current running python
            if sys.executable:
                found_paths.add(sys.executable)
            
            # 2. PATH environments
            path_env = os.environ.get("PATH", "")
            for part in path_env.split(os.pathsep):
                if not part or "windowsapps" in part.lower(): 
                    continue
                try:
                    p = Path(part)
                    if p.exists() and p.is_dir():
                        # Check for python.exe or python
                        for name in ["python.exe", "python3.exe", "python", "python3"]:
                            target = p / name
                            if target.is_file():
                                found_paths.add(str(target))
                except (OSError, PermissionError):
                    continue

            # 3. Common Windows install locations
            if os.name == "nt":
                programs = [os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")]
                for base in filter(None, programs):
                    try:
                        base_p = Path(base)
                        # Check directly in Local/Programs/Python
                        python_root = base_p / "Programs" / "Python"
                        if python_root.exists() and python_root.is_dir():
                            for folder in python_root.iterdir():
                                try:
                                    if folder.is_dir() and folder.name.lower().startswith("python"):
                                        exe = folder / "python.exe"
                                        if exe.is_file():
                                            found_paths.add(str(exe))
                                except (OSError, PermissionError):
                                    continue
                    except (OSError, PermissionError):
                        continue

            added_count = 0
            existing_count = 0
            total_scanned = len(found_paths)
            existing_set = {self._norm_key(e["path"]) for e in self.config_mgr.config.pip_environments}
            
            for p in found_paths:
                if self._norm_key(p) in existing_set:
                    existing_count += 1
                else:
                    if self._process_path("pip", p, silent=True, save=False, reload=False, existing_keys=existing_set):
                        added_count += 1
            
            # Comprehensive Feedback
            if added_count > 0:
                self.config_mgr.save_config()
                self._load_envs("pip")
                QMessageBox.information(self, "Auto Detect", 
                    f"Scan Complete!\n\n"
                    f"- Scanned locations: {total_scanned}\n"
                    f"- Already in list: {existing_count}\n"
                    f"- Newly Added: {added_count}\n\n"
                    "Your environment list has been updated.")
            else:
                QMessageBox.information(self, "Auto Detect", 
                    f"Scan Complete.\n\n"
                    f"- Scanned locations: {total_scanned}\n"
                    f"- Already in list: {existing_count}\n"
                    f"- New found: 0\n\n"
                    "No new Python environments were found in standard system locations.")
        except Exception as e:
            QMessageBox.critical(self, "Scanner Error", f"A fatal error occurred during scanning:\n{str(e)}")

    def _add_pip_folder(self):
        p = self._pick_existing_directory("Select Folder")
        if p: self._process_path("pip", p)

    def _add_pip_file(self):
        p = self._pick_open_file("Select Python", "Python (*.exe python*);;All (*)")
        if p: self._process_path("pip", p)

    def _add_npm_folder(self):
        p = self._pick_existing_directory("Select NPM Root")
        if p: self._process_path("npm", p)

    def _add_npm_file(self):
        path = self._pick_open_file("Select NPM Package Metadata", "NPM Entry (package.json);;All Files (*)")
        if path:
            self._process_path("npm", path)

    def _add_global_env(self):
        path = "global"
        if any(e.get("path") == path for e in self.config_mgr.config.npm_environments):
            QMessageBox.information(self, "Info", "Already exists.")
            return
        self.config_mgr.add_npm_env(path=path, name="Global Packages", env_type="global")
        self._changed = True
        self._load_envs("npm")

    # ---------- Sources tab ----------

    def _build_sources_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        page = QWidget()
        scroll.setWidget(page)
        
        layout = QVBoxLayout(page)

        hint = QLabel("Source settings affect pip/uv/npm commands and PyPI cache refresh source selection.")
        hint.setObjectName("SettingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        pip_group = QGroupBox("Python (uv/pip)")
        pip_layout = QVBoxLayout(pip_group)
        pip_layout.addWidget(QLabel("Source mode (one-click):"))
        pip_modes = [
            ("system", "Follow System"),
            ("official", "Official PyPI"),
            ("custom", "Custom Mirror"),
        ]
        pip_cards, self.pip_source_mode_group, self.pip_source_mode_buttons = self._create_mode_cards(pip_modes)
        pip_layout.addWidget(pip_cards)
        pip_layout.addWidget(QLabel("Index URL:"))
        self.pip_index_url = QLineEdit()
        self.pip_index_url.textChanged.connect(self._on_pip_url_edited)
        pip_layout.addWidget(self.pip_index_url)
        pip_layout.addWidget(self._build_preset_row(COMMON_PIP_MIRRORS, "pip"))
        layout.addWidget(pip_group)

        npm_group = QGroupBox("Node.js (npm)")
        npm_layout = QVBoxLayout(npm_group)
        npm_layout.addWidget(QLabel("Source mode (one-click):"))
        npm_modes = [
            ("system", "Follow System"),
            ("official", "Official Registry"),
            ("custom", "Custom Registry"),
        ]
        npm_cards, self.npm_source_mode_group, self.npm_source_mode_buttons = self._create_mode_cards(npm_modes)
        npm_layout.addWidget(npm_cards)
        npm_layout.addWidget(QLabel("Registry URL:"))
        self.npm_registry_url = QLineEdit()
        self.npm_registry_url.textChanged.connect(self._on_npm_url_edited)
        npm_layout.addWidget(self.npm_registry_url)
        npm_layout.addWidget(self._build_preset_row(COMMON_NPM_REGISTRIES, "npm"))
        layout.addWidget(npm_group)

        layout.addStretch()
        return scroll

    def _build_backend_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        page = QWidget()
        scroll.setWidget(page)
        
        layout = QVBoxLayout(page)

        hint = QLabel("Backend behavior for OmniPack internals (engine and local PyPI search cache).")
        hint.setObjectName("SettingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        engine_group = QGroupBox("Internal Engine (uv)")
        engine_layout = QVBoxLayout(engine_group)
        engine_layout.addWidget(QLabel("Custom uv path (leave blank to auto-detect from bundled/system):"))

        uv_row = QHBoxLayout()
        self.uv_path_edit = QLineEdit()
        self.uv_path_edit.setPlaceholderText("e.g. C:\\tools\\uv.exe")
        self.uv_path_edit.textChanged.connect(self._on_uv_path_edited)
        uv_row.addWidget(self.uv_path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_uv_path)
        uv_row.addWidget(browse_btn)
        engine_layout.addLayout(uv_row)

        update_btn = QPushButton("Check for Update / Self Update (uv)")
        update_btn.clicked.connect(self._update_uv_engine)
        engine_layout.addWidget(update_btn)

        self.uv_version_label = QLabel("Testing engine...")
        self.uv_version_label.setWordWrap(True)
        self.uv_version_label.setStyleSheet("color: gray; font-size: 11px; font-style: italic;")
        engine_layout.addWidget(self.uv_version_label)
        layout.addWidget(engine_group)

        cache_group = QGroupBox("PyPI Search Cache")
        cache_layout = QVBoxLayout(cache_group)
        cache_hint = QLabel("Python package search uses this local cache only.")
        cache_hint.setWordWrap(True)
        cache_layout.addWidget(cache_hint)

        self.pypi_cache_status_label = QLabel("Loading cache status...")
        self.pypi_cache_status_label.setWordWrap(True)
        self.pypi_cache_status_label.setStyleSheet("color: gray;")
        cache_layout.addWidget(self.pypi_cache_status_label)

        cache_btn_row = QHBoxLayout()
        self.pypi_cache_refresh_btn = QPushButton("Update Cache")
        self.pypi_cache_refresh_btn.clicked.connect(self._on_refresh_pypi_cache_clicked)
        cache_btn_row.addWidget(self.pypi_cache_refresh_btn)
        self.pypi_cache_open_btn = QPushButton("Open Cache Folder")
        self.pypi_cache_open_btn.clicked.connect(self._open_pypi_cache_folder)
        cache_btn_row.addWidget(self.pypi_cache_open_btn)
        cache_btn_row.addStretch()
        cache_layout.addLayout(cache_btn_row)

        self.pypi_cache_auto_refresh_check = QCheckBox("Auto refresh in background on startup")
        self.pypi_cache_auto_refresh_check.toggled.connect(lambda _checked=False: self._on_pypi_cache_settings_changed())
        cache_layout.addWidget(self.pypi_cache_auto_refresh_check)

        self.pypi_cache_log = QPlainTextEdit()
        self.pypi_cache_log.setReadOnly(True)
        self.pypi_cache_log.setPlaceholderText("Cache update progress will appear here.")
        cache_layout.addWidget(self.pypi_cache_log, 1)
        layout.addWidget(cache_group, 1)
        return scroll

    def _create_mode_cards(self, modes):
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        group = QButtonGroup(container)
        group.setExclusive(True)
        buttons = {}

        for mode, title in modes:
            btn = QPushButton(title)
            btn.setObjectName("SourceModeCard")
            btn.setProperty("mode", mode)
            btn.setCheckable(True)
            btn.clicked.connect(self._on_source_mode_changed)
            group.addButton(btn)
            buttons[mode] = btn
            row.addWidget(btn)

        return container, group, buttons

    def _build_preset_row(self, profiles, source_kind: str):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(QLabel("Quick fill:"))
        for name, url in profiles:
            btn = QPushButton(name)
            btn.setObjectName("SourcePresetBtn")
            btn.clicked.connect(lambda _checked=False, k=source_kind, u=url: self._on_quick_fill(k, u))
            row.addWidget(btn)
        row.addStretch()
        return row_widget

    def _on_accept(self):
        self._save_source_settings()
        self._save_proxy_settings()
        self._save_pypi_cache_settings()
        if self._changed:
            self.settings_changed.emit()
            self._changed = False
        self.accept()

    # ---------- Specialized Helpers ----------

    def _show_selectable_message(self, title, msg, icon=QMessageBox.Information):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(msg)
        box.setIcon(icon)
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.exec()

    def _build_proxy_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        page = QWidget()
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        hint = QLabel("Proxy applies to cache refresh, internal requests, and optional pip/npm commands.")
        hint.setObjectName("SettingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        proxy_group = QGroupBox("Proxy Connection")
        proxy_layout = QVBoxLayout(proxy_group)

        self.proxy_enabled_check = QCheckBox("Enable proxy")
        self.proxy_enabled_check.toggled.connect(self._on_proxy_fields_changed)
        proxy_layout.addWidget(self.proxy_enabled_check)

        http_row = QHBoxLayout()
        http_row.addWidget(QLabel("HTTP:"))
        self.proxy_http_edit = QLineEdit()
        self.proxy_http_edit.setPlaceholderText("e.g. http://127.0.0.1:3128")
        self.proxy_http_edit.textChanged.connect(self._on_proxy_fields_changed)
        http_row.addWidget(self.proxy_http_edit)
        proxy_layout.addLayout(http_row)

        https_row = QHBoxLayout()
        https_row.addWidget(QLabel("HTTPS:"))
        self.proxy_https_edit = QLineEdit()
        self.proxy_https_edit.setPlaceholderText("e.g. http://127.0.0.1:3128")
        self.proxy_https_edit.textChanged.connect(self._on_proxy_fields_changed)
        https_row.addWidget(self.proxy_https_edit)
        proxy_layout.addLayout(https_row)

        layout.addWidget(proxy_group)

        target_group = QGroupBox("Apply Proxy To")
        target_layout = QVBoxLayout(target_group)

        self.proxy_target_pypi = QCheckBox("PyPI cache update requests (pypi.org / files.pythonhosted.org)")
        self.proxy_target_pypi.toggled.connect(self._on_proxy_fields_changed)
        target_layout.addWidget(self.proxy_target_pypi)

        self.proxy_target_npm = QCheckBox("NPM domains (registry.npmjs.org)")
        self.proxy_target_npm.toggled.connect(self._on_proxy_fields_changed)
        target_layout.addWidget(self.proxy_target_npm)

        self.proxy_target_pip_cmd = QCheckBox("pip / uv commands (install, update, etc.)")
        self.proxy_target_pip_cmd.toggled.connect(self._on_proxy_fields_changed)
        target_layout.addWidget(self.proxy_target_pip_cmd)

        self.proxy_target_github = QCheckBox("GitHub API (uv update check)")
        self.proxy_target_github.toggled.connect(self._on_proxy_fields_changed)
        target_layout.addWidget(self.proxy_target_github)

        self.proxy_target_winget = QCheckBox("winget command (Node.js/Python runtime update check)")
        self.proxy_target_winget.toggled.connect(self._on_proxy_fields_changed)
        target_layout.addWidget(self.proxy_target_winget)

        layout.addWidget(target_group)

        test_group = QGroupBox("Connectivity Test")
        test_layout = QVBoxLayout(test_group)
        test_hint = QLabel("Compare direct vs proxy latency. Expand details only when needed.")
        test_hint.setWordWrap(True)
        test_layout.addWidget(test_hint)

        test_btn_row = QHBoxLayout()
        self.proxy_test_btn = QPushButton("Test Direct vs Proxy")
        self.proxy_test_btn.clicked.connect(self._on_test_proxy_connections_clicked)
        test_btn_row.addWidget(self.proxy_test_btn)
        self.proxy_test_toggle_btn = QPushButton("Show Details")
        self.proxy_test_toggle_btn.clicked.connect(self._toggle_proxy_test_output)
        test_btn_row.addWidget(self.proxy_test_toggle_btn)
        test_btn_row.addStretch()
        test_layout.addLayout(test_btn_row)

        self.proxy_test_output = QTextEdit()
        self.proxy_test_output.setReadOnly(True)
        self.proxy_test_output.setPlaceholderText("Click the button to test connectivity.")
        self.proxy_test_output.setVisible(False)
        test_layout.addWidget(self.proxy_test_output, 1)

        layout.addWidget(test_group, 1) # Give stretch factor of 1 to the test group
        return scroll

    def _load_source_settings(self):
        pip_settings = getattr(self.config_mgr.config, "pip_settings", {}) or {}
        npm_settings = getattr(self.config_mgr.config, "npm_settings", {}) or {}

        self.uv_path_edit.blockSignals(True)
        self.uv_path_edit.setText(str(pip_settings.get("uv_path", "")).strip())
        self.uv_path_edit.blockSignals(False)
        self._check_uv_version()

        self._pip_custom_url = str(pip_settings.get("index_url", "")).strip()
        self._npm_custom_url = str(npm_settings.get("registry_url", "")).strip()
        self._pip_system_url = detect_system_pip_index_url()
        self._npm_system_url = detect_system_npm_registry_url()

        self._set_mode_value(self.pip_source_mode_buttons, str(pip_settings.get("source_mode", "system")))
        self._set_mode_value(self.npm_source_mode_buttons, str(npm_settings.get("source_mode", "system")))
        self._apply_source_ui()

    def _load_proxy_settings(self):
        settings = normalize_proxy_settings(getattr(self.config_mgr.config, "proxy_settings", {}) or {})
        targets = settings.get("targets", {})

        self.proxy_enabled_check.blockSignals(True)
        self.proxy_http_edit.blockSignals(True)
        self.proxy_https_edit.blockSignals(True)
        self.proxy_target_pypi.blockSignals(True)
        self.proxy_target_npm.blockSignals(True)
        self.proxy_target_pip_cmd.blockSignals(True)
        self.proxy_target_github.blockSignals(True)
        self.proxy_target_winget.blockSignals(True)

        self.proxy_enabled_check.setChecked(bool(settings.get("enabled", False)))
        self.proxy_http_edit.setText(str(settings.get("http_proxy", "")))
        self.proxy_https_edit.setText(str(settings.get("https_proxy", "")))
        self.proxy_target_pypi.setChecked(bool(targets.get("pypi", False)))
        self.proxy_target_npm.setChecked(bool(targets.get("npm", False)))
        self.proxy_target_pip_cmd.setChecked(bool(targets.get("pip", False)))
        self.proxy_target_github.setChecked(bool(targets.get("github", False)))
        self.proxy_target_winget.setChecked(bool(targets.get("winget", False)))

        self.proxy_enabled_check.blockSignals(False)
        self.proxy_http_edit.blockSignals(False)
        self.proxy_https_edit.blockSignals(False)
        self.proxy_target_pypi.blockSignals(False)
        self.proxy_target_npm.blockSignals(False)
        self.proxy_target_pip_cmd.blockSignals(False)
        self.proxy_target_github.blockSignals(False)
        self.proxy_target_winget.blockSignals(False)

        self._apply_proxy_ui()

    def _load_pypi_cache_settings(self):
        settings = getattr(self.config_mgr.config, "pypi_cache_settings", {}) or {}
        self.pypi_cache_auto_refresh_check.blockSignals(True)
        self.pypi_cache_auto_refresh_check.setChecked(bool(settings.get("auto_refresh_on_start", True)))
        self.pypi_cache_auto_refresh_check.blockSignals(False)
        self.pypi_cache_log.clear()
        self._pypi_cache_log_cursor = 0
        self._sync_pypi_refresh_ui()
        if not self._pypi_progress_timer.isActive():
            self._pypi_progress_timer.start()

    def _save_source_settings(self):
        pip_mode = self._get_selected_mode(self.pip_source_mode_group)
        npm_mode = self._get_selected_mode(self.npm_source_mode_group)

        pip_settings = getattr(self.config_mgr.config, "pip_settings", {}) or {}
        npm_settings = getattr(self.config_mgr.config, "npm_settings", {}) or {}

        new_pip = dict(pip_settings)
        new_pip["source_mode"] = pip_mode
        new_pip["index_url"] = self._pip_custom_url
        new_pip["uv_path"] = self.uv_path_edit.text().strip()

        new_npm = dict(npm_settings)
        new_npm["source_mode"] = npm_mode
        new_npm["registry_url"] = self._npm_custom_url

        if new_pip != pip_settings or new_npm != npm_settings:
            self.config_mgr.config.pip_settings = new_pip
            self.config_mgr.config.npm_settings = new_npm
            self.config_mgr.save_config()
            self._changed = True

    def _save_proxy_settings(self):
        existing = getattr(self.config_mgr.config, "proxy_settings", {}) or {}
        new_settings = normalize_proxy_settings({
            "enabled": self.proxy_enabled_check.isChecked(),
            "http_proxy": self.proxy_http_edit.text().strip(),
            "https_proxy": self.proxy_https_edit.text().strip(),
            "targets": {
                "pypi": self.proxy_target_pypi.isChecked(),
                "npm": self.proxy_target_npm.isChecked(),
                "pip": self.proxy_target_pip_cmd.isChecked(),
                "github": self.proxy_target_github.isChecked(),
                "winget": self.proxy_target_winget.isChecked(),
            },
        })
        if normalize_proxy_settings(existing) != new_settings:
            self.config_mgr.config.proxy_settings = new_settings
            self.config_mgr.save_config()
            self._changed = True

    def _save_pypi_cache_settings(self):
        existing = getattr(self.config_mgr.config, "pypi_cache_settings", {}) or {}
        new_settings = {
            "auto_refresh_on_start": bool(self.pypi_cache_auto_refresh_check.isChecked()),
            "stale_after_hours": int(existing.get("stale_after_hours", 24) or 24),
        }
        if existing != new_settings:
            self.config_mgr.config.pypi_cache_settings = new_settings
            self.config_mgr.save_config()
            self._changed = True

    def _on_proxy_fields_changed(self, _value=None):
        self._changed = True
        self._apply_proxy_ui()

    def _apply_proxy_ui(self):
        enabled = self.proxy_enabled_check.isChecked()
        self.proxy_http_edit.setEnabled(enabled)
        self.proxy_https_edit.setEnabled(enabled)
        self.proxy_target_pypi.setEnabled(enabled)
        self.proxy_target_npm.setEnabled(enabled)
        self.proxy_target_pip_cmd.setEnabled(enabled)
        self.proxy_target_github.setEnabled(enabled)
        self.proxy_target_winget.setEnabled(enabled)

    def _on_pypi_cache_settings_changed(self):
        self._changed = True

    def _format_age(self, age_seconds):
        if age_seconds is None:
            return "unknown"
        if age_seconds < 60:
            return f"{age_seconds}s"
        if age_seconds < 3600:
            return f"{age_seconds // 60}m"
        return f"{age_seconds // 3600}h"

    def _refresh_pypi_cache_status_text(self, refresh_state=None):
        status = get_cache_status()
        package_count = int(status.get("package_count", 0))
        updated_at = str(status.get("updated_at", "")) or "unknown"
        source = str(status.get("source", "unknown"))
        stale_text = "yes" if bool(status.get("stale", True)) else "no"
        age_text = self._format_age(status.get("age_seconds"))
        state = refresh_state or get_refresh_state()
        is_running = bool(state.get("running", False))
        percent = state.get("percent")
        stage_text = str(state.get("stage", "") or "")
        message = str(state.get("message", "") or "")
        refresh_source = str(state.get("source_label", "") or "")
        if not refresh_source:
            refresh_source = self._resolve_pypi_refresh_source_from_ui().get("source_label", "")

        base_text = f"Packages: {package_count} | Updated: {updated_at} | Age: {age_text} | Stale: {stale_text} | Source: {source}"
        if refresh_source:
            base_text += f" | Refresh Source: {refresh_source}"
        if is_running:
            if percent is not None:
                state_text = f" | Refresh: {percent:.1f}% ({stage_text})"
            else:
                state_text = f" | Refresh: running ({stage_text})"
            self.pypi_cache_status_label.setStyleSheet("color: #FF9800;")
            self.pypi_cache_status_label.setText(base_text + state_text)
        elif stage_text == "error":
            self.pypi_cache_status_label.setStyleSheet("color: #E57373;")
            self.pypi_cache_status_label.setText(base_text + f" | Last refresh failed: {message}")
        elif stage_text == "cancelled":
            self.pypi_cache_status_label.setStyleSheet("color: #B0BEC5;")
            self.pypi_cache_status_label.setText(base_text + f" | Last refresh: {message}")
        else:
            self.pypi_cache_status_label.setStyleSheet("color: gray;")
            self.pypi_cache_status_label.setText(base_text)

    def _append_pypi_cache_log(self, message: str):
        self.pypi_cache_log.appendPlainText(message)

    def _sync_pypi_refresh_ui(self):
        state = get_refresh_state()
        logs = state.get("logs", [])
        if self._pypi_cache_log_cursor > len(logs):
            self._pypi_cache_log_cursor = 0
        for line in logs[self._pypi_cache_log_cursor :]:
            self._append_pypi_cache_log(line)
        self._pypi_cache_log_cursor = len(logs)

        if bool(state.get("running", False)):
            percent = state.get("percent")
            if percent is not None:
                self.pypi_cache_refresh_btn.setText(f"Cancel Update ({percent:.1f}%)")
            else:
                self.pypi_cache_refresh_btn.setText("Cancel Update")
            self.pypi_cache_refresh_btn.setEnabled(True)
        else:
            self.pypi_cache_refresh_btn.setText("Update Cache")
            self.pypi_cache_refresh_btn.setEnabled(True)

        self._refresh_pypi_cache_status_text(refresh_state=state)

    def _on_pypi_progress_tick(self):
        self._sync_pypi_refresh_ui()

    def _on_refresh_pypi_cache_clicked(self):
        state = get_refresh_state()
        if bool(state.get("running", False)):
            cancel_refresh_task()
            self._sync_pypi_refresh_ui()
            return
        proxy_settings = self._current_proxy_settings_from_ui()
        pip_settings = self._build_pip_settings_snapshot_for_cache()
        started = start_refresh_task(
            proxy_settings=proxy_settings,
            timeout=None,
            pip_settings=pip_settings,
            system_index_url=self._pip_system_url,
        )
        if started:
            self.pypi_cache_log.clear()
            self._pypi_cache_log_cursor = 0
        self._sync_pypi_refresh_ui()

    def _open_pypi_cache_folder(self):
        cache_dir = str(cache_file_path().parent)
        try:
            if os.name == "nt":
                os.startfile(cache_dir)
            elif os.name == "darwin":
                import subprocess
                subprocess.Popen(["open", cache_dir])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", cache_dir])
        except Exception as e:
            self._append_pypi_cache_log(f"Failed to open cache folder: {e}")

    def _current_proxy_settings_from_ui(self):
        return normalize_proxy_settings({
            "enabled": self.proxy_enabled_check.isChecked(),
            "http_proxy": self.proxy_http_edit.text().strip(),
            "https_proxy": self.proxy_https_edit.text().strip(),
            "targets": {
                "pypi": self.proxy_target_pypi.isChecked(),
                "npm": self.proxy_target_npm.isChecked(),
                "pip": self.proxy_target_pip_cmd.isChecked(),
                "github": self.proxy_target_github.isChecked(),
                "winget": self.proxy_target_winget.isChecked(),
            },
        })

    def _toggle_proxy_test_output(self):
        visible = not self.proxy_test_output.isVisible()
        self.proxy_test_output.setVisible(visible)
        self.proxy_test_toggle_btn.setText("Hide Details" if visible else "Show Details")

    def _build_pip_settings_snapshot_for_cache(self) -> dict:
        return {
            "source_mode": self._get_selected_mode(self.pip_source_mode_group),
            "index_url": self._pip_custom_url,
            "uv_path": self.uv_path_edit.text().strip(),
        }

    def _resolve_pypi_refresh_source_from_ui(self) -> dict:
        return resolve_refresh_source(
            pip_settings=self._build_pip_settings_snapshot_for_cache(),
            system_index_url=self._pip_system_url,
        )

    def _on_test_proxy_connections_clicked(self):
        from PySide6.QtCore import QThread, Signal
        import urllib.request
        import time

        service_specs = [
            ("pypi", "PyPI API", "https://pypi.org/pypi/pip/json"),
            ("pypi", "PyPI Simple", "https://pypi.org/simple/pip/"),
            ("npm", "NPM Registry", "https://registry.npmjs.org/-/ping"),
            ("github", "GitHub API", "https://api.github.com/rate_limit"),
            ("winget", "Winget CDN", "https://cdn.winget.microsoft.com/cache/source.msix"),
        ]
        ui_settings = self._current_proxy_settings_from_ui()
        proxy_map = {}
        if ui_settings.get("http_proxy"):
            proxy_map["http"] = ui_settings["http_proxy"]
        if ui_settings.get("https_proxy"):
            proxy_map["https"] = ui_settings["https_proxy"]

        class ProxyConnectivityWorker(QThread):
            result_ready = Signal(list, str)

            def __init__(self, specs, settings, proxies):
                super().__init__()
                self.specs = specs
                self.settings = settings
                self.proxies = proxies

            @staticmethod
            def _probe(url: str, headers: dict, mode: str, proxies: dict):
                import ssl
                try:
                    ctx = ssl._create_unverified_context()
                except Exception:
                    ctx = None
                    
                handler = urllib.request.ProxyHandler({}) if mode == "direct" else urllib.request.ProxyHandler(proxies)
                opener = urllib.request.build_opener(
                    handler,
                    urllib.request.HTTPSHandler(context=ctx) if ctx else urllib.request.HTTPSHandler()
                )
                req = urllib.request.Request(url, headers=headers)
                start = time.perf_counter()
                try:
                    with opener.open(req, timeout=8) as response:
                        response.read(1)
                        elapsed_ms = int((time.perf_counter() - start) * 1000)
                        return f"OK {elapsed_ms}ms (HTTP {response.getcode()})"
                except Exception as e:
                    elapsed_ms = int((time.perf_counter() - start) * 1000)
                    return f"FAIL {elapsed_ms}ms ({e})"

            def run(self):
                rows = []
                proxy_note = ""
                if not self.proxies:
                    proxy_note = "Proxy not configured (HTTP/HTTPS empty)."
                for target_key, name, url in self.specs:
                    headers = {"User-Agent": f"OmniPack/{__version__}"}
                    if "github.com" in url:
                        headers["Accept"] = "application/vnd.github+json"
                    policy = "ON" if self.settings.get("enabled") and self.settings.get("targets", {}).get(target_key, False) else "OFF"
                    direct = self._probe(url, headers, "direct", {})
                    proxy = "SKIP (proxy not configured)" if not self.proxies else self._probe(url, headers, "proxy", self.proxies)
                    rows.append((name, policy, direct, proxy))
                self.result_ready.emit(rows, proxy_note)

        self.proxy_test_btn.setEnabled(False)
        self.proxy_test_btn.setText("Testing...")
        if not self.proxy_test_output.isVisible():
            self.proxy_test_output.setVisible(True)
            self.proxy_test_toggle_btn.setText("Hide Details")
        self.proxy_test_output.setHtml("<i style='color: gray;'>Running connectivity tests...</i>")

        self._proxy_test_worker = ProxyConnectivityWorker(service_specs, ui_settings, proxy_map)

        def on_ready(rows, proxy_note):
            html = """
            <style>
                table { border-collapse: collapse; width: 100%; font-family: Consolas, monospace; font-size: 12px; }
                th { text-align: left; border-bottom: 2px solid #555; padding: 4px; color: #aaa; }
                td { padding: 4px; border-bottom: 1px solid #333; vertical-align: top; }
                .ok { color: #6BCB77; font-weight: bold; }
                .fail { color: #FF6B6B; font-weight: bold; }
                .policy-on { color: #4CC9F0; }
                .policy-off { color: #888; }
                .note { color: #E8A838; font-style: italic; margin-top: 8px; }
            </style>
            <table>
                <tr>
                    <th>Service</th>
                    <th>App Policy</th>
                    <th>Direct</th>
                    <th>Proxy</th>
                </tr>
            """
            for name, policy, direct, proxy in rows:
                p_class = "policy-on" if policy == "ON" else "policy-off"
                
                def fmt_res(res):
                    if res.startswith("OK"):
                        return f"<span class='ok'>{res}</span>"
                    if res.startswith("FAIL"):
                        return f"<span class='fail'>{res}</span>"
                    return res

                html += f"""
                <tr>
                    <td><b>{name}</b></td>
                    <td class='{p_class}'>{policy}</td>
                    <td>{fmt_res(direct)}</td>
                    <td>{fmt_res(proxy)}</td>
                </tr>
                """
            
            html += "</table>"
            if proxy_note:
                html += f"<div class='note'>{proxy_note}</div>"
            
            if not self.proxy_test_output.isVisible():
                self.proxy_test_output.setVisible(True)
                self.proxy_test_toggle_btn.setText("Hide Details")
            
            self.proxy_test_output.setHtml(html)
            self.proxy_test_btn.setEnabled(True)
            self.proxy_test_btn.setText("Test Direct vs Proxy")

        self._proxy_test_worker.result_ready.connect(on_ready)
        self._proxy_test_worker.finished.connect(self._proxy_test_worker.deleteLater)
        self._proxy_test_worker.start()

    def _on_source_mode_changed(self, _checked=False):
        self._apply_source_ui()
        self._refresh_pypi_cache_status_text()

    def _on_quick_fill(self, source_kind: str, url: str):
        if source_kind == "pip":
            self._pip_custom_url = url
            self._set_mode_value(self.pip_source_mode_buttons, "custom")
        else:
            self._npm_custom_url = url
            self._set_mode_value(self.npm_source_mode_buttons, "custom")
        self._apply_source_ui()
        self._refresh_pypi_cache_status_text()

    def _on_pip_url_edited(self, text: str):
        if self._get_selected_mode(self.pip_source_mode_group) == "custom":
            self._pip_custom_url = text.strip()
            self._refresh_pypi_cache_status_text()

    def _on_npm_url_edited(self, text: str):
        if self._get_selected_mode(self.npm_source_mode_group) == "custom":
            self._npm_custom_url = text.strip()

    def _apply_source_ui(self):
        pip_mode = self._get_selected_mode(self.pip_source_mode_group)
        npm_mode = self._get_selected_mode(self.npm_source_mode_group)

        self._update_mode_card_texts("pip")
        self._update_mode_card_texts("npm")

        self._set_url_view(
            line_edit=self.pip_index_url,
            mode=pip_mode,
            system_url=self._pip_system_url,
            official_url=PYPI_OFFICIAL_INDEX,
            custom_url=self._pip_custom_url,
        )
        self._set_url_view(
            line_edit=self.npm_registry_url,
            mode=npm_mode,
            system_url=self._npm_system_url,
            official_url=NPM_OFFICIAL_REGISTRY,
            custom_url=self._npm_custom_url,
        )

    def _update_mode_card_texts(self, source_kind: str):
        if source_kind == "pip":
            buttons = self.pip_source_mode_buttons
            system_url = self._pip_system_url
            official_url = PYPI_OFFICIAL_INDEX
            custom_url = self._pip_custom_url
        else:
            buttons = self.npm_source_mode_buttons
            system_url = self._npm_system_url
            official_url = NPM_OFFICIAL_REGISTRY
            custom_url = self._npm_custom_url

        system_text = system_url if system_url else "(no system override detected)"
        custom_text = custom_url if custom_url else "(use URL field or quick fill)"

        if "system" in buttons:
            buttons["system"].setText(f"Follow System\n{system_text}")
        if "official" in buttons:
            buttons["official"].setText(f"Official\n{official_url}")
        if "custom" in buttons:
            buttons["custom"].setText(f"Custom\n{custom_text}")

    @staticmethod
    def _set_url_view(line_edit: QLineEdit, mode: str, system_url: str, official_url: str, custom_url: str):
        if mode == "custom":
            value = custom_url
            editable = True
        elif mode == "official":
            value = official_url
            editable = False
        else:
            value = system_url
            editable = False

        line_edit.blockSignals(True)
        line_edit.setText(value)
        line_edit.setReadOnly(not editable)
        line_edit.setProperty("readonly", not editable)
        line_edit.style().unpolish(line_edit)
        line_edit.style().polish(line_edit)
        line_edit.update()
        line_edit.blockSignals(False)

    @staticmethod
    def _get_selected_mode(group: QButtonGroup) -> str:
        btn = group.checkedButton()
        return str(btn.property("mode")) if btn else "system"

    @staticmethod
    def _set_mode_value(buttons: dict, value: str):
        btn = buttons.get(value) or buttons.get("system")
        if btn:
            btn.setChecked(True)

    def _on_uv_path_edited(self, text: str):
        self._changed = True
        self._check_uv_version()

    def _browse_uv_path(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select uv Executable",
            "",
            "Executable (*.exe);;All Files (*)" if os.name == "nt" else "Executable (*);;All Files(*)",
        )
        if path:
            self.uv_path_edit.setText(path)
            self._changed = True

    def _check_uv_version(self):
        # Prevent spamming network/disk IO while typing
        if hasattr(self, '_uv_version_timer'):
            self._uv_version_timer.stop()
        else:
            from PySide6.QtCore import QTimer
            self._uv_version_timer = QTimer(self)
            self._uv_version_timer.setSingleShot(True)
            self._uv_version_timer.timeout.connect(self._run_uv_version_check)
        
        self._uv_version_timer.start(500)

    def _run_uv_version_check(self):
        from core.utils import get_uv_path
        from core.network_proxy import urlopen as proxy_urlopen, normalize_proxy_settings
        
        # Save current typed value temporarily to config so get_uv_path can read it
        old_uv_path = str(self.config_mgr.config.pip_settings.get("uv_path", ""))
        self.config_mgr.config.pip_settings["uv_path"] = self.uv_path_edit.text().strip()
        uv_path = get_uv_path(self.config_mgr)
        # Restore, wait for actual save logic when pressing OK
        self.config_mgr.config.pip_settings["uv_path"] = old_uv_path
        proxy_settings = normalize_proxy_settings(getattr(self.config_mgr.config, "proxy_settings", {}) or {})

        from PySide6.QtCore import QThread, Signal
        import subprocess, json

        class UvVersionCheckWorker(QThread):
            version_ready = Signal(str, str) # local, remote
            
            def __init__(self, executable, proxy_settings):
                super().__init__()
                self.executable = executable
                self.proxy_settings = proxy_settings
                
            def run(self):
                local_ver = "Unknown"
                remote_ver = "Unknown"
                
                # Check local
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                try:
                    res = subprocess.run([self.executable, "--version"], capture_output=True, text=True, creationflags=flags)
                    if res.returncode == 0:
                        local_ver = res.stdout.strip()
                except Exception:
                    pass
                
                # Check remote (only if local actually executed successfully, otherwise it's not a valid uv path)
                if local_ver != "Unknown":
                    try:
                        with proxy_urlopen(
                            "https://api.github.com/repos/astral-sh/uv/releases/latest",
                            timeout=3,
                            headers={'User-Agent': f'OmniPack/{__version__}'},
                            proxy_settings=self.proxy_settings,
                        ) as response:
                            data = json.loads(response.read().decode())
                            remote_ver = data.get("tag_name", "").lstrip("v")
                    except Exception:
                        remote_ver = "Network error"
                        
                self.version_ready.emit(local_ver, remote_ver)

        self.uv_version_label.setText(f"Targeting: {uv_path} (checking version...)")
        self.uv_version_label.setStyleSheet("color: gray; font-style: italic;")
        
        self._uv_version_worker = UvVersionCheckWorker(uv_path, proxy_settings)
        
        def on_version_ready(local_ver, remote_ver):
            if local_ver == "Unknown":
                self.uv_version_label.setText(f"<b>Targeting:</b> {uv_path}<br/>(Invalid or not found)")
                self.uv_version_label.setStyleSheet("color: #E91E63; font-weight: bold;")
                return
                
            msg = f"<b>Targeting:</b> {uv_path}<br/><b>Local:</b> {local_ver}"
            
            # Extract just the version number (e.g., '0.11.0') from 'uv 0.11.0 (hash ...)'
            import re
            m = re.search(r"uv\s+([0-9.]+)", local_ver)
            local_pure = m.group(1) if m else local_ver.replace("uv ", "").split()[0]
            
            if remote_ver not in ("Unknown", "Network error"):
                if local_pure != remote_ver:
                    msg += f"<br/><span style='color: #FF9800;'><b>Update Available:</b> {remote_ver}</span>"
                    self.uv_version_label.setStyleSheet("color: #FF9800;") 
                else:
                    msg += " <span style='color: #4CAF50;'>(Up to date)</span>"
                    self.uv_version_label.setStyleSheet("color: #4CAF50;") 
            else:
                 msg += f"<br/><i>(Remote check failed: {remote_ver})</i>"
                 self.uv_version_label.setStyleSheet("color: gray;")
                 
            self.uv_version_label.setText(msg)
            
        self._uv_version_worker.version_ready.connect(on_version_ready)
        self._uv_version_worker.start()

    def _update_uv_engine(self):
        from core.utils import get_uv_path
        from core.network_proxy import merge_env_for_command, normalize_proxy_settings
        
        uv_path = get_uv_path(self.config_mgr)
        proxy_settings = normalize_proxy_settings(getattr(self.config_mgr.config, "proxy_settings", {}) or {})
        
        # Disable button to prevent multiple clicks and show loading state
        update_btn = self.sender()
        if isinstance(update_btn, QPushButton):
            update_btn.setEnabled(False)
            update_btn.setText("Updating... Please wait")
        
        # Define local worker class to avoid polluting global scope
        from PySide6.QtCore import QThread, Signal
        import subprocess

        class UvUpdateWorker(QThread):
            result_ready = Signal(bool, str, str)  # success, title, message
            
            def __init__(self, uv_path, proxy_settings):
                super().__init__()
                self.uv_path = uv_path
                self.proxy_settings = proxy_settings
                
            def run(self):
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                try:
                    cmd = [self.uv_path, "self", "update"]
                    res = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        creationflags=flags,
                        env=merge_env_for_command(cmd, proxy_settings=self.proxy_settings),
                    )
                    if res.returncode == 0:
                        out = res.stdout.strip() or res.stderr.strip()
                        self.result_ready.emit(True, "Success", f"Update successful:\n{out}")
                    else:
                        out = res.stderr.strip() or res.stdout.strip()
                        self.result_ready.emit(False, "Failed", f"Update failed (code {res.returncode}):\n{out}")
                except FileNotFoundError:
                    self.result_ready.emit(False, "Not Found", f"Could not execute '{self.uv_path}'. Ensure uv is correctly configured.")
                except Exception as e:
                    self.result_ready.emit(False, "Error", f"Error executing update:\n{e}")

        self._uv_worker = UvUpdateWorker(uv_path, proxy_settings)
        
        # --- Animation Timer ---
        from PySide6.QtCore import QTimer
        self._anim_timer = QTimer(self)
        self._dots_count = 0
        def update_anim():
            self._dots_count = (self._dots_count + 1) % 4
            dots = "." * self._dots_count
            if isinstance(update_btn, QPushButton):
                update_btn.setText(f"Updating{dots} Please wait")
        
        self._anim_timer.timeout.connect(update_anim)
        self._anim_timer.start(500) # 2 fps animation
        # -----------------------

        def on_result(success, title, msg):
            if hasattr(self, "_anim_timer"):
                self._anim_timer.stop()
                
            if isinstance(update_btn, QPushButton):
                update_btn.setEnabled(True)
                update_btn.setText("Check for Update / Self Update (uv)")
                
            if success:
                self._show_selectable_message(title, msg)
                self._run_uv_version_check()
            else:
                self._show_selectable_message(title, msg, QMessageBox.Warning)
                
        self._uv_worker.result_ready.connect(on_result)
        self._uv_worker.start()

    def closeEvent(self, event):
        if hasattr(self, "_pypi_progress_timer") and self._pypi_progress_timer.isActive():
            self._pypi_progress_timer.stop()
        if self._changed:
            self.settings_changed.emit()
            self._changed = False
        super().closeEvent(event)
