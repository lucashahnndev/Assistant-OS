from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


COGNITIVE_STATE_VERSION = "cognitive.v1"


def _clip_text(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _normalize_lines(items: List[Any], *, max_items: int, max_chars: int = 180) -> List[str]:
    seen = set()
    output: List[str] = []
    for item in items:
        text = _clip_text(item, max_chars)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
        if len(output) >= max_items:
            break
    return output


@dataclass
class MissionState:
    objective: str = ""
    status: str = "active"


@dataclass
class FocusState:
    primary_task_id: Optional[str] = None
    primary_summary: str = ""
    reasoning_mode: str = "standard"
    attention_mode: str = "foreground"


@dataclass
class ProvenanceState:
    sources: List[str] = field(default_factory=list)
    broker_evidence_used: bool = False


@dataclass
class CognitiveState:
    version: str = COGNITIVE_STATE_VERSION
    updated_at: int = field(default_factory=lambda: int(time.time()))
    turn_id: int = 0
    mission: MissionState = field(default_factory=MissionState)
    focus: FocusState = field(default_factory=FocusState)
    agenda: List[str] = field(default_factory=list)
    open_loops: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    working_set: List[str] = field(default_factory=list)
    checkpoints: List[str] = field(default_factory=list)
    recent_progress: List[str] = field(default_factory=list)
    watchpoints: List[str] = field(default_factory=list)
    provenance: ProvenanceState = field(default_factory=ProvenanceState)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CognitiveState":
        payload = data if isinstance(data, dict) else {}
        mission_raw = payload.get("mission") if isinstance(payload.get("mission"), dict) else {}
        focus_raw = payload.get("focus") if isinstance(payload.get("focus"), dict) else {}
        provenance_raw = payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
        return cls(
            version=str(payload.get("version") or COGNITIVE_STATE_VERSION),
            updated_at=int(payload.get("updated_at") or int(time.time())),
            turn_id=int(payload.get("turn_id") or 0),
            mission=MissionState(
                objective=_clip_text(mission_raw.get("objective"), 220),
                status=str(mission_raw.get("status") or "active"),
            ),
            focus=FocusState(
                primary_task_id=str(focus_raw.get("primary_task_id")) if focus_raw.get("primary_task_id") is not None else None,
                primary_summary=_clip_text(focus_raw.get("primary_summary"), 220),
                reasoning_mode=str(focus_raw.get("reasoning_mode") or "standard"),
                attention_mode=str(focus_raw.get("attention_mode") or "foreground"),
            ),
            agenda=_normalize_lines(list(payload.get("agenda") or []), max_items=6, max_chars=180),
            open_loops=_normalize_lines(list(payload.get("open_loops") or []), max_items=6, max_chars=180),
            blockers=_normalize_lines(list(payload.get("blockers") or []), max_items=6, max_chars=180),
            constraints=_normalize_lines(list(payload.get("constraints") or []), max_items=6, max_chars=180),
            assumptions=_normalize_lines(list(payload.get("assumptions") or []), max_items=4, max_chars=160),
            decisions=_normalize_lines(list(payload.get("decisions") or []), max_items=4, max_chars=180),
            working_set=_normalize_lines(list(payload.get("working_set") or []), max_items=5, max_chars=160),
            checkpoints=_normalize_lines(list(payload.get("checkpoints") or []), max_items=4, max_chars=180),
            recent_progress=_normalize_lines(list(payload.get("recent_progress") or []), max_items=4, max_chars=180),
            watchpoints=_normalize_lines(list(payload.get("watchpoints") or []), max_items=5, max_chars=180),
            provenance=ProvenanceState(
                sources=_normalize_lines(list(provenance_raw.get("sources") or []), max_items=8, max_chars=60),
                broker_evidence_used=bool(provenance_raw.get("broker_evidence_used")),
            ),
        )


@dataclass
class CognitiveProjection:
    focus_lines: List[str] = field(default_factory=list)
    background_lines: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "focus_lines": copy.deepcopy(self.focus_lines),
            "background_lines": copy.deepcopy(self.background_lines),
        }


@dataclass
class CognitiveDiagnostics:
    version: str = COGNITIVE_STATE_VERSION
    phase: str = "reconcile"
    reconciled_at: int = field(default_factory=lambda: int(time.time()))
    turn_id: int = 0
    primary_task_id: str = ""
    agenda_count: int = 0
    open_loops_count: int = 0
    blockers_count: int = 0
    constraints_count: int = 0
    decisions_count: int = 0
    working_set_count: int = 0
    changed_fields: List[str] = field(default_factory=list)
    commit_performed: bool = False
    decisions_added: int = 0
    checkpoints_added: int = 0
    progress_added: int = 0
    open_loops_added: int = 0
    open_loops_closed: int = 0
    blockers_added: int = 0
    blockers_cleared: int = 0
    watchpoints_added: int = 0
    normalized_outcome_type: str = ""
    outcome_type_generic_fallback_used: bool = False
    commit_coverage_path: str = ""
    broker_hints_generated: bool = False
    broker_hint_summary: List[str] = field(default_factory=list)
    hint_categories_generated: List[str] = field(default_factory=list)
    hint_applied: bool = False
    hint_ignored: bool = False
    hinted_domains: List[str] = field(default_factory=list)
    hint_impact_summary: List[str] = field(default_factory=list)
    ranking_changed_by_hint: bool = False
    hint_low_signal: bool = False
    hint_suppressed: bool = False
    cognitive_fields_populated: List[str] = field(default_factory=list)
    cognitive_fields_changed: List[str] = field(default_factory=list)
    cognitive_fields_projected: List[str] = field(default_factory=list)
    cognitive_fields_derived_from_outcome: List[str] = field(default_factory=list)
    projection_field_sizes: Dict[str, int] = field(default_factory=dict)
    projection_non_empty: bool = False
    strategic_updates_summary: List[str] = field(default_factory=list)
    commit_signal_strength: str = "none"
    commit_noise_suppressed_count: int = 0
    outcome_refined: bool = False
    strategic_field_pruned_count: int = 0
    effectiveness_flags: List[str] = field(default_factory=list)
    planner_relevance_signal: bool = False
    fallback_used: bool = False
    fallback_mode: str = "none"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def default_cognitive_state() -> CognitiveState:
    return CognitiveState()


def default_cognitive_state_dict() -> Dict[str, Any]:
    return default_cognitive_state().to_dict()


def coerce_cognitive_state(data: Optional[Dict[str, Any]]) -> CognitiveState:
    return CognitiveState.from_dict(data)
