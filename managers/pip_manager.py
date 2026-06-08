import os
import json
import re
import shutil
from PySide6.QtCore import Signal

from core.manager_base import PackageManager, Environment, Package
from core.dep_resolver import resolve_dependencies_subprocess, merge_dependency_info
from core.network_proxy import proxy_urlopen
from core.pip_spec import extract_pip_requirement_name
from core.runtime_update import (
    build_python_runtime_update_command,
    check_runtime_patch_update,
    check_version_satisfies_constraint,
    compare_versions,
    has_build_variant_mismatch,
    is_prerelease_version,
    parse_cycle,
    parse_python_version,
    find_safe_update_version,
)
from core.source_profiles import PYPI_OFFICIAL_INDEX
from core.utils import find_system_pythons, get_uv_path
from managers.base_worker import BaseCmdWorker

# Use 'uv' as the backend executor, just like in pip_manager.pyw
UV_CMD = "uv" 


def build_pip_source_args(config_mgr):
    settings = getattr(config_mgr.config, "pip_settings", {}) or {}
    mode = str(settings.get("source_mode", "system")).strip().lower()
    if mode == "official":
        return ["--index-url", PYPI_OFFICIAL_INDEX]
    if mode == "custom":
        url = str(settings.get("index_url", "")).strip()
        if url:
            return ["--index-url", url]
    return []


def _parse_target_loc(target: str) -> tuple[str, str]:
    if ":" in target:
        parts = target.split(":", 1)
        return parts[0], parts[1]
    return target, ""


def resolve_python_executable(env: Environment) -> str:
    env_path = os.path.normpath(str(env.path or "").strip().strip('"').strip("'"))
    if not env_path:
        return env_path

    # UNC/mapped-network paths can occasionally fail os.path.isfile() checks even
    # when they are valid. If the configured path itself looks like a Python
    # executable, use it directly instead of treating it as an environment root.
    exe_basename = os.path.basename(env_path).lower()
    if exe_basename in {"python", "python.exe", "python3", "python3.exe"}:
        return env_path

    if os.path.isfile(env_path):
        return env_path

    exe_name = "python.exe" if os.name == "nt" else "python"
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    py_exe = os.path.join(env_path, scripts_dir, exe_name)
    if not os.path.exists(py_exe):
        py_exe = os.path.join(env_path, "bin", "python")
    return os.path.normpath(py_exe)


def read_venv_cfg_version(py_exe: str) -> str:
    """Read version from pyvenv.cfg when available."""
    try:
        scripts_dir = os.path.dirname(py_exe)
        venv_root = os.path.dirname(scripts_dir)
        cfg_path = os.path.join(venv_root, "pyvenv.cfg")
        if not os.path.exists(cfg_path):
            return ""
        with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key_norm = key.strip().lower()
                if key_norm not in {"version", "version_info"}:
                    continue
                val_str = value.strip()
                if not val_str.lower().startswith("python"):
                    val_str = f"Python {val_str}"
                parsed = parse_python_version(val_str)
                if parsed:
                    return parsed
        # pyvenv.cfg exists but has no version/version_info key
        return ""
    except Exception as exc:
        import sys
        print(f"[OmniPack] read_venv_cfg_version error for {py_exe}: {exc}", file=sys.stderr)
        return ""

