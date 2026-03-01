from PySide6.QtCore import QObject, Signal, QThread
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class Package:
    name: str
    version: str
    latest_version: str = ""
    description: str = ""
    has_update: bool = False
    is_selected: bool = False

    @property
    def is_outdated(self) -> bool:
        return self.has_update
    
@dataclass
class Environment:
    path: str
    name: str
    type: str # system, venv, user
    python_version: str = ""
    packages: List[Package] = None # Will be initialized in __post_init__ or similar
    is_scanned: bool = False

    def __post_init__(self):
        if self.packages is None:
            self.packages = []

class BaseWorker(QObject):
    """Base worker for async operations"""
    finished = Signal(object) # Returns result
    progress = Signal(str)    # Returns status update
    error = Signal(str)       # Returns error message

    def run(self):
        raise NotImplementedError

class PackageManager(QObject):
    """Abstract Base Class for Package Managers (Pip, Npm, etc.)"""
    
    # Signals for UI updates
    env_scan_started = Signal(str)
    env_scanned = Signal(Environment) 
    package_updated = Signal(str, str) # pkg_name, env_path
    
    def __init__(self):
        super().__init__()
        self.environments: List[Environment] = []
    
    def list_environments(self) -> List[Environment]:
        """Return list of known environments (fast, no scanning)"""
        return self.environments
        
    def scan_environment(self, env: Environment):
        """Start async scan of an environment"""
        raise NotImplementedError

    def check_updates(self, env: Environment):
        """Check for updates in an environment"""
        raise NotImplementedError

    def update_package(self, pkg: Package, env: Environment):
        """Update a specific package"""
        raise NotImplementedError
