# Agent Start Here

Leia este arquivo primeiro.

Este guia tambem esta espelhado em `docs/agent-start-here.md` para ficar acessivel dentro do indice de documentacao.

## Ordem de leitura

1. `README.md` do projeto.
2. `agent-start-here.md`.
3. `.spec` relevante em `agent/specs/`.
4. `.stat` correspondente.
5. documentação humana relevante em `docs/`.
6. testes relacionados.

## Regra básica

- `.spec` é contrato durável.
- `.stat` é estado vivo.
- `agent/` é workspace operacional.
- `agent/specs/` é a fonte canônica das specs normativas.
- `docs/` é documentação humana, explicativa e de navegação.
- as regras detalhadas ficam em `agent/policy/`.

## Regra de abstração

Se o tema parecer amplo o suficiente para virar contrato, verifique primeiro se já existe uma `.spec` parecida.
Se houver conflito, ajuste a proposta antes de criar nova documentação.
Se fizer sentido formalizar, crie uma `.spec` com nome abstrato e estável.

## Regra de trabalho

- mantenha mudanças pequenas e coerentes;
- valide antes de avançar;
- registre evidência no workspace apropriado;
- atualize `.stat` quando houver progresso real;
- atualize docs oficiais apenas quando contrato ou uso mudar.
