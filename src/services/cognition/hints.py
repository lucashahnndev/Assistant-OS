from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .models import CognitiveState, _clip_text, _normalize_lines


_ACTION_RE = re.compile(r"\b([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)(?:\.[a-z][a-z0-9_]*)?\b")


@dataclass
class CognitiveBrokerHints:
    primary_task_id: str = ""
    mission_label: str = ""
    reasoning_mode: str = "standard"
    attention_mode: str = "foreground"
    open_loop_type: str = ""
    blocker_active: bool = False
    approval_pending: bool = False
    troubleshooting_active: bool = False
    hot_action_namespace: str = ""
    hint_categories: List[str] = field(default_factory=list)
    signal_strength: str = "none"
    hint_summary: List[str] = field(default_factory=list)
    hint_suppressed: bool = False
    suppression_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CognitiveBrokerHintBuilder:
    def build(self, state: CognitiveState) -> CognitiveBrokerHints:
        mission_label = _clip_text(state.mission.objective, 80)
        primary_task_id = str(state.focus.primary_task_id or "")
        reasoning_mode = str(state.focus.reasoning_mode or "standard")
        attention_mode = str(state.focus.attention_mode or "foreground")
        blocker_active = bool(state.blockers)
        approval_pending = any("approval" in item.lower() or "pending confirmation" in item.lower() for item in state.open_loops + state.blockers)
        troubleshooting_active = reasoning_mode == "troubleshooting" or blocker_active
        open_loop_type = self._classify_open_loop(state.open_loops)
        hot_action_namespace = self._extract_hot_namespace(state)

        summary: List[str] = []
        if primary_task_id:
            summary.append(f"task={primary_task_id}")
        if mission_label:
            summary.append(f"mission={mission_label}")
        if open_loop_type:
            summary.append(f"loop={open_loop_type}")
        if troubleshooting_active:
            summary.append("mode=troubleshooting")
        if approval_pending:
            summary.append("approval=pending")
        if hot_action_namespace:
            summary.append(f"ns={hot_action_namespace}")

        hint_categories: List[str] = []
        if primary_task_id:
            hint_categories.append("task_focus")
        if mission_label:
            hint_categories.append("mission")
        if open_loop_type:
            hint_categories.append("open_loop")
        if blocker_active:
            hint_categories.append("blocker")
        if troubleshooting_active:
            hint_categories.append("troubleshooting")
        if approval_pending:
            hint_categories.append("approval")
        if hot_action_namespace:
            hint_categories.append("action_namespace")

        signal_score = len(hint_categories)
        signal_strength = "high" if signal_score >= 4 else ("medium" if signal_score >= 2 else ("low" if signal_score == 1 else "none"))
        suppression_reasons: List[str] = []
        hint_suppressed = False
        if signal_strength == "none":
            hint_suppressed = True
            suppression_reasons.append("no_signal")
        if signal_strength == "low" and hint_categories in (["mission"], ["task_focus"]):
            hint_suppressed = True
            suppression_reasons.append("low_signal_single_axis")
        if signal_strength == "low" and not (open_loop_type or blocker_active or approval_pending or troubleshooting_active or hot_action_namespace):
            hint_suppressed = True
            suppression_reasons.append("low_signal_context")

        return CognitiveBrokerHints(
            primary_task_id=primary_task_id,
            mission_label=mission_label,
            reasoning_mode=reasoning_mode,
            attention_mode=attention_mode,
            open_loop_type=open_loop_type,
            blocker_active=blocker_active,
            approval_pending=approval_pending,
            troubleshooting_active=troubleshooting_active,
            hot_action_namespace=hot_action_namespace,
            hint_categories=_normalize_lines(hint_categories, max_items=6, max_chars=40),
            signal_strength=signal_strength,
            hint_summary=_normalize_lines(summary, max_items=6, max_chars=80),
            hint_suppressed=hint_suppressed,
            suppression_reasons=_normalize_lines(suppression_reasons, max_items=4, max_chars=60),
        )

    @staticmethod
    def _classify_open_loop(items: List[str]) -> str:
        for item in items:
            text = str(item or "").lower()
            if "approval" in text or "pending confirmation" in text:
                return "approval"
            if "clarification" in text or "awaiting user" in text:
                return "clarification"
            if "blocked" in text:
                return "blocker"
            if "resume" in text:
                return "resume"
        return ""

    @staticmethod
    def _extract_hot_namespace(state: CognitiveState) -> str:
        candidates = list(state.checkpoints) + list(state.working_set) + [state.focus.primary_summary]
        for item in candidates:
            match = _ACTION_RE.search(str(item or ""))
            if match:
                return str(match.group(1) or "")
        return ""
