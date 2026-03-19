# External RAG Refinements

Status: complemento técnico da proposta aprovada de External RAG.
Escopo: formalizar limites de modelo, taxonomia semântica, controle operacional e regras de fallback/explicabilidade.

---

## 1) Separação formal: contract vs profile vs runtime

### 1.1 Capability Contract (estático, versionado)

Responsável por descrever a capability como produto de execução.

Inclui:
- `capability.id`, `namespace`, `version`, `actions`
- `auth` (modo, campos, fontes)
- `permissions`/`risk_level` por action
- schemas de input/output por action

Não inclui:
- métricas operacionais em tempo real
- score dinâmico de provider
- estado de degradação transitória

Versionamento:
- versionado por release de contrato (`contract_version` + `capability.version`)
- mudança de schema/semântica => bump controlado de versão

### 1.2 Retrieval Profile (semântico, versionado)

Responsável por descrever “o que este provider oferece para o ecossistema de retrieval”.

Inclui (somente semântica/capacidade):
- `roles`: search / retrieve / structured_entity / metadata_only
- `domains`: web, encyclopedia, media, music, geo, academic
- `entity_types`: article, video, track, place, paper etc.
- `freshness_class`: live | near_live | batch | archival
- `evidence_contract_ref` e `entity_contract_ref`
- `setup_requirements_ref` (referência, não estado runtime)
- `routing_hints` estáveis (prefer/avoid por intent)
- `trust_tier` base (declarativo)

Não inclui:
- `success_rate` atual
- `latency` observada recente
- `quota remaining`
- `degraded_now`

Versionamento:
- versionado junto ao contrato da capability (ou `retrieval_profile.version` próprio)
- alteração de semântica => versão nova

### 1.3 Provider Runtime Scorecard (dinâmico, não versionado por release)

Responsável por comportamento operacional e adaptação.

Inclui:
- health atual (`healthy`, `degraded`, `unavailable`)
- readiness de setup efetivo (`ready`, `missing_auth`, `misconfigured`)
- métricas móveis: `success_rate_window`, `p95_latency`, `error_rate`, `timeout_rate`
- estado de quota/rate limit
- penalidades temporárias (cooldown)
- overrides do control plane

Atualização:
- atualizado em tempo real e por janelas (EWMA/sliding windows)
- persistência curta/média (runtime store + opcional histórico)

### 1.4 Regra anti-“super objeto”

Separação obrigatória:
- `capability_contract`: execução e segurança
- `retrieval_profile`: semântica de oferta
- `provider_runtime_scorecard`: operação e aprendizagem

Qualquer campo dinâmico no `retrieval_profile` é inválido por design.

---

## 2) Taxonomia mínima de intents

## 2.1 Estrutura de classificação

Entrada de planner para retrieval:
- `intent` (classe principal)
- `subintent` (especialização opcional)
- `constraints` (restrições da consulta)

Modelo conceitual:
- `intent`: `general_knowledge | entity_lookup | latest_update | structured_fact | media_lookup | music_lookup | location_lookup | academic_lookup`
- `subintent`: livre controlado por catálogo (ex.: `video_stats`, `artist_profile`, `place_details`)
- `constraints`:
  - `freshness_required` (none/soft/hard)
  - `structure_required` (none/soft/hard)
  - `citation_required` (bool)
  - `media_type` (video/audio/text/place)
  - `geo_scope` (global/city/nearby)
  - `language`
  - `cost_sensitivity` (low/medium/high)

## 2.2 Mapeamento intent -> providers

Regras base:
- `general_knowledge`: web + encyclopedia
- `entity_lookup`: provider por tipo de entidade (media/music/geo/encyclopedia)
- `latest_update`: prioriza providers live/near_live
- `structured_fact`: prioriza providers com `structured_entity`
- `media_lookup`: youtube + web fallback
- `music_lookup`: deezer/spotify + youtube fallback
- `location_lookup`: maps primário + web local fallback
- `academic_lookup`: openalex primário + web acadêmico fallback

## 2.3 Impacto em fallback e largura de plano

- intents com baixa ambiguidade (`music_lookup`, `location_lookup`) usam plano estreito (1-2 providers iniciais)
- intents amplas (`general_knowledge`, `latest_update`) usam plano mais largo (2-4 providers)
- `structured_fact` exige pelo menos 1 provider que entregue estrutura confiável antes de sintetizar final

---

## 3) Provider Control Plane / Runtime Override

## 3.1 Modelo

Adicionar um plano de controle operacional separado do contrato:
- `ProviderControlPlane` (config + estado operacional)

Capacidades:
- `disable_provider` (temporário/permanente)
- `set_degraded`
- `set_priority_bias` (penalizar/bonificar)
- `set_quota_guard` (limites por janela)
- `force_fallback_chain` (ordem forçada por incidente)
- `cooldown_on_error`

