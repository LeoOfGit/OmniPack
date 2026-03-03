import os
import subprocess
import threading
import json
import shutil
from PySide6.QtCore import QObject, Signal, QThread, Slot
import re

from core.manager_base import PackageManager, Environment, Package
from core.dep_resolver import resolve_dependencies_subprocess, merge_dependency_info
from core.utils import find_system_pythons

# Use 'uv' as the backend executor, just like in pip_manager.pyw
UV_CMD = "uv" 

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
        # Normalize keys to handle slash/casing differences on Windows
        old_envs = {os.path.normpath(e.path).lower(): e for e in self.environments}
        self.environments.clear()
        
        # 1. From Config
        for env_dict in self.config_mgr.config.pip_environments:
            path = os.path.normpath(env_dict.get("path"))
            name = env_dict.get("name")
            env_type = env_dict.get("type", "venv")
            
            key = path.lower()
            if key in old_envs:
                # Retain existing state
                env = old_envs[key]
                env.path = path # Update path in case slashes changed
                env.name = name # Update name in case user changed it
                env.type = env_type
                self.environments.append(env)
            else:
                self.environments.append(
                    Environment(path=path, name=name, type=env_type)
                )
            
        # 2. auto-discover system pythons if none in config
        if not any(e.type == "system" for e in self.environments):
            sys_pythons = find_system_pythons()
            for py in sys_pythons:
                py_path = os.path.normpath(py["path"])
                # Check for duplicates by path
                if not any(os.path.normpath(e.path).lower() == py_path.lower() for e in self.environments):
                    self.config_mgr.add_pip_env(path=py_path, name=py["name"], env_type="system")
                    self.environments.append(
                        Environment(path=py_path, name=py["name"], type="system")
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
        worker = ScanWorker(env)
        worker.env_scanned.connect(self._on_env_scanned)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start() # Start QThread
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._active_workers.remove(worker) if worker in self._active_workers else None)

    def update_package(self, env: Environment, pkg_name: str):
        worker = UpdateWorker(env, pkg_name)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        # Notify UI when update is done so it can refresh the list
        worker.finished.connect(lambda: [self._active_workers.remove(worker) if worker in self._active_workers else None, self.update_done.emit(env.path, pkg_name, worker.success)])

    def remove_package(self, env: Environment, pkg_name: str):
        worker = RemoveWorker(env, pkg_name)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda: [self._active_workers.remove(worker) if worker in self._active_workers else None, self.remove_done.emit(env.path, pkg_name, worker.success)])

    def install_package(self, env: Environment, pkg_names: str, force_reinstall: bool = False):
        worker = InstallWorker(env, pkg_names, force_reinstall)
        worker.log_msg.connect(self.log_msg)
        worker.log_batch.connect(self.log_batch)
        worker.start()
        self._active_workers.append(worker)
        worker.finished.connect(lambda: [self._active_workers.remove(worker) if worker in self._active_workers else None, self.install_done.emit(env.path, pkg_names, worker.success)])

    update_done = Signal(str, str, bool) # env_path, pkg_name, success
    remove_done = Signal(str, str, bool) # env_path, pkg_name, success
    install_done = Signal(str, str, bool) # env_path, pkg_names, success