class PipManager(PackageManager):
    """
    Manages Python environments using 'uv'.
    Implements async scanning signals.
    """
    
    def __init__(self, config_mgr):
        super().__init__()
        self.config_mgr = config_mgr
        self._active_workers = []
        self._load_envs()

    def _load_envs(self):
        old_envs = {os.path.normcase(os.path.normpath(e.path)): e for e in self.environments}
        self.environments.clear()
        
        # 1. auto-discover system pythons strictly on FIRST RUN
        if not getattr(self.config_mgr.config, "pip_scanned_once", False):
            sys_pythons = find_system_pythons()
            for py in sys_pythons:
                py_path = os.path.normpath(py["path"])
                self.config_mgr.add_pip_env(
                    path=py_path, 
                    name=py["name"], 
                    env_type="system", 
                    tags=py.get("tags", []), 
                    save=False
                )
            self.config_mgr.config.pip_scanned_once = True
            self.config_mgr.save_config()

        # 2. loads from config
        if hasattr(self.config_mgr.config, "pip_environments"):
            for env_dict in self.config_mgr.config.pip_environments:
                path = os.path.normpath(env_dict.get("path", ""))
                if not path: continue
                name = env_dict.get("name")
                env_type = env_dict.get("type", "venv")
                tags = env_dict.get("tags", [])
                
                key = os.path.normcase(path)
                if key in old_envs:
                    env = old_envs[key]
                    env.path = path 
                    env.name = name 
                    env.type = env_type
                    env.tags = tags
                    self.environments.append(env)
                else:
                    self.environments.append(
                        Environment(path=path, name=name, type=env_type, tags=tags)
                    )
    
    def reload_envs(self):
        self._load_envs()
        
    log_msg = Signal(str, str) # text, tag
    log_batch = Signal(list)
    specific_packages_scanned = Signal(str, list, list) # env_path, found_pkgs, requested_names

    def scan_specific_packages(self, env: Environment, pkg_names: list[str]):
        """Runs a targeted background scan for specific packages."""
        if not env or not pkg_names:
            return
        uv_path = get_uv_path()
        source_args = build_pip_source_args(self.config_mgr)
        worker = PipPartialScanWorker(env, pkg_names, source_args=source_args, uv_path=uv_path)
        worker.packages_scanned.connect(self._on_partial_scan_done)
        worker.log_msg.connect(self.log_msg.emit)
        worker.log_batch.connect(self.log_batch.emit)
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _on_partial_scan_done(self, env_path: str, pkgs: list, requested_names: list):
        self.specific_packages_scanned.emit(env_path, pkgs, requested_names)

    def _cleanup_worker(self, worker):
        if worker in self._active_workers:
            self._active_workers.remove(worker)

    def _on_env_scanned(self, env: Environment):
        for i, e in enumerate(self.environments):
            if e.path == env.path:
                self.environments[i] = env
                break
        self.env_scanned.emit(env)

    def scan_environment(self, env: Environment, scan_mode: str = "full"):
        """Async scan trigger"""
        worker = ScanWorker(
            env,
            source_args=build_pip_source_args(self.config_mgr),
            uv_path=get_uv_path(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
            scan_mode=scan_mode,
        )
        worker.env_scanned.connect(self._on_env_scanned)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._active_workers.remove(worker) if worker in self._active_workers else None)
        worker.start() # Start QThread

    def build_install_command(self, env: Environment, pkg_names: str, force_reinstall: bool = False) -> list[str]:
        uv_path = get_uv_path(self.config_mgr)
        env_path = os.path.normpath(env.path)
        py_exe = resolve_python_executable(env)
        
        # Parse targets and determine if installing into user-site on system Pythons
        real_names = []
        use_user_target = False
        for name in pkg_names.split():
            pkg_name, loc = _parse_target_loc(name)
            real_names.append(pkg_name)
            if loc == "user":
                use_user_target = True
                
        from core.utils import is_admin
        if env.type == "system" and (use_user_target or not is_admin()):
            from core.utils import get_user_site_packages
            user_site = get_user_site_packages(py_exe)
            args = ["--target", user_site] if user_site else ["--system", "--python", env_path]
        else:
            args = ["--system", "--python", env_path] if env.type == "system" else ["--python", py_exe]
            
        cmd = [uv_path, "pip", "install"]
        cmd.extend(build_pip_source_args(self.config_mgr))
        if force_reinstall:
            cmd.append("--force-reinstall")
        cmd.extend(real_names)
        cmd.extend(args)
        return cmd

    def build_remove_command(self, env: Environment, pkg_names: list[str]) -> list[str]:
        uv_path = get_uv_path(self.config_mgr)
        env_path = os.path.normpath(env.path)
        py_exe = resolve_python_executable(env)
        
        real_names = []
        use_user_target = False
        for name in pkg_names:
            pkg_name, loc = _parse_target_loc(name)
            real_names.append(pkg_name)
            if loc == "user":
                use_user_target = True
                
        if use_user_target and env.type == "system":
            from core.utils import get_user_site_packages
            user_site = get_user_site_packages(py_exe)
            args = ["--target", user_site] if user_site else ["--system", "--python", env_path]
        else:
            args = ["--system", "--python", env_path] if env.type == "system" else ["--python", py_exe]
            
        cmd = [uv_path, "pip", "uninstall"] + real_names + args
        return cmd

    def build_update_command(self, env: Environment, pkg_names: list[str]) -> list[str]:
        uv_path = get_uv_path(self.config_mgr)
        env_path = os.path.normpath(env.path)
        py_exe = resolve_python_executable(env)
        
        real_names = []
        use_user_target = False
        for name in pkg_names:
            pkg_name, loc = _parse_target_loc(name)
            real_names.append(pkg_name)
            if loc == "user":
                use_user_target = True
                
        from core.utils import is_admin
        if env.type == "system" and (use_user_target or not is_admin()):
            from core.utils import get_user_site_packages
            user_site = get_user_site_packages(py_exe)
            args = ["--target", user_site] if user_site else ["--system", "--python", env_path]
        else:
            args = ["--system", "--python", env_path] if env.type == "system" else ["--python", py_exe]
            
        cmd = [uv_path, "pip", "install", "-U"] + build_pip_source_args(self.config_mgr) + real_names + args
        return cmd

    def update_runtime(self, env: Environment):
        worker = RuntimeUpdateWorker(env)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        self._active_workers.append(worker)
        def on_finished():
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            self.runtime_update_done.emit(
                env.path, worker.success, worker.result_message,
                worker.winget_failed, worker.target_version,
            )

        worker.finished.connect(on_finished)
        worker.start()

    update_done = Signal(str, str, bool) # env_path, pkg_name, success
    batch_update_done = Signal(str, list, bool) # env_path, pkg_names, success
    remove_done = Signal(str, str, bool) # env_path, pkg_name, success
    install_done = Signal(str, str, bool) # env_path, pkg_names, success
    runtime_update_done = Signal(str, bool, str, bool, str)
    # env_path, success, message, winget_failed, target_version



