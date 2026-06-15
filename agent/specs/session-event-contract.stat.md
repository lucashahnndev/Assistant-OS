# Session Event Contract Stat

Data da ultima atualizacao: 2026-06-07
Spec mirror: [session-event-contract.spec.md](session-event-contract.spec.md).

## Estado atual

- o contrato de sessao/evento agora esta materializado no backend e no frontend como contrato canônico, com pipeline de eventos, snapshot HTTP e timeline consumindo o mesmo modelo;
- o fluxo consolidado cobre `events.jsonl`, `messages.index.json`, `turns.index.json`, `streams.index.json`, `thoughts.index.json`, `media.index.json`, `cards.index.json`, `artifacts.index.json`, `wegena.index.json`, `workers.index.json` e `feedback.index.json`;
- o `turn_id` passou a ser o eixo canônico de request/response, com suporte a respostas espontâneas e a eventos live incrementais;
- reasoning/thought foi separado da timeline de chat, com persistencia própria e visualização estruturada no chat;
- thought duration, stream duration e turn duration passaram a ser derivados estáveis no snapshot;
- feedback like/unlike para respostas do assistente passou a ser persistido e exposto no snapshot sem virar mensagem ou reasoning;
- o consumidor vivo do Nexus passou a tratar `turn_id` como fronteira de reset do transcript, acumulando `asr.partial` / `transcript.partial` por turno e deixando `voice.state` / `tts.chunk` apenas como ponte de transporte;
- a regra central continua evitando baloes vazios, skeletons sem alvo e inferencias de UI baseadas apenas em `chat.json` bruto.
- a spec principal ganhou uma limpeza estrutural no bloco `assistant_chunk`, recolocando `Relacionados` no fim do documento para evitar ambiguidade de leitura.

## Pendencias

- alinhar a documentacao humana correlata com este contrato, especialmente as partes de chat/snapshot/timeline/feedback;
- manter coerencia entre o contrato e quaisquer caminhos legados que ainda existirem no runtime;
- revisar se algum documento antigo de `system_sessions` ou `agent_events` deve continuar apontando para este dominio como referencia principal.

## Evidencias / validacoes

- contrato formal criado em `agent/specs/` e consolidado em implementacao real;
- o backend agora possui pipeline canônico, snapshot HTTP, turn canônico, timeline de thought, feedback persistido e eventos live normalizados;
- o Nexus agora consome o turno vivo como uma unica sessão visual, sem separar texto e voz como cards independentes;
- os fluxos foram validados com testes mínimos para snapshot, reload, turn grouping, live stream, thought duration e feedback;
- o escopo ficou limitado a dados, eventos, persistencia e consumo por interface;
- o dominio nao mexe em cognicao, prompt, LLM resolver ou tool choice.

- `trace_id=conv-20260605-nexus-live-transcript-docs`
  - resumo: adicionou ponte humana em `docs/contracts/` para o fluxo de transcrição viva do Nexus, alinhou a spec de sessão/evento com a regra de reset por `turn_id` e registrou o comportamento de voz/texto como uma unica superficie de sessão;
  - validacao: documentação atualizada e contrato revisado para refletir a implementação viva do Nexus;
  - observacao: o histórico colapsável continua sendo o arquivo durável, enquanto o card vivo representa apenas o turno corrente.

## Relacionados

- [session-event-contract.spec.md](session-event-contract.spec.md)
- [../policy/session-event-contract.policy.md](../policy/session-event-contract.policy.md)
- [system_sessions.spec.md](system_sessions.spec.md)
- [system_sessions.stat.md](system_sessions.stat.md)
- [../../docs/contracts/overview.md](../../docs/contracts/overview.md)

## Proximo passo recomendado

- usar este contrato como referencia canonica quando for revisar sessao, timeline, websocket, chat, console, Nexus, Telegram, Wegena, cards, midia, workers ou feedback.

## Riscos ou duvidas abertas

- este dominio se sobrepoe parcialmente a `system_sessions` e `agent_events`, entao futuras revisoes devem evitar duplicar regras em vez de consolidar referencias;
- a implementacao real pode ainda ter nomes antigos ou caminhos legados que precisem de mapeamento progressivo;
- qualquer ampliacao futura de feedback, ranking ou memoria precisa manter o contrato de snapshot como fonte de verdade para a UI.

## Registros de commits recentes

- `a9fd2901` `feat(sessions): persist assistant feedback feedback index`
  - resumo: adicionou persistencia canonica de feedback por resposta do assistente em `feedback.index.json`, com endpoint de feedback e exposicao no snapshot;
  - validacao: testes minimos de feedback, snapshot e event pipeline.

- `645e89ef` `feat(sessions): expose thought duration in timeline`
  - resumo: derivou duracao de thought, stream e turn em `thoughts.index.json`, `turns.index.json`, `streams.index.json` e snapshot, com consumo no frontend;
  - validacao: testes minimos de event pipeline, snapshot e timeline de thought.

- `6167e4eb` `fix(sessions): route reasoning to thoughts index`
  - resumo: separou reasoning do `chat.json`, roteando pensamento para `thoughts.index.json` e para a timeline estruturada;
  - validacao: testes minimos de pipeline e snapshot.

- `a75ff590` `feat(sessions): add canonical session snapshot and rich indexes`
  - resumo: introduziu `GET /sessions/{session_id}/snapshot`, indices ricos e tolerancia a arquivos ausentes;
  - validacao: smoke de snapshot e tests minimos.

- `2ea78334` `feat(sessions): add canonical session event pipeline`
  - resumo: criou o pipeline canônico de sessao com `events.jsonl` e indices basicos;
  - validacao: testes minimos do pipeline e `Session.add_message`.
