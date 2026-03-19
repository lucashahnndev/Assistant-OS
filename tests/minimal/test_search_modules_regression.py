from capabilities.shared.search_providers.commoncrawl_provider import CommonCrawlCdxProvider
from capabilities.shared.search_providers.base import SearchRequest
from capabilities.shared.search_providers.base import SearchResultItem
from capabilities.shared.search_providers.ddg_provider import DdgProvider
from capabilities.shared.search_providers.openalex_provider import OpenAlexProvider
from capabilities.shared.search_providers.router import SearchRouter
from capabilities.youtube import search as youtube_capability_module
from capabilities.youtube.search import YouTubeSearchCapability


class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeCommonCrawlClient:
    def get(self, url, params=None):
        if "collinfo.json" in url:
            return _FakeResponse(
                status_code=200,
                payload=[
                    {"id": "CC-MAIN-2099-99", "cdx-api": "https://index.commoncrawl.org/future-index"},
                    {"id": "CC-MAIN-2025-51", "cdx-api": "https://index.commoncrawl.org/live-index"},
                ],
            )
        if "future-index" in url:
            return _FakeResponse(status_code=404, payload={})
        if "live-index" in url:
            return _FakeResponse(status_code=200, payload={})
        return _FakeResponse(status_code=500, payload={})


def test_commoncrawl_skips_unavailable_indexes():
    provider = CommonCrawlCdxProvider(max_indexes=1)
    indexes = provider._load_indexes(_FakeCommonCrawlClient())
    assert indexes == ["https://index.commoncrawl.org/live-index"]


class _FakeDDGS:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def videos(self, query, max_results=10, timeout=4):
        _ = (query, max_results, timeout)
        return iter(
            [
                {
                    "title": "Video Teste",
                    "content": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "uploader": "Canal Teste",
                    "description": "Descricao teste",
                }
            ]
        )

    def text(self, query, max_results=10, timeout=4):
        _ = (query, max_results, timeout)
        return iter([])


def test_youtube_fallback_uses_video_search_results(monkeypatch):
    monkeypatch.setattr(youtube_capability_module, "DDGS", _FakeDDGS)
    capability = YouTubeSearchCapability(config={})
    results = capability._fallback_search_web("never gonna give you up", limit=3, search_type="video")
    assert len(results) == 1
    assert results[0]["videoId"] == "dQw4w9WgXcQ"
    assert results[0]["source"] == "duckduckgo_videos_fallback"


def test_openalex_skips_non_academic_queries():
    provider = OpenAlexProvider(enabled=True)
    request = SearchRequest(
        query="melhores cafeterias em porto alegre",
        limit=5,
        recency_days=0,
        domains_allow=[],
        domains_deny=[],
        language="pt-BR",
        country="BR",
        location={"city": "Porto Alegre", "country": "BR"},
    )
    response = provider.search(request)
    assert response.results == []
    assert "PROVIDER_SKIPPED:openalex:non_academic_query" in response.warnings


def test_router_location_match_helper():
    item = SearchResultItem(
        title="Melhores cafeterias em Porto Alegre",
        url="https://exemplo.com/porto-alegre/cafeterias",
        snippet="Guia local da cidade",
        source="x",
        provider="x",
    )
    assert SearchRouter._item_matches_location(item, city="Porto Alegre", country="Brasil") is True
    assert SearchRouter._contains_location_token("cafeterias em porto alegre", "Porto Alegre") is True


def test_router_strict_location_keeps_only_city_matches():
    router = SearchRouter({"strict_location_when_query_mentions_city": True})
    # Inject synthetic provider outputs directly through helpers.
    match = SearchResultItem(
        title="Cafeterias em Porto Alegre",
        url="https://example.com/porto-alegre/cafe",
        snippet="guia local",
        source="x",
        provider="ddg",
    )
    miss = SearchResultItem(
        title="Cafeterias em São Paulo",
        url="https://example.com/sao-paulo/cafe",
        snippet="guia local",
        source="x",
        provider="ddg",
    )
    assert router._item_matches_location(match, city="Porto Alegre", country="BR")
    assert not router._item_matches_location(miss, city="Porto Alegre", country="BR")


def test_router_geo_bias_only_for_location_sensitive_queries():
    loc = {"city": "Austin", "country": "US"}
    assert SearchRouter._apply_geo_bias("python asyncio tutorial", location=loc) == "python asyncio tutorial"
    biased = SearchRouter._apply_geo_bias("cafeterias em porto alegre", location={"city": "Porto Alegre", "country": "BR"})
    assert "porto alegre" in biased.lower()


class _FakeDDGSTextOnly:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def text(self, query, max_results=5, **kwargs):
        _ = (query, max_results, kwargs)
        return iter(
            [
                {
                    "title": "如何系统地自学 Python？ - 知乎",
                    "href": "https://www.zhihu.com/question/123",
                    "body": "中文内容",
                },
                {
                    "title": "Python asyncio tutorial",
                    "href": "https://realpython.com/async-io-python/",
                    "body": "A practical tutorial",
                },
            ]
        )


def test_ddg_filters_obvious_language_mismatch(monkeypatch):
    from capabilities.shared.search_providers import ddg_provider as ddg_mod

    monkeypatch.setattr(ddg_mod, "DDGS", _FakeDDGSTextOnly)
    provider = DdgProvider(enabled=True)
    req = SearchRequest(
        query="python asyncio tutorial",
        limit=5,
        recency_days=0,
        domains_allow=[],
        domains_deny=[],
        language="en-US",
        country="US",
        location=None,
    )
    resp = provider.search(req)
    assert len(resp.results) == 1
    assert "realpython" in resp.results[0].url
