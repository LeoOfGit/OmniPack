"""
OmniPack — Universal Package Manager
Entry point: Thin shell for admin elevation and app startup.
"""
import sys
import os
import ctypes
from PySide6.QtWidgets import QApplication


def run_main():
    """Application entry point with global exception catching."""
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
    # Check for Admin rights per standard fix requirements
    if not ctypes.windll.shell32.IsUserAnAdmin():
        python_exe = sys.executable
        if python_exe.lower().endswith("python.exe"):
            target_pw = python_exe.lower().replace("python.exe", "pythonw.exe")
            if os.path.exists(target_pw):
                python_exe = target_pw

        script = os.path.abspath(sys.argv[0])
        params = f'"{script}"'
        if len(sys.argv) > 1:
            params += " " + " ".join(f'"{arg}"' for arg in sys.argv[1:])

        # Re-launch current script with "runas" (elevated)
        # SW_SHOW (5) ensures the new window is visible
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", python_exe, params, None, 5
        )
        if ret > 32:
            sys.exit(0) # Elevated child started successfully, close this one
        else:
            # Elevation failed/denied, attempt running in current context anyway
            run_main()
    else:
        # Already running as admin
        run_main()
