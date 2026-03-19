# Cognitive Layer v1 Stage 1 Implementation Report

## 1. Executive Summary

Stage 1 of Cognitive Layer v1 has been implemented as a conservative, production-safe strategic state layer.

This implementation introduces:

- persistent `Session.cognitive_state`
- typed cognitive models under `src/services/cognition/`
- deterministic pre-turn reconciliation
- compact prompt projection from cognitive state
- cognitive diagnostics persisted into session context
- strict fallback to the legacy `build_cognitive_frame()` path when needed

The broker-centric architecture was preserved. No cognitive retrieval, broker query shaping, post-turn strategic mutation, or LLM-generated cognition was added in this stage.

## 2. Cognitive State Model Implemented

New typed cognition modules were added:

- `src/services/cognition/models.py`
- `src/services/cognition/reconciler.py`
- `src/services/cognition/projector.py`
- `src/services/cognition/layer.py`
- `src/services/cognition/__init__.py`

The implemented persistent state shape matches the approved v1 design closely:

- `version`
- `updated_at`
- `turn_id`
- `mission`
- `focus`
- `agenda`
- `open_loops`
- `blockers`
- `constraints`
- `assumptions`
- `decisions`
- `working_set`
- `checkpoints`
- `recent_progress`
- `watchpoints`
- `provenance`

The state remains bounded and strategic. It stores short, planner-friendly facts rather than hidden reasoning traces.

## 3. Session Persistence Changes

`src/core/session.py` now persists:

- `cognitive_state`
- `last_cognitive_projection`
- `cognitive_diagnostics`

These fields were added to:

- `Session.__init__`
- `Session.to_dict()`
- `Session.from_dict()`

This makes cognitive state survive normal session save/load behavior without changing the existing session persistence flow in `AgentOrchestrator`.

## 4. Deterministic Reconciliation Rules

Stage 1 uses a fully deterministic reconciler in `src/services/cognition/reconciler.py`.

Implemented rules include:

- `mission.objective`
  - prefers current user input
  - then active primary task summary/role
  - then `session.state_summary["goal"]`

- `focus.primary_task_id` and `focus.primary_summary`
  - prefer `active_focus_task_id`
  - then highest-salience non-terminal task
  - otherwise fall back to mission-oriented summary

- `open_loops`
  - derive from pending actions
  - waiting-user tasks
  - blocked dependencies
  - resumable checkpoints

- `blockers`
  - derive from blocked tasks
  - waiting-user states
  - failure summaries
  - degraded tool health
  - pending confirmation
  - visible auth/config problems in session context

- `constraints`
  - derive from degraded tools
  - driver/runtime presentation limits
  - pending action gating
  - no-evidence broker mode

- `working_set`
  - includes a small bounded set of hot tactical facts such as objective, primary task, session summary, memory notes, and broker intent

- `watchpoints`
  - derive from highest-priority open loops, blockers, constraints, pending approvals, and no-evidence broker mode

All list fields are bounded and deduplicated.

## 5. Prompt Projection Design

Prompt projection is implemented in `src/services/cognition/projector.py`.

The projection stays compact and compatible with the prompt-reduction architecture:

- `[FOCUS]`
  - `objective=...`
  - `primary=...`
  - `next=...`
  - `open_loops=...`

- `[BACKGROUND]`
  - `secondary=...`
  - `blockers=...`
  - `constraints=...`
  - `watchpoints=...`

`src/services/llm/prompt_composer.py` now accepts `cognitive_projection` and prefers it when available. If no projection is supplied, the existing legacy `cognitive_frame` path still works unchanged.

## 6. Orchestrator Integration Changes

`src/core/orchestrator.py` now:

- initializes `self.cognitive_layer = CognitiveLayer()`
- reconciles cognitive state after broker diagnostics are available and before prompt composition
- persists:
  - `session.cognitive_state`
  - `session.last_cognitive_projection`
  - `session.cognitive_diagnostics`
  - `session.context["last_cognitive_layer"]`
- passes either:
  - `cognitive_projection` to `PromptComposer`, or
  - `cognitive_frame` from the legacy path when fallback is required

This stage only adds pre-turn reconcile + projection + persistence.

It does not add post-turn strategic commit logic.

## 7. Fallback Behavior

Fallback safety was implemented explicitly.

Behavior:

- if reconciliation fails and a previous cognitive state exists, the layer preserves the previous valid state and still projects from it when possible
- if projection cannot be produced, the orchestrator falls back to the legacy `session.get_cognitive_frame(user_input)` path
- prompt composition remains valid even when cognition falls back
- broker flow remains unchanged when cognition is absent or failing

Fallback diagnostics are recorded using:

- `fallback_used`
- `fallback_mode`

## 8. Diagnostics / Observability Added

The new cognitive layer emits compact diagnostics with fields such as:

- `version`
- `reconciled_at`
- `turn_id`
- `primary_task_id`
- `agenda_count`
- `open_loops_count`
- `blockers_count`
- `constraints_count`
- `decisions_count`
- `working_set_count`
- `changed_fields`
- `fallback_used`
- `fallback_mode`

These are stored in:

- `session.cognitive_diagnostics`
- `session.context["last_cognitive_layer"]`

This keeps the layer inspectable and testable in the same style as broker and prompt-reduction observability.

## 9. Tests Added

New tests added:

- `tests/cognition/test_cognitive_state_persistence.py`
- `tests/cognition/test_cognitive_reconciler.py`
- `tests/cognition/test_cognitive_projector.py`
- `tests/cognition/test_cognitive_fallback.py`
- `tests/cognition/test_cognitive_orchestrator_integration.py`

Validated in this implementation pass:

- `./env/bin/pytest -q tests/cognition`
- `./env/bin/pytest -q tests/minimal/test_prompt_composer_assistive_mode.py tests/minimal/test_prompt_persona_scope.py tests/minimal/test_context_broker_phase1.py`
- `/usr/bin/python3 -m compileall src/services/cognition src/core/session.py src/core/orchestrator.py src/services/llm/prompt_composer.py`

Results:

- cognition test suite passed
- targeted compatibility sweep passed
- modified modules compiled successfully

## 10. Current Limitations

Intentional Stage 1 limitations:

- no post-turn strategic mutation/commit logic
- no broker hinting or query shaping
- no LLM-assisted cognition
- no cross-session cognition
- no cognitive retrieval / RAG domain
- no autonomous reprioritization
- no heavy planner redesign

Also, `assumptions` and `decisions` are currently preserved as bounded state rather than actively synthesized, which keeps Stage 1 deterministic and low-risk.

## 11. Recommended Cognitive Layer Stage 2

Recommended next step for Stage 2:

- add post-turn strategic commit logic
- update decisions/checkpoints/recent progress from execution outcomes
- refine assumptions/decision handling with deterministic state transitions
- optionally add broker hinting from cognitive focus, but only after proving Stage 1 stable
- expand observability to compare cognitive projection quality across long-running sessions

The key principle should remain unchanged:

- keep cognition deterministic unless there is strong evidence an LLM-assisted layer is necessary
- keep cognition separate from retrieval and memory domains
- preserve compact prompts and stable fallback behavior
