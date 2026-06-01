# Agent Events Spec

Note: for the broader session/message/turn/stream/work/event correlation model, see `agent/specs/session-event-contract.spec.md`. This document remains the narrower internal-agent-event contract.

## Overview
`AgentEvent` is the formal contract for internal system signals that require agent attention. It allows capabilities and background services to wake up a system session, such as `system.attention`, with structured context and human-readable summaries.

## Flow
1. Capability or service generates an `AgentEvent`.
2. `InternalDriver` receives the event, transforms it into an agent-readable input, and attaches the structured payload to the metadata.
3. `Kernel` processes the input as internal (`is_internal=True`) and suppresses user-facing notifications.
4. Agent orchestrator routes the event to the correct system session.
5. Agent reasoning processes the event context and decides the next action.

## Data Contract
| Field | Type | Description |
|---|---|---|
| `event_id` | `str` | UUID for tracking. |
| `event_type` | `str` | Canonical name, for example `calendar.reminder_due`. |
| `source` | `str` | Name of the service or capability. |
| `priority` | `Enum` | `low`, `medium`, `high`, `critical`. |
| `payload` | `dict` | Structured data for automation. |
| `metadata` | `dict` | Auxiliary tracking info, for example `trace_id`. |

## Canonical Examples

### 1. Calendar Reminder
```python
AgentEvent(
    event_type="calendar.reminder_due",
    source="calendar_service",
    payload={
        "title": "Pair Programming",
        "start_time": "2026-03-17T10:00:00Z",
        "meeting_link": "https://zoom.us/j/123"
    }
)
```

### 2. System Alert
```python
AgentEvent(
    event_type="monitor.alert",
    source="health_monitor",
    priority="high",
    payload={
        "metric": "cpu_usage",
        "value": 95,
        "threshold": 90
    }
)
```

## Difference from WorkerEvent
- `WorkerEvent`: tracks execution progress of a specific task, such as started, progress or failed. It centers on what the worker is doing.
- `AgentEvent`: triggers new reasoning or context updates. It centers on what the world is telling the agent.
## Relacionados

- [agent_events.stat.md](agent_events.stat.md)
- [system_sessions.spec.md](system_sessions.spec.md)
- [session-event-contract.spec.md](session-event-contract.spec.md)
