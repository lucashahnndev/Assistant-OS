import React, { memo } from 'react';
import { Brain, RefreshCw } from 'lucide-react';

import { formatTime } from '../../utils/chatHistoryTransform';

export const ThoughtTimeline = memo(({ block }) => {
    if (!block || !Array.isArray(block.entries) || block.entries.length === 0) return null;

    return (
        <div
            className="animate-fade-in"
            style={{
                width: '100%',
                display: 'flex',
                justifyContent: 'flex-start',
            }}
        >
            <div
                style={{
                    width: 'min(92%, 56rem)',
                    marginLeft: 0,
                    marginBottom: '10px',
                    padding: '12px 14px',
                    borderRadius: '14px',
                    border: '1px solid rgba(168,85,247,0.22)',
                    background: 'linear-gradient(180deg, rgba(168,85,247,0.08), rgba(255,255,255,0.03))',
                    boxShadow: '0 10px 24px rgba(0,0,0,0.12)',
                    backdropFilter: 'blur(10px)',
                    overflow: 'hidden',
                }}
            >
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '10px',
                    marginBottom: '10px',
                }}>
                    <div style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '8px',
                        color: 'var(--text-muted)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.08em',
                        fontSize: '10px',
                        fontWeight: 900,
                    }}>
                        <Brain size={12} color="var(--accent-color)" />
                        <span>{block.title || 'Thoughts'}</span>
                    </div>
                    {block.isLive && (
                        <div style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '6px',
                            color: 'var(--accent-color)',
                            textTransform: 'uppercase',
                            letterSpacing: '0.08em',
                            fontSize: '9px',
                            fontWeight: 800,
                        }}>
                            <RefreshCw size={10} className="animate-spin" />
                            <span>Processing</span>
                        </div>
                    )}
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {block.entries.map((entry, idx) => (
                        <div
                            key={entry.id || `${block.key}-${idx}`}
                            style={{
                                display: 'flex',
                                gap: '10px',
                                alignItems: 'flex-start',
                                opacity: idx === block.entries.length - 1 ? 1 : 0.72,
                            }}
                        >
                            <div
                                style={{
                                    minWidth: '4px',
                                    alignSelf: 'stretch',
                                    borderRadius: '999px',
                                    background: 'var(--accent-color)',
                                    opacity: idx === block.entries.length - 1 ? 0.8 : 0.45,
                                }}
                            />
                            <div style={{ minWidth: 0, flex: 1 }}>
                                <p style={{
                                    margin: 0,
                                    fontSize: '12px',
                                    lineHeight: 1.6,
                                    color: 'var(--text-main)',
                                    whiteSpace: 'pre-wrap',
                                }}>
                                    {entry.text}
                                </p>
                                <div style={{
                                    marginTop: '4px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    flexWrap: 'wrap',
                                    fontSize: '9px',
                                    letterSpacing: '0.04em',
                                    textTransform: 'uppercase',
                                    color: 'var(--text-muted)',
                                    opacity: 0.8,
                                }}>
                                    {entry.ts && <span>{formatTime(entry.ts)}</span>}
                                    {entry.source && <span>{String(entry.source).replace(/_/g, ' ')}</span>}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
});
