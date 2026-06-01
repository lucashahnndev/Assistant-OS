# Session Event Contract Runtime Audit

Data: 2026-05-31

## Scope

Audit of the current A.T.L.A.S runtime against the `Session Event Contract` umbrella domain.

In scope:

- session persistence;
- `chat.json`, `session.json`, `thoughts.json`, `cards.json`;
- current WebSocket and event bus signals;
- chat/console/Nexus/Telegram flows;
- workers, cards, media, playback, Wegena, and indexes.

Out of scope:

- cognition;
- prompt composition;
- `LLMResolver`;
- tool choice;
- agentic policies;
- mental reasoning behavior.

## Executive Summary

The runtime is already close to the new contract in one important way: it has a durable per-session folder model, a session index, a work directory model with `context.json` and `events.jsonl`, and separate persistence for thoughts/cards/playback.

The main gaps are structural:

- the live event envelope is still mostly `type/session_id/work_id` instead of `event_id/session_id/turn_id/message_id/stream_id/work_id`;
- `chat.json` and `session.json` are still both relied on, but they mean different things and are not fully normalized;
- the frontend still reconstructs state from optimistic messages plus raw history, which makes empty balloons and reconciliation drift possible;
- Wegena and visual artifacts are partly persisted, but not yet namespaced or indexed as first-class event outputs.

## 1. Session Persistence Today

### What exists

- `data/sessions/<session_id>/session.json` stores the mutable session snapshot.
- `data/sessions/<session_id>/chat.json` stores the append-only visible history timeline.
- Some sessions also have `thoughts.json` and `cards.json`.
- `data/sessions/index.json` indexes session metadata for listing/filtering.
- Playback is stored under `data/sessions/<session_id>/playback/<run_id>/manifest.json` plus `frames/`.

### What `session.json` contains

`Session.to_dict()` serializes a broad mutable snapshot, including:

- identity fields: `session_id`, `source`, `session_type`, `domain`;
- presentation fields: `name`, `profile_picture`;
- timing fields: `created_at`, `last_interaction`, `last_opened_at`;
- live conversation state: `history`, `context`, `summary`, `scratchpad`, `plan`;
- task and event state: `task_registry`, `event_history`, `event_timeline`, `turn_id`;
- memory and decision state: `memory`, `candidate_store`, `decision_traces`, `rejected_memory`, `audit_trail`;
- tool/runtime state: `tool_health`, `tool_failure_counts`, `cognitive_state`, `last_cognitive_projection`, `cognitive_diagnostics`, `last_cognitive_frame_snapshot`;
- UI/continuity state: `pending_action`, `drivers_state`, `active_focus_task_id`, `active_focus_group`, `intent_agenda`, `media_cards`.

Source:
- [src/core/session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py)
- [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py)

### What `chat.json` contains

`chat.json` is an append-only visible timeline of message records, each with fields like:

- `id`
- `role`
- `content`
- `tokens`
- `type`
- `timestamp`
- `is_read`
- `model_info`
- optional `work_id`
- optional `actor`
- optional `attachments`

Observed in real data:

- user messages are stored as normal chat records;
- assistant replies are stored with `work_id` when available;
- reasoning entries are stored with `role=system` and `type=reasoning`;
- internal notifications can appear as `role=notification` / `type=internal_event`;
- there is no canonical `turn_id`, `message_id`, `reply_to_message_id`, or `stream_id` in the visible timeline today.

Sources:
- [data/sessions/system.boot.bak/chat.json](/home/lucas/Documentos/GitHub/Assistant-OS/data/sessions/system.boot.bak/chat.json)
- [data/sessions/system.calendar/chat.json](/home/lucas/Documentos/GitHub/Assistant-OS/data/sessions/system.calendar/chat.json)

### What is persisted vs derived

Persisted:

- session metadata;
- visible chat history;
- thought trail;
- cards;
- playback manifests and frames;
- work artifacts under `data/works/<work_id>/`.

Derived:

- session list order and unread counts from `index.json`;
- UI groupings of reasoning and work segments;
- playback summaries from manifest files;
- many cognition and broker views from live session context.

Lost or fragile on refresh:

- live streaming state;
- optimistic placeholders;
- correlation between a stream chunk and the message it belongs to when the frontend misses an event;
- reasoned structure when only raw `chat.json` is available;
- Wegena scene state unless it survives in `data/workspace/wegena` or the session payload.

