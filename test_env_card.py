import sys
from PySide6.QtWidgets import QApplication
from core.manager_base import Environment, Package
from ui.widgets.env_card_base import BaseEnvCard

app = QApplication(sys.argv)
env = Environment(path="test", name="test", type="venv", packages=[Package("test", "1.0")])
env.is_scanned = True
card = BaseEnvCard(env)
try:
    card._toggle_collapse()
except Exception as e:
    import traceback
    traceback.print_exc()
