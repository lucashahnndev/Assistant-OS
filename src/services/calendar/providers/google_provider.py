import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo
from .base import CalendarProvider
from capabilities.shared.google_auth import resolve_google_request_auth
from config.manager import ConfigManager

logger = logging.getLogger("GoogleCalendarProvider")

class GoogleCalendarProvider(CalendarProvider):
    """
    Implementation of CalendarProvider for Google Calendar.
    """
    API_BASE = "https://www.googleapis.com/calendar/v3"

    def __init__(self, kernel, user_id: str):
        super().__init__(kernel, user_id)
        # We need a context for resolve_google_request_auth
        self.context = {"portal_user_id": user_id}

    def _make_request(self, method: str, path: str, params: Optional[Dict] = None, data: Optional[Dict] = None) -> Any:
        auth = resolve_google_request_auth(
            context=self.context,
            kernel=self.kernel,
            requested_source="linked_account"
        )
        
        if auth["mode"] == "none":
            logger.error(f"Google Auth failed for user {self.user_id}: {auth.get('reason')}")
            raise RuntimeError(f"Google Auth failed: {auth.get('reason')}")

        url = f"{self.API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        headers = auth.get("headers", {}).copy()
        body = None
        if data:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 204:
                    return True
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_content = e.read().decode("utf-8", errors="ignore")
            logger.error(f"Google Calendar API error: {e.code} {e.reason} - {body_content}")
            raise RuntimeError(f"Google Calendar API error: {e.code} {e.reason} - {body_content}") from e
        except Exception as e:
            logger.error(f"Unexpected error calling Google Calendar API: {e}")
            raise RuntimeError(f"Unexpected error calling Google Calendar API: {e}") from e

    def list_events(self, start_time: datetime, end_time: datetime) -> List[Dict[str, Any]]:
        params = {
            "timeMin": start_time.isoformat(),
            "timeMax": end_time.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime"
        }
        
        # Primary calendar by default
        result = self._make_request("GET", "/calendars/primary/events", params=params)
        if not result:
            return []
            
        items = result.get("items", [])
        events = []
        for item in items:
            events.append(self._map_to_internal(item))
        return events

    def get_event(self, provider_event_id: str) -> Optional[Dict[str, Any]]:
        result = self._make_request("GET", f"/calendars/primary/events/{provider_event_id}")
        if result:
            return self._map_to_internal(result)
        return None

    def create_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        g_data = self._map_to_google(event_data)
        result = self._make_request("POST", "/calendars/primary/events", data=g_data)
        return result.get("id") if result else None

    def update_event(self, provider_event_id: str, event_data: Dict[str, Any]) -> bool:
        g_data = self._map_to_google(event_data)
        result = self._make_request("PUT", f"/calendars/primary/events/{provider_event_id}", data=g_data)
        return True if result else False

    def delete_event(self, provider_event_id: str) -> bool:
        result = self._make_request("DELETE", f"/calendars/primary/events/{provider_event_id}")
        return True if result is True else False

    def _map_to_internal(self, g_event: Dict[str, Any]) -> Dict[str, Any]:
        """Maps Google event structure to internal CalendarEvent dict."""
        start = g_event.get("start", {})
        end = g_event.get("end", {})
        
        # Google uses 'dateTime' for specific times and 'date' for all-day events
        start_raw = start.get("dateTime") or start.get("date")
        end_raw = end.get("dateTime") or end.get("date")
        
        # Simple parsing - we'll keep them as strings for CalendarEvent.from_dict which handles it?
        # Actually our new CalendarEvent handles floats or datetimes.
        # isoformat strings should be converted to datetime objects first.
        tz_name = ConfigManager().get_timezone()
        
        return {
            "user_id": "admin", # Forced single-user: admin
            "title": g_event.get("summary", "Untitled Event"),
            "description": g_event.get("description"),
            "start_time": datetime.fromisoformat(start_raw.replace("Z", "+00:00")).timestamp(),
            "end_time": datetime.fromisoformat(end_raw.replace("Z", "+00:00")).timestamp(),
            "timezone": tz_name,
            "location": g_event.get("location"),
            "status": "scheduled" if g_event.get("status") == "confirmed" else "cancelled",
            "source": "google",
            "external_provider": "google",
            "external_event_id": g_event.get("id"),
            "metadata": {
                "etag": g_event.get("etag"),
                "htmlLink": g_event.get("htmlLink")
            }
        }

    def _map_to_google(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Maps internal event data to Google structure."""
        # Convert float timestamps to ISO format if needed
        tz_name = ConfigManager().get_timezone()
        tz = ZoneInfo(tz_name)
        
        start_time = event_data.get("start_time")
        if isinstance(start_time, (int, float)):
            start_time = datetime.fromtimestamp(start_time, tz=tz).isoformat()
            
        end_time = event_data.get("end_time")
        if isinstance(end_time, (int, float)):
            end_time = datetime.fromtimestamp(end_time, tz=tz).isoformat()

        return {
            "summary": event_data.get("title"),
            "description": event_data.get("description"),
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
            "location": event_data.get("location")
        }
