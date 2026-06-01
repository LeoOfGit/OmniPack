import shlex
import subprocess
import os

class ShellCommandRenderer:
    @staticmethod
    def render(cmd_list: list[str], shell_name: str = "cmd.exe") -> str:
        """
        Renders a list of command arguments into a shell-safe string.
        """
        if not cmd_list:
            return ""

        shell_lower = os.path.basename(shell_name).lower()
        is_pwsh = "powershell" in shell_lower or "pwsh" in shell_lower
        is_posix = shell_lower in {"sh", "bash", "zsh", "fish", "dash"}

        if is_pwsh:
            return ShellCommandRenderer._render_pwsh(cmd_list)
        elif is_posix:
            return ShellCommandRenderer._render_posix(cmd_list)
        else:
            return ShellCommandRenderer._render_cmd(cmd_list)

    @staticmethod
    def _render_cmd(cmd_list: list[str]) -> str:
        return subprocess.list2cmdline(cmd_list)

    @staticmethod
    def _render_posix(cmd_list: list[str]) -> str:
        return " ".join(shlex.quote(str(arg)) for arg in cmd_list)

    @staticmethod
    def _render_pwsh(cmd_list: list[str]) -> str:
        # PowerShell renderer should safely quote each argument instead of using --%
        exe = str(cmd_list[0])
        exe_quoted = ShellCommandRenderer._pwsh_quote(exe)
        
        if len(cmd_list) == 1:
            return f"& {exe_quoted}"
            
        args_str = " ".join(ShellCommandRenderer._pwsh_quote(str(arg)) for arg in cmd_list[1:])
        return f"& {exe_quoted} {args_str}"

    @staticmethod
    def _pwsh_quote(text: str) -> str:
        if not text:
            return "''"
        if "'" not in text:
            return f"'{text}'"
        
        # If it has single quotes, we use double quotes
        escaped = text.replace('`', '``').replace('"', '`"').replace('$', '`$')
        return f'"{escaped}"'

    @staticmethod
    def append_marker(cmd_str: str, marker: str, shell_name: str = "cmd.exe", include_exit_code: bool = True) -> str:
        shell_lower = os.path.basename(shell_name).lower()
        is_pwsh = "powershell" in shell_lower or "pwsh" in shell_lower
        is_posix = shell_lower in {"sh", "bash", "zsh", "fish", "dash"}

        if is_pwsh:
            if include_exit_code:
                return f"{cmd_str} ; echo {marker}:$LASTEXITCODE"
            return f"{cmd_str} ; echo {marker}"
        elif is_posix:
            if include_exit_code:
                return f"{cmd_str} ; echo {marker}:$?"
            return f"{cmd_str} ; echo {marker}"
        else:
            # cmd.exe
            if include_exit_code:
                return f"{cmd_str}\necho {marker}:%ERRORLEVEL%"
            return f"{cmd_str}\necho {marker}"

    @staticmethod
    def write_rendered_command(terminal, cmd_str: str) -> None:
        """Write a rendered command to a terminal handling multi-line sequences."""
        for part in cmd_str.splitlines():
            terminal.write(f"{part}\r")
