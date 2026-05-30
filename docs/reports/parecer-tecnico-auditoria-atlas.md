# Parecer Tecnico de Auditoria do Atlas

Data: 2026-05-27

## Escopo

Este documento resume os bugs logicos encontrados e corrigidos na base do Atlas durante a auditoria recente, com foco em:

- roteamento de acoes e recuperacao
- controle de acesso e validacao de planos
- memoria, cognicao e sinalizacao de progresso
- integracao MCP e Obsidian
- telemetria de contexto e hints
- normalizacao de respostas dos provedores LLM

Observacao: ha mudancas de frontend no worktree que nao fazem parte desta auditoria funcional. Este parecer cobre apenas a camada logica e de integracao que foi analisada e ajustada.

## Resumo executivo

Foram encontrados varios falsos positivos, caminhos de fallback silenciosos e inconsistencias de telemetria. O principal padrao de falha era o sistema responder como se tivesse executado algo com sucesso, quando na pratica a acao havia sido barrada por validacao, roteamento incorreto ou classificacao de resultado incompleta.

As correcoes mais relevantes foram:

- canonizacao de acoes MCP e correcao do caminho de escrita no Obsidian
- reforco do fail-closed em acesso e validacao
- correcao de classificacao de resultados parciais e fallback
- correcao de memoria candidata, patch de identidade e dedupe por `memory_id`
- filtragem mais estrita de progresso, experiencia de agente e outcome generico
- eliminacao de falso positivo em `ranking_changed_by_hint`
- normalizacao de respostas em provedores OpenAI, Ollama e HuggingFace

## Bugs encontrados e corrigidos

| Area | Bug encontrado | Impacto | Correcoes aplicadas | Prova concreta |
|---|---|---|---|---|
| Obsidian / MCP | Pedido como `obsidian.note.create` caia em `system.file.write` ou em fallback, sem dispatch real da tool | O chat dizia "sucesso" sem haver escrita confiavel | Canonizacao de aliases MCP e roteamento mais preciso em `src/core/resolution/llm_resolver.py` | Log mostra `LLM confidence 0.16 below threshold 0.65 for action 'obsidian.note.create'` seguido de `FallbackChainResolver` e `Recovery reply generated` em [assistant.log](/home/lucas/Documentos/GitHub/Assistant-OS/data/logs/assistant.log:43186) |
| Acesso | `AccessController` podia estourar quando metadata de risco/permissao nao existia | Falha em tempo de execucao, em vez de negar de forma segura | Fail-closed em `src/core/access_controller.py` | Teste de seguranca em `tests/minimal/test_access_controller_safety.py` |
| Validacao de plano | `PlanValidator` dependia de registry presente e podia falhar fora do lugar correto | Excecao antes da negacao controlada | Reforco de guard clauses em `src/core/plan_validator.py` | Coberto pela bateria de lockdown/plan validation |
| Execucao | `allowed_actions=[]` podia ser interpretado de forma permissiva em alguns fluxos | Acesso indevido por ambiguidade de allowlist | Normalizacao de allowlist e fluxo de decisao em `src/core/action_gateway.py` e `src/core/resolution/llm_resolver.py` | Suíte de regressao de arquitetura/lockdown passou apos a correcao |
| Orchestrator | `_summarize_last_success_data` tinha assinatura inconsistente e havia caminhos de recovery que podiam responder sucesso sem prova real | Falso positivo em recovery | Ajuste de assinatura, classificacao de `partial` e protecao de reply em `src/core/orchestrator.py` | `tests/minimal/test_orchestrator_recovery_safety.py` |
| Cognicao | Resultados `partial`, `fallback`, `running`, `pending`, `in_progress` podiam ser tratados como sucesso implicito | Progresso artificial | `_assess_action_result(...)` passou a devolver `partial` nesses casos | `tests/minimal/test_orchestrator_recovery_safety.py` |
| Outcomes | Outcome generico/desconhecido era colapsado em `action_executed` | `task_progressed` e `task_completed` podiam ser marcados sem semantica real | `src/services/cognition/outcomes.py` preserva `generic_fallback_used` | `tests/cognition/test_cognitive_outcomes.py` |
| Reconciler | `recent_progress` aceitava sinais fracos ou negativos como progresso | Memoria de progresso contaminada | Filtro mais conservador em `src/services/cognition/reconciler.py` | `tests/cognition/test_cognitive_reconciler.py` |
| Commit strength | `commit_signal_strength` podia subir demais para outcomes genericos | Telemetria otimista demais | Cap de `medium` para outcomes genericos em `src/services/cognition/effectiveness.py` | `tests/cognition/test_cognitive_effectiveness.py` |
| Memory ingest | Memoria candidata podia entrar como memoria aceita; `memory_id` era tratado de forma inconsistente | Memoria falsa ou patch aplicado no item errado | Filtro de `accepted`, identidade canonica e patch por `memory_id` em `src/services/context/ingestion/user_memory_ingestor.py` e `src/core/session.py` | `tests/minimal/test_user_memory_ingestor_safety.py` e `tests/minimal/test_memory_patch_identity.py` |
| Event infra | Eventos com `memory_id` podiam ser suprimidos indevidamente por dedupe do candidate store | Perda de evento valido | Dedupe restrito ao tipo `MEMORY_CANDIDATE` em `src/core/session.py` | `tests/minimal/test_event_infrastructure.py` |
| Agent experience | Experiencias positivas ou frases com negacao de falha podiam ser promovidas como aprendizado de erro | Aprendizado contaminado | Filtros mais conservadores em `src/services/context/ingestion/agent_experience_ingestor.py` | `tests/minimal/test_agent_experience_ingestor_safety.py` |
| Context broker | `ranking_changed_by_hint` gerava falso positivo porque o baseline era calculado com `max_items=6` e o hinted com outro cap | Telemetria errada no painel | Baseline agora usa o mesmo `max_items` do ranking principal em `src/services/context/broker.py` | `tests/cognition/test_cognitive_hint_effectiveness.py` |
| LLM providers | OpenAI, Ollama e HuggingFace tratavam respostas e tool calls de forma inconsistente | Fallbacks silenciosos e JSON mal normalizado | Normalizacao de resposta e parsing mais robusto em `src/drivers/providers/openai/llm.py`, `src/drivers/providers/ollama/llm.py` e `src/drivers/providers/huggingface/llm.py` | `tests/minimal/test_gemini_response_text_normalization.py` e suites de alinhamento de provider |

