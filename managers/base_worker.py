import os
import subprocess
import threading
import re
from PySide6.QtCore import QThread, Signal
from core.config import ConfigManager
from core.network_proxy import merge_env_for_command

class BaseCmdWorker(QThread):
    """
    Common worker to execute command line subprocesses.
    Reads stdout/stderr asynchronously and strips ANSI codes.
    Subclasses should override the `run` method, but can use `_run_command`
    to execute their primary shell process.
    """
    log_msg = Signal(str, str)
    log_batch = Signal(list)

    def __init__(self):
        super().__init__()
        self.success = False
        self._log_buffer = []

    def _log(self, msg: str, tag: str):
        self._log_buffer.append((msg, tag))
        # Emit each line in real-time so the console renders progressively
        # during long-running commands (pip install, npm install, etc.)
        self.log_msg.emit(msg, tag)

    def _flush_logs(self):
        """Must be called in `finally` block of `run()` to emit batched logs."""
        if self._log_buffer:
            self.log_batch.emit(self._log_buffer)
            self._log_buffer.clear()

    def _run_command(self, cmd: list[str], cwd: str = None, capture_output: bool = False) -> subprocess.CompletedProcess:
        """
        Runs a command, streaming stdout/stderr line-by-line via self._log().

        When capture_output=True, the collected stdout/stderr text is included
        in the returned CompletedProcess so callers can parse JSON output.
        """
        self._log(f"> {' '.join(cmd)}", "cmd")

        proxy_settings = getattr(self, "proxy_settings", None)
        if proxy_settings is None:
            try:
                proxy_settings = getattr(ConfigManager().config, "proxy_settings", {}) or {}
            except Exception:
                proxy_settings = {}
        proc_env = merge_env_for_command(cmd, base_env=os.environ.copy(), proxy_settings=proxy_settings)

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=proc_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )

        ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\r")

        captured_stdout = []
        captured_stderr = []

        def read_stream(stream, tag, capture_list=None):
            try:
                for raw_line in stream:
                    line = ANSI_ESCAPE.sub("", raw_line).rstrip()
                    if line:
                        self._log(line, tag)
                        if capture_list is not None:
                            capture_list.append(line)
            except Exception:
                pass

        cap_out = captured_stdout if capture_output else None
        cap_err = captured_stderr if capture_output else None
        stdout_t = threading.Thread(target=read_stream, args=(process.stdout, "stdout", cap_out), daemon=True)
        stderr_t = threading.Thread(target=read_stream, args=(process.stderr, "stderr", cap_err), daemon=True)
        stdout_t.start()
        stderr_t.start()
        process.wait()
        stdout_t.join(timeout=5)
        stderr_t.join(timeout=5)

        self.success = (process.returncode == 0)
        if capture_output:
            return subprocess.CompletedProcess(
                process.args, process.returncode,
                stdout="\n".join(captured_stdout),
                stderr="\n".join(captured_stderr),
            )
        return subprocess.CompletedProcess(process.args, process.returncode)
