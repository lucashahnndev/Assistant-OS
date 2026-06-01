# Prompt Reduction Pass 5 Report

> Historical report. Some terminology and architecture assumptions here were superseded by the current discovery-first contract.

## 1. Executive Summary

Prompt Reduction Pass 5 shifted the reduction effort away from kernel-adjacent framing and into dynamic prompt cost.

This pass focused on:

- compacting TOON and session-state payloads when evidence or summaries are already present
- suppressing redundant scratchpad state
- compacting worker and supervisory appendices into short material-only sections
- improving broker evidence density with best-of-domain selection and caps
- exposing new dynamic-cost metrics for state, evidence, and appendices

The planner remains fallback-safe and broker-aware, but the prompt now pays less for repeated dynamic context.

## 2. Dynamic-Cost Blocks Audited

Pass 5 explicitly targeted these dynamic-cost contributors:

- `toon_state`
- `toon_deltas`
- `session_summary`
- `scratchpad`
- `cognitive_foreground`
- `cognitive_supporting`
- broker evidence payload
- worker update appendices
- supervisory alert appendices

These were treated as dynamic, conditional cost centers rather than fixed prompt debt.

## 3. TOON / Session-State Compaction Changes

State compaction now happens inside [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py).

Main changes:

- TOON, deltas, summary, scratchpad, and evidence now use dynamic clipping via `_clip_state_block`
- clipping adapts to prompt profile and whether broker evidence / summary is already present
- scratchpad is suppressed when redundant with session summary
- conversational turns use a lighter dynamic-state budget
- troubleshooting turns retain more state than conversational turns, but still compact it

This reduces dynamic duplication without removing resumability.

## 4. Worker / Supervisory Appendix Changes

Worker and supervisory appendices were compacted in [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py).

Changes:

- verbose worker appendix became `[WORKER UPDATES]`
- only material worker events are included
- low-value progress chatter is suppressed
- worker items are capped and normalized into short role/type/summary lines
- supervisory appendix became `[SUPERVISION]`
- alerts are capped, normalized, and only a short priority hint is appended when input is required

This reduces appendix sprawl while preserving critical signals.

## 5. Broker Evidence Density Changes

Broker evidence density is now controlled by `_prepare_context_evidence` in [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py).

Changes:

- evidence is selected with a best-of-domain strategy
- duplicate/near-duplicate evidence is suppressed
- total evidence cap is profile-aware
- troubleshooting keeps more evidence than conversational or standard operational turns
- per-domain caps prevent one domain from dominating rich turns

This keeps evidence useful without letting it overwhelm the planner.

## 6. Evidence vs Grounding Balance Changes

Pass 5 tightened the balance between:

- broker evidence
- action grounding
- live/session grounding

Main behavior:

- when evidence is present, state blocks are clipped more aggressively
- action grounding remains present, but evidence gets a better cost/value ratio
- when evidence is absent, live/session grounding remains intact
- troubleshooting retains a stronger evidence budget than ordinary turns

This improves efficiency without making planning depend on broker success.

## 7. Prompt Profiles or Mode Refinements Introduced (if any)

Pass 5 refined prompt-profile handling by adding an explicit `troubleshooting` profile on top of the existing profile split.

Current profiles:

- `conversational`
- `operational`
- `troubleshooting`

These profiles now affect:

- dynamic state clipping
- evidence caps
- evidence density policy

The profile system remains local and explicit rather than framework-heavy.

## 8. Blocks Still Kept and Why

Still kept intentionally:

- structured output contract
- execution policy
- system context
- TOON state
- session summary
- action grounding
- broker guidance
- broker evidence channel

These remain because the planner still needs deterministic reliability, current-state continuity, and sufficient fallback grounding in evidence-poor turns.

## 9. Evidence-Present vs Evidence-Absent Metrics

The existing evidence-mode metrics remain active and now work alongside the new density metrics.

Relevant metrics now include:

- evidence-present vs evidence-absent mode
- broker load vs grounding load
- evidence coverage ratio
- raw evidence count
- kept vs suppressed evidence count
- kept/suppressed evidence by domain

This makes broker contribution more inspectable in rich turns.

## 10. Prompt Size / Reduction Metrics

Pass 5 added:

- `estimated_before_pass5_chars`
- `estimated_after_pass5_chars`
- `estimated_pass5_reduction_chars`
- `dynamic_state_metrics`
- `evidence_density_metrics`

