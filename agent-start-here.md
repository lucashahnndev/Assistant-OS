# Agent Start Here

This is the agent entry point for this project.

Read this file first.
Then follow the order below.

## Ordem de leitura

1. `project.overview.md`.
2. `project.update.md` when the local installation may diverge from the recorded version.
3. `project.migrations.md` when the change spans more than one version row.
4. `README.md` when you need human landing-page context.
5. the relevant `.spec` in `agent/specs/`, including system, architecture, contract, or domain specs that govern the change. For prompt, discovery, tool use, approval, runtime, observation, or clarification changes, also read `agent/specs/atlas_operating_model.spec.md`.
6. the corresponding `.stat`.
7. relevant human, operational, or architectural documentation in `docs/`, when it exists.
8. related tests.

## Regra básica

- `.spec` é contrato durável.
- `.stat` é estado vivo.
- `agent/` é workspace operacional.
- as regras detalhadas ficam em `agent/policy/`.
- `project.overview.md` is the conceptual map for agent-oriented navigation.
- `project.update.md` is the update index for already-installed workspaces.
- `project.migrations.md` is the version-by-version migration ledger.

## Regra de abstração

Se o tema parecer amplo o suficiente para virar contrato, verifique primeiro se já existe uma `.spec` parecida.
Se houver conflito, ajuste a proposta antes de criar nova documentação.
Se fizer sentido formalizar, crie uma `.spec` com nome abstrato e estável.

## Regra de trabalho

- mantenha mudanças pequenas e coerentes;
- valide antes de avançar;
- registre evidência no workspace apropriado;
- ligue documentos relevantes quando isso ajudar a entender contrato, dependência ou continuidade;
- when the target is a file that is not `.md`, use an explicit file or path reference; do not create a new note to represent it;
- não reorganize arquivos existentes sem aprovação;
- atualize `.stat` quando houver progresso real;
- atualize docs oficiais apenas quando contrato ou uso mudar.
- para commits, siga [agent/policy/commit-safety.policy.md](agent/policy/commit-safety.policy.md) e use `trace_id` quando houver mudança relevante.


## Protocolo de adequacao

1. aplique o bootstrap da convenção;
2. ajuste grafo e exclusoes do vault;
3. faca inventario de ruido, artefatos e arquivos soltos;
4. peca aprovacao antes de organizar;
5. organize o repositorio;
6. mapeie docs que precisam virar contexto, .spec ou .stat;
7. peca aprovacao antes de criar ou ajustar contratos;
8. faca linkagem e consolidacao;
9. use a mensagem padrao de handoff da policy de adequacao e peça aprovacao para a proxima fase.

## Relacionados

- [agent/policy/overview.md](agent/policy/overview.md)
- [agent/specs/overview.md](agent/specs/overview.md)
- [agent/specs/project.spec.md](agent/specs/project.spec.md)
- [agent/specs/project.stat.md](agent/specs/project.stat.md)
