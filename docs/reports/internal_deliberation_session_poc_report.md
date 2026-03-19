# Internal Deliberation Session (PoC) - Analise Tecnica no Atlas

## Escopo
Este documento consolida a analise tecnica para introduzir uma sessao interna de deliberacao continua no Atlas, reutilizando a arquitetura atual (runtime/sessoes/orquestrador/scheduler), sem criar um segundo runtime.

Premissas do PoC:
- Uma unica sessao interna.
- Persistente e system-owned.
- Oculta da lista principal de sessoes.
- Executada periodicamente em background.
- Sem execucao destrutiva por padrao.
- Sem contato automatico com usuario.
- Sem mutacao autonoma permanente.

---

## A) Feasibility Assessment

Conclusao: **viavel com a arquitetura atual**, sem subsystem novo.

Razoes:
1. Sessao persistente ja existe (`Session`, `session.json`, `chat.json`) e o ciclo de save/load ja e robusto.
2. Scheduler periodico ja existe (task definitions + triggers interval/cron/date).
3. Jobs do scheduler ja executam no mesmo caminho de worker + `orchestrator.process(...)`.
4. Telemetria e observabilidade ja existem (`works/*/context.json`, `events.jsonl`, endpoints de tasks/overwatch).

Risco tecnico central identificado:
- Fluxos de worker/scheduled podem rodar sem `PrincipalContext` explicito; nesse caso o `pre_dispatch_gate` nao e aplicado no dispatch em alguns caminhos. Para o PoC interno isso precisa ser fechado.

---

## B) Architectural Fit

### Reuso de componentes existentes
- **Sessao**: `src/core/session.py`
- **Persistencia/indice**: `src/core/orchestrator.py` (`_save_session`, `_load_session`) e `src/core/sessions_index.py`
- **Orquestracao**: `src/core/orchestrator.py::process`
- **Execucao assinc**: `src/core/worker.py`, `src/core/worker_runtime.py`
- **Agendamento periodico**: `src/core/scheduler.py`
- **Entrada de jobs agendados no runtime**: `src/main.py::_event_consumer_loop`
- **ACL/permissions**: `src/core/access_controller.py`, `src/core/plan_validator.py`, `src/services/safety_service.py`

### `session_type` novo ou nao?
Para PoC minimo, daria para operar com `source="internal"` + flags em `context`.

Recomendacao tecnica:
- Introduzir `session_type` explicito (`user`, `internal`) no modelo de sessao para evitar ambiguidade de `source` e facilitar regras de visibilidade, ACL e observabilidade.

### Integracao com orquestrador/scheduler/session/task
Melhor encaixe:
1. Boot cria/retoma uma sessao fixa interna.
2. Boot garante um `TaskDefinition` fixo + `ScheduleTrigger` de intervalo.
3. Trigger dispara `scheduled_job_trigger`.
4. Kernel cria `Work` e worker chama `orchestrator.process(...)` no mesmo pipeline existente.

Sem runtime paralelo.

---

## C) Code Touchpoints

## 1) Session model / visibilidade
- `src/core/session.py`
  - Adicionar campos: `session_type`, `visibility`, `system_owned` (ou equivalente).
  - Persistir em `to_dict`/`from_dict`.
- `src/core/sessions_index.py`
  - `register_session`: indexar os novos metadados.
  - `list_sessions`: filtrar internal por default (manter admin path explicito).

## 2) Bootstrap de lifecycle no boot
- `src/main.py`
  - Em `Kernel.start()` (ou no init do kernel), chamar `ensure_internal_deliberation_bootstrap()`.
  - Garantir idempotencia (nao duplicar task/trigger).
- `src/core/scheduler.py`
  - Reusar `create_task`, `add_trigger`; pode exigir helper `find_task_by_name`/`find_trigger_by_task` para idempotencia limpa.

## 3) Scheduler -> worker -> orchestrator
- `src/main.py::_event_consumer_loop` (`scheduled_job_trigger`)
  - Injetar contexto interno explicito para o worker interno (`PrincipalContext` sintetico).
  - Aplicar marca de origem interna no `user_data`.

