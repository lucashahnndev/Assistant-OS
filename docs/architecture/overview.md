# Architecture

Este diretorio guarda documentacao humana de arquitetura do sistema.
As specs normativas canônicas vivem em `agent/specs/`.
O runtime executa e valida; Atlas carrega a autoridade semantica.

`Session Event Contract` e o dominio guarda-chuva para sessoes, mensagens, turnos, streams, works, eventos, indices e persistencia. Para trabalho novo em session/event/WebSocket, consulte esse contrato primeiro; `system_sessions` e `agent_events` permanecem como contratos especificos e complementares.
Quando a pergunta for sobre isolamento de dominio e a semantica `system.<domain>`, leia tambem `system_sessions.spec.md` e `system_sessions.stat.md`.

## Uso

- explicacoes de arquitetura;
- propostas tecnicas como referencia humana;
- notas de evolucao estrutural.

## Indice

### Core Architecture

- [system_architecture.spec.md](../../agent/specs/system_architecture.spec.md)
- [system_sessions.spec.md](../../agent/specs/system_sessions.spec.md)
- [system_sessions.stat.md](../../agent/specs/system_sessions.stat.md)
- [trusted_execution_path.spec.md](../../agent/specs/trusted_execution_path.spec.md)
- [unified-context-rag-architecture.spec.md](../../agent/specs/unified-context-rag-architecture.spec.md)

### Atlas and Runtime

- [agent_events.spec.md](../../agent/specs/agent_events.spec.md)
- [agent_events.stat.md](../../agent/specs/agent_events.stat.md)
- [mcp_service_and_playwright_architecture.spec.md](../../agent/specs/mcp_service_and_playwright_architecture.spec.md)
- [mcp_service_and_playwright_architecture.stat.md](../../agent/specs/mcp_service_and_playwright_architecture.stat.md)
- [conversational_core_tool_discovery_architecture.spec.md](../../agent/specs/conversational_core_tool_discovery_architecture.spec.md)
- [conversational_core_tool_discovery_architecture.stat.md](../../agent/specs/conversational_core_tool_discovery_architecture.stat.md)

### Calendar and External RAG

- [calendar_core.spec.md](../../agent/specs/calendar_core.spec.md)
- [calendar_core.stat.md](../../agent/specs/calendar_core.stat.md)
- [calendar-adaptive-alert-architecture.spec.md](../../agent/specs/calendar-adaptive-alert-architecture.spec.md)
- [calendar-adaptive-alert-architecture.stat.md](../../agent/specs/calendar-adaptive-alert-architecture.stat.md)
- [calendar_google_provider_sync.spec.md](../../agent/specs/calendar_google_provider_sync.spec.md)
- [calendar_google_provider_sync.stat.md](../../agent/specs/calendar_google_provider_sync.stat.md)
- [calendar_sync_review.spec.md](../../agent/specs/calendar_sync_review.spec.md)
- [calendar_sync_review.stat.md](../../agent/specs/calendar_sync_review.stat.md)
- [external_rag_refinements.spec.md](../../agent/specs/external_rag_refinements.spec.md)
- [external_rag_refinements.stat.md](../../agent/specs/external_rag_refinements.stat.md)
- [external_rag_final_design_closures.spec.md](../../agent/specs/external_rag_final_design_closures.spec.md)

### Other

- [wegena_runtime_embedding.spec.md](../../agent/specs/wegena_runtime_embedding.spec.md)
- [wegena_runtime_embedding.stat.md](../../agent/specs/wegena_runtime_embedding.stat.md)

## Regra

Se o documento for decisao fechada, mova para `docs/decisions/`.
Se for plano de migracao, mova para `docs/plans/`.
Se for relatorio de auditoria, mova para `docs/reports/`.

## Relacionados

- [../overview.md](../overview.md)
- [../contracts/overview.md](../contracts/overview.md)
- [../policies/overview.md](../policies/overview.md)
- [../plans/overview.md](../plans/overview.md)
- [../decisions/overview.md](../decisions/overview.md)
- [../reports/overview.md](../reports/overview.md)
- [../guides/overview.md](../guides/overview.md)
- [../concepts/overview.md](../concepts/overview.md)
- [../legacy/overview.md](../legacy/overview.md)
- [../../agent/overview.md](../../agent/overview.md)
- [../../agent/specs/overview.md](../../agent/specs/overview.md)
