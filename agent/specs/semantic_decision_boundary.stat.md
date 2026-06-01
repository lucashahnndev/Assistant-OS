# Semantic Decision Boundary Stat

Data da ultima atualizacao: 2026-05-29

## Estado atual

- nova spec criada para fixar a fronteira entre orquestração técnica e decisão semântica;
- a convenção agora explicita que heurísticas e reflexes nao podem virar decisão final por linguagem natural;
- a fronteira documental ficou pronta para sustentar a Fase 1/Fase 2 do `IntentClassifier`.
- a Fase 1/Fase 2 começou no runtime: `IntentClassifier` agora emite um pacote de sinais fracos com ponte de compatibilidade para `ContextIntent`.
- a Fase 3 do `RetrievalRouter` tambem começou no runtime: o roteador agora devolve sinais de rota, candidatos e pesos junto com `RetrievalTarget` compatível.
- a Fase 4 de reflexes começou no runtime: shortcuts de linguagem natural para tools/capabilities foram desativados; permanecem apenas comandos explícitos existentes, eventos internos e fallback técnico.
- a Fase 5 de overrides browser/media começou no runtime: o orchestrator deixou de trocar action por heurística textual em queries nao interativas e playback do YouTube; sobraram apenas hints/validacao tecnica e reparo de `youtube.retrieve.get` quando a action ja foi escolhida.
- a nova spec `atlas_operating_model.spec.md` passou a complementar esta fronteira com um contrato operacional explicito para o proprio agente.

## Pendencias

- alinhar documentos correlatos para referenciar esta spec quando a fronteira agentica for revisada;
- revisar o runtime depois para garantir aderencia ao contrato semântico aqui definido.

## Evidencias / validacoes

- spec criada em `agent/specs/`;
- as specs antigas podem agora ser avaliadas contra esta fronteira como referência normativa principal.
- o broker ja consome a classificacao como `legacy_intent` + `hints`, em vez de tratar o classificador como autoridade semantica final.
- o broker tambem passou a consumir `route_signals.targets`, mantendo a lista como compatibilidade enquanto a semantica fica fora do roteador.
- reflex dispatch agora fica restrito ao fluxo operacional/compatível, sem atalho de intenção natural-language para ferramentas.
- os overrides semanticos de browser/media foram rebaixados: o orchestrator nao troca mais `browser.control.run` por actions de busca nem fabrica `browser.control.run` a partir de texto; a policy agora preserva apenas validacao tecnica e assistive hinting.

## Proximo passo recomendado

- usar esta spec como contrato base para reduzir hardcode semantico em intent, routing, reflexes e overrides;
- continuar a evolucao do retrieval e revisar a necessidade de compatibilidade legada nos reflexes em fases futuras.
- usar `atlas_operating_model.spec.md` como orientacao primaria para clarificar quando agir, quando perguntar e quando deixar o runtime gatear.

## Registros de commits recentes

- `fe9e2eac` `feat: tighten operating model and factual grounding prompt`
  - resumo: reforcou o `PromptComposer` com regras mais duras contra clarificacao como fuga, limitacao generica e claims factuais sem `ActionObservation` fresca;
  - validacao: `python3 -m py_compile src/services/llm/prompt_composer.py tests/minimal/test_prompt_composer_operating_model.py` e `PYTHONPATH=src:. env/bin/python -m pytest tests/minimal/test_prompt_composer_operating_model.py -q`;
  - falhas conhecidas fora do escopo: os testes antigos de alias/Obsidian em `tests/minimal/test_mcp_llm_alias_and_recovery.py` seguem preexistentes e nao afetam este bloco.
## Relacionados

- [semantic_decision_boundary.spec.md](semantic_decision_boundary.spec.md)
- [../README.md](../overview.md)
