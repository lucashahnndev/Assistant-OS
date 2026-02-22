import logging
import requests
import os
from urllib.parse import quote_plus, urlparse, parse_qs
from typing import Dict, Any, List, Optional
from ..base import SkillBase

logger = logging.getLogger("YouTubeSearchSkill")

try:
    from ddgs import DDGS  # type: ignore
except Exception:  # pragma: no cover - fallback for older environments
    from duckduckgo_search import DDGS  # type: ignore


class YouTubeSearchSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "youtube"

    @property
    def name(self) -> str: return "youtube_search"

    @property
    def actions(self) -> List[str]: return ["find"]

    @staticmethod
    def _clamp_limit(value: Any, default: int = 5) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 10))

    def _get_api_key(self) -> Optional[str]:
        api_key = self.config.get("apiKey")
        if not api_key or "ENV_" in api_key:
            api_key = os.getenv("GOOGLE_YOUTUBE_API_KEY")
        return api_key

    def _calculate_confidence(self, query: str, title: str, channel: str) -> float:
        query_lower = query.lower()
        title_lower = title.lower()
        
        if query_lower == title_lower: return 1.0
        if query_lower in title_lower: return 0.9
        
        # If query mentions channel
        if channel.lower() in query_lower: return 0.85

        return 0.6

    @staticmethod
    def _youtube_url_from_id(item_id: Dict[str, Any], search_type: str, surface: str) -> Optional[str]:
        if search_type == "playlist":
            playlist_id = item_id.get("playlistId")
            if playlist_id:
                return f"https://www.youtube.com/playlist?list={playlist_id}"
            return None
        if search_type == "channel":
            channel_id = item_id.get("channelId")
            if channel_id:
                return f"https://www.youtube.com/channel/{channel_id}"
            return None

        video_id = item_id.get("videoId")
        if not video_id:
            return None
        if surface == "music":
            return f"https://music.youtube.com/watch?v={video_id}"
        return f"https://www.youtube.com/watch?v={video_id}"

    @staticmethod
    def _extract_youtube_id(url: str, search_type: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            if "youtube.com" not in host and "youtu.be" not in host:
                return None

            if search_type == "playlist":
                query = parse_qs(parsed.query)
                return query.get("list", [None])[0]

            if search_type == "channel":
                parts = [p for p in parsed.path.split("/") if p]
                if not parts:
                    return None
                if parts[0] == "channel" and len(parts) > 1:
                    return parts[1]
                if parts[0].startswith("@"):
                    return parts[0]
                return None

            if host == "youtu.be":
                parts = [p for p in parsed.path.split("/") if p]
                return parts[0] if parts else None

            query = parse_qs(parsed.query)
            if "v" in query:
                return query["v"][0]

            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in {"shorts", "live"}:
                return parts[1]
        except Exception:
            return None
        return None

    def _fallback_search_web(self, query: str, limit: int, search_type: str) -> List[Dict[str, Any]]:
        try:
            target = "youtube.com"
            q = f"site:{target} {query}"
            results: List[Dict[str, Any]] = []
            with DDGS() as ddgs:
                for item in ddgs.text(q, max_results=max(5, limit * 4)):
                    if not isinstance(item, dict):
                        continue
                    url = (item.get("href") or "").strip()
                    if not url:
                        continue
                    entry_id = self._extract_youtube_id(url, search_type)
                    if not entry_id:
                        continue
                    title = (item.get("title") or "YouTube result").strip()
                    snippet = (item.get("body") or "").strip()
                    results.append({
                        "videoId": entry_id if search_type == "video" else None,
                        "playlistId": entry_id if search_type == "playlist" else None,
                        "channelId": entry_id if search_type == "channel" else None,
                        "url": url,
                        "title": title,
                        "channel": None,
                        "descriptionSnippet": snippet,
                        "confidenceScore": 0.55,
                        "matchReason": "Web fallback result",
                        "source": "duckduckgo_fallback",
                    })
                    if len(results) >= limit:
                        break
            return results
        except Exception as e:
            logger.error(f"YouTube fallback search error: {e}")
            return []

    @staticmethod
    def _render_text(query: str, results: List[Dict[str, Any]], provider: str) -> str:
        if not results:
            return f"Nenhum resultado encontrado no YouTube para '{query}'."
        lines = [f"Resultados YouTube para '{query}' via {provider} ({len(results)} itens):"]
        for i, item in enumerate(results, start=1):
            title = item.get("title") or "Sem título"
            channel = item.get("channel")
            score = item.get("confidenceScore")
            url = item.get("url")
            head = f"{i}. {title}"
            if channel:
                head += f" - {channel}"
            if score is not None:
                head += f" (score {score:.2f})"
            lines.append(head)
            if url:
                lines.append(f"   URL: {url}")
        return "\n".join(lines)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        query = params.get("query")
        limit = self._clamp_limit(params.get("limit") or self.config.get("defaults", {}).get("limit", 5), default=5)
        surface = params.get("surface") or self.config.get("defaults", {}).get("surfaceMode", "auto")
        search_type = params.get("type", "video")

        if not query:
            return {
                "ok": False,
                "status": "error",
                "error": "MISSING_QUERY",
                "message": "Missing query for YouTube search.",
                "provider": "youtube",
                "query": "",
                "count": 0,
                "results": [],
                "best": None,
                "text": "Erro: parâmetro 'query' é obrigatório para youtube.search.find.",
            }

        if search_type not in {"video", "playlist", "channel"}:
            return {
                "ok": False,
                "status": "error",
                "error": "INVALID_TYPE",
                "message": f"Unsupported YouTube search type: {search_type}",
                "provider": "youtube",
                "query": query,
                "count": 0,
                "results": [],
                "best": None,
                "text": f"Erro: tipo '{search_type}' não suportado em youtube.search.find.",
            }

        # 1. Check Config
        api_key = self._get_api_key()
        if not api_key:
            fallback_results = self._fallback_search_web(query, limit, search_type)
            text = self._render_text(query, fallback_results, "duckduckgo_fallback")
            return {
                "ok": True,
                "status": "success" if fallback_results else "empty",
                "provider": "youtube_fallback_web",
                "query": query,
                "count": len(fallback_results),
                "results": fallback_results,
                "best": fallback_results[0] if fallback_results else None,
                "fallback": True,
                "warning": "YouTube API key not configured. Using web fallback search.",
                "text": text,
            }

        # 2. Search API
        try:
            query_qs = quote_plus(str(query))
            url = (
                "https://www.googleapis.com/youtube/v3/search"
                f"?part=snippet&maxResults={limit}&q={query_qs}&key={api_key}&type={search_type}"
            )
            response = requests.get(url, timeout=10)
            data = response.json()

            if response.status_code >= 400 or "error" in data:
                error_msg = data.get("error", {}).get("message", f"HTTP {response.status_code}")
                fallback_results = self._fallback_search_web(query, limit, search_type)
                text = self._render_text(query, fallback_results, "duckduckgo_fallback")
                return {
                    "ok": True if fallback_results else False,
                    "status": "success" if fallback_results else "error",
                    "provider": "youtube_fallback_web" if fallback_results else "youtube",
                    "query": query,
                    "count": len(fallback_results),
                    "results": fallback_results,
                    "best": fallback_results[0] if fallback_results else None,
                    "fallback": True,
                    "warning": f"YouTube API error: {error_msg}",
                    "text": text if fallback_results else f"Erro na API do YouTube: {error_msg}",
                }

            items = data.get("items", [])
            results = []
            
            for item in items:
                item_id = item.get("id") or {}
                entity_url = self._youtube_url_from_id(item_id, search_type, surface)
                if not entity_url:
                    continue
                
                snippet = item.get("snippet") or {}
                title = snippet.get("title") or "YouTube result"
                channel = snippet.get("channelTitle") or ""
                score = self._calculate_confidence(query, title, channel)
                
                results.append({
                    "videoId": item_id.get("videoId"),
                    "playlistId": item_id.get("playlistId"),
                    "channelId": item_id.get("channelId"),
                    "url": entity_url,
                    "title": title,
                    "channel": channel,
                    "descriptionSnippet": snippet.get("description"),
                    "publishedAt": snippet.get("publishedAt"),
                    "confidenceScore": score,
                    "matchReason": "High relevance" if score >= 0.9 else "Search result",
                    "source": "youtube_api",
                })

            results.sort(key=lambda x: x["confidenceScore"], reverse=True)
            best = results[0] if results else None

            text = self._render_text(query, results, "youtube_api")
            return {
                "ok": True,
                "status": "success" if results else "empty",
                "results": results,
                "best": best,
                "provider": "youtube",
                "query": query,
                "count": len(results),
                "surfaceHint": surface
                ,
                "text": text
            }
        except Exception as e:
            logger.error(f"YouTube Search Execution Error: {e}")
            fallback_results = self._fallback_search_web(query, limit, search_type)
            text = self._render_text(query, fallback_results, "duckduckgo_fallback")
            return {
                "ok": True if fallback_results else False,
                "status": "success" if fallback_results else "error",
                "provider": "youtube_fallback_web" if fallback_results else "youtube",
                "query": query,
                "count": len(fallback_results),
                "results": fallback_results,
                "best": fallback_results[0] if fallback_results else None,
                "fallback": True,
                "warning": f"YouTube exception: {str(e)}",
                "text": text if fallback_results else f"Erro na execução da busca do YouTube: {str(e)}",
            }