## 4) ACL / permission envelope
- `src/core/access_controller.py`
  - Definir policy/grupo interno read-only com allowlist estrita.
- `src/core/orchestrator.py`
  - No dispatch, aplicar gate mesmo quando `context` nao vier explicitamente: fallback para `_get_principal_context(session)`.
  - Reforcar `allowed_actions` via principal da sessao.
- `src/core/plan_validator.py`
  - Reforco opcional: bloquear side-effect destrutivo quando `session_type=internal` no PoC.

## 5) Worker spawning rules
- `src/main.py`, `src/core/scheduler.py`
  - Evitar concorrencia para a sessao interna (nao iniciar novo tick se ha work interno ativo).
  - Opcional PoC: bloquear worker spawning derivado de acoes internas que criem novos schedulers/triggers.

## 6) Tracing / observabilidade
- Reuso de trilhas existentes:
  - Sessao: `history`, `event_history`, `task_registry`, `event_timeline`.
  - Work: `context.json`, `events.jsonl`, endpoints `/api/tasks/works/*`.
- Adicionar tags de origem interna nos eventos para filtro admin.

## 7) Internal outputs (`internal_observation`, `proposal`, etc.)
- Opcao minima: persistir como mensagens `type` nao-default na sessao interna.
- Opcao melhor: salvar bloco estruturado em `work.context.data.internal_outputs[]` + referencia na sessao.

---

## D) Minimal PoC Design

### 1) Uma unica sessao interna
- ID fixo: `internal-deliberation`.
- `session_type="internal"`, `source="internal"`, `system_owned=true`.

### 2) Tick periodico
- Um `TaskDefinition` fixo (`atlas_internal_deliberation_tick`).
- Um trigger `interval` (ex.: 5 ou 10 min para inicio).

### 3) Prompt/bootstrap suave
Prompt inicial simples, sem workflow hardcoded:
- objetivo: observar ambiente, skills, estado runtime, logs e works
- gerar observacoes, propostas e diagnosticos
- sem contato com usuario
- sem acao destrutiva

### 4) Fontes de contexto inspecionaveis (mapeadas ao runtime atual)
- memory.read -> `memory.recall` e/ou `deep.memory.recall_memory`
- task.inspect -> `task.scheduler.list`, `task.scheduler.list_works`
- log.inspect -> `system_logs.list`, `system_logs.read`
- web.search.read -> `web.search.discover`, `web.retrieve.read`
- rag.external.read -> `research.retrieve.run`
- shell.workspace.read -> preferir `system.control.fs.list/read` (evitar shell execute no PoC)
- vision.read -> `vision.analyze`, `vision.search_screen` (se necessario)

### 5) Outputs permitidos
Estruturas internas:
- `internal_observation`
- `proposal`
- `diagnostic_report`
- `memory_candidate`

Sem envio a chat de usuario.

### 6) Armazenamento
- Sessao interna (`chat.json`, `session.json`).
- `works` internos (`context.json`, `events.jsonl`) para painel administrativo.

---

## E) Lifecycle Model

## Criacao no boot
1. Kernel sobe.
2. `ensure_internal_deliberation_bootstrap()`:
   - carrega sessao interna existente ou cria se nao existir
   - garante task definition fixa
   - garante trigger de intervalo

## Resume
- Se sessao/task/trigger ja existem, apenas reutiliza.
- Sem duplicar artefatos.

## Frequencia
- Inicial recomendado: 10 min (conservador).
- Ajustavel por config.

## Evitar runaway loop/custo
- Nao iniciar tick novo se ha `WorkStatus` ativo para essa sessao/tarefa.
- Cap de passos por run (`max_steps`) e timeout por run.
- Limitar volume de output interno por tick.
- Debounce de propostas repetidas (hash/dedupe key em outputs).

---

## F) Safety Constraints

Objetivo: garantir que o PoC interno nao escale privilegios nem burle controles.

1. **Sem privilege escalation**
- Sessao interna recebe principal/grupo proprio e restrito.
- Nao usa grupo `master`.

