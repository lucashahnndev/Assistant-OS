# Contracts

Este diretorio guarda referencias humanas sobre contratos operacionais e tecnicos.
As specs normativas canônicas vivem em `agent/specs/`.

`Session Event Contract` e o dominio guarda-chuva para sessoes, mensagens, turnos, streams, works, eventos, indices e persistencia. `system_sessions` e `agent_events` continuam validos como contratos especificos e/ou legados; consultas novas de session/event/WebSocket devem olhar primeiro para o dominio guarda-chuva.

## Uso

- definicoes de runtime;
- contratos de task/worker;
- contratos de habilidades e integracoes.

## Indice

### Active Specs
- [worker_task_contract.spec.md](../../agent/specs/worker_task_contract.spec.md)
- [skill_contract.spec.md](../../agent/specs/skill_contract.spec.md)
- [remote.spec.md](../../agent/specs/remote.spec.md)
- [session-event-contract.spec.md](../../agent/specs/session-event-contract.spec.md)

### State Tracking
- [remote.stat.md](../../agent/specs/remote.stat.md)
- [worker_task_contract.stat.md](../../agent/specs/worker_task_contract.stat.md)
- [skill_contract.stat.md](../../agent/specs/skill_contract.stat.md)
- [session-event-contract.stat.md](../../agent/specs/session-event-contract.stat.md)
