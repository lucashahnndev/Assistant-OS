# Prompt Reduction Pass 3 Report

> Historical report. Some terminology and architecture assumptions here were superseded by the current discovery-first contract.

## 1. Executive Summary

Prompt Reduction Pass 3 moved the planner further from legacy prompt-heavy operational framing toward broker-first grounding without removing kernel rules, live context, session state, or deterministic enforcement.

This pass focused on the highest-value remaining prompt debt:

- compacting the instruction pack payload
- removing the `[DYNAMIC CONTEXT]` wrapper and making retained blocks individually auditable
- compressing cognitive-frame formatting
- tightening action catalog framing while keeping action grounding intact
- extending prompt observability to compare broker-evidence mode vs fallback-only mode

The result is a smaller and more inspectable prompt path that still degrades safely when broker evidence is absent.

## 2. Largest Retained Blocks Audited

Prompt metrics now expose:

- `retained_block_sizes`
- `largest_retained_blocks`
- `largest_retained_blocks_audit`
- `retained_block_audit`
- `grouped_load_chars`

Retained blocks are now classified into:

- `A_true_kernel`
- `B_live_context`
- `C_session_state`
- `D_grounding_compactable`
- `E_legacy_debt_or_misc`

This makes it easier to separate real kernel load from still-compactable grounding load in future passes.

## 3. Instruction Pack Audit and Changes

The instruction pack in [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L4626) was compacted from a more descriptive JSON payload into a denser `ip.v2` payload.

Changes:

- `persona_scope` became `scope`
- `lang` was collapsed into a single compact string
- `present` became a short mode marker
- browser intent guidance now stores only allowed values plus `infer=true`
- output schema framing was reduced to a compact `out` list
- voice reply constraints were collapsed into a short string

This preserves planner grounding while removing descriptive prose that duplicated broker-covered operational knowledge.

## 4. Cognitive Frame / Action Catalog Changes

