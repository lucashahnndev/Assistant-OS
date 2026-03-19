from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .committer import CognitiveCommitter
from .effectiveness import (
    build_effectiveness_flags,
    build_strategic_updates_summary,
    collect_populated_fields,
    collect_projection_metrics,
    collect_strategic_field_changes,
    compute_commit_signal_strength,
    compute_planner_relevance_signal,
    derive_outcome_updated_fields,
)
from .hints import CognitiveBrokerHintBuilder
from .models import CognitiveDiagnostics, CognitiveProjection, CognitiveState, coerce_cognitive_state
from .projector import CognitiveProjector
from .reconciler import CognitiveReconciler


class CognitiveLayer:
    def __init__(
        self,
        *,
        reconciler: Optional[CognitiveReconciler] = None,
        projector: Optional[CognitiveProjector] = None,
        committer: Optional[CognitiveCommitter] = None,
        hint_builder: Optional[CognitiveBrokerHintBuilder] = None,
    ):
        self.reconciler = reconciler or CognitiveReconciler()
        self.projector = projector or CognitiveProjector()
        self.committer = committer or CognitiveCommitter(reconciler=self.reconciler)
        self.hint_builder = hint_builder or CognitiveBrokerHintBuilder()

    def reconcile_and_project(
        self,
        *,
        session: Any,
        user_input: str = "",
        broker_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        previous_state_raw = getattr(session, "cognitive_state", None)
        previous_state = coerce_cognitive_state(previous_state_raw)
        changed_fields = []
        fallback_used = False
        fallback_mode = "none"

        try:
            state = self.reconciler.reconcile(
                session=session,
                user_input=user_input,
                previous_state=previous_state,
                broker_snapshot=broker_snapshot,
            )
        except Exception:
            state = previous_state
            fallback_used = True
            fallback_mode = "preserved_previous_state"

        projection: Optional[CognitiveProjection] = None
        try:
            projection = self.projector.project(state)
        except Exception:
            projection = None
            fallback_used = True
            fallback_mode = "legacy_frame"

        new_state_dict = state.to_dict()
        old_state_dict = previous_state.to_dict()
        for key in new_state_dict.keys():
            if new_state_dict.get(key) != old_state_dict.get(key):
                changed_fields.append(str(key))
        strategic_changed_fields = collect_strategic_field_changes(previous_state, state)
        projection_fields, projection_field_sizes = collect_projection_metrics(state, projection)
        projection_non_empty = bool((projection and (projection.focus_lines or projection.background_lines)))
        planner_relevance_signal = compute_planner_relevance_signal(
            projection_non_empty=projection_non_empty,
            hint_applied=False,
            changed_fields=strategic_changed_fields,
            outcome_updated_fields=[],
        )

        diagnostics = CognitiveDiagnostics(
            phase="reconcile",
            reconciled_at=int(time.time()),
            turn_id=int(getattr(session, "turn_id", 0) or 0),
            primary_task_id=str(state.focus.primary_task_id or ""),
            agenda_count=len(state.agenda),
            open_loops_count=len(state.open_loops),
            blockers_count=len(state.blockers),
            constraints_count=len(state.constraints),
            decisions_count=len(state.decisions),
            working_set_count=len(state.working_set),
            changed_fields=changed_fields[:8],
            cognitive_fields_populated=collect_populated_fields(state)[:10],
            cognitive_fields_changed=strategic_changed_fields[:10],
            cognitive_fields_projected=projection_fields[:10],
            projection_field_sizes=projection_field_sizes,
            projection_non_empty=projection_non_empty,
            commit_noise_suppressed_count=0,
            outcome_refined=False,
            strategic_field_pruned_count=0,
            commit_signal_strength=compute_commit_signal_strength(
                projection_non_empty=projection_non_empty,
                hint_applied=False,
                strategic_changed_fields=strategic_changed_fields,
                strategic_updates_summary=[],
                generic_outcome=False,
            ),
            effectiveness_flags=build_effectiveness_flags(
                projection_non_empty=projection_non_empty,
                hint_applied=False,
                generic_outcome=False,
                strategic_updates=[],
                strategic_changed_fields=strategic_changed_fields,
                planner_relevance_signal=planner_relevance_signal,
            ),
            planner_relevance_signal=planner_relevance_signal,
            fallback_used=fallback_used,
            fallback_mode=fallback_mode,
        )

        return {
            "state": new_state_dict,
            "projection": projection.to_dict() if projection else None,
            "diagnostics": diagnostics.to_dict(),
            "use_legacy_frame": projection is None,
        }

    def build_broker_hints(self, *, state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cognitive_state = coerce_cognitive_state(state)
        hints = self.hint_builder.build(cognitive_state)
        return hints.to_dict()

    def commit_after_turn(
        self,
        *,
        session: Any,
        user_input: str = "",
        broker_snapshot: Optional[Dict[str, Any]] = None,
        turn_outcome: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        previous_state_raw = getattr(session, "cognitive_state", None)
        previous_state = coerce_cognitive_state(previous_state_raw)
        fallback_used = False
        fallback_mode = "none"

        try:
            commit_result = self.committer.commit(
                session=session,
                user_input=user_input,
                previous_state=previous_state,
                broker_snapshot=broker_snapshot,
                turn_outcome=turn_outcome,
            )
            state = commit_result["state"]
            stats = commit_result["stats"]
            normalized_outcome = commit_result.get("normalized_outcome") or {}
        except Exception:
            state = previous_state
            stats = {
                "decisions_added": 0,
                "checkpoints_added": 0,
                "progress_added": 0,
                "open_loops_added": 0,
                "open_loops_closed": 0,
                "blockers_added": 0,
                "blockers_cleared": 0,
                "watchpoints_added": 0,
                "normalized_outcome_type": "",
                "commit_coverage_path": "",
            }
            normalized_outcome = {}
            fallback_used = True
            fallback_mode = "preserved_previous_state"

        projection: Optional[CognitiveProjection] = None
        try:
            projection = self.projector.project(state)
        except Exception:
            projection = None
            fallback_used = True
            fallback_mode = "projection_unavailable"

        new_state_dict = state.to_dict()
        old_state_dict = previous_state.to_dict()
        changed_fields = [
            str(key)
            for key in new_state_dict.keys()
            if new_state_dict.get(key) != old_state_dict.get(key)
        ]
        strategic_changed_fields = collect_strategic_field_changes(previous_state, state)
        projection_fields, projection_field_sizes = collect_projection_metrics(state, projection)
        projection_non_empty = bool((projection and (projection.focus_lines or projection.background_lines)))
        strategic_updates_summary = build_strategic_updates_summary(stats)
        outcome_updated_fields = derive_outcome_updated_fields(stats)
        planner_relevance_signal = compute_planner_relevance_signal(
            projection_non_empty=projection_non_empty,
            hint_applied=False,
            changed_fields=strategic_changed_fields,
            outcome_updated_fields=outcome_updated_fields,
        )
        diagnostics = CognitiveDiagnostics(
            phase="commit",
            reconciled_at=int(time.time()),
            turn_id=int(getattr(session, "turn_id", 0) or 0),
            primary_task_id=str(state.focus.primary_task_id or ""),
            agenda_count=len(state.agenda),
            open_loops_count=len(state.open_loops),
            blockers_count=len(state.blockers),
            constraints_count=len(state.constraints),
            decisions_count=len(state.decisions),
            working_set_count=len(state.working_set),
            changed_fields=changed_fields[:8],
            commit_performed=not fallback_used or bool(changed_fields),
            decisions_added=int(stats.get("decisions_added") or 0),
            checkpoints_added=int(stats.get("checkpoints_added") or 0),
            progress_added=int(stats.get("progress_added") or 0),
            open_loops_added=int(stats.get("open_loops_added") or 0),
            open_loops_closed=int(stats.get("open_loops_closed") or 0),
            blockers_added=int(stats.get("blockers_added") or 0),
            blockers_cleared=int(stats.get("blockers_cleared") or 0),
            watchpoints_added=int(stats.get("watchpoints_added") or 0),
            normalized_outcome_type=str(stats.get("normalized_outcome_type") or ""),
            outcome_type_generic_fallback_used=bool(stats.get("outcome_type_generic_fallback_used")),
            commit_coverage_path=str(stats.get("commit_coverage_path") or ""),
            cognitive_fields_populated=collect_populated_fields(state)[:10],
            cognitive_fields_changed=strategic_changed_fields[:10],
            cognitive_fields_projected=projection_fields[:10],
            cognitive_fields_derived_from_outcome=outcome_updated_fields[:10],
            projection_field_sizes=projection_field_sizes,
            projection_non_empty=projection_non_empty,
            strategic_updates_summary=strategic_updates_summary[:8],
            commit_noise_suppressed_count=int(stats.get("commit_noise_suppressed_count") or 0),
            outcome_refined=bool(stats.get("outcome_refined")),
            strategic_field_pruned_count=int(stats.get("strategic_field_pruned_count") or 0),
            commit_signal_strength=compute_commit_signal_strength(
                projection_non_empty=projection_non_empty,
                hint_applied=False,
                strategic_changed_fields=strategic_changed_fields,
                strategic_updates_summary=strategic_updates_summary,
                generic_outcome=bool(stats.get("outcome_type_generic_fallback_used")),
            ),
            effectiveness_flags=build_effectiveness_flags(
                projection_non_empty=projection_non_empty,
                hint_applied=False,
                generic_outcome=bool(stats.get("outcome_type_generic_fallback_used")),
                strategic_updates=strategic_updates_summary,
                strategic_changed_fields=strategic_changed_fields,
                planner_relevance_signal=planner_relevance_signal,
            ),
            planner_relevance_signal=planner_relevance_signal,
            fallback_used=fallback_used,
            fallback_mode=fallback_mode,
        )

        return {
            "state": new_state_dict,
            "projection": projection.to_dict() if projection else None,
            "diagnostics": diagnostics.to_dict(),
            "normalized_outcome": normalized_outcome,
        }
