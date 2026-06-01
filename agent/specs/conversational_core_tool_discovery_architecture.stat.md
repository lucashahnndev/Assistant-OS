# Conversational Core + Tool Discovery Semantic Architecture Stat

Data da ultima atualizacao: 2026-05-28

## Estado atual

- o fluxo conversacional e a descoberta semantica de tools foram formalizados como contrato;
- o prompt principal deve evitar surface aberta de descoberta/execution;
- `consult_tools` e a unica porta publica de descoberta;
- os demais endpoints seguem apenas como suporte interno;
- a descoberta passa a ser etapa explicita antes da execucao canonica;
- o bibliotecario e um subagente LLM agêntico com acesso a RAG compartilhado e pode usar multiplas rodadas internas;
- o bibliotecario pode expor um conjunto amplo de candidatos antes de chegar a uma decisao;
- a descoberta nao deve ser limitada por uma politica fixa de exposicao de tools.
- o modo de descoberta e configuravel por `tools_discovery.decision_mode`, com `agentic_only` como comportamento padrao e sem fallback; `hybrid` admite fallback deterministico; `deterministic` usa apenas o caminho deterministico; `off` desliga a descoberta para aquele escopo.

## Pendencias

- validar normalizacao de aliases e respostas malformadas em runtime;
- formalizar o contrato operacional do bibliotecario LLM no runtime para manter a separacao estrita entre descoberta e validacao de execucao.
- revisar a UX/config para expor o override por modelo sem tocar na superficie de execucao.

## Evidencias / validacoes

- spec criada na pasta de arquitetura;
- proposta anterior foi promovida para contrato ativo.

## Proximo passo recomendado

- usar esta spec como referencia para qualquer novo fluxo de tools semanticos.
## Relacionados

- [conversational_core_tool_discovery_architecture.spec.md](conversational_core_tool_discovery_architecture.spec.md)
- [../README.md](../overview.md)
