import React, { memo } from 'react';

import { formatTime } from '../../utils/chatHistoryTransform';
import { formatDurationMs } from './ThoughtTimeline.utils.js';

export const ThoughtTimeline = memo(({ block }) => {
    if (!block || !Array.isArray(block.entries) || block.entries.length === 0) return null;

    const entries = block.entries.filter(Boolean);
    const latestEntry = entries[entries.length - 1] || null;
    const durationMs = latestEntry?.thinkingDurationMs ?? block.thinkingDurationMs ?? block.streamDurationMs ?? block.turnDurationMs ?? null;
    const durationLabel = formatDurationMs(durationMs);
    const liveLabel = block.isLive ? 'Pensando...' : 'Pensou por';

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
                    marginBottom: '12px',
                    padding: '10px 12px',
                    borderRadius: '12px',
                    border: '1px solid rgba(168,85,247,0.18)',
                    background: 'linear-gradient(180deg, rgba(168,85,247,0.06), rgba(255,255,255,0.025))',
                    boxShadow: '0 8px 18px rgba(0,0,0,0.08)',
                    backdropFilter: 'blur(8px)',
                    overflow: 'hidden',
                }}
            >
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '10px',
                    marginBottom: '8px',
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
                        {latestEntry?.label && (
                            <span style={{
                                fontSize: '9px',
                                fontWeight: 800,
                                color: 'var(--text-muted)',
                                letterSpacing: '0.04em',
                                textTransform: 'none',
                                opacity: 0.85,
                            }}>
                                {latestEntry.label}
                            </span>
                        )}
                        {durationLabel && (
                            <span style={{
                                fontSize: '9px',
                                fontWeight: 800,
                                color: 'var(--text-muted)',
                                letterSpacing: '0.04em',
                                textTransform: 'none',
                                opacity: 0.8,
                            }}>
                                {liveLabel} {durationLabel}
                            </span>
                        )}
                    </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {entries.map((entry, idx) => (
                        <div
                            key={entry.id || `${block.key}-${idx}`}
                            style={{
                                display: 'flex',
                                gap: '10px',
                                alignItems: 'flex-start',
                                opacity: idx === entries.length - 1 ? 1 : 0.68,
                            }}
                        >
                            <div
                                style={{
                                    minWidth: '4px',
                                    alignSelf: 'stretch',
                                    borderRadius: '999px',
                                    background: 'var(--accent-color)',
                                    opacity: idx === entries.length - 1 ? 0.75 : 0.4,
                                }}
                            />
                            <div style={{ minWidth: 0, flex: 1 }}>
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    gap: '10px',
                                    marginBottom: '2px',
                                }}>
                                    <p style={{
                                        margin: 0,
                                        fontSize: '12px',
                                        lineHeight: 1.5,
                                        color: 'var(--text-main)',
                                        whiteSpace: 'pre-wrap',
                                        fontWeight: 600,
                                    }}>
                                        {entry.label || entry.summary || entry.text}
                                    </p>
                                    {entry.ts && (
                                        <span style={{
                                            fontSize: '9px',
                                            color: 'var(--text-muted)',
                                            opacity: 0.8,
                                            flexShrink: 0,
                                        }}>
                                            {formatTime(entry.ts)}
                                        </span>
                                    )}
                                </div>

                                {entry.summary && entry.summary !== entry.label && (
                                    <p style={{
                                        margin: 0,
                                        fontSize: '11px',
                                        lineHeight: 1.5,
                                        color: 'var(--text-muted)',
                                        opacity: 0.95,
                                        whiteSpace: 'pre-wrap',
                                    }}>
                                        {entry.summary}
                                    </p>
                                )}

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
                                    {entry.phase && <span>{String(entry.phase).replace(/_/g, ' ')}</span>}
                                    {entry.source && <span>{String(entry.source).replace(/_/g, ' ')}</span>}
                                    {entry.capability && <span>{String(entry.capability).replace(/_/g, ' ')}</span>}
                                    {entry.turnId != null && <span>turn {entry.turnId}</span>}
                                    {entry.workId && <span>work {String(entry.workId).slice(0, 8)}</span>}
                                    {entry.streamId && <span>stream {String(entry.streamId).slice(0, 8)}</span>}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
});
