from typing import Dict, Any, List, Optional, Tuple
from .base import SkillBase
import logging
import difflib
import hashlib
import re

logger = logging.getLogger("SkillRegistry")

class SkillRegistry:
    def __init__(self):
        self.skills: Dict[str, SkillBase] = {}
        self.action_map: Dict[str, SkillBase] = {}
        self.schemas: Dict[str, dict] = {} # skill_name -> schema

    def _is_legacy_blocked_action(self, action_id: str, skill: Optional[SkillBase] = None) -> bool:
        if not action_id:
            return False
        aid = str(action_id).strip().lower()
        parts = aid.split(".")
        if len(parts) >= 3 and parts[0] == "browser" and parts[1] in {"automator", "controller"}:
            return True
        sk = skill or self.action_map.get(action_id)
        contract = getattr(sk, "_contract", {}) if sk else {}
        if isinstance(contract, dict):
            if bool(contract.get("blocked", False)) and bool(contract.get("legacy", False)):
                return True
        return False

    def _is_hidden_from_discovery(self, action_id: str, skill: Optional[SkillBase] = None) -> bool:
        sk = skill or self.action_map.get(action_id)
        contract = getattr(sk, "_contract", {}) if sk else {}
        if not isinstance(contract, dict):
            return False
        if bool(contract.get("hidden_from_discovery", False)):
            return True
        if bool(contract.get("legacy", False)) and bool(contract.get("blocked", False)):
            return True
        return False

    def _is_discoverable_action(self, action_id: str, skill: Optional[SkillBase] = None) -> bool:
        return not self._is_hidden_from_discovery(action_id, skill) and not self._is_legacy_blocked_action(action_id, skill)

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
        if self._is_legacy_blocked_action(action_id):
            return {
                "ok": False,
                "status": "error",
                "error": "SKILL_REMOVED_USE_BROWSER_CONTROL",
                "error_code": "SKILL_REMOVED_USE_BROWSER_CONTROL",
                "text": "Skill removed. Use browser.control.run or browser.control.step.",
            }
        skill = self.get_skill_for_action(action_id)
        if skill:
            try:
                return skill.execute(action_id, params, context)
            except Exception as e:
                logger.error(f"Error executing action '{action_id}' in skill '{skill.name}': {e}")
                return f"Error executing {action_id}: {str(e)}"
        
        return f"Unknown action: {action_id}"

    def list_actions(self) -> List[str]:
        return [a for a, s in self.action_map.items() if self._is_discoverable_action(a, s)]

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
        actions = [a for a, s in self.action_map.items() if self._is_discoverable_action(a, s)]
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

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        tokens = re.findall(r"[a-zA-Z0-9_]+", (text or "").lower())
        return [t for t in tokens if len(t) > 2]

    def _lexical_score(self, user_input: str, action_id: str, description: str) -> Tuple[float, str]:
        tokens_input = self._tokenize(user_input)
        if not tokens_input:
            return 0.0, "empty_input"

        corpus = f"{action_id} {description}".strip()
        tokens_action = self._tokenize(corpus)
        if not tokens_action:
            return 0.0, "empty_action_tokens"

        overlap = len(set(tokens_input) & set(tokens_action))
        overlap_ratio = overlap / max(1, len(set(tokens_input)))

        action_suffix = action_id.split(".")[-1]
        lower_input = (user_input or "").lower()
        exact_boost = 0.25 if action_suffix in lower_input else 0.0
        dotless_boost = 0.20 if action_id.replace(".", " ") in lower_input else 0.0
        score = min(1.0, overlap_ratio + exact_boost + dotless_boost)
        return score, f"overlap={overlap_ratio:.2f}, exact={exact_boost:.2f}, dotless={dotless_boost:.2f}"

    def get_summary(self, allowed_actions: Optional[List[str]] = None) -> str:
        """Returns a summarized list of actions and descriptions.
        If allowed_actions is provided, only those actions are included.
        """
        allowed_set = set(allowed_actions) if allowed_actions is not None else None
        summary = []
        for action_id, skill in self.action_map.items():
            if not self._is_discoverable_action(action_id, skill):
                continue
            if allowed_set is not None and action_id not in allowed_set:
                continue

            desc = self._describe_action(action_id, skill)
            summary.append(f"- `{action_id}`: {desc}")
        return "\n".join(sorted(summary))

    def get_compact_manifest(self, allowed_actions: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Returns a compact action manifest for prompt injection with minimal token footprint.
        """
        allowed_set = set(allowed_actions) if allowed_actions is not None else None
        actions: List[str] = []
        namespaces: set[str] = set()
        for action_id in sorted(self.action_map.keys()):
            skill = self.action_map.get(action_id)
            if not self._is_discoverable_action(action_id, skill):
                continue
            if allowed_set is not None and action_id not in allowed_set:
                continue
            actions.append(action_id)
            ns = ".".join(action_id.split(".")[:2]) if "." in action_id else action_id
            namespaces.add(ns)

        digest = hashlib.sha1("\n".join(actions).encode("utf-8")).hexdigest()[:12] if actions else "none"
        return {
            "count": len(actions),
            "hash": digest,
            "namespaces": sorted(namespaces),
            "actions": actions,
        }

    def get_focus_actions(
        self,
        user_input: str,
        allowed_actions: Optional[List[str]] = None,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        """
        Returns the most relevant actions for the current user input.
        """
        allowed_set = set(allowed_actions) if allowed_actions is not None else None
        ranked: List[Tuple[float, str, str]] = []
        for action_id, skill in self.action_map.items():
            if not self._is_discoverable_action(action_id, skill):
                continue
            if allowed_set is not None and action_id not in allowed_set:
                continue
            desc = self._describe_action(action_id, skill)
            score, _ = self._lexical_score(user_input or "", action_id, desc)
            ranked.append((score, action_id, desc))

        ranked.sort(key=lambda x: (-x[0], x[1]))
        out: List[Dict[str, Any]] = []
        for score, action_id, desc in ranked[: max(1, int(limit or 1))]:
            out.append(
                {
                    "id": action_id,
                    "description": desc,
                    "score": round(float(score), 3),
                }
            )
        return out

    def get_catalog(
        self,
        allowed_actions: Optional[List[str]] = None,
        include_descriptions: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Returns structured catalog entries for skill discovery actions.
        """
        allowed_set = set(allowed_actions) if allowed_actions is not None else None
        out: List[Dict[str, Any]] = []
        for action_id in sorted(self.action_map.keys()):
            skill = self.action_map.get(action_id)
            if not self._is_discoverable_action(action_id, skill):
                continue
            if allowed_set is not None and action_id not in allowed_set:
                continue
            metadata = self.get_action_metadata(action_id)
            row: Dict[str, Any] = {
                "id": action_id,
                "namespace": ".".join(action_id.split(".")[:2]) if "." in action_id else action_id,
                "risk_level": str(metadata.get("risk_level") or "unknown"),
            }
            if include_descriptions:
                row["description"] = str(metadata.get("description") or "No description available.")
            out.append(row)
        return out
