import os
from typing import Dict, Any
from services.i18n import I18nService

class SafetyService:
    def __init__(self):
        self.i18n = I18nService(default_locale="en")
        self.workspace_dir = ""

        # Commands that are SAFE to run without approval (read-only or common)
        self.safe_shell_patterns = [
            "ls", "df", "free", "uptime", "whoami", "pwd", "date", "cat", "grep", "find", "echo"
        ]

    def set_workspace_dir(self, workspace_dir: str) -> None:
        try:
            self.workspace_dir = os.path.abspath(str(workspace_dir or "").strip())
        except Exception:
            self.workspace_dir = ""

    def _resolve_fs_target(self, raw_path: Any) -> str:
        path_str = str(raw_path or "").strip()
        if not path_str:
            return ""
        path_str = os.path.expanduser(os.path.expandvars(path_str))
        if os.path.isabs(path_str):
            return os.path.abspath(path_str)
        if self.workspace_dir:
            return os.path.abspath(os.path.join(self.workspace_dir, path_str))
        return os.path.abspath(path_str)

    def _is_inside_workspace(self, target_path: str) -> bool:
        if not target_path or not self.workspace_dir:
            return False
        try:
            common = os.path.commonpath([self.workspace_dir, target_path])
            return common == self.workspace_dir
        except Exception:
            return False

    def is_sensitive(self, action: str, params: Dict[str, Any], capability_registry: Any = None) -> bool:
        """
        Determines if an action is sensitive and requires HITL approval.
        """
        action = (action or "").lower().strip()

        # File read/list/write/delete inside workspace is frictionless.
        # Outside workspace should pause worker in HITL waiting approval.
        if action in {"system.control.fs.list", "system.control.fs.write", "system.control.fs.delete", "fs_list", "fs_write", "fs_delete"}:
            target_path = self._resolve_fs_target((params or {}).get("path"))
            if not target_path:
                return True
            return not self._is_inside_workspace(target_path)

        metadata = self._get_action_metadata(action, capability_registry)
        permissions = metadata.get("permissions") if isinstance(metadata.get("permissions"), dict) else {}
        requires_approval = bool(permissions.get("requires_approval", False))

        if not requires_approval:
            return False

        # Shell actions keep a command-level exception for common read-only commands.
        if action.startswith("shell.") or action == "execute_command":
            cmd_str = (params or {}).get("command", "").lower().strip()
            if not cmd_str:
                return False

            danger_patterns = ["sudo ", "rm ", "mkfs", "> /dev/", "chmod ", "chown ", ":(){ :|:& };:"]
            if any(pattern in cmd_str for pattern in danger_patterns):
                return True

            base_cmd = cmd_str.split()[0]
            if base_cmd in self.safe_shell_patterns:
                return False

            # Keep behavior permissive for non-sudo ad-hoc commands.
            return "sudo" in cmd_str

        return True

    def get_approval_message(self, action: str, params: Dict[str, Any]) -> str:
        """
        Generates a human-friendly message describing the sensitive action.
        """
        action = (action or "").lower().strip()

        if "process.kill" in action:
            return self.i18n.t("safety.confirm_process_kill", pid=params.get("pid"))
        elif "control.power" in action:
            return self.i18n.t("safety.confirm_power")
        elif action.startswith("shell."):
            return self.i18n.t("safety.confirm_shell", command=params.get("command"))
        elif "service_" in action or "service.manage" in action:
            return self.i18n.t("safety.confirm_service", unit=params.get("unit"), action=action)
        elif action in {"system.control.fs.list", "system.control.fs.write", "system.control.fs.delete"}:
            path = str((params or {}).get("path") or "").strip() or "<empty-path>"
            return self.i18n.t("safety.confirm_fs_outside_workspace", action=action, path=path)
            
        return self.i18n.t("safety.confirm_generic", action=action)

    @staticmethod
    def _get_action_metadata(action: str, capability_registry: Any = None) -> Dict[str, Any]:
        if not (capability_registry and hasattr(capability_registry, "get_action_metadata")):
            raise RuntimeError("Canonical capability registry is required for safety checks.")
        metadata = capability_registry.get_action_metadata(action)
        if not isinstance(metadata, dict) or not metadata:
            raise RuntimeError(f"Action metadata not found for '{action}'.")
        return metadata
