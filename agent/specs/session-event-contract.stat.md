# Session Event Contract Stat

Data da ultima atualizacao: 2026-05-31

## Estado atual

- novo dominio normativo criado para unificar sessoes, turnos, mensagens, streams, works e eventos;
- o contrato separa claramente envelope de evento, mensagem canonica, stream incremental, work operacional e artefatos visuais;
- a regra central evita baloes vazios, skeletons sem alvo e inferencias de UI baseadas apenas em `chat.json` bruto.

## Pendencias

- alinhar a documentacao humana correlata com este contrato;
- revisar se algum documento antigo de `system_sessions` ou `agent_events` deve passar a apontar para este dominio como referencia principal;
- manter coerencia com os caminhos de persistencia e renderizacao existentes quando o comportamento real for revisado.

## Evidencias / validacoes

- contrato formal criado em `agent/specs/`;
- o escopo ficou limitado a dados, eventos, persistencia e consumo por interface;
- o dominio nao mexe em cognicao, prompt ou tool choice.

## Proximo passo recomendado

- usar este contrato como referencia canonica quando for revisar sessao, timeline, websocket, chat, console, Nexus, Telegram, Wegena, cards, midia ou workers.

## Riscos ou duvidas abertas

- este dominio se sobrepoe parcialmente a `system_sessions` e `agent_events`, entao futuras revisoes devem evitar duplicar regras em vez de consolidar referencias;
- a implementacao real pode ainda ter nomes antigos ou caminhos legados que precisem de mapeamento progressivo.
