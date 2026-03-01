import json
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict


@dataclass
class AppConfig:
    version: str = "1.0.0"

    # Pip
    pip_environments: List[dict] = field(default_factory=list)  # [{path, name, type}]

    # Npm
    npm_apps: Dict[str, dict] = field(default_factory=dict)     # {name: {display_name, channel, ...}}
    npm_channels: Dict[str, dict] = field(default_factory=dict) # {name: {label, suffix, color}}
    npm_settings: dict = field(default_factory=dict)            # {auto_refresh_on_start, theme, ...}

    # UI State
    window_geometry: str = ""
    window_state: str = ""
    pip_splitter_state: str = ""
    current_tab: int = 0


class ConfigManager:
    def __init__(self):
        self.config_path = Path(__file__).parent.parent / "omnipack_config.json"
        self.config = self._load_config()

    def _load_config(self) -> AppConfig:
        if not self.config_path.exists():
            return self._create_default_config()
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AppConfig(
                version=data.get("version", "1.0.0"),
                pip_environments=data.get("pip_environments", []),
                npm_apps=data.get("npm_apps", {}),
                npm_channels=data.get("npm_channels", {}),
                npm_settings=data.get("npm_settings", {}),
                window_geometry=data.get("window_geometry", ""),
                window_state=data.get("window_state", ""),
                pip_splitter_state=data.get("pip_splitter_state", ""),
                current_tab=data.get("current_tab", 0),
            )
        except Exception:
            return self._create_default_config()

    def _create_default_config(self) -> AppConfig:
        config = AppConfig()
        config.npm_channels = self._default_npm_channels()
        config.npm_settings = {"auto_refresh_on_start": True}
        return config

    @staticmethod
    def _default_npm_channels() -> Dict[str, dict]:
        return {
            "latest":  {"label": "Latest",  "suffix": "",         "color": "#4cc9f0"},
            "stable":  {"label": "Stable",  "suffix": "",         "color": "#4CAF50"},
            "preview": {"label": "Preview", "suffix": "@preview", "color": "#FF9800"},
            "nightly": {"label": "Nightly", "suffix": "@nightly", "color": "#9C27B0"},
            "beta":    {"label": "Beta",    "suffix": "@beta",    "color": "#2196F3"},
            "canary":  {"label": "Canary",  "suffix": "@canary",  "color": "#E91E63"},
            "next":    {"label": "Next",    "suffix": "@next",    "color": "#3b82f6"},
        }

    def save_config(self):
        data = asdict(self.config)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    # ── Pip helpers ──

    def add_pip_env(self, path: str, name: str, env_type: str):
        path = os.path.normpath(path)
        if any(os.path.normpath(e.get("path", "")) == path for e in self.config.pip_environments):
            return
        self.config.pip_environments.append({"path": path, "name": name, "type": env_type})
        self.save_config()

    def remove_pip_env(self, path: str):
        self.config.pip_environments = [e for e in self.config.pip_environments if e.get("path") != path]
        self.save_config()

    # ── Npm helpers ──

    def add_npm_app(self, name: str, app_data: dict):
        self.config.npm_apps[name] = app_data
        self.save_config()

    def update_npm_app(self, name: str, **kwargs):
        if name in self.config.npm_apps:
            self.config.npm_apps[name].update(kwargs)
            self.save_config()

    def remove_npm_app(self, name: str):
        if name in self.config.npm_apps:
            del self.config.npm_apps[name]
            self.save_config()
