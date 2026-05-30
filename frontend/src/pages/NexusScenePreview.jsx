import React, { useMemo, useState } from 'react';
import WegenaParticleCanvas from '../components/WegenaParticleCanvas';
import { ThemeProvider, useTheme } from '../context/ThemeContext';
import StitchBackground from '../components/StitchBackground';

const STATUS_OPTIONS = ['idle', 'listening', 'thinking', 'speaking'];
const SCENE_OPTIONS = [
    { id: 'ai-orb-classic', label: 'ai-orb-classic' },
    { id: 'neural-network', label: 'neural-network' },
    { id: 'neon-waves', label: 'neon-waves' },
    { id: 'hexa-cube', label: 'hexa-cube' },
    { id: 'aether-minimal', label: 'aether-minimal' }
];

function getPreviewParams() {
    if (typeof window === 'undefined') {
        return {
            sceneId: 'aether-minimal',
            status: 'idle',
            micIntensity: 0.45,
            ttsIntensity: 0.35,
            recording: true,
        };
    }

    const params = new URLSearchParams(window.location.search);
    const sceneId = params.get('scene');
    const status = params.get('status');
    const mic = Number(params.get('mic'));
    const tts = Number(params.get('tts'));
    const recording = params.get('recording');

    return {
        sceneId: SCENE_OPTIONS.some((option) => option.id === sceneId) ? sceneId : 'aether-minimal',
        status: STATUS_OPTIONS.includes(status) ? status : 'idle',
        micIntensity: Number.isFinite(mic) ? Math.max(0, Math.min(1, mic)) : 0.45,
        ttsIntensity: Number.isFinite(tts) ? Math.max(0, Math.min(1, tts)) : 0.35,
        recording: recording == null ? true : recording !== 'false',
    };
}

function PreviewSurface() {
    const { theme, setTheme } = useTheme();
    const initialParams = useMemo(() => getPreviewParams(), []);
    const [status, setStatus] = useState(initialParams.status);
    const [micIntensity, setMicIntensity] = useState(initialParams.micIntensity);
    const [ttsIntensity, setTtsIntensity] = useState(initialParams.ttsIntensity);
    const [isRecording, setIsRecording] = useState(initialParams.recording);
    const [sceneId, setSceneId] = useState(initialParams.sceneId);

    const state = useMemo(() => ({
        voiceState: {
            status,
            intensity: micIntensity,
            isActive: status === 'listening',
        },
    }), [status, micIntensity]);

    const voice = useMemo(() => ({
        isRecording,
        intensity: micIntensity,
    }), [isRecording, micIntensity]);

    const panelBg = theme === 'light'
        ? 'radial-gradient(circle at top, rgba(96,165,250,0.18), rgba(243,244,246,0.96) 48%, rgba(229,231,235,1) 100%)'
        : 'radial-gradient(circle at top, rgba(37,99,235,0.16), rgba(2,2,5,0.98) 44%, rgba(2,2,5,1) 100%)';

    return (
        <div style={{ width: '100vw', height: '100vh', position: 'relative', overflow: 'hidden', background: panelBg }}>
            {theme === 'dark' && <StitchBackground />}
            <WegenaParticleCanvas
                state={state}
                voice={voice}
                ttsIntensity={status === 'speaking' ? ttsIntensity : 0}
                theme={theme}
                defaultPresetId={sceneId}
            />

            <div
                style={{
                    position: 'absolute',
                    top: 18,
                    left: 18,
                    zIndex: 5,
                    padding: '6px 10px',
                    borderRadius: 999,
                    background: 'rgba(5,8,20,0.72)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    color: '#dbeafe',
                    fontFamily: 'system-ui, sans-serif',
                    fontSize: 12,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase'
                }}
            >
                Wegena Scene
            </div>

            <div
                style={{
                    position: 'absolute',
                    left: 24,
                    bottom: 24,
                    zIndex: 20,
                    width: 320,
                    padding: 18,
                    borderRadius: 18,
                    background: theme === 'light' ? 'rgba(255,255,255,0.82)' : 'rgba(5,8,20,0.72)',
                    border: theme === 'light' ? '1px solid rgba(15,23,42,0.08)' : '1px solid rgba(255,255,255,0.08)',
                    boxShadow: '0 18px 60px rgba(0,0,0,0.24)',
                    backdropFilter: 'blur(18px)',
                    color: theme === 'light' ? '#0f172a' : '#e5eefc',
                    fontFamily: 'system-ui, sans-serif'
                }}
            >
                <div style={{ fontSize: 12, letterSpacing: '0.14em', textTransform: 'uppercase', opacity: 0.72, marginBottom: 10 }}>
                    Atlas Scene Preview
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
                    {SCENE_OPTIONS.map((option) => (
                        <button
                            key={option.id}
                            type="button"
                            onClick={() => setSceneId(option.id)}
                            style={{
                                border: 'none',
                                cursor: 'pointer',
                                padding: '8px 12px',
                                borderRadius: 999,
                                background: option.id === sceneId ? '#0f766e' : (theme === 'light' ? 'rgba(148,163,184,0.18)' : 'rgba(148,163,184,0.14)'),
                                color: option.id === sceneId ? '#fff' : 'inherit'
                            }}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
                    {STATUS_OPTIONS.map((option) => (
                        <button
                            key={option}
                            type="button"
                            onClick={() => setStatus(option)}
                            style={{
                                border: 'none',
                                cursor: 'pointer',
                                padding: '8px 12px',
                                borderRadius: 999,
                                textTransform: 'capitalize',
                                background: option === status ? '#2563eb' : (theme === 'light' ? 'rgba(148,163,184,0.18)' : 'rgba(148,163,184,0.14)'),
                                color: option === status ? '#fff' : 'inherit'
                            }}
                        >
                            {option}
                        </button>
                    ))}
                </div>

                <label style={{ display: 'block', fontSize: 12, marginBottom: 6 }}>Mic intensity</label>
                <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    value={micIntensity}
                    onChange={(e) => setMicIntensity(Number(e.target.value))}
                    style={{ width: '100%', marginBottom: 12 }}
                />

                <label style={{ display: 'block', fontSize: 12, marginBottom: 6 }}>TTS intensity</label>
                <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    value={ttsIntensity}
                    onChange={(e) => setTtsIntensity(Number(e.target.value))}
                    style={{ width: '100%', marginBottom: 12 }}
                />

                <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12 }}>
                    <button
                        type="button"
                        onClick={() => setIsRecording((value) => !value)}
                        style={{
                            border: 'none',
                            cursor: 'pointer',
                            padding: '8px 12px',
                            borderRadius: 999,
                            background: isRecording ? '#0f766e' : '#475569',
                            color: '#fff'
                        }}
                    >
                        {isRecording ? 'Recording on' : 'Recording off'}
                    </button>
                    <button
                        type="button"
                        onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
                        style={{
                            border: 'none',
                            cursor: 'pointer',
                            padding: '8px 12px',
                            borderRadius: 999,
                            background: theme === 'light' ? '#0f172a' : '#dbeafe',
                            color: theme === 'light' ? '#fff' : '#0f172a'
                        }}
                    >
                        Theme: {theme}
                    </button>
                </div>

                <div style={{ fontSize: 12, opacity: 0.72 }}>
                    Use this route to compare the Wegena default scene against the current Atlas orb without auth noise.
                </div>
            </div>
        </div>
    );
}

export default function NexusScenePreview() {
    return (
        <ThemeProvider>
            <PreviewSurface />
        </ThemeProvider>
    );
}
