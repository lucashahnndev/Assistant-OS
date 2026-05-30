# Calendar Notification Flow Correction

> Documento historico. Este fluxo foi corrigido ou substituido por contratos mais novos no runtime ativo.

## Status

Corrected architectural note, kept as historical reference.

## Context

The initial Phase 5 implementation incorrectly called `orchestrator.notify_user()` directly from `CalendarScheduler`, bypassing the `system.calendar` session logic.

## Corrected Flow

1. `CalendarScheduler` detects a time window and emits an `AgentEvent(calendar.reminder_due, ...)`.
2. `InternalDriver` and `DomainSessionResolver` route the event to `system.calendar`.
3. The agent in `system.calendar` receives the event as an internal thought or message.
4. The agent reasons that the user needs to be notified and executes the `notifications.send` action.
5. `NotificationCapability` calls `orchestrator.notify_user()`, which formally creates a `NotificationIntent`.
6. `NotificationDispatcher` resolves the best target and delivers the message.

## Why It Matters

- auditability is preserved because every notification is traceable to a domain-session decision;
- the scheduler stays decoupled from delivery targets and intents;
- the calendar domain can decide whether, when and how to notify the user.
