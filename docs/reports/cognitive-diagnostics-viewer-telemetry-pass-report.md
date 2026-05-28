# Cognitive Diagnostics Viewer + Telemetry Pass

> Historical report. This telemetry/viewer pass reflects an earlier instrumentation stage and may not match the current discovery-first contract.

## 1. Executive Summary

This pass adds a thin operational diagnostics surface for the existing cognitive architecture.

It does not change the cognition design. Instead, it exposes the already-implemented telemetry from Stage 1, Stage 2, v1.1, and v1.2 so real sessions can be inspected safely and quickly.

The implementation adds:

- compact backend cognition diagnostics routes
- a thin frontend diagnostics viewer
- session-level exposure of current and cumulative cognition telemetry
- compact broker/cognition cross-telemetry
- backend, integration, and viewer tests

## 2. Backend Diagnostics Exposure Added

Backend exposure was added in `src/server/routes/sessions.py`.

New route shapes:

- `/api/sessions/{session_id}/cognition`
- `/api/sessions/{session_id}/cognition/snapshot`
- `/api/sessions/{session_id}/cognition/counters`

The payloads are intentionally compact and operational. They expose:

- current cognitive state summary
- last cognitive projection summary
- latest cognitive diagnostics snapshot
- hint telemetry
- outcome coverage summary
- strategic usefulness summary
- fallback telemetry
- broker/cognition cross-telemetry
- cumulative `cognitive_effectiveness_counters`

The routes do not dump raw hidden reasoning, full session context, or large logs.

## 3. Viewer / UI Changes

A thin diagnostics viewer was added to the frontend:

- `frontend/src/pages/CognitionDiagnostics.jsx`
- `frontend/src/pages/CognitionDiagnostics.model.js`

It is available as a dedicated page inside the existing shell and was wired into:

- `frontend/src/App.jsx`
- `frontend/src/layouts/DashboardLayout.jsx`
- locale labels in `frontend/src/i18n/locales/*.json`

The viewer supports:

- selecting a session
- defaulting to the active/latest useful session
- refreshing current telemetry
- showing empty/no-data state safely

The UI stays intentionally thin: compact cards, lists, counters, and no heavy analytics/dashboard layer.

## 4. Cognitive Telemetry Surfaced

The viewer now surfaces:

- current mission and focus
- open loops / blockers / constraints / watchpoints / decisions / checkpoints / recent progress counts
- latest changed fields
- commit performed
- normalized outcome type
- fallback used + fallback mode
- commit signal strength
- planner relevance signal
- populated / changed / projected strategic fields
- projection field sizes
- counts by normalized outcome type
- generic fallback count and streak
- cumulative hint / commit / relevance counters

This makes it easier to spot:

- generic outcome overuse
- weak commit signal
- inert strategic fields
- frequent fallback
- sessions where cognition is mostly decorative

## 5. Broker/Cognition Cross-Telemetry Surfaced

Where data already existed, the viewer now exposes the broker/cognition overlap:

- evidence present vs absent
- evidence count
- queried domains
- evidence domains selected
- hint applied / ignored at broker level
- hinted domains
- hint impact summary
- hint ranking change signal

This is intentionally lightweight and reuses already-available snapshots instead of creating a new telemetry subsystem.

## 6. Real Session Validation Workflow

A practical debugging workflow is now available:

1. Open the Cognition page in the dashboard.
2. Select the session to inspect.
3. Compare current cognitive state summary against latest diagnostics.
4. Check cumulative counters for repeated generic fallback or low hint impact.
5. Use broker cross-telemetry to see whether hints actually influenced evidence routing/ranking.
6. Use strategic usefulness and commit signal strength to identify the next refinement target.

This supports real-session questions such as:

- are hints being generated but ignored?
- are outcomes still collapsing into generic buckets?
- are we populating fields that never get projected?
- are commits mostly weak or mostly strong?
- are fallback paths happening too often?

## 7. Tests Added

New tests added:

- `tests/cognition/test_cognitive_diagnostics_routes.py`
- `tests/cognition/test_cognitive_diagnostics_viewer.py`
- `tests/cognition/test_cognitive_diagnostics_integration.py`

Coverage includes:

- backend route shape
- counters route shape
- missing session safety
- empty telemetry safety
- integration with real stored session telemetry
- broker/cognition cross-telemetry exposure
- partial-field degraded mode safety
- viewer model section rendering
- viewer model empty state handling

Validation performed:

- `env/bin/python -m pytest tests/cognition`
- `npm run build` in `frontend/`

Results:

- `44 passed`
- frontend build succeeded

## 8. Current Limitations

- the viewer is session-scoped and does not compare across sessions
- the UI is intentionally card/list based and does not include charting
- viewer testing is currently model-focused rather than full DOM-testing infrastructure
- cumulative telemetry is persisted in-session context, not exported to a wider observability backend
- no dedicated “latest cognition session” route was added because existing active/session listing was sufficient

## 9. Recommended Next Refinement Step

The next refinement step should be evidence-driven and small:

1. review real-session `generic_fallback_count` and `generic_outcome_streak`
2. inspect sessions with high hint generation but low hint application
3. identify strategic fields that are frequently populated but rarely projected or planner-relevant
4. refine only the highest-frequency low-value branches
5. optionally add a compact cross-session comparison view later, but only after this session-level viewer is used in practice

The main goal now should be operational learning from real telemetry, not adding more architecture.
