# MCP + Playwright Agent Platform Architecture (Final) (2026-03-19)

Status: arquitetura conceitual final para plataforma de agentes/subagentes em produção contínua.
Escopo: plataforma distribuída, multi-tenant, governável, auditável e com evolução segura de policy.

---

## 1) Objetivo Final da Plataforma

A plataforma deve ser:
- robusta na execução distribuída;
- governável por policy explícita e evolutiva;
- segura para múltiplos tenants;
- previsível em QoS, risco e custo;
- explicável para operadores humanos;
- preparada para simulação, canary, rollout e rollback sem ambiguidade.

---

## 2) Baseline Mantido

Mantido do desenho anterior:
- scheduler global com fairness;
- distributed lock com fencing;
- isolamento por sessão + failure budget;
- page intelligence + cold start;
- adaptive budgeting;
- backpressure global;
- execution control (cancel/deadline/preemption);
- checkpoint/recovery;
- safe mode;
- replay determinístico;
- QoS, multi-tenant governance, planner guardrails, policy layer, risk model e delegation contracts.

---

## 3) Modelo de Simulação de Policy (Obrigatório)

## 3.1 `PolicySimulationMode`

Objetivo:
- avaliar decisões de policy sem executar efeito real.

Modos:
- `single_policy_eval`: avalia uma policy version para um evento.
- `diff_eval`: compara `policy_version_current` vs `policy_version_candidate`.
- `historical_replay_eval`: roda candidate sobre eventos históricos.

## 3.2 Entradas obrigatórias

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
- checkpoints + replay events + receipts históricos.

## 3.3 Saída estruturada

`PolicySimulationResult`:
- `decision_current` (`allow|deny|require_approval|allow_with_constraints`)
- `decision_candidate`
- `decision_changed` (bool)
- `constraint_delta`
- `risk_delta`
- `impact_score`
- `explanation` (DecisionExplanation)
- agregados por dimensão: tenant, domain, risk_level, page_type.

## 3.4 Uso operacional

- obrigatório antes de promover policy para `canary`.
- bloqueia promoção se regressão acima do limite definido.

---

## 4) Modelo de Camadas de Policy (Obrigatório)

## 4.1 Separação formal

`SecurityPolicyLayer`:
- controles de segurança, irreversibilidade, domínios bloqueados, ações críticas, compliance.

`BusinessPolicyLayer`:
- regras de negócio por tenant, jornada, QoS e otimização operacional.

## 4.2 Ordem de avaliação

Pipeline obrigatório:
1. `SecurityPolicyLayer`
2. `BusinessPolicyLayer`
3. `PolicyMerger`

## 4.3 Precedência e conflito

Regras:
- `deny` de Security sempre vence.
- Business não pode enfraquecer restrição Security.
- Business só pode:
  - manter decisão;
  - adicionar restrição;
  - elevar para `require_approval`.

## 4.4 Resultado consolidado

`PolicyDecisionEnvelope`:
- `security_decision`
- `business_decision`
- `final_decision`
- `conflict_detected`
- `conflict_resolution_rule`
- `constraints_final`

---

## 5) Modelo de Explicabilidade (Obrigatório)

## 5.1 `DecisionExplanation` estruturado

Formato obrigatório (não texto solto):
- `decision_id`
- `timestamp`
- `action_proposed`
- `context_summary` (tenant, page_type, domain, qos, delegation)
- `policy_rules_evaluated[]`
- `risk_level_calculated`
- `decision_final`
- `decision_reason_codes[]`
- `constraints_applied[]`
- `human_message`

## 5.2 Quando é obrigatório

Obrigatório para:
- `deny`
- `require_approval`
- `allow_with_constraints`
- entrada em `safe_mode`
- `SYSTEM_OVERLOADED`
- `PLANNER_GUARDRAIL_TRIGGERED`

## 5.3 Impacto em logging/performance

- `STANDARD`: explanation resumida + reason codes.
- `DEBUG`: inclui regras avaliadas detalhadas.
- `FORENSIC`: inclui árvore de decisão completa (amostrado).

---

## 6) Modelo Sandbox (Obrigatório)

## 6.1 `TenantSandboxMode`

