# Atlas Agent Mode and Cognition Deep Audit

> Technical audit note. This report reflects a point-in-time analysis of the current Atlas agent stack and the changes applied during this review cycle.

Date: 2026-05-29
Repository: `Assistant-OS`
Scope: agent mode orchestration, cognition normalization, situational context, recovery behavior, work status propagation, driver contract stability

## Executive Summary

The main lesson from this audit is simple: Atlas was not primarily failing because the model was "too weak" or because the prompt was "too short". The bigger issue was that the runtime was not consistently carrying enough structured state upward from execution into cognition.

That produced three visible symptoms:

1. repeated clarification loops
2. false success narratives after recovery paths
3. task-state confusion, where "the worker finished" was treated as "the task was actually completed"

The agent-mode stack now has better separation between:

- conversation
- task execution
- approval waiting
- clarification required
- recovery fallback

It also now exposes more situational context to the model without reintroducing decision-making rules that would bias the agent.

## What Atlas Agent Mode Actually Looks Like

Atlas is not a single decision layer. It is a chain of stateful layers:

- session context and intent agenda
- situational context snapshot
- prompt composition
- cognitive outcome normalization
- worker/work status propagation
- UI and task-inspection presentation

The important design point is that the model should not have to infer whether it is in:

- a normal conversational turn
- an execution turn
- a blocked approval turn
- a clarification turn
- a recovery turn

The runtime should carry that information explicitly.

### The Core Continuity Path

The continuity flow now relies on a few explicit signals:

- `last_user_request`
- `last_clarification`
- `pending_action`
- `active_intents`
- `location.source`
- `location.mode`
- `execution_state`
- `status_details`

