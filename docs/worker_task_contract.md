# Worker + Task Contract (Normative)

## 1. Purpose
This document defines the **authoritative contract** for asynchronous execution in Assistant-OS:
- `TaskDefinition` (what to run)
- `ScheduleTrigger` (when to run)
- `TaskExecution` (audit trail for scheduled runs)
- `Work` (runtime unit for both scheduled and interactive jobs)

All future changes to scheduler, worker orchestration, APIs, UI, and capabilities **must comply** with this contract.

## 2. Scope
This contract applies to:
- Backend runtime: `src/core/scheduler.py`, `src/core/worker.py`, `src/core/orchestrator.py`, `src/main.py`
- Task APIs: `src/server/routes/tasks.py`
- Session routing/status sync: `src/server/routes/sessions.py`, `src/drivers/server_driver.py`, `src/main.py`
- Task/Worker UI surfaces: `frontend/src/pages/Tasks.jsx`, `frontend/src/components/tasks/*`, `frontend/src/pages/Chat.jsx`

## 3. Core Entities

### 3.1 TaskDefinition (declarative)
Represents reusable intent + context.
- Stable fields: `task_id`, `name`, `context`, `owner_session_id`, `owner_sender_id`, `notes`, `created_at`
- Must be immutable by execution runtime except `notes` and explicit management operations.

### 3.2 ScheduleTrigger (declarative)
Represents scheduling policy.
- Stable fields: `trigger_id`, `task_id`, `schedule_type`, `schedule_value`, `holiday_rules`, `enabled`, `last_run`, `next_run`
- Trigger ownership follows linked task ownership unless explicitly overridden in future schema migrations.

### 3.3 TaskExecution (audit)
Represents historical scheduled execution record.
- Stable fields: `execution_id`, `task_id`, `trigger_id`, `status`, `start_time`, `end_time`, `log_file`, `cancel_requested`
- MUST exist for scheduled runs (best effort persistence).

### 3.4 Work (runtime)
Represents actual asynchronous runtime activity for both manual and scheduled operations.
- Stable fields include:
  - identity/routing: `work_id`, `session_id`, `owner_session_id`, `favorite_session_id`, `owner_sender_id`, `favorite_sender_id`, `scope`
  - lifecycle: `status`, `created_at`, `started_at`, `updated_at`, `result`, `error`, `cancel_requested`
  - storage: `work_dir`, `context_file`, `status_file`, `events_file`
  - metadata: `label`, `key`

`Work` is the unifying abstraction for "worker" and "task runtime".

## 4. Work Lifecycle (State Machine)
Allowed statuses:
- `queued`
- `running`
- `waiting_user`
- `paused`
- `failed`
- `succeeded`
- `cancelled`

### 4.1 Legal transitions
- `queued -> running | cancelled | failed`
- `running -> waiting_user | paused | succeeded | failed | cancelled`
- `waiting_user -> running | cancelled | failed`
- `paused -> running | cancelled | failed`
- terminal: `succeeded | failed | cancelled` (no further transitions except migration/repair operations)

### 4.2 Transition invariants
- Every transition MUST update `updated_at`.
- On first `running`, `started_at` MUST be set.
- Terminal transition MAY set `result` or `error`.
- Every transition MUST append `status_change` event to `events.jsonl`.
- Every transition MUST emit `work_status_change` into kernel event bus.

## 5. Command Contract (Control Plane)
Accepted commands (current):
- `pause`
- `resume`
- `cancel`
- `approve`
- `deny`
- `inject_message`
- `update_context`

### 5.1 Command behavior
- Commands are enqueued in scheduler command queue and consumed by orchestrator loop.
- Unknown commands MUST be ignored safely and never crash loop.
- `pause` MUST set work status to `paused` and keep work resumable.
- `resume` MUST set status back to `running`.
- `inject_message` MUST append to worker-side queue/history context (not drop original user message history).
- `cancel` MUST force exit path and terminal `cancelled`.

## 6. Context Contract
Each work context file (`context.json`) contains at minimum:
- `summary` object
- `planner` object
- `data` object

### 6.1 Reserved keys
- `summary.goal`
- `summary.status`
- `summary.cursor`
- `summary.last_action`
- `summary.last_thought`
- `summary.final_response`
- `planner.steps`
- `planner.max_steps`
- `planner.replan_budget`
- `planner.replans_used`
- `data.actions_used`
- `data.capabilities_used`
- `data.media_used`
- `data.queued_messages`
- `data.task_id`
- `data.trigger_id`
- `data.execution_id`
- `data.origin`

### 6.2 Context rules
- Writers MUST patch/merge; never blindly overwrite entire file from unrelated flow.
- Unknown keys MUST be preserved.
- Lists SHOULD be bounded (`actions_used`, `capabilities_used`, `media_used`, etc.) to avoid unbounded growth.

