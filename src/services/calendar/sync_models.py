import time
from typing import Optional, Dict, Any

class CalendarSyncMetadata:
    """
    Tracks synchronization state between an internal event and an external provider.
    """
    def __init__(
        self,
        internal_event_id: str,
        provider_name: str,
        provider_event_id: str,
        last_synced_at: Optional[float] = None,
        sync_status: str = "synced", # synced, pending, error, conflicted
        provider_version: Optional[str] = None, # ETag or similar
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.internal_event_id = internal_event_id
        self.provider_name = provider_name
        self.provider_event_id = provider_event_id
        self.last_synced_at = last_synced_at or time.time()
        self.sync_status = sync_status
        self.provider_version = provider_version
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "internal_event_id": self.internal_event_id,
            "provider_name": self.provider_name,
            "provider_event_id": self.provider_event_id,
            "last_synced_at": self.last_synced_at,
            "sync_status": self.sync_status,
            "provider_version": self.provider_version,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalendarSyncMetadata":
        return cls(**data)
