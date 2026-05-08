import json
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict
from core.utils import get_persistent_root


@dataclass
class AppConfig:
    version: str = "5"

    # Pip
    pip_environments: List[dict] = field(default_factory=list)  # [{path, name, type}]
    pip_settings: dict = field(default_factory=dict)            # {source_mode, index_url}

    # Npm
    npm_environments: List[dict] = field(default_factory=list)  # [{path, name, type, tags}]
    npm_apps: Dict[str, dict] = field(default_factory=dict)     # {name: {display_name, channel, ...}}
    npm_channels: Dict[str, dict] = field(default_factory=dict) # {name: {label, suffix, color}}
    npm_settings: dict = field(default_factory=dict)            # {auto_refresh_on_start, theme, ...}
    proxy_settings: dict = field(default_factory=dict)          # {enabled, http_proxy, https_proxy, targets}
    pypi_cache_settings: dict = field(default_factory=dict)     # {auto_refresh_on_start, stale_after_hours}

    # UI State
    window_geometry: str = ""
    window_state: str = ""
    pip_splitter_state: str = ""
    current_tab: int = 0
    
    # First-run scanning flags
    pip_scanned_once: bool = False
    npm_scanned_once: bool = False


class ConfigManager:
    def __init__(self):
        self.config_path = get_persistent_root() / "omnipack_config.json"
        self.config = self._load_config()
        self.normalize_settings()

    def _load_config(self) -> AppConfig:
        if not self.config_path.exists():
            return self._create_default_config()
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AppConfig(
                version=data.get("version", "1.0.0"),
                pip_environments=data.get("pip_environments", []),
                pip_settings=data.get("pip_settings", {}),
                npm_environments=data.get("npm_environments", []),
                npm_apps=data.get("npm_apps", {}),
                npm_channels=data.get("npm_channels", {}),
                npm_settings=data.get("npm_settings", {}),
                proxy_settings=data.get("proxy_settings", {}),
                pypi_cache_settings=data.get("pypi_cache_settings", {}),
                window_geometry=data.get("window_geometry", ""),
                window_state=data.get("window_state", ""),
                pip_splitter_state=data.get("pip_splitter_state", ""),
                current_tab=data.get("current_tab", 0),
                pip_scanned_once=data.get("pip_scanned_once", False),
                npm_scanned_once=data.get("npm_scanned_once", False),
            )
        except Exception:
            return self._create_default_config()

    def _create_default_config(self) -> AppConfig:
        config = AppConfig()
        config.pip_settings = self._default_pip_settings()
        config.npm_channels = self._default_npm_channels()
        config.npm_settings = self._default_npm_settings()
        config.proxy_settings = self._default_proxy_settings()
        config.pypi_cache_settings = self._default_pypi_cache_settings()
        return config

    @staticmethod
    def _default_pip_settings() -> Dict[str, str]:
        return {
            "source_mode": "system",  # system | official | custom
            "index_url": "",
            "uv_path": "",
        }

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

    @staticmethod
    def _default_npm_settings() -> Dict[str, object]:
        return {
            "auto_refresh_on_start": True,
            "source_mode": "system",  # system | official | custom
            "registry_url": "",
        }

    @staticmethod
    def _default_proxy_settings() -> Dict[str, object]:
        return {
            "enabled": False,
            "http_proxy": "",
            "https_proxy": "",
            "targets": {
                "pypi": True,
                "npm": False,
                "pip": False,
                "github": False,
            },
        }

    @staticmethod
    def _default_pypi_cache_settings() -> Dict[str, object]:
        return {
            "auto_refresh_on_start": True,
            "stale_after_hours": 24,
        }

    def normalize_settings(self):
        pip_defaults = self._default_pip_settings()
        if not isinstance(self.config.pip_settings, dict):
            self.config.pip_settings = {}
        for k, v in pip_defaults.items():
            self.config.pip_settings.setdefault(k, v)

        npm_defaults = self._default_npm_settings()
        if not isinstance(self.config.npm_settings, dict):
            self.config.npm_settings = {}
        for k, v in npm_defaults.items():
            self.config.npm_settings.setdefault(k, v)

        proxy_defaults = self._default_proxy_settings()
        if not isinstance(self.config.proxy_settings, dict):
            self.config.proxy_settings = {}
        for k, v in proxy_defaults.items():
            if k == "targets":
                current_targets = self.config.proxy_settings.get("targets", {})
                if not isinstance(current_targets, dict):
                    current_targets = {}
                for target_key, target_default in proxy_defaults["targets"].items():
                    current_targets.setdefault(target_key, target_default)
                self.config.proxy_settings["targets"] = current_targets
            else:
                self.config.proxy_settings.setdefault(k, v)

        cache_defaults = self._default_pypi_cache_settings()
        if not isinstance(self.config.pypi_cache_settings, dict):
            self.config.pypi_cache_settings = {}
        for k, v in cache_defaults.items():
            self.config.pypi_cache_settings.setdefault(k, v)
        auto_refresh = self.config.pypi_cache_settings.get("auto_refresh_on_start", True)
        if isinstance(auto_refresh, str):
            auto_refresh = auto_refresh.strip().lower() in {"1", "true", "yes", "on"}
        else:
            auto_refresh = bool(auto_refresh)
        self.config.pypi_cache_settings["auto_refresh_on_start"] = auto_refresh
        try:
            stale_hours = int(self.config.pypi_cache_settings.get("stale_after_hours", 24) or 24)
        except Exception:
            stale_hours = 24
        self.config.pypi_cache_settings["stale_after_hours"] = max(1, stale_hours)

    def save_config(self):
        try:
            data = asdict(self.config)
            # Ensure the directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            # Fallback logging to temp directory if main config fails
            import tempfile
            log_path = Path(tempfile.gettempdir()) / "omnipack_config_error.log"
            with open(log_path, "a", encoding="utf-8") as f:
                import datetime
                f.write(f"[{datetime.datetime.now()}] Failed to save config to {self.config_path}: {str(e)}\n")

    # ── Pip helpers ──

    @staticmethod
    def _norm_key(path: str) -> str:
        return os.path.normcase(os.path.normpath(str(path)))

    def add_pip_env(self, path: str, name: str, env_type: str, tags: list = None, save: bool = True):
        path = os.path.normpath(path)
        path_key = self._norm_key(path)
        if any(self._norm_key(e.get("path", "")) == path_key for e in self.config.pip_environments):
            return
        self.config.pip_environments.append({"path": path, "name": name, "type": env_type, "tags": tags or []})
        if save:
            self.save_config()

    def remove_pip_env(self, path: str):
        path_key = self._norm_key(path)
        self.config.pip_environments = [
            e for e in self.config.pip_environments
            if self._norm_key(e.get("path", "")) != path_key
        ]
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

    def add_npm_env(self, path: str, name: str, env_type: str = "project", tags: list = None, save: bool = True):
        path = os.path.normpath(path)
        path_key = self._norm_key(path)
        if any(self._norm_key(e.get("path", "")) == path_key for e in self.config.npm_environments):
            return
        self.config.npm_environments.append({"path": path, "name": name, "type": env_type, "tags": tags or []})
        if save:
            self.save_config()

    def remove_npm_env(self, path: str):
        path_key = self._norm_key(path)
        self.config.npm_environments = [
            e for e in self.config.npm_environments
            if self._norm_key(e.get("path", "")) != path_key
        ]
        self.save_config()
