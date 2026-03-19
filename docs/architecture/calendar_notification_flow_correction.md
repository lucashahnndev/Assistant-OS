# Calendar Notification Flow Correction

## Status: Corrected (Architectural Alignment)

### 1. Context and Problem
In the initial Phase 5 implementation, the `CalendarScheduler` was incorrectly calling `orchestrator.notify_user()` directly. This bypassed the domain session logic (`system.calendar`), which violated the architectural principle that "domain reasoning should decide on user delivery".

### 2. Corrected Flow
The flow now follows the canonical event-driven pipeline:
1.  **Fact Emission**: `CalendarScheduler` detects a time window and emits an `AgentEvent(calendar.reminder_due, ...)`.
2.  **Routing**: `InternalDriver` and `DomainSessionResolver` route this event to the `system.calendar` session.
3.  **Reasoning**: The agent in `system.calendar` receives the event as an internal thought/message.
4.  **Decision**: The agent reasons that the user needs to be notified and executes the `notifications.send` action.
5.  **Intent Creation**: The `NotificationCapability` calls `orchestrator.notify_user()`, which formally creates a `NotificationIntent`.
6.  **Delivery**: The `NotificationDispatcher` resolves the best target and delivers the message.

### 3. Changes Made
- **CalendarScheduler**: Reverted direct calls to `notify_user`. It now strictly emits `AgentEvent` facts.
- **NotificationCapability**: [NEW] A specialist capability that allows agents to formally trigger the notification delivery layer.
- **AgentOrchestrator**: Registered the new capability and ensured system sessions have access to it.

### 4. Benefits
- **Auditability**: Every notification can be traced back to an agent thought/decision in a domain session.
- **Flexibility**: The `system.calendar` agent can decide to skip notifications, combine them, or change the priority based on context (e.g., "User is in another meeting, I'll lower priority").
- **Decoupling**: The scheduler knows nothing about delivery targets or intents; it only knows about time and events.
