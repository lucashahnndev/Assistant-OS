import os
import json
import logging
import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("WorkspaceService")

class WorkspaceService:
    """
    Manages dedicated working directories for agent sessions to anchor context.
    """
    def __init__(self, base_dir: str = None, sessions_dir: str = None):
        # Fallback to defaults relative to AOSD data dir if not specifically provided
        from config.manager import ConfigManager
        aosd_data_dir = ConfigManager.get_data_dir()
        
        self.base_dir = os.path.abspath(base_dir if base_dir else os.path.join(aosd_data_dir, "workspace"))
        self.sessions_dir = os.path.abspath(sessions_dir if sessions_dir else os.path.join(aosd_data_dir, "sessions"))
        self.output_dir = os.path.join(self.base_dir, "aosd-output")
        
        # Initialize basic structure
        for d in [self.base_dir, self.sessions_dir, self.output_dir]:
            os.makedirs(d, exist_ok=True)
            
        # Initialize output subcategories
        for sub in ["exports", "reports", "clips"]:
            os.makedirs(os.path.join(self.output_dir, sub), exist_ok=True)

    def get_workspace_dir(self, session_id: str = None) -> str:
        """Returns the absolute path to the shared workspace."""
        return self.base_dir
        
    def get_session_dir(self, session_id: str) -> str:
        """Returns the absolute path to a session-specific data directory."""
        path = os.path.join(self.sessions_dir, session_id)
        os.makedirs(path, exist_ok=True)
        return path

    def write_task_file(self, session_id: str, filename: str, content: str):
        """Writes a metadata file inside the session folder (e.g. task.md, plan.md)."""
        sess_dir = self.get_session_dir(session_id)
        file_path = os.path.join(sess_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return file_path

    def read_task_file(self, session_id: str, filename: str) -> Optional[str]:
        """Reads a metadata file from the session folder."""
        sess_dir = self.get_session_dir(session_id)
        file_path = os.path.join(sess_dir, filename)
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def get_workspace_summary(self, session_id: str) -> str:
        """
        Returns a summary of session metadata and shared workspace contents.
        """
        summary = []
        
        # Priority metadata from session folder
        anchors = ["task.md", "plan.md", "notes.md"]
        for anchor in anchors:
            content = self.read_task_file(session_id, anchor)
            if content:
                summary.append(f"--- Session {anchor} ---\n{content}")
        
        # List files from shared workspace (excluding technical junk)
        ws_dir = self.get_workspace_dir()
        if os.path.exists(ws_dir):
            all_items = os.listdir(ws_dir)
            # Filter out aosd-output and other technical-looking files if any remain
            human_files = [f for f in all_items if f != "aosd-output" and not f.startswith(".")]
            if human_files:
                summary.append(f"Human Workspace Files: {', '.join(human_files)}")
            
            # List outputs
            if os.path.exists(self.output_dir):
                outputs = []
                for sub in os.listdir(self.output_dir):
                    sub_path = os.path.join(self.output_dir, sub)
                    if os.path.isdir(sub_path):
                        files = os.listdir(sub_path)
                        if files:
                            outputs.append(f"{sub}/: {', '.join(files)}")
                if outputs:
                    summary.append(f"Assistant Outputs:\n" + "\n".join(outputs))
            
        return "\n\n".join(summary) if summary else "No context available."

    def save_artifact(self, scope: str, session_id: str, filename: str, content: Any, category: str = None) -> str:
        """
        Centrally routes artifacts to either 'session' (technical) or 'workspace' (human).
        """
        import re
        
        if scope == "workspace":
            # Validation: Block technical-looking filenames in workspace
            # Rules: No UUIDs, no 'tmp', no 'run_', no long random hex
            uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
            tmp_pattern = r'(^tmp_|_tmp$|cache|hex_[0-9a-f]{4,})'
            
            if re.search(uuid_pattern, filename, re.IGNORECASE) or re.search(tmp_pattern, filename, re.IGNORECASE):
                logger.warning(f"BLOCKED: Intent to save technical artifact '{filename}' in workspace scope.")
                # Force route to session instead of workspace to avoid pollution
                scope = "session"
            else:
                target_dir = os.path.join(self.output_dir, category if category else "exports")
                os.makedirs(target_dir, exist_ok=True)
                path = os.path.join(target_dir, filename)
                
        if scope == "session":
            if not session_id:
                raise ValueError("session_id is required for session-scoped artifacts.")
            target_dir = self.get_session_dir(session_id)
            if category:
                target_dir = os.path.join(target_dir, category)
                os.makedirs(target_dir, exist_ok=True)
            path = os.path.join(target_dir, filename)

        # Write content
        mode = "wb" if isinstance(content, bytes) else "w"
        encoding = None if isinstance(content, bytes) else "utf-8"
        
        with open(path, mode, encoding=encoding) as f:
            f.write(content)
            
        logger.info(f"Artifact saved: {path} (scope: {scope})")
        return path
