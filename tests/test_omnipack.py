import os
import pytest
from core.npm_spec import split_npm_spec
from core.terminal.command_renderer import ShellCommandRenderer
from core.config import ConfigManager
from version import __version__

def test_split_npm_spec():
    assert split_npm_spec("react") == ("react", None)
    assert split_npm_spec("react@18") == ("react", "18")
    assert split_npm_spec("@vue/cli") == ("@vue/cli", None)
    assert split_npm_spec("@vue/cli@latest") == ("@vue/cli", "latest")
    assert split_npm_spec("@scope/pkg@1.2.3") == ("@scope/pkg", "1.2.3")

def test_command_renderer_cmd():
    cmd = ["C:\\Program Files\\nodejs\\npm.cmd", "install", "react"]
    res = ShellCommandRenderer.render(cmd, "cmd.exe")
    assert res == '"C:\\Program Files\\nodejs\\npm.cmd" install react'

def test_command_renderer_pwsh():
    cmd = ["C:\\Program Files\\nodejs\\npm.cmd", "install", "react"]
    res = ShellCommandRenderer.render(cmd, "powershell.exe")
    assert res == "& 'C:\\Program Files\\nodejs\\npm.cmd' 'install' 'react'"

def test_command_renderer_pwsh_no_args():
    cmd = ["C:\\Program Files\\nodejs\\npm.cmd"]
    res = ShellCommandRenderer.render(cmd, "pwsh.exe")
    assert res == '& \'C:\\Program Files\\nodejs\\npm.cmd\''

def test_command_renderer_posix():
    cmd = ["/usr/local/bin/npm", "install", "react"]
    res = ShellCommandRenderer.render(cmd, "bash")
    assert res == "/usr/local/bin/npm install react"

def test_append_marker_cmd():
    import tempfile
    import os
    tmp = tempfile.gettempdir()
    marker_file = os.path.join(tmp, "MARKER.done").replace('/', '\\')
    res = ShellCommandRenderer.append_marker("echo foo", "MARKER", "cmd.exe", True)
    assert res == f"echo foo\necho %ERRORLEVEL% > \"{marker_file}\""

def test_append_marker_pwsh():
    import tempfile
    import os
    tmp = tempfile.gettempdir()
    marker_file = os.path.join(tmp, "MARKER.done").replace('/', '\\')
    res = ShellCommandRenderer.append_marker("echo foo", "MARKER", "powershell", True)
    assert res == f"echo foo ; $LASTEXITCODE | Out-File -FilePath '{marker_file}' -Encoding ascii"

