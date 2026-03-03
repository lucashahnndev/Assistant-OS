import logging
import re
from time import perf_counter
from typing import Any, Dict, List

import requests

from ..base import SkillBase
from ..shared.chunking import chunk_text
from ..shared.error_contract import error_envelope, success_envelope

logger = logging.getLogger("WikipediaSearchSkill")


class WikipediaSearchSkill(SkillBase):
    USER_AGENT = "Assistant-OS/1.0 (knowledge-skill; +https://github.com/)"

    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "wikipedia"

    @property
    def name(self) -> str:
        return "wikipedia_search"

    @property
    def actions(self) -> List[str]:
        return ["search"]

    @staticmethod
    def _sanitize_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @staticmethod
    def _resolve_query(params: Dict[str, Any]) -> str:
        for key in ("query", "search_query", "searchQuery", "q", "term", "text"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _clamp_limit(value: Any, default: int = 3) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 5))

    @staticmethod
    def _clamp_chars(value: Any, default: int = 4500) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(500, min(n, 18000))

    @staticmethod
    def _clamp_chunk_size(value: Any, default: int = 700) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(200, min(n, 2000))

    @staticmethod
    def _clamp_chunk_overlap(value: Any, default: int = 100) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(0, min(n, 500))

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    def _search_titles(self, query: str, language: str, limit: int) -> List[Dict[str, Any]]:
        endpoint = f"https://{language}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "utf8": 1,
            "format": "json",
        }
        response = requests.get(
            endpoint,
            params=params,
            timeout=10,
            headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("query", {}).get("search", []) or []

    def _fetch_pages(self, titles: List[str], language: str) -> List[Dict[str, Any]]:
        if not titles:
            return []
        endpoint = f"https://{language}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "prop": "extracts|info",
            "inprop": "url",
            "explaintext": 1,
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
            "titles": "|".join(titles),
        }
        response = requests.get(
            endpoint,
            params=params,
            timeout=10,
            headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("query", {}).get("pages", []) or []

    def _build_docs(
        self,
        pages: List[Dict[str, Any]],
        max_chars_per_page: int,
        chunk_size: int,
        chunk_overlap: int,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        docs: List[Dict[str, Any]] = []
        flat_chunks: List[Dict[str, Any]] = []
        warnings: List[str] = []

        seen_titles = set()
        rank = 1
        for page in pages:
            title = self._sanitize_text(page.get("title"))
            if not title:
                warnings.append("Página sem título recebida da API.")
                continue
            title_key = title.lower()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            content = self._sanitize_text(page.get("extract"))
            if not content:
                warnings.append(f"Conteúdo vazio para '{title}'.")
                continue

            url = page.get("fullurl") or f"https://wikipedia.org/wiki/{title.replace(' ', '_')}"
            content = self._truncate(content, max_chars_per_page)
            chunks = chunk_text(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

            doc = {
                "rank": rank,
                "title": title,
                "url": url,
                "excerpt": self._truncate(content, 280),
                "content": content,
                "chunks": chunks,
                "source": "wikipedia_api",
            }
            docs.append(doc)

            for chunk in chunks:
                flat_chunks.append(
                    {
                        "doc_rank": rank,
                        "title": title,
                        "url": url,
                        "chunk_id": chunk.get("id"),
                        "text": chunk.get("text"),
                        "start": chunk.get("start"),
                        "end": chunk.get("end"),
                    }
                )
            rank += 1

        return docs, flat_chunks, warnings

    def _resolve_language(self, params: Dict[str, Any]) -> tuple[str, bool]:
        configured_default = (
            self.config.get("defaults", {}).get("language")
            or self.config.get("language")
            or "pt"
        )
        explicit = params.get("language")
        language = self._sanitize_text(explicit or configured_default).lower()
        if not language:
            language = "pt"
        language = re.sub(r"[^a-z\-]", "", language)
        if not language:
            language = "pt"
        return language, explicit is not None

    def _error_result(
        self,
        *,
        query: str,
        language: str,
        error_code: str,
        message: str,
        elapsed: int,
        retryable: bool,
        status_code: int | None = None,
        warnings: List[str] | None = None,
    ) -> Dict[str, Any]:
        payload = error_envelope(
            provider="wikipedia",
            error_code=error_code,
            error_message=message,
            retryable=retryable,
            status_code=status_code,
            elapsed=elapsed,
            warnings=warnings,
        )
        payload.update(
            {
                "query": query,
                "language": language,
                "count": 0,
                "results": [],
                "best": None,
                "chunks": [],
            }
        )
        return payload

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        _ = context
        started = perf_counter()
        action = action_id.split(".")[-1]
        if action != "search":
            return self._error_result(
                query=self._sanitize_text(self._resolve_query(params)),
                language="pt",
                error_code="UNKNOWN_ACTION",
                message=f"Unknown action para wikipedia_search: {action_id}",
                elapsed=int((perf_counter() - started) * 1000),
                retryable=False,
            )

        query = self._sanitize_text(self._resolve_query(params))
        if not query:
            return self._error_result(
                query="",
                language="pt",
                error_code="MISSING_QUERY",
                message="Error: parameter 'query' is required para wikipedia.search.",
                elapsed=int((perf_counter() - started) * 1000),
                retryable=False,
            )

        language, explicit_language = self._resolve_language(params)
        limit = self._clamp_limit(
            params.get("limit") or params.get("max_results") or params.get("maxResults") or self.config.get("defaults", {}).get("limit", 3),
            default=3,
        )
        max_chars_per_page = self._clamp_chars(
            params.get("max_chars_per_page") or self.config.get("defaults", {}).get("max_chars_per_page", 4500),
            default=4500,
        )
        chunk_size = self._clamp_chunk_size(
            params.get("chunk_size") or self.config.get("defaults", {}).get("chunk_size", 700),
            default=700,
        )
        chunk_overlap = self._clamp_chunk_overlap(
            params.get("chunk_overlap") or self.config.get("defaults", {}).get("chunk_overlap", 100),
            default=100,
        )

        warnings: List[str] = []

        try:
            titles_data = self._search_titles(query, language, limit)
        except requests.RequestException as e:
            status_code = int(e.response.status_code) if getattr(e, "response", None) is not None else None
            return self._error_result(
                query=query,
                language=language,
                error_code="NETWORK_ERROR",
                message=f"Falha de rede ao consultar Wikipedia: {e}",
                elapsed=int((perf_counter() - started) * 1000),
                retryable=True,
                status_code=status_code,
            )
        except Exception as e:
            return self._error_result(
                query=query,
                language=language,
                error_code="SEARCH_ERROR",
                message=f"Erro ao buscar na Wikipedia: {e}",
                elapsed=int((perf_counter() - started) * 1000),
                retryable=True,
            )

        # Fallback para EN quando idioma não foi explicitado e PT não retornou resultados.
        if not titles_data and not explicit_language and language == "pt":
            fallback_language = "en"
            try:
                fallback_titles = self._search_titles(query, fallback_language, limit)
                if fallback_titles:
                    language = fallback_language
                    titles_data = fallback_titles
                    warnings.append("Sem resultados em pt; usando fallback automático para en.")
            except Exception:
                pass

        if not titles_data:
            elapsed = int((perf_counter() - started) * 1000)
            payload = success_envelope(provider="wikipedia", elapsed=elapsed, warnings=warnings)
            payload.update(
                {
                    "status": "empty",
                    "query": query,
                    "language": language,
                    "count": 0,
                    "results": [],
                    "best": None,
                    "chunks": [],
                }
            )
            return payload

        titles: List[str] = []
        seen = set()
        for item in titles_data:
            title = self._sanitize_text(item.get("title"))
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            titles.append(title)
            if len(titles) >= limit:
                break

        try:
            pages = self._fetch_pages(titles, language)
        except requests.RequestException as e:
            status_code = int(e.response.status_code) if getattr(e, "response", None) is not None else None
            return self._error_result(
                query=query,
                language=language,
                error_code="NETWORK_ERROR",
                message=f"Falha de rede ao obter páginas da Wikipedia: {e}",
                elapsed=int((perf_counter() - started) * 1000),
                retryable=True,
                status_code=status_code,
            )
        except Exception as e:
            return self._error_result(
                query=query,
                language=language,
                error_code="PAGE_FETCH_ERROR",
                message=f"Erro ao obter conteúdo da Wikipedia: {e}",
                elapsed=int((perf_counter() - started) * 1000),
                retryable=True,
            )

        docs, chunks, page_warnings = self._build_docs(
            pages,
            max_chars_per_page=max_chars_per_page,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        warnings.extend(page_warnings)

        elapsed = int((perf_counter() - started) * 1000)
        payload = success_envelope(provider="wikipedia", elapsed=elapsed, warnings=warnings)
        if not docs:
            payload.update(
                {
                    "status": "empty",
                    "query": query,
                    "language": language,
                    "count": 0,
                    "results": [],
                    "best": None,
                    "chunks": [],
                }
            )
            return payload

        payload.update(
            {
                "query": query,
                "language": language,
                "count": len(docs),
                "results": docs,
                "best": docs[0],
                "chunks": chunks,
            }
        )
        return payload
