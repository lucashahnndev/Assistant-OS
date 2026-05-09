# Proposta de Arquitetura — Conversational Core + Tool Discovery Semântico (2026-03-22)

## 1. Objetivo

Esta proposta reorganiza o fluxo de raciocínio do Assistant-OS para separar claramente:

- o núcleo conversacional do agente;
- a descoberta semântica de tools/capabilities;
- a execução de actions canônicas;
- a normalização de peculiaridades por provider.

A meta é reduzir alucinação de `action id`, eliminar dependência de catálogo compacto no prompt principal e tornar o comportamento do agente mais previsível em provedores locais e remotos.

## 2. Diagnóstico do Estado Atual

### 2.1 Fluxo atual em alto nível

Hoje o fluxo principal funciona mais ou menos assim:

1. O `Kernel` recebe a mensagem.
2. O `AgentOrchestrator` monta estado, memória, broker e prompt.
3. O `ContextBroker` classifica o turno e recupera evidência.
4. O `PromptComposer` monta um prompt grande com estado, persona, evidence e um bloco de ações compactado.
5. O `LLMResolver` chama o provider.
6. O provider local OpenAI gera um `AgentIntent` estruturado.
7. O `CapabilityRegistry` e o `intent_repair` validam/canonizam a `action`.
8. Se a `action` estiver fora do catálogo, o sistema corrige, degrada ou falha.

### 2.2 Onde o sistema ainda está conflitando

Os problemas observados nos logs e no código são consistentes:

- o prompt ainda expõe um bloco `[ACTIONS]` com catálogo compacto;
- o modelo tenta escolher `action` diretamente, mesmo quando a fala é apenas conversacional;
- o provider local devolve aliases plausíveis, mas não canônicos, como `weather.fetch_current_conditions` e `weather.get_current_conditions`;
- o parser também já viu saída malformada, como `response_text):`;
- o resolver precisa recuperar comportamento conversacional com regras extras;
- a persona já é injetada, mas está no mesmo fluxo de prompt que mistura conversa e execução;
- a descoberta de capabilities ainda não é um estágio explícito e semântico do fluxo.

### 2.3 Evidências recentes

Os arquivos de violação mostram o padrão:

- `data/logs/contracts/openai_violations.jsonl` registrou `action not in catalog` para `principal-filtered`, `weather.fetch_current_conditions` e `weather.get_current_conditions`;
- o resumo em `data/logs/contracts/openai_violations_summary.json` mostra múltiplas violações no contrato `agent_intent_v1`;
- o contrato canônico do clima está em `src/capabilities/weather_control/contract.json`, com `weather.control.get` como action válida.

## 3. Princípio Arquitetural

### 3.1 Regra central

O modelo não deve escolher tools específicas no primeiro passo.

Ele deve escolher entre:

- conversar;
- lembrar;
- anexar/formatar;
- consultar tools;
- pedir clarificação;
- ou, em último caso, executar uma action já descoberta e validada.

### 3.2 Consequência prática

O prompt principal deve carregar apenas o necessário para:

- conversa;
- memória;
- anexos;
- persona;
- políticas de resposta;
- descoberta de tools.

O catálogo de execução específica não deve ser despejado no prompt principal.

## 4. Arquitetura Alvo

### 4.1 Camada 1: Núcleo Conversacional

Responsável por:

- responder mensagens simples;
- preservar persona;
- manter memória curta da conversa;
- decidir quando consultar tools;
- produzir `reply` sem tool quando o turno é claramente conversacional.

Conteúdo permitido no prompt dessa camada:

- `reply`;
- memória/estado relevante;
- anexos;
- políticas de conversa;
- instrução explícita para consultar tools quando necessário.

Conteúdo que não deve ficar no prompt principal:

- catálogo expandido de actions de domínio;
- lista inteira de capabilities;
- ids específicos de execução que o usuário final não pediu.

### 4.2 Camada 2: Tool Discovery Semântico

Nova etapa lógica entre intenção e execução.

Quando o agente perceber que precisa agir fora do núcleo conversacional, ele chama uma ação de descoberta, por exemplo:

- `tools.discover`;
- `consult_tools`;
- `capabilities.search`;
- ou outro nome canônico definido pelo sistema.

Essa ação não executa a capability final.
Ela retorna um subconjunto curto e relevante de tools candidatas.

### 4.3 Camada 3: Execução Canônica

Depois da descoberta, o modelo escolhe uma action específica entre as candidatas retornadas.

Nesse ponto:

- o `CapabilityRegistry` continua sendo a fonte canônica;
- a action precisa ser exata;
- aliases podem ser normalizados, mas devem ser auditáveis;
- execução fora do escopo descoberto deve ser rejeitada ou reencaminhada.

