import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.services.external_rag import ExternalRAGPlanner, ExternalRAGRuntime, ProviderSpec


def test_external_rag_planner_builds_minimum_retrieval_plan():
    planner = ExternalRAGPlanner()
    providers = [
        ProviderSpec(id="web.search", domains=("web",), trust_tier="high"),
        ProviderSpec(id="wikipedia.search", domains=("encyclopedia", "web"), trust_tier="high"),
        ProviderSpec(id="youtube.search", domains=("video", "web"), trust_tier="medium"),
    ]

    plan, decisions = planner.build_plan(
        query="latest iphone price",
        constraints={"max_providers": 2, "max_fallback_depth": 2},
        providers=providers,
    )

    assert plan.intent == "structured_fact"
    assert plan.query_id
    assert plan.plan_steps
    assert len(plan.selected_providers) >= 1
    assert len(decisions) == 3
    assert all(item.provider for item in decisions)


def test_external_rag_planner_classifies_music_lookup():
    planner = ExternalRAGPlanner()
    intent, subintent = planner.classify_intent("spotify playlist para foco")
    assert intent == "music_lookup"
    assert subintent == "catalog_search"


def test_external_rag_runtime_emits_traces_and_success_payload():
    def fake_dispatch(action_id, params):
        if action_id == "web.search.discover":
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
                "text_md": "This is a factual page about the query.",
                "chunks": [{"id": "c1", "text": "This is a factual page about the query."}],
                "status_code": 200,
            }
        if action_id == "wikipedia.search":
            return {
                "ok": True,
                "results": [
                    {
                        "url": "https://wikipedia.org/wiki/Retrieval-augmented_generation",
                        "title": "Retrieval-augmented generation",
                        "content": "RAG is a method that combines retrieval with generation.",
                        "excerpt": "RAG combines retrieval and generation.",
                    }
                ],
            }
        if action_id == "youtube.search.find":
            return {"ok": True, "results": []}
        return {"ok": False, "error_code": "UNKNOWN"}

    runtime = ExternalRAGRuntime(
        dispatch=fake_dispatch,
        pick_urls=lambda goal, results, max_links_to_open: (["https://example.com/a"], []),
        synthesize=lambda goal, docs, evidence, language_hint: "Synthesized answer",
    )

    result, docs = runtime.run(
        query="what is retrieval plan",
        constraints={"max_docs": 2, "max_total_chars": 4000},
        language_hint="en",
    )

    payload = result.to_payload()
    assert result.status == "success"
    assert payload["answer_md"] == "Synthesized answer"
    assert docs
    assert "plan_trace" in payload["traces"]
    assert "execution_trace" in payload["traces"]
    assert "merge_trace" in payload["traces"]


def test_external_rag_planner_respects_provider_runtime_overrides():
    planner = ExternalRAGPlanner()
    providers = [
        ProviderSpec(id="web.search", domains=("web",), trust_tier="high"),
        ProviderSpec(id="wikipedia.search", domains=("encyclopedia", "web"), trust_tier="high"),
        ProviderSpec(id="youtube.search", domains=("video", "web"), trust_tier="medium"),
    ]
    constraints = {
        "max_providers": 2,
        "provider_runtime_overrides": {
            "web.search": {"disabled": True},
            "wikipedia.search": {"quota_exceeded": True},
            "youtube.search": {"force_fallback": True},
        },
    }
    plan, decisions = planner.build_plan(query="what is retrieval plan", constraints=constraints, providers=providers)

    assert plan.selected_providers == []
    assert plan.provider_runtime_scorecard["web.search"]["disabled"] is True
    by_provider = {item.provider: item for item in decisions}
    assert by_provider["web.search"].reason == "disabled"
    assert by_provider["wikipedia.search"].reason == "quota_exceeded"
    assert by_provider["youtube.search"].reason == "force_fallback"


