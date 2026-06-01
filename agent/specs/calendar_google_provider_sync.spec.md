# Architecture: Google Calendar Provider Sync

This document describes the integration of Google Calendar as an external provider for the Atlas / Assistant-OS internal calendar domain.

## Core Principle: Internal Source of Truth

The internal calendar domain (`CalendarStore`, `CalendarService`) remains the canonical source of truth for the system. External providers like Google Calendar are treated as secondary data sources that synchronize with the internal models.

## Components

### 1. `CalendarProvider` (Abstraction)
Located at `src/services/calendar/providers/base.py`.
Defines the interface for all external calendar integrations. It ensures that the core calendar logic is not coupled to any specific provider API.

### 2. `GoogleCalendarProvider`
Located at `src/services/calendar/providers/google_provider.py`.
Concrete implementation for Google Calendar. It uses the system's shared OAuth infrastructure (`GoogleAuthShared`) to resolve tokens and make authenticated requests via `urllib`.

### 3. `CalendarSyncService`
Located at `src/services/calendar/sync_service.py`.
The engine that coordinates data flow between a provider and the internal store.
- **Pull Logic**: Periodically (or on-demand) fetches events from the provider.
- **Push Logic**: Propagates internal changes (create, update, delete) to the external provider.
- **Sync State**: Tracks mappings in `sync_mappings_<user_id>.json`, storing `provider_event_id` and `last_synced_at`.

### 4. `CalendarSyncMetadata`
Located at `src/services/calendar/sync_models.py`.
Data structure for tracking the synchronization state of individual events.

## Sync Rules & Conflict Handling

- **New External Events**: Events created in Google are imported as `source="google"` events.
- **Modifications**:
  - If an event is modified internally, it is pushed to Google.
  - If modified in Google, it is pulled internally.
  - **Conflict**: If both internal and external versions were updated since the last sync, the **internal version currently wins** to ensure user-initiated agent changes are preserved.
- **Deletions**:
  - Internal deletion propagates a delete request to Google if a mapping exists.
  - External deletion results in the internal event being marked as `cancelled` or deleted (depending on policy).

## Integration Flow

1. **Initialization**: `AgentOrchestrator` can call `init_user_calendar_sync(user_id)` when a user session is established.
2. **Runtime Sync**: CRUD operations in `CalendarService` trigger immediate `push()` calls to the provider.
3. **Background Sync**: Triggered by the system or on-demand via `sync_all()`.
4. **Impact**: Synced events are picked up by `CalendarScheduler`, which emits `AgentEvent`s, triggering the standard reasoning-and-notification pipeline.
## Relacionados

- [calendar_google_provider_sync.stat.md](calendar_google_provider_sync.stat.md)
- [../README.md](../overview.md)
