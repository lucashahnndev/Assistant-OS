# BrowserSubagent Internal Contract Stat

Data da ultima atualizacao: 2026-06-09
Spec mirror: [browser-subagent-internal-contract.spec.md](browser-subagent-internal-contract.spec.md).

## Estado atual

- contrato interno do `BrowserSubagent` formalizado como subagente operacional;
- fronteira de autoridade separada de Atlas e do pensamento primário;
- necessidade mapeada de substituir controle por `thought_lower` por campos estruturados.

## Pendencias

- aplicar a migração estrutural no planner;
- adicionar testes de regressão para completion signal, parse diagnostics e fallback legado;
- validar que o histórico do browser permanece namespaceado e não invade pensamento primário do Atlas.

## Evidencias / validacoes

- contrato documentado com fronteira de autoridade explícita;
- mapping de legado e estratégia de migração descritos;
- escopo fora de Atlas principal formalizado.

## Relacionados

- [browser-subagent-internal-contract.spec.md](browser-subagent-internal-contract.spec.md)
- [atlas_operating_model.spec.md](atlas_operating_model.spec.md)
- [semantic_decision_boundary.spec.md](semantic_decision_boundary.spec.md)

## Proximo passo recomendado

- implementar a versão mínima do payload estruturado no `BrowserSubagent` e cobrir com testes antes de remover o fallback textual.
