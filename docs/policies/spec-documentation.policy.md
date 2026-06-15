# Spec Documentation Policy

Data: 2026-05-27

## Propósito

Este documento define quando uma mudanca exige atualizacao documental e como fechar a responsabilidade entre codigo, spec e documentacao de dominio.

O objetivo e manter:

- contratos claros
- documentacao coerente com o comportamento real
- responsabilidade explicita por frontend, backend e integracoes
- fechamento de etapa sem lacunas documentais

## Principio central

Uma spec so esta verdadeiramente concluida quando o comportamento, o codigo e a documentacao relevante estao consistentes entre si.

## Quando uma mudanca exige documentacao

Uma mudanca exige atualizacao documental quando afeta qualquer um destes pontos:

- contrato
- schema
- API
- capability
- fluxo de UX
- heuristica que influencia comportamento
- responsabilidade operacional
- integracao entre backend e frontend

Se a mudanca altera somente detalhe interno sem efeito externo, a documentacao pode nao precisar mudar, mas a avaliacao disso deve ficar registrada no `stat` da area.

## Responsabilidade por tipo de mudanca

### Backend

Quando a mudanca altera:

- contrato de API
- roteamento
- policy
- validacao
- integracao com services ou capabilities

deve haver revisao da documentacao tecnica correspondente.

### Frontend

Quando a mudanca altera:

- fluxo visual
- estados de tela
- cards, modais ou paines
- feedback do usuario
- adaptacao por canal

deve haver revisao da documentacao de UX ou da doc tecnica relacionada.

### Spec

Quando a mudanca altera:

- limites do sistema
- heuristicas permitidas
- responsabilidade de componente
- contrato entre camadas

deve haver revisao da spec afetada e, se necessario, criacao de nova spec abstrata.

## Regra de fechamento

Uma etapa so deve ser considerada fechada quando:

1. o codigo foi ajustado
2. os testes relevantes passaram
3. a documentacao afetada foi atualizada ou explicitamente marcada como pendente
4. o `stat` da area reflete o estado real
5. o commit de marco foi feito

## Quando o `stat` deve registrar pendencia

O `stat` deve registrar pendencia quando:

- ainda falta doc de backend
- ainda falta doc de frontend
- ainda falta alinhamento entre docs
- a spec mudou mas a doc de dominio ainda nao foi revisada
- a mudanca foi entregue, mas a documentacao ficou para uma etapa seguinte

## Regra de responsabilidade compartilhada

Quando uma mudanca atravessa backend e frontend:

- deve existir um responsavel principal pela coerencia tecnica
- pode existir um responsavel secundario pela revisao de UX ou integracao
- nenhum dos dois deve fechar a etapa ignorando a documentacao afetada

## Anti-padroes

Nao devemos:

- atualizar codigo e ignorar a documentacao afetada
- registrar doc sem validar o comportamento real
- concluir uma spec com doc divergente
- usar o `stat` para esconder pendencia sem clareza
- misturar backlog operacional com contrato oficial

## Fecho

Documentacao nao e enfeite.

Ela faz parte da definicao de pronto quando a mudanca toca contrato, UX, integracao ou heuristica.

## Relacionados

- [../overview.md](../overview.md): indice geral da documentacao humana.
- [../plans/skills_audit_planner.md](../plans/skills_audit_planner.md): plano que operacionaliza auditar contrato, runtime e docs.
- [../plans/permission_groups_planner.md](../plans/permission_groups_planner.md): plano que leva a policy de documentacao para governance prática.
- [../reports/system-audit-2026-05-24.md](../reports/system-audit-2026-05-24.md): exemplo de audit que exige fechamento documental.
- [../../agent/specs/skill_contract.spec.md](../../agent/specs/skill_contract.spec.md): contrato que costuma exigir atualização quando a mudanca afeta skills.
