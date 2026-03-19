import logging
from typing import Optional
from services.agent_events.models import AgentEvent

logger = logging.getLogger("DomainSessionResolver")

class DomainSessionResolver:
    """
    Resolves domains from AgentEvents to route them to the correct system session.
    """
    def resolve_domain(self, event: AgentEvent) -> str:
        """
        Logic: Use the namespace of event_type (prefix before first dot).
        Fallback to source or 'attention'.
        """
        if event.event_type and "." in event.event_type:
            domain = event.event_type.split(".")[0]
            if domain:
                return domain
        
        if event.source:
            # Check if source contains hints, or use source as domain
            return event.source.replace("_service", "").replace("_monitor", "")
            
        return "attention"

    def resolve_target_session_id(self, event: AgentEvent) -> str:
        """
        Determines the target session ID for an event.
        Priority: explicit target_session_id -> resolved domain.
        """
        if event.target_session_id:
            return event.target_session_id
            
        domain = self.resolve_domain(event)
        if domain == "attention":
            return "system.attention"
        return f"system.{domain}"