def _compute_breaks_constraint(pkgs: list, dep_graph: dict, version_fetcher=None):
    for pkg in pkgs:
        pkg.breaks_constraint = False
        pkg.safe_update_version = ""
        if not pkg.has_update or not pkg.latest_version or pkg.is_missing:
            continue
        for parent_norm in pkg.required_by:
            parent = dep_graph.get(parent_norm)
            if not parent:
                continue
            for dep_req in parent.requires:
                if dep_req.norm_name != pkg.norm_name or not dep_req.constraint:
                    continue
                if not check_version_satisfies_constraint(pkg.latest_version, dep_req.constraint):
                    pkg.breaks_constraint = True
                    break
            if pkg.breaks_constraint:
                break
        
        if pkg.breaks_constraint and version_fetcher:
            all_versions = version_fetcher(pkg.name)
            if all_versions:
                safe_ver = find_safe_update_version(pkg, dep_graph, all_versions)
                if safe_ver:
                    pkg.safe_update_version = safe_ver

class PipPartialScanWorker(BaseCmdWorker):
    packages_scanned = Signal(str, list, list)

    def __init__(self, env: Environment, pkg_names: list[str], source_args=None, uv_path="uv"):
        super().__init__()
        self.env = env
        self.pkg_names = pkg_names
        self.source_args = list(source_args or [])
        self.uv_path = uv_path

    def run(self):
        try:
            uv_path = self.uv_path
            py_exe = resolve_python_executable(self.env)
            args = ["--system", "--python", self.env.path] if self.env.type == "system" else ["--python", py_exe]

            requested_names = [extract_pip_requirement_name(name) for name in self.pkg_names]
            requested_names = [name for name in requested_names if name]
            target_names = set(requested_names)

            cmd = [uv_path, "pip", "list", "--format", "json"] + args
            res = self._run_command(cmd, capture_output=True, stream_stdout=False)

            pkgs = []
            
            # Calculate physical paths
            system_site_path = ""
            if self.env.path:
                if os.name == "nt":
                    system_site_path = os.path.normpath(os.path.join(self.env.path, "Lib", "site-packages"))
                else:
                    system_site_path = os.path.normpath(os.path.join(self.env.path, "lib", "python3.x", "site-packages"))

            def parse_partial_pkgs(stdout_str, source_type="system", install_path=""):
                parsed = []
                json_stdout = stdout_str[stdout_str.find('['):] if '[' in stdout_str else stdout_str
                if json_stdout.strip():
                    try:
                        end_idx = json_stdout.rfind(']')
                        if end_idx != -1:
                            json_stdout = json_stdout[:end_idx+1]
                        data = json.loads(json_stdout)
                        for item in data:
                            name = item.get("name", "")
                            if extract_pip_requirement_name(name) in target_names:
                                pkg = Package(name=name, version=item.get("version"))
                                pkg.metadata["location"] = source_type
                                if install_path:
                                    pkg.metadata["install_path"] = install_path
                                parsed.append(pkg)
                    except Exception:
                        pass
                return parsed

            if res.returncode == 0 and res.stdout:
                pkgs.extend(parse_partial_pkgs(res.stdout, "system", system_site_path))

            # Dual-path scanning for partial scan
            if self.env.type == "system":
                from core.utils import get_user_site_packages
                user_site = get_user_site_packages(py_exe)
                if user_site and os.path.exists(user_site):
                    cmd_user = [uv_path, "pip", "list", "--format", "json", "--target", user_site]
                    res_user = self._run_command(cmd_user, capture_output=True, stream_stdout=False)
                    if res_user.returncode == 0 and res_user.stdout:
                        pkgs.extend(parse_partial_pkgs(res_user.stdout, "user", user_site))
            self.packages_scanned.emit(self.env.path, pkgs, requested_names)
        except Exception as e:
            self._log(f"Partial Scan Error: {e}", "error")
        finally:
            self._flush_logs()


