# Context Broker Phase 2B Implementation Report

> Historical report. This phase note reflects an earlier broker rollout and may not match the current discovery-first contract.

## 1. Executive Summary

Phase 2B activates two new retrieval domains in the Unified Context architecture:

- `procedures`
- `examples`

The implementation extends the existing broker flow introduced in Phases 1 and 2A with real ingestion, vector retrieval, compact evidence normalization, explicit routing, and diagnostics for both domains.

The current runtime remains backward-compatible:

- the orchestrator flow is preserved
- prompt assembly remains additive
- retrieval failure degrades gracefully
- non-scope domains remain inactive

## 2. Procedures Ingestion Design

Procedure ingestion is implemented in:

- `src/services/context/ingestion/procedure_ingestor.py`

The ingestor scans procedure-like explanatory sources from the repository, including:

- `agent/specs/worker_task_contract.spec.md`
- `docs/guides/browser_control_playbook.md`
- capability `README.md` files

It explicitly treats only explanatory operational guidance as retrievable procedure knowledge. Enforcement code remains outside retrieval.

Procedure ingestion behavior:

1. scans known procedure/document sources
2. splits markdown into logical sections by headings
3. identifies procedural sections using explicit workflow/playbook/runbook/checklist markers and ordered-step detection
4. creates:
   - section-level procedure chunks
   - step-level procedure chunks for numbered or bullet workflows
5. stores the result in the `procedures` collection
6. maintains a manifest keyed by source mtimes to avoid unnecessary reindexing

This gives the planner reusable workflow guidance without copying large prompt prose directly.

## 3. Examples Ingestion Design

Example ingestion is implemented in:

- `src/services/context/ingestion/example_ingestor.py`

The ingestor scans safe example sources such as:

- action `examples` in capability contracts
- capability README usage-example sections
- capability-local `example_flow.py` files

Example ingestion behavior:

1. extracts action examples from `contract.json`
2. extracts fenced usage-example blocks from `README.md`
3. extracts normalized flow snippets from `example_flow.py`
4. stores these artifacts in the `examples` collection
5. keeps a manifest for incremental reindexing

This keeps the examples domain focused on demonstrations of correct usage instead of arbitrary logs or chat history.

## 4. Retrieval Adapter Implementation

New retrieval adapters were added under:

- `src/services/context/retrieval/procedures.py`
- `src/services/context/retrieval/examples.py`

### Procedures adapter

- ensures ingestion has run
- executes vector search against the `procedures` collection
- groups related chunks by procedure identity
- normalizes retrieved text into compact workflow evidence such as:
  - section summary
  - step-specific guidance

### Examples adapter

- ensures ingestion has run
- executes vector search against the `examples` collection
- filters by allowed actions when relevant
- groups related examples
- normalizes retrieved content into compact usage-demonstration evidence

Both adapters return compact payloads that are then converted into `EvidenceItem` objects by the existing `EvidenceBuilder`.

## 5. Retrieval Router Changes

`src/services/context/retrieval_router.py` was updated to route the new domains explicitly.

Current Phase 2B routing:

- `task_execution`
  - `procedures`
  - `capability_knowledge`
  - `user_memory`
- `capability_lookup`
  - `capability_knowledge`
  - `examples`
- `troubleshooting`
  - `user_memory`
  - `procedures`
  - `examples`
  - `capability_knowledge`

`conversational` still avoids `procedures` and `examples` by default, which keeps the prompt bounded and aligned with the scope of this phase.

## 6. Context Broker Changes

`src/services/context/broker.py` now:

- initializes real handlers for:
  - `procedures`
  - `examples`
  - `capability_knowledge`
  - `user_memory`
- tracks per-domain query state
- tracks per-domain raw result counts
- tracks per-domain injected evidence counts
- continues to rerank evidence by route priority and score
- degrades safely to empty handlers if vector initialization fails

Diagnostics now expose:

- which domains were queried
- how many results each domain returned
- how many evidence items each domain injected

This supports later tuning and prompt-reduction work.

## 7. Prompt Composer Integration Changes

The prompt composer did not require a structural rewrite for Phase 2B.

The existing broker evidence path already accepted arbitrary domain-tagged evidence. For this phase it now receives real `procedures` and `examples` evidence in the same bounded `[BROKER EVIDENCE]` section.

The evidence channel remains bounded:

- broker route limits constrain per-domain retrieval
- prompt rendering is capped to the first 6 evidence items

This preserves compatibility and avoids aggressive prompt growth.

## 8. Metadata Schema Introduced

`RAGChunkMetadata` in `src/services/context/models.py` was extended with fields needed by the new domains.

New procedure/example-related metadata:

- `procedure_id`
- `example_type`
- `step_index`
- `section`
- `tags`
- `success_signal`

These sit on top of the Phase 2A base metadata such as:

- `doc_type`
- `collection_type`
- `source_file`
- `source_type`
- `capability_id`
- `action_id`
- `created_at`
- `updated_at`
- `trust_level`
- `embedding_version`

## 9. Tests Added

New tests:

- `tests/context/test_procedure_ingestion.py`
- `tests/context/test_example_ingestion.py`
- `tests/context/test_context_broker_phase2b.py`
- `tests/context/test_evidence_injection_phase2b.py`

Updated test:

- `tests/minimal/test_context_broker_phase1.py`

Covered behaviors include:

- procedure section and step parsing
- example extraction from contracts, README, and flow scripts
- routing behavior including `procedures` and `examples`
- broker diagnostics for queried/result/injected domains
- prompt rendering of procedure/example evidence
- graceful fallback when handlers are missing

## 10. Current Limitations

- procedures are extracted conservatively from markdown and may miss some implicit workflow text
- example extraction from README files currently depends on explicit usage-example sections and fenced blocks
- reranking remains basic and does not yet do domain-aware fusion beyond route priority and retrieval score
- examples from Python flow files are normalized heuristically rather than semantically summarized
- the remaining domains (`policies`, `agent_experience`, `external_knowledge`, `custom_knowledge`) are still inactive in this phase

## 11. Recommended Phase 2C

Recommended next steps for Phase 2C:

1. activate the `policies` domain with explanatory rule retrieval
2. improve domain-aware reranking across procedures/examples/capabilities
3. add richer semantic summarization for extracted Python example flows
4. expand procedure-source coverage for operational docs still living in prompt prose
5. add broker metrics around domain hit rate and prompt token contribution
