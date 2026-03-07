from core.utils import get_app_root

def load_theme(theme_name="dark"):
    """
    Load a QSS file and return its contents as a string.
    """
    theme_path = get_app_root() / "ui" / "styles" / f"{theme_name}.qss"
    if theme_path.exists():
        with theme_path.open("r", encoding="utf-8") as f:
            return f.read()
    return ""