class ScanWorker(QThread):
    """Worker thread to run 'uv pip list' and 'outdated'"""
    
    env_scanned = Signal(Environment) 
    log_msg = Signal(str, str)
    log_batch = Signal(list)

    def __init__(self, env: Environment):
        super().__init__()
        self.env = env
        self._log_buffer = []

    def _log(self, msg, tag):
        self._log_buffer.append((msg, tag))
    
    def run(self):
        try:
            # Determine python executable for this env
            env_path = os.path.normpath(self.env.path)
            if os.path.isfile(env_path):
                py_exe = env_path
            else:
                # venv root provided
                py_exe = os.path.join(env_path, "Scripts", "python.exe")
                if not os.path.exists(py_exe):
                    py_exe = os.path.join(env_path, "bin", "python")
            
            py_exe = os.path.normpath(py_exe)
            self._log(f"Scanning {self.env.name} using {py_exe}...", "system")
            
            if not os.path.exists(py_exe):
                self._log(f"Error: Python executable not found at {py_exe}", "error")
                return

            # 1. Version Check
            ver_cmd = [py_exe, "--version"]
            self._log(f"> {' '.join(ver_cmd)}", "cmd")
            res = subprocess.run(ver_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            py_ver = res.stdout.strip().split(" ")[1] if res.returncode == 0 else "?"
            if res.stdout.strip():
                self._log(res.stdout.strip(), "stdout")
            
            # 2. List Packages
            uv_path = shutil.which("uv") or "uv"
            # Verify uv
            try:
                uv_cmd = [uv_path, "--version"]
                self._log(f"> {' '.join(uv_cmd)}", "cmd")
                uv_res = subprocess.run(uv_cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                if uv_res.stdout.strip():
                    self._log(uv_res.stdout.strip(), "stdout")
            except FileNotFoundError:
                self._log("Error: 'uv' command not found. Please install uv (https://gh.io/uv).", "error")
                return

            args = ["--system", "--python", self.env.path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "list", "--format", "json"] + args
            self._log(f"> {' '.join(cmd)}", "cmd")
            res = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
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
            cmd_outdated = [uv_path, "pip", "list", "--outdated", "--format", "json"] + args
            self._log(f"> {' '.join(cmd_outdated)}", "cmd")
            res_outdated = subprocess.run(cmd_outdated, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
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

            # 4. Resolve dependency tree
            self._log(f"Resolving dependency tree for {self.env.name}...", "system")
            dep_data = resolve_dependencies_subprocess(py_exe)
            if dep_data:
                pkgs, dep_graph = merge_dependency_info(pkgs, dep_data)
                self.env.dep_graph = dep_graph
                top_level_count = sum(1 for p in pkgs if p.is_top_level and not p.is_missing)
                missing_count = sum(1 for p in pkgs if p.is_missing)
                self._log(f"Dependency tree: {top_level_count} top-level, {len(pkgs) - top_level_count} transitive"
                          + (f", {missing_count} missing" if missing_count else ""), "stdout")
            else:
                self._log(f"Warning: Could not resolve dependency tree for {self.env.name}", "stderr")
                # Fallback: treat all as top-level
                self.env.dep_graph = {pkg.norm_name: pkg for pkg in pkgs}

            self.env.python_version = py_ver
            self.env.packages = pkgs
            self.env.is_scanned = True
            
            self._log(f"✓ Found {len(pkgs)} packages, {count_updates} updates in {self.env.name}", "success")
            
        except Exception as e:
            self._log(f"Scan Error for {self.env.path}: {e}", "error")
            self.env.is_scanned = True 
            
        finally:
            self.env_scanned.emit(self.env)
            if self._log_buffer:
                self.log_batch.emit(self._log_buffer)



class UpdateWorker(QThread):
    """Worker to run `uv pip install -U <pkg>`"""
    
    log_msg = Signal(str, str)
    log_batch = Signal(list)
    
    def __init__(self, env: Environment, pkg_name: str):
        super().__init__()
        self.env = env
        self.pkg_name = pkg_name
        self.success = False
        self._log_buffer = []

    def _log(self, msg, tag):
        self._log_buffer.append((msg, tag))

    def run(self):
        try:
            self._log(f"Updating {self.pkg_name} in {self.env.name}...", "system")
            uv_path = shutil.which("uv") or "uv"
            env_path = os.path.normpath(self.env.path)
            
            if os.path.isfile(env_path):
                py_exe = env_path
            else:
                py_exe = os.path.join(env_path, "Scripts", "python.exe")
                if not os.path.exists(py_exe):
                    py_exe = os.path.join(env_path, "bin", "python")
            
            py_exe = os.path.normpath(py_exe)
            
            args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "install", "-U", self.pkg_name] + args
            self._log(f"> {' '.join(cmd)}", "cmd")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )

            ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\r")

            def read_stream(stream, tag):
                try:
                    for raw_line in stream:
                        line = ANSI_ESCAPE.sub("", raw_line).rstrip()
                        if line:
                            self._log(line, tag)
                except Exception:
                    pass

            stdout_t = threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True)
            stderr_t = threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True)
            stdout_t.start()
            stderr_t.start()
            process.wait()
            stdout_t.join(timeout=5)
            stderr_t.join(timeout=5)
            
            self.success = (process.returncode == 0)
            if self.success:
                self._log(f"✓ Updated {self.pkg_name} in {self.env.name}", "success")
            else:
                self._log(f"✗ Failed to update {self.pkg_name}", "error")
                
        except Exception as e:
            self._log(f"Error during update: {e}", "error")
            self.success = False
        finally:
            if self._log_buffer:
                self.log_batch.emit(self._log_buffer)


