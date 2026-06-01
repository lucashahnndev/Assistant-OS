# ALL_IN_ONE_AGENT_SPEC.md
## Plataforma Open de Agentes de IA - Especificacao Consolidada

> Documento legado. Esta especificacao foi superada pelo contrato discovery-first ativo em `agent/specs/conversational_core_tool_discovery_architecture.spec.md`.

Este arquivo consolida **todo o contexto arquitetural** definido para a plataforma de agentes de IA:
- arquitetura geral
- execucao assincrona (Main + Workers)
- drivers
- skills (habilidades)
- memoria e RAG
- compilacao de contexto para LLM
- consumo de APIs

Este documento pode ser usado como:
- contexto base (system prompt) para uma LLM
- especificacao tecnica do projeto
- referencia unica para implementacao

---

## 1. Principios Fundamentais

- LLMs **nao executam acoes**
- LLMs **apenas intencionam**
- Execucao ocorre exclusivamente via **drivers**
- Interface conversacional **nunca bloqueia**
- Tarefas longas rodam isoladas
- Arquitetura **open-source**
- Semantica > coordenadas
- Contratos explicitos > improviso

---

## 2. Separacao de Responsabilidades

### Main (Conversacao Permanente)
- Interage com o usuario
- Roteia intencoes
- Inicia e encerra works
- Recebe eventos
- Nunca executa tarefas longas

### Router / Scheduler
- Seleciona skills
- Aplica politicas
- Cria work_id
- Define permissoes

### Workers
- Um processo por work
- Executam skills
- Usam drivers
- Emitem eventos
- Mantem heartbeat
- Reportam PID/handle

---

## 3. Execucao Assincrona

Modelo Supervisor + Workers com mensageria interna.

Eventos padrao:
- job.started
- job.progress
- job.need_input
- job.result
- job.error
- job.heartbeat

Main reage a eventos, nunca espera sincronicamente.

---

## 4. Drivers do Agente

### 4.1. Browser Driver
- Playwright / Selenium
- DOM + Accessibility Tree
- Clique semantico
- Extracao estruturada

### 4.2. Vision Driver
- Screenshot
- OCR
- Deteccao de UI
- Apenas descreve estado visual

### 4.3. Code Execution Driver
- Shell / Scripts
- Sandbox
- Timeout
- Policy por capability

### 4.4. Memory Driver
- Long-term memory
- RAG
- Embeddings
- Busca semantica

### 4.5. Session / Work Memory Driver
- Estado do work
- Plano
- Resumo incremental
- Fatos confirmados

### 4.6. API Driver
- REST / GraphQL / gRPC
- Auth desacoplada
- Rate-limit
- Retry
- Schemas validados

---

## 5. Skills (Habilidades)

Skill = "o que fazer"
Driver = "como fazer"

Tipos:
- Atomic
- Composite
- Human-in-the-loop

Skill nao conversa com usuario.
Ela emite eventos.

### Skill Contract (resumo)
- name
- description
- input_schema
- output_schema
- capabilities
- policy
- events

---

## 6. Memoria e RAG

### Tipos de Memoria
1. User Profile
2. Global Knowledge Base
3. Work Memory
4. Session Memory

### Estrutura por Work
```text
/works/<work_id>/
  meta.json
  state.json
  plan.md
  summary.md
  logs/
  artifacts/
  memory/
```

Prompt e pequeno.
Memoria grande e consultada via tools.

---

## 7. Context Compiler (para LLM)

### Sempre no prompt
- System + Policies
- User Profile
- Session Summary
- Work State
- Skills Index
- Tools disponiveis

### Sob demanda
- RAG results
- Skill spec detalhada
- Logs / artifacts

---

## 8. Governanca

- Capabilities por skill
- Sandbox obrigatorio
- Kill por PID/handle
- Timeout e watchdog
- Auditoria
- Replay

---

## 9. Filosofia Final

IA decide.
Sistema executa.
Interface nao trava.
Trabalhos sao isolados.
Memoria e consultavel.
Skills sao reutilizaveis.
Drivers sao infraestrutura.

---

## 10. Resultado

Uma **plataforma open de agentes**, modular, controlavel e escalavel.

## Relacionados

- [../README.md](../README.md): entrada geral da documentacao humana.
- [../architecture/README.md](../architecture/README.md): contrato tecnico atual que substituiu esta consolidacao.
- [../../agent/specs/conversational_core_tool_discovery_architecture.spec.md](../../agent/specs/conversational_core_tool_discovery_architecture.spec.md): contrato discovery-first que superou esta especificacao.
- [../../agent/specs/atlas_operating_model.spec.md](../../agent/specs/atlas_operating_model.spec.md): contrato operacional moderno que substitui a governanca descrita aqui.