In [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py#L183), the old verbose cognitive sections:

- `[COGNITIVE FRAME - FOREGROUND]`
- `[COGNITIVE FRAME - SUPPORTING]`

were replaced with denser blocks:

- `[FOCUS]`
- `[BACKGROUND]`

The content remains semantically equivalent, but the phrasing is much tighter.

In [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py#L5162), action catalog framing was compacted:

- `Catalog mode: ...` became `m=...`
- `ac.v2` became `ac.v3`
- payload keys such as `discover`, `rules`, and `prefer_reply` were shortened to `d`, `r`, and `pr`

The action catalog itself remains present and usable. This pass reduced framing, not grounding.

## 5. Additional Blocks Reduced or Removed

Additional reductions in this pass:

- removed the `[DYNAMIC CONTEXT]` wrapper from prompt assembly
- reduced the execution policy block again while preserving core safety rules
- made dynamic blocks individually injected and individually measurable
- reduced catalog and instruction-pack framing around browser intent behavior that is already represented in broker-aware grounding

## 6. Blocks Still Kept and Why

Still kept intentionally:

- kernel identity and behavior rules
- `[STRUCTURED OUTPUT CONTRACT]`
- `[SYSTEM CONTEXT]`
- `[INTERNAL STATE (TOON)]`
- session continuity blocks such as summary, scratchpad, relevant memory, and cognitive frame
- `[ACTIONS]` with compact action availability grounding
- `[BROKER GUIDANCE]`

These remain because the planner still needs stable kernel behavior, live execution continuity, and fallback grounding even when retrieval is empty or partial.

## 7. Broker-Aware Grounding Strategy

The grounding strategy is now more explicit:

- broker evidence is the preferred source for operational knowledge
- live state and session context remain active grounding
- action availability remains fallback execution grounding
- no-evidence mode remains fully valid

This pass did not create a hard dependency on broker success. It only shifted more redundant fixed prose out of the prompt path.

## 8. Evidence-Present vs Evidence-Absent Metrics

Prompt metrics now include `evidence_mode_comparison`, with:

- `mode`
- `domains`
- `fallback_grounding_relied_upon`
- `broker_load_chars`
- `grounding_load_chars`
- `estimated_prompt_chars_if_evidence_absent`
- `estimated_prompt_chars_if_evidence_present`
- `evidence_coverage_ratio`

This makes it possible to inspect how much of the current prompt load is coming from broker evidence versus fallback grounding.

## 9. Prompt Size / Reduction Metrics

PromptComposer metrics now expose richer retained-block and load-group views:

- `retained_block_audit`
- `largest_retained_blocks_audit`
- `grouped_load_chars`
- `replacement_modes`

These complement the existing size metrics:

- `estimated_before_chars`
- `estimated_after_chars`
- `estimated_reduction_chars`
- `estimated_total_reduction_chars`

Together they allow later passes to target the biggest remaining non-kernel costs more safely.

## 10. Orchestrator / Prompt Composer Changes

Main changes:

- [src/services/llm/prompt_composer.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/prompt_composer.py)
  - compacted cognitive frame
  - removed dynamic wrapper
  - tightened execution policy wording
  - added retained-block classification and grouped load metrics
  - added evidence-present vs evidence-absent comparison metrics

- [src/core/orchestrator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/orchestrator.py)
  - compacted instruction pack payload
  - compacted action catalog framing and payload keys
  - updated prompt metrics capture to the new block layout
  - continued persisting prompt reduction metrics into `session.context["last_prompt_reduction"]` and the broker snapshot

## 11. Tests Added

New tests:

- [tests/context/test_prompt_reduction_pass3.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass3.py)
- [tests/context/test_prompt_reduction_pass3_fallback.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass3_fallback.py)
- [tests/context/test_prompt_reduction_pass3_integration.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass3_integration.py)
- [tests/context/test_prompt_reduction_pass3_metrics.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/context/test_prompt_reduction_pass3_metrics.py)

Validated with:

- `./env/bin/pytest -q tests/context/test_prompt_reduction_pass1.py tests/context/test_prompt_reduction_fallback.py tests/context/test_prompt_reduction_integration.py tests/context/test_prompt_reduction_pass2.py tests/context/test_prompt_reduction_pass2_fallback.py tests/context/test_prompt_reduction_pass2_integration.py tests/context/test_prompt_reduction_pass3.py tests/context/test_prompt_reduction_pass3_fallback.py tests/context/test_prompt_reduction_pass3_integration.py tests/context/test_prompt_reduction_pass3_metrics.py tests/minimal/test_prompt_composer_assistive_mode.py`
- `/usr/bin/python3 -m compileall src/services/llm/prompt_composer.py src/core/orchestrator.py`

Result:

- `17 passed`

## 12. Fallback / Degraded Mode Behavior

Fallback remains safe:

- if broker evidence is absent, prompt composition still injects live state, session state, and action grounding
- if broker evidence is present, planner gets compact broker-first operational grounding
- if one or more retrieval domains return nothing, prompt construction still succeeds
- no new hard dependency on broker success was introduced

## 13. Remaining Prompt Debt

Largest remaining likely debt after Pass 3:

- structured output contract size
- presentation directive accumulation
- action manifest payload size on large capability surfaces
- TOON/session state cost in long-running sessions
- response persona / specialist payload when enabled

These were left in place because they are either kernel-critical or still risk planner instability if reduced too aggressively without more measurement.

## 14. Recommended Next Step

Recommended next step: `Prompt Reduction Pass 4`.

Focus areas:

- measure whether structured output contract can be compacted without harming JSON reliability
- selectively compress large action manifest payloads using stronger on-demand grounding
- evaluate whether presentation directive and specialist hint content can be normalized into a smaller kernel-level form
- introduce controlled per-mode prompt profiles for conversational vs operational turns while preserving shared kernel behavior
