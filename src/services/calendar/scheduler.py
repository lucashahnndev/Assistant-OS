import logging
import threading
import time
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from .models import CalendarEvent
from .store import CalendarStore
from services.agent_events.models import AgentEvent
from config.manager import ConfigManager
from services.notifications.user_preferences import UserPreferenceStore
from services.notifications.store import NotificationStore

logger = logging.getLogger("CalendarScheduler")

class CalendarScheduler:
    def __init__(self, store: CalendarStore, internal_driver):
        self.store = store
        self.internal_driver = internal_driver
        self.data_dir = store.data_dir
        self.state_file = os.path.join(self.data_dir, "scheduler_state.json")
        self.base_data_dir = os.path.dirname(self.data_dir)
        self.config_manager = ConfigManager()
        self.preference_store = UserPreferenceStore(self.base_data_dir)
        self.notification_store = NotificationStore(self.base_data_dir)
        
        # event_id -> set of triggered reminder offsets (e.g. {10, 30})
        # also using "started" as a key for the event start signal
        self.triggered_markers: Dict[str, List[str]] = {}
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._load_state()

    def _refresh_adaptive_sources(self):
        # Scheduler and notification/capability layers may hold distinct store instances.
        # Refresh from disk each loop to keep timing adaptation consistent across processes/threads.
        try:
            self.preference_store._load()
        except Exception as e:
            logger.debug("Failed refreshing preference store: %s", e)
        try:
            self.notification_store._load()
        except Exception as e:
            logger.debug("Failed refreshing notification store: %s", e)

    def _default_reminder_offsets(self) -> List[int]:
        cfg = self.config_manager.get_capability_config("calendar") or {}
        raw = cfg.get("default_reminder_offsets_minutes")
        offsets: List[int] = []
        if isinstance(raw, list):
            for item in raw:
                try:
                    val = int(item)
                except Exception:
                    continue
                if 1 <= val <= 10080:
                    offsets.append(val)
        # Backward compatibility for single-value setting.
        if not offsets:
            fallback_single = cfg.get("default_reminder_offset_minutes")
            if fallback_single is not None:
                try:
                    val = int(fallback_single)
                    if 1 <= val <= 10080:
                        offsets = [val]
                except Exception:
                    pass
        if not offsets:
            offsets = [30, 10, 1]
        return sorted(set(offsets), reverse=True)

    @staticmethod
    def _sanitize_offsets(values: List[int]) -> List[int]:
        cleaned = []
        for item in values or []:
            try:
                val = int(item)
            except Exception:
                continue
            if 1 <= val <= 10080:
                cleaned.append(val)
        return sorted(set(cleaned), reverse=True)

    def _resolve_timing_preference_offset(self, user_id: str) -> Optional[int]:
        try:
            effective = self.preference_store.get_effective_preferences(
                user_id=user_id,
                domain="calendar",
                event_type="calendar.event_starting",
                context_tags=[],
            )
            for pref in effective:
                if str(pref.get("dimension") or "").strip().lower() != "timing":
                    continue
                if str(pref.get("key") or "").strip().lower() != "default_reminder_offset_minutes":
                    continue
                try:
                    val = int(pref.get("value"))
                except Exception:
                    continue
                if 1 <= val <= 10080:
                    return val
        except Exception as e:
            logger.debug("Failed to resolve timing preference offset for %s: %s", user_id, e)
        return None

    def _resolve_runtime_timing_override_offset(self, user_id: str) -> Optional[int]:
        try:
            overrides = self.notification_store.get_runtime_overrides_for_user(user_id)
            timing = overrides.get("timing_policy") if isinstance(overrides.get("timing_policy"), dict) else {}
            proposal = timing.get("proposal") if isinstance(timing.get("proposal"), dict) else {}
            if "default_reminder_offset_minutes" not in proposal:
                return None
            val = int(proposal.get("default_reminder_offset_minutes"))
            if 1 <= val <= 10080:
                return val
        except Exception as e:
            logger.debug("Failed to resolve runtime timing override for %s: %s", user_id, e)
        return None

    def _effective_reminders_for_event(self, event: CalendarEvent) -> List[int]:
        # 1) Event-specific reminders always win.
        explicit_event = self._sanitize_offsets(list(event.reminders or []))
        if explicit_event:
            return explicit_event

        user_id = str(getattr(event, "user_id", "") or "admin")

        # 2) Explicit user preference for timing.
        pref_offset = self._resolve_timing_preference_offset(user_id)
        if pref_offset is not None:
            return [pref_offset]

        # 3) Runtime override from approved/applied timing patch.
        override_offset = self._resolve_runtime_timing_override_offset(user_id)
        if override_offset is not None:
            return [override_offset]

        # 4) Deterministic defaults from config.
        return self._default_reminder_offsets()

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    self.triggered_markers = json.load(f)
        except Exception as e:
            logger.error(f"Error loading scheduler state: {e}")

    def _save_state(self):
        try:
            # Cleanup old events from state to keep it small
            active_ids = {e.event_id for e in self.store.events.values()}
            self.triggered_markers = {k: v for k, v in self.triggered_markers.items() if k in active_ids}

            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.triggered_markers, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving scheduler state: {e}")

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("Calendar Scheduler started.")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
        logger.info("Calendar Scheduler stopped.")

    def _run_loop(self):
        while self.running:
            try:
                self._check_events()
                # Periodically pull from external providers for all active users
                self._periodic_sync_pull()
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
            time.sleep(60) # Check every minute

    def _periodic_sync_pull(self):
        """Triggers a pull for all registered sync services."""
        # This assumes the scheduler has access to the service or we can get it via kernel
        # For simplicity and isolation, we'll try to find the calendar_service via kernel
        calendar_service = getattr(self.internal_driver.kernel, "calendar_service", None)
        if calendar_service:
            for user_id, sync_service in calendar_service.sync_services.items():
                try:
                    logger.debug(f"Periodic sync pull for user {user_id}")
                    sync_service.pull()
                except Exception as e:
                    logger.error(f"Error during periodic pull for {user_id}: {e}")

    def _check_events(self):
        import pytz
        now = datetime.now(pytz.UTC)
        now_ts = now.timestamp()
        self._refresh_adaptive_sources()
        
        upcoming = self.store.get_upcoming_events(limit=100)
        changed = False

        for event in upcoming:
            if event.status != "scheduled":
                continue

            event_id = event.event_id
            if event_id not in self.triggered_markers:
                self.triggered_markers[event_id] = []

            # 1. Check Reminders
            effective_offsets = self._effective_reminders_for_event(event)
            for offset in effective_offsets:
                marker = f"reminder_{offset}"
                if marker not in self.triggered_markers[event_id]:
                    # event.start_time is a float (timestamp)
                    trigger_time_ts = event.start_time - (offset * 60)
                    if now_ts >= trigger_time_ts:
                        self._trigger_reminder(event, offset)
                        self.triggered_markers[event_id].append(marker)
                        changed = True

            # 2. Check Event Start
            if "started" not in self.triggered_markers[event_id]:
                if now_ts >= event.start_time:
                    self._trigger_start(event)
                    self.triggered_markers[event_id].append("started")
                    changed = True

        if changed:
            self._save_state()

    def _trigger_reminder(self, event: CalendarEvent, offset: int):
        logger.info(f"Triggering reminder for event '{event.title}' ({offset}m before)")
        
        # Convert timestamps to ISO for the payload
        start_iso = datetime.fromtimestamp(event.start_time).isoformat()
        end_iso = datetime.fromtimestamp(event.end_time).isoformat()

        agent_event = AgentEvent(
            event_type="calendar.reminder_due",
            source="calendar_scheduler",
            priority="medium",
            payload={
                "event_id": event.event_id,
                "title": event.title,
                "start_time": start_iso,
                "end_time": end_iso,
                "minutes_remaining": offset,
                "reminder_offset_minutes": offset,
                "effective_reminder_offsets": self._effective_reminders_for_event(event),
            }
        )
        self.internal_driver.inject_event(agent_event)

    def _trigger_start(self, event: CalendarEvent):
        logger.info(f"Triggering start for event '{event.title}'")
        
        # Convert timestamps to ISO for the payload
        start_iso = datetime.fromtimestamp(event.start_time).isoformat()
        end_iso = datetime.fromtimestamp(event.end_time).isoformat()

        agent_event = AgentEvent(
            event_type="calendar.event_starting",
            source="calendar_scheduler",
            priority="high",
            payload={
                "event_id": event.event_id,
                "title": event.title,
                "start_time": start_iso,
                "end_time": end_iso
            }
        )
        self.internal_driver.inject_event(agent_event)

    def notify_event_changed(self, event: CalendarEvent):
        """Called by service when an event is added or updated."""
        # Force a check or just let the loop handle it
        pass

    def notify_event_deleted(self, event_id: str):
        if event_id in self.triggered_markers:
            del self.triggered_markers[event_id]
            self._save_state()
