from ..base import SkillBase
from typing import Dict, Any, List

class MemorySkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "memory"

    @property
    def name(self) -> str: return "memory"

    @property
    def actions(self) -> List[str]: return ["recall", "store"]

    @staticmethod
    def _resolve_query(params: Dict[str, Any]) -> str:
        for key in ("query", "search_query", "searchQuery", "q", "term", "text"):
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
                "message": "MemoryService not available.",
                "text": "Erro: serviço de memória indisponível.",
            }

        if action == "recall":
            query = self._resolve_query(params)
            results = ms.search_memory(query)
            count = len(results) if isinstance(results, list) else 0
            return {
                "ok": True,
                "status": "success" if count > 0 else "empty",
                "action": "recall",
                "query": query,
                "count": count,
                "results": results if isinstance(results, list) else [],
                "text": f"Memória: {count} resultado(s) para '{query}'.",
            }
        elif action == "store":
            content = self._resolve_content(params)
            if not content:
                return {
                    "ok": False,
                    "status": "error",
                    "error": "MISSING_CONTENT",
                    "message": "Missing 'content' parameter.",
                    "text": "Erro: parâmetro 'content' é obrigatório para memory.store.",
                }
            category = params.get("category", "general")
            ms.add_fact(category, content)
            return {
                "ok": True,
                "status": "success",
                "action": "store",
                "category": category,
                "stored": True,
                "text": f"Fato armazenado na memória (categoria: {category}).",
            }
        return {
            "ok": False,
            "status": "error",
            "error": "UNKNOWN_ACTION",
            "message": f"Unknown memory action: {action_id}",
            "text": f"Ação de memória desconhecida: {action_id}",
        }
