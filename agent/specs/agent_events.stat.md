# Agent Events Stat

Data da ultima atualizacao: 2026-05-28

## Estado atual

- `AgentEvent` formalizado como contrato para sinais internos de atencao do agente;
- eventos continuam sendo a ponte canonica entre servicos/capabilities e sessoes do sistema;
- o indice da pasta de arquitetura agora referencia a versao `.spec`.

## Pendencias

- validar se novos tipos de evento seguem a mesma estrutura de payload e metadata;
- manter alinhamento com o `InternalDriver` e o roteamento de sessoes do sistema.

## Evidencias / validacoes

- spec criada e movida para a pasta de arquitetura;
- referencias antigas da pasta foram atualizadas.

## Proximo passo recomendado

- usar esta spec como base para formalizar outros eventos internos relacionados a dominios.
## Relacionados

- [agent_events.spec.md](agent_events.spec.md)
- [../README.md](../overview.md)
