import React, { useState, useEffect, useReducer, useRef } from 'react';
import { api } from '../hooks/api';
import toast from 'react-hot-toast';
import {
    Activity,
    Cpu,
    Zap,
    Globe,
    Clock,
    User,
    Shield,
    Terminal,
    Maximize2,
    Minimize2,
    Mic,
    MessageSquare,
    PlayCircle,
    ChevronLeft,
    ChevronRight,
    Database,
    ZapOff,
    MoreVertical,
    Layers,
    RefreshCw,
    Pin,
    X,
    Radio,
    Command,
    Image as ImageIcon,
    Cloud,
    BookOpen,
    MapPin,
    BarChart2
} from 'lucide-react';
import {
    WeatherAssistCard,
    SystemHealthAssistCard,
    WikiAssistCard,
    MapAssistCard,
    YouTubeAssistCard,
    DataChartAssistCard,
    hasWeatherCue,
    hasSystemHealthCue,
    hasWikipediaCue,
    hasMapCue,
    hasYouTubeCue,
    tryParseMarkdownTable
} from '../components/AssistCards';
import { useAssistCards } from '../hooks/useAssistCards';
import AtlasOrbCanvas from '../components/AtlasOrbCanvas';
import LinkPreviewCard from '../components/LinkPreviewCard';
import PlaybackCard from '../components/PlaybackCard';
// ============================================================================
// CONSTANTS (Strict AHIA v1)
// ============================================================================
const HERO_CONSTANTS = {
    MEDIA_FOCUS_DURATION_MS: 8000,
    MEDIA_EXPIRE_DURATION_MS: 180000,
    SURFACE_TRANSITION_MS: 150,
    HOVER_PAUSE_GRACE_MS: 300,
    MAX_POPUPS: 4,
    RADIUS: {
        INPUT: '5px',
        BUTTON: '8px',
        CARD: '12px',
        CONTAINER: '20px'
    }
};

// ============================================================================
// STATE MACHINE
// ============================================================================
const initialState = {
    immersive: true,
    leftExpanded: false,
    executionState: { isLive: false, status: '', message: '' },
    voiceState: { isActive: false, phrase: '', status: '' },
    textState: {
        input: '',
        history: [],
        sessionId: null,
        sessionName: '',
        isConnected: false,
        isSending: false
    },
    voiceMode: 'manual' // 'manual', 'live', 'keyword'
};

function dashboardReducer(state, action) {
    switch (action.type) {
        case 'SET_SESSION':
            return {
                ...state,
                textState: {
                    ...state.textState,
                    sessionId: action.payload.id || action.payload,
                    sessionName: action.payload.name || state.textState.sessionName
                }
            };
        case 'SET_CONNECTED':
            return { ...state, textState: { ...state.textState, isConnected: action.payload } };
        case 'UPDATE_EXECUTION':
            return { ...state, executionState: { ...state.executionState, ...action.payload } };
        case 'START_EXECUTION':
            return { ...state, executionState: { isLive: true, status: action.payload.status || 'running', message: action.payload.message || '' } };
        case 'END_EXECUTION':
            return { ...state, executionState: { isLive: false, status: '', message: '' } };
        case 'START_VOICE':
            if (state.executionState.isLive) return state;
            return {
                ...state,
                voiceState: { isActive: true, phrase: 'Listening...', status: 'waiting' }
            };
        case 'UPDATE_VOICE':
            return { ...state, voiceState: { ...state.voiceState, ...action.payload } };
        case 'END_VOICE':
            return {
                ...state,
                voiceState: { isActive: false, phrase: '', status: '' }
            };
        case 'TOGGLE_IMMERSIVE':
            return { ...state, immersive: !state.immersive };
        case 'TOGGLE_LEFT':
            return { ...state, leftExpanded: !state.leftExpanded };
        case 'SET_TEXT':
            return { ...state, textState: { ...state.textState, ...action.payload } };
        case 'SET_SENDING':
            return { ...state, textState: { ...state.textState, isSending: action.payload } };
        case 'ADD_MESSAGE': {
            const history = state.textState.history || [];
            if (action.payload.id && history.find(m => m.id === action.payload.id)) return state;
            return { ...state, textState: { ...state.textState, history: [...history, action.payload] } };
        }
        case 'SET_HISTORY':
            return { ...state, textState: { ...state.textState, history: action.payload } };
        case 'SET_VOICE_MODE':
            return { ...state, voiceMode: action.payload };
        default:
            return state;
    }
}

// ============================================================================
// HOOKS
// ============================================================================
// Helper to resolve local paths to API URLs (Phase 6.3)
const getFileUrl = (item, sessionId) => {
    if (!item) return null;
    if (item.url) return item.url;
    if (!sessionId) return null;

    const rawPath = item.path || item.file_path || item.filename || item.name;
    if (!rawPath) return null;
    const normalizedPath = String(rawPath).replace(/\\/g, '/');

    const diskSessionMatch = normalizedPath.match(/\/sessions\/([^/]+)\/(media|uploads)\/(.+)$/);
    if (diskSessionMatch) {
        const [, sourceSessionId, bucket, rest] = diskSessionMatch;
        return `/api/sessions/${sourceSessionId}/files/${bucket}/${rest}`;
    }

    if (normalizedPath.startsWith('/api/sessions/') && normalizedPath.includes('/files/')) return normalizedPath;

    if (normalizedPath.includes('/media/')) {
        const parts = normalizedPath.split('/media/');
        return `/api/sessions/${sessionId}/files/media/${parts[parts.length - 1]}`;
    }
    if (normalizedPath.includes('/uploads/')) {
        const parts = normalizedPath.split('/uploads/');
        return `/api/sessions/${sessionId}/files/uploads/${parts[parts.length - 1]}`;
    }
    if (normalizedPath.includes('data/')) return `/api/static/${normalizedPath.split('data/')[1]}`;

    // Absolute path fallback (agent produced)
    return `/api/sessions/${sessionId}/files/${normalizedPath.replace(/^\/+/, '')}`;
};

