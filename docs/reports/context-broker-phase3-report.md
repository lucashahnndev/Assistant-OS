# Phase 3 - Agent Experience Implementation Report

## 1. Executive Summary

Phase 3 activates the `agent_experience` retrieval domain on top of the existing Context Broker flow. The new domain converts prior operational traces into compact, reusable experience lessons instead of storing raw logs. It now ingests high-signal recovery and failure patterns from session decision traces, event history, task registry state, and the legacy episodic memory store when available.

The implementation preserves backward compatibility:

- the broker still degrades safely when retrieval fails
- prompt composition remains bounded through the existing `[BROKER EVIDENCE]` channel
- no existing prompt blocks were removed
- no legacy memory system was force-migrated

Phase 3 also adds deterministic suppression for low-value experience and duplicate operational lessons, plus broker diagnostics that expose ingestion quality for future tuning.

## 2. Agent Experience Domain Design

The new `agent_experience` domain is implemented as a retrieval collection for consolidated operational learning.

Design intent:

- store reusable recovery and troubleshooting lessons
- prefer concise guidance over raw execution traces
- index only future-useful operational knowledge
- keep the domain bounded and planner-friendly

Accepted experience patterns include:

- repeated failure and recovery patterns
- permission/approval handling lessons
- configuration/auth failure guidance
- environment-specific recovery hints
- fallback and replan lessons after retry exhaustion

Rejected material includes:

- trivial success records
- conversational noise
- raw status-only logs
- contextless operational fragments
- semantically duplicated lessons

## 3. Ingestion and Consolidation Pipeline

The ingestion pipeline lives in `src/services/context/ingestion/agent_experience_ingestor.py`.

Pipeline shape:

`raw trace -> value filter -> normalization -> dedupe -> vector storage`

Current source inputs:

- `session.decision_traces`
- `session.event_history`
- `session.task_registry`
- `services.memory.episodic_memory.EpisodicMemoryService` collection, when available

Normalization strategy:

- decision traces with `recovery_assessment` become recovery lessons
- failure events become failure-handling lessons when the summary implies a reusable response
- task registry entries produce escalation/fallback lessons only when retries or fallback state make them operationally useful
- episodic rows are parsed from the existing compact TOON-like payload and only promoted when they imply future recovery value

Stored chunk metadata for the domain now includes:

- `status`
- `experience_type`
- `success_signal`
- `environment_hint`
- `provenance_hash`
- `session_id`
- `error_type`
- `recovery_type`

All records are stored through the existing typed context vector store.

## 4. Noise Suppression and Deduplication Rules

Noise suppression is deterministic and explicit.

An experience candidate is rejected when:

- it is too short to be useful
- it matches noise patterns like status chatter or conversational boilerplate
- it has no failure/recovery/configuration signal
- it cannot be normalized into a concrete future-useful lesson

Deduplication is performed in two layers:

1. semantic signature dedupe
- based on `action_id`, `error_type`, `recovery_type`, `experience_type`, and `environment_hint`

2. normalized text similarity dedupe
- exact normalized match
- Jaccard-style token overlap threshold for near-identical lessons

Existing collection rows are also checked before accepting a new lesson, so repeated promotions do not bloat the store.

## 5. Retrieval Adapter Implementation

The retrieval adapter lives in `src/services/context/retrieval/agent_experience.py`.

Behavior:

- promotes session experience before querying
- queries the `agent_experience` collection through the typed vector store
- returns compact, normalized experience evidence
- exposes `last_ingestion_stats` for broker diagnostics

Evidence format is intentionally short and operational, for example:

`lesson: When browser extraction fails after stale state, restart browser control before retrying.`

The adapter does not expose raw episode rows directly to prompt assembly.

## 6. Context Broker Changes

The broker now initializes an `AgentExperienceIngestor` and `AgentExperienceRetriever` in its default handler set.

Integration changes:

- `agent_experience` is now an active broker domain
- the router can activate it for troubleshooting-heavy task execution queries
- troubleshooting intent now prioritizes `agent_experience`
- broker diagnostics now include `ingestion_stats_by_domain`
- handler-bound ingestion statistics are captured without changing the existing broker handler contract

The orchestrator snapshot in `session.context["last_context_broker"]` was extended so these new ingestion diagnostics are inspectable at runtime.

## 7. Reranking Integration

The existing deterministic reranker was extended instead of replaced.

Phase 3 reranking changes:

- `agent_experience` receives a strong intent bonus for `troubleshooting`
- it receives a smaller bonus for `task_execution`
- domain caps now treat `agent_experience` specially:
  - up to `2` items for troubleshooting
  - up to `1` item otherwise

This keeps troubleshooting evidence useful without letting experience dominate normal execution or capability lookup turns.

## 8. Prompt Composer Integration Changes

No prompt rewrite was required.

The existing `[BROKER EVIDENCE]` channel now accepts `agent_experience` items automatically through the generic evidence pipeline. The bounded injection behavior remains unchanged, so the planner prompt still stays compact and valid even when the domain is empty.

Phase 3 therefore remains additive and backward-compatible.

## 9. Metadata Schema Introduced

`RAGChunkMetadata` was expanded with agent experience fields:

- `status`
- `experience_type`
- `environment_hint`
- `provenance_hash`
- `session_id`
- `error_type`
- `recovery_type`

`ContextDiagnostics` was also extended with:

- `ingestion_stats_by_domain`

This supports tuning learning quality separately from retrieval quality.

## 10. Tests Added

New tests added:

- `tests/context/test_agent_experience_ingestion.py`
- `tests/context/test_agent_experience_dedup.py`
- `tests/context/test_context_broker_phase3.py`
- `tests/context/test_evidence_injection_phase3.py`

Coverage added in this phase:

- experience consolidation and filtering
- duplicate suppression across repeated promotions
- routing activation for troubleshooting-like queries
- reranker preference for agent experience in troubleshooting
- broker diagnostics for ingestion stats
- prompt evidence rendering and empty-domain fallback

Validation executed:

- `./env/bin/pytest -q tests/context/test_agent_experience_ingestion.py tests/context/test_agent_experience_dedup.py tests/context/test_context_broker_phase3.py tests/context/test_evidence_injection_phase3.py tests/context/test_context_broker_phase2c.py tests/context/test_context_broker_phase2b.py tests/context/test_context_broker_retrieval.py tests/minimal/test_context_broker_phase1.py tests/minimal/test_prompt_composer_assistive_mode.py tests/minimal/test_prompt_persona_scope.py`
- `/usr/bin/python3 -m compileall src/services/context src/services/llm/prompt_composer.py src/core/orchestrator.py`

## 11. Current Limitations

Current limitations remain intentional for stability:

- experience extraction is heuristic and deterministic, not semantic summarization
- the episodic memory bridge reads only compact stored rows and does not perform deep trace synthesis
- there is no cross-session clustering beyond signature and similarity suppression
- retrieval still uses a single-query path through the broker
- agent experience is not yet separated into finer subtypes like environment quirks vs recovery playbooks

These limits keep the domain useful without introducing speculative learning behavior.

## 12. Recommended Phase 4

Recommended next step: activate `external_knowledge` and `custom_knowledge` carefully, while preserving the current bounded broker flow.

Phase 4 should focus on:

- introducing source-scoped retrieval for external and repo-specific knowledge
- keeping enforcement logic deterministic and separate
- adding source trust controls and visibility controls
- improving domain-aware caps so operational experience, policies, and external knowledge do not crowd one another
- starting selective prompt reduction only after retrieval diagnostics show stable quality
