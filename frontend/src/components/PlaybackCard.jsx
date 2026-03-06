import React, { useState, useEffect, useRef } from 'react';
import { Play, Pause, SkipBack, SkipForward, Monitor, ExternalLink, Download, Maximize2, Minimize2 } from 'lucide-react';

const PlaybackCard = ({ runId, sessionId, initialManifest = null, liveEvent = null, embedMode = false }) => {
    const [manifest, setManifest] = useState(initialManifest);
    const [currentStepIndex, setCurrentStepIndex] = useState(0);
    const [isPlaying, setIsPlaying] = useState(false);
    const [playbackSpeed, setPlaybackSpeed] = useState(1000); // ms per step
    const playbackTimerRef = useRef(null);
    const [isLive, setIsLive] = useState(!initialManifest || initialManifest.status === 'running');
    const manifestPollRef = useRef(null);
    const cardRef = useRef(null);
    const [isSystemFullscreen, setIsSystemFullscreen] = useState(false);
    const [isMinimized, setIsMinimized] = useState(false);

    // Fetch manifest if not provided
    useEffect(() => {
        if (!initialManifest && runId && sessionId) {
            fetchManifest();
        } else if (initialManifest) {
            setManifest(initialManifest);
            if (initialManifest.status !== 'running') {
                setIsLive(false);
                setCurrentStepIndex(initialManifest.steps?.length > 0 ? initialManifest.steps.length - 1 : 0);
            }
        }
    }, [runId, sessionId, initialManifest]);

    const fetchManifest = async () => {
        try {
            const response = await fetch(`/api/sessions/${sessionId}/playback/${runId}/manifest`, {
                credentials: 'include',
                cache: 'no-store',
            });
            const data = await response.json();
            setManifest(data);
            if (isLive && data?.steps?.length) {
                setCurrentStepIndex(data.steps.length - 1);
            }
            if (data.status !== 'running') {
                setIsLive(false);
                setCurrentStepIndex(data.steps?.length > 0 ? data.steps.length - 1 : 0);
            }
        } catch (err) {
            console.error("Error fetching playback manifest:", err);
        }
    };

    // Handle live events
    useEffect(() => {
        if (liveEvent && liveEvent.run_id === runId) {
            if (liveEvent.type === 'playback.frame') {
                setManifest(prev => {
                    if (!prev) {
                        const seeded = {
                            run_id: runId,
                            session_id: sessionId,
                            status: 'running',
                            steps: [liveEvent.frame],
                            title: 'Browser Agent'
                        };
                        if (isLive) setCurrentStepIndex(0);
                        return seeded;
                    }
                    const newSteps = [...(prev.steps || []), liveEvent.frame];
                    if (isLive) setCurrentStepIndex(newSteps.length - 1);
                    return { ...prev, steps: newSteps, total_steps: newSteps.length };
                });
            } else if (liveEvent.type === 'playback.end') {
                setIsLive(false);
                setManifest(prev => prev ? { ...prev, status: liveEvent.status || 'success' } : null);
                fetchManifest();
            }
        }
    }, [liveEvent, runId, isLive]);

    // Poll manifest while live to avoid stale UI if SSE frames are missed.
    useEffect(() => {
        if (!runId || !sessionId || !isLive) {
            if (manifestPollRef.current) {
                clearInterval(manifestPollRef.current);
                manifestPollRef.current = null;
            }
            return;
        }

        fetchManifest();
        manifestPollRef.current = setInterval(() => {
            fetchManifest();
        }, 1000);

        return () => {
            if (manifestPollRef.current) {
                clearInterval(manifestPollRef.current);
                manifestPollRef.current = null;
            }
        };
    }, [runId, sessionId, isLive]);

    useEffect(() => {
        if (isPlaying && !isLive) {
            playbackTimerRef.current = setInterval(() => {
                setCurrentStepIndex(current => {
                    if (current < (manifest?.steps?.length || 0) - 1) {
                        return current + 1;
                    } else {
                        setIsPlaying(false);
                        return current;
                    }
                });
            }, playbackSpeed);
        } else {
            clearInterval(playbackTimerRef.current);
        }
        return () => clearInterval(playbackTimerRef.current);
    }, [isPlaying, isLive, playbackSpeed, manifest]);

    useEffect(() => {
        const onFullscreenChange = () => {
            const active = document.fullscreenElement === cardRef.current
                || document.webkitFullscreenElement === cardRef.current;
            setIsSystemFullscreen(Boolean(active));
        };
        document.addEventListener('fullscreenchange', onFullscreenChange);
        document.addEventListener('webkitfullscreenchange', onFullscreenChange);
        return () => {
            document.removeEventListener('fullscreenchange', onFullscreenChange);
            document.removeEventListener('webkitfullscreenchange', onFullscreenChange);
        };
    }, []);

    const requestSystemFullscreen = async () => {
        const el = cardRef.current;
        if (!el) return;
        try {
            if (el.requestFullscreen) await el.requestFullscreen();
            else if (el.webkitRequestFullscreen) await el.webkitRequestFullscreen();
        } catch (err) {
            console.error('Failed to enter fullscreen:', err);
        }
    };

    if (!manifest || !manifest.steps || manifest.steps.length === 0) {
        return (
            <div className="playback-card glass loading" style={{ margin: embedMode ? '0 auto' : '10px auto', borderRadius: '14px', border: '1px solid var(--card-border)', background: 'rgba(0,0,0,0.4)', maxWidth: '420px', width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '170px', flexDirection: 'column', gap: '12px' }}>
                    <div className="loader-spin" style={{ width: '24px', height: '24px', border: '2px solid rgba(255,255,255,0.1)', borderTopColor: 'var(--accent-color)', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Aguardando interação visual...</span>
                </div>
            </div>
        );
    }

    // Minimized compact chip
    if (isMinimized) {
        return (
            <div
                onClick={() => setIsMinimized(false)}
                style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '6px 14px',
                    borderRadius: '12px',
                    background: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid var(--card-border)',
                    cursor: 'pointer',
                    margin: '8px 0',
                    transition: 'all 0.2s ease',
                }}
            >
                <Monitor size={12} color="var(--accent-color)" />
                <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-primary)' }}>
                    {manifest.title || 'Browser Session'}
                </span>
                <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                    • {manifest.steps.length} frames
                </span>
                {isLive && (
                    <div style={{ width: '6px', height: '6px', background: '#ef4444', borderRadius: '50%', animation: 'pulse 1.5s infinite' }} />
                )}
                <Maximize2 size={12} color="var(--text-muted)" />
            </div>
        );
    }

    const currentStep = manifest.steps[currentStepIndex];
    if (!currentStep) return null;

    // Build frame URL on same-origin /api path so auth cookies are always sent.
    const rawFrameRef = currentStep.url || currentStep.frame_filename || currentStep.filename || '';
    let frameUrl = '';
    if (rawFrameRef) {
        if (rawFrameRef.startsWith('/api/')) {
            frameUrl = rawFrameRef;
        } else if (rawFrameRef.startsWith('http://') || rawFrameRef.startsWith('https://')) {
            try {
                const parsed = new URL(rawFrameRef);
                frameUrl = parsed.pathname + parsed.search;
            } catch {
                frameUrl = rawFrameRef;
            }
        } else if (rawFrameRef.startsWith('frames/')) {
            // Manifest stores frames as "frames/000001.jpg"
            const basename = rawFrameRef.replace(/^frames\//, '');
            frameUrl = `/api/sessions/${sessionId}/playback/${runId}/frames/${basename}`;
        } else {
            frameUrl = `/api/sessions/${sessionId}/playback/${runId}/frames/${rawFrameRef}`;
        }
    } else {
        frameUrl = `/api/sessions/${sessionId}/playback/${runId}/frames/${String(currentStepIndex).padStart(6, '0')}.jpg`;
    }

    return (
        <div ref={cardRef} className="playback-card glass" style={{
            borderRadius: '14px',
            overflow: 'hidden',
            border: '1px solid var(--card-border)',
            background: 'rgba(15, 23, 42, 0.6)',
            margin: embedMode ? '0 auto' : '10px auto',
            maxWidth: isSystemFullscreen ? '100vw' : '420px',
            width: isSystemFullscreen ? '100vw' : '100%',
            boxShadow: 'var(--shadow-lg)',
            animation: 'fadeIn 0.3s ease-out'
        }}>
            {/* Header */}
            <div style={{ padding: '10px 14px', background: 'rgba(0,0,0,0.3)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0, flex: 1 }}>
                    <Monitor size={14} color="var(--accent-color)" />
                    <span style={{ fontSize: '12px', fontWeight: '700', letterSpacing: '0.5px', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{manifest.title || 'Browser Session'}</span>
                    {isLive && (
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', marginLeft: '8px', padding: '2px 8px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '12px', border: '1px solid rgba(239, 68, 68, 0.2)', flexShrink: 0, whiteSpace: 'nowrap' }}>
                            <div style={{ width: '6px', height: '6px', background: '#ef4444', borderRadius: '50%', animation: 'pulse 1.5s infinite' }} />
                            <span style={{ fontSize: '9px', color: '#ef4444', fontWeight: '800', textTransform: 'uppercase', lineHeight: 1 }}>Live</span>
                        </div>
                    )}
                </div>
                <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                    <button onClick={requestSystemFullscreen} style={{ padding: '6px', borderRadius: '8px' }} className="btn-ghost" title="Fullscreen"><Maximize2 size={14} /></button>
                    <button onClick={() => setIsMinimized(true)} style={{ padding: '6px', borderRadius: '8px' }} className="btn-ghost" title="Minimize"><Minimize2 size={14} /></button>
                </div>
            </div>

            {/* Frame View */}
            <div style={{ position: 'relative', width: '100%', aspectRatio: '16/9', background: '#000', cursor: isLive ? 'default' : 'pointer' }}>
                <img
                    src={frameUrl}
                    alt={`Step ${currentStepIndex}`}
                    style={{ width: '100%', height: '100%', objectFit: 'contain', transition: '0.2s' }}
                    onLoad={(e) => e.target.style.opacity = 1}
                />

                {/* Overlay Action */}
                {currentStep.action && (
                    <div style={{
                        position: 'absolute',
                        bottom: '16px',
                        left: '16px',
                        right: '16px',
                        background: 'rgba(15, 23, 42, 0.85)',
                        backdropFilter: 'blur(8px)',
                        padding: '10px 14px',
                        borderRadius: '12px',
                        fontSize: '11px',
                        color: '#fff',
                        border: '1px solid rgba(255,255,255,0.1)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '10px',
                        boxShadow: 'var(--shadow-md)',
                        animation: 'slideUp 0.3s ease-out'
                    }}>
                        <div style={{ width: '8px', height: '8px', background: 'var(--accent-color)', borderRadius: '2px' }} />
                        <span style={{ color: 'var(--accent-color)', fontWeight: '800', textTransform: 'uppercase' }}>{currentStep.action.name}</span>
                        <span style={{ opacity: 0.8, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{currentStep.action.target}</span>
                    </div>
                )}
            </div>

            {/* Controls */}
            <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                    <button
                        onClick={() => setIsPlaying(!isPlaying)}
                        disabled={isLive}
                        style={{
                            background: isPlaying ? 'rgba(255,255,255,0.1)' : 'var(--accent-color)',
                            width: '36px',
                            height: '36px',
                            borderRadius: '50%',
                            display: 'flex',
                            justifyContent: 'center',
                            alignItems: 'center',
                            border: 'none',
                            cursor: isLive ? 'not-allowed' : 'pointer',
                            opacity: isLive ? 0.5 : 1,
                            transition: '0.2s'
                        }}
                    >
                        {isPlaying ? <Pause size={18} color="white" fill="white" /> : <Play size={18} color="white" fill="white" style={{ marginLeft: '2px' }} />}
                    </button>

                    <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center' }}>
                        <input
                            type="range"
                            min="0"
                            max={manifest.steps.length - 1}
                            value={currentStepIndex}
                            disabled={isLive}
                            onChange={(e) => {
                                setCurrentStepIndex(parseInt(e.target.value));
                                setIsPlaying(false);
                            }}
                            style={{
                                width: '100%',
                                accentColor: 'var(--accent-color)',
                                cursor: isLive ? 'not-allowed' : 'pointer',
                                height: '4px',
                                borderRadius: '2px'
                            }}
                        />
                    </div>

                    <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '600', minWidth: '45px', textAlign: 'right', fontFamily: 'monospace' }}>
                        {(currentStepIndex + 1).toString().padStart(2, '0')} / {manifest.steps.length.toString().padStart(2, '0')}
                    </span>
                </div>
            </div>

            <style dangerouslySetInnerHTML={{
                __html: `
                @keyframes pulse {
                    0% { transform: scale(1); opacity: 1; }
                    50% { transform: scale(1.2); opacity: 0.7; }
                    100% { transform: scale(1); opacity: 1; }
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}} />

        </div>
    );
};

export default PlaybackCard;
