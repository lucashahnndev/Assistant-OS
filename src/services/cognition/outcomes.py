from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NormalizedCognitiveOutcome:
    outcome_type: str = "reply_only"
    generic_fallback_used: bool = False
    refined_mapping_used: bool = False
    refinement_reason: str = ""
    coverage_label: str = "reply_only_default"
    action_id: str = ""
    action_namespace: str = ""
    status: str = ""
    reason: str = ""
    clarification_required: bool = False
    approval_pending: bool = False
    blocker_detected: bool = False
    blocker_cleared: bool = False
    recovery_path_used: bool = False
    fallback_used: bool = False
    fallback_suppressed: bool = False
    task_progressed: bool = False
    task_completed: bool = False
    task_paused: bool = False
    handoff_or_escalation: bool = False
    commit_path: str = "final_turn"
    final_response: str = ""
    planner_tree: List[Dict[str, Any]] = field(default_factory=list)
    raw_tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_cognitive_outcome(raw_outcome: Optional[Dict[str, Any]]) -> NormalizedCognitiveOutcome:
    raw = raw_outcome if isinstance(raw_outcome, dict) else {}
    explicit = str(raw.get("outcome_type") or "").strip().lower()
    action_id = str(raw.get("last_action_id") or raw.get("action_id") or "").strip()
    action_namespace = ".".join(action_id.split(".")[:2]) if "." in action_id else action_id
    status = str(raw.get("last_action_status") or "").strip().lower()
    reason = str(raw.get("last_action_reason") or "").strip()
    final_response = str(raw.get("final_response") or "").strip()
    pending_action = raw.get("pending_action") if isinstance(raw.get("pending_action"), dict) else None
    planner_tree = raw.get("planner_tree") if isinstance(raw.get("planner_tree"), list) else []
    replans_used = int(raw.get("replans_used") or 0)
    commit_path = str(raw.get("commit_path") or "final_turn").strip() or "final_turn"
    raw_tags: List[str] = []
    reason_lower = reason.lower()
    final_lower = final_response.lower()
    commit_path_lower = commit_path.lower()
    known_explicit_types = {
        "approval_pending",
        "approval_cancelled",
        "approval_forwarded",
        "action_executed",
        "action_failed",
        "blocker_detected",
        "fallback_used",
        "handoff_or_escalation",
        "recovery_path_used",
        "reply_only",
        "task_completed",
        "task_paused",
        "task_progressed",
        "turn_complete",
    }
    generic_fallback_signal = bool(explicit) and explicit not in known_explicit_types

    clarification_required = bool(
        final_response.endswith("?")
        or "clarification" in reason_lower
        or "need_user_input" in reason_lower
        or "waiting_user" in reason_lower
    )
    approval_pending = bool(pending_action) or explicit == "approval_pending" or status in {"pending_approval", "pending"} or "approval" in commit_path_lower
    handoff_or_escalation = explicit in {"approval_forwarded", "handoff_or_escalation"} or status in {"handoff", "cancelled", "canceled"}
    fallback_signal = bool(raw.get("fallback_used")) or explicit in {"fallback_used", "recovery_path_used"}
    fallback_used = fallback_signal or (replans_used > 0 and status in {"failure", "error"}) or any(token in commit_path_lower for token in ("recovery", "fallback", "no_plan"))
    fallback_suppressed = False
    if replans_used > 0 and not fallback_used and not fallback_signal:
        fallback_suppressed = True
    blocker_detected = explicit == "blocker_detected" or status == "failure" or approval_pending
    blocker_cleared = bool(raw.get("blocker_cleared"))
    task_paused = approval_pending or explicit == "task_paused"
    task_completed = explicit == "task_completed" or (
        status in {"success", "completed"}
        and action_id
        and not generic_fallback_signal
        and not any(isinstance(step, dict) and step.get("status") in {"pending", "in_progress", "blocked"} for step in planner_tree)
    )
    task_progressed = explicit == "task_progressed" or (
        status in {"success", "completed"}
        and bool(action_id)
        and not generic_fallback_signal
    )
    recovery_path_used = explicit == "recovery_path_used" or (status == "failure" and replans_used > 0)
    if fallback_used and replans_used > 0:
        recovery_path_used = True
    if any(token in commit_path_lower for token in ("recovery", "no_plan", "fallback")):
        recovery_path_used = True

    if explicit == "approval_pending":
        outcome_type = "approval_pending"
        coverage_label = "explicit_approval_pending"
    elif explicit == "approval_cancelled":
        outcome_type = "handoff_or_escalation"
        handoff_or_escalation = True
        coverage_label = "explicit_approval_cancelled"
    elif explicit == "approval_forwarded":
        outcome_type = "handoff_or_escalation"
        coverage_label = "explicit_approval_forwarded"
    elif approval_pending:
        outcome_type = "approval_pending"
        coverage_label = "derived_approval_pending"
    elif handoff_or_escalation and explicit != "handoff_or_escalation":
        outcome_type = "handoff_or_escalation"
        coverage_label = "derived_handoff_or_escalation"
    elif recovery_path_used and fallback_used and status != "failure":
        outcome_type = "recovery_path_used"
        coverage_label = "derived_recovery_path"
    elif clarification_required:
        outcome_type = "clarification_required"
        coverage_label = "derived_clarification"
    elif status == "failure":
        outcome_type = "action_failed"
        coverage_label = "derived_action_failure"
    elif status in {"cancelled", "canceled"} and "approval" in reason_lower:
        outcome_type = "handoff_or_escalation"
        coverage_label = "derived_approval_cancelled"
    elif status in {"success", "completed"} and action_id and (not explicit or explicit == "action_executed"):
        outcome_type = "action_executed"
        coverage_label = "derived_action_success"
    elif explicit:
        outcome_type = explicit
        coverage_label = "explicit_unknown" if explicit not in known_explicit_types else f"explicit_{explicit}"
    else:
        outcome_type = "reply_only"
        coverage_label = "reply_only_default"

    generic_fallback_used = outcome_type == "reply_only" or coverage_label == "explicit_unknown"
    refined_mapping_used = coverage_label.startswith("derived_") and outcome_type not in {"reply_only", "action_executed", "action_failed", "clarification_required"}
    refinement_reason = ""
    if refined_mapping_used:
        refinement_reason = coverage_label
    elif coverage_label.startswith("derived_") and outcome_type in {"clarification_required", "action_failed", "action_executed"}:
        refinement_reason = coverage_label

    if clarification_required:
        raw_tags.append("clarification_required")
    if approval_pending:
        raw_tags.append("approval_pending")
    if blocker_detected:
        raw_tags.append("blocker_detected")
    if blocker_cleared:
        raw_tags.append("blocker_cleared")
    if recovery_path_used:
        raw_tags.append("recovery_path_used")
    if fallback_used:
        raw_tags.append("fallback_used")
    if task_progressed:
        raw_tags.append("task_progressed")
    if task_completed:
        raw_tags.append("task_completed")
    if task_paused:
        raw_tags.append("task_paused")
    if handoff_or_escalation:
        raw_tags.append("handoff_or_escalation")
    if generic_fallback_used:
        raw_tags.append("generic_fallback_used")
    if refined_mapping_used:
        raw_tags.append("refined_outcome")
    if fallback_suppressed:
        raw_tags.append("fallback_suppressed")

    return NormalizedCognitiveOutcome(
        outcome_type=outcome_type,
        generic_fallback_used=generic_fallback_used,
        refined_mapping_used=refined_mapping_used,
        refinement_reason=refinement_reason,
        coverage_label=coverage_label,
        action_id=action_id,
        action_namespace=action_namespace,
        status=status,
        reason=reason,
        clarification_required=clarification_required,
        approval_pending=approval_pending,
        blocker_detected=blocker_detected,
        blocker_cleared=blocker_cleared,
        recovery_path_used=recovery_path_used,
        fallback_used=fallback_used,
        fallback_suppressed=fallback_suppressed,
        task_progressed=task_progressed,
        task_completed=task_completed,
        task_paused=task_paused,
        handoff_or_escalation=handoff_or_escalation,
        commit_path=commit_path,
        final_response=final_response,
        planner_tree=planner_tree,
        raw_tags=raw_tags,
    )