def test_external_rag_runtime_includes_runtime_scorecard_in_plan_trace():
    def fake_dispatch(action_id, params):
        if action_id == "web.search.discover":
            return {"ok": True, "results": []}
        if action_id == "wikipedia.search":
            return {"ok": True, "results": []}
        if action_id == "youtube.search.find":
            return {"ok": True, "results": []}
        return {"ok": False, "error_code": "UNKNOWN"}

    runtime = ExternalRAGRuntime(
        dispatch=fake_dispatch,
        pick_urls=lambda goal, results, max_links_to_open: ([], []),
        synthesize=lambda goal, docs, evidence, language_hint: "n/a",
    )
    result, _ = runtime.run(
        query="latest news about ai",
        constraints={
            "provider_runtime_overrides": {"web.search": {"degraded": True}},
            "provider_runtime_scorecard": {"web.search": {"runtime_health": 0.4, "success_rate": 0.3, "latency_ms": 2400}},
        },
        language_hint="en",
    )
    payload = result.to_payload()
    scorecard = payload["traces"]["plan_trace"]["provider_runtime_scorecard"]
    assert "web.search" in scorecard
    assert scorecard["web.search"]["degraded"] is True
    assert scorecard["web.search"]["runtime_health"] == 0.4


def test_external_rag_runtime_triggers_explicit_replan_trace_when_initial_plan_fails():
    def fake_dispatch(action_id, params):
        if action_id in {"web.search.discover", "wikipedia.search", "youtube.search.find"}:
            return {"ok": True, "results": []}
        return {"ok": False, "error_code": "UNKNOWN"}

    runtime = ExternalRAGRuntime(
        dispatch=fake_dispatch,
        pick_urls=lambda goal, results, max_links_to_open: ([], []),
        synthesize=lambda goal, docs, evidence, language_hint: "n/a",
    )
    result, _ = runtime.run(
        query="find updates and a video about this topic",
        constraints={"allow_replan": True, "max_providers": 1, "max_fallback_depth": 1},
        language_hint="en",
    )
    payload = result.to_payload()
    assert payload["status"] == "empty_with_reason"
    assert payload["traces"]["replan_trace"]
    assert payload["traces"]["merge_trace"]["fallback_layer"] == "exhausted"


def test_external_rag_runtime_retries_retryable_provider_error():
    calls = {"web_search": 0}

    def fake_dispatch(action_id, params):
        if action_id == "web.search.discover":
            calls["web_search"] += 1
            if calls["web_search"] == 1:
                return {"ok": False, "error_code": "TEMP", "retryable": True, "status_code": 503}
            return {"ok": True, "results": [{"url": "https://example.com/a", "title": "A", "snippet": "ok"}]}
        if action_id == "web.retrieve.read":
            return {
                "ok": True,
                "url": "https://example.com/a",
                "canonical_url": "https://example.com/a",
                "title": "A",
                "text_md": "Recovered after retry.",
                "chunks": [{"id": "c1", "text": "Recovered after retry."}],
                "status_code": 200,
            }
        if action_id == "wikipedia.search":
            return {"ok": True, "results": []}
        if action_id == "youtube.search.find":
            return {"ok": True, "results": []}
        return {"ok": False, "error_code": "UNKNOWN"}

    runtime = ExternalRAGRuntime(
        dispatch=fake_dispatch,
        pick_urls=lambda goal, results, max_links_to_open: (["https://example.com/a"], []),
        synthesize=lambda goal, docs, evidence, language_hint: "Synthesized answer",
    )
    result, _ = runtime.run(
        query="what is retry",
        constraints={"max_retries": 1, "max_docs": 1, "retry_backoff_base_ms": 1, "retry_backoff_jitter_ms": 0},
        language_hint="en",
    )
    payload = result.to_payload()
    assert payload["status"] == "success"
    assert calls["web_search"] == 2
    assert any("web.search.discover retry" in w for w in payload["warnings"])
    assert any("web.search.discover backoff" in w for w in payload["warnings"])


