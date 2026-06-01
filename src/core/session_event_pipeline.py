import copy
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

from config.manager import ConfigManager

MESSAGE_EVENT_TYPES = {
    "user_message.created",
    "message_added",
    "message.persisted",
    "assistant_stream.started",
    "assistant_message.created",
}

STREAM_EVENT_TYPES = {
    "assistant_chunk",
    "final_message_chunk",
    "assistant_stream.started",
    "stream",
}

STATUS_EVENT_TYPES = {
    "status",
    "system_metrics",
    "system_health",
}

SESSION_EVENT_TYPES = {
    "session_updated",
}

WORKER_EVENT_TYPES = {
    "worker_state",
    "worker.updated",
}

REASONING_EVENT_TYPES = {
    "thought",
    "cognitive_thought",
    "assistant_thought",
    "reasoning_chunk",
}


def _is_mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _pick_first(*values):
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def _normalize_target(value: Any) -> Optional[str]:
    target = str(value or "").strip()
    return target or None


class SessionEventPipeline:
    """
    Canonical session event pipeline for normalization and durable append-only
    session event logging.
    """

    def __init__(self, session, base_data_dir: Optional[str] = None):
        self.session = session
        self.session_id = str(getattr(session, "session_id", "") or "").strip()
        if not self.session_id:
            raise ValueError("SessionEventPipeline requires a session with a session_id.")

        self.base_data_dir = os.path.abspath(base_data_dir or getattr(ConfigManager(), "base_data_dir", ConfigManager.get_data_dir()))
        self.sessions_dir = os.path.join(self.base_data_dir, "sessions")
        self.session_dir = os.path.join(self.sessions_dir, self.session_id)
        self.events_path = os.path.join(self.session_dir, "events.jsonl")
        self._lock = threading.Lock()

        os.makedirs(self.session_dir, exist_ok=True)

    def _category_for(self, event_type: str, target: Optional[str] = None) -> str:
        event_type = str(event_type or "").strip()
        target = _normalize_target(target)

        if not event_type:
            return "unknown"
        if target == "legacy":
            return "legacy"
        if event_type.startswith("visual.") or event_type == "weg_scene_reset":
            return "visual"
        if event_type.startswith("card."):
            return "card"
        if event_type.startswith("artifact."):
            return "artifact"
        if event_type.startswith("media."):
            return "media"
        if event_type == "complete":
            return "completion"
        if event_type == "assistant_response":
            return "completion"
        if event_type in STREAM_EVENT_TYPES:
            return "stream"
        if event_type in MESSAGE_EVENT_TYPES:
            return "message"
        if event_type in STATUS_EVENT_TYPES:
            return "status"
        if event_type in SESSION_EVENT_TYPES:
            return "session"
        if event_type in WORKER_EVENT_TYPES:
            return "worker"
        if event_type in REASONING_EVENT_TYPES:
            return "reasoning"
        return "unknown"

    def _coerce_timestamp(self, value: Any) -> Any:
        if value not in (None, "", []):
            return value
        return time.time()

    def normalize_event(self, raw_event: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raw = copy.deepcopy(raw_event) if _is_mapping(raw_event) else {}
        defaults = copy.deepcopy(defaults) if _is_mapping(defaults) else {}
        payload = copy.deepcopy(
            _pick_first(raw.get("payload"), raw.get("data"), raw.get("message"), defaults.get("payload"), defaults.get("data"))
        )
        if payload is None:
            payload = {}

        event_type = _pick_first(raw.get("event_type"), raw.get("type"), defaults.get("event_type"), defaults.get("type"))
        event_type = str(event_type or "").strip() or "unknown"
        event_type = str(event_type)

        type_value = _pick_first(raw.get("type"), defaults.get("type"), event_type)
        type_value = str(type_value or event_type).strip() or event_type

        target = _normalize_target(_pick_first(raw.get("target"), defaults.get("target"), payload.get("target") if _is_mapping(payload) else None))
        category = self._category_for(event_type, target)

        event = {
            "event_id": str(_pick_first(raw.get("event_id"), defaults.get("event_id")) or uuid.uuid4()),
            "event_type": event_type,
            "type": type_value,
            "session_id": str(_pick_first(raw.get("session_id"), defaults.get("session_id"), getattr(self.session, "session_id", "")) or "").strip() or self.session_id,
            "timestamp": self._coerce_timestamp(_pick_first(raw.get("timestamp"), defaults.get("timestamp"), payload.get("timestamp") if _is_mapping(payload) else None)),
            "category": category,
            "payload": payload,
            "raw": raw,
        }

        for field in (
            "turn_id",
            "message_id",
            "reply_to_message_id",
            "stream_id",
            "work_id",
            "sequence",
            "target",
            "channel",
            "interface",
            "source",
        ):
            value = _pick_first(
                raw.get(field),
                defaults.get(field),
                payload.get(field) if _is_mapping(payload) else None,
            )
            if value not in (None, "", []):
                event[field] = value

        if target and "target" not in event:
            event["target"] = target

        return event

    def append_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self.normalize_event(event) if "event_id" not in event or "event_type" not in event else copy.deepcopy(event)
        os.makedirs(self.session_dir, exist_ok=True)
        line = json.dumps(normalized, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.events_path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.write("\n")
        return normalized
