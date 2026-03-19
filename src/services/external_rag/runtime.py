from __future__ import annotations

import random
from time import perf_counter, sleep
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from datetime import datetime, timezone

from capabilities.shared.chunking import normalize_whitespace

from .models import EvidenceItem, RetrievalRunResult
from .planner import ExternalRAGPlanner, ProviderSpec

DispatchFn = Callable[[str, Dict[str, Any]], Dict[str, Any]]
PickUrlsFn = Callable[..., Tuple[List[str], List[str]]]
SynthesizeFn = Callable[..., str]


class ExternalRAGRuntime:
    """Phase 1 runtime with explicit plan + traces and deterministic fallbacks."""

    def __init__(
        self,
        *,
        dispatch: DispatchFn,
        pick_urls: PickUrlsFn,
        synthesize: SynthesizeFn,
        provider_specs: Optional[Sequence[ProviderSpec]] = None,
    ):
        self._dispatch = dispatch
        self._pick_urls = pick_urls
        self._synthesize = synthesize
        self._planner = ExternalRAGPlanner()
        # None => use runtime defaults; [] => force no providers.
        self._provider_specs_override = None if provider_specs is None else list(provider_specs)

    def run(self, *, query: str, constraints: Dict[str, Any], language_hint: str) -> Tuple[RetrievalRunResult, List[Dict[str, Any]]]:
        started = perf_counter()
        warnings: List[str] = []
        execution_events: List[Dict[str, Any]] = []
        providers = self._provider_specs()
        provider_index = {spec.id: spec for spec in providers}
        initial_plan, initial_routing = self._planner.build_plan(query=query, constraints=constraints, providers=providers)

        all_docs: List[Dict[str, Any]] = []
        all_sources: List[Dict[str, Any]] = []
        all_evidence: List[EvidenceItem] = []

        max_docs = self._clamp_int(constraints.get("max_docs"), default=3, lo=1, hi=8)
        max_total_chars = self._clamp_int(constraints.get("max_total_chars"), default=14000, lo=1000, hi=90000)
        providers_attempted = 0
        provider_attempts_global: Dict[str, int] = {}
        routing_phases: List[Dict[str, Any]] = [
            {"phase": "initial", "decisions": [item.to_dict() for item in initial_routing]}
        ]
        replan_trace: List[Dict[str, Any]] = []

        providers_attempted = self._execute_plan(
            plan=initial_plan,
            constraints=constraints,
            started=started,
            max_docs=max_docs,
            max_total_chars=max_total_chars,
            all_docs=all_docs,
            all_sources=all_sources,
            all_evidence=all_evidence,
            warnings=warnings,
            execution_events=execution_events,
            providers_attempted=providers_attempted,
            provider_attempts_global=provider_attempts_global,
            provider_index=provider_index,
            fallback_layer="intra_domain",
        )

        allow_replan = bool(constraints.get("allow_replan", True))
        if allow_replan and not all_evidence and self._elapsed_ms(started) < initial_plan.budgets.latency_budget_ms:
            replan_constraints = self._make_replan_constraints(constraints)
            replan_plan, replan_routing = self._planner.build_plan(
                query=query,
                constraints=replan_constraints,
                providers=providers,
            )
            replan_trace.append(
                {
                    "phase": "replan_1",
                    "reason": "no_evidence_after_initial_plan",
                    "previous_query_id": initial_plan.query_id,
                    "replan_query_id": replan_plan.query_id,
                    "constraints_patch": {
                        "replan_mode": replan_constraints.get("replan_mode"),
                        "max_providers": replan_constraints.get("max_providers"),
                        "max_fallback_depth": replan_constraints.get("max_fallback_depth"),
                    },
                }
            )
            routing_phases.append({"phase": "replan_1", "decisions": [item.to_dict() for item in replan_routing]})
            providers_attempted = self._execute_plan(
                plan=replan_plan,
                constraints=replan_constraints,
                started=started,
                max_docs=max_docs,
                max_total_chars=max_total_chars,
                all_docs=all_docs,
                all_sources=all_sources,
                    all_evidence=all_evidence,
                    warnings=warnings,
                    execution_events=execution_events,
                    providers_attempted=providers_attempted,
                    provider_attempts_global=provider_attempts_global,
                    provider_index=provider_index,
                    fallback_layer="cross_domain_replan",
                )

        answer_md, status, final_fallback_layer = self._resolve_terminal_response(
            query=query,
            docs=all_docs,
            sources=all_sources,
            evidence=all_evidence,
            language_hint=language_hint,
            constraints=constraints,
        )
        chars_read = sum(len(str(doc.get("content") or "")) for doc in all_docs)
        merge_trace: Dict[str, Any] = {
            "strategy": initial_plan.merge_strategy,
            "consensus_mode": "composition",
            "providers_with_data": sorted({item.provider for item in all_evidence}),
            "source_count": len(all_sources),
            "evidence_count": len(all_evidence),
            "status": status,
            "fallback_layer": final_fallback_layer,
        }

        result = RetrievalRunResult(
            answer_md=answer_md,
            status=status,
            sources=all_sources,
            evidence=all_evidence,
            stats={
                "steps": len(initial_plan.plan_steps),
                "docs_opened": len(all_docs),
                "chars_read": chars_read,
                "providers_attempted": providers_attempted,
            },
            traces={
                "plan_trace": initial_plan.to_dict(),
                "routing_explanation": routing_phases,
                "execution_trace": execution_events,
                "replan_trace": replan_trace,
                "merge_trace": merge_trace,
            },
            warnings=warnings,
        )
        return result, all_docs

    def _execute_plan(
        self,
        *,
        plan: Any,
        constraints: Dict[str, Any],
        started: float,
        max_docs: int,
        max_total_chars: int,
        all_docs: List[Dict[str, Any]],
        all_sources: List[Dict[str, Any]],
        all_evidence: List[EvidenceItem],
        warnings: List[str],
        execution_events: List[Dict[str, Any]],
        providers_attempted: int,
        provider_attempts_global: Dict[str, int],
        provider_index: Dict[str, ProviderSpec],
        fallback_layer: str,
    ) -> int:
        chars_read = sum(len(str(doc.get("content") or "")) for doc in all_docs)
        max_per_step = self._clamp_int(constraints.get("max_provider_attempts_per_step"), default=1, lo=1, hi=3)
        max_global = self._clamp_int(constraints.get("max_provider_attempts_global"), default=2, lo=1, hi=8)
        for step in plan.plan_steps:
            provider_attempts_step: Dict[str, int] = {}
            sequence = list(step.selected_providers)
            for provider in plan.fallback_chain:
                if provider not in sequence:
                    sequence.append(provider)

            for provider in sequence:
                provider_spec = provider_index.get(provider)
                if provider_spec is None:
                    execution_events.append(
                        {
                            "step_id": step.step_id,
                            "provider": provider,
                            "attempt": providers_attempted,
                            "used": False,
                            "status": "skipped",
                            "reason": "provider_missing_in_registry_index",
                            "elapsed_ms": 0,
                            "fallback_layer": fallback_layer,
                        }
                    )
                    continue
                provider_attempts_step.setdefault(provider, 0)
                provider_attempts_global.setdefault(provider, 0)
                if provider_attempts_step[provider] >= max_per_step:
                    execution_events.append(
                        {
                            "step_id": step.step_id,
                            "provider": provider,
                            "attempt": providers_attempted,
                            "used": False,
                            "status": "skipped",
                            "reason": "provider_attempt_limit_step",
                            "elapsed_ms": 0,
                            "fallback_layer": fallback_layer,
                        }
                    )
                    continue
                if provider_attempts_global[provider] >= max_global:
                    execution_events.append(
                        {
                            "step_id": step.step_id,
                            "provider": provider,
                            "attempt": providers_attempted,
                            "used": False,
                            "status": "skipped",
                            "reason": "provider_attempt_limit_global",
                            "elapsed_ms": 0,
                            "fallback_layer": fallback_layer,
                        }
                    )
                    continue
                if providers_attempted >= (plan.budgets.max_providers + plan.budgets.max_fallback_depth):
                    warnings.append("Provider attempt budget exhausted.")
                    break
                providers_attempted += 1
                provider_attempts_step[provider] += 1
                provider_attempts_global[provider] += 1

                if self._elapsed_ms(started) >= plan.budgets.latency_budget_ms:
                    warnings.append("Latency budget exhausted.")
                    break

                event = {
                    "step_id": step.step_id,
                    "provider": provider,
                    "attempt": providers_attempted,
                    "used": False,
                    "status": "skipped",
                    "reason": "not_executed",
                    "elapsed_ms": 0,
                    "fallback_layer": fallback_layer,
                }
                p_started = perf_counter()

                try:
                    docs, sources, evidence, p_warnings, success = self._execute_provider(
                        provider=provider_spec,
                        query=step.query,
                        constraints=constraints,
                        remaining_chars=max(0, max_total_chars - chars_read),
                        max_docs=max_docs - len(all_docs),
                        max_retries=int(plan.budgets.max_retries),
                    )
                    warnings.extend(p_warnings)

                    event["elapsed_ms"] = self._elapsed_ms(p_started)
                    event["used"] = True
                    if success:
                        event["status"] = "success"
                        event["reason"] = "provider_returned_data"
                        all_docs.extend(docs)
                        for src in sources:
                            if src not in all_sources:
                                all_sources.append(src)
                        all_evidence.extend(evidence)
                        chars_read = sum(len(str(doc.get("content") or "")) for doc in all_docs)
                        execution_events.append(event)
                        break

                    event["status"] = "empty"
                    event["reason"] = "provider_empty"
                except Exception as exc:  # defensive, avoid leaking runtime exceptions
                    event["elapsed_ms"] = self._elapsed_ms(p_started)
                    event["used"] = True
                    event["status"] = "error"
                    event["reason"] = "runtime_exception"
                    warnings.append(f"Provider '{provider}' failed: {exc}")

                execution_events.append(event)

            execution_events.append(
                {
                    "step_id": step.step_id,
                    "provider": "step",
                    "attempt": providers_attempted,
                    "used": True,
                    "status": "step_complete",
                    "reason": "step_terminated",
                    "elapsed_ms": self._elapsed_ms(started),
                    "docs_collected": len(all_docs),
                    "fallback_layer": fallback_layer,
                }
            )

            if len(all_docs) >= max_docs or chars_read >= max_total_chars:
                break
        return providers_attempted

    def _resolve_terminal_response(
        self,
        *,
        query: str,
        docs: List[Dict[str, Any]],
        sources: List[Dict[str, Any]],
        evidence: List[EvidenceItem],
        language_hint: str,
        constraints: Dict[str, Any] | None = None,
    ) -> Tuple[str, str, str]:
        if docs:
            evidence_payload = [item.to_dict() for item in evidence]
            return (
                self._synthesize(
                    goal=query,
                    docs=docs,
                    evidence=evidence_payload,
                    language_hint=language_hint,
                ),
                "success",
                "none",
            )
        if sources:
            return self._fallback_answer_from_sources(query=query, sources=sources), "partial", "internal_source_only"
        internal = self._internal_knowledge_rows(constraints or {})
        if internal:
            lines = [f"Query: {query}", "", "Internal knowledge fallback (no external evidence found):"]
            for row in internal[:8]:
                title = str(row.get("title") or "internal_note")
                content = normalize_whitespace(row.get("content") or "")
                source = str(row.get("source") or "internal_knowledge")
                if content:
                    lines.append(f"- {title} ({source}): {content[:220]}")
            return "\n".join(lines), "partial", "internal_knowledge"
        return "No relevant evidence found with the current providers and constraints.", "empty_with_reason", "exhausted"

    @staticmethod
    def _make_replan_constraints(constraints: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(constraints)
        out["replan_mode"] = "broad_recovery"
        try:
            out["max_providers"] = min(3, int(out.get("max_providers") or 2) + 1)
        except Exception:
            out["max_providers"] = 3
        try:
            out["max_fallback_depth"] = min(4, int(out.get("max_fallback_depth") or 2) + 1)
        except Exception:
            out["max_fallback_depth"] = 3
        return out

    def _provider_specs(self) -> Sequence[ProviderSpec]:
        if self._provider_specs_override is not None:
            return list(self._provider_specs_override)
        return [
            ProviderSpec(
                id="web",
                domains=("web", "academic", "location"),
                action_id="web.search.discover",
                strategy="search_then_read",
                setup_ready=True,
                trust_tier="high",
            ),
            ProviderSpec(
                id="wikipedia_search",
                domains=("encyclopedia", "web"),
                action_id="wikipedia.search",
                strategy="direct_results",
                setup_ready=True,
                trust_tier="high",
            ),
            ProviderSpec(
                id="youtube",
                domains=("video", "web"),
                action_id="youtube.search.find",
                strategy="direct_results",
                setup_ready=True,
                trust_tier="medium",
            ),
        ]

    def _execute_provider(
        self,
        *,
        provider: ProviderSpec,
        query: str,
        constraints: Dict[str, Any],
        remaining_chars: int,
        max_docs: int,
        max_retries: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[EvidenceItem], List[str], bool]:
        if provider.strategy == "search_then_read":
            return self._run_web_provider(
                provider=provider,
                query=query,
                constraints=constraints,
                remaining_chars=remaining_chars,
                max_docs=max_docs,
                max_retries=max_retries,
            )
        if provider.action_id:
            return self._run_direct_provider(
                provider=provider,
                query=query,
                constraints=constraints,
                max_docs=max_docs,
                max_retries=max_retries,
            )
        return [], [], [], [f"Unknown provider '{provider.id}' skipped."], False

    def _run_web_provider(
        self,
        *,
        provider: ProviderSpec,
        query: str,
        constraints: Dict[str, Any],
        remaining_chars: int,
        max_docs: int,
        max_retries: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[EvidenceItem], List[str], bool]:
        warnings: List[str] = []
        retry_policy = self._retry_policy(constraints)
        if max_docs <= 0 or remaining_chars <= 0:
            return [], [], [], ["Web provider skipped due to document/char budget."], False

        max_links_to_open = self._clamp_int(constraints.get("max_links_to_open"), default=3, lo=1, hi=8)
        search_limit = min(12, max(6, max_links_to_open * 3))
        search_params: Dict[str, Any] = {
            "query": query,
            "limit": search_limit,
            "mode": "links",
            "domains_allow": self._to_list(constraints.get("domains_allow")),
            "domains_deny": self._to_list(constraints.get("domains_deny")),
        }
        recency_days = self._clamp_int(constraints.get("recency_days"), default=0, lo=0, hi=3650)
        if recency_days > 0:
            search_params["recency_days"] = recency_days

        search_result, search_warnings = self._dispatch_with_retry(
            action_id=provider.action_id or "web.search.discover",
            params=search_params,
            max_retries=max_retries,
            retry_policy=retry_policy,
        )
        warnings.extend(search_warnings)
        if not isinstance(search_result, dict) or not search_result.get("ok"):
            code = str((search_result or {}).get("error_code") or "SEARCH_FAILED")
            return [], [], [], [f"{provider.action_id} failed ({code})."], False

        results = search_result.get("results") if isinstance(search_result.get("results"), list) else []
        if not results:
            return [], [], [], ["web.search.discover returned no results."], False

        picked_urls, pick_warnings = self._pick_urls(
            goal=query,
            results=results,
            max_links_to_open=max_links_to_open,
        )
        warnings.extend(pick_warnings)
        if not picked_urls:
            return [], [], [], warnings + ["No URLs selected for reading."], False

        docs: List[Dict[str, Any]] = []
        sources: List[Dict[str, Any]] = []
        evidence: List[EvidenceItem] = []
        chars_read = 0

        for url in picked_urls:
            if len(docs) >= max_docs:
                break
            per_doc_budget = max(200, remaining_chars - chars_read)
            if per_doc_budget <= 200:
                break
            read_result, read_warnings = self._dispatch_with_retry(
                action_id="web.retrieve.read",
                params={
                    "url": url,
                    "mode": "main",
                    "max_chars": min(3500, per_doc_budget),
                    "timeout_ms": 12000,
                    "retries": 1,
                },
                max_retries=max_retries,
                retry_policy=retry_policy,
            )
            warnings.extend(read_warnings)
            if not isinstance(read_result, dict) or not read_result.get("ok"):
                code = str((read_result or {}).get("error_code") or "READ_FAILED")
                warnings.append(f"web.retrieve.read failed for {url} ({code}).")
                continue

            text_md = normalize_whitespace(read_result.get("text_md") or "")
            if not text_md:
                warnings.append(f"Read empty content for {url}.")
                continue

            text_md = text_md[:per_doc_budget]
            chars_read += len(text_md)
            doc_url = str(read_result.get("canonical_url") or read_result.get("url") or url)
            doc_title = str(read_result.get("title") or doc_url)
            source_obj = {
                "url": doc_url,
                "title": doc_title,
                "status_code": read_result.get("status_code"),
            }
            if source_obj not in sources:
                sources.append(source_obj)

            quote = text_md[:280]
            chunk_id: Optional[str] = None
            chunks = read_result.get("chunks") if isinstance(read_result.get("chunks"), list) else []
            if chunks:
                first = chunks[0] if isinstance(chunks[0], dict) else {}
                quote = str(first.get("text") or quote)
                chunk_id = str(first.get("id") or "") or None

            docs.append({"url": doc_url, "title": doc_title, "content": text_md})
            evidence.append(
                EvidenceItem(
                    provider=provider.id,
                    source_url=doc_url,
                    source_title=doc_title,
                    quote=quote,
                    chunk_id=chunk_id,
                    metadata=self._evidence_metadata(
                        provider_id=provider.id,
                        source_url=doc_url,
                        source_title=doc_title,
                        quote=quote,
                        source_type="web_read",
                        confidence=None,
                    ),
                )
            )

        return docs, sources, evidence, warnings, bool(docs)

    def _run_direct_provider(
        self,
        *,
        provider: ProviderSpec,
        query: str,
        constraints: Dict[str, Any],
        max_docs: int,
        max_retries: int,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[EvidenceItem], List[str], bool]:
        warnings: List[str] = []
        retry_policy = self._retry_policy(constraints)
        result, call_warnings = self._dispatch_with_retry(
            action_id=provider.action_id,
            params={"query": query, "limit": max(1, min(max_docs, 4))},
            max_retries=max_retries,
            retry_policy=retry_policy,
        )
        warnings.extend(call_warnings)
        if not isinstance(result, dict) or not result.get("ok"):
            code = str((result or {}).get("error_code") or "PROVIDER_FAILED")
            return [], [], [], [f"{provider.action_id} failed ({code})."], False

        rows = result.get("results") if isinstance(result.get("results"), list) else []
        if not rows:
            return [], [], [], [f"{provider.action_id} returned no results."], False

        docs: List[Dict[str, Any]] = []
        sources: List[Dict[str, Any]] = []
        evidence: List[EvidenceItem] = []

        for row in rows[:max_docs]:
            url = str(row.get("url") or "").strip()
            title = str(row.get("title") or url)
            content = normalize_whitespace(row.get("content") or "")
            if not content:
                parts = [
                    str(title or "").strip(),
                    str(row.get("artist") or "").strip(),
                    str(row.get("album") or "").strip(),
                    str(row.get("excerpt") or row.get("descriptionSnippet") or row.get("snippet") or "").strip(),
                ]
                content = normalize_whitespace(". ".join([part for part in parts if part]))
            if not url or not content:
                continue
            docs.append({"url": url, "title": title, "content": content})
            source_obj = {"url": url, "title": title, "status_code": 200}
            if source_obj not in sources:
                sources.append(source_obj)
            quote = str(
                row.get("excerpt")
                or row.get("descriptionSnippet")
                or row.get("snippet")
                or content[:280]
            )
            evidence.append(
                EvidenceItem(
                    provider=provider.id,
                    source_url=url,
                    source_title=title,
                    quote=quote,
                    metadata=self._evidence_metadata(
                        provider_id=provider.id,
                        source_url=url,
                        source_title=title,
                        quote=quote,
                        source_type=str(row.get("source") or "provider_search"),
                        confidence=row.get("confidenceScore"),
                    ),
                )
            )

        return docs, sources, evidence, warnings, bool(docs)

    def _dispatch_with_retry(
        self,
        *,
        action_id: str,
        params: Dict[str, Any],
        max_retries: int,
        retry_policy: Dict[str, int] | None = None,
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings: List[str] = []
        attempts = max(1, int(max_retries) + 1)
        policy = retry_policy or {}
        base_ms = self._clamp_int(policy.get("base_ms"), default=0, lo=0, hi=2000)
        max_ms = self._clamp_int(policy.get("max_ms"), default=1200, lo=0, hi=10000)
        jitter_ms = self._clamp_int(policy.get("jitter_ms"), default=0, lo=0, hi=500)
        last_result: Dict[str, Any] = {}
        for attempt in range(1, attempts + 1):
            result = self._dispatch(action_id, params)
            if isinstance(result, dict):
                last_result = result
            if isinstance(result, dict) and result.get("ok"):
                return result, warnings
            if not self._is_retryable(result):
                return result if isinstance(result, dict) else {}, warnings
            if attempt < attempts:
                warnings.append(f"{action_id} retry {attempt}/{attempts - 1}")
                delay = min(max_ms, base_ms * (2 ** (attempt - 1)))
                if jitter_ms > 0:
                    delay += random.randint(0, jitter_ms)
                if delay > 0:
                    warnings.append(f"{action_id} backoff {delay}ms")
                    sleep(delay / 1000.0)
        return last_result, warnings

    @staticmethod
    def _is_retryable(result: Any) -> bool:
        if not isinstance(result, dict):
            return False
        if bool(result.get("retryable", False)):
            return True
        status_code = result.get("status_code")
        try:
            code = int(status_code)
        except Exception:
            code = 0
        return code in {408, 425, 429, 500, 502, 503, 504}

    @staticmethod
    def _internal_knowledge_rows(constraints: Dict[str, Any]) -> List[Dict[str, Any]]:
        value = constraints.get("internal_knowledge_fallback")
        if isinstance(value, list):
            out: List[Dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    out.append(item)
            return out
        return []

    @staticmethod
    def _retry_policy(constraints: Dict[str, Any]) -> Dict[str, int]:
        return {
            "base_ms": ExternalRAGRuntime._clamp_int(constraints.get("retry_backoff_base_ms"), default=0, lo=0, hi=2000),
            "max_ms": ExternalRAGRuntime._clamp_int(constraints.get("retry_backoff_max_ms"), default=1200, lo=0, hi=10000),
            "jitter_ms": ExternalRAGRuntime._clamp_int(constraints.get("retry_backoff_jitter_ms"), default=0, lo=0, hi=500),
        }

    @staticmethod
    def provider_specs_from_offers(offers: Sequence[Dict[str, Any]]) -> List[ProviderSpec]:
        if not offers:
            return []
        specs: List[ProviderSpec] = []
        trust_map = {
            "curated": "high",
            "public_api": "medium",
            "community": "low",
        }
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            capability_id = str(offer.get("capability_id") or "").strip()
            if not capability_id or capability_id == "research_retrieve":
                continue
            actions = [str(a).strip() for a in (offer.get("actions") or []) if str(a).strip()]
            if not actions:
                continue

            action_id = actions[0]
            strategy = "direct_results"
            if "web.search.discover" in actions:
                action_id = "web.search.discover"
                strategy = "search_then_read"
            quality = offer.get("quality") if isinstance(offer.get("quality"), dict) else {}
            trust_tier_raw = str(quality.get("trust_tier") or "").strip().lower()
            trust_tier = trust_map.get(trust_tier_raw, "medium")
            domains = tuple(str(x).strip().lower() for x in (offer.get("domains") or []) if str(x).strip())
            if not domains:
                domains = ("web",)
            specs.append(
                ProviderSpec(
                    id=capability_id,
                    domains=domains,
                    action_id=action_id,
                    strategy=strategy,
                    setup_ready=bool(offer.get("setup_ready", True)),
                    trust_tier=trust_tier,
                )
            )
        return specs

    @staticmethod
    def _fallback_answer_from_sources(*, query: str, sources: List[Dict[str, Any]]) -> str:
        lines = [f"Query: {query}", "", "Found references but limited readable evidence:"]
        for source in sources[:8]:
            url = str(source.get("url") or "").strip()
            title = str(source.get("title") or url)
            if url:
                lines.append(f"- [{title}]({url})")
        return "\n".join(lines)

    @staticmethod
    def _clamp_int(value: Any, *, default: int, lo: int, hi: int) -> int:
        try:
            n = int(value)
        except Exception:
            n = default
        return max(lo, min(hi, n))

    @staticmethod
    def _to_list(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(1, int((perf_counter() - started) * 1000))

    @staticmethod
    def _evidence_metadata(
        *,
        provider_id: str,
        source_url: str,
        source_title: str,
        quote: str,
        source_type: str,
        confidence: Any,
    ) -> Dict[str, Any]:
        confidence_value = None
        try:
            if confidence is not None:
                confidence_value = float(confidence)
        except Exception:
            confidence_value = None
        return {
            "provider_id": provider_id,
            "domain": "external",
            "source_id": source_url or source_title,
            "source_type": source_type,
            "citation_required": True,
            "confidence": confidence_value,
            "snippet": str(quote or "")[:280],
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "schema": "external.evidence.v1",
        }
