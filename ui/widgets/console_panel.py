from datetime import datetime
from time import perf_counter

from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QApplication, QCheckBox
from PySide6.QtGui import QColor, QTextCursor, QTextCharFormat, QFont
from PySide6.QtCore import Qt, QEvent, Property

class LogTextEdit(QTextEdit):
    """Subclass to support custom QSS properties without warnings."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._props = {}

    def _get_prop(self, name): return self._props.get(name, "")
    def _set_prop(self, name, val): self._props[name] = val

    # Color properties used by QSS
    system_color = Property(str, fget=lambda s: s._get_prop("system_color"), fset=lambda s, v: s._set_prop("system_color", v))
    cmd_color = Property(str, fget=lambda s: s._get_prop("cmd_color"), fset=lambda s, v: s._set_prop("cmd_color", v))
    stdout_color = Property(str, fget=lambda s: s._get_prop("stdout_color"), fset=lambda s, v: s._set_prop("stdout_color", v))
    stderr_color = Property(str, fget=lambda s: s._get_prop("stderr_color"), fset=lambda s, v: s._set_prop("stderr_color", v))
    success_color = Property(str, fget=lambda s: s._get_prop("success_color"), fset=lambda s, v: s._set_prop("success_color", v))
    error_color = Property(str, fget=lambda s: s._get_prop("error_color"), fset=lambda s, v: s._set_prop("error_color", v))
    divider_color = Property(str, fget=lambda s: s._get_prop("divider_color"), fset=lambda s, v: s._set_prop("divider_color", v))

class ConsolePanel(QFrame):
    """Terminal-style console panel with colored output logging."""

    def __init__(self, parent=None, config_mgr=None):
        super().__init__(parent)
        self.setObjectName("ConsolePanel")
        self.config_mgr = config_mgr
        self._colors = {}
        
        # Load initial state from config
        self._timestamp_enabled = False
        if self.config_mgr:
            self._timestamp_enabled = getattr(self.config_mgr.config, "console_timestamp_enabled", False)
            
        self._timing_origin = perf_counter()
        self._create_ui()
        
        # Sync checkbox state
        if hasattr(self, "timestamp_checkbox"):
            self.timestamp_checkbox.setChecked(self._timestamp_enabled)
            
        self._refresh_colors()

    def _create_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("ConsoleHeader")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 0, 6, 0)

        lbl = QLabel("⌘ Console")
        lbl.setObjectName("ConsoleTitle")
        h_layout.addWidget(lbl)
        h_layout.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ConsoleClearBtn")
        clear_btn.clicked.connect(self.clear)
        h_layout.addWidget(clear_btn)

        self.timestamp_checkbox = QCheckBox("timestamp")
        self.timestamp_checkbox.setObjectName("ConsoleTimestampCheckbox")
        self.timestamp_checkbox.setToolTip("Prefix console lines with wall-clock time and elapsed time since enable/clear")
        self.timestamp_checkbox.toggled.connect(self._on_timestamp_toggled)
        h_layout.addWidget(self.timestamp_checkbox)

        layout.addWidget(header)

        self.text_edit = LogTextEdit()
        self.text_edit.setObjectName("ConsoleText")
        self.text_edit.setReadOnly(True)
        
        layout.addWidget(self.text_edit)

    def _refresh_colors(self):
        """Fetch color tokens from QSS properties."""
        # Mapping between tag and QSS property name
        tags = ["system", "cmd", "stdout", "stderr", "success", "error", "divider"]
        for tag in tags:
            prop_name = f"{tag}_color"
            color_val = self.text_edit.property(prop_name)
            if color_val:
                # color_val might be a string (hex) or QColor depending on how QSS is parsed/applied
                self._colors[tag] = QColor(color_val)
            else:
                # Fallbacks if properties not yet applied
                fallbacks = {
                    "system": "#6CB4EE", "cmd": "#56D6C2", "stdout": "#D4D4D4",
                    "stderr": "#E8A838", "success": "#6BCB77", "error": "#FF6B6B", "divider": "#555555"
                }
                self._colors[tag] = QColor(fallbacks.get(tag, "#ffffff"))

    def event(self, event):
        # Refresh colors when style/polish changes (e.g. live QSS reload)
        if event.type() in [QEvent.Type.ChildPolished, QEvent.Type.Polish]:
            self._refresh_colors()
        return super().event(event)

    def log(self, message: str, tag: str = "stdout"):
        """Append tagged text to console."""
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        fmt = QTextCharFormat()
        color = self._colors.get(tag, self._colors.get("stdout", QColor("#ffffff")))
        fmt.setForeground(color)
        
        if tag == "cmd":
            fmt.setFontWeight(QFont.Bold)
        elif tag == "divider":
            fmt.setFontPointSize(9)
        else:
            fmt.setFontWeight(QFont.Normal)
            fmt.setFontPointSize(10)

        cursor.insertText(self._format_message(message) + "\n", fmt)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()
        # Force Qt to repaint immediately so real-time output is visible
        # during long-running subprocesses (winget downloads, pip install, etc.)
        QApplication.processEvents()

        # Trim if too long
        doc = self.text_edit.document()
        if doc.blockCount() > 2000:
            cursor = QTextCursor(doc.findBlockByNumber(0))
            cursor.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor, doc.blockCount() - 2000)
            cursor.removeSelectedText()

    def log_batch(self, entries: list):
        """Append a batch of tagged text immediately (atomic block)."""
        if not entries:
            return
            
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        for message, tag in entries:
            fmt = QTextCharFormat()
            color = self._colors.get(tag, self._colors.get("stdout", QColor("#ffffff")))
            fmt.setForeground(color)
            
            if tag == "cmd":
                fmt.setFontWeight(QFont.Bold)
            elif tag == "divider":
                fmt.setFontPointSize(9)
            else:
                fmt.setFontWeight(QFont.Normal)
                fmt.setFontPointSize(10)

            cursor.insertText(self._format_message(message) + "\n", fmt)
            
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()
        
        doc = self.text_edit.document()
        if doc.blockCount() > 2000:
            cursor = QTextCursor(doc.findBlockByNumber(0))
            cursor.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor, doc.blockCount() - 2000)
            cursor.removeSelectedText()

    def log_divider(self, label: str = ""):
        if label:
            line = f"{'─' * 4} {label} {'─' * 40}"
        else:
            line = "─" * 52
        self.log(line, "divider")

    def clear(self):
        self.text_edit.clear()
        self._reset_timing_origin()

    def _on_timestamp_toggled(self, enabled: bool):
        self._timestamp_enabled = enabled
        if self.config_mgr:
            self.config_mgr.config.console_timestamp_enabled = enabled
            self.config_mgr.save_config()
        self._reset_timing_origin()

    def _reset_timing_origin(self):
        self._timing_origin = perf_counter()

    def _format_message(self, message: str) -> str:
        if not self._timestamp_enabled:
            return message

        wall_clock = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        elapsed = perf_counter() - self._timing_origin
        return f"[{wall_clock} | +{elapsed:0.3f}s] {message}"
