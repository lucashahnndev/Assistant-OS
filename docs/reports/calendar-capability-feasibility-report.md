# Relatório de Viabilidade — System Sessions / Internal Driver (Atlas / Assistant-OS)

> Documento historico. Esta viabilidade descreve uma direcao anterior e pode nao refletir o contrato discovery-first atual.

## 1. Resumo da Arquitetura Atual (relevante)

- **Entrada**: drivers chamam `Kernel.process_input`, que cria/resolve sessão, resolve intenção e inicia o loop agentic. (`src/drivers/interfaces/base_driver.py`, `src/drivers/interfaces/server_driver.py`, `src/main.py`)
- **Pipeline principal**: driver → `Kernel.process_input` → `AgentOrchestrator.get_initial_intent` → `AgentOrchestrator.process` → resposta via driver. (`src/main.py`, `src/core/orchestrator.py`)
- **Sessões**: `Session` já tem `source`, histórico, `event_history`, `event_timeline`, `task_registry`, memória etc., com persistência em `session.json` + `chat.json`. (`src/core/session.py`, `src/core/orchestrator.py`)
- **UI/listagem**: index de sessões filtra por `interface` (web/telegram); outras interfaces não aparecem na listagem web. (`src/core/sessions_index.py`, `src/server/routes/sessions.py`)
- **Eventos internos atuais**: workers publicam eventos na session (`publish_event` → `event_history`), e o orchestrator decide o que fazer com eles. (`src/core/session.py`, `src/core/orchestrator.py`, `src/core/worker_runtime.py`, `src/core/events.py`)
- **Sistema de acesso**: `PrincipalContext` governa permissões; interfaces não listadas no policy caem num default restritivo. (`src/core/identity.py`, `src/core/access_controller.py`)

## 2. Viabilidade de `system sessions`

**É viável**, porque:

- A `Session` já possui **campo `source`** que define a interface e persiste no index. (`src/core/session.py`, `src/core/orchestrator.py`, `src/core/sessions_index.py`)
- Há suporte a **persistência completa** e **carregamento lazy**. (`src/core/orchestrator.py`)
- Existe conceito de **sessões transitórias** via `session.context["__transient_session"]` e `source="system"` (usado hoje para workers), indicando tolerância a “sessões não humanas”. (`src/core/orchestrator.py`)

**Pontos de atenção**:

- `source` hoje é **interface**, não tipo. Usar `source="system"` funciona para esconder da UI, mas **mistura tipo com interface**. Talvez seja melhor adicionar `session.type` (“user|system”) mantendo `source` como interface. (`src/core/session.py`, `src/core/sessions_index.py`)
- `Kernel.process_input` sempre grava mensagem como “user” e emite eventos para UI. Há comentário explícito sobre “internal/hidden trigger ainda não existe”. Isso precisa ser ajustado para evitar poluição de histórico/UI. (`src/main.py`)

## 3. Viabilidade de `internal driver`

**É viável e coerente** com a arquitetura atual:

- O contrato `BaseDriver` permite um driver que **só injeta input** e **não responde** (send_* no-op). (`src/drivers/interfaces/base_driver.py`)
- Já existe um `SystemDriver`, mas ele é para controle do host (CPU, processos etc.), não para eventos internos. Usá-lo para eventos pode confundir responsabilidades. (`src/drivers/interfaces/system_driver.py`)
- Há um esboço de **envelope universal** (`UniversalInputFrame`) para inputs canônicos, apesar de **não estar usado**. Isso é um bom ponto de apoio para um driver interno. (`src/drivers/contracts.py`)

**Ponto crítico**:

- Se o internal driver usar `PrincipalContext(interface="system")`, o `AccessController` aplicará política default restritiva (approved_only, rate limit). Isso pode bloquear eventos internos se não houver policy para “system”. (`src/core/access_controller.py`)

## 4. Como eventos internos podem entrar no pipeline atual

