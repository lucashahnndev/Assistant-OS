# External RAG Final Design Closures

Status: fechamento final dos pontos em aberto da arquitetura de External RAG.
Escopo: contratos, fluxo operacional e responsabilidades para implementação/refatoração segura.

---

## Resumo Executivo

### Buracos restantes identificados

1. faltava um objeto central auditável de execução (`retrieval_plan`);
2. decomposição de query composta estava implícita e sem contrato formal de steps/dependências;
3. merge de evidência ainda dependia de heurística não explicitada por intent;
4. budgets operacionais sem modelo formal único;
5. cold start sem estratégia explícita de seleção/adaptação;
6. fronteira planner vs runtime parcialmente implícita;
7. observabilidade fim a fim sem modelo de trace padronizado.

### Como este fechamento resolve

- define `retrieval_plan` como contrato operacional canônico;
- formaliza `plan_steps` com dependências e modos de execução (parallel/sequence/conditional);
- define `evidence_merge_strategy` por intent e contratos de `evidence_item`, `merged_result`, `merge_decision_trace`;
- formaliza budgets e suas regras de aplicação no plano;
- define cold start com pesos default, exploração controlada e anti-fixação prematura;
- separa responsabilidades entre classifier, planner, builder, selector, runtime, merge e fallback;
- padroniza `plan_trace`, `execution_trace`, `merge_trace` para debug/UI/auditoria.

### Resultado

A arquitetura fica suficientemente fechada para implementação incremental sem decisões improvisadas de meio de caminho.

---

## 1) Contrato formal de `retrieval_plan`

## 1.1 Papel

`retrieval_plan` é o objeto central de execução do External RAG.
Ele encapsula decisão de planejamento, estratégia de execução, merge e fallback sob orçamento.

## 1.2 Contrato lógico (v1)

```json
{
  "plan_version": "1.0",
  "query_id": "uuid",
  "created_at": "iso8601",
  "intent": "general_knowledge|entity_lookup|latest_update|structured_fact|media_lookup|music_lookup|location_lookup|academic_lookup",
  "subintent": "optional_string",
  "constraints": {
    "freshness_required": "none|soft|hard",
    "structure_required": "none|soft|hard",
    "citation_required": true,
    "language": "pt-BR",
    "geo_scope": "global|city|nearby",
    "cost_sensitivity": "low|medium|high"
  },
  "selected_providers": [
    {
      "provider_id": "string",
      "domain": "string",
      "roles": ["search"],
      "selection_score": 0.0,
      "selection_reason": "primary|fallback_ready"
    }
  ],
  "plan_steps": [
    {
      "step_id": "s1",
      "query": "string",
      "intent": "...",
      "subintent": "...",
      "mode": "parallel|sequential|conditional",
      "depends_on": [],
      "candidate_providers": ["provider_a", "provider_b"],
      "step_budgets": {
        "latency_budget_ms": 2000,
        "max_providers": 2,
        "max_retries": 1
      },
      "output_contract": "external.evidence.v1"
    }
  ],
  "merge_strategy": {
    "strategy_id": "by_intent_v1",
    "policy": "consensus|recency_priority|trust_priority|composite"
  },
  "fallback_chain": {
    "intra_domain": true,
    "cross_domain": true,
    "internal_knowledge": true,
    "max_fallback_depth": 3
  },
  "budgets": {
    "latency_budget_ms": 7000,
    "cost_budget": {"class": "low", "hard_limit": 1.0},
    "max_providers": 4,
    "max_parallelism": 2,
    "max_retries": 2
  },
  "explanation_trace": {
    "plan_reasons": [],
    "provider_decisions": []
  }
}
```

## 1.3 Produção, consumo e ciclo de vida

- Quem produz: `RetrievalPlanBuilder` (com input de classifier + planner + selector).
- Quem consome:
  - `ExecutionRuntime` (execução de steps);
  - `MergeEngine` (aplica estratégia);
  - `FallbackManager` (replanejamento local dentro dos limites).
- Geração: incremental em 2 fases:
  1. skeleton plan (intent/constraints/budgets globais);
  2. enrichment plan (steps/providers/merge/fallback).
- Persistência:
  - persistir plano final e traces mínimos por `query_id` (auditoria);
  - plano completo com detalhes sensíveis opcionalmente com TTL curto.

---

