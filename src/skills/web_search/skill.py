import logging
import re
from typing import Dict, Any, List

import requests
from ..base import SkillBase

logger = logging.getLogger("WebSearchSkill")

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - optional dependency fallback
    BeautifulSoup = None  # type: ignore

try:
    # New package name
    from ddgs import DDGS  # type: ignore
except Exception:  # pragma: no cover - fallback for older environments
    from duckduckgo_search import DDGS  # type: ignore


class WebSearchSkill(SkillBase):
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )

    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "web"

    @property
    def name(self) -> str: return "web_search"

    @property
    def actions(self) -> List[str]: return ["discover"]

    @staticmethod
    def _clamp_limit(value: Any, default: int = 5) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 10))

    @staticmethod
    def _clamp_knowledge_limit(value: Any, default: int = 2) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(1, min(n, 5))

    @staticmethod
    def _clamp_chars(value: Any, default: int = 2500) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(500, min(n, 12000))

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
    def _sanitize_text(text: Any) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    @staticmethod
    def _resolve_query(params: Dict[str, Any]) -> str:
        for key in ("query", "search_query", "searchQuery", "q", "term", "text"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1].rstrip() + "…"

    @classmethod
    def _is_knowledge_query(cls, query: str) -> bool:
        q = (query or "").strip().lower()
        if not q:
            return False
        if "?" in q:
            return True

        knowledge_markers = [
            "o que",
            "oque",
            "quem",
            "quando",
            "onde",
            "como",
            "por que",
            "porque",
            "qual",
            "quais",
            "what is",
            "who is",
            "when",
            "where",
            "how",
            "explique",
            "explain",
            "história",
            "historia",
            "definição",
            "definicao",
            "conceito",
        ]
        return any(marker in q for marker in knowledge_markers)

    @classmethod
    def _resolve_mode(cls, requested_mode: Any, query: str) -> str:
        mode = str(requested_mode or "links").strip().lower()
        if mode not in {"links", "knowledge", "auto"}:
            mode = "links"
        if mode == "auto":
            return "knowledge" if cls._is_knowledge_query(query) else "links"
        return mode

    @classmethod
    def _chunk_text(cls, text: str, chunk_size: int, overlap: int) -> List[Dict[str, Any]]:
        clean = cls._sanitize_text(text)
        if not clean:
            return []

        if overlap >= chunk_size:
            overlap = max(0, chunk_size // 4)
        step = max(1, chunk_size - overlap)

        chunks: List[Dict[str, Any]] = []
        cursor = 0
        idx = 1
        while cursor < len(clean):
            end = min(len(clean), cursor + chunk_size)
            piece = clean[cursor:end].strip()
            if piece:
                chunks.append(
                    {
                        "chunk_id": idx,
                        "text": piece,
                        "start": cursor,
                        "end": end,
                    }
                )
                idx += 1
            if end >= len(clean):
                break
            cursor += step
        return chunks

    @staticmethod
    def _normalize_result_item(raw: Dict[str, Any], rank: int) -> Dict[str, Any]:
        title = raw.get("title") or raw.get("heading") or "Sem título"
        url = raw.get("href") or raw.get("url") or ""
        snippet = raw.get("body") or raw.get("snippet") or raw.get("text") or ""
        return {
            "rank": rank,
            "title": str(title).strip(),
            "snippet": str(snippet).strip(),
            "url": str(url).strip(),
            "source": "duckduckgo",
        }

    @staticmethod
    def _render_summary_text(query: str, results: List[Dict[str, Any]]) -> str:
        if not results:
            return f"Nenhum resultado encontrado para '{query}'."

        lines = [f"Resultados para '{query}' ({len(results)} itens):"]
        for item in results:
            rank = item.get("rank", 0)
            title = item.get("title", "Sem título")
            snippet = item.get("snippet", "")
            url = item.get("url", "")
            lines.append(f"{rank}. {title}")
            if snippet:
                lines.append(f"   {snippet}")
            if url:
                lines.append(f"   URL: {url}")
        return "\n".join(lines)

    def _ddg_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            with DDGS() as ddgs:
                results = []
                ddgs_gen = ddgs.text(query, max_results=limit)
                for idx, item in enumerate(ddgs_gen, start=1):
                    if not isinstance(item, dict):
                        continue
                    normalized = self._normalize_result_item(item, idx)
                    if normalized["url"]:
                        results.append(normalized)
                    if len(results) >= limit:
                        break
                return results
        except Exception as e:
            logger.error(f"DuckDuckGo Search Error: {e}")
        return []

    def _extract_page_content(self, url: str, max_chars_per_doc: int) -> Dict[str, Any]:
        if not url:
            return {"ok": False, "error": "EMPTY_URL", "message": "URL vazia."}

        if BeautifulSoup is None:
            return {
                "ok": False,
                "error": "BS4_UNAVAILABLE",
                "message": "BeautifulSoup indisponível para extração de conteúdo.",
            }

        try:
            response = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": self.USER_AGENT},
                allow_redirects=True,
            )
            if response.status_code >= 400:
                return {
                    "ok": False,
                    "error": "HTTP_ERROR",
                    "message": f"HTTP {response.status_code}",
                }

            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                raw_text = self._sanitize_text(response.text)
                if not raw_text:
                    return {
                        "ok": False,
                        "error": "UNSUPPORTED_CONTENT",
                        "message": f"Tipo de conteúdo não suportado: {content_type or 'unknown'}",
                    }
                return {
                    "ok": True,
                    "title": url,
                    "content": self._truncate(raw_text, max_chars_per_doc),
                }

            soup = BeautifulSoup(response.text, "html.parser")
            for tag_name in ["script", "style", "noscript", "svg", "header", "footer", "nav"]:
                for node in soup.find_all(tag_name):
                    node.decompose()

            title = self._sanitize_text(soup.title.string if soup.title and soup.title.string else "")
            body = soup.body or soup
            candidates = body.find_all(["article", "main", "section"]) if body else []

            best_text = ""
            for candidate in candidates:
                text = self._sanitize_text(candidate.get_text(" ", strip=True))
                if len(text) > len(best_text):
                    best_text = text

            if not best_text and body:
                best_text = self._sanitize_text(body.get_text(" ", strip=True))

            if not best_text:
                return {
                    "ok": False,
                    "error": "EMPTY_CONTENT",
                    "message": "Página sem conteúdo textual útil.",
                }

            return {
                "ok": True,
                "title": title or url,
                "content": self._truncate(best_text, max_chars_per_doc),
            }
        except requests.RequestException as e:
            logger.warning(f"Web knowledge fetch failed for {url}: {e}")
            return {
                "ok": False,
                "error": "NETWORK_ERROR",
                "message": str(e),
            }
        except Exception as e:
            logger.warning(f"Web knowledge parse failed for {url}: {e}")
            return {
                "ok": False,
                "error": "PARSE_ERROR",
                "message": str(e),
            }

    @staticmethod
    def _render_knowledge_text(query: str, docs: List[Dict[str, Any]], warnings: List[str]) -> str:
        if not docs:
            base = f"Não consegui extrair conteúdo de conhecimento para '{query}'."
            if warnings:
                base += " Mantive os links para referência."
            return base
        lines = [f"Base de conhecimento para '{query}' ({len(docs)} fonte(s) extraídas):"]
        for doc in docs:
            lines.append(f"- {doc.get('title', 'Sem título')} ({doc.get('url', 'sem URL')})")
        if warnings:
            lines.append(f"Avisos: {len(warnings)} ocorrência(s) durante extração.")
        return "\n".join(lines)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        query = self._resolve_query(params)
        limit = self._clamp_limit(
            params.get("limit") or params.get("max_results") or params.get("maxResults") or self.config.get("defaults", {}).get("limit", 5),
            default=5,
        )
        requested_mode = params.get("mode") or self.config.get("defaults", {}).get("mode", "links")
        mode = self._resolve_mode(requested_mode, str(query or ""))
        knowledge_limit = self._clamp_knowledge_limit(
            params.get("knowledge_limit") or self.config.get("defaults", {}).get("knowledge_limit", 2),
            default=2,
        )
        max_chars_per_doc = self._clamp_chars(
            params.get("max_chars_per_doc") or self.config.get("defaults", {}).get("max_chars_per_doc", 2500),
            default=2500,
        )
        chunk_size = self._clamp_chunk_size(
            params.get("chunk_size") or self.config.get("defaults", {}).get("chunk_size", 700),
            default=700,
        )
        chunk_overlap = self._clamp_chunk_overlap(
            params.get("chunk_overlap") or self.config.get("defaults", {}).get("chunk_overlap", 100),
            default=100,
        )

        if not query:
            return {
                "ok": False,
                "status": "error",
                "error": "MISSING_QUERY",
                "message": "Missing query for web discovery.",
                "provider": "duckduckgo",
                "query": "",
                "mode": mode,
                "count": 0,
                "results": [],
                "knowledge_docs": [],
                "chunks": [],
                "warnings": [],
                "text": "Erro: parâmetro 'query' é obrigatório para web.search.discover.",
            }

        if action == "discover":
            results = self._ddg_search(query, limit=limit)
            warnings: List[str] = []
            knowledge_docs: List[Dict[str, Any]] = []
            chunks: List[Dict[str, Any]] = []
            text = self._render_summary_text(query, results)

            if mode == "knowledge" and results:
                candidates = results[:knowledge_limit]
                for entry in candidates:
                    url = entry.get("url") or ""
                    extraction = self._extract_page_content(url, max_chars_per_doc=max_chars_per_doc)
                    if not extraction.get("ok"):
                        warnings.append(
                            f"{url or 'sem_url'}: {extraction.get('error') or extraction.get('message') or 'erro desconhecido'}"
                        )
                        continue

                    content = self._sanitize_text(extraction.get("content"))
                    if not content:
                        warnings.append(f"{url or 'sem_url'}: conteúdo vazio após limpeza.")
                        continue

                    doc_chunks = self._chunk_text(content, chunk_size=chunk_size, overlap=chunk_overlap)
                    doc = {
                        "rank": entry.get("rank"),
                        "title": extraction.get("title") or entry.get("title") or "Sem título",
                        "url": url,
                        "excerpt": self._truncate(content, 280),
                        "content": content,
                        "chunks": doc_chunks,
                        "source": entry.get("source", "duckduckgo"),
                    }
                    knowledge_docs.append(doc)

                    for chunk in doc_chunks:
                        chunks.append(
                            {
                                "doc_rank": doc.get("rank"),
                                "title": doc.get("title"),
                                "url": url,
                                "chunk_id": chunk.get("chunk_id"),
                                "text": chunk.get("text"),
                                "start": chunk.get("start"),
                                "end": chunk.get("end"),
                            }
                        )

                text = self._render_knowledge_text(query, knowledge_docs, warnings)

            if not results:
                return {
                    "ok": True,
                    "status": "empty",
                    "provider": "duckduckgo",
                    "query": query,
                    "mode": mode,
                    "count": 0,
                    "results": [],
                    "best": None,
                    "knowledge_docs": [],
                    "chunks": [],
                    "warnings": warnings,
                    "text": text,
                }

            return {
                "ok": True,
                "status": "success",
                "provider": "duckduckgo",
                "query": query,
                "mode": mode,
                "count": len(results),
                "results": results,
                "best": results[0],
                "knowledge_docs": knowledge_docs,
                "chunks": chunks,
                "warnings": warnings,
                "text": text,
            }

        return {
            "ok": False,
            "status": "error",
            "error": "UNKNOWN_ACTION",
            "message": f"Unknown web_search action: {action_id}",
            "provider": "duckduckgo",
            "query": query or "",
            "mode": mode,
            "count": 0,
            "results": [],
            "knowledge_docs": [],
            "chunks": [],
            "warnings": [],
            "text": f"Erro: ação desconhecida '{action_id}' para web_search.",
        }
