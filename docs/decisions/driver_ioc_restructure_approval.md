# Aprovação Técnica: Reestruturação de Drivers e Contratos (IoC)

## Status
- **Aprovado** para implementação.
- Este documento define a orientação oficial para a IA durante a refatoração.

## Objetivo
Corrigir o fluxo arquitetural removendo normalizações e reparos de sintaxe do Kernel/Core, mantendo no Core apenas orquestração, roteamento e política de fallback.

## Decisão Arquitetural Aprovada
1. O Kernel **deve manter consciência** de:
- canal/interface atual da sessão;
- identidade da sessão ativa (session_id, sender_id, interface);
- capacidades do canal (`driver_capabilities`);
- lista/pool de providers e política de fallback.

2. O Kernel **não deve executar**:
- parsing/sanitização/reparo de JSON de LLM;
- normalização de entrada/saída específica de canal;
- heurísticas específicas de provider (workarounds por modelo).

3. Drivers de Interface e Providers são responsáveis pelo “trabalho sujo” de adaptação nas bordas.

4. Consciência de interface é requisito de cognição:
- o agente deve saber se está em interação por voz ou texto;
- essa consciência orienta estilo de resposta, ritmo conversacional e memória contextual;
- isso **não** autoriza normalização de payload no Core.

## Estrutura de Paths Aprovada
```text
src/
  core/
    orchestrator.py
    resolution/
    policy/
  drivers/
    interfaces/
      telegram/
      voice/
      web/
      whatsapp/
    providers/
      openai/
      gemini/
      openrouter/
      ollama/
      huggingface/
```

## Responsabilidade por Camada
1. **Interface Driver**
- converte input nativo em frame canônico;
- publica capabilities;
- informa interface e contexto de sessão ao Kernel;
- não decide regra de negócio global.

2. **Provider Driver**
- chama API do modelo;
- garante contrato de saída (`AgentIntent`) válido;
- executa parse/repair interno quando necessário;
- lança erro contratual padronizado quando não conseguir cumprir o contrato.

3. **Kernel/Core**
- seleciona provider por política;
- aplica fallback de provider;
- transforma `AgentIntent` em `ActionPlan`;
- coordena execução e estado da sessão.

## Contratos Obrigatórios (Aprovados)
1. **Contrato de Intent**
- saída final para o Core: `AgentIntent` consistente (`action`, `params`, `thought`, `response_text`, `plan`, `state_summary`).

2. **Contrato de Erro de Provider**
- erro padronizado para fallback (`ProviderContractError` ou equivalente);
- diferenciar erro recuperável (troca provider) de erro fatal (interrompe fluxo).

3. **Contrato de Capability de Interface**
- schema estável para `driver_capabilities`;
- o Core usa capability, nunca nome hardcoded de canal para normalização.

4. **Contrato de Contexto de Interface**
- `interface` deve ser explícita no contexto de turno/sessão;
- `session_id` e `sender_id` devem ser preservados para continuidade cognitiva;
- o Core pode usar interface para estratégia cognitiva (voz vs texto), não para parsing.

5. **Contrato de Anexos em Interação por Voz**
- interface de voz pode transportar anexos no fluxo de dados;
- restrição de voz é de saída TTS (não verbalizar caminhos técnicos de arquivo);
- anexos permanecem disponíveis para raciocínio e ações técnicas quando aplicável.

## Ajustes de Fluxo Aprovados
1. Remover inferência de interface por prefixo de `session_id` dentro do Orchestrator.
2. Passar interface/capabilities de forma explícita desde o ponto de entrada do Kernel.
3. Centralizar validação e reparo de resposta LLM nos drivers de provider.
4. Eliminar parsing duplicado em skill/planner quando depender de saída de provider.

## Política de Fallback (Aprovada)
1. Fallback é decisão de Core/Manager, não da skill.
2. Provider só deve retornar “intent degradado” em casos bem definidos; no restante, deve lançar erro contratual para permitir fallback real.
3. Registrar telemetria por provider: latência, parse_fail, fallback_count, sucesso final.

## Proposta Simples de Logs (Aprovada)
1. Estrutura de arquivos:
- `logs/llm/router.log`
- `logs/llm/providers/openai.log`
- `logs/llm/providers/gemini.log`
- `logs/llm/providers/openrouter.log`
- `logs/llm/providers/ollama.log`
- `logs/llm/providers/huggingface.log`

2. Formato padrão:
- JSONL (um evento por linha).
- Campos mínimos: `ts`, `level`, `event`, `request_id`, `session_id`, `provider`, `model`, `latency_ms`, `fallback_triggered`, `error_code`.

3. Eventos mínimos:
- `intent_request_start`
- `intent_response_received`
- `intent_parse_result`
- `intent_repair_attempt`
- `intent_contract_error`
- `provider_fallback`
- `intent_success`

4. Rotação e retenção:
- rotação por tamanho (ex.: 10MB) ou diária;
- retenção sugerida: 7 dias para INFO, 30 dias para WARN/ERROR;
- compressão dos arquivos antigos.

5. Regras operacionais:
- parser/repair apenas no provider;
- `router.log` registra decisão de fallback e motivo;
- Core registra resultado contratual, não heurística de parsing.

## Critérios de Aceitação (Definition of Done)
1. Core sem lógica de reparo/parse de JSON de LLM.
2. Orchestrator sem hardcode de nomes de canal para inferência operacional.
3. Providers aderindo ao mesmo contrato de retorno/erro.
4. Planner sem parser duplicado para fluxos cobertos por provider intent.
5. Testes cobrindo:
- fallback entre providers;
- consistência de `AgentIntent`;
- roteamento por capability de interface.

## Diretriz Final para a IA
Durante qualquer alteração nesta frente:
1. Priorize contrato e fronteiras de responsabilidade acima de atalhos locais.
2. Não reintroduza parsing/reparo no Core.
3. Se surgir exceção de provider, classifique no contrato de erro e deixe o fallback do manager agir.
4. Sempre validar impacto em multi-provider e multi-canal antes de concluir.

## Relacionados

- [../architecture/README.md](../architecture/README.md): base arquitetural para a reestruturação de drivers e contratos.
- [../policies/README.md](../policies/README.md): camada humana das politicas que cercam o comportamento.
- [../../agent/specs/atlas_operating_model.spec.md](../../agent/specs/atlas_operating_model.spec.md): contrato operacional que precisa preservar consciencia de interface sem reparo no core.
- [../../agent/specs/system_architecture.spec.md](../../agent/specs/system_architecture.spec.md): arquitetura do sistema que recebe o ajuste de responsabilidades.
