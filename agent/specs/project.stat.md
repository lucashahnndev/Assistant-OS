# Project Stat

Data da última atualização: 2026-06-06
Spec mirror: [project.spec.md](project.spec.md).

Este é o estado inicial pareado com `project.spec.md`.

## Relacionados

- [project.spec.md](project.spec.md)
- [../../README.md](../../README.md)
- [../policy/overview.md](../policy/overview.md)
- [../README.md](../overview.md)

## Estado atual

- convenção inicial criada;
- estrutura base disponível;
- domínios reais ainda podem ser separados em specs próprias.
- artefatos temporarios de validacao foram movidos para `agent/test/` e `agent/scripts/`, reduzindo o uso de `tests/` e `scratch/` para apoio operacional fora da workspace do agente.
- rastreamento da convenção de entrada alinhado com `trace_id=conv-20260531-root-entry-links`.
- o dominio de sessoes/eventos ja amadureceu em contrato proprio em `agent/specs/session-event-contract.spec.md` e sua `.stat`, servindo como referencia canonica para chat, snapshot, timeline, feedback e stream live.
- a fase de adequacao local consolidou ruido operacional da raiz em `agent/tmp/`, `agent/prints/`, `agent/reports/` e `agent/note/`, e passou a registrar novos apontamentos humanos em `docs/plans/` e `docs/reports/` com linkagem canonica.

## Pendências

- definir specs de domínio reais quando o projeto alvo amadurecer;
- ajustar documentação operacional conforme o uso concreto aparecer.
- decidir se `agent/README.md`, `docs/concepts/market-learning-engine.concept.md` e `src/capabilities/browser_control/IMPLEMENTATION_PLAN.md` devem ser restaurados, arquivados ou removidos de forma definitiva.

## Evidências / validações

- template inicial criado;
- estrutura do workspace definida;
- convenção de `.spec` e `.stat` estabelecida.
- a raiz do repositorio foi limpa de scripts e arquivos de teste temporarios rastreados; os artefatos pontuais de validacao agora vivem na workspace do agente.
- leitura canônica do agente agora aponta para `agent-start-here.md` na raiz, com `docs/agent-start-here.md` mantido apenas como atalho de navegação.
- a malha de entrada da convenção foi reforçada com links entre `README.md`, `agent-start-here.md`, `agent/overview.md`, `agent/specs/overview.md` e `agent/policy/overview.md`.
- a convenção aplicada no projeto foi alinhada com a revisão `v3`, incluindo a regra de que arquivos que não são `.md` devem ser referenciados explicitamente em vez de virarem notas novas.
- o contrato de sessao/evento consolidou pipeline canônico, snapshot HTTP, turn canônico, timeline de thought, duracao derivada e feedback persistido sem alterar cognição/prompt/tool choice.
- a organização do workspace operacional moveu scripts e artefatos temporários soltos para `agent/tmp/`, `agent/prints/`, `agent/reports/` e `agent/note/`, além de reforçar o `.gitignore` local para ruído recorrente da raiz.
- `trace_id=conv-20260606-workspace-adequation-phase2` `chore: consolidate root noise into agent workspace and link new docs`
  - resumo: reposicionou artefatos soltos da raiz para o workspace operacional do agente, adicionou links canônicos para o plano de browser control e o relatório de UI/UX, e registrou a fase 2 da adequação local;
  - validacao: `git status --short` revisado após a organização e a convenção recebeu apontamento de progresso real;
  - observacao: permanecem em aberto decisões sobre deleções estruturais herdadas de iterações anteriores, sem commit nesta rodada.

## Próximo passo recomendado

- substituir ou dividir esta spec fundacional quando os domínios do projeto estiverem claros.

## Riscos ou dúvidas abertas

- esta spec é apenas um ponto de partida;
- não deve absorver domínios independentes por conveniência.

## Regra central

- `.stat` registra estado, pendências, validações e próximos passos.
- `.stat` não redefine contrato.

## Registros de commits recentes

- `fa7b13dc` `chore: move temporary validation assets into agent workspace`
  - resumo: moveu harnesses temporarios de `tests/minimal/` para `agent/test/` e scripts de `scratch/` para `agent/scripts/`, reduzindo sujeira fora da workspace do agente;
  - validacao: `python3 -m py_compile agent/scripts/check_braces.py agent/scripts/check_syntax.py agent/test/test_attachment_delivery_contract.py agent/test/test_last_mile_grounding.py agent/test/test_observation_freshness.py agent/test/test_orchestrator_grounding_flow.py` e `PYTHONPATH=src:. env/bin/python -m pytest agent/test/test_attachment_delivery_contract.py agent/test/test_last_mile_grounding.py agent/test/test_observation_freshness.py agent/test/test_orchestrator_grounding_flow.py -q`;
  - falhas conhecidas fora do escopo: os arquivos paralelos de frontend e os testes antigos de alias/Obsidian continuam fora desta limpeza e nao foram alterados.

- `trace_id=conv-20260602-ui-modernization-and-chat-improvements` `feat: comprehensive UI standardization, stability audit, and chat interface upgrades`
  - resumo:
    1. **Padronização de Formulários & UI:** Aplicação global das classes `.input-field` e `.toggle-switch` em todos os inputs, selects e checkboxes (substituindo inputs legados). Padronização dos botões de "Cancel" e "Collapse" em `Settings.jsx` e `ModelPoolManager.jsx` com espaçamento e ícones unificados (`X`, `ChevronUp`, `ChevronDown`, `Save`).
    2. **Refatoração de Interação:** Imposição do estado "colapsado por padrão" para listas dinâmicas (ex: MCP Servers) para reduzir o ruído visual ("wall of cards"). Limpeza profunda de estilos inline redundantes no `Settings.jsx`.
    3. **Estabilidade de Renderização:** Auditoria de `ErrorBoundary` para componentes dinâmicos. Resolução crítica do crash (`NotFoundError`) ao expandir/retrair abas no `Settings.jsx`, substituindo a troca condicional de fragmentos JSX (`<></>`) por elementos estritos `<span>`. Correção de importação ausente do `XCircle` que causava crash na aba de Network.
    4. **Visualizador de Arquivos (Markdown Viewer):** Refatoração na renderização de documentos de texto na timeline. O conteúdo bruto não fica mais preso no tooltip gigante ou num bloco preto segregado; a visualização foi otimizada para parecer um visualizador de texto limpo, incorporado ao componente principal e removendo ícones redundantes ("thought").
    5. **Empty State Operacional (`MessageItem.jsx`):** Substituição do bloco genérico por uma saudação contextual ("A.T.L.A.S is standing by") contendo 4 diretivas estáticas acionáveis que apenas preenchem o input de forma segura, evitando execução acidental.
    6. **Ferramentas de UX no Chat:** Adição do botão "Copy" embaixo de cada balão de mensagem (usuário e assistente) com feedback visual de 2 segundos. Implementação do suporte nativo de colar imagens (`onPaste`) na `textarea` do chat (`ChatInputArea.jsx`), conectando o clipboard diretamente ao fluxo existente de `handleFileUpload`.
  - validacao: UI auditada para o tema "Quiet Interface" ("Premium Soft Flat"); Build do Vite concluído sem erros; testes manuais nas ações de cópia, deleção, colapso de servidores e colagem de clipboard realizados com sucesso.
