# Commit Safety

Data: 2026-05-27

## Propósito

Este documento define como o Atlas deve registrar progresso no Git sem poluir especificacoes ou misturar etapas.

## Regra principal

O commit deve acontecer entre etapas coerentes de trabalho.

Nao deve ser usado para:

- marcar etapas dentro de `.spec`
- registrar pensamento intermediario
- salvar estados sem sentido de reversao

## Quando fazer commit

Fazer commit quando:

- uma etapa logica foi concluida
- testes relevantes passaram
- a mudanca nao esta mais em estado intermediario
- o trabalho pode ser retomado sem ambiguidade

## Quando nao fazer commit

Nao fazer commit quando:

- a etapa ainda esta incompleta
- a mudanca depende de ajuste imediato ainda nao validado
- o estado atual ainda e exploratorio
- o arquivo alterado ainda representa um experimento

## Nivel de granularidade

O commit deve refletir um marco util, nao cada linha editada.

O ponto ideal e:

- pequeno o suficiente para revisar
- grande o suficiente para ter significado
- limpo o bastante para reverter sem confusao

## Relacao com `.spec` e `.stat`

- `.spec` define contrato e limites
- `.stat` registra aderencia, risco e direcao
- `commit` registra o fechamento de uma etapa

Esses tres elementos nao devem se misturar.

## Mensagem de commit

A mensagem deve descrever:

- o que foi fechado
- qual area foi afetada
- qual risco foi reduzido

Exemplo:

- `fix(context): align hint ranking diagnostics with baseline cap`
- `docs: add agent start and commit safety guidance`

## Politica pratica

Entre etapas:

1. finalizar a mudanca
2. validar
3. atualizar documentacao de estado se necessario
4. fazer commit
5. continuar na proxima etapa

## Sinal de alerta

Se o trabalho estiver pedindo commits excessivamente pequenos, normalmente isso indica:

- falta de recorte claro da etapa
- granularidade ruim da tarefa
- ou risco de estar fazendo hardcode em vez de evolucao arquitetural

## Fecho

Commit e marco de progresso.  
Spec e contrato.  
Stat e acompanhamento.  
Nao misturar os tres.

## Relacionados

- [../overview.md](../overview.md): indice geral da documentacao humana.
- [../plans/permission_groups_planner.md](../plans/permission_groups_planner.md): plano que depende de marcos claros de trabalho e commit.
- [../plans/skills_audit_planner.md](../plans/skills_audit_planner.md): plano que tambem pede etapas bem separadas.
- [../reports/session_event_contract_phase_b_execution_order.md](../reports/session_event_contract_phase_b_execution_order.md): exemplo de ordem por fatias pequenas antes de commitar.
