from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .models import CognitiveState, _clip_text, _normalize_lines
from .outcomes import normalize_cognitive_outcome
from .reconciler import CognitiveReconciler


class CognitiveCommitter:
    def __init__(self, *, reconciler: Optional[CognitiveReconciler] = None):
        self.reconciler = reconciler or CognitiveReconciler()

    def commit(
        self,
        *,
        session: Any,
        user_input: str = "",
        previous_state: Optional[CognitiveState] = None,
        broker_snapshot: Optional[Dict[str, Any]] = None,
        turn_outcome: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        previous = previous_state or CognitiveState()
        baseline = self.reconciler.reconcile(
            session=session,
            user_input=user_input,
            previous_state=previous,
            broker_snapshot=broker_snapshot,
        )
        outcome = normalize_cognitive_outcome(turn_outcome)

        decision_candidates = self._derive_decisions(session=session, baseline=baseline, outcome=outcome)
        checkpoint_candidates = self._derive_checkpoints(session=session, baseline=baseline, outcome=outcome)
        progress_candidates = self._derive_progress(session=session, baseline=baseline, previous=previous, outcome=outcome)
        loop_candidates = self._derive_outcome_open_loops(outcome=outcome)
        blocker_candidates = self._derive_outcome_blockers(outcome=outcome)
        watchpoint_candidates = self._derive_watchpoints(outcome=outcome, baseline=baseline)

        decision_candidates, decisions_suppressed = self._calibrate_decision_candidates(outcome=outcome, items=decision_candidates)
        checkpoint_candidates, checkpoints_suppressed = self._calibrate_checkpoint_candidates(outcome=outcome, items=checkpoint_candidates)
        progress_candidates, progress_suppressed = self._calibrate_progress_candidates(outcome=outcome, items=progress_candidates)
        watchpoint_candidates, watchpoints_suppressed = self._calibrate_watchpoint_candidates(outcome=outcome, baseline=baseline, items=watchpoint_candidates)
        if self._should_clear_watchpoints(outcome=outcome):
            baseline.watchpoints = []
            watchpoint_candidates = []

        commit_noise_suppressed_count = decisions_suppressed + checkpoints_suppressed + progress_suppressed + watchpoints_suppressed
        strategic_field_pruned_count = progress_suppressed + watchpoints_suppressed

        baseline.decisions = self._merge_priority(
            decision_candidates,
            baseline.decisions,
            previous.decisions,
            max_items=4,
            max_chars=180,
        )
        baseline.checkpoints = self._merge_priority(
            checkpoint_candidates,
            baseline.checkpoints,
            previous.checkpoints,
            max_items=4,
            max_chars=180,
        )
        baseline.recent_progress = self._merge_priority(
            progress_candidates,
            baseline.recent_progress,
            previous.recent_progress,
            max_items=4,
            max_chars=180,
        )
        baseline.open_loops = self._merge_priority(
            loop_candidates,
            baseline.open_loops,
            max_items=6,
            max_chars=180,
        )
        baseline.blockers = self._merge_priority(
            blocker_candidates,
            baseline.blockers,
            max_items=6,
            max_chars=180,
        )
        baseline.watchpoints = self._merge_priority(
            watchpoint_candidates,
            baseline.watchpoints,
            max_items=5,
            max_chars=180,
        )
        baseline.updated_at = int(time.time())
        baseline.turn_id = int(getattr(session, "turn_id", 0) or 0)

        return {
            "state": baseline,
            "stats": self._build_stats(
                previous=previous,
                current=baseline,
                outcome=outcome,
                commit_noise_suppressed_count=commit_noise_suppressed_count,
                strategic_field_pruned_count=strategic_field_pruned_count,
            ),
            "normalized_outcome": outcome.to_dict(),
        }

    @staticmethod
    def _merge_priority(*groups: List[str], max_items: int, max_chars: int = 180) -> List[str]:
        items: List[str] = []
        seen = set()
        for group in groups:
            for item in group:
                text = _clip_text(item, max_chars)
                if not text:
                    continue
                key = text.casefold()
                if key in seen:
                    continue
                seen.add(key)
                items.append(text)
                if len(items) >= max_items:
                    return items
        return items

    def _derive_decisions(self, *, session: Any, baseline: CognitiveState, outcome) -> List[str]:
        items: List[str] = []
        pending_action = getattr(session, "pending_action", None)
        action_id = _clip_text(outcome.action_id, 80)
        reason = _clip_text(outcome.reason, 80)

        if isinstance(pending_action, dict):
            gated_action = _clip_text(pending_action.get("action"), 80) or action_id
            if gated_action:
                items.append(f"Paused {gated_action} pending approval.")

        if outcome.status == "failure" and action_id:
            items.append(
                f"Changed approach after {action_id} failed{f' ({reason})' if reason else ''}."
            )

        if outcome.recovery_path_used and outcome.status == "failure":
            items.append("Escalated from retry to recovery path after repeated failure.")

        if outcome.approval_pending:
            items.append("Deferred destructive step pending explicit approval.")

        if outcome.handoff_or_escalation:
            items.append("Escalated control to another approval or handoff path.")

        if outcome.outcome_type == "handoff_or_escalation" and "denied" in outcome.final_response.lower():
            items.append("Stopped sensitive action after approval was denied or canceled.")

        if outcome.clarification_required and not pending_action:
            items.append("Switched from direct execution to clarification.")

        return _normalize_lines(items, max_items=4, max_chars=180)

    @staticmethod
    def _calibrate_decision_candidates(*, outcome, items: List[str]) -> tuple[List[str], int]:
        suppressed = 0
        if outcome.outcome_type == "reply_only" and not outcome.clarification_required:
            suppressed = len(items)
            return [], suppressed
        if outcome.clarification_required and not outcome.approval_pending and not outcome.handoff_or_escalation and outcome.status not in {"failure"}:
            suppressed = len(items)
            return [], suppressed
        calibrated = _normalize_lines(items, max_items=4, max_chars=180)
        suppressed = max(0, len(items) - len(calibrated))
        return calibrated, suppressed

    def _derive_checkpoints(self, *, session: Any, baseline: CognitiveState, outcome) -> List[str]:
        items: List[str] = []
        pending_action = getattr(session, "pending_action", None)
        action_id = _clip_text(outcome.action_id, 80)

        if isinstance(pending_action, dict):
            gated_action = _clip_text(pending_action.get("action"), 80) or action_id
            if gated_action:
                items.append(f"Approval required before {gated_action}.")

        if outcome.status == "success" and action_id:
            items.append(f"Last successful action: {action_id}.")

        planner_items = outcome.planner_tree if isinstance(outcome.planner_tree, list) else []
        current_step = next((str(step.get("title") or "").strip() for step in planner_items if isinstance(step, dict) and step.get("status") in {"in_progress", "blocked"}), "")
        if current_step:
            items.append(f"Resume at step: {current_step}")

        return _normalize_lines(items, max_items=4, max_chars=180)

    @staticmethod
    def _calibrate_checkpoint_candidates(*, outcome, items: List[str]) -> tuple[List[str], int]:
        suppressed = 0
        if outcome.outcome_type == "reply_only" and not outcome.approval_pending and not outcome.task_progressed:
            suppressed = len(items)
            return [], suppressed
        if outcome.clarification_required and not outcome.approval_pending and not outcome.task_progressed:
            suppressed = len(items)
            return [], suppressed
        calibrated = _normalize_lines(items, max_items=4, max_chars=180)
        suppressed = max(0, len(items) - len(calibrated))
        return calibrated, suppressed

    def _derive_progress(
        self,
        *,
        session: Any,
        baseline: CognitiveState,
        previous: CognitiveState,
        outcome,
    ) -> List[str]:
        items: List[str] = []
        action_id = _clip_text(outcome.action_id, 80)
        status = str(outcome.status or "").lower()

        if status == "success" and action_id:
            items.append(f"{action_id} completed successfully.")
        elif outcome.handoff_or_escalation and "forwarded" in outcome.final_response.lower():
            items.append("Approval decision forwarded to active work.")
        elif outcome.handoff_or_escalation and "denied" in outcome.final_response.lower():
            items.append("Sensitive action was canceled safely.")
        elif outcome.blocker_cleared:
            items.append("A previously active blocker was cleared.")
        elif outcome.task_progressed and action_id:
            items.append(f"Task progressed through {action_id}.")

        previous_blockers = {str(item).casefold() for item in previous.blockers}
        current_blockers = {str(item).casefold() for item in baseline.blockers}
        cleared = [item for item in previous.blockers if str(item).casefold() not in current_blockers]
        if cleared:
            items.append(f"Blocker cleared: {_clip_text(cleared[0], 120)}")

        return _normalize_lines(items, max_items=4, max_chars=180)

    @staticmethod
    def _calibrate_progress_candidates(*, outcome, items: List[str]) -> tuple[List[str], int]:
        suppressed = 0
        if outcome.generic_fallback_used and not outcome.blocker_cleared and not outcome.task_progressed and not outcome.handoff_or_escalation:
            suppressed = len(items)
            return [], suppressed
        if outcome.clarification_required and not outcome.task_progressed and not outcome.handoff_or_escalation and not outcome.blocker_cleared:
            suppressed = len(items)
            return [], suppressed
        calibrated = _normalize_lines(items, max_items=4, max_chars=180)
        suppressed = max(0, len(items) - len(calibrated))
        return calibrated, suppressed

    def _derive_outcome_open_loops(self, *, outcome) -> List[str]:
        items: List[str] = []
        if outcome.clarification_required:
            items.append("Awaiting user clarification before continuing.")
        if outcome.task_paused and not outcome.approval_pending:
            items.append("Task is paused and should be resumed from the latest checkpoint.")
        return _normalize_lines(items, max_items=3, max_chars=180)

    def _derive_outcome_blockers(self, *, outcome) -> List[str]:
        items: List[str] = []
        action_id = _clip_text(outcome.action_id, 80)
        status = str(outcome.status or "").lower()
        reason = _clip_text(outcome.reason, 120)
        if status == "failure" and action_id:
            items.append(f"{action_id} failed{f': {reason}' if reason else ''}.")
        if outcome.approval_pending:
            items.append("Execution is waiting for approval before continuing.")
        return _normalize_lines(items, max_items=3, max_chars=180)

    def _derive_watchpoints(self, *, outcome, baseline: CognitiveState) -> List[str]:
        items: List[str] = []
        if outcome.approval_pending and outcome.action_id:
            action_id = _clip_text(outcome.action_id, 80)
            items.append(f"Wait for approval response before retrying{f' {action_id}' if action_id else ''}.")
        elif outcome.status == "failure" and outcome.action_id:
            items.append(f"Avoid immediately repeating {outcome.action_id} with the same params.")
        if outcome.handoff_or_escalation:
            items.append("Track the external handoff or approval path before resuming.")
        if baseline.watchpoints:
            items.extend(baseline.watchpoints[:2])
        return _normalize_lines(items, max_items=5, max_chars=180)

    @staticmethod
    def _calibrate_watchpoint_candidates(*, outcome, baseline: CognitiveState, items: List[str]) -> tuple[List[str], int]:
        if outcome.task_completed and not outcome.approval_pending and not outcome.clarification_required and not outcome.status == "failure":
            carried = []
        elif outcome.clarification_required and not outcome.approval_pending and outcome.status not in {"failure"}:
            carried = []
        elif outcome.blocker_cleared and not baseline.blockers:
            carried = [item for item in items if "track the external handoff" in item.lower()]
        else:
            carried = items
        calibrated = _normalize_lines(carried, max_items=5, max_chars=180)
        suppressed = max(0, len(items) - len(calibrated))
        return calibrated, suppressed

    @staticmethod
    def _should_clear_watchpoints(*, outcome) -> bool:
        if outcome.task_completed and not outcome.approval_pending and not outcome.clarification_required and outcome.status != "failure":
            return True
        if outcome.clarification_required and not outcome.approval_pending and outcome.status != "failure":
            return True
        if outcome.generic_fallback_used and not outcome.blocker_detected and not outcome.approval_pending and not outcome.clarification_required and not outcome.handoff_or_escalation:
            return True
        return False

    @staticmethod
    def _build_stats(
        *,
        previous: CognitiveState,
        current: CognitiveState,
        outcome,
        commit_noise_suppressed_count: int = 0,
        strategic_field_pruned_count: int = 0,
    ) -> Dict[str, Any]:
        prev_loops = {item.casefold() for item in previous.open_loops}
        curr_loops = {item.casefold() for item in current.open_loops}
        prev_blockers = {item.casefold() for item in previous.blockers}
        curr_blockers = {item.casefold() for item in current.blockers}
        prev_decisions = {item.casefold() for item in previous.decisions}
        prev_checkpoints = {item.casefold() for item in previous.checkpoints}
        prev_progress = {item.casefold() for item in previous.recent_progress}
        prev_watchpoints = {item.casefold() for item in previous.watchpoints}

        return {
            "decisions_added": sum(1 for item in current.decisions if item.casefold() not in prev_decisions),
            "checkpoints_added": sum(1 for item in current.checkpoints if item.casefold() not in prev_checkpoints),
            "progress_added": sum(1 for item in current.recent_progress if item.casefold() not in prev_progress),
            "open_loops_added": sum(1 for item in curr_loops if item not in prev_loops),
            "open_loops_closed": sum(1 for item in prev_loops if item not in curr_loops),
            "blockers_added": sum(1 for item in curr_blockers if item not in prev_blockers),
            "blockers_cleared": sum(1 for item in prev_blockers if item not in curr_blockers),
            "watchpoints_added": sum(1 for item in current.watchpoints if item.casefold() not in prev_watchpoints),
            "normalized_outcome_type": outcome.outcome_type,
            "outcome_type_generic_fallback_used": bool(getattr(outcome, "generic_fallback_used", False)),
            "outcome_refined": bool(getattr(outcome, "refined_mapping_used", False)),
            "commit_noise_suppressed_count": int(commit_noise_suppressed_count),
            "strategic_field_pruned_count": int(strategic_field_pruned_count),
            "commit_coverage_path": outcome.commit_path,
        }
