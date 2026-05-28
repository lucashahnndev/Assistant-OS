# Agent Start Here

Este arquivo acompanha o ponto de entrada principal do agente.

## Ordem de leitura

1. `README.md` do projeto.
2. `agent-start-here.md` na raiz do repositorio.
3. `.spec` relevante em `agent/specs/`.
4. `.stat` correspondente.
5. documentacao humana relevante em `docs/`.
6. testes relacionados.

## Regra basica

- `.spec` e contrato duravel.
- `.stat` e estado vivo.
- `agent/` e workspace operacional.
- `agent/specs/` e a fonte canonica das specs normativas.
- `docs/` e documentacao humana, explicativa e de navegacao.
- as regras detalhadas ficam em `agent/policy/`.

## Regra de abstracao

Se o tema parecer amplo o suficiente para virar contrato, verifique primeiro se ja existe uma `.spec` parecida.
Se houver conflito, ajuste a proposta antes de criar nova documentacao.
Se fizer sentido formalizar, crie uma `.spec` com nome abstrato e estavel.

## Regra de trabalho

- mantenha mudancas pequenas e coerentes;
- valide antes de avancar;
- registre evidencia no workspace apropriado;
- atualize `.stat` quando houver progresso real;
- atualize docs oficiais apenas quando contrato ou uso mudar.
