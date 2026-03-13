import json
import logging
import re
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from ..base import CapabilityBase
from ..shared.chunking import normalize_whitespace
from ..shared.error_contract import error_envelope, success_envelope
from utils.toon_codec import dumps_toon

logger = logging.getLogger("ResearchRetrieveCapability")


class RegistryWrapper:
    ALLOWLIST = {
        "web.search.discover",
        "web.retrieve.read",
        "web.retrieve.extract",
        "wikipedia.search",
        "youtube.search.find",
        "youtube.retrieve.get",
    }

    def __init__(self, dispatch_fn: Any, envelope: Dict[str, Any]):
        self._dispatch_fn = dispatch_fn
        self.envelope = envelope

    def dispatch(self, action_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action_id not in self.ALLOWLIST:
            return error_envelope(
                provider="research.retrieve",
                error_code="RESEARCH_SCOPE_VIOLATION",
                error_message=f"Action '{action_id}' is outside research.retrieve scope.",
                retryable=False,
                elapsed=0,
                warnings=[],
            )
        if not callable(self._dispatch_fn):
            return error_envelope(
                provider="research.retrieve",
                error_code="SKILL_REGISTRY_MISSING",
                error_message="Execution context missing capability registry.",
                retryable=False,
                elapsed=0,
                warnings=[],
            )

        # Hard-isolated context: no chat history, no global memory, no browser state.
        isolated_context = {"research_envelope": dict(self.envelope)}
        result = self._dispatch_fn(action_id, params, isolated_context)
        if isinstance(result, dict):
            return result
        return error_envelope(
            provider="research.retrieve",
            error_code="INVALID_SKILL_RESPONSE",
            error_message=f"Action '{action_id}' returned non-object response.",
            retryable=False,
            elapsed=0,
            warnings=[],
        )


class ResearchRetrieveCapability(CapabilityBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "research.retrieve"

    @property
    def name(self) -> str:
        return "research_retrieve"

    @property
    def actions(self) -> List[str]:
        return ["run"]

    @staticmethod
    def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(lo, min(n, hi))

    @staticmethod
    def _to_list(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return []

    @staticmethod
    def _clean_query(params: Dict[str, Any]) -> str:
        for key in ("query", "goal", "search_query", "q", "text"):
            raw = params.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return ""

    @staticmethod
    def _looks_field_request(goal: str) -> bool:
        text = str(goal or "").lower()
        field_markers = (
            "schema",
            "campos",
            "fields",
            "extrair",
            "extract",
            "structured",
            "json",
            "preço",
            "price",
        )
        return any(marker in text for marker in field_markers)

    @staticmethod
    def _fallback_pick(results: List[Dict[str, Any]], limit: int) -> List[str]:
        urls: List[str] = []
        for item in results:
            url = str(item.get("url") or "").strip()
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(1, int((perf_counter() - started) * 1000))

    def _llm_text(self, *, prompt: str, system_prompt: str) -> Optional[str]:
        kernel = self.kernel
        llm_manager = getattr(kernel, "llm_manager", None) if kernel else None
        if not llm_manager:
            return None
        try:
            result, err = llm_manager._execute_with_router(  # noqa: SLF001
                llm_manager.chat_pool,
                "generate_text",
                prompt,
                system_prompt=system_prompt,
            )
            if err:
                logger.warning("research.retrieve LLM fallback: %s", err)
            if isinstance(result, str) and result.strip():
                return result.strip()
        except Exception as e:
            logger.warning("research.retrieve LLM error: %s", e)
        return None

    def _pick_urls_with_llm(
        self,
        *,
        goal: str,
        results: List[Dict[str, Any]],
        max_links_to_open: int,
    ) -> Tuple[List[str], List[str]]:
        warnings: List[str] = []
        if not results:
            return [], warnings

        shortlist = results[: min(len(results), max(4, max_links_to_open * 3))]
        prompt_payload = []
        for idx, item in enumerate(shortlist, start=1):
            prompt_payload.append(
                {
                    "idx": idx,
                    "title": str(item.get("title") or ""),
                    "snippet": str(item.get("snippet") or ""),
                    "url": str(item.get("url") or ""),
                }
            )

        prompt = (
            "Select the most relevant links for this research goal. "
            "Return strict JSON: {\"pick\":[idx,...],\"why\":\"...\"}. "
            f"Pick at most {max_links_to_open}.\n\n"
            f"Goal:\n{goal}\n\n"
            f"Candidates:\n{json.dumps(prompt_payload, ensure_ascii=False)}"
        )
        system_prompt = (
            "You are a web research planner. Choose only links likely to contain factual evidence. "
            "Return only JSON."
        )
        raw = self._llm_text(prompt=prompt, system_prompt=system_prompt)
        if not raw:
            warnings.append("LLM picker unavailable; using deterministic top links.")
            return self._fallback_pick(shortlist, max_links_to_open), warnings

        parsed: Dict[str, Any] = {}
        try:
            parsed = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except Exception:
                    parsed = {}

        picks = parsed.get("pick") if isinstance(parsed, dict) else []
        idxs: List[int] = []
        if isinstance(picks, list):
            for p in picks:
                try:
                    i = int(p)
                except Exception:
                    continue
                if 1 <= i <= len(shortlist) and i not in idxs:
                    idxs.append(i)

        if not idxs:
            warnings.append("LLM picker returned invalid JSON; using deterministic top links.")
            return self._fallback_pick(shortlist, max_links_to_open), warnings

        urls: List[str] = []
        for idx in idxs:
            url = str(shortlist[idx - 1].get("url") or "").strip()
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= max_links_to_open:
                break
        if not urls:
            return self._fallback_pick(shortlist, max_links_to_open), warnings
        return urls, warnings

    def _synthesize_answer(
        self,
        *,
        goal: str,
        docs: List[Dict[str, Any]],
        evidence: List[Dict[str, Any]],
        language_hint: str,
    ) -> str:
        doc_summaries: List[Dict[str, Any]] = []
        for doc in docs:
            doc_summaries.append(
                {
                    "title": doc.get("title"),
                    "url": doc.get("url"),
                    "content": str(doc.get("text") or "")[:2000],
                }
            )

        prompt = (
            "Synthesize an evidence-based answer. "
            "Cite supporting sources using markdown links. "
            "Be concise and do not invent facts.\n\n"
            f"Language hint: {language_hint or 'auto'}\n"
            f"Goal:\n{goal}\n\n"
            f"Evidence:\n{json.dumps(evidence[:12], ensure_ascii=False)}\n\n"
            f"Documents:\n{json.dumps(doc_summaries[:8], ensure_ascii=False)}"
        )
        system_prompt = (
            "You are a retrieval synthesis assistant. Use only provided evidence. "
            "If evidence is insufficient, state limitations explicitly."
        )
        raw = self._llm_text(prompt=prompt, system_prompt=system_prompt)
        if raw:
            return raw

        lines = ["## Research Summary", ""]
        if not docs:
            lines.append("Insufficient evidence found in retrieved documents.")
            return "\n".join(lines)
        lines.append(f"Goal: {goal}")
        lines.append("")
        lines.append("### Key Evidence")
        for ev in evidence[:6]:
            quote = str(ev.get("quote") or "").strip()
            src = str(ev.get("source_url") or "").strip()
            title = str(ev.get("source_title") or "source").strip()
            if quote and src:
                lines.append(f"- {quote} ([{title}]({src}))")
        lines.append("")
        lines.append("### Sources")
        for doc in docs[:8]:
            src = str(doc.get("url") or "").strip()
            title = str(doc.get("title") or src)
            if src:
                lines.append(f"- [{title}]({src})")
        return "\n".join(lines)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        started = perf_counter()
        action = action_id.split(".")[-1]
        if action != "run":
            return error_envelope(
                provider="research.retrieve",
                error_code="UNKNOWN_ACTION",
                error_message=f"Unknown research.retrieve action: {action_id}",
                retryable=False,
                elapsed=self._elapsed_ms(started),
                warnings=[],
            )

        query = self._clean_query(params)
        if not query:
            return error_envelope(
                provider="research.retrieve",
                error_code="MISSING_QUERY",
                error_message="Provide 'query' or 'goal'.",
                retryable=False,
                elapsed=self._elapsed_ms(started),
                warnings=[],
            )

        constraints = params.get("constraints") if isinstance(params.get("constraints"), dict) else {}
        output_format = str(params.get("output_format") or "md").strip().lower()
        if output_format not in {"md", "toon"}:
            output_format = "md"

        lang = str(constraints.get("lang") or "").strip() or "auto"
        recency_days = self._clamp_int(constraints.get("recency_days"), default=0, lo=0, hi=3650)
        domains_allow = self._to_list(constraints.get("domains_allow"))
        domains_deny = self._to_list(constraints.get("domains_deny"))
        max_links_to_open = self._clamp_int(constraints.get("max_links_to_open"), default=3, lo=1, hi=8)
        max_docs = self._clamp_int(constraints.get("max_docs"), default=3, lo=1, hi=8)
        max_total_chars = self._clamp_int(constraints.get("max_total_chars"), default=14000, lo=100, hi=80000)
        max_steps = self._clamp_int(constraints.get("max_steps"), default=7, lo=3, hi=20)
        extract_schema = constraints.get("extract_schema") if isinstance(constraints.get("extract_schema"), list) else []

        warnings: List[str] = []
        steps = 0
        chars_read = 0
        docs_opened = 0
        evidence: List[Dict[str, Any]] = []
        sources: List[Dict[str, Any]] = []
        docs: List[Dict[str, Any]] = []

        registry = context.get("capability_registry")
        dispatch_fn = getattr(registry, "dispatch", None) if registry else None
        envelope = {
            "query": query,
            "constraints": {
                "lang": lang,
                "recency_days": recency_days,
                "domains_allow": domains_allow,
                "domains_deny": domains_deny,
                "max_links_to_open": max_links_to_open,
                "max_docs": max_docs,
                "max_total_chars": max_total_chars,
                "max_steps": max_steps,
            },
            "output_format": output_format,
        }
        kernel_lite = RegistryWrapper(dispatch_fn=dispatch_fn, envelope=envelope)

        def budget_stop() -> bool:
            return steps >= max_steps or docs_opened >= max_docs or chars_read >= max_total_chars

        if budget_stop():
            warnings.append("Budget exhausted before search step.")
            results: List[Dict[str, Any]] = []
        else:
            steps += 1
            search_limit = min(10, max(5, max_links_to_open * 3))
            search_params = {
                "query": query,
                "limit": search_limit,
                "mode": "links",
                "domains_allow": domains_allow,
                "domains_deny": domains_deny,
            }
            if recency_days > 0:
                search_params["recency_days"] = recency_days

            search_result = kernel_lite.dispatch("web.search.discover", search_params)
            if not isinstance(search_result, dict) or not search_result.get("ok"):
                err_code = str((search_result or {}).get("error_code") or "SEARCH_FAILED")
                err_msg = str((search_result or {}).get("error_message") or "web.search.discover failed")
                result = error_envelope(
                    provider="research.retrieve",
                    error_code=err_code,
                    error_message=err_msg,
                    retryable=bool((search_result or {}).get("retryable", True)),
                    status_code=(search_result or {}).get("status_code"),
                    elapsed=self._elapsed_ms(started),
                    warnings=warnings,
                )
                result.update(
                    {
                        "sources": [],
                        "evidence": [],
                        "stats": {"steps": steps, "docs_opened": 0, "chars_read": 0},
                    }
                )
                return result

            results = search_result.get("results") if isinstance(search_result.get("results"), list) else []
            warnings.extend([str(w) for w in (search_result.get("warnings") or []) if str(w).strip()])
            if not results:
                payload = success_envelope(
                    provider="research.retrieve",
                    elapsed=self._elapsed_ms(started),
                    warnings=warnings,
                )
                payload.update(
                    {
                        "status": "empty",
                        "answer_md": "No relevant results found.",
                        "sources": [],
                        "evidence": [],
                        "stats": {"steps": steps, "docs_opened": 0, "chars_read": 0},
                    }
                )
                return payload

        if budget_stop():
            picked_urls = []
            warnings.append("Budget exhausted before pick step.")
        else:
            steps += 1
            picked_urls, pick_warnings = self._pick_urls_with_llm(
                goal=query,
                results=results,
                max_links_to_open=max_links_to_open,
            )
            warnings.extend(pick_warnings)

        for url in picked_urls:
            if budget_stop():
                warnings.append("Budget exhausted during read step.")
                break
            remaining_chars = max_total_chars - chars_read
            if remaining_chars < 120:
                warnings.append("Remaining char budget too small to continue reading.")
                break

            steps += 1
            read_result = kernel_lite.dispatch(
                "web.retrieve.read",
                {
                    "url": url,
                    "mode": "main",
                    "max_chars": min(3500, remaining_chars),
                    "timeout_ms": 12000,
                    "retries": 1,
                },
            )
            if not isinstance(read_result, dict) or not read_result.get("ok"):
                warnings.append(
                    f"Read failed for {url}: {str((read_result or {}).get('error_code') or (read_result or {}).get('error') or 'unknown')}."
                )
                continue

            text_md = normalize_whitespace(read_result.get("text_md") or "")
            if not text_md:
                warnings.append(f"Read empty content for {url}.")
                continue

            text_md = text_md[:remaining_chars]
            chars_read += len(text_md)
            docs_opened += 1

            doc_title = str(read_result.get("title") or url)
            doc_source = {
                "url": str(read_result.get("canonical_url") or read_result.get("url") or url),
                "title": doc_title,
                "status_code": read_result.get("status_code"),
            }
            if doc_source not in sources:
                sources.append(doc_source)

            chunks = read_result.get("chunks") if isinstance(read_result.get("chunks"), list) else []
            quote = ""
            chunk_id = None
            if chunks:
                first = chunks[0] if isinstance(chunks[0], dict) else {}
                quote = str(first.get("text") or "").strip()
                chunk_id = first.get("id")
            if not quote:
                quote = text_md[:280]

            evidence.append(
                {
                    "source_url": doc_source["url"],
                    "source_title": doc_title,
                    "chunk_id": chunk_id,
                    "quote": quote,
                }
            )

            docs.append(
                {
                    "url": doc_source["url"],
                    "title": doc_title,
                    "content": text_md,
                }
            )
            if docs_opened >= max_docs:
                break

        extracted_rows: List[Dict[str, Any]] = []
        should_extract = bool(extract_schema) or self._looks_field_request(query)
        if should_extract and docs and not budget_stop() and extract_schema:
            steps += 1
            for doc in docs[: max_docs]:
                if budget_stop():
                    break
                extract_result = kernel_lite.dispatch(
                    "web.retrieve.extract",
                    {
                        "url": doc.get("url"),
                        "schema": extract_schema,
                        "max_chars": 1200,
                    },
                )
                if isinstance(extract_result, dict) and extract_result.get("ok"):
                    extracted_rows.append(
                        {
                            "url": doc.get("url"),
                            "data": extract_result.get("data") if isinstance(extract_result.get("data"), dict) else {},
                        }
                    )

        if budget_stop() and not docs:
            answer_md = "Insufficient budget to retrieve documents."
        else:
            if steps < max_steps:
                steps += 1
            answer_md = self._synthesize_answer(
                goal=query,
                docs=docs,
                evidence=evidence,
                language_hint=lang,
            )

        if extracted_rows:
            answer_md = (
                f"{answer_md}\n\n### Extracted Fields\n\n```json\n"
                f"{json.dumps(extracted_rows, ensure_ascii=False, indent=2)}\n```"
            )

        result = success_envelope(
            provider="research.retrieve",
            elapsed=self._elapsed_ms(started),
            warnings=warnings,
        )
        result.update(
            {
                "status": "success" if docs else "empty",
                "sources": sources,
                "evidence": evidence,
                "stats": {
                    "steps": steps,
                    "docs_opened": docs_opened,
                    "chars_read": chars_read,
                },
                "content": answer_md,
            }
        )

        if output_format == "toon":
            toon_payload = {
                "v": "toon.v1",
                "t": "research.retrieve.result",
                "ok": bool(result["ok"]),
                "st": str(result["status"]),
                "ans": answer_md,
                "src": [{"u": s.get("url"), "t": s.get("title")} for s in sources[:12]],
                "ev": [
                    {
                        "u": ev.get("source_url"),
                        "c": ev.get("chunk_id"),
                        "q": str(ev.get("quote") or "")[:180],
                    }
                    for ev in evidence[:16]
                ],
                "stats": result["stats"],
                "w": warnings[:16],
            }
            result["toon"] = dumps_toon(toon_payload)
        else:
            result["answer_md"] = answer_md

        return result
