# Documentation: Trusted Execution Path (InternalDriver)

## Current Status: Phase 3
As of Phase 3, the `InternalDriver` remains a **trusted execution path**, but with significantly hardened identity and routing mechanics.
This path should be read together with [atlas_operating_model.spec.md](atlas_operating_model.spec.md), which defines the agent/runtime boundary that uses this trust path.

### Why it is safe today
1. **Kernel Residency**: Owned and instantiated exclusively by the `Kernel`.
2. **Domain Isolation**: Events are routed to specific `system.<domain>` sessions, preventing cognitive and context crosstalk.
3. **Identity Integration**: System sessions are now authenticated principals within the `AccessController`, assigned to the `critical` permission group.
4. **Controlled Injection**: `inject_event` mandates `AgentEvent` contracts or explicit session targets, maintaining the `is_internal=True` safety fork.

### Current Limits (Addressed in Phase 3)
- ~~**Identity Simplification**~~: Now integrated with the identity framework.
- **Source Authentication**: Still assumes any code calling `InternalDriver` is trusted.
- **Capability Scoping**: Restricting which tools a specific system domain can use is the target of Phase 4.

### Future Roadmap
1. **Source Authentication**: Implement caller signatures for services.
2. **Capability Scoping**: Dynamic tool whitelisting per system domain.
3. **Auditability**: Enhanced logging for automated reasoning loops.
## Relacionados

- [trusted_execution_path.stat.md](trusted_execution_path.stat.md)
- [../README.md](../overview.md)
