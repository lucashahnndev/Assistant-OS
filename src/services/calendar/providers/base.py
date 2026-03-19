from typing import List, Dict, Any, Optional
from datetime import datetime

class CalendarProvider:
    """
    Abstract base class for calendar providers (Google, Outlook, etc).
    """
    def __init__(self, kernel, user_id: str):
        self.kernel = kernel
        self.user_id = user_id

    def list_events(self, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        """
        List events from the provider within a time range.
        Should return list of dicts compatible with CalendarEvent.from_dict
        but with provider-specific IDs.
        """
        raise NotImplementedError

    def get_event(self, provider_event_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single event by provider ID.
        """
        raise NotImplementedError

    def create_event(self, event_data: Dict[str, Any]) -> str:
        """
        Create an event in the provider. Return the provider_event_id.
        """
        raise NotImplementedError

    def update_event(self, provider_event_id: str, event_data: Dict[str, Any]) -> bool:
        """
        Update an event in the provider.
        """
        raise NotImplementedError

    def delete_event(self, provider_event_id: str) -> bool:
        """
        Delete/cancel an event in the provider.
        """
        raise NotImplementedError