def _fetch_available_versions(worker, uv_path: str, env: Environment, py_exe: str, source_args: list[str], proxy_settings: dict, pkg_name: str) -> list[str]:
    import functools

    pip_cmd = shutil.which("pip") or "pip"
    cmd = [pip_cmd, "--python", py_exe, "index", "versions", pkg_name, "--json"] + list(source_args or [])
    res = worker._run_command(cmd, capture_output=True, stream_stdout=False)
    versions = []

    if res.returncode == 0 and res.stdout:
        try:
            payload = json.loads(res.stdout.strip())
            if isinstance(payload, dict):
                v_list = payload.get("versions", []) or []
                versions.extend([str(v).strip() for v in v_list if str(v).strip()])
        except json.JSONDecodeError:
            if "Available versions:" in res.stdout:
                m2 = re.search(r"Available versions:\s*(.*)", res.stdout)
                if m2:
                    v_list = m2.group(1).split(",")
                    versions.extend([v.strip() for v in v_list if v.strip()])
            else:
                m = re.search(r"\((.*?)\)", res.stdout)
                if m:
                    v_list = m.group(1).split(",")
                    versions.extend([v.strip() for v in v_list if v.strip()])

    if not versions:
        from core.source_profiles import PYPI_OFFICIAL_INDEX
        import urllib.request

        index_url = PYPI_OFFICIAL_INDEX
        if source_args:
            for i, arg in enumerate(source_args):
                if arg == "--index-url" and i + 1 < len(source_args):
                    index_url = source_args[i + 1]
                    break
        index_url = index_url.rstrip("/")
        is_official = "pypi.org" in index_url.lower()

        try:
            if is_official:
                with proxy_urlopen(
                    f"https://pypi.org/pypi/{pkg_name}/json",
                    timeout=3,
                    proxy_settings=proxy_settings,
                ) as response:
                    data = json.loads(response.read())
                versions = [
                    version
                    for version in data.get("releases", {}).keys()
                    if not is_prerelease_version(version)
                ]
            else:
                req = urllib.request.Request(
                    f"{index_url}/{pkg_name}/",
                    headers={"Accept": "application/vnd.pypi.simple.v1+json, text/html;q=0.1"}
                )
                with proxy_urlopen(
                    req,
                    timeout=3,
                    proxy_settings=proxy_settings,
                ) as response:
                    content_type = response.getheader("Content-Type", "")
                    body = response.read()

                if "application/vnd.pypi.simple.v1+json" in content_type:
                    data = json.loads(body)
                    versions = [v for v in data.get("versions", []) if not is_prerelease_version(v)]
                else:
                    html = body.decode("utf-8", errors="ignore")
                    pkg_prefix_dash = pkg_name.replace('-', '_').lower() + '-'
                    pkg_prefix_norm = pkg_name.lower() + '-'
                    
                    found_versions = set()
                    for match in re.finditer(r'<a[^>]*>([^<]+)</a>', html, re.IGNORECASE):
                        filename = match.group(1).strip()
                        if filename.endswith(".whl"):
                            parts = filename.split('-')
                            if len(parts) >= 2:
                                found_versions.add(parts[1])
                        elif filename.endswith(".tar.gz") or filename.endswith(".zip"):
                            base = filename.rsplit('.', 2)[0] if filename.endswith(".tar.gz") else filename.rsplit('.', 1)[0]
                            base_lower = base.lower()
                            if base_lower.startswith(pkg_prefix_dash):
                                found_versions.add(base[len(pkg_prefix_dash):])
                            elif base_lower.startswith(pkg_prefix_norm):
                                found_versions.add(base[len(pkg_prefix_norm):])
                    
                    versions = [v for v in found_versions if not is_prerelease_version(v)]
        except Exception as e:
            import sys
            print(f"[OmniPack] Fallback API error for {pkg_name}: {e}", file=sys.stderr)


    if versions:
        unique_versions = list(set(versions))
        unique_versions.sort(key=functools.cmp_to_key(compare_versions), reverse=True)
        versions = sorted(
            unique_versions,
            key=lambda version: (
                [int(x) for x in re.findall(r"\d+", str(version or ""))][:4],
                1 if "+" not in str(version or "") else 0,
                str(version or "").lower(),
            ),
            reverse=True,
        )

    return versions


def _restore_package_state(current_pkgs: list[Package], previous_pkgs: list[Package], include_tree: bool = False, restore_update_state: bool = True):
    previous_map = {
        getattr(pkg, "norm_name", ""): pkg
        for pkg in (previous_pkgs or [])
        if getattr(pkg, "norm_name", "")
    }
    if not previous_map:
        return

    for pkg in current_pkgs:
        previous = previous_map.get(getattr(pkg, "norm_name", ""))
        if not previous:
            continue

        pkg.is_selected = getattr(previous, "is_selected", False)
        pkg.metadata = dict(getattr(previous, "metadata", {}) or {})

        if restore_update_state and getattr(previous, "version", "") == getattr(pkg, "version", ""):
            pkg.latest_version = getattr(previous, "latest_version", "")
            pkg.has_update = getattr(previous, "has_update", False)
            pkg.breaks_constraint = getattr(previous, "breaks_constraint", False)
            pkg.build_variant_mismatch = getattr(previous, "build_variant_mismatch", False)
            pkg.safe_update_version = getattr(previous, "safe_update_version", "")

        if include_tree:
            pkg.requires = list(getattr(previous, "requires", []) or [])
            pkg.required_by = list(getattr(previous, "required_by", []) or [])
            pkg.is_top_level = getattr(previous, "is_top_level", True)


def _uv_output_reports_package_changes(output: str) -> bool:
    if not output:
        return False

    markers = (
        "Prepared ",
        "Installed ",
        "Uninstalled ",
        "\n + ",
        "\n - ",
    )
    return any(marker in output for marker in markers)


