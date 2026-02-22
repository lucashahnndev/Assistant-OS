import json
from pathlib import Path
from types import SimpleNamespace

from skills.browser_automator.skill import BrowserAutomatorSkill
from skills.deezer_search.skill import DeezerSearchSkill
from skills.maps_search.skill import MapsSearchSkill
from skills.memory_management.skill import MemorySkill
from skills.reflex_skill.skill import ReflexSkill
from skills.shell_control.skill import ShellSkill
from skills.spotify_search.skill import SpotifySearchSkill
from skills.system_apps.skill import SystemAppsSkill
from skills.system_control.skill import SystemSkill
from skills.system_logs.skill import SystemLogsSkill
from skills.vision.skill import VisionSkill
from skills.weather_control.skill import WeatherSkill
from skills.web_search.skill import WebSearchSkill
from skills.wikipedia_search.skill import WikipediaSearchSkill
from skills.youtube_search.skill import YouTubeSearchSkill
from skills.loader import SkillLoader
from skills.registry import SkillRegistry


def test_shell_execute_returns_structured_success():
    skill = ShellSkill(kernel=None, config={})
    result = skill.execute("shell.control.execute", {"command": "echo hello"}, {})
    assert isinstance(result, dict)
    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


def test_browser_open_query_converts_to_search_url():
    captured = {}

    class FakeBrowserDriver:
        def navigate(self, url, session_id=None):
            captured["url"] = url
            return f"Navigated to {url}"

    skill = BrowserAutomatorSkill(kernel=None, config={})
    result = skill.execute(
        "browser.automator.open",
        {"query": "capital da frança"},
        {"browser_driver": FakeBrowserDriver(), "session_id": "s1"},
    )
    assert result["ok"] is True
    assert captured["url"].startswith("https://www.google.com/search?q=")
    assert "capital+da+fran%C3%A7a" in captured["url"]


def test_web_search_returns_structured_payload(monkeypatch):
    skill = WebSearchSkill(kernel=None, config={})
    monkeypatch.setattr(
        skill,
        "_ddg_search",
        lambda query, limit=5: [
            {
                "rank": 1,
                "title": "Paris",
                "snippet": "Capital da França",
                "url": "https://pt.wikipedia.org/wiki/Paris",
                "source": "duckduckgo",
            }
        ],
    )
    result = skill.execute("web.search.discover", {"query": "capital da França", "limit": 1}, {})
    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["best"]["title"] == "Paris"


def test_web_search_knowledge_mode_returns_docs_and_chunks(monkeypatch):
    skill = WebSearchSkill(kernel=None, config={})
    monkeypatch.setattr(
        skill,
        "_ddg_search",
        lambda query, limit=5: [
            {
                "rank": 1,
                "title": "Ada Lovelace",
                "snippet": "Pioneira da computação.",
                "url": "https://example.org/ada",
                "source": "duckduckgo",
            }
        ],
    )
    monkeypatch.setattr(
        skill,
        "_extract_page_content",
        lambda url, max_chars_per_doc: {
            "ok": True,
            "title": "Ada Lovelace - Artigo",
            "content": "Ada Lovelace foi uma matemática e escritora inglesa conhecida por seu trabalho com Charles Babbage.",
        },
    )

    result = skill.execute(
        "web.search.discover",
        {"query": "quem foi ada lovelace", "mode": "knowledge", "knowledge_limit": 1},
        {},
    )
    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["mode"] == "knowledge"
    assert result["count"] == 1
    assert len(result["knowledge_docs"]) == 1
    assert len(result["chunks"]) >= 1


def test_web_search_missing_query_keeps_structured_error():
    skill = WebSearchSkill(kernel=None, config={})
    result = skill.execute("web.search.discover", {}, {})
    assert result["ok"] is False
    assert result["status"] == "error"
    assert result["error"] == "MISSING_QUERY"
    assert result["mode"] in {"links", "knowledge", "auto"}


def test_wikipedia_search_returns_structured_payload(monkeypatch):
    skill = WikipediaSearchSkill(kernel=None, config={})
    monkeypatch.setattr(
        skill,
        "_search_titles",
        lambda query, language, limit: [
            {"title": "Python"},
        ],
    )
    monkeypatch.setattr(
        skill,
        "_fetch_pages",
        lambda titles, language: [
            {
                "title": "Python",
                "extract": "Python é uma linguagem de programação interpretada.",
                "fullurl": "https://pt.wikipedia.org/wiki/Python",
            }
        ],
    )
    result = skill.execute("wikipedia.search", {"query": "Python"}, {})
    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["provider"] == "wikipedia"
    assert result["count"] == 1
    assert result["best"]["title"] == "Python"
    assert len(result["chunks"]) >= 1


