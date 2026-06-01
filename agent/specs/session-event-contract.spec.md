# Session Event Contract
State mirror: [session-event-contract.stat.md](session-event-contract.stat.md).

## Purpose

This spec defines the canonical contract for sessions, turns, messages, streams, works, events, and visual persistence.

It keeps chat surfaces, consoles, Nexus-style views, Telegram, WebSocket streams, workers, cards, media, and Wegena-related visuals aligned on the same event model.

## Scope

In scope:

- session and turn identity;
- message correlation and reply linkage;
- stream lifecycle and chunk ordering;
- work/task/worker correlation;
- event envelopes and persistence;
- placeholder and skeleton reconciliation;
- UI consumption rules for chat-like surfaces;
- visual, artifact, and media association rules.

Out of scope:

- cognition;
- prompt composition;
- LLM resolver behavior;
- tool choice;
- policy decisions for the agent mind;
- provider fallback;
- browser or schema heuristics;
- mental reasoning traces.

## Canonical Unit

The canonical unit of interaction is the `turn`.

A turn usually starts from a user message, but it may also start from an asynchronous or spontaneous assistant action.

Core identifiers:

- `session_id`: durable session identity;
- `turn_id`: interaction cycle identity;
- `message_id`: identity of a specific message;
- `reply_to_message_id`: message that originated the reply;
- `stream_id`: incremental chunk stream identity;
- `work_id`: execution, task, tool, or worker identity;
- `event_id`: identity of a single event record;
- `channel`: transport origin such as `web`, `telegram`, `internal`, or `cli`;
- `interface`: surface such as `chat`, `console`, `nexus`, or `telegram`;
- `source`: producer such as `user`, `assistant`, `worker`, `system`, or `wegena`;
- `sequence`: ordering within a turn or stream;
- `timestamp`: normalized time value.

The assistant response must never reuse the user message `message_id`.

If a response is incremental, it must keep the same `turn_id` and use a distinct `message_id` and `stream_id`.

## Canonical Event Envelope

All events should use a shared envelope shape.

```json
{
  "event_id": "evt-...",
  "event_type": "assistant_chunk",
  "session_id": "session-...",
  "turn_id": "turn-...",
  "message_id": "msg-...",
  "reply_to_message_id": "msg-user-...",
  "stream_id": "stream-...",
  "work_id": "work-...",
  "channel": "web",
  "interface": "chat",
  "source": "assistant",
  "sequence": 12,
  "timestamp": "2026-05-31T12:34:56Z",
  "payload": {}
}
```

Not every field is required for every event type, but each event type must define its own required fields explicitly.

## Conceptual Separation

### Message

A message is the canonical visible or persisted conversation unit.

It may represent:

- user input;
- assistant output;
- visible system text;
- spontaneous assistant output;
- the final consolidated text for a response.

### Stream

A stream is the incremental flow that fills a message.

A stream must point to:

- `session_id`;
- `turn_id`;
- `message_id`;
- `stream_id`;
- `sequence`.

### Work

A work is an operational execution unit: tool call, task, worker, or background job.

A work may emit:

- status updates;
- observations;
- artifacts;
- cards;
- media;
- logs;
- final results.

### Event

An event is a single persisted record of something that happened.

Event persistence should be append-only whenever possible.

### Card / Artifact / Media / Visual

These are not messages by default.

They may attach to a message or turn, but they should not automatically become a text bubble.

## Event Types

### `user_message.created`

Creates a user message and starts a turn.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `turn_id`;
- `message_id`;
- `channel`;
- `interface`;
- `source=user`;
- `timestamp`;
- `payload.content`.

May create a visible bubble: yes.

### `assistant_stream.started`

Starts an incremental assistant response.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `turn_id`;
- `message_id`;
- `stream_id`;
- `source=assistant`;
- `timestamp`.

Recommended:

- `reply_to_message_id`.

May create a placeholder bubble: yes, if correlation is complete.

### `assistant_message.created`

Creates a direct assistant message without an incremental stream.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `turn_id`;
- `message_id`;
- `source=assistant`;
- `timestamp`;
- `payload.content`.

Recommended:

- `reply_to_message_id`.

May create a visible bubble: yes.

### `assistant_chunk`

## Relacionados

