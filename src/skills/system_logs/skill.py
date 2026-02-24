from ..base import SkillBase
from typing import Dict, Any, List
import logging
from utils.logging_config import list_log_files, read_recent_logs

logger = logging.getLogger("SystemLogsSkill")

class SystemLogsSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "logs"
        self._contract = {} # Will be loaded by loader

    @property
    def name(self) -> str: return "system_logs"

    @property
    def actions(self) -> List[str]: return ["list", "read"]

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]

        if action == "list":
            files = list_log_files()
            context_map = self._contract.get("context_map", {})
            items = []
            for f in files:
                desc = context_map.get(f, "System log file.")
                items.append({"file": f, "description": desc})
            lines = ["Categorias de logs disponíveis:"]
            for item in items:
                lines.append(f"- {item['file']}: {item['description']}")
            return {
                "ok": True,
                "status": "success",
                "action": "list",
                "count": len(items),
                "logs": items,
                "text": "\n".join(lines),
            }

        elif action == "read":
            filename = params.get("file", "assistant.log")
            lines = params.get("lines", 20)
            
            # Security: Caps and validation
            try:
                lines = int(lines)
            except Exception:
                lines = 20
            lines = max(1, min(lines, 100))
            
            log_content = read_recent_logs(n=lines, filename=filename)
            if isinstance(log_content, list):
                joined = "\n".join(log_content)
                return {
                    "ok": True,
                    "status": "success",
                    "action": "read",
                    "file": filename,
                    "lines_requested": lines,
                    "lines_returned": len(log_content),
                    "content": joined,
                    "text": f"Leitura de {filename}: {len(log_content)} linha(s).",
                }
            return {
                "ok": False,
                "status": "error",
                "action": "read",
                "file": filename,
                "lines_requested": lines,
                "error": "READ_FAILED",
                "message": str(log_content),
                "text": f"Erro ao ler log '{filename}': {str(log_content)}",
            }

        return {
            "ok": False,
            "status": "error",
            "error": "UNKNOWN_ACTION",
            "message": f"Unknown action: {action_id}",
            "text": f"Unknown action em system_logs: {action_id}",
        }
