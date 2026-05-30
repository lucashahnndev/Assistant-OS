# Agent Heuristics Status

Data: 2026-05-28

## Objetivo deste arquivo

Este documento acompanha o estado de aderencia do Atlas ao `agent/specs/agent-heuristics.spec.md`.

Ele existe para registrar:

- o que ja parece alinhado ao spec
- onde ainda ha risco de hardcode cognitivo
- quais areas merecem correcao ou refinamento

## Estado atual

O sistema ja possui uma base boa para autonomia agentica:

- contratos e guardrails existem em camadas separadas
- `ContextBroker` trabalha com hints, nao com ordem absoluta
- `PromptComposer` e interfaces adaptam saida por contexto
- `MCP` foi integrado como superficie externa governada
- validacao de acesso e plan validator estao fail-closed

Ao mesmo tempo, ainda ha pontos que merecem vigilancia para evitar rigidez excessiva:

- heuristicas muito especificas podem virar regra de dominio se crescerem demais
- telemetria pode ser interpretada como decisao final quando e apenas sinal
- alguns caminhos de recovery e normalizacao precisam permanecer neutros
- adaptacoes por interface precisam ficar na borda, nao no nucleo cognitivo
- a fronteira entre heuristica e decisao semantica ficou melhor formalizada com a nova spec de fronteira

Recentemente, parte desse risco foi reduzida em camadas que ainda carregavam muito roteamento por cenarios:

- `src/core/resolution/llm_resolver.py` passou a tratar a inferencia de Obsidian como tabela declarativa de intentos, deixando o especial-casing mais explicito e menos procedural
- `src/core/resolution/llm_resolver.py` passou a usar tabela de ajustes de confiança mais declarativa
- `src/core/resolution/llm_resolver.py` passou a concentrar o scoring de candidatos Obsidian em helpers pequenos, reduzindo ifs embutidos no fluxo de canonicalizacao
- `src/services/context/retrieval_router.py` passou a usar mapeamento unificado para ativacao, prioridade e notas
- `src/services/context/reranker.py` ganhou tabelas mais explicitas para boosts por intencao, hint e caps de dominio
- `src/services/context/broker.py` passou a concentrar regras de tuning de evidencia em tabelas declarativas, reduzindo supressao procedural dispersa
- `src/services/context/broker.py` passou a aplicar regras de tuning por dispatch declarativo, reduzindo a sequencia procedural de tratamento por regra
- `src/services/context/retrieval_router.py` passou a resolver relevancia de consulta e hints com helpers mais uniformes, reduzindo repeticao de marcadores e ramificacoes por tipo de sinal
- `src/services/context/ingestion/agent_experience_ingestor.py` reduziu a dispersao de heuristicas em varios blocos condicionais, centralizando regras de recovery, inferencia e tags
- `src/services/cognition/reconciler.py` e `src/services/cognition/outcomes.py` passaram a reconhecer melhor sinais de conclusao/progresso, sem colapsar tudo em recuperacao ou pessimismo
- `src/core/orchestrator.py` passou a classificar `completed` e `done` como sucesso real no classificador de saida
- `src/core/orchestrator.py` passou a separar a politica de midia/recovery em helpers mais declarativos, reduzindo o bloco procedural de roteamento por cenario
- `src/services/llm/prompt_composer.py` teve instrucoes antropomorficas e imperativas suavizadas e reestruturadas como listas declarativas de regras, mantendo contrato sem impor rigidez desnecessaria
- `src/services/context/intent_classifier.py` passou a expor uma classificacao de compatibilidade com `legacy_intent`, `hints` e `candidate_intents`, reduzindo a aparencia de autoridade semantica final
- `src/services/context/retrieval_router.py` passou a expor um envelope de sinais com `targets`, pesos, candidatos e justificativas, reduzindo a aparencia de rota semantica final
- `src/capabilities/assistive_overlay/capability.py`, `src/capabilities/browser_control/browser_control_capability.py` e `src/capabilities/notifications/capability.py` removeram shortcuts de linguagem natural em reflex, mantendo apenas fluxos operacionais e eventos tecnicos
- `src/core/orchestrator.py` removeu os overrides semanticos de browser/media que trocavam action por heuristica textual, preservando apenas assistive hints, validacao tecnica e reparo de `youtube.retrieve.get`
- `atlas_operating_model.spec.md` passou a formalizar, de forma curta, quando heuristicas devem orientar e quando o agente deve agir em vez de clarificar por fuga

