# Proposta de Arquitetura — External RAG por Capabilities Plugáveis (2026-03-19)

> Historical proposal. This document records a design direction and may differ from the current active implementation.

## 1. Resumo Executivo

Este documento propõe uma refatoração do sistema de RAG externo do Assistant-OS para eliminar dependências de fluxo hardcoded, reduzir acoplamento entre capacidades e criar um modelo de orquestração adaptativa orientado a contrato.

Objetivos principais:

- transformar providers externos em plugins explícitos e configuráveis;
- manter um orquestrador único para pesquisa/retrieval com fallback robusto;
- permitir descoberta automática de capacidades de RAG externo via metadados de contrato;
- usar o RAG interno atual (typed domains + agent_experience) para aprendizado de priorização e qualidade;
- evitar estado "sem dados" com política de degradação controlada.

---

## 2. Diagnóstico do Estado Atual

### 2.1 Pontos fortes existentes

- Arquitetura modular por capabilities já madura (`src/capabilities/*`).
- Registro/dispatch central (`CapabilityRegistry`) com contratos validados e schema.
- Context Broker typed (`services/context/*`) com domínios explícitos, reranking e diagnósticos.
- Suporte a auth em contrato (`auth.mode`, `fields`, `sources`) e UI administrativa para configuração.

### 2.2 Limitações estruturais atuais (RAG externo)

1. **Monolito lógico de pesquisa externa**
- `research.retrieve.run` concentra fluxo de planejamento/seleção/abertura/síntese e depende fortemente de `web.search.discover` como porta de entrada.
- Mesmo com `wikipedia.search` na allowlist, o pipeline atual não usa fallback semântico automático para Wikipedia quando web search retorna vazio.

2. **Semântica de provider implícita no código, não no contrato**
- O contrato atual (`contract_v1`) descreve ação e auth, mas não descreve de forma rica “o que esse plugin fornece para RAG externo” (tipo de dado, cobertura de domínio, frescor, confiabilidade, custo, requisitos de setup).

3. **Fluxo parcialmente hardcoded por ação**
- Integração entre componentes ocorre por IDs de ação específicos (ex.: `web.search.discover`, `web.retrieve.read`, etc.), não por “capacidade declarada” e escopo de retrieval.

4. **Observabilidade de setup ainda insuficiente para UX de pesquisa**
- A UI de capabilities mostra validação/config, mas o usuário final não recebe um "perfil operacional" claro por provider para saber por que a pesquisa está vazia (ex.: `provider sem API key`, `provider desabilitado`, `provider indisponível`).

5. **Capacidades relacionadas, porém dispersas por domínio externo**
- Exemplo explícito: YouTube dividido em `youtube_search` e `youtube_retrieve` (válido tecnicamente), mas sem uma camada declarativa única de "oferta de retrieval" para orquestração cross-provider.

### 2.3 Evidências de operação recente

Pelos logs e execução recente do sistema:

- retorno frequente de `web.search.discover` em estado `empty` por combinação de provider indisponível/desabilitado/misconfigured;
- fallback operacional migra para caminhos de browser em alguns fluxos quando retrieval fica degradado;
- resultado prático: risco de ausência de evidência em tarefas de pesquisa factual.

---

## 3. Diretriz Arquitetural Proposta

### 3.1 Princípio

**“Sem hardcode de fluxo por action id; com hardcode mínimo apenas em segurança/política.”**

- Roteamento de retrieval deve ser **orientado por contrato semântico**.
- Enforcement (ACL, approval, segurança) permanece determinístico em código.

### 3.2 Novo modelo

1. **Orquestrador único de External RAG**
- Capability de topo (bridge): `external.research.run`.
- Funções: planejar providers, executar fallback, deduplicar evidência, sintetizar resposta, retornar telemetria.

2. **Providers plugáveis independentes**
- Cada provider exporta ações próprias (ou uma ação padrão de retrieval) e metadados declarativos.
- Exemplos:
  - `external.provider.web.brave.search`
  - `external.provider.web.searxng.search`
  - `external.provider.encyclopedia.wikipedia.search`
  - `external.provider.academic.openalex.search`
  - `external.provider.media.youtube.search`
  - `external.provider.media.youtube.retrieve`
  - `external.provider.music.deezer.search`
  - `external.provider.music.spotify.search`
  - `external.provider.geo.maps.search`

3. **Índice automático de capacidades de retrieval**
- No boot/reload, o loader gera um catálogo de “ofertas de retrieval” a partir dos contratos.
- O orquestrador consulta esse índice em tempo de execução (sem listas hardcoded de actions).

---

## 4. Evolução de Contrato (Capability Contract v2 para Retrieval)

### 4.1 Lacuna do contrato atual

`contract_v1` é excelente para execução e auth, mas não modela semântica de retrieval externo de forma explícita.

