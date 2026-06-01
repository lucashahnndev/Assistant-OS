# Agent Workspace

Este diretorio organiza o workspace operacional do agente.

## Entradas úteis

- [../project.overview.md](../project.overview.md)
- [../project.update.md](../project.update.md)
- [../agent-start-here.md](../agent-start-here.md)
- [policy/overview.md](./policy/overview.md)
- [specs/overview.md](./specs/overview.md)
- [specs/project.spec.md](./specs/project.spec.md)
- [specs/project.stat.md](./specs/project.stat.md)

## Estrutura

- `tmp/` para artefatos temporarios e descartaveis
- `prints/` para capturas e imagens de teste
- `reports/` para relatorios temporarios e evidencias consolidadas
- `scripts/` para scripts auxiliares de validacao
- `test/` para anotações e casos de teste
- `note/` para notas mais internas do agente

## Regra

Tudo aqui e apoio ao trabalho.

Nada aqui deve substituir especificacao, contrato ou documentacao oficial do projeto.

## Contrato operacional

Ao alterar prompt, discovery, tool use, approval, observacao, clarificacao ou runtime, considere `agent/specs/atlas_operating_model.spec.md` como contrato ativo e leia a `.stat` correspondente antes de alterar comportamento.

## Relacionados

- [../README.md](../README.md)
- [../project.overview.md](../project.overview.md)
- [../docs/overview.md](../docs/overview.md)
- [policy/overview.md](./policy/overview.md)
- [specs/overview.md](./specs/overview.md)
