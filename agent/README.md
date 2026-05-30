# Agent Workspace

Este diretorio organiza o workspace operacional do agente.

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