### What needs to become an index

The runtime already has partial persistence for these concepts, but they are not indexed as first-class session primitives:

- turns;
- messages;
- streams;
- workers;
- cards;
- media;
- playback runs;
- Wegena scene runs;
- thought records.

## 2. Current WebSocket Events

### Real event types in use

The runtime emits or routes these event types today:

- `status`
- `message_added`
- `assistant_chunk`
- `final_message_chunk`
- `complete`
- `session_updated`
- `reasoning_chunk`
- `assistant_thought`
- `thought`
- `cognitive_thought`
- `worker_state`
- `work_progress`
- `work_status_change`
- `playback_stream`
- `playback.frame`
- `playback.end`
- `weg_scene_reset`
- `weg_scene`
- voice protocol events like `voice.state`, `asr.final`, `tts.start`, `tts.end`

### Contract table

| event_type | emitter | current payload | missing vs contract | frontend consumer | bubble behavior | risk |
|---|---|---|---|---|---|---|
| `status` | `src/core/orchestrator.py` via `global_event_bus`; `src/drivers/interfaces/server_driver.py`; `src/drivers/interfaces/telegram/telegram_driver.py`; `src/main.py` | `phase`, `message`, `payload`, `model_info`, `timestamp`, sometimes `work_id` | usually lacks `event_id`, `turn_id`, `message_id`, `stream_id`, `reply_to_message_id`, `source`, `interface`, `sequence` | `Chat.jsx`, `MessageItem.jsx`, `GlobalSessionContext` | can create/update a visible skeleton | partially conformant, but technically weak |
| `message_added` | `Session.add_message()` in `src/core/session.py`; broadcast by `server_driver` and session routes | `session_id`, `role`, `message`, `msg_type`, `work_id`, `unread_count`, plus embedded message object | lacks canonical `turn_id`, `message_id` correlation envelope; `reply_to_message_id` absent | `Chat.jsx`, `WegenaSceneObserver`, `ServerDriver`, session refresh | can create a bubble | legacy, partially conformant |
| `assistant_chunk` | `ServerDriver.send_response()` via event bus; `WegenaSceneObserver` consumes it | `session_id`, `content`, `model_info`, `attachments` | lacks `stream_id`, `turn_id`, `message_id`, `sequence` | `Chat.jsx`, `WegenaSceneObserver` | updates skeleton / streaming message | divergent because it is chunk content without stream identity |
| `final_message_chunk` | `ServerDriver.send_response()` | WebSocket payload has `type`, `content`, `timestamp`, `attachments` | lacks explicit `target`, `stream_id`, `turn_id`, `message_id` | `Chat.jsx` | may finalize a balloon | legacy, risky if stream identity is lost |
| `complete` | `ServerDriver.send_complete()`, `TelegramDriver.send_complete()`, `VoiceDriver.send_complete()`, many paths in `src/main.py` | only `type`, `timestamp` in server WS; no target fields | missing `target`, `session_id` context in payload, `turn_id`, `message_id`, `stream_id` | `Chat.jsx`, `TelegramDriver`, `GlobalSessionContext` | finalizes/clears UI state, sometimes without content | divergent and potentially dangerous |
| `session_updated` | `src/server/routes/sessions.py` | `session_id`, changed field(s) like `name`, `profile_picture` | lacks event envelope detail and sequence; no turn/message linkage | sidebar/session list via WS bridge | should not create a bubble | mostly conformant as technical event |
| `worker_state` | `GlobalSessionContext` internal handling; scheduler emits into WS elsewhere | worker snapshot data | not a session/event envelope; mostly work-centric | `GlobalSessionContext`, `Chat.jsx` | no bubble intended | legacy, but useful |
| `work_progress` | `src/main.py::_event_consumer_loop` | `message` and routing metadata | lacks canonical stream/work envelope fields in UI-facing payload | `Chat.jsx`, `InternalDriver`, `ServerDriver`, `TelegramDriver` | can create reasoning/status UI | partially conformant |
| `work_status_change` | `src/main.py::_event_consumer_loop` | `status`, `status_details`, `approval_request`, `work_id` | lacks `event_id`, `turn_id`, `message_id`, `stream_id`; `target` missing for `complete` | `Chat.jsx`, `InlineApprovalBar`, `WorkUnitInspector` | may create status bubble, approval bar, or final response | partially conformant, but overloaded |
| `reasoning_chunk` | `ServerDriver.send_reasoning_chunk()`, `Main` callbacks | `content`, `timestamp` | no `stream_id`, `turn_id`, `message_id`, `sequence` | `Chat.jsx`, `MessageItem.jsx` | updates thought panel | divergent relative to new contract |
| `assistant_thought` | `ServerDriver.send_thought()` | `content`, `timestamp` | no canonical envelope | `Chat.jsx` | no bubble intended, but can appear as reasoning | legacy |
| `thought` / `cognitive_thought` | `Session.add_thought()` and related routes | `thought`, `message_id`, `work_id`, `timestamp` | no `turn_id`, no `stream_id`, no event envelope normalization | `Chat.jsx`, `/sessions/{id}/thoughts` | can appear in cognitive panel | partially conformant |
| `weg_scene_reset` | `WegenaSceneObserver` | `session_id`, `reason` | no `source=wegena` envelope, no event id | `ServerDriver` WS bridge, `Chat.jsx` if consumed | should not create bubble | legacy/typo-like naming |
| `weg_scene` | `WegenaSceneObserver` | `session_id`, `script`, `meta.media_path` | should be `visual.wegena.*`; lacks envelope | `ServerDriver` WS bridge | visual artifact only | divergent naming and namespace |
| `playback_stream` | `Chat.jsx` consumer, emitted by playback-related paths | `data` | no canonical envelope | `Chat.jsx` | no direct bubble | legacy UI stream |
| `playback.frame` / `playback.end` | browser control / playback flow | run metadata | not session-message events | `WorkUnitInspector`, playback card | no bubble | acceptable as technical playback |
| `voice.state`, `asr.final`, `tts.start`, `tts.end` | voice manager / server driver | voice protocol payloads | separate transport protocol, not session contract | voice UI / websocket consumers | usually no bubble | transport-specific, not contract-aligned yet |

