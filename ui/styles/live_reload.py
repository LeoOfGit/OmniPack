"""
Live Reload utility for QSS styles.
Watches a specific QSS file and applies it to the application whenever it changes.
"""
import os
from PySide6.QtCore import QObject, QTimer, QFileInfo, Signal

class StyleReloader(QObject):
    """
    Polls the QSS file for modification time changes and emits a signal
    so the main window can reapply the stylesheet.
    """
    style_changed = Signal(str)

    def __init__(self, qss_path: str, interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self.qss_path = qss_path
        self.interval_ms = interval_ms
        self.last_modified = self._get_modified_time()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_file)
        self.timer.start(self.interval_ms)

    def _get_modified_time(self):
        if os.path.exists(self.qss_path):
            return QFileInfo(self.qss_path).lastModified()
        return None

    def check_file(self):
        current_time = self._get_modified_time()
        if current_time and current_time != self.last_modified:
            self.last_modified = current_time
            # Read new style
            try:
                with open(self.qss_path, "r", encoding="utf-8") as f:
                    new_style = f.read()
                self.style_changed.emit(new_style)
                print(f"[LiveReload] Stylesheet reloaded at {current_time.toString()}")
            except Exception as e:
                print(f"[LiveReload] Error reading QSS: {e}")
