from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.capabilities.assistive_overlay.capability import AssistiveOverlayCapability
from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability
from src.capabilities.calendar.runtime import CalendarCapability
from src.capabilities.notifications.capability import NotificationCapability
from src.capabilities.shared.error_contract import error_envelope, success_envelope
from src.capabilities.shared.provider_search_capability import ProviderSearchCapabilityBase
from src.capabilities.shared.search_providers.base import SearchProvider, SearchResponse, SearchResultItem
from src.capabilities.system_logs.capability import SystemLogsCapability
from src.capabilities.task_management.capability import TaskCapability


def test_shared_error_contract_exposes_standard_fields():
    payload = success_envelope(
        provider="demo",
        elapsed=12,
        result_summary="Done.",
        structured_result={"value": 7},
        freshness={"status": "current"},
    )

    assert payload["ok"] is True
    assert payload["success"] is True
    assert payload["status"] == "success"
    assert payload["result_summary"] == "Done."
    assert payload["structured_result"] == {"value": 7}
    assert payload["artifacts"] == []
    assert payload["attachment_delivery"]["status"] == "none"
    assert payload["freshness"]["status"] == "current"
    assert payload["requires_followup"] is False
    assert payload["diagnostics"] == {}

    err = error_envelope(
        provider="demo",
        error_code="BROKEN",
        error_message="Broken.",
        retryable=False,
        elapsed=1,
        diagnostics={"parse_status": "invalid_json"},
    )
    assert err["ok"] is False
    assert err["success"] is False
    assert err["status"] == "error"
    assert err["reason"] == "BROKEN"
    assert err["result_summary"] == "Broken."
    assert err["diagnostics"]["parse_status"] == "invalid_json"


class _EmptySearchProvider(SearchProvider):
    name = "empty"

    def search(self, request):
        _ = request
        return SearchResponse(results=[], warnings=["cached"])


class _SearchCapability(ProviderSearchCapabilityBase):
    CAPABILITY_NAME = "demo_search"
    ACTION_HANDLER = "query"
    PROVIDER_LABEL = "demo_search"

    def _build_provider(self):
        return _EmptySearchProvider()


def test_provider_search_capability_marks_empty_result_as_followup():
    capability = _SearchCapability(kernel=None, config={})
    result = capability.execute("query", {"query": "climate"}, {})

    assert result["ok"] is True
    assert result["success"] is True
    assert result["status"] == "empty"
    assert result["result_summary"] == "No results found for 'climate'."
    assert result["structured_result"]["count"] == 0
    assert result["requires_followup"] is True
    assert result["next_step_context"]["suggestion"]
    assert result["freshness"]["status"] == "empty"
    assert result["diagnostics"]["parse_status"] == "ok"


def test_calendar_list_and_missing_fields_use_operational_envelope():
    class _Event:
        def __init__(self, idx: int):
            self.short_id = f"ev-{idx}"
            self.title = f"Event {idx}"
            self.start_time = 1_700_000_000 + idx
            self.end_time = self.start_time + 3600
            self.source = "internal"
            self.description = "desc"
            self.location = "room"
            self.status = "confirmed"
            self.timezone = "UTC"
            self.reminders = []
            self.event_id = f"event-{idx}"

    class _CalendarService:
        def list_events(self, user_id, start_time=None, end_time=None):
            _ = (user_id, start_time, end_time)
            return [_Event(1)]

        def create_event(self, **kwargs):
            _ = kwargs
            return _Event(2), False

        def get_event(self, event_ref):
            _ = event_ref
            return None

        def delete_event(self, event_ref):
            _ = event_ref
            return False

        def resolve_event_ref(self, event_ref):
            return None

        def sync_all(self, user_id):
            _ = user_id
            return False

    kernel = SimpleNamespace(orchestrator=SimpleNamespace(calendar_service=_CalendarService()))
    capability = CalendarCapability(kernel=kernel, config={})

    listed = capability.execute("calendar.event.list", {}, {})
    assert listed["ok"] is True
    assert listed["success"] is True
    assert listed["status"] == "success"
    assert listed["structured_result"]["operation"] == "search_events"
    assert listed["structured_result"]["confirmed"] is True

    created = capability.execute(
        "calendar.event.create",
        {"title": "Meet", "start_time": "2026-06-11T10:00:00Z", "end_time": "2026-06-11T11:00:00Z"},
        {},
    )
    assert created["ok"] is False
    assert created["status"] == "partial"
    assert created["requires_followup"] is True
    assert created["structured_result"]["operation"] == "create_event"
    assert created["freshness"]["source"] == "live"


