import os
import subprocess

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from core.network_proxy import merge_env_for_command
from core.winget_helpers import build_winget_command, find_winget_executable, parse_winget_table


class WingetTaskWorker(QThread):
    finished_task = Signal(str, object, str)

    def __init__(self, task_name: str, proxy_settings: dict, **kwargs):
        super().__init__()
        self.task_name = task_name
        self.proxy_settings = proxy_settings or {}
        self.kwargs = kwargs

    def _resolve_winget(self) -> str:
        custom = str(self.kwargs.get("winget_path", "") or "").strip()
        if custom:
            return custom
        return find_winget_executable() or "winget"

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env=merge_env_for_command(cmd, proxy_settings=self.proxy_settings),
        )

    def run(self):
        try:
            if self.task_name == "diagnostics":
                self.finished_task.emit(self.task_name, self._run_diagnostics(), "")
                return
            if self.task_name == "sources":
                cmd = build_winget_command("source", "list")
                cmd[0] = self._resolve_winget()
                result = self._run(cmd)
                rows = parse_winget_table(result.stdout, mode="source") if result.returncode == 0 else []
                error = "" if result.returncode == 0 else ((result.stderr or result.stdout or "").strip() or "winget source list failed")
                self.finished_task.emit(self.task_name, rows, error)
                return
            if self.task_name == "source-update":
                cmd = build_winget_command("source", "update")
                cmd[0] = self._resolve_winget()
                result = self._run(cmd)
                error = "" if result.returncode == 0 else ((result.stderr or result.stdout or "").strip() or "winget source update failed")
                self.finished_task.emit(self.task_name, result.stdout or result.stderr, error)
                return
            if self.task_name == "source-update-url":
                name = self.kwargs.get("name", "winget")
                arg = self.kwargs.get("arg", "")
                source_type = str(self.kwargs.get("source_type", "Microsoft.PreIndexed.Package")).strip()
                remove_cmd = build_winget_command("source", "remove", "--name", name)
                remove_cmd[0] = self._resolve_winget()
                self._run(remove_cmd)
                add_cmd = build_winget_command("source", "add", "--name", name, "--arg", arg)
                add_cmd[0] = self._resolve_winget()
                if source_type:
                    add_cmd.extend(["--type", source_type])
                if self.kwargs.get("explicit", False):
                    add_cmd.append("--explicit")
                result = self._run(add_cmd)
                error = "" if result.returncode == 0 else ((result.stderr or result.stdout or "").strip() or "winget source add failed")
                self.finished_task.emit(self.task_name, result.stdout or result.stderr, error)
                return

            if self.task_name == "source-reset":
                cmd = build_winget_command("source", "reset", "--force")
                cmd[0] = self._resolve_winget()
                result = self._run(cmd)
                error = "" if result.returncode == 0 else ((result.stderr or result.stdout or "").strip() or "winget source reset failed")
                self.finished_task.emit(self.task_name, result.stdout or result.stderr, error)
                return
            if self.task_name == "source-remove":
                cmd = build_winget_command("source", "remove", "--name", self.kwargs.get("name", ""))
                cmd[0] = self._resolve_winget()
                result = self._run(cmd)
                error = "" if result.returncode == 0 else ((result.stderr or result.stdout or "").strip() or "winget source remove failed")
                self.finished_task.emit(self.task_name, result.stdout or result.stderr, error)
                return
            if self.task_name == "source-add":
                cmd = build_winget_command("source", "add", "--name", self.kwargs.get("name", ""), "--arg", self.kwargs.get("arg", ""))
                cmd[0] = self._resolve_winget()
                source_type = str(self.kwargs.get("source_type", "")).strip()
                if source_type:
                    cmd.extend(["--type", source_type])
                if self.kwargs.get("explicit", False):
                    cmd.append("--explicit")
                result = self._run(cmd)
                error = "" if result.returncode == 0 else ((result.stderr or result.stdout or "").strip() or "winget source add failed")
                self.finished_task.emit(self.task_name, result.stdout or result.stderr, error)
                return
        except Exception as exc:
            self.finished_task.emit(self.task_name, None, str(exc))

    def _run_diagnostics(self) -> dict:
        winget_path = self._resolve_winget()
        version = ""
        source_count = 0
        source_error = ""
        if winget_path:
            ver_res = self._run([winget_path, "--version"])
            if ver_res.returncode == 0:
                version = (ver_res.stdout or ver_res.stderr or "").strip()
            source_res = self._run(build_winget_command("source", "list", winget_path=winget_path))
            if source_res.returncode == 0:
                source_count = len(parse_winget_table(source_res.stdout, mode="source"))
            else:
                source_error = (source_res.stderr or source_res.stdout or "").strip()
        return {
            "available": bool(winget_path),
            "path": winget_path,
            "version": version,
            "source_count": source_count,
            "source_error": source_error,
        }


class AddWingetSourceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add WinGet Source")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.arg_edit = QLineEdit()
        self.arg_edit.setPlaceholderText("https://example.test/cache")
        self.type_combo = QComboBox()
        self.type_combo.addItem("Microsoft.PreIndexed.Package")
        self.type_combo.addItem("Microsoft.Rest")
        self.explicit_check = QCheckBox("Explicit only")

        form.addRow("Name:", self.name_edit)
        form.addRow("Arg:", self.arg_edit)
        form.addRow("Type:", self.type_combo)
        form.addRow("", self.explicit_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "arg": self.arg_edit.text().strip(),
            "source_type": self.type_combo.currentText().strip(),
            "explicit": bool(self.explicit_check.isChecked()),
        }