function useMediaStackManager() {
    const [mediaList, setMediaList] = useState([]);
    const [focusedMediaId, setFocusedMediaId] = useState(null);
    const timersRef = useRef(new Map());

    const clearMediaTimer = (id) => {
        if (timersRef.current.has(id)) {
            clearTimeout(timersRef.current.get(id));
            timersRef.current.delete(id);
        }
    };

    const addMedia = (itemPayload, type = 'IMAGE') => {
        const id = `media_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;

        // Prevent near-duplicate cards (same type and content/payload within short window)
        // This addresses the user's "various cards coming from same work id" issue
        const isDuplicateSnippet = (payload) => {
            if (!payload) return false;
            // Check for explicit work_id or unique markers in content
            const content = payload.content || payload.code || payload.url || JSON.stringify(payload);
            const workId = payload.work_id;

            return mediaList.some(m => {
                if (workId && m.payload?.work_id === workId) return true;
                const mContent = m.payload?.content || m.payload?.code || m.payload?.url || JSON.stringify(m.payload);
                return m.type === type && mContent === content && (Date.now() - m.createdAt < 8000);
            });
        };

        if (isDuplicateSnippet(itemPayload)) return null;

        const newItem = {
            id, type, createdAt: Date.now(), status: 'focused', payload: itemPayload,
            expiresAt: Date.now() + HERO_CONSTANTS.MEDIA_EXPIRE_DURATION_MS,
            remainingTime: HERO_CONSTANTS.MEDIA_EXPIRE_DURATION_MS,
            isPinned: false
        };

        setMediaList(prev => {
            // Dock currently focused item
            const updated = prev.map(m => m.status === 'focused' ? { ...m, status: 'docked' } : m);

            // MAX_POPUPS Eviction (apply to docked items)
            const active = updated.filter(m => m.status !== 'expired');
            if (active.length >= HERO_CONSTANTS.MAX_POPUPS) {
                const nonPinned = active.filter(m => !m.isPinned);
                if (nonPinned.length > 0) {
                    const oldestId = nonPinned[0].id;
                    return [...active.filter(m => m.id !== oldestId), newItem];
                }
            }
            return [...active, newItem];
        });

        setFocusedMediaId(id);
        clearMediaTimer(`${id}_focus`);
        const t = setTimeout(() => dockMedia(id), HERO_CONSTANTS.MEDIA_FOCUS_DURATION_MS);
        timersRef.current.set(`${id}_focus`, t);
        return id;
    };

    const dockMedia = (id) => {
        clearMediaTimer(`${id}_focus`);
        setFocusedMediaId(prev => (prev === id ? null : prev));
        setMediaList(prev => prev.map(m => {
            if (m.id === id) {
                const rem = Math.max(0, (m.expiresAt || (Date.now() + HERO_CONSTANTS.MEDIA_EXPIRE_DURATION_MS)) - Date.now());
                clearMediaTimer(`${id}_expire`);
                const t = setTimeout(() => removeMedia(id), rem);
                timersRef.current.set(`${id}_expire`, t);
                return { ...m, status: 'docked', remainingTime: rem, expiresAt: Date.now() + rem };
            }
            return m;
        }));
    };

    const pauseMediaExpiry = (id) => {
        clearMediaTimer(`${id}_expire`);
    };

    const resumeMediaExpiry = (id) => {
        setMediaList(prev => prev.map(m => {
            if (m.id === id && !m.isPinned && m.status === 'docked') {
                clearMediaTimer(`${id}_expire`);
                const t = setTimeout(() => removeMedia(id), m.remainingTime);
                timersRef.current.set(`${id}_expire`, t);
                return { ...m, expiresAt: Date.now() + m.remainingTime };
            }
            return m;
        }));
    };

    const togglePinMedia = (id) => {
        setMediaList(prev => prev.map(m => {
            if (m.id === id) {
                const nextPinned = !m.isPinned;
                clearMediaTimer(`${id}_expire`);
                if (!nextPinned) {
                    const t = setTimeout(() => removeMedia(id), m.remainingTime);
                    timersRef.current.set(`${id}_expire`, t);
                }
                return { ...m, isPinned: nextPinned, expiresAt: nextPinned ? null : Date.now() + m.remainingTime };
            }
            return m;
        }));
    };

    const focusMedia = (id) => {
        clearMediaTimer(`${id}_expire`);
        setFocusedMediaId(id);
        setMediaList(prev => prev.map(m => ({
            ...m,
            status: m.id === id ? 'focused' : (m.status === 'focused' ? 'docked' : m.status)
        })));
    };

    const removeMedia = (id) => {
        clearMediaTimer(`${id}_focus`); clearMediaTimer(`${id}_expire`);
        setFocusedMediaId(prev => (prev === id ? null : prev));
        setMediaList(prev => prev.filter(m => m.id !== id));
    };

    useEffect(() => () => {
        timersRef.current.forEach(t => clearTimeout(t));
        timersRef.current.clear();
    }, []);

    return {
        mediaList,
        focusedMediaId,
        mediaState: {
            focusedMediaId,
            focusedItem: mediaList.find(m => m.id === focusedMediaId),
            popups: mediaList.filter(m => m.status === 'docked')
        },
        addMedia, focusMedia, dockMedia, removeMedia,
        pauseMediaExpiry, resumeMediaExpiry, togglePinMedia
    };
}

// ============================================================================
// COMPONENTS
// ============================================================================

// ============================================================================
// NEW COMPONENTS (Phase 7 - Immersive)
// ============================================================================

// OBSOLETE - Replaced by AtlasOrbCanvas but kept minimal so compilation doesn't fail if referenced elsewhere
const VoiceOrb = ({ state }) => {
    return null;
};

const HeroTranscriptRenderer = ({ history, isSending, executionStatus }) => {
    const scrollRef = useRef(null);
    useEffect(() => {
        if (scrollRef.current) scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }, [history, isSending]);

    // Keep only last 12 turns
    const displayHistory = history.slice(-12);

    const renderContent = (content) => {
        // Minimal MD support: emphasis and links
        return content
            .replace(/\*\*(.*?)\*\*/g, '<b style="color:var(--text-primary)">$1</b>')
            .replace(/\*(.*?)\*/g, '<i>$1</i>')
            .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" style="color:var(--accent-color);text-decoration:underline">$1</a>');
    };

    return (
        <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div ref={scrollRef} className="hide-scrollbar" style={{
                width: '100%', height: '80px', overflowY: 'auto', padding: '10px var(--space-6) 0 var(--space-6)',
                display: 'flex', flexDirection: 'column', gap: '4px',
                fontFamily: "'Fira Code', monospace", fontSize: '11px', lineHeight: '1.4',
                opacity: 0.85,
                maskImage: 'linear-gradient(to bottom, transparent 0%, black 60%)',
                WebkitMaskImage: 'linear-gradient(to bottom, transparent 0%, black 60%)'
            }}>
                {displayHistory.map((msg, i) => {
                    const isAtlas = msg.role === 'atlas' || msg.role === 'assistant';
                    // DASHBOARD HUD PURITY RULES:
                    // 1. Strip all JSON/Objects { ... }
                    // 2. Strip all tool/kernel internal markers [TOOL_X], etc.
                    // 3. Strip all filesystem paths (e.g., /home/lucas/...)
                    // 4. Strip long code blocks (already handled but reinforced)
                    const rawContent = msg.content;
                    const cleanContent = rawContent
                        .replace(/\{[\s\S]*?\}/g, '') // Strip JSON blobs
                        .replace(/\[[A-Z_]+(:.*?)?\]/g, '') // Strip [TOOL_CALL], [KERNEL_IDLE]
                        .replace(/\/[a-zA-Z0-9\._\- \/]*\/[a-zA-Z0-9\._\- \/]*/g, '[RESOURCE]') // Strip file paths
                        .replace(/```[\s\S]*?```/g, '[CODE_BLOCK]')
                        .replace(/^#+.*$/gm, '')
                        .replace(/!\[.*?\]\(.*?\)/g, '[MEDIA]')
                        .trim();

                    const pureLabels = cleanContent.match(/^(\[RESOURCE\]|\[CODE_BLOCK\]|\[MEDIA\])+$/);
                    // Ultra-Aggressive HUD Purity (Phase 6.5)
                    const isRichAnnouncement = (cleanContent.length < 180 && (
                        cleanContent.includes('[RESOURCE]') ||
                        cleanContent.includes('[MEDIA]') ||
                        cleanContent.includes('[CODE_BLOCK]') ||
                        cleanContent.toLowerCase().includes('capturing') ||
                        cleanContent.toLowerCase().includes('please wait') ||
                        cleanContent.toLowerCase().includes('attachment')
                    )) || (
                            cleanContent.toLowerCase().includes('capturando a tela') ||
                            cleanContent.toLowerCase().includes('aguarde um momento')
                        );

                    if (!cleanContent || pureLabels || isRichAnnouncement) return null;

                    return (
                        <div key={i} style={{ display: 'flex', gap: '8px', marginBottom: '4px' }}>
                            <span style={{
                                color: isAtlas ? 'var(--accent-color)' : 'var(--text-secondary)',
                                fontWeight: '900', flexShrink: 0
                            }}>
                                {isAtlas ? 'ATLAS &gt;' : 'USER &gt;'}
                            </span>
                            <span
                                style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}
                                dangerouslySetInnerHTML={{ __html: renderContent(cleanContent) }}
                            />
                        </div>
                    );
                })}
                {(isSending || ['thinking', 'executing', 'responding'].includes(executionStatus)) && (
                    <div style={{ display: 'flex', gap: '8px', opacity: 0.5 }}>
                        <span style={{ color: 'var(--accent-color)', fontWeight: '900' }}>ATLAS &gt;</span>
                        <span className="pulse-slow">THINKING...</span>
                    </div>
                )}
            </div></div>
    );
};

const OverlayPopupStack = ({ popups, onFocus, onClose, onPause, onResume, onPin, sessionId }) => {
    if (popups.length === 0) return null;

    return (
        <div style={{
            position: 'absolute', top: '16px', right: '16px', zIndex: 100,
            display: 'flex', flexDirection: 'column-reverse', gap: '8px', pointerEvents: 'none'
        }}>
            {popups.map(item => (
                <div
                    key={item.id}
                    onMouseEnter={() => onPause(item.id)}
                    onMouseLeave={() => onResume(item.id)}
                    className="glass"
                    style={{
                        width: '240px', padding: '10px', borderRadius: HERO_CONSTANTS.RADIUS.CARD,
                        border: '1px solid var(--card-border)', boxShadow: 'var(--shadow-lg)',
                        pointerEvents: 'auto', display: 'flex', gap: '10px', alignItems: 'center',
                        animation: 'slideInRight 0.3s cubic-bezier(0.19, 1, 0.22, 1)',
                        position: 'relative', overflow: 'hidden'
                    }}
                >
                    {/* Expiry Progress Bar */}
                    {!item.isPinned && (
                        <div style={{
                            position: 'absolute', bottom: 0, left: 0, height: '2px', background: 'var(--accent-color)',
                            width: `${(item.remainingTime / HERO_CONSTANTS.MEDIA_EXPIRE_DURATION_MS) * 100}%`,
                            transition: 'width 0.1s linear'
                        }} />
                    )}

                    <div style={{ width: '40px', height: '40px', borderRadius: '4px', overflow: 'hidden', flexShrink: 0, background: 'var(--bg-color)' }}>
                        {item.type === 'IMAGE' ? (
                            <img src={getFileUrl(item.payload, sessionId)} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        ) : item.type === 'YOUTUBE' ? (
                            <div className="flex-center" style={{ height: '100%', background: '#f00' }}><PlayCircle size={20} color="#fff" /></div>
                        ) : item.type === 'CODE' ? (
                            <div className="flex-center" style={{ height: '100%' }}><Terminal size={20} color="var(--accent-color)" /></div>
                        ) : item.type === 'PLAYBACK' ? (
                            <div className="flex-center" style={{ height: '100%', background: 'rgba(var(--accent-rgb), 0.1)' }}><Activity size={20} color="var(--accent-color)" /></div>
                        ) : item.type === 'WEATHER' ? (
                            <div className="flex-center" style={{ height: '100%', background: 'rgba(var(--accent-rgb), 0.1)' }}><Cloud size={20} color="var(--accent-color)" /></div>
                        ) : item.type === 'SYSTEM_HEALTH' ? (
                            <div className="flex-center" style={{ height: '100%', background: 'rgba(var(--accent-rgb), 0.1)' }}><Cpu size={20} color="var(--accent-color)" /></div>
                        ) : item.type === 'WIKI' ? (
                            <div className="flex-center" style={{ height: '100%', background: 'rgba(var(--accent-rgb), 0.1)' }}><BookOpen size={20} color="var(--accent-color)" /></div>
                        ) : item.type === 'MAP' ? (
                            <div className="flex-center" style={{ height: '100%', background: 'rgba(var(--accent-rgb), 0.1)' }}><MapPin size={20} color="var(--accent-color)" /></div>
                        ) : item.type === 'CHART' ? (
                            <div className="flex-center" style={{ height: '100%', background: 'rgba(var(--accent-rgb), 0.1)' }}><BarChart2 size={20} color="var(--accent-color)" /></div>
                        ) : (
                            <div className="flex-center" style={{ height: '100%', position: 'relative' }}>
                                {item.payload?.url ? (
                                    <>
                                        <Globe size={20} color="var(--accent-color)" style={{ position: 'absolute' }} />
                                        <img
                                            src={`/api/favicon?url=${encodeURIComponent(item.payload.url)}`}
                                            alt=""
                                            style={{ width: '100%', height: '100%', objectFit: 'cover', position: 'absolute', inset: 0, zIndex: 1 }}
                                            onError={(e) => { e.currentTarget.style.display = 'none'; }}
                                        />
                                    </>
                                ) : (
                                    <Globe size={20} color="var(--accent-color)" />
                                )}
                            </div>
                        )}
                    </div>

                    <div style={{ flex: 1, minWidth: 0 }}>
                        <p style={{ fontSize: '11px', fontWeight: '800', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {item.payload?.title || (
                                item.type === 'WEATHER' ? 'Weather Info' :
                                    item.type === 'SYSTEM_HEALTH' ? 'System Health' :
                                        item.type === 'WIKI' ? 'Wiki Insight' :
                                            item.type === 'MAP' ? 'Location Map' :
                                                item.type === 'CHART' ? 'Data Analytics' :
                                                    'System Asset'
                            )}
                        </p>
                        <p style={{ fontSize: '9px', color: 'var(--text-muted)', margin: '2px 0 0 0', textTransform: 'uppercase' }}>
                            {item.type} • {item.isPinned ? 'PINNED' : `${Math.ceil(item.remainingTime / 1000)}s`}
                        </p>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        <button onClick={() => onPin(item.id)} className="btn-ghost" style={{ padding: '4px', color: item.isPinned ? 'var(--accent-color)' : 'var(--text-muted)' }}><Pin size={12} /></button>
                        <button onClick={() => onFocus(item.id)} className="btn-ghost" style={{ padding: '4px' }}><Maximize2 size={12} /></button>
                        {item.payload?.url && <a href={item.payload.url} target="_blank" rel="noreferrer" className="btn-ghost" style={{ padding: '4px', display: 'flex' }}><Globe size={12} /></a>}
                        <button onClick={() => onClose(item.id)} className="btn-ghost" style={{ padding: '4px' }}><X size={12} /></button>
                    </div>
                </div>
            ))}
        </div>
    );
};

const StageOrbLayer = ({ state }) => {
    const orbRef = useRef(null);

    // Only render actual Orb visuals if active or in live mode
    const isOrbActive = state.voiceState.isActive || state.executionState.isLive || state.voiceMode === 'live';

    useEffect(() => {
        if (!orbRef.current) return;

        // Determine the semantic state to pass to the Canvas Orb
        let targetState = 'idle';
        let pulseForce = 0;

        if (state.executionState.isLive) {
            targetState = 'speaking';
            pulseForce = 0.95; // Speaking start burst
        } else if (state.voiceState.status === 'processing' || state.executionState.status === 'thinking') {
            targetState = 'thinking';
        } else if (state.voiceState.isActive || state.voiceMode === 'live') {
            targetState = 'listening';
        }

        // Apply state
        orbRef.current.setState(targetState);

        // Optional: Pulse if transition is sudden
        if (state.executionState.isLive && state.executionState.status !== 'speaking') {
            orbRef.current.pulse({ score: pulseForce, ms: 200 });
        }

    }, [state.voiceState.status, state.voiceState.isActive, state.executionState.status, state.executionState.isLive, state.voiceMode]);

    return (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '20px', opacity: isOrbActive ? 1 : 0.1, transition: 'opacity 0.5s', width: '100%', height: '100%', position: 'relative' }}>
            {isOrbActive ? <AtlasOrbCanvas ref={orbRef} /> : <Terminal size={48} color="var(--accent-color)" />}

            {state.executionState.isLive && (
                <div className="flex-center" style={{
                    padding: '4px 12px', borderRadius: '100px',
                    background: 'rgba(var(--accent-rgb), 0.1)',
                    border: '1px solid var(--accent-color)',
                    fontSize: '10px', color: 'var(--accent-color)',
                    fontWeight: 'bold', letterSpacing: '0.1em',
                    animation: 'fadeIn 0.5s ease-out',
                    position: 'absolute', bottom: '20px', zIndex: 20
                }}>
                    {state.executionState.status?.toUpperCase() || 'CORE_ACTIVE'}
                </div>
            )}
        </div>
    );
};

const StageAssistCard = ({ type, payload, sessionId }) => {
    const {
        weatherCardData, weatherCardLoading,
        systemHealthData, systemHealthLoading,
        wikiCardData, mapCardData, youtubeCardData, parsedDataChart
    } = useAssistCards(sessionId, payload.content || '');

    if (type === 'WEATHER') {
        if (weatherCardLoading && !weatherCardData) return <div className="flex-center" style={{ height: '200px', color: 'var(--accent-color)' }}>Loading Weather Data...</div>;
        return <div style={{ width: '100%', maxWidth: '800px' }}><WeatherAssistCard data={weatherCardData} isStage={true} /></div>;
    }
    if (type === 'SYSTEM_HEALTH') {
        if (systemHealthLoading && !systemHealthData) return <div className="flex-center" style={{ height: '200px', color: 'var(--accent-color)' }}>Loading System Health...</div>;
        return <div style={{ width: '100%', maxWidth: '900px' }}><SystemHealthAssistCard data={systemHealthData} isStage={true} /></div>;
    }
    if (type === 'WIKI') return <div style={{ width: '100%', maxWidth: '800px' }}><WikiAssistCard data={wikiCardData} isStage={true} /></div>;
    if (type === 'MAP') return <div style={{ width: '100%', height: '100%', minHeight: '60vh' }}><MapAssistCard data={mapCardData} isStage={true} /></div>;
    if (type === 'CHART') return <div style={{ width: '100%', maxWidth: '1000px' }}><DataChartAssistCard chart={parsedDataChart || tryParseMarkdownTable(payload.content)} isStage={true} /></div>;

    return null;
};

const StageMediaLayer = ({ mediaState, onDockMedia, sessionId }) => {
    if (mediaState.focusedMediaId == null) return null;

    const item = mediaState.focusedItem;
    return (
        <div style={{
            width: '100%', height: '100%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            position: 'absolute', inset: 0, padding: 0, pointerEvents: 'none',
            animation: 'scaleUp 0.3s cubic-bezier(0.19, 1, 0.22, 1)', zIndex: 10
        }}>
            {/* Media Area (Stage Center) */}
            <div style={{
                flex: 1, width: '100%', display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', position: 'relative',
                padding: '100px 0 60px 0', zIndex: 10
            }}>
                {/* HUD Connector Line - Extended to top and bottom */}
                <div style={{
                    position: 'absolute', top: '-20px', left: '50%', transform: 'translateX(-50%)',
                    width: '1px', height: 'calc(100% + 40px)',
                    background: 'linear-gradient(to bottom, var(--accent-color) 0%, transparent 30%, transparent 70%, var(--accent-color) 100%)',
                    opacity: 0.25, pointerEvents: 'none', zIndex: -1
                }} />

                {/* Auto-Sizing Wrapper for Media + Button */}
                <div style={{
                    position: 'relative', display: 'flex', pointerEvents: 'auto',
                    width: (item?.type === 'LINK' || item?.type === 'CODE') ? 'auto' : '100%',
                    maxWidth: (item?.type === 'LINK' || item?.type === 'CODE') ? '80%' : '80%',
                    height: item?.type === 'LINK' ? 'auto' : '100%',
                    maxHeight: '45%',
                    aspectRatio: item?.type === 'YOUTUBE' ? '16/9' : 'auto'
                }}>

                    {/* HUD Brackets (Corner Decorations) */}
                    <div style={{ position: 'absolute', top: '-6px', left: '-6px', width: '12px', height: '12px', borderTop: '2px solid var(--accent-color)', borderLeft: '2px solid var(--accent-color)', opacity: 0.6, pointerEvents: 'none' }} />
                    <div style={{ position: 'absolute', top: '-6px', right: '-6px', width: '12px', height: '12px', borderTop: '2px solid var(--accent-color)', borderRight: '2px solid var(--accent-color)', opacity: 0.6, pointerEvents: 'none' }} />
                    <div style={{ position: 'absolute', bottom: '-6px', left: '-6px', width: '12px', height: '12px', borderBottom: '2px solid var(--accent-color)', borderLeft: '2px solid var(--accent-color)', opacity: 0.6, pointerEvents: 'none' }} />
                    <div style={{ position: 'absolute', bottom: '-6px', right: '-6px', width: '12px', height: '12px', borderBottom: '2px solid var(--accent-color)', borderRight: '2px solid var(--accent-color)', opacity: 0.6, pointerEvents: 'none' }} />

                    {/* Media Container (Intelligent Sizing based on Type) */}
                    <div style={{
                        borderRadius: HERO_CONSTANTS.RADIUS.CARD,
                        overflow: 'visible',
                        background: 'transparent',
                        border: item?.type === 'LINK' ? 'none' : '1px solid var(--card-border)',
                        boxShadow: item?.type === 'LINK' ? 'none' : '0 30px 60px rgba(0,0,0,0.4)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        width: '100%', height: '100%'
                    }}>
                        {item?.type === 'IMAGE' ? (
                            <img
                                src={getFileUrl(item.payload, sessionId)}
                                alt=""
                                style={{ maxWidth: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
                            />
                        ) : item?.type === 'YOUTUBE' ? (
                            <div style={{ width: 'auto', height: '100%', aspectRatio: '16/9' }}>
                                <iframe
                                    width="100%" height="100%"
                                    src={`https://www.youtube.com/embed/${item.payload.videoId}?autoplay=1`}
                                    title="YouTube player" frameBorder="0"
                                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                                    allowFullScreen
                                />
                            </div>
                        ) : ['WEATHER', 'SYSTEM_HEALTH', 'WIKI', 'MAP', 'CHART'].includes(item?.type) ? (
                            <div className="custom-scrollbar" style={{ width: '100%', height: '100%', padding: '20px', overflow: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                <StageAssistCard type={item.type} payload={item.payload} sessionId={sessionId} />
                            </div>
                        ) : item?.type === 'CODE' ? (
                            <div className="custom-scrollbar" style={{ maxWidth: '100%', height: '100%', padding: '24px', color: '#0f0', fontFamily: "'Fira Code', monospace", fontSize: '12px', overflow: 'auto', textAlign: 'left' }}>
                                <pre style={{ margin: 0 }}>{item.payload.code}</pre>
                            </div>
                        ) : item?.type === 'PLAYBACK' ? (
                            <div style={{ width: '100%', height: '100%', padding: '20px', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'auto' }}>
                                <PlaybackCard runId={item.payload.runId} sessionId={sessionId} />
                            </div>
                        ) : item?.type === 'LINK' ? (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%' }}>
                                <LinkPreviewCard messageContent={item.payload.fullContent || item.payload.url} isStage={true} />
                            </div>
                        ) : (
                            <div className="flex-center" style={{ padding: '40px', flexDirection: 'column', gap: '12px', height: '100%' }}>
                                <Globe size={48} color="var(--accent-color)" opacity={0.5} />
                                <span style={{ fontSize: '12px', fontWeight: '800', color: '#fff' }}>{item?.payload?.title || 'Resource Active'}</span>
                                {item?.payload?.url && <a href={item.payload.url} target="_blank" rel="noreferrer" style={{ fontSize: '10px', color: 'var(--accent-color)', textDecoration: 'underline' }}>OPEN_LINK</a>}
                            </div>
                        )}
                    </div>
                </div>

                {/* Close Button - Moved closer and styled more integrally */}
                <button
                    onClick={() => onDockMedia(mediaState.focusedMediaId)}
                    className="glass flex-center"
                    style={{
                        position: 'absolute', top: '-12px', right: '-12px',
                        width: '32px', height: '32px', borderRadius: '50%',
                        background: 'var(--accent-color)', color: '#fff',
                        border: '2px solid #000', cursor: 'pointer', zIndex: 100,
                        boxShadow: '0 4px 12px rgba(0,0,0,0.5)', transition: 'transform 0.2s'
                    }}
                    onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.1)'}
                    onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
                >
                    <X size={14} strokeWidth={3} />
                </button>
            </div>
        </div>
    );
};
// ============================================================================
// DASHBOARD
// ============================================================================
const Dashboard = () => {
    const [state, dispatch] = useReducer(dashboardReducer, initialState);
    const msm = useMediaStackManager();
    const msmRef = useRef(msm);
    useEffect(() => { msmRef.current = msm; }, [msm]);

    const [sys, setSys] = useState({ status: null, works: [] });
    const wsRef = useRef(null);
    const msmAddRef = useRef(msm.addMedia);
    useEffect(() => { msmAddRef.current = msm.addMedia; }, [msm.addMedia]);

    // Initial Session Load & System Poller
    useEffect(() => {
        const init = async () => {
            try {
                // 1. Try localStorage first
                let activeId = localStorage.getItem('dash_session_id');

                // 2. If not in localStorage, check server for active 'dash' session
                if (!activeId) {
                    const activeData = await api.get('/sessions/active?interface=web');
                    if (activeData && activeData.id) {
                        activeId = activeData.id;
                    }
                }

                if (activeId) {
                    localStorage.setItem('dash_session_id', activeId);
                    const historyData = await api.get(`/sessions/${activeId}`);
                    if (historyData) {
                        dispatch({ type: 'SET_SESSION', payload: { id: activeId, name: historyData.name } });
                        if (historyData.history) {
                            dispatch({ type: 'SET_HISTORY', payload: historyData.history });
                        }
                    }
                }
            } catch (err) {
                console.error("Dashboard session init error:", err);
            }
        };

        const fetchMetrics = async () => {
            try {
                const [status, works] = await Promise.all([
                    api.get('/status'),
                    api.get('/tasks/works')
                ]);
                setSys({ status, works: works || [] });
            } catch (err) { /* silent fail */ }
        };

        init();
        fetchMetrics();
        const t = setInterval(fetchMetrics, 5000);
        return () => clearInterval(t);
    }, []);

    // WebSocket Connection
    useEffect(() => {
        const sessionId = state.textState.sessionId;
        if (!sessionId) return;

        if (wsRef.current) wsRef.current.close();

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.hostname}:8000/ws/${sessionId}`;
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            dispatch({ type: 'SET_CONNECTED', payload: true });
            toast.success("Assistant Link Active", { id: 'dashboard-ws' });
        };

        ws.onclose = () => dispatch({ type: 'SET_CONNECTED', payload: false });

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'pong') return;

                if (data.type === 'status') {
                    const phase = String(data.payload?.status || data.phase || '').toLowerCase();
                    const isTerminal = ['complete', 'idle', 'succeeded', 'failed'].includes(phase);
                    const isExecuting = !isTerminal && (['running', 'thinking', 'executing', 'tool_use', 'responding'].includes(phase) || !!data.payload?.work_id);

                    if (isExecuting) {
                        dispatch({ type: 'START_EXECUTION', payload: { status: phase, message: data.message } });
                    } else if (isTerminal) {
                        dispatch({ type: 'END_EXECUTION' });
                    }
                } else if (data.type === 'media') {
                    msmAddRef.current(data.payload, data.payload.media_type || 'IMAGE');
                } else if (data.type === 'playback' || data.type === 'terminal_update') {
                    dispatch({ type: 'START_EXECUTION', payload: { status: 'RUNTIME_ACTIVE' } });
                }

                if (data.type === 'message_added' && data.session_id === sessionId) {
                    if (data.message?.role !== 'system') {
                        dispatch({ type: 'ADD_MESSAGE', payload: data.message });

                        const content = data.message.content || '';

                        // 1. YouTube Detection (Synchronized with LinkPreviewCard)
                        const YOUTUBE_RE = /(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/)|youtu\.be\/|\[RESOURCE\]\?v=)([\w-]{11})/i;
                        const ytMatch = content.match(YOUTUBE_RE);
                        if (ytMatch && ytMatch[1].length === 11) {
                            msmRef.current.addMedia({ videoId: ytMatch[1], title: 'YouTube Video', url: content.match(/https?:\/\/[^\s]+/)?.[0] }, 'YOUTUBE');
                        }
                        // 2. Path / Resource Detection (e.g. screenshots from file system)
                        else if (content.match(/(\/[a-zA-Z0-9\._\- \/]+\.(png|jpg|jpeg|gif|webp|mp4|webm|pdf|zip|txt|csv|json))/i)) {
                            const pathMatch = content.match(/(\/[a-zA-Z0-9\._\- \/]+\.(png|jpg|jpeg|gif|webp|mp4|webm|pdf|zip|txt|csv|json))/i);
                            msmRef.current.addMedia({ path: pathMatch[0], title: pathMatch[0].split('/').pop() }, 'IMAGE');
                        }
                        // 3. Image URL Detection
                        else if (content.match(/\.(jpg|jpeg|png|gif|webp|svg)(\?.*)?$/i) || content.startsWith('IMAGE:')) {
                            const url = content.replace('IMAGE:', '').trim();
                            msmRef.current.addMedia(url, 'IMAGE');
                        }
                        // 4. Code Detection
                        else if (content.includes('```')) {
                            const codeMatch = content.match(/```(?:\w+)?\s*([\s\S]*?)```/);
                            if (codeMatch && codeMatch[1].trim()) {
                                msmRef.current.addMedia({ code: codeMatch[1].trim() }, 'CODE');
                            }
                        }
                        // 5. Assist Card Cues
                        else if (hasWeatherCue(content)) {
                            msmRef.current.addMedia({ content }, 'WEATHER');
                        }
                        else if (hasSystemHealthCue(content)) {
                            msmRef.current.addMedia({ content }, 'SYSTEM_HEALTH');
                        }
                        else if (hasWikipediaCue(content)) {
                            msmRef.current.addMedia({ content }, 'WIKI');
                        }
                        else if (hasMapCue(content)) {
                            msmRef.current.addMedia({ content }, 'MAP');
                        }
                        else if (tryParseMarkdownTable(content)) {
                            msmRef.current.addMedia({ content }, 'CHART');
                        }
                        // 6. Link Detection (Fallback)
                        else {
                            const urlMatch = content.match(/https?:\/\/[^\s]+/);
                            if (urlMatch) {
                                msmRef.current.addMedia({ url: urlMatch[0], fullContent: content }, 'LINK');
                            }
                        }
                    }
                }

                if (data.type === 'playback' || data.type?.startsWith('playback.')) {
                    if (data.payload?.type === 'image' || data.payload?.type === 'video') {
                        msmRef.current.addMedia(data.payload, data.payload.type.toUpperCase());
                    } else if (data.type === 'playback' && data.run_id) {
                        msmRef.current.addMedia({ runId: data.run_id, title: 'Session Playback' }, 'PLAYBACK');
                    }
                }
            } catch (e) {
                console.error("Dashboard WS Parse Error:", e);
            }
        };

        return () => ws.close();
    }, [state.textState.sessionId]);

    useEffect(() => {
        const fetch = async () => {
            try {
                const [s, w] = await Promise.all([api.get('/system/status'), api.get('/tasks/works?include_completed=false&limit=5')]);
                setSys({ status: s, works: Array.isArray(w) ? w : [] });
            } catch (err) { console.error(err); }
        };
        fetch(); const i = setInterval(fetch, 5000); return () => clearInterval(i);
    }, []);

    useEffect(() => {
        if (state.immersive) {
            const p = document.body.style.overflow; document.body.style.overflow = 'hidden';
            return () => { document.body.style.overflow = p; };
        }
    }, [state.immersive]);

    const handleSubmit = async (e) => {
        if (e) e.preventDefault();
        const input = state.textState.input.trim();
        if (!input || state.textState.isSending) return;

        let activeId = state.textState.sessionId;

        // Lazy creation
        const handleResetSession = async () => {
            try {
                const data = await api.post('/sessions', { interface: 'web' });
                dispatch({ type: 'SET_SESSION', payload: { id: data.id, name: data.name } });
                dispatch({ type: 'SET_HISTORY', payload: [] });
                localStorage.setItem('dash_session_id', data.id);
                toast.success("New Session Created");
            } catch (err) {
                toast.error("Failed to reset session");
            }
        };

        if (!activeId) {
            try {
                const data = await api.post('/sessions', { interface: 'web' });
                if (data && data.id) {
                    activeId = data.id;
                    dispatch({ type: 'SET_SESSION', payload: { id: activeId, name: data.name } });
                    localStorage.setItem('dash_session_id', activeId);
                } else return;
            } catch (err) {
                toast.error("Bridge failure");
                return;
            }
        }

        dispatch({ type: 'SET_SENDING', payload: true });
        dispatch({ type: 'SET_TEXT', payload: { input: '' } });

        const payload = {
            type: 'msg',
            content: input,
            timestamp: Date.now()
        };

        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(payload));
        } else {
            try {
                await api.post(`/sessions/${activeId}/message`, { message: input });
            } catch (err) {
                toast.error("Transmission failed");
            }
        }
        dispatch({ type: 'SET_SENDING', payload: false });
    };

    const handleReload = async () => {
        if (wsRef.current) wsRef.current.close();
        localStorage.removeItem('dash_session_id');
        dispatch({ type: 'SET_SESSION', payload: null });
        dispatch({ type: 'SET_HISTORY', payload: [] });
        dispatch({ type: 'SET_CONNECTED', payload: false });
        toast.loading("Provisioning new session...", { id: 'dash-reload', duration: 2000 });

        try {
            const data = await api.post('/sessions', { interface: 'web' });
            if (data && data.id) {
                dispatch({ type: 'SET_SESSION', payload: { id: data.id, name: data.name } });
                localStorage.setItem('dash_session_id', data.id);
                toast.success("New Session Ready", { id: 'dash-reload' });
            }
        } catch (err) {
            toast.error("Reload failed", { id: 'dash-reload' });
        }
    };

    const Metric = ({ label, value, icon: Icon }) => (
        <div style={{ padding: '12px', background: 'var(--accent-glow)', border: '1px solid var(--card-border)', borderRadius: HERO_CONSTANTS.RADIUS.CARD, backdropFilter: 'blur(10px)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                <Icon size={12} color="var(--accent-color)" />
                <span style={{ fontSize: '9px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
            </div>
            <div style={{ fontSize: '12px', fontWeight: '900', letterSpacing: '0.05em' }}>{value}</div>
        </div>
    );

    return (
        <div className="dashboard-root" style={{
            height: '100vh', display: 'flex', overflow: 'hidden', color: '#fff',
            background: 'radial-gradient(circle at center, rgba(40, 0, 80, 0.25) 0%, #050505 75%)',
            position: 'relative'
        }}>
            <style>{`
                @keyframes slideInRight {
                    from { transform: translateX(100%); opacity: 0; }
                    to { transform: translateX(0); opacity: 1; }
                }
                @keyframes slideUp {
                    from { transform: translateY(20px); opacity: 0; }
                    to { transform: translateY(0); opacity: 1; }
                }
                @keyframes scaleUp {
                    from { transform: scale(0.95); opacity: 0; }
                    to { transform: scale(1); opacity: 1; }
                }
                @keyframes fadeIn {
                    from { opacity: 0; }
                    to { opacity: 1; }
                }
                .pulse-slow { animation: pulse-slow 2s infinite ease-in-out; }
                .custom-scrollbar::-webkit-scrollbar { width: 4px; }
                .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
                .custom-scrollbar::-webkit-scrollbar-thumb { background: var(--card-border); border-radius: 10px; }
                .flex-center { display: flex; align-items: center; justify-content: center; }
                .glass { background: var(--card-bg); backdrop-filter: var(--surface-blur); -webkit-backdrop-filter: var(--surface-blur); }

                /* Voice Orb Styles */
                .voice-orb {
                    width: 150px; height: 150px; border-radius: 50%;
                    background: radial-gradient(circle at center, var(--accent-color) 0%, rgba(var(--accent-rgb), 0.5) 50%, transparent 100%);
                    position: absolute; display: flex; align-items: center; justify-content: center;
                    transition: all 0.5s ease-in-out;
                    box-shadow: 0 0 30px rgba(var(--accent-rgb), 0.6);
                }
                .voice-orb.orb-listening { animation: orb-pulse 1.5s infinite ease-in-out; }
                .voice-orb.orb-thinking { animation: orb-thinking 1.8s infinite ease-in-out; }
                .voice-orb.orb-speaking { animation: orb-speaking 1.2s infinite ease-in-out; }

                .orb-inner {
                    width: 80%; height: 80%; border-radius: 50%;
                    background: rgba(var(--accent-rgb), 0.15);
                    border: 1px solid rgba(255,255,255,0.1);
                }
                .hide-scrollbar {
                    -ms-overflow-style: none;
                    scrollbar-width: none;
                }
                .hide-scrollbar::-webkit-scrollbar {
                    display: none;
                }
                .orb-waves {
                    position: absolute; width: 100%; height: 100%; border-radius: 50%;
                    border: 2px solid rgba(var(--accent-rgb), 0.3);
                    animation: orb-wave 2s infinite ease-out;
                    opacity: 0;
                }
                .voice-orb.orb-listening .orb-waves { animation: orb-wave 2s infinite ease-out; }

                .orb-glow-purple, .orb-glow-indigo {
                    position: absolute; border-radius: 50%; opacity: 0;
                    transition: all 0.5s ease-in-out;
                }
                .orb-glow-purple { background: radial-gradient(circle, rgba(128, 0, 128, 0.6) 0%, transparent 70%); width: 200px; height: 200px; }
                .orb-glow-indigo { background: radial-gradient(circle, rgba(75, 0, 130, 0.6) 0%, transparent 70%); width: 220px; height: 220px; }

                .orb-glow-purple.orb-listening, .orb-glow-purple.orb-thinking, .orb-glow-purple.orb-speaking { opacity: 0.3; }
                .orb-glow-indigo.orb-listening, .orb-glow-indigo.orb-thinking, .orb-glow-indigo.orb-speaking { opacity: 0.2; }

                @keyframes orb-pulse {
                    0% { transform: scale(1); box-shadow: 0 0 30px rgba(var(--accent-rgb), 0.6); }
                    50% { transform: scale(1.05); box-shadow: 0 0 45px rgba(var(--accent-rgb), 0.8); }
                    100% { transform: scale(1); box-shadow: 0 0 30px rgba(var(--accent-rgb), 0.6); }
                }
                @keyframes orb-thinking {
                    0% { transform: rotate(0deg) scale(1); }
                    25% { transform: rotate(10deg) scale(1.02); }
                    50% { transform: rotate(0deg) scale(1); }
                    75% { transform: rotate(-10deg) scale(1.02); }
                    100% { transform: rotate(0deg) scale(1); }
                }
                @keyframes orb-speaking {
                    0% { transform: scale(1); }
                    20% { transform: scale(1.08); }
                    40% { transform: scale(1); }
                    60% { transform: scale(1.05); }
                    80% { transform: scale(1); }
                    100% { transform: scale(1.03); }
                }
                @keyframes orb-wave {
                    0% { transform: scale(0.7); opacity: 0.8; }
                    100% { transform: scale(1.2); opacity: 0; }
                }

                .status-pill {
                    position: absolute; padding: 6px 12px; border-radius: 20px;
                    background: rgba(0,0,0,0.6); border: 1px solid rgba(255,255,255,0.1);
                    font-size: 9px; font-weight: 800; letter-spacing: 0.1em;
                    display: flex; align-items: center; gap: 6px;
                    opacity: 0; transform: scale(0.8);
                    transition: all 0.3s ease-out;
                    color: var(--text-muted);
                }
                .status-pill.active { opacity: 1; transform: scale(1); color: var(--accent-color); }
                .status-pill.pill-top { top: -30px; }
                .status-pill.pill-right { right: -50px; }
                .status-pill.pill-bottom { bottom: -30px; }
            `}</style>

            {/* Dot Texture Overlay */}
            <div style={{
                position: 'absolute', inset: 0, opacity: 0.05, pointerEvents: 'none',
                backgroundImage: 'radial-gradient(var(--text-muted) 1px, transparent 0)',
                backgroundSize: '30px 30px'
            }} />

            {/* Main Stage */}
            <main style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column' }}>
                <header style={{
                    height: '60px', padding: '0 32px', display: 'flex', alignItems: 'center',
                    justifyContent: 'space-between', zIndex: 10
                }}>
                    <div className="flex-center" style={{ gap: '12px' }}>
                        <div style={{ color: 'var(--accent-color)', fontWeight: '900', letterSpacing: '0.1em', fontSize: '11px', textTransform: 'uppercase' }}>
                            A.T.L.A.S | {state.textState.sessionName || 'DASHBOARD_ACTIVE'}
                        </div>
                        <button onClick={handleReload} className="flex-center" style={{
                            width: '24px', height: '24px', borderRadius: '4px', background: 'transparent',
                            border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-muted)', cursor: 'pointer', transition: 'all 0.2s'
                        }} title="Reset Session">
                            <RefreshCw size={12} />
                        </button>
                    </div>
                </header>

                <div style={{ flex: 1, width: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>

                    {/* STAGE AREA (Top: Orb + Media Overlap) */}
                    <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                        {/* Background Layer (Orb / System State) */}
                        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1 }}>
                            <StageOrbLayer state={state} />
                        </div>

                        {/* Foreground Layer (Media / Focus) */}
                        <StageMediaLayer mediaState={msm.mediaState} onDockMedia={msm.dockMedia} sessionId={state.textState.sessionId} />

                        {/* Popups (Overlay) */}
                        <OverlayPopupStack
                            popups={msm.mediaState.popups}
                            onFocus={msm.focusMedia} onClose={msm.removeMedia}
                            onPause={msm.pauseMediaExpiry} onResume={msm.resumeMediaExpiry}
                            onPin={msm.togglePinMedia} sessionId={state.textState.sessionId}
                        />
                    </div>

                    {/* DIALOGUE AREA (Bottom: Transcript + Input) */}
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%', paddingBottom: '16px', zIndex: 20 }}>
                        {/* Minimal Transcript Layer */}
                        <div style={{ width: '100%', maxWidth: '800px', padding: '0 40px', pointerEvents: 'auto', marginBottom: '8px' }}>
                            <HeroTranscriptRenderer
                                history={state.textState.history}
                                isSending={state.textState.isSending}
                                executionStatus={state.executionState.status}
                            />
                        </div>
                        {/* Floating Interaction Area */}
                        <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 40px', gap: '16px' }}>
                            {/* Mode Toggles (Outside) */}
                            <div className="flex-center" style={{ gap: '8px' }}>
                                {/* Mode Toggle: Keyword */}
                                <button
                                    type="button"
                                    onClick={() => dispatch({ type: 'SET_VOICE_MODE', payload: state.voiceMode === 'keyword' ? 'manual' : 'keyword' })}
                                    className="flex-center glass"
                                    disabled={state.voiceMode === 'live'}
                                    style={{
                                        width: '42px', height: '42px', borderRadius: '14px',
                                        background: state.voiceMode === 'keyword' ? 'var(--accent-color)' : 'rgba(255,255,255,0.03)',
                                        border: '1px solid rgba(255,255,255,0.08)',
                                        color: state.voiceMode === 'keyword' ? '#000' : 'var(--text-muted)',
                                        cursor: state.voiceMode === 'live' ? 'not-allowed' : 'pointer',
                                        transition: 'all 0.2s', opacity: state.voiceMode === 'live' ? 0.3 : 1
                                    }}
                                    title="Keyword Mode (Hey Atlas)"
                                >
                                    <Command size={18} />
                                </button>

                                {/* Mode Toggle: Live Voice */}
                                <button
                                    type="button"
                                    onClick={() => dispatch({ type: 'SET_VOICE_MODE', payload: state.voiceMode === 'live' ? 'manual' : 'live' })}
                                    className="flex-center glass"
                                    disabled={state.voiceMode === 'keyword'}
                                    style={{
                                        width: '42px', height: '42px', borderRadius: '14px',
                                        background: state.voiceMode === 'live' ? 'var(--accent-color)' : 'rgba(255,255,255,0.03)',
                                        border: '1px solid rgba(255,255,255,0.08)',
                                        color: state.voiceMode === 'live' ? '#000' : 'var(--text-muted)',
                                        cursor: state.voiceMode === 'keyword' ? 'not-allowed' : 'pointer',
                                        transition: 'all 0.2s', opacity: state.voiceMode === 'keyword' ? 0.3 : 1
                                    }}
                                    title="Live Voice Mode"
                                >
                                    <Radio size={18} />
                                </button>
                            </div>

                            <div style={{
                                flex: state.voiceMode === 'live' ? '0 0 auto' : '1',
                                maxWidth: '800px',
                                display: 'flex',
                                justifyContent: 'center',
                                transition: 'all 0.3s cubic-bezier(0.19, 1, 0.22, 1)'
                            }}>
                                {state.voiceMode === 'live' ? (
                                    /* Collapsed Live Voice Bubble */
                                    <div
                                        className="glass pulse-slow"
                                        onClick={() => dispatch({ type: 'SET_VOICE_MODE', payload: 'manual' })}
                                        style={{
                                            width: '54px', height: '54px', borderRadius: '50%',
                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            border: '1px solid var(--accent-color)', cursor: 'pointer',
                                            color: 'var(--accent-color)', boxShadow: '0 0 20px rgba(var(--accent-rgb), 0.3)'
                                        }}
                                    >
                                        <MessageSquare size={24} />
                                    </div>
                                ) : (
                                    /* Standard Refined Input Bar */
                                    <div className="glass" style={{
                                        width: '100%', height: '54px', borderRadius: '27px',
                                        display: 'flex', alignItems: 'center', padding: '0 20px', gap: '16px',
                                        border: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(40px)',
                                        boxShadow: '0 10px 40px rgba(0,0,0,0.5)', transition: 'all 0.3s ease'
                                    }}>
                                        <div style={{ color: 'var(--accent-color)', opacity: 0.8 }}><Activity size={20} /></div>
                                        <form onSubmit={handleSubmit} style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
                                            <input
                                                value={state.textState.input}
                                                onChange={(e) => dispatch({ type: 'SET_TEXT', payload: { input: e.target.value } })}
                                                placeholder="Ask Atlas anything..."
                                                style={{
                                                    flex: 1, background: 'none', border: 'none', color: '#fff',
                                                    fontSize: '15px', outline: 'none', fontFamily: 'inherit'
                                                }}
                                            />
                                            <div className="flex-center" style={{ gap: '10px' }}>
                                                <div style={{ width: '1px', height: '20px', background: 'rgba(255,255,255,0.1)', margin: '0 4px' }} />
                                                <Terminal size={16} style={{ opacity: 0.4 }} />
                                                <button type="submit" className="flex-center" style={{
                                                    width: '36px', height: '36px', borderRadius: '10px',
                                                    background: 'var(--accent-color)', border: 'none', color: '#fff', cursor: 'pointer'
                                                }}>
                                                    <ChevronRight size={18} />
                                                </button>
                                            </div>
                                        </form>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>

                {/* Footer Padding */}
                <div style={{ height: '24px' }} />
            </main>
        </div>
    );
};

export default Dashboard;
