import os
import subprocess
import threading
import re
import time
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

    def _log(self, msg: str, tag: str):
        # Emit each line in real-time so the console renders progressively
        # during long-running commands (pip install, npm install, etc.)
        self.log_msg.emit(msg, tag)

    def _flush_logs(self):
        """Retained for worker API compatibility."""

    def _run_command(
        self,
        cmd: list[str],
        cwd: str = None,
        capture_output: bool = False,
        stream_stdout: bool = True,
        stream_stderr: bool = True,
    ) -> subprocess.CompletedProcess:
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
        proc_env["FORCE_COLOR"] = "1"
        start_time = time.monotonic()
        last_output_at = [start_time]
        last_heartbeat_at = [start_time]
        heartbeat_interval = 5.0
        silence_hint_logged = [False]

        # ── heartbeat label based on command type ──
        _cmd_base = os.path.basename(str(cmd[0])).lower() if cmd else ""
        if _cmd_base in {"uv", "uv.exe", "pip", "pip.exe", "pip3", "pip3.exe"}:
            _heartbeat_label = "downloading/installing packages..."
        elif _cmd_base in {"npm", "npm.cmd", "npx", "npx.cmd", "pnpm", "pnpm.cmd", "yarn", "yarn.cmd"}:
            _heartbeat_label = "downloading npm packages..."
        elif _cmd_base in {"winget", "winget.exe"}:
            _heartbeat_label = "waiting for winget..."
        else:
            _heartbeat_label = "still running..."

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

        ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")

        captured_stdout = []
        captured_stderr = []

        def _emit_line(line: str, tag: str, capture_list, do_stream: bool = True):
            last_output_at[0] = time.monotonic()
            if capture_list is not None:
                capture_list.append(line)
            if do_stream:
                self._log(line, tag)

        def read_stream(stream, tag, capture_list=None, should_stream=True):
            """Read stdout/stderr in chunks, splitting on \\r and \\n.

            \\r-delimited segments are progress-bar updates (throttled to ~1/s).
            \\n-delimited segments are regular log lines (emitted immediately).
            """
            try:
                buf = ""
                pending = ""  # latest \r-delimited progress text
                last_pending_at = 0.0
                pending_min_interval = 0.8  # seconds

                def _flush_pending():
                    nonlocal pending, last_pending_at
                    if not pending:
                        return
                    _emit_line(pending, tag, capture_list, do_stream=should_stream)
                    last_pending_at = time.monotonic()
                    pending = ""

                while True:
                    chunk = stream.read(8192)
                    if not chunk:
                        break

                    buf += chunk

                    while True:
                        cr = buf.find("\r")
                        nl = buf.find("\n")
                        if cr == -1 and nl == -1:
                            break

                        pos = cr if nl == -1 else (nl if cr == -1 else min(cr, nl))
                        segment = buf[:pos]
                        term = buf[pos]
                        buf = buf[pos + 1:]

                        cleaned = ANSI_ESCAPE.sub("", segment).rstrip()
                        if not cleaned:
                            continue

                        if term == "\r":
                            pending = cleaned
                            now = time.monotonic()
                            if should_stream and now - last_pending_at >= pending_min_interval:
                                _emit_line(pending, tag, capture_list)
                                last_pending_at = now
                        else:  # \n
                            if pending:
                                _flush_pending()
                            else:
                                _emit_line(cleaned, tag, capture_list, do_stream=should_stream)

                    # periodic flush of pending progress (for long stretches of \r-only output)
                    if pending and should_stream:
                        now = time.monotonic()
                        if now - last_pending_at >= pending_min_interval:
                            _emit_line(pending, tag, capture_list)
                            last_pending_at = now

                # flush remaining
                _flush_pending()
                if buf:
                    cleaned = ANSI_ESCAPE.sub("", buf).rstrip()
                    if cleaned:
                        _emit_line(cleaned, tag, capture_list, do_stream=should_stream)
            except Exception:
                pass

        cap_out = captured_stdout if capture_output else None
        cap_err = captured_stderr if capture_output else None
        stdout_t = threading.Thread(target=read_stream, args=(process.stdout, "stdout", cap_out, stream_stdout), daemon=True)
        stderr_t = threading.Thread(target=read_stream, args=(process.stderr, "stderr", cap_err, stream_stderr), daemon=True)
        stdout_t.start()
        stderr_t.start()

        while True:
            returncode = process.poll()
            if returncode is not None:
                break

            now = time.monotonic()
            if now - last_output_at[0] >= heartbeat_interval and now - last_heartbeat_at[0] >= heartbeat_interval:
                elapsed = now - start_time
                self._log(f"... {_heartbeat_label} ({elapsed:0.0f}s)", "system")
                last_heartbeat_at[0] = now
                if not silence_hint_logged[0] and elapsed >= 30.0:
                    self._log(
                        "... still no output from subprocess — large download or build in progress",
                        "stderr",
                    )
                    silence_hint_logged[0] = True
            time.sleep(0.2)

        stdout_t.join(timeout=5)
        stderr_t.join(timeout=5)

        self.success = (returncode == 0)
        if capture_output:
            return subprocess.CompletedProcess(
                process.args, returncode,
                stdout="\n".join(captured_stdout),
                stderr="\n".join(captured_stderr),
            )
        return subprocess.CompletedProcess(process.args, returncode)