def test_external_rag_runtime_uses_internal_knowledge_fallback_layer():
    def fake_dispatch(action_id, params):
        if action_id in {"web.search.discover", "wikipedia.search", "youtube.search.find"}:
            return {"ok": True, "results": []}
        return {"ok": False, "error_code": "UNKNOWN"}

    runtime = ExternalRAGRuntime(
        dispatch=fake_dispatch,
        pick_urls=lambda goal, results, max_links_to_open: ([], []),
        synthesize=lambda goal, docs, evidence, language_hint: "n/a",
    )
    result, _ = runtime.run(
        query="how do we run onboarding",
        constraints={
            "allow_replan": False,
            "internal_knowledge_fallback": [
                {"title": "Onboarding policy", "content": "Use checklist A then B.", "source": "policy.internal"}
            ],
        },
        language_hint="en",
    )
    payload = result.to_payload()
    assert payload["status"] == "partial"
    assert payload["traces"]["merge_trace"]["fallback_layer"] == "internal_knowledge"
    assert "Internal knowledge fallback" in payload["answer_md"]


def test_external_rag_runtime_respects_global_provider_attempt_limit():
    def fake_dispatch(action_id, params):
        if action_id in {"web.search.discover", "wikipedia.search", "youtube.search.find"}:
            return {"ok": True, "results": []}
        return {"ok": False, "error_code": "UNKNOWN"}

    runtime = ExternalRAGRuntime(
        dispatch=fake_dispatch,
        pick_urls=lambda goal, results, max_links_to_open: ([], []),
        synthesize=lambda goal, docs, evidence, language_hint: "n/a",
    )
    result, _ = runtime.run(
        query="find updates and videos",
        constraints={"allow_replan": True, "max_provider_attempts_global": 1},
        language_hint="en",
    )
    payload = result.to_payload()
    reasons = [ev.get("reason") for ev in payload["traces"]["execution_trace"] if isinstance(ev, dict)]
    assert "provider_attempt_limit_global" in reasons


def test_external_rag_runtime_builds_provider_specs_from_offers():
    offers = [
        {
            "capability_id": "web",
            "domains": ["web", "academic"],
            "actions": ["web.search.discover"],
            "quality": {"trust_tier": "public_api"},
        },
        {
            "capability_id": "wikipedia_search",
            "domains": ["encyclopedia"],
            "actions": ["wikipedia.search"],
            "quality": {"trust_tier": "curated"},
        },
        {
            "capability_id": "research_retrieve",
            "domains": ["web"],
            "actions": ["research.retrieve.run"],
            "quality": {"trust_tier": "curated"},
        },
    ]
    specs = ExternalRAGRuntime.provider_specs_from_offers(offers)
    ids = {spec.id for spec in specs}
    assert "web" in ids
    assert "wikipedia_search" in ids
    assert "research_retrieve" not in ids
    web_spec = next(spec for spec in specs if spec.id == "web")
    assert web_spec.strategy == "search_then_read"
    assert web_spec.action_id == "web.search.discover"


def test_external_rag_runtime_provider_specs_respect_setup_ready_offer_flag():
    offers = [
        {
            "capability_id": "brave_search",
            "domains": ["web"],
            "actions": ["brave.search.query"],
            "quality": {"trust_tier": "public_api"},
            "setup_ready": False,
        }
    ]
    specs = ExternalRAGRuntime.provider_specs_from_offers(offers)
    assert len(specs) == 1
    assert specs[0].id == "brave_search"
    assert specs[0].setup_ready is False


def test_external_rag_runtime_empty_override_does_not_fallback_to_default_specs():
    calls = {"dispatch": 0}

    def fake_dispatch(action_id, params):
        _ = action_id, params
        calls["dispatch"] += 1
        return {"ok": True, "results": []}

    runtime = ExternalRAGRuntime(
        dispatch=fake_dispatch,
        pick_urls=lambda goal, results, max_links_to_open: ([], []),
        synthesize=lambda goal, docs, evidence, language_hint: "n/a",
        provider_specs=[],
    )
    result, _ = runtime.run(
        query="latest updates",
        constraints={"allow_replan": False},
        language_hint="en",
    )
    payload = result.to_payload()
    assert payload["status"] == "empty_with_reason"
    assert calls["dispatch"] == 0
