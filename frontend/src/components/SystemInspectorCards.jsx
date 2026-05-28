import React, { memo, useState } from 'react';
import { Brain, MessageSquare, Layers, ChevronDown, ChevronRight, Clock, Hash, User, Folder, Activity } from 'lucide-react';
import { WorkUnitInspector } from './chat/WorkUnitInspector';

/* ─── ThoughtInspectorCard ─────────────────────────────────────────────── */
export const ThoughtInspectorCard = memo(({ data, isStage = false }) => {
    const title = data?.title || 'System Thought Stream';
    const thoughts = data?.thoughts || [];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', minHeight: '300px', overflow: 'hidden' }}>
            <div style={{
                border: isStage ? '1px solid rgba(168, 85, 247, 0.2)' : '1px solid var(--card-border)',
                borderRadius: '12px',
                padding: '14px',
                background: isStage
                    ? 'radial-gradient(circle at 0% 0%, rgba(168, 85, 247, 0.1), transparent 60%)'
                    : 'radial-gradient(circle at 0% 0%, rgba(168,85,247,0.16), transparent 45%), linear-gradient(120deg, rgba(15,23,42,0.5), rgba(168,85,247,0.08))',
                display: 'flex', flexDirection: 'column',
                flex: 1, minHeight: 0, overflow: 'hidden'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', flexShrink: 0 }}>
                    <Brain size={16} color="#a855f7" />
                    <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-primary)' }}>{title}</div>
                    <div style={{ marginLeft: 'auto', fontSize: '9px', color: 'var(--text-muted)', background: 'rgba(168,85,247,0.15)', padding: '2px 6px', borderRadius: '999px' }}>{thoughts.length} EVENTS</div>
                </div>

                <div className="custom-scrollbar" style={{
                    flex: 1, overflowY: 'auto', overflowX: 'hidden',
                    border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px',
                    padding: '10px', background: 'rgba(0,0,0,0.2)',
                    display: 'flex', flexDirection: 'column', gap: '8px'
                }}>
                    {thoughts.length === 0 ? (
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>No thoughts recorded.</div>
                    ) : thoughts.map((t, i) => {
                        let tag = '';
                        let content = typeof t.text === 'string' ? t.text : JSON.stringify(t.text, null, 2);
                        let tagColor = 'var(--text-muted)';
                        const match = typeof t.text === 'string' ? t.text.match(/^\[(.*?)\]:\s*(.*)/) : null;
                        if (match) {
                            tag = match[1];
                            content = match[2];
                            if (tag.toLowerCase().includes('sistema')) tagColor = '#3b82f6';
                            else if (tag.toLowerCase().includes('worker')) tagColor = '#10b981';
                            else if (tag.toLowerCase().includes('transceptor')) tagColor = '#f59e0b';
                            else tagColor = '#a855f7';
                        }
                        return (
                            <div key={i} style={{ borderLeft: `2px solid ${tag ? tagColor : 'rgba(255,255,255,0.2)'}`, paddingLeft: '10px', flexShrink: 0 }}>
                                {tag && <div style={{ fontSize: '9px', fontWeight: '800', color: tagColor, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '2px' }}>{tag}</div>}
                                <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: "'Fira Code', 'JetBrains Mono', monospace", whiteSpace: 'pre-wrap', lineHeight: '1.5', wordBreak: 'break-word' }}>
                                    {content}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
});

/* ─── HistoryInspectorCard ─────────────────────────────────────────────── */
export const HistoryInspectorCard = memo(({ data, isStage = false }) => {
    const title = data?.title || 'Chat History';
    const history = data?.history || [];
    const validChat = history.filter(m => m.role !== 'system' && m.type !== 'reasoning' && m.role !== 'reasoning' && m.role !== 'thought');

    return (
        <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', minHeight: '300px', overflow: 'hidden' }}>
            <div style={{
                border: isStage ? '1px solid rgba(59, 130, 246, 0.2)' : '1px solid var(--card-border)',
                borderRadius: '12px',
                padding: '14px',
                background: isStage
                    ? 'radial-gradient(circle at 0% 0%, rgba(59, 130, 246, 0.1), transparent 60%)'
                    : 'radial-gradient(circle at 0% 0%, rgba(59,130,246,0.16), transparent 45%), linear-gradient(120deg, rgba(15,23,42,0.5), rgba(59,130,246,0.08))',
                display: 'flex', flexDirection: 'column',
                flex: 1, minHeight: 0, overflow: 'hidden'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', flexShrink: 0 }}>
                    <MessageSquare size={16} color="#3b82f6" />
                    <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-primary)' }}>{title}</div>
                    <div style={{ marginLeft: 'auto', fontSize: '9px', color: 'var(--text-muted)', background: 'rgba(59,130,246,0.15)', padding: '2px 6px', borderRadius: '999px' }}>{validChat.length} MSG</div>
                </div>

                <div className="custom-scrollbar" style={{
                    flex: 1, overflowY: 'auto', overflowX: 'hidden',
                    border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px',
                    padding: '10px', background: 'rgba(0,0,0,0.2)',
                    display: 'flex', flexDirection: 'column', gap: '10px'
                }}>
                    {validChat.length === 0 ? (
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Nenhuma interação no histórico.</div>
                    ) : validChat.map((msg, i) => {
                        const isAtlas = msg.role === 'atlas' || msg.role === 'assistant';
                        return (
                            <div key={i} style={{ padding: '8px 12px', borderRadius: '6px', background: 'rgba(255,255,255,0.03)', borderLeft: isAtlas ? '3px solid var(--accent-color)' : '3px solid rgba(255,255,255,0.3)', flexShrink: 0 }}>
                                <div style={{ fontSize: '9px', fontWeight: '900', color: isAtlas ? 'var(--accent-color)' : 'rgba(255,255,255,0.5)', letterSpacing: '0.05em', marginBottom: '4px' }}>
                                    {isAtlas ? 'ATLAS' : 'USER'}
                                </div>
                                <div style={{ fontSize: '12px', color: isAtlas ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.7)', whiteSpace: 'pre-wrap', lineHeight: '1.5', wordBreak: 'break-word' }}>
                                    {msg.content?.replace(/\{[\s\S]*?\}/g, '').replace(/\[[A-Z_]+(:.*?)?\]/g, '').trim()}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
});

/* ─── WorkerInspectorCard ──────────────────────────────────────────────── */
const WORKER_STATUS_COLORS = {
    running: '#10b981', executing: '#10b981', active: '#10b981',
    thinking: '#a855f7', waiting: '#f59e0b', tool_use: '#00f2ff',
    responding: '#3b82f6', done: '#64748b', completed: '#64748b',
    error: '#ef4444', failed: '#ef4444', cancelled: '#ef4444',
};

const WorkerRow = ({ worker, index }) => {
    const [expanded, setExpanded] = useState(false);
    const wStatus = String(worker.status || 'running').toLowerCase();
    const statusColor = WORKER_STATUS_COLORS[wStatus] || 'var(--text-muted)';
    const label = worker.label || worker.key || worker.work_id || worker.id || `Worker ${index + 1}`;
    const inputText = worker.input_text || worker.inputText || '';
    const progressCount = worker.progress_count ?? worker.progressCount ?? null;
    const workId = worker.work_id || worker.workId || worker.id || '';
    const sessionId = worker.session_id || worker.sessionId || '';
    const scope = worker.scope || '';
    const createdAt = worker.created_at || worker.createdAt || '';
    const startedAt = worker.started_at || worker.startedAt || '';
    const updatedAt = worker.updated_at || worker.updatedAt || '';
    const result = worker.result;
    const error = worker.error;
    const cancelRequested = worker.cancel_requested || worker.cancelRequested || false;

    const fmt = (ts) => {
        if (!ts) return null;
        try { return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
        catch { return ts; }
    };

    return (
        <div style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: '10px', overflow: 'hidden', background: 'rgba(255,255,255,0.02)', flexShrink: 0 }}>
            {/* Header row */}
            <div
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 12px', cursor: 'pointer', userSelect: 'none' }}
                onClick={() => setExpanded(e => !e)}
            >
                <div style={{ flexShrink: 0, color: 'var(--text-muted)' }}>
                    {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '12px', fontWeight: '800', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</div>
                    {inputText && (
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: '2px' }}>{inputText}</div>
                    )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                    {cancelRequested && (
                        <div style={{ fontSize: '8px', fontWeight: '800', padding: '2px 5px', borderRadius: '999px', background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>CANCEL REQ</div>
                    )}
                    {progressCount !== null && (
                        <div style={{ fontSize: '9px', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.06)', padding: '2px 6px', borderRadius: '999px' }}>
                            <Activity size={8} style={{ display: 'inline', marginRight: '3px' }} />
                            {progressCount}
                        </div>
                    )}
                    <div style={{ fontSize: '9px', fontWeight: '800', padding: '2px 8px', borderRadius: '999px', background: `${statusColor}20`, color: statusColor, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{wStatus}</div>
                </div>
            </div>

            {/* Quick meta bar */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', padding: '0 12px 8px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                {workId && <MetaPill icon={<Hash size={9} />} label="ID" value={workId.slice(0, 8) + (workId.length > 8 ? '…' : '')} title={workId} />}
                {sessionId && <MetaPill icon={<User size={9} />} label="Session" value={sessionId.slice(0, 8) + '…'} title={sessionId} />}
                {scope && <MetaPill icon={<Folder size={9} />} label="Scope" value={scope} />}
                {fmt(startedAt) && <MetaPill icon={<Clock size={9} />} label="Started" value={fmt(startedAt)} />}
                {fmt(updatedAt) && <MetaPill icon={<Clock size={9} />} label="Updated" value={fmt(updatedAt)} />}
            </div>

            {/* Expanded details */}
            {expanded && (
                <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '8px', background: 'rgba(0,0,0,0.25)' }}>
                    {error && (
                        <div style={{ padding: '8px', borderRadius: '6px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', fontSize: '11px', color: '#fca5a5', fontFamily: "'Fira Code', monospace", whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            <div style={{ fontSize: '9px', fontWeight: 800, color: '#ef4444', marginBottom: '4px' }}>ERROR</div>
                            {String(error)}
                        </div>
                    )}
                    {result !== null && result !== undefined && (
                        <div style={{ padding: '8px', borderRadius: '6px', background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)', fontSize: '11px', color: '#6ee7b7', fontFamily: "'Fira Code', monospace", whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                            <div style={{ fontSize: '9px', fontWeight: 800, color: '#10b981', marginBottom: '4px' }}>RESULT</div>
                            {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
                        </div>
                    )}
                    {workId && (
                        <div style={{ marginTop: '4px', background: 'rgba(0,0,0,0.4)', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)', overflow: 'hidden' }}>
                            <WorkUnitInspector workId={workId} sessionId={sessionId} open={true} hideButton={true} inline={false} />
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

const MetaPill = ({ icon, label, value, title }) => (
    <div title={title || value} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '9px', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.05)', padding: '2px 7px', borderRadius: '999px', cursor: title ? 'help' : 'default' }}>
        {icon}
        <span style={{ color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</span>
        <span style={{ color: 'rgba(255,255,255,0.65)' }}>{value}</span>
    </div>
);

export const WorkerInspectorCard = memo(({ data, isStage = false }) => {
    const title = data?.title || 'Worker Inspector';
    const workers = data?.workers || [];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', minHeight: '300px', overflow: 'hidden' }}>
            <div style={{
                border: isStage ? '1px solid rgba(16, 185, 129, 0.2)' : '1px solid var(--card-border)',
                borderRadius: '12px',
                padding: '14px',
                background: isStage
                    ? 'radial-gradient(circle at 0% 0%, rgba(16, 185, 129, 0.1), transparent 60%)'
                    : 'radial-gradient(circle at 0% 0%, rgba(16,185,129,0.16), transparent 45%), linear-gradient(120deg, rgba(15,23,42,0.5), rgba(16,185,129,0.08))',
                display: 'flex', flexDirection: 'column',
                flex: 1, minHeight: 0, overflow: 'hidden'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', flexShrink: 0 }}>
                    <Layers size={16} color="#10b981" />
                    <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-primary)' }}>{title}</div>
                    <div style={{ marginLeft: 'auto', fontSize: '9px', color: 'var(--text-muted)', background: 'rgba(16,185,129,0.15)', padding: '2px 6px', borderRadius: '999px' }}>{workers.length} WORKERS</div>
                </div>

                <div className="custom-scrollbar" style={{
                    flex: 1, overflowY: 'auto', overflowX: 'hidden',
                    border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px',
                    padding: '10px', background: 'rgba(0,0,0,0.2)',
                    display: 'flex', flexDirection: 'column', gap: '8px'
                }}>
                    {workers.length === 0 ? (
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Nenhum worker ativo no momento.</div>
                    ) : workers.map((worker, i) => (
                        <WorkerRow key={worker.work_id || worker.id || i} worker={worker} index={i} />
                    ))}
                </div>
            </div>
        </div>
    );
});
