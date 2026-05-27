import React, { memo } from 'react';
import { Brain, MessageSquare, Layers } from 'lucide-react';

export const ThoughtInspectorCard = memo(({ data, isStage = false }) => {
    const title = data?.title || 'System Thought Stream';
    const thoughts = data?.thoughts || [];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', width: '100%', height: '100%', minHeight: '300px' }}>
            <div style={{
                border: isStage ? '1px solid rgba(168, 85, 247, 0.2)' : '1px solid var(--card-border)',
                borderRadius: '12px',
                padding: '14px',
                background: isStage
                    ? 'radial-gradient(circle at 0% 0%, rgba(168, 85, 247, 0.1), transparent 60%)'
                    : 'radial-gradient(circle at 0% 0%, rgba(168,85,247,0.16), transparent 45%), linear-gradient(120deg, rgba(15,23,42,0.5), rgba(168,85,247,0.08))',
                boxShadow: isStage ? 'none' : 'inset 0 1px 0 rgba(255,255,255,0.05)',
                backdropFilter: isStage ? 'blur(10px)' : 'none',
                display: 'flex', flexDirection: 'column',
                flex: 1, minHeight: 0
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', flexShrink: 0 }}>
                    <Brain size={16} color="#a855f7" />
                    <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-primary)' }}>{title}</div>
                </div>

                <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px', padding: '12px', background: 'rgba(0,0,0,0.2)' }}>
                    {thoughts.length === 0 ? (
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>No thoughts recorded.</div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            {thoughts.map((t, i) => {
                                let tag = '';
                                let content = t.text;
                                let tagColor = 'var(--text-muted)';
                                const match = t.text.match(/^\[(.*?)\]:\s*(.*)/);
                                if (match) {
                                    tag = match[1];
                                    content = match[2];
                                    if (tag.toLowerCase().includes('sistema')) tagColor = '#3b82f6';
                                    else if (tag.toLowerCase().includes('worker')) tagColor = '#10b981';
                                    else if (tag.toLowerCase().includes('transceptor')) tagColor = '#f59e0b';
                                    else tagColor = '#a855f7';
                                }

                                return (
                                    <div key={i} style={{ borderLeft: `2px solid ${tag ? tagColor : 'rgba(255,255,255,0.2)'}`, paddingLeft: '10px' }}>
                                        {tag && <div style={{ fontSize: '9px', fontWeight: '800', color: tagColor, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '2px' }}>{tag}</div>}
                                        <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: "'Fira Code', 'JetBrains Mono', monospace", whiteSpace: 'pre-wrap', lineHeight: '1.5' }}>
                                            {content}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
});

export const HistoryInspectorCard = memo(({ data, isStage = false }) => {
    const title = data?.title || 'Chat History';
    const history = data?.history || [];
    const validChat = history.filter(m => m.role !== 'system' && m.type !== 'reasoning' && m.role !== 'reasoning' && m.role !== 'thought');

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', width: '100%', height: '100%', minHeight: '300px' }}>
            <div style={{
                border: isStage ? '1px solid rgba(59, 130, 246, 0.2)' : '1px solid var(--card-border)',
                borderRadius: '12px',
                padding: '14px',
                background: isStage
                    ? 'radial-gradient(circle at 0% 0%, rgba(59, 130, 246, 0.1), transparent 60%)'
                    : 'radial-gradient(circle at 0% 0%, rgba(59,130,246,0.16), transparent 45%), linear-gradient(120deg, rgba(15,23,42,0.5), rgba(59,130,246,0.08))',
                boxShadow: isStage ? 'none' : 'inset 0 1px 0 rgba(255,255,255,0.05)',
                backdropFilter: isStage ? 'blur(10px)' : 'none',
                display: 'flex', flexDirection: 'column',
                flex: 1, minHeight: 0
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', flexShrink: 0 }}>
                    <MessageSquare size={16} color="#3b82f6" />
                    <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-primary)' }}>{title}</div>
                </div>

                <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px', padding: '12px', background: 'rgba(0,0,0,0.2)' }}>
                    {validChat.length === 0 ? (
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Nenhuma interação no histórico.</div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            {validChat.map((msg, i) => {
                                const isAtlas = msg.role === 'atlas' || msg.role === 'assistant';
                                return (
                                    <div key={i} style={{ padding: '8px 12px', borderRadius: '6px', background: 'rgba(255,255,255,0.03)', borderLeft: isAtlas ? '3px solid var(--accent-color)' : '3px solid rgba(255,255,255,0.3)' }}>
                                        <div style={{ fontSize: '9px', fontWeight: '900', color: isAtlas ? 'var(--accent-color)' : 'rgba(255,255,255,0.5)', letterSpacing: '0.05em', marginBottom: '4px' }}>
                                            {isAtlas ? 'ATLAS' : 'USER'}
                                        </div>
                                        <div style={{ fontSize: '12px', color: isAtlas ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.7)', whiteSpace: 'pre-wrap', lineHeight: '1.5' }}>
                                            {msg.content?.replace(/\{[\s\S]*?\}/g, '').replace(/\[[A-Z_]+(:.*?)?\]/g, '').trim()}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
});

export const WorkerInspectorCard = memo(({ data, isStage = false }) => {
    const title = data?.title || 'Worker Inspector';
    const workers = data?.workers || [];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', width: '100%', height: '100%', minHeight: '300px' }}>
            <div style={{
                border: isStage ? '1px solid rgba(16, 185, 129, 0.2)' : '1px solid var(--card-border)',
                borderRadius: '12px',
                padding: '14px',
                background: isStage
                    ? 'radial-gradient(circle at 0% 0%, rgba(16, 185, 129, 0.1), transparent 60%)'
                    : 'radial-gradient(circle at 0% 0%, rgba(16,185,129,0.16), transparent 45%), linear-gradient(120deg, rgba(15,23,42,0.5), rgba(16,185,129,0.08))',
                boxShadow: isStage ? 'none' : 'inset 0 1px 0 rgba(255,255,255,0.05)',
                backdropFilter: isStage ? 'blur(10px)' : 'none',
                display: 'flex', flexDirection: 'column',
                flex: 1, minHeight: 0
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', flexShrink: 0 }}>
                    <Layers size={16} color="#10b981" />
                    <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-primary)' }}>{title}</div>
                </div>

                <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px', padding: '12px', background: 'rgba(0,0,0,0.2)' }}>
                    {workers.length === 0 ? (
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Nenhum worker ativo no momento.</div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            {workers.map((worker, i) => {
                                const wStatus = String(worker.status || 'running').toLowerCase();
                                const statusColor = { running: '#10b981', executing: '#10b981', active: '#10b981', thinking: '#a855f7', waiting: '#f59e0b', tool_use: '#00f2ff', responding: '#3b82f6' }[wStatus] || 'var(--text-muted)';
                                
                                return (
                                    <div key={i} style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '10px', background: 'rgba(255,255,255,0.02)' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                                            <div style={{ fontSize: '11px', fontWeight: '800', color: 'var(--text-primary)' }}>{worker.label || worker.work_id || worker.id || `Worker ${i}`}</div>
                                            <div style={{ fontSize: '9px', fontWeight: '800', padding: '2px 6px', borderRadius: '999px', background: `${statusColor}20`, color: statusColor, textTransform: 'uppercase' }}>{wStatus}</div>
                                        </div>
                                        <pre style={{ margin: 0, padding: '8px', background: 'rgba(0,0,0,0.4)', borderRadius: '4px', fontSize: '10px', color: 'var(--text-muted)', fontFamily: "'Fira Code', monospace", overflowX: 'auto' }}>
                                            {JSON.stringify(worker, null, 2)}
                                        </pre>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
});
