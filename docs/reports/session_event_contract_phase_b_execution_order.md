# Session Event Contract - Phase B Execution Order

## Regra principal

Implementar em fatias pequenas. Não misturar B1, B2, B3, B4 e B5 no mesmo commit.

Fora do escopo:

- cognição;
- prompts;
- `LLMResolver`;
- tool choice;
- policies agenticas;
- refactor cognitivo;
- índices V1/V2 completos;
- Wegena persistente completo;
- cards/media/thoughts/playback completos.

## Ordem recomendada

### B1 - Event Envelope Baseline

Objetivo:
Criar ou normalizar o envelope mínimo para eventos sem alterar a semântica do agente.

Campos:

- `event_id`;
- `event_type`;
- `session_id`;
- `timestamp`;
- `channel`;
- `interface`;
- `source`.

Critério de sucesso:

- eventos principais carregam envelope mínimo;
- eventos antigos continuam funcionando;
- nenhum frontend muda comportamento visual ainda.

### B2 - Turn/Message/Stream Correlation

Objetivo:
Introduzir correlação estável para resposta live.

Campos:

- `turn_id`;
- `message_id`;
- `reply_to_message_id`;
- `stream_id`;
- `sequence`.

Prioridade:

- `assistant_chunk`;
- `final_message_chunk`;
- `message_added`;
- stream start ou equivalente.

Critério de sucesso:

- chunks apontam para mensagem ou stream;
- mensagem do usuário e resposta compartilham `turn_id`;
- resposta aponta para `reply_to_message_id`.

### B3 - Complete Target

Objetivo:
Remover ambiguidade do `complete`.

Regra:

- `complete` sempre tem `target`;
- `target=stream` exige `stream_id`;
- `target=message` exige `message_id`;
- `target=work` exige `work_id`;
- `target=session` exige `session_id`.

Critério de sucesso:

- nenhum complete genérico finaliza visual;
- frontend consegue saber exatamente o que foi concluído.

### B4 - Frontend Event Normalizer

Objetivo:
Fazer Chat e Nexus consumirem o mesmo contrato normalizado, sem padronizar UX.

Regras:

- evento técnico não cria balão;
- evento visual não cria balão;
- chunk sem correlação não cria mensagem;
- placeholder exige `turn_id + message_id/stream_id`;
- `session_updated` não sobrescreve live stream sem merge ou reconcile.

Critério de sucesso:

- Chat e Nexus interpretam eventos pelo mesmo envelope;
- renderização continua específica por interface.

### B5 - Reconciliation and Validation

Objetivo:
Validar o fluxo real contra o contrato.

Casos obrigatórios:

- optimistic user message;
- assistant stream;
- `assistant_chunk`;
- `final_message_chunk`;
- `message_added` tardio;
- `complete` com target;
- `session_updated`;
- refresh/histórico;
- Nexus;
- Telegram;
- Welcome/Boot oculto.

Critério de sucesso:

- nenhum skeleton vira balão vazio;
- nenhum chunk fica sem dono;
- nenhum evento visual interfere em mensagem;
- refresh não corrige algo que deveria funcionar live;
- Chat e Nexus seguem consumindo o mesmo contrato.

## Regra de commit

Cada etapa deve virar commit separado:

- `feat(events): add session event envelope baseline`;
- `feat(events): add turn message stream correlation`;
- `fix(events): target complete events explicitly`;
- `feat(frontend): normalize session event consumption`;
- `test(events): validate live stream reconciliation`.

Essas mensagens são sugestões; ajustar conforme o diff real.

## Regra de parada

Se uma etapa exigir mexer em cognição, prompt, `LLMResolver` ou decisão agentica, parar e pedir revisão de escopo.

Se uma etapa gerar patch amplo demais, dividir.

Se um evento não tiver correlação suficiente, não inventar balão visual.