## 2) Arquitetura de Query Decomposition

## 2.1 Quando decompor

Decompor query quando houver:
- múltiplos objetivos explícitos (conectores: “e”, “além disso”, “também”);
- mistura de intents incompatíveis num único passo (ex.: `structured_fact` + `media_lookup`);
- dependência natural entre resultados (ex.: encontrar entidade antes de buscar atualização);
- necessidade de contratos de saída diferentes por parte da pergunta.

Não decompor quando:
- um único intent resolve com qualidade suficiente;
- decomposição aumentaria custo/latência sem ganho de evidência.

## 2.2 Representação dos steps

`plan_step`:
- `step_id`
- `query_fragment`
- `intent/subintent`
- `constraints_override` (opcional)
- `mode`: `parallel|sequential|conditional`
- `depends_on[]`
- `success_criteria`
- `step_budgets`
- `candidate_providers[]`

## 2.3 Relações entre steps

- Paralelo: steps independentes sem dependência de output.
- Sequencial: step N depende de entidade/resultado do step N-1.
- Condicional: step executa apenas se condição de cobertura/confiança não for satisfeita.

## 2.4 Controle de complexidade

- `max_steps` global (default 3, hard 5)
- decompor apenas se ganho estimado > threshold
- pruning de steps redundantes por similaridade semântica
- abortar expansão de plano ao atingir budget ou baixa utilidade marginal

---

## 3) Arquitetura de Evidence Merge

## 3.1 Contrato de `evidence_item`

```json
{
  "evidence_id": "string",
  "provider_id": "string",
  "domain": "web|media|music|geo|encyclopedia|academic",
  "intent": "...",
  "entity_type": "optional",
  "title": "string",
  "url": "string",
  "snippet": "string",
  "payload": {},
  "retrieved_at": "iso8601",
  "freshness_score": 0.0,
  "trust_score": 0.0,
  "provider_confidence": 0.0,
  "provenance": {
    "source_type": "api|crawl|index|internal",
    "citation_required": true
  }
}
```

## 3.2 Contrato de `merged_result`

```json
{
  "query_id": "uuid",
  "status": "full|partial|degraded|empty_with_reason",
  "answer_mode": "consensus|divergence|uncertain",
  "primary_claims": [],
  "supporting_evidence_ids": [],
  "citations": [],
  "conflicts": [],
  "uncertainties": [],
  "coverage": {"required_met": true, "missing_aspects": []}
}
```

## 3.3 Contrato de `merge_decision_trace`

```json
{
  "strategy": "by_intent_v1",
  "rules_applied": [],
  "conflict_resolution": [],
  "discarded_evidence": [
    {"evidence_id": "...", "reason": "stale|low_trust|duplicate|off_scope"}
  ]
}
```

## 3.4 Estratégia por intent

- `structured_fact`:
  - prioridade: estrutura + trust + consistência;
  - conflito => divergência explícita, nunca “média cega”.
- `latest_update`:
  - prioridade: recência validada + citação;
  - fonte antiga pode compor contexto, não claim principal.
- `general_knowledge`:
  - composição multi-fonte com consenso semântico;
  - conflito leve => incerteza declarada.
- `entity_lookup`:
  - priorizar canonicalização (id/nome/url canônica);
  - campos divergentes vão para seção de divergência.

## 3.5 Regras de arbitragem de conflito

Ordem padrão:
1. validade estrutural
2. elegibilidade de citação
3. trust tier efetivo (base + runtime)
4. recência (se relevante ao intent)
5. cobertura de constraints

Saída final:
- `consensus`: quando conflito residual baixo;
- `divergence`: quando conflito relevante permanece;
- `uncertain`: quando evidência insuficiente para afirmação forte.

---

## 4) Modelo de Execution Budgets

## 4.1 Contrato

```json
{
  "latency_budget_ms": 7000,
  "cost_budget": {"class": "low|medium|high", "hard_limit": 1.0},
  "max_providers": 4,
  "max_fallback_depth": 3,
  "max_parallelism": 2,
  "max_retries": 2
}
```

## 4.2 Onde entra no plano

- `budgets` globais no `retrieval_plan`;
- `step_budgets` opcionais por `plan_step`.

## 4.3 Efeito operacional

