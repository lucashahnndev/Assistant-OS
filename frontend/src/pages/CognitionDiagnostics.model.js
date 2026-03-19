const normalizePairs = (entries) =>
    Object.entries(entries || {})
        .filter(([key, value]) => String(key || '').trim() && value !== null && value !== undefined && value !== '')
        .map(([key, value]) => ({ key: String(key), value }));

const formatBool = (value) => (value ? 'Yes' : 'No');

export const buildCognitionDiagnosticsViewModel = (payload) => {
    const state = payload?.current_cognitive_state || {};
    const diagnostics = payload?.last_cognitive_layer || {};
    const hint = payload?.hint_telemetry || {};
    const outcome = payload?.outcome_coverage || {};
    const usefulness = payload?.strategic_usefulness || {};
    const counters = payload?.counters || {};
    const broker = payload?.broker_cross_telemetry || {};

    const hasData = Boolean(payload && (state?.mission || diagnostics?.phase || Object.keys(counters || {}).length > 0));

    const sections = [
        {
            id: 'state',
            title: 'Current Cognitive State',
            rows: [
                { label: 'Mission', value: state?.mission || 'None' },
                { label: 'Focus', value: state?.focus?.primary_summary || state?.focus?.primary_task_id || 'None' },
                { label: 'Open loops', value: state?.open_loops_count ?? 0 },
                { label: 'Blockers', value: state?.blockers_count ?? 0 },
                { label: 'Constraints', value: state?.constraints_count ?? 0 },
                { label: 'Watchpoints', value: state?.watchpoints_count ?? 0 },
                { label: 'Decisions', value: state?.decisions_count ?? 0 },
                { label: 'Checkpoints', value: state?.checkpoints_count ?? 0 },
                { label: 'Recent progress', value: state?.recent_progress_count ?? 0 },
            ],
            lists: [
                { label: 'Open loops preview', values: state?.open_loops_preview || [] },
                { label: 'Blockers preview', values: state?.blockers_preview || [] },
            ],
        },
        {
            id: 'diagnostics',
            title: 'Latest Diagnostics',
            rows: [
                { label: 'Phase', value: diagnostics?.phase || 'n/a' },
                { label: 'Commit performed', value: formatBool(diagnostics?.commit_performed) },
                { label: 'Outcome type', value: diagnostics?.normalized_outcome_type || 'n/a' },
                { label: 'Fallback used', value: formatBool(diagnostics?.fallback_used) },
                { label: 'Commit signal', value: diagnostics?.commit_signal_strength || 'none' },
                { label: 'Planner relevance', value: formatBool(diagnostics?.planner_relevance_signal) },
            ],
            chips: diagnostics?.changed_fields || [],
        },
        {
            id: 'hint',
            title: 'Hint Effectiveness',
            rows: [
                { label: 'Generated', value: formatBool(hint?.generated) },
                { label: 'Applied', value: formatBool(hint?.applied) },
                { label: 'Ignored', value: formatBool(hint?.ignored) },
                { label: 'Suppressed', value: formatBool(hint?.suppressed) },
                { label: 'Ranking changed', value: formatBool(hint?.ranking_changed_by_hint) },
            ],
            lists: [
                { label: 'Hinted domains', values: hint?.hinted_domains || [] },
                { label: 'Hint impact', values: hint?.hint_impact_summary || [] },
            ],
        },
        {
            id: 'outcome',
            title: 'Outcome Coverage',
            rows: [
                { label: 'Generic fallback count', value: outcome?.generic_fallback_count ?? 0 },
                { label: 'Generic fallback streak', value: outcome?.generic_fallback_streak ?? 0 },
            ],
            pairs: normalizePairs(outcome?.counts_by_type || {}),
        },
        {
            id: 'usefulness',
            title: 'Strategic Usefulness',
            rows: [
                { label: 'Commit signal', value: usefulness?.commit_signal_strength || 'none' },
                { label: 'Planner relevance', value: formatBool(usefulness?.planner_relevance_signal) },
            ],
            lists: [
                { label: 'Fields populated', values: usefulness?.fields_populated || [] },
                { label: 'Fields changed', values: usefulness?.fields_changed || [] },
                { label: 'Fields projected', values: usefulness?.fields_projected || [] },
            ],
            pairs: normalizePairs(usefulness?.projection_field_sizes || {}),
        },
        {
            id: 'counters',
            title: 'Session Counters',
            rows: [
                { label: 'Reconcile turns', value: counters?.reconcile_turns ?? 0 },
                { label: 'Commit turns', value: counters?.commit_turns ?? 0 },
                { label: 'Hints generated', value: counters?.hints_generated ?? 0 },
                { label: 'Hints applied', value: counters?.hints_applied ?? 0 },
                { label: 'Hints ignored', value: counters?.hints_ignored ?? 0 },
                { label: 'Planner relevance turns', value: counters?.planner_relevance_turns ?? 0 },
            ],
            pairs: normalizePairs(counters?.commit_signal_strength || {}),
        },
        {
            id: 'broker',
            title: 'Broker Cross-Telemetry',
            rows: [
                { label: 'Evidence present', value: formatBool(broker?.evidence_present) },
                { label: 'Evidence count', value: broker?.evidence_count ?? 0 },
                { label: 'Evidence chars', value: broker?.total_evidence_chars ?? 0 },
                { label: 'Density reductions', value: broker?.evidence_density_reduction_count ?? 0 },
                { label: 'Low-value suppressed', value: broker?.low_value_suppressed_count ?? 0 },
                { label: 'Hint applied in broker', value: formatBool(broker?.hint_applied) },
            ],
            lists: [
                { label: 'Queried domains', values: broker?.domains_queried || [] },
                { label: 'Evidence domains', values: broker?.evidence_domains || [] },
                { label: 'Broker hint impact', values: broker?.hint_impact_summary || [] },
                { label: 'Conflict resolution', values: broker?.domain_conflict_resolution_summary || [] },
            ],
            pairs: [
                ...normalizePairs(broker?.evidence_counts_by_domain_selected || {}),
                ...normalizePairs(broker?.evidence_counts_by_domain_suppressed || {}),
                ...normalizePairs(broker?.rerank_win_by_domain || {}),
            ],
        },
    ];

    return {
        hasData,
        title: 'Cognitive Diagnostics',
        sessionId: payload?.session_id || '',
        sections,
    };
};
