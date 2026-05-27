import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta

logger = logging.getLogger("CalendarCapability")

class CalendarCapability:
    def __init__(self, kernel, config):
        self.kernel = kernel
        self.config = config
        self.name = "calendar"
        self.orchestrator = kernel.orchestrator
        self.calendar_service = self.orchestrator.calendar_service
        self.actions = [
            "calendar.event.list",
            "calendar.event.get",
            "calendar.event.create",
            "calendar.event.delete",
            "calendar.sync"
        ]

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                # re.DOTALL is now supported by the registry
                "pattern": r"\[INTERNAL_EVENT\].*?Type: calendar\.event_starting.*?Payload: ({.*?})",
                "action_id": "notifications.send",
                "handler": self._handle_event_reflex
            }
        ]

    def _handle_event_reflex(self, match) -> Dict[str, Any]:
        try:
            import ast
            payload_str = match.group(1)
            # Use ast.literal_eval to safely parse Python dict string representation
            payload = ast.literal_eval(payload_str)
            title = payload.get("title", "Evento do Calendário")
            event_id = payload.get("event_id")
            start_time = payload.get("start_time")
            return {
                "message": f"Evento '{title}' iniciando.",
                "title": "Lembrete de Calendário",
                "priority": "high",
                "domain": "calendar",
                "as_agent_message": True,
                "message_context": {
                    "event_type": "calendar.event_starting",
                    "event_id": event_id,
                    "title": title,
                    "start_time": start_time,
                    "instruction": "Notifique o usuário em tom de assistente pessoal, de forma elegante e breve. Não diga que recebeu o evento; apenas avise/lembre diretamente."
                },
                "metadata": {
                    "event_type": "calendar.event_starting",
                    "event_id": event_id,
                    "start_time": start_time,
                    "dedupe_key": f"calendar.event_starting:{event_id or title}:{start_time or ''}"
                }
            }
        except Exception as e:
            logger.error(f"Error parsing calendar event reflex payload: {e}")
            return {
                "message": "Um evento do calendário está começando.",
                "title": "Lembrete de Calendário",
                "priority": "high",
                "domain": "calendar",
                "as_agent_message": True,
            }

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        if action_id == "calendar.event.list":
            return self.handle_list(context, **params)
        if action_id == "calendar.event.get":
            return self.handle_get(context, **params)
        if action_id == "calendar.event.create":
            return self.handle_create(context, **params)
        if action_id == "calendar.event.delete":
            return self.handle_delete(context, **params)
        if action_id == "calendar.sync":
            return self.handle_sync(context, **params)
        raise ValueError(f"Unknown action: {action_id}")

    def _get_user_id(self, context: Dict[str, Any]) -> str:
        # Unified User Approach: Always use 'admin' for system calendar.
        # This aligns with the request to treat the system as having a single system-wide user.
        return "admin"

    def _wants_internal_id(self, context: Dict[str, Any], params: Dict[str, Any]) -> bool:
        if bool(params.get("include_internal_id", False)):
            return True
        text = str((context or {}).get("user_input") or "").lower()
        markers = (
            "event_id",
            "uuid",
            "id interno",
            "id do evento",
            "internal id",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _event_summary(event, expose_internal_id: bool = False) -> Dict[str, Any]:
        start_dt = datetime.fromtimestamp(event.start_time)
        data = {
            "short_id": event.short_id,
            "title": event.title,
            "start_time": start_dt.isoformat(),
            "time_local": start_dt.strftime("%H:%M"),
            "source": event.source,
        }
        if expose_internal_id:
            data["event_id"] = event.event_id
        return data

    @staticmethod
    def _event_details(event, expose_internal_id: bool = False) -> Dict[str, Any]:
        data = {
            "short_id": event.short_id,
            "title": event.title,
            "details": event.description,
            "location": event.location,
            "status": event.status,
            "timezone": event.timezone,
            "source": event.source,
            "start_time": datetime.fromtimestamp(event.start_time).isoformat(),
            "end_time": datetime.fromtimestamp(event.end_time).isoformat(),
            "reminders": event.reminders,
        }
        if expose_internal_id:
            data["event_id"] = event.event_id
        return data

    def handle_list(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        user_id = self._get_user_id(context)
        expose_internal_id = self._wants_internal_id(context, kwargs)
        
        start_time = kwargs.get("start_time")
        end_time = kwargs.get("end_time")
        
        # Convert ISO strings to epoch floats if present
        start_float = None
        end_float = None
        
        if start_time:
            try:
                # Handle common ISO formats (Z, +HH:MM, or naive)
                start_float = datetime.fromisoformat(start_time.replace('Z', '+00:00')).timestamp()
            except Exception:
                logger.warning(f"Failed to parse start_time: {start_time}")
                
        if end_time:
            try:
                end_float = datetime.fromisoformat(end_time.replace('Z', '+00:00')).timestamp()
            except Exception:
                logger.warning(f"Failed to parse end_time: {end_time}")

        if not start_float and not end_float:
            # Default to today (00:00 to 23:59 local time)
            from datetime import datetime, time as dt_time
            now = datetime.now()
            start_float = datetime.combine(now.date(), dt_time.min).timestamp()
            end_float = datetime.combine(now.date(), dt_time.max).timestamp()
            logger.info(f"Defaulting calendar list to today: {now.date()}")

        events = self.calendar_service.list_events(user_id, start_time=start_float, end_time=end_float)
        return {
            "ok": True,
            "status": "success" if events else "empty",
            "provider": "internal",
            "data": {
                "count": len(events),
                "events": [
                    self._event_summary(e, expose_internal_id=expose_internal_id) for e in events
                ],
                "note": "Listagem resumida por design. Use calendar.event.get com short_id para detalhes completos."
            }
        }

    def handle_create(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        user_id = self._get_user_id(context)
        title = kwargs.get("title")
        start_time = kwargs.get("start_time")
        end_time = kwargs.get("end_time")
        description = kwargs.get("description")
        details = kwargs.get("details")
        location = kwargs.get("location")
        expose_internal_id = self._wants_internal_id(context, kwargs)

        if details and not description:
            description = details

        if start_time and not end_time:
            try:
                base = datetime.fromisoformat(str(start_time).replace('Z', '+00:00'))
                cfg = self.config or {}
                duration_min = int(cfg.get("default_event_duration_minutes", 30))
                duration_min = max(5, min(720, duration_min))
                end_time = (base + timedelta(minutes=duration_min)).isoformat()
                logger.info(
                    "calendar.create_event auto-filled end_time using default duration | duration_min=%s",
                    duration_min,
                )
            except Exception:
                # Keep original behavior if parsing fails; service/model validators
                # will return a clear error.
                pass

        try:
            event, sync_ok = self.calendar_service.create_event(
                user_id=user_id,
                title=title,
                start_time=start_time,
                end_time=end_time,
                description=description,
                location=location
            )
            return {
                "ok": True,
                "status": "success",
                "sync_status": "synced" if sync_ok else "failed_external",
                "provider": "internal",
                "data": {
                    "event": self._event_summary(event, expose_internal_id=expose_internal_id),
                    "sync_ok": sync_ok
                }
            }
        except Exception as e:
            logger.error(f"Calendar create_event failed: {e}")
            return {
                "ok": False,
                "status": "error",
                "error_details": str(e)
            }

    def handle_get(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        event_ref = kwargs.get("short_id") or kwargs.get("event_id") or kwargs.get("id") or kwargs.get("event_ref")
        expose_internal_id = self._wants_internal_id(context, kwargs)
        event = self.calendar_service.get_event(event_ref)
        if event:
            return {
                "ok": True,
                "status": "success",
                "data": {
                    "event": self._event_details(event, expose_internal_id=expose_internal_id)
                }
            }
        user_id = self._get_user_id(context)
        events = self.calendar_service.list_events(user_id)
        return {
            "ok": False,
            "status": "not_found",
            "error_details": f"Event {event_ref} not found",
            "data": {
                "available_events": [self._event_summary(e, expose_internal_id=expose_internal_id) for e in events[:20]]
            }
        }

    def handle_delete(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        event_ref = kwargs.get("short_id") or kwargs.get("event_id") or kwargs.get("id") or kwargs.get("eventId") or kwargs.get("event_ref")
        user_id = self._get_user_id(context)
        expose_internal_id = self._wants_internal_id(context, kwargs)

        if not event_ref:
            events = self.calendar_service.list_events(user_id)
            return {
                "ok": False,
                "status": "error",
                "provider": "internal",
                "error_details": "Missing required parameter: short_id/event_id",
                "data": {
                    "available_events": [
                        self._event_summary(e, expose_internal_id=expose_internal_id) for e in events[:20]
                    ]
                }
            }

        target_event = self.calendar_service.resolve_event_ref(event_ref)
        success = self.calendar_service.delete_event(event_ref)
        if not success:
            events = self.calendar_service.list_events(user_id)
            return {
                "ok": False,
                "status": "not_found",
                "provider": "internal",
                "error_details": f"Event {event_ref} not found",
                "data": {
                    "event_ref": event_ref,
                    "available_events": [
                        self._event_summary(e, expose_internal_id=expose_internal_id) for e in events[:20]
                    ]
                }
            }

        return {
            "ok": True,
            "status": "success",
            "provider": "internal",
            "data": {
                "deleted": self._event_summary(target_event, expose_internal_id=expose_internal_id) if target_event else {"short_id": str(event_ref)}
            }
        }
    def handle_sync(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        user_id = self._get_user_id(context)
        success = self.calendar_service.sync_all(user_id)
        return {
            "ok": success,
            "status": "success" if success else "failed",
            "sync_status": "synced" if success else "failed",
            "provider": "internal",
            "data": {
                "user_id": user_id
            }
        }

def create_capability(kernel, config):
    return CalendarCapability(kernel, config)