### 4.4 Camada 4: Normalização por Provider

Cada provider precisa lidar com suas peculiaridades:

- respostas com aliases naturais;
- respostas com campos malformados;
- modelos que devolvem `thought` sem `response_text`;
- modelos que tentam inventar `action` plausível, mas não canônica.

Essa camada deve:

- normalizar aliases;
- preencher fallback de `response_text` quando apropriado;
- registrar mapeamentos e reparos;
- nunca mascarar silenciosamente uma violação estrutural grave.

## 5. Contrato Proposto

### 5.1 Contrato de intenção

O contrato principal de intenção deve ser enxuto:

- `thought`;
- `action`;
- `params`;
- `response_text`;
- `attachments`;
- `state_summary`;
- `plan` quando necessário.

### 5.2 Regras de ação

- `reply` sempre é permitido.
- `consult_tools` é permitido como ação de descoberta.
- actions específicas de domínio não entram no prompt principal como catálogo aberto.
- actions específicas só são liberadas após discovery.
- `action` fora do catálogo canônico deve ser normalizada ou rejeitada com diagnóstico claro.

### 5.3 Contrato de descoberta

Sugestão de shape para a action de descoberta:

```json
{
  "action": "consult_tools",
  "params": {
    "query": "clima atual",
    "intent": "task_execution",
    "domain_hints": ["weather"],
    "top_k": 5
  }
}
```

Resposta esperada:

```json
{
  "candidates": [
    {
      "action_id": "weather.control.get",
      "capability_id": "weather_control",
      "title": "Get current weather",
      "summary": "Fetch current weather conditions",
      "setup_ready": true,
      "reason": "Best semantic match for current weather"
    }
  ],
  "selected_domain": "weather",
  "confidence": 0.91
}
```

## 6. Estrutura de Dados Reutilizável

O sistema já tem uma base boa para essa mudança:

- `CapabilityRegistry.list_actions()` como catálogo canônico;
- `CapabilityRegistry.resolve_action_id()` como normalizador;
- `CapabilityRegistry.list_retrieval_offers()` como índice declarativo de ofertas;
- `ContextBroker` como classificador e roteador de evidência;
- `PromptComposer` como montador do contrato de prompt;
- `LLMResolver` como guardrail entre intenção e execução.

Isso significa que a mudança não exige reinventar o core. Ela exige reorganizar responsabilidades.

## 7. Fluxo Alvo

### 7.1 Turno conversacional

1. Usuário envia algo simples, como “qual o seu nome?”.
2. O broker classifica como conversacional.
3. O prompt contém apenas contexto conversacional e persona.
4. O modelo devolve `reply`.
5. O executor responde sem tool.

### 7.2 Turno de ação

1. Usuário pede algo como “como está o clima?”.
2. O broker identifica necessidade de execução.
3. O modelo primeiro emite `consult_tools`.
4. O índice semântico retorna candidatos relevantes.
5. O modelo escolhe a action canônica, por exemplo `weather.control.get`.
6. O executor valida e roda a capability.
7. O resultado volta ao usuário com estado claro.

### 7.3 Turno com alias do provider

1. O provider local devolve algo como `weather.get_current_conditions`.
2. O normalizador mapeia para `weather.control.get`.
3. O sistema registra o alias usado.
4. A execução continua sem quebrar, mas o log preserva o reparo.

## 8. Ajustes Necessários no Sistema

### 8.1 `PromptComposer`

O `PromptComposer` ainda monta um bloco `[ACTIONS]` compacto no prompt principal.

Trechos relevantes:

- persona já entra em bloco próprio em `src/services/llm/prompt_composer.py:190`;
- o bloco `[ACTIONS]` ainda é montado em `src/services/llm/prompt_composer.py:384`;
- a política de execução está em `src/services/llm/prompt_composer.py:517`;
- o contrato estruturado está em `src/services/llm/prompt_composer.py:579`.

Direção proposta:

- remover catálogo de execução específico do prompt principal;
- substituir por instrução de descoberta;
- manter somente ações conversacionais e `consult_tools`.

### 8.2 `LLMResolver`

O resolver já aplica algumas proteções:

- força `reply` em turnos claramente conversacionais;
- injeta `allowed_actions` e `capability_registry` no provider;
- calcula confiança baseada no contexto.

Mas ele ainda assume que o provider já tentou escolher uma action específica.

Direção proposta:

- tratar `consult_tools` como primeira classe;
- transformar turnos ambíguos em discovery antes de execução;
- reduzir o espaço de decisões diretas fora do núcleo conversacional.

### 8.3 `CapabilityRegistry`

