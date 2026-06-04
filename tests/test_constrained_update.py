import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest
from types import SimpleNamespace
from core.manager_base import Package, DepRequirement
from core.runtime_update import find_safe_update_version, is_prerelease_version
from managers.pip_manager import _compute_breaks_constraint, _fetch_available_versions
from core.pip_spec import extract_pip_requirement_name

def test_find_safe_update_version_basic():
    pkg = Package(name="A", version="1.6", latest_version="2.1")
    pkg.norm_name = "a"
    pkg.required_by = ["b"]
    
    # 模拟 dep_graph
    # b 依赖 A < 2.0
    req = DepRequirement(name="A", norm_name="a", constraint="<2.0")
    b_pkg = Package(name="B", version="1.0")
    b_pkg.requires = [req]
    dep_graph = {"b": b_pkg}
    
    all_versions = ["2.1", "2.0", "1.9", "1.8", "1.6", "1.5"]
    
    res = find_safe_update_version(pkg, dep_graph, all_versions)
    assert res == "1.9"

def test_find_safe_update_version_no_safe_version():
    pkg = Package(name="A", version="1.6", latest_version="2.1")
    pkg.norm_name = "a"
    pkg.required_by = ["b"]
    
    req = DepRequirement(name="A", norm_name="a", constraint="<2.0")
    b_pkg = Package(name="B", version="1.0")
    b_pkg.requires = [req]
    dep_graph = {"b": b_pkg}
    
    # 在 1.6 和 2.0 之间没有可用版本
    all_versions = ["2.1", "2.0", "1.6", "1.5"]
    
    res = find_safe_update_version(pkg, dep_graph, all_versions)
    assert res == ""

def test_find_safe_update_version_multiple_constraints():
    pkg = Package(name="A", version="1.0", latest_version="3.0")
    pkg.norm_name = "a"
    pkg.required_by = ["b", "c"]
    
    req_b = DepRequirement(name="A", norm_name="a", constraint="<2.0")
    b_pkg = Package(name="B", version="1.0")
    b_pkg.requires = [req_b]
    
    req_c = DepRequirement(name="A", norm_name="a", constraint=">=1.5")
    c_pkg = Package(name="C", version="1.0")
    c_pkg.requires = [req_c]
    
    dep_graph = {"b": b_pkg, "c": c_pkg}
    
    all_versions = ["3.0", "2.0", "1.9", "1.5", "1.0"]
    
    res = find_safe_update_version(pkg, dep_graph, all_versions)
    assert res == "1.9"

def test_find_safe_update_version_conflict_constraints():
    pkg = Package(name="A", version="1.5", latest_version="3.0")
    pkg.norm_name = "a"
    pkg.required_by = ["b", "c"]
    
    req_b = DepRequirement(name="A", norm_name="a", constraint="<2.0")
    b_pkg = Package(name="B", version="1.0")
    b_pkg.requires = [req_b]
    
    req_c = DepRequirement(name="A", norm_name="a", constraint=">=2.5")
    c_pkg = Package(name="C", version="1.0")
    c_pkg.requires = [req_c]
    
    dep_graph = {"b": b_pkg, "c": c_pkg}
    
    all_versions = ["3.0", "2.6", "1.9", "1.5"]
    
    res = find_safe_update_version(pkg, dep_graph, all_versions)
    assert res == ""


def test_find_safe_update_version_skips_prereleases():
    pkg = Package(name="A", version="1.6", latest_version="2.1")
    pkg.norm_name = "a"
    pkg.required_by = ["b"]

    req = DepRequirement(name="A", norm_name="a", constraint="<2.0")
    b_pkg = Package(name="B", version="1.0")
    b_pkg.requires = [req]
    dep_graph = {"b": b_pkg}

    all_versions = ["2.1", "2.0rc1", "1.9rc1", "1.8"]

    res = find_safe_update_version(pkg, dep_graph, all_versions)
    assert res == "1.8"


def test_is_prerelease_version_detects_common_patterns():
    assert is_prerelease_version("2.0rc1") is True
    assert is_prerelease_version("1.5b2") is True
    assert is_prerelease_version("3.0.dev4") is True
    assert is_prerelease_version("1.9") is False
    assert is_prerelease_version("1.9+cpu") is False


def test_compute_breaks_constraint_resets_stale_safe_update_state():
    pkg = Package(name="A", version="1.6", latest_version="2.1", has_update=True)
    pkg.norm_name = "a"
    pkg.required_by = ["b"]
    pkg.breaks_constraint = True
    pkg.safe_update_version = "1.9"

    req = DepRequirement(name="A", norm_name="a", constraint="<3.0")
    b_pkg = Package(name="B", version="1.0")
    b_pkg.requires = [req]

    _compute_breaks_constraint([pkg], {"b": b_pkg})

    assert pkg.breaks_constraint is False
    assert pkg.safe_update_version == ""


def test_extract_pip_requirement_name_strips_pinned_version():
    assert extract_pip_requirement_name("numpy==1.26.4") == "numpy"
    assert extract_pip_requirement_name("requests") == "requests"


def test_fetch_available_versions_fallback_uses_proxy_and_filters_prereleases(monkeypatch):
    env = SimpleNamespace(path="demo-env", type="venv")
    worker = SimpleNamespace(
        _run_command=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="")
    )

    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'{"releases":{"2.0rc1":{},"1.9":{},"1.8b1":{},"1.8":{},"1.8+cpu":{}}}'
            )

    def fake_urlopen(url, timeout=None, headers=None, proxy_settings=None, force_proxy=False):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["proxy_settings"] = proxy_settings
        return FakeResponse()

    monkeypatch.setattr("managers.pip_manager.proxy_urlopen", fake_urlopen)

    versions = _fetch_available_versions(
        worker,
        "uv",
        env,
        "python",
        [],
        {"enabled": True},
        "demo",
    )

    assert versions == ["1.9", "1.8", "1.8+cpu"]
    assert captured["url"] == "https://pypi.org/pypi/demo/json"
    assert captured["timeout"] == 3
    assert captured["proxy_settings"] == {"enabled": True}
