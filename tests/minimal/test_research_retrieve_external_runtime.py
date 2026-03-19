import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.capabilities.research_retrieve.capability import ResearchRetrieveCapability


class _FakeRegistry:
    def __init__(self, mode: str = "success", offers: list[dict] | None = None):
        self.mode = mode
        self.last_offer_query = None
        self.offer_queries = []
        self.offers = offers or [
            {
                "capability_id": "web_search",
                "domains": ["web"],
                "actions": ["web.search.discover"],
                "quality": {"trust_tier": "public_api"},
                "routing_hints": {"preferred_intents": ["structured_fact", "latest_update", "general_knowledge"]},
            }
        ]

    def dispatch(self, action_id, params, context):
        _ = params, context
        if action_id == "web.search.discover":
            if self.mode == "retry_once":
                count = getattr(self, "_retry_count", 0)
                self._retry_count = count + 1
                if count == 0:
                    return {"ok": False, "error_code": "TEMP", "retryable": True, "status_code": 503}
            if self.mode == "empty":
                return {"ok": True, "results": []}
            return {
                "ok": True,
                "results": [{"url": "https://example.com/a", "title": "A", "snippet": "snippet"}],
                "warnings": [],
            }
        if action_id == "web.retrieve.read":
            return {
                "ok": True,
                "url": "https://example.com/a",
                "canonical_url": "https://example.com/a",
                "title": "A",
                "text_md": "This page contains objective facts.",
                "chunks": [{"id": "c1", "text": "This page contains objective facts."}],
                "status_code": 200,
            }
        if action_id == "wikipedia.search":
            return {"ok": True, "results": []}
        if action_id == "youtube.search.find":
            return {"ok": True, "results": []}
        if action_id == "web.retrieve.extract":
            return {"ok": True, "data": {"field": "value"}}
        if action_id == "brave.search.query":
            return {
                "ok": True,
                "results": [{"url": "https://brave.example.com/r", "title": "R", "content": "Brave factual snippet"}],
            }
        return {"ok": False, "error_code": "UNKNOWN_ACTION"}

    def list_retrieval_offers(self, **kwargs):
        query = dict(kwargs)
        self.last_offer_query = query
        self.offer_queries.append(query)
        return list(self.offers)


def test_research_retrieve_contract_includes_external_rag_controls():
    contract_path = ROOT / "src" / "capabilities" / "research_retrieve" / "contract.json"
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    assert payload["runtime"]["config_schema"] == "./config.schema.json"
    assert (contract_path.parent / payload["runtime"]["config_schema"]).exists()
    params = payload["actions"][0]["parameters"]["properties"]
    constraints = params["constraints"]["properties"]

    assert "use_external_rag_runtime" in params
    assert "provider_runtime_overrides" in constraints
    assert "provider_runtime_scorecard" in constraints
    assert "allow_replan" in constraints
    assert "max_retries" in constraints
    assert "retry_backoff_base_ms" in constraints
    assert "max_provider_attempts_global" in constraints
    assert "internal_knowledge_fallback" in constraints


def test_research_retrieve_runtime_mode_returns_traces_and_internal_fallback():
    capability = ResearchRetrieveCapability(kernel=None, config={})

    success_result = capability.execute(
        "research.retrieve.run",
        {
            "query": "what is retrieval plan",
            "use_external_rag_runtime": True,
            "constraints": {"max_docs": 1, "max_total_chars": 3000},
        },
        {"capability_registry": _FakeRegistry(mode="success")},
    )
    assert success_result.get("ok") is True
    assert success_result.get("status") == "success"
    assert isinstance(success_result.get("traces"), dict)
    assert "plan_trace" in success_result["traces"]
    assert "execution_trace" in success_result["traces"]
    assert "offer_selection_trace" in success_result["traces"]

    fallback_result = capability.execute(
        "research.retrieve.run",
        {
            "query": "how do we run onboarding",
            "use_external_rag_runtime": True,
            "constraints": {
                "allow_replan": False,
                "internal_knowledge_fallback": [
                    {"title": "Onboarding", "content": "Use checklist A then B.", "source": "policy.internal"}
                ],
            },
        },
        {"capability_registry": _FakeRegistry(mode="empty")},
    )
    assert fallback_result.get("ok") is True
    assert fallback_result.get("status") == "partial"
    assert fallback_result.get("traces", {}).get("merge_trace", {}).get("fallback_layer") == "internal_knowledge"