def test_config_manager_corrupt_json(tmp_path, monkeypatch):
    import core.config
    monkeypatch.setattr(core.config, "get_persistent_root", lambda: tmp_path)
    config_file = tmp_path / "omnipack_config.json"
    config_file.write_text("{corrupt json", encoding="utf-8")
    
    mgr = ConfigManager()
    # It should not crash, it should load default
    assert mgr.config is not None
    assert mgr.config.version == __version__
    
    # Check if a backup was created
    backups = list(tmp_path.glob("omnipack_config.corrupt.*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{corrupt json"

def test_parse_winget_table():
    from core.winget_helpers import parse_winget_table
    output_en = """Name     Id       Version   Available  Source
----     --       -------   ---------  ------
OmniPack pkg_id   1.0.0     2.0.0      winget
"""
    res = parse_winget_table(output_en)
    assert len(res) == 1
    assert res[0]["name"] == "OmniPack"
    assert res[0]["id"] == "pkg_id"
    assert res[0]["available"] == "2.0.0"

    output_zh = """名称     ID       版本      可用       源
----     --       ----      ----       --
OmniPack pkg_id   1.0.0     2.0.0      winget
"""
    res_zh = parse_winget_table(output_zh)
    assert len(res_zh) == 1
    assert res_zh[0]["name"] == "OmniPack"

def test_marker_parser():
    import re
    buffer = "some output\n__OMNIPACK_OP_DONE_123__:-1\n"
    match = re.search(r"(?:^|[\r\n])(__OMNIPACK_OP_DONE_[a-f0-9]+__)(?::(-?\d+))?", buffer)
    assert match is not None
    assert match.group(1) == "__OMNIPACK_OP_DONE_123__"
    assert match.group(2) == "-1"

    buffer_no_code = "some output\n__OMNIPACK_OP_DONE_123__\n"
    match = re.search(r"(?:^|[\r\n])(__OMNIPACK_OP_DONE_[a-f0-9]+__)(?::(-?\d+))?", buffer_no_code)
    assert match is not None
    assert match.group(1) == "__OMNIPACK_OP_DONE_123__"
    assert match.group(2) is None

def test_pwsh_marker_execution():
    import subprocess
    import tempfile
    import os
    if os.name != "nt":
        return
    cmd = ["cmd.exe", "/c", "exit 42"]
    res = ShellCommandRenderer.render(cmd, "powershell")
    marker_cmd = ShellCommandRenderer.append_marker(res, "MARKER", "powershell", True)
    
    marker_file = os.path.join(tempfile.gettempdir(), "MARKER.done")
    if os.path.exists(marker_file):
        os.remove(marker_file)
        
    p = subprocess.run(["powershell.exe", "-NoProfile", "-Command", marker_cmd], capture_output=True, text=True)
    
    assert os.path.exists(marker_file)
    with open(marker_file, "r") as f:
        assert f.read().strip() == "42"
    os.remove(marker_file)

def test_import_all_core_modules():
    import ui.panels.pip_panel
    import ui.panels.npm_panel
    import ui.panels.winget_panel
    import managers.pip_manager
    import managers.npm_manager
    import managers.winget_manager
    import core.pypi_cache
    import core.runtime_update
    import ui.widgets.add_package_dialog

def test_terminal_write_ends_with_newline():
    from unittest.mock import MagicMock
    from ui.panels.npm_panel import NpmPanel
    
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    panel = NpmPanel(MagicMock(), None)
    panel.terminal = MagicMock()
    panel.npm_mgr.build_remove_command = MagicMock(return_value=["npm", "uninstall", "react"])
    
    env_mock = MagicMock()
    env_mock.path = "test_env"
    panel._find_env_by_path = MagicMock(return_value=env_mock)
    
    # Mock QMessageBox.question to return Yes
    from PySide6.QtWidgets import QMessageBox
    orig_question = QMessageBox.question
    QMessageBox.question = MagicMock(return_value=QMessageBox.Yes)
    
    try:
        panel._start_pkg_remove("react", "test_env")
        assert panel.terminal.write.called
        written_str = panel.terminal.write.call_args[0][0]
        # Must end with actual \r or \n character, not literal string \\n
        assert written_str.endswith("\r") or written_str.endswith("\n")
        assert not written_str.endswith("\\n")
    finally:
        QMessageBox.question = orig_question

def test_cmd_marker_execution():
    import subprocess
    import tempfile
    import os
    if os.name != "nt":
        return
    cmd = ["cmd.exe", "/c", "exit 42"]
    res = ShellCommandRenderer.render(cmd, "cmd.exe")
    marker_cmd = ShellCommandRenderer.append_marker(res, "MARKER", "cmd.exe", True)
    
    marker_file = os.path.join(tempfile.gettempdir(), "MARKER.done")
    if os.path.exists(marker_file):
        os.remove(marker_file)
        
    p = subprocess.run(["cmd.exe", "/Q"], input=marker_cmd + "\nexit\n", capture_output=True, text=True)
    
    assert os.path.exists(marker_file)
    with open(marker_file, "r") as f:
        assert f.read().strip() == "42"
    os.remove(marker_file)

def test_winget_fallback_commands():
    from ui.panels.winget_panel import WingetPanel
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    
    panel = WingetPanel(MagicMock(), None)
    panel.winget_mgr = MagicMock()
    panel.winget_mgr.build_update_command.return_value = ["winget", "upgrade", "foo"]
    panel.winget_mgr.build_update_fallback_install_command.return_value = ["winget", "install", "foo"]
    
    env_mock = MagicMock()
    
    # Test pwsh
    panel.terminal = MagicMock()
    panel.terminal._resolve_shell = MagicMock(return_value="powershell.exe")
    pwsh_cmd = panel._build_update_terminal_command(env_mock, {}, "MARKER")
    assert "if ($LASTEXITCODE -ne 0) { & 'winget' 'install' 'foo' }" in pwsh_cmd
    
    # Test cmd
    panel.terminal._resolve_shell = MagicMock(return_value="cmd.exe")
    cmd_cmd = panel._build_update_terminal_command(env_mock, {}, "MARKER")
    
    import tempfile
    import os
    tmp = tempfile.gettempdir()
    marker_file = os.path.join(tmp, "MARKER.done").replace('/', '\\')
    
    assert 'winget upgrade foo || winget install foo' in cmd_cmd
    assert f'\necho %ERRORLEVEL% > "{marker_file}"' in cmd_cmd

def test_npm_install_channel_parsing():
    from unittest.mock import MagicMock
    from ui.panels.npm_panel import NpmPanel
    from managers.npm_manager import NpmManager
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    
    panel = NpmPanel(MagicMock(), None)
    panel.terminal = MagicMock()
    
    env_mock = MagicMock()
    env_mock.path = "test_env"
    panel._get_env = MagicMock(return_value=env_mock)
    
    # We mock build_install_command to capture what it receives
    panel.npm_mgr.build_install_command = MagicMock(return_value=["npm", "install"])
    
    # 1. Plain package
    panel._start_pkg_install("test_env", "react")
    panel.npm_mgr.build_install_command.assert_called_with(env_mock, "react", channel="latest")
    
    # 2. Explicit tag
    panel._start_pkg_install("test_env", "react@beta")
    panel.npm_mgr.build_install_command.assert_called_with(env_mock, "react@beta", channel="latest")
    
    # 3. Scoped with tag
    panel._start_pkg_install("test_env", "@scope/pkg@next")
    panel.npm_mgr.build_install_command.assert_called_with(env_mock, "@scope/pkg@next", channel="latest")
    
    # Now let's test NpmManager's actual build_install_command
    npm_mgr = NpmManager(MagicMock())
    
    # 1. Plain package -> becomes pkg@latest
    cmd = npm_mgr.build_install_command(env_mock, "react", channel="latest")
    assert "react@latest" in cmd
    
    # 2. Scoped package with beta -> tag preserved
    cmd = npm_mgr.build_install_command(env_mock, "@scope/pkg@beta", channel="latest")
    assert "@scope/pkg@beta" in cmd
    
    # 3. Multiple packages -> mixed tags
    cmd = npm_mgr.build_install_command(env_mock, "vue @types/node@18", channel="latest")
    assert "vue@latest" in cmd
    assert "@types/node@18" in cmd

def test_winget_batch_write_path():
    from ui.panels.winget_panel import WingetPanel
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    panel = WingetPanel(MagicMock(), None)
    panel.winget_mgr = MagicMock()
    panel.terminal = MagicMock()

    panel._batch_update()
    assert panel.terminal.write.called

def test_pip_panel_fs_watcher_sync():
    from ui.panels.pip_panel import PipPanel
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    import os
    
    app = QApplication.instance() or QApplication([])
    config_mgr = MagicMock()
    panel = PipPanel(config_mgr, None)
    
    env_mock = MagicMock()
    env_mock.path = "/mock/venv"
    panel.pip_mgr.environments = [env_mock]
    
    panel._get_site_packages_path = MagicMock(return_value="/mock/venv/Lib/site-packages")
    panel._refresh_single_env = MagicMock()
    
    changed_path = os.path.normpath("/mock/venv/Lib/site-packages")
    panel._on_directory_changed(changed_path)
    
    norm_key = panel._path_key(env_mock.path)
    assert norm_key in panel._fs_debounce_timers
    
    panel._on_fs_debounce_timeout(env_mock)
    panel._refresh_single_env.assert_called_once_with(env_mock.path)


def test_pip_panel_update_all_uses_safe_version():
    from ui.panels.pip_panel import PipPanel
    from core.manager_base import Package
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    panel = PipPanel(MagicMock(), None)
    panel.terminal = MagicMock()
    panel.terminal._resolve_shell = MagicMock(return_value="powershell.exe")
    panel.pip_mgr.build_update_command = MagicMock(return_value=["uv", "pip", "install", "-U"])

    constrained = Package(
        name="A",
        version="1.6",
        latest_version="2.1",
        has_update=True,
        breaks_constraint=True,
        safe_update_version="1.9",
    )
    unconstrained = Package(
        name="B",
        version="1.0",
        latest_version="1.1",
        has_update=True,
    )
    blocked = Package(
        name="C",
        version="1.0",
        latest_version="2.0",
        has_update=True,
        breaks_constraint=True,
        safe_update_version="",
    )

    env_mock = MagicMock()
    env_mock.path = "test_env"
    env_mock.name = "Test Env"
    env_mock.is_scanned = True
    env_mock.packages = [constrained, unconstrained, blocked]
    panel._find_env_by_path = MagicMock(return_value=env_mock)

    panel._update_all_in_env(env_mock.path)

    panel.pip_mgr.build_update_command.assert_called_once_with(env_mock, ["A==1.9", "B"])


def test_pip_panel_batch_update_uses_safe_version():
    from ui.panels.pip_panel import PipPanel
    from core.manager_base import Package
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    panel = PipPanel(MagicMock(), None)
    panel.terminal = MagicMock()
    panel.terminal._resolve_shell = MagicMock(return_value="powershell.exe")
    panel.pip_mgr.build_update_command = MagicMock(return_value=["uv", "pip", "install", "-U"])

    constrained = Package(
        name="A",
        version="1.6",
        latest_version="2.1",
        has_update=True,
        is_selected=True,
        breaks_constraint=True,
        safe_update_version="1.9",
    )
    unconstrained = Package(
        name="B",
        version="1.0",
        latest_version="1.1",
        has_update=True,
        is_selected=True,
    )
    blocked = Package(
        name="C",
        version="1.0",
        latest_version="2.0",
        has_update=True,
        is_selected=True,
        breaks_constraint=True,
        safe_update_version="",
    )

    env_mock = MagicMock()
    env_mock.path = "test_env"
    env_mock.is_scanned = True
    env_mock.packages = [constrained, unconstrained, blocked]

    card_mock = MagicMock()
    card_mock.env = env_mock
    panel._env_cards = {"test_env": card_mock}

    panel._batch_update()

    panel.pip_mgr.build_update_command.assert_called_once_with(env_mock, ["A==1.9", "B"])

def test_npm_panel_fs_watcher_sync():
    from ui.panels.npm_panel import NpmPanel
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    import os
    
    app = QApplication.instance() or QApplication([])
    config_mgr = MagicMock()
    panel = NpmPanel(config_mgr, None)
    
    env_mock = MagicMock()
    env_mock.path = "/mock/project"
    panel.npm_mgr.environments = [env_mock]
    
    panel._refresh_single_env = MagicMock()
    
    changed_path = os.path.normpath(os.path.join(env_mock.path, "node_modules"))
    panel._on_directory_changed(changed_path)
    
    norm_key = panel._path_key(env_mock.path)
    assert norm_key in panel._fs_debounce_timers
    
    panel._on_fs_debounce_timeout(env_mock)
    panel._refresh_single_env.assert_called_once_with(env_mock.path)

def test_winget_real_write_path():
    from ui.panels.winget_panel import WingetPanel
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    
    panel = WingetPanel(MagicMock(), None)
    panel.winget_mgr = MagicMock()
    panel.winget_mgr.build_update_command.return_value = ["winget", "upgrade", "foo"]
    panel.winget_mgr.build_update_fallback_install_command.return_value = ["winget", "install", "foo"]
    
    env_mock = MagicMock()
    panel._get_env = MagicMock(return_value=env_mock)
    pkg_mock = MagicMock()
    pkg_mock.name = "foo"
    panel._find_package = MagicMock(return_value=pkg_mock)
    panel.terminal = MagicMock()
    panel.terminal._resolve_shell = MagicMock(return_value="cmd.exe")
    
    # This should not raise NameError
    panel._start_pkg_update("foo", "latest", "env")
    assert panel.terminal.write.called

def test_cmd_marker_pywinpty():
    import os
    if os.name != "nt":
        return
    import time
    from core.terminal.command_renderer import ShellCommandRenderer
    try:
        from winpty import PtyProcess
    except ImportError:
        return # Skip if pywinpty is not available
    
    cmd = ["cmd.exe", "/c", "exit 42"]
    res = ShellCommandRenderer.render(cmd, "cmd.exe")
    marker_cmd = ShellCommandRenderer.append_marker(res, "MARKER", "cmd.exe", True)
    
    pty = PtyProcess.spawn("cmd.exe")
    
    # Mock a terminal with write method that writes to pty
    class MockTerminal:
        def write(self, text):
            pty.write(text)
            
    ShellCommandRenderer.write_rendered_command(MockTerminal(), marker_cmd)
    
    # Wait for the marker file to appear
    import tempfile
    marker_file = os.path.join(tempfile.gettempdir(), "MARKER.done")
    if os.path.exists(marker_file):
        os.remove(marker_file)

    output = ""
    for _ in range(20):
        try:
            output += pty.read(1024)
        except Exception:
            pass
        if os.path.exists(marker_file):
            break
        time.sleep(0.1)
    
    pty.terminate()
    assert os.path.exists(marker_file)
    with open(marker_file, "r") as f:
        assert f.read().strip() == "42"
    os.remove(marker_file)

def test_winget_batch_write_path():
    from ui.panels.winget_panel import WingetPanel
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    
    panel = WingetPanel(MagicMock(), None)
    panel.winget_mgr = MagicMock()
    panel.winget_mgr.build_remove_command.return_value = ["winget", "uninstall", "foo"]
    
    env_mock = MagicMock()
    env_mock.path = "test_env"
    env_mock.is_scanned = True
    
    pkg_mock = MagicMock()
    pkg_mock.name = "foo"
    pkg_mock.is_selected = True
    env_mock.packages = [pkg_mock]
    
    card_mock = MagicMock()
    card_mock.env = env_mock
    panel._env_cards = {"test_env": card_mock}
    
    panel.terminal = MagicMock()
    panel.terminal._resolve_shell = MagicMock(return_value="cmd.exe")
    
    from PySide6.QtWidgets import QMessageBox
    orig_question = QMessageBox.question
    QMessageBox.question = MagicMock(return_value=QMessageBox.Yes)
    
    try:
        panel._batch_remove()
        assert panel.terminal.write.called
    finally:
        QMessageBox.question = orig_question

def test_winget_sanitize_output():
    from core.winget_helpers import _sanitize_terminal_output, parse_winget_table
    
    # Test ANSI removal
    raw = "\x1b[2J\x1b[H\x1b[?25lName      Id\n----      --\nFoo       bar"
    clean = _sanitize_terminal_output(raw)
    assert "Name      Id" in clean
    assert "\x1b" not in clean
    
    # Test \r and \b processing
    raw2 = "-\r\\\r|\r/\rName                                   Id\n-----------------------------------------  --\nFoo                                        bar"
    clean2 = _sanitize_terminal_output(raw2)
    assert clean2.startswith("Name")
    
    raw3 = "  - \b\b\b \\ \b\b\bName   Id\n----   --\nFoo    bar"
    clean3 = _sanitize_terminal_output(raw3)
    assert "Name" in clean3
    
    # Verify the table parser works with the dirty output
    # Here the raw output has garbage characters that shift the header right by 17 spaces
    raw4 = "   -    -    \\ Name                                   Id\n----------------------------------------------------------------------\nFoo                                        bar"
    rows = parse_winget_table(raw4, mode="installed")
    assert len(rows) == 1
    assert rows[0]["name"] == "Foo"
    assert rows[0]["id"] == "bar"