### 4.2 Extensão proposta (nova seção no contrato)

Adicionar um bloco opcional (ex.: `retrieval_profile`) em cada capability que queira participar do ecossistema de External RAG.

Exemplo conceitual:

```json
{
  "retrieval_profile": {
    "enabled": true,
    "roles": ["search", "retrieve", "structured_entity"],
    "domains": ["web", "encyclopedia", "media", "music", "geo", "academic"],
    "entity_types": ["article", "video", "track", "place", "paper"],
    "freshness": {"type": "live", "sla_hours": 24},
    "quality": {
      "default_confidence": 0.72,
      "trust_tier": "curated|community|public_api",
      "citation_mode": "url_required"
    },
    "cost": {
      "latency_class": "low|medium|high",
      "quota_class": "free|metered|strict"
    },
    "setup": {
      "requires_auth": true,
      "required_fields": ["search_router.providers.brave.api_key"],
      "healthcheck_action": "external.provider.web.brave.health"
    },
    "output_contract": {
      "evidence_schema": "external.evidence.v1",
      "entity_schema": "external.entity.v1"
    },
    "routing_hints": {
      "preferred_intents": ["general_knowledge", "capability_lookup"],
      "avoid_when": ["policy_lookup"]
    }
  }
}
```

### 4.3 Benefícios

- Descoberta automática de provider apto por intenção/escopo.
- UI consegue mostrar claramente “setup requerido” vs “pronto para uso”.
- Orquestrador decide por atributos (domínio, qualidade, custo), não por IDs fixos.

---

## 5. Modelo de Orquestração Inteligente (Sem Hardcode de Fluxo)

### 5.1 Pipeline proposto do `external.research.run`

1. Classificar objetivo da pesquisa (intent + subintent).
2. Consultar índice de providers elegíveis por `retrieval_profile` + ACL.
3. Calcular ranking inicial por:
   - disponibilidade/health,
   - setup completeness,
   - domínio compatível,
   - latência/custo,
   - qualidade histórica.
4. Executar plano em camadas (top-k + fallback progressivo).
5. Normalizar resultados em schema comum de evidência.
6. Deduplicar e reranquear por confiança/recência/cobertura.
7. Sintetizar resposta e reportar proveniência explícita.
8. Persistir telemetry outcome para aprendizagem.

### 5.2 Política anti-“sem dados”

Quando um provider falha/vem vazio:

- fallback para provider de mesma classe de domínio;
- fallback cruzado de domínio se permitido (ex.: encyclopedia quando web geral falha);
- fallback para fontes curadas internas (`external_knowledge`/`custom_knowledge`) com marcação de stale/fresh;
- resposta final sempre com estado claro: `partial`, `degraded`, `empty_with_reason`.

---

## 6. Aprendizado Adaptativo com o RAG Interno Atual

### 6.1 Reuso do que já existe

O sistema já possui elementos úteis para aprendizagem robusta:

- `agent_experience` (memória operacional consolidada);
- `ContextDiagnostics` com contagem por domínio e efeitos de ranking;
- telemetria de outcomes em logs/resultados de action;
- `external_knowledge` e `custom_knowledge` typed para suporte documental.

### 6.2 Loop de aprendizado proposto (deterministic-safe)

1. Cada execução de `external.research.run` grava `retrieval_outcome` estruturado:
   - providers tentados;
   - taxa de sucesso;
   - latência;
   - cobertura de evidência;
   - satisfação heurística da resposta.
2. Um consolidator periódico gera “provider scorecards” por intent/domínio.
3. O orquestrador usa scorecards como priorização (weights), sem alterar ACL/política.
4. Mudanças de peso são auditáveis e reversíveis.

### 6.3 O que **não** deve ser “aprendido automaticamente”

- regras de segurança;
- aprovação e escopo de permissão;
- bloqueios de alto risco;
- regras de privacidade/compliance.

---

## 7. Separação de Capabilities (Proposta prática)

### 7.1 Estado alvo por domínio externo

- `external_orchestrator` (novo):
  - ação principal: `external.research.run`
  - opcional: `external.research.plan`, `external.research.health`

- `web_search_providers` (split em plugins):
  - Brave plugin
  - SearXNG plugin
  - DDG plugin
  - etc.

- `encyclopedia_provider`:
  - Wikipedia plugin

- `academic_provider`:
  - OpenAlex plugin

- `media/music/geo providers`:
  - YouTube, Deezer, Spotify, Maps permanecem separados, mas com `retrieval_profile` padronizado.

### 7.2 Sobre duplicidade YouTube

Não é “erro” ter `youtube_search` e `youtube_retrieve`; o problema é a falta de uma camada semântica comum para o orquestrador.

Recomendação:

- manter split funcional (search vs retrieve) por responsabilidade;
- adicionar metadados de oferta de retrieval em ambos;
- deixar o orquestrador selecionar qual chamar conforme objetivo.

