# Specs

Este diretório guarda os contratos normativos canônicos do agente e do sistema alvo.

## Regras

- cada `.spec` ativa deve ter uma `.stat`;
- `.spec` define contrato durável;
- `.stat` registra estado vivo;
- não usar `.spec` como diário de progresso;
- não usar `.stat` para redefinir contrato.
- `agent/specs/` e a fonte de verdade para specs normativas;
- `docs/` pode referenciar specs, mas nao compete com este diretorio.

## Convenção

- `nome-do-dominio.spec.md`
- `nome-do-dominio.stat.md`

## Base inicial

- `project.spec.md`
- `project.stat.md`
- `agent-heuristics.spec.md`
- `agent-heuristics.stat.md`
