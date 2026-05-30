# Calendar Sync Review Spec

## Overview

This specification defines how ambiguous calendar synchronization states are elevated to agentic review instead of being resolved destructively by the sync service.

## The Flow

1. `CalendarSyncService` detects a conflict, such as both sides being updated, or an ambiguous deletion, such as an item deleted externally but with recent local updates.
2. The service emits an `AgentEvent` with the type `calendar.sync_conflict_detected` or `calendar.external_deletion_detected`.
3. `InternalDriver` routes this event to the `system.calendar` session.
4. The agent in `system.calendar`, guided by the `calendar` specialist profile, analyzes the payload.
5. Resolution occurs in one of two ways:
   - Safe: the agent applies a resolution automatically, for example by choosing the version with more details.
   - Ambiguous: the agent generates a `NotificationIntent` to ask the user for a decision.

## Event Payloads

### `calendar.sync_*` payload structure
- `internal_event_id`: UUID of the internal event.
- `provider`: Name of the provider, such as `GoogleCalendarProvider`.
- `conflict_type`: `both_updated` or `ambiguous_deletion`.
- `internal_snapshot`: JSON representation of current internal state.
- `provider_snapshot`: JSON representation of provider state.
- `diff`: Fields that changed.
- `last_internal_update`: Timestamp.
- `last_provider_update`: Timestamp.

## Sync States

Events in `CalendarStore` can have a `sync_state`:
- `synced`: fully synchronized with provider.
- `review_required`: pending agentic or human decision.
- `conflicted`: local state differs from provider and needs resolution.

## Specialist Rules (`system.calendar`)

The `calendar` specialist is configured with the following safeguards:
1. No data loss: never delete an event with meaningful local updates without user confirmation.
2. Preference: if updates are minor, such as description formatting, prefer the one with the most recent timestamp.
3. Clarity: when asking the user, show the exact divergence, for example, `Title changed to X in Google, but Y in Atlas`.
