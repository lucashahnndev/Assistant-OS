# Broker / RAG Tuning Pass 1 Report

> Historical report. This tuning note reflects an earlier broker stage and may not match the current discovery-first contract.

## 1. Executive Summary
This pass tightened broker evidence selection with intent-aware caps, domain balance tuning, low-value suppression, and more informative diagnostics. Reranking now favors operationally useful domains (procedures/capability/custom) while keeping policy and example evidence bounded unless explicitly relevant.

## 2. Reranker Tuning Changes
- Adjusted intent bonuses to reduce examples/policies dominance in execution flows and lift custom knowledge in business-scoped contexts.
- Added a balance factor to make intent-specific domain preferences explicit and inspectable in rerank traces.
- Refined intent-aware per-domain caps for capability lookup, troubleshooting, and policy intents.

Files:
- src/services/context/reranker.py

## 3. Domain Cap and Density Changes
- Introduced intent-specific broker max evidence caps.
- Added cross-item de-duplication in broker selection and enforced domain caps post-rerank.
- Applied per-domain content limits to reduce verbose evidence payloads.

Files:
- src/services/context/broker.py
- src/services/context/evidence_builder.py

## 4. Low-Value Evidence Suppression Rules
- Suppress examples when capability knowledge is already strong in capability lookup.
- Suppress policies unless policy intent or approval context is active.
- Suppress external knowledge when custom knowledge is present in business-specific turns.

Files:
- src/services/context/broker.py

## 5. Domain Conflict Resolution Rules
- Custom knowledge now displaces lower-trust external knowledge when both are present.
- Examples are capped to avoid crowding out procedures/capability guidance.
- Agent experience is favored in troubleshooting intent, without bleeding into normal execution.

Files:
- src/services/context/broker.py
- src/services/context/reranker.py

## 6. Diagnostics Updates
- Added diagnostics for selected/suppressed evidence by domain, rerank wins, conflict summaries, total evidence chars, density reductions, and low-value suppression counts.
- Exposed these broker metrics through session telemetry payloads.

Files:
- src/services/context/models.py
- src/services/context/broker.py
- src/core/orchestrator.py
- src/server/routes/sessions.py

## 7. Viewer Integration Changes (if any)
- Surfaced the new broker suppression, density, and conflict metrics in the diagnostics viewer.

Files:
- frontend/src/pages/CognitionDiagnostics.model.js

## 8. Tests Added
- Reranker preference tests for custom vs external and procedures vs examples.
- Caps enforcement test for capability lookup.
- Suppression and integration tests for broker diagnostics and conflict handling.

Files:
- tests/context/test_broker_tuning_reranker.py
- tests/context/test_broker_tuning_caps.py
- tests/context/test_broker_tuning_suppression.py
- tests/context/test_broker_tuning_integration.py

## 9. Remaining Retrieval Noise Sources
- Overlapping procedural and example evidence can still surface when user explicitly requests examples.
- External knowledge may still appear alongside custom knowledge if external trust is very high.

## 10. Recommended Next Phase
Audit real-session broker telemetry to identify the highest-volume domain conflicts and fine-tune caps per intent, then refine low-value suppression thresholds for example-heavy capability lookup turns.
