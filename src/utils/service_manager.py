import os
import shutil
import subprocess
import getpass
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

@dataclass
class ServiceManagerResult:
    success: bool
    message: str
    details: Optional[Dict] = None

class ServiceManager:
    def __init__(self, project_root: str, data_dir: str):
        self.project_root = os.path.abspath(project_root)
        self.data_dir = os.path.abspath(data_dir)
        self.python_bin = self._resolve_python_bin()
        self.node_bin = shutil.which("node")
        self.npm_bin = shutil.which("npm")
        
        # Systemd paths
        self.user_unit_path = os.path.expanduser("~/.config/systemd/user")
        self.system_unit_path = "/etc/systemd/system"

    def _resolve_python_bin(self) -> str:
        # Prefer venv if it exists
        venv_python = os.path.join(self.project_root, "env", "bin", "python")
        if os.path.exists(venv_python):
            return venv_python
        return shutil.which("python3") or shutil.which("python")

    def get_kernel_template(self) -> str:
        env_file = os.path.join(self.data_dir, ".env")
        env_file_line = f"EnvironmentFile={env_file}" if os.path.exists(env_file) else ""
        
        return f"""[Unit]
Description=Assistant-OS Backend Kernel
Wants=network-online.target
After=network-online.target
PartOf=aosd.target

[Service]
Type=simple
WorkingDirectory={self.project_root}
ExecStart={self.python_bin} {self.project_root}/src/main.py
Restart=always
RestartSec=3
TimeoutStopSec=30
Environment=PYTHONPATH={self.project_root}/src
{env_file_line}

[Install]
WantedBy=default.target
"""

    def get_ui_template(self, host: str = "localhost", port: int = 5173) -> str:
        return f"""[Unit]
Description=Assistant-OS Frontend (Production Preview)
After=aosd-kernel.service
PartOf=aosd.target

[Service]
Type=simple
WorkingDirectory={os.path.join(self.project_root, "frontend")}
ExecStart={self.npm_bin} run preview -- --port {port} --host {host}
Restart=always
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=default.target
"""

    def get_target_template(self) -> str:
        return f"""[Unit]
Description=Assistant-OS Integrated Stack
Requires=aosd-kernel.service aosd-ui.service

[Install]
WantedBy=default.target
"""

    def prepare_frontend(self) -> ServiceManagerResult:
        """Runs npm run build in the frontend directory."""
        if not self.npm_bin:
            return ServiceManagerResult(False, "npm not found in PATH.")
        
        frontend_dir = os.path.join(self.project_root, "frontend")
        if not os.path.exists(frontend_dir):
            return ServiceManagerResult(False, f"Frontend directory not found: {frontend_dir}")
        
        try:
            print(f"Building frontend in {frontend_dir}...")
            subprocess.run([str(self.npm_bin), "install"], cwd=frontend_dir, check=True)
            subprocess.run([str(self.npm_bin), "run", "build"], cwd=frontend_dir, check=True)
            return ServiceManagerResult(True, "Frontend build successful.")
        except subprocess.CalledProcessError as e:
            return ServiceManagerResult(False, f"Frontend build failed: {e}")

    def generate_units(self) -> Dict[str, str]:
        return {
            "aosd-kernel.service": self.get_kernel_template(),
            "aosd-ui.service": self.get_ui_template(),
            "aosd.target": self.get_target_template()
        }

    def install(self, system_mode: bool = False) -> ServiceManagerResult:
        # Automatically prepare frontend
        build_res = self.prepare_frontend()
        if not build_res.success:
            return build_res

        units = self.generate_units()
        target_dir = self.system_unit_path if system_mode else self.user_unit_path
        
        if not system_mode:
            os.makedirs(target_dir, exist_ok=True)
        
        try:
            for name, content in units.items():
                dest = os.path.join(target_dir, name)
                if system_mode:
                    # In system mode, we might need sudo. 
                    # But per plan, we expect the caller to run with sudo if system_mode is requested.
                    with open(dest, "w") as f:
                        f.write(content)
                else:
                    with open(dest, "w") as f:
                        f.write(content)
            
            # Reload daemon
            try:
                cmd = ["systemctl", "--user", "daemon-reload"] if not system_mode else ["systemctl", "daemon-reload"]
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                if not system_mode and "Failed to connect to bus" in e.stderr.decode():
                    return ServiceManagerResult(False, "Failed to connect to systemd user bus. This usually happens when running via 'sudo'. Please run the setup/installer without sudo.")
                return ServiceManagerResult(False, f"Systemd daemon-reload failed: {e.stderr.decode().strip()}")
            
            return ServiceManagerResult(True, f"Services installed successfully in {'system' if system_mode else 'user'} mode.")
        except PermissionError:
            mode_str = "sudo " if system_mode else ""
            return ServiceManagerResult(False, f"Permission denied. Try running with {mode_str}or check directory permissions.")
        except Exception as e:
            return ServiceManagerResult(False, f"Installation failed: {e}")

    def get_status(self, system_mode: bool = False) -> Dict[str, str]:
        results = {}
        target_units = ["aosd-kernel.service", "aosd-ui.service", "aosd.target"]
        base_cmd = ["systemctl", "--user"] if not system_mode else ["systemctl"]
        
        for unit in target_units:
            try:
                proc = subprocess.run(base_cmd + ["is-active", unit], capture_output=True, text=True)
                results[unit] = proc.stdout.strip()
            except Exception:
                results[unit] = "unknown"
        return results
