# Session Event Contract Phase B Checklist

This checklist breaks Phase B into small execution steps. It is documentation
only and does not change runtime behavior.

## B1 — Event Envelope Baseline

**Objective**
- Establish the minimum live event envelope for backend emission without touching cognition.

**Likely files**
- `src/utils/event_bus.py`
- `src/core/orchestrator.py`
- `src/core/worker.py`
- `src/core/scheduler.py`
- `src/services/playback_service.py`
- `src/services/wegena_observer.py`
- `src/drivers/interfaces/server_driver.py`
- `src/drivers/interfaces/internal_driver.py`

**Preconditions**
- Current live event emitters are identified.
- The existing WebSocket payload shapes are cataloged.
- No cognition or prompt changes are in scope.

**Expected validation**
- `event_id` is present on emitted live events.
- `session_id` remains present on emitted live events.
- `timestamp` remains present on emitted live events.
- Legacy payload fields are still accepted by consumers.

**Risk**
- Adding envelope fields in the wrong layer can fragment event identity across emitters.

**Rollback criterion**
- Revert the envelope changes if any consumer starts rejecting legacy payloads or live updates stop appearing.

**Suggested test command**
- `pytest tests/minimal -k "event or websocket or session"`

## B2 — Turn/Message/Stream Correlation

**Objective**
- Propagate identity fields that connect live chunks, messages, and turns.

**Likely files**
- `src/core/orchestrator.py`
- `src/core/worker.py`
- `src/core/session.py`
- `src/server/routes/sessions.py`
- `src/drivers/interfaces/server_driver.py`
- `frontend/src/utils/chatHistoryTransform.js`
- `frontend/src/pages/Chat.jsx`

**Preconditions**
- Event envelope baseline is in place.
- There is a clear rule for when `turn_id`, `message_id`, and `stream_id` are born.
- Legacy sessions without these fields still render.

**Expected validation**
- `turn_id` is introduced or propagated where a turn is known.
- `message_id` is introduced or propagated where a visible message exists.
- `stream_id` is introduced or propagated for live assistant streams.
- `sequence` is present on chunks that need ordering.
- Legacy records continue to render without hard failure.

**Risk**
- Over-eager correlation can duplicate visible messages or misattach chunks to the wrong turn.

**Rollback criterion**
- Revert correlation propagation if Chat or Nexus starts duplicating bubbles or mis-ordering chunks.

**Suggested test command**
- `pytest tests/minimal -k "chat or session or websocket"`

## B3 — Complete Target

**Objective**
- Make terminal completion explicit so the frontend knows what is being closed.

**Likely files**
- `src/core/orchestrator.py`
- `src/core/worker.py`
- `src/drivers/interfaces/server_driver.py`
- `frontend/src/pages/Chat.jsx`
- `frontend/src/components/chat/MessageItem.jsx`

**Preconditions**
- The live event envelope exists.
- Terminal events can carry a target without changing cognition.

**Expected validation**
- `complete` includes `target`.
- `target=stream` requires `stream_id`.
- `target=message` requires `message_id`.
- `target=work` requires `work_id`.
- The frontend does not finalize a visible bubble without a target.

**Risk**
- A missing or mismatched target can close the wrong UI element or leave a stream dangling.

**Rollback criterion**
- Revert the target field if completion events start causing incorrect UI finalization.

**Suggested test command**
- `pytest tests/minimal -k "complete or stream or message"`

## B4 — Frontend Event Normalizer

**Objective**
- Centralize event normalization so technical payloads cannot create visible bubbles by accident.

**Likely files**
- `frontend/src/utils/chatHistoryTransform.js`
- `frontend/src/pages/Chat.jsx`
- `frontend/src/components/chat/MessageItem.jsx`
- `frontend/src/context/GlobalSessionContext.jsx`

**Preconditions**
- The frontend understands the live envelope fields.
- The UI has a single normalization path for live and persisted events.

**Expected validation**
- A single normalizer handles incoming events.
- Technical events do not create bubbles.
- Visual events do not create bubbles unless correlation is valid.
- Chunks without correlation do not create messages.
- Placeholders require `turn_id` plus either `message_id` or `stream_id`.

**Risk**
- If the normalizer is too permissive, the UI can regress to empty or duplicate assistant bubbles.

**Rollback criterion**
- Revert normalizer tightening if legacy sessions stop rendering or event intake becomes lossy.

**Suggested test command**
- `pytest tests/minimal -k "chat or frontend or transform"`

## B5 — Reconciliation and Validation

**Objective**
- Reconcile optimistic UI with durable identity and prove that live updates remain stable.

**Likely files**
- `frontend/src/pages/Chat.jsx`
- `frontend/src/utils/chatHistoryTransform.js`
- `src/server/routes/sessions.py`
- `src/core/session.py`
- `src/core/sessions_index.py`

**Preconditions**
- B1 through B4 are in place or at least designed together.
- The optimistic message flow and durable message flow are both understood.

**Expected validation**
- Optimistic user messages reconcile by `message_id` or `turn_id`.
- `message_added` reconciles instead of duplicating.
- Late chunks do not create a new bubble.
- `session_updated` does not overwrite the live stream.
- The skeleton or empty-bubble case is used as the regression guard.

**Risk**
- Reconciliation bugs are easy to miss because the UI may appear correct until a late event lands.

**Rollback criterion**
- Revert reconciliation logic if late events create duplicate visible messages or wipe active live state.

**Suggested test command**
- `pytest tests/minimal -k "reconcile or session_updated or bubble"`
