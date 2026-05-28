# Prompt Reduction Pass 4 Report

> Historical report. Some terminology and architecture assumptions here were superseded by the current discovery-first contract.

## 1. Executive Summary

Prompt Reduction Pass 4 targeted the last large compactable planner blocks without removing kernel behavior, live context, session continuity, or deterministic enforcement.

This pass focused on:

- compacting the structured output contract
- compacting action manifest/catalog payloads
- normalizing presentation, response persona, and specialist payloads
- introducing explicit prompt-profile and catalog-mode observability

The planner remains broker-aware and fallback-safe, but with denser structural grounding and better instrumentation for future reductions.

## 2. Largest Retained Blocks Audited in Pass 4

Pass 4 used the retained-block and evidence-mode metrics added earlier to target the remaining structural-heavy areas:

- `structured_output_contract`
- `actions`
- `presentation_directive`
- `response_persona`
- `specialist_prompt`
- `instruction_pack`

These remained classified under the existing retained-block model, with persona/presentation/specialist now treated as compactable grounding rather than immutable kernel.

## 3. Structured Output Contract Compaction

The structured output contract in [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L336) was rewritten into a denser form.

Changes:

- replaced the verbose schema object with `_INTENT_SCHEMA_COMPACT`
- reduced repeated wording around `reply`, clarification, and optional `response_text`
- kept the same core semantics: one JSON object, namespaced actions, `reply`/`error`, state summary, params, attachments

This preserves output reliability while lowering fixed contract cost.

## 4. Action Manifest / Catalog Compaction Changes

The action manifest in [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5153) was further compacted:

- `ac.v3` became `ac.v4`
- `on_demand` became `od`
- `on_demand_chat` became `od_chat`
- `compact_chat` became `chat`
- large action surfaces now support `dense` / `dense_hybrid`
- large catalogs keep only a compact seed list plus `more`

The prompt-side wrapper in [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L294) was also shortened from `scope=...` to `s=...`.

This reduces payload size without removing action availability grounding.

## 5. Presentation / Persona / Specialist Payload Changes

Three behavior-related payloads were normalized:

- presentation directives are now compacted into `[PRESENTATION]` mode lines
- response persona is now a shorter scoped rule in `[RESPONSE PERSONA]`
- specialist payload is now a dedicated `[SPECIALIST]` block instead of being embedded in the base header

Relevant code:

- [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L157)
- [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L450)
- [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L4945)

This keeps behavioral boundaries clear while reducing verbose framing.

## 6. Prompt Profiles or Mode Variants Introduced (if any)

Pass 4 introduced explicit prompt-profile tracking:

- `conversational`
- `operational`

Profile selection is lightweight and local:

- the orquestrator derives the profile from the turn type
- the composer records the active profile in metrics
- action catalogs already adapt to profile through `chat`, `od_chat`, `od`, and dense variants

This is not a large framework. It is a bounded local refinement for prompt cost control.

## 7. Blocks Still Kept and Why

Still kept intentionally:

- kernel identity and execution policy
- structured output contract
- system context
- TOON state and active session continuity
- action grounding
- broker guidance
- broker evidence channel

These remain because the planner still needs deterministic reliability, current-state continuity, and safe degraded-mode behavior when retrieval is absent or partial.

## 8. Broker-Aware Grounding Strategy

The planner grounding model is now clearer:

- broker evidence remains the preferred source for operational knowledge
- compact action availability remains structural execution grounding
- live/session context remains current-state grounding
- no-evidence mode falls back to state plus action availability

This pass did not create broker dependence as a single point of failure.

## 9. Evidence-Present vs Evidence-Absent Metrics

The existing `evidence_mode_comparison` metrics remain active and continue to expose:

- mode
- domains
- fallback grounding reliance
- broker load vs grounding load
- estimated prompt size with and without evidence
- evidence coverage ratio

Pass 4 builds on that by making profile and catalog mode visible alongside the evidence-mode split.

## 10. Prompt Size / Reduction Metrics

New Pass 4 metrics added in [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L547):

- `estimated_before_pass4_chars`
- `estimated_after_pass4_chars`
- `estimated_pass4_reduction_chars`
- `prompt_profile`
- `catalog_mode`
- `compact_catalog_used`
- `retained_focus_sizes`

`retained_focus_sizes` now exposes retained sizes for:

- structured output contract
- action catalog
- presentation payload
- response persona
- specialist payload
- instruction pack

This makes the next reduction pass much easier to target precisely.

## 11. Orchestrator / Prompt Composer Changes

Main code changes:

- [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py)
  - compact output contract
  - compact response persona block
  - separate specialist block
  - compact presentation normalization
  - prompt-profile and catalog-mode metrics

- [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py)
  - denser `ip.v3` instruction pack
  - compact presentation directive generation
  - prompt-profile selection
  - `ac.v4` action catalog with `od`, `chat`, `dense`, and `dense_hybrid`

The existing broker snapshot integration remained intact and now carries the richer prompt metrics.

## 12. Tests Added

New tests:

- [tests/context/test_prompt_reduction_pass4.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass4.py)
- [tests/context/test_prompt_reduction_pass4_fallback.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass4_fallback.py)
- [tests/context/test_prompt_reduction_pass4_integration.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass4_integration.py)
- [tests/context/test_prompt_reduction_pass4_metrics.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass4_metrics.py)

Adjusted compatibility coverage:

- [tests/minimal/test_prompt_persona_scope.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/minimal/test_prompt_persona_scope.py)

Validation run:

- `./env/bin/pytest -q tests/context/test_prompt_reduction_pass1.py tests/context/test_prompt_reduction_fallback.py tests/context/test_prompt_reduction_integration.py tests/context/test_prompt_reduction_pass2.py tests/context/test_prompt_reduction_pass2_fallback.py tests/context/test_prompt_reduction_pass2_integration.py tests/context/test_prompt_reduction_pass3.py tests/context/test_prompt_reduction_pass3_fallback.py tests/context/test_prompt_reduction_pass3_integration.py tests/context/test_prompt_reduction_pass3_metrics.py tests/context/test_prompt_reduction_pass4.py tests/context/test_prompt_reduction_pass4_fallback.py tests/context/test_prompt_reduction_pass4_integration.py tests/context/test_prompt_reduction_pass4_metrics.py tests/minimal/test_prompt_persona_scope.py tests/minimal/test_prompt_composer_assistive_mode.py`
- `/usr/bin/python3 -m compileall src/services/llm/prompt_composer.py src/core/orchestrator.py`

Result:

- `24 passed`

## 13. Fallback / Degraded Mode Behavior

Fallback remains safe:

- broker absence still yields a valid planner prompt
- action grounding remains present
- structured output contract remains present
- conversational profile still works with compact chat grounding
- degraded tool state still becomes compact presentation guidance instead of disappearing

This pass reduced verbosity, not resilience.

## 14. Remaining Prompt Debt

Remaining prompt debt after Pass 4 is more concentrated and lower-risk:

- TOON/session-state size in long sessions
- instruction-pack size when multiple optional behaviors are enabled
- broker evidence payload size in evidence-rich operational turns
- background worker / supervisory alert add-ons outside the main composer path

These are better tackled with later targeted reductions rather than aggressive cuts now.

## 15. Recommended Next Step

Recommended next step: a final controlled prompt reduction pass focused on dynamic-state cost rather than fixed kernel cost.

Priority targets:

- long-session TOON/state compaction
- broker evidence density controls per domain
- optional compression of worker-update and supervisory-alert appendices
- tighter evidence-vs-grounding balancing using the new retained-focus metrics