Sources:
- [src/core/session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py)
- [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py)
- [src/main.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/main.py)
- [src/drivers/interfaces/server_driver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/interfaces/server_driver.py)
- [src/drivers/interfaces/telegram/telegram_driver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/interfaces/telegram/telegram_driver.py)
- [src/drivers/interfaces/internal_driver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/interfaces/internal_driver.py)
- [src/services/wegena_observer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/wegena_observer.py)

## 3. Contract Comparison

### Verdict labels

- conforme: already matches the new contract shape or intent;
- parcialmente conforme: usable, but missing correlation/envelope fields;
- divergente: payload or semantics break the target contract;
- legado: older contract shape that still functions, but should be replaced gradually;
- perigoso: can create incorrect bubbles or finalization.

### Summary by event

- `status`: parcialmente conforme, perigoso when it creates a skeleton without explicit target.
- `message_added`: parcialmente conforme, legacy, can be okay for visible messages but lacks turn/stream correlation.
- `assistant_chunk`: divergente because it carries chunk text without explicit `stream_id`/`message_id`.
- `final_message_chunk`: divergente or legado depending on transport; the server-side payload is too thin.
- `complete`: divergente because it has no `target`.
- `session_updated`: conforme for technical session metadata.
- `work_progress`: parcialmente conforme.
- `work_status_change`: parcialmente conforme, but overloaded.
- `reasoning_chunk` / `assistant_thought` / `thought` / `cognitive_thought`: parcialmente conforme to legacy reasoning UI, divergent to the new session-event contract.
- `weg_scene_reset` / `weg_scene`: divergente and legacy because of naming and envelope mismatch.

## 4. Console / Chat Flow

### Current live flow

1. `Chat.jsx` fetches session detail via `GET /api/sessions/{session_id}`.
2. It also marks the session read/open and updates the active session in `GlobalSessionContext`.
3. On send, it appends an optimistic user message with `isSending: true`.
4. It sends the payload over WebSocket when online, otherwise via `POST /sessions/{id}/message`.
5. `handleWebSocketMessage` reacts to `status`, `thought`, `assistant_chunk`, `message_added`, and `complete`.

## Relacionados

- [../architecture/README.md](../architecture/README.md): contexto arquitetural do dominio `Session Event Contract`.
- [session_event_contract_phase_b_plan.md](session_event_contract_phase_b_plan.md): desdobramento da fase B.
- [session_event_contract_phase_b_checklist.md](session_event_contract_phase_b_checklist.md): execucao passo a passo da fase B.
- [../../agent/specs/session-event-contract.spec.md](../../agent/specs/session-event-contract.spec.md): contrato normativo que fundamenta a auditoria.
- [../../agent/specs/session-event-contract.stat.md](../../agent/specs/session-event-contract.stat.md): estado vivo correspondente ao contrato.
6. `MessageList` merges `messages` with `streamingMessage`.
7. `MessageItem` renders reasoning, playback, attachments, and a skeleton state when a non-user message is actively streaming without content.

