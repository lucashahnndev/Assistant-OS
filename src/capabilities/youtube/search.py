import logging
from time import perf_counter
from typing import Any, Dict, List, Optional
from server.core.secret_manager import resolve_secret_ref
from urllib.parse import parse_qs, quote_plus, urlparse

import requests

from ..base import CapabilityBase
from ..shared.error_contract import error_envelope, success_envelope
from ..shared.google_auth import resolve_google_request_auth
from ..shared.link_validation import validate_media_results

logger = logging.getLogger("YouTubeSearchCapability")

try:
    from ddgs import DDGS  # type: ignore
except Exception:  # pragma: no cover - fallback for older environments
    from duckduckgo_search import DDGS  # type: ignore


class YouTubeSearchCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "youtube"

    @property
    def name(self) -> str:
        return "youtube_search"

    @property
    def actions(self) -> List[str]:
        return ["search.find"]

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

    def _get_api_key(self) -> Optional[str]:
        api_key = resolve_secret_ref(self.config.get("apiKey"))
        return str(api_key or "").strip() or None

    def _calculate_confidence(self, query: str, title: str, channel: str) -> float:
        query_lower = query.lower()
        title_lower = title.lower()

        if query_lower == title_lower:
            return 1.0
        if query_lower in title_lower:
            return 0.9

        if channel.lower() in query_lower:
            return 0.85

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
            results: List[Dict[str, Any]] = []
            seen_ids = set()
            if search_type == "video":
                with DDGS() as ddgs:
                    try:
                        try:
                            video_gen = ddgs.videos(query, max_results=max(8, limit * 5), timeout=4)
                        except TypeError:
                            video_gen = ddgs.videos(query, max_results=max(8, limit * 5))
                        for item in video_gen:
                            if not isinstance(item, dict):
                                continue
                            url = (item.get("content") or item.get("url") or item.get("href") or "").strip()
                            if not url:
                                continue
                            entry_id = self._extract_youtube_id(url, search_type)
                            if not entry_id or entry_id in seen_ids:
                                continue
                            seen_ids.add(entry_id)
                            results.append(
                                {
                                    "videoId": entry_id,
                                    "playlistId": None,
                                    "channelId": None,
                                    "url": url,
                                    "title": (item.get("title") or "YouTube result").strip(),
                                    "channel": (item.get("uploader") or item.get("publisher") or "").strip() or None,
                                    "descriptionSnippet": (item.get("description") or "").strip(),
                                    "confidenceScore": 0.6,
                                    "matchReason": "Video web fallback result",
                                    "source": "duckduckgo_videos_fallback",
                                }
                            )
                            if len(results) >= limit:
                                return results
                    except Exception as video_exc:
                        logger.debug("YouTube fallback videos query failed: %s", video_exc)

            queries = [
                f"{query} site:youtube.com",
                f"{query} youtube",
                f"site:youtube.com {query}",
            ]
            with DDGS() as ddgs:
                for q in queries:
                    try:
                        try:
                            generator = ddgs.text(q, max_results=max(8, limit * 5), timeout=4)
                        except TypeError:
                            generator = ddgs.text(q, max_results=max(8, limit * 5))

                        for item in generator:
                            if not isinstance(item, dict):
                                continue
                            url = (item.get("href") or item.get("url") or item.get("link") or "").strip()
                            if not url:
                                continue
                            entry_id = self._extract_youtube_id(url, search_type)
                            if not entry_id or entry_id in seen_ids:
                                continue

                            seen_ids.add(entry_id)
                            title = (item.get("title") or "YouTube result").strip()
                            snippet = (item.get("body") or item.get("snippet") or "").strip()
                            results.append(
                                {
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
                                }
                            )
                            if len(results) >= limit:
                                return results
                    except Exception as q_exc:
                        logger.debug("YouTube fallback query failed (%s): %s", q, q_exc)
            return results
        except Exception as e:
            logger.error("YouTube fallback search error: %s", e)
            return []

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        started = perf_counter()
        action = action_id.split(".")[-1]
        query = self._resolve_query(params)
        limit = self._clamp_limit(
            params.get("limit")
            or params.get("max_results")
            or params.get("maxResults")
            or self.config.get("defaults", {}).get("limit", 5),
            default=5,
        )
        surface = params.get("surface") or self.config.get("defaults", {}).get("surfaceMode", "auto")
        search_type = params.get("type", "video")
        if isinstance(search_type, str) and search_type.strip().lower() == "music":
            search_type = "video"

        if action != "find":
            payload = error_envelope(
                provider="youtube",
                error_code="UNKNOWN_ACTION",
                error_message=f"Unknown YouTube action: {action_id}",
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
            )
            payload.update({"query": query, "count": 0, "results": [], "best": None})
            return payload

        if not query:
            payload = error_envelope(
                provider="youtube",
                error_code="MISSING_QUERY",
                error_message="Missing query for YouTube search.",
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
            )
            payload.update({"query": "", "count": 0, "results": [], "best": None})
            return payload

        if search_type not in {"video", "playlist", "channel"}:
            payload = error_envelope(
                provider="youtube",
                error_code="INVALID_TYPE",
                error_message=f"Unsupported YouTube search type: {search_type}",
                retryable=False,
                elapsed=int((perf_counter() - started) * 1000),
            )
            payload.update({"query": query, "count": 0, "results": [], "best": None})
            return payload

        api_key = self._get_api_key()
        auth = resolve_google_request_auth(
            context=context or {},
            kernel=self.kernel,
            api_key_fallback=api_key,
            requested_source=self.config.get("authSource"),
        )
        if auth.get("mode") == "none":
            fallback_results = self._fallback_search_web(query, limit, search_type)
            payload = success_envelope(
                provider="youtube_fallback_web",
                elapsed=int((perf_counter() - started) * 1000),
                warnings=[f"YouTube auth unavailable ({auth.get('reason')}). Using web fallback search."],
            )
            payload.update(
                {
                    "status": "success" if fallback_results else "empty",
                    "query": query,
                    "count": len(fallback_results),
                    "results": fallback_results,
                    "best": fallback_results[0] if fallback_results else None,
                    "fallback": True,
                }
            )
            payload["warning"] = f"YouTube auth unavailable ({auth.get('reason')}). Using web fallback search."
            return payload

        try:
            query_qs = quote_plus(str(query))
            url = (
                "https://www.googleapis.com/youtube/v3/search"
                f"?part=snippet&maxResults={limit}&q={query_qs}&type={search_type}"
            )
            response = requests.get(
                url,
                params=auth.get("params") or {},
                headers=auth.get("headers") or {},
                timeout=4,
            )
            data = response.json()

            if response.status_code >= 400 or "error" in data:
                error_msg = data.get("error", {}).get("message", f"HTTP {response.status_code}")
                fallback_results = self._fallback_search_web(query, limit, search_type)
                if fallback_results:
                    validation = validate_media_results(fallback_results[:limit], timeout=4.0)
                    fallback_results = validation["results"]
                    best = validation["best"]
                    failures = validation["failures"]
                    if best:
                        warnings = [f"YouTube API error: {error_msg}"]
                        if best.get("link_validation", {}).get("status") == "restricted":
                            warnings.append("YouTube fallback link is access-restricted; returning the best verified candidate.")
                        payload = success_envelope(
                            provider="youtube_fallback_web",
                            elapsed=int((perf_counter() - started) * 1000),
                            warnings=warnings,
                            status_code=response.status_code,
                        )
                        payload.update(
                            {
                                "status": "success" if fallback_results else "empty",
                                "query": query,
                                "count": len(fallback_results),
                                "results": fallback_results,
                                "best": best,
                                "fallback": True,
                                "validation_failures": failures,
                            }
                        )
                        payload["warning"] = f"YouTube API error: {error_msg}"
                        return payload

                payload = error_envelope(
                    provider="youtube",
                    error_code="HTTP_ERROR",
                    error_message=f"YouTube API error: {error_msg}",
                    retryable=response.status_code in {408, 425, 429, 500, 502, 503, 504},
                    elapsed=int((perf_counter() - started) * 1000),
                    status_code=response.status_code,
                )
                payload.update({"query": query, "count": 0, "results": [], "best": None, "fallback": True})
                return payload

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

                results.append(
                    {
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
                    }
                )

            results.sort(key=lambda x: x["confidenceScore"], reverse=True)
            validation = validate_media_results(results[:limit], timeout=4.0)
            validated_results = validation["results"]
            best = validation["best"]
            failures = validation["failures"]
            if not best:
                fallback_results = self._fallback_search_web(query, limit, search_type)
                if fallback_results:
                    validation = validate_media_results(fallback_results[:limit], timeout=4.0)
                    validated_results = validation["results"]
                    best = validation["best"]
                    failures.extend(validation["failures"])
                    results = validated_results
                else:
                    results = validated_results
            else:
                results = validated_results

            if not best:
                payload = error_envelope(
                    provider="youtube",
                    error_code="BROKEN_LINK",
                    error_message="Nenhum link de YouTube válido foi encontrado.",
                    retryable=True,
                    elapsed=int((perf_counter() - started) * 1000),
                    warnings=[f"Falhas de validação: {len(failures)}"],
                )
                payload.update(
                    {
                        "query": query,
                        "count": len(results),
                        "results": results,
                        "best": None,
                        "validation_failures": failures,
                        "fallback": bool(failures),
                    }
                )
                return payload

            payload = success_envelope(
                provider="youtube_oauth" if auth.get("mode") == "oauth" else "youtube",
                elapsed=int((perf_counter() - started) * 1000),
                status_code=response.status_code,
                warnings=(
                    ["Best YouTube link is access-restricted but not broken."]
                    if best and best.get("link_validation", {}).get("status") == "restricted"
                    else None
                ),
            )
            payload.update(
                {
                    "status": "success" if results else "empty",
                    "results": results,
                    "best": best,
                    "query": query,
                    "count": len(results),
                    "surfaceHint": surface,
                    "validation_failures": failures,
                }
            )
            return payload
        except Exception as e:
            logger.error("YouTube Search Execution Error: %s", e)
            fallback_results = self._fallback_search_web(query, limit, search_type)
            if fallback_results:
                payload = success_envelope(
                    provider="youtube_fallback_web",
                    elapsed=int((perf_counter() - started) * 1000),
                    warnings=[f"YouTube exception: {str(e)}"],
                )
                payload.update(
                    {
                        "query": query,
                        "count": len(fallback_results),
                        "results": fallback_results,
                        "best": fallback_results[0],
                        "fallback": True,
                    }
                )
                payload["warning"] = f"YouTube exception: {str(e)}"
                return payload

            payload = error_envelope(
                provider="youtube",
                error_code="SEARCH_ERROR",
                error_message=f"YouTube exception: {str(e)}",
                retryable=True,
                elapsed=int((perf_counter() - started) * 1000),
            )
            payload.update({"query": query, "count": 0, "results": [], "best": None, "fallback": True})
            return payload
