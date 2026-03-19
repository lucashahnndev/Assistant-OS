# Unified Context RAG Architecture Audit (2026-03-13)

## 1. Executive Summary
This report consolidates the full architectural analysis of the current agent context model across prompt construction, live runtime injection, session persistence, memory systems, capability metadata, policies, procedures, and retrieval behavior.

The current system is still primarily prompt-centric. The planner prompt is assembled dynamically in [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L4905) and [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L101), and a large amount of operational knowledge is hardcoded or injected directly into that prompt.

The actual persistent context model is fragmented across:
- session persistence in `data/sessions/*`
- session-native structured state in [session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py#L11)
- semantic Chroma memory in [memory_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/memory/memory_service.py#L11)
- episodic Chroma memory in [episodic_memory.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/memory/episodic_memory.py#L12)
- capability contracts and metadata in [registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py#L13) and [loader.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/loader.py#L21)
- operational policies and task contracts in [policy.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/policy.py#L49) and [worker_task_contract.md](/home/lucas/Documentos/GitHub/Assistant-OS/docs/worker_task_contract.md#L1)

The main redesign conclusion is:
- the kernel prompt should be much smaller
- live situational facts should remain outside RAG
- active task/conversation state should remain session persistence
- persistent recoverable knowledge should move into typed RAG collections
- Chroma should stop being treated as a generic sidecar memory bucket and become part of a unified typed retrieval broker

## 2. Current Context Architecture Overview
The current reasoning path is:
1. driver collects interface/user data and constructs `PrincipalContext`
2. kernel injects driver/user metadata into session context
3. orchestrator builds the planner system prompt
4. LLMResolver pulls compressed recent history + prompt
5. model returns structured `AgentIntent`
6. orchestrator validates and executes actions
7. tool observations are written back into session history and sometimes into episodic Chroma
8. some long history is recursively compressed into `session.summary`

Core entry points:
- input entry: [main.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/main.py#L966)
- initial intent resolution: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L1459)
- planner prompt construction: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L4905)
- prompt assembly: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L101)
- LLM planning call: [llm_resolver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/resolution/llm_resolver.py#L16)

Current architecture is not unified because different context classes are mixed:
- invariant planning rules
- current runtime facts
- active task/session state
- persistent user knowledge
- operational procedures
- capability metadata
- examples

These are currently blended across prompt text, session state, and memory stores without clear ownership.

## 3. Current Prompt Sources
### 3.1 Main Planner Prompt
The main planner prompt is built in [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L4905) and assembled by [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L101).

Always or near-always injected blocks:
- base agent role: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L134)
- response persona scope: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L140)
- instruction pack or fallback language directive: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L149)
- original user directive anchor: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L159)
- presentation directive: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L4964)
- cognitive frame: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L167)
- system/environment facts: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L197)
- TOON internal state: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L203)
- dynamic context envelope: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L209)
- available actions: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L266)
- execution policy: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L296)
- structured output contract: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L327)

### 3.2 Dynamically Injected Planner Context
Current dynamic prompt inputs include:
- `session.summary`: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5047)
- scratchpad file contents: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5048)
- last attachments: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5049)
- session-native relevant memory: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5024)
- TOON deltas: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L4922)
- live location: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5021)
- capability scope/action catalog: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5004)
- cognitive frame from session runtime truth: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5053)
- worker updates and supervisory alerts: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5055)

