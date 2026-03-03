import os
from utils.logging_config import get_logger

logger = get_logger("ScratchpadService")

class ScratchpadService:
    def __init__(self, workspace_service=None):
        self.workspace_service = workspace_service
        self.root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    def _get_path(self, session_id: str) -> str:
        if self.workspace_service and session_id:
            return os.path.join(self.workspace_service.get_session_dir(session_id), "scratchpad.md")
        # Fallback to legacy path if no workspace_service or session_id
        legacy_dir = os.path.join(self.root_dir, 'data', 'memory')
        os.makedirs(legacy_dir, exist_ok=True)
        return os.path.join(legacy_dir, 'scratchpad.md')

    def read(self, session_id: str = None) -> str:
        path = self._get_path(session_id)
        if not os.path.exists(path):
            return ""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading scratchpad at {path}: {e}")
            return "Error reading scratchpad."

    def append(self, content: str, session_id: str = None):
        path = self._get_path(session_id)
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f"\n{content}")
            logger.info(f"Content appended to scratchpad: {path}")
        except Exception as e:
            logger.error(f"Error appending to scratchpad at {path}: {e}")

    def update(self, content: str, session_id: str = None):
        path = self._get_path(session_id)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Scratchpad updated: {path}")
        except Exception as e:
            logger.error(f"Error updating scratchpad at {path}: {e}")

    def clear(self, session_id: str = None):
        msg = "# Agentic Scratchpad\n\nNotes cleared.\n"
        self.update(msg, session_id)
