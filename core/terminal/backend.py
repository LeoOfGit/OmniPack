"""
PTY Backend — Platform-specific pseudo-terminal implementations.

Provides a unified interface for PTY operations across Windows and Unix.
  • Windows: pywinpty (``winpty.PtyProcess``)
  • Unix:    stdlib ``pty`` module

The ``read()`` method always returns **bytes** so that the caller can feed
them directly into ``pyte.ByteStream``.
"""

import os


# ── Abstract base ───────────────────────────────────────────────────────

class BasePtyBackend:
    """Platform-agnostic interface for a PTY session."""

    def spawn(self, cmd: str | None = None, cwd: str | None = None,
              env: dict | None = None):
        """Spawn a shell process inside the PTY."""
        raise NotImplementedError

    def write(self, data: str):
        """Write a string to the PTY stdin (will be received by the shell)."""
        raise NotImplementedError

    def read(self, max_bytes: int = 4096) -> bytes:
        """Read raw bytes from the PTY stdout.  May block."""
        raise NotImplementedError

    def resize(self, cols: int, rows: int):
        """Inform the PTY of a new terminal size."""
        raise NotImplementedError

    def is_alive(self) -> bool:
        """Return *True* if the child process is still running."""
        raise NotImplementedError

    def close(self):
        """Terminate the child process and release resources (idempotent)."""
        raise NotImplementedError


# ── Platform implementations ────────────────────────────────────────────

if os.name == "nt":
    # ── Windows ──────────────────────────────────────────────────────────
    from winpty import PtyProcess  # pywinpty

    class _WinPtyBackend(BasePtyBackend):
        """Windows PTY backend powered by *pywinpty*."""

        def __init__(self):
            self._process: PtyProcess | None = None

        def spawn(self, cmd=None, cwd=None, env=None):
            cmd = cmd or "cmd.exe"
            cwd = cwd or os.path.expanduser("~")
            self._process = PtyProcess.spawn(cmd, cwd=cwd)

        def write(self, data: str):
            if self._process:
                self._process.write(data)

        def read(self, max_bytes: int = 4096) -> bytes:
            if not self._process:
                return b""
            try:
                data = self._process.read(max_bytes)
                # pywinpty returns str — encode for pyte.ByteStream
                if isinstance(data, str):
                    return data.encode("utf-8", errors="replace")
                return data or b""
            except (EOFError, OSError):
                return b""

        def resize(self, cols: int, rows: int):
            if self._process:
                try:
                    self._process.setwinsize(rows, cols)
                except Exception:
                    pass

        def is_alive(self) -> bool:
            if not self._process:
                return False
            try:
                return self._process.isalive()
            except Exception:
                return False

        def close(self):
            if self._process:
                try:
                    self._process.close()
                except Exception:
                    pass
                self._process = None

    _BackendImpl = _WinPtyBackend

else:
    # ── Unix (macOS / Linux) ─────────────────────────────────────────────
    import pty
    import signal
    import struct
    import fcntl
    import termios
    import select

    class _UnixPtyBackend(BasePtyBackend):
        """Unix PTY backend using the standard-library ``pty`` module."""

        def __init__(self):
            self._pid: int | None = None
            self._fd: int | None = None

        def spawn(self, cmd=None, cwd=None, env=None):
            shell = cmd or os.environ.get("SHELL", "/bin/bash")
            cwd = cwd or os.path.expanduser("~")

            self._pid, self._fd = pty.fork()

            if self._pid == 0:                     # child process
                try:
                    os.chdir(cwd)
                except Exception:
                    pass
                run_env = os.environ.copy()
                run_env["TERM"] = "xterm-256color"
                if env:
                    run_env.update(env)
                os.execvpe(shell, [shell], run_env)

        def write(self, data: str):
            if self._fd is not None:
                try:
                    os.write(self._fd, data.encode("utf-8"))
                except OSError:
                    pass

        def read(self, max_bytes: int = 4096) -> bytes:
            if self._fd is None:
                return b""
            try:
                ready, _, _ = select.select([self._fd], [], [], 0.1)
                if ready:
                    return os.read(self._fd, max_bytes)
                return b""
            except OSError:
                return b""

        def resize(self, cols: int, rows: int):
            if self._fd is not None:
                try:
                    winsize = struct.pack("HHHH", rows, cols, 0, 0)
                    fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)
                except Exception:
                    pass

        def is_alive(self) -> bool:
            if self._pid is None:
                return False
            try:
                pid, _ = os.waitpid(self._pid, os.WNOHANG)
                return pid == 0
            except ChildProcessError:
                return False

        def close(self):
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None
            if self._pid is not None:
                try:
                    os.kill(self._pid, signal.SIGHUP)
                    os.waitpid(self._pid, 0)
                except Exception:
                    pass
                self._pid = None

    _BackendImpl = _UnixPtyBackend


# ── Factory ─────────────────────────────────────────────────────────────

def create_pty_backend() -> BasePtyBackend:
    """Return a platform-appropriate PTY backend instance."""
    return _BackendImpl()