---

## 8. Mudanças de Plataforma Necessárias

### 8.1 Capability Contract

- Evoluir `contract_v1` para suportar seção `retrieval_profile` (ou criar `contract_v1.1` backward-compatible).
- Validadores para garantir consistência de schemas de output de evidência.

### 8.2 Loader/Registry

- Loader indexa `retrieval_profile` no registro.
- Registry expõe catálogo semântico (`list_retrieval_offers(intent, domain, entity_type, requires_structured=true)`)

### 8.3 API/UI de Capabilities

Na tela de Capabilities Hub, incluir:

- status de setup por provider (`ready`, `needs_key`, `degraded`, `disabled`);
- healthcheck e último erro operacional;
- botão de “test run” por provider;
- score de confiabilidade recente.

### 8.4 Orquestrador

- Introduzir `ExternalRetrievalPlanner` (service dedicado) com fallback não hardcoded.
- Reaproveitar guardrails atuais de não-interactive research para acionar esse planejador.

---

## 9. Estratégia de Migração (sem quebra)

### Fase 1 — Compatibilidade

- Adicionar `retrieval_profile` opcional em contratos existentes.
- Criar índice semântico no loader/registry.
- Manter actions atuais funcionando sem alteração.

### Fase 2 — Orquestrador novo em paralelo

- Implementar `external.research.run` v2 usando índice semântico.
- Executar shadow mode (comparar decisões com pipeline atual, sem trocar produção).

### Fase 3 — Cutover gradual

- Direcionar intents de pesquisa para o novo orquestrador.
- Reduzir hardcodes em `research.retrieve` antigo.
- Transformar o antigo em adapter/legacy facade.

### Fase 4 — Consolidação e limpeza

- Deprecar fluxos duplicados hardcoded.
- Padronizar contratos de output estruturado.
- Fechar lacunas de observabilidade/setup no Hub.

---

## 10. Modelo de Dados Comum para Evidência Externa

Definir schemas comuns (versão inicial):

- `external.evidence.v1`
  - `source_id`, `provider_id`, `domain`, `url`, `title`, `snippet`, `content_ref`, `confidence`, `freshness`, `license`, `retrieved_at`

- `external.entity.v1`
  - `entity_type` (`video`, `track`, `place`, `article`, `paper`),
  - `canonical_id`, `name`, `attributes`, `links`, `metrics`, `provenance`

Com isso, qualquer capability externa pode plugar sem custom mapping ad hoc no planner.

---

## 11. Riscos e Mitigações

1. **Risco: complexidade inicial da refatoração**
- Mitigação: migração por fases + compatibilidade de contrato.

2. **Risco: regressão de roteamento**
- Mitigação: shadow mode com métricas de equivalência.

3. **Risco: aprendizado gerar oscilação**
- Mitigação: learning bounded (weights com limites e rollback).

4. **Risco: UX confusa de configuração**
- Mitigação: status de setup/health por provider no Hub.

---

## 12. Critérios de Sucesso

- Redução de respostas `empty` em pesquisa externa.
- Aumento de cobertura de evidência por consulta.
- Queda de fallback para browser em consultas não interativas.
- Tempo de recuperação em falha de provider menor (fallback efetivo).
- Setup de provider compreensível no Hub (sem necessidade de conhecimento interno do código).

---

## 13. Conclusão

A base atual é sólida para evoluir: já existe modularidade, contrato, broker typed e telemetria. O principal gap é semântico (contrato ainda não expressa “capacidade de retrieval externo” em nível suficiente para orquestração dinâmica). 

A proposta deste documento resolve esse gap com:

- `retrieval_profile` declarativo por capability;
- índice automático de ofertas de retrieval;
- orquestrador único orientado a contrato (não a action hardcoded);
- aprendizado adaptativo com segurança determinística preservada.

Isso permite escalar para YouTube/Deezer/Spotify/Wikipedia/Maps e novos providers com baixo acoplamento, maior robustez e menor risco operacional de ficar “sem dados”.

## Relacionados

- [../architecture/README.md](../architecture/README.md): contexto arquitetural onde a proposta se encaixa.
- [prompt-reduction-pass5-report.md](prompt-reduction-pass5-report.md): redução dinâmica de prompt que conversa com a camada de evidencias.
- [../../agent/specs/unified-context-rag-architecture.spec.md](../../agent/specs/unified-context-rag-architecture.spec.md): contrato normativo já ativo para RAG unificado.
- [../../agent/specs/external_rag_refinements.spec.md](../../agent/specs/external_rag_refinements.spec.md): refinamentos incrementais do desenho externo de RAG.
- [../../agent/specs/external_rag_final_design_closures.spec.md](../../agent/specs/external_rag_final_design_closures.spec.md): fechamento final do desenho externo de RAG.
