# ALL_IN_ONE_AGENT_SPEC.md
## Plataforma Open de Agentes de IA — Especificação Consolidada

Este arquivo consolida **todo o contexto arquitetural** definido para a plataforma de agentes de IA:
- arquitetura geral
- execução assíncrona (Main + Workers)
- drivers
- skills (habilidades)
- memória e RAG
- compilação de contexto para LLM
- consumo de APIs

Este documento pode ser usado como:
- contexto base (system prompt) para uma LLM
- especificação técnica do projeto
- referência única para implementação

---

## 1. Princípios Fundamentais

- LLMs **não executam ações**
- LLMs **apenas intencionam**
- Execução ocorre exclusivamente via **drivers**
- Interface conversacional **nunca bloqueia**
- Tarefas longas rodam isoladas
- Arquitetura **open-source**
- Semântica > coordenadas
- Contratos explícitos > improviso

---

## 2. Separação de Responsabilidades

### Main (Conversação Permanente)
- Interage com o usuário
- Roteia intenções
- Inicia e encerra works
- Recebe eventos
- Nunca executa tarefas longas

### Router / Scheduler
- Seleciona skills
- Aplica políticas
- Cria work_id
- Define permissões

### Workers
- Um processo por work
- Executam skills
- Usam drivers
- Emitem eventos
- Mantêm heartbeat
- Reportam PID/handle

---

## 3. Execução Assíncrona

Modelo Supervisor + Workers com mensageria interna.

Eventos padrão:
- job.started
- job.progress
- job.need_input
- job.result
- job.error
- job.heartbeat

Main reage a eventos, nunca espera sincronicamente.

---

## 4. Drivers do Agente

### 4.1 Browser Driver
- Playwright / Selenium
- DOM + Accessibility Tree
- Clique semântico
- Extração estruturada

### 4.2 Vision Driver
- Screenshot
- OCR
- Detecção de UI
- Apenas descreve estado visual

### 4.3 Code Execution Driver
- Shell / Scripts
- Sandbox
- Timeout
- Policy por capability

### 4.4 Memory Driver
- Long-term memory
- RAG
- Embeddings
- Busca semântica

### 4.5 Session / Work Memory Driver
- Estado do work
- Plano
- Resumo incremental
- Fatos confirmados

### 4.6 API Driver
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

Skill não conversa com usuário.  
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

## 6. Memória e RAG

### Tipos de Memória
1. User Profile
2. Global Knowledge Base
3. Work Memory
4. Session Memory

### Estrutura por Work
```
/works/<work_id>/
  meta.json
  state.json
  plan.md
  summary.md
  logs/
  artifacts/
  memory/
```

Prompt é pequeno.  
Memória grande é consultada via tools.

---

## 7. Context Compiler (para LLM)

### Sempre no prompt
- System + Policies
- User Profile
- Session Summary
- Work State
- Skills Index
- Tools disponíveis

### Sob demanda
- RAG results
- Skill spec detalhada
- Logs / artifacts

---

## 8. Governança

- Capabilities por skill
- Sandbox obrigatório
- Kill por PID/handle
- Timeout e watchdog
- Auditoria
- Replay

---

## 9. Filosofia Final

IA decide.  
Sistema executa.  
Interface não trava.  
Trabalhos são isolados.  
Memória é consultável.  
Skills são reutilizáveis.  
Drivers são infraestrutura.

---

## 10. Resultado

Uma **plataforma open de agentes**, modular, controlável e escalável.
