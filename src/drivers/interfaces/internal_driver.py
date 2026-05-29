import logging
from typing import Dict, Any, Optional
from core.identity import PrincipalContext

logger = logging.getLogger("InternalDriver")

class InternalDriver:
    """
    Internal driver for system events and agentic communication.
    Doesn't depend on any external protocol (Telegram, Voice, etc).
    """
    def __init__(self, kernel):
        self.kernel = kernel
        self.interface_id = "system"

    def get_interface_id(self) -> str:
        return self.interface_id

    def start(self):
        logger.info("Internal Driver started.")

    def stop(self):
        logger.info("Internal Driver stopped.")

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "can_receive_internal_events": True,
            "voice_only": False,
            "supports_multimodal": True
        }

    def send_status(self, session_id: str, phase: str, payload: Optional[Dict] = None, model_info: Optional[Dict] = None, **kwargs):
        # Internal status updates can be logged or ignored depending on the need
        logger.debug(f"Internal Status for {session_id}: {phase} | {payload}")

    def send_response(self, text: str, target: str = None, is_chunk: bool = False, attachments: list = None, model_info=None):
        # Route to the real interface driver when target is a user session.
        # This prevents "notification delivered only in internal logs".
        if target and hasattr(self.kernel, "_resolve_driver_for_session"):
            try:
                driver = self.kernel._resolve_driver_for_session(target)
                if driver and driver is not self and hasattr(driver, "send_response"):
                    driver.send_response(
                        text,
                        target=target,
                        is_chunk=is_chunk,
                        attachments=attachments,
                        model_info=model_info,
                    )
                    if hasattr(driver, "send_complete"):
                        driver.send_complete(target)
                    logger.info(f"Internal response routed to {target} via {driver.__class__.__name__}.")
                    return
            except Exception as e:
                logger.debug(f"Failed to route internal response to {target}: {e}")

        logger.info(f"Internal Response to {target}: {text[:100]}...")

    def send_complete(self, session_id: str):
        logger.debug(f"Internal processing complete for {session_id}")

    def inject_event(self, event_or_text: Any, session_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """
        Injects an event into the kernel pipeline.
        Supports both raw text and AgentEvent objects.
        """
        from services.agent_events.models import AgentEvent
        
        if isinstance(event_or_text, AgentEvent):
            event = event_or_text
            text = event.as_text()
            
            # Resolve target session
            if session_id:
                target_session = session_id
            elif event.target_session_id:
                target_session = event.target_session_id
            else:
                # Resolve domain via orchestrator services
                domain = self.kernel.orchestrator.domain_resolver.resolve_domain(event)
                # Ensure the system session exists for this domain
                session = self.kernel.orchestrator.system_session_registry.ensure_domain_session(domain)
                target_session = session.session_id
                
            user_data = {**(metadata or {}), **event.metadata, "__agent_event": event.to_dict()}
            sender_name = str(event.source or "system")
        else:
            text = str(event_or_text)
            target_session = session_id or "system.attention"
            user_data = metadata or {}
            sender_name = "system"

        context = PrincipalContext(
            interface=self.interface_id,
            sender_id="system",
            session_id=target_session,
            sender_name=sender_name,
            roles=["system_event", "notification_event"] if isinstance(event_or_text, AgentEvent) else ["system_event"],
        )
        
        return self.kernel.process_input(
            text=text,
            driver_instance=self,
            user_id=target_session,
            user_data=user_data,
            context=context,
            is_internal=True
        )
