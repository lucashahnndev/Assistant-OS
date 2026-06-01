# Assistant-OS System Audit

> Historical report. This audit reflects a point-in-time architectural diagnosis and may not match the current discovery-first contract.

Date: 2026-05-24
Repository: `Assistant-OS`
Scope: backend orchestration, worker/work model, goal governance, browser control, live panel/runtime synchronization

## Executive Summary

This audit confirms that the system's current limitations are not primarily caused by model size or lack of vision. The largest gaps are architectural and operational:

- the platform is asynchronous in infrastructure, but often synchronous in behavior
- goal ownership is fragmented across multiple state layers
- browser control is treated as a resource-exclusive workflow, but that exclusivity leaks into whole-session UX
- the worker model exists in two partially overlapping implementations
- the live panel historically lagged behind the dashboard in state synchronization and artifact promotion

The net result is a system that can spawn workers and long-running tasks, but still tends to behave as if only one task can safely exist per session. Browser control amplifies the problem, but it is not the root cause by itself.

## Method

This report is based on a fresh code audit of:

- kernel and admission path: `src/main.py`
- orchestrator and cognitive loop: `src/core/orchestrator.py`
- session, intents, cognition, reconciler: `src/core/session.py`, `src/core/intents.py`, `src/core/cognition.py`, `src/services/cognition/reconciler.py`
- worker/work runtime: `src/core/scheduler.py`, `src/core/worker.py`, `src/core/worker_runtime.py`, `agent/specs/worker_task_contract.spec.md`
- browser control capability/runtime/planner: `src/capabilities/browser_control/*`
- live panel and media/playback routing: `frontend/src/pages/PainelVivo.jsx`

This report also incorporates the recent live panel stabilization work already present in the current working tree.

## Current Architecture

### 1. Runtime Model

The system has a real async execution substrate:

- `Work` is the runtime unit in `src/core/scheduler.py`
- workers can be spawned through `Kernel.process_input(...)` in `src/main.py`
- a richer worker abstraction exists in `src/core/worker_runtime.py`
- the orchestrator can create worker-linked task structures through `AgentOrchestrator.spawn_worker(...)`

This means the platform is not fundamentally single-threaded or single-task.

### 2. Cognitive/Goal Layers

There are several overlapping representations of "what the system is trying to do":

- `session.state_summary.goal`
- `work.context.summary.goal`
- `cognitive_frame.objective`
- `cognitive_state.mission.objective`
- `intent_agenda` open intents
- browser planner `goal`, `meta_goal`, `phase_goal`, `completion_contract`

These layers are individually useful, but no single layer is currently the hard authority.

### 3. Browser Control Stack

Browser control is a multi-layer stack:

- routing decision in prompt/orchestrator
- capability execution in `browser_control_capability.py`
- runtime transport in `runtime_playwright.py`
- MCP adapter in `playwright_mcp_adapter.py`
- agentic browser planner in `planner.py`

This stack is capable, but several parts are still too agentic or too globally coupled.

## Key Findings

## A. Async Infrastructure Exists, But Session Behavior Is Still Often Serial

### Evidence

- `Kernel._admission_gate(...)` in `src/main.py` blocks new work whenever active works exist, except for a few special cases.
- media/browser actions can trigger `confirm_takeover` instead of parallel coexistence.
- non-media actions can still be rejected with session busy behavior.
- browser execution also uses per-instance and per-tab locks in `browser_control_capability.py`.

### Impact

Users experience Atlas as "one task at a time", even though the system already has workers and a scheduler.

This is especially visible during browser tasks because:

- browser tasks are slow
- browser tasks are exclusive over a scarce resource
- admission policy promotes the exclusivity of the resource into exclusivity of the session

### Root Cause

The current system lacks a clear distinction between:

- conversation concurrency
- worker concurrency
- resource exclusivity
- user-facing foreground ownership

## B. Goal Governance Is Fragmented

### Evidence

- `session.state_summary.goal` is still updated from planner metadata in `src/core/orchestrator.py`
- `Work` persists its own `summary.goal` in `src/core/scheduler.py`
- `build_cognitive_frame(...)` uses `session.state_summary.goal` directly in `src/core/cognition.py`
- `CognitiveReconciler._derive_objective(...)` may derive objective from user input, primary task, or session goal in `src/services/cognition/reconciler.py`
- `IntentAgenda` tracks open and paused intents but does not fully arbitrate execution in `src/core/intents.py`

### Impact

The system can exhibit:

- stale goal resumption
- random-seeming reentry into an older task
- divergence between what the user just asked, what the worker is doing, and what the session says the current goal is

### Root Cause

There is no single canonical hierarchy such as:

`foreground_work.goal -> current_turn.goal -> session summary goal`

As a result, multiple components can think they are allowed to define the active objective.

## C. Two Worker Models Coexist

### Evidence

- `src/core/worker.py` defines a basic `Worker` thread wrapper
- `src/core/worker_runtime.py` defines a richer eventful worker runtime with checkpointing, stall detection, supersession checks, and memory proposal support

