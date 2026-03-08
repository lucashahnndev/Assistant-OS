import os
import shutil
import psutil
import platform
import datetime
import time
import subprocess
import json
import socket
_PYAUTOGUI_IMPORT_ERROR = None
try:
    import pyautogui
except BaseException as e:
    pyautogui = None
    _PYAUTOGUI_IMPORT_ERROR = e
from .base_driver import BaseDriver
from utils.logging_config import get_logger

logger = get_logger("SystemDriver")

class SystemDriver(BaseDriver):
    def __init__(self, kernel):
        super().__init__(kernel)
        self.os_type = platform.system()
        if _PYAUTOGUI_IMPORT_ERROR is not None:
            logger.warning(
                "PyAutoGUI unavailable (%s). Screenshot support will use CLI fallbacks only.",
                _PYAUTOGUI_IMPORT_ERROR,
            )

    def start(self):
        logger.info("SystemDriver started.")

    def stop(self):
        logger.info("SystemDriver stopped.")

    def send_response(self, text, target=None, is_chunk=False, attachments=None):
        # Implementation to satisfy protocol, though kernel usually handles the back-routing
        pass

    def send_file(self, target, file_path, caption=None):
        # SystemDriver doesn't send files directly to users
        pass

    def send_status(self, target, phase, payload):
        """SystemDriver does not support structured status."""
        pass

    def send_reasoning_chunk(self, target, content):
        """SystemDriver does not support reasoning chunks."""
        pass

    def send_complete(self, target):
        """SystemDriver does not support completion events."""
        pass


    # --- System Control ---
    def get_status(self):
        """Returns CPU, RAM, Disk, Uptime, Top processes, and Temp."""
        try:
            status = {
                "cpu_usage_percent": psutil.cpu_percent(interval=1),
                "load_avg": os.getloadavg() if hasattr(os, 'getloadavg') else "N/A",
                "memory": {
                    "total": psutil.virtual_memory().total,
                    "available": psutil.virtual_memory().available,
                    "percent": psutil.virtual_memory().percent
                },
                "swap": {
                    "total": psutil.swap_memory().total,
                    "used": psutil.swap_memory().used,
                    "percent": psutil.swap_memory().percent
                },
                "disk": {
                    "total": psutil.disk_usage('/').total,
                    "used": psutil.disk_usage('/').used,
                    "free": psutil.disk_usage('/').free,
                    "percent": psutil.disk_usage('/').percent
                },
                "uptime": str(datetime.timedelta(seconds=int(datetime.datetime.now().timestamp() - psutil.boot_time()))),
                "top_processes": []
            }

            # Get top processes with a short sampling window for usable CPU percentages.
            # First pass primes per-process CPU counters.
            primed = []
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    p.cpu_percent(None)
                    primed.append(p)
                except Exception:
                    continue

            # Small wait to compute deltas without blocking too long.
            time.sleep(0.08)

            ranked = []
            for p in primed:
                try:
                    info = p.as_dict(attrs=['pid', 'name', 'cpu_percent', 'memory_percent'])
                    info["cpu_percent"] = float(info.get("cpu_percent") or 0.0)
                    info["memory_percent"] = float(info.get("memory_percent") or 0.0)
                    ranked.append(info)
                except Exception:
                    continue

            ranked.sort(key=lambda row: (row.get("cpu_percent", 0.0), row.get("memory_percent", 0.0)), reverse=True)
            status["top_processes"] = ranked[:5]

            # Temperature (Linux specific typically)
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    status["temperature"] = temps

            return status
        except Exception as e:
            logger.error(f"Error in get_status: {e}")
            return {"error": str(e)}

    def get_hw_info(self):
        """Returns CPU model, RAM total, disks, GPU, NICs."""
        try:
            info = {
                "cpu": platform.processor(),
                "ram_total": psutil.virtual_memory().total,
                "disks": [d._asdict() for d in psutil.disk_partitions()],
                "network_interfaces": list(psutil.net_if_addrs().keys())
            }
            # Add GPU info if possible (very basic check)
            try:
                if self.os_type == "Linux":
                    gpu = subprocess.check_output("lspci | grep -i vga", shell=True, timeout=10).decode().strip()
                    info["gpu"] = gpu
            except:
                pass
            return info
        except Exception as e:
            return {"error": str(e)}

    def get_os_info(self):
        """Detailed distro, kernel, hostname, etc."""
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "node": platform.node(),
            "machine": platform.machine(),
            "user": os.getlogin() if hasattr(os, 'getlogin') else "N/A",
            "timezone": str(datetime.datetime.now().astimezone().tzinfo)
        }

    # --- Process Control ---
    def list_processes(self, name_contains=None, user=None, sort='cpu'):
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
            try:
                if name_contains and name_contains.lower() not in p.info['name'].lower():
                    continue
                if user and user.lower() not in (p.info['username'] or '').lower():
                    continue
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if sort == 'cpu':
            procs = sorted(procs, key=lambda x: x['cpu_percent'], reverse=True)
        elif sort == 'mem':
            procs = sorted(procs, key=lambda x: x['memory_percent'], reverse=True)

        return procs[:50] # Limit to 50

    def kill_process(self, pid, signal_name='TERM'):
        try:
            p = psutil.Process(pid)
            # Guardrails: Protection for critical processes
            critical_names = ['systemd', 'init', 'sshd', 'python', 'bash']
            if p.name().lower() in critical_names and p.pid < 1000:
                return f"Error: Process {p.name()} (PID {pid}) is critical and cannot be killed via this skill."
            
            p.terminate()
            return f"Process {pid} ({p.name()}) terminated."
        except Exception as e:
            return f"Error killing process {pid}: {e}"

    # --- Power Control ---
    def power_reboot(self):
        logger.warning("Reboot requested.")
        return "Command 'reboot' would be executed here. (Placeholder for safety in dev)"

    def power_shutdown(self):
        logger.warning("Shutdown requested.")
        return "Command 'shutdown' would be executed here. (Placeholder for safety in dev)"

    # --- Inventory Control ---
    def list_installed_apps(self):
        apps = []
        # Search for .desktop files in standard Linux locations
        search_paths = ['/usr/share/applications', os.path.expanduser('~/.local/share/applications')]
        for path in search_paths:
            if os.path.exists(path):
                for f in os.listdir(path):
                    if f.endswith('.desktop'):
                        apps.append(f.replace('.desktop', ''))
        return sorted(list(set(apps)))[:100]

    def list_installed_packages(self):
        try:
            # Check for common package managers
            if shutil.which('dpkg'):
                res = subprocess.check_output("dpkg --get-selections | head -n 100", shell=True, timeout=20).decode()
                return res
            elif shutil.which('pacman'):
                res = subprocess.check_output("pacman -Qq | head -n 100", shell=True, timeout=20).decode()
                return res
            return "No common package manager found or supported."
        except Exception as e:
            return str(e)

    # --- Service Control ---
    def service_action(self, unit, action):
        if action not in ['status', 'start', 'stop', 'restart']:
            return "Invalid action."
        try:
            # For status, no sudo needed. For others, it might be.
            # We assume the user running the kernel has some permissions or it's a dev environment.
            cmd = ["systemctl", action, unit]
            res = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=15).decode()
            return res if res else f"Action {action} on {unit} executed."
        except Exception as e:
            return f"Error on service {unit}: {e}"

    def service_logs(self, unit, lines=50):
        try:
            cmd = ["journalctl", "-u", unit, "-n", str(lines), "--no-pager"]
            return subprocess.check_output(cmd, timeout=20).decode()
        except Exception as e:
            return str(e)

    # --- Network Control ---
    def net_status(self):
        try:
            interfaces = {}
            for name, addrs in psutil.net_if_addrs().items():
                interfaces[name] = [a._asdict() for a in addrs]
            
            return {
                "interfaces": interfaces,
                "hostname": socket.gethostname(),
                "fqdn": socket.getfqdn()
            }
        except Exception as e:
            return str(e)

    def net_ping(self, host, count=4):
        try:
            cmd = ["ping", "-c", str(count), host]
            return subprocess.check_output(cmd, timeout=10).decode()
        except Exception as e:
            return str(e)

    # --- FS Control ---
    def fs_list(self, path):
        try:
            ws_dir = self.kernel.workspace_service.get_workspace_dir()
            target_path = os.path.abspath(os.path.join(ws_dir, path))
            
            if not os.path.exists(target_path): return f"Path not found: {path}"
            
            items = []
            for entry in os.scandir(target_path):
                info = entry.stat()
                items.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": info.st_size,
                    "modified": datetime.datetime.fromtimestamp(info.st_mtime).isoformat()
                })
            return items
        except Exception as e:
            return str(e)

    def take_screenshot(self, filename="screenshot.png", session_id=None):
        """Captures the system screen and saves it to the session media folder."""
        try:
            # We want technical screenshots to go to the session scope by default
            ws_service = self.kernel.workspace_service
            
            if not session_id:
                target_path = os.path.join(ws_service.get_workspace_dir(), filename)
            else:
                normalized = os.path.normpath(str(filename or "screenshot.png")).replace("\\", "/")
                if normalized.startswith("temp/"):
                    # Ephemeral artifacts are persisted under workspace/temp/<session_id>/<execution_id>/...
                    relative_temp = normalized[len("temp/") :].lstrip("/")
                    target_path = os.path.join(
                        ws_service.get_workspace_dir(),
                        "temp",
                        str(session_id),
                        relative_temp,
                    )
                else:
                    target_path = os.path.join(ws_service.get_session_dir(session_id), "media", "image", normalized)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            # 1. Try PyAutoGUI first (more reliable for HiDPI/Scaling)
            if pyautogui:
                try:
                    screenshot = pyautogui.screenshot()
                    screenshot.save(target_path)
                    logger.info(f"Screenshot taken via PyAutoGUI: {target_path}")
                    return os.path.abspath(target_path)
                except Exception as e:
                    logger.warning(f"PyAutoGUI screenshot failed, falling back: {e}")

            # 2. Try gnome-screenshot
            if shutil.which('gnome-screenshot'):
                subprocess.run(['gnome-screenshot', '-f', target_path], check=True, timeout=10)
                return os.path.abspath(target_path)
            # 3. Try scrot
            elif shutil.which('scrot'):
                subprocess.run(['scrot', target_path], check=True, timeout=10)
                return os.path.abspath(target_path)
            # 4. Try import (ImageMagick)
            elif shutil.which('import'):
                subprocess.run(['import', '-window', 'root', target_path], check=True, timeout=10)
                return os.path.abspath(target_path)
            else:
                return "Error: No screenshot tool found (pyautogui, gnome-screenshot, scrot, or import)."
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return f"Error: {e}"

    def fs_read(self, path, start=1, end=None):
        try:
            ws_dir = self.kernel.workspace_service.get_workspace_dir()
            target_path = os.path.abspath(os.path.join(ws_dir, path))

            # Guardrail: Prevent reading sensitive paths OUTSIDE workspace if absolute
            if not target_path.startswith(ws_dir):
                forbidden = ['/etc/shadow', '/etc/passwd', '/root', '.ssh']
                for f in forbidden:
                    if f in target_path:
                        return f"Access Denied: Path '{path}' is restricted."

            with open(target_path, 'r') as f:
                lines = f.readlines()
                if end is None:
                    end = len(lines)
                subset = lines[start-1:end]
                return "".join(subset)
        except Exception as e:
            return str(e)

    def fs_write(self, path, content):
        try:
            ws_dir = self.kernel.workspace_service.get_workspace_dir()
            target_path = os.path.abspath(os.path.join(ws_dir, path))

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"File written successfully: {path}"
        except Exception as e:
            return str(e)

    def fs_delete(self, path):
        try:
            ws_dir = self.kernel.workspace_service.get_workspace_dir()
            target_path = os.path.abspath(os.path.join(ws_dir, path))

            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
                return f"Directory deleted: {path}"
            elif os.path.exists(target_path):
                os.remove(target_path)
                return f"File deleted: {path}"
            else:
                return f"Path not found: {path}"
        except Exception as e:
            return str(e)
