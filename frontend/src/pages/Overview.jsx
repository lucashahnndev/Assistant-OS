import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Mic, ShieldCheck, Activity, Cpu, Network, Calendar, Loader } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import Typewriter from 'typewriter-effect';
import WegenaParticleCanvas from '../components/WegenaParticleCanvas';
import DynamicPluginRenderer from '../components/DynamicPluginRenderer';

const Overview = () => {
    const navigate = useNavigate();
    const { agentName } = useAuth();
    const { theme } = useTheme();
    
    const [bootText, setBootText] = useState("");
    const [bootStatus, setBootStatus] = useState("Initializing core Neural Matrices...");
    const [widgets, setWidgets] = useState([]);
    const [sceneLoaded, setSceneLoaded] = useState(false);
    const [wsConnected, setWsConnected] = useState(false);
    const [bootComplete, setBootComplete] = useState(false);
    
    const wsRef = useRef(null);
    const audioCtxRef = useRef(null);
    const audioQueueRef = useRef([]);
    const isPlayingRef = useRef(false);
    const hasSentBootRef = useRef(false); // Guard against StrictMode double-mount

    useEffect(() => {
        // If already opened (React StrictMode cleanup+remount), don't reopen
        if (wsRef.current && wsRef.current.readyState < 2) return;

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/system.boot`;
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            setWsConnected(true);

            // Send the boot prompt directly — same mechanism Nexus uses.
            // No separate HTTP trigger needed; server_driver routes WS messages
            // through the orchestrator automatically.
            // Check settings for voice preference
            const localSettings = JSON.parse(localStorage.getItem('atlas_settings') || '{}');
            const isVoiceActive = localSettings.voice_active !== false; // Default true

            if (!hasSentBootRef.current) {
                hasSentBootRef.current = true;
                ws.send(JSON.stringify({
                    type: 'msg',
                    content: '__BOOT_SEQUENCE__',
                    user_data: { is_boot: true, is_voice_active: isVoiceActive }
                }));
            }
        };

        ws.onclose = () => setWsConnected(false);

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                if (data.type === 'status' || data.type === 'worker_state') {
                    const msg = data.payload?.message || data.data?.status || data.message;
                    if (msg) setBootStatus(`[SYS] ${msg}`);
                }

                if (data.type === 'thought' || data.type === 'assistant_thought' || data.type === 'reasoning_chunk') {
                    const txt = data.thought || data.content;
                    if (txt) setBootStatus(`[THINKING] ${txt}`);
                }

                if (data.type === 'assistant_chunk' || data.type === 'final_message_chunk') {
                    setBootText(prev => prev + (data.chunk || data.content || ''));
                }

                if (data.type === 'tts.chunk') {
                    if (!audioCtxRef.current) {
                        const AudioContext = window.AudioContext || window.webkitAudioContext;
                        audioCtxRef.current = new AudioContext();
                    }
                    audioQueueRef.current.push(data.b64);
                    playNextChunk();
                }

                if (data.type === 'tool_result' || data.type === 'worker_event') {
                    const payload = data.payload || data.data || {};
                    if (payload && typeof payload === 'object') {
                        const title = payload.title || payload.action || 'System Check';
                        setWidgets(prev => {
                            if (prev.find(w => w.title === title)) return prev;
                            return [...prev, { capabilityId: payload.capability || 'generic', title, payload }];
                        });
                    }
                }

                if (data.type === 'assistant_response') {
                    setBootComplete(true);
                }

            } catch (err) {
                console.error('Boot WS Error:', err);
            }
        };

        return () => {
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
            if (audioCtxRef.current) {
                audioCtxRef.current.close();
                audioCtxRef.current = null;
            }
        };
    }, []);

    const playNextChunk = async () => {
        if (isPlayingRef.current || audioQueueRef.current.length === 0 || !audioCtxRef.current) return;
        isPlayingRef.current = true;
        
        try {
            const b64 = audioQueueRef.current.shift();
            const binaryString = window.atob(b64);
            const len = binaryString.length;
            const bytes = new Uint8Array(len);
            for (let i = 0; i < len; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            
            const audioBuffer = await audioCtxRef.current.decodeAudioData(bytes.buffer);
            const source = audioCtxRef.current.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(audioCtxRef.current.destination);
            
            source.onended = () => {
                isPlayingRef.current = false;
                playNextChunk();
            };
            
            source.start();
        } catch (e) {
            console.error("Audio playback error", e);
            isPlayingRef.current = false;
            playNextChunk();
        }
    };

    const handleEnterNexus = (voice = false) => {
        navigate('/nexus', { state: { autoStartVoice: voice } });
    };

    return (
        <div
            className="flex-center"
            style={{
                width: '100%',
                height: '100%',
                minHeight: '100vh',
                background: theme === 'light'
                    ? 'radial-gradient(120% 90% at 16% 18%, #eef3fb 0%, #dce5f2 54%, #cfd9ea 100%)'
                    : 'radial-gradient(120% 100% at 18% 18%, rgba(46, 92, 198, 0.15) 0%, rgba(13, 31, 78, 0.05) 46%, rgba(0,0,0,0) 70%), linear-gradient(138deg, #020817 0%, #050a14 46%, #050a14 100%)',
                position: 'relative',
                overflow: 'hidden'
            }}
        >
            <div style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                zIndex: 1,
                opacity: 0.8
            }}>
                <WegenaParticleCanvas
                    defaultPresetId="neon-waves"
                    onSceneLoaded={() => setTimeout(() => setSceneLoaded(true), 800)}
                />
            </div>

            {/* Ambient glows */}
            <div className="login-ambient login-ambient--a" style={{
                position: 'absolute',
                top: '14%',
                left: '24%',
                width: '560px',
                height: '560px',
                borderRadius: '50%',
                background: theme === 'light'
                    ? 'radial-gradient(circle, rgba(90, 122, 188, 0.12) 0%, rgba(90,122,188,0.03) 42%, rgba(0,0,0,0) 75%)'
                    : 'radial-gradient(circle, rgba(37, 99, 235, 0.08) 0%, rgba(37,99,235,0.02) 44%, rgba(0,0,0,0) 76%)',
                filter: 'blur(78px)',
                zIndex: 2,
            }} />
            <div className="login-ambient login-ambient--b" style={{
                position: 'absolute',
                right: '8%',
                bottom: '8%',
                width: '500px',
                height: '500px',
                borderRadius: '50%',
                background: theme === 'light'
                    ? 'radial-gradient(circle, rgba(108, 146, 205, 0.10) 0%, rgba(108,146,205,0.02) 40%, rgba(0,0,0,0) 74%)'
                    : 'radial-gradient(circle, rgba(14, 165, 233, 0.06) 0%, rgba(14,165,233,0.02) 40%, rgba(0,0,0,0) 74%)',
                filter: 'blur(90px)',
                zIndex: 2,
                pointerEvents: 'none'
            }} />

            {/* Soft radial wash & Vignette */}
            <div style={{
                position: 'absolute', inset: 0,
                background: theme === 'light'
                    ? 'radial-gradient(circle at center, rgba(255,255,255,0) 10%, rgba(226,233,245,0.52) 66%, rgba(214,222,238,0.86) 100%)'
                    : 'radial-gradient(circle at center, rgba(0,0,0,0.0) 10%, rgba(7,12,24,0.12) 62%, rgba(3,7,14,0.30) 100%)',
                pointerEvents: 'none', zIndex: 3
            }} />
            <div style={{
                position: 'absolute', inset: 0,
                background: theme === 'light'
                    ? 'radial-gradient(circle at center, transparent 44%, rgba(168,178,197,0.22) 100%)'
                    : 'radial-gradient(circle at center, transparent 48%, rgba(0,0,0,0.6) 100%)',
                pointerEvents: 'none', zIndex: 4
            }} />

            {/* Main Glassmorphic Container */}
            <div style={{
                width: '680px',
                maxWidth: 'calc(100vw - 40px)',
                padding: '40px',
                display: 'flex',
                flexDirection: 'column',
                gap: '24px',
                borderRadius: '24px',
                background: theme === 'light' ? 'rgba(244, 247, 253, 0.66)' : 'rgba(10, 12, 16, 0.6)',
                backdropFilter: 'blur(32px)',
                WebkitBackdropFilter: 'blur(32px)',
                border: theme === 'light' ? '1px solid rgba(20, 28, 46, 0.14)' : '1px solid rgba(255, 255, 255, 0.05)',
                boxShadow: theme === 'light'
                    ? '0 30px 84px rgba(28, 42, 68, 0.24), 0 0 38px rgba(94,122,178,0.08)'
                    : '0 40px 120px rgba(0,0,0,0.65), 0 0 60px rgba(37,99,235,0.08)',
                zIndex: 10,
                position: 'relative',
                animation: 'loginCardIn 400ms cubic-bezier(0.16, 1, 0.3, 1) forwards'
            }}>
                <div style={{ textAlign: 'center', marginBottom: '8px' }}>
                    <h1 style={{ fontSize: '28px', fontWeight: '700', letterSpacing: '0.28em', color: 'var(--text-primary)', margin: 0, opacity: 0.96, textTransform: 'uppercase' }}>{agentName}</h1>
                    <h2 style={{ fontSize: '11px', fontWeight: '700', color: 'var(--accent-color)', marginTop: '8px', textTransform: 'uppercase', letterSpacing: '0.15em' }}>Boot Sequence Complete</h2>
                </div>

                {/* Dynamic Widgets Layout */}
                {widgets.length > 0 && (
                    <div className="grid grid-cols-2 gap-4">
                        {widgets.slice(0, 4).map((widget, idx) => (
                            <DynamicPluginRenderer 
                                key={idx} 
                                capabilityId={widget.capabilityId} 
                                title={widget.title} 
                                payload={widget.payload} 
                            />
                        ))}
                    </div>
                )}

                {/* Briefing Area */}
                <div style={{
                    minHeight: '80px',
                    padding: '24px',
                    background: theme === 'light' ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.25)',
                    borderRadius: '12px',
                    border: '1px solid ' + (theme === 'light' ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.03)'),
                    color: 'var(--text-color)',
                    fontSize: '1rem',
                    lineHeight: '1.6',
                    fontFamily: 'monospace',
                    boxShadow: 'inset 0 2px 10px rgba(0,0,0,0.05)'
                }}>
                    {!wsConnected ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: 'var(--text-muted)' }}>
                            <Loader size={16} className="spin" />
                            <span>Establishing Core Link...</span>
                        </div>
                    ) : (
                        <div>
                            {bootStatus && !bootComplete && (
                                <div style={{ color: 'var(--text-muted)', fontSize: '0.85em', marginBottom: '8px' }}>
                                    {bootStatus}
                                </div>
                            )}
                            <div style={{ color: 'var(--text-primary)', fontWeight: '500', fontFamily: 'var(--font-primary)', fontSize: '1.1rem', whiteSpace: 'pre-wrap' }}>
                                {bootText}
                                {!bootComplete && <span className="animate-pulse">_</span>}
                            </div>
                        </div>
                    )}
                </div>

                {/* Sub-Stats Row */}
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '0 8px', opacity: 0.8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '1px' }}>
                        <ShieldCheck size={14} color="#10b981" />
                        <span>System Secured</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '1px' }}>
                        <Activity size={14} color="var(--accent-color)" />
                        <span>Telemetry Online</span>
                    </div>
                </div>

                {/* Single Launcher */}
                <div style={{ display: 'flex', justifyContent: 'center', marginTop: '12px' }}>
                    <button
                        onClick={() => handleEnterNexus(true)}
                        className="login-submit"
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '12px',
                            width: '100%',
                            padding: '16px',
                            borderRadius: '12px',
                            border: 'none',
                            cursor: 'pointer',
                            color: '#fff',
                            fontSize: '1rem',
                            fontWeight: '600',
                            letterSpacing: '0.1em',
                            textTransform: 'uppercase'
                        }}
                    >
                        <Mic size={20} />
                        <span>Initialize Nexus</span>
                    </button>
                </div>
            </div>

            <style>{`
                .login-ambient {
                    will-change: transform, opacity, filter;
                    animation-iteration-count: infinite;
                    animation-timing-function: ease-in-out;
                }
                .login-ambient--a {
                    animation-name: loginAmbientDriftA;
                    animation-duration: 24s;
                }
                .login-ambient--b {
                    animation-name: loginAmbientDriftB;
                    animation-duration: 28s;
                }
                .login-submit {
                    background: var(--accent-color) !important;
                    transition: transform 180ms ease, filter 180ms ease, box-shadow 180ms ease !important;
                    box-shadow: 0 8px 20px rgba(28, 40, 66, 0.26);
                }
                .login-submit:hover {
                    transform: translateY(-2px);
                    filter: brightness(1.15);
                    box-shadow: 0 10px 28px rgba(37, 99, 235, 0.35);
                }
                .login-submit:active {
                    transform: translateY(0);
                    filter: brightness(0.95);
                }
                @keyframes loginCardIn {
                    from { opacity: 0; transform: translateY(12px) scale(0.98); }
                    to { opacity: 1; transform: translateY(0) scale(1); }
                }
                @keyframes loginAmbientDriftA {
                    0% { transform: translate3d(-20px, -12px, 0) scale(0.98); opacity: 0.68; }
                    50% { transform: translate3d(34px, 18px, 0) scale(1.03); opacity: 0.86; }
                    100% { transform: translate3d(-20px, -12px, 0) scale(0.98); opacity: 0.68; }
                }
                @keyframes loginAmbientDriftB {
                    0% { transform: translate3d(24px, 14px, 0) scale(1); opacity: 0.64; }
                    50% { transform: translate3d(-26px, -20px, 0) scale(1.04); opacity: 0.84; }
                    100% { transform: translate3d(24px, 14px, 0) scale(1); opacity: 0.64; }
                }
                @media (prefers-reduced-motion: reduce) {
                    .login-ambient { animation: none !important; }
                }
            `}</style>
        </div>
    );
};

export default Overview;
