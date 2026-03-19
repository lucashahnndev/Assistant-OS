# Phase 4 - External and Custom Knowledge Implementation Report

## 1. Executive Summary

Phase 4 activates two new retrieval domains in the Unified Context architecture:

- `external_knowledge`
- `custom_knowledge`

The implementation preserves the stable broker flow while adding:

- controlled ingestion for repo/reference knowledge and user-curated knowledge
- explicit trust and visibility metadata
- scope-aware retrieval filtering
- deterministic reranking updates so knowledge domains stay bounded
- backward-compatible prompt evidence injection through the existing broker channel

No prompt diet or major prompt removal was performed in this phase.

## 2. External Knowledge Domain Design

The `external_knowledge` domain stores referenceable knowledge that is not part of the core runtime/capability/session layers.

Initial supported source classes:

- `docs/*.md`
- repository `README.md` when present
- controlled local drop-in files under `data/knowledge/external/`

Design boundaries:

- no blind whole-repo ingestion
- no default source code indexing
- no mixing of executable code with external reference knowledge

This domain is intended for manuals, repo docs, technical notes, imported markdown/text documents, and curated reference material.

## 3. Custom Knowledge Domain Design

The `custom_knowledge` domain stores user-authored or tenant/workspace-specific knowledge used to teach the agent through retrieval.

Initial supported source class:

- controlled knowledge files under `data/knowledge/custom/`

Design boundaries:

- not session memory
- not raw chat history
- not model fine-tuning

This domain is the first retrieval-based substrate for business rules, internal instructions, client-specific playbooks, and manual user training.

## 4. Ingestion Pipelines

New ingestion modules:

- `src/services/context/ingestion/external_knowledge_ingestor.py`
- `src/services/context/ingestion/custom_knowledge_ingestor.py`

Both pipelines:

- scan only controlled source roots
- support markdown/text documents
- split by headings/sections
- normalize content
- chunk with the existing `DocumentChunker`
- store typed chunks in the context vector store
- write incremental manifests for change detection

Metadata overrides are supported through optional sidecar manifests:

- `data/knowledge/external/_manifest.json`
- `data/knowledge/custom/_manifest.json`

These manifests allow per-file overrides for trust, visibility, scope, tenant/principal targeting, author, version, and origin without code changes.

## 5. Trust and Visibility Model

Phase 4 makes trust and visibility first-class metadata for the two new domains.

New metadata concepts:

- `trust_level`
  - examples: `curated`, `user`, `imported`, `system`, `low-confidence`
- `policy_visibility`
  - examples: `public`, `tenant`, `principal`, `internal`
- `knowledge_scope`
  - examples: `global`, `tenant`, `principal`, `workspace`

Additional optional knowledge metadata introduced:

- `origin`
- `author`
- `version`

Retrieval adapters now filter results using `policy_visibility` and `knowledge_scope` with lightweight principal/tenant/workspace checks. This is intentionally simpler than a full RBAC system, but enough to keep source boundaries explicit and stable.

## 6. Retrieval Adapter Implementation

New retrieval adapters:

- `src/services/context/retrieval/external_knowledge.py`
- `src/services/context/retrieval/custom_knowledge.py`

Behavior:

- ensure ingestion is up to date before querying
- query the appropriate vector collection
- filter rows by visibility/scope
- normalize evidence into compact source-aware summaries
- expose ingestion stats to the broker for diagnostics

Evidence examples:

- `reference: Use page retrieval for extraction and planner mode for navigation.`
- `custom: New client onboarding must always create a tracking ticket before provisioning.`

## 7. Context Broker Changes

Broker integration updates:

- default handlers now initialize `external_knowledge` and `custom_knowledge`
- routing now supports conditional knowledge activation for documentation-oriented and business-specific queries
- `general_knowledge` now routes to `external_knowledge` by default and to `custom_knowledge` when custom/user-business cues are present
- `task_execution`, `capability_lookup`, and `troubleshooting` now support bounded conditional knowledge retrieval

The intent classifier was extended conservatively so documentation-style and custom/business-style queries can route into the knowledge layer without breaking existing task-oriented behavior.

## 8. Reranking Integration

The deterministic reranker was extended rather than redesigned.

Phase 4 reranking changes:

- new trust weights for `curated`, `user`, `imported`, `system`, and `low-confidence`
- new visibility weights for `tenant` and `principal`
- new scope weights for `global`, `tenant`, `principal`, and `workspace`
- new intent bonuses for `external_knowledge` and `custom_knowledge`
- bounded caps so these domains do not crowd out procedures, policies, capabilities, or agent experience during operational turns

Rerank diagnostics now include scope influence in the compact rerank summary, making trust/visibility effects inspectable without adding a large analytics subsystem.

## 9. Prompt Composer Integration Changes

No prompt architecture rewrite was required.

The existing `[BROKER EVIDENCE]` pathway now accepts:

- `external_knowledge`
- `custom_knowledge`

Evidence injection remains bounded and optional. If no knowledge documents exist or retrieval returns nothing, the planner prompt remains valid and the system degrades gracefully.

## 10. Metadata Schema Introduced

`RAGChunkMetadata` was expanded with:

- `knowledge_scope`
- `origin`
- `author`
- `version`

These fields sit alongside the trust and visibility fields already present and are now actively used by retrieval and reranking for the new domains.

## 11. Tests Added

New tests added:

- `tests/context/test_external_knowledge_ingestion.py`
- `tests/context/test_custom_knowledge_ingestion.py`
- `tests/context/test_visibility_and_trust.py`
- `tests/context/test_context_broker_phase4.py`
- `tests/context/test_evidence_injection_phase4.py`

Coverage added in this phase:

- external knowledge ingestion
- custom knowledge ingestion
- manifest-driven trust/visibility metadata
- scope/visibility retrieval filtering
- broker routing for documentation and business-specific queries
- reranking behavior with trust and scope
- prompt evidence rendering for the new domains

Validation executed:

- `./env/bin/pytest -q tests/context/test_external_knowledge_ingestion.py tests/context/test_custom_knowledge_ingestion.py tests/context/test_visibility_and_trust.py tests/context/test_context_broker_phase4.py tests/context/test_evidence_injection_phase4.py tests/context/test_agent_experience_ingestion.py tests/context/test_agent_experience_dedup.py tests/context/test_context_broker_phase3.py tests/context/test_context_broker_phase2c.py tests/context/test_context_broker_phase2b.py tests/context/test_context_broker_retrieval.py tests/minimal/test_context_broker_phase1.py tests/minimal/test_prompt_composer_assistive_mode.py tests/minimal/test_prompt_persona_scope.py`
- `/usr/bin/python3 -m compileall src/services/context src/services/llm/prompt_composer.py src/core/orchestrator.py`

## 12. Current Limitations

Current limitations are intentional for stability:

- custom and external ingestion are file-based, not a full management product
- visibility filtering is lightweight and not a full authorization layer
- code files are still intentionally excluded from external knowledge ingestion
- repo docs ingestion is broad within `docs/`, but still controlled and non-code
- there is no authoring UI or CRUD API in this phase
- retrieval remains single-query and deterministic

## 13. Recommended Next Step

The next step should be the first serious prompt reduction pass, guided by the broker diagnostics now available across all active domains.

Recommended focus:

- begin replacing hardcoded prompt prose with broker evidence where quality is already stable
- keep deterministic enforcement in code
- tune per-domain caps and rerank weights from observed diagnostics
- add a minimal management surface for custom/external knowledge only if operationally necessary
