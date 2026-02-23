import logging
import requests
import base64
import time
import os
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional
from ..base import SkillBase

logger = logging.getLogger("SpotifySearchSkill")

try:
    from ddgs import DDGS  # type: ignore
except Exception:  # pragma: no cover - fallback for older environments
    from duckduckgo_search import DDGS  # type: ignore


class SpotifySearchSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "spotify"
        self._access_token = None
        self._token_expires_at = 0

    @property
    def name(self) -> str: return "spotify_search"

    @property
    def actions(self) -> List[str]: return ["search"]

    @staticmethod
    def _clamp_limit(value: Any, default: int = 5) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 10))

    @staticmethod
    def _resolve_query(params: Dict[str, Any]) -> str:
        for key in ("query", "search_query", "searchQuery", "q", "term", "text"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _get_auth_config(self) -> Dict[str, str]:
        auth = self.config.get("auth", {})
        client_id = auth.get("clientId") or os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = auth.get("clientSecret") or os.getenv("SPOTIFY_CLIENT_SECRET")
        return {"client_id": client_id, "client_secret": client_secret}

    def _get_access_token(self) -> Optional[str]:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        auth = self._get_auth_config()
        if not auth["client_id"] or not auth["client_secret"]:
            return None

        try:
            auth_str = f"{auth['client_id']}:{auth['client_secret']}"
            auth_base64 = base64.b64encode(auth_str.encode()).decode()
            
            response = requests.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {auth_base64}"},
                timeout=10
            )
            data = response.json()
            if "access_token" in data:
                self._access_token = data["access_token"]
                self._token_expires_at = time.time() + data["expires_in"] - 60
                return self._access_token
        except Exception as e:
            logger.error(f"Spotify Auth Error: {e}")
        return None

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
    def _extract_spotify_id(url: str, search_type: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            if "spotify.com" not in host:
                return None
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) < 2:
                return None
            if parts[0] != search_type:
                return None
            return parts[1].split("?")[0]
        except Exception:
            return None

    def _fallback_search_web(self, query: str, limit: int, search_type: str) -> List[Dict[str, Any]]:
        try:
            q = f"site:open.spotify.com/{search_type} {query}"
            results = []
            with DDGS() as ddgs:
                for item in ddgs.text(q, max_results=max(5, limit * 4)):
                    if not isinstance(item, dict):
                        continue
                    url = (item.get("href") or "").strip()
                    entry_id = self._extract_spotify_id(url, search_type)
                    if not entry_id:
                        continue
                    title = (item.get("title") or "Spotify result").strip()
                    snippet = (item.get("body") or "").strip()
                    results.append({
                        "id": entry_id,
                        "url": url,
                        "title": title,
                        "artist": None,
                        "album": None,
                        "confidenceScore": 0.55,
                        "matchReason": "Web fallback result",
                        "descriptionSnippet": snippet,
                        "source": "duckduckgo_fallback",
                    })
                    if len(results) >= limit:
                        break
            return results
        except Exception as e:
            logger.error(f"Spotify fallback search error: {e}")
            return []

    @staticmethod
    def _render_text(query: str, provider: str, results: List[Dict[str, Any]]) -> str:
        if not results:
            return f"Nenhum resultado encontrado para '{query}' no Spotify."
        lines = [f"Resultados Spotify para '{query}' ({len(results)} itens):"]
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
        query = self._resolve_query(params)
        search_type = params.get("type") or params.get("search_type") or "track"
        limit = self._clamp_limit(
            params.get("limit") or params.get("max_results") or params.get("maxResults") or self.config.get("defaults", {}).get("limit", 5),
            default=5,
        )
        market = params.get("market") or self.config.get("defaults", {}).get("market", "BR")

        if not query:
            return {
                "ok": False,
                "status": "error",
                "error": "MISSING_QUERY",
                "message": "Missing query for Spotify search.",
                "provider": "spotify",
                "query": "",
                "count": 0,
                "results": [],
                "best": None,
                "text": "Erro: parâmetro 'query' é obrigatório para spotify.search.search.",
            }

        if search_type not in {"track", "artist", "album", "playlist"}:
            return {
                "ok": False,
                "status": "error",
                "error": "INVALID_TYPE",
                "message": f"Unsupported Spotify type: {search_type}",
                "provider": "spotify",
                "query": query,
                "count": 0,
                "results": [],
                "best": None,
                "text": f"Erro: tipo '{search_type}' não suportado em spotify.search.search.",
            }

        # 1. Check Config
        auth = self._get_auth_config()
        if not auth["client_id"] or not auth["client_secret"]:
            fallback_results = self._fallback_search_web(query, limit, search_type)
            missing = []
            if not auth["client_id"]:
                missing.append("clientId (env: SPOTIFY_CLIENT_ID)")
            if not auth["client_secret"]:
                missing.append("clientSecret (env: SPOTIFY_CLIENT_SECRET)")
            text = self._render_text(query, "duckduckgo_fallback", fallback_results)
            return {
                "ok": True if fallback_results else False,
                "status": "success" if fallback_results else "error",
                "error": None if fallback_results else "MISSING_CONFIG",
                "message": (
                    f"Configuração do Spotify incompleta. Faltando: {', '.join(missing)}"
                    if missing else "Configuração do Spotify incompleta."
                ),
                "missing_fields": missing,
                "provider": "spotify_fallback_web" if fallback_results else "spotify",
                "query": query,
                "count": len(fallback_results),
                "results": fallback_results,
                "best": fallback_results[0] if fallback_results else None,
                "fallback": True,
                "text": text if fallback_results else f"Erro de configuração Spotify: {', '.join(missing)}",
            }

        # 2. Get Token
        token = self._get_access_token()
        if not token:
            fallback_results = self._fallback_search_web(query, limit, search_type)
            text = self._render_text(query, "duckduckgo_fallback", fallback_results)
            return {
                "ok": True if fallback_results else False,
                "status": "success" if fallback_results else "error",
                "error": None if fallback_results else "AUTH_FAILED",
                "message": "Erro ao obter token de acesso do Spotify. Verifique suas credenciais.",
                "provider": "spotify_fallback_web" if fallback_results else "spotify",
                "query": query,
                "count": len(fallback_results),
                "results": fallback_results,
                "best": fallback_results[0] if fallback_results else None,
                "fallback": True,
                "text": text if fallback_results else "Erro ao autenticar no Spotify.",
            }

        # 3. Perform Search
        try:
            response = requests.get(
                "https://api.spotify.com/v1/search",
                params={"q": query, "type": search_type, "limit": limit, "market": market},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10
            )
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "status": "error",
                    "error": "HTTP_ERROR",
                    "message": f"Spotify API HTTP {response.status_code}",
                    "provider": "spotify",
                    "query": query,
                    "count": 0,
                    "results": [],
                    "best": None,
                    "text": f"Erro na API do Spotify: HTTP {response.status_code}",
                }
            data = response.json()
            if isinstance(data, dict) and data.get("error"):
                err = data["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                return {
                    "ok": False,
                    "status": "error",
                    "error": "API_ERROR",
                    "message": msg or "Unknown Spotify API error",
                    "provider": "spotify",
                    "query": query,
                    "count": 0,
                    "results": [],
                    "best": None,
                    "text": f"Erro na API do Spotify: {msg or 'erro desconhecido'}",
                }
            
            type_key = f"{search_type}s"
            items = data.get(type_key, {}).get("items", [])
            
            results = []
            for item in items:
                main_artist = item.get("artists", [{}])[0].get("name") if "artists" in item else None
                score = self._calculate_confidence(query, item['name'], main_artist)
                
                res = {
                    "id": item["id"],
                    "url": item["external_urls"]["spotify"],
                    "title": item["name"],
                    "artist": main_artist,
                    "album": item.get("album", {}).get("name") if "album" in item else None,
                    "confidenceScore": score,
                    "matchReason": "Exact match" if score == 1.0 else "Partial match",
                    "source": "spotify_api",
                }
                results.append(res)

            # Sort by confidence
            results.sort(key=lambda x: x["confidenceScore"], reverse=True)
            best = results[0] if results else None
            text = self._render_text(query, "spotify_api", results)

            return {
                "ok": True,
                "status": "success" if results else "empty",
                "results": results,
                "best": best,
                "provider": "spotify",
                "surfaceHint": "spotify",
                "query": query,
                "count": len(results),
                "type": search_type,
                "market": market,
                "text": text,
            }
        except Exception as e:
            logger.error(f"Spotify Search Execution Error: {e}")
            fallback_results = self._fallback_search_web(query, limit, search_type)
            text = self._render_text(query, "duckduckgo_fallback", fallback_results)
            return {
                "ok": True if fallback_results else False,
                "status": "success" if fallback_results else "error",
                "error": None if fallback_results else "EXCEPTION",
                "message": str(e),
                "provider": "spotify_fallback_web" if fallback_results else "spotify",
                "query": query,
                "count": len(fallback_results),
                "results": fallback_results,
                "best": fallback_results[0] if fallback_results else None,
                "fallback": True,
                "text": text if fallback_results else f"Erro na busca do Spotify: {str(e)}",
            }
