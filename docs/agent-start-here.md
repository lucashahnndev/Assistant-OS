# Agent Start Here

This file is a navigation shortcut inside `docs/`.
The primary entry point is the root file: [../agent-start-here.md](../agent-start-here.md).

## Ordem de leitura

1. `project.overview.md`.
2. `project.update.md` when the installed convention may diverge.
3. `project.migrations.md` when the migration spans more than one row.
4. `agent-start-here.md` in the repository root.
5. the relevant `.spec` in `agent/specs/`.
6. the corresponding `.stat`.
7. relevant human documentation in `docs/`.
8. related tests.

## Regra basica

- `.spec` e contrato duravel.
- `.stat` e estado vivo.
- `agent/` e workspace operacional.
- `agent/specs/` e a fonte canonica das specs normativas.
- `docs/` e documentacao humana, explicativa e de navegacao.
- a ligacao entre `.spec` e `.stat` deve ser clara quando ela ajuda a seguir contrato e estado.
- as regras detalhadas ficam em `agent/policy/`.

## Regra de abstracao

Se o tema parecer amplo o suficiente para virar contrato, verifique primeiro se ja existe uma `.spec` parecida.
Se houver conflito, ajuste a proposta antes de criar nova documentacao.
Se fizer sentido formalizar, crie uma `.spec` com nome abstrato e estavel.

## Regra de trabalho

- mantenha mudancas pequenas e coerentes;
- valide antes de avancar;
- registre evidencia no workspace apropriado;
- ligue documentos relevantes quando isso ajudar a entender contrato, dependência ou continuidade;
- atualize `.stat` quando houver progresso real;
- atualize docs oficiais apenas quando contrato ou uso mudar.
