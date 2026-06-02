import copy
import datetime
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

from config.manager import ConfigManager
from utils.event_bus import global_event_bus

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

FEEDBACK_EVENT_TYPES = {
    "feedback",
    "message.feedback.updated",
}

REASONING_EVENT_TYPES = {
    "thought",
    "cognitive_thought",
    "assistant_thought",
    "reasoning_chunk",
}

NON_CHAT_MESSAGE_TYPES = {
    "reasoning",
    "internal_event",
}

MEDIA_EVENT_TYPES = {
    "media.added",
    "media.updated",
    "media.created",
    "media_message",
}

ARTIFACT_EVENT_TYPES = {
    "artifact.created",
    "artifact.updated",
}

CARD_EVENT_TYPES = {
    "card.created",
    "card.updated",
}

WEGENA_EVENT_TYPES = {
    "weg_scene_reset",
    "visual.wegena.scene_reset",
    "visual.wegena.scene_update",
    "visual.wegena.composition_ready",
    "visual.wegena.scene_failed",
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


TERMINAL_STATUS_VALUES = {
    "complete",
    "completed",
    "succeeded",
    "success",
    "done",
    "failed",
    "error",
    "aborted",
    "cancelled",
    "canceled",
}


def _is_terminal_status(value: Any) -> bool:
    return str(value or "").strip().lower() in TERMINAL_STATUS_VALUES


def _timestamp_to_ms(value: Any) -> Optional[int]:
    if value in (None, "", []):
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric >= 1_000_000_000_000:
            return int(numeric)
        return int(numeric * 1000)

    text = str(value).strip()
    if not text:
        return None

    try:
        numeric = float(text)
    except Exception:
        numeric = None

    if numeric is not None:
        if numeric >= 1_000_000_000_000:
            return int(numeric)
        return int(numeric * 1000)

    iso_text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(iso_text)
    except Exception:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return int(parsed.timestamp() * 1000)


def _duration_ms(start_value: Any, end_value: Any) -> Optional[int]:
    start_ms = _timestamp_to_ms(start_value)
    end_ms = _timestamp_to_ms(end_value)
    if start_ms is None or end_ms is None:
        return None
    return max(0, int(end_ms - start_ms))


def is_conversational_chat_message(message: Any) -> bool:
    if not isinstance(message, dict):
        return False

    role = str(message.get("role") or "").strip().lower()
    msg_type = str(message.get("type") or message.get("msg_type") or "").strip().lower()
    if msg_type in NON_CHAT_MESSAGE_TYPES:
        return False
    return role in {"user", "assistant"}


def filter_conversational_chat_history(messages: Any) -> list[Dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    return [copy.deepcopy(msg) for msg in messages if is_conversational_chat_message(msg)]


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

        resolved_data_dir = base_data_dir or ConfigManager.get_data_dir()
        self.base_data_dir = os.path.abspath(resolved_data_dir)
        self.sessions_dir = os.path.join(self.base_data_dir, "sessions")
        self.session_dir = os.path.join(self.sessions_dir, self.session_id)
        self.events_path = os.path.join(self.session_dir, "events.jsonl")
        self.indices_dir = self.session_dir
        self.store = SessionEventStore(self.events_path)
        self.index_writer = SessionEventIndexWriter(self.indices_dir)
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
        if event_type == "assistant_visual_intent":
            return "visual"
        if event_type.startswith("card."):
            return "card"
        if event_type.startswith("artifact."):
            return "artifact"
        if event_type.startswith("media."):
            return "media"
        if event_type in FEEDBACK_EVENT_TYPES or event_type.startswith("message.feedback."):
            return "feedback"
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
        msg_type = str(
            _pick_first(
                raw.get("msg_type"),
                defaults.get("msg_type"),
                payload.get("msg_type") if _is_mapping(payload) else None,
            )
            or ""
        ).strip().lower()
        role = str(
            _pick_first(
                raw.get("role"),
                defaults.get("role"),
                payload.get("role") if _is_mapping(payload) else None,
            )
            or ""
        ).strip().lower()

        event_type = _pick_first(raw.get("event_type"), raw.get("type"), defaults.get("event_type"), defaults.get("type"))
        event_type = str(event_type or "").strip() or "unknown"
        event_type = str(event_type)

        type_value = _pick_first(raw.get("type"), defaults.get("type"), event_type)
        type_value = str(type_value or event_type).strip() or event_type

        target = _normalize_target(_pick_first(raw.get("target"), defaults.get("target"), payload.get("target") if _is_mapping(payload) else None))
        category = self._category_for(event_type, target)
        if category == "message" and (msg_type in NON_CHAT_MESSAGE_TYPES or (role == "system" and msg_type == "reasoning")):
            category = "reasoning"

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
            "msg_type",
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

        preserved_raw_fields = {}
        for key, value in raw.items():
            if key in {
                "payload",
                "data",
                "type",
                "event_type",
                "event_id",
                "session_id",
                "timestamp",
                "target",
                "turn_id",
                "message_id",
                "reply_to_message_id",
                "stream_id",
                "work_id",
                "sequence",
                "msg_type",
                "channel",
                "interface",
                "source",
            }:
                continue
            if key not in event:
                preserved_raw_fields[key] = copy.deepcopy(value)
        if preserved_raw_fields:
            event.update(preserved_raw_fields)

        return event

    def append_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        return self.process_event(event, publish=False)

    def process_event(self, event: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None, publish: bool = False) -> Dict[str, Any]:
        normalized = self.normalize_event(event, defaults=defaults)
        self.store.append(normalized)
        self.index_writer.update(normalized)
        if hasattr(self.session, "event_timeline") and isinstance(getattr(self.session, "event_timeline"), list):
            self.session.event_timeline.append(copy.deepcopy(normalized))
        if publish:
            published = copy.deepcopy(normalized)
            published["_pipeline_recorded"] = True
            global_event_bus.emit_threadsafe(published)
        return normalized


def record_session_event(
    session,
    raw_event: Dict[str, Any],
    defaults: Optional[Dict[str, Any]] = None,
    publish: bool = False,
    base_data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    pipeline = SessionEventPipeline(session, base_data_dir=base_data_dir)
    return pipeline.process_event(raw_event, defaults=defaults, publish=publish)


def _read_json_file(path: str, default: Any):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data
    except Exception:
        return default


def build_session_snapshot(session_id: str, base_data_dir: Optional[str] = None, recent_events_limit: int = 100) -> Dict[str, Any]:
    resolved_data_dir = os.path.abspath(base_data_dir or ConfigManager.get_data_dir())
    session_dir = os.path.join(resolved_data_dir, "sessions", str(session_id))
    events_path = os.path.join(session_dir, "events.jsonl")
    session_path = os.path.join(session_dir, "session.json")
    chat_path = os.path.join(session_dir, "chat.json")

    snapshot = {
        "session_id": str(session_id),
        "session": _read_json_file(session_path, {}),
        "chat": filter_conversational_chat_history(_read_json_file(chat_path, [])),
        "events": [],
        "indices": {},
        "paths": {
            "session": session_path,
            "chat": chat_path,
            "events": events_path,
        },
    }

    if os.path.exists(events_path):
        try:
            with open(events_path, "r", encoding="utf-8") as fh:
                lines = [line.strip() for line in fh if line.strip()]
            recent_lines = lines[-int(recent_events_limit or 0):] if recent_events_limit else lines
            snapshot["events"] = [json.loads(line) for line in recent_lines]
        except Exception:
            snapshot["events"] = []

    index_files = {
        "messages": "messages.index.json",
        "turns": "turns.index.json",
        "streams": "streams.index.json",
        "workers": "workers.index.json",
        "thoughts": "thoughts.index.json",
        "media": "media.index.json",
        "feedback": "feedback.index.json",
        "links": "links.index.json",
        "cards": "cards.index.json",
        "artifacts": "artifacts.index.json",
        "playback": "playback.index.json",
        "wegena": "wegena.index.json",
    }
    for index_name, filename in index_files.items():
        path = os.path.join(session_dir, filename)
        snapshot["indices"][index_name] = _read_json_file(path, {"updated_at": None, "items": {}})
        snapshot["paths"][index_name] = path

    return snapshot


class SessionEventStore:
    def __init__(self, events_path: str):
        self.events_path = os.path.abspath(events_path)
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.events_path), exist_ok=True)

    def append(self, event: Dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.events_path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.write("\n")


class SessionEventIndexWriter:
    def __init__(self, session_dir: str):
        self.session_dir = os.path.abspath(session_dir)
        self._lock = threading.Lock()
        self.paths = {
            "messages": os.path.join(self.session_dir, "messages.index.json"),
            "turns": os.path.join(self.session_dir, "turns.index.json"),
            "streams": os.path.join(self.session_dir, "streams.index.json"),
            "workers": os.path.join(self.session_dir, "workers.index.json"),
            "thoughts": os.path.join(self.session_dir, "thoughts.index.json"),
            "media": os.path.join(self.session_dir, "media.index.json"),
            "feedback": os.path.join(self.session_dir, "feedback.index.json"),
            "links": os.path.join(self.session_dir, "links.index.json"),
            "cards": os.path.join(self.session_dir, "cards.index.json"),
            "artifacts": os.path.join(self.session_dir, "artifacts.index.json"),
            "playback": os.path.join(self.session_dir, "playback.index.json"),
            "wegena": os.path.join(self.session_dir, "wegena.index.json"),
        }
        os.makedirs(self.session_dir, exist_ok=True)

    @staticmethod
    def _initial_index() -> Dict[str, Any]:
        return {"updated_at": time.time(), "items": {}}

    def _load_index(self, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            return self._initial_index()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and isinstance(data.get("items"), dict):
                return data
        except Exception:
            pass
        return self._initial_index()

    def _get_index_record(self, name: str, key: Any) -> Dict[str, Any]:
        if key in (None, "", []):
            return {}
        path = self.paths[name]
        data = self._load_index(path)
        items = data.get("items", {})
        record = items.get(str(key))
        return copy.deepcopy(record) if isinstance(record, dict) else {}

    def _atomic_write_json(self, path: str, data: Dict[str, Any]) -> None:
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
            fh.write("\n")
        os.replace(tmp_path, path)

    def _upsert(self, name: str, key: Optional[str], record: Dict[str, Any]) -> None:
        if not key:
            return
        path = self.paths[name]
        with self._lock:
            data = self._load_index(path)
            items = data.setdefault("items", {})
            items[str(key)] = record
            data["updated_at"] = time.time()
            self._atomic_write_json(path, data)

    def _delete(self, name: str, key: Optional[str]) -> None:
        if not key:
            return
        path = self.paths[name]
        with self._lock:
            data = self._load_index(path)
            items = data.setdefault("items", {})
            if str(key) not in items:
                return
            items.pop(str(key), None)
            data["updated_at"] = time.time()
            self._atomic_write_json(path, data)

    @staticmethod
    def _preview_text(value: Any, limit: int = 120) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text[:limit]

    def _decorate_turn_record(self, turn_record: Dict[str, Any]) -> Dict[str, Any]:
        if not turn_record:
            return turn_record
        turn_record.setdefault("thinking_started_at", turn_record.get("created_at"))
        turn_record["thinking_updated_at"] = turn_record.get("updated_at")
        if turn_record.get("status") == "completed" and not turn_record.get("thinking_completed_at"):
            turn_record["thinking_completed_at"] = turn_record.get("updated_at")
        end_value = turn_record.get("thinking_completed_at") or turn_record.get("updated_at")
        turn_record["thinking_duration_ms"] = _duration_ms(turn_record.get("thinking_started_at"), end_value)
        turn_record["turn_duration_ms"] = _duration_ms(turn_record.get("created_at"), turn_record.get("updated_at"))
        turn_record["is_active"] = not _is_terminal_status(turn_record.get("status"))
        return turn_record

    def _decorate_stream_record(self, stream_record: Dict[str, Any]) -> Dict[str, Any]:
        if not stream_record:
            return stream_record
        stream_record.setdefault("thinking_started_at", stream_record.get("started_at"))
        stream_record["thinking_updated_at"] = stream_record.get("updated_at")
        if stream_record.get("completed_at") and not stream_record.get("thinking_completed_at"):
            stream_record["thinking_completed_at"] = stream_record.get("completed_at")
        end_value = stream_record.get("completed_at") or stream_record.get("updated_at")
        stream_record["stream_duration_ms"] = _duration_ms(stream_record.get("started_at"), end_value)
        stream_record["thinking_duration_ms"] = _duration_ms(stream_record.get("thinking_started_at"), end_value)
        stream_record["is_active"] = not bool(stream_record.get("completed_at")) and not _is_terminal_status(stream_record.get("status"))
        return stream_record

    def _decorate_thought_record(self, thought_record: Dict[str, Any], turn_record: Optional[Dict[str, Any]] = None, stream_record: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not thought_record:
            return thought_record

        turn_record = turn_record or {}
        stream_record = stream_record or {}
        started_at = (
            turn_record.get("thinking_started_at")
            or turn_record.get("created_at")
            or thought_record.get("created_at")
            or thought_record.get("timestamp")
            or thought_record.get("updated_at")
        )
        updated_at = (
            turn_record.get("thinking_updated_at")
            or turn_record.get("updated_at")
            or thought_record.get("updated_at")
            or thought_record.get("timestamp")
        )
        completed_at = (
            turn_record.get("thinking_completed_at")
            or turn_record.get("completed_at")
            or stream_record.get("completed_at")
            or thought_record.get("thinking_completed_at")
        )

        thought_record["thinking_started_at"] = started_at
        thought_record["thinking_updated_at"] = updated_at
        if completed_at:
            thought_record["thinking_completed_at"] = completed_at
        end_value = thought_record.get("thinking_completed_at") or updated_at
        thought_record["thinking_duration_ms"] = _duration_ms(started_at, end_value)
        thought_record["turn_duration_ms"] = turn_record.get("turn_duration_ms")
        thought_record["stream_duration_ms"] = stream_record.get("stream_duration_ms")
        thought_record["is_active"] = bool(turn_record.get("is_active", True)) and not bool(thought_record.get("thinking_completed_at"))
        return thought_record

    def _upsert_turn_record(
        self,
        turn_id: Any,
        session_id: str,
        timestamp: Any,
        *,
        message_id: Optional[str] = None,
        role: Optional[str] = None,
        stream_id: Optional[str] = None,
        work_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        turn_key = str(turn_id or "").strip()
        if not turn_key:
            return

        turn_path = self.paths["turns"]
        with self._lock:
            data = self._load_index(turn_path)
            items = data.setdefault("items", {})
            turn_record = items.get(turn_key, {
                "turn_id": turn_id,
                "session_id": session_id,
                "user_message_id": None,
                "assistant_message_ids": [],
                "stream_ids": [],
                "work_ids": [],
                "message_ids": [],
                "created_at": timestamp,
                "updated_at": timestamp,
                "status": "open",
            })

            if message_id and message_id not in turn_record["message_ids"]:
                turn_record["message_ids"].append(message_id)
            if role == "user" and message_id:
                turn_record["user_message_id"] = message_id
            elif role and role != "user" and message_id:
                if message_id not in turn_record["assistant_message_ids"]:
                    turn_record["assistant_message_ids"].append(message_id)
            if stream_id and stream_id not in turn_record["stream_ids"]:
                turn_record["stream_ids"].append(stream_id)
            if work_id and work_id not in turn_record["work_ids"]:
                turn_record["work_ids"].append(work_id)
            if status:
                turn_record["status"] = status
            turn_record["updated_at"] = timestamp
            turn_record = self._decorate_turn_record(turn_record)
            items[turn_key] = turn_record
            data["updated_at"] = time.time()
            self._atomic_write_json(turn_path, data)

    def _close_thought_records_for_turn(self, turn_id: Any, completed_at: Any, stream_id: Optional[str] = None) -> None:
        turn_key = str(turn_id or "").strip()
        if not turn_key:
            return

        thoughts_path = self.paths["thoughts"]
        turn_record = self._get_index_record("turns", turn_key)
        stream_record = self._get_index_record("streams", stream_id) if stream_id else {}
        with self._lock:
            data = self._load_index(thoughts_path)
            items = data.setdefault("items", {})
            updated = False
            for record in items.values():
                if str(record.get("turn_id") or "").strip() != turn_key:
                    continue
                if stream_id and str(record.get("stream_id") or "").strip() not in {"", str(stream_id)}:
                    continue
                started_at = record.get("thinking_started_at") or record.get("timestamp") or record.get("created_at") or completed_at
                record["thinking_completed_at"] = completed_at
                record["thinking_updated_at"] = completed_at
                record["thinking_duration_ms"] = _duration_ms(started_at, completed_at)
                record["turn_duration_ms"] = _duration_ms(turn_record.get("created_at") or started_at, completed_at)
                if stream_record:
                    record["stream_duration_ms"] = _duration_ms(stream_record.get("started_at") or started_at, completed_at)
                record["is_active"] = False
                record["updated_at"] = completed_at
                updated = True

            if updated:
                data["updated_at"] = time.time()
                self._atomic_write_json(thoughts_path, data)

    def update(self, event: Dict[str, Any]) -> None:
        event_type = str(event.get("event_type") or event.get("type") or "").strip()
        category = str(event.get("category") or "").strip()
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        session_id = str(event.get("session_id") or "").strip()
        timestamp = event.get("timestamp")
        turn_id = event.get("turn_id")
        message_id = str(event.get("message_id") or payload.get("message_id") or payload.get("id") or "").strip() or None
        stream_id = str(event.get("stream_id") or payload.get("stream_id") or "").strip() or None
        work_id = str(event.get("work_id") or payload.get("work_id") or "").strip() or None
        target = str(event.get("target") or payload.get("target") or "").strip() or None

        if category == "message" or event_type in MESSAGE_EVENT_TYPES:
            key = message_id
            if key:
                role = str(event.get("payload", {}).get("role") or event.get("role") or payload.get("role") or "").strip() or "assistant"
                record = {
                    "message_id": key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "role": role,
                    "source": event.get("source") or payload.get("source") or "",
                    "reply_to_message_id": event.get("reply_to_message_id") or payload.get("reply_to_message_id"),
                    "stream_id": stream_id,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "content_preview": self._preview_text(payload.get("content") or payload.get("message") or event.get("content")),
                    "status": str(payload.get("status") or event_type),
                    "work_id": work_id,
                    "event_id": event.get("event_id"),
                }
                self._upsert("messages", key, record)
                self._upsert_turn_record(
                    turn_id,
                    session_id,
                    timestamp,
                    message_id=key,
                    role=role,
                    stream_id=stream_id,
                    work_id=work_id,
                )

        if category == "stream" or event_type in STREAM_EVENT_TYPES or (event_type == "complete" and target == "stream"):
            key = stream_id
            if key:
                current_stream = self._get_index_record("streams", key)
                current_turn = self._get_index_record("turns", turn_id)
                stream_record = {
                    "stream_id": key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message_id": message_id,
                    "sequence_last": event.get("sequence"),
                    "status": "completed" if event_type == "complete" and target == "stream" else "streaming",
                    "started_at": current_stream.get("started_at") or timestamp,
                    "updated_at": timestamp,
                    "completed_at": timestamp if event_type == "complete" and target == "stream" else current_stream.get("completed_at"),
                    "last_chunk_preview": self._preview_text(payload.get("content") or event.get("content")),
                    "event_id": event.get("event_id"),
                    "turn_duration_ms": _duration_ms(current_turn.get("created_at") or timestamp, timestamp),
                    "thinking_duration_ms": _duration_ms(current_turn.get("thinking_started_at") or current_turn.get("created_at") or timestamp, timestamp),
                    "thinking_started_at": current_turn.get("thinking_started_at") or current_turn.get("created_at") or timestamp,
                    "thinking_updated_at": timestamp,
                    "thinking_completed_at": timestamp if event_type == "complete" and target == "stream" else current_stream.get("thinking_completed_at"),
                    "is_active": not (event_type == "complete" and target == "stream"),
                }
                stream_record = self._decorate_stream_record(stream_record)
                self._upsert("streams", key, stream_record)
                self._upsert_turn_record(
                    turn_id,
                    session_id,
                    timestamp,
                    stream_id=key,
                    status="completed" if event_type == "complete" and target == "stream" else None,
                )
                if event_type == "complete" and target == "stream":
                    self._close_thought_records_for_turn(turn_id, timestamp, stream_id=key)

        if category == "reasoning" or event_type in REASONING_EVENT_TYPES:
            thought_key = str(event.get("thought_id") or payload.get("thought_id") or event.get("event_id") or "").strip()
            if thought_key:
                current_turn = self._get_index_record("turns", turn_id)
                current_stream = self._get_index_record("streams", stream_id) if stream_id else {}
                thought_record = {
                    "thought_id": thought_key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message_id": message_id,
                    "work_id": work_id,
                    "sequence": event.get("sequence"),
                    "timestamp": timestamp,
                    "visibility": payload.get("visibility") or event.get("visibility") or "private",
                    "kind": payload.get("kind") or event.get("msg_type") or event_type,
                    "content_ref": payload.get("content_ref"),
                    "content": payload.get("content") or event.get("content"),
                    "summary": payload.get("summary") or event.get("summary"),
                    "event_id": event.get("event_id"),
                    "thinking_started_at": current_turn.get("thinking_started_at") or current_turn.get("created_at") or timestamp,
                    "thinking_updated_at": timestamp,
                    "thinking_completed_at": current_turn.get("thinking_completed_at"),
                    "thinking_duration_ms": _duration_ms(current_turn.get("thinking_started_at") or current_turn.get("created_at") or timestamp, timestamp),
                    "turn_duration_ms": _duration_ms(current_turn.get("created_at") or timestamp, timestamp),
                    "stream_duration_ms": _duration_ms(current_stream.get("started_at"), timestamp) if current_stream else None,
                    "is_active": bool(current_turn.get("is_active", True)),
                }
                thought_record = self._decorate_thought_record(thought_record, current_turn, current_stream)
                self._upsert("thoughts", thought_key, thought_record)
                self._upsert_turn_record(
                    turn_id,
                    session_id,
                    timestamp,
                    work_id=work_id,
                )

        if category == "media" or event_type in MEDIA_EVENT_TYPES:
            media_key = str(event.get("media_id") or payload.get("media_id") or event.get("event_id") or "").strip()
            if media_key:
                media_record = {
                    "media_id": media_key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message_id": message_id,
                    "work_id": work_id,
                    "origin_event_id": event.get("event_id"),
                    "kind": payload.get("kind") or payload.get("type") or event_type,
                    "mime": payload.get("mime") or payload.get("mime_type") or "",
                    "path": payload.get("path") or payload.get("url") or "",
                    "size": payload.get("size"),
                    "thumbnail_ref": payload.get("thumbnail_ref"),
                    "delivery_status": payload.get("delivery_status") or payload.get("status") or "",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "derived_refs": payload.get("derived_refs") or [],
                    "event_id": event.get("event_id"),
                }
                self._upsert("media", media_key, media_record)
                self._upsert_turn_record(turn_id, session_id, timestamp, message_id=message_id, work_id=work_id)

        if category == "artifact" or event_type in ARTIFACT_EVENT_TYPES:
            artifact_key = str(event.get("artifact_id") or payload.get("artifact_id") or event.get("event_id") or "").strip()
            if artifact_key:
                artifact_record = {
                    "artifact_id": artifact_key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message_id": message_id,
                    "work_id": work_id,
                    "origin_event_id": event.get("event_id"),
                    "artifact_type": payload.get("artifact_type") or payload.get("kind") or event_type,
                    "path": payload.get("path") or payload.get("url") or "",
                    "content_ref": payload.get("content_ref") or payload.get("content"),
                    "summary": payload.get("summary") or "",
                    "status": payload.get("status") or "active",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "event_id": event.get("event_id"),
                }
                self._upsert("artifacts", artifact_key, artifact_record)

        if category == "card" or event_type in CARD_EVENT_TYPES:
            card_key = str(event.get("card_id") or payload.get("card_id") or event.get("event_id") or "").strip()
            if card_key:
                card_record = {
                    "card_id": card_key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message_id": message_id,
                    "work_id": work_id,
                    "origin_event_id": event.get("event_id"),
                    "card_type": payload.get("card_type") or payload.get("kind") or event_type,
                    "payload": payload,
                    "status": payload.get("status") or "active",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "ttl": payload.get("ttl"),
                    "pinned": bool(payload.get("pinned")),
                    "event_id": event.get("event_id"),
                }
                self._upsert("cards", card_key, card_record)
                self._upsert_turn_record(turn_id, session_id, timestamp, message_id=message_id, work_id=work_id)

        if category == "visual" or event_type in WEGENA_EVENT_TYPES:
            scene_key = str(event.get("scene_id") or payload.get("scene_id") or event.get("event_id") or "").strip()
            if scene_key:
                wege_record = {
                    "scene_id": scene_key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "trigger_event_id": event.get("event_id"),
                    "status": payload.get("status") or event_type,
                    "scene_type": payload.get("scene_type") or payload.get("kind") or event_type,
                    "composition_ref": payload.get("composition_ref"),
                    "snapshot_ref": payload.get("snapshot_ref"),
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "event_id": event.get("event_id"),
                }
                self._upsert("wegena", scene_key, wege_record)
                # Visual events never create messages, but they can still be reflected on the turn lineage.
                self._upsert_turn_record(turn_id, session_id, timestamp)

        if category == "worker" or event_type in WORKER_EVENT_TYPES:
            key = work_id
            if key:
                worker_record = {
                    "work_id": key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message_id": message_id,
                    "status": str(payload.get("status") or payload.get("state") or event_type),
                    "label": payload.get("label") or payload.get("message") or event.get("message") or "",
                    "last_thought": payload.get("last_thought") or payload.get("thought") or "",
                    "started_at": timestamp,
                    "updated_at": timestamp,
                    "completed_at": timestamp if event_type in {"worker.updated", "worker_state"} and str(payload.get("status") or "").lower() in {"completed", "complete", "succeeded", "failed", "cancelled"} else None,
                    "event_id": event.get("event_id"),
                }
                self._upsert("workers", key, worker_record)
                self._upsert_turn_record(
                    turn_id,
                    session_id,
                    timestamp,
                    work_id=key,
                )

        if category == "feedback" or event_type in FEEDBACK_EVENT_TYPES or event_type.startswith("message.feedback."):
            feedback_key = str(
                _pick_first(
                    payload.get("feedback_id"),
                    event.get("feedback_id"),
                    event.get("message_id"),
                    payload.get("message_id"),
                )
                or ""
            ).strip()
            rating = payload.get("rating") if _is_mapping(payload) else None
            if rating in (None, "", "null"):
                self._delete("feedback", feedback_key or event.get("message_id"))
            elif feedback_key:
                feedback_record = {
                    "feedback_id": feedback_key,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message_id": message_id,
                    "message_role": payload.get("message_role") or event.get("message_role") or payload.get("role") or event.get("role"),
                    "message_type": payload.get("message_type") or event.get("message_type") or payload.get("msg_type") or event.get("msg_type"),
                    "rating": rating,
                    "reason": payload.get("reason") or event.get("reason"),
                    "comment": payload.get("comment") or event.get("comment"),
                    "source": payload.get("source") or event.get("source") or "chat",
                    "user_id": payload.get("user_id") or event.get("user_id"),
                    "created_at": payload.get("created_at") or event.get("timestamp") or timestamp,
                    "updated_at": timestamp,
                    "event_id": event.get("event_id"),
                }
                self._upsert("feedback", feedback_key, feedback_record)
                self._upsert_turn_record(turn_id, session_id, timestamp)