Caminho mais natural (reuso do pipeline existente):

1. Evento interno ocorre (capability/serviço).
2. Internal driver normaliza e chama `Kernel.process_input`.
3. `process_input` → orchestrator → loop agentic.

**Problema atual**:

- `Kernel.process_input` grava sempre uma mensagem “user” no histórico e emite `message_added` via event bus. Isso pode gerar ruído na UI. (`src/main.py`, `src/core/session.py`, `src/drivers/interfaces/server_driver.py`)

Isso exige um mecanismo de **“input interno não visível”** (ex: `user_data["internal_event"]=True` + condicionais em `process_input` e/ou `Session.add_message`).

**Alternativa existente**:

- O sistema já tem um caminho “semi-interno” via **Scheduler + Worker**, com `transient_session` e `SYSTEM_WORKER_ANCHOR_SESSION_ID`. Isso pode ser reaproveitado no MVP para rodar eventos internos sem UI. (`src/core/scheduler.py`, `src/main.py`)
- Porém, esse fluxo é mais voltado a jobs do que a “system session persistente”.

## 5. Envelope estruturado para eventos internos

Há dois formatos no repositório que podem inspirar o envelope:

- `WorkerEvent` (event_type, priority, origin, etc.) → já tem semântica de evento interno, mas voltado a workers. (`src/core/events.py`)
- `UniversalInputFrame` → estrutura “canônica” para input, porém ainda não usada. (`src/drivers/contracts.py`)

Seu envelope proposto é compatível com o modelo atual. Sugestão: definir um **`InternalEventEnvelope`** que:

- seja criado no **internal driver**,
- seja injetado como `user_data` e/ou como `text` prefixado (“[SYSTEM_EVENT] …”),
- seja preservado no `session.context` para o prompt.

Campos com paralelos atuais:

- `event_type` → `WorkerEventType` / `session.publish_event`
- `source` → `Session.source` ou `context["principal_context"]`
- `priority` → `WorkerEvent` priority / `attention_score`
- `target_session_id` → já suportado por `_send_to_session` e routing. (`src/main.py`)

## 6. System session como linha de raciocínio persistente

**Viável**, porque:

- Sessões têm persistência robusta. (`src/core/orchestrator.py`)
- Não há TTL automático (logo, podem ficar “sempre disponíveis”). (`src/core/orchestrator.py`)
- Há locks de sessão para concorrência. (`src/core/orchestrator.py`)

**Pontos de cuidado**:

- “Sempre ativa” hoje significa “recarregável”, não “resident”. Para manter ativa, precisaria de rotinas de warm-load/loop dedicado (não existe hoje).
- Reset automático pode ser feito via `delete_session` + recriação, que já existe. (`src/core/orchestrator.py`)

## 7. Eventos internos acordando o agent

Hoje **não existe** um caminho “oficial” para eventos internos fora de:

- input humano (drivers)
- scheduled jobs
- hooks de worker

`on_event` no orchestrator é apenas stub. (`src/core/orchestrator.py`)

Logo, **um internal driver é a forma mais limpa de “acordar” o agent sem hardcode no kernel**. O kernel já aceita qualquer driver chamando `process_input`. (`src/main.py`, `src/drivers/interfaces/base_driver.py`)

## 8. Separação de responsabilidades

A separação proposta **encaixa bem na arquitetura atual**, com pequenos ajustes:

- Capabilities/serviços geram eventos brutos → já fazem isso para workers.
- Driver interno normaliza → não existe, mas encaixa no modelo de drivers.
- System session raciocina → compatível com `Session` + `Orchestrator`.
- Notificação ao usuário via sessão alvo → já existe `_send_to_session` e routing por driver. (`src/main.py`)

**Refatoração necessária**: pequena a média, principalmente:

- permitir input “interno/oculto” sem poluir histórico/UI,
- garantir policy/segurança para a interface “system”.

## 9. Sessão alvo / entrega ao usuário

Caminhos existentes:

