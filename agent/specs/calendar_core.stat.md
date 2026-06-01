# Calendar Core Stat

Data da ultima atualizacao: 2026-05-28

## Estado atual

- nucleo de calendario formalizado como spec;
- calendario interno segue como fonte canonica de eventos;
- scheduler, store e service permanecem como componentes centrais do dominio.

## Pendencias

- manter o alinhamento entre a spec e a implementacao do scheduler;
- revisar impactos quando novos tipos de evento forem adicionados.

## Evidencias / validacoes

- contrato de calendario agora tem formato espec + stat;
- pipeline interno continua descrito como trusted capability.

## Proximo passo recomendado

- usar esta spec como base para evolucoes de sincronizacao e notificacao.
## Relacionados

- [calendar_core.spec.md](calendar_core.spec.md)
- [../README.md](../overview.md)
