# Session Event Contract Phase B Plan

## Goal

Define the smallest safe technical delta to introduce a live event envelope and
correlation layer without changing cognition, prompts, tool choice, or agentic
policies.

## Scope

In scope:
- WebSocket events;
- session event envelope;
- `event_id`;
- `turn_id`;
- `message_id`;
- `stream_id`;
- `sequence`;
- `target` on `complete`;
- frontend normalizer;
- rule that a bubble must not be created without correlation.

Out of scope:
- cognition;
- prompts;
- `LLMResolver`;
- tool choice;
- agentic policies;
- cognitive refactors;
- full V1/V2 index creation;
- persistent Wegena end-to-end work;
- cards/media/thoughts/playback completion.

## 1. Normalization Priority

Normalize these event families first, in this order:

1. `assistant_chunk`
2. `final_message_chunk`
3. `complete`
4. `message_added`
5. `assistant_stream.started` or the current equivalent
6. `status`
7. `session_updated`

Why this order:
- the chunk path drives visible assistant output;
- `complete` closes the live stream and needs a target;
- `message_added` is the first durable correlation bridge for visible chat rows;
- `assistant_stream.started` establishes the stream identity needed by later chunks;
- `status` and `session_updated` are useful context events, but they should never
  be allowed to create a visible assistant bubble by themselves.

## 2. Field Origin

### `event_id`
- Should be born in the backend for all live events.
- May be generated in the frontend only as a fallback for legacy delivery paths,
  but that fallback should not become the canonical source of truth.
- Should travel over WebSocket.
- Should be persisted whenever an event is recorded durably.

### `turn_id`
- Should originate in the backend when the assistant/user turn is known.
- Can be derived temporarily from legacy session state when missing.
- Should travel over WebSocket.
- Should be persisted once available.
- Frontend fallback is acceptable only for correlation display, not for durable identity.

### `message_id`
- Should originate in the backend for assistant-visible messages and message-added
  reconciliation events.
- Can be derived temporarily from legacy chat records when missing.
- Should travel over WebSocket.
- Should be persisted.
- Frontend fallback is acceptable only to bridge legacy rows, not to invent a new
  visible message.

### `stream_id`
- Should originate in the backend when a live assistant stream starts.
- Can be derived temporarily from the current stream/work context when missing.
- Should travel over WebSocket.
- Should be persisted for live stream tracking.
- Frontend fallback may reuse the active stream context only as a compatibility shim.

### `sequence`
- Should originate in the backend as an ordering field for the live session event stream.
- Can be derived temporarily from existing append order when historical records lack it.
- Should travel over WebSocket.
- Should be persisted where live event ordering is stored.
- Frontend should treat it as ordering metadata, not as identity.

### `target`
- Should originate in the backend for terminal events, especially `complete`.
- Should travel over WebSocket.
- Should be persisted for terminal records.
- Frontend should use it to reconcile the completion target and close the right bubble,
  not to infer new content.

## 3. Legacy Compatibility

The compatibility rule is: preserve old sessions without forcing a rewrite.

- Legacy sessions may not have `turn_id`; the frontend must still render them.
- Legacy events may not have `message_id`; the normalizer should fall back to the
  current row/stream context if it exists.
- Legacy chunks may not have `stream_id`; they should attach to the most recent
  live assistant stream only when that stream is unambiguous.
- The frontend must never create a new assistant bubble purely because a chunk arrived
  without a valid correlation target.
- If correlation is missing or ambiguous, the event may update metadata or diagnostics,
  but it must not produce a visible empty bubble.

Compatibility rules by consumer:
- Chat should prefer the live envelope when present and ignore orphaned content events.
- Nexus should remain tolerant of missing correlation fields and continue rendering
  session/work timelines.
- Legacy transport payloads should still be accepted, but only through the safe fallback
  path, not through a new bubble creation path.
- `session_updated` should continue to refresh session state without replacing live stream
  correlation that is already in progress.

## 4. Likely Files To Touch

### Backend emitters
- `src/core/orchestrator.py`
- `src/core/worker.py`
- `src/core/scheduler.py`
- `src/services/playback_service.py`
- `src/services/wegena_observer.py`
- `src/utils/event_bus.py`

### Session persistence
- `src/core/session.py`
- `src/core/sessions_index.py`
- `src/server/routes/sessions.py`

### WebSocket/server driver
- `src/drivers/interfaces/server_driver.py`
- `src/drivers/interfaces/internal_driver.py`
- `src/drivers/interfaces/telegram/telegram_driver.py`
- `src/server/routes/system.py`

### Frontend normalizer
- `frontend/src/utils/chatHistoryTransform.js`
- `frontend/src/pages/Chat.jsx`

### Chat consumer
- `frontend/src/components/chat/MessageItem.jsx`
- `frontend/src/context/GlobalSessionContext.jsx`

### Nexus consumer
- the Nexus session/event consumer paths that read live session updates and timeline
  events, including the code that consumes `message_added`, chunk events, and session
  refresh payloads

## 5. Smallest Safe Patch

The smallest safe patch should be incremental:

### B1: add envelope fields to emitted events
- Add `event_id`, `turn_id`, `message_id`, `stream_id`, and `sequence` to live events
  at the backend emission layer.
- Keep old fields in place so old clients do not break.

### B2: add `target` on `complete`
- Emit `target` on terminal completion events.
- Use that target to reconcile the stream that is actually closing.

### B3: frontend ignores orphaned events for bubble creation
- Teach the normalizer to refuse bubble creation when a chunk has no valid correlation.
- Allow metadata updates and diagnostics to continue.

### B4: reconcile `message_added` with stream/message identity
- Use `message_added` as the bridge between stream output and persisted message identity.
- Let it reconcile, not duplicate, the assistant bubble.

### B5: add a regression test for the empty-bubble case
- Verify that a chunk without correlation does not create an empty assistant bubble.

## 6. Tests and Validation

Required validations:

- event chunk includes `stream_id`;
- `complete` includes `target`;
- `message_added` reconciles stream and message identity;
- `status` does not create a bubble;
- `session_updated` does not overwrite live stream state;
- Chat does not generate an empty bubble;
- Nexus continues to render without breaking on legacy payloads;
- Telegram continues to accept legacy and partially normalized event payloads.

Recommended test shape:
- one backend emission test per event family that gains envelope fields;
- one frontend normalizer test for orphaned chunk rejection;
- one integration-style regression for the live chat path;
- one compatibility test for legacy sessions without correlation fields.

## Decision Summary

The preferred strategy is to make the backend the canonical source of event
identity, keep the frontend as a tolerant normalizer, and block empty bubble
creation unless a message can be correlated to a live stream or persisted message.
