import os
import json
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo
from .models import CalendarEvent
from .sync_models import CalendarSyncMetadata
from .providers.base import CalendarProvider
from services.agent_events.models import AgentEvent, AgentEventPriority
from config.manager import ConfigManager

logger = logging.getLogger("CalendarSyncService")

class CalendarSyncService:
    """
    Coordinates synchronization between internal store and external providers.
    """
    def __init__(self, kernel, store, provider: CalendarProvider):
        self.kernel = kernel
        self.store = store
        self.provider = provider
        self.user_id = "admin" # Forced single-user: admin
        
        # Metadata storage (separate file or integrated)
        # For simplicity, we'll store synchronization metadata in a dedicated mapping
        # In a real app, this could be a DB table or a JSON file.
        # Retention settings (default 2 years)
        self.retention_days = ConfigManager().get_capability_config("calendar").get("retention_days", 730)
        
        self._lock = threading.RLock()
        self.sync_mappings: Dict[str, CalendarSyncMetadata] = {}
        self._load_mappings()

    def _load_mappings(self):
        # Load mappings from store data_dir
        mapping_file = os.path.join(self.store.data_dir, f"sync_mappings_{self.user_id}.json")
        if os.path.exists(mapping_file):
            try:
                with open(mapping_file, 'r') as f:
                    data = json.load(f)
                    for int_id, m_data in data.items():
                        self.sync_mappings[int_id] = CalendarSyncMetadata.from_dict(m_data)
            except Exception as e:
                logger.error(f"Error loading sync mappings: {e}")

    def _save_mappings(self):
        """Atomically saves sync_mappings to prevent JSON corruption."""
        mapping_file = os.path.join(self.store.data_dir, f"sync_mappings_{self.user_id}.json")
        tmp_file = mapping_file + ".tmp"
        try:
            data = {int_id: m.to_dict() for int_id, m in self.sync_mappings.items()}
            with open(tmp_file, 'w') as f:
                json.dump(data, f, indent=4)
            os.replace(tmp_file, mapping_file)
        except Exception as e:
            logger.error(f"Error saving sync mappings: {e}")
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    def pull(self, days_back: Optional[int] = None, days_forward: int = 30):
        """
        Pull events from provider and update internal store.
        """
        # Use configured retention_days if days_back not provided
        back = days_back if days_back is not None else self.retention_days
        
        tz_name = ConfigManager().get_timezone()
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        start = now - timedelta(days=back)
        end = now + timedelta(days=days_forward)

        # Timestamps for boundary checking
        start_ts = start.timestamp()
        end_ts = end.timestamp()

        try:
            external_events = self.provider.list_events(start, end)
            logger.info(f"Pulled {len(external_events)} events from provider (Window: -{back} to +{days_forward} days)")
        except Exception as e:
            logger.error(f"Failed to pull events from provider for user {self.user_id}: {e}", exc_info=True)
            return

        with self._lock:
            for ext_event_data in external_events:
                ext_id = ext_event_data["external_event_id"]
                
                # Find if we already have this event mapped
                mapping = self._find_mapping_by_external_id(ext_id)
                
                if not mapping:
                    # SELF-HEAL: Check if store already has this external ID
                    # but we just lost the mapping (e.g. during user migration)
                    existing_event = self.store.get_event_by_external_id(ext_id)
                    if existing_event:
                        logger.info(f"Self-healed mapping for event {existing_event.event_id} ({ext_id})")
                        mapping = CalendarSyncMetadata(
                            internal_event_id=existing_event.event_id,
                            provider_name=self.provider.__class__.__name__,
                            provider_event_id=ext_id,
                            provider_version=ext_event_data.get("metadata", {}).get("etag"),
                            last_synced_at=time.time(),
                            sync_status="synced"
                        )
                        self.sync_mappings[existing_event.event_id] = mapping

                if mapping:
                    # Update existing
                    internal_event = self.store.get_event(mapping.internal_event_id)
                    if internal_event:
                        ext_version = ext_event_data.get("metadata", {}).get("etag")
                        version_changed = ext_version != mapping.provider_version
                        internal_changed = internal_event.updated_at > mapping.last_synced_at

                        if internal_changed and version_changed:
                            # COMPLEX CONFLICT: Both sides updated
                            logger.info(f"Sync Conflict detected for event {internal_event.event_id}. Emitting event.")
                            self._emit_conflict_event(internal_event, ext_event_data, mapping)
                            internal_event.sync_state = "review_required"
                            self.store.save_event(internal_event)
                            mapping.sync_status = "conflicted"
                        elif internal_changed:
                            # Internal only: will be handled by push()
                            logger.debug(f"Event {internal_event.event_id} has local changes, skipping pull update.")
                        elif version_changed:
                            # External only: Safe to apply
                            self._apply_external_to_internal(internal_event, ext_event_data)
                            self.store.save_event(internal_event)
                            mapping.last_synced_at = time.time()
                            mapping.sync_status = "synced"
                            mapping.provider_version = ext_version
                        else:
                            # No changes on either side
                            mapping.sync_status = "synced"
                else:
                    # Create new internal event
                    new_event = CalendarEvent.from_dict(ext_event_data)
                    self.store.save_event(new_event)
                    
                    # Create mapping
                    new_mapping = CalendarSyncMetadata(
                        internal_event_id=new_event.event_id,
                        provider_name=self.provider.__class__.__name__,
                        provider_event_id=ext_id,
                        provider_version=ext_event_data.get("metadata", {}).get("etag")
                    )
                    self.sync_mappings[new_event.event_id] = new_mapping
            
            # Cleanup: Handle events deleted in provider
            external_ids_found = {e["external_event_id"] for e in external_events}
            mappings_to_delete = []
            
            for int_id, mapping in self.sync_mappings.items():
                if mapping.provider_name == self.provider.__class__.__name__:
                    if mapping.provider_event_id not in external_ids_found:
                        internal_event = self.store.get_event(int_id)
                        if not internal_event:
                            mappings_to_delete.append(int_id)
                            continue

                        # CLEANUP GUARD: 
                        # Only delete if the event's start_time is within the window we just polled.
                        is_within_window = start_ts <= internal_event.start_time <= end_ts
                        
                        if not is_within_window:
                            logger.debug(f"Event {int_id} is outside sync window. Preserving.")
                            continue

                        # Potential external deletion
                        internal_changed = internal_event.updated_at > mapping.last_synced_at
                        
                        if internal_changed:
                            logger.warning(f"Ambiguous deletion detected for {int_id}. Local was updated. Emitting event.")
                            self._emit_deletion_ambiguity_event(internal_event, mapping)
                            internal_event.sync_state = "review_required"
                            self.store.save_event(internal_event)
                            mapping.sync_status = "conflicted"
                        else:
                            logger.info(f"Event {int_id} not found in provider within sync window. Deleting internally.")
                            self.store.delete_event(int_id)
                            mappings_to_delete.append(int_id)
            
            for int_id in mappings_to_delete:
                self.sync_mappings.pop(int_id, None)
            
            self._save_mappings()

    def push(self, event_id: Optional[str] = None) -> bool:
        """
        Push local events that are marked for sync or are new.
        If event_id is provided, only push that specific event.
        Returns True if all targeted pushes succeeded.
        """
        if event_id:
            event = self.store.get_event(event_id)
            if event:
                return self._push_event(event)
            return False
        else:
            events = self.store.list_events(self.user_id)
            all_ok = True
            for event in events:
                if not self._push_event(event):
                    all_ok = False
            return all_ok

    def _push_event(self, event: CalendarEvent) -> bool:
        mapping = self.sync_mappings.get(event.event_id)
        success = True
        
        if mapping:
            if event.updated_at > mapping.last_synced_at:
                # Update external
                success = self.provider.update_event(mapping.provider_event_id, event.to_dict())
                if success:
                    mapping.last_synced_at = time.time()
                    mapping.sync_status = "synced"
        elif event.source == "internal":
            # Create external
            ext_id = self.provider.create_event(event.to_dict())
            if ext_id:
                new_mapping = CalendarSyncMetadata(
                    internal_event_id=event.event_id,
                    provider_name=self.provider.__class__.__name__,
                    provider_event_id=ext_id
                )
                self.sync_mappings[event.event_id] = new_mapping
            else:
                success = False
        
        self._save_mappings()
        return success

    def _find_mapping_by_external_id(self, external_id: str) -> Optional[CalendarSyncMetadata]:
        for m in self.sync_mappings.values():
            if m.provider_event_id == external_id:
                return m
        return None

    def _apply_external_to_internal(self, internal_event: CalendarEvent, ext_data: Dict[str, Any]):
        internal_event.title = ext_data.get("title", internal_event.title)
        internal_event.description = ext_data.get("description", internal_event.description)
        internal_event.start_time = ext_data.get("start_time", internal_event.start_time)
        internal_event.end_time = ext_data.get("end_time", internal_event.end_time)
        internal_event.location = ext_data.get("location", internal_event.location)
        internal_event.status = ext_data.get("status", internal_event.status)
        internal_event.updated_at = time.time()

    def _emit_conflict_event(self, internal_event: CalendarEvent, ext_data: Dict[str, Any], mapping: CalendarSyncMetadata):
        """Emits an AgentEvent for complex sync conflicts."""
        payload = {
            "internal_event_id": internal_event.event_id,
            "provider": mapping.provider_name,
            "provider_event_id": mapping.provider_event_id,
            "conflict_type": "both_updated",
            "internal_snapshot": internal_event.to_dict(),
            "provider_snapshot": ext_data,
            "last_internal_update": internal_event.updated_at,
            "last_provider_update": mapping.last_synced_at, # This is the last time we SAW it synced
            "risk_level": "medium"
        }
        
        event = AgentEvent(
            event_type="calendar.sync_conflict_detected",
            source="calendar_sync_service",
            priority=AgentEventPriority.HIGH,
            payload=payload
        )
        self._inject_event(event)

    def _emit_deletion_ambiguity_event(self, internal_event: CalendarEvent, mapping: CalendarSyncMetadata):
        """Emits an AgentEvent for ambiguous deletions."""
        payload = {
            "internal_event_id": internal_event.event_id,
            "provider": mapping.provider_name,
            "provider_event_id": mapping.provider_event_id,
            "conflict_type": "ambiguous_deletion",
            "internal_snapshot": internal_event.to_dict(),
            "last_internal_update": internal_event.updated_at,
            "risk_level": "high"
        }
        
        event = AgentEvent(
            event_type="calendar.external_deletion_detected",
            source="calendar_sync_service",
            priority=AgentEventPriority.HIGH,
            payload=payload
        )
        self._inject_event(event)

    def _inject_event(self, event: AgentEvent):
        """Injects event into system via InternalDriver."""
        internal_driver = getattr(self.kernel, "internal_driver", None)
        if internal_driver:
            internal_driver.inject_event(event)
        else:
            logger.error("InternalDriver not found in kernel. Cannot emit sync event.")

