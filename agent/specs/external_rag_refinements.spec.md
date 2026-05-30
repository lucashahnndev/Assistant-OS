# External RAG Refinements Spec

Status: complemento tecnico da proposta aprovada de External RAG.
Escopo: formalizar limites de modelo, taxonomia semantica, controle operacional e regras de fallback e explicabilidade.

---

## 1) Separacao formal: contract vs profile vs runtime

### 1.1 Capability Contract (estatico, versionado)

Responsavel por descrever a capability como produto de execucao.

Inclui:
- `capability.id`, `namespace`, `version`, `actions`
- `auth` (modo, campos, fontes)
- `permissions` and `risk_level` per action
- schemas de input and output por action

Nao inclui:
- metricas operacionais em tempo real
- score dinamico de provider
- estado de degradacao transitoria

Versionamento:
- versionado por release de contrato (`contract_version` + `capability.version`)
- mudanca de schema ou semantica implica bump controlado de versao

### 1.2 Retrieval Profile (semantico, versionado)

Responsavel por descrever o que este provider oferece para o ecossistema de retrieval.

Inclui somente semantica e capacidade:
- `roles`: search / retrieve / structured_entity / metadata_only
- `domains`: web, encyclopedia, media, music, geo, academic
- `entity_types`: article, video, track, place, paper, and similar entities
- `freshness_class`: live | near_live | batch | archival
- `evidence_contract_ref` and `entity_contract_ref`
- `setup_requirements_ref` as reference, not runtime state
- `routing_hints` estaveis, such as prefer or avoid by intent
- `trust_tier` base, declarative

Nao inclui:
- `success_rate` atual
- `latency` observada recente
- `quota remaining`
- `degraded_now`

Versionamento:
- versionado junto ao contrato da capability or through `retrieval_profile.version`
- alteracao de semantica implica nova versao

### 1.3 Provider Runtime Scorecard (dinamico, nao versionado por release)

Responsavel por comportamento operacional e adaptacao.

Inclui:
- health atual (`healthy`, `degraded`, `unavailable`)
- readiness de setup efetivo (`ready`, `missing_auth`, `misconfigured`)
- metricas moveis: `success_rate_window`, `p95_latency`, `error_rate`, `timeout_rate`
- estado de quota ou rate limit
- penalidades temporarias, such as cooldown
- overrides do control plane

Atualizacao:
- atualizada em tempo real e por janelas, via EWMA or sliding windows
- persistencia curta ou media, via runtime store and optional historico

### 1.4 Regra anti-super objeto

Separacao obrigatoria:
- `capability_contract`: execucao e seguranca
- `retrieval_profile`: semantica de oferta
- `provider_runtime_scorecard`: operacao e aprendizagem

Qualquer campo dinamico no `retrieval_profile` e invalido por design.

---

## 2) Taxonomia minima de intents

### 2.1 Estrutura de classificacao

Entrada de planner para retrieval:
- `intent` (classe principal)
- `subintent` (especializacao opcional)
- `constraints` (restricoes da consulta)

Modelo conceitual:
- `intent`: `general_knowledge | entity_lookup | latest_update | structured_fact | media_lookup | music_lookup | location_lookup | academic_lookup`
- `subintent`: livre controlado por index semantico, such as `video_stats`, `artist_profile`, `place_details`
- `constraints`:
  - `freshness_required` (`none`, `soft`, `hard`)
  - `structure_required` (`none`, `soft`, `hard`)
  - `citation_required` (`bool`)
  - `media_type` (`video`, `audio`, `text`, `place`)
  - `geo_scope` (`global`, `city`, `nearby`)
  - `language`
  - `cost_sensitivity` (`low`, `medium`, `high`)

### 2.2 Mapeamento intent -> providers

Regras base:
- `general_knowledge`: web + encyclopedia
- `entity_lookup`: provider por tipo de entidade, such as media, music, geo or encyclopedia
- `latest_update`: prioriza providers live ou near_live
- `structured_fact`: prioriza providers com `structured_entity`
- `media_lookup`: youtube + web fallback
- `music_lookup`: deezer or spotify + youtube fallback
- `location_lookup`: maps primario + web local fallback
- `academic_lookup`: openalex primario + web academico fallback

### 2.3 Impacto em fallback e largura de plano

- intents com baixa ambiguidade, such as `music_lookup` and `location_lookup`, usam plano estreito, com 1 a 2 providers iniciais
- intents amplas, such as `general_knowledge` and `latest_update`, usam plano mais largo, com 2 a 4 providers
- `structured_fact` exige pelo menos 1 provider que entregue estrutura confiavel antes de sintetizar o final

