from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit
from PySide6.QtGui import QColor, QTextCursor, QTextCharFormat, QFont
from PySide6.QtCore import Qt, QEvent

class ConsolePanel(QFrame):
    """Terminal-style console panel with colored output logging."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConsolePanel")
        self._colors = {}
        self._create_ui()
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

        layout.addWidget(header)

        self.text_edit = QTextEdit()
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

        cursor.insertText(message + "\n", fmt)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.ensureCursorVisible()
        
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

            cursor.insertText(message + "\n", fmt)
            
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
