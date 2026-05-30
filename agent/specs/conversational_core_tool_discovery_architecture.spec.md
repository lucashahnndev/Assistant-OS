# Conversational Core + Tool Discovery Semantic Architecture Spec

## 1. Objective

This specification separates the Assistant-OS reasoning flow into four clear stages:

- conversational core;
- semantic tool discovery;
- canonical action execution;
- provider-specific normalization.

The goal is to reduce action-id hallucinations, remove dependency on a compact action surface in the main prompt, and make behavior more predictable across local and remote providers.
The discovery stage is intentionally modeled as an LLM bibliotecário with shared RAG access so it can reason agentically about tools, compare alternatives, and avoid premature tool bias.

---

## 2. Architectural Principle

The model must not choose specific tools on the first pass.

It must first choose among:

- conversing;
- remembering;
- attaching or formatting;
- consulting tools through the single canonical discovery entrypoint;
- asking for clarification;
- or, as a last resort, executing a validated discovered action.

The main prompt should carry only what is needed for:

- conversation;
- memory;
- attachments;
- persona;
- response policies;
- tool discovery.

The execution surface for every domain must not be dumped into the main prompt.

---

## 3. Target Architecture

### 3.1 Layer 1: Conversational Core

Responsible for:

- answering simple messages;
- preserving persona;
- keeping short-term conversational memory;
- deciding when to consult tools;
- producing `reply` without tool use when the turn is clearly conversational.

Allowed prompt content for this layer:

- `reply`;
- relevant memory or state;
- attachments;
- conversation policies;
- explicit instruction to consult tools when needed.

Content that must not appear in the main prompt:

- expanded domain action surfaces;
- full capability lists;
- specific execution ids the user did not ask for.

### 3.2 Layer 2: Semantic Tool Discovery

When the agent needs to act outside the conversational core, it calls the single canonical discovery action:

- `consult_tools`.

This action does not execute the final capability.
It launches the "bibliotecário" subagent, which is itself an LLM worker with a constrained prompt and shared RAG access.
The bibliotecário may use:

- the canonical discovery index as a starting surface;
- shared RAG about prior tool success/failure, cost, latency, and domain fit;
- the current request only, not the full conversation transcript;
- multiple internal turns when needed to compare candidates and disambiguate intent;
- broad candidate exposure when useful, instead of prematurely collapsing the search space.

The discovery strategy is configurable through a `tools_discovery.decision_mode` setting with model-scoped overrides. The default operational mode is `agentic_only`, meaning the bibliotecário LLM is solely responsible for discovery and choice of candidate set. In this contract:

- `agentic_only` is strict and has no fallback path;
- `hybrid` may fall back to a deterministic discovery path if agentic discovery does not produce a usable candidate set;
- `deterministic` uses only the deterministic discovery path;
- `off` disables tool discovery for that scope.

These modes govern discovery only and must never be mixed into execution validation.

Its job is to return a relevant structured candidate set with enough metadata for a conscious choice, while avoiding premature narrowing that would bias the agent toward a small repeated tool set.
No other public discovery verb should be presented to the model as an alternative entrypoint.

### 3.3 Layer 3: Canonical Execution

After discovery, the model chooses a specific action among the returned candidates.

At this stage:

- `CapabilityRegistry` remains the canonical source;
- the action must be exact;
- aliases may be normalized, but must be auditable;
- execution outside the discovered scope must be rejected or re-routed.
The bibliotecário is agentic and deliberative, but the kernel remains the execution gate.

### 3.4 Layer 4: Provider Normalization

Each provider must handle its own quirks:

- natural aliases;
- malformed fields;
- models that return `thought` without `response_text`;
- models that invent a plausible but non-canonical action.

This layer must:

- normalize aliases;
- provide `response_text` fallback when appropriate;
- record mappings and repairs;
- never silently hide a serious structural violation.

---

## 4. Proposed Contract

### 4.1 Intent contract

The main intent contract should stay compact:

- `thought`;
- `action`;
- `params`;
- `response_text`;
- `attachments`;
- `state_summary`;
- `plan` when needed.

### 4.2 Action rules

