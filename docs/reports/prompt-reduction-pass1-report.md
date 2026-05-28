# Prompt Reduction Pass 1 Report

> Historical report. Some terminology and architecture assumptions here were superseded by the current discovery-first contract.

## 1. Executive Summary

Prompt Reduction Pass 1 introduces the first controlled prompt diet for the planner. The goal of this pass was not to rewrite the prompt system, but to reduce fixed explanatory prose that is now better supplied by the Context Broker and active retrieval domains.

This pass keeps the planner stable by preserving:

- kernel planner identity and structured output contract
- live situational context
- session state and execution continuity
- deterministic enforcement in code

The implementation reduces redundant prompt material, adds short broker-aware anchors, and records prompt reduction diagnostics for later tuning.

## 2. Prompt Blocks Audited

The prompt composition path was audited in `src/services/llm/prompt_composer.py` and the upstream orchestration path in `src/core/orchestrator.py`.

Major audited blocks:

- base planner header
- response persona block
- instruction pack
- presentation directive
- cognitive frame
- system/environment context
- TOON state and deltas
- session summary, scratchpad, attachments, memory
- broker evidence
- available actions
- browser intent classes
- assistive mode directive
- execution policy
- structured output contract

The largest prompt-centric knowledge/procedure candidates were:

- browser intent explanation prose
- assistive/browser procedural guidance
- long execution-policy prose mixing kernel rules with operational knowledge

## 3. Blocks Reduced or Removed

This pass targeted the safest reductions first.

Reduced or removed:

- `[BROWSER INTENT CLASSES]`
  - removed as a dedicated fixed block
  - intent-class grounding remains covered by the compact instruction pack and a shorter execution-policy line

- `[ASSISTIVE MODE DIRECTIVE]`
  - reduced from a long, highly specific procedural block to a short operational directive

- `[EXECUTION POLICY]`
  - reduced substantially
  - verbose explanation prose, artifact prose, and clarification prose were compressed into shorter kernel-safe guidance

- `[BROKER EVIDENCE]` intro line
  - shortened

## 4. Blocks Kept and Why

Blocks intentionally kept:

- `[STRUCTURED OUTPUT CONTRACT]`
  - still critical for planner correctness

- `[INTERNAL STATE (TOON)]`
  - required for continuity and execution recovery

- `[BACKGROUND CONTEXT - SYSTEM & ENVIRONMENT]`
  - required live situational context

- `[DYNAMIC CONTEXT]`
  - still needed for summary, scratchpad, attachments, memory, and broker evidence

- `[AVAILABLE ACTIONS]`
  - still required for reliable capability grounding

- instruction pack
  - remains the compact kernel carrier for policy and browser intent constraints

## 5. Broker-Aware Anchor Instructions Added

New broker-aware anchor:

- `[BROKER GUIDANCE]`

Behavior:

- when evidence exists, it tells the planner to prefer broker evidence for capability behavior, procedures, examples, policies, experience, and reference knowledge
- when evidence is absent, it explicitly instructs the planner to fall back to live state, action discovery, and current tool results

This creates broker reliance without turning broker success into a hard dependency.

## 6. Prompt Size / Reduction Metrics

`PromptComposer` now records reduction metrics on every compose call through `last_compose_metrics`.

Captured metrics:

- `estimated_before_chars`
- `estimated_after_chars`
- `estimated_reduction_chars`
- `broker_evidence_present`
- `evidence_item_count`
- `evidence_domains`
- `fallback_no_evidence_mode`
- `reduction_audit`

`reduction_audit` currently includes per-block before/after estimates for:

- `browser_intent_classes`
- `assistive_mode`
- `execution_policy`

## 7. Orchestrator / Prompt Composer Changes

Changes in `src/services/llm/prompt_composer.py`:

- removed the dedicated fixed browser intent block
- shortened assistive-mode instructions
- shortened execution-policy prose
- added `[BROKER GUIDANCE]`
- added prompt reduction metrics and block audit capture

Changes in `src/core/orchestrator.py`:

- stores prompt reduction metrics in `session.context["last_prompt_reduction"]`
- also attaches them to `session.context["last_context_broker"]["prompt_reduction"]` when broker diagnostics exist

This makes prompt reduction observable in the runtime snapshot used for later tuning.

## 8. Tests Added

New tests added:

- `tests/context/test_prompt_reduction_pass1.py`
- `tests/context/test_prompt_reduction_fallback.py`
- `tests/context/test_prompt_reduction_integration.py`

Coverage added:

- required kernel blocks still present
- large redundant blocks removed or reduced
- broker evidence still injected correctly
- fallback mode remains coherent when evidence is empty
- reduction metrics are produced and auditable

Validation executed:

- `./env/bin/pytest -q tests/context/test_prompt_reduction_pass1.py tests/context/test_prompt_reduction_fallback.py tests/context/test_prompt_reduction_integration.py tests/context/test_external_knowledge_ingestion.py tests/context/test_custom_knowledge_ingestion.py tests/context/test_visibility_and_trust.py tests/context/test_context_broker_phase4.py tests/context/test_evidence_injection_phase4.py tests/context/test_agent_experience_ingestion.py tests/context/test_agent_experience_dedup.py tests/context/test_context_broker_phase3.py tests/context/test_context_broker_phase2c.py tests/context/test_context_broker_phase2b.py tests/context/test_context_broker_retrieval.py tests/minimal/test_context_broker_phase1.py tests/minimal/test_prompt_composer_assistive_mode.py tests/minimal/test_prompt_persona_scope.py`
- `/usr/bin/python3 -m compileall src/services/context src/services/llm/prompt_composer.py src/core/orchestrator.py`

## 9. Fallback / Degraded Mode Behavior

Fallback behavior remains explicit and safe.

If broker evidence is empty:

- the prompt still contains kernel rules
- the prompt still contains live system/session state
- the prompt still contains the action catalog
- `[BROKER GUIDANCE]` switches to a degraded-mode reminder instead of failing silently

This pass does not create a hidden dependency on broker evidence always existing.

## 10. Risks / Follow-up Work

Current risks:

- some operational prose still exists in shortened form because removing it entirely in one pass would be too aggressive
- the action catalog still carries grounding load and should not be cut too hard yet
- prompt size metrics are estimate-based, not tokenizer-exact

These are acceptable for Pass 1 because the priority is stability over maximal reduction.

## 11. Recommended Prompt Reduction Pass 2

Recommended next step:

- reduce remaining fixed operational prose that now overlaps with `procedures`, `policies`, `examples`, and `capability_knowledge`
- evaluate whether some action-catalog guidance can move further into compact broker-aware anchors
- compare broker evidence presence against planner quality using the new reduction metrics
- only then consider deeper prompt restructuring or removal of additional fixed guidance
