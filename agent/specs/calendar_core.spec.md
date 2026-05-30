# Calendar Core Architecture

The `calendar` domain provides a robust internal agenda system for the Atlas/Assistant-OS user. It is designed to be highly resilient, timezone-aware, and seamlessly integrated into the agentic input pipeline.

## Components

### 1. CalendarEvent (Model)
- Canonical representation of an event.
- **Validation**: Strict start/end time ordering and IANA timezone validation.
- **Default Reminders**: Standard offsets in minutes (e.g., 15, 30, 60).
- **Time Handling**: Serialized to ISO format but handled as UTC-aware datetimes internally.

### 2. CalendarStore (Persistence)
- Local JSON storage located in `data/calendar/events.json`.
- Optimized for quick lookups and filtration of "upcoming" or "active" events.
- Automatic UTC timestamp comparison for consistent filtering.

### 3. CalendarService (Business Logic)
- Handles the full lifecycle of an event (CRUD).
- Acts as the interface for other services (or future agent tools) to manipulate the user's agenda.
- Notifies the scheduler of changes to ensure temporal triggers stay synchronized.

### 4. CalendarScheduler (Trigger System)
- A daemon thread that monitors the user's agenda every minute.
- **Markers**: Tracks `started` and `reminder_<offset>` markers to guarantee at-most-once delivery of agent events.
- **State Persistence**: Markers are saved to `data/calendar/scheduler_state.json` to survive process restarts.
- **Events**:
  - `calendar.reminder_due`: Emitted when a reminder offset threshold is reached.
  - `calendar.event_starting`: Emitted when the event's start time is reached.

## Input Pipeline Integration

The Calendar domain operates as a "trusted capability":

1. **Scheduler** detects a trigger.
2. Emits an **AgentEvent** via the **InternalDriver**.
3. **InternalDriver** injects the event into the **system.calendar** session.
4. **Kernel** processes the input silently (no UI noise).
5. **Orchestrator** manages the agent reasoning flow within the calendar domain context.

This architecture ensures the agent is aware of the user's schedule without manual polling or external dependencies in this phase.
