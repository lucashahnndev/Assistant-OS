import os
import json
import logging
import time
import threading
import re
from typing import List, Dict, Optional
from .models import CalendarEvent

logger = logging.getLogger("CalendarStore")

class CalendarStore:
    def __init__(self, data_dir: str):
        self.data_dir = os.path.join(data_dir, "calendar")
        self.events_file = os.path.join(self.data_dir, "events.json")
        os.makedirs(self.data_dir, exist_ok=True)
        self.events: Dict[str, CalendarEvent] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        with self._lock:
            try:
                if os.path.exists(self.events_file):
                    with open(self.events_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for event_id, event_data in data.items():
                            self.events[event_id] = CalendarEvent.from_dict(event_data)
            except Exception as e:
                logger.error(f"Error loading calendar events: {e}")

    def _save(self):
        """Atomically writes events to disk using a temp file + os.replace pattern."""
        tmp_file = self.events_file + ".tmp"
        try:
            data = {event_id: event.to_dict() for event_id, event in self.events.items()}
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            # Atomic replace: prevents partial writes from corrupting the main file
            os.replace(tmp_file, self.events_file)
        except Exception as e:
            logger.error(f"Error saving calendar events: {e}")
            # Cleanup orphan tmp file on failure
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    def save_event(self, event: CalendarEvent):
        with self._lock:
            self._ensure_unique_short_id(event)
            self.events[event.event_id] = event
            self._save()

    def get_event(self, event_id: str) -> Optional[CalendarEvent]:
        with self._lock:
            return self.events.get(event_id)

    def list_events(self, user_id: str, start_time: Optional[float] = None, end_time: Optional[float] = None) -> List[CalendarEvent]:
        with self._lock:
            events = [e for e in self.events.values() if e.user_id == user_id]
            if start_time is not None:
                events = [e for e in events if e.end_time >= start_time]
            if end_time is not None:
                events = [e for e in events if e.start_time <= end_time]
            events.sort(key=lambda e: e.start_time)
            return events

    def delete_event(self, event_id: str):
        with self._lock:
            if event_id in self.events:
                del self.events[event_id]
                self._save()

    def get_upcoming_events(self, limit: int = 50) -> List[CalendarEvent]:
        with self._lock:
            now = time.time()
            upcoming = [e for e in self.events.values() if e.end_time > now and e.status == "scheduled"]
            upcoming.sort(key=lambda x: x.start_time)
            return upcoming[:limit]
    def get_event_by_external_id(self, external_id: str) -> Optional[CalendarEvent]:
        with self._lock:
            for event in self.events.values():
                if event.external_event_id == external_id:
                    return event
            return None

    def resolve_event_ref(self, event_ref: str) -> Optional[CalendarEvent]:
        """Resolves a reference by full UUID, short_id, or unique prefix."""
        with self._lock:
            ref = self._normalize_ref(event_ref)
            if not ref:
                return None

            if ref in self.events:
                return self.events.get(ref)

            by_short = [e for e in self.events.values() if self._normalize_ref(e.short_id) == ref]
            if len(by_short) == 1:
                return by_short[0]

            by_uuid_prefix = [e for e in self.events.values() if self._normalize_ref(e.event_id).startswith(ref)]
            if len(by_uuid_prefix) == 1:
                return by_uuid_prefix[0]

            by_short_prefix = [e for e in self.events.values() if self._normalize_ref(e.short_id).startswith(ref)]
            if len(by_short_prefix) == 1:
                return by_short_prefix[0]

            return None

    @staticmethod
    def _normalize_ref(value: Optional[str]) -> str:
        text = str(value or "").strip().lower()
        return re.sub(r"[^a-z0-9-]", "", text)

    def _ensure_unique_short_id(self, event: CalendarEvent):
        short = self._normalize_ref(event.short_id)
        if short and not any(
            e.event_id != event.event_id and self._normalize_ref(e.short_id) == short
            for e in self.events.values()
        ):
            return

        base = re.sub(r"[^a-z0-9]", "", str(event.event_id).lower())
        if not base:
            base = str(int(time.time() * 1000))

        for size in (10, 12, 14, 16, 20, 24, 32):
            candidate = base[:size]
            if candidate and not any(
                e.event_id != event.event_id and self._normalize_ref(e.short_id) == candidate
                for e in self.events.values()
            ):
                event.short_id = candidate
                return

        event.short_id = f"{base[:12]}{int(time.time())}"