---

## 3) Provider Control Plane / Runtime Override

### 3.1 Modelo

Adicionar um plano de controle operacional separado do contrato:
- `ProviderControlPlane` (config + estado operacional)

Capacidades:
- `disable_provider` (temporario ou permanente)
- `set_degraded`
- `set_priority_bias` (penalizar or bonificar)
- `set_quota_guard` (limites por janela)
- `force_fallback_chain` (ordem forcada por incidente)
- `cooldown_on_error`

### 3.2 Onde vive

- fonte primaria: store operacional persistido em `data/` com TTL para overrides temporarios
- fonte secundaria: configuracao administrativa, for persistent overrides
- cache runtime em memoria para decisao rapida

### 3.3 Aplicacao no planner

Ordem de aplicacao:
1. ACL or policy gates
2. Control plane hard overrides
3. scoring normal
4. fallback policy

### 3.4 Relacao com trust_tier

- `trust_tier` e base declarativa, from contract or profile
- override runtime pode suplantar temporariamente prioridade operacional
- override nunca altera `trust_tier` de origem, only the effective runtime score

---

## 4) Modelo de explicabilidade de roteamento

### 4.1 Estrutura `routing_explanation`

Para cada provider considerado:
- `provider_id`
- `used` (`bool`)
- `reason_code`:
  - `intent_mismatch`
  - `requires_setup`
  - `disabled`
  - `quota_exceeded`
  - `lower_score`
  - `error_previous`
  - `selected_primary`
  - `selected_fallback`
- `score_total`
- `score_breakdown` (opcional por fator)
- `runtime_flags` (degraded, cooldown, quota)

Resumo final da decisao:
- `providers_used` (ordem de execucao)
- `providers_discarded` + motivo
- `fallback_steps_taken`
- `final_status` (`full`, `partial`, `degraded`, `empty_with_reason`)

### 4.2 Uso

- debug interno
- auditoria operacional
- exposicao em UI tecnica, com nivel de detalhe por perfil de usuario

---

## 5) Modelo de scoring e priorizacao

### 5.1 Funcao de score (conceitual)

`score(provider) = w1*intent_match + w2*setup_ready + w3*runtime_health + w4*trust_base + w5*success_rate + w6*latency_score + w7*cost_score + w8*context_fit + w9*historical_performance + w10*override_bias`

### 5.2 Fatores obrigatorios

- `intent_match`
- `setup_ready`
- `runtime_health`
- `trust_base`

Sem esses fatores, o provider nao entra em selecao primaria.

### 5.3 Fatores opcionais

- `success_rate`
- `latency_score`
- `cost_score`
- `context_fit` (idioma or local)
- `historical_performance`

### 5.4 Guardrails anti-domínio excessivo do historico

- teto para contribuicao historica, such as max 20-25% do score
- decaimento temporal, with recency emphasis
- smoothing via EWMA para reduzir oscilacao
- exploracao minima controlada para nao fixar eternamente o mesmo provider
- rollback de pesos por incidente

### 5.5 Anti-overfitting operacional

- separar metricas por intent and domain to avoid noise transfer
- exigir minimo de amostras para aplicar ajuste aprendido
- fallback para pesos default quando o sinal for fraco

---

## 6) Estrategia de fallback (regras formais)

### 6.1 Tipos de fallback

1. `intra_domain`: troca para outro provider do mesmo dominio and role
2. `cross_domain`: troca para dominio semanticamente compativel
3. `internal_knowledge`: usar `external_knowledge`, `custom_knowledge` or procedures como suporte
4. `final_degraded_response`: resposta com limitacao explicita

### 6.2 Regras de parada

Parar tentativas quando qualquer condicao ocorrer:
- budget de latencia excedido
- budget de custo ou quota excedido
- numero maximo de providers tentados atingido
- cobertura minima de evidencia ja atendida
- cadeia de fallback sem novos candidatos elegiveis

### 6.3 Status de saida

- `full`: evidencia suficiente e consistente
- `partial`: parte dos requisitos atendida, such as sem frescor hard
- `degraded`: resposta suportada por fallback inferior ou indireto
- `empty_with_reason`: nenhuma evidencia utilizavel mais motivo explicito

### 6.4 Regras anti-loop

- nao repetir provider no mesmo ciclo apos erro equivalente
- cooldown curto por erro repetitivo
- limite de tentativas por reason class (`timeout`, `auth`, `quota`, `empty`)
