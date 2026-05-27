import React, { useState, useEffect, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import {
    FileText, Brain, AlertTriangle, Terminal as TerminalIcon, Wrench, Archive, Link2,
    Monitor, ChevronRight, Maximize2, Download, Globe, ArrowUpRight, Zap, X,
    Video, Music, Paperclip
} from 'lucide-react';
import { api } from '../../hooks/api';
import CapabilityIcon from '../CapabilityIcon';
import PlaybackCard from '../PlaybackCard';
import { formatTime, getFileUrl } from '../../utils/chatHistoryTransform';

const INSPECTOR_TABS = [
    { id: 'plan', label: 'Plan', icon: FileText },
    { id: 'thought', label: 'Thought', icon: Brain },
    { id: 'logs', label: 'Logs', icon: AlertTriangle },
    { id: 'terminal', label: 'Terminal', icon: TerminalIcon },
    { id: 'capabilities', label: 'Capabilities', icon: Wrench },
    { id: 'media', label: 'Media', icon: Archive },
    { id: 'sources', label: 'Sources', icon: Link2 },
];

const stepStatusIcon = (status) => {
    switch (status) {
        case 'done': return { icon: '✓', color: '#10b981' };
        case 'in_progress': return { icon: '◉', color: 'var(--accent-color)' };
        case 'blocked': return { icon: '✕', color: '#ef4444' };
        default: return { icon: '○', color: 'var(--text-muted)' };
    }
};

const normalizeInspectorList = (value) => {
    if (!Array.isArray(value)) return [];
    return value
        .map((item) => {
            if (typeof item === 'string') return item;
            if (item && typeof item === 'object') {
                return item.name || item.id || item.key || item.path || item.file || JSON.stringify(item);
            }
            return String(item || '');
        })
        .map((entry) => String(entry || '').trim())
        .filter(Boolean);
};

const URL_EXTRACT_RE = /https?:\/\/[^\s<>)"'\]]+/gi;

const extractUrlsFromAny = (value) => {
    const text = typeof value === 'string' ? value : JSON.stringify(value || {});
    return [...new Set((String(text).match(URL_EXTRACT_RE) || []).map((u) => u.replace(/[.,;!?]+$/, '')))];
};

const isInspectorErrorEvent = (event) => {
    const name = String(event?.event || '').toLowerCase();
    const payload = event?.payload && typeof event.payload === 'object' ? event.payload : {};
    const status = String(payload?.status || '').toLowerCase();
    const errorCode = String(payload?.error_code || payload?.code || payload?.result_reason || '').toLowerCase();
    const reason = String(payload?.reason || '').toLowerCase();
    const summary = String(payload?.summary || payload?.failure_summary || '').toLowerCase();
    const blob = `${name} ${status} ${errorCode} ${reason} ${summary}`;
    return [
        'fail',
        'error',
        'exception',
        'recovery_needed',
        'replan',
        'replanning',
        'validation',
        'schema',
        'llm_error',
        'planner',
        'refusal',
        'timeout',
    ].some((token) => blob.includes(token));
};

const extractInspectorErrorMessage = (payload = {}) => {
    const raw = payload?.error || payload?.message || payload?.details || payload?.reason || payload?.exception || '';
    if (typeof raw === 'string') return raw.trim();
    try {
        return JSON.stringify(raw || {});
    } catch {
        return String(raw || '').trim();
    }
};

export const WorkUnitInspector = ({ workId, sessionId, onExpand, inline = false, open: controlledOpen, onToggle, hideButton = false, hidePanel = false }) => {
    const [open, setOpen] = useState(false);
    const [activeTab, setActiveTab] = useState('plan');
    const [context, setContext] = useState(null);
    const [overwatch, setOverwatch] = useState(null);
    const [sessionPlaybackRuns, setSessionPlaybackRuns] = useState([]);
    const [expandedPlaybackRunId, setExpandedPlaybackRunId] = useState(null);
    const [fullscreenTerminalId, setFullscreenTerminalId] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const hasLoadedOnceRef = useRef(false);
    const fullscreenTerminalBodyRef = useRef(null);

    const uniqueStrings = (items = []) => {
        const seen = new Set();
        const out = [];
        for (const item of items) {
            const value = String(item || '').trim();
            if (!value || seen.has(value)) continue;
            seen.add(value);
            out.push(value);
        }
        return out;
    };

    const isEqualObject = (a, b) => {
        if (a === b) return true;
        try {
            return JSON.stringify(a) === JSON.stringify(b);
        } catch {
            return false;
        }
    };

    const mergeContextIncremental = (prev, next) => {
        if (!next || typeof next !== 'object') return prev || null;
        if (!prev || typeof prev !== 'object') return next;

        const prevPlanner = prev.planner && typeof prev.planner === 'object' ? prev.planner : {};
        const nextPlanner = next.planner && typeof next.planner === 'object' ? next.planner : {};
        const prevData = prev.data && typeof prev.data === 'object' ? prev.data : {};
        const nextData = next.data && typeof next.data === 'object' ? next.data : {};

        const mergedPlanLines = uniqueStrings([
            ...(Array.isArray(prevPlanner.plan) ? prevPlanner.plan : []),
            ...(Array.isArray(nextPlanner.plan) ? nextPlanner.plan : []),
        ]);
        const prevSteps = Array.isArray(prevPlanner.steps) ? prevPlanner.steps : [];
        const nextSteps = Array.isArray(nextPlanner.steps) ? nextPlanner.steps : [];
        const stepMap = new Map();
        prevSteps.forEach((s, i) => {
            const key = String(s?.id || `prev-${i}`);
            stepMap.set(key, s);
        });
        nextSteps.forEach((s, i) => {
            const key = String(s?.id || `next-${i}`);
            if (!stepMap.has(key)) {
                stepMap.set(key, s);
            }
        });
        const mergedSteps = [...stepMap.values()];

        const mergedData = {
            ...prevData,
            ...nextData,
            actions_used: uniqueStrings([
                ...(Array.isArray(prevData.actions_used) ? prevData.actions_used : []),
                ...(Array.isArray(nextData.actions_used) ? nextData.actions_used : []),
            ]),
            capabilities_used: uniqueStrings([
                ...(Array.isArray(prevData.capabilities_used) ? prevData.capabilities_used : []),
                ...(Array.isArray(nextData.capabilities_used) ? nextData.capabilities_used : []),
            ]),
            media_used: uniqueStrings([
                ...(Array.isArray(prevData.media_used) ? prevData.media_used : []),
                ...(Array.isArray(nextData.media_used) ? nextData.media_used : []),
            ]),
            sources_used: (() => {
                const all = [
                    ...(Array.isArray(prevData.sources_used) ? prevData.sources_used : []),
                    ...(Array.isArray(nextData.sources_used) ? nextData.sources_used : []),
                ];
                const seen = new Set();
                const out = [];
                for (const src of all) {
                    const url = String(src?.url || '').trim();
                    if (!url || seen.has(url)) continue;
                    seen.add(url);
                    out.push(src);
                }
                return out;
            })(),
        };

        const merged = {
            ...prev,
            ...next,
            planner: {
                ...prevPlanner,
                ...nextPlanner,
                plan: mergedPlanLines,
                steps: mergedSteps,
            },
            data: mergedData,
        };

        return isEqualObject(prev, merged) ? prev : merged;
    };

    const mergeOverwatchIncremental = (prev, next) => {
        if (!next || typeof next !== 'object') return prev || null;
        if (!prev || typeof prev !== 'object') return next;

        const prevEvents = Array.isArray(prev.events) ? prev.events : [];
        const nextEvents = Array.isArray(next.events) ? next.events : [];
        const seen = new Set(prevEvents.map((e) => `${e?.ts || ''}|${e?.event || ''}|${JSON.stringify(e?.payload || {})}`));
        const mergedEvents = [...prevEvents];
        for (const event of nextEvents) {
            const fp = `${event?.ts || ''}|${event?.event || ''}|${JSON.stringify(event?.payload || {})}`;
            if (seen.has(fp)) continue;
            seen.add(fp);
            mergedEvents.push(event);
        }

        const merged = {
            ...prev,
            ...next,
            events: mergedEvents,
            capabilities_assets: {
                ...(prev.capabilities_assets || {}),
                ...(next.capabilities_assets || {}),
            },
        };
        return isEqualObject(prev, merged) ? prev : merged;
    };

    const load = async (force = false, silent = false) => {
        if (!force && (context || loading)) return;
        if (!silent) {
            if (!hasLoadedOnceRef.current) setLoading(true);
            setError(null);
        }
        try {
            const [ctxRes, owRes] = await Promise.allSettled([
                api.get(`/system/works/${workId}/context`),
                api.get(`/tasks/works/${workId}/overwatch?events_limit=400`),
            ]);
            if (ctxRes.status === 'fulfilled') {
                const nextContext = ctxRes.value?.context || ctxRes.value || {};
                setContext(prev => mergeContextIncremental(prev, nextContext));
                hasLoadedOnceRef.current = true;
            }
            if (owRes.status === 'fulfilled') {
                const nextOw = owRes.value || null;
                setOverwatch(prev => mergeOverwatchIncremental(prev, nextOw));
            }
            if (ctxRes.status !== 'fulfilled' && owRes.status !== 'fulfilled') {
                throw new Error('both context and overwatch failed');
            }
        } catch (e) {
            if (!silent) setError('Could not load work details.');
        } finally {
            if (!silent) setLoading(false);
        }
    };

    const isOpen = typeof controlledOpen === 'boolean' ? controlledOpen : open;

    const toggle = () => {
        if (!isOpen && !hidePanel) load(true);
        if (onToggle) onToggle(!isOpen);
        else setOpen(v => !v);
    };

    useEffect(() => {
        if (!isOpen || !workId || hidePanel) return undefined;

        load(true, false);
        const interval = setInterval(() => {
            load(true, true);
        }, 1000);

        return () => clearInterval(interval);
    }, [isOpen, workId]);

    useEffect(() => {
        if (!isOpen || !sessionId || hidePanel) return undefined;
        let cancelled = false;
        const fetchSessionPlaybackRuns = async () => {
            try {
                const response = await api.get(`/sessions/${sessionId}/playback`);
                if (cancelled) return;
                setSessionPlaybackRuns(Array.isArray(response?.runs) ? response.runs : []);
            } catch {
                if (!cancelled) setSessionPlaybackRuns([]);
            }
        };
        fetchSessionPlaybackRuns();
        return () => {
            cancelled = true;
        };
    }, [isOpen, sessionId, hidePanel]);

    const planner = context?.planner || {};
    const data = context?.data || {};
    const browserPlanner = data?.browser_planner && typeof data.browser_planner === 'object' ? data.browser_planner : {};
    const summary = context?.summary || {};
    const events = Array.isArray(overwatch?.events) ? overwatch.events : [];
    const steps = Array.isArray(planner.steps) ? planner.steps : [];
    const plan = Array.isArray(planner.plan) ? planner.plan : [];
    const capabilities = normalizeInspectorList(data.capabilities_used);
    const actions = normalizeInspectorList(data.actions_used);
    const media = normalizeInspectorList(data.media_used);
    const playbackRunIds = (() => {
        const ids = new Set();
        const fromContext = Array.isArray(data?.playback_runs) ? data.playback_runs : [];
        fromContext.forEach((id) => {
            const value = String(id || '').trim();
            if (value) ids.add(value);
        });
        const lastRun = String(data?.last_playback_run_id || '').trim();
        if (lastRun) ids.add(lastRun);
        return [...ids];
    })();
    const relatedPlaybackRuns = (() => {
        if (!Array.isArray(sessionPlaybackRuns) || sessionPlaybackRuns.length === 0) return [];
        if (playbackRunIds.length === 0) return [];
        const wanted = new Set(playbackRunIds);
        return sessionPlaybackRuns.filter((run) => wanted.has(String(run?.run_id || '').trim()));
    })();
    const thoughtTimeline = (() => {
        const entries = [];
        events.forEach((event) => {
            const payload = event?.payload || {};
            const thought = payload?.summary?.last_thought || payload?.thought || payload?.details;
            if (typeof thought === 'string' && thought.trim()) {
                entries.push({ text: thought.trim(), ts: event?.ts || null });
            }
        });
        if (entries.length === 0 && typeof summary?.last_thought === 'string' && summary.last_thought.trim()) {
            entries.push({ text: summary.last_thought.trim(), ts: context?.updated_at || null });
        }
        if (typeof browserPlanner?.thought === 'string' && browserPlanner.thought.trim()) {
            entries.push({ text: browserPlanner.thought.trim(), ts: browserPlanner?.ts || context?.updated_at || null });
        }
        const dedup = [];
        entries.forEach((entry) => {
            if (!dedup.some((d) => d.text === entry.text)) dedup.push(entry);
        });
        return dedup;
    })();
    const sources = (() => {
        const set = new Set();
        extractUrlsFromAny(plan).forEach((u) => set.add(u));
        extractUrlsFromAny(data).forEach((u) => set.add(u));
        events.forEach((event) => extractUrlsFromAny(event?.payload || {}).forEach((u) => set.add(u)));
        return [...set];
    })();
    const shellTerminals = (() => {
        const terminalsMap = data?.shell?.terminals;
        if (!terminalsMap || typeof terminalsMap !== 'object') return [];
        return Object.values(terminalsMap)
            .filter((item) => item && typeof item === 'object')
            .sort((a, b) => {
                const ta = Number(a?.started_at || 0);
                const tb = Number(b?.started_at || 0);
                return tb - ta;
            });
    })();
    const workerErrors = (() => {
        const fromApi = Array.isArray(overwatch?.worker_errors) ? overwatch.worker_errors : [];
        if (fromApi.length > 0) return fromApi;
        return events
            .filter((event) => isInspectorErrorEvent(event))
            .map((event) => ({
                ts: event?.ts || null,
                event: String(event?.event || 'worker_event'),
                message: extractInspectorErrorMessage(event?.payload || {}),
                payload: event?.payload || {},
                component: null,
                severity: 'error',
                error_code: String(event?.payload?.error_code || event?.payload?.code || event?.payload?.result_reason || '') || null,
            }));
    })();
    const executionLogs = overwatch?.latest_execution_logs && typeof overwatch.latest_execution_logs === 'object'
        ? overwatch.latest_execution_logs
        : { available: false, execution_id: null, tail: '', error_lines: [] };
    const fullscreenTerminal = shellTerminals.find((term) => String(term?.id || '') === String(fullscreenTerminalId || '')) || null;

    useEffect(() => {
        if (!fullscreenTerminalBodyRef.current || !fullscreenTerminalId) return;
        fullscreenTerminalBodyRef.current.scrollTop = fullscreenTerminalBodyRef.current.scrollHeight;
    }, [fullscreenTerminalId, shellTerminals]);

    const renderPlan = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {steps.length > 0 ? steps.map((s, i) => {
                const { icon, color } = stepStatusIcon(s.status);
                return (
                    <div key={s.id || i} style={{ display: 'flex', gap: '9px', alignItems: 'flex-start', padding: '6px 8px', border: '1px solid var(--card-border)', borderRadius: '7px', background: 'rgba(2,6,23,0.02)' }}>
                        <span style={{ color, fontWeight: '900', fontSize: '11px', flexShrink: 0, minWidth: '11px', marginTop: '1px' }}>{icon}</span>
                        <span style={{ fontSize: '12px', color: s.status === 'done' ? 'var(--text-muted)' : 'var(--text-primary)', textDecoration: s.status === 'done' ? 'line-through' : 'none', opacity: s.status === 'done' ? 0.72 : 1 }}>
                            {s.title}
                        </span>
                    </div>
                );
            }) : plan.length > 0 ? plan.map((line, i) => (
                <div key={i} style={{ display: 'flex', gap: '9px', alignItems: 'flex-start', padding: '6px 8px', border: '1px solid var(--card-border)', borderRadius: '7px', background: 'rgba(2,6,23,0.02)' }}>
                    <span style={{ color: 'var(--text-muted)', fontSize: '11px', flexShrink: 0 }}>{'›'}</span>
                    <span style={{ fontSize: '12px', color: 'var(--text-primary)' }}>{String(line).replace(/^\[.\]\s*/, '')}</span>
                </div>
            )) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No plan recorded.</span>}
        </div>
    );

    const renderCapabilities = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {capabilities.length > 0 && (
                <div>
                    <p style={{ fontSize: '10px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: '6px' }}>Capabilities</p>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {capabilities.map((s, i) => (
                            <span key={i} style={{ padding: '3px 8px', background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.35)', borderRadius: '8px', fontSize: '11px', color: 'var(--text-primary)', fontWeight: '700', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                                <CapabilityIcon
                                    variant="inline"
                                    capabilityId={s}
                                    assets={overwatch?.capabilities_assets?.[s]}
                                />
                                {s}
                            </span>
                        ))}
                    </div>
                </div>
            )}
            {actions.length > 0 && (
                <div>
                    <p style={{ fontSize: '10px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: '6px' }}>Actions performed</p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {[...new Set(actions)].map((a, i) => (
                            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: 'var(--text-muted)', flexShrink: 0 }} />
                                <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{a}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {capabilities.length === 0 && actions.length === 0 && (
                <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No capabilities recorded.</span>
            )}
        </div>
    );

    const renderThought = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {browserPlanner?.phase && (
                <div style={{ border: '1px solid var(--card-border)', borderRadius: '7px', background: 'rgba(2,6,23,0.02)', padding: '8px 9px' }}>
                    <p style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '800', marginBottom: '4px' }}>
                        Browser Planner
                    </p>
                    <p style={{ fontSize: '11px', color: 'var(--text-primary)', fontFamily: 'monospace' }}>
                        {String(browserPlanner.phase || 'unknown')}
                        {browserPlanner.step_id ? ` · ${String(browserPlanner.step_id)}` : ''}
                    </p>
                    {browserPlanner.action && (
                        <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px', fontFamily: 'monospace' }}>
                            action: {String(browserPlanner.action)}
                        </p>
                    )}
                    {typeof browserPlanner.parse_failures !== 'undefined' && (
                        <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px', fontFamily: 'monospace' }}>
                            parse_failures: {String(browserPlanner.parse_failures)}
                        </p>
                    )}
                    {browserPlanner.reason && (
                        <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                            reason: {String(browserPlanner.reason)}
                        </p>
                    )}
                    {browserPlanner.error && (
                        <p style={{ fontSize: '11px', color: 'var(--error)', marginTop: '4px', whiteSpace: 'pre-wrap' }}>
                            {String(browserPlanner.error)}
                        </p>
                    )}
                </div>
            )}
            {thoughtTimeline.length > 0 ? thoughtTimeline.map((entry, i) => (
                <div key={i} style={{ display: 'flex', gap: '9px', alignItems: 'flex-start', padding: '8px 9px', border: '1px solid var(--card-border)', borderRadius: '7px', background: 'rgba(2,6,23,0.02)' }}>
                    <Brain size={14} color="var(--text-muted)" style={{ flexShrink: 0, marginTop: '1px' }} />
                    <div style={{ minWidth: 0 }}>
                        <p style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: 1.5 }}>{entry.text}</p>
                        {entry.ts && <p style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px', fontFamily: 'monospace' }}>{formatTime(entry.ts)}</p>}
                    </div>
                </div>
            )) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No thought timeline recorded.</span>}
        </div>
    );

    const renderTerminal = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {shellTerminals.length > 0 ? shellTerminals.map((term, i) => {
                const status = String(term?.status || '').toLowerCase();
                const termId = String(term?.id || `terminal-${i}`);
                const cmd = String(term?.command || '').trim();
                const lines = Number(term?.line_count || 0);
                const description = cmd || termId;
                const statusLabel = status === 'running'
                    ? 'running'
                    : (status === 'success' ? 'completed' : (status || 'error'));
                const statusColor = status === 'running' ? '#10b981' : status === 'success' ? '#22c55e' : status === 'timeout' ? '#f59e0b' : '#ef4444';
                return (
                    <div key={termId} style={{ border: '1px solid var(--card-border)', borderRadius: '7px', background: 'rgba(2,6,23,0.02)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', padding: '7px 9px' }}>
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={description}>
                                {description}
                            </span>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                                <span style={{ fontSize: '9px', fontWeight: 800, color: statusColor, textTransform: 'lowercase', letterSpacing: '0.01em' }}>
                                    {statusLabel}
                                </span>
                                <button
                                    className="btn-ghost"
                                    style={{ padding: '2px', borderRadius: '6px' }}
                                    title="Open terminal fullscreen"
                                    onClick={() => setFullscreenTerminalId(termId)}
                                >
                                    <ArrowUpRight size={12} />
                                </button>
                            </div>
                        </div>
                        <div style={{ padding: '0 9px 7px', fontSize: '9px', color: 'var(--text-muted)' }}>
                            {lines} lines
                        </div>
                    </div>
                );
            }) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No terminal activity recorded.</span>}
        </div>
    );

    const renderLogs = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                <div style={{ border: '1px solid var(--card-border)', borderRadius: '7px', padding: '8px' }}>
                    <p style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '800' }}>Worker errors</p>
                    <p style={{ fontSize: '14px', fontWeight: '800', color: workerErrors.length > 0 ? 'var(--error)' : 'var(--success)' }}>{workerErrors.length}</p>
                </div>
                <div style={{ border: '1px solid var(--card-border)', borderRadius: '7px', padding: '8px' }}>
                    <p style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '800' }}>Execution log</p>
                    <p style={{ fontSize: '11px', color: executionLogs.available ? 'var(--text-primary)' : 'var(--text-muted)', fontFamily: 'monospace' }}>
                        {executionLogs.execution_id || 'not available'}
                    </p>
                </div>
            </div>
            {workerErrors.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
                    {workerErrors.slice(-10).reverse().map((entry, idx) => (
                        <div key={`worker-error-${idx}`} style={{ border: '1px solid rgba(239,68,68,0.35)', borderRadius: '7px', background: 'rgba(239,68,68,0.06)', padding: '8px' }}>
                            <p style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-primary)' }}>{entry.event || 'worker_error'}</p>
                            <div style={{ marginTop: '2px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                                {entry.component && <span style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '1px 6px' }}>{String(entry.component)}</span>}
                                {entry.error_code && <span style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '1px 6px', fontFamily: 'monospace' }}>{String(entry.error_code)}</span>}
                                {entry.severity && <span style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '1px 6px' }}>{String(entry.severity)}</span>}
                            </div>
                            {entry.ts && <p style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{formatTime(entry.ts)}</p>}
                            <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px', whiteSpace: 'pre-wrap' }}>{entry.message || 'No message'}</p>
                        </div>
                    ))}
                </div>
            ) : (
                <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No worker errors detected.</span>
            )}
            {executionLogs.available && executionLogs.tail ? (
                <details style={{ border: '1px solid var(--card-border)', borderRadius: '7px', padding: '8px', background: 'rgba(2,6,23,0.02)' }}>
                    <summary style={{ cursor: 'pointer', fontSize: '11px', fontWeight: '700' }}>Execution log tail</summary>
                    <pre className="custom-scrollbar" style={{ marginTop: '8px', maxHeight: '180px', overflow: 'auto', fontSize: '10px', border: '1px solid var(--card-border)', borderRadius: '6px', padding: '8px', whiteSpace: 'pre-wrap' }}>
                        {executionLogs.tail}
                    </pre>
                </details>
            ) : (
                <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No execution logs available for this worker yet.</span>
            )}
        </div>
    );

    const renderMedia = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {relatedPlaybackRuns.length > 0 && (
                <div style={{ marginBottom: '6px' }}>
                    <p style={{ fontSize: '10px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', marginBottom: '6px' }}>Playback</p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {relatedPlaybackRuns.map((run) => (
                            <div key={run.run_id} style={{ border: '1px solid var(--card-border)', borderRadius: '7px', background: 'rgba(2,6,23,0.02)' }}>
                                {expandedPlaybackRunId === run.run_id ? (
                                    <div style={{ padding: '8px' }}>
                                        <button
                                            className="btn-ghost"
                                            style={{ marginBottom: '8px', padding: '4px 8px', fontSize: '10px', fontWeight: '700', color: 'var(--accent-color)' }}
                                            onClick={() => setExpandedPlaybackRunId(null)}
                                        >
                                            ← Back
                                        </button>
                                        <PlaybackCard runId={run.run_id} sessionId={sessionId} />
                                    </div>
                                ) : (
                                    <button
                                        onClick={() => setExpandedPlaybackRunId(run.run_id)}
                                        style={{
                                            width: '100%',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '10px',
                                            padding: '8px',
                                            background: 'transparent',
                                            border: 'none',
                                            textAlign: 'left',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        {run.thumbnail ? (
                                            <img
                                                src={run.thumbnail}
                                                alt=""
                                                style={{
                                                    width: '48px',
                                                    height: '34px',
                                                    borderRadius: '6px',
                                                    objectFit: 'cover',
                                                    border: '1px solid rgba(255,255,255,0.06)',
                                                    flexShrink: 0,
                                                }}
                                            />
                                        ) : (
                                            <div style={{
                                                width: '48px',
                                                height: '34px',
                                                borderRadius: '6px',
                                                border: '1px solid rgba(255,255,255,0.06)',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                flexShrink: 0,
                                            }}>
                                                <Monitor size={12} color="var(--text-muted)" />
                                            </div>
                                        )}
                                        <div style={{ minWidth: 0, flex: 1 }}>
                                            <p style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                {run.title || 'Browser Session'}
                                            </p>
                                            <p style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                                                {run.total_steps || 0} frames · {run.status === 'running' ? 'LIVE' : run.status === 'completed' || run.status === 'success' ? '✓' : '—'}
                                            </p>
                                        </div>
                                        <ChevronRight size={12} className="text-muted" />
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {media.length > 0 ? media.map((m, i) => {
                const name = String(m).split('/').pop();
                const ext = name.split('.').pop()?.toLowerCase();
                const isImg = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext);
                const url = getFileUrl({ path: m, name, type: isImg ? 'image' : 'file' }, sessionId);
                return (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px', background: 'rgba(2,6,23,0.02)', borderRadius: '7px', border: '1px solid var(--card-border)' }}>
                        <div style={{ width: '42px', height: '42px', borderRadius: '5px', overflow: 'hidden', border: '1px solid var(--card-border)', background: 'rgba(2,6,23,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                            {isImg ? (
                                <img src={url} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                            ) : (
                                ext === 'mp4' ? <Video size={18} color="#f87171" /> :
                                    ext === 'mp3' ? <Music size={18} color="#a78bfa" /> :
                                        ext === 'pdf' ? <FileText size={18} color="#cbd5e1" /> :
                                            <Paperclip size={18} color="var(--text-muted)" />
                            )}
                        </div>
                        <div style={{ minWidth: 0, flex: 1 }}>
                            <p style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</p>
                            <p style={{ fontSize: '10px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m}</p>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
                            {isImg && (
                                <button
                                    className="btn-ghost"
                                    style={{ padding: '6px', borderRadius: '8px' }}
                                    title="Expand"
                                    onClick={() => onExpand?.({ type: 'image', name, previewUrl: url, path: m })}
                                >
                                    <Maximize2 size={12} />
                                </button>
                            )}
                            <a
                                href={url}
                                download={name}
                                className="btn-ghost"
                                style={{ padding: '6px', borderRadius: '8px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                                title="Download"
                            >
                                <Download size={12} />
                            </a>
                        </div>
                    </div>
                );
            }) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No media recorded.</span>}
        </div>
    );

    const renderSources = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {sources.length > 0 ? sources.map((url, i) => (
                <a
                    key={i}
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        padding: '8px',
                        borderRadius: '7px',
                        border: '1px solid var(--card-border)',
                        background: 'rgba(2,6,23,0.02)',
                        fontSize: '11px',
                        color: 'var(--text-primary)',
                        textDecoration: 'underline',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                    }}
                    title={url}
                >
                    <span
                        style={{
                            position: 'relative',
                            width: '14px',
                            height: '14px',
                            borderRadius: '4px',
                            overflow: 'hidden',
                            flexShrink: 0,
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: 'rgba(255,255,255,0.08)',
                        }}
                    >
                        <Globe size={9} color="var(--text-muted)" style={{ opacity: 0.75 }} />
                        <img
                            src={`/api/favicon?url=${encodeURIComponent(url)}`}
                            alt=""
                            loading="lazy"
                            style={{
                                position: 'absolute',
                                inset: 0,
                                width: '100%',
                                height: '100%',
                                objectFit: 'cover',
                            }}
                            onError={(e) => {
                                e.currentTarget.style.display = 'none';
                            }}
                        />
                    </span>
                    <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {url}
                    </span>
                    <ArrowUpRight size={11} color="var(--text-muted)" style={{ flexShrink: 0 }} />
                </a>
            )) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No sources recorded.</span>}
        </div>
    );

    const tabRenderers = { plan: renderPlan, thought: renderThought, logs: renderLogs, terminal: renderTerminal, capabilities: renderCapabilities, media: renderMedia, sources: renderSources };

    return (
        <>
        <div style={{ marginTop: (inline || hideButton) ? '0' : '12px', position: 'relative', display: inline ? 'inline-flex' : 'block' }}>
            {!hideButton && (
                <button
                    onClick={toggle}
                    title="Work Unit Details"
                    className="btn-ghost"
                    style={{
                        display: 'inline-flex', 
                        alignItems: 'center', 
                        gap: '6px',
                        padding: '3px 8px',
                        background: 'rgba(255,255,255,0.04)',
                        border: '1px solid var(--card-border)',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                        marginLeft: '4px'
                    }}
                >
                    <Zap size={10} color={isOpen ? 'var(--accent-color)' : 'var(--text-muted)'} fill={isOpen ? 'var(--accent-color)' : 'none'} />
                    <span style={{ fontSize: '9px', fontWeight: '800', color: isOpen ? 'var(--accent-color)' : 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        {isOpen ? 'HIDE DETAILS' : 'WORK DETAILS'}
                    </span>
                </button>
            )}

            {/* Panel */}
            {isOpen && !hidePanel && (
                <div style={{
                    marginTop: inline ? '0' : '10px',
                    position: inline ? 'absolute' : 'relative',
                    top: inline ? 'calc(100% + 8px)' : 'auto',
                    left: 0,
                    zIndex: inline ? 40 : 'auto',
                    minWidth: inline ? '320px' : 'auto',
                    border: '1px solid var(--card-border)',
                    borderRadius: '8px',
                    overflow: 'hidden',
                    background: 'rgba(2,6,23,0.02)',
                    animation: 'fadeIn 0.2s ease'
                }}>
                    {/* Tab Bar */}
                    <div style={{ display: 'flex', borderBottom: '1px solid var(--card-border)', background: 'rgba(2,6,23,0.03)' }}>
                        {INSPECTOR_TABS.map(tab => {
                            const TabIcon = tab.icon;
                            return (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                style={{
                                    flex: 1, padding: '7px 4px',
                                    background: 'transparent', border: 'none', cursor: 'pointer',
                                    borderBottom: activeTab === tab.id ? '2px solid rgba(99,102,241,0.85)' : '2px solid transparent',
                                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
                                    transition: 'background 0.15s',
                                }}
                            >
                                <TabIcon size={13} color={activeTab === tab.id ? 'var(--accent-color)' : 'var(--text-muted)'} />
                                <span style={{ fontSize: '9px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.05em', color: activeTab === tab.id ? 'var(--accent-color)' : 'var(--text-muted)' }}>
                                    {tab.label}
                                </span>
                            </button>
                            );
                        })}
                    </div>

                    {/* Tab Content */}
                    <div style={{ padding: '14px', maxHeight: '260px', minHeight: '130px', overflowY: 'auto' }}>
                        {loading && !context && <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px', padding: '12px' }}>Loading…</div>}
                        {error && <div style={{ color: '#ef4444', fontSize: '12px' }}>{error}</div>}
                        {!loading && !error && (context || overwatch) && tabRenderers[activeTab]?.()}
                    </div>
                </div>
            )}
        </div>
        {fullscreenTerminal && createPortal((
            <div
                style={{
                    position: 'fixed',
                    inset: 0,
                    zIndex: 1200,
                    background: 'rgba(15,23,42,0.08)',
                    backdropFilter: 'blur(5px)',
                    WebkitBackdropFilter: 'blur(5px)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '10px',
                }}
                onClick={() => setFullscreenTerminalId(null)}
            >
                <div
                    style={{
                        width: 'min(1100px, 96vw)',
                        maxHeight: '78vh',
                        border: '1px solid var(--card-border)',
                        borderRadius: '8px',
                        overflow: 'hidden',
                        background: 'var(--card-bg)',
                        boxShadow: '0 10px 26px rgba(2,6,23,0.14)',
                        display: 'flex',
                        flexDirection: 'column',
                    }}
                    onClick={(e) => e.stopPropagation()}
                >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', padding: '7px 10px', borderBottom: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.03)' }}>
                        <div style={{ minWidth: 0 }}>
                            <p style={{ fontSize: '11px', color: 'var(--text-primary)', fontFamily: 'monospace', fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {String(fullscreenTerminal?.command || fullscreenTerminal?.id || 'terminal')}
                            </p>
                            <p style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {String(fullscreenTerminal?.cwd || '')}
                            </p>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{Number(fullscreenTerminal?.line_count || 0)} lines</span>
                            <button className="btn-ghost" style={{ padding: '4px', borderRadius: '6px', color: 'var(--text-primary)' }} onClick={() => setFullscreenTerminalId(null)} title="Close">
                                <X size={13} />
                            </button>
                        </div>
                    </div>
                    <div
                        ref={fullscreenTerminalBodyRef}
                        className="custom-scrollbar"
                        style={{
                            flex: 1,
                            minHeight: '220px',
                            overflowY: 'auto',
                            padding: '10px',
                            background: 'var(--bg-color)',
                        }}
                    >
                        <div
                            style={{
                                border: '1px solid var(--card-border)',
                                borderRadius: '6px',
                                background: 'var(--card-bg)',
                                padding: '10px',
                            }}
                        >
                        <pre
                            style={{
                                margin: 0,
                                padding: 0,
                                background: 'transparent',
                                border: 'none',
                                boxShadow: 'none',
                                borderRadius: 0,
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                                fontSize: '11px',
                                lineHeight: 1.42,
                                color: 'var(--text-primary)',
                                fontFamily: '"JetBrains Mono","Fira Code",monospace',
                            }}
                        >
                            {String(fullscreenTerminal?.transcript || fullscreenTerminal?.output_full || fullscreenTerminal?.output_tail || `$ ${String(fullscreenTerminal?.command || 'shell command')}\n(waiting for output...)`)}
                        </pre>
                        </div>
                    </div>
                </div>
            </div>
        ), document.body)}
        </>
    );
};
