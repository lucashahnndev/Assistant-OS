# Adequation Policy

## Relacionados

- [README.md](../../README.md)
- [../README.md](README.md)
- [../workspace.policy.md](workspace.policy.md)
- [../specs/README.md](../specs/overview.md)
- [../specs/project.stat.md](../specs/project.stat.md)

- esta policy orienta o modo de adequação pós-instalação da convenção;
- use quando o repositório já recebeu `standard` e precisa ser alinhado ao contrato de uso;
- não faça alterações estruturais grandes sem passar pelas fases e aprovações abaixo;
- trate cada fase como um checkpoint reutilizável;
- o objetivo é deixar o repositório pronto para o agente trabalhar com menos ruído e menos suposições.

## Fluxo padrão

1. verificar bootstrap;
2. alinhar grafo e exclusões do vault;
3. mapear ruído, artefatos e arquivos soltos;
4. pedir aprovação para organizar o repositório;
5. organizar o repositório aprovado;
6. mapear documentação que precisa virar contrato ou estado;
7. pedir aprovação para criar ou ajustar contexto e specs;
8. criar ou ajustar contexto, specs, stats e linkagem;
9. pedir aprovação para consolidar e commitar;
10. registrar o resultado na `.stat`.

## Handoff padrao

Depois do bootstrap, o agente deve encerrar a primeira mensagem de forma
curta e previsivel. O formato recomendado é:

```text
Instalei a convenção, alinhei o grafo e o .gitignore, e li o roteiro de adequação.
Posso iniciar a fase 2: inventário de ruído, artefatos e arquivos soltos?
```

Se houver aprovacao, o agente segue para o inventario.
Se nao houver aprovacao, o agente para e aguarda nova instrucao.

Antes de sair de cada fase, o agente deve repetir o mesmo padrao:

- resumir o que encontrou;
- listar arquivos criados ou alterados;
- mostrar `git status --short`;
- dizer o que pretende fazer na proxima fase;
- pedir aprovacao antes de mudar estrutura, mover arquivos ou apagar artefatos.

## Fase 1: bootstrap

- confirmar que `agent-start-here.md` foi lido;
- confirmar que `README.md` e `agent/policy/README.md` foram lidos quando existirem;
- aplicar `graph.json` recomendado quando o projeto usar Obsidian;
- alinhar `.gitignore` do projeto para o ruído local conhecido;
- criar ou alinhar entradas mínimas de documentação quando faltarem, se isso estiver no escopo aprovado.

## Fase 2: inventário

- listar arquivos soltos, temporários, caches, artefatos, notas, relatórios e docs legados;
- classificar cada item em:
  - manter;
  - investigar;
  - mover;
  - renomear;
  - apagar;
  - preservar;
- não executar limpeza sem aprovação explícita.

## Fase 3: organização

- mover artefatos para os diretórios corretos;
- remover ruído aprovado;
- alinhar workspace operacional;
- preservar histórico e evidência útil.

## Fase 4: contexto e contratos

- identificar quais documentos já são contrato;
- identificar quais documentos precisam virar `.spec` / `.stat`;
- identificar quais documentos são só explicação, evidência ou legado;
- propor ligações entre docs, specs, stats e policies por domínio e por função.

## Fase 5: consolidação

- atualizar `.stat` com progresso real;
- registrar `trace_id` quando houver mudança relevante;
- se houver commit, registrar mensagem e hash depois do commit;
- deixar claro o que foi feito, o que ficou pendente e o que precisa de decisão.

## Aprovação

Antes de avançar entre as fases, mostre:

- resumo do inventário ou da proposta;
- arquivos criados ou alterados;
- `git status --short`;
- dúvidas e decisões pendentes.

## Regra central

- a adequação existe para tornar o repositório compatível com a convenção;
- não transforme a adequação em refatoração arbitrária;
- não pule aprovação quando a fase envolver mudança estrutural.
