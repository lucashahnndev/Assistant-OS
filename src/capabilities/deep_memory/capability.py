from ..base import CapabilityBase
from typing import Dict, Any, List


class DeepMemoryCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "deep_memory"

    @property
    def name(self) -> str:
        return "deep_memory"

    @property
    def actions(self) -> List[str]:
        return ["store_memory", "recall_memory"]

    @staticmethod
    def _resolve_query(params: Dict[str, Any]) -> str:
        for key in ("query", "q", "term", "text"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _resolve_content(params: Dict[str, Any]) -> str:
        for key in ("content", "text", "note", "value", "message"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
        ms = getattr(orch, "memory_service", None) if orch else None
        if not ms:
            return {
                "ok": False,
                "status": "error",
                "error": "MEMORY_SERVICE_UNAVAILABLE",
                "error_details": "Deep memory unavailable.",
            }

        if action == "recall_memory":
            query = self._resolve_query(params)
            results = ms.search_memory(query)
            return {
                "ok": True,
                "status": "success" if results else "empty",
                "action": "recall_memory",
                "query": query,
                "count": len(results),
                "results": results,
                "error_details": f"Deep memory returned {len(results)} result(s).",
            }

        if action == "store_memory":
            content = self._resolve_content(params)
            if not content:
                return {
                    "ok": False,
                    "status": "error",
                    "error": "MISSING_CONTENT",
                    "error_details": "Missing 'content' parameter for store_memory.",
                }
            category = str(params.get("category") or "general")
            ms.add_fact(category, content)
            return {
                "ok": True,
                "status": "success",
                "action": "store_memory",
                "category": category,
                "stored": True,
                "error_details": "Deep memory fact stored.",
            }

        return {
            "ok": False,
            "status": "error",
            "error": "UNKNOWN_ACTION",
            "error_details": f"Unknown deep memory action: {action_id}",
        }
