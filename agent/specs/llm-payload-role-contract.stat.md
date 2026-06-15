# LLM Payload Role Contract Stat

Data da ultima atualizacao: 2026-06-10
Spec mirror: [llm-payload-role-contract.spec.md](llm-payload-role-contract.spec.md).

## Estado atual

- contrato de papéis e payloads definido;
- fronteira reforçada para impedir colapso de `system`, `tool`, `evidence` e diagnóstico em `user`;
- lista de funções candidatas à revisão mapeada.

## Pendencias

- revisar `Session.get_context_for_llm()` para parar de colapsar papéis não-user em `user`;
- mover qualquer compatibilidade residual para adapters/providers específicos;
- cobrir com testes os casos de system, tool/evidence, diagnostics e Gemini/system_instruction;
- validar que fallback técnico continua terminal e nao vira texto operacional comum.

## Evidencias / validacoes

- contrato de papéis formalizado em spec;
- compatibilidade por provider descrita;
- impacto mínimo mapeado para o próximo patch.

## Relacionados

- [llm-payload-role-contract.spec.md](llm-payload-role-contract.spec.md)
- [atlas_operating_model.spec.md](atlas_operating_model.spec.md)
- [semantic_decision_boundary.spec.md](semantic_decision_boundary.spec.md)

## Proximo passo recomendado

- implementar a migração mínima em `Session.get_context_for_llm()` e nos adapters que hoje dependem do colapso legado.
