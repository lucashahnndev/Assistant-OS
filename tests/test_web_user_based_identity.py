from types import SimpleNamespace
from unittest.mock import MagicMock

from drivers.server_driver import ServerDriver
from server.routes import sessions as sessions_routes


def test_server_driver_extract_identity_from_cookie_uses_uid(monkeypatch):
    monkeypatch.setattr(
        "drivers.server_driver.decode_access_token",
        lambda token: {"uid": 42, "sub": "admin"},
    )
    sender_id, sender_name = ServerDriver._extract_identity_from_cookie(
        "access_token=Bearer%20dummy-jwt", "web-abc123"
    )

    # Cookie parser decodes quoted values; encoded space support varies by client.
    # We only care that decoded payload drives user-based sender id.
    assert sender_id == "user_42"
    assert sender_name == "admin"


def test_server_driver_extract_identity_from_cookie_fallbacks_to_session(monkeypatch):
    monkeypatch.setattr("drivers.server_driver.decode_access_token", lambda token: None)
    sender_id, sender_name = ServerDriver._extract_identity_from_cookie("", "web-xyz999")
    assert sender_id == "web-xyz999"
    assert sender_name is None


def test_sessions_send_message_uses_user_based_principal_and_payload():
    mock_kernel = SimpleNamespace()
    mock_kernel.process_input = MagicMock()
    mock_kernel.drivers = [SimpleNamespace(app=True)]

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(kernel=mock_kernel)))
    user = SimpleNamespace(id=7, username="admin", display_name="Admin")

    payload = {
        "message": "teste",
        "attachments": [{"name": "a.txt"}],
        "user_data": {"location": {"latitude": 1, "longitude": 2}},
    }
    result = sessions_routes.send_message("web-123", payload, request, user)

    assert result["status"] == "sent"
    assert mock_kernel.process_input.call_count == 1

    kwargs = mock_kernel.process_input.call_args.kwargs
    context = kwargs["context"]
    assert context.sender_id == "user_7"
    assert context.sender_name == "Admin"
    assert context.session_id == "web-123"
    assert kwargs["attachments"] == payload["attachments"]
    assert kwargs["user_data"]["location"]["latitude"] == 1
    assert kwargs["user_data"]["user_name"] == "Admin"