- [session-event-contract.stat.md](session-event-contract.stat.md)
- [../policy/session-event-contract.policy.md](../policy/session-event-contract.policy.md)
- [system_sessions.spec.md](system_sessions.spec.md)
- [system_sessions.stat.md](system_sessions.stat.md)
- [../README.md](../overview.md)
- [../../docs/contracts/README.md](../../docs/contracts/README.md)

Updates an existing stream.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `turn_id`;
- `message_id`;
- `stream_id`;
- `sequence`;
- `source=assistant`;
- `payload.content`.

May create a bubble: no, unless a controlled fallback is needed because the start event was lost.

May update an existing placeholder or bubble: yes.

### `final_message_chunk`

Finalizes the textual content of a stream or message.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `turn_id`;
- `message_id`;
- `sequence`;
- `payload.content`.

If the content belongs to a stream, `stream_id` is required.

May create a bubble: no, if the `message_id` already exists.

### `message.persisted` / `message_added`

Confirms that the canonical message was persisted.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `turn_id`;
- `message_id`;
- `source`;
- `timestamp`;
- content or a reference to content in `chat.json`.

May create a bubble: yes, if the message does not already exist.

### `complete`

Finalizes an explicit target.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `target`;
- `timestamp`.

Target-specific requirements:

- `target=stream` requires `stream_id`, `turn_id`, `message_id`;
- `target=message` requires `message_id`, `turn_id`;
- `target=work` requires `work_id`;
- `target=session` requires `session_id`.

May create a bubble: no.

May close a placeholder or skeleton: only when the target is explicit and correlated.

### `worker.updated`

Updates a work, task, or tool execution.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `work_id`;
- `status`;
- `timestamp`.

Recommended:

- `turn_id`;
- `message_id`;
- `payload`.

May create a bubble: no.

### `status`

Technical status event.

Required:

- `event_id`;
- `event_type`;
- `session_id`, when session-related;
- `timestamp`;
- `payload.status`.

May create a bubble: no.

### `session_updated`

Updates session metadata.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `timestamp`;
- `payload`.

May create a bubble: no.

### `visual.wegena.*`

Visual events related to Wegena.

Examples:

- `visual.wegena.scene_reset`;
- `visual.wegena.scene_update`;
- `visual.wegena.composition_ready`;
- `visual.wegena.scene_failed`.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `timestamp`;
- `source=wegena`.

Optional:

- `turn_id`;
- `trigger_event_id`;
- `payload.scene`;
- `payload.composition`.

May create a bubble: no.

May modify message, stream, or work state: never.

### `card.created` / `artifact.updated` / `media.added`

Structured data events.

Required:

- `event_id`;
- `event_type`;
- `session_id`;
- `timestamp`;
- `payload`.

Recommended:

- `turn_id`;
- `message_id`;
- `work_id`;
- `source`.

May create a bubble: no by default.

May materialize a card, artifact, media item, or technical panel.

## Rendering Rules

Events that may create a visible message:

- `user_message.created`;
- `message.persisted`;
- `message_added`;
- `assistant_stream.started`, only as a correlated placeholder;
- `assistant_message.created`.

Events that may update a visible message:

- `assistant_chunk`;
- `final_message_chunk`;
- `message.persisted`;
- any event linked by `message_id` or `stream_id`.

Events that may finalize a visible target:

- `complete`, only when the target is explicit and correlated.

Events that should never create a bubble:

- `status`;
- `session_updated`;
- `worker.updated`;
- `visual.wegena.*`;
- `card.created`;
- `artifact.updated`;
- `media.added`;
- any event without enough correlation data.

## Skeleton and Placeholder Rules

Every placeholder must have a target:

- `turn_id`;
- `message_id`;
- `stream_id`.

A skeleton with no final content must:

- be filled by chunks;
- be replaced by a persisted message;
- expire as technical state;
- or be removed with a clear reason.

## Persistence and Consumption Rules

- session persistence must remain recoverable from the event log and canonical message records;
- the frontend must not infer durable state from raw `chat.json` alone when more precise event data exists;
- channel and interface differences must preserve the same correlation semantics;
- cards, media, and visual artifacts should be recoverable without becoming accidental text bubbles;
- stream completion must reconcile with the existing message rather than creating a second final bubble.

## Related Specs

- `agent/specs/system_sessions.spec.md`;
- `agent/specs/agent_events.spec.md`;
- `agent/specs/worker_task_contract.spec.md`;
- `agent/specs/plugin_ui_architecture.spec.md`;
- `agent/specs/atlas_operating_model.spec.md`.