### Who creates what

- Skeleton creation: `Chat.jsx` creates `streamingMessage` as soon as a send begins.
- Skeleton fill: `assistant_chunk` / `final_message_chunk` append content into `streamingMessage`.
- Bubble creation: `message_added` and `complete` both can add a final assistant message.
- Finalization: `complete` clears `streamingMessage` and may add a final message if content exists.

### Where the user message can disappear

- `fetchSessionDetail()` replaces message state with `data.history` and only re-adds optimistic messages that do not match by role and timestamp window.
- If the backend message arrives with a timestamp or role mismatch, the optimistic user bubble can be lost or duplicated.

### Where an empty balloon can be born

- `Chat.jsx` initializes `streamingMessage` before any content exists.
- `MessageItem` defines a skeleton when `isStreaming` and `!msg.content && !hasReasoning && !msg.playback`.
- `complete` can mark a message complete even when no final content is available, leaving an empty shell if the payload is weak.

### Where live state can be overwritten

- `fetchSessionDetail()` runs on selection and after some WS events, and it rebuilds `messages` from server history.
- `session_updated` / periodic refetch can rebase `currentSession` and partial message state.
- `fetchSessions()` is also called after message and complete events, which can cause sidebar state to lag the live stream.

Sources:
- [frontend/src/pages/Chat.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Chat.jsx)
- [frontend/src/components/chat/MessageItem.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/components/chat/MessageItem.jsx)
- [frontend/src/context/GlobalSessionContext.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/context/GlobalSessionContext.jsx)
- [frontend/src/utils/chatHistoryTransform.js](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/utils/chatHistoryTransform.js)

## 5. Nexus Comparison

The Nexus surface is not fully separated in the audited code paths, but the current UI architecture treats it as another session surface in the same family.

Compared to Chat/Console:

- it still consumes the same session list and WebSocket transport shape;
- it does not have a distinct canonical turn/message envelope;
- it appears to rely on the same work and message reconstruction logic;
- it can receive cards, workers, and Wegena visuals through the same technical payloads;
- it does not appear to enforce a different data contract from Chat.

Practical conclusion:

- Nexus is not yet a separate contract domain; it is another consumer of the same session/event data.

## 6. Channel / Interface / Source Mapping

### Current differentiation

- `session_id`: used as the primary transport and identity key.
- `session_type`: distinguishes `user` vs `system`.
- `source`: stored in `Session`, usually `web`, `telegram`, or `system`.
- `interface`: derived from `source` in multiple places and is sometimes treated as the same thing.
- `driver`: inferred by connection and route, not always explicit in payloads.
- `external_ref`: present only in some integrations or inferred from Telegram/chat metadata.

### Findings

- Telegram can be identified, but mostly through session prefixes and driver-specific handling, not by a full canonical interface envelope.
- Nexus does not have a visible first-class identity in the core session index yet.
- The web UI can still pick the wrong active session if list ordering or interface filtering is weak.
- Welcome/boot sessions can be hidden operationally, but the general index still lists sessions by interface/type heuristics.
- There are enough fields to list sessions, but not enough to express a canonical session/event hierarchy across transports.

Sources:
- [src/core/session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py)
- [src/core/sessions_index.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/sessions_index.py)
- [src/drivers/interfaces/server_driver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/interfaces/server_driver.py)
- [src/drivers/interfaces/telegram/telegram_driver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/interfaces/telegram/telegram_driver.py)
- [src/server/routes/sessions.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/sessions.py)

## 7. Wegena

### Current behavior

- `WegenaSceneObserver` watches `assistant_chunk` and `message_added`.
- It resets scene state on new user turns and emits `weg_scene_reset`.
- It accumulates assistant content and, after final assistant content, may generate a `.weg` script.
- The final script is written to `data/workspace/wegena/scene_<id>.weg`.
- It emits `weg_scene` with `script` and `meta.media_path`.

### What is persisted

- final `.weg` script file on disk;
- generated media path in event metadata;
- no dedicated session-level Wegena index exists in the audited code.

