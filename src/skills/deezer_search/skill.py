import logging
import requests
from typing import Dict, Any, List, Optional
from ..base import SkillBase

logger = logging.getLogger("DeezerSearchSkill")

class DeezerSearchSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "deezer"

    @property
    def name(self) -> str: return "deezer_search"

    @property
    def actions(self) -> List[str]: return ["search"]

    @staticmethod
    def _clamp_limit(value: Any, default: int = 5) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 10))

    def _calculate_confidence(self, query: str, item_name: str, artist_name: Optional[str] = None) -> float:
        query_lower = query.lower()
        item_lower = item_name.lower()
        
        if query_lower == item_lower: return 1.0
        if query_lower in item_lower: return 0.9
        
        if artist_name:
            artist_lower = artist_name.lower()
            if query_lower in artist_lower: return 0.8
            if artist_lower in query_lower and item_lower in query_lower: return 0.95
            
        return 0.5

    @staticmethod
    def _render_text(query: str, provider: str, results: List[Dict[str, Any]]) -> str:
        if not results:
            return f"Nenhum resultado encontrado para '{query}' no Deezer."
        lines = [f"Resultados Deezer para '{query}' ({len(results)} itens):"]
        for i, item in enumerate(results, start=1):
            title = item.get("title") or "Sem título"
            artist = item.get("artist")
            score = item.get("confidenceScore")
            line = f"{i}. {title}"
            if artist:
                line += f" - {artist}"
            if score is not None:
                line += f" (score {score:.2f})"
            lines.append(line)
            if item.get("url"):
                lines.append(f"   URL: {item['url']}")
        lines.append(f"Provider: {provider}")
        return "\n".join(lines)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        query = params.get("query")
        search_type = params.get("type", "track")
        limit = self._clamp_limit(params.get("limit") or self.config.get("defaults", {}).get("limit", 5), default=5)
        base_url = self.config.get("api", {}).get("baseUrl", "https://api.deezer.com")

        if not query:
            return {
                "ok": False,
                "status": "error",
                "error": "MISSING_QUERY",
                "message": "Missing query for Deezer search.",
                "provider": "deezer",
                "query": "",
                "count": 0,
                "results": [],
                "best": None,
                "text": "Erro: parâmetro 'query' é obrigatório para deezer.search.search.",
            }

        if search_type not in {"track", "artist", "album", "playlist"}:
            return {
                "ok": False,
                "status": "error",
                "error": "INVALID_TYPE",
                "message": f"Unsupported Deezer type: {search_type}",
                "provider": "deezer",
                "query": query,
                "count": 0,
                "results": [],
                "best": None,
                "text": f"Erro: tipo '{search_type}' não suportado em deezer.search.search.",
            }

        try:
            # Deezer search endpoint: /search/{type}?q={query}
            # For track/artist/album/playlist
            endpoint = f"{base_url}/search/{search_type}"
            response = requests.get(
                endpoint,
                params={"q": query, "limit": limit},
                timeout=10
            )
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "status": "error",
                    "error": "HTTP_ERROR",
                    "message": f"Deezer API HTTP {response.status_code}",
                    "provider": "deezer",
                    "query": query,
                    "count": 0,
                    "results": [],
                    "best": None,
                    "text": f"Erro na API do Deezer: HTTP {response.status_code}",
                }
            data = response.json()
            if isinstance(data, dict) and data.get("error"):
                err = data["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                return {
                    "ok": False,
                    "status": "error",
                    "error": "API_ERROR",
                    "message": msg or "Unknown Deezer API error",
                    "provider": "deezer",
                    "query": query,
                    "count": 0,
                    "results": [],
                    "best": None,
                    "text": f"Erro na API do Deezer: {msg or 'erro desconhecido'}",
                }
            
            items = data.get("data", [])
            results = []
            
            for item in items:
                display_name = item.get("title") or item.get("name") or "Untitled"
                artist_name = item.get("artist", {}).get("name") if "artist" in item else None
                score = self._calculate_confidence(query, display_name, artist_name)
                
                res = {
                    "id": item["id"],
                    "url": item.get("link"),
                    "title": display_name,
                    "artist": artist_name,
                    "album": item.get("album", {}).get("title") if "album" in item else None,
                    "durationSec": item.get("duration"),
                    "confidenceScore": score,
                    "matchReason": "Exact match" if score == 1.0 else "Partial match",
                    "source": "deezer_api",
                }
                results.append(res)

            results.sort(key=lambda x: x["confidenceScore"], reverse=True)
            best = results[0] if results else None
            text = self._render_text(query, "deezer_api", results)

            return {
                "ok": True,
                "status": "success" if results else "empty",
                "results": results,
                "best": best,
                "provider": "deezer",
                "surfaceHint": "deezer",
                "query": query,
                "count": len(results),
                "type": search_type,
                "text": text,
            }
        except Exception as e:
            logger.error(f"Deezer Search Execution Error: {e}")
            return {
                "ok": False,
                "status": "error",
                "error": "EXCEPTION",
                "message": str(e),
                "provider": "deezer",
                "query": query,
                "count": 0,
                "results": [],
                "best": None,
                "text": f"Erro na busca do Deezer: {str(e)}",
            }
