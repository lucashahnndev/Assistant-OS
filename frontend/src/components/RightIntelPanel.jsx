import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ChevronRight, ChevronLeft, Brain, Layers, Clock, Server, GitBranch, ChevronDown, ChevronUp, Zap, MessageSquare, Maximize2, Minimize2, RefreshCw, LayoutGrid, Trash2 } from 'lucide-react';
import { normalizeHistoryMessageType, extractReasoningLine } from '../utils/chatHistoryTransform';
import { WorkUnitInspector } from './chat/WorkUnitInspector';
import { api } from '../hooks/api';
import { useGlobalSession } from '../context/GlobalSessionContext';

const STORAGE_KEY = 'atlas_intel_sidebar_v2';
const DEFAULTS = { panelOpen: false, thoughtOpen: true, workersOpen: true, vitalsOpen: false, chatOpen: false, mediaOpen: true };

function loadState() {
    try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') }; } catch { return { ...DEFAULTS }; }
}
function saveState(s) { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)); } catch { } }

const SectionHeader = ({ icon: Icon, title, open, onToggle, badge, onMaximize, onClear }) => (
    <div style={{
        width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px 8px', userSelect: 'none',
    }}>
        <button onClick={onToggle} style={{
            display: 'flex', alignItems: 'center', gap: '6px', background: 'none', border: 'none', cursor: 'pointer', flex: 1, textAlign: 'left', padding: 0
        }}>
            <Icon size={12} color="var(--accent-color)" />
            <span style={{ fontSize: '10px', fontWeight: '800', letterSpacing: '0.09em', color: 'var(--accent-color)', textTransform: 'uppercase' }}>{title}</span>
            {badge > 0 && <span style={{ fontSize: '9px', fontWeight: '800', padding: '1px 5px', borderRadius: '999px', background: 'rgba(0,242,255,0.12)', color: 'var(--accent-color)' }}>{badge}</span>}
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {onClear && (
                <button onClick={(e) => { e.stopPropagation(); onClear(); }} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'flex', transition: 'all 0.2s', color: 'var(--text-muted)' }} title="Limpar" onMouseEnter={e => e.currentTarget.style.color = '#ef4444'} onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}>
                    <Trash2 size={12} color="currentColor" />
                </button>
            )}
            {onMaximize && (
                <button onClick={(e) => { e.stopPropagation(); onMaximize(); }} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'flex', transition: 'all 0.2s', color: 'var(--text-muted)' }} title="Expandir no HUD" onMouseEnter={e => e.currentTarget.style.color = '#fff'} onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}>
                    <Maximize2 size={12} color="currentColor" />
                </button>
            )}
            <button onClick={onToggle} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'flex' }}>
                {open ? <ChevronUp size={12} color="var(--text-muted)" /> : <ChevronDown size={12} color="var(--text-muted)" />}
            </button>
        </div>
    </div>
);

