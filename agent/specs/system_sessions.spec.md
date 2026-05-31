# Documentation: System Sessions & Domain Isolation

Note: the broader `Session Event Contract` in `agent/specs/session-event-contract.spec.md` is the umbrella reference for session/message/turn/stream/work/event correlation and persistence. This document remains the narrower system-session/domain-isolation contract.

## Overview
As of Phase 3, the Atlas architecture evolved from a single `system.attention` catch-all to a robust, domain-isolated system session model. This ensures that internal agentic events (calendar, monitoring, notifications) are handled in separate cognitive contexts, preventing domain bleed and improving observability.

## Architecture Components

### 1. Domain Resolution (`DomainSessionResolver`)
The `DomainSessionResolver` is responsible for mapping an incoming `AgentEvent` to a specific domain.
- **Logic**: It inspects the `event_type` (e.g., `event.calendar.*` maps to `calendar`) and the `source`.
- **Targeting**: Converts a domain into a canonical session ID format: `system.<domain>`.
- **Fallback**: Events that cannot be resolved to a specific domain are routed to the legacy `system.attention` session.

### 2. Session Registry (`SystemSessionRegistry`)
The `SystemSessionRegistry` manages the lifecycle of these sessions:
- **Idempotency**: Ensures that `ensure_domain_session(domain)` always returns the same session object and persists it correctly.
- **Metadata**: Marks sessions with `session_type="system"` and saves the `domain` attribute for indexing.

### 3. Identity Integration (Access Control)
System sessions are now integrated with the `AccessController`:
- **Principal Creation**: Every domain session has a corresponding internal user entity.
- **Permission Group**: System identities are automatically assigned to the `critical` group.
- **Approval Status**: These identities are created with `APPROVED` status to ensure immediate execution capability.

## Silent Execution Path
To prevent internal activity from polluting the Human-Agent interface:
- **Session-Level Silence**: The `Session` model defaults to `silent=True` for all messages added to a system session.
- **Real-time Suppression**: `message_added` events are NOT emitted for system sessions, keeping the Web UI clean.
- **Kernel Logic**: The `Kernel` identifies these inputs via `is_internal=True` and suppresses status updates (e.g., "thinking" states).

## Observability & Indexing
The `SessionIndexManager` was updated to index the `domain` field.
- **Filtering**: Developers can list sessions filtered by `domain` or `session_type`.
- **Auditability**: While hidden from the main UI, system sessions maintain their own history for debugging and auditing automated reasoning loops.
