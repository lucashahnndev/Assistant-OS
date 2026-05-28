# Prompt Reduction Pass 2 Report

> Historical report. Some terminology and architecture assumptions here were superseded by the current discovery-first contract.

## 1. Executive Summary

Prompt Reduction Pass 2 continues the transition from a prompt-centric planner to a broker-centric planner using the retrieval coverage and observability introduced in earlier phases.

This pass was more assertive than Pass 1, but still controlled:

- additional fixed operational framing was reduced
- broker-aware anchors were kept short and explicit
- action grounding was preserved
- degraded mode remained safe
- prompt observability was extended with retained-block sizing and replacement strategy signals

The result is a smaller planner prompt with less redundant operational prose and better instrumentation for the next reduction step.

## 2. Prompt Blocks Audited in Pass 2

Pass 2 audited the remaining prompt after Pass 1, focusing on blocks still carrying fixed explanatory or framing overhead:

- language directive fallback
- system/environment context framing
- TOON explanatory note
- dynamic-context explanatory notes
- session summary / scratchpad / attachments framing
- broker evidence framing
- action catalog framing
- assistive-mode directive
- execution-policy block

The audit also considered whether these blocks were still kernel/continuity requirements or whether they were now mostly carrying knowledge that the broker already supplies.

## 3. Additional Blocks Reduced or Removed

Additional reductions made in Pass 2:

- `[BACKGROUND CONTEXT - SYSTEM & ENVIRONMENT]`
  - renamed and compacted to `[SYSTEM CONTEXT]`

- `[INTERNAL STATE (TOON)]`
  - removed the explanatory note under the header

- `[TOON CONTEXT DELTAS]`
  - removed explanatory prose

- `[BROWSER STATE]`
  - removed explanatory prose

- `[CONSOLIDATED SESSION SUMMARY]`
  - reduced to `[SESSION SUMMARY]`

- `[PERSISTENT SCRATCHPAD]`
  - reduced to `[SCRATCHPAD]`

- `[SESSION ATTACHMENTS]`
  - reduced to `[ATTACHMENTS]`

- `[BROKER EVIDENCE]`
  - removed the remaining explanatory line

- `[AVAILABLE ACTIONS]`
  - reduced to `[ACTIONS]` with compact `scope=...` formatting

- `[EXECUTION POLICY]`
  - reduced further, removing residual artifact/help framing and leaving only the shortest stable operational rules

- `[BROKER GUIDANCE]`
  - shortened again to focus on broker semantics + fallback behavior without repeating operational prose

## 4. Blocks Still Kept and Why

Still kept intentionally:

- base planner header
  - core planner identity and action orientation

- instruction pack
  - compact kernel carrier for action policy, language mode, and browser intent grounding

- response persona block
  - needed for output-style scoping

- system context
  - live runtime grounding

- TOON state
  - continuity and task progress

- dynamic context
  - session summary, scratchpad, attachments, memory, broker evidence

- action catalog
  - capability selection grounding is still too sensitive to remove aggressively

- structured output contract
  - still critical and non-negotiable

## 5. Broker-Aware Anchor Strategy

Pass 2 kept the broker anchor intentionally small.

When evidence is present:

- instruct the planner to use broker evidence for capability semantics, procedures, examples, policies, experience, and reference knowledge
- instruct it to combine evidence with live state and action availability when evidence is partial

When evidence is absent:

- instruct the planner to rely on live state, session context, and action availability

This keeps broker dependence explicit while preserving degraded-mode safety.

## 6. Prompt Size / Reduction Metrics

Prompt reduction observability was extended in `PromptComposer`.

Current metrics now include:

- `estimated_before_pass2_chars`
- `estimated_after_pass2_chars`
- `estimated_before_chars`
- `estimated_after_chars`
- `estimated_reduction_chars`
- `estimated_total_reduction_chars`
- `broker_evidence_present`
- `evidence_item_count`
- `evidence_domains`
- `fallback_no_evidence_mode`
- `retained_block_sizes`
- `largest_retained_blocks`
- `reduction_audit`

