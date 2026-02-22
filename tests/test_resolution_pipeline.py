from core.intent import AgentIntent
from core.resolution.chain_resolver import FallbackChainResolver
from core.resolution.llm_resolver import LLMResolver
from core.resolution.semantic_resolver import SemanticResolver
from core.session import Session
from skills.base import SkillBase
from skills.registry import SkillRegistry


class DummyLLMManager:
    def __init__(self, intent: AgentIntent):
        self._intent = intent

    def generate_intent(self, user_input, history, system_prompt, attachments=None):
        return self._intent


class DummySkill(SkillBase):
    def __init__(self, name: str, namespace: str, actions: list[str], contract: dict | None = None):
        self._name = name
        self._namespace = namespace
        self._actions = actions
        self._contract = contract or {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def actions(self) -> list[str]:
        return self._actions

    def execute(self, action_id, params, context):
        return {"ok": True}


def _registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(
        DummySkill(
            name="web_search",
            namespace="web.search",
            actions=["discover"],
            contract={
                "actions": {
                    "discover": {
                        "description": "Searches the web for a given query",
                        "risk_level": "low",
                    }
                }
            },
        )
    )
    registry.register(
        DummySkill(
            name="system_control",
            namespace="system.control",
            actions=["time", "power"],
            contract={
                "actions": [
                    {"id": "system.control.time", "name": "time", "description": "Current system time"},
                    {
                        "id": "system.control.power",
                        "name": "power",
                        "description": "Shutdown or reboot the machine",
                        "risk_level": "high",
                    },
                ]
            },
        )
    )
    registry.register(
        DummySkill(
            name="weather_control",
            namespace="weather.control",
            actions=["get"],
            contract={
                "actions": {"get": {"description": "Get current weather by city or coordinates"}}
            },
        )
    )
    registry.register(
        DummySkill(
            name="wikipedia_search",
            namespace="wikipedia",
            actions=["search"],
            contract={
                "actions": {
                    "search": {
                        "description": "Searches Wikipedia by topic",
                        "risk_level": "low",
                    }
                }
            },
        )
    )
    return registry


def _context(session: Session, registry: SkillRegistry, allowed_actions: list[str] | None = None) -> dict:
    return {
        "session": session,
        "system_prompt": "system",
        "history": [],
        "allowed_actions": allowed_actions,
        "skill_registry": registry,
    }


def test_llm_resolver_accepts_registered_allowed_action():
    registry = _registry()
    session = Session("resolver-ok")
    intent = AgentIntent(
        thought="Need to search",
        action="web.search.discover",
        params={"query": "python asyncio"},
        response_text="",
    )
    resolver = LLMResolver(DummyLLMManager(intent), threshold=0.65, skill_registry=registry)

    plan = resolver.resolve("pesquise asyncio", _context(session, registry, ["web.search.discover"]))

    assert plan is not None
    assert plan.action_id == "web.search.discover"
    assert plan.confidence >= 0.65


def test_llm_resolver_rejects_action_outside_allowed_scope():
    registry = _registry()
    session = Session("resolver-deny")
    intent = AgentIntent(
        thought="Power action requested",
        action="system.control.power",
        params={"command": "shutdown"},
        response_text="",
    )
    resolver = LLMResolver(DummyLLMManager(intent), threshold=0.65, skill_registry=registry)

    plan = resolver.resolve("desliga", _context(session, registry, ["web.search.discover"]))

    assert plan is None


def test_llm_resolver_accepts_reply_with_text():
    registry = _registry()
    session = Session("resolver-reply")
    intent = AgentIntent(
        thought="Simple response",
        action="reply",
        params={},
        response_text="Olá, em que posso ajudar?",
    )
    resolver = LLMResolver(DummyLLMManager(intent), threshold=0.65, skill_registry=registry)

    plan = resolver.resolve("oi", _context(session, registry))

    assert plan is not None
    assert plan.action_id == "reply"


def test_semantic_resolver_matches_search_rule_when_allowed():
    registry = _registry()
    resolver = SemanticResolver(threshold=0.92, skill_registry=registry)
    plan = resolver.resolve(
        "pesquise sobre energia solar",
        {"allowed_actions": ["web.search.discover"], "skill_registry": registry},
    )

    assert plan is not None
    assert plan.action_id == "web.search.discover"
    assert "query" in plan.args


def test_semantic_resolver_prefers_wikipedia_for_explicit_intent():
    registry = _registry()
    resolver = SemanticResolver(threshold=0.92, skill_registry=registry)
    plan = resolver.resolve(
        "pesquise na wikipedia sobre energia solar",
        {"allowed_actions": ["wikipedia.search", "web.search.discover"], "skill_registry": registry},
    )

    assert plan is not None
    assert plan.action_id == "wikipedia.search"
    assert plan.args.get("query")


def test_semantic_resolver_generic_search_stays_on_web_search():
    registry = _registry()
    resolver = SemanticResolver(threshold=0.92, skill_registry=registry)
    plan = resolver.resolve(
        "pesquise sobre energia solar",
        {"allowed_actions": ["wikipedia.search", "web.search.discover"], "skill_registry": registry},
    )

    assert plan is not None
    assert plan.action_id == "web.search.discover"


def test_semantic_resolver_respects_allowed_scope():
    registry = _registry()
    resolver = SemanticResolver(threshold=0.92, skill_registry=registry)
    plan = resolver.resolve(
        "pesquise sobre energia solar",
        {"allowed_actions": ["system.control.time"], "skill_registry": registry},
    )

    assert plan is None


def test_semantic_resolver_extracts_weather_city():
    registry = _registry()
    resolver = SemanticResolver(threshold=0.92, skill_registry=registry)
    plan = resolver.resolve(
        "qual a previsão do tempo em Porto Alegre",
        {"allowed_actions": ["weather.control.get"], "skill_registry": registry},
    )

    assert plan is not None
    assert plan.action_id == "weather.control.get"
    assert plan.args.get("city") == "Porto Alegre"


def test_fallback_chain_uses_semantic_when_llm_confidence_is_rejected():
    registry = _registry()
    session = Session("resolver-chain")

    # LLM returns an out-of-scope action => confidence should fall below threshold.
    llm_intent = AgentIntent(
        thought="Attempting privileged action",
        action="system.control.power",
        params={"command": "shutdown"},
        response_text="",
    )
    llm = LLMResolver(DummyLLMManager(llm_intent), threshold=0.65, skill_registry=registry)
    semantic = SemanticResolver(threshold=0.92, skill_registry=registry)
    chain = FallbackChainResolver([llm, semantic])

    ctx = _context(session, registry, allowed_actions=["web.search.discover"])
    plan = chain.resolve("pesquise sobre python assíncrono", ctx)

    assert plan is not None
    assert plan.source == "semantic"
    assert plan.action_id == "web.search.discover"
