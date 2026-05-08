import os
import subprocess
import json
from PySide6.QtCore import Signal

from core.manager_base import PackageManager, Environment, Package
from core.dep_resolver import resolve_dependencies_subprocess, merge_dependency_info
from core.network_proxy import merge_env_for_command
from core.runtime_update import (
    build_python_runtime_update_command,
    check_runtime_patch_update,
    check_version_satisfies_constraint,
    compare_versions,
    has_build_variant_mismatch,
    parse_cycle,
    parse_python_version,
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
                if key.strip().lower() not in {"version", "version_info"}:
                    continue
                parsed = parse_python_version(value.strip())
                if parsed:
                    return parsed
    except Exception:
        pass
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

    def _on_env_scanned(self, env: Environment):
        for i, e in enumerate(self.environments):
            if e.path == env.path:
                self.environments[i] = env
                break
        self.env_scanned.emit(env)

    def scan_environment(self, env: Environment):
        """Async scan trigger"""
        worker = ScanWorker(
            env,
            source_args=build_pip_source_args(self.config_mgr),
            uv_path=get_uv_path(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        worker.env_scanned.connect(self._on_env_scanned)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start() # Start QThread
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._active_workers.remove(worker) if worker in self._active_workers else None)

    def update_package(self, env: Environment, pkg_name: str):
        worker = UpdateWorker(
            env,
            pkg_name,
            source_args=build_pip_source_args(self.config_mgr),
            uv_path=get_uv_path(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        # Notify UI when update is done so it can refresh the list
        worker.finished.connect(lambda: [self._active_workers.remove(worker) if worker in self._active_workers else None, self.update_done.emit(env.path, pkg_name, worker.success)])

    def remove_package(self, env: Environment, pkg_name: str):
        worker = RemoveWorker(
            env,
            pkg_name,
            uv_path=get_uv_path(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda: [self._active_workers.remove(worker) if worker in self._active_workers else None, self.remove_done.emit(env.path, pkg_name, worker.success)])

    def install_package(self, env: Environment, pkg_names: str, force_reinstall: bool = False):
        worker = InstallWorker(
            env,
            pkg_names,
            force_reinstall,
            source_args=build_pip_source_args(self.config_mgr),
            uv_path=get_uv_path(self.config_mgr),
            proxy_settings=getattr(self.config_mgr.config, "proxy_settings", {}) or {},
        )
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda: [self._active_workers.remove(worker) if worker in self._active_workers else None, self.install_done.emit(env.path, pkg_names, worker.success)])

    def update_runtime(self, env: Environment):
        worker = RuntimeUpdateWorker(env)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(
            lambda: [
                self._active_workers.remove(worker) if worker in self._active_workers else None,
                self.runtime_update_done.emit(env.path, worker.success, worker.result_message),
            ]
        )

    update_done = Signal(str, str, bool) # env_path, pkg_name, success
    remove_done = Signal(str, str, bool) # env_path, pkg_name, success
    install_done = Signal(str, str, bool) # env_path, pkg_names, success
    runtime_update_done = Signal(str, bool, str) # env_path, success, message



def _compute_breaks_constraint(pkgs: list, dep_graph: dict):
    for pkg in pkgs:
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


class ScanWorker(BaseCmdWorker):
    """Worker thread to run 'uv pip list' and 'outdated'"""
    
    env_scanned = Signal(Environment) 

    def __init__(self, env: Environment, source_args=None, uv_path="uv", proxy_settings=None):
        super().__init__()
        self.env = env
        self.source_args = list(source_args or [])
        self.uv_path = uv_path
        self.proxy_settings = proxy_settings or {}
    
    def run(self):
        try:
            # Determine python executable for this env
            env_path = os.path.normpath(self.env.path)
            py_exe = resolve_python_executable(self.env)
            self._log(f"Scanning {self.env.name} using {py_exe}...", "system")
            
            if not os.path.exists(py_exe):
                self._log(f"Error: Python executable not found at {py_exe}", "error")
                return

            # 1. Version Check
            ver_cmd = [py_exe, "--version"]
            self._log(f"> {' '.join(ver_cmd)}", "cmd")
            res = subprocess.run(
                ver_cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                env=merge_env_for_command(ver_cmd, proxy_settings=self.proxy_settings),
            )
            raw_ver = (res.stdout or "").strip() or (res.stderr or "").strip()
            py_ver = parse_python_version(raw_ver) if res.returncode == 0 and raw_ver else ""
            if str(self.env.type or "").lower() != "system":
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
            if raw_ver:
                self._log(raw_ver, "stdout")

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
                self._log(f"> {' '.join(uv_cmd)}", "cmd")
                uv_res = subprocess.run(
                    uv_cmd,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    env=merge_env_for_command(uv_cmd, proxy_settings=self.proxy_settings),
                )
                if uv_res.stdout.strip():
                    self._log(uv_res.stdout.strip(), "stdout")
            except FileNotFoundError:
                self._log("Error: 'uv' command not found. Please install uv (https://gh.io/uv).", "error")
                return

            args = ["--system", "--python", self.env.path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "list", "--format", "json"] + args
            self._log(f"> {' '.join(cmd)}", "cmd")
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                env=merge_env_for_command(cmd, proxy_settings=self.proxy_settings),
            )
            
            pkgs = []
            if res.returncode == 0:
                # Find JSON start
                json_stdout = res.stdout[res.stdout.find('['):] if '[' in res.stdout else res.stdout
                if json_stdout.strip():
                    try:
                        data = json.loads(json_stdout)
                        self._log(f"Loaded JSON for {len(data)} packages.", "stdout")
                        for item in data:
                            pkgs.append(Package(
                                name=item.get("name"),
                                version=item.get("version")
                            ))
                    except Exception as je:
                        self._log(f"JSON Parse Error: {je}", "error")
            else:
                 if res.stderr.strip():
                     self._log(res.stderr.strip(), "stderr")
            
            # 3. Check Updates
            cmd_outdated = [uv_path, "pip", "list", "--outdated", "--format", "json"] + self.source_args + args
            self._log(f"> {' '.join(cmd_outdated)}", "cmd")
            res_outdated = subprocess.run(
                cmd_outdated,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                env=merge_env_for_command(cmd_outdated, proxy_settings=self.proxy_settings),
            )
            
            outdated_map = {}
            if res_outdated.returncode == 0:
                json_stdout = res_outdated.stdout[res_outdated.stdout.find('['):] if '[' in res_outdated.stdout else res_outdated.stdout
                if json_stdout.strip():
                    try:
                        data = json.loads(json_stdout)
                        self._log(f"Loaded JSON for {len(data)} outdated packages.", "stdout")
                        for item in data:
                            name = item.get("name", "")
                            latest = item.get("latest_version", "")
                            if name and latest:
                                outdated_map[name] = latest
                    except: pass
            else:
                 if res_outdated.stderr.strip():
                     self._log(res_outdated.stderr.strip(), "stderr")
            
            # Update objects
            count_updates = 0
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
                _compute_breaks_constraint(pkgs, dep_graph)

                top_level_count = sum(1 for p in pkgs if p.is_top_level and not p.is_missing)
                missing_count = sum(1 for p in pkgs if p.is_missing)
                self._log(f"Dependency tree: {top_level_count} top-level, {len(pkgs) - top_level_count} transitive"
                          + (f", {missing_count} missing" if missing_count else ""), "stdout")
            else:
                self._log(f"Warning: Could not resolve dependency tree for {self.env.name}", "stderr")
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
            
            self._log(f"✓ Found {len(pkgs)} packages, {count_updates} updates in {self.env.name}", "success")
            
        except Exception as e:
            self._log(f"Scan Error for {self.env.path}: {e}", "error")
            self.env.is_scanned = True 
            
        finally:
            self.env_scanned.emit(self.env)
            self._flush_logs()


class RuntimeUpdateWorker(BaseCmdWorker):
    """Worker to update Python runtime itself (not packages)."""

    def __init__(self, env: Environment):
        super().__init__()
        self.env = env
        self.result_message = ""

    def run(self):
        try:
            current_ver = self.env.runtime_version or self.env.python_version
            cycle = self.env.runtime_cycle or parse_cycle("python", current_ver)
            latest = self.env.runtime_latest_version
            self._log(
                f"Updating Python runtime for {self.env.name} ({current_ver or 'unknown'}"
                + (f" -> {latest}" if latest else "")
                + ")...",
                "system",
            )

            cmd, reason = build_python_runtime_update_command(self.env.type, self.env.path, cycle)
            if not cmd:
                self.success = False
                self.result_message = reason or "No runnable command for Python runtime update."
                self._log(self.result_message, "error")
                return

            self._run_command(cmd)
            if self.success:
                self.result_message = "Python runtime update command completed."
                self._log(f"✓ {self.result_message}", "success")
            else:
                self.result_message = "Python runtime update command failed."
                self._log(f"✗ {self.result_message}", "error")
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
            self._log(f"Updating {self.pkg_name} in {self.env.name}...", "system")
            uv_path = self.uv_path
            env_path = os.path.normpath(self.env.path)
            py_exe = resolve_python_executable(self.env)
            
            args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "install", "-U"] + self.source_args + [self.pkg_name] + args
            
            self._run_command(cmd)
            
            if self.success:
                self._log(f"✓ Updated {self.pkg_name} in {self.env.name}", "success")
            else:
                self._log(f"✗ Failed to update {self.pkg_name}", "error")
                
        except Exception as e:
            self._log(f"Error during update: {e}", "error")
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
            self._log(f"Uninstalling {self.pkg_name} from {self.env.name}...", "system")
            uv_path = self.uv_path
            env_path = os.path.normpath(self.env.path)
            py_exe = resolve_python_executable(self.env)
            
            args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "uninstall", self.pkg_name] + args
            
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
            
            args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "install"]
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
