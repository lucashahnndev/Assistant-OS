from __future__ import annotations

import requests

from capabilities.shared.link_validation import validate_media_link, validate_media_results


class _FakeResponse:
    def __init__(self, status_code: int, url: str):
        self.status_code = status_code
        self.url = url


def _fake_request(method, url, **kwargs):
    _ = (method, kwargs)
    if "broken" in url:
        return _FakeResponse(404, url)
    if "restricted" in url:
        return _FakeResponse(403, url)
    if "valid" in url:
        return _FakeResponse(200, url)
    raise requests.RequestException("network error")


def test_validate_media_link_marks_broken_and_valid(monkeypatch):
    monkeypatch.setattr("capabilities.shared.link_validation.requests.request", _fake_request)

    broken = validate_media_link("https://example.com/broken")
    valid = validate_media_link("https://example.com/valid")

    assert broken.ok is False
    assert broken.status == "broken"
    assert valid.ok is True
    assert valid.status == "valid"


def test_validate_media_link_marks_restricted_as_inconclusive(monkeypatch):
    monkeypatch.setattr("capabilities.shared.link_validation.requests.request", _fake_request)

    restricted = validate_media_link("https://example.com/restricted")

    assert restricted.ok is False
    assert restricted.status == "restricted"
    assert "Acesso restrito" in restricted.reason


def test_validate_media_results_prefers_first_valid_candidate(monkeypatch):
    monkeypatch.setattr("capabilities.shared.link_validation.requests.request", _fake_request)

    result = validate_media_results(
        [
            {"title": "Broken", "url": "https://example.com/broken"},
            {"title": "Valid", "url": "https://example.com/valid"},
        ]
    )

    assert result["best"]["title"] == "Valid"
    assert result["results"][0]["link_validation"]["status"] == "broken"
    assert result["results"][1]["link_validation"]["status"] == "valid"
