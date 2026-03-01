from dataclasses import dataclass
from typing import List, Optional

@dataclass
class PackageInfo:
    """Standardized Package Info"""
    name: str
    version: str
    latest_version: str = ""
    description: str = ""
    is_outdated: bool = False
    is_selected: bool = False

@dataclass
class EnvInfo:
    """Environment Info"""
    path: str
    name: str
    env_type: str  # "system", "venv", "global", etc.
    version: str = ""
    packages: List[PackageInfo] = None
    is_scanned: bool = False

    def __post_init__(self):
        if self.packages is None:
            self.packages = []
