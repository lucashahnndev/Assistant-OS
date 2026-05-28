# Context Broker Phase 1 Implementation Report

> Historical report. This implementation note reflects an earlier broker stage and may differ from the current discovery-first contract.

## 1. Executive Summary

Phase 1 introduced a production-ready Context Broker subsystem that classifies turn intent, routes retrieval by logical domain, normalizes evidence into typed prompt-ready units, and injects that evidence into the orchestrator prompt assembly path.

The implementation is infrastructure-first:

- it does not perform the full RAG migration
- it does not remove existing prompt/state/session injections
- it keeps current behavior backward-compatible
- it creates a clean broker layer that future typed collections can plug into

## 2. New Context Subsystem Files

- `src/services/context/__init__.py`
- `src/services/context/models.py`
- `src/services/context/intent_classifier.py`
- `src/services/context/retrieval_router.py`
- `src/services/context/evidence_builder.py`
- `src/services/context/broker.py`

## 3. Models Introduced

The subsystem adds typed broker-flow models in `src/services/context/models.py`:

- `ContextIntent`
  - enum for turn-level context intent classification
  - current values: `task_execution`, `capability_lookup`, `policy_lookup`, `memory_lookup`, `troubleshooting`, `conversational`, `general_knowledge`
- `RetrievalTarget`
  - logical retrieval target descriptor
  - fields: `domain`, `priority`, `max_results`, `filters`, `active`, `notes`
- `EvidenceItem`
  - normalized evidence unit for prompt use
  - fields: `domain`, `title`, `content`, `source`, `metadata`, `score`, `timestamp`, `provenance`
- `ContextDiagnostics`
  - broker observability payload
  - fields: `intent`, `selected_targets`, `evidence_domains`, `evidence_count`, `classifier_notes`, `retrieval_notes`
- `ContextBundle`
  - final broker output passed into prompt composition
  - fields: `situational_context`, `session_context`, `evidence_items`, `diagnostics`

## 4. Intent Classification Design

`IntentClassifier` uses deterministic heuristics only.

Current signals:

- pending approval/action state biases toward `task_execution` or `policy_lookup`
- explicit capability/tool/how-to language maps to `capability_lookup`
- rule/permission/approval language maps to `policy_lookup`
- memory/remember/last-time language maps to `memory_lookup`
- error/debug/failure/problem language maps to `troubleshooting`
- fact/explain/who-is language maps to `general_knowledge`
- action-oriented or multi-step phrasing maps to `task_execution`
- everything else falls back to `conversational`

The classifier returns both the chosen intent and lightweight classifier notes for diagnostics.

## 5. Retrieval Routing Design

`RetrievalRouter` maps each intent to logical retrieval domains without embedding Chroma-specific behavior.

Implemented Phase 1 logical domains:

- `user_memory`
- `persona_memory`
- `capability_knowledge`
- `procedures`
- `policies`
- `examples`
- `agent_experience`
- `external_knowledge`
- `custom_knowledge`

Phase 1 only activates the domains that have safe retrieval adapters today. Stubbed domains remain visible in the router with `active=False` and notes indicating Phase 1 status.

## 6. Evidence Builder Design

`EvidenceBuilder` isolates normalization between retrieval and prompt assembly.

Responsibilities:

- converts raw retrieval rows into `EvidenceItem`
- clips content to bounded prompt-friendly size
- preserves domain/source/provenance/score metadata
- provides a reusable prompt formatting path for `[EVIDENCE: domain]` blocks

This ensures the planner receives normalized evidence instead of raw store rows.

## 7. Orchestrator Integration Changes

`src/core/orchestrator.py` now:

- instantiates `ContextBroker` during orchestrator setup
- runs the broker before prompt composition
- passes current user input, session, capability registry, allowed actions, situational context, and session context into the broker
- stores broker diagnostics under `session.context["last_context_broker"]`
- continues to preserve existing `relevant_memory`, session summary, scratchpad, and other prompt injections

This keeps the new path additive rather than disruptive.

## 8. Prompt Composer Integration Changes

`src/services/llm/prompt_composer.py` now accepts an optional `context_bundle`.

If broker evidence exists, prompt composition adds a bounded optional section:

- `[BROKER EVIDENCE]`

Each evidence item is rendered as:

- `[EVIDENCE: <domain>]`
- `title: ...`
- `content: ...`
- `source: ...`
- optional `score`

If no broker evidence is present, prompt behavior remains unchanged.

## 9. Phase 1 Retrieval Sources Used

The broker currently uses a hybrid temporary retrieval layer:

- `user_memory`
  - sourced from `session.memory`
- `persona_memory`
  - sourced from safe session context fields such as `response_persona` and `user_language`
- `capability_knowledge`
  - sourced from `CapabilityRegistry.get_focus_actions()` plus `get_action_metadata()`
- `agent_experience`
  - sourced from session-native execution state:
    - `session.state_summary["last_error"]`
    - failure/block/slow entries from `session.task_registry`

This gives Phase 1 a real retrieval flow without binding the broker to the legacy Chroma schema.

## 10. Current Limitations / Stubbed Domains

The following domains are present in routing but intentionally not implemented yet:

- `procedures`
- `policies`
- `examples`
- `external_knowledge`
- `custom_knowledge`

These are surfaced as inactive targets in diagnostics so routing behavior is visible now and future adapters can be added without changing broker shape.

## 11. Observability Added

Observability is exposed through `ContextBundle.diagnostics` and mirrored into session context.

Captured fields:

- classified intent
- selected retrieval targets
- evidence domains included
- evidence item count
- classifier notes
- retrieval notes including inactive/unhandled/error states and per-domain counts

The broker also logs a structured per-turn summary line with session, intent, targets, domains, and evidence count.

## 12. Risks / Follow-up Work

- policy and procedure retrieval are still stubbed, so policy-oriented questions still mostly rely on existing prompt rules
- capability evidence is lexical and metadata-based, not yet document/chunk-based
- user memory retrieval is still session-memory backed and not yet unified with future typed persistent stores
- some retrieval information can overlap with existing `relevant_memory` injection until later prompt diet work reduces duplication
- diagnostics are stored in session context for inspectability, which is useful now but may need a dedicated tracing sink later

## 13. Recommended Phase 2

Recommended next steps:

1. add real typed adapters for `policies`, `procedures`, and `examples`
2. introduce collection-backed retrieval interfaces behind the current logical domains
3. migrate capability knowledge from metadata-only retrieval to chunked typed documents
4. replace the old ad hoc memory injection path with broker-owned memory evidence once parity is confirmed
5. add dedicated tracing/metrics views for broker diagnostics and prompt token impact
6. start prompt diet work by trimming duplicated legacy context blocks after evidence coverage is stronger
