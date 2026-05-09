import json
import logging
import re
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from ..base import CapabilityBase
from core.action_gateway import ActionGateway
from ..shared.chunking import normalize_whitespace
from ..shared.error_contract import error_envelope, success_envelope
from services.external_rag.planner import ExternalRAGPlanner
from services.external_rag.runtime import ExternalRAGRuntime
from utils.toon_codec import dumps_toon

logger = logging.getLogger("ResearchRetrieveCapability")


class RegistryWrapper:
    BASE_ALLOWLIST = {
        "web.retrieve.read",
        "web.retrieve.extract",
    }

    def __init__(self, dispatch_fn: Any, envelope: Dict[str, Any], allowlist: Optional[set[str]] = None):
        self._dispatch_fn = dispatch_fn
        self.envelope = envelope
        if allowlist is None:
            allowlist = set(self.BASE_ALLOWLIST)
        self._allowlist = set(allowlist)

    def dispatch(self, action_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action_id not in self._allowlist:
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

        class _ProxyRegistry:
            def __init__(self, dispatch_fn: Any, allowlist: set[str]):
                self._dispatch_fn = dispatch_fn
                self._allowlist = set(allowlist)

            def get_capability_for_action(self, candidate: str):
                return object() if candidate in self._allowlist else None

            def get_action_metadata(self, candidate: str) -> Dict[str, Any]:
                return {}

            def dispatch(self, candidate: str, candidate_params: Dict[str, Any], candidate_context: Dict[str, Any]) -> Any:
                isolated_context = {"research_envelope": dict(candidate_context.get("research_envelope") or {})}
                return self._dispatch_fn(candidate, candidate_params, isolated_context)

            def list_actions(self) -> List[str]:
                return sorted(self._allowlist)

        gateway = ActionGateway()
        proxy_registry = _ProxyRegistry(self._dispatch_fn, self._allowlist)
        result = gateway.execute_action(
            action_id=action_id,
            params=params,
            allowed_actions=sorted(self._allowlist),
            capability_registry=proxy_registry,
            capability_metadata={},
            context={"research_envelope": dict(self.envelope)},
            strict_mode=False,
        )
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
    MODULAR_SEARCH_PROVIDER_IDS = {"brave_search", "ddg_search", "searxng_search", "openalex_search", "commoncrawl_search"}
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

    def _merged_constraints(self, params: Dict[str, Any]) -> Dict[str, Any]:
        request_constraints = params.get("constraints") if isinstance(params.get("constraints"), dict) else {}
        live_config = self._live_config()
        config_defaults = live_config.get("defaults") if isinstance(live_config.get("defaults"), dict) else {}
        merged: Dict[str, Any] = self._normalize_default_constraints(config_defaults)
        merged.update(request_constraints)
        return merged

    def _live_config(self) -> Dict[str, Any]:
        base = self.config if isinstance(self.config, dict) else {}
        out = dict(base)
        kernel = self.kernel
        cfg_manager = getattr(kernel, "config_manager", None) if kernel else None
        if cfg_manager and hasattr(cfg_manager, "get_capability_config"):
            try:
                live = cfg_manager.get_capability_config("research_retrieve")
                if isinstance(live, dict):
                    out.update(live)
            except Exception:
                pass
        return out

    @staticmethod
    def _normalize_default_constraints(defaults: Dict[str, Any]) -> Dict[str, Any]:
        """
        Backward-compatible normalization for capability config defaults.
        Supports:
        1) legacy flat keys under `defaults`
        2) grouped keys under section objects (execution/retry/provider_limits/replan)
        """
        out: Dict[str, Any] = {}
        if not isinstance(defaults, dict):
            return out

        # Keep existing flat defaults.
        for key, value in defaults.items():
            if not isinstance(value, dict):
                out[key] = value

        section_names = ("execution", "retry", "provider_limits", "replan", "control_plane")
        for section in section_names:
            section_obj = defaults.get(section)
            if not isinstance(section_obj, dict):
                continue
            if section == "control_plane":
                overrides = section_obj.get("overrides")
                if isinstance(overrides, dict):
                    out["provider_runtime_overrides"] = dict(overrides)
                scorecard = section_obj.get("scorecard")
                if isinstance(scorecard, dict):
                    out["provider_runtime_scorecard"] = dict(scorecard)
                # Also accept canonical key names inside grouped config.
                grouped_overrides = section_obj.get("provider_runtime_overrides")
                if isinstance(grouped_overrides, dict):
                    out["provider_runtime_overrides"] = dict(grouped_overrides)
                grouped_scorecard = section_obj.get("provider_runtime_scorecard")
                if isinstance(grouped_scorecard, dict):
                    out["provider_runtime_scorecard"] = dict(grouped_scorecard)
                continue
            for key, value in section_obj.items():
                out[key] = value

        return out

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

    @classmethod
    def _prefer_modular_offers(
        cls,
        offers: List[Dict[str, Any]],
        *,
        enabled: bool,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if not enabled:
            return offers, []
        has_modular = any(
            str(row.get("capability_id") or "").strip() in cls.MODULAR_SEARCH_PROVIDER_IDS
            for row in offers
            if isinstance(row, dict)
        )
        if not has_modular:
            return offers, []
        dropped: List[Dict[str, Any]] = []
        filtered = [
            row
            for row in offers
            if isinstance(row, dict) and str(row.get("capability_id") or "").strip() not in {"web_search", "web"}
        ]
        if len(filtered) != len(offers):
            dropped.append({"capability_id": "web", "reason": "prefer_modular_providers"})
        return (filtered or offers), dropped

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

        constraints = self._merged_constraints(params)
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
        runtime_allowlist: set[str] = set(RegistryWrapper.BASE_ALLOWLIST)
        if registry and hasattr(registry, "list_retrieval_offers"):
            try:
                        offers_all = registry.list_retrieval_offers()
                        for offer in offers_all:
                            if not isinstance(offer, dict):
                                continue
                            capability_id = str(offer.get("capability_id") or "").strip()
                            if capability_id == "research_retrieve":
                                continue
                            actions = offer.get("actions") if isinstance(offer.get("actions"), list) else []
                            for action in actions:
                                action_id = str(action or "").strip()
                                if action_id:
                                    runtime_allowlist.add(action_id)
            except Exception as e:
                warnings.append(f"retrieval_allowlist_unavailable: {e}")
        kernel_lite = RegistryWrapper(dispatch_fn=dispatch_fn, envelope=envelope, allowlist=runtime_allowlist)
        live_config = self._live_config()
        use_external_runtime = bool(params.get("use_external_rag_runtime", live_config.get("use_external_rag_runtime", True)))
        allow_legacy_fallback = bool(
            params.get("allow_legacy_fallback")
            if params.get("allow_legacy_fallback") is not None
            else live_config.get("allow_legacy_fallback", False)
        )

        if use_external_runtime:
            try:
                provider_specs = []
                offer_selection_trace: Dict[str, Any] = {
                    "queries": [],
                    "selected_capability_ids": [],
                    "dropped": [],
                    "prefer_modular_providers": bool(constraints.get("prefer_modular_providers", True)),
                }
                if registry and hasattr(registry, "list_retrieval_offers"):
                    try:
                        planner = ExternalRAGPlanner()
                        intent, _subintent = planner.classify_intent(query)
                        domain = planner.intent_to_domain(intent)
                        offers = registry.list_retrieval_offers(intent=intent, domain=domain)
                        offer_selection_trace["queries"].append({"intent": intent, "domain": domain, "count": len(offers or [])})
                        if not offers:
                            offers = registry.list_retrieval_offers(intent=intent)
                            offer_selection_trace["queries"].append({"intent": intent, "domain": None, "count": len(offers or [])})
                        if not offers:
                            offers = registry.list_retrieval_offers()
                            offer_selection_trace["queries"].append({"intent": None, "domain": None, "count": len(offers or [])})
                        prefer_modular = bool(constraints.get("prefer_modular_providers", True))
                        offers, dropped = self._prefer_modular_offers(list(offers or []), enabled=prefer_modular)
                        offer_selection_trace["dropped"] = dropped
                        offer_selection_trace["selected_capability_ids"] = [
                            str(row.get("capability_id") or "").strip()
                            for row in offers
                            if isinstance(row, dict) and str(row.get("capability_id") or "").strip()
                        ]
                        provider_specs = ExternalRAGRuntime.provider_specs_from_offers(offers)
                    except Exception as e:
                        warnings.append(f"retrieval_offer_index_unavailable: {e}")
                        offer_selection_trace["error"] = str(e)
                else:
                    offer_selection_trace = {
                        "queries": [],
                        "selected_capability_ids": [],
                        "dropped": [],
                        "prefer_modular_providers": bool(constraints.get("prefer_modular_providers", True)),
                        "error": "capability_registry_without_retrieval_offers",
                    }

                runtime = ExternalRAGRuntime(
                    dispatch=kernel_lite.dispatch,
                    pick_urls=self._pick_urls_with_llm,
                    synthesize=self._synthesize_answer,
                    provider_specs=provider_specs,
                )
                runtime_result, docs = runtime.run(
                    query=query,
                    constraints=constraints,
                    language_hint=lang,
                )
                warnings.extend(runtime_result.warnings)

                extracted_rows: List[Dict[str, Any]] = []
                should_extract = bool(extract_schema) or self._looks_field_request(query)
                if should_extract and docs and extract_schema:
                    for doc in docs[:max_docs]:
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
                                    "data": extract_result.get("data")
                                    if isinstance(extract_result.get("data"), dict)
                                    else {},
                                }
                            )

                answer_md = runtime_result.answer_md
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
                payload = runtime_result.to_payload()
                result.update(
                    {
                        "status": payload.get("status") or "success",
                        "sources": payload.get("sources") or [],
                        "evidence": payload.get("evidence") or [],
                        "stats": payload.get("stats") or {},
                        "traces": {
                            **((payload.get("traces") or {}) if isinstance(payload.get("traces"), dict) else {}),
                            "offer_selection_trace": offer_selection_trace,
                            "runtime_allowlist_size": len(runtime_allowlist),
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
                        "src": [{"u": s.get("url"), "t": s.get("title")} for s in (result.get("sources") or [])[:12]],
                        "ev": [
                            {
                                "u": ev.get("source_url"),
                                "c": ev.get("chunk_id"),
                                "q": str(ev.get("quote") or "")[:180],
                            }
                            for ev in (result.get("evidence") or [])[:16]
                        ],
                        "stats": result.get("stats") or {},
                        "w": warnings[:16],
                    }
                    result["toon"] = dumps_toon(toon_payload)
                else:
                    result["answer_md"] = answer_md
                return result
            except Exception as e:
                warnings.append(f"external_rag_runtime_failed: {e}")
                if not allow_legacy_fallback:
                    result = error_envelope(
                        provider="research.retrieve",
                        error_code="EXTERNAL_RAG_RUNTIME_FAILED",
                        error_message=str(e),
                        retryable=True,
                        elapsed=self._elapsed_ms(started),
                        warnings=warnings,
                    )
                    result.update(
                        {
                            "status": "error",
                            "sources": [],
                            "evidence": [],
                            "stats": {"steps": 0, "docs_opened": 0, "chars_read": 0},
                        }
                    )
                    return result
                warnings.append("fallback=legacy_pipeline")

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
