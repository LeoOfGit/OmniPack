"""
OmniPack - Universal Package Manager
Entry point: Thin shell for admin elevation and app startup.
"""
import ctypes
import os
import sys

from PySide6.QtWidgets import QApplication

from core.utils import is_admin


def _is_truthy_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def hide_console():
    """Hide the console window if it exists."""
    if os.name == "nt":
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)


def _show_startup_error(title: str, message: str):
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
            return
        except Exception:
            pass

    try:
        sys.stderr.write(f"{title}\n{message}\n")
    except Exception:
        pass


def run_main():
    """Application entry point with global exception catching."""
    hide_console()
    if getattr(sys, "frozen", False) or _is_truthy_env("OMNIPACK_REQUIRE_ADMIN", False):
        os.environ["QT_LOGGING_RULES"] = "*.warning=false"

    try:
        app = QApplication(sys.argv)

        # Import window here to keep the entry point extremely light.
        from ui.main_window import OmniPackWindow

        window = OmniPackWindow()
        window.show()
        sys.exit(app.exec())
    except Exception:
        import traceback

        error_msg = traceback.format_exc()
        _show_startup_error("OmniPack Startup Error", error_msg)
        sys.exit(1)


if __name__ == "__main__":
    hide_console()

    # Default to elevation only for unfrozen Windows source runs.
    default_require = (os.name == "nt") and not getattr(sys, "frozen", False)
    require_admin = _is_truthy_env("OMNIPACK_REQUIRE_ADMIN", default_require)
    if os.name == "nt" and require_admin and not is_admin():
        params = " ".join([f'"{arg}"' for arg in sys.argv])
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 0)
        if ret <= 32:
            _show_startup_error(
                "OmniPack UAC",
                "Administrator elevation was cancelled or failed. "
                "You can continue with normal privileges, or set OMNIPACK_REQUIRE_ADMIN=0.",
            )
            sys.exit(1)
        sys.exit(0)

    if getattr(sys, "frozen", False) or "__nuitka_binary_dir" in globals():
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")

    run_main()