def test_research_retrieve_uses_config_defaults_for_external_runtime_constraints():
    capability = ResearchRetrieveCapability(
        kernel=None,
        config={
            "use_external_rag_runtime": True,
            "defaults": {
                "max_retries": 1,
                "retry_backoff_base_ms": 0,
                "max_docs": 1,
                "max_total_chars": 3000,
            },
        },
    )
    result = capability.execute(
        "research.retrieve.run",
        {
            "query": "latest iphone price",
            "use_external_rag_runtime": True,
        },
        {"capability_registry": _FakeRegistry(mode="retry_once")},
    )
    assert result.get("ok") is True
    assert result.get("status") in {"success", "partial"}
    assert any("web.search.discover retry" in str(w) for w in (result.get("warnings") or []))


def test_research_retrieve_supports_grouped_defaults_configuration():
    capability = ResearchRetrieveCapability(
        kernel=None,
        config={
            "use_external_rag_runtime": True,
            "defaults": {
                "execution": {"max_docs": 1, "max_total_chars": 3000},
                "retry": {"max_retries": 1, "retry_backoff_base_ms": 0},
                "provider_limits": {"max_providers": 1},
                "replan": {"allow_replan": False},
            },
        },
    )
    result = capability.execute(
        "research.retrieve.run",
        {
            "query": "latest iphone price",
            "use_external_rag_runtime": True,
        },
        {"capability_registry": _FakeRegistry(mode="retry_once")},
    )
    assert result.get("ok") is True
    assert any("web.search.discover retry" in str(w) for w in (result.get("warnings") or []))


def test_research_retrieve_queries_registry_with_intent_and_domain_filters():
    registry = _FakeRegistry(mode="success")
    capability = ResearchRetrieveCapability(kernel=None, config={})
    result = capability.execute(
        "research.retrieve.run",
        {
            "query": "latest iphone price",
            "use_external_rag_runtime": True,
            "constraints": {"max_docs": 1, "max_total_chars": 3000},
        },
        {"capability_registry": registry},
    )
    assert result.get("ok") is True
    assert isinstance(registry.last_offer_query, dict)
    assert registry.last_offer_query.get("domain") == "web"
    assert registry.last_offer_query.get("intent") == "structured_fact"


def test_research_retrieve_allows_external_provider_actions_from_retrieval_offers():
    offers = [
        {
            "capability_id": "brave_search",
            "domains": ["web"],
            "actions": ["brave.search.query"],
            "quality": {"trust_tier": "public_api"},
            "routing_hints": {"preferred_intents": ["structured_fact", "general_knowledge"]},
        }
    ]
    registry = _FakeRegistry(mode="success", offers=offers)
    capability = ResearchRetrieveCapability(kernel=None, config={})
    result = capability.execute(
        "research.retrieve.run",
        {
            "query": "latest iphone price",
            "use_external_rag_runtime": True,
            "constraints": {"max_docs": 1, "max_total_chars": 3000, "allow_replan": False},
        },
        {"capability_registry": registry},
    )
    assert result.get("ok") is True
    assert result.get("status") in {"success", "partial"}
    providers = {
        str(ev.get("provider") or "")
        for ev in (result.get("evidence") or [])
        if isinstance(ev, dict)
    }
    assert "brave_search" in providers


def test_research_retrieve_supports_grouped_control_plane_defaults():
    capability = ResearchRetrieveCapability(
        kernel=None,
        config={
            "use_external_rag_runtime": True,
            "defaults": {
                "execution": {"max_docs": 1, "max_total_chars": 3000},
                "control_plane": {
                    "overrides": {"web_search": {"disabled": True}},
                    "scorecard": {"web_search": {"runtime_health": 0.2}},
                },
            },
        },
    )
    result = capability.execute(
        "research.retrieve.run",
        {
            "query": "latest iphone price",
            "use_external_rag_runtime": True,
            "constraints": {"allow_replan": False},
        },
        {"capability_registry": _FakeRegistry(mode="success")},
    )
    assert result.get("ok") is True
    traces = result.get("traces") if isinstance(result.get("traces"), dict) else {}
    plan = traces.get("plan_trace") if isinstance(traces.get("plan_trace"), dict) else {}
    scorecard = plan.get("provider_runtime_scorecard") if isinstance(plan.get("provider_runtime_scorecard"), dict) else {}
    assert "web_search" in scorecard
    assert bool(scorecard.get("web_search", {}).get("disabled")) is True