### Impact

This creates maintenance and behavioral ambiguity:

- two different mental models of async execution
- potentially different semantics for progress, cancellation, and recovery
- harder reasoning about which worker contract is authoritative

### Root Cause

The platform appears to be mid-migration from a simpler thread wrapper to a richer worker supervision model, but both are still present.

## D. Supersession Exists, But It Is Too Local

### Evidence

- `AgentOrchestrator.spawn_worker(...)` marks prior tasks with the same `intent_group_id` as superseded
- `WorkerRuntime.is_superseded()` only checks whether its own task was marked superseded in `session.task_registry`
- focus policy exists in `_process_worker_events(...)` and `_decide_on_worker_events(...)`

### Impact

Supersession is helpful, but still not enough to prevent wrong-goal execution because:

- it is tied to `intent_group_id`, not a stronger `goal_id` model
- it does not fully unify with session-level goal ownership
- it does not define freshness or precedence across turns

### Root Cause

Supersession today is a task-local mechanism, not a global goal-governance mechanism.

## E. Browser Control Is Over-Agentic For Many Tasks

### Evidence

- the browser planner generates a master plan through LLM decomposition
- it derives `meta_goal`, `phase_goal`, and `action_intent`
- it builds completion contracts and recovery actions
- it fuses DOM and screenshot perception for state reconstruction

All of this is powerful, but it means many simple tasks still go through:

- plan synthesis
- phase maintenance
- perception fusion
- structured action generation
- parse fallback
- recovery logic

### Impact

This increases:

- latency
- drift risk
- loop probability
- fragility under local models

Claude Code-like systems often appear stronger not only because of model quality, but because they do more deterministic work before invoking rich agentic planning.

### Root Cause

The browser system is optimized for generality and recoverability, but not yet strongly optimized for fast-path determinism on simple goals.

## F. Browser Resource Locks Are Correct, But Poorly Surfaced

### Evidence

- browser execution acquires instance and tab locks in `browser_control_capability.py`
- playback and execution metadata are attached to browser runs
- admission gate still treats active work as a broad blocker

### Impact

Users perceive:

- "Atlas is stuck"
- "Atlas says it can only do one thing"
- "browser task hijacked the assistant"

Even when the real constraint is narrower:

- a specific browser instance
- a tab
- a media singleton

### Root Cause

Resource exclusivity is not separated clearly enough from conversational concurrency.

## G. Live Panel Historically Masked Progress And Increased Perceived Failure

### Evidence

The live panel previously diverged from the dashboard in:

- playback event consumption
- terminal tracking
- link preview integration
- artifact routing
- stage persistence
- semantic deduplication

These gaps have now been substantially reduced in the current working tree, but they were part of the original perception problem.

### Impact

Even when backend/browser execution partially worked, the user often saw:

- missing playback
- repeated cards
- stale or lost terminal streams
- duplicated media promotions

This made browser control look less capable than it really was.

### Root Cause

The live panel was not consuming the same state model as the more mature dashboard path.

## H. Worker Contract Is Good, But Missing Strong Goal/Supersession Semantics

### Evidence

`agent/specs/worker_task_contract.spec.md` defines:

- work lifecycle
- command contract
- context contract
- event contract
- session synchronization contract

But it does not yet strongly define:

- canonical goal identity
- work supersession rules
- stale work rejection rules
- active foreground owner semantics

### Impact

The platform has a strong execution contract, but a weaker objective-governance contract.

## Why This Is Not Mainly A "Weak Model" Problem

The codebase already shows that many failures were due to:

- admission policy
- stale goal selection
- weak supersession semantics
- browser lock leakage into session UX
- incomplete frontend synchronization
- overly agentic browser flow for simple tasks

This explains why even stronger models can still fail in the current environment: the environment itself still makes goal drift and serial behavior likely.

## Recommended Correction Strategy

## Phase 1. Canonical Goal Governance

### Objective

Create a single authority chain for objective ownership.

### Changes

1. Introduce canonical identifiers:
- `goal_id`
- `goal_text`
- `origin_turn_id`
- `parent_intent_id`
- `supersedes_goal_id`
- `freshness_epoch`

2. Define authority order:
- `foreground_work.goal` is operational truth
- `current_turn.goal` is pre-commit truth
- `session.state_summary.goal` becomes summary only
- `intent_agenda` tracks open loops, but does not implicitly reactivate work

3. Reject planner-provided goal rewrites unless they match current turn/work lineage.

### Files

- `src/core/orchestrator.py`
- `src/core/session.py`
- `src/core/intents.py`
- `src/core/scheduler.py`
- `src/services/cognition/reconciler.py`

## Phase 2. Session/Work Concurrency Redesign

### Objective

Make the platform behavior match its async architecture.

### Changes

1. Replace broad session blocking with class-based admission:
- `reply_fast`
- `lookup_native`
- `worker_background`
- `browser_exclusive`
- `approval_blocked`

