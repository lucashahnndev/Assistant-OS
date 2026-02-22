import logging
import re
from typing import Any, Dict, List, Optional

import requests

from ..base import SkillBase

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
        index = 1
        while cursor < len(clean):
            end = min(len(clean), cursor + chunk_size)
            piece = clean[cursor:end].strip()
            if piece:
                chunks.append(
                    {
                        "chunk_id": index,
                        "text": piece,
                        "start": cursor,
                        "end": end,
                    }
                )
                index += 1
            if end >= len(clean):
                break
            cursor += step
        return chunks

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

    @staticmethod
    def _summary_text(query: str, language: str, docs: List[Dict[str, Any]], warnings: List[str]) -> str:
        if not docs:
            return f"Nenhum conteúdo encontrado na Wikipedia para '{query}' (idioma: {language})."
        lines = [f"Wikipedia: {len(docs)} artigo(s) para '{query}' (idioma: {language})."]
        for doc in docs[:5]:
            lines.append(f"- {doc.get('title', 'Sem título')} ({doc.get('url', 'sem URL')})")
        if warnings:
            lines.append(f"Avisos: {len(warnings)} ocorrência(s).")
        return "\n".join(lines)

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
            chunks = self._chunk_text(content, chunk_size=chunk_size, overlap=chunk_overlap)

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
                        "chunk_id": chunk.get("chunk_id"),
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

    def _result_error(self, query: str, language: str, error: str, message: str) -> Dict[str, Any]:
        return {
            "ok": False,
            "status": "error",
            "provider": "wikipedia",
            "query": query,
            "language": language,
            "count": 0,
            "results": [],
            "best": None,
            "chunks": [],
            "warnings": [],
            "error": error,
            "message": message,
            "text": message,
        }

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        if action != "search":
            return self._result_error(
                query=self._sanitize_text(params.get("query")),
                language="pt",
                error="UNKNOWN_ACTION",
                message=f"Ação desconhecida para wikipedia_search: {action_id}",
            )

        query = self._sanitize_text(params.get("query"))
        if not query:
            return self._result_error(
                query="",
                language="pt",
                error="MISSING_QUERY",
                message="Erro: parâmetro 'query' é obrigatório para wikipedia.search.",
            )

        language, explicit_language = self._resolve_language(params)
        limit = self._clamp_limit(params.get("limit") or self.config.get("defaults", {}).get("limit", 3), default=3)
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
            return self._result_error(
                query=query,
                language=language,
                error="NETWORK_ERROR",
                message=f"Falha de rede ao consultar Wikipedia: {e}",
            )
        except Exception as e:
            return self._result_error(
                query=query,
                language=language,
                error="SEARCH_ERROR",
                message=f"Erro ao buscar na Wikipedia: {e}",
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
                # Ignora erro de fallback, mantendo comportamento empty abaixo.
                pass

        if not titles_data:
            return {
                "ok": True,
                "status": "empty",
                "provider": "wikipedia",
                "query": query,
                "language": language,
                "count": 0,
                "results": [],
                "best": None,
                "chunks": [],
                "warnings": warnings,
                "text": f"Nenhum resultado encontrado na Wikipedia para '{query}' (idioma: {language}).",
            }

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
            return self._result_error(
                query=query,
                language=language,
                error="NETWORK_ERROR",
                message=f"Falha de rede ao obter páginas da Wikipedia: {e}",
            )
        except Exception as e:
            return self._result_error(
                query=query,
                language=language,
                error="PAGE_FETCH_ERROR",
                message=f"Erro ao obter conteúdo da Wikipedia: {e}",
            )

        docs, chunks, page_warnings = self._build_docs(
            pages,
            max_chars_per_page=max_chars_per_page,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        warnings.extend(page_warnings)

        if not docs:
            return {
                "ok": True,
                "status": "empty",
                "provider": "wikipedia",
                "query": query,
                "language": language,
                "count": 0,
                "results": [],
                "best": None,
                "chunks": [],
                "warnings": warnings,
                "text": f"Nenhum conteúdo textual útil foi encontrado para '{query}' na Wikipedia.",
            }

        return {
            "ok": True,
            "status": "success",
            "provider": "wikipedia",
            "query": query,
            "language": language,
            "count": len(docs),
            "results": docs,
            "best": docs[0],
            "chunks": chunks,
            "warnings": warnings,
            "text": self._summary_text(query, language, docs, warnings),
        }
