# LLM Payload Role Contract

Data: 2026-06-10
State mirror: [llm-payload-role-contract.stat.md](llm-payload-role-contract.stat.md).

## Propósito

Esta spec define o contrato de papéis e payloads para o runtime de LLM.

Regra central:

- `user` significa somente fala real do usuário;
- `assistant` significa somente resposta do agente;
- `system` / `developer` / equivalente significam somente orientação comportamental, políticas e instruções;
- `tool` / `evidence` / `context` significam somente observação, resultado e dados estruturados;
- diagnóstico técnico vive em `session.context`, `session.state_summary`, `events` e logs;
- fallback técnico só aparece em falha terminal real e deve ser claramente identificado.

## 1. Regra de papéis

- `user` deve conter somente texto originado no usuário humano ou na origem externa que represente fala real do usuário;
- `assistant` deve conter somente a fala final do agente;
- `system` e `developer` devem carregar orientação comportamental, política, contrato e instrução técnica;
- `tool`, `evidence` e `context` devem carregar observações, resultados, artefatos e sinais de execução;
- diagnósticos de parse, fallback, rejeição, stale, recovery e sanitizer não pertencem ao `user`.

## 2. Proibições

O runtime nao deve:

- colapsar `system` em `user`;
- colapsar `tool` ou observação em `user`;
- colapsar diagnóstico em `user`;
- colapsar policy ou orientação em `user`;
- colapsar fallback ou recovery em `user`;
- misturar policy com fala do usuário;
- fingir que contexto técnico foi enunciado pelo usuário;
- criar um canal paralelo de fala comum para dados técnicos.

## 3. Compatibilidade por provider

- OpenAI, OpenRouter, Ollama, LlamaServer e HuggingFace devem preservar `system` / `user` / `assistant` quando o contrato do provider suportar esse formato;
- Gemini deve usar `system_instruction` e mapear histórico para o formato do provider sem transformar observação, política ou diagnóstico em fala do usuário;
- providers limitados devem adaptar contexto técnico em campo técnico equivalente a `system` ou `tool`, nunca como `user`;
- se um provider exigir colapso estrutural, o colapso deve ser explícito e rastreável no adapter do provider, nao em `Session.get_context_for_llm()`.

## 4. Regra de evidência

- tool observation deve ser transportada como tool/evidence/context;
- observação nao deve ser reescrita como se o usuário a tivesse dito;
- `ActionObservation`, attachment delivery, state changes e freshness devem chegar ao agente como evidência, nao como prompt de usuário;
- a síntese final deve saber que está lendo observação e nao intenção do usuário.

## 5. Contrato de `Session.get_context_for_llm()`

- esta função nao pode transformar mensagens não-`user` em `user`;
- se houver necessidade de compatibilidade antiga, o retorno deve preservar metadados de origem e papel;
- consumidores que não suportam papéis ricos devem fazer a adaptação no provider ou no adapter específico;
- o runtime nao deve resolver essa compatibilidade apagando a distinção entre papéis.

## 6. Mapa de impacto mínimo

Funções a revisar no próximo patch:

- `src/core/session.py:get_context_for_llm()`
- `src/services/llm/prompt_composer.py:compose()`
- `src/services/llm/manager.py:generate_intent()`
- `src/services/llm/manager.py:generate_text()`
- `src/core/resolution/llm_resolver.py:resolve()`
- `src/drivers/providers/openai/llm.py:generate_intent()`
- `src/drivers/providers/openrouter/llm.py:generate_intent()`
- `src/drivers/providers/ollama/llm.py:generate_intent()`
- `src/drivers/providers/llama_server/llm.py:generate_intent()`
- `src/drivers/providers/huggingface/llm.py:generate_intent()`
- `src/drivers/providers/gemini/llm.py:generate_intent()`

## 7. Testes mínimos

- mensagem `system` no histórico nao vira `user`;
- observação/tool/evidence nao vira `user`;
- fala real do usuário continua `user`;
- provider payload preserva system/context no canal correto;
- Gemini usa `system_instruction` quando aplicável;
- `get_context_for_llm()` nao polui `user` com papel colapsado;
- nenhum diagnostic/recovery é serializado como `user`.

## 8. Fora do escopo

Esta spec nao altera:

- prompt principal do Atlas;
- políticas agenticas;
- tool choice global;
- sessions/events;
- frontend;
- fallback terminal existente, exceto quanto ao uso correto de papéis e origem.

## Relacionados

- [llm-payload-role-contract.stat.md](llm-payload-role-contract.stat.md)
- [atlas_operating_model.spec.md](atlas_operating_model.spec.md)
- [semantic_decision_boundary.spec.md](semantic_decision_boundary.spec.md)