- `Kernel._send_to_session` envia via driver, mas **depende do session_id estar mapeado** e não é “agnóstico”. (`src/main.py`)
- `driver_instances` mapeia sessões a drivers (associado a input anterior). Para notificações “offline”, o driver pode não estar registrado. (`src/main.py`)

Logo, para notificações:

- será necessário um **dispatcher explícito**, ou
- escolher uma `target_session_id` ativa (se houver), ou
- criar um “pending message” que o frontend puxará.

Hoje não há dispatcher central: isso precisará ser criado ou adicionado no MVP.

## 10. Estado de presença / escolha de canal

- Presença websocket existe apenas dentro do `ServerDriver.ConnectionManager`, e **não é exposta** para o kernel/orchestrator. (`src/drivers/interfaces/server_driver.py`)
- Não há mecanismo comum para Telegram/Voice.

Portanto, **a heurística “se websocket ativo” não é acessível hoje** sem criar uma ponte.

Para MVP, a seleção de canal só pode ser:

- baseada em “última sessão ativa” (`last_opened_at`), ou
- baseada em `session.context["last_interface"]`. (`src/core/orchestrator.py`)

## 11. Estrutura recomendada para MVP

Estrutura inicial coerente com o repo:

- `src/drivers/interfaces/internal_driver.py`
- `src/services/agent_events/` (normalização e roteamento)
- `src/services/system_sessions/` (gerência de sessões system)
- `src/services/internal_routing/` (regras para escolher `target_session_id` e canal)

Onde colocar o envelope:

- `src/drivers/contracts.py` (aproveitando `UniversalInputFrame`), ou
- `src/core/events.py` (como `InternalEventEnvelope`, alinhado a WorkerEvent)

## 12. Riscos e limitações

- **Semântica de “user session” contaminando system sessions** (auto-message, event bus, history). (`src/main.py`, `src/core/session.py`)
- **Eventos internos virarem prompts soltos** sem contrato de envelope. (`src/drivers/contracts.py`)
- **Driver interno virar “cozinha” de lógica de domínio** se normalização ficar muito inteligente.
- **Acoplamento com entrega ao usuário** (Kernel._send_to_session depende de driver ativo). (`src/main.py`)
- **Loops internos**: system session pode disparar eventos que geram novos eventos sem guardrails.
- **Ambiguidade entre evento interno, worker e input humano** — falta contrato formal. (`src/core/events.py`, `src/main.py`)
- **Acesso/segurança**: interface “system” não tem policy explícita e pode cair em modos restritivos ou permissivos indevidos. (`src/core/access_controller.py`)

## 13. Conclusão objetiva

- **Viável**: `system sessions + internal driver + event envelope` encaixa na arquitetura atual.
- **Melhor que criar pipeline especial no kernel/orchestrator**: reusa infraestrutura madura de sessões, locks, persistência e drivers.
- **MVP mínimo viável**:
  1. Criar internal driver que chama `Kernel.process_input`.
  2. Definir envelope de evento e passá-lo via `user_data`.
  3. Ajustar `process_input` para não registrar histórico/UI quando `internal_event=True`.
  4. Garantir política de acesso adequada para interface “system” (ou bypass explícito controlado).
- **Ajustes mínimos necessários**:
  - Condicional em `Kernel.process_input` para não gravar histórico e não emitir `message_added` quando `internal_event=True`. (`src/main.py`, `src/core/session.py`)
  - Permitir `Session.source="system"` (ou adicionar `session.type`) e filtrar na listagem (o `SessionIndexManager` já dá base para isso). (`src/core/sessions_index.py`)
  - Registrar policy para interface “system” para evitar bloqueios inadvertidos. (`src/core/access_controller.py`)

## Observação de escopo

Não há capability de `calendar` no repositório atual (não foi encontrado `calendar` em `src/capabilities`). Portanto, o exemplo de uso inicial não pode ser validado diretamente em código.
