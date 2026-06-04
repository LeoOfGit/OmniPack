import pytest
import json
import os
from unittest.mock import MagicMock, patch
import urllib.request
from io import BytesIO
from managers.pip_manager import _fetch_available_versions, Package, Environment

class DummyResponse:
    def __init__(self, body: bytes, headers: dict):
        self._body = body
        self._headers = headers

    def read(self):
        return self._body

    def getheader(self, key, default=""):
        # Very simple case-insensitive matching
        key_lower = key.lower()
        for k, v in self._headers.items():
            if k.lower() == key_lower:
                return v
        return default

    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

@pytest.fixture
def mock_worker():
    worker = MagicMock()
    # Mock uv failing to return versions
    cmd_res = MagicMock()
    cmd_res.returncode = 1
    cmd_res.stdout = ""
    worker._run_command.return_value = cmd_res
    return worker

@pytest.fixture
def mock_env():
    env = MagicMock()
    env.type = "venv"
    env.path = "/fake/env"
    return env

def test_fetch_versions_official_json(mock_worker, mock_env):
    # Official source fallback to JSON
    with patch("managers.pip_manager.proxy_urlopen") as mock_urlopen:
        mock_response = DummyResponse(
            body=json.dumps({"releases": {"1.0.0": [], "1.1.0": [], "1.2.0-alpha": []}}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        mock_urlopen.return_value = mock_response

        versions = _fetch_available_versions(
            mock_worker, "uv", mock_env, "/fake/python",
            source_args=["--index-url", "https://pypi.org/simple"],
            proxy_settings={},
            pkg_name="foo"
        )
        
        assert "1.1.0" in versions
        assert "1.0.0" in versions
        assert "1.2.0-alpha" not in versions  # prerelease filtered out
        assert len(versions) == 2

def test_fetch_versions_mirror_pep691_json(mock_worker, mock_env):
    # Mirror source fallback, returns PEP 691 JSON
    with patch("managers.pip_manager.proxy_urlopen") as mock_urlopen:
        mock_response = DummyResponse(
            body=json.dumps({"versions": ["2.0.0", "2.1.0", "3.0.0b1"]}).encode("utf-8"),
            headers={"Content-Type": "application/vnd.pypi.simple.v1+json"}
        )
        mock_urlopen.return_value = mock_response

        versions = _fetch_available_versions(
            mock_worker, "uv", mock_env, "/fake/python",
            source_args=["--index-url", "https://mirrors.aliyun.com/pypi/simple/"],
            proxy_settings={},
            pkg_name="bar"
        )
        
        assert "2.1.0" in versions
        assert "2.0.0" in versions
        assert "3.0.0b1" not in versions
        assert len(versions) == 2
        
def test_fetch_versions_mirror_html_regex(mock_worker, mock_env):
    # Mirror source fallback, returns HTML (regex parsing)
    with patch("managers.pip_manager.proxy_urlopen") as mock_urlopen:
        html = """
        <html><body>
        <a href="baz-1.0.0-py3-none-any.whl">baz-1.0.0-py3-none-any.whl</a>
        <a href="baz-1.0.1.tar.gz">baz-1.0.1.tar.gz</a>
        <a href="baz-2.0.0b1.zip">baz-2.0.0b1.zip</a>
        <a href="other-1.0.0.tar.gz">other-1.0.0.tar.gz</a>
        </body></html>
        """
        mock_response = DummyResponse(
            body=html.encode("utf-8"),
            headers={"Content-Type": "text/html; charset=utf-8"}
        )
        mock_urlopen.return_value = mock_response

        versions = _fetch_available_versions(
            mock_worker, "uv", mock_env, "/fake/python",
            source_args=["--index-url", "https://mirrors.aliyun.com/pypi/simple/"],
            proxy_settings={},
            pkg_name="baz"
        )
        
        assert "1.0.1" in versions
        assert "1.0.0" in versions
        assert "2.0.0b1" not in versions
        assert "other" not in versions
        assert len(versions) == 2


def test_fetch_versions_uses_python_pip_index(mock_env):
    worker = MagicMock()
    cmd_res = MagicMock()
    cmd_res.returncode = 0
    cmd_res.stdout = json.dumps({
        "name": "demo",
        "versions": ["2.1", "1.9", "1.6"],
        "latest": "2.1",
        "installed_version": "1.6",
    })
    worker._run_command.return_value = cmd_res

    versions = _fetch_available_versions(
        worker, "uv", mock_env, "/fake/python",
        source_args=["--index-url", "https://pypi.org/simple"],
        proxy_settings={},
        pkg_name="demo"
    )

    worker._run_command.assert_called_once()
    called_cmd = worker._run_command.call_args.args[0]
    assert os.path.basename(called_cmd[0]).lower() in {"pip", "pip.exe"}
    assert called_cmd[1:6] == ["--python", "/fake/python", "index", "versions", "demo"]
    assert "--json" in called_cmd
    assert "demo" in called_cmd
    assert versions[:2] == ["2.1", "1.9"]


def test_fetch_versions_prefers_available_versions_text_over_header_parentheses(mock_env):
    worker = MagicMock()
    cmd_res = MagicMock()
    cmd_res.returncode = 0
    cmd_res.stdout = (
        "mpmath (1.4.1)\n"
        "Available versions: 1.4.1, 1.4.0, 1.3.0, 1.2.1\n"
        "  INSTALLED: 1.2.1\n"
        "  LATEST:    1.4.1"
    )
    worker._run_command.return_value = cmd_res

    versions = _fetch_available_versions(
        worker, "uv", mock_env, "/fake/python",
        source_args=[],
        proxy_settings={},
        pkg_name="mpmath"
    )

    assert versions[:4] == ["1.4.1", "1.4.0", "1.3.0", "1.2.1"]
