"""
OmniPack — Universal Package Manager
Entry point: Thin shell for admin elevation and app startup.
"""
import sys
import os
import ctypes
from PySide6.QtWidgets import QApplication


def is_admin():
    """Check if the current process has administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def hide_console():
    """Hide the console window if it exists."""
    # Only relevant on Windows
    if os.name == 'nt':
        # Get the handle to the console window
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            # SW_HIDE = 0
            ctypes.windll.user32.ShowWindow(hwnd, 0)


def run_main():
    """Application entry point with global exception catching."""
    hide_console()
    # Suppress spurious QSS property warnings to keep the startup clean
    os.environ["QT_LOGGING_RULES"] = "*.warning=false"
    
    try:
        app = QApplication(sys.argv)
        
        # Import window here to keep the entry point extremely light
        from ui.main_window import OmniPackWindow
        
        window = OmniPackWindow()
        window.show()
        sys.exit(app.exec())
    except Exception:
        import traceback
        error_msg = traceback.format_exc()
        # Use Windows MessageBox to report startup crashes (prevent silent exits)
        ctypes.windll.user32.MessageBoxW(0, error_msg, "OmniPack Startup Error", 0x10)
        sys.exit(1)


if __name__ == "__main__":
    # Immediately attempt to hide the console if we were started from one
    hide_console()
    
    # If not running as admin, request elevation to ensure package managers work correctly.
    # CRITICAL: If frozen (packaged as EXE), we skip this because Nuitka's --windows-uac-admin 
    # handles elevation via manifest. Re-launching here can lose Nuitka's environment variables.
    if not is_admin() and not getattr(sys, "frozen", False):
        # Re-run the application with 'runas' verb to trigger Windows UAC
        params = ' '.join([f'"{arg}"' for arg in sys.argv])
        # nShow: 0 = SW_HIDE (Hidden)
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 0)
        sys.exit(0)

    # Redirect stdout/stderr to devnull to ensure no console allocation occurs
    if getattr(sys, "frozen", False) or "__nuitka_binary_dir" in globals():
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
        
    run_main()
