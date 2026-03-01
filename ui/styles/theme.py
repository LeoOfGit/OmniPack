"""
Theme Management for OmniPack
"""
import os

def load_theme(theme_name="dark"):
    """
    Load a QSS file and return its contents as a string.
    """
    theme_path = os.path.join(os.path.dirname(__file__), f"{theme_name}.qss")
    if os.path.exists(theme_path):
        with open(theme_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""
