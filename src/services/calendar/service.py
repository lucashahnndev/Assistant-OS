import logging
import time
from typing import List, Optional, Dict, Any
from .models import CalendarEvent
from .store import CalendarStore

logger = logging.getLogger("CalendarService")

class CalendarService:
    def __init__(self, store: CalendarStore, kernel=None):
        self.store = store
        self.kernel = kernel
        self.scheduler = None # To be set by orchestrator
        self.sync_services: Dict[str, Any] = {} # user_id -> CalendarSyncService

    def set_scheduler(self, scheduler):
        self.scheduler = scheduler

    def register_sync_service(self, user_id: str, sync_service):
        # We use a single sync service for all users since we are single-user 'admin'
        self.sync_services["admin"] = sync_service
        logger.info(f"Registered sync service for user admin (request from {user_id})")

    def has_sync_service(self, user_id: str = "admin") -> bool:
        return "admin" in self.sync_services

    def create_event(self, user_id: str, title: str, start_time: Any, end_time: Any, **kwargs) -> tuple[CalendarEvent, bool]:
        user_id = "admin" # Forced single-user
        event = CalendarEvent(
            user_id=user_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            **kwargs
        )
        self.store.save_event(event)
        
        sync_ok = True
        # Trigger push if sync service exists
        if user_id in self.sync_services:
            try:
                sync_ok = self.sync_services[user_id].push(event.event_id)
            except Exception as e:
                logger.error(f"Error pushing event to provider: {e}")
                sync_ok = False

        if self.scheduler:
            self.scheduler.notify_event_changed(event)
        return event, sync_ok

    def update_event(self, event_id: str, **kwargs) -> tuple[Optional[CalendarEvent], bool]:
        event = self.store.resolve_event_ref(event_id)
        if not event:
            return None, False
        
        # update fields
        data = event.to_dict()
        data.update(kwargs)
        data["updated_at"] = time.time()
        
        updated_event = CalendarEvent.from_dict(data)
        self.store.save_event(updated_event)
        
        sync_ok = True
        # Trigger push
        sync_user_id = "admin" 
        if sync_user_id in self.sync_services:
            try:
                sync_ok = self.sync_services[sync_user_id].push(updated_event.event_id)
            except Exception as e:
                logger.error(f"Error pushing updated event: {e}")
                sync_ok = False
        
        if self.scheduler:
            self.scheduler.notify_event_changed(updated_event)
        return updated_event, sync_ok

    def cancel_event(self, event_id: str) -> bool:
        event = self.store.resolve_event_ref(event_id)
        if not event:
            return False
        
        event.status = "cancelled"
        event.updated_at = time.time()
        self.store.save_event(event)
        
        sync_ok = True
        # Trigger push
        sync_user_id = "admin"
        if sync_user_id in self.sync_services:
            try:
                sync_ok = self.sync_services[sync_user_id].push(event.event_id)
            except Exception as e:
                logger.error(f"Error pushing cancelled event: {e}")
                sync_ok = False
        
        if self.scheduler:
            self.scheduler.notify_event_changed(event)
        return sync_ok

    def delete_event(self, event_id: str) -> bool:
        event = self.store.resolve_event_ref(event_id)
        if not event:
            return False
        
        # Pull the mapping if it exists to delete from provider
        sync_user_id = "admin"
        if sync_user_id in self.sync_services:
            sync_service = self.sync_services[sync_user_id]
            mapping = sync_service.sync_mappings.get(event.event_id)
            if mapping:
                try:
                    sync_service.provider.delete_event(mapping.provider_event_id)
                    del sync_service.sync_mappings[event.event_id]
                    sync_service._save_mappings()
                except Exception as e:
                    logger.error(f"Error deleting event from provider: {e}")
            
            # Final push to ensure any other dirty state is synced (though delete is usually enough)
            try:
                sync_service.push()
            except Exception as e:
                logger.error(f"Error pushing after delete: {e}")

        self.store.delete_event(event.event_id)
        
        if self.scheduler:
            self.scheduler.notify_event_deleted(event.event_id)
        return True

    def sync_all(self, user_id: str):
        """Manual sync trigger for a user."""
        if user_id in self.sync_services:
            sync_service = self.sync_services[user_id]
            logger.info(f"Starting full sync for user {user_id}")
            sync_service.pull()
            sync_service.push()
            return True
        return False

    def list_events(self, user_id: str, start_time: Optional[float] = None, end_time: Optional[float] = None) -> List[CalendarEvent]:
        user_id = "admin" # Forced single-user
        return self.store.list_events(user_id, start_time=start_time, end_time=end_time)

    def get_event(self, event_id: str) -> Optional[CalendarEvent]:
        return self.store.resolve_event_ref(event_id)

    def resolve_event_ref(self, event_ref: str) -> Optional[CalendarEvent]:
        return self.store.resolve_event_ref(event_ref)
