from PySide6.QtCore import QObject, Signal, QThread
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field


@dataclass
class DepRequirement:
    """A single dependency requirement entry."""
    name: str                    # Display name of the dependency
    norm_name: str = ""          # Normalized name for lookup
    constraint: str = ""         # Version constraint string (e.g. ">=2.0")
    is_installed: bool = True    # Whether this dep is actually installed in the env


@dataclass
class Package:
    name: str
    version: str
    latest_version: str = ""
    description: str = ""
    has_update: bool = False
    is_selected: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Dependency tree fields
    requires: List[DepRequirement] = field(default_factory=list)    # Direct dependencies
    required_by: List[str] = field(default_factory=list)            # Packages that depend on me
    is_top_level: bool = True           # Not depended on by any other installed package
    is_missing: bool = False            # Ghost dep: required but not installed
    version_constraint: str = ""        # Constraint imposed by the parent (display only)
    norm_name: str = ""                 # Normalized name for matching
    breaks_constraint: bool = False     # Latest version violates a version constraint from dependents
    build_variant_mismatch: bool = False  # Installed version has local suffix (+cu132) that differs from latest

    @property
    def is_outdated(self) -> bool:
        return self.has_update

    @property
    def has_children(self) -> bool:
        """Whether this package has any dependencies to show."""
        return len(self.requires) > 0

    def __post_init__(self):
        if not self.norm_name:
            import re
            self.norm_name = re.sub(r'[-_.]+', '-', self.name).lower()


@dataclass
class Environment:
    path: str
    name: str
    type: str  # system, venv, user
    python_version: str = ""
    runtime_name: str = ""
    runtime_version: str = ""
    runtime_cycle: str = ""
    runtime_latest_version: str = ""
    runtime_has_update: bool = False
    runtime_has_major_update: bool = False
    runtime_major_latest_version: str = ""
    runtime_update_error: str = ""
    tags: List[str] = field(default_factory=list)
    packages: List[Package] = None  # Will be initialized in __post_init__ or similar
    is_scanned: bool = False
    # Dependency graph: norm_name -> Package (for quick lookup)
    dep_graph: Dict[str, Package] = field(default_factory=dict)

    def __post_init__(self):
        if self.packages is None:
            self.packages = []

    def get_top_level_packages(self) -> List[Package]:
        """Return packages that are not depended on by any other package."""
        return [p for p in self.packages if p.is_top_level]

    def get_package_by_norm_name(self, norm_name: str) -> Optional[Package]:
        """Lookup a package by its normalized name."""
        return self.dep_graph.get(norm_name)

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
