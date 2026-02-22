import React, { useState, useEffect, useRef } from 'react';
import { Play, Pause, SkipBack, SkipForward, Monitor, ExternalLink, Download, Maximize2 } from 'lucide-react';

const PlaybackCard = ({ runId, sessionId, initialManifest = null, liveEvent = null }) => {
    const [manifest, setManifest] = useState(initialManifest);
    const [currentStepIndex, setCurrentStepIndex] = useState(0);
    const [isPlaying, setIsPlaying] = useState(false);
    const [playbackSpeed, setPlaybackSpeed] = useState(1000); // ms per step
    const playbackTimerRef = useRef(null);
    const [isLive, setIsLive] = useState(!initialManifest || initialManifest.status === 'running');

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
            const response = await fetch(`http://localhost:8000/api/sessions/${sessionId}/playback/${runId}/manifest`);
            const data = await response.json();
            setManifest(data);
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
                    if (!prev) return {
                        run_id: runId,
                        session_id: sessionId,
                        status: 'running',
                        steps: [liveEvent.frame],
                        title: 'Browser Agent'
                    };
                    const newSteps = [...(prev.steps || []), liveEvent.frame];
                    return { ...prev, steps: newSteps, total_steps: newSteps.length };
                });
                if (isLive) {
                    setManifest(prev => {
                        if (prev && prev.steps) {
                            setCurrentStepIndex(prev.steps.length - 1);
                        }
                        return prev;
                    });
                }
            } else if (liveEvent.type === 'playback.end') {
                setIsLive(false);
                setManifest(prev => prev ? { ...prev, status: 'success' } : null);
            }
        }
    }, [liveEvent, runId, isLive]);

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

    if (!manifest || !manifest.steps || manifest.steps.length === 0) {
        return (
            <div className="playback-card glass loading" style={{ margin: '12px 0', borderRadius: '16px', border: '1px solid var(--card-border)', background: 'rgba(0,0,0,0.4)' }}>
                <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '200px', flexDirection: 'column', gap: '12px' }}>
                    <div className="loader-spin" style={{ width: '24px', height: '24px', border: '2px solid rgba(255,255,255,0.1)', borderTopColor: 'var(--accent-color)', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Aguardando interação visual...</span>
                </div>
            </div>
        );
    }

    const currentStep = manifest.steps[currentStepIndex];
    if (!currentStep) return null;

    // Build URL: prepend backend base if it's a relative path from manifest
    let frameUrl = currentStep.url || `http://localhost:8000/api/sessions/${sessionId}/playback/${runId}/${currentStep.frame_filename}`;
    if (frameUrl.startsWith('/api')) {
        frameUrl = `http://localhost:8000${frameUrl}`;
    }

    return (
        <div className="playback-card glass" style={{
            borderRadius: '16px',
            overflow: 'hidden',
            border: '1px solid var(--card-border)',
            background: 'rgba(15, 23, 42, 0.6)',
            margin: '16px 0',
            maxWidth: '100%',
            boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
            animation: 'fadeIn 0.3s ease-out'
        }}>
            {/* Header */}
            <div style={{ padding: '12px 16px', background: 'rgba(0,0,0,0.3)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Monitor size={14} color="var(--accent-color)" />
                    <span style={{ fontSize: '12px', fontWeight: '700', letterSpacing: '0.5px' }}>{manifest.title || 'Browser Session'}</span>
                    {isLive && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginLeft: '8px', padding: '2px 8px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '12px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
                            <div style={{ width: '6px', height: '6px', background: '#ef4444', borderRadius: '50%', animation: 'pulse 1.5s infinite' }} />
                            <span style={{ fontSize: '9px', color: '#ef4444', fontWeight: '800', textTransform: 'uppercase' }}>Live</span>
                        </div>
                    )}
                </div>
                <div style={{ display: 'flex', gap: '4px' }}>
                    <button style={{ padding: '6px', borderRadius: '8px' }} className="btn-ghost"><Maximize2 size={14} /></button>
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
                        boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
                        animation: 'slideUp 0.3s ease-out'
                    }}>
                        <div style={{ width: '8px', height: '8px', background: 'var(--accent-color)', borderRadius: '2px' }} />
                        <span style={{ color: 'var(--accent-color)', fontWeight: '800', textTransform: 'uppercase' }}>{currentStep.action.name}</span>
                        <span style={{ opacity: 0.8, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{currentStep.action.target}</span>
                    </div>
                )}
            </div>

            {/* Controls */}
            <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
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
