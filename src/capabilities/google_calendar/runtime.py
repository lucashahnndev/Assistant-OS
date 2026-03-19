import logging
from typing import Dict, Any, List

logger = logging.getLogger("GoogleCalendarCapability")

class GoogleCalendarCapability:
    def __init__(self, kernel, config):
        self.kernel = kernel
        self.config = config
        self.name = "google_calendar"
        self.orchestrator = kernel.orchestrator
        self.calendar_service = self.orchestrator.calendar_service
        self.actions = [
            "google.calendar.sync",
            "google.calendar.list_calendars"
        ]

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        if action_id == "google.calendar.sync":
            return self.handle_sync(context, **params)
        if action_id == "google.calendar.list_calendars":
            return self.handle_list_calendars(context, **params)
        raise ValueError(f"Unknown action: {action_id}")

    def _get_user_id(self, context: Dict[str, Any]) -> str:
        principal = context.get("principal")
        if principal:
            return principal.sender_id
        return "default_user"

    def handle_sync(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        user_id = self._get_user_id(context)
        success = self.calendar_service.sync_all(user_id)
        return {
            "ok": success,
            "status": "success" if success else "empty",
            "provider": "google",
            "data": {
                "sync_triggered": success,
                "message": "Google Calendar synchronization triggered." if success else "User has no Google account linked to calendar sync."
            }
        }
    def handle_list_calendars(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        user_id = self._get_user_id(context)
        # We access the provider directly from the sync service if it exists
        sync_service = self.calendar_service.sync_services.get(user_id)
        if not sync_service or not hasattr(sync_service, "provider"):
             return {"status": "error", "message": "No Google Calendar provider configured for this user."}
        
        provider = sync_service.provider
        # Call the API to list calendars
        # Since _make_request is "private", we access it carefully or just use the sync service
        result = provider._make_request("GET", "/users/me/calendarList")
        if not result:
            return {
                "ok": False,
                "status": "error",
                "provider": "google",
                "data": {"message": "Failed to fetch calendar list from Google."}
            }
            
        return {
            "ok": True,
            "status": "success",
            "provider": "google",
            "data": {
                "calendars": result.get("items", [])
            }
        }
def create_capability(kernel, config):
    return GoogleCalendarCapability(kernel, config)
