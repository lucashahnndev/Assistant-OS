# MCP + Playwright Agent Platform Architecture Spec

Status: arquitetura conceitual final para plataforma de agentes e subagentes em producao continua.
Escopo: plataforma distribuida, multi-tenant, governavel, auditavel e com evolucao segura de policy.

---

## 1) Objetivo Final da Plataforma

A plataforma deve ser:
- robusta na execucao distribuida;
- governavel por policy explicita e evolutiva;
- segura para multiplos tenants;
- previsivel em QoS, risco e custo;
- explicavel para operadores humanos;
- preparada para simulacao, canary, rollout e rollback sem ambiguidade.

---

## 2) Baseline Mantido

Mantido do desenho anterior:
- scheduler global com fairness;
- distributed lock com fencing;
- isolamento por sessao + failure budget;
- page intelligence + cold start;
- adaptive budgeting;
- backpressure global;
- execution control, including cancel, deadline and preemption;
- checkpoint and recovery;
- safe mode;
- replay deterministico;
- QoS, multi-tenant governance, planner guardrails, policy layer, risk model e delegation contracts.

---

## 3) Modelo de Simulacao de Policy (Obrigatorio)

### 3.1 `PolicySimulationMode`

Objetivo:
- avaliar decisoes de policy sem executar efeito real.

Modos:
- `single_policy_eval`: avalia uma policy version para um evento.
- `diff_eval`: compara `policy_version_current` vs `policy_version_candidate`.
- `historical_replay_eval`: roda candidate sobre eventos historicos.

### 3.2 Entradas obrigatorias

`PolicySimulationInput`:
- `tenant_id`
- `agent_id`
- `delegation_id` (opcional)
- `action_proposed`
- `page_type`
- `domain`
- `risk_level`
- `qos_class`
- `execution_context_envelope`
- `policy_version_current`
- `policy_version_candidate`

Fonte de eventos:
- checkpoints + replay events + receipts historicos.

### 3.3 Saida estruturada

`PolicySimulationResult`:
- `decision_current` (`allow|deny|require_approval|allow_with_constraints`)
- `decision_candidate`
- `decision_changed` (bool)
- `constraint_delta`
- `risk_delta`
- `impact_score`
- `explanation` (`DecisionExplanation`)
- agregados por dimensao: tenant, domain, risk_level, page_type.

### 3.4 Uso operacional

- obrigatorio antes de promover policy para `canary`.
- bloqueia promocao se regressao acima do limite definido.

---

## 4) Modelo de Camadas de Policy (Obrigatorio)

### 4.1 Separacao formal

`SecurityPolicyLayer`:
- controles de seguranca, irreversibilidade, dominios bloqueados, acoes criticas, compliance.

`BusinessPolicyLayer`:
- regras de negocio por tenant, jornada, QoS e otimizacao operacional.

### 4.2 Ordem de avaliacao

Pipeline obrigatorio:
1. `SecurityPolicyLayer`
2. `BusinessPolicyLayer`
3. `PolicyMerger`

### 4.3 Precedencia e conflito

Regras:
- `deny` de Security sempre vence.
- Business nao pode enfraquecer restricao Security.
- Business so pode:
  - manter decisao;
  - adicionar restricao;
  - elevar para `require_approval`.

### 4.4 Resultado consolidado

`PolicyDecisionEnvelope`:
- `security_decision`
- `business_decision`
- `final_decision`
- `conflict_detected`
- `conflict_resolution_rule`
- `constraints_final`

---

## 5) Modelo de Explicabilidade (Obrigatorio)

### 5.1 `DecisionExplanation` estruturado

Formato obrigatorio:
- `decision_id`
- `timestamp`
- `action_proposed`
- `context_summary` (`tenant`, `page_type`, `domain`, `qos`, `delegation`)
- `policy_rules_evaluated[]`
- `risk_level_calculated`
- `decision_final`
- `decision_reason_codes[]`
- `constraints_applied[]`
- `human_message`

### 5.2 Quando e obrigatorio

Obrigatorio para:
- `deny`
- `require_approval`
- `allow_with_constraints`
- entrada em `safe_mode`
- `SYSTEM_OVERLOADED`
- `PLANNER_GUARDRAIL_TRIGGERED`

### 5.3 Impacto em logging e performance

- `STANDARD`: explanation resumida + reason codes.
- `DEBUG`: inclui regras avaliadas detalhadas.
- `FORENSIC`: inclui arvore de decisao completa, com amostragem.

---

## 6) Modelo Sandbox (Obrigatorio)

### 6.1 `TenantSandboxMode`

Sandbox e ambiente de execucao controlada por tenant, nao mock simplista.

Campos no envelope:
- `environment_mode: production|sandbox`
- `sandbox_profile_id`

### 6.2 Comportamento no sandbox

- acoes mutaveis sao simuladas ou contidas conforme policy.
- efeitos irreversiveis sempre bloqueados ou virtualizados.
- latencia, rate limit, QoS e policy continuam aplicados para realismo operacional.

### 6.3 Receipts, checkpoints e replay em sandbox

- receipts completos com `environment_mode=sandbox`.
- checkpoints persistidos em namespace isolado por tenant sandbox.
- replay integral suportado no mesmo formato da producao.

### 6.4 Isolamento garantido

- isolamento de dados, locks, budgets e filas por namespace sandbox.
- sem efeitos laterais em producao.

---

## 7) Modelo de Rollout de Policy (Obrigatorio)

### 7.1 Lifecycle de policy

Estados:
- `draft`
- `simulated`
- `canary`
- `active`
- `deprecated`
- `rolled_back`

### 7.2 Estrategias de rollout

- por tenant especifico
- por percentual de trafego
- por classe de risco (`low->medium->high`)
- por QoS class (`LOW/NORMAL` antes de `HIGH/CRITICAL`)

### 7.3 Canary e metricas de regressao

Metricas de controle:
- aumento de `deny_rate` inesperado
- aumento de `require_approval_rate`
- aumento de falha operacional por decisao
- impacto em latencia e custo por tenant

### 7.4 Abort automatico e rollback rapido

Critérios automaticos:
- regressao acima do limiar configurado em janela curta.

Acao:
- transicao imediata para `rolled_back`
- retorno para ultima `active` estavel
- emissao de incidente + `DecisionExplanation` agregada.

---

## 8) Modelo de Governanca Unificado

### 8.1 `ExecutionContextEnvelope` canonico

Campos minimos:
- `tenant_id`
- `agent_id`
- `delegation_id`
- `session_scope`
- `qos_class`
- `risk_level`
- `execution_control`
- `budget_state`
- `policy_context`