class ScanWorker(BaseCmdWorker):
    """Worker thread to run 'uv pip list' and 'outdated'"""
    
    env_scanned = Signal(Environment) 

    def __init__(self, env: Environment, source_args=None, uv_path="uv", proxy_settings=None, scan_mode: str = "full"):
        super().__init__()
        self.env = env
        self.source_args = list(source_args or [])
        self.uv_path = uv_path
        self.proxy_settings = proxy_settings or {}
        self.scan_mode = scan_mode if scan_mode in {"full", "fast"} else "full"
    
    def run(self):
        try:
            previous_pkgs = list(getattr(self.env, "packages", []) or [])
            fast_mode = self.scan_mode == "fast"

            # Determine python executable for this env
            env_path = os.path.normpath(self.env.path)
            py_exe = resolve_python_executable(self.env)
            self._log(f"Scanning {self.env.name} using {py_exe}...", "system")
            
            if not os.path.exists(py_exe):
                self._log(f"Error: Python executable not found at {py_exe}", "error")
                return

            # 1. Version Check
            ver_cmd = [py_exe, "--version"]
            res = self._run_command(ver_cmd, capture_output=True)
            raw_ver = (res.stdout or "").strip() or (res.stderr or "").strip()
            py_ver = parse_python_version(raw_ver) if res.returncode == 0 and raw_ver else ""

            # Always prefer pyvenv.cfg version when present.
            # On Windows the venv's python.exe is a redirector that loads the system
            # python DLL — so python --version reports the SYSTEM version after a
            # winget upgrade, not the venv's actual configured version.
            cfg_ver = read_venv_cfg_version(py_exe)
            if cfg_ver:
                if py_ver and compare_versions(cfg_ver, py_ver) != 0:
                    self._log(
                        f"Detected venv metadata version {cfg_ver} (runtime reports {py_ver}); using metadata version for display.",
                        "stderr",
                    )
                py_ver = cfg_ver
            if not py_ver:
                py_ver = "?"

            cycle, latest_ver, runtime_has_update, runtime_err = check_runtime_patch_update(
                "python",
                py_ver,
                proxy_settings=self.proxy_settings,
            )
            if runtime_has_update:
                self._log(
                    f"Python runtime update available in {self.env.name}: {py_ver} -> {latest_ver}",
                    "system",
                )
            elif runtime_err:
                self._log(f"Python runtime update check skipped: {runtime_err}", "stderr")
            
            # 2. List Packages
            uv_path = self.uv_path
            # Verify uv
            try:
                uv_cmd = [uv_path, "--version"]
                uv_res = self._run_command(uv_cmd, capture_output=True)
            except FileNotFoundError:
                self._log("Error: 'uv' command not found. Please install uv (https://gh.io/uv).", "error")
                return

            args = ["--system", "--python", self.env.path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "list", "--format", "json"] + args
            res = self._run_command(cmd, capture_output=True, stream_stdout=False)

            # Calculate system site-packages physical path
            system_site_path = ""
            if self.env.path:
                if os.name == "nt":
                    system_site_path = os.path.normpath(os.path.join(self.env.path, "Lib", "site-packages"))
                else:
                    system_site_path = os.path.normpath(os.path.join(self.env.path, "lib", f"python{py_ver[:4] if py_ver else '3.x'}", "site-packages"))

            pkgs = []

            def parse_packages_to_list(stdout_str, source_type="system", install_path=""):
                parsed = []
                json_stdout = stdout_str[stdout_str.find('['):] if '[' in stdout_str else stdout_str
                if json_stdout.strip():
                    try:
                        data = json.loads(json_stdout)
                        for item in data:
                            pkg_name = item.get("name")
                            pkg_version = item.get("version")
                            if pkg_name:
                                pkg = Package(name=pkg_name, version=pkg_version)
                                pkg.metadata["location"] = source_type
                                if install_path:
                                    pkg.metadata["install_path"] = install_path
                                parsed.append(pkg)
                    except Exception as je:
                        self._log(f"JSON Parse Error: {je}", "error")
                return parsed

            if res.returncode == 0 and res.stdout:
                system_pkgs = parse_packages_to_list(res.stdout, source_type="system", install_path=system_site_path)
                self._log(f"Loaded JSON for {len(system_pkgs)} system packages.", "stdout")
                pkgs.extend(system_pkgs)

            # Dual-path scanning: include user-site packages for system environments
            if self.env.type == "system":
                from core.utils import get_user_site_packages
                user_site = get_user_site_packages(py_exe)
                if user_site and os.path.exists(user_site):
                    self._log(f"Scanning user site-packages at {user_site}...", "system")
                    cmd_user = [uv_path, "pip", "list", "--format", "json", "--target", user_site]
                    res_user = self._run_command(cmd_user, capture_output=True, stream_stdout=False)
                    if res_user.returncode == 0 and res_user.stdout:
                        user_pkgs = parse_packages_to_list(res_user.stdout, source_type="user", install_path=user_site)
                        self._log(f"Loaded JSON for {len(user_pkgs)} user packages.", "stdout")
                        pkgs.extend(user_pkgs)

            outdated_map = {}
            count_updates = 0

            if fast_mode:
                self._log(f"Fast refresh for {self.env.name}: skipping update check and dependency tree rebuild.", "system")
                _restore_package_state(pkgs, previous_pkgs, include_tree=True)
                self.env.dep_graph = {pkg.norm_name: pkg for pkg in pkgs}
                count_updates = sum(1 for pkg in pkgs if getattr(pkg, "has_update", False))
            else:
                # 3. Check Updates
                self._log("Checking for package updates...", "system")
                cmd_outdated = [uv_path, "pip", "list", "--outdated", "--format", "json"] + self.source_args + args
                res_outdated = self._run_command(cmd_outdated, capture_output=True, stream_stdout=False)

                def parse_outdated_json(stdout_str):
                    mapping = {}
                    json_stdout = stdout_str[stdout_str.find('['):] if '[' in stdout_str else stdout_str
                    if json_stdout.strip():
                        try:
                            data = json.loads(json_stdout)
                            for item in data:
                                name = item.get("name", "")
                                latest = item.get("latest_version", "")
                                if name and latest:
                                    mapping[name] = latest
                        except Exception:
                            pass
                    return mapping

                if res_outdated.returncode == 0 and res_outdated.stdout:
                    system_outdated = parse_outdated_json(res_outdated.stdout)
                    self._log(f"Loaded JSON for {len(system_outdated)} outdated system packages.", "stdout")
                    outdated_map.update(system_outdated)

                # Check outdated user-site packages for system environments
                if self.env.type == "system":
                    from core.utils import get_user_site_packages
                    user_site = get_user_site_packages(py_exe)
                    if user_site and os.path.exists(user_site):
                        cmd_outdated_user = [uv_path, "pip", "list", "--outdated", "--format", "json", "--target", user_site] + self.source_args
                        res_outdated_user = self._run_command(cmd_outdated_user, capture_output=True, stream_stdout=False)
                        if res_outdated_user.returncode == 0 and res_outdated_user.stdout:
                            user_outdated = parse_outdated_json(res_outdated_user.stdout)
                            self._log(f"Loaded JSON for {len(user_outdated)} outdated user packages.", "stdout")
                            outdated_map.update(user_outdated)

                # Update objects
                for pkg in pkgs:
                    if pkg.name in outdated_map:
                        pkg.latest_version = outdated_map[pkg.name]
                        pkg.has_update = True
                        count_updates += 1
                        if has_build_variant_mismatch(pkg.version, pkg.latest_version):
                            pkg.build_variant_mismatch = True

                # 4. Resolve dependency tree
                self._log(f"Resolving dependency tree for {self.env.name}...", "system")
                dep_data = resolve_dependencies_subprocess(py_exe)
                if dep_data:
                    pkgs, dep_graph = merge_dependency_info(pkgs, dep_data)
                    self.env.dep_graph = dep_graph

                    # Compute breaks_constraint for packages with updates
                    version_cache = {}
                    
                    def fetch_versions(pkg_name: str) -> list[str]:
                        if pkg_name in version_cache:
                            return version_cache[pkg_name]
                        versions = _fetch_available_versions(
                            self,
                            uv_path,
                            self.env,
                            py_exe,
                            self.source_args,
                            self.proxy_settings,
                            pkg_name,
                        )
                        version_cache[pkg_name] = versions
                        return versions

                    _compute_breaks_constraint(pkgs, dep_graph, version_fetcher=fetch_versions)
                    _restore_package_state(
                        pkgs,
                        previous_pkgs,
                        include_tree=False,
                        restore_update_state=False,
                    )

                    top_level_count = sum(1 for p in pkgs if p.is_top_level and not p.is_missing)
                    missing_count = sum(1 for p in pkgs if p.is_missing)
                    self._log(f"Dependency tree: {top_level_count} top-level, {len(pkgs) - top_level_count} transitive"
                              + (f", {missing_count} missing" if missing_count else ""), "stdout")
                else:
                    self._log(f"Warning: Could not resolve dependency tree for {self.env.name}", "stderr")
                    _restore_package_state(pkgs, previous_pkgs, include_tree=True)
                    # Fallback: treat all as top-level
                    self.env.dep_graph = {pkg.norm_name: pkg for pkg in pkgs}

            self.env.python_version = py_ver
            self.env.runtime_name = "Python"
            self.env.runtime_version = py_ver
            self.env.runtime_cycle = cycle or parse_cycle("python", py_ver)
            self.env.runtime_latest_version = latest_ver
            self.env.runtime_has_update = runtime_has_update
            self.env.runtime_update_error = runtime_err
            self.env.packages = pkgs
            self.env.is_scanned = True
            self.env._last_scan_mode = self.scan_mode
             
            self._log(f"✓ Found {len(pkgs)} packages, {count_updates} updates in {self.env.name}", "success")
             
        except Exception as e:
            import traceback
            self._log(f"Scan Error for {self.env.path}: {e}", "error")
            self._log(traceback.format_exc(), "stderr")
            if 'pkgs' in locals():
                self.env.packages = pkgs
                self.env.dep_graph = {
                    pkg.norm_name: pkg for pkg in pkgs if getattr(pkg, "norm_name", "")
                }
            self.env.is_scanned = True 
            self.env._last_scan_mode = self.scan_mode
             
        finally:
            self.env_scanned.emit(self.env)
            self._flush_logs()