2. **Sem bypass de skill gate**
- Dispatch precisa passar por `pre_dispatch_gate` tambem em scheduled runs sem context explicito (fallback pelo principal persistido da sessao).

3. **Sem destructive actions por default**
- Allowlist interna somente read/analysis.
- Deny explicito para: shell write/exec privilegiado, fs mutation, browser action, patch apply, sends externos, memory global writes.

4. **Sem poluicao de chat usuario**
- Sessao interna nao aparece na listagem principal.
- Nenhum evento interno vira mensagem user-facing automaticamente.

5. **Sem execucao oculta fora regras de aprovacao**
- Mesmo pipeline de Worker/Scheduler/Orchestrator.
- Logs e works acessiveis no painel admin.

---

## Riscos e decisoes em aberto

1. **Budget de tokens por tick**
- Definir teto por run para nao competir com UX principal.

2. **Intervalo ideal**
- 5 min traz mais reatividade, 10-15 min reduz custo/ruido.

3. **Volume de output**
- Necessario cap por tipo (`proposal`, `diagnostic_report`, etc.).

4. **Memoria**
- Decidir se `memory_candidate` interno entra apenas em sessao interna (recomendado no PoC) sem global write.

5. **Visibilidade admin**
- Definir endpoint/filtro claro de `internal sessions` (em vez de depender apenas de comportamento indireto da listagem atual).

6. **Worker spawning interno**
- Para PoC, recomendado desabilitar ou limitar acoes internas que criem novos tasks/triggers.

---

## Plano incremental recomendado

## Step 1 - Bootstrap interno idempotente
**Arquivos/funcoes:**
- `src/main.py` (`Kernel.start` + helper bootstrap)
- `src/core/scheduler.py` (helpers de find/upsert opcionais)
- `src/core/orchestrator.py` (`create_session` com metadados internos)

**Comportamento esperado:**
- Na subida, existe exatamente 1 sessao interna + 1 task + 1 trigger interval.

**Criterio de aceitacao:**
- Reiniciar Atlas nao duplica task/trigger.

## Step 2 - Envelope de permissoes interno
**Arquivos/funcoes:**
- `src/core/access_controller.py`
- `src/core/orchestrator.py` (dispatch gate fallback para principal da sessao)
- `src/core/plan_validator.py` (hard-block destrutivo interno opcional)

**Comportamento esperado:**
- Sessao interna so executa acoes read-only permitidas.

**Criterio de aceitacao:**
- Tentativa de acao bloqueada gera negacao deterministica e nao executa side effect.

## Step 3 - Tick periodico e sem contato com usuario
**Arquivos/funcoes:**
- `src/main.py::_event_consumer_loop`
- `src/core/orchestrator.py::process`

**Comportamento esperado:**
- Tick roda em background na sessao interna e grava outputs internos.
- Nenhuma mensagem e enviada para sessoes de usuario.

**Criterio de aceitacao:**
- Work interno aparece em `/api/tasks/works`, sem poluir chat principal.

## Step 4 - Outputs internos estruturados
**Arquivos/funcoes:**
- `src/core/session.py`
- `src/core/orchestrator.py` (normalizacao/tipagem de outputs)
- `src/server/routes/tasks.py` / `src/server/routes/sessions.py` (leitura admin)

**Comportamento esperado:**
- `internal_observation`, `proposal`, `diagnostic_report`, `memory_candidate` ficam consultaveis de forma estruturada.

**Criterio de aceitacao:**
- Painel admin consegue listar outputs por tick.

## Step 5 - Guardrails de custo/loop
**Arquivos/funcoes:**
- `src/main.py`
- `src/core/orchestrator.py`
- `data/config.json` (novos knobs)

**Comportamento esperado:**
- Sem sobreposicao de runs internos; limites de passos/tempo/token ativos.

**Criterio de aceitacao:**
- Estabilidade de CPU/tokens em execucao prolongada.

---

## Observacoes finais
- Esta proposta mantem o PoC como **sessao interna no mesmo runtime Atlas**.
- Nao cria engine paralelo.
- Prioriza reuso com mudancas pequenas, rastreaveis e auditaveis.