## 7. Event Contract (Observability)
`events.jsonl` is append-only and chronological.
Each event MUST include:
- `ts`, `event`, `work_id`, `session_id`
- owner/favorite session/sender metadata when available
- event-specific `payload`

Mandatory event types:
- `created`
- `status_change`
- `progress`

Consumers (UI/API) MUST tolerate additional event types.

## 8. Session Synchronization Contract
Main chat session synchronization is mandatory for user trust.

### 8.1 Required behavior
- For every `work_status_change`, kernel MUST forward a status update to the target session (favorite -> owner -> original fallback).
- For terminal statuses (`succeeded`, `failed`, `cancelled`), kernel MUST emit completion signal to session channel to close thinking/loading state.
- Waiting-for-approval states MUST enqueue digest requests and optionally notify user depending on idle/cooldown policy.

### 8.2 Duplication tolerance
UI MUST tolerate duplicate `complete` signals and deduplicate assistant content by id/content strategy.

## 9. Access Control Contract
Worker visibility/control is identity-scoped.
- `worker_view_scope`: `origin` | `group` | `global`
- `worker_control_scope`: `origin` | `group` | `global`

Rules:
- Admin may bypass.
- Non-admin operations MUST pass policy check before view/control endpoints.
- Ownership links are identity-based (`owner_sender_id`, `favorite_sender_id`) and session-linked (`owner_session_id`, `favorite_session_id`).

## 10. API Contract (Tasks/Works)
Current worker endpoints:
- `GET /api/tasks/works`
- `GET /api/tasks/works/{work_id}`
- `GET /api/tasks/works/{work_id}/events`
- `GET /api/tasks/works/{work_id}/overwatch`
- `POST /api/tasks/works/{work_id}/commands`
- `POST /api/tasks/works/{work_id}/pause`
- `POST /api/tasks/works/{work_id}/resume`
- `POST /api/tasks/works/{work_id}/queue_message`
- `POST /api/tasks/works/{work_id}/direct_message`
- `POST /api/tasks/works/{work_id}/notes`

Compatibility requirements:
- Additive response fields are allowed.
- Removing/renaming existing fields requires migration + versioning + UI compatibility patch.

## 11. UI Overwatch Contract
Task Overwatch UI MUST expose at minimum:
- `Overview`: goal, cursor, status, last thought/action, origin metadata
- `Flow`: live/recent events
- `Capabilities`: capability/action usage
- `Media`: media artifacts
- `Triggers/Executions`: trigger info + execution counts/history
- `Notes`: contextual annotations
- `Queue`: queued message + pause-and-direct message mode
- Controls: pause/resume

UI MUST auto-refresh while an overwatch panel is open (polling or stream).

## 11.1 User Feedback During Async Execution
- On worker start, system MUST emit an immediate user-facing acknowledgment message in the origin session.
- For long-running works, system SHOULD emit periodic progress feedback when meaningful milestones/fallbacks occur.
- Progress feedback MUST be throttled (loop/time/message count) to avoid chat spam.
- Progress feedback MUST NOT break final response lifecycle (`status -> response -> complete`).

## 12. Storage Layout Contract
- Global work scope: `data/works/{work_id}/...`
- Session work scope: `data/sessions/{session_id}/works/{work_id}/...`

Required files:
- `work.json` (status snapshot)
- `context.json` (mutable runtime context)
- `events.jsonl` (append-only timeline)

## 13. Failure Semantics
- Worker/orchestrator exceptions MUST not crash kernel.
- Failure paths MUST set terminal status and surface user-readable error in session channel when possible.
- Repetition/loop guardrails MAY stop execution but MUST provide explicit reason and mark state (`blocked` summary or terminal status).

## 14. Concurrency and Threading Rules
- Scheduler registry mutations require scheduler lock.
- Context updates must be atomic enough to prevent truncated JSON writes.
- Event bus consumers MUST never block indefinitely on downstream sender operations.

## 15. Non-Goals (for this contract)
- Defining exact reasoning model internals.
- Defining external channel UX text templates beyond control semantics.
- Guaranteeing strict exactly-once delivery for every websocket event.

## 16. Change Management Checklist (Mandatory)
Before merging worker/task changes:
1. Validate legal status transitions.
2. Verify session status synchronization (`status` + terminal `complete`) in web chat.
3. Verify access control for origin/group/global scopes.
4. Verify overwatch payload integrity (`summary/planner/data/events`).
5. Verify task scheduled runs still create execution logs.
6. Run targeted tests (worker coordination, permissions, task routes) and frontend build.
7. Update this contract if behavior changed.

## 17. Versioning
Contract version: `1.0.0`
Last updated: `2026-02-23`

If contract-breaking behavior is introduced, increment major version and provide migration notes.