def test_browser_run_and_step_return_partial_when_objective_not_confirmed():
    browser = object.__new__(BrowserControlCapability)
    browser._resolve_intent_class = lambda raw: "automacao_ui"
    browser._contains_platform_hint = lambda text: False
    browser._run_sync = lambda coro: {"ok": True, "status": "partial", "result": {"status": "partial", "confirmed": False, "result_summary": "Opened page", "final_url": "https://example.com", "title": "Example", "steps_completed": [], "steps_failed": [], "observations": [], "truncated": False}, "execution_context": {"browser_instance_id": "b1"}}

    run_result = browser.execute("browser.control.run", {"goal": "open example", "intent_class": "automacao_ui"}, {"user_input": "open example"})
    assert run_result["ok"] is False
    assert run_result["status"] == "partial"
    assert run_result["requires_followup"] is True
    assert run_result["structured_result"]["confirmed"] is False

    browser._run_sync = lambda coro: {"ok": True, "status": "partial", "result": {"status": "partial", "confirmed": False, "result_summary": "Clicked once", "final_url": "https://example.com", "title": "Example", "steps_completed": ["step1"], "steps_failed": [], "observations": [], "truncated": False}, "execution_context": {"browser_instance_id": "b1"}}
    browser._runtime = object()
    browser._subagent = object()
    browser._runtime_intent_class = "automacao_ui"
    browser._maybe_run_registry_gc = lambda ctx: {"ok": True}
    browser._ensure_attached_to_registered_tab = lambda: True
    browser._recover_target_binding = lambda: {"ok": True}
    browser._ensure_registry_instance = lambda ctx, intent_class: "inst-1"
    browser._sync_registry_tab = lambda: "tab-1"
    browser._acquire_instance_execution_lock = lambda instance_id, ctx: {"ok": True}
    browser._acquire_tab_execution_lock = lambda instance_id, tab_id, ctx: {"ok": True}
    browser._release_tab_execution_lock = lambda instance_id, tab_id, ctx: {"ok": True}
    browser._release_instance_execution_lock = lambda instance_id, ctx: {"ok": True}
    browser._apply_runtime_trace_context = lambda ctx: None
    browser._touch_work_context = lambda ctx, patch: None
    browser._current_target_id = lambda: "target-1"
    browser._get_last_vision_observation = lambda: {}
    browser._build_registry_snapshot = lambda ctx: {"count_instances": 1}
    browser._build_result_metadata = lambda policy: {}
    browser._emit_status = lambda callbacks, payload: None
    browser._subagent.run_to_goal = lambda *args, **kwargs: SimpleNamespace(model_dump=lambda mode="json": {"status": "partial", "confirmed": False, "result_summary": "Step incomplete", "final_url": "https://example.com", "title": "Example", "steps_completed": ["step1"], "steps_failed": [], "observations": [], "truncated": False})

    step_result = browser._run_sync(browser.step("continue", context={"session_id": "s1"}))
    assert step_result["ok"] is False
    assert step_result["status"] == "partial"
    assert step_result["requires_followup"] is True



def test_assistive_overlay_contract_exposes_structured_result_and_artifact():
    class _FakeRenderer:
        def draw(self, command_type, payload):
            command = dict(payload)
            command["type"] = command_type
            command.setdefault("id", "overlay-debug")
            return {"ok": True, "backend": "noop", "command": command}

        def clear_by_id(self, _command_id):
            return {"ok": True, "backend": "noop"}

        def clear_all(self):
            return {"ok": True, "backend": "noop", "cleared": 0}

    class _FakeLocator:
        def locate(self, **_kwargs):
            return {
                "ok": True,
                "bbox": {
                    "label": "target",
                    "x": 200,
                    "y": 120,
                    "width": 80,
                    "height": 40,
                    "screen_id": 0,
                },
                "screenshot_path": str(ROOT / "tests" / "minimal" / "fake_overlay.png"),
            }

    capability = AssistiveOverlayCapability(
        kernel=SimpleNamespace(),
        config={"overlay": {"backend": "noop", "debug": {"enabled": True}}},
    )
    capability.renderer = _FakeRenderer()
    capability.locator = _FakeLocator()

    result = capability.execute(
        "overlay.assist.highlight_target",
        {"label": "botao enviar", "mark_type": "rect"},
        {"session_id": "s1"},
    )

    assert result["ok"] is True
    assert result["success"] is True
    assert result["result_summary"].startswith("Target 'botao enviar'")
    assert result["structured_result"]["target"]["label"] == "target"
    assert result["artifacts"]
    assert result["attachment_delivery"]["status"] == "none"
    assert result["diagnostics"]["capability"] == "assistive_overlay"


def test_system_logs_returns_structured_result():
    capability = SystemLogsCapability(kernel=None, config={})
    capability_module = sys.modules[SystemLogsCapability.__module__]

    original_list = getattr(capability_module, "list_log_files")
    original_read = getattr(capability_module, "read_recent_logs")
    try:
        capability_module.list_log_files = lambda: ["assistant.log", "session.log"]
        capability_module.read_recent_logs = lambda n, filename: [f"{filename}:{idx}" for idx in range(1, n + 1)]

        result = capability.execute("list", {}, {})

        assert result["ok"] is True
        assert result["success"] is True
        assert result["result_summary"] == "Listed 2 log file(s)."
        assert result["structured_result"]["count"] == 2
        assert result["structured_result"]["logs"][0]["file"] == "assistant.log"
        assert result["attachment_delivery"]["status"] == "none"
    finally:
        capability_module.list_log_files = original_list
        capability_module.read_recent_logs = original_read


def test_notifications_send_exposes_structured_result_without_text_only_fallback():
    class _Dispatcher:
        def dispatch(self, intent):
            self.intent = intent
            return True

    orchestrator = SimpleNamespace(notification_dispatcher=_Dispatcher())
    capability = NotificationCapability(kernel=SimpleNamespace(orchestrator=orchestrator), config={})

    result = capability.execute(
        "notifications.send",
        {"message": "ping", "title": "Hello", "domain": "system"},
        {},
    )

    assert result["ok"] is True
    assert result["success"] is True
    assert result["status"] == "sent"
    assert result["result_summary"] == "Notification dispatched to delivery layer."
    assert result["structured_result"]["action"] == "notifications.send"
    assert result["diagnostics"]["dispatch_success"] is True


def test_task_capability_error_path_preserves_diagnostics():
    capability = TaskCapability(kernel=SimpleNamespace(orchestrator=SimpleNamespace()), config={})

    result = capability.execute("task.notes", {"command": "read"}, {"session": None})

    assert result["ok"] is False
    assert result["success"] is False
    assert result["status"] == "error"
    assert result["reason"] == "SCRATCHPAD_UNAVAILABLE"
    assert result["result_summary"] == "Scratchpad service is not available."
    assert result["diagnostics"]["capability"] == "task"