### 3.3 Prompt Material Currently Hardcoded But Not Kernel-Worthy
These are currently prompt-injected but should not remain permanently injected:
- browser intent class explanation: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L271)
- assistive overlay/vision procedure block: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L283)
- extensive execution-policy prose: [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L296)
- specialist domain heuristics from [specialist_manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/specialist_manager.py#L4)

These are better modeled as retrievable procedure or capability knowledge.

### 3.4 Secondary LLM Prompt Sources
The system has additional prompt-producing flows outside the main planner:
- conversation auto-title prompt: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L1557)
- recursive session summary compression prompt: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L3838)
- conversational recovery prompt: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L4222)
- technical log summarizer prompt: [manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/manager.py#L332)
- browser-control strategic planner prompt: [planner.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/browser_control/planner.py#L445)
- browser-control action planner prompt: [planner.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/browser_control/planner.py#L1670)
- vision locator prompt: [locator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/assistive_overlay/locator.py#L248)
- research link-picking and synthesis prompts: [research_retrieve capability](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/research_retrieve/capability.py#L141)

These also feed reasoning and action selection and therefore belong in the architecture scope.

## 4. Current Session State Sources
### 4.1 Session Persistence
Sessions are persisted in:
- `data/sessions/{session_id}/session.json`
- `data/sessions/{session_id}/chat.json`

Persistence and restore logic:
- save path: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L1094)
- load path: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L1132)

Important current behavior:
- `chat.json` is treated as append-only
- `session.json` stores metadata plus only the last 50 context messages
- session restore source of truth remains `session.json`

### 4.2 Session Object as Active Context Graph
The live session state is defined in [session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py#L11).

Current session fields with context significance:
- `history`
- `context`
- `summary`
- `scratchpad`
- `plan`
- `state_summary`
- `pending_action`
- `drivers_state`
- `task_registry`
- `event_history`
- `active_focus_task_id`
- `tool_health`
- `memory`
- `candidate_store`
- `decision_traces`
- `event_timeline`
- `rejected_memory`
- `audit_trail`
- `last_cognitive_frame_snapshot`
- `intent_agenda`

This is already the de facto live state model. It should remain outside RAG.

### 4.3 Session Context Dictionary
`session.context` is currently an untyped catch-all. It receives:
- `driver_capabilities`
- `principal_context`
- `initial_user_request`
- `last_attachments`
- `active_specialist`
- `planner_tree`
- `cooldowns`
- `last_action_plan`
- `metrics`
- `last_interface`
- `last_sender_id`
- `last_sender_name`
- `last_chat_id`
- `last_chat_name`
- `last_is_group`
- transient runtime flags

Write sites:
- initial intent path: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L1473)
- main processing path: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L1652)
- kernel input bridge: [main.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/main.py#L1018)

This should be normalized into typed session-state submodels in the redesign.

### 4.4 History as Active Context
Conversation history compression for the planner happens in [session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py#L387).

Notable behavior:
- recent turns are kept raw
- older system observations are dropped unless attached/file-bearing
- older turns are compressed using `summary` if available
- system observations are role-shifted into user-formatted observation text

This is active session context, not retrieval memory.

## 5. Current Memory / Chroma Usage
### 5.1 Memory Models That Currently Exist
There are at least six distinct memory/context persistence models:
- recent compressed history in `session.history`
- recursive session summary in `session.summary`
- scratchpad file notes
- session-native accepted memory in `session.memory`
- semantic Chroma facts in `long_term_memory`
- episodic Chroma traces in `episodic_memory`

### 5.2 Current Semantic Chroma Usage
Semantic Chroma is implemented in [memory_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/memory/memory_service.py#L11).

What is stored:
- documents formatted as `"[{category}]: {content}"`
- metadata only includes `category` and `relevance`
- collection name: `long_term_memory`

How it is indexed:
- default Chroma embeddings
- no explicit chunking
- one fact per document
- no user/session/principal/tenant metadata

How it is queried:
- plain `collection.query(query_texts=[query], n_results=n)`
- exposed through memory capabilities and admin API
- not used by the orchestrator’s default prompt construction

How it is injected:
- not automatically injected into planner prompt
- only available if model chooses `memory.recall` or `deep.memory.recall_memory`

Relevant files:
- storage/query: [memory_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/memory/memory_service.py#L23)
- capability access: [memory_management capability](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/memory_management/capability.py#L1)
- deep memory access: [deep_memory capability](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/deep_memory/capability.py#L1)
- admin UI/API: [memory.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/memory.py#L1)

### 5.3 Current Episodic Chroma Usage
Episodic Chroma is implemented in [episodic_memory.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/memory/episodic_memory.py#L12).

What is stored:
- compact JSON episode with clipped user input, thought, action, observation, status, timestamp
- metadata with `action`, `status`, `timestamp`, clipped `user_input`, `hash`
- collection name: `episodic_memory`

How it is indexed:
- one episode per tool observation cycle
- duplicate suppression only through recent hash window
- no environment, capability, session, principal, or policy metadata

How it is queried:
- `recall_episodes(query, n_results)`
- no default orchestrator query path
- not used in automatic planner prompt composition

How it is injected:
- it is not injected into the main planner prompt at all
- it is effectively a diagnostic/sidecar memory today

Write path:
- tool execution loop writes episodes in [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L3023)

### 5.4 Session-Native Memory Governance
The orchestrator also has a non-Chroma memory governance pipeline:
- workers emit `MEMORY_CANDIDATE` via [worker_runtime.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/worker_runtime.py#L302)
- candidates land in `session.candidate_store` via [session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py#L227)
- supervisor evaluates and accepts/rejects via [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5593)
- accepted entries are stored in `session.memory`

This is currently the only memory store automatically eligible for prompt injection through `_retrieve_relevant_memory()`.

### 5.5 Current Retrieval Behavior
The planner’s automatic relevant-memory injection is session-native only:
- retrieval function: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5711)
- source: `session.memory`
- trigger: explicit recall terms or weak continuity heuristics
- max injected memories: 5

This means the current system has no unified retrieval layer. Chroma is not part of the default reasoning loop.

### 5.6 Current Chroma Limitations
Current limitations are structural:
- no typed memory domains
- no ACL/principal filtering
- no user/session ownership metadata
- no provenance beyond minimal metadata
- no reranking
- no freshness handling
- no injection broker
- no unified retrieval API used by planner
- no separation between user memory and agent operational experience

## 6. Current Capability Knowledge Sources
### 6.1 Canonical Capability Metadata
Capability metadata is loaded from:
- `contract.json`
- optional `config.schema.json`
- runtime module/factory
- action metadata and permissions

Loading and validation path:
- [loader.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/loader.py#L139)

Registry path:
- [registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py#L13)

Action metadata fields currently available:
- action id
- title
- description
- handler
- risk level
- permissions
- parameters schema
- side effect
- namespace
- capability id

This is recoverable knowledge and should become a first-class RAG domain instead of being reduced to prompt text.

### 6.2 Capability Catalog Injection
The planner currently sees a filtered compact action catalog, not full capability knowledge:
- action filtering by ACL: [access_controller.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/access_controller.py#L716)
- planner catalog build: [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5130)

Modes include:
- `full`
- `on_demand`
- `compact_hybrid`
- `compact_chat`

The system also supports on-demand catalog inspection:
- `system.control.capabilities.list.*`
- `system.control.capabilities.describe.*`

Implementation:
- [system_control capability](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/system_control/capability.py#L190)

### 6.3 Additional Capability Knowledge Not Used by Planner by Default
Not currently integrated into the default planner context:
- contract `examples`
- capability README files
- manifest files
- category index manifest

Examples:
- [web_retrieve contract examples](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/web_retrieve/contract.json#L80)
- [memory_management README](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/memory_management/README.md)
- [capabilities index manifest](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/index/manifest.json)

These should move into retrievable capability knowledge and examples collections.

## 7. Current Procedures / Policies / Examples
### 7.1 Deterministic Operational Procedures
Important live code procedures exist in:
- access gating and allowed-action filtering: [access_controller.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/access_controller.py#L644)
- plan validation: [plan_validator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/plan_validator.py#L1)
- safety sensitivity/approval logic: [safety_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/safety_service.py#L1)
- supervisor recovery/scheduling/event policy: [policy.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/policy.py#L49)
- worker runtime event contract: [worker_runtime.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/worker_runtime.py#L11)

These should remain executable code. Their explanatory documents can move to RAG, but enforcement should not.

### 7.2 Normative Policy / Control Plane Documents
The strongest operational document in-repo is:
- [worker_task_contract.md](/home/lucas/Documentos/GitHub/Assistant-OS/docs/worker_task_contract.md#L1)

This is policy/procedure knowledge, not kernel prompt material.

### 7.3 Few-Shot and Examples
Examples exist in:
- action contract `examples` fields
- capability READMEs
- some capability-local example flows such as [browser_control/example_flow.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/browser_control/example_flow.py)

Current planner use of examples is minimal to none. They are ideal RAG content.

## 8. Context Classification Matrix
| Context Source | Current Location | Category | Recommendation |
|---|---|---|---|
| Base planner role + JSON contract + core epistemic rules | [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L134) | A. Kernel Prompt | Keep fixed, but shrink |
| Date/time/OS/location/channel/user runtime facts | [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L4907) | B. Situational Context | Keep live-injected |
| Driver capabilities, voice mode, markdown mode, tool health | [main.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/main.py#L1008) | B. Situational Context | Keep live-injected |
| `history`, `summary`, `plan`, `pending_action`, `task_registry`, `drivers_state`, `intent_agenda` | [session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py#L11) | C. Session State | Keep as session persistence |
| `session.context` free-form runtime keys | [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L1652) | C. Session State | Normalize into typed state |
| scratchpad file notes | [scratchpad_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/memory/scratchpad_service.py#L11) | C. Session State | Keep outside RAG |
| `session.memory` accepted facts/preferences | [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5659) | D. User Memory | Migrate to `user_memory` |
| Chroma `long_term_memory` | [memory_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/memory/memory_service.py#L23) | D. User Memory | Redesign and split |
| Chroma `episodic_memory` | [episodic_memory.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/memory/episodic_memory.py#L24) | E. Agent Experience Memory | Redesign as typed experience store |
| `candidate_store`, `rejected_memory`, `audit_trail` | [session.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/session.py#L46) | E. Agent Experience Memory | Keep as governance/audit companion |
| capability contracts / schemas / metadata | [registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py#L108) | F. Capability Knowledge | Index into RAG |
| specialist profiles | [specialist_manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/specialist_manager.py#L4) | F. Capability Knowledge | Move to domain playbooks |
| worker/task contract and other operational docs | [worker_task_contract.md](/home/lucas/Documentos/GitHub/Assistant-OS/docs/worker_task_contract.md#L1) | G. Procedure / Workflow | Index as procedure knowledge |
| supervisor policy, safety policy, ACL explanations | [policy.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/policy.py#L49) | H. Policy / Guardrail Knowledge | Keep enforcement in code, docs in RAG |
| contract examples / README examples | [web_retrieve contract](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/web_retrieve/contract.json#L80) | I. Examples / Demonstrations | Index as examples |
| dead browser state path, unused summary gatherer, duplicated scratchpad fielding | [prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L227), [memory_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/memory/memory_service.py#L113) | J. Legacy / Redundant / Remove | Remove |

## 9. What Must Remain Fixed in Kernel Prompt
The kernel prompt should be reduced to invariant behavior only:
- core role as tool-using planner/supervisor
- mandatory JSON-only structured output contract
- core truthfulness rules
- basic distinction between `reply`, action execution, and error
- minimal language/output scoping rules
- minimal safe tool-use norms such as exact action ids and honesty on failure

What should not remain in the fixed kernel:
- capability-specific procedures
- browser intent class catalogs
- assistive overlay procedures
- specialist profiles
- lengthy continuity/advice/artifact heuristics
- large domain-specific control instructions

## 10. What Must Become Live Situational Context
These should always be injected live and never stored in RAG:
- current date and time
- current OS/runtime environment
- current location signal
- current interface/channel
- current principal identity
- current allowed action scope
- current driver capabilities
- current attachments and active artifacts
- current degraded-tool state
- current worker updates and active alerts

This layer is ephemeral and must reflect the exact current turn.

## 11. What Must Become Session State
These belong to active session persistence, not retrieval:
- recent conversational history
- recursive session summary
- TOON state and planner cursor
- current planner tree
- pending approvals and resumable actions
- active focus task and task registry
- event inbox/history/timelines
- browser/session driver state
- scratchpad
- intent agenda and cognitive frame snapshot

The existing session model already contains most of this. The redesign should formalize it, not move it into RAG.

## 12. What Must Move to RAG
### 12.1 User Memory
Move into typed retrieval:
- stable user preferences
- long-term user facts
- stable project context
- user-specific persistent goals and constraints

Current sources to migrate:
- `session.memory`
- semantic Chroma `long_term_memory`

### 12.2 Agent Experience Memory
Move into typed retrieval:
- action failure/recovery episodes
- environment-specific quirks
- successful recovery patterns
- diagnostic execution traces useful for future planning

Current sources to migrate:
- episodic Chroma
- selected structured decision traces

### 12.3 Capability Knowledge
Move into typed retrieval:
- capability descriptions
- parameter semantics
- auth/source metadata
- risk and side-effect semantics
- capability-specific usage notes

Current sources:
- contracts
- schemas
- READMEs
- manifests

### 12.4 Procedures / Policies / Examples
Move into typed retrieval:
- operational playbooks
- orchestration procedures
- explainable policy documentation
- examples of successful usage

Enforcement remains in code, but knowledge becomes retrievable.

## 13. What Must Be Removed
### 13.1 Dead or Redundant Prompt Paths
- `browser_pages` prompt path is currently dead because orchestrator always passes `browser_pages=[]` in [orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5046)
- `MemoryService.get_all_summaries()` appears unused and should be removed from future architecture consideration

### 13.2 Redundant Memory/State Duplication
- `session.scratchpad` and file scratchpad are duplicated concepts
- the same fact may exist in `history`, `summary`, `toon_deltas`, `session.memory`, and Chroma

### 13.3 Prompt Bloat That Should Leave the Planner Prompt
- specialist hints
- assistive mode procedure block
- browser intent-class explanation block
- most of the execution-policy prose

These should become RAG-backed procedure/capability retrieval or session-state cues.

## 14. Chroma Redesign Recommendations
### 14.1 Problems With the Current Chroma Design
Current Chroma design is too generic:
- one semantic collection for all facts
- one episodic collection for all episodes
- weak metadata
- no typed ownership or scope
- no ACL filters
- no prompt broker
- no unified retrieval routing

### 14.2 Required New Memory Architecture
At minimum separate:
- `user_memory`
- `agent_experience`
- `capability_knowledge`
- `procedures`
- `policies`
- `examples`

### 14.3 Required Metadata for Every Retrieval Chunk
Every stored chunk should carry:
- `doc_type`
- `collection_type`
- `tenant_id`
- `principal_id`
- `session_id`
- `scope`
- `source_file`
- `source_type`
- `capability_id`
- `action_id`
- `created_at`
- `updated_at`
- `trust_level`
- `policy_visibility`
- `embedding_version`

### 14.4 Required Retrieval Broker Behavior
The redesign should introduce a single context broker:
1. classify the turn
2. decide which collections to query
3. apply metadata filters
4. perform similarity retrieval
5. rerank by relevance + freshness + provenance + policy
6. inject only normalized evidence blocks under budget

The planner should never see raw ungoverned Chroma rows.

## 15. Proposed Unified Context Architecture
### 15.1 Layer 1: Kernel Prompt
Minimal fixed prompt containing:
- planner identity
- output contract
- invariant epistemic/tool-use rules

### 15.2 Layer 2: Live Situational Context
Per-turn injected runtime facts:
- environment
- interface
- principal
- ACL-derived scope
- tool health
- active artifacts
- current supervisory signals

### 15.3 Layer 3: Session State
Durable active work context:
- recent history
- summary
- task graph
- pending approvals
- runtime driver state
- scratchpad

### 15.4 Layer 4: Unified Retrieval Layer
Typed retrieval domains:
- user memory
- agent experience
- capability knowledge
- procedures
- policies
- examples

### 15.5 Layer 5: Deterministic Enforcement Layer
Remain in code:
- ACL
- safety checks
- plan validation
- side-effect restrictions
- work lifecycle controls

RAG should support reasoning, not replace enforcement.

## 16. Proposed RAG Collection Taxonomy
| Collection | Purpose | Current Sources |
|---|---|---|
| `user_memory` | stable user/profile/project facts | `session.memory`, `long_term_memory` |
| `agent_experience` | action episodes, failures, recoveries | `episodic_memory`, selected traces |
| `capability_knowledge` | action metadata, schemas, docs | contracts, README, schemas |
| `procedures` | workflows and playbooks | task contracts, procedural docs |
| `policies` | governance and guardrail docs | ACL docs, safety docs, policy docs |
| `examples` | few-shot and usage exemplars | contract examples, README examples, example flows |
| `artifacts_index` | optional artifact retrieval/index | generated reports and work artifacts |

## 17. Migration Priorities
1. Define canonical context ownership boundaries.
2. Introduce typed context broker abstraction before touching retrieval internals.
3. Normalize `session.context` into typed session-state models.
4. Merge `session.memory` and semantic Chroma into typed `user_memory`.
5. Convert episodic Chroma into `agent_experience` with better metadata.
6. Index capability contracts, READMEs, schemas, and examples into capability/procedure/example collections.
7. Remove prompt-heavy capability/procedure prose from the main planner prompt.
8. Add retrieval observability: which collections were queried, why chunks were selected, what was injected.
9. Remove dead legacy context paths and duplicated memory channels.

## 18. Direct Answers to the Key Questions
### 18.1 What context is currently always injected into prompts?
Always or near-always:
- base role
- language/instruction pack
- presentation directive
- system/environment block
- TOON state
- available actions
- execution policy
- structured output contract

### 18.2 What context is currently dynamically injected?
- location
- session summary
- scratchpad
- attachments
- relevant memory from `session.memory`
- TOON deltas
- cognitive frame
- worker updates
- active alerts
- specialist hint
- tool degradation
- driver capabilities and channel mode

### 18.3 What context is currently stored in Chroma?
- semantic long-term facts in `long_term_memory`
- compact action episodes in `episodic_memory`

### 18.4 What memory models currently exist?
- compressed chat history
- recursive session summary
- scratchpad file
- session-native memory candidates and accepted memory
- semantic Chroma
- episodic Chroma

### 18.5 What context is currently duplicated across prompt, memory, and runtime?
- user facts and preferences
- task progress/status
- recent outcomes/errors
- operational hints
- file/project references

### 18.6 What should remain permanently fixed in the kernel prompt?
- invariant planner identity
- JSON output contract
- core truthfulness/tool-use rules

### 18.7 What should move out of prompt injection into RAG?
- capability explanations
- specialist/domain knowledge
- operational procedures
- policy documents
- examples

### 18.8 What should remain outside RAG as live state?
- session/task/work state
- current runtime facts
- ACL scope
- active artifacts and attachments

### 18.9 What should be redesigned in the current Chroma memory architecture?
- type separation
- metadata richness
- ACL-aware filtering
- provenance
- brokered retrieval and reranking
- automatic planner integration

### 18.10 What new RAG collections / knowledge domains should exist?
- `user_memory`
- `agent_experience`
- `capability_knowledge`
- `procedures`
- `policies`
- `examples`
- optional `artifacts_index`

## 19. Final Architectural Conclusion
The current codebase already contains most of the raw ingredients for a strong unified context architecture, but they are distributed across prompt text, session persistence, local deterministic policy code, and disconnected memory stores.

The clean redesign is not "replace prompt injection with Chroma". The correct redesign is:
- shrink the kernel prompt
- formalize live situational injection
- formalize session state as the active execution memory
- introduce typed RAG domains for recoverable knowledge
- keep policy and safety enforcement deterministic in code

That separation is the critical step required to move from the current prompt-heavy architecture to a true unified RAG-driven context model.
