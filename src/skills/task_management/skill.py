from ..base import SkillBase
from typing import Dict, Any, List
import os

class TaskSkill(SkillBase):
    def __init__(self, kernel=None, config=None):
        self.kernel = kernel
        self.config = config or {}
        self._namespace = "task"

    @property
    def name(self) -> str: return "task"

    @property
    def actions(self) -> List[str]: return ["notes", "specialist"]

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        session = context.get("session")
        orch = getattr(self.kernel, "orchestrator", None) if self.kernel else None
        
        if action == "notes":
            ss = getattr(orch, "scratchpad_service", None) if orch else None
            if not ss: return "ScratchpadService missing."
            cmd = params.get("command", "read")
            content = params.get("content", "")
            sid = session.session_id if session else None
            if cmd == 'read': return ss.read(sid)
            if cmd == 'append' and content: ss.append(content, sid); return "Appended."
            if cmd == 'update' and content: ss.update(content, sid); return "Updated."
            if cmd == 'clear': ss.clear(sid); return "Cleared."
            return "Invalid notes command."

        elif action == "specialist":
            sm = getattr(orch, "specialist_manager", None) if orch else None
            if not sm: return "SpecialistManager missing."
            name = params.get("name")
            if name in ['none', 'clear']:
                if session: session.context['active_specialist'] = None
                return "Specialist deactivated."
            if name.lower() in sm.list_specialists():
                if session: session.context['active_specialist'] = name.lower()
                return f"Specialist '{name}' activated."
            return "Specialist not found."

        return f"Unknown task action: {action_id}"
