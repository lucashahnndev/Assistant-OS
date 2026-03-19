from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .models import CognitiveState, FocusState, MissionState, ProvenanceState, _clip_text, _normalize_lines


class CognitiveReconciler:
    _NON_TERMINAL = {
        "STARTED",
        "PROGRESS",
        "PAUSED",
        "WAITING_INPUT",
        "WAITING_APPROVAL",
        "BLOCKED_BY_DEPENDENCY",
        "FOREGROUND_BUDGET_EXCEEDED",
    }
    _BLOCKED = {"BLOCKED_BY_DEPENDENCY", "WAITING_INPUT", "WAITING_APPROVAL"}

    def reconcile(
        self,
        *,
        session: Any,
        user_input: str = "",
        previous_state: Optional[CognitiveState] = None,
        broker_snapshot: Optional[Dict[str, Any]] = None,
    ) -> CognitiveState:
        previous = previous_state or CognitiveState()
        tasks = self._rank_tasks(session)
        primary_task = tasks[0] if tasks else None
        broker = broker_snapshot if isinstance(broker_snapshot, dict) else {}

        objective = self._derive_objective(session=session, user_input=user_input, primary_task=primary_task)
        reasoning_mode = self._derive_reasoning_mode(session=session, tasks=tasks)
        attention_mode = "foreground" if primary_task else ("background" if tasks else "monitoring")
        primary_summary = self._derive_primary_summary(primary_task=primary_task, objective=objective)

        agenda = self._derive_agenda(tasks)
        open_loops = self._derive_open_loops(session=session, tasks=tasks)
        blockers = self._derive_blockers(session=session, tasks=tasks)
        constraints = self._derive_constraints(session=session, broker_snapshot=broker)
        working_set = self._derive_working_set(session=session, objective=objective, primary_task=primary_task, broker_snapshot=broker)
        checkpoints = self._derive_checkpoints(primary_task=primary_task, tasks=tasks)
        recent_progress = self._derive_recent_progress(session=session, tasks=tasks)
        watchpoints = self._derive_watchpoints(
            session=session,
            open_loops=open_loops,
            blockers=blockers,
            constraints=constraints,
            broker_snapshot=broker,
        )

        assumptions = previous.assumptions[:4]
        decisions = previous.decisions[:4]

        sources = ["session_state", "task_registry"]
        if user_input.strip():
            sources.append("user_input")
        if getattr(session, "intent_agenda", None) is not None:
            sources.append("intent_agenda")
        if getattr(session, "pending_action", None):
            sources.append("pending_action")
        if getattr(session, "tool_health", None):
            sources.append("tool_health")
        if broker:
            sources.append("broker_snapshot")

        return CognitiveState(
            updated_at=int(time.time()),
            turn_id=int(getattr(session, "turn_id", 0) or 0),
            mission=MissionState(objective=objective, status="active" if objective else "standby"),
            focus=FocusState(
                primary_task_id=str(primary_task.get("task_id")) if primary_task and primary_task.get("task_id") is not None else None,
                primary_summary=primary_summary,
                reasoning_mode=reasoning_mode,
                attention_mode=attention_mode,
            ),
            agenda=agenda,
            open_loops=open_loops,
            blockers=blockers,
            constraints=constraints,
            assumptions=assumptions,
            decisions=decisions,
            working_set=working_set,
            checkpoints=checkpoints,
            recent_progress=recent_progress,
            watchpoints=watchpoints,
            provenance=ProvenanceState(
                sources=_normalize_lines(sources, max_items=8, max_chars=60),
                broker_evidence_used=bool(broker.get("evidence_count")),
            ),
        )

    def _rank_tasks(self, session: Any) -> List[Dict[str, Any]]:
        registry = getattr(session, "task_registry", {}) or {}
        tasks: List[Dict[str, Any]] = []
        active_focus_task_id = getattr(session, "active_focus_task_id", None)
        for task_id, raw in registry.items():
            task = raw if isinstance(raw, dict) else {}
            status = str(task.get("status") or "").upper()
            if status and status not in self._NON_TERMINAL:
                continue
            task_copy = dict(task)
            task_copy["task_id"] = str(task_copy.get("task_id") or task_id)
            task_copy["_is_active_focus"] = task_copy["task_id"] == active_focus_task_id
            tasks.append(task_copy)

        def _sort_key(task: Dict[str, Any]) -> tuple:
            status = str(task.get("status") or "").upper()
            waiting = bool(task.get("waiting_user_response") or task.get("user_waiting"))
            blocked = status == "BLOCKED_BY_DEPENDENCY"
            active_focus = bool(task.get("_is_active_focus"))
            attention = float(task.get("attention_score") or 0.0)
            urgency = float(task.get("urgency") or 0.0)
            last_event_at = float(task.get("last_event_at") or 0.0)
            return (
                0 if active_focus else 1,
                0 if not blocked else 1,
                0 if waiting else 1,
                -attention,
                -urgency,
                -last_event_at,
                str(task.get("task_id") or ""),
            )

        return sorted(tasks, key=_sort_key)

    @staticmethod
    def _derive_objective(session: Any, user_input: str, primary_task: Optional[Dict[str, Any]]) -> str:
        text = _clip_text(user_input, 220)
        if text:
            return text
        if primary_task:
            for key in ("last_summary", "completion_summary", "last_outcome", "task_role"):
                value = _clip_text(primary_task.get(key), 220)
                if value:
                    return value
        state_summary = getattr(session, "state_summary", {}) or {}
        goal = _clip_text(state_summary.get("goal"), 220)
        if goal and goal.lower() != "standby":
            return goal
        return "Standby"

    @staticmethod
    def _derive_primary_summary(primary_task: Optional[Dict[str, Any]], objective: str) -> str:
        if not primary_task:
            return _clip_text(objective, 180)
        role = _clip_text(primary_task.get("task_role"), 80) or "task"
        status = _clip_text(primary_task.get("status"), 40) or "unknown"
        summary = _clip_text(
            primary_task.get("last_summary")
            or primary_task.get("completion_summary")
            or primary_task.get("last_outcome"),
            120,
        )
        if summary:
            return f"{role}|{status}|{summary}"
        return f"{role}|{status}"

    @staticmethod
    def _derive_reasoning_mode(session: Any, tasks: List[Dict[str, Any]]) -> str:
        state_summary = getattr(session, "state_summary", {}) or {}
        last_error = str(state_summary.get("last_error") or "").strip().lower()
        if last_error and last_error not in {"none", "null"}:
            return "troubleshooting"
        if any(str(task.get("status") or "").upper() == "BLOCKED_BY_DEPENDENCY" for task in tasks):
            return "troubleshooting"
        return "standard"

    def _derive_agenda(self, tasks: List[Dict[str, Any]]) -> List[str]:
        items: List[str] = []
        for task in tasks[:5]:
            role = _clip_text(task.get("task_role"), 70) or "task"
            status = _clip_text(task.get("status"), 40) or "unknown"
            summary = _clip_text(task.get("last_summary") or task.get("completion_summary"), 90)
            line = f"[{task.get('task_id', '?')}] {role}|{status}"
            if summary:
                line += f"|{summary}"
            items.append(line)
        return _normalize_lines(items, max_items=5, max_chars=180)

    def _derive_open_loops(self, session: Any, tasks: List[Dict[str, Any]]) -> List[str]:
        loops: List[str] = []
        pending_action = getattr(session, "pending_action", None)
        if isinstance(pending_action, dict):
            requested_action = _clip_text(pending_action.get("requested_action") or pending_action.get("action"), 90)
            if requested_action:
                loops.append(f"Pending confirmation for action {requested_action}.")
            else:
                loops.append("Pending user confirmation before continuing.")

        for task in tasks:
            role = _clip_text(task.get("task_role"), 80) or "task"
            status = str(task.get("status") or "").upper()
            if bool(task.get("waiting_user_response") or task.get("user_waiting")):
                loops.append(f"Awaiting user response for {role}.")
            if status == "BLOCKED_BY_DEPENDENCY":
                deps = task.get("depends_on") if isinstance(task.get("depends_on"), list) else []
                dep_text = ", ".join(_clip_text(dep, 30) for dep in deps[:3] if _clip_text(dep, 30))
                loops.append(f"{role} blocked by dependencies{': ' + dep_text if dep_text else ''}.")
            checkpoint = _clip_text(task.get("checkpoint"), 90)
            if checkpoint and status in {"PAUSED", "PROGRESS", "FOREGROUND_BUDGET_EXCEEDED"}:
                loops.append(f"Resume {role} from checkpoint: {checkpoint}")

        return _normalize_lines(loops, max_items=6, max_chars=180)

    def _derive_blockers(self, session: Any, tasks: List[Dict[str, Any]]) -> List[str]:
        blockers: List[str] = []
        for task in tasks:
            role = _clip_text(task.get("task_role"), 80) or "task"
            status = str(task.get("status") or "").upper()
            if status == "BLOCKED_BY_DEPENDENCY":
                blockers.append(f"{role} is blocked by dependencies.")
            if bool(task.get("waiting_user_response") or task.get("user_waiting")):
                blockers.append(f"{role} is waiting for user input.")
            failure = _clip_text(task.get("last_failure_summary"), 120)
            if failure:
                blockers.append(f"{role} failure: {failure}")

        tool_health = getattr(session, "tool_health", {}) or {}
        for tool_name, health in tool_health.items():
            status = str(health or "").strip().upper()
            if status and status != "HEALTHY":
                blockers.append(f"Tool {tool_name} is {status}.")

        pending_action = getattr(session, "pending_action", None)
        if isinstance(pending_action, dict):
            blockers.append("Execution is paused pending user confirmation.")

        context = getattr(session, "context", {}) or {}
        auth_status = _clip_text(context.get("auth_status"), 80)
        if auth_status and auth_status.lower() not in {"ok", "healthy"}:
            blockers.append(f"Auth/config issue: {auth_status}")

        return _normalize_lines(blockers, max_items=6, max_chars=180)

    def _derive_constraints(self, session: Any, broker_snapshot: Optional[Dict[str, Any]]) -> List[str]:
        constraints: List[str] = []
        tool_health = getattr(session, "tool_health", {}) or {}
        for tool_name, health in tool_health.items():
            status = str(health or "").strip().upper()
            if status and status != "HEALTHY":
                constraints.append(f"Avoid relying on tool {tool_name} while it is {status}.")

        caps = getattr(session, "context", {}) or {}
        driver_caps = caps.get("driver_capabilities") if isinstance(caps.get("driver_capabilities"), dict) else {}
        if bool(driver_caps.get("voice_only")):
            constraints.append("Respond in voice-safe plain text.")
        if driver_caps and not bool(driver_caps.get("markdown", True)):
            constraints.append("Avoid markdown-heavy formatting.")
        if getattr(session, "pending_action", None):
            constraints.append("Do not execute gated action until user confirms.")
        if isinstance(broker_snapshot, dict) and "evidence_count" in broker_snapshot and not bool(broker_snapshot.get("evidence_count")):
            constraints.append("Broker evidence absent; rely on live state and available actions.")

        return _normalize_lines(constraints, max_items=6, max_chars=180)

    def _derive_working_set(
        self,
        *,
        session: Any,
        objective: str,
        primary_task: Optional[Dict[str, Any]],
        broker_snapshot: Optional[Dict[str, Any]],
    ) -> List[str]:
        facts: List[str] = []
        if objective and objective != "Standby":
            facts.append(f"Objective: {_clip_text(objective, 140)}")
        if primary_task:
            facts.append(f"Primary task: {_clip_text(primary_task.get('task_role'), 90)}")
        summary = _clip_text(getattr(session, "summary", ""), 140)
        if summary:
            facts.append(f"Session summary: {summary}")
        state_summary = getattr(session, "state_summary", {}) or {}
        memory_notes = _clip_text(state_summary.get("memory_notes"), 120)
        if memory_notes and memory_notes.lower() != "none":
            facts.append(f"Memory notes: {memory_notes}")
        if isinstance(broker_snapshot, dict):
            intent = _clip_text(broker_snapshot.get("intent"), 60)
            if intent:
                facts.append(f"Broker intent: {intent}")
        return _normalize_lines(facts, max_items=5, max_chars=160)

    def _derive_checkpoints(self, *, primary_task: Optional[Dict[str, Any]], tasks: List[Dict[str, Any]]) -> List[str]:
        checkpoints: List[str] = []
        if primary_task:
            checkpoint = _clip_text(primary_task.get("checkpoint"), 120)
            if checkpoint:
                checkpoints.append(checkpoint)
        for task in tasks[1:4]:
            checkpoint = _clip_text(task.get("checkpoint"), 120)
            if checkpoint:
                checkpoints.append(checkpoint)
        return _normalize_lines(checkpoints, max_items=4, max_chars=180)

    def _derive_recent_progress(self, session: Any, tasks: List[Dict[str, Any]]) -> List[str]:
        progress: List[str] = []
        for task in tasks[:4]:
            outcome = _clip_text(task.get("last_outcome") or task.get("completion_summary") or task.get("last_summary"), 120)
            role = _clip_text(task.get("task_role"), 70) or "task"
            if outcome:
                progress.append(f"{role}: {outcome}")
        events = getattr(session, "event_history", []) or []
        for event in list(events)[-3:]:
            if not isinstance(event, dict):
                continue
            summary = _clip_text(event.get("summary") or event.get("outcome"), 120)
            if summary:
                progress.append(summary)
        return _normalize_lines(progress, max_items=4, max_chars=180)

    def _derive_watchpoints(
        self,
        *,
        session: Any,
        open_loops: List[str],
        blockers: List[str],
        constraints: List[str],
        broker_snapshot: Optional[Dict[str, Any]],
    ) -> List[str]:
        watchpoints: List[str] = []
        if open_loops:
            watchpoints.append(open_loops[0])
        if blockers:
            watchpoints.append(blockers[0])
        if constraints:
            watchpoints.append(constraints[0])
        if getattr(session, "pending_action", None):
            watchpoints.append("There is a resumable action waiting for user approval.")
        if (
            isinstance(broker_snapshot, dict)
            and not bool(broker_snapshot.get("evidence_count"))
            and (open_loops or blockers or constraints or getattr(session, "pending_action", None))
        ):
            watchpoints.append("Avoid assuming missing broker evidence implies missing capability.")
        return _normalize_lines(watchpoints, max_items=5, max_chars=180)
