"""
RealTerminalPanel — Interactive PTY terminal widget.

Drop-in replacement for ``ConsolePanel`` when ``console_mode`` is
``"real_terminal"``.  Provides the **same public API**:

    log(message, tag)
    log_batch(entries)
    log_divider(label)
    clear()

so that all existing worker signals (``log_msg``, ``log_batch``) keep
working without changes to Panel subclasses.
"""

import os
import pyte

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QApplication,
)
from PySide6.QtGui import QColor, QTextCursor, QTextCharFormat, QFont
from PySide6.QtCore import Qt, QTimer, Signal

from core.terminal.backend import create_pty_backend
from core.terminal.output_thread import PtyOutputThread


# ── Colour look-up tables ──────────────────────────────────────────────

# pyte named-colour → hex  (VS Code Dark+ palette)
_PYTE_COLORS = {
    "black":         "#000000",
    "red":           "#CD3131",
    "green":         "#0DBC79",
    "brown":         "#E5E510",   # ANSI "yellow" ≡ pyte "brown"
    "blue":          "#2472C8",
    "magenta":       "#BC3FBC",
    "cyan":          "#11A8CD",
    "white":         "#E5E5E5",
    "brightblack":   "#666666",
    "brightred":     "#F14C4C",
    "brightgreen":   "#23D18B",
    "brightyellow":  "#F5F543",
    "brightblue":    "#3B8EEA",
    "brightmagenta": "#D670D6",
    "brightcyan":    "#29B8DB",
    "brightwhite":   "#FFFFFF",
}

_DEFAULT_FG = QColor("#D4D4D4")

# Worker-log tag → (hex, bold)
_TAG_STYLES = {
    "system":  ("#6CB4EE", False),
    "cmd":     ("#56D6C2", True),
    "stdout":  ("#D4D4D4", False),
    "stderr":  ("#E8A838", False),
    "success": ("#6BCB77", False),
    "error":   ("#FF6B6B", False),
    "divider": ("#555555", False),
}


# ════════════════════════════════════════════════════════════════════════
#  Keyboard-capture widget
# ════════════════════════════════════════════════════════════════════════

class _TerminalTextEdit(QTextEdit):
    """QTextEdit subclass that routes **all** keyboard input to the PTY
    instead of editing the document."""

    key_pressed = Signal(str)

    # ── Key mapping tables ──────────────────────────────────────────────

    _CTRL_MAP = {
        Qt.Key_D: "\x04", Qt.Key_Z: "\x1a", Qt.Key_L: "\x0c",
        Qt.Key_A: "\x01", Qt.Key_E: "\x05", Qt.Key_U: "\x15",
        Qt.Key_K: "\x0b", Qt.Key_W: "\x17",
    }

    _SPECIAL_MAP = {
        Qt.Key_Return:   "\r",   Qt.Key_Enter:    "\r",
        Qt.Key_Backspace: "\x7f", Qt.Key_Tab:      "\t",
        Qt.Key_Escape:   "\x1b",
        Qt.Key_Up:       "\x1b[A", Qt.Key_Down:     "\x1b[B",
        Qt.Key_Right:    "\x1b[C", Qt.Key_Left:     "\x1b[D",
        Qt.Key_Home:     "\x1b[H", Qt.Key_End:      "\x1b[F",
        Qt.Key_Delete:   "\x1b[3~", Qt.Key_Insert:   "\x1b[2~",
        Qt.Key_PageUp:   "\x1b[5~", Qt.Key_PageDown: "\x1b[6~",
    }

    def keyPressEvent(self, event):                     # noqa: N802
        key  = event.key()
        text = event.text()
        mods = event.modifiers()

        # Shift+PageUp/Down → scroll the QTextEdit viewport
        if mods & Qt.ShiftModifier:
            if key == Qt.Key_PageUp:
                sb = self.verticalScrollBar()
                sb.setValue(sb.value() - sb.pageStep())
                return
            if key == Qt.Key_PageDown:
                sb = self.verticalScrollBar()
                sb.setValue(sb.value() + sb.pageStep())
                return

        # Ctrl combos
        if mods & Qt.ControlModifier:
            if key == Qt.Key_C:
                # Copy if text selected, else send SIGINT
                if self.textCursor().hasSelection():
                    self.copy()
                else:
                    self.key_pressed.emit("\x03")
                return
            if key == Qt.Key_V:
                # Paste → send clipboard text to PTY
                cb = QApplication.clipboard()
                if cb and cb.text():
                    self.key_pressed.emit(cb.text())
                return
            seq = self._CTRL_MAP.get(key)
            if seq:
                self.key_pressed.emit(seq)
                return

        # Special / function keys
        seq = self._SPECIAL_MAP.get(key)
        if seq:
            self.key_pressed.emit(seq)
            return

        # Regular printable characters
        if text:
            self.key_pressed.emit(text)
        # NOTE: super() is intentionally NOT called — all input goes to PTY.

    def insertFromMimeData(self, source):               # noqa: N802
        """Route pasted text to the PTY."""
        if source.hasText():
            self.key_pressed.emit(source.text())


