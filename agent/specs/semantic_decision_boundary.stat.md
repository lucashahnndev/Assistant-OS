# Semantic Decision Boundary Stat

Data da ultima atualizacao: 2026-05-29

## Estado atual

- nova spec criada para fixar a fronteira entre orquestração técnica e decisão semântica;
- a convenção agora explicita que heurísticas e reflexes nao podem virar decisão final por linguagem natural;
- a fronteira documental ficou pronta para sustentar a Fase 1/Fase 2 do `IntentClassifier`.
- a Fase 1/Fase 2 começou no runtime: `IntentClassifier` agora emite um pacote de sinais fracos com ponte de compatibilidade para `ContextIntent`.
- a Fase 3 do `RetrievalRouter` tambem começou no runtime: o roteador agora devolve sinais de rota, candidatos e pesos junto com `RetrievalTarget` compatível.
- a Fase 4 de reflexes começou no runtime: shortcuts de linguagem natural para tools/capabilities foram desativados; permanecem apenas comandos explícitos existentes, eventos internos e fallback técnico.

## Pendencias

- alinhar documentos correlatos para referenciar esta spec quando a fronteira agentica for revisada;
- revisar o runtime depois para garantir aderencia ao contrato semântico aqui definido.

## Evidencias / validacoes

- spec criada em `agent/specs/`;
- as specs antigas podem agora ser avaliadas contra esta fronteira como referência normativa principal.
- o broker ja consome a classificacao como `legacy_intent` + `hints`, em vez de tratar o classificador como autoridade semantica final.
- o broker tambem passou a consumir `route_signals.targets`, mantendo a lista como compatibilidade enquanto a semantica fica fora do roteador.
- reflex dispatch agora fica restrito ao fluxo operacional/compatível, sem atalho de intenção natural-language para ferramentas.

## Proximo passo recomendado

- usar esta spec como contrato base para reduzir hardcode semantico em intent, routing, reflexes e overrides;
- continuar a evolucao do retrieval e revisar a necessidade de compatibilidade legada nos reflexes em fases futuras.
