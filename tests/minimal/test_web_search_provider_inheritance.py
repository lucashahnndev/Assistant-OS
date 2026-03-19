import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.capabilities.web.search import WebSearchCapability


class _FakeConfigManager:
    def __init__(self, values):
        self._values = values

    def get_capability_config(self, capability_name):
        return self._values.get(capability_name, {})


class _FakeKernel:
    def __init__(self, values):
        self.config_manager = _FakeConfigManager(values)


def test_web_search_infers_provider_configs_from_dedicated_capabilities():
    kernel = _FakeKernel(
        {
            "brave_search": {
                "provider": {"enabled": True, "api_key": "ENV_BRAVE_API_KEY", "api_base": "https://api.search.brave.com/res/v1/web/search"},
                "defaults": {"timeout_ms": 9000, "retries": 2},
            },
            "ddg_search": {"provider": {"enabled": True}},
            "searxng_search": {
                "provider": {"enabled": True, "endpoints": ["https://searx.be"], "engines": ["google"], "timeout_ms": 7000, "retries": 1}
            },
            "openalex_search": {
                "provider": {"enabled": True, "api_base": "https://api.openalex.org", "timeout_ms": 6000, "retries": 1}
            },
            "commoncrawl_search": {
                "provider": {
                    "enabled": True,
                    "collinfo_url": "https://index.commoncrawl.org/collinfo.json",
                    "max_indexes": 3,
                },
                "defaults": {"timeout_ms": 6100, "retries": 2},
            },
        }
    )
    capability = WebSearchCapability(kernel=kernel, config={"search_router": {"inherit_provider_capabilities": True}})
    router_cfg = capability._router_config()
    providers = router_cfg.get("providers") if isinstance(router_cfg.get("providers"), dict) else {}

    assert providers.get("brave", {}).get("enabled") is True
    assert providers.get("brave", {}).get("api_key") == "ENV_BRAVE_API_KEY"
    assert providers.get("ddg", {}).get("enabled") is True
    assert providers.get("searxng", {}).get("endpoints") == ["https://searx.be"]
    assert providers.get("openalex", {}).get("enabled") is True
    assert providers.get("commoncrawl", {}).get("enabled") is True
    assert providers.get("commoncrawl", {}).get("max_indexes") == 3


def test_web_search_explicit_router_provider_values_override_inferred_values():
    kernel = _FakeKernel({"ddg_search": {"provider": {"enabled": False}}})
    capability = WebSearchCapability(
        kernel=kernel,
        config={
            "search_router": {
                "inherit_provider_capabilities": True,
                "providers": {"ddg": {"enabled": True}},
            }
        },
    )

    router_cfg = capability._router_config()
    providers = router_cfg.get("providers") if isinstance(router_cfg.get("providers"), dict) else {}
    assert providers.get("ddg", {}).get("enabled") is True
