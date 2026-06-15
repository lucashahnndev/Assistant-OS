# Specs

Este diretório guarda os contratos normativos do projeto alvo que o agente deve ler e obedecer ao alterar o sistema.

## Regras

- cada `.spec` ativa deve ter uma `.stat`;
- `.spec` define contrato durável;
- `.stat` registra estado vivo;
- não usar `.spec` como diário de progresso;
- não usar `.stat` para redefinir contrato;
- isso inclui sistema, arquitetura, comportamento de produto, contratos entre módulos, regras de domínio e políticas operacionais;
- `docs/` é documentação oficial voltada a humanos e pode referenciar specs, mas não é o lugar principal do contrato normativo.

## Convenção

- `nome-do-dominio.spec.md`
- `nome-do-dominio.stat.md`

## Base inicial

- `project.spec.md`
- `project.stat.md`

## Sessions and Events

- `session-event-contract.spec.md`
- `session-event-contract.stat.md`
- `system_sessions.spec.md`
- `system_sessions.stat.md`

## Contrato operacional central

- `atlas_operating_model.spec.md`: contrato ativo do modelo operacional do Atlas para separacao entre semantica do Atlas e execucao do runtime, clarificacao, approval, grounded response e uso de tools/capabilities.
- `atlas_operating_model.stat.md`: estado vivo correspondente do contrato operacional.

## Contrato de Payloads LLM

- `llm-payload-role-contract.spec.md`: contrato de papéis e payloads para preservar `user` como fala real do usuário e manter system/tool/evidence/diagnóstico fora do `user`.
- `llm-payload-role-contract.stat.md`: estado vivo correspondente do contrato de papéis.

## Subagentes Operacionais

- `browser-subagent-internal-contract.spec.md`: contrato interno do `BrowserSubagent` como subagente operacional do browser, com thought somente diagnóstico e controle estruturado de fluxo.
- `browser-subagent-internal-contract.stat.md`: estado vivo correspondente do contrato interno do subagente browser.

## Pontos de apoio

- [../policy/overview.md](../policy/overview.md)
- [../../README.md](../../README.md)

## Relacionados

- [../policy/overview.md](../policy/overview.md)
- [../../docs/overview.md](../../docs/overview.md)