2. Allow non-conflicting work to coexist:
- quick replies while a browser worker runs
- native lookup while a browser worker runs
- independent background workers when no scarce resource conflicts exist

3. Keep exclusivity only where justified:
- browser instance
- tab
- media singleton
- waiting approval for a specific action

### Files

- `src/main.py`
- `src/core/scheduler.py`
- `src/core/orchestrator.py`

## Phase 3. Supersession And Reentry Policy

### Objective

Prevent old work from resurfacing arbitrarily.

### Changes

1. Add explicit work states or metadata:
- `foreground`
- `background`
- `paused`
- `superseded`
- `abandoned`

2. Before reentry or continuation:
- validate goal freshness
- validate parent intent still open
- validate work still belongs to active objective

3. Add supersession checks at the scheduler/admission layer, not only worker-local checks.

### Files

- `src/core/orchestrator.py`
- `src/core/scheduler.py`
- `src/core/worker_runtime.py`

## Phase 4. Unify Worker Runtime

### Objective

Converge on one worker model.

### Changes

1. Make `WorkerRuntime` the authoritative async execution abstraction.
2. Decommission or narrow `src/core/worker.py` to simple compatibility glue.
3. Standardize:
- progress reporting
- cancellation semantics
- checkpointing
- waiting-for-user behavior
- event emission

### Files

- `src/core/worker.py`
- `src/core/worker_runtime.py`
- `src/main.py`
- `agent/specs/worker_task_contract.spec.md`

## Phase 5. Browser Control Optimization

### Objective

Make browser control more deterministic for simple tasks and more robust for complex ones.

### Changes

1. Add browser execution modes:
- `lookup`
- `navigate`
- `extract`
- `form`
- `media`
- `transaction`

2. Add deterministic fast paths before full planner:
- open URL
- search query
- collect result titles/links
- click obvious CTA
- fill one visible field

3. Improve run memory:
- current URL
- current tab
- last successful action
- last failed action
- attempted selectors/targets
- recovery history

4. Upgrade recovery ladder:
- wait
- role/text fallback
- scroll/reposition
- refresh state
- deterministic re-navigation
- only then deeper replan

### Files

- `src/capabilities/browser_control/browser_control_capability.py`
- `src/capabilities/browser_control/planner.py`
- `src/capabilities/browser_control/runtime_playwright.py`

## Phase 6. Observability And Forensics

### Objective

Make failures explainable.

### Add Events/Logs

- `goal_selected`
- `goal_superseded`
- `foreground_owner_changed`
- `admission_gate_decision`
- `worker_spawned`
- `worker_reentry_denied`
- `browser_mode_selected`
- `browser_lock_wait`
- `planner_recovery_triggered`

### UI/Inspector Surfacing

- active goal
- foreground work
- blocked reason
- browser exclusivity state
- approval pending state

## Phase 7. Contract Update

### Objective

Document the new invariants so future regressions are less likely.

### Update `agent/specs/worker_task_contract.spec.md`

Add normative sections for:

- canonical goal ownership
- supersession
- stale work rejection
- foreground vs background execution
- concurrency classes

## Priority Order

1. goal governance
2. admission/concurrency redesign
3. supersession/reentry policy
4. worker runtime unification
5. browser deterministic optimization
6. observability
7. contract update

## Acceptance Criteria

The update should be considered successful only if:

1. A browser task no longer forces the whole session into perceived single-task mode.
2. Quick replies or native lookups can coexist with long-running workers when safe.
3. The system never resumes an old goal without explicit lineage and freshness checks.
4. The active foreground goal is always inspectable and explainable.
5. Browser control uses deterministic fast paths for simple tasks before invoking rich planner logic.
6. Live panel and dashboard both reflect the same async state model consistently.

## Final Assessment

Assistant-OS already contains most of the pieces needed for a high-quality async agent:

- a scheduler
- works
- workers
- task events
- intent tracking
- a browser capability with structured planning
- a live panel capable of rich state rendering

The main issue is not missing infrastructure, but insufficient unification of control logic across those layers.

The most important next move is not "swap to a bigger model". It is to make objective ownership, concurrency policy, and browser resource boundaries explicit and authoritative across the entire stack.

## Relacionados

- [../architecture/README.md](../architecture/README.md): contexto arquitetural do sistema e das areas investigadas.
- [../guides/browser_control_playbook.md](../guides/browser_control_playbook.md): playbook operacional da parte de browser control citada no audit.
- [session_event_contract_runtime_audit.md](session_event_contract_runtime_audit.md): auditoria complementar da camada de eventos e persistencia.
- [atlas-agent-mode-cognition-deep-audit-2026-05-29.md](atlas-agent-mode-cognition-deep-audit-2026-05-29.md): audit complementar da camada de cognicao e continuidade.
- [../../agent/specs/system_architecture.spec.md](../../agent/specs/system_architecture.spec.md): contrato arquitetural ativo que enquadra o runtime.
- [../../agent/specs/worker_task_contract.spec.md](../../agent/specs/worker_task_contract.spec.md): contrato de worker/work que sustenta o modelo assíncrono.
