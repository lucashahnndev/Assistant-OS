# Calendar Notification Flow Correction

> Documento historico. Este fluxo foi corrigido ou substituido por contratos mais novos no runtime ativo.
> O texto abaixo preserva a linguagem antiga e nao descreve a semantica vigente.

## Status

Corrected architectural note, kept as historical reference.

## Context

The initial Phase 5 implementation incorrectly called `orchestrator.notify_user()` directly from `CalendarScheduler`, bypassing the `system.calendar` session logic.

## Corrected Flow

1. `CalendarScheduler` detects a time window and emits an `AgentEvent(calendar.reminder_due, ...)`.
2. `InternalDriver` and `DomainSessionResolver` route the event to `system.calendar`.
3. The historical agent in `system.calendar` receives the event as an internal thought or message.
4. The historical flow reasons that the user needs to be notified and executes the `notifications.send` action.
5. `NotificationCapability` calls `orchestrator.notify_user()`, which formally creates a `NotificationIntent`.
6. `NotificationDispatcher` resolves the best target and delivers the message.

## Why It Matters

- auditability is preserved because every notification is traceable to a domain-session decision;
- the scheduler stays decoupled from delivery targets and intents;
- the calendar domain can decide whether, when and how to notify the user in the historical flow.

## Relacionados

- [../architecture/README.md](../architecture/README.md): contexto atual de arquitetura de notificacoes e calendario.
- [../guides/README.md](../guides/README.md): guias operacionais ligados ao fluxo corrigido.
- [../../agent/specs/calendar_core.spec.md](../../agent/specs/calendar_core.spec.md): contrato ativo do dominio de calendario.
- [../../agent/specs/calendar-adaptive-alert-architecture.spec.md](../../agent/specs/calendar-adaptive-alert-architecture.spec.md): contrato de alertas que substitui a trilha historica.
- [../../agent/specs/system_sessions.spec.md](../../agent/specs/system_sessions.spec.md): continuidade e isolamento por dominio quando o fluxo chega ao runtime.
