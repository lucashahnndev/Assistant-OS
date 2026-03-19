# Calendar Sync Review Architecture

## Overview

In Phase 7, the Atlas/Assistant-OS moves away from purely deterministic and potentially destructive synchronization in the `calendar` domain. Instead of the `CalendarSyncService` making final decisions on ambiguous states, it now elevates these states to **Agentic Events**.

## The Flow

1.  **Detection**: `CalendarSyncService` detects a conflict (both sides updated) or an ambiguous deletion (deleted externally but has recent local updates).
2.  **Elevation**: The service emits an `AgentEvent` with the type `calendar.sync_conflict_detected` or `calendar.external_deletion_detected`.
3.  **Routing**: The `InternalDriver` routes this event to the `system.calendar` session.
4.  **Reasoning**: The `system.calendar` agent (guided by the `calendar` specialist profile) analyzes the payload.
5.  **Resolution**: 
    - **Safe**: The agent applies a resolution automatically (e.g., choosing the version with more details).
    - **Ambiguous**: The agent generates a `NotificationIntent` to ask the user for a decision.

## Event Payloads

### `calendar.sync_*` Payload structure:
- `internal_event_id`: UUID of the internal event.
- `provider`: Name of the provider (e.g., `GoogleCalendarProvider`).
- `conflict_type`: `both_updated` | `ambiguous_deletion`.
- `internal_snapshot`: JSON representation of current internal state.
- `provider_snapshot`: JSON representation of provider state.
- `diff`: Fields that changed.
- `last_internal_update`: Timestamp.
- `last_provider_update`: Timestamp.

## Sync States

Events in the `CalendarStore` can have a `sync_state`:
- `synced`: Fully synchronized with provider.
- `review_required`: Pending agentic or human decision.
- `conflicted`: Local state differs from provider and needs resolution.

## Specialist Rules (system.calendar)

The `calendar` specialist is programmed with these safe-guards:
1. **No Data Loss**: Never delete an event with meaningful local updates without user confirmation.
2. **Preference**: If updates are minor (e.g., description formatting), prefer the one with the most recent timestamp.
3. **Clarity**: When asking the user, show the exact divergence (e.g., "Title changed to X in Google, but Y in Atlas").
