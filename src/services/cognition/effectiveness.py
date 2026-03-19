from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from .models import CognitiveProjection, CognitiveState, _clip_text


STRATEGIC_FIELDS: Sequence[str] = (
    "mission",
    "focus",
    "open_loops",
    "blockers",
    "constraints",
    "watchpoints",
    "decisions",
    "checkpoints",
    "recent_progress",
)


def collect_populated_fields(state: CognitiveState) -> List[str]:
    populated: List[str] = []
    if _clip_text(state.mission.objective, 220) and str(state.mission.objective).strip().lower() != "standby":
        populated.append("mission")
    if state.focus.primary_task_id or _clip_text(state.focus.primary_summary, 220):
        populated.append("focus")
    if state.open_loops:
        populated.append("open_loops")
    if state.blockers:
        populated.append("blockers")
    if state.constraints:
        populated.append("constraints")
    if state.watchpoints:
        populated.append("watchpoints")
    if state.decisions:
        populated.append("decisions")
    if state.checkpoints:
        populated.append("checkpoints")
    if state.recent_progress:
        populated.append("recent_progress")
    return populated


def collect_strategic_field_changes(previous: CognitiveState, current: CognitiveState) -> List[str]:
    changed: List[str] = []
    if previous.mission.objective != current.mission.objective or previous.mission.status != current.mission.status:
        changed.append("mission")
    if previous.focus != current.focus:
        changed.append("focus")
    for field in ("open_loops", "blockers", "constraints", "watchpoints", "decisions", "checkpoints", "recent_progress"):
        if list(getattr(previous, field)) != list(getattr(current, field)):
            changed.append(field)
    return changed


def collect_projection_metrics(state: CognitiveState, projection: Optional[CognitiveProjection]) -> tuple[List[str], Dict[str, int]]:
    if projection is None:
        return [], {}

    projected_fields: List[str] = []
    field_sizes: Dict[str, int] = {}

    def _record(field: str, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        if field not in projected_fields:
            projected_fields.append(field)
        field_sizes[field] = field_sizes.get(field, 0) + len(text)

    for line in list(projection.focus_lines or []):
        text = str(line or "").strip()
        if text.startswith("objective="):
            _record("mission", text)
        elif text.startswith("primary="):
            _record("focus", text)
        elif text.startswith("next="):
            if state.checkpoints:
                _record("checkpoints", text)
            elif state.open_loops:
                _record("open_loops", text)
            elif state.recent_progress:
                _record("recent_progress", text)
        elif text.startswith("open_loops="):
            _record("open_loops", text)

    for line in list(projection.background_lines or []):
        text = str(line or "").strip()
        if text.startswith("secondary="):
            _record("focus", text)
        elif text.startswith("blockers="):
            _record("blockers", text)
        elif text.startswith("constraints="):
            _record("constraints", text)
        elif text.startswith("watchpoints="):
            _record("watchpoints", text)

    return projected_fields[:10], {str(k): int(v) for k, v in list(field_sizes.items())[:10]}


def derive_outcome_updated_fields(stats: Dict[str, Any]) -> List[str]:
    fields: List[str] = []
    if int(stats.get("decisions_added") or 0) > 0:
        fields.append("decisions")
    if int(stats.get("checkpoints_added") or 0) > 0:
        fields.append("checkpoints")
    if int(stats.get("progress_added") or 0) > 0:
        fields.append("recent_progress")
    if int(stats.get("open_loops_added") or 0) > 0 or int(stats.get("open_loops_closed") or 0) > 0:
        fields.append("open_loops")
    if int(stats.get("blockers_added") or 0) > 0 or int(stats.get("blockers_cleared") or 0) > 0:
        fields.append("blockers")
    if int(stats.get("watchpoints_added") or 0) > 0:
        fields.append("watchpoints")
    return fields


def build_strategic_updates_summary(stats: Dict[str, Any]) -> List[str]:
    summary: List[str] = []
    mapping = (
        ("decisions_added", "decisions"),
        ("checkpoints_added", "checkpoints"),
        ("progress_added", "recent_progress"),
        ("open_loops_added", "open_loops+"),
        ("open_loops_closed", "open_loops-"),
        ("blockers_added", "blockers+"),
        ("blockers_cleared", "blockers-"),
        ("watchpoints_added", "watchpoints"),
    )
    for key, label in mapping:
        value = int(stats.get(key) or 0)
        if value > 0:
            summary.append(f"{label}:{value}")
    return summary[:8]


def build_effectiveness_flags(
    *,
    projection_non_empty: bool,
    hint_applied: bool,
    generic_outcome: bool,
    strategic_updates: Iterable[str],
    strategic_changed_fields: Iterable[str],
    planner_relevance_signal: bool,
) -> List[str]:
    flags: List[str] = []
    if projection_non_empty:
        flags.append("projection_non_empty")
    if hint_applied:
        flags.append("hint_influenced_broker")
    if generic_outcome:
        flags.append("generic_outcome")
    if any(True for _ in strategic_updates):
        flags.append("strategy_updated")
    if any(True for _ in strategic_changed_fields):
        flags.append("strategic_fields_changed")
    if planner_relevance_signal:
        flags.append("planner_relevance_signal")
    return flags[:8]


def compute_planner_relevance_signal(
    *,
    projection_non_empty: bool,
    hint_applied: bool,
    changed_fields: Sequence[str],
    outcome_updated_fields: Sequence[str],
) -> bool:
    if hint_applied:
        return True
    if not projection_non_empty:
        return False
    strategic_changes = set(changed_fields) | set(outcome_updated_fields)
    return bool(strategic_changes.intersection({"mission", "focus", "open_loops", "blockers", "constraints", "watchpoints", "checkpoints", "recent_progress"}))


def compute_commit_signal_strength(
    *,
    projection_non_empty: bool,
    hint_applied: bool,
    strategic_changed_fields: Sequence[str],
    strategic_updates_summary: Sequence[str],
    generic_outcome: bool,
) -> str:
    score = 0
    if projection_non_empty:
        score += 1
    if hint_applied:
        score += 1
    if strategic_changed_fields:
        score += 1
    if strategic_updates_summary:
        score += 1
    if not generic_outcome:
        score += 1

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    if score == 1:
        return "low"
    return "none"