class RemoveWorker(QThread):
    """Worker to run `uv pip uninstall <pkg>`"""
    
    log_msg = Signal(str, str)
    log_batch = Signal(list)
    
    def __init__(self, env: Environment, pkg_name: str):
        super().__init__()
        self.env = env
        self.pkg_name = pkg_name
        self.success = False
        self._log_buffer = []

    def _log(self, msg, tag):
        self._log_buffer.append((msg, tag))

    def run(self):
        try:
            self._log(f"Uninstalling {self.pkg_name} from {self.env.name}...", "system")
            uv_path = shutil.which("uv") or "uv"
            env_path = os.path.normpath(self.env.path)
            
            if os.path.isfile(env_path):
                py_exe = env_path
            else:
                py_exe = os.path.join(env_path, "Scripts", "python.exe")
                if not os.path.exists(py_exe):
                    py_exe = os.path.join(env_path, "bin", "python")
            
            py_exe = os.path.normpath(py_exe)
            
            args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "uninstall", self.pkg_name] + args
            self._log(f"> {' '.join(cmd)}", "cmd")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )

            ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\r")

            def read_stream(stream, tag):
                try:
                    for raw_line in stream:
                        line = ANSI_ESCAPE.sub("", raw_line).rstrip()
                        if line:
                            self._log(line, tag)
                except Exception:
                    pass

            stdout_t = threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True)
            stderr_t = threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True)
            stdout_t.start()
            stderr_t.start()
            process.wait()
            stdout_t.join(timeout=5)
            stderr_t.join(timeout=5)
            
            self.success = (process.returncode == 0)
            if self.success:
                self._log(f"✓ Uninstalled {self.pkg_name} from {self.env.name}", "success")
            else:
                self._log(f"✗ Failed to uninstall {self.pkg_name}", "error")
                
        except Exception as e:
            self._log(f"Error during uninstall: {e}", "error")
            self.success = False
        finally:
            if self._log_buffer:
                self.log_batch.emit(self._log_buffer)


class InstallWorker(QThread):
    """Worker to run `uv pip install <pkgs>`"""
    
    log_msg = Signal(str, str)
    log_batch = Signal(list)
    
    def __init__(self, env: Environment, pkg_names: str, force_reinstall: bool = False):
        super().__init__()
        self.env = env
        self.pkg_names = pkg_names
        self.force_reinstall = force_reinstall
        self.success = False
        self._log_buffer = []

    def _log(self, msg, tag):
        self._log_buffer.append((msg, tag))

    def run(self):
        try:
            self._log(f"Installing {self.pkg_names} in {self.env.name}...", "system")
            uv_path = shutil.which("uv") or "uv"
            env_path = os.path.normpath(self.env.path)
            
            if os.path.isfile(env_path):
                py_exe = env_path
            else:
                py_exe = os.path.join(env_path, "Scripts", "python.exe")
                if not os.path.exists(py_exe):
                    py_exe = os.path.join(env_path, "bin", "python")
            
            py_exe = os.path.normpath(py_exe)
            
            args = ["--system", "--python", env_path] if self.env.type == "system" else ["--python", py_exe]
            
            cmd = [uv_path, "pip", "install"]
            if self.force_reinstall:
                cmd.append("--force-reinstall")
            cmd.extend(self.pkg_names.split())
            cmd.extend(args)
            
            self._log(f"> {' '.join(cmd)}", "cmd")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )

            ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07|\r")

            def read_stream(stream, tag):
                try:
                    for raw_line in stream:
                        line = ANSI_ESCAPE.sub("", raw_line).rstrip()
                        if line:
                            self._log(line, tag)
                except Exception:
                    pass

            stdout_t = threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True)
            stderr_t = threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True)
            stdout_t.start()
            stderr_t.start()
            process.wait()
            stdout_t.join(timeout=5)
            stderr_t.join(timeout=5)
            
            self.success = (process.returncode == 0)
            if self.success:
                self._log(f"✓ Installed {self.pkg_names} in {self.env.name}", "success")
            else:
                self._log(f"✗ Failed to install {self.pkg_names}", "error")
                
        except Exception as e:
            self._log(f"Error during install: {e}", "error")
            self.success = False
        finally:
            if self._log_buffer:
                self.log_batch.emit(self._log_buffer)
