"""
PtyOutputThread — Background QThread that reads PTY output.

Emits ``data_ready(bytes)`` for every chunk read from the backend,
and ``process_exited()`` when the child shell terminates.
"""

import threading
from PySide6.QtCore import QThread, Signal


class PtyOutputThread(QThread):
    """Continuously reads from a PTY backend and signals new data."""

    data_ready = Signal(bytes)
    process_exited = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._stop_event = threading.Event()

    # ── Thread loop ─────────────────────────────────────────────────────

    def run(self):
        while not self._stop_event.is_set():
            if not self._backend.is_alive():
                self.process_exited.emit()
                break
            try:
                data = self._backend.read(4096)
                if data:
                    self.data_ready.emit(data)
            except Exception:
                if self._stop_event.is_set():
                    break

    # ── Control ─────────────────────────────────────────────────────────

    def request_stop(self):
        """Set the stop flag (non-blocking).

        The caller should close the PTY backend afterwards so that a
        blocking ``read()`` is unblocked and the thread can exit.
        """
        self._stop_event.set()

    def stop(self):
        """Convenience: set the stop flag **and** wait up to 2 s."""
        self.request_stop()
        self.wait(2000)
