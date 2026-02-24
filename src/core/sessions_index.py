import os
import json
import logging
import datetime
from typing import List, Dict, Optional
from .session import Session

logger = logging.getLogger("SessionIndex")

class SessionIndexManager:
    def __init__(self, sessions_dir: str):
        self.sessions_dir = sessions_dir
        self.index_path = os.path.join(sessions_dir, "index.json")
        self.index: Dict[str, Dict] = {}
        self.load()

    def load(self):
        try:
            if os.path.exists(self.index_path):
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.index = loaded
                else:
                    logger.warning(
                        "Invalid session index format at %s (expected object, got %s). Resetting to empty index.",
                        self.index_path,
                        type(loaded).__name__,
                    )
                    self.index = {}
                    self.save()
                logger.info(f"Session index loaded: {len(self.index)} sessions.")
            else:
                self.index = {}
                logger.info("Session index not found. Created new empty index.")
        except Exception as e:
            logger.error(f"Error loading session index: {e}")
            self.index = {}

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump(self.index, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving session index: {e}")

    def register_session(self, session: Session):
        session_id = session.session_id
        self.index[session_id] = {
            "session_id": session_id,
            "interface": getattr(session, 'source', 'web'),
            "name": getattr(session, 'name', ""),
            "name_generated": getattr(session, 'name_generated', False),
            "profile_picture": getattr(session, 'profile_picture', ""),
            "title": getattr(session, 'title', f"Session {session_id[:8]}"),
            "created_at": datetime.datetime.fromtimestamp(session.created_at).isoformat(),
            "updated_at": datetime.datetime.fromtimestamp(session.last_interaction).isoformat(),
            "last_opened_at": datetime.datetime.fromtimestamp(getattr(session, 'last_opened_at', session.last_interaction)).isoformat(),
            "unread_count": session.get_unread_count("assistant"),
            "path": os.path.join(self.sessions_dir, session_id, "session.json")
        }
        self.save()
    def delete_session(self, session_id: str):
        if session_id in self.index:
            del self.index[session_id]
            self.save()
            logger.info(f"Session {session_id} removed from index.")

    def list_sessions(self, interface: str = "all") -> List[Dict]:
        if interface == "all" or interface == "web": 
            # Include Telegram in Web view so they appear in Dashboard
            sessions = [s for s in self.index.values() if s.get("interface") in ["web", "telegram"]]
        else:
            sessions = [s for s in self.index.values() if s.get("interface") == interface]
        
        # Sort by updated_at (last interaction) for better relevance
        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return sessions

    def get_active_session(self, interface: str = "all") -> Optional[Dict]:
        sessions = self.list_sessions(interface)
        return sessions[0] if sessions else None

    def reconcile(self):
        """
        Scans session folders on disk and syncs with the index.
        """
        logger.info("Starting session index reconciliation...")
        if not os.path.exists(self.sessions_dir):
            return

        # Scan for session.json in subdirectories
        found_ids = set()
        for session_id in os.listdir(self.sessions_dir):
            sess_dir = os.path.join(self.sessions_dir, session_id)
            if not os.path.isdir(sess_dir) or session_id == "__pycache__":
                continue
            
            file_path = os.path.join(sess_dir, "session.json")
            if os.path.exists(file_path):
                found_ids.add(session_id)
                if session_id not in self.index:
                    logger.info(f"Reconciliation: Found missing session {session_id} on disk. Adding to index.")
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            session = Session.from_dict(data)
                            self.register_session(session)
                    except Exception as e:
                        logger.error(f"Error reading session {session_id} during reconciliation: {e}")

        # Optional: Remove index entries that no longer exist on disk
        to_remove = []
        for session_id in self.index:
            if session_id not in found_ids:
                logger.warning(f"Reconciliation: Session {session_id} in index but not on disk. Marking for removal.")
                to_remove.append(session_id)
        
        for sid in to_remove:
            del self.index[sid]
        
        if to_remove:
            self.save()
            
        logger.info("Reconciliation complete.")
