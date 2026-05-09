import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.capabilities.base import CapabilityBase
from src.capabilities.contract_v1 import load_contract_v1
from src.capabilities.registry import CapabilityRegistry


class _DummyCapability(CapabilityBase):
    def __init__(self, capability_name: str, action_ids: list[str], config: dict | None = None):
        self._name = capability_name
        self._actions = action_ids
        self.config = config or {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def actions(self):
        return self._actions

    def execute(self, action_id, params, context):
        _ = action_id, params, context
        return {"ok": True, "status": "success", "provider": self._name}


def _load_contract(cap_folder: str):
    return load_contract_v1(str(ROOT / "src" / "capabilities" / cap_folder / "contract.json"))


def test_contract_v1_parses_retrieval_profile_fields():
    contract = _load_contract("web")
    assert contract.retrieval_profile is not None
    assert contract.retrieval_profile.enabled is True
    assert "search" in (contract.retrieval_profile.roles or [])
    assert "web" in (contract.retrieval_profile.domains or [])


def test_contract_v1_parses_discoverability_profile_fields():
    contract = _load_contract("calendar")
    assert contract.discoverability_profile is not None
    assert contract.discoverability_profile.enabled is True
    assert "agenda" in (contract.discoverability_profile.domains or [])
    assert "agenda" in (contract.discoverability_profile.keywords or [])


def test_all_capability_contracts_expose_discoverability_profiles():
    contracts = sorted((ROOT / "src" / "capabilities").glob("*/contract.json"))
    assert contracts, "expected capability contracts to exist"
    for contract_path in contracts:
        contract = load_contract_v1(str(contract_path))
        assert contract.discoverability_profile is not None, contract_path.name
        assert contract.discoverability_profile.enabled is True, contract_path.name


def test_capability_registry_indexes_and_filters_retrieval_offers():
    registry = CapabilityRegistry()

    for folder in ("web", "wikipedia_search", "youtube", "research_retrieve"):
        contract = _load_contract(folder)
        cap = _DummyCapability(contract.capability.id, [action.id for action in contract.actions])
        registry.register(cap, contract)

    all_offers = registry.list_retrieval_offers()
    assert len(all_offers) >= 4

    encyclopedia = registry.list_retrieval_offers(domain="encyclopedia")
    ids = {row.get("capability_id") for row in encyclopedia}
    assert "wikipedia_search" in ids

    media_for_intent = registry.list_retrieval_offers(intent="media_lookup", domain="media")
    media_ids = {row.get("capability_id") for row in media_for_intent}
    assert "youtube" in media_ids

    policy_avoided = registry.list_retrieval_offers(intent="policy_lookup", domain="media")
    policy_ids = {row.get("capability_id") for row in policy_avoided}
    assert "youtube" not in policy_ids


def test_capability_registry_indexes_external_provider_capabilities():
    registry = CapabilityRegistry()
    folders = ("brave_search", "ddg_search", "searxng_search", "openalex_search", "commoncrawl_search")
    for folder in folders:
        contract = _load_contract(folder)
        cap = _DummyCapability(contract.capability.id, [action.id for action in contract.actions])
        registry.register(cap, contract)

    all_ids = {row.get("capability_id") for row in registry.list_retrieval_offers()}
    assert {"brave_search", "ddg_search", "searxng_search", "openalex_search", "commoncrawl_search"}.issubset(all_ids)

    academic = registry.list_retrieval_offers(intent="academic_lookup", domain="academic")
    academic_ids = {row.get("capability_id") for row in academic}
    assert "openalex_search" in academic_ids


def test_capability_registry_indexes_music_retrieval_offers():
    registry = CapabilityRegistry()
    for folder in ("spotify_search", "deezer_search"):
        contract = _load_contract(folder)
        cap = _DummyCapability(contract.capability.id, [action.id for action in contract.actions])
        registry.register(cap, contract)

    music = registry.list_retrieval_offers(intent="music_lookup", domain="music")
    music_ids = {row.get("capability_id") for row in music}
    assert "spotify_search" in music_ids
    assert "deezer_search" in music_ids


def test_capability_registry_indexes_location_retrieval_offers():
    registry = CapabilityRegistry()
    contract = _load_contract("maps_search")
    cap = _DummyCapability(contract.capability.id, [action.id for action in contract.actions], config={"apiKey": "ENV_MAPS_KEY"})
    registry.register(cap, contract)

    rows = registry.list_retrieval_offers(intent="location_lookup", domain="location")
    ids = {row.get("capability_id") for row in rows}
    assert "maps_search" in ids


def test_capability_registry_indexes_discoverability_offers_for_calendar_capabilities():
    registry = CapabilityRegistry()
    for folder in ("calendar", "google_calendar"):
        contract = _load_contract(folder)
        cap = _DummyCapability(contract.capability.id, [action.id for action in contract.actions])
        registry.register(cap, contract)

    rows = registry.list_discovery_offers(domain="agenda")
    ids = {row.get("capability_id") for row in rows}
    assert "calendar" in ids
    assert "google_calendar" not in ids


def test_capability_registry_indexes_google_calendar_for_sync_related_discovery():
    registry = CapabilityRegistry()
    for folder in ("calendar", "google_calendar"):
        contract = _load_contract(folder)
        cap = _DummyCapability(contract.capability.id, [action.id for action in contract.actions])
        registry.register(cap, contract)

    rows = registry.list_discovery_offers(domain="sync")
    ids = {row.get("capability_id") for row in rows}
    assert "google_calendar" in ids


def test_retrieval_offer_excludes_disabled_capability():
    registry = CapabilityRegistry()
    contract = _load_contract("youtube")
    cap = _DummyCapability(contract.capability.id, [action.id for action in contract.actions], config={"enabled": False})
    registry.register(cap, contract)
    rows = registry.list_retrieval_offers(intent="music_lookup", domain="music")
    ids = {row.get("capability_id") for row in rows}
    assert "youtube" not in ids


def test_retrieval_offer_exposes_setup_readiness_from_capability_config():
    registry = CapabilityRegistry()
    contract = _load_contract("brave_search")

    cap_missing = _DummyCapability(contract.capability.id, [action.id for action in contract.actions], config={})
    registry.register(cap_missing, contract)
    offers = registry.list_retrieval_offers()
    brave_offer = next((row for row in offers if row.get("capability_id") == "brave_search"), {})
    assert brave_offer.get("setup_ready") is False
    assert "provider.api_key" in (brave_offer.get("missing_required_fields") or [])

    cap_ready = _DummyCapability(
        contract.capability.id,
        [action.id for action in contract.actions],
        config={"provider": {"api_key": "secret_ref:test"}},
    )
    registry.register(cap_ready, contract)
    offers = registry.list_retrieval_offers()
    brave_offer = next((row for row in offers if row.get("capability_id") == "brave_search"), {})
    assert brave_offer.get("setup_ready") is True
    assert brave_offer.get("missing_required_fields") == []


def test_retrieval_offer_refreshes_after_live_capability_config_change():
    registry = CapabilityRegistry()
    contract = _load_contract("brave_search")
    cap = _DummyCapability(contract.capability.id, [action.id for action in contract.actions], config={})
    registry.register(cap, contract)

    first = next((row for row in registry.list_retrieval_offers() if row.get("capability_id") == "brave_search"), {})
    assert first.get("setup_ready") is False
    assert "provider.api_key" in (first.get("missing_required_fields") or [])

    cap.config = {"provider": {"api_key": "ENV_BRAVE_API_KEY"}}
    second = next((row for row in registry.list_retrieval_offers() if row.get("capability_id") == "brave_search"), {})
    assert second.get("setup_ready") is True
    assert second.get("missing_required_fields") == []