- seleção inicial limita candidatos ao orçamento de custo/latência;
- decomposição reduzida quando `max_steps` implícito por budget é baixo;
- fallback encerra ao atingir `max_fallback_depth` ou orçamento global;
- merge recebe janela de evidência resultante do budget (não requisita novos fetches fora do limite).

## 4.4 Perfis de budget

- padrão global: perfil equilibrado;
- por intent:
  - `latest_update`: maior latência tolerada, maior exigência de recência;
  - `structured_fact`: mais rigor estrutural, menor tolerância a fonte fraca;
  - `media/music`: plano estreito e rápido.
- por contexto:
  - sessão interativa: menor latência;
  - job assíncrono: maior budget.
- por sensibilidade de custo:
  - `high`: restringe providers pagos e paralelismo.

---

## 5) Estratégia de Cold Start

## 5.1 Seleção inicial sem histórico

Usar apenas:
- `intent_match`
- `trust_tier` base
- `setup_readiness`
- `routing_hints`
- compatibilidade de domínio/entidade

## 5.2 Pesos default

- preset estável por intent (não dependente de histórico)
- histórico inicia com peso mínimo e cresce por amostragem suficiente

## 5.3 Exploração controlada

- epsilon-greedy limitado por budget (ex.: 10-15% das decisões elegíveis)
- exploração só entre providers `ready` e policy-compliant

## 5.4 Anti-vies e anti-fixação prematura

- exigir mínimo de N execuções antes de promover priorização forte
- cap de contribuição histórica
- janelas temporais com decaimento
- fallback para default quando sinal inconsistente

---

## 6) Relação entre Planner e Runtime (responsabilidades)

## 6.1 Componentes e responsabilidades

- `Intent Classifier`:
  - decide `intent/subintent/constraints` iniciais.
- `Planner`:
  - decide necessidade de decomposição e objetivo dos steps.
- `RetrievalPlan Builder`:
  - materializa `retrieval_plan` completo e validado.
- `Provider Selector`:
  - ranqueia e escolhe candidatos por step.
- `Execution Runtime`:
  - executa steps conforme plano e budgets.
- `Merge Engine`:
  - aplica `merge_strategy` e gera `merged_result`.
- `Fallback Manager`:
  - adapta execução em falha sem quebrar guardrails.

## 6.2 Quem pode replanejar

- replanejamento estrutural (adicionar/remover steps): somente `Planner + Plan Builder`.
- adaptação tática (trocar provider dentro do step): `Fallback Manager`.

## 6.3 Plano fechado vs mutável

- fechado após validação do `retrieval_plan`.
- mutável apenas em campos runtime permitidos:
  - `selected_provider` por step (dentro do conjunto elegível);
  - transição de fallback;
  - atualização de status/trace.
- mutação estrutural exige “replan event” explícito auditado.

---

## 7) Observabilidade e auditabilidade

## 7.1 `plan_trace`

Registra decisão de planejamento:
- classificação intent/subintent;
- motivo de decomposição (ou não);
- providers elegíveis e ranking inicial;
- budgets aplicados;
- rationale do merge/fallback planejado.

## 7.2 `execution_trace`

Registra execução real:
- ordem de steps;
- provider efetivamente usado por step;
- retries/timeouts/errors;
- consumo de budget;
- acionamento de fallback + reason.

## 7.3 `merge_trace`

Registra reconciliação:
- estratégia aplicada por intent;
- conflitos detectados;
- evidências descartadas e motivo;
- decisão final (`consensus|divergence|uncertain`).

## 7.4 Política de logging/persistência

Logar sempre (runtime):
- ids, reason codes, status, budget usage.

Mostrar em UI técnica:
- `routing_explanation` resumido + cadeia de fallback + status final.

Persistir para auditoria:
- `retrieval_plan` (snapshot), `execution_trace`, `merge_trace`, `merged_result` (com retenção por política).

---

## 8) Critérios de prontidão para implementação

Arquitetura considerada pronta quando:

1. `retrieval_plan` v1 estiver validado como contrato canônico;
2. decomposition, merge e fallback estiverem ligados a reason codes e traces padronizados;
3. budgets por intent/contexto estiverem definidos com defaults operacionais;
4. cold start policy e limites de aprendizado estiverem ativados por configuração;
5. fronteira planner/runtime estiver implementada com replan events auditáveis.

Com esses fechamentos, a fase de implementação pode iniciar com baixa ambiguidade arquitetural.
