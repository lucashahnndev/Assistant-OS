import { useEffect, useState } from 'react';
import { api } from '../hooks/api';
import { Activity, Brain, RefreshCw, Search } from 'lucide-react';
import PageHeader from '../components/PageHeader';
import { buildCognitionDiagnosticsViewModel } from './CognitionDiagnostics.model';

const normalizeSessionItem = (item) => {
    const source = String(item?.source || item?.interface || 'web').trim() || 'web';
    const id = String(item?.session_id || item?.id || '').trim();
    if (!id) return null;
    return {
        id,
        label: String(item?.name || id).trim() || id,
        source,
    };
};

const DiagnosticsSection = ({ section }) => (
    <section className="glass" style={{ padding: '20px', borderRadius: '14px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
            <h3 style={{ fontSize: '15px', fontWeight: '800', letterSpacing: '0.01em' }}>{section.title}</h3>
            {section.chips?.length > 0 && (
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    {section.chips.map((chip) => (
                        <span
                            key={chip}
                            style={{
                                padding: '4px 10px',
                                borderRadius: '999px',
                                background: 'rgba(75, 106, 149, 0.12)',
                                border: '1px solid rgba(75, 106, 149, 0.22)',
                                fontSize: '11px',
                                fontWeight: '700',
                                color: 'var(--accent-color)',
                            }}
                        >
                            {chip}
                        </span>
                    ))}
                </div>
            )}
        </div>

        {section.rows?.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px' }}>
                {section.rows.map((row) => (
                    <div key={row.label} style={{ padding: '12px', borderRadius: '12px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: '6px' }}>{row.label}</div>
                        <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>{String(row.value ?? 'n/a')}</div>
                    </div>
                ))}
            </div>
        )}

        {section.pairs?.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {section.pairs.map((pair) => (
                    <div key={pair.key} style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', fontSize: '13px', padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>{pair.key}</span>
                        <strong style={{ color: 'var(--text-primary)' }}>{String(pair.value)}</strong>
                    </div>
                ))}
            </div>
        )}

        {section.lists?.filter((group) => group.values?.length > 0).map((group) => (
            <div key={group.label} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)' }}>{group.label}</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {group.values.map((item, index) => (
                        <div key={`${group.label}-${index}`} style={{ padding: '10px 12px', borderRadius: '10px', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', fontSize: '13px', color: 'var(--text-secondary)' }}>
                            {item}
                        </div>
                    ))}
                </div>
            </div>
        ))}
    </section>
);