Sandbox é ambiente de execução controlada por tenant, não mock simplista.

Campos no envelope:
- `environment_mode: production|sandbox`
- `sandbox_profile_id`

## 6.2 Comportamento no sandbox

- ações mutáveis são simuladas/contidas conforme policy.
- efeitos irreversíveis sempre bloqueados ou virtualizados.
- latência, rate limit, QoS e policy continuam aplicados para realismo operacional.

## 6.3 Receipts/checkpoints/replay em sandbox

- receipts completos com `environment_mode=sandbox`.
- checkpoints persistidos em namespace isolado por tenant sandbox.
- replay integral suportado no mesmo formato da produção.

## 6.4 Isolamento garantido

- isolamento de dados, locks, budgets e filas por namespace sandbox.
- sem efeitos laterais em produção.

---

## 7) Modelo de Rollout de Policy (Obrigatório)

## 7.1 Lifecycle de policy

Estados:
- `draft`
- `simulated`
- `canary`
- `active`
- `deprecated`
- `rolled_back`

## 7.2 Estratégias de rollout

- por tenant específico
- por percentual de tráfego
- por classe de risco (`low->medium->high`)
- por QoS class (`LOW/NORMAL` antes de `HIGH/CRITICAL`)

## 7.3 Canary e métricas de regressão

Métricas de controle:
- aumento de `deny_rate` inesperado
- aumento de `require_approval_rate`
- aumento de falha operacional por decisão
- impacto em latência/custo por tenant

## 7.4 Abort automático e rollback rápido

Critérios automáticos:
- regressão acima do limiar configurado em janela curta.

Ação:
- transição imediata para `rolled_back`
- retorno para última `active` estável
- emissão de incidente + `DecisionExplanation` agregada.

---

## 8) Modelo de Governança Unificado

## 8.1 `ExecutionContextEnvelope` canônico

Campos mínimos:
- `tenant_id`
- `agent_id`
- `delegation_id`
- `session_scope`
- `qos_class`
- `risk_level`
- `execution_control`
- `budget_state`
- `policy_context`
- `environment_mode`
- `runtime_version`
- `planner_version`
- `policy_version`

Esse envelope percorre planner -> policy -> runtime -> adapter -> receipt.

## 8.2 Delegation contract preservado

Subagente só executa com:
- objetivo delegado explícito
- escopo permitido
- budget herdado
- policy herdada
- critérios de cancelamento/sucesso

---

## 9) Operabilidade e Auditoria

## 9.1 Observabilidade obrigatória adicional

- `policy_simulation_runs_total`
- `policy_canary_abort_total`
- `policy_rollback_total`
- `sandbox_execution_total`
- `security_vs_business_conflict_total`
- `decision_explanation_generated_total`

## 9.2 SLOs de governança

- 100% das decisões críticas com `DecisionExplanation`.
- 100% das mudanças de policy passando por `simulated` antes de `canary`.
- 100% dos rollbacks executáveis em tempo objetivo definido.

---

## 10) Roadmap Final de Implementação

Fase A - Policy governance core:
- `SecurityPolicyLayer`, `BusinessPolicyLayer`, merge e precedência.

Fase B - Simulation e explanation:
- `PolicySimulationMode` + `DecisionExplanation` estruturada.

Fase C - Sandbox multi-tenant:
- `TenantSandboxMode` com namespace isolado e observabilidade equivalente.

Fase D - Rollout/rollback engine:
- lifecycle completo, canary progressivo e abort automático.

Fase E - Hardening operacional:
- dashboards e playbooks para policy, risco, tenant, QoS e sandbox.

---

## 11) Decisões Finais

1. Policy simulation é etapa obrigatória, não opcional.
2. Security policy tem precedência absoluta sobre business policy.
3. Explicabilidade é estruturada (`DecisionExplanation`), não narrativa livre.
4. Sandbox por tenant é execução controlada realista, não mock.
5. Rollout de policy é progressivo, observável e reversível rapidamente.
6. A plataforma mantém compatibilidade externa com `browser.control.*`.

---

## 12) Entregável

Documento arquitetural final consolidado para base de implementação e operação contínua:
- `docs/architecture/mcp_service_and_playwright_architecture_proposal_2026-03-19.md`

