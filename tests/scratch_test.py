import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.manager_base import Package, DepRequirement
from core.runtime_update import find_safe_update_version

def test_user_setuptools_case():
    pkg = Package(name="setuptools", version="80.10.2", latest_version="82.0.1")
    pkg.norm_name = "setuptools"
    pkg.required_by = ["b"]
    
    req = DepRequirement(name="setuptools", norm_name="setuptools", constraint="<82")
    b_pkg = Package(name="B", version="1.0")
    b_pkg.requires = [req]
    dep_graph = {"b": b_pkg}
    
    all_versions = ["82.0.1", "82.0.0", "81.0.0", "80.10.2", "80.10.1"]
    
    res = find_safe_update_version(pkg, dep_graph, all_versions)
    print(f"Result for user case: {res}")
    
test_user_setuptools_case()