### What is lost on refresh

- current scene buffer;
- whether the observer already started a final generation pass;
- the relation between the last user turn and a visual scene unless it survives in the `.weg` file or event bus history.

### Assessment

- Wegena is currently fail-soft in the sense that the observer catches errors and does not crash the whole loop.
- The event naming is not yet aligned to `visual.wegena.*`.
- A dedicated `wegena.index.json` would help if scenes must be recoverable and discoverable without re-synthesizing them.

### Recommendation

- namespace visual events as `visual.wegena.*`;
- persist a small indexed record for scene runs if visual recovery matters.

Sources:
- [src/services/wegena_observer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/wegena_observer.py)
- [src/drivers/interfaces/server_driver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/interfaces/server_driver.py)

## 8. Indexes Needed

### V1 fundamental

| index | exists today | derivable today | should be created | consumers | risk if missing |
|---|---|---|---|---|---|
| `session.json` | yes | no | keep | orchestrator, API, UI | low |
| `chat.json` | yes | partly | keep | UI history, restore, audits | medium because it is overloaded |
| `events.jsonl` | yes, but per work not per session | yes for work streams | session-level version likely needed | work console, audit, replay | high for session/event contract |
| `turns.index.json` | no | partly from `chat.json` | yes | UI, replay, correlation | high |
| `messages.index.json` | no | partly from `chat.json` and `session.json` | yes | UI, reconciliation, search | high |
| `streams.index.json` | no | partly from WS flow | yes | live UI, replay | high |
| `workers.index.json` | no session-level index | partly from scheduler/work registry | yes | task panels, list views | medium-high |

### V1.5 / V2

| index | exists today | derivable today | should be created | consumers | risk if missing |
|---|---|---|---|---|---|
| `thoughts.index.json` | no | yes from `thoughts.json` | maybe V1.5 | cognitive panel | medium |
| `media.index.json` | no | partly from session files | yes if media needs search/recovery | chat attachments, gallery | medium |
| `links.index.json` | no | partly from `chat.json` and session media payloads | maybe V1.5 | profile links, previews | medium |
| `cards.index.json` | no | yes from `cards.json` | yes | assistive cards, recovery | medium-high |
| `playback.index.json` | no | yes from playback manifests | yes | playback panel, audits | medium-high |
| `wegena.index.json` | no | partly from `.weg` files and event bus metadata | maybe V2 | visual recovery, catalog | medium-high |

### Work indexes

The runtime already has per-work persistence:

- `data/works/<work_id>/work.json`
- `data/works/<work_id>/context.json`
- `data/works/<work_id>/events.jsonl`

This is strong groundwork for work-level indexing, but it is not yet bridged to the session-event contract with canonical turn/message correlation.

Sources:
- [src/core/scheduler.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/scheduler.py)
- [src/core/worker.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/worker.py)
- [src/services/playback_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/playback_service.py)

## 9. Minimum V1 Delta

The smallest useful set of changes to move toward the contract is:

1. Add canonical `event_id` and `turn_id` to all live session events.
2. Add `message_id` to all visible message events and make `reply_to_message_id` explicit for assistant replies.
3. Add `stream_id` to chunked responses and keep one `stream_id` per assistant stream.
4. Require `target` for `complete` and use it consistently for `stream`, `message`, `work`, and `session`.
5. Add a minimal session-level `events.jsonl` or equivalent append-only event log.
6. Add a `messages.index.json` and `turns.index.json` to stop reconstructing everything from raw `chat.json`.
7. Add a `streams.index.json` for live reconciliation.
8. Make the frontend ignore technical events that should never create a visible balloon.
9. Namespace Wegena visual events as `visual.wegena.*`.

### Frontend normalizer priorities

- prefer `message_id` over timestamp matching;
- merge optimistic user messages by explicit ID if possible;
- reconcile `assistant_chunk` into an existing stream instead of appending a new assistant bubble;
- let `complete` finalize an existing target, not invent a new one;
- ignore `status`, `session_updated`, worker telemetry, and visual-only events as message creators.

## Closing Assessment

The runtime is not far from the new contract in terms of storage surfaces, but it is still too loose in live event identity.

The key gap is not data volume. It is correlation.

If the system keeps using raw `type/session_id/work_id` events for everything, the UI will continue to depend on heuristics and timing windows. The new contract solves that by making turn, message, stream, work, and event identity explicit.
