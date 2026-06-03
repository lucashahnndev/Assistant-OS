import React, { memo } from 'react';

import { buildThoughtTimelineRenderRows, formatDurationMs } from './ThoughtTimeline.utils.js';

export const ThoughtTimeline = memo(({ block }) => {
    if (!block || !Array.isArray(block.entries) || block.entries.length === 0) return null;

    const entries = buildThoughtTimelineRenderRows(block);
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
                padding: '0',
            }}
        >
            <div
                style={{
                    width: 'min(92%, 56rem)',
                    marginLeft: 0,
                    marginBottom: '8px',
                    padding: 0,
                    border: 'none',
                    background: 'transparent',
                    boxShadow: 'none',
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
                        fontSize: '10px',
                        fontWeight: 600,
                        letterSpacing: '0.02em',
                    }}>
                        {durationLabel ? (
                            <span style={{ opacity: 0.8 }}>
                                {liveLabel} {durationLabel}
                            </span>
                        ) : (
                            <span style={{ opacity: 0.8 }}>{liveLabel}</span>
                        )}
                    </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {entries.map((entry, idx) => (
                        <div
                            key={entry.id || `${block.key}-${idx}`}
                            style={{
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '2px',
                                opacity: idx === entries.length - 1 ? 1 : 0.62,
                                padding: '1px 0',
                            }}
                        >
                            <p style={{
                                margin: 0,
                                fontSize: '11px',
                                lineHeight: 1.35,
                                color: 'var(--text-muted)',
                                whiteSpace: 'pre-wrap',
                                fontWeight: idx === entries.length - 1 ? 700 : 600,
                                letterSpacing: '-0.01em',
                            }}>
                                {`${entry.displayTitle || entry.title || entry.label || 'Pensando na próxima etapa'}${idx === entries.length - 1 ? '...' : ''}`}
                            </p>

                            {entry.displaySummary && (
                                <p style={{
                                    margin: 0,
                                    fontSize: '13px',
                                    lineHeight: 1.5,
                                    color: 'var(--text-main)',
                                    opacity: 0.88,
                                    whiteSpace: 'pre-wrap',
                                }}>
                                    {entry.displaySummary}
                                </p>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
});