def test_youtube_search_uses_web_fallback_without_api_key(monkeypatch):
    skill = YouTubeSearchSkill(kernel=None, config={})
    monkeypatch.setattr(skill, "_get_api_key", lambda: None)
    monkeypatch.setattr(
        skill,
        "_fallback_search_web",
        lambda query, limit, search_type: [
            {
                "videoId": "abc123",
                "playlistId": None,
                "channelId": None,
                "url": "https://www.youtube.com/watch?v=abc123",
                "title": "Test Video",
                "channel": "Test",
                "descriptionSnippet": "snippet",
                "confidenceScore": 0.55,
                "matchReason": "Web fallback result",
                "source": "duckduckgo_fallback",
            }
        ],
    )
    result = skill.execute("youtube.search.find", {"query": "test"}, {})
    assert result["ok"] is True
    assert result["fallback"] is True
    assert result["provider"] == "youtube_fallback_web"
    assert result["count"] == 1


def test_spotify_search_uses_web_fallback_without_credentials(monkeypatch):
    skill = SpotifySearchSkill(kernel=None, config={})
    monkeypatch.setattr(skill, "_get_auth_config", lambda: {"client_id": None, "client_secret": None})
    monkeypatch.setattr(
        skill,
        "_fallback_search_web",
        lambda query, limit, search_type: [
            {
                "id": "id1",
                "url": "https://open.spotify.com/track/id1",
                "title": "Track 1",
                "artist": None,
                "album": None,
                "confidenceScore": 0.55,
                "matchReason": "Web fallback result",
                "descriptionSnippet": "snippet",
                "source": "duckduckgo_fallback",
            }
        ],
    )
    result = skill.execute("spotify.search.search", {"query": "track test", "type": "track"}, {})
    assert result["ok"] is True
    assert result["fallback"] is True
    assert result["provider"] == "spotify_fallback_web"
    assert result["count"] == 1


def test_deezer_search_rejects_invalid_type():
    skill = DeezerSearchSkill(kernel=None, config={})
    result = skill.execute("deezer.search.search", {"query": "abc", "type": "invalid"}, {})
    assert result["ok"] is False
    assert result["error"] == "INVALID_TYPE"


def test_weather_forecast_action_available(monkeypatch):
    skill = WeatherSkill(kernel=None, config={"api_key": "test-key"})
    monkeypatch.setattr(skill, "_resolve_location", lambda params, context: {"city": "Sao Paulo", "lat": None, "lon": None})
    monkeypatch.setattr(
        skill,
        "_get_openweather_forecast",
        lambda api_key, city, lat, lon, days: {
            "ok": True,
            "status": "success",
            "provider": "openweather",
            "location": city,
            "days": days,
            "forecast": [{"date": "2026-02-22", "temp_min": 20, "temp_max": 28, "description": "céu limpo"}],
            "text": "Previsão mock",
        },
    )
    result = skill.execute("weather.control.forecast", {"days": 2}, {})
    assert result["ok"] is True
    assert result["provider"] == "openweather"
    assert result["days"] == 2


