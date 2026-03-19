# Context Broker Phase 2A Implementation Report

## 1. Executive Summary

Phase 2A activates the first two real retrieval domains of the Unified Context architecture:

- `capability_knowledge`
- `user_memory`

The implementation adds real ingestion, typed chunk metadata, vector-backed retrieval, broker integration, prompt evidence injection, and focused automated tests while preserving the existing orchestration and prompt flow.

This phase does not perform the full RAG migration. It keeps retrieval scoped to the two requested domains and leaves the remaining domains for later phases.

## 2. Capability Knowledge Ingestion Design

Capability knowledge ingestion is implemented under:

- `src/services/context/ingestion/capability_ingestor.py`
- `src/services/context/ingestion/document_chunker.py`

Behavior:

1. scans the capability tree for:
   - `contract.json`
   - `README.md`
   - `config.schema.json`
2. extracts:
   - capability overview
   - action descriptions
   - parameter summaries
   - contract examples
   - schema summaries
   - README text
3. chunks the normalized documents with bounded overlap
4. stores the resulting chunks in the `capability_knowledge` collection
5. writes a manifest based on file mtimes to avoid unnecessary reindexing

The ingestor rebuilds the capability collection when source files change and otherwise reuses the existing index.

## 3. User Memory Ingestion Design

User memory ingestion is implemented in:

- `src/services/context/ingestion/user_memory_ingestor.py`

Behavior:

1. reads accepted session memory entries from `session.memory`
2. validates candidate memory before promotion
3. resolves `principal_id` and `tenant_id`
4. maps each memory item into a typed chunk
5. upserts the chunks into the `user_memory` collection

This provides the requested promotion path:

session memory observation  
→ validated memory entry  
→ persistent vector storage

Phase 2A keeps the source intentionally conservative by promoting session memory entries already accepted by the system instead of inventing a new memory-governance path.

## 4. Retrieval Adapter Implementation

Retrieval adapters live under:

- `src/services/context/retrieval/capability_knowledge.py`
- `src/services/context/retrieval/user_memory.py`

### Capability knowledge adapter

- ensures ingestion has run
- queries the `capability_knowledge` vector collection
- filters results against allowed actions/capabilities when available
- groups related chunks into compact evidence units
- returns normalized capability evidence such as:
  - capability id
  - action id
  - description
  - parameters
  - risk

### User memory adapter

- promotes current session memory before search
- filters retrieval by `principal_id`
- keeps `tenant_id` scoped
- returns normalized fact-style evidence blocks for prompt injection

## 5. Context Broker Integration Changes

`src/services/context/broker.py` now:

- builds real default handlers using:
  - `ContextVectorStore`
  - `CapabilityKnowledgeIngestor`
  - `UserMemoryIngestor`
  - both retrieval adapters
- reranks evidence using target priority and score
- preserves fail-safe behavior by degrading to an empty handler set if storage initialization fails

`src/services/context/retrieval_router.py` was also updated so the active routes for this phase are:

- `capability_lookup` → `capability_knowledge`
- `task_execution` → `capability_knowledge` + `user_memory`
- `memory_lookup` → `user_memory`
- `troubleshooting` → `user_memory` + `capability_knowledge`

Non-scope domains remain inactive/stubbed.

## 6. Prompt Composer Integration Changes

The prompt composer already had the optional broker evidence channel from Phase 1.

For Phase 2A it now:

- continues to accept `context_bundle`
- injects broker evidence only when present
- bounds evidence rendering to the first 6 evidence items
- keeps the rest of the prompt unchanged

This preserves compatibility with existing prompt logic while allowing the planner to consume real retrieved evidence.

## 7. Metadata Schema Introduced

New chunk metadata is defined in `src/services/context/models.py` via `RAGChunkMetadata`.

### Capability chunk metadata

Included fields:

- `doc_type`
- `collection_type`
- `capability_id`
- `action_id`
- `source_file`
- `created_at`
- `updated_at`
- `embedding_version`

Additional fields used for tracing/chunk handling:

- `title`
- `chunk_index`
- `total_chunks`

### User memory metadata

Included fields:

- `doc_type = "user_memory"`
- `principal_id`
- `tenant_id`
- `created_at`
- `updated_at`
- `trust_level`
- `source_type`
- `embedding_version`

These are stored in the vector collection metadata and surfaced back through retrieval results.

## 8. Tests Added

New tests:

- `tests/context/test_capability_ingestion.py`
- `tests/context/test_user_memory_ingestion.py`
- `tests/context/test_context_broker_retrieval.py`
- `tests/context/test_evidence_injection.py`

Updated test:

- `tests/minimal/test_context_broker_phase1.py`

Covered behaviors:

- capability knowledge ingestion
- user memory promotion and persistence
- retrieval from both real collections
- broker evidence creation across both domains
- prompt evidence injection
- router and classifier stability

## 9. Current Limitations

- embeddings are deterministic local hashed vectors rather than a production semantic embedding model
- capability retrieval is chunk-based but still relatively shallow; there is no domain-specific reranker yet
- user memory promotion currently relies on `session.memory` as the upstream validated source
- there is no dedicated background indexing scheduler yet; ingestion occurs lazily on retrieval
- the remaining retrieval domains remain intentionally inactive in this phase

## 10. Recommended Phase 2B

Recommended next steps for Phase 2B:

1. add typed retrieval for `procedures` and `policies`
2. introduce richer ranking and chunk aggregation for capability retrieval
3. add a background or startup indexing path for capabilities
4. connect explicit memory insert/promote flows directly to the new `user_memory` collection
5. add tracing/metrics around index freshness, retrieval hit rate, and prompt token cost