class RuntimeUpdateWorker(BaseCmdWorker):
    """Worker to update Python runtime itself (not packages)."""

    def __init__(self, env: Environment):
        super().__init__()
        self.env = env
        self.result_message = ""
        self.winget_failed = False
        self.target_version = ""

    def _detect_winget_failure(self, result, cmd: list[str]) -> bool:
        """Return True if the failure looks like a winget source issue."""
        is_winget_cmd = os.path.basename(str(cmd[0])).lower() in {"winget", "winget.exe"}
        if not is_winget_cmd:
            return False
        combined = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
        return "failed when opening source" in combined or "0x8d15000f" in combined

    def run(self):
        try:
            current_ver = self.env.runtime_version or self.env.python_version
            cycle = self.env.runtime_cycle or parse_cycle("python", current_ver)
            latest = self.env.runtime_latest_version
            self.target_version = latest or ""
            self._log(
                f"Updating Python runtime for {self.env.name} ({current_ver or 'unknown'}"
                + (f" -> {latest}" if latest else "")
                + ")...",
                "system",
            )

            commands, reason = build_python_runtime_update_command(
                self.env.type, self.env.path, cycle, self.target_version
            )
            if not commands:
                self.success = False
                self.result_message = reason or "No runnable command for Python runtime update."
                self._log(self.result_message, "error")
                return

            multi_step = len(commands) > 1
            for i, cmd in enumerate(commands):
                if multi_step:
                    if i == 0:
                        self._log("Step 1/2: Updating system Python via winget...", "system")
                    else:
                        self._log("Step 2/2: Upgrading virtual environment...", "system")

                result = self._run_command(cmd, capture_output=True)

                # Detect silent file-lock failures during venv upgrade
                if "venv" in cmd and "--upgrade" in cmd:
                    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
                    if "Unable to copy" in output and "python.exe" in output:
                        self.success = False
                        self.result_message = (
                            "Virtual environment update partially failed: 'python.exe' is locked by another process "
                            "(e.g., your IDE, a running script, or OmniPack itself). "
                            "Please close all programs using this environment and try again."
                        )
                        self._log(f"✗ {self.result_message}", "error")
                        return

                if not self.success:
                    if i == 0 and multi_step:
                        if self._detect_winget_failure(result, cmd):
                            self.winget_failed = True
                            self._log("✗ winget source unavailable — installer fallback available", "stderr")
                        else:
                            self._log(
                                "System Python winget update returned non-zero "
                                "(may already be current). Proceeding with venv upgrade...",
                                "stderr",
                            )
                        self.success = True  # reset for next step
                        continue
                    if self._detect_winget_failure(result, cmd):
                        self.winget_failed = True
                        self.result_message = "winget source unavailable."
                        self._log(f"✗ winget failed — installer fallback available", "stderr")
                    else:
                        self.result_message = f"Python runtime update command failed."
                        self._log(f"✗ {self.result_message}", "error")
                    return

            self.success = True
            self.result_message = "Python runtime update completed."
            self._log(f"✓ {self.result_message}", "success")
        except Exception as exc:
            self.success = False
            self.result_message = f"Python runtime update error: {exc}"
            self._log(self.result_message, "error")
        finally:
            self._flush_logs()