def test_maps_search_builds_city_query_from_category(monkeypatch):
    skill = MapsSearchSkill(kernel=None, config={})
    monkeypatch.setattr(skill, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(skill, "_resolve_location_bias", lambda api_key, near, city, context: None)
    captured = {}

    def fake_search(api_key, query, location_bias, radius, place_type, open_now):
        captured["query"] = query
        return {
            "ok": True,
            "status": "success",
            "places": [
                {
                    "rank": 1,
                    "name": "Restaurante X",
                    "address": "Rua A, 10",
                    "placeId": "pid1",
                    "rating": 4.8,
                    "user_ratings_total": 100,
                    "types": ["restaurant"],
                    "open_now": True,
                    "confidenceScore": 0.9,
                }
            ],
        }

    monkeypatch.setattr(skill, "_search_google_places", fake_search)
    result = skill.execute("maps.search.search", {"category": "restaurantes", "city": "Porto Alegre"}, {})
    assert result["ok"] is True
    assert "restaurantes em Porto Alegre" in captured["query"]
    assert result["count"] == 1


def test_maps_search_diverse_mode_executes_variants_and_deduplicates(monkeypatch):
    skill = MapsSearchSkill(kernel=None, config={})
    monkeypatch.setattr(skill, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(skill, "_resolve_location_bias", lambda api_key, near, city, context: None)

    def fake_search(api_key, query, location_bias, radius, place_type, open_now):
        if "melhores" in query:
            return {
                "ok": True,
                "status": "success",
                "places": [{"rank": 1, "name": "Lugar B", "address": "B", "placeId": "pidB", "rating": 4.9}],
            }
        return {
            "ok": True,
            "status": "success",
            "places": [
                {"rank": 1, "name": "Lugar A", "address": "A", "placeId": "pidA", "rating": 4.7},
                {"rank": 2, "name": "Lugar B", "address": "B", "placeId": "pidB", "rating": 4.9},
            ],
        }

    monkeypatch.setattr(skill, "_search_google_places", fake_search)
    result = skill.execute(
        "maps.search.search",
        {"category": "restaurantes", "city": "Curitiba", "mode": "diverse", "max_variants": 3},
        {},
    )
    assert result["ok"] is True
    assert result["mode"] == "diverse"
    assert len(result["queries_executed"]) >= 2
    assert result["count"] == 2
    assert result["best"]["placeId"] in {"pidA", "pidB"}


def test_memory_skill_returns_structured_store_and_recall():
    class DummyMemoryService:
        def __init__(self):
            self.data = []

        def add_fact(self, category, content):
            self.data.append({"category": category, "content": content})

        def search_memory(self, query):
            return [item for item in self.data if query.lower() in item["content"].lower()]

    memory_service = DummyMemoryService()
    kernel = SimpleNamespace(orchestrator=SimpleNamespace(memory_service=memory_service))
    skill = MemorySkill(kernel=kernel, config={})

    store = skill.execute("memory.store", {"category": "profile", "content": "Nome: Lucas"}, {})
    recall = skill.execute("memory.recall", {"query": "Lucas"}, {})

    assert store["ok"] is True
    assert recall["ok"] is True
    assert recall["count"] == 1


def test_system_logs_returns_structured_list():
    skill = SystemLogsSkill(kernel=None, config={})
    skill._contract = {"context_map": {"assistant.log": "Main log"}}
    result = skill.execute("system_logs.list", {}, {})
    assert result["ok"] is True
    assert isinstance(result["logs"], list)


def test_system_apps_missing_program_name_is_structured_error():
    skill = SystemAppsSkill(kernel=None, config={})
    result = skill.execute("system.apps.open", {}, {})
    assert result["ok"] is False
    assert result["error"] == "MISSING_PROGRAM_NAME"


def test_system_apps_find_alias_map_success():
    skill = SystemAppsSkill(kernel=None, config={})
    result = skill.execute("system.apps.find", {"program_name": "youtube"}, {})
    assert result["ok"] is True
    assert result["found"] is True
    assert result["source"] == "alias_map"


def test_system_control_time_returns_structured_payload():
    skill = SystemSkill(kernel=None, config={})
    result = skill.execute("system.control.time", {}, {})
    assert result["ok"] is True
    assert result["status"] == "success"
    assert "Current time is" in result["text"]


def test_system_control_ping_requires_host():
    class DummySystemDriver:
        def net_ping(self, host, count):
            return f"ping {host} {count}"

    skill = SystemSkill(kernel=SimpleNamespace(system_driver=DummySystemDriver()), config={})
    result = skill.execute("system.control.network.ping", {}, {})
    assert result["ok"] is False
    assert result["error"] == "MISSING_HOST"


def test_reflex_skill_delegates_to_system_control_registry():
    class DummyRegistry:
        def get_skill_for_action(self, action_id):
            return object() if action_id == "system.control.status" else None

        def dispatch(self, action_id, params, context):
            return {"ok": True, "status": "success", "text": "delegated"}

    skill = ReflexSkill(kernel=SimpleNamespace(skill_registry=DummyRegistry()), config={})
    result = skill.execute("reflex.status", {}, {})
    assert result["ok"] is True
    assert result["legacy_alias"] == "reflex"


def test_reflex_rules_live_in_system_control():
    reflex = ReflexSkill(kernel=None, config={})
    system = SystemSkill(kernel=None, config={})
    assert reflex.get_reflex_rules() == []
    rules = system.get_reflex_rules()
    action_ids = {r["action_id"] for r in rules}
    assert "system.control.status" in action_ids
    assert "system.control.cancel" in action_ids


def test_vision_requires_image_path_with_structured_error():
    class DummyLLM:
        def analyze_image(self, path, prompt):
            return {"text": "ok"}

    kernel = SimpleNamespace(llm_manager=DummyLLM(), workspace_service=None, orchestrator=None)
    skill = VisionSkill(kernel=kernel, config={})
    result = skill.execute("vision.analyze", {"prompt": "teste"}, {})
    assert result["ok"] is False
    assert result["error"] == "MISSING_IMAGE_PATH"


def test_contract_actions_match_loaded_registry():
    class DummyCfg:
        def get(self, key, default=None):
            if key == "skills":
                return {}
            return default if default is not None else {}

    registry = SkillRegistry()
    loader = SkillLoader(registry=registry, kernel=None, config_manager=DummyCfg())
    loader.load_from_directory("src/skills")
    loaded = set(registry.list_actions())

    contract_actions = set()
    for contract_path in sorted(Path("src/skills").glob("*/contract.json")):
        contract = json.loads(contract_path.read_text())
        namespace = str(contract.get("name", contract_path.parent.name)).lower().replace(" ", ".")
        actions = contract.get("actions", [])
        if isinstance(actions, list):
            for entry in actions:
                if not isinstance(entry, dict):
                    continue
                action_id = entry.get("id") or f"{namespace}.{entry.get('name') or entry.get('handler')}"
                if action_id:
                    contract_actions.add(action_id)
        elif isinstance(actions, dict):
            for action_key, action_data in actions.items():
                action_id = action_data.get("id") if isinstance(action_data, dict) else None
                contract_actions.add(action_id or f"{namespace}.{action_key}")

    assert contract_actions == loaded
