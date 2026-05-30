# Agent Start Here

Este é o ponto de entrada do agente neste projeto.

Leia este arquivo primeiro.
Depois siga a ordem abaixo.

## Ordem de leitura

1. `README.md` do projeto.
2. `.spec` relevante em `agent/specs/`, incluindo specs de sistema, arquitetura, contrato ou domínio que governem a mudança. Para mudanças em prompt, discovery, tool use, approval, runtime, observação ou clarificação, leia também `agent/specs/atlas_operating_model.spec.md`.
3. `.stat` correspondente.
4. documentação humana, operacional ou de arquitetura relevante em `docs/`, quando existir.
5. testes relacionados.

## Regra básica

- `.spec` é contrato durável.
- `.stat` é estado vivo.
- `agent/` é workspace operacional.
- as regras detalhadas ficam em `agent/policy/`.

## Regra de abstração

Se o tema parecer amplo o suficiente para virar contrato, verifique primeiro se já existe uma `.spec` parecida.
Se houver conflito, ajuste a proposta antes de criar nova documentação.
Se fizer sentido formalizar, crie uma `.spec` com nome abstrato e estável.

## Regra de trabalho

- mantenha mudanças pequenas e coerentes;
- valide antes de avançar;
- registre evidência no workspace apropriado;
- não reorganize arquivos existentes sem aprovação;
- atualize `.stat` quando houver progresso real;
- atualize docs oficiais apenas quando contrato ou uso mudar.
