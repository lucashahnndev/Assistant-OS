# Context Broker Phase 2C Implementation Report

> Historical report. This phase note reflects an earlier broker rollout and may not match the current discovery-first contract.

## 1. Executive Summary

Phase 2C activates the `policies` retrieval domain and introduces a deterministic cross-domain reranker for broker evidence selection.

This phase adds:

- real ingestion for explanatory policy knowledge
- real policy retrieval
- query-aware routing for policy relevance
- deterministic reranking across active domains
- richer broker diagnostics for rerank reasoning

The implementation remains backward-compatible and additive:

- deterministic enforcement stays in code
- the broker continues to provide compact evidence bundles
- prompt composition remains bounded
- missing retrieval results degrade gracefully

## 2. Policies Ingestion Design

Policy ingestion is implemented in:

- `src/services/context/ingestion/policy_ingestor.py`

The ingestor scans explanatory policy/governance sources from the repository, including:

- `agent/specs/worker_task_contract.spec.md`
- `docs/plans/permission_groups_planner.md`
- `docs/decisions/driver_ioc_restructure_approval.md`
- `agent/specs/skill_contract.spec.md`

It explicitly ignores raw enforcement code and only ingests explanatory rule text.

Policy ingestion behavior:

1. scans known governance documents
2. splits markdown by heading
3. selects sections that look policy-like using explicit rule/permission/approval/contract markers
4. normalizes the selected content
5. chunks long sections while preserving section identity
6. stores the chunks in the `policies` collection
7. keeps a manifest to avoid unnecessary rebuilds

Policy chunks are grouped by derived `policy_id` and preserve section/rule-group metadata for later retrieval and reranking.

## 3. Policy Retrieval Adapter Implementation

The policy retrieval adapter is implemented in:

- `src/services/context/retrieval/policies.py`

Behavior:

- ensures policy ingestion has run
- performs vector search against the `policies` collection
- groups matching chunks by policy identity
- normalizes results into compact rule-summary evidence

Example normalized shape:

- `title`: policy section title
- `content`: compact summary with `rule_group` and `scope`
- `metadata`: policy visibility, rule group, source and tags

This keeps policy evidence short enough for the broker evidence lane while still giving the planner meaningful explanatory rules.

## 4. Retrieval Router Changes

`src/services/context/retrieval_router.py` now includes `policies` in explicit routes.

Current policy-aware routing:

- `policy_lookup`
  - `policies`
  - `capability_knowledge`
- `task_execution`
  - `procedures`
  - `capability_knowledge`
  - `user_memory`
  - `policies` as query-activated low priority
- `capability_lookup`
  - `capability_knowledge`
  - `examples`
  - `policies` as query-activated low priority
- `troubleshooting`
  - `user_memory`
  - `procedures`
  - `examples`
  - `capability_knowledge`
  - `policies`

The router remains explicit and deterministic. Outside `policy_lookup`, `policies` becomes active only when the user query contains policy/governance/approval-style signals.

## 5. Reranker Design and Scoring Rules

The reranker is implemented in:

- `src/services/context/reranker.py`

It is deterministic and explainable. It scores evidence using:

1. route priority
2. retrieval score
3. trust level
4. freshness
5. domain relevance to current intent
6. policy visibility

Scoring rules are explicit and weighted. The reranker also applies bounded per-domain caps so that:

- `policies` do not dominate the prompt
- `examples` stay small
- `procedures` and `capability_knowledge` remain balanced

The reranker returns:

- selected evidence items
- compact rerank trace lines showing the factors used for each chosen item

## 6. Context Broker Changes

`src/services/context/broker.py` now:

- initializes the `policies` retrieval handler
- routes with query-aware policy activation
- sends all evidence through the dedicated reranker
- records richer diagnostics including:
  - queried domains
  - raw result counts per domain
  - injected evidence counts per domain
  - rerank summary for selected items

It also continues to degrade safely if retrieval handlers fail or return nothing.

## 7. Prompt Composer Integration Changes

No structural rewrite was needed in the prompt composer.

The existing `[BROKER EVIDENCE]` block continues to work, and policy evidence now appears there as compact domain-tagged evidence when selected by the broker.

The evidence path remains bounded:

- broker retrieval limits constrain candidates
- reranker limits final evidence selection
- prompt rendering still caps evidence items

This preserves backward compatibility and prevents policy content from crowding out the rest of the prompt.

## 8. Metadata Schema Introduced

`RAGChunkMetadata` in `src/services/context/models.py` was extended with policy-specific metadata:

- `policy_id`
- `policy_visibility`
- `rule_group`
- `scope_hint`

These build on the existing shared metadata fields such as:

- `doc_type`
- `collection_type`
- `source_file`
- `source_type`
- `section`
- `tags`
- `created_at`
- `updated_at`
- `trust_level`
- `embedding_version`

`ContextDiagnostics` was also extended with:

- `rerank_summary`

This makes the broker’s final selection easier to inspect during later tuning.

## 9. Tests Added

New tests:

- `tests/context/test_policy_ingestion.py`
- `tests/context/test_reranker.py`
- `tests/context/test_context_broker_phase2c.py`
- `tests/context/test_evidence_injection_phase2c.py`

Updated/validated existing tests:

- `tests/context/test_context_broker_phase2b.py`
- `tests/context/test_context_broker_retrieval.py`
- `tests/minimal/test_context_broker_phase1.py`
- prompt composer tests

Covered behavior includes:

- policy ingestion and chunk metadata
- query-driven routing for `policies`
- reranker ordering behavior
- safe reranker degradation with sparse metadata
- broker policy retrieval and diagnostics
- prompt rendering for policy evidence

## 10. Current Limitations

- policy ingestion is still section-based and may miss some policy-relevant prose buried in non-obvious docs
- reranking is deterministic and readable, but still simple; it is not a full query planner
- policy visibility is currently metadata-driven and not tied to a richer principal/tenant visibility model
- some policy guidance still exists in legacy prompt text and has not yet been migrated out
- non-scope domains (`agent_experience`, `external_knowledge`, `custom_knowledge`) remain inactive

## 11. Recommended Phase 3

Recommended next steps for Phase 3:

1. activate `agent_experience` as a retrievable operational-learning domain
2. add richer domain-aware retrieval fusion and duplicate suppression across all active domains
3. continue migrating large hardcoded prompt policy/procedure prose into typed retrieval
4. introduce richer broker observability around token cost and evidence usefulness
5. begin the first careful prompt-diet pass once retrieval coverage is strong enough