const CognitionDiagnostics = () => {
    const [sessions, setSessions] = useState([]);
    const [selectedSessionId, setSelectedSessionId] = useState('');
    const [payload, setPayload] = useState(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState('');

    const fetchSessions = async () => {
        const list = await api.get('/sessions');
        return Array.isArray(list) ? list.map(normalizeSessionItem).filter(Boolean) : [];
    };

    const fetchDiagnostics = async (sessionId, { silent = false } = {}) => {
        if (!sessionId) {
            setPayload(null);
            setLoading(false);
            return;
        }
        if (silent) {
            setRefreshing(true);
        } else {
            setLoading(true);
        }
        setError('');
        try {
            const data = await api.get(`/sessions/${sessionId}/cognition`);
            setPayload(data);
        } catch (err) {
            setError(err.message || 'Failed to load cognitive diagnostics');
            setPayload(null);
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    };

    useEffect(() => {
        let cancelled = false;
        const init = async () => {
            setLoading(true);
            try {
                const [active, list] = await Promise.all([
                    api.get('/sessions/active'),
                    fetchSessions(),
                ]);
                if (cancelled) return;
                setSessions(list);
                const activeId = String(active?.id || '').trim();
                const firstId = list[0]?.id || '';
                const targetId = activeId || firstId;
                setSelectedSessionId(targetId);
                if (targetId) {
                    await fetchDiagnostics(targetId);
                } else {
                    setPayload(null);
                    setLoading(false);
                }
            } catch (err) {
                if (cancelled) return;
                setError(err.message || 'Failed to load sessions');
                setLoading(false);
            }
        };
        init();
        return () => {
            cancelled = true;
        };
    }, []);

    const viewModel = buildCognitionDiagnosticsViewModel(payload);

    return (
        <div className="animate-fade-in" style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <PageHeader
                title="Cognitive Diagnostics"
                subtitle="Thin operational visibility for cognition, hints, outcomes, and broker cross-telemetry."
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', width: '100%', justifyContent: 'space-between', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: '260px', flex: '1 1 280px' }}>
                        <div style={{ position: 'relative', flex: 1 }}>
                            <Search size={14} style={{ position: 'absolute', left: '10px', top: '10px', opacity: 0.55 }} />
                            <select
                                className="input-field"
                                value={selectedSessionId}
                                onChange={(e) => {
                                    const nextId = e.target.value;
                                    setSelectedSessionId(nextId);
                                    fetchDiagnostics(nextId);
                                }}
                                style={{ paddingLeft: '34px', height: '36px' }}
                            >
                                {!sessions.length && <option value="">No sessions available</option>}
                                {sessions.map((session) => (
                                    <option key={session.id} value={session.id}>
                                        {`${session.label} (${session.source})`}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>
                    <button
                        onClick={() => fetchDiagnostics(selectedSessionId, { silent: true })}
                        className="btn-ghost"
                        disabled={!selectedSessionId || refreshing}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '8px 12px' }}
                    >
                        <RefreshCw size={16} className={refreshing ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>
            </PageHeader>

            <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '0 var(--space-6) 100px' }}>
                {loading ? (
                    <div className="glass" style={{ padding: '60px', borderRadius: '16px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px' }}>
                        <RefreshCw size={24} className="animate-spin" color="var(--accent-color)" />
                        <span style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>Loading cognitive diagnostics...</span>
                    </div>
                ) : !viewModel.hasData ? (
                    <div className="glass" style={{ padding: '48px', borderRadius: '16px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', textAlign: 'center' }}>
                        <Brain size={28} color="var(--accent-color)" />
                        <strong style={{ fontSize: '18px' }}>No Cognitive Telemetry Yet</strong>
                        <p style={{ color: 'var(--text-secondary)', maxWidth: '56ch' }}>
                            Start or select a session with cognitive activity to inspect hints, outcomes, strategic usefulness, and fallback behavior.
                        </p>
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
                            <div className="glass" style={{ padding: '18px', borderRadius: '14px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                                    <Activity size={16} color="var(--accent-color)" />
                                    <strong>Session</strong>
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', color: 'var(--text-secondary)', fontSize: '13px' }}>
                                    <span>{`ID: ${viewModel.sessionId || 'n/a'}`}</span>
                                    <span>{`Mission: ${payload?.current_cognitive_state?.mission || 'None'}`}</span>
                                    <span>{`Focus task: ${payload?.current_cognitive_state?.focus?.primary_task_id || 'None'}`}</span>
                                </div>
                            </div>
                            <div className="glass" style={{ padding: '18px', borderRadius: '14px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                                    <Brain size={16} color="var(--accent-color)" />
                                    <strong>Projection</strong>
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', color: 'var(--text-secondary)', fontSize: '13px' }}>
                                    <span>{`Focus lines: ${payload?.last_cognitive_projection?.focus_line_count ?? 0}`}</span>
                                    <span>{`Background lines: ${payload?.last_cognitive_projection?.background_line_count ?? 0}`}</span>
                                    <span>{`Generic outcomes: ${payload?.outcome_coverage?.generic_fallback_count ?? 0}`}</span>
                                </div>
                            </div>
                        </div>

                        {error && (
                            <div className="glass" style={{ padding: '14px 16px', borderRadius: '12px', borderColor: 'rgba(239,68,68,0.35)', color: '#fca5a5' }}>
                                {error}
                            </div>
                        )}

                        {viewModel.sections.map((section) => (
                            <DiagnosticsSection key={section.id} section={section} />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};

export default CognitionDiagnostics;
