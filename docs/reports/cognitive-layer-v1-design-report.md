# Cognitive Layer v1 Design Report

## 1. Executive Summary

The current architecture is now clearly broker-centric for knowledge retrieval and prompt-reduced for execution stability, but it still lacks a durable strategic state layer.

Today, the system has:

- strong bounded retrieval through the Context Broker
- compact prompt construction with stable fallback behavior
- multiple persistent state surfaces (`summary`, `scratchpad`, `state_summary`, task/event history, memory stores)
- only an ephemeral cognitive projection for the current turn

The next architectural step should be a **Cognitive Layer v1** that maintains persistent, session-local strategic state and produces a compact prompt projection for the planner.

This layer should not replace the broker, long-term memory, or task/event history. It should sit above them and answer a narrower question:

**What does the agent currently believe it is trying to do, what is still open, what matters now, and what should stay stable across turns?**

Recommended v1 direction:

- deterministic and code-driven first
- persistent per session
- compact prompt projection
- explicit separation from memory/RAG
- broker-aware but not broker-dependent
- safe fallback to the existing `build_cognitive_frame()` path

## 2. Current Architecture Analysis

### 2.1 Existing Strategic Inputs

The system already stores a large amount of raw and semi-structured state:

- `Session.summary`
- `Session.scratchpad`
- `Session.state_summary`
- `Session.task_registry`
- `Session.event_history`
- `Session.event_timeline`
- `Session.decision_traces`
- `Session.memory`
- `Session.context["last_context_broker"]`
- `Session.context["last_prompt_reduction"]`

This gives the system plenty of truth sources, but not a single durable strategic interpretation of that truth.

### 2.2 Current Cognition Is Ephemeral

`src/core/cognition.py` builds a `CognitiveFrame` dynamically from session state for the current reasoning turn.

Current behavior:

- derives an objective from `session.state_summary["goal"]`
- extracts a single primary task from `task_registry`
- collects secondary tasks, blockers, and constraints
- adds active intents when present
- stores only a tiny observability snapshot via `last_cognitive_frame_snapshot`

This is useful as a projection layer, but it is not a persistent cognitive system:

- no durable open-loop model
- no explicit strategic commitments
- no persistent assumptions/decision ledger
- no notion of what changed between turns
- no bounded strategic working set distinct from scratchpad or summary

### 2.3 Broker Role Is Well Defined

`src/services/context/broker.py` now handles:

- intent classification
- selective retrieval routing
- bounded retrieval per domain
- deterministic reranking
- normalized evidence packaging

The broker is currently optimized for knowledge retrieval, not strategic continuity.

That separation is healthy and should be preserved.

The Cognitive Layer should therefore:

- consume broker output when useful
- optionally provide hints back to broker later
- avoid becoming another retrieval subsystem in v1

### 2.4 Prompt Path Is Ready for a Better Strategic Projection

`src/services/llm/prompt_composer.py` already supports compact cognitive injection through:

- `[FOCUS]`
- `[BACKGROUND]`

Those blocks are currently generated from the ephemeral `CognitiveFrame`.

This is the ideal seam for Cognitive Layer v1:

- keep prompt output compact
- improve strategic quality
- avoid re-expanding prompt cost

### 2.5 Memory Systems Exist, But Serve Different Jobs

Current memory surfaces already cover other responsibilities:

- `MemoryService`: semantic long-term fact retrieval
- `EpisodicMemoryService`: prior action/outcome episodes
- session memory arrays: accepted per-session memory items
- scratchpad: freeform working notes

None of these are a clean substitute for strategic state.

The missing layer is not “more memory.” It is **persistent interpretation and prioritization**.

## 3. Problem Statement

The system currently recomputes focus each turn from raw session truth, but it does not maintain a stable strategic model across turns.

This creates four architectural gaps:

1. **Strategic drift**
   The planner can lose stable intent framing across long, multi-step, or interrupted sessions.

2. **Overloaded state surfaces**
   `summary`, `scratchpad`, and `state_summary` carry mixed responsibilities: recap, working notes, and strategy.

3. **Poor change tracking**
   The system stores plenty of history, but not a compact record of what strategic assumptions, blockers, or commitments changed.

4. **No durable attention model**
   There is no canonical representation of foreground vs background work that survives beyond the current derived frame.

## 4. Cognitive Layer v1 Goals

The Cognitive Layer v1 should:

- maintain persistent session-local strategic state
- produce a compact prompt projection for planning
- track open loops, blockers, and current focus across turns
- record a bounded strategic ledger of decisions and assumptions
- stay deterministic and inspectable
- degrade safely without affecting broker fallback behavior

The Cognitive Layer v1 should not:

- store chain-of-thought
- replace long-term memory or episodic memory
- become a general-purpose RAG domain
- perform heavy autonomous planning outside the existing planner/orchestrator path
- rewrite the broker architecture

## 5. Proposed Architecture

### 5.1 Position in the Stack

Recommended placement:

`Session Truth -> Cognitive Layer -> Broker + Planner Prompt -> Resolver/Execution -> Session Truth`

Interpretation:

- session/task/event state remains source-of-truth runtime data
- broker remains source-of-truth retrieval layer
- cognitive layer becomes source-of-truth strategic continuity layer

### 5.2 Core Responsibilities

Cognitive Layer v1 should perform five jobs:

1. **Observe**
   Read session truth, current user turn, and recent system/execution signals.

2. **Reconcile**
   Convert raw state into a persistent strategic model.

3. **Persist**
   Store the latest cognitive state on the session object and disk with versioning.

4. **Project**
   Emit a compact planner-facing digest for prompt composition.

5. **Audit**
   Track what strategic items changed and expose lightweight diagnostics.

## 6. Recommended Data Model

### 6.1 Persistent Cognitive State

Recommended top-level object:

```json
{
  "version": "cognitive.v1",
  "updated_at": 0,
  "turn_id": 0,
  "mission": {
    "objective": "",
    "status": "active"
  },
  "focus": {
    "primary_task_id": null,
    "primary_summary": "",
    "reasoning_mode": "standard",
    "attention_mode": "foreground"
  },
  "agenda": [],
  "open_loops": [],
  "blockers": [],
  "constraints": [],
  "assumptions": [],
  "decisions": [],
  "working_set": [],
  "checkpoints": [],
  "recent_progress": [],
  "watchpoints": [],
  "provenance": {
    "sources": [],
    "broker_evidence_used": false
  }
}
```

### 6.2 Field Semantics

Recommended meanings:

- `mission`
  Stable current objective for the session or active request cluster.

- `focus`
  What should dominate the next planning turn.

- `agenda`
  Bounded list of active strategic threads, including paused/background items.

- `open_loops`
  Unresolved commitments, unanswered questions, pending confirmations, incomplete workflows.

- `blockers`
  Explicit obstacles such as missing input, degraded tools, failed dependencies, authorization gaps.

- `constraints`
  Stable policy/tool/runtime constraints relevant to planning.

- `assumptions`
  Explicit, bounded assumptions currently being carried forward.

- `decisions`
  Short ledger of meaningful strategic choices made by the agent.

- `working_set`
  Small, non-memory-grade tactical facts worth keeping hot across turns.

- `checkpoints`
  Recovery anchors for resumability.

- `recent_progress`
  Short record of meaningful progress transitions, not verbose event history.

- `watchpoints`
  Things the planner should avoid forgetting on the next turn.

### 6.3 Important Boundary Rule

This state must store **strategic facts**, not hidden reasoning.

Allowed:

- `Need user confirmation before destructive step`
- `Primary task changed from search to report generation`
- `Assuming target repo is current workspace`

Not allowed:

- long hidden reasoning traces
- speculative internal monologues
- token-heavy freeform deliberation

## 7. Lifecycle

### 7.1 Pre-Turn Reconciliation

Before prompt composition:

- load current cognitive state from session
- inspect user input
- inspect active task registry and intent agenda
- inspect recent worker/supervisory signals
- inspect degraded tool state
- reconcile a new cognitive state snapshot

This step should be deterministic in v1.

### 7.2 Broker Interaction

In v1, broker interaction should stay minimal:

- cognitive layer may read `last_context_broker` or current broker diagnostics
- cognitive layer may note whether evidence was present
- broker does not need to retrieve cognitive state

Optional future extension:

- use cognitive state to provide retrieval hints such as active task labels or unresolved threads

### 7.3 Prompt Projection

The cognitive layer should emit a compact digest for prompt injection.

Recommended projection:

```text
[FOCUS]
objective=...
primary=[task] role|status|summary
next=...
open_loops=...

[BACKGROUND]
secondary=...
blockers=...
constraints=...
watchpoints=...
```

This keeps compatibility with the current prompt-reduction model while improving quality.

### 7.4 Post-Turn Commit

After the turn resolves, the system should commit strategic changes back into persistent cognitive state.

Likely signals:

- selected action
- state summary delta
- worker outcome
- newly created blocker
- completion or supersession of task
- user clarification requirement

This creates continuity without requiring full replay of raw history every turn.

## 8. Integration Plan

### 8.1 Session Model

Add a new persistent field to `Session`:

- `cognitive_state: Dict[str, Any]`

Also recommended:

- `last_cognitive_projection`
- `cognitive_diagnostics`

This should be serialized in `to_dict()` and `from_dict()`.

### 8.2 Service Layer

Recommended new module group:

- `src/services/cognition/models.py`
- `src/services/cognition/layer.py`
- `src/services/cognition/reconciler.py`
- `src/services/cognition/projector.py`

Suggested roles:

- `models.py`
  typed dataclasses / schema helpers

- `reconciler.py`
  deterministic strategic-state update rules

- `projector.py`
  compact prompt projection builder

- `layer.py`
  orchestration entry point used by `AgentOrchestrator`

### 8.3 Orchestrator

Recommended orchestrator seam:

1. Build or load cognitive state before prompt composition.
2. Pass compact projection into `PromptComposer`.
3. Persist diagnostics into `session.context`.
4. Commit strategic deltas after planning/execution events.