- `reply` is always allowed.
- `consult_tools` is allowed as a discovery action.
- `capabilities.list*` and `capabilities.describe*` remain internal support APIs and must not be promoted as alternate public discovery entrypoints.
- specific domain actions do not enter the main prompt as an open discovery surface.
- the main prompt should expose only `reply` and `consult_tools`, not the full execution surface.
- specific actions are released only after discovery.
- any action outside the canonical discovery index must be normalized or rejected with a clear diagnostic.

### 4.3 Discovery contract

Suggested shape for the discovery action:

```json
{
  "action": "consult_tools",
  "params": {
    "query": "clima atual",
    "intent": "task_execution",
    "domain_hints": ["weather"],
    "top_k": 5
  }
}
```

Expected response:

```json
{
  "count": 1,
  "items": [
    {
      "action_id": "weather.control.get",
      "capability_id": "weather_control",
      "namespace": "weather.control",
      "title": "Get current weather",
      "summary": "Fetch current weather conditions",
      "description": "Fetch current weather conditions",
      "risk_level": "low",
      "setup_ready": true,
      "source": "retrieval_offer",
      "reason": "Best semantic match for current weather"
    }
  ],
  "primary_action_id": "weather.control.get",
  "primary_score": 0.91,
  "discovery_source": "retrieval_offer",
  "broker_domains": ["weather"],
  "format": "legacy",
  "audience": "ai"
}
```

---

## 5. Reusable System Structure

The system already has a strong base for this change:

- `CapabilityRegistry.list_actions()` as canonical execution index;
- `CapabilityRegistry.resolve_action_id()` as normalizer;
- `CapabilityRegistry.list_retrieval_offers()` as a declarative offer index;
- `ContextBroker` as classifier and evidence router;
- `PromptComposer` as prompt-contract assembler;
- `LLMResolver` as the guardrail between intent and execution;
- shared RAG about tool performance, suitability, and prior outcomes;
- a bibliotecário LLM worker that can reason over those inputs in one or more turns.

The change is therefore a responsibility reorganization plus a new LLM-mediated discovery layer, not a rewrite of the core.

---

## 6. Target Flow

### 6.1 Conversational turn

1. User asks something simple, such as "what is your name?".
2. The broker classifies it as conversational.
3. The prompt contains only conversational context and persona.
4. The model returns `reply`.
5. The executor answers without a tool.

### 6.2 Action turn

1. User asks something like "how is the weather?".
2. The broker identifies execution need.
3. The model first emits `consult_tools`.
4. The bibliotecário LLM reads the request, shared RAG, and discovery/index surface.
5. The bibliotecário may take one or two internal turns to compare candidates and prior tool outcomes.
6. The bibliotecário returns a structured candidate set with its own ordering and concise reasons.
7. The main model chooses the canonical action, such as `weather.control.get`.
8. The executor validates and runs the capability.
9. The result returns to the user with clear state.

### 6.3 Provider alias turn

1. The local provider returns something like `weather.get_current_conditions`.
2. The normalizer maps it to `weather.control.get`.
3. The system logs the alias used.
4. Execution continues without breaking, while the log preserves the repair.

---

## 7. Required System Adjustments

### 7.1 `PromptComposer`

The `PromptComposer` must stop placing a compact execution surface block in the main prompt.
It should keep only conversational guidance and the explicit discovery entrypoint (`consult_tools`), never a broad execution surface or alternate discovery verbs.
It must not expose a fixed top-3 tool exposure policy as if it were the only discovery mechanism; the bibliotecário owns the discovery reasoning layer.
The discovery decision mode may be surfaced through configuration, but the main prompt should still expose only the discovery entrypoint and never the mode as an execution surface.

### 7.2 `LLMResolver`

The resolver remains the guardrail between intent and execution, but it should enforce the discovery-first flow and must not infer tools by heuristic text matching or silently promote alternate discovery verbs.
It should treat discovery output as a constrained proposal, not a hardcoded ranking truth source.

---

## 8. Acceptance Criteria

- the model can reply conversationally without choosing a domain action;
- discovery is explicit before execution;
- `consult_tools` is the only public discovery entrypoint;
- canonical actions are required for execution;
- provider aliases are visible and auditable;
- malformed outputs are normalized or rejected with a clear diagnostic.
- the bibliotecário can inspect shared RAG and prior tool outcomes before choosing a candidate set;
- the discovery layer may take more than one turn when ambiguity or tradeoff comparison is useful;
- discovery must not be locked to a fixed exposure policy or fixed-size shortlist.
