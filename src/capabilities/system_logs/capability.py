from ..base import CapabilityBase
from typing import Dict, Any, List
import logging
from utils.logging_config import list_log_files, read_recent_logs

logger = logging.getLogger("SystemLogsCapability")

class SystemLogsCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "logs"

    @property
    def name(self) -> str: return "system_logs"

    @property
    def actions(self) -> List[str]: return ["list", "read"]

    @staticmethod
    def _success(summary: str, **extra: Any) -> Dict[str, Any]:
        payload = {
            "ok": True,
            "success": True,
            "status": "success",
            "reason": None,
            "result_summary": str(summary or "").strip() or "System log operation completed.",
            "structured_result": dict(extra),
            "artifacts": [],
            "attachment_delivery": {"status": "none", "confirmed": False},
            "freshness": {"status": "current", "source": "system_logs"},
            "truncated": False,
            "requires_followup": False,
            "next_step_context": {},
            "diagnostics": {"capability": "system_logs"},
        }
        payload.update(extra)
        return payload

    @staticmethod
    def _error(code: str, summary: str, **extra: Any) -> Dict[str, Any]:
        payload = {
            "ok": False,
            "success": False,
            "status": "error",
            "error": code,
            "reason": code,
            "result_summary": str(summary or "").strip() or "System log operation failed.",
            "structured_result": dict(extra),
            "artifacts": [],
            "attachment_delivery": {"status": "none", "confirmed": False},
            "freshness": {"status": "current", "source": "system_logs"},
            "truncated": False,
            "requires_followup": False,
            "next_step_context": {},
            "diagnostics": {"capability": "system_logs", "error": code},
        }
        payload.update(extra)
        return payload

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]

        if action == "list":
            files = list_log_files()
            context_map = self.config.get("context_map", {}) if isinstance(self.config, dict) else {}
            items = []
            for f in files:
                desc = context_map.get(f, "System log file.")
                items.append({"file": f, "description": desc})
            lines = ["Categorias de logs disponíveis:"]
            for item in items:
                lines.append(f"- {item['file']}: {item['description']}")
            return self._success(
                f"Listed {len(items)} log file(s).",
                action="list",
                count=len(items),
                logs=items,
                content="\n".join(lines),
            )

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
                return self._success(
                    f"Read {len(log_content)} line(s) from {filename}.",
                    action="read",
                    file=filename,
                    lines_requested=lines,
                    lines_returned=len(log_content),
                    content=joined,
                    error_details=f"Leitura de {filename}: {len(log_content)} linha(s).",
                )
            return self._error(
                "READ_FAILED",
                f"Erro ao ler log '{filename}': {str(log_content)}",
                action="read",
                file=filename,
                lines_requested=lines,
            )

        return self._error(
            "UNKNOWN_ACTION",
            f"Unknown action em system_logs: {action_id}",
            action=action,
        )