O registry já é forte como fonte canônica.

Ele deve virar a base do índice semântico de descoberta:

- actions canônicas;
- ofertas de retrieval;
- readiness/setup;
- rotas preferenciais;
- metadados para ranking.

### 8.4 Provider local OpenAI

O driver local precisa continuar tolerante com quirks do modelo:

- fallback de `reply`;
- canonicalização de aliases;
- repair de schema;
- logging de mapeamentos;
- rejeição clara quando a saída não puder ser recuperada.

## 9. Fases de Migração

### Fase 0 — Estabilização

Objetivo:

- manter o sistema funcionando enquanto reduz erros de contrato.

Ações:

- preservar normalização de aliases;
- manter fallback de `reply`;
- manter guardrails de conversação;
- continuar coletando violações em `openai_violations.jsonl`.

### Fase 1 — Separação do prompt

Objetivo:

- remover o catálogo de execução do prompt principal.

Ações:

- deixar o prompt com conversa, memória, anexos, persona e policy;
- colocar a descoberta de tools como instrução explícita;
- reduzir o bloco `[ACTIONS]` para um conjunto conversacional mínimo.

### Fase 2 — Discovery semântico

Objetivo:

- transformar discovery em etapa real do fluxo.

Ações:

- introduzir `consult_tools`;
- usar `CapabilityRegistry.list_retrieval_offers()` e/ou índice semântico;
- retornar candidatas curtas e canônicas;
- permitir ranking por intenção, domínio e readiness.

### Fase 3 — Execução fechada

Objetivo:

- impedir que o modelo pule discovery quando a tarefa for de tool.

Ações:

- executar somente actions descobertas;
- bloquear ou redirecionar ids fora do conjunto retornado;
- manter aliases apenas como fallback auditável.

### Fase 4 — Observabilidade e aprendizado

Objetivo:

- aprender com violações, baixa confiança e reparos.

Ações:

- consolidar scorecards por provider;
- registrar taxa de alias canonicalizado;
- medir tempo até discovery;
- medir taxas de `reply` correto em conversa.

## 10. Invariantes

Estas regras devem permanecer verdadeiras:

- turnos conversacionais simples não podem exigir tool;
- persona só pode afetar `response_text`;
- ids canônicos continuam sendo fonte de verdade;
- discovery não executa a action final;
- provider quirks não podem sobrescrever a semântica do contrato;
- toda normalização de alias deve ser auditável;
- toda falha estrutural deve aparecer em log/telemetria.

## 11. Riscos e Mitigações

### Risco 1: overblocking

Se o gate de discovery ficar rígido demais, o agente pode travar em casos simples.

Mitigação:

- manter `reply` sempre permitido;
- permitir fallback seguro para clarificação;
- usar confidence thresholds conservadores.

### Risco 2: discovery demasiado verboso

Se o catálogo retornado por discovery for grande, o problema volta.

Mitigação:

- top-k baixo;
- ranking por domínio/intenção;
- retorno resumido e canônico.

### Risco 3: alias drift entre providers

Modelos locais e remotos podem continuar inventando nomes próximos.

Mitigação:

- normalização central;
- logs de alias;
- testes de regressão por provider.

### Risco 4: mistura de responsabilidade

Se discovery, execução e conversa voltarem a se misturar no prompt, o ganho se perde.

Mitigação:

- contrato mínimo no prompt;
- separação explícita em camadas;
- revisão de regressões por diff de prompt.

## 12. Critérios de Aceitação

A arquitetura proposta estará madura quando:

- `oi` ou `qual o seu nome?` resultarem em `reply` sem tool;
- `como está o clima?` passar por discovery antes de execução;
- `weather.get_current_conditions` for sempre canonizado para `weather.control.get`;
- o prompt principal não precisar carregar catálogo expandido de tools;
- a taxa de violações em `openai_violations.jsonl` cair de forma consistente;
- o provider local e o remote provider seguirem o mesmo contrato de descoberta/execução.

## 13. Conclusão

O sistema já tem as peças certas:

- `CapabilityRegistry` como base canônica;
- `ContextBroker` como roteador de evidência;
- `PromptComposer` como controlador do contrato de prompt;
- `LLMResolver` como guardrail;
- driver local com repair e normalização.

O próximo passo arquitetural não é adicionar mais catálogo ao prompt.
É inverter a lógica:

1. conversa primeiro;
2. discovery semântico quando necessário;
3. execução canônica só depois;
4. normalização por provider como suporte, não como essência.

Esse desenho tende a reduzir os erros que apareceram nos logs e a deixar o agente mais inteligente de forma observável, não só “mais esperto no texto”.
