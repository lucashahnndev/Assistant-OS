from typing import Dict, Any, List, Optional
from .base import SkillBase
import logging
import difflib

logger = logging.getLogger("SkillRegistry")

class SkillRegistry:
    def __init__(self):
        self.skills: Dict[str, SkillBase] = {}
        self.action_map: Dict[str, SkillBase] = {}
        self.schemas: Dict[str, dict] = {} # skill_name -> schema

    def register(self, skill: SkillBase):
        self.skills[skill.name] = skill
        namespace = getattr(skill, "_namespace", None)
        
        for action in skill.actions:
            # If skill provides full namespaced IDs, use them. 
            # Otherwise, if it has a namespace, prepend it.
            full_id = action
            if namespace and not action.startswith(f"{namespace}."):
                full_id = f"{namespace}.{action}"
            
            if full_id in self.action_map:
                logger.warning(f"Action '{full_id}' is already registered by skill '{self.action_map[full_id].name}'. Overwriting with '{skill.name}'.")
                
            self.action_map[full_id] = skill
            logger.debug(f"Registered action '{full_id}' for skill '{skill.name}'")

    def get_skill_for_action(self, action_id: str) -> Optional[SkillBase]:
        return self.action_map.get(action_id)

    def dispatch(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        skill = self.get_skill_for_action(action_id)
        if skill:
            try:
                return skill.execute(action_id, params, context)
            except Exception as e:
                logger.error(f"Error executing action '{action_id}' in skill '{skill.name}': {e}")
                return f"Error executing {action_id}: {str(e)}"
        
        return f"Unknown action: {action_id}"

    def list_actions(self) -> List[str]:
        return list(self.action_map.keys())

    def resolve_action_id(self, action_id: str) -> Optional[str]:
        """
        Resolves legacy/partial/typo action ids to a registered full action id.
        Returns None if resolution is ambiguous or impossible.
        """
        if not action_id:
            return None

        normalized = action_id.strip().lower().replace(" ", ".")

        # 1) Exact match
        if normalized in self.action_map:
            return normalized

        actions = list(self.action_map.keys())
        if not actions:
            return None

        # 2) Local-id match (suffix) when unique
        local_matches = [a for a in actions if a.split(".")[-1] == normalized]
        if len(local_matches) == 1:
            return local_matches[0]

        # 3) Prefix-like match when unique
        prefix_matches = [a for a in actions if a.startswith(normalized) or normalized.startswith(a)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

        # 4) Close match (typo correction)
        close = difflib.get_close_matches(normalized, actions, n=1, cutoff=0.82)
        if close:
            return close[0]

        return None

    def suggest_actions(self, action_id: str, limit: int = 3) -> List[str]:
        """Returns nearest registered action ids for user-facing diagnostics."""
        if not action_id:
            return []
        normalized = action_id.strip().lower().replace(" ", ".")
        actions = list(self.action_map.keys())
        return difflib.get_close_matches(normalized, actions, n=max(1, limit), cutoff=0.5)

    def _find_action_contract_entry(self, action_id: str, skill: SkillBase) -> Optional[dict]:
        try:
            if not hasattr(skill, "_contract") or not isinstance(skill._contract, dict):
                return None

            actions = skill._contract.get("actions")
            local_id = action_id.split(".")[-1]

            if isinstance(actions, list):
                for action_entry in actions:
                    if not isinstance(action_entry, dict):
                        continue
                    contract_id = action_entry.get("id")
                    handler = action_entry.get("handler")
                    name = action_entry.get("name")
                    if contract_id == action_id or handler == local_id or name == local_id:
                        return action_entry

            if isinstance(actions, dict):
                action_data = actions.get(local_id)
                if isinstance(action_data, dict):
                    return action_data
        except Exception as e:
            logger.warning(f"Error parsing contract entry for action '{action_id}': {e}")
        return None

    def get_action_metadata(self, action_id: str) -> Dict[str, Any]:
        """Returns best-effort metadata from a skill contract for an action."""
        skill = self.get_skill_for_action(action_id)
        if not skill:
            return {}

        action_entry = self._find_action_contract_entry(action_id, skill)
        if not action_entry:
            return {}
        return dict(action_entry)

    def _describe_action(self, action_id: str, skill: SkillBase) -> str:
        """Best-effort description from contract metadata."""
        desc = "No description available."
        action_entry = self._find_action_contract_entry(action_id, skill)
        if action_entry:
            desc = action_entry.get("description", desc)
        return desc

    def get_summary(self, allowed_actions: Optional[List[str]] = None) -> str:
        """Returns a summarized list of actions and descriptions.
        If allowed_actions is provided, only those actions are included.
        """
        allowed_set = set(allowed_actions) if allowed_actions is not None else None
        summary = []
        for action_id, skill in self.action_map.items():
            if allowed_set is not None and action_id not in allowed_set:
                continue

            desc = self._describe_action(action_id, skill)
            summary.append(f"- `{action_id}`: {desc}")
        return "\n".join(sorted(summary))