These are assembled in the orchestrator and passed into the prompt as a compact situational block. See [src/core/orchestrator.py](../../src/core/orchestrator.py#L1886), [src/core/orchestrator.py](../../src/core/orchestrator.py#L6125) and [src/services/llm/prompt_composer.py](../../src/services/llm/prompt_composer.py#L170).

## Cognitive Patterns Observed

### 1. Reply-only vs task execution

The cognitive layer now explicitly distinguishes between a simple reply and a real execution result. That distinction is normalized in [src/services/cognition/outcomes.py](../../src/services/cognition/outcomes.py#L38).

This matters because a session can end successfully from the worker point of view without the user task being completed. Before the recent changes, those two ideas were too easy to conflate.

### 2. Clarification as a terminal-but-not-final state

Atlas often enters clarification when the input is underspecified. That is expected. The bug was not clarification itself, but the fact that clarification could repeat without remembering the last clarification attempt.

The new session memory now stores `last_clarification` and keeps `last_user_request` up to date on every turn. See [src/core/orchestrator.py](../../src/core/orchestrator.py#L1886) and [src/core/orchestrator.py](../../src/core/orchestrator.py#L3761).

### 3. Approval waiting as a first-class pause state

Sensitive or out-of-workspace actions should not look like failure, and they should not look like completion either. They are a blocked state with a pending decision.

That intent is now visible both in the work status summary and in the cognitive outcome model. See [src/core/scheduler.py](../../src/core/scheduler.py#L388) and [src/services/cognition/outcomes.py](../../src/services/cognition/outcomes.py#L88).

### 4. Recovery is not execution

One of the most important fixes in this cycle was separating "I have a recovery reply" from "I have proof that the action really happened".

Recovery paths can now be neutralized when they try to claim progress or completion without evidence from the tool layer. The guard lives in [src/core/orchestrator.py](../../src/core/orchestrator.py#L4724) and checks unverified claims like "created", "saved", or "wrote" in [src/core/orchestrator.py](../../src/core/orchestrator.py#L4928).

### 5. Intent reentry is conservative on purpose

The `IntentAgenda` is not a full planner. It is a lightweight continuity layer that tracks open and paused intents, then reopens them only when the linked tasks truly complete.

That conservative behavior is implemented in [src/core/intents.py](../../src/core/intents.py#L42). It is a good pattern for Atlas because it avoids "phantom reentry" into tasks that were merely superseded or narrated, not actually completed.

## Bugs and Failure Patterns Found

| Finding | User-visible symptom | Root cause | Current status |
|---|---|---|---|
| False success after recovery | The agent says it created, saved, or finished something even when no tool output exists | Recovery prompt was allowed to narrate completion without evidence | Guarded in runtime and recovery logic |
| Clarification loop | The same clarification question repeats across turns | `last_clarification` and `last_user_request` were not preserved with enough continuity | Fixed in session context and situational snapshot |
| Memory amnesia between turns | The assistant forgets the task it was already handling and resets to "How can I help?" | Context continuity was trimmed too aggressively while removing decision bias | Mitigated by restoring compact situational context |
| Location ambiguity | Desktop or fallback flows keep asking for city/region even when a default location exists | Location source was not exposed clearly enough to the agent | Fixed by adding `source` and `mode` to location payloads |
| Status conflation | A work item looked "completed" even when it only reached the end of a worker turn | `succeeded` was overloaded as a completion signal | Fixed with `status_details` and `execution_overview` |
| Driver contract drift | Telegram and other drivers crashed on `model_info` kwargs | Driver signatures diverged from kernel callbacks | Fixed by aligning `send_response` and `send_status` contracts |
| Prompt crash on empty capability summary | `IndexError` during prompt composition when the capability summary was empty | `_extract_discovery_mode()` assumed at least one line existed | Fixed by returning a safe fallback |

### Why these bugs matter

The key theme is not "model hallucination". The key theme is "the system made it too easy to confuse narrative with evidence".

That confusion shows up in three places:

- the prompt
- the cognitive outcome model
- the work/status presentation layer

If any one of those layers is too optimistic, Atlas can appear to have advanced when it has not.

## Architecture Notes by Layer

### 1. Prompt and situational context

The prompt now includes a compact situational context block with:

- user language
- timezone
- initial and last user request
- pending action
- last clarification
- active intents
- location source/mode and resolved fields
- task state snapshot

See [src/core/orchestrator.py](../../src/core/orchestrator.py#L6125) and [src/services/llm/prompt_composer.py](../../src/services/llm/prompt_composer.py#L266).

This is a good compromise: it restores continuity without reintroducing semantic rules that decide actions on behalf of the agent.

### 2. Location fallback

The location service now makes the fallback chain explicit:

- `context`
- `config_default`
- `ip`
- `fallback_unknown`

That is implemented in [src/services/location/location_service.py](../../src/services/location/location_service.py#L87).

This matters because Atlas should behave differently when it has a trusted browser/web context versus when it is using the system default location. The agent should not have to guess which source won.

### 3. Work status propagation

The scheduler now stores structured `status_details` on the work object and emits them with the event payload. The UI and task inspection endpoint can now distinguish:

- `action_executed`
- `task_completed`
- `task_progressed`
- `approval_pending`
- `clarification_required`
- `fallback_used`
- `reply_only`

See [src/core/scheduler.py](../../src/core/scheduler.py#L388), [src/main.py](../../src/main.py#L952) and [src/server/routes/tasks.py](../../src/server/routes/tasks.py#L634).

That removes the old ambiguity where "work ended" was visually treated as "task succeeded".

### 4. Cognition normalization

The normalizer in [src/services/cognition/outcomes.py](../../src/services/cognition/outcomes.py#L38) is now one of the most important parts of the stack.

It turns raw execution evidence into consistent states such as:

- `reply_only`
- `clarification_required`
- `approval_pending`
- `action_executed`
- `action_failed`
- `recovery_path_used`

This layer is what keeps the rest of the system honest. If it collapses too many cases into "success", Atlas will look more certain than it really is.

### 5. Intent continuity

`IntentAgenda` is intentionally lightweight. It does not try to replace the planner or the scheduler. It simply preserves the high-level unresolved objective across turns and only reopens paused intents when linked tasks are actually completed.

That is the right shape for Atlas: persistence without overreach.

## What Changed During This Review Cycle

The most relevant fixes applied during this cycle were:

- restored situational continuity in the prompt path
- tagged location origin and fallback source
- added `last_user_request` and `last_clarification` continuity
- added structured work status details
- exposed execution overview in the task API
- aligned driver signatures around `model_info`
- protected recovery replies from claiming unverified execution
- hardened prompt composition against empty capability summaries

## Residual Risks

There are still a few structural risks to keep in mind:

1. Atlas remains dependent on good evidence plumbing. If a future change strips out `status_details` or situational context, the same class of bug can reappear.
2. The agent is still only as good as the quality of its blocked-state reporting. If approval or clarification is not surfaced cleanly, the model will drift back toward repeated clarification.
3. Any external provider or driver integration must preserve the same response/status contract discipline. Signature drift is a recurring integration risk.

## Conclusion

Atlas does have a real agent mode. It is not just "chat plus tools". But the mode only works well when the runtime carries enough state upward for the model to understand where it is in the task lifecycle.

This audit shows that the biggest issues were not model intelligence problems. They were:

- continuity gaps
- state conflation
- weak source tagging
- optimistic fallback narration
- contract drift between layers

The current changes move Atlas toward a healthier pattern:

- factual context is explicit
- task state is structured
- recovery is more honest
- clarification is remembered
- approval is a first-class pause

That is a much stronger base for the Atlas agent than relying on the model to infer all of it from raw conversation alone.