## 3.2 Onde vive

- fonte primária: store operacional (persistido em `data/` com TTL para overrides temporários)
- fonte secundária: configuração administrativa (overrides persistentes)
- cache runtime em memória para decisão rápida

## 3.3 Aplicação no planner

Ordem de aplicação:
1. ACL/policy gates
2. Control plane hard overrides
3. scoring normal
4. fallback policy

## 3.4 Relação com trust_tier

- `trust_tier` é base declarativa (contrato/perfil)
- override runtime pode suplantar temporariamente prioridade operacional
- override nunca altera `trust_tier` de origem, apenas o score efetivo no runtime

---

## 4) Modelo de explicabilidade de roteamento

## 4.1 Estrutura `routing_explanation`

Para cada provider considerado:
- `provider_id`
- `used` (bool)
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

Resumo final da decisão:
- `providers_used` (ordem de execução)
- `providers_discarded` + motivo
- `fallback_steps_taken`
- `final_status` (`full`, `partial`, `degraded`, `empty_with_reason`)

## 4.2 Uso

- Debug interno
- Auditoria operacional
- Exposição em UI técnica (com nível de detalhe por perfil de usuário)

---

## 5) Modelo de scoring e priorização

## 5.1 Função de score (conceitual)

`score(provider) = w1*intent_match + w2*setup_ready + w3*runtime_health + w4*trust_base + w5*success_rate + w6*latency_score + w7*cost_score + w8*context_fit + w9*historical_performance + w10*override_bias`

## 5.2 Fatores obrigatórios

- `intent_match`
- `setup_ready`
- `runtime_health`
- `trust_base`

Sem esses fatores, provider não entra em seleção primária.

## 5.3 Fatores opcionais

- `success_rate`
- `latency_score`
- `cost_score`
- `context_fit` (idioma/local)
- `historical_performance`

## 5.4 Guardrails anti-domínio excessivo do histórico

- teto para contribuição histórica (ex.: max 20-25% do score)
- decaimento temporal (recência)
- smoothing (EWMA) para reduzir oscilação
- exploração mínima controlada (não fixar eternamente o mesmo provider)
- rollback de pesos por incidente

## 5.5 Anti-overfitting operacional

- separar métricas por intent/domínio (evita transferir ruído entre contextos)
- exigir mínimo de amostras para aplicar ajuste aprendido
- fallback para pesos default quando sinal fraco

---

## 6) Estratégia de fallback (regras formais)

## 6.1 Tipos de fallback

1. `intra_domain`: troca para outro provider do mesmo domínio e role
2. `cross_domain`: troca para domínio semanticamente compatível
3. `internal_knowledge`: usar `external_knowledge`/`custom_knowledge`/procedures como suporte
4. `final_degraded_response`: resposta com limitação explícita

## 6.2 Regras de parada

Parar tentativas quando qualquer condição ocorrer:
- budget de latência excedido
- budget de custo/quota excedido
- número máximo de providers tentados atingido
- cobertura mínima de evidência já atendida
- cadeia de fallback sem novos candidatos elegíveis

## 6.3 Status de saída

- `full`: evidência suficiente e consistente
- `partial`: parte dos requisitos atendida (ex.: sem frescor hard)
- `degraded`: resposta suportada por fallback inferior/indireto
- `empty_with_reason`: nenhuma evidência utilizável + motivo explícito

## 6.4 Regras anti-loop

- não repetir provider no mesmo ciclo após erro equivalente
- cooldown curto por erro repetitivo
- limite de tentativas por reason class (`timeout`, `auth`, `quota`, `empty`)

---

## 7) Limites do aprendizado

## 7.1 O sistema PODE aprender

- priorização de providers por intent/domínio
- ajuste fino de ranking
- seleção condicional por contexto (idioma, região, tipo de consulta)
- thresholds operacionais de fallback com limites predefinidos

## 7.2 O sistema NÃO pode aprender

- ACL e escopo de permissão
- `risk_level`
- `requires_approval`
- políticas de segurança e compliance
- decisões de bloqueio normativo

## 7.3 Garantia de design

Enforcement em camadas obrigatórias:
1. Policy/ACL gate (imutável por aprendizado)
2. Plan validator de segurança (imutável)
3. Retrieval planner adaptativo (aprendizado permitido apenas aqui)

Qualquer saída do planner adaptativo passa novamente por validação determinística antes da execução.

---

## 8) Resultado esperado com estes refinements

Com os refinements acima, o External RAG fica:
- previsível (taxonomia + fallback formal + score controlado)
- explicável (routing_explanation)
- controlável em runtime (control plane separado do contrato)
- escalável (plugins por domínio/provider sem fluxo hardcoded por action)
- robusto (anti-loop + anti-overfitting + degradação explícita)