## Evidencias concretas

### 1. Log do bug no Obsidian

Em [data/logs/assistant.log](/home/lucas/Documentos/GitHub/Assistant-OS/data/logs/assistant.log:43186), o turno mostrou:

- `LLM confidence 0.16 below threshold 0.65 for action 'obsidian.note.create'`
- notas de decisao: `action_outside_allowed_scope`, `params_present`, `thought_present`, `plan_present`
- queda para `FallbackChainResolver`
- `Triggering LLM Recovery Loop`
- `Recovery reply generated`

Esse trecho prova que a resposta textual de "sucesso" nao garantia dispatch real da tool.

### 2. Telemetria de hint false positive

O bug do `ranking_changed_by_hint` estava em [src/services/context/broker.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/context/broker.py:139). O baseline foi alinhado ao mesmo `max_items` do ranking principal para evitar diferenca artificial causada apenas por limite de corte.

O teste de regressao foi adicionado em [tests/cognition/test_cognitive_hint_effectiveness.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/cognition/test_cognitive_hint_effectiveness.py:93).

### 3. Correcoes de execucao e recovery

As areas que passaram a evitar falso sucesso e negacao indevida de acao incluem:

- [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py:3131)
- [src/core/access_controller.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/access_controller.py)
- [src/core/action_gateway.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/action_gateway.py)
- [src/core/plan_validator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/plan_validator.py)

### 4. Memoria e cognicao

As protecoes contra memoria contaminada e progresso falso estao em:

- [src/services/context/ingestion/user_memory_ingestor.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/context/ingestion/user_memory_ingestor.py)
- [src/core/session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py)
- [src/services/cognition/reconciler.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/cognition/reconciler.py)
- [src/services/cognition/effectiveness.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/cognition/effectiveness.py)
- [src/services/cognition/outcomes.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/cognition/outcomes.py)

### 5. MCP e Obsidian

O Atlas passou a ter:

- cliente MCP generico
- transporte HTTP e stdio
- descoberta de tools e resources
- rotas de sistema para status e refresh
- interface de configuracao no frontend

Arquivos principais:

- [src/services/mcp/runtime.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/mcp/runtime.py)
- [src/server/routes/system.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/system.py)
- [frontend/src/pages/Settings.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Settings.jsx)

## Validacao executada

As suites abaixo foram executadas com sucesso durante a auditoria:

- `PYTHONPATH=src ./env/bin/python -m pytest tests/cognition/test_cognitive_hint_effectiveness.py tests/cognition/test_cognitive_broker_hints.py tests/cognition/test_cognitive_diagnostics_integration.py -q` -> `8 passed`
- `PYTHONPATH=src ./env/bin/python -m pytest tests/minimal/test_access_controller_safety.py tests/minimal/test_orchestrator_recovery_safety.py tests/minimal/test_mcp_llm_alias_and_recovery.py tests/minimal/test_user_memory_ingestor_safety.py tests/minimal/test_agent_experience_ingestor_safety.py tests/minimal/test_event_infrastructure.py tests/minimal/test_memory_patch_identity.py tests/minimal/test_intent_agenda_reentry.py -q` -> `27 passed`

Outras baterias relevantes, executadas ao longo da auditoria e ja validadas:

- memoria e cognicao: `21 passed`
- outcomes e coverage: `9 passed`
- effectiveness/reconciler/commit: `12 passed`
- infrastrutura de eventos e memoria: `14 passed`

## Risco residual

O principal risco residual nao e mais de corretude basica, e sim de telemetria semantica fina em dashboards e rotas de observabilidade. Em especial:

- metricas de hint podem ainda ser interpretadas de forma exagerada por analises externas
- o ecossistema MCP depende do comportamento do plugin/servidor externo do Obsidian para expor `resources`
- qualquer novo provider LLM precisa manter a mesma disciplina de normalizacao e envelopes

## Conclusao

A auditoria encontrou erros reais de logica e varios falsos positivos de sucesso. As correcoes reduziram:

- dispatch silencioso sem prova de execucao
- memoria e progresso contaminados por sinais fracos
- telemetria enganosa de ranking/hints
- inconsistencias de provider e parsing

O Atlas ficou mais deterministico, mais seguro para operacao e mais confiavel para observabilidade.
