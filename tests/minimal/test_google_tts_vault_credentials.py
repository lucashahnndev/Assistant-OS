from __future__ import annotations

import os
from types import SimpleNamespace

from services.tts.providers import google as google_tts


def test_google_tts_uses_api_key_without_env_global(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

    fake_tts = SimpleNamespace(
        TextToSpeechClient=FakeClient,
        SsmlVoiceGender=SimpleNamespace(MALE="MALE", FEMALE="FEMALE", NEUTRAL="NEUTRAL"),
        AudioEncoding=SimpleNamespace(MP3="MP3", OGG_OPUS="OGG_OPUS", LINEAR16="LINEAR16"),
    )
    fake_client_options = SimpleNamespace(ClientOptions=lambda api_key=None: {"api_key": api_key})

    monkeypatch.setattr(google_tts, "texttospeech", fake_tts)
    monkeypatch.setattr(google_tts, "resolve_secret_ref", lambda value: "resolved-api-key" if value else "")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "google.api_core.client_options", fake_client_options)

    provider = google_tts.GoogleCloudProvider({"secret_ref": "ENV_GOOGLE_CLOUD_API_KEY"})

    assert provider.is_available() is True
    assert calls
    assert getattr(calls[0]["client_options"], "api_key", None) == "resolved-api-key"
    assert os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") is None


def test_google_tts_uses_explicit_service_account_credentials_without_env_global(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

    fake_tts = SimpleNamespace(
        TextToSpeechClient=FakeClient,
        SsmlVoiceGender=SimpleNamespace(MALE="MALE", FEMALE="FEMALE", NEUTRAL="NEUTRAL"),
        AudioEncoding=SimpleNamespace(MP3="MP3", OGG_OPUS="OGG_OPUS", LINEAR16="LINEAR16"),
    )
    fake_service_account = SimpleNamespace(
        Credentials=SimpleNamespace(
            from_service_account_file=lambda path: {"loaded_from": path}
        )
    )

    def fake_resolve(value):
        if value == "ENV_GOOGLE_CREDS":
            return "/tmp/fake-google-creds.json"
        return ""

    monkeypatch.setattr(google_tts, "texttospeech", fake_tts)
    monkeypatch.setattr(google_tts, "service_account", fake_service_account)
    monkeypatch.setattr(google_tts, "resolve_secret_ref", fake_resolve)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    provider = google_tts.GoogleCloudProvider({"credentials_path": "ENV_GOOGLE_CREDS"})

    assert provider.is_available() is True
    assert calls
    assert calls[0]["credentials"] == {"loaded_from": "/tmp/fake-google-creds.json"}
    assert os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") is None
