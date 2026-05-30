# Unified Context & RAG Architecture Specification

**System:** Assistant-OS
**Scope:** Context model, memory model, and retrieval architecture
**Goal:** Replace prompt-centric reasoning with a structured context architecture combining minimal kernel prompt, live state, and typed RAG domains.

---

# 1. Architectural Principles

1. **Prompt minimalism**

   * The system prompt must contain only invariant behavioral rules.

2. **State separation**

   * Runtime facts and active task state must not be stored in RAG.

3. **Typed retrieval**

   * RAG must be divided into explicit knowledge domains.

4. **Deterministic enforcement**

   * Security, ACL, safety and execution validation remain in code.

5. **Evidence-based reasoning**

   * The planner receives curated evidence blocks from retrieval, not raw vector results.

---

# 2. Global Context Model

The system context is divided into five layers.

```
Layer 1 — Kernel Prompt
Layer 2 — Situational Context
Layer 3 — Session State
Layer 4 — Retrieval Layer (RAG)
Layer 5 — Deterministic Enforcement
```

---

# 3. Layer Definitions

## 3.1 Kernel Prompt

Contains invariant system behavior.

Properties:

* static
* small
* never retrieved from RAG

Contents:

* agent identity
* structured output contract
* truthfulness rules
* tool-use rules
* reasoning obligations
* minimal safety guidance

Excluded from kernel:

* capability descriptions
* operational procedures
* examples
* domain knowledge
* user memory

---

## 3.2 Situational Context

Ephemeral runtime facts injected per turn.

Properties:

* never stored in RAG
* always live generated

Examples:

* current date/time
* current location signal
* runtime environment
* active interface/channel
* principal identity
* ACL-derived capability scope
* tool health
* active attachments/artifacts
* worker updates
* system alerts

---

## 3.3 Session State

Active execution context of the conversation.

Properties:

* persisted per session
* not retrievable knowledge
* not indexed in RAG

Typical fields:

* recent message history
* session summary
* planner tree
* active task graph
* pending approvals
* scratchpad
* driver state
* task registry
* intent agenda
* event timeline

Session state represents **live work context**, not knowledge.

---

# 4. Retrieval Layer (RAG)

The retrieval layer stores persistent knowledge that can be reused across sessions.

All RAG content must be stored in **typed collections**.

The system defines the following retrieval domains.

---

## 4.1 `user_memory`

Persistent facts about the user.

Examples:

* user preferences
* long-term constraints
* project context
* recurring operational patterns
* personalization signals

Sources:

* promoted session memory
* explicit user instructions
* stable behavioral signals

---

## 4.2 `persona_memory`

Adaptive behavioral tuning of the agent.

Purpose:
Allow the agent to evolve its interaction style.

Examples:

* user communication style preference
* verbosity preference
* technical depth preference
* workflow habits

Important:

```
persona_base → kernel prompt
persona_adaptive → persona_memory
```

---

## 4.3 `capability_knowledge`

Operational knowledge about capabilities.

Sources:

* capability contracts
* capability READMEs
* schemas
* manifests
* parameter semantics

Content examples:

* action semantics
* parameter behavior
* side effects
* capability usage notes
* troubleshooting notes

This domain replaces large capability descriptions in prompts.

---

## 4.4 `procedures`

Operational workflows and playbooks.

Examples:

* multi-step execution flows
* troubleshooting playbooks
* operational recipes
* capability usage patterns
* orchestration procedures

Procedures describe **how tasks are performed**.

---

## 4.5 `policies`

Normative knowledge explaining system rules.

Examples:

* governance documentation
* safety explanation
* ACL documentation
* worker orchestration rules
* operational guidelines

Important:

```
policy enforcement → code
policy explanation → RAG
```

---

## 4.6 `examples`

Retrievable demonstrations.

Examples:

* correct capability usage
* example workflows
* sample plans
* response format examples

Used as few-shot evidence when relevant.

---

## 4.7 `agent_experience`

Agent operational learning.

Sources:

* episodic task traces
* failure/recovery cases
* environment quirks
* execution outcomes

Data stored must be **consolidated experience**, not raw logs.

Pipeline example:

```
task_history
→ analysis
→ experience extraction
→ agent_experience
```

---

## 4.8 `external_knowledge`

User-supplied knowledge bases.

Examples:

* imported documents
* manuals
* PDFs
* external knowledge packs
* scraped content

These sources extend the agent’s knowledge without modifying core system behavior.

---

## 4.9 `custom_knowledge`

Manually curated user training data.

Purpose:
Allow users to teach the agent domain-specific knowledge.

Examples:

* company playbooks
* operational rules
* internal procedures
* custom workflows
* structured instructions

This domain functions as **user-trainable RAG**.

---

# 5. Retrieval Broker

All retrieval must pass through a centralized broker.

Responsibilities:

1. classify the user turn
2. select relevant collections
3. apply metadata filters
4. run similarity search
5. rerank results
6. enforce token budget
7. inject normalized evidence blocks

Planner prompts must never receive raw vector store output.

---

# 6. Required Retrieval Metadata

Each RAG chunk must contain structured metadata.

Required fields:

```
doc_type
collection_type
tenant_id
principal_id
session_id
scope
source_file
source_type
capability_id
action_id
created_at
updated_at
trust_level
policy_visibility
embedding_version
```

This metadata enables:

* ACL filtering
* provenance tracking
* freshness ranking
* policy enforcement

---

# 7. Retrieval Injection Model

Planner context should receive **evidence blocks**, not documents.

Example structure:

```
[EVIDENCE: capability_knowledge]
capability: web_retrieve
action: search
notes: Use when external information is required.
side_effects: network request
risk_level: low
```

Evidence blocks must be:

* normalized
* concise
* source attributed

---

# 8. Non-RAG System Components

The following layers must remain deterministic and outside retrieval.

### Enforcement Layer

Implemented in code:

* ACL checks
* plan validation
* safety service
* capability risk gating
* approval workflows
* worker orchestration

RAG must support reasoning, never replace enforcement.

---

# 9. Learning Pipelines

The system supports three learning flows.

## 9.1 User Memory Promotion

```
session observation
→ candidate memory
→ validation
→ user_memory
```

## 9.2 Agent Experience Extraction

```
task trace
→ episode analysis
→ pattern extraction
→ agent_experience
```

## 9.3 Procedure Discovery

```
repeated task execution
→ pattern detection
→ procedure synthesis
→ procedures
```

---

# 10. Context Assembly Pipeline

Final planner context is constructed in the following order:

```
Kernel Prompt
↓
Situational Context
↓
Session State
↓
Retrieval Evidence (RAG)
↓
Planner Invocation
```

This guarantees clear separation between:

* invariants
* live state
* persistent knowledge

---

# 11. Final Architecture

```
Kernel Prompt
      │
      ▼
Situational Context
      │
      ▼
Session State
      │
      ▼
Retrieval Broker
      │
      ▼
Typed RAG Domains
      │
      ▼
Planner
      │
      ▼
Deterministic Enforcement
```

This model transforms the system from **prompt-centric reasoning** into **retrieval-driven contextual reasoning** while preserving deterministic control over security and execution.