const WorkerCard = ({ worker, sessionId }) => {
    const [expanded, setExpanded] = useState(false);
    const [inspOpen, setInspOpen] = useState(false);
    const wId = worker.work_id || worker.id || '';
    const wStatus = String(worker.status || 'running').toLowerCase();
    const label = worker.label || String(wId).substring(0, 14);
    const lastThought = worker.context?.summary?.last_thought || worker.last_thought || null;
    const statusColor = { running: '#10b981', executing: '#10b981', active: '#10b981', thinking: '#a855f7', waiting: '#f59e0b', waiting_user: '#f59e0b', tool_use: '#00f2ff', responding: '#3b82f6' }[wStatus] || 'var(--text-muted)';

    return (
        <div style={{ borderRadius: '8px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)', overflow: 'hidden' }}>
            <button onClick={() => setExpanded(v => !v)} style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer', padding: '8px 10px', display: 'flex', alignItems: 'center', gap: '7px', textAlign: 'left' }}>
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', flexShrink: 0, background: statusColor, boxShadow: `0 0 6px ${statusColor}` }} />
                <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-primary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
                <span style={{ fontSize: '9px', fontWeight: '800', padding: '1px 5px', borderRadius: '999px', background: `${statusColor}25`, color: statusColor, border: `1px solid ${statusColor}45`, textTransform: 'uppercase', flexShrink: 0 }}>{wStatus}</span>
                {expanded ? <ChevronUp size={10} color="var(--text-muted)" /> : <ChevronDown size={10} color="var(--text-muted)" />}
            </button>
            {expanded && (
                <div style={{ padding: '0 10px 10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {lastThought && <p style={{ fontSize: '10px', color: 'var(--text-muted)', lineHeight: '1.55', margin: 0, fontStyle: 'italic', borderLeft: '2px solid rgba(0,242,255,0.25)', paddingLeft: '8px' }}>{lastThought}</p>}
                    {wId && <WorkUnitInspector workId={wId} sessionId={sessionId} open={inspOpen} onToggle={setInspOpen} inline={false} />}
                </div>
            )}
        </div>
    );
};

const RightIntelPanel = ({ sys, activeWorkers = [], agentThought = '', isThinking = false, isMobile, sessionId, history = [], onAddMedia, onReload, onToggleFullscreen, isFullscreen }) => {
    const { thoughts: ctxThoughts, pushGlobalThought, clearGlobalPanel } = useGlobalSession();
    const [ps, setPs] = useState(loadState);
    const thoughtRef = useRef(null);
    const [thoughts, setThoughts] = useState(ctxThoughts || []);
    const [historicalWorkers, setHistoricalWorkers] = useState([]);
    const [mediaCards, setMediaCards] = useState([]);

    useEffect(() => { saveState(ps); }, [ps]);
    const toggle = useCallback((key) => setPs(prev => ({ ...prev, [key]: !prev[key] })), []);

    // 1. Listen to streamed reasoning chunks
    useEffect(() => {
        if (!agentThought) return;
        setThoughts(prev => {
            if (prev[prev.length - 1]?.text === agentThought) return prev;
            return [...prev, { text: agentThought, ts: Date.now() }].slice(-50);
        });
        pushGlobalThought(agentThought);
    }, [agentThought, pushGlobalThought]);

    // 2. Fallback/Reconstruction: fetch cognitive audit trail from thoughts.json
    useEffect(() => {
        if (!sessionId) return;
        let isSubscribed = true;

        const loadThoughts = async () => {
            try {
                const res = await api.get(`/sessions/${sessionId}/thoughts`);
                if (!isSubscribed) return;
                
                const remoteThoughts = res.thoughts || [];
                if (remoteThoughts.length > 0) {
                    setThoughts(prev => {
                        let updated = [...prev];
                        let changed = false;
                        
                        remoteThoughts.forEach(rt => {
                            const text = rt.thought || '';
                            let baseTs = Date.now();
                            if (rt.timestamp) {
                                if (typeof rt.timestamp === 'number') {
                                    baseTs = rt.timestamp > 9999999999 ? rt.timestamp : rt.timestamp * 1000;
                                } else {
                                    const parsed = Date.parse(rt.timestamp);
                                    if (!isNaN(parsed)) baseTs = parsed;
                                }
                            }
                            
                            const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
                            lines.forEach((line, idx) => {
                                const lineTs = baseTs + (idx * 10);
                                if (!updated.some(t => t.text === line && t.ts === lineTs)) {
                                    updated.push({ text: line, ts: lineTs });
                                    changed = true;
                                }
                            });
                        });

                        if (changed) {
                            updated.sort((a, b) => a.ts - b.ts);
                            return updated.slice(-50);
                        }
                        return prev;
                    });
                }
            } catch (err) {
                if (!String(err).includes('404') && !String(err).includes('Not Found')) {
                    console.error("Failed to load thoughts.json audit trail", err);
                }
            }
        };
        
        const loadCards = async () => {
            try {
                const res = await api.get(`/sessions/${sessionId}/cards`);
                if (!isSubscribed) return;
                if (res.cards && Array.isArray(res.cards)) {
                    setMediaCards(res.cards);
                }
            } catch (err) {
                if (!String(err).includes('404') && !String(err).includes('Not Found')) {
                    console.error("Failed to load cards.json persistence layer", err);
                }
            }
        };
        
        loadThoughts();
        loadCards();
        return () => { isSubscribed = false; };
    }, [sessionId]);

    useEffect(() => {
        if (thoughtRef.current && ps.thoughtOpen) thoughtRef.current.scrollTop = thoughtRef.current.scrollHeight;
    }, [thoughts, ps.thoughtOpen]);

    const status = sys?.status || {};
    useEffect(() => {
        const works = Array.isArray(sys?.works) ? sys.works : [];
        const liveMap = new Map(activeWorkers.map(w => [w.work_id || w.id, w]));
        const currentActive = [
            ...works.map(w => liveMap.has(w.work_id || w.id) ? { ...w, ...liveMap.get(w.work_id || w.id) } : w),
            ...activeWorkers.filter(w => !works.some(pw => (pw.work_id || pw.id) === (w.work_id || w.id))),
        ];
        
        setHistoricalWorkers(prev => {
            const newHistory = [...prev];
            let changed = false;
            
            // Update or add active workers
            currentActive.forEach(w => {
                const id = w.work_id || w.id;
                if (!id) return;
                const existingIndex = newHistory.findIndex(h => (h.work_id || h.id) === id);
                if (existingIndex >= 0) {
                    const updated = { ...newHistory[existingIndex], ...w };
                    if (JSON.stringify(updated) !== JSON.stringify(newHistory[existingIndex])) {
                        newHistory[existingIndex] = updated;
                        changed = true;
                    }
                } else {
                    newHistory.push(w);
                    changed = true;
                }
            });
            
            // Mark orphaned workers as completed
            newHistory.forEach((hw, i) => {
                const hwId = hw.work_id || hw.id;
                const isStillActive = currentActive.some(cw => (cw.work_id || cw.id) === hwId);
                if (!isStillActive) {
                    const oldStatus = String(hw.status || '').toLowerCase();
                    if (['running', 'executing', 'thinking', 'active', 'tool_use', 'waiting', 'waiting_user', 'responding'].includes(oldStatus)) {
                        newHistory[i] = { ...hw, status: 'completed' };
                        changed = true;
                    }
                }
            });

            return changed ? newHistory.slice(-15) : prev;
        });
    }, [sys?.works, activeWorkers]);

    const works = Array.isArray(sys?.works) ? sys.works : [];
    const liveMap = new Map(activeWorkers.map(w => [w.work_id || w.id, w]));
    const currentActiveList = [
        ...works.map(w => liveMap.has(w.work_id || w.id) ? { ...w, ...liveMap.get(w.work_id || w.id) } : w),
        ...activeWorkers.filter(w => !works.some(pw => (pw.work_id || pw.id) === (w.work_id || w.id))),
    ].filter(w => !['complete', 'failed', 'succeeded', 'cancelled'].includes(String(w.status || '').toLowerCase()));

    const workerCount = currentActiveList.length;
    const mergedWorks = historicalWorkers.slice().reverse(); // Show newest at the top
    const isOnline = status?.status === 'running';
    const agentName = status?.agent_name || null;

    // ── Shared panel style tokens (matches Live Panel glass system)
    const glassBase = {
        position: 'relative', height: '100%', flexShrink: 0,
        zIndex: 10900,
        background: 'rgba(10, 12, 22, 0.72)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderRight: '1px solid rgba(255, 255, 255, 0.05)',
        transition: 'width 0.28s cubic-bezier(0.19, 1, 0.22, 1)',
    };

    // ── COLLAPSED — thin accent bar
    if (!ps.panelOpen) {
        return (
            <div style={{ ...glassBase, width: isMobile ? '40px' : '48px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                {/* Status dot top */}
                <div style={{ marginTop: '20px', width: '6px', height: '6px', borderRadius: '50%', background: isOnline ? '#10b981' : '#ef4444', boxShadow: isOnline ? '0 0 7px #10b981' : '0 0 7px #ef4444', flexShrink: 0 }} />

                {workerCount > 0 && (
                    <div style={{ marginTop: '8px', fontSize: '9px', fontWeight: '900', background: 'rgba(0,242,255,0.12)', color: 'var(--accent-color)', border: '1px solid rgba(0,242,255,0.25)', borderRadius: '999px', padding: '1px 4px', lineHeight: '14px' }}>
                        {workerCount}
                    </div>
                )}

                {isThinking && <div style={{ marginTop: '8px', width: '4px', height: '4px', borderRadius: '50%', background: '#a855f7', animation: 'intel-pulse 1.1s ease-in-out infinite', flexShrink: 0 }} />}

                {/* Center expand button */}
                <button
                    onClick={() => setPs(p => ({ ...p, panelOpen: true }))}
                    title="Expandir painel"
                    style={{
                        position: 'absolute', top: '50%', transform: 'translateY(-50%)',
                        width: '30px', height: '30px', borderRadius: '8px',
                        background: 'rgba(0,242,255,0.06)', border: '1px solid rgba(0,242,255,0.15)',
                        cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: 'var(--accent-color)', transition: 'all 0.2s',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(0,242,255,0.15)'; e.currentTarget.style.borderColor = 'rgba(0,242,255,0.35)'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'rgba(0,242,255,0.06)'; e.currentTarget.style.borderColor = 'rgba(0,242,255,0.15)'; }}
                >
                    <ChevronRight size={15} />
                </button>

                <style>{`
                    @keyframes intel-pulse { 0%,100%{opacity:1;} 50%{opacity:0.3;} }
                    @keyframes intel-blink { 0%,100%{opacity:1;} 50%{opacity:0;} }
                `}</style>
            </div>
        );
    }

    // ── EXPANDED — full-height glass sidebar
    return (
        <div style={{ ...glassBase, width: '280px', display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '4px 0 24px rgba(0,0,0,0.4)' }}>

            {/* Collapse tab on right edge */}
            <button
                onClick={() => setPs(p => ({ ...p, panelOpen: false }))}
                title="Colapsar"
                style={{
                    position: 'absolute', right: '-13px', top: '50%', transform: 'translateY(-50%)',
                    width: '26px', height: '26px', borderRadius: '0 7px 7px 0',
                    background: 'rgba(10,12,22,0.85)', border: '1px solid rgba(255,255,255,0.08)',
                    borderLeft: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: 'var(--text-muted)', zIndex: 1, transition: 'color 0.2s',
                }}
                onMouseEnter={e => e.currentTarget.style.color = 'var(--accent-color)'}
                onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
            >
                <ChevronLeft size={13} />
            </button>

            {/* Top status bar */}
            <div style={{
                padding: '12px 14px 10px', borderBottom: '1px solid rgba(255,255,255,0.06)',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0,
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: isOnline ? '#10b981' : '#ef4444', boxShadow: isOnline ? '0 0 6px #10b981' : '0 0 6px #ef4444' }} />
                    <div style={{ display: 'flex', gap: '6px' }}>
                        {onReload && (
                            <button onClick={onReload} style={{ width: '18px', height: '18px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '4px', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-muted)', cursor: 'pointer', transition: 'all 0.2s' }} title="Reset Session">
                                <RefreshCw size={10} />
                            </button>
                        )}
                        {onToggleFullscreen && (
                            <button onClick={onToggleFullscreen} style={{ width: '18px', height: '18px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '4px', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-muted)', cursor: 'pointer', transition: 'all 0.2s' }} title={isFullscreen ? "Sair da Tela Cheia" : "Tela Cheia"}>
                                {isFullscreen ? <Minimize2 size={10} /> : <Maximize2 size={10} />}
                            </button>
                        )}
                    </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {status.uptime && <span style={{ fontSize: '10px', fontFamily: 'monospace', color: 'rgba(255,255,255,0.3)' }}>{status.uptime}</span>}
                    {isThinking && <span style={{ fontSize: '8px', fontWeight: '800', padding: '1px 6px', borderRadius: '999px', background: 'rgba(168,85,247,0.15)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)', textTransform: 'uppercase', animation: 'intel-pulse 1.5s ease-in-out infinite' }}>thinking</span>}
                    {workerCount > 0 && !isThinking && <span style={{ fontSize: '8px', fontWeight: '800', padding: '1px 6px', borderRadius: '999px', background: 'rgba(16,185,129,0.12)', color: '#10b981', border: '1px solid rgba(16,185,129,0.25)', textTransform: 'uppercase' }}>{workerCount}w</span>}
                </div>
            </div>

            {/* Scrollable body */}
            <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto' }}>

                {/* 1 — LIVE THOUGHT */}
                <SectionHeader icon={Brain} title="Pensamento" open={ps.thoughtOpen} onToggle={() => toggle('thoughtOpen')} onMaximize={() => onAddMedia?.({ title: 'System Thought Stream', thoughts }, 'THOUGHT_INSPECTOR')} onClear={() => { setThoughts([]); clearGlobalPanel(); }} />
                {ps.thoughtOpen && (
                    <div ref={thoughtRef} className="custom-scrollbar" style={{ padding: '4px 14px 12px 20px', maxHeight: '45vh', overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
                        {thoughts.length === 0 ? (
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontStyle: 'italic', marginLeft: '-6px' }}>Aguardando atividade cognitiva…</span>
                        ) : (
                            <div style={{ position: 'relative', borderLeft: '1px solid rgba(255,255,255,0.1)' }}>
                                {thoughts.map((t, i) => {
                                    const isLast = i === thoughts.length - 1;
                                    
                                    let tag = '';
                                    let content = typeof t.text === 'string' ? t.text : JSON.stringify(t.text, null, 2);
                                    let tagColor = 'var(--text-muted)';
                                    
                                    // Parse synthetic tags like [Sistema]: or [Worker: xyz]:
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
                                        <div key={i} style={{ position: 'relative', paddingBottom: isLast ? '2px' : '12px', paddingLeft: '12px' }}>
                                            {/* Timeline dot */}
                                            <div style={{
                                                position: 'absolute', left: '-4.5px', top: '4px', width: '8px', height: '8px', borderRadius: '50%',
                                                background: isLast ? '#a855f7' : 'rgba(255,255,255,0.15)',
                                                border: '2px solid rgba(10, 12, 22, 1)',
                                                boxShadow: isLast && isThinking ? '0 0 6px #a855f7' : 'none'
                                            }} />
                                            
                                            {/* Content */}
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                                                {tag && (
                                                    <span style={{ fontSize: '9px', fontWeight: '800', color: tagColor, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                                        {tag}
                                                    </span>
                                                )}
                                                <p style={{
                                                    margin: 0, fontSize: '10px', lineHeight: '1.5',
                                                    fontFamily: "'Fira Code', 'JetBrains Mono', monospace",
                                                    color: isLast ? 'var(--text-primary)' : 'rgba(255,255,255,0.35)',
                                                    wordBreak: 'break-word',
                                                    whiteSpace: 'pre-wrap',
                                                    display: '-webkit-box',
                                                    WebkitLineClamp: isLast ? 'none' : '3',
                                                    WebkitBoxOrient: 'vertical',
                                                    overflow: 'hidden'
                                                }}>
                                                    {content}
                                                    {isLast && isThinking && <span style={{ display: 'inline-block', width: '4px', height: '10px', background: '#a855f7', marginLeft: '4px', verticalAlign: 'text-bottom', borderRadius: '1px', animation: 'intel-blink 0.85s step-end infinite' }} />}
                                                </p>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                )}

                <div style={{ height: '1px', background: 'rgba(255,255,255,0.05)', margin: '0 14px' }} />

                {/* 1.5 — CHAT HISTORY COMPACT */}
                <SectionHeader icon={MessageSquare} title="Histórico" open={ps.chatOpen} onToggle={() => toggle('chatOpen')} onMaximize={() => onAddMedia?.({ title: 'Chat History', history }, 'HISTORY_INSPECTOR')} />
                {ps.chatOpen && (
                    <div className="custom-scrollbar" style={{ padding: '0 14px 12px', maxHeight: '30vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {(() => {
                            const validChat = history.filter(m => m.role !== 'system' && m.type !== 'reasoning' && m.role !== 'reasoning' && m.role !== 'thought');
                            if (validChat.length === 0) return <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontStyle: 'italic' }}>Nenhuma interação...</span>;
                            
                            return validChat.map((msg, i) => {
                                const isAtlas = msg.role === 'atlas' || msg.role === 'assistant';
                                return (
                                    <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '2px', background: 'rgba(255,255,255,0.02)', padding: '6px 8px', borderRadius: '6px', borderLeft: isAtlas ? '2px solid var(--accent-color)' : '2px solid rgba(255,255,255,0.2)' }}>
                                        <span style={{ fontSize: '8px', fontWeight: '900', color: isAtlas ? 'var(--accent-color)' : 'rgba(255,255,255,0.5)', letterSpacing: '0.05em' }}>
                                            {isAtlas ? 'ATLAS' : 'USER'}
                                        </span>
                                        <p style={{
                                            margin: 0, fontSize: '9px', lineHeight: '1.4',
                                            color: isAtlas ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.4)',
                                            wordBreak: 'break-word', whiteSpace: 'pre-wrap',
                                            display: '-webkit-box', WebkitLineClamp: '2', WebkitBoxOrient: 'vertical', overflow: 'hidden'
                                        }}>
                                            {msg.content?.replace(/\{[\s\S]*?\}/g, '').replace(/\[[A-Z_]+(:.*?)?\]/g, '').replace(/!\[.*?\]\(.*?\)/g, '[MEDIA]').replace(/```[\s\S]*?```/g, '[CODE_BLOCK]').trim()}
                                        </p>
                                    </div>
                                );
                            });
                        })()}
                    </div>
                )}
                
                <div style={{ height: '1px', background: 'rgba(255,255,255,0.05)', margin: '0 14px' }} />
                
                {/* 1.8 — MEDIA CARDS PERSISTENCE */}
                <SectionHeader icon={LayoutGrid} title="Mídias & Widgets" open={ps.mediaOpen} onToggle={() => toggle('mediaOpen')} badge={mediaCards.length} />
                {ps.mediaOpen && (
                    <div style={{ padding: '0 14px 12px', display: 'flex', flexDirection: 'column', gap: '5px' }}>
                        {mediaCards.length === 0 ? (
                            <p style={{ fontSize: '10px', color: 'var(--text-muted)', textAlign: 'center', margin: 0, fontStyle: 'italic' }}>Nenhuma mídia armazenada.</p>
                        ) : (
                            mediaCards.slice().reverse().map((card) => (
                                <button
                                    key={card.id}
                                    onClick={() => {
                                        // Re-trigger the media card creation to the center stage
                                        if (onAddMedia) onAddMedia(card.payload, card.type);
                                    }}
                                    style={{
                                        width: '100%', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)',
                                        borderRadius: '6px', padding: '6px 8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', textAlign: 'left', transition: 'all 0.2s'
                                    }}
                                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; e.currentTarget.style.borderColor = 'var(--accent-color)'; }}
                                    onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.02)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'; }}
                                >
                                    <span style={{ fontSize: '12px' }}>
                                        {card.type === 'WEATHER' ? '⛅' : card.type === 'YOUTUBE' ? '▶️' : card.type === 'DEEZER' ? '🎵' : card.type === 'CHART' ? '📊' : card.type === 'WEGENA' ? '🏔️' : '📄'}
                                    </span>
                                    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                                        <span style={{ fontSize: '9px', fontWeight: '800', color: 'var(--text-primary)', textTransform: 'uppercase' }}>
                                            {card.type}
                                        </span>
                                        <span style={{ fontSize: '9px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                            {card.payload?.title || card.payload?.content || 'Widget Interativo'}
                                        </span>
                                    </div>
                                </button>
                            ))
                        )}
                    </div>
                )}


                {/* 2 — WORKERS */}
                <SectionHeader icon={Layers} title="Workers" open={ps.workersOpen} onToggle={() => toggle('workersOpen')} badge={workerCount} onMaximize={() => onAddMedia?.({ title: 'Worker Inspector', workers: mergedWorks }, 'WORKER_INSPECTOR')} />
                {ps.workersOpen && (
                    <div style={{ padding: '0 10px 12px', display: 'flex', flexDirection: 'column', gap: '5px' }}>
                        {mergedWorks.length === 0
                            ? <p style={{ fontSize: '10px', color: 'var(--text-muted)', textAlign: 'center', padding: '10px 0', margin: 0, fontStyle: 'italic' }}>Nenhum worker ativo</p>
                            : mergedWorks.map((w, idx) => <WorkerCard key={w.work_id || w.id || idx} worker={w} sessionId={sessionId} />)
                        }
                    </div>
                )}

                <div style={{ height: '1px', background: 'rgba(255,255,255,0.05)', margin: '0 14px' }} />

                {/* 3 — VITALS (minimal, hidden by default) */}
                <SectionHeader icon={Server} title="Vitais" open={ps.vitalsOpen} onToggle={() => toggle('vitalsOpen')} />
                {ps.vitalsOpen && (
                    <div style={{ padding: '0 14px 12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {[
                            { icon: Clock, label: 'Uptime', value: status.uptime || '—' },
                            { icon: GitBranch, label: 'Drivers', value: status.drivers?.length ?? '—' },
                            { icon: Zap, label: 'Caps', value: status.loaded_capabilities?.length ?? '—' },
                        ].map(({ icon: Icon, label, value }) => (
                            <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                                    <Icon size={11} color="var(--text-muted)" />
                                    <span style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: '700' }}>{label}</span>
                                </div>
                                <span style={{ fontSize: '11px', fontWeight: '800', color: 'var(--text-primary)', fontFamily: 'monospace' }}>{value}</span>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <style>{`
                @keyframes intel-pulse { 0%,100%{opacity:1;} 50%{opacity:0.35;} }
                @keyframes intel-blink { 0%,100%{opacity:1;} 50%{opacity:0;} }
            `}</style>
        </div>
    );
};

export default RightIntelPanel;