class UpdateWorker(BaseCmdWorker):
    """Worker to run `uv pip install -U <pkg>`"""
    
    def __init__(self, env: Environment, pkg_name: str, source_args=None, uv_path="uv", proxy_settings=None):
        super().__init__()
        self.env = env
        self.pkg_name = pkg_name
        self.source_args = list(source_args or [])
        self.uv_path = uv_path
        self.proxy_settings = proxy_settings or {}

    def run(self):
        try:
            pkg_name, loc = _parse_target_loc(self.pkg_name)
            self._log(f"Updating {pkg_name} in {self.env.name}...", "system")
            uv_path = self.uv_path
            env_path = os.path.normpath(self.env.path)
            py_exe = resolve_python_executable(self.env)
            # Check if this package was installed in user-site
            is_user_package = loc == "user"
            if not is_user_package and self.env.type == "system":
                for p in getattr(self.env, "packages", []):
                    if p.name == pkg_name or getattr(p, "norm_name", "") == pkg_name:
                        if p.metadata.get("location") == "user":
                            is_user_package = True
                            break
            
            if is_user_package:
                from core.utils import get_user_site_packages
                user_site = get_user_site_packages(py_exe)
                args = ["--target", user_site] if user_site else ["--system", "--python", env_path]
            else:
                args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "install", "-v", "-U"] + self.source_args + [pkg_name] + args
            
            res = self._run_command(cmd, capture_output=True)
            combined_output = "\n".join(part for part in ((res.stdout or ""), (res.stderr or "")) if part)
             
            if self.success:
                if _uv_output_reports_package_changes(combined_output):
                    self._log(f"✓ Updated {self.pkg_name} in {self.env.name}", "success")
                else:
                    self._log(
                        f"✓ No package file changes were reported for {self.pkg_name} in {self.env.name}; it may already have been updated by a previous run.",
                        "success",
                    )
            else:
                self._log(f"✗ Failed to update {self.pkg_name}", "error")
                
        except Exception as e:
            self._log(f"Error during update: {e}", "error")
            self.success = False
        finally:
            self._flush_logs()