def test_research_retrieve_prefers_modular_provider_over_web_search_when_enabled():
    offers = [
        {
            "capability_id": "web_search",
            "domains": ["web"],
            "actions": ["web.search.discover"],
            "quality": {"trust_tier": "public_api"},
            "routing_hints": {"preferred_intents": ["structured_fact", "general_knowledge"]},
        },
        {
            "capability_id": "brave_search",
            "domains": ["web"],
            "actions": ["brave.search.query"],
            "quality": {"trust_tier": "public_api"},
            "routing_hints": {"preferred_intents": ["structured_fact", "general_knowledge"]},
        },
    ]
    registry = _FakeRegistry(mode="success", offers=offers)
    capability = ResearchRetrieveCapability(kernel=None, config={})
    result = capability.execute(
        "research.retrieve.run",
        {
            "query": "latest iphone price",
            "use_external_rag_runtime": True,
            "constraints": {"max_docs": 1, "max_total_chars": 3000, "allow_replan": False},
        },
        {"capability_registry": registry},
    )
    assert result.get("ok") is True
    providers = {
        str(ev.get("provider") or "")
        for ev in (result.get("evidence") or [])
        if isinstance(ev, dict)
    }
    assert "brave_search" in providers
    assert "web_search" not in providers
    trace = result.get("traces") if isinstance(result.get("traces"), dict) else {}
    offer_trace = trace.get("offer_selection_trace") if isinstance(trace.get("offer_selection_trace"), dict) else {}
    dropped = offer_trace.get("dropped") if isinstance(offer_trace.get("dropped"), list) else []
    assert any(
        isinstance(item, dict)
        and item.get("capability_id") == "web_search"
        and item.get("reason") == "prefer_modular_providers"
        for item in dropped
    )


def test_research_retrieve_can_disable_modular_preference():
    offers = [
        {
            "capability_id": "web_search",
            "domains": ["web"],
            "actions": ["web.search.discover"],
            "quality": {"trust_tier": "public_api"},
            "routing_hints": {"preferred_intents": ["structured_fact", "general_knowledge"]},
        },
        {
            "capability_id": "brave_search",
            "domains": ["web"],
            "actions": ["brave.search.query"],
            "quality": {"trust_tier": "public_api"},
            "routing_hints": {"preferred_intents": ["structured_fact", "general_knowledge"]},
        },
    ]
    registry = _FakeRegistry(mode="success", offers=offers)
    capability = ResearchRetrieveCapability(kernel=None, config={})
    result = capability.execute(
        "research.retrieve.run",
        {
            "query": "latest iphone price",
            "use_external_rag_runtime": True,
            "constraints": {
                "max_docs": 1,
                "max_total_chars": 3000,
                "allow_replan": False,
                "prefer_modular_providers": False,
            },
        },
        {"capability_registry": registry},
    )
    assert result.get("ok") is True
    providers = {
        str(ev.get("provider") or "")
        for ev in (result.get("evidence") or [])
        if isinstance(ev, dict)
    }
    assert "web_search" in providers
    trace = result.get("traces") if isinstance(result.get("traces"), dict) else {}
    offer_trace = trace.get("offer_selection_trace") if isinstance(trace.get("offer_selection_trace"), dict) else {}
    dropped = offer_trace.get("dropped") if isinstance(offer_trace.get("dropped"), list) else []
    assert not dropped


def test_research_retrieve_does_not_try_default_providers_when_offer_index_is_empty():
    registry = _FakeRegistry(mode="success", offers=[])
    capability = ResearchRetrieveCapability(kernel=None, config={})
    result = capability.execute(
        "research.retrieve.run",
        {
            "query": "latest iphone price",
            "use_external_rag_runtime": True,
            "constraints": {"allow_replan": False},
        },
        {"capability_registry": registry},
    )
    assert result.get("ok") is True
    assert result.get("status") == "empty_with_reason"
    trace = result.get("traces") if isinstance(result.get("traces"), dict) else {}
    execution = trace.get("execution_trace") if isinstance(trace.get("execution_trace"), list) else []
    providers = {str(item.get("provider") or "") for item in execution if isinstance(item, dict)}
    assert "web" not in providers
    assert "wikipedia_search" not in providers
    assert "youtube" not in providers
