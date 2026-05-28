# Architecture

Este diretorio guarda documentacao humana de arquitetura do sistema.
As specs normativas canônicas vivem em `agent/specs/`.

## Uso

- explicacoes de arquitetura;
- propostas tecnicas como referencia humana;
- notas de evolucao estrutural.

## Indice

### Core Architecture

- [system_architecture.spec.md](system_architecture.spec.md)
- [system_sessions.spec.md](system_sessions.spec.md)
- [trusted_execution_path.spec.md](trusted_execution_path.spec.md)
- [unified-context-rag-architecture.spec.md](unified-context-rag-architecture.spec.md)

### Agent and Runtime

- [agent_events.spec.md](agent_events.spec.md)
- [agent_events.stat.md](agent_events.stat.md)
- [mcp_service_and_playwright_architecture.spec.md](mcp_service_and_playwright_architecture.spec.md)
- [mcp_service_and_playwright_architecture.stat.md](mcp_service_and_playwright_architecture.stat.md)
- [conversational_core_tool_discovery_architecture.spec.md](conversational_core_tool_discovery_architecture.spec.md)
- [conversational_core_tool_discovery_architecture.stat.md](conversational_core_tool_discovery_architecture.stat.md)

### Calendar and External RAG

- [calendar_core.spec.md](calendar_core.spec.md)
- [calendar-adaptive-alert-architecture.spec.md](calendar-adaptive-alert-architecture.spec.md)
- [calendar-adaptive-alert-architecture.stat.md](calendar-adaptive-alert-architecture.stat.md)
- [calendar_google_provider_sync.spec.md](calendar_google_provider_sync.spec.md)
- [calendar_sync_review.spec.md](calendar_sync_review.spec.md)
- [calendar_sync_review.stat.md](calendar_sync_review.stat.md)
- [external_rag_refinements.spec.md](external_rag_refinements.spec.md)
- [external_rag_refinements.stat.md](external_rag_refinements.stat.md)
- [external_rag_final_design_closures.spec.md](external_rag_final_design_closures.spec.md)

### Other

- [wegena_runtime_embedding.spec.md](wegena_runtime_embedding.spec.md)
- [wegena_runtime_embedding.stat.md](wegena_runtime_embedding.stat.md)

## Regra

Se o documento for decisao fechada, mova para `docs/decisions/`.
Se for plano de migracao, mova para `docs/plans/`.
Se for relatorio de auditoria, mova para `docs/reports/`.