Minimum v1 requirement:

- pre-turn reconcile
- prompt projection
- persistence

Post-turn mutation can be added in the same phase if straightforward, or immediately after as v1.1.

### 8.4 Prompt Composer

Keep the current compact blocks, but change the source:

- old source: `session.get_cognitive_frame(user_input)`
- new source: `cognitive_layer.project_for_prompt(...)`

Fallback rule:

- if cognitive layer fails, use existing `get_cognitive_frame()` behavior unchanged

### 8.5 Existing `core/cognition.py`

Recommended treatment:

- keep as fallback compatibility path during migration
- later refactor or retire after stable adoption

This avoids risky big-bang replacement.

## 9. Deterministic Reconciliation Rules for v1

To preserve stability, v1 should use rule-based updates.

Recommended initial rules:

- objective defaults to active user request, then active primary task, then `state_summary.goal`
- primary focus prefers active foreground task, otherwise most relevant non-terminal task
- open loops are created from pending confirmations, blocked tasks, paused intents, and unresolved worker asks
- blockers are derived from dependency blocks, waiting-user states, degraded tools, and latest failure summaries
- constraints are derived from tool health, policy flags, and session/runtime conditions
- decisions are appended only for explicit mode shifts, handoffs, or confirmed strategy changes
- working set is capped and refreshed from recent progress plus durable session signals
- checkpoints are updated when meaningful progress or recovery anchors appear

Bound everything aggressively:

- no unbounded lists
- deduplicate semantically similar items
- keep newest/highest-salience items only

## 10. Diagnostics and Observability

The Cognitive Layer should expose compact diagnostics similar to broker and prompt-reduction observability.

Recommended fields:

```json
{
  "version": "cognitive.v1",
  "reconciled_at": 0,
  "turn_id": 0,
  "primary_task_id": "",
  "agenda_count": 0,
  "open_loops_count": 0,
  "blockers_count": 0,
  "constraints_count": 0,
  "decisions_count": 0,
  "working_set_count": 0,
  "changed_fields": [],
  "fallback_used": false
}
```

Persist in:

- `session.context["last_cognitive_layer"]`

This keeps the new layer inspectable and testable.

## 11. Fallback and Degraded Behavior

The Cognitive Layer must not become a new single point of failure.

Required fallback behavior:

- if reconciliation fails, keep prior `session.cognitive_state` if valid
- if no valid cognitive state exists, fall back to `build_cognitive_frame()`
- prompt composition must remain valid with no cognitive layer output
- broker flow must remain unchanged when cognitive layer is absent

This mirrors the resilience pattern already established in the broker and prompt-reduction work.

## 12. Why This Should Not Be a RAG Domain in v1

It may be tempting to add `cognitive_state` as another broker retrieval domain, but that is not the right first move.

Reasons:

- strategic state is session-local and should be immediately available
- retrieval adds latency and optionality where determinism is preferable
- prompt continuity needs current truth, not nearest-neighbor recall
- broker domains are for evidence retrieval, not live control state

Future versions may expose archived strategic state through retrieval, but v1 should keep cognition as a first-class runtime subsystem.

## 13. Implementation Sequence

Recommended implementation order:

1. **Schema and persistence**
   Add `Session.cognitive_state` and serialization support.

2. **Deterministic reconciler**
   Build strategic state from existing session/task/runtime truth.

3. **Prompt projection**
   Replace ephemeral cognitive injection with cognitive-layer projection.

4. **Diagnostics**
   Persist `last_cognitive_layer` metrics into session context.

5. **Post-turn commit hooks**
   Update decisions, checkpoints, and recent progress after execution outcomes.

6. **Broker hinting**
   Only after v1 is stable, consider passing strategic hints into broker routing/retrieval.

## 14. Test Plan

Minimum test coverage should include:

- cognitive state persistence round-trip in `Session`
- deterministic reconciliation from task registry and tool health
- open-loop extraction from blocked/waiting tasks
- bounded list behavior and deduplication
- prompt projection shape and compactness
- fallback to legacy `build_cognitive_frame()` when cognitive layer fails
- compatibility with prompt-reduction metrics and no-evidence broker mode

## 15. Recommended Scope for Cognitive Layer v1

Recommended v1 scope:

- per-session persistent strategic state
- deterministic reconciliation
- compact prompt projection
- diagnostics and fallback

Defer to later versions:

- LLM-assisted strategic summarization
- cross-session strategic retrieval
- broker query shaping from cognitive state
- autonomous reprioritization policies
- full decision-intent graphing

## 16. Final Recommendation

The cleanest v1 is:

- **not** a memory rewrite
- **not** a broker extension first
- **not** a heavy planner redesign

It should be a **persistent strategic interpretation layer** that:

- reads existing session truth
- writes bounded cognitive state
- emits compact planner-facing focus/background guidance
- preserves the broker-centric architecture already established

In short:

**Broker = what knowledge is relevant**

**Cognitive Layer = what currently matters**

That division matches the current architecture, preserves the prompt gains from Pass 1 to Pass 5, and creates a safe foundation for later strategic autonomy.
