# Cognitive Layer v1.2 - Effectiveness Pass

## 1. Executive Summary

Cognitive Layer v1.2 was implemented as a bounded refinement pass over the existing v1, Stage 2, and v1.1 architecture.

This pass does not introduce a new cognition architecture. It improves:

- broker hint effectiveness tracking
- normalized outcome coverage visibility
- strategic state usefulness diagnostics
- planner-relevance signaling
- conservative commit calibration
- session-level effectiveness counters

All additions remain deterministic, compact, inspectable, and non-critical to execution flow.

## 2. Broker Hint Effectiveness Tracking

Broker hint effectiveness was extended in three places:

- `src/services/cognition/hints.py`
- `src/services/context/models.py`
- `src/services/context/broker.py`

Implemented tracking includes:

- whether hints were generated
- generated hint categories
- signal strength (`none`, `low`, `medium`, `high`)
- hinted domains
- whether hints changed retrieval activation
- whether hints changed retrieval priority
- whether hint presence changed rerank outcome
- whether the hint was applied or ignored
- compact hint impact summaries

The broker now compares:

- routing with hints
- routing without hints
- ranking with hints
- ranking without hints

This comparison is used only for diagnostics and does not create a hard dependency from the broker back into cognition.

## 3. Outcome Coverage Audit and Refinements

Outcome coverage improvements were implemented in:

- `src/services/cognition/outcomes.py`
- `src/services/cognition/committer.py`
- `src/services/cognition/layer.py`
- `src/core/orchestrator.py`

New outcome diagnostics include:

- `normalized_outcome_type`
- `outcome_type_generic_fallback_used`
- `coverage_label` on normalized outcomes
- per-session `outcome_types` counters
- per-session `generic_outcomes` count
- `generic_outcome_streak` warning signal

Conservative normalization refinement:

- unknown explicit outcome types remain deterministic and visible
- they are now flagged as generic fallback coverage gaps instead of silently looking fully intentional

This improves inspectability without expanding the taxonomy aggressively.

## 4. Strategic State Usefulness Metrics

Strategic usefulness instrumentation was added through:

- `src/services/cognition/effectiveness.py`
- `src/services/cognition/layer.py`
- `src/services/cognition/models.py`

Tracked strategic usefulness fields now include:

- `cognitive_fields_populated`
- `cognitive_fields_changed`
- `cognitive_fields_projected`
- `cognitive_fields_derived_from_outcome`
- `projection_field_sizes`
- `projection_non_empty`

The tracked field families include:

- mission
- focus
- open_loops
- blockers
- constraints
- watchpoints
- decisions
- checkpoints
- recent_progress

This makes it possible to see which strategic parts were merely carried forward versus which actually contributed to prompt projection or changed because of the turn.

## 5. Commit Rule Calibration Changes

Conservative explicit commit calibration was added in:

- `src/services/cognition/committer.py`

Calibrations implemented:

- suppress low-value decision entries for generic reply-only turns
- suppress low-value checkpoint entries for generic reply-only turns
- suppress noisy progress entries for generic fallback turns
- clear stale watchpoints on task completion
- clear stale watchpoints on low-value generic turns that did not create a real blocker, clarification, approval wait, or handoff

These rules are explicit, bounded, and test-covered. No opaque heuristic planner was added.

## 6. Diagnostics / Observability Changes

`CognitiveDiagnostics` was extended in:

- `src/services/cognition/models.py`

New compact fields include:

- `outcome_type_generic_fallback_used`
- `hint_categories_generated`
- `hinted_domains`
- `hint_impact_summary`
- `ranking_changed_by_hint`
- `hint_low_signal`
- `cognitive_fields_populated`
- `cognitive_fields_changed`
- `cognitive_fields_projected`
- `cognitive_fields_derived_from_outcome`
- `projection_field_sizes`
- `projection_non_empty`
- `strategic_updates_summary`
- `commit_signal_strength`
- `effectiveness_flags`
- `planner_relevance_signal`

Session-level cumulative counters are now persisted in:

- `session.context["cognitive_effectiveness_counters"]`

Tracked counters include:

- reconcile turns
- commit turns
- hints generated/applied/ignored
- routing impacts
- ranking impacts
- projection-non-empty turns
- planner-relevance turns
- strategic-update turns
- normalized outcome counts
- generic fallback counts and streak
- commit signal strength distribution

## 7. Orchestrator / Broker Integration Changes

Integration changes were made in:

- `src/core/orchestrator.py`

Behavior changes:

- pre-turn reconcile diagnostics are enriched with broker hint effectiveness after broker execution
- post-turn commit diagnostics preserve pre-turn hint effectiveness fields
- the latest cognitive snapshot remains in `session.context["last_cognitive_layer"]`
- cumulative effectiveness counters are maintained separately in `session.context["cognitive_effectiveness_counters"]`
- broker diagnostics snapshot now includes expanded hint-effectiveness fields

The broker still works normally with no hints, and planner prompt construction remains valid if diagnostics are absent or partial.

## 8. Fallback Behavior

Fallback safety remains intact.

If the new instrumentation fails:

- broker routing still runs
- broker reranking still runs
- prompt construction still works
- cognitive reconcile still preserves prior valid state
- commit still preserves prior valid state
- existing fallback modes remain visible in diagnostics

Instrumentation is still not a critical-path requirement.

## 9. Tests Added

New tests added:

- `tests/cognition/test_cognitive_effectiveness.py`
- `tests/cognition/test_cognitive_hint_effectiveness.py`
- `tests/cognition/test_cognitive_outcome_coverage.py`
- `tests/cognition/test_cognitive_commit_calibration.py`
- `tests/cognition/test_cognitive_v12_integration.py`

Validated categories:

- hint generation and application tracking
- hint absence safety
- outcome coverage visibility
- generic fallback visibility
- strategic field usefulness metrics
- projection size metrics
- commit calibration behavior
- orchestrator persistence and cumulative counters
- regression safety across existing cognition tests

Validation run:

- `env/bin/python -m pytest tests/cognition`

Result:

- `37 passed`

## 10. Current Limitations

- hint effectiveness is still an approximation based on routing/priority/rerank deltas, not causal attribution
- projection usefulness is inferred from compact field contribution, not planner decision introspection
- outcome coverage warnings are session-local and compact, not exported to a larger telemetry system
- unknown explicit outcomes are flagged, but there is not yet a dedicated reporting UI for taxonomy hotspots
- broker ranking comparison is diagnostic-only and intentionally lightweight

## 11. Recommended Next Stage

Recommended next step:

1. review accumulated `cognitive_effectiveness_counters` on real sessions
2. identify the most common generic outcome fallback branches
3. refine only the highest-value missing outcome mappings
4. tune hint categories and routing influence based on observed `hint_impact_summary`
5. consider a thin diagnostics viewer before any deeper cognition/planner expansion

The next stage should still remain conservative and evidence-driven before any larger planning or memory redesign.
