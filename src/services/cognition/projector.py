from __future__ import annotations

from typing import List

from .models import CognitiveProjection, CognitiveState, _clip_text


class CognitiveProjector:
    def project(self, state: CognitiveState) -> CognitiveProjection:
        focus_lines: List[str] = []
        background_lines: List[str] = []

        objective = _clip_text(state.mission.objective, 180)
        if objective and objective != "Standby":
            focus_lines.append(f"objective={objective}")

        primary_task_id = _clip_text(state.focus.primary_task_id, 60)
        primary_summary = _clip_text(state.focus.primary_summary, 160)
        if primary_task_id or primary_summary:
            primary_value = primary_summary or "active"
            if primary_task_id:
                primary_value = f"[{primary_task_id}] {primary_value}"
            focus_lines.append(f"primary={primary_value}")
        else:
            focus_lines.append("primary=none")

        next_item = ""
        for candidate in state.checkpoints + state.open_loops + state.recent_progress:
            next_item = _clip_text(candidate, 160)
            if next_item:
                break
        if next_item:
            focus_lines.append(f"next={next_item}")

        if state.open_loops:
            focus_lines.append("open_loops=" + " | ".join(_clip_text(item, 90) for item in state.open_loops[:3]))

        secondary = []
        for item in state.agenda[:4]:
            if primary_task_id and f"[{primary_task_id}]" in item:
                continue
            secondary.append(_clip_text(item, 120))
        if secondary:
            background_lines.append("secondary=" + " ; ".join(secondary[:4]))

        if state.blockers:
            background_lines.append("blockers=" + " | ".join(_clip_text(item, 90) for item in state.blockers[:4]))

        if state.constraints:
            background_lines.append("constraints=" + " | ".join(_clip_text(item, 90) for item in state.constraints[:4]))

        if state.watchpoints:
            background_lines.append("watchpoints=" + " | ".join(_clip_text(item, 90) for item in state.watchpoints[:4]))

        return CognitiveProjection(
            focus_lines=focus_lines[:4],
            background_lines=background_lines[:4],
        )