# ════════════════════════════════════════════════════════════════════════
#  Main panel
# ════════════════════════════════════════════════════════════════════════

class RealTerminalPanel(QFrame):
    """Interactive PTY terminal — ConsolePanel-compatible drop-in."""
    
    pty_output_ready = Signal(str)

    def __init__(self, parent=None, config_mgr=None):
        super().__init__(parent)
        self.setObjectName("ConsolePanel")       # reuse ConsolePanel QSS
        self.config_mgr = config_mgr

        # Terminal geometry (updated after first layout)
        self._cols = 80
        self._rows = 24

        # pyte virtual terminal
        self._screen = pyte.HistoryScreen(self._cols, self._rows, history=5000)
        self._screen.set_mode(pyte.modes.LNM)    # LF also does CR
        self._stream = pyte.ByteStream(self._screen)

        # Worker-log buffer (rendered *above* the live terminal area)
        self._log_entries: list[tuple[str, str]] = []
        self._MAX_LOG_ENTRIES = 2000

        # PTY handles
        self._backend = None
        self._output_thread = None
        self._cleaned_up = False
        self._process_exited = False

        # Render throttle (≈ 30 fps)
        self._render_pending = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(33)
        self._render_timer.timeout.connect(self._render_screen)

        # QTextCharFormat cache — avoids re-creating identical formats
        self._fmt_cache: dict[tuple, QTextCharFormat] = {}

        # Pending commands to write to PTY once it becomes ready
        self._pending_commands: list[str] = []

        self._create_ui()
        QTimer.singleShot(150, self._start_pty)

    # ── UI ──────────────────────────────────────────────────────────────

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header (same objectNames → QSS reuse)
        header = QFrame()
        header.setObjectName("ConsoleHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 6, 0)

        title = QLabel("⌘ Terminal")
        title.setObjectName("ConsoleTitle")
        hl.addWidget(title)
        hl.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ConsoleClearBtn")
        clear_btn.clicked.connect(self.clear)
        hl.addWidget(clear_btn)

        layout.addWidget(header)

        # Terminal canvas
        self.text_edit = _TerminalTextEdit()
        self.text_edit.setObjectName("ConsoleText")
        self.text_edit.key_pressed.connect(self._on_key_pressed)
        layout.addWidget(self.text_edit)

    # ── PTY lifecycle ───────────────────────────────────────────────────

    def _start_pty(self):
        if self._cleaned_up:
            return
        vp = self.text_edit.viewport()
        if vp.width() <= 0 or vp.height() <= 0:
            QTimer.singleShot(100, self._start_pty)
            return

        self._recalculate_size()
        shell = self._resolve_shell()

        self._backend = create_pty_backend()
        
        from core.network_proxy import proxy_env_for_terminal
        proxy_settings = getattr(self.config_mgr.config, "proxy_settings", {}) if self.config_mgr else {}
        pty_env = proxy_env_for_terminal(proxy_settings)
        
        self._backend.spawn(cmd=shell, cwd=os.path.expanduser("~"), env=pty_env)
        self._backend.resize(self._cols, self._rows)

        self._output_thread = PtyOutputThread(self._backend, parent=self)
        self._output_thread.data_ready.connect(self._on_pty_data)
        self._output_thread.process_exited.connect(self._on_process_exited)
        self._output_thread.start()

        # Flush any pending commands that were written before the PTY was ready
        if self._pending_commands:
            QTimer.singleShot(600, self._flush_pending_commands)

    def _resolve_shell(self) -> str:
        shell = ""
        if self.config_mgr:
            shell = getattr(self.config_mgr.config, "terminal_shell", "")
        if not shell:
            shell = "cmd.exe" if os.name == "nt" else os.environ.get("SHELL", "/bin/bash")
        return shell

    def _restart_pty(self):
        """Kill current shell and start a fresh session."""
        self._process_exited = False
        self._stop_pty()
        self._screen.reset()
        self._screen.history.top.clear()
        self._log_entries.clear()
        self._schedule_render()
        QTimer.singleShot(100, self._start_pty)

    def _stop_pty(self):
        if self._output_thread:
            self._output_thread.request_stop()
        if self._backend:
            self._backend.close()
            self._backend = None
        if self._output_thread:
            self._output_thread.wait(2000)
            self._output_thread = None

    def _cleanup(self):
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self._render_timer.stop()
        self._stop_pty()

    # ── PTY I/O ─────────────────────────────────────────────────────────

    def _on_key_pressed(self, data: str):
        # If shell exited, Enter restarts it
        if self._process_exited and data == "\r":
            self._restart_pty()
            return
        self.write(data)

    def write(self, data: str):
        """Write string data directly to the PTY backend, or queue it if not ready."""
        if self._backend and self._backend.is_alive():
            self._backend.write(data)
        else:
            self._pending_commands.append(data)

    def _flush_pending_commands(self):
        """Write any queued commands to the PTY backend once it is ready."""
        if self._backend and self._backend.is_alive() and self._pending_commands:
            while self._pending_commands:
                cmd = self._pending_commands.pop(0)
                self._backend.write(cmd)

    def _on_pty_data(self, data: bytes):
        if self._cleaned_up:
            return
        try:
            self.pty_output_ready.emit(data.decode("utf-8", errors="replace"))
            self._stream.feed(data)
        except Exception:
            pass
        self._schedule_render()

    def _on_process_exited(self):
        self._process_exited = True
        self._log_entries.append(("[Process exited — press Enter to restart]", "system"))
        self._schedule_render()

    # ── Rendering ───────────────────────────────────────────────────────

    def _schedule_render(self):
        self._render_pending = True
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _render_screen(self):
        if not self._render_pending:
            return
        self._render_pending = False

        te = self.text_edit
        sb = te.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 20

        te.setUpdatesEnabled(False)

        doc = te.document()
        doc.clear()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()

        # 1. Worker-log entries (top section)
        for msg, tag in self._log_entries:
            cursor.insertText(msg + "\n", self._tag_format(tag))

        # 2. pyte history (scrolled-off lines)
        history = list(self._screen.history.top)
        for line_data in history:
            self._render_pyte_line(cursor, line_data, None)
            cursor.insertText("\n", QTextCharFormat())

        # 3. pyte current screen
        screen_lines = self._screen.lines
        
        last_row = self._screen.cursor.y
        default_char = self._screen.default_char
        for row in range(screen_lines - 1, self._screen.cursor.y, -1):
            if row in self._screen.buffer:
                line_data = self._screen.buffer[row]
                has_content = False
                for col in range(self._screen.columns):
                    ch = line_data[col] if col in line_data else default_char
                    if (ch.data and not ch.data.isspace()) or (ch.bg and ch.bg != "default") or ch.underscore or ch.strikethrough or ch.reverse:
                        has_content = True
                        break
                if has_content:
                    last_row = row
                    break

        for row in range(last_row + 1):
            cursor_x = self._screen.cursor.x if row == self._screen.cursor.y else None
            self._render_pyte_line(cursor, self._screen.buffer[row], cursor_x)
            if row < last_row:
                cursor.insertText("\n", QTextCharFormat())

        cursor.endEditBlock()
        te.setUpdatesEnabled(True)

        # Place the blinking cursor at the terminal cursor position
        term_block = len(self._log_entries) + len(history) + self._screen.cursor.y
        if term_block < doc.blockCount():
            blk = doc.findBlockByNumber(term_block)
            tc = QTextCursor(blk)
            move = min(self._screen.cursor.x, max(0, blk.length() - 1))
            if move > 0:
                tc.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, move)
            te.setTextCursor(tc)

        if at_bottom:
            sb.setValue(sb.maximum())

    # ── pyte line → QTextEdit ───────────────────────────────────────────

    def _render_pyte_line(self, cursor: QTextCursor, line_data, cursor_x=None):
        """Render one pyte buffer row, grouping same-styled chars."""
        default_char = self._screen.default_char
        cols = self._screen.columns
        segments: list[tuple[str, QTextCharFormat]] = []
        buf = ""
        prev_key = None

        for col in range(cols):
            ch = line_data[col] if col in line_data else default_char
            key = (ch.fg, ch.bg, ch.bold, ch.italics,
                   ch.underscore, ch.strikethrough, ch.reverse)
            if key == prev_key:
                buf += (ch.data or " ")
            else:
                if buf:
                    segments.append((buf, self._cached_format(prev_key)))
                buf = ch.data or " "
                prev_key = key

        if buf:
            segments.append((buf, self._cached_format(prev_key)))

        # Strip trailing whitespace from the last segment
        if segments:
            t, f = segments[-1]
            t_stripped = t.rstrip()
            if cursor_x is not None:
                len_before = sum(len(text) for text, _ in segments[:-1])
                keep_len = max(0, cursor_x - len_before)
                if len(t_stripped) < keep_len:
                    t_stripped = t[:keep_len]
            segments[-1] = (t_stripped, f)

        for t, f in segments:
            if t:
                cursor.insertText(t, f)

    # ── Format helpers ──────────────────────────────────────────────────

    def _cached_format(self, key: tuple) -> QTextCharFormat:
        """Return a cached QTextCharFormat for the given style tuple."""
        fmt = self._fmt_cache.get(key)
        if fmt is not None:
            return fmt
        fmt = self._build_char_format(*key)
        self._fmt_cache[key] = fmt
        return fmt

    def _build_char_format(self, fg, bg, bold, italics,
                           underscore, strikethrough, reverse):
        if reverse:
            fg, bg = bg, fg
        fmt = QTextCharFormat()
        fg_c = self._resolve_color(fg, bright=bold)
        fmt.setForeground(fg_c if fg_c else _DEFAULT_FG)
        bg_c = self._resolve_color(bg, bright=False)
        if bg_c:
            fmt.setBackground(bg_c)
        if bold:
            fmt.setFontWeight(QFont.Bold)
        if italics:
            fmt.setFontItalic(True)
        if underscore:
            fmt.setFontUnderline(True)
        if strikethrough:
            fmt.setFontStrikeOut(True)
        return fmt

    @staticmethod
    def _resolve_color(value, bright=False):
        """Resolve a pyte colour descriptor to a ``QColor`` (or *None*)."""
        if not value or value == "default":
            return None
        if value in _PYTE_COLORS:
            if bright:
                bk = f"bright{value}"
                if bk in _PYTE_COLORS:
                    return QColor(_PYTE_COLORS[bk])
            return QColor(_PYTE_COLORS[value])
        # 6-digit hex without '#' (pyte 256-colour / 24-bit output)
        if isinstance(value, str):
            if value.startswith("#"):
                return QColor(value)
            if len(value) == 6:
                try:
                    int(value, 16)
                    return QColor(f"#{value}")
                except ValueError:
                    pass
        return None

    def _tag_format(self, tag: str) -> QTextCharFormat:
        """Return a QTextCharFormat for a worker-log tag."""
        hex_col, bold = _TAG_STYLES.get(tag, ("#D4D4D4", False))
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(hex_col))
        if bold:
            fmt.setFontWeight(QFont.Bold)
        if tag == "divider":
            fmt.setFontPointSize(9)
        return fmt

    # ── ConsolePanel-compatible public API ──────────────────────────────

    def log(self, message: str, tag: str = "stdout"):
        """Append a worker log line (displayed above the terminal area)."""
        self._log_entries.append((message, tag))
        if len(self._log_entries) > self._MAX_LOG_ENTRIES:
            self._log_entries = self._log_entries[-self._MAX_LOG_ENTRIES:]
        self._schedule_render()

    def log_batch(self, entries: list):
        """Append multiple worker log lines at once."""
        for msg, tag in entries:
            self._log_entries.append((msg, tag))
        if len(self._log_entries) > self._MAX_LOG_ENTRIES:
            self._log_entries = self._log_entries[-self._MAX_LOG_ENTRIES:]
        self._schedule_render()

    def log_divider(self, label: str = ""):
        """Append a visual divider (worker-log area)."""
        line = f"{'─' * 4} {label} {'─' * 40}" if label else "─" * 52
        self.log(line, "divider")

    def clear(self):
        """Clear logs *and* reset the terminal screen."""
        self._log_entries.clear()
        self._screen.reset()
        self._screen.history.top.clear()
        if self._backend and self._backend.is_alive():
            self._backend.write("\x0c")          # Ctrl+L → shell clears screen
        self._schedule_render()

    # ── Geometry ────────────────────────────────────────────────────────

    def _recalculate_size(self):
        fm = self.text_edit.fontMetrics()
        cw = fm.horizontalAdvance("M")
        ch = fm.height()
        if cw <= 0 or ch <= 0:
            return
        vp = self.text_edit.viewport()
        new_cols = max(40, vp.width() // cw)
        new_rows = max(10, vp.height() // ch)
        if new_cols != self._cols or new_rows != self._rows:
            old_buffer = {r: dict(self._screen.buffer[r]) for r in range(self._rows)}
            old_cursor_x = self._screen.cursor.x
            old_cursor_y = self._screen.cursor.y

            self._cols = new_cols
            self._rows = new_rows
            self._screen.resize(new_rows, new_cols)
            
            for r, row_data in old_buffer.items():
                if r < new_rows:
                    for c, char in row_data.items():
                        if c < new_cols:
                            self._screen.buffer[r][c] = char
            self._screen.cursor.x = min(old_cursor_x, new_cols - 1)
            self._screen.cursor.y = min(old_cursor_y, new_rows - 1)

            if self._backend:
                self._backend.resize(self._cols, self._rows)
            self._fmt_cache.clear()
            self._schedule_render()

    def resizeEvent(self, event):                       # noqa: N802
        super().resizeEvent(event)
        QTimer.singleShot(50, self._recalculate_size)

    # ── Teardown ────────────────────────────────────────────────────────

    def closeEvent(self, event):                        # noqa: N802
        self._cleanup()
        super().closeEvent(event)

    def __del__(self):
        self._cleanup()