`retained_focus_sizes` was also extended with:

- `toon_chars`
- `session_state_chars`
- `broker_evidence_chars`

At the orchestrator layer, prompt metrics now also include:

- `worker_appendix_metrics`
- `supervisory_appendix_metrics`

## 11. Orchestrator / Prompt Composer Changes

Main changes:

- [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py)
  - dynamic clipping for state and evidence
  - scratchpad redundancy suppression
  - troubleshooting profile inference
  - profile-aware evidence density selection
  - pass-5 observability for state/evidence cost

- [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py)
  - compact worker appendix builder
  - compact supervisory appendix builder
  - appendix metrics persisted into `last_prompt_reduction`

The broker itself was not redesigned.

## 12. Tests Added

New tests:

- [tests/context/test_prompt_reduction_pass5.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass5.py)
- [tests/context/test_prompt_reduction_pass5_fallback.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass5_fallback.py)
- [tests/context/test_prompt_reduction_pass5_integration.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass5_integration.py)
- [tests/context/test_prompt_reduction_pass5_metrics.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass5_metrics.py)
- [tests/context/test_broker_evidence_density.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_broker_evidence_density.py)

Adjusted compatibility coverage:

- [tests/minimal/test_supervisor_inbox_v2.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/minimal/test_supervisor_inbox_v2.py)

Validated with:

- `./env/bin/pytest -q tests/context/test_prompt_reduction_pass1.py tests/context/test_prompt_reduction_fallback.py tests/context/test_prompt_reduction_integration.py tests/context/test_prompt_reduction_pass2.py tests/context/test_prompt_reduction_pass2_fallback.py tests/context/test_prompt_reduction_pass2_integration.py tests/context/test_prompt_reduction_pass3.py tests/context/test_prompt_reduction_pass3_fallback.py tests/context/test_prompt_reduction_pass3_integration.py tests/context/test_prompt_reduction_pass3_metrics.py tests/context/test_prompt_reduction_pass4.py tests/context/test_prompt_reduction_pass4_fallback.py tests/context/test_prompt_reduction_pass4_integration.py tests/context/test_prompt_reduction_pass4_metrics.py tests/context/test_prompt_reduction_pass5.py tests/context/test_prompt_reduction_pass5_fallback.py tests/context/test_prompt_reduction_pass5_integration.py tests/context/test_prompt_reduction_pass5_metrics.py tests/context/test_broker_evidence_density.py tests/minimal/test_prompt_persona_scope.py tests/minimal/test_prompt_composer_assistive_mode.py`
- `/usr/bin/python3 -m compileall src/services/llm/prompt_composer.py src/core/orchestrator.py`

Result:

- `29 passed`

## 13. Fallback / Degraded Mode Behavior

Fallback remains safe:

- no-evidence mode still produces a valid planner prompt
- action grounding still remains present
- long TOON/session payloads are compacted, not removed
- worker/supervisory appendices can be absent safely
- degraded tool conditions still remain represented through compact presentation guidance

This pass reduced redundancy, not resilience.

## 14. Remaining Dynamic Prompt Debt

Remaining dynamic prompt debt is now concentrated in:

- very long TOON state snapshots in long-running sessions
- broker evidence content quality when retrieved chunks are individually verbose
- background worker/supervisory flows outside compact appendices
- overlap between relevant memory and session summary in some long turns

These are smaller and more tractable than the earlier fixed prompt debt.

## 15. Recommended Next Step

Recommended next step: a final dynamic-context refinement pass focused on state summarization quality rather than pure structural compaction.

Priority areas:

- stronger TOON/state summarization for long sessions
- richer evidence summarization before prompt injection
- better overlap detection between relevant memory, summary, and scratchpad
- optional compression of worker/supervision signals into state rather than appendices when safe

## Relacionados

- [../architecture/README.md](../architecture/README.md): onde a reducao de prompt cruza com o desenho do runtime e da orchestracao.
- [../guides/testing_guide.md](../guides/testing_guide.md): guia util para validar o comportamento do prompt composer.
- [../../agent/specs/atlas_operating_model.spec.md](../../agent/specs/atlas_operating_model.spec.md): contrato que delimita prompt, discovery, tool use e approval.
- [../../agent/specs/atlas_operating_model.stat.md](../../agent/specs/atlas_operating_model.stat.md): estado vivo do modelo operacional.
