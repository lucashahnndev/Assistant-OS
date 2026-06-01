# Session Event Contract Policy

Contract reference: [../specs/session-event-contract.spec.md](../specs/session-event-contract.spec.md) and [../specs/session-event-contract.stat.md](../specs/session-event-contract.stat.md).

- use `session_id`, `turn_id`, `message_id`, `stream_id`, `work_id`, and `event_id` as the canonical correlation keys;
- do not infer durable UI state from raw `chat.json` when event correlation is available;
- do not create a new visible bubble when the existing `message_id` already identifies the target;
- only finalize a stream, message, work, or session when the target is explicit;
- keep placeholders and skeletons correlated to a turn, a message, and a stream;
- treat cards, artifacts, media, and Wegena visuals as structured outputs, not automatic chat bubbles;
- preserve the same correlation semantics across web, console, Nexus, Telegram, and internal transports;
- prefer reconciliation over duplication when a stream finishes or a persisted message arrives late;
- if the event cannot be correlated, keep it technical instead of inventing a visible message.

## Relacionados

- [README.md](README.md)
- [../specs/README.md](../specs/overview.md)
- [../specs/session-event-contract.spec.md](../specs/session-event-contract.spec.md)
- [../specs/session-event-contract.stat.md](../specs/session-event-contract.stat.md)
- [../specs/system_sessions.spec.md](../specs/system_sessions.spec.md)
