import json
import urllib.parse
from typing import Optional
from core.config import ConfigManager
from core.network_proxy import urlopen as proxy_urlopen
from core.npm_spec import split_npm_spec, has_explicit_tag
from core.pypi_cache import search_cached_packages, get_cache_status
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QCheckBox, QStackedWidget, QWidget, QFrame, QGridLayout
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer

class SearchWorker(QThread):
    results_ready = Signal(list)
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(self, registry_type: str, query: str, proxy_settings: Optional[dict] = None):
        super().__init__()
        self.registry_type = registry_type
        self.query = query
        self.proxy_settings = proxy_settings or {}
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self._emit_status(f"Searching '{self.query}'...")
            if self.registry_type == 'pip':
                results = self._search_pypi()
            else:
                results = self._search_npm()

            if not self._is_cancelled:
                self.results_ready.emit(results)
        except Exception as e:
            if not self._is_cancelled:
                self.error_occurred.emit(str(e))

    def _emit_status(self, text: str):
        if not self._is_cancelled:
            self.status_update.emit(text)

    def _search_pypi(self) -> list:
        self._emit_status("Searching local PyPI cache...")
        results = search_cached_packages(self.query, limit=30)
        if self._is_cancelled:
            return []
        if not results:
            cache_status = get_cache_status()
            if int(cache_status.get("package_count", 0)) <= 0:
                self._emit_status("PyPI cache is empty. Update cache in Settings.")
        return results

    def _search_npm(self) -> list:
        url = f"https://registry.npmjs.org/-/v1/search?text={urllib.parse.quote(self.query)}&size=30"
        self._emit_status("Connecting to NPM registry...")
        
        try:
            with proxy_urlopen(
                url,
                timeout=10,
                headers={'User-Agent': 'Mozilla/5.0'},
                proxy_settings=self.proxy_settings,
            ) as response:
                res = response.read().decode('utf-8')
        except Exception as e:
            raise Exception(f"Failed to connect to NPM registry: {e}")
            
        data = json.loads(res)
        results = []
        for obj in data.get("objects", []):
            pkg = obj.get("package", {})
            results.append({
                "name": pkg.get("name", ""),
                "version": pkg.get("version", ""),
                "description": pkg.get("description", "").replace('\n', ' ')
            })
        return results

class NpmChannelsWorker(QThread):
    channels_ready = Signal(list, dict)
    error_occurred = Signal(str)

    def __init__(self, pkg_name: str, proxy_settings: Optional[dict] = None):
        super().__init__()
        self.pkg_name = pkg_name
        self.proxy_settings = proxy_settings or {}
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            url = f"https://registry.npmjs.org/{urllib.parse.quote(self.pkg_name, safe='@/')}"
            with proxy_urlopen(
                url,
                timeout=10,
                headers={'User-Agent': 'Mozilla/5.0'},
                proxy_settings=self.proxy_settings,
            ) as response:
                res = response.read().decode('utf-8')
                
            if self._is_cancelled:
                return
                
            data = json.loads(res)
            
            dist_tags = data.get("dist-tags", {})
            if dist_tags:
                channels = list(dist_tags.keys())
                others = [c for c in channels if c != "latest"]
                others.sort()
                final_channels = (["latest"] if "latest" in channels else []) + others
                self.channels_ready.emit(final_channels, dict(dist_tags))
            else:
                self.channels_ready.emit(["latest"], {})
        except Exception as e:
            if not self._is_cancelled:
                self.error_occurred.emit(str(e))