`reduction_audit` now also records compact replacement strategy signals such as:

- `instruction_pack_only`
- `short_anchor`
- `broker_anchor_and_kernel`

This makes Pass 2 more evidence-driven and prepares the next reduction round to target the largest retained blocks instead of reducing blindly.

## 7. Orchestrator / Prompt Composer Changes

Changes in `src/services/llm/prompt_composer.py`:

- compacted several remaining prompt headers and helper notes
- further reduced execution-policy prose
- further reduced broker-guidance prose
- changed action catalog framing to a smaller header
- added retained block sizing metrics
- added largest-retained-block diagnostics
- added replacement-strategy markers in reduction audit

Changes in `src/core/orchestrator.py`:

- no structural flow change was needed
- the existing prompt reduction snapshot path continues to capture the richer Pass 2 metrics automatically through `last_compose_metrics`

## 8. Tests Added

New tests added:

- `tests/context/test_prompt_reduction_pass2.py`
- `tests/context/test_prompt_reduction_pass2_fallback.py`
- `tests/context/test_prompt_reduction_pass2_integration.py`

Updated tests:

- `tests/context/test_prompt_reduction_pass1.py`
- `tests/context/test_prompt_reduction_fallback.py`

Coverage added:

- newly reduced framing is no longer present
- broker anchor remains short and explicit
- fallback remains safe without evidence
- retained block metrics are exposed
- replacement strategy audit is populated

Validation executed:

- `./env/bin/pytest -q tests/context/test_prompt_reduction_pass1.py tests/context/test_prompt_reduction_fallback.py tests/context/test_prompt_reduction_integration.py tests/context/test_prompt_reduction_pass2.py tests/context/test_prompt_reduction_pass2_fallback.py tests/context/test_prompt_reduction_pass2_integration.py tests/context/test_external_knowledge_ingestion.py tests/context/test_custom_knowledge_ingestion.py tests/context/test_visibility_and_trust.py tests/context/test_context_broker_phase4.py tests/context/test_evidence_injection_phase4.py tests/context/test_agent_experience_ingestion.py tests/context/test_agent_experience_dedup.py tests/context/test_context_broker_phase3.py tests/context/test_context_broker_phase2c.py tests/context/test_context_broker_phase2b.py tests/context/test_context_broker_retrieval.py tests/minimal/test_context_broker_phase1.py tests/minimal/test_prompt_composer_assistive_mode.py tests/minimal/test_prompt_persona_scope.py`
- `/usr/bin/python3 -m compileall src/services/context src/services/llm/prompt_composer.py src/core/orchestrator.py`

## 9. Fallback / Degraded Mode Behavior

Fallback behavior remains safe.

If broker evidence is empty:

- prompt still includes kernel rules
- prompt still includes live system context
- prompt still includes session continuity context
- prompt still includes action availability grounding
- broker guidance explicitly switches to fallback mode

If multiple domains are present:

- evidence still injects through the existing broker channel
- prompt remains bounded
- no new hidden dependency on any single retrieval domain was introduced

## 10. Remaining Prompt Debt

Remaining prompt debt is now narrower and clearer:

- some execution-policy text still exists because removing it entirely would risk planner quality
- the action catalog still carries meaningful grounding cost
- cognitive-frame formatting could likely be compressed further in a later pass
- instruction-pack payload may still carry some broker-covered semantics indirectly

This is acceptable for Pass 2 because the current focus is controlled reduction, not maximal shrinkage.

## 11. Recommended Next Step

Recommended next step:

- perform a broker-informed Prompt Reduction Pass 3 focused on the largest retained blocks reported by the new metrics
- evaluate whether some action-grounding structure can be compacted further without harming capability selection
- compare planner quality on evidence-present vs evidence-absent turns before removing more operational fallback text
- only then consider deeper prompt restructuring or catalog-level reduction
