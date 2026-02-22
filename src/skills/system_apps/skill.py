import logging
import platform
import shlex
import shutil
import subprocess
import time
import webbrowser
from typing import Any, Dict, List

import psutil

from ..base import SkillBase

logger = logging.getLogger("SystemAppsSkill")

class SystemAppsSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "app"
        self._app_map = {
            "notas": "notepad",
            "bloco de notas": "notepad",
            "netflix": "https://www.netflix.com/br/",
            "youtube": "https://www.youtube.com/",
            "youtube music": "https://music.youtube.com/",
            "spotify": "https://open.spotify.com/",
            "star plus": "https://www.starplus.com/pt-br",
            "disney plus": "https://www.disneyplus.com/pt-br",
            "prime video": "https://www.primevideo.com/",
            "hbomax": "https://play.hbomax.com/",
            "hbo": "https://play.hbomax.com/",
            "maps": "https://www.google.com.br/maps/preview",
            "mapa": "https://www.google.com.br/maps/preview",
            "google": "https://www.google.com.br/",
            "facebook": "https://www.facebook.com/",
            "instagram": "https://www.instagram.com/",
            "whatsapp": "https://web.whatsapp.com/",
            "telegram": "https://web.telegram.org/",
            "twitter": "https://twitter.com/",
            "tiktok": "https://www.tiktok.com/pt-BR/",
            "linkedin": "https://www.linkedin.com/",
            "github": "https://github.com/",
            "gmail": "https://mail.google.com/mail/u/0/#inbox",
            "outlook": "https://outlook.live.com/mail/inbox",
            "drive": "https://drive.google.com/drive/my-drive",
            "google drive": "https://drive.google.com/drive/my-drive",
            "dropbox": "https://www.dropbox.com/home",
            "onedrive": "https://onedrive.live.com/",
            "mega": "https://mega.nz/"
        }

    @property
    def name(self) -> str:
        return "system_apps"

    @property
    def actions(self) -> List[str]:
        return ["open", "close", "find"]

    @staticmethod
    def _result(ok: bool, status: str, text: str, **extra: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": ok, "status": status, "text": text}
        payload.update(extra)
        return payload

    @staticmethod
    def _extract_process_name(command: str) -> str:
        token = shlex.split(command)[0] if command else ""
        return token.rsplit("/", 1)[-1]

    @staticmethod
    def _is_url(value: str) -> bool:
        return value.startswith("http://") or value.startswith("https://")

    @staticmethod
    def _process_running(program_name: str) -> bool:
        if not program_name:
            return False
        needle = program_name.lower()
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                cmd = " ".join(proc.info.get("cmdline") or []).lower()
                if needle in name or needle in cmd:
                    return True
            except Exception:
                continue
        return False

    def _open_linux(self, program: str) -> bool:
        try:
            subprocess.run(
                ["xdg-open", program],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            return True
        except Exception:
            try:
                subprocess.Popen(
                    shlex.split(program),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                return False

    def _open_windows(self, program: str) -> bool:
        try:
            res = subprocess.run(
                ["cmd", "/c", "start", "", program],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False

    def _close_windows(self, program_name: str) -> bool:
        try:
            target = program_name if program_name.endswith(".exe") else f"{program_name}.exe"
            subprocess.run(
                ["taskkill", "/f", "/im", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            return True
        except Exception:
            return False

    def _close_linux(self, program_name: str) -> bool:
        try:
            subprocess.run(
                ["pkill", "-f", program_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
            return True
        except Exception:
            return False

    def _resolve_target(self, params: Dict[str, Any]) -> str:
        return str(params.get("program_name") or params.get("query") or "").strip()

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]

        if action == "open":
            target = self._resolve_target(params)
            if not target:
                return self._result(
                    ok=False,
                    status="error",
                    text="Missing required parameter 'program_name' (or alias 'query').",
                    error="MISSING_PROGRAM_NAME",
                    message="program_name is required for system.apps.open",
                )

            mapped_target = self._app_map.get(target.lower(), target)

            if self._is_url(mapped_target):
                opened = webbrowser.open(mapped_target)
                return self._result(
                    ok=bool(opened),
                    status="success" if opened else "error",
                    text=f"Opening '{target}' in browser.",
                    action="open",
                    target=target,
                    resolved_target=mapped_target,
                    opened=bool(opened),
                )

            success = False
            if platform.system() == "Windows":
                success = self._open_windows(mapped_target)
            else:
                success = self._open_linux(mapped_target)

            process_name = self._extract_process_name(mapped_target)
            if process_name:
                time.sleep(0.4)
            running = self._process_running(process_name)
            ok = bool(success or running)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                text=f"Program '{target}' started." if ok else f"Failed to open '{target}'.",
                action="open",
                target=target,
                resolved_target=mapped_target,
                running=running,
            )

        if action == "close":
            target = self._resolve_target(params)
            if not target:
                return self._result(
                    ok=False,
                    status="error",
                    text="Missing required parameter 'program_name' (or alias 'query').",
                    error="MISSING_PROGRAM_NAME",
                    message="program_name is required for system.apps.close",
                )

            if platform.system() == "Windows":
                sent = self._close_windows(target)
            else:
                sent = self._close_linux(target)

            time.sleep(0.4)
            still_running = self._process_running(target)
            ok = bool(sent and not still_running)
            return self._result(
                ok=ok,
                status="success" if ok else "error",
                text=(
                    f"Program '{target}' closed."
                    if ok
                    else f"Close signal sent for '{target}', but process may still be running."
                ),
                action="close",
                target=target,
                signal_sent=sent,
                still_running=still_running,
            )

        if action == "find":
            target = self._resolve_target(params)
            if not target:
                return self._result(
                    ok=False,
                    status="error",
                    text="Missing required parameter 'program_name' (or alias 'query').",
                    error="MISSING_PROGRAM_NAME",
                    message="program_name is required for system.apps.find",
                )

            mapped_target = self._app_map.get(target.lower(), target)
            if self._is_url(mapped_target):
                return self._result(
                    ok=True,
                    status="success",
                    text=f"Alias '{target}' is available as URL target.",
                    action="find",
                    target=target,
                    resolved_target=mapped_target,
                    found=True,
                    source="alias_map",
                )

            binary = self._extract_process_name(mapped_target)
            binary_path = shutil.which(binary)
            running = self._process_running(binary)
            found = bool(binary_path or running)
            return self._result(
                ok=True,
                status="success" if found else "empty",
                text=(
                    f"Found '{target}' in system path."
                    if found
                    else f"Could not find '{target}' in system path."
                ),
                action="find",
                target=target,
                resolved_target=mapped_target,
                found=found,
                binary_path=binary_path,
                running=running,
            )

        return self._result(
            ok=False,
            status="error",
            text=f"Unknown action: {action_id}",
            error="UNKNOWN_ACTION",
            message=f"Unknown action: {action_id}",
        )