class BatchUpdateWorker(BaseCmdWorker):
    """Worker to run `uv pip install -U pkg1 pkg2 ...` for multiple packages at once."""

    def __init__(self, env: Environment, pkg_names: list, source_args=None, uv_path="uv", proxy_settings=None):
        super().__init__()
        self.env = env
        self.pkg_names = pkg_names
        self.source_args = list(source_args or [])
        self.uv_path = uv_path
        self.proxy_settings = proxy_settings or {}

    def run(self):
        try:
            real_pkg_names = []
            has_user_pkg = False
            for name in self.pkg_names:
                pkg_name, loc = _parse_target_loc(name)
                real_pkg_names.append(pkg_name)
                if loc == "user":
                    has_user_pkg = True

            names = ", ".join(real_pkg_names)
            self._log(f"Batch updating {names} in {self.env.name}...", "system")
            uv_path = self.uv_path
            env_path = os.path.normpath(self.env.path)
            py_exe = resolve_python_executable(self.env)

            if self.env.type == "system" and not has_user_pkg:
                user_pkg_names = {p.name for p in getattr(self.env, "packages", []) if p.metadata.get("location") == "user"}
                for rname in real_pkg_names:
                    if rname in user_pkg_names:
                        has_user_pkg = True
                        break
            
            from core.utils import is_admin
            if self.env.type == "system" and (has_user_pkg or not is_admin()):
                from core.utils import get_user_site_packages
                user_site = get_user_site_packages(py_exe)
                args = ["--target", user_site] if user_site else ["--system", "--python", env_path]
            else:
                args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "install", "-v", "-U"] + self.source_args + real_pkg_names + args
            res = self._run_command(cmd, capture_output=True)
            combined_output = "\n".join(part for part in ((res.stdout or ""), (res.stderr or "")) if part)

            if self.success:
                if _uv_output_reports_package_changes(combined_output):
                    self._log(f"✓ Batch updated {len(self.pkg_names)} packages in {self.env.name}", "success")
                else:
                    self._log(
                        f"✓ No package file changes were reported in {self.env.name}; selected packages may already have been updated by a previous run.",
                        "success",
                    )
            else:
                self._log(f"✗ Batch update failed in {self.env.name}", "error")
        except Exception as e:
            self._log(f"Error during batch update: {e}", "error")
            self.success = False
        finally:
            self._flush_logs()


class RemoveWorker(BaseCmdWorker):
    """Worker to run `uv pip uninstall <pkg>`"""
    
    def __init__(self, env: Environment, pkg_name: str, uv_path="uv", proxy_settings=None):
        super().__init__()
        self.env = env
        self.pkg_name = pkg_name
        self.uv_path = uv_path
        self.proxy_settings = proxy_settings or {}

    def run(self):
        try:
            pkg_name, loc = _parse_target_loc(self.pkg_name)
            self._log(f"Uninstalling {pkg_name} from {self.env.name}...", "system")
            uv_path = self.uv_path
            env_path = os.path.normpath(self.env.path)
            py_exe = resolve_python_executable(self.env)
            
            # Check if this package was installed in user-site
            is_user_package = loc == "user"
            if not is_user_package and self.env.type == "system":
                for p in getattr(self.env, "packages", []):
                    if p.name == pkg_name or getattr(p, "norm_name", "") == pkg_name:
                        if p.metadata.get("location") == "user":
                            is_user_package = True
                            break
            
            if is_user_package:
                from core.utils import get_user_site_packages
                user_site = get_user_site_packages(py_exe)
                args = ["--target", user_site] if user_site else ["--system", "--python", env_path]
            else:
                args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "uninstall", pkg_name] + args
            
            self._run_command(cmd)
            
            if self.success:
                self._log(f"✓ Uninstalled {self.pkg_name} from {self.env.name}", "success")
            else:
                self._log(f"✗ Failed to uninstall {self.pkg_name}", "error")
                
        except Exception as e:
            self._log(f"Error during uninstall: {e}", "error")
            self.success = False
        finally:
            self._flush_logs()


class InstallWorker(BaseCmdWorker):
    """Worker to run `uv pip install <pkgs>`"""
    
    def __init__(self, env: Environment, pkg_names: str, force_reinstall: bool = False, source_args=None, uv_path="uv", proxy_settings=None):
        super().__init__()
        self.env = env
        self.pkg_names = pkg_names
        self.force_reinstall = force_reinstall
        self.source_args = list(source_args or [])
        self.uv_path = uv_path
        self.proxy_settings = proxy_settings or {}

    def run(self):
        try:
            self._log(f"Installing {self.pkg_names} in {self.env.name}...", "system")
            uv_path = self.uv_path
            env_path = os.path.normpath(self.env.path)
            py_exe = resolve_python_executable(self.env)
            
            from core.utils import is_admin
            if self.env.type == "system" and not is_admin():
                from core.utils import get_user_site_packages
                user_site = get_user_site_packages(py_exe)
                args = ["--target", user_site] if user_site else ["--system", "--python", env_path]
            else:
                args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "install", "-v"]
            cmd.extend(self.source_args)
            if self.force_reinstall:
                cmd.append("--force-reinstall")
            cmd.extend(self.pkg_names.split())
            cmd.extend(args)
            
            self._run_command(cmd)
            
            if self.success:
                self._log(f"✓ Installed {self.pkg_names} in {self.env.name}", "success")
            else:
                self._log(f"✗ Failed to install {self.pkg_names}", "error")
                
        except Exception as e:
            self._log(f"Error during install: {e}", "error")
            self.success = False
        finally:
            self._flush_logs()
