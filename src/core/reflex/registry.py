import re
from dataclasses import dataclass
from typing import Callable, Any, List, Optional
from core.resolution.action_plan import ActionPlan

@dataclass
class ReflexRule:
    pattern: str
    action_id: str
    priority: int = 0
    # Returns args dict if matched
    handler: Optional[Callable[[re.Match], dict]] = None

class ReflexRegistry:
    def __init__(self):
        self.rules: List[ReflexRule] = []
        self._compiled_rules = []
        self._rule_fingerprints = set()

    def register(self, pattern: str, action_id: str, priority: int = 0, handler: Optional[Callable] = None):
        handler_id = None
        if handler is not None:
            handler_id = getattr(handler, "__qualname__", None) or getattr(handler, "__name__", None) or str(handler)
        fp = (str(pattern or ""), str(action_id or ""), int(priority or 0), str(handler_id or ""))
        if fp in self._rule_fingerprints:
            return
        self._rule_fingerprints.add(fp)
        rule = ReflexRule(pattern, action_id, priority, handler)
        self.rules.append(rule)
        # Sort by priority (higher first)
        self.rules.sort(key=lambda x: x.priority, reverse=True)
        self._compile()

    def _compile(self):
        self._compiled_rules = []
        for rule in self.rules:
            self._compiled_rules.append((re.compile(rule.pattern, re.IGNORECASE | re.DOTALL), rule))

    def match(self, text: str) -> Optional[ActionPlan]:
        for regex, rule in self._compiled_rules:
            match = regex.search(text)
            if match:
                args = rule.handler(match) if rule.handler else {}
                return ActionPlan(
                    action_id=rule.action_id,
                    args=args,
                    confidence=1.0,
                    source="reflex"
                )
        return None
