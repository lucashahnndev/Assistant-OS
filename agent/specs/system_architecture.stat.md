# System Architecture Stat

Data da ultima atualizacao: 2026-05-30

## Estado atual

- arquitetura base formalizada em spec;
- camadas Kernel, Drivers, Orchestrator e Memory continuam como contrato central;
- o portal HTML de arquitetura agora aponta para a pasta `docs/architecture/`.
- a descrição de reflexes foi atualizada para nao normalizar regex hardcoded como autoridade semantica.
- o runtime passou a registrar um envelope estruturado de observacao pos-execucao, mantendo a observacao textual compativel para o proximo ciclo do agente.
- o envelope de observacao agora projeta evidencia enumeravel fiel quando o output estruturado traz listas/itens/campos exatos, preservando preview/truncamento explicitos para o proximo ciclo.
- a nova spec `atlas_operating_model.spec.md` passou a servir como referencia operacional para clarificar que o agente opera sobre um runtime com gates tecnicos.

## Pendencias

- manter alinhamento entre runtime real e descricao arquitetural;
- revisar documentos filiados quando camadas novas forem introduzidas.
- referenciar a nova spec de fronteira semantica quando o fluxo cognitivo for reavaliado.
- acompanhar a nova observacao estruturada no loop para garantir que o proximo passo do agente leia o estado de forma mais explicita.

## Evidencias / validacoes

- indice da pasta criado;
- spec movida para a pasta de arquitetura;
- referencias antigas ainda estao sendo normalizadas.
- observacao textual antiga continua existindo, mas agora ha um envelope estruturado em `session.context` e um resumo compacto em `state_summary`.
- outputs enumeraveis agora carregam `evidence_items`/`last_observation_evidence` para grounding mais fiel sem inflar o contexto bruto.

## Proximo passo recomendado

- usar esta spec como referencia para revisar docs secundarias de arquitetura.
- usar `semantic_decision_boundary.spec.md` como clausula de fronteira semantica principal.
- usar `atlas_operating_model.spec.md` como clausula operacional principal para clarificar papel do agente, do runtime e da clarificacao.

## Registros de commits recentes

- `5536d28f` `feat: add observation freshness and grounding evidence`
  - resumo: ampliou `ActionObservation`, `Session` e o encoder TOON para carregar proveniencia/freshness da observacao atual, mantendo evidencias enumeraveis e preview truncado para o proximo ciclo do agente;
  - validacao: `python3 -m py_compile src/core/observation.py src/core/session.py src/utils/toon_codec.py tests/minimal/test_action_observation_contract.py tests/minimal/test_observation_freshness.py tests/minimal/test_last_mile_grounding.py` e `PYTHONPATH=src:. env/bin/python -m pytest tests/minimal/test_action_observation_contract.py tests/minimal/test_observation_freshness.py tests/minimal/test_last_mile_grounding.py -q`;
  - falhas conhecidas fora do escopo: os testes antigos de alias/Obsidian em `tests/minimal/test_mcp_llm_alias_and_recovery.py` continuam preexistentes e nao bloqueiam este pacote.
- `01061ad8` `feat: add attachment delivery confirmation contract`
  - resumo: separou o contrato de entrega de anexos entre resolvido, preparado e enviado, propagando confirmacao estruturada pelos bridges Telegram/Web e impedindo claims de envio sem payload confirmado;
  - validacao: `python3 -m py_compile src/core/observation.py src/core/orchestrator.py src/drivers/interfaces/internal_driver.py src/drivers/interfaces/server_driver.py src/drivers/interfaces/telegram/telegram_bot.py src/drivers/interfaces/telegram/telegram_driver.py tests/minimal/test_attachment_delivery_contract.py tests/minimal/test_orchestrator_grounding_flow.py` e `PYTHONPATH=src:. env/bin/python -m pytest tests/minimal/test_attachment_delivery_contract.py tests/minimal/test_orchestrator_grounding_flow.py -q`;
  - falhas conhecidas fora do escopo: os testes antigos de alias/Obsidian em `tests/minimal/test_mcp_llm_alias_and_recovery.py` continuam preexistentes e nao bloqueiam este pacote.
