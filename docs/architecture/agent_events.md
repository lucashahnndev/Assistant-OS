# Documentation: Agent Events (Internal Events)

## Overview
`AgentEvent` is the formal contract for internal system signals that require agent attention. It allows capabilities and background services to wake up a system session (e.g., `system.attention`) with structured context and human-readable summaries.

## Flow
1. **Capability/Service**: Generates an `AgentEvent`.
2. **InternalDriver**: Receives the event, transforms it into an agent-readable input, and attaches the structured payload to the metadata.
3. **Kernel**: Processes the input as internal (`is_internal=True`), suppressing user-facing notifications.
4. **Agent Orchestrator**: Routes the event to the correct system session.
5. **Agent Reasoning**: Processes the event context to decide on the next action.

## Data Contract
| Field | Type | Description |
|---|---|---|
| `event_id` | `str` | UUID for tracking. |
| `event_type` | `str` | Canonical name (e.g., `calendar.reminder_due`). |
| `source` | `str` | Name of the service/capability. |
| `priority` | `Enum` | `low`, `medium`, `high`, `critical`. |
| `payload` | `dict` | Structured data for automation. |
| `metadata` | `dict` | Auxiliar tracking info (e.g., `trace_id`). |

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
- **WorkerEvent**: Tracks execution progress of a specific task (started, progress, failed). Centers on "what the worker is doing".
- **AgentEvent**: Triggers new reasoning or context updates. Centers on "what the world is telling the agent".