Essas areas agora estao menos proximas de um "if por caso" e mais proximas de regras observaveis e revisaveis.

## Areas com boa aderencia ao spec

- `src/services/context/broker.py`
- `src/services/llm/prompt_composer.py`
- `src/core/access_controller.py`
- `src/core/plan_validator.py`
- `src/services/mcp/runtime.py`
- `src/services/mcp/policy.py`
- `src/services/mcp/bridge.py`
- `src/core/resolution/llm_resolver.py`
- `src/services/context/retrieval_router.py`
- `src/services/context/reranker.py`
- `src/services/context/ingestion/agent_experience_ingestor.py`
- `src/services/cognition/reconciler.py`
- `src/services/cognition/outcomes.py`

Essas areas ja seguem em boa medida a separacao entre:

- contrato
- heuristica
- adaptacao
- observabilidade

## Areas com risco de rigidez excessiva

Estas areas merecem revisao cuidadosa para garantir que o sistema nao passe a decidir por padroes fixos demais:

- `src/core/orchestrator.py`

Nota: `src/core/resolution/llm_resolver.py` ainda e um ponto de atencao porque continua tendo inferencia especial para Obsidian/MCP, mas agora essa logica esta mais declarativa e menos dispersa.

Motivos principais:

- podem concentrar heuristicas de roteamento
- podem induzir comportamento por excecao
- podem transformar sinais em regras duras sem intencao explicita

## Principio de correcao

Quando uma area estiver muito rigida, a correcao preferida deve ser:

1. mover a decisao para contrato ou policy declarativa
2. reduzir a logica hardcoded
3. transformar regra cognitiva em hint ou configuracao
4. manter o agente livre para decidir dentro do envelope

## Proxima direcao recomendada

A melhor proxima etapa e uma auditoria orientada pelo spec para separar:

- invariantes que precisam permanecer duros
- heuristicas que devem continuar apenas sugerindo
- regras que estao excessivamente especificas e podem ser relaxadas

Os primeiros pontos para revisar sao:

- roteamento de contexto
- priorizacao de evidencia
- recuperacao de fallback
- adaptacao por interface
- normalizacao de resposta de tools e providers
- consolidacao da fronteira semantica agora explicitada em `semantic_decision_boundary.spec.md`
- alinhamento do comportamento do agente ao contrato operacional descrito em `atlas_operating_model.spec.md`

## Conclusao

O Atlas ja esta mais perto de um sistema agentico de verdade do que de um chatbot com roteamento rigido.

O foco agora deve ser preservar essa direcao:

- arquitetura firme
- heuristica leve
- autonomia real do agente
- minimo acoplamento cognitivo no sistema

## Registros de commits recentes

- `e14536a7` `feat: make recovery and final answers operationally honest`
  - resumo: endureceu o fluxo de recovery e sanitizacao para evitar claims de execucao/conclusao sem `ActionObservation` fresca, mantendo fallback honesto quando a resposta e apenas orientacao textual;
  - validacao: `python3 -m py_compile src/core/orchestrator.py tests/minimal/test_mcp_llm_alias_and_recovery.py` e `PYTHONPATH=src:. env/bin/python -m pytest tests/minimal/test_mcp_llm_alias_and_recovery.py -q -k 'recovery_reply_without_tool_data or sanitize_user_facing_response_requires_sent_confirmation_for_attachment_claims or sanitize_user_facing_response_blocks_attachment_claim_without_payload or sanitize_user_facing_response_blocks_execution_claim_without_fresh_evidence or sanitize_user_facing_response_allows_grounded_execution_and_attachment_claims_when_evidence_exists'`;
  - falhas conhecidas fora do escopo: tres testes antigos de alias/Obsidian em `tests/minimal/test_mcp_llm_alias_and_recovery.py` continuam preexistentes e nao bloqueiam este bloco.
