# Worker + Task Contract Stat

Data da ultima atualizacao: 2026-05-28

## Estado atual

- contrato de execucao assincrona formalizado em spec;
- entidades `TaskDefinition`, `ScheduleTrigger`, `TaskExecution` e `Work` continuam como contrato duravel;
- UI, APIs e runtime dependem desta especificacao.

## Pendencias

- manter sincronizacao entre runtime real e contrato;
- atualizar a spec quando o fluxo de scheduler/worker mudar.

## Evidencias / validacoes

- spec separada do texto explicativo;
- ingestores de procedimentos e documentos operacionais ainda apontam para esta fonte.

## Proximo passo recomendado

- alinhar contratos de API e UI com esta spec antes de qualquer refatoracao do worker runtime.
