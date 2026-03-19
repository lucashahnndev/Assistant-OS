import logging
import os
from typing import List, Dict, Optional
from core.session import Session, SESSION_TYPE_SYSTEM
from core.identity import PrincipalContext, AccessStatus

logger = logging.getLogger("SystemSessionRegistry")

class SystemSessionRegistry:
    """
    Manages idempotent creation and retrieval of system sessions by domain.
    """
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.sessions_index = orchestrator.sessions_index

    def resolve_system_session_id(self, domain: str) -> str:
        """Returns the canonical naming for a domain session."""
        if domain == "attention":
            return "system.attention"
        return f"system.{domain}"

    def ensure_domain_session(self, domain: str) -> Session:
        """
        Idempotently ensures a system session for the given domain exists.
        Integrates with the orchestrator to load or create.
        """
        session_id = self.resolve_system_session_id(domain)
        
        # 1. Try to get existing robustly
        session = self.orchestrator.get_session_robust(session_id)
        
        # 2. If not found or not system, ensure it's created correctly
        if not session or session.session_type != SESSION_TYPE_SYSTEM:
            logger.info(f"Ensuring creation of system session for domain: {domain}")
            # Interface resolution via Kernel IoC if available
            interface = "system"
            if hasattr(self.orchestrator, "kernel") and self.orchestrator.kernel:
                interface = "system" # Force system interface for these
            
            session = self.orchestrator.create_session(
                session_id, 
                interface=interface, 
                session_type=SESSION_TYPE_SYSTEM
            )
            session.domain = domain
            
            # Auto-assign specialist based on domain if it exists
            if domain:
                specialist_manager = getattr(self.orchestrator, "specialist_manager", None)
                if specialist_manager and domain in specialist_manager.list_specialists():
                    session.context["active_specialist"] = domain
                    logger.info(f"Auto-assigned specialist '{domain}' to system session '{session_id}'")
            
            self.orchestrator._save_session(session)
            
        return session

    def list_system_sessions(self) -> List[Dict]:
        """Returns list of all system sessions in the index."""
        return self.sessions_index.list_sessions(session_type=SESSION_TYPE_SYSTEM)