class AddPackageDialog(QDialog):
    _orphan_workers = set()

    def __init__(self, registry_type: str, parent=None):
        super().__init__(parent)
        self.registry_type = registry_type # 'pip' or 'npm'
        self.setWindowTitle(f"Search & Add {registry_type.upper()} Package")
        self.resize(500, 600)

        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self._search_worker = None
        self._channels_worker = None
        self._worker_refs = set()
        self._pending_search_query = None
        self._search_seq = 0
        self._proxy_settings = {}
        self._channel_versions = {}
        self._channel_card_buttons = {}
        self._selected_channel = "latest"

        self._final_pkg_name = ""
        self._final_channel = ""
        self._final_force = False

        self._load_proxy_settings()
        self._build_ui()

    def _load_proxy_settings(self):
        try:
            cfg = ConfigManager()
            self._proxy_settings = dict(getattr(cfg.config, "proxy_settings", {}) or {})
        except Exception:
            self._proxy_settings = {}

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)

        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)

        # PAGE 1: SEARCH
        self.page_search = QWidget()
        ps_layout = QVBoxLayout(self.page_search)
        ps_layout.setContentsMargins(0, 0, 0, 0)

        search_header = QHBoxLayout()
        self.search_input = QLineEdit()
        if self.registry_type == "pip":
            self.search_input.setPlaceholderText("Type package name to search local PyPI cache...")
        else:
            self.search_input.setPlaceholderText("Type a package name to search online...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        search_header.addWidget(self.search_input)
        
        ps_layout.addLayout(search_header)

        self.status_lbl = QLabel("Type to search...")
        self.status_lbl.setStyleSheet("color: #888;")
        ps_layout.addWidget(self.status_lbl)

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_item_selected)
        self.list_widget.itemDoubleClicked.connect(self._on_proceed)
        ps_layout.addWidget(self.list_widget)

        # Pip specific options
        if self.registry_type == 'pip':
            self.force_check = QCheckBox("--force-reinstall")
            ps_layout.addWidget(self.force_check)

        btn_layout_1 = QHBoxLayout()
        btn_layout_1.addStretch()
        self.cancel_btn_1 = QPushButton("Cancel")
        self.cancel_btn_1.clicked.connect(self.reject)
        self.proceed_btn_1 = QPushButton("Install" if self.registry_type == 'pip' else "Next >")
        self.proceed_btn_1.setEnabled(False)
        self.proceed_btn_1.clicked.connect(self._on_proceed)
        btn_layout_1.addWidget(self.cancel_btn_1)
        btn_layout_1.addWidget(self.proceed_btn_1)
        ps_layout.addLayout(btn_layout_1)

        self.stack.addWidget(self.page_search)

        # PAGE 2: NPM CONFIG (Only for NPM)
        if self.registry_type == 'npm':
            self.page_config = QWidget()
            pc_layout = QVBoxLayout(self.page_config)
            pc_layout.setContentsMargins(0, 0, 0, 0)

            self.pkg_title_lbl = QLabel()
            self.pkg_title_lbl.setStyleSheet("font-size: 16px; font-weight: bold;")
            pc_layout.addWidget(self.pkg_title_lbl)

            pc_layout.addWidget(QLabel("Target Tag (one-click):"))
            self.channel_cards = QWidget()
            self.channel_grid = QGridLayout(self.channel_cards)
            self.channel_grid.setContentsMargins(0, 0, 0, 0)
            self.channel_grid.setHorizontalSpacing(8)
            self.channel_grid.setVerticalSpacing(8)
            pc_layout.addWidget(self.channel_cards)

            self.channel_state_lbl = QLabel("Selected Tag: latest")
            self.channel_state_lbl.setStyleSheet("color: #999;")
            pc_layout.addWidget(self.channel_state_lbl)
            
            self.loading_lbl = QLabel("Fetching channels...")
            self.loading_lbl.setStyleSheet("color: #FF9800;")
            pc_layout.addWidget(self.loading_lbl)
            
            pc_layout.addStretch()

            btn_layout_2 = QHBoxLayout()
            self.back_btn_2 = QPushButton("< Back")
            self.back_btn_2.clicked.connect(lambda: self.stack.setCurrentWidget(self.page_search))
            btn_layout_2.addWidget(self.back_btn_2)
            btn_layout_2.addStretch()
            self.cancel_btn_2 = QPushButton("Cancel")
            self.cancel_btn_2.clicked.connect(self.reject)
            self.proceed_btn_2 = QPushButton("Install")
            self.proceed_btn_2.clicked.connect(self._on_final_install)
            self.proceed_btn_2.setEnabled(False)
            btn_layout_2.addWidget(self.cancel_btn_2)
            btn_layout_2.addWidget(self.proceed_btn_2)
            pc_layout.addLayout(btn_layout_2)

            self.stack.addWidget(self.page_config)

    def _on_search_text_changed(self, text):
        query = text.strip()
        self.proceed_btn_1.setEnabled(bool(query))
        
        if not query:
            self.list_widget.clear()
            self.status_lbl.setText("Type to search...")
            if self._search_worker:
                try:
                    self._search_worker.results_ready.disconnect()
                    self._search_worker.error_occurred.disconnect()
                    self._search_worker.status_update.disconnect()
                except (RuntimeError, TypeError):
                    pass
                self._search_worker.cancel()
            return
            
        self.status_lbl.setText("Waiting to search...")
        self._search_timer.start(500)

    def _do_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.cancel()
            self._pending_search_query = query
            self.status_lbl.setText(f"Cancelling current search, queued '{query}'...")
            return

        self._start_search_worker(query)

    def _start_search_worker(self, query: str):
        self._search_seq += 1
        seq = self._search_seq
        self._pending_search_query = None
        self.status_lbl.setText(f"Searching for '{query}'...")
        self._search_worker = SearchWorker(self.registry_type, query, proxy_settings=self._proxy_settings)
        self._search_worker.results_ready.connect(lambda results, s=seq: self._on_search_results(s, results))
        self._search_worker.error_occurred.connect(lambda err, s=seq: self._on_search_error(s, err))
        self._search_worker.status_update.connect(lambda msg, s=seq: self._on_search_status(s, msg))
        self._track_worker(self._search_worker)
        self._search_worker.start()

    def _on_search_results(self, seq: int, results):
        if seq != self._search_seq:
            return
        self.list_widget.clear()
        if not results:
            if self.registry_type == "pip":
                cache_status = get_cache_status()
                if int(cache_status.get("package_count", 0)) <= 0:
                    self.status_lbl.setText("PyPI cache is empty. Update cache in Settings > Backend.")
                    return
            self.status_lbl.setText(f"No results for '{self.search_input.text()}'. Installing raw input.")
            return
            
        self.status_lbl.setText(f"Found {len(results)} matches for '{self.search_input.text()}':")
        for r in results:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, r["name"])
            title = f"{r['name']} ({r['version']})"
            desc = r['description']
            if len(desc) > 80: desc = desc[:77] + "..."
            
            widget = QWidget()
            w_layout = QVBoxLayout(widget)
            w_layout.setContentsMargins(5, 5, 5, 5)
            w_layout.setSpacing(2)
            
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-weight: bold;")
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet("color: #999; font-size: 11px;")
            
            w_layout.addWidget(title_lbl)
            w_layout.addWidget(desc_lbl)
            
            item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def _on_search_status(self, seq: int, status: str):
        if seq != self._search_seq:
            return
        self.status_lbl.setText(status)

    def _on_search_error(self, seq: int, err):
        if seq != self._search_seq:
            return
        self.status_lbl.setText(f"Search error: {err}")

    def _on_item_selected(self):
        items = self.list_widget.selectedItems()
        if items:
            pkgcmd = items[0].data(Qt.UserRole)
            self.search_input.blockSignals(True)
            self.search_input.setText(pkgcmd)
            self.search_input.blockSignals(False)
            self.proceed_btn_1.setEnabled(True)

    def _on_proceed(self):
        self._final_pkg_name = self.search_input.text().strip()
        if not self._final_pkg_name: return

        if self.registry_type == 'pip':
            self._final_force = self.force_check.isChecked()
            self.accept()
        else:
            # NPM Configuration
            # Respect manually typed name@tag (including scoped packages)
            if has_explicit_tag(self._final_pkg_name):
                # Use as is
                self.accept()
                return

            self.pkg_title_lbl.setText(f"Configuring: {self._final_pkg_name}")
            self._clear_channel_cards()
            self._channel_versions = {}
            self._selected_channel = "latest"
            self.channel_state_lbl.setText("Selected Tag: latest")
            self.stack.setCurrentWidget(self.page_config)
            
            self.proceed_btn_2.setEnabled(False)
            self.loading_lbl.setVisible(True)
            self.loading_lbl.setText("Fetching channels...")
            
            if self._channels_worker and self._channels_worker.isRunning():
                try:
                    self._channels_worker.channels_ready.disconnect()
                    self._channels_worker.error_occurred.disconnect()
                except (RuntimeError, TypeError):
                    pass
                self._channels_worker.cancel()
            
            self._channels_worker = NpmChannelsWorker(self._final_pkg_name, proxy_settings=self._proxy_settings)
            self._channels_worker.channels_ready.connect(self._on_channels_ready)
            self._channels_worker.error_occurred.connect(self._on_channels_error)
            self._track_worker(self._channels_worker)
            self._channels_worker.start()

    def _set_tag_card_state(self, btn: QPushButton, state: str):
        btn.setProperty("state", state)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.update()

    def _clear_channel_cards(self):
        self._channel_card_buttons = {}
        while self.channel_grid.count():
            item = self.channel_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _format_channel_version(self, channel: str) -> str:
        if isinstance(self._channel_versions, dict):
            version = str(self._channel_versions.get(channel, "")).strip()
            if version:
                return version
        return "-"

    def _refresh_channel_cards_ui(self):
        selected = self._selected_channel
        self.channel_state_lbl.setText(f"Selected Tag: {selected}")
        for channel, button in self._channel_card_buttons.items():
            button.blockSignals(True)
            button.setChecked(channel == selected)
            button.blockSignals(False)
            self._set_tag_card_state(button, "target" if channel == selected else "normal")

    def _select_channel(self, channel: str):
        self._selected_channel = channel
        self._refresh_channel_cards_ui()

    def _build_channel_cards(self, channels: list[str]):
        self._clear_channel_cards()
        columns = 3
        for idx, channel in enumerate(channels):
            version = self._format_channel_version(channel)
            card = QPushButton(f"{channel}\n{version}")
            card.setObjectName("NpmTagCard")
            card.setCheckable(True)
            card.setMinimumHeight(56)
            card.clicked.connect(lambda _checked=False, c=channel: self._select_channel(c))
            self._channel_card_buttons[channel] = card
            row = idx // columns
            col = idx % columns
            self.channel_grid.addWidget(card, row, col)

        if channels:
            self._selected_channel = "latest" if "latest" in channels else channels[0]
            self._refresh_channel_cards_ui()

    def _on_channels_ready(self, channels, channel_versions):
        self.loading_lbl.setVisible(False)
        self._channel_versions = dict(channel_versions or {})
        normalized_channels = list(channels or [])
        if not normalized_channels:
            normalized_channels = ["latest"]
        self._build_channel_cards(normalized_channels)
        self.proceed_btn_2.setEnabled(bool(normalized_channels))

    def _on_channels_error(self, err):
        self.loading_lbl.setText(f"Auto-fetch failed: {err}")
        self._channel_versions = {}
        self._build_channel_cards(["latest"])
        self.proceed_btn_2.setEnabled(True)

    def _on_final_install(self):
        self._final_channel = self._selected_channel
        # If user selected a specific channel, append it
        if self._final_channel and self._final_channel != "latest":
            name, parsed_tag = split_npm_spec(self._final_pkg_name)
            if name and not parsed_tag:
                self._final_pkg_name = f"{name}@{self._final_channel}"
        self.accept()

    def get_data(self):
        return self._final_pkg_name, self._final_force

    def closeEvent(self, event):
        self._cleanup_workers()
        super().closeEvent(event)

    def reject(self):
        self._cleanup_workers()
        super().reject()

    def accept(self):
        self._cleanup_workers()
        super().accept()

    def _cleanup_workers(self):
        self._search_timer.stop()
        workers = list(self._worker_refs)
        for worker in workers:
            self._detach_worker(worker)
        self._worker_refs.clear()
        self._search_worker = None
        self._channels_worker = None

    def _track_worker(self, worker):
        self._worker_refs.add(worker)
        worker.finished.connect(self._on_any_worker_finished)

    def _on_any_worker_finished(self):
        worker = self.sender()
        if worker is None:
            return
        self._worker_refs.discard(worker)
        if worker is self._search_worker:
            self._search_worker = None
            pending_query = self._pending_search_query
            self._pending_search_query = None
            if pending_query and self.search_input.text().strip() == pending_query and self.isVisible():
                self._start_search_worker(pending_query)
        if worker is self._channels_worker:
            self._channels_worker = None
        worker.deleteLater()

    def _detach_worker(self, worker):
        try:
            worker.results_ready.disconnect()
        except Exception:
            pass
        try:
            worker.error_occurred.disconnect()
        except Exception:
            pass
        try:
            worker.status_update.disconnect()
        except Exception:
            pass
        try:
            worker.channels_ready.disconnect()
        except Exception:
            pass
        try:
            worker.finished.disconnect(self._on_any_worker_finished)
        except Exception:
            pass

        if hasattr(worker, "cancel"):
            worker.cancel()
        if worker.isRunning():
            self._adopt_orphan_worker(worker)
        else:
            worker.deleteLater()

    @classmethod
    def _adopt_orphan_worker(cls, worker):
        if worker in cls._orphan_workers:
            return
        cls._orphan_workers.add(worker)
        worker.finished.connect(lambda w=worker, c=cls: c._release_orphan_worker(w))

    @classmethod
    def _release_orphan_worker(cls, worker):
        cls._orphan_workers.discard(worker)
        worker.deleteLater()
