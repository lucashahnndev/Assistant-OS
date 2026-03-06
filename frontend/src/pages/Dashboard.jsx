import React, { useState, useEffect, useReducer, useRef, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useVoice } from '../hooks/useVoice';
import { useTheme } from '../context/ThemeContext';
import { api } from '../hooks/api';
import toast from 'react-hot-toast';
import {
    Activity,
    Copy,
    ExternalLink,
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
    Play,
    Pause,
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
    DataChartAssistCard,
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

const DASHBOARD_Z = {
    STAGE_CARD: 10900,
    POPUP_STACK: 10950,
    CARD_CONTROL: 10960,
    HUD: 10850,
    FULLSCREEN_TERMINAL: 11000,
};

// ============================================================================
// STATE MACHINE
// ============================================================================
const initialState = {
    immersive: true,
    leftExpanded: false,
    executionState: { isLive: false, status: '', message: '' },
    voiceState: { isActive: false, phrase: '', status: '', intensity: 0 },
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
                    sessionId: action.payload?.id || action.payload,
                    sessionName: action.payload?.name || state.textState.sessionName || ''
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
                voiceState: { isActive: false, phrase: '', status: '', intensity: 0 }
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

const DASHBOARD_URL_RE = /https?:\/\/[^\s<>)"'\]]+/gi;
const DASHBOARD_YOUTUBE_RE = /(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/)|youtu\.be\/|\[RESOURCE\]\?v=)([\w-]{11})/i;
const DASHBOARD_DEEZER_TRACK_RE = /(?:deezer\.com\/(?:[a-z]{2}\/)?track\/)(\d+)/i;

const extractUrlsFromText = (text) => {
    if (!text || typeof text !== 'string') return [];
    return [...new Set((text.match(DASHBOARD_URL_RE) || []))];
};

const extractYouTubeId = (value) => {
    if (!value || typeof value !== 'string') return null;
    const m = value.match(DASHBOARD_YOUTUBE_RE);
    return m ? m[1] : null;
};

const extractDeezerTrackId = (value) => {
    if (!value || typeof value !== 'string') return null;
    const m = value.match(DASHBOARD_DEEZER_TRACK_RE);
    return m ? String(m[1]) : null;
};

const parseDeezerMetaFromText = (text) => {
    const raw = String(text || '').trim();
    if (!raw) return { title: '', artist: '' };

    const matchPt = raw.match(/m[úu]sica:\s*(.+?)\s+por\s+(.+?)(?:\s+link|$)/i);
    if (matchPt) {
        return { title: String(matchPt[1] || '').trim(), artist: String(matchPt[2] || '').trim() };
    }
    const matchEn = raw.match(/track:\s*(.+?)\s+by\s+(.+?)(?:\s+link|$)/i);
    if (matchEn) {
        return { title: String(matchEn[1] || '').trim(), artist: String(matchEn[2] || '').trim() };
    }
    const ranked = raw.match(/(?:^|\n)\s*1\.\s*(.+?)\s*-\s*(.+?)(?:\s*\(|\s*URL:|$)/i);
    if (ranked) {
        return { title: String(ranked[1] || '').trim(), artist: String(ranked[2] || '').trim() };
    }
    return { title: '', artist: '' };
};

const resolveDeezerMeta = (payload) => {
    const p = (payload && typeof payload === 'object') ? payload : {};
    const firstResult = Array.isArray(p.results) && p.results.length > 0 && typeof p.results[0] === 'object' ? p.results[0] : {};
    const best = (p.best && typeof p.best === 'object') ? p.best : {};
    const fromText = parseDeezerMetaFromText(p.content || '');
    const title = String(
        p.trackTitle
        || p.title
        || best.title
        || firstResult.title
        || fromText.title
        || ''
    ).trim();
    const artist = String(
        p.trackArtist
        || p.artist
        || best.artist
        || firstResult.artist
        || fromText.artist
        || ''
    ).trim();
    return {
        title: /^deezer track$/i.test(title) ? (fromText.title || best.title || firstResult.title || '') : title,
        artist,
    };
};

const mediaSignatureFromItem = (item) => {
    const type = String(item?.type || '').toUpperCase();
    const payload = (item?.payload && typeof item.payload === 'object') ? item.payload : {};
    const safe = (v) => String(v || '').trim();
    if (!type) return '';
    if (type === 'YOUTUBE') return `YOUTUBE:${safe(payload.videoId || extractYouTubeId(safe(payload.url)) || payload.url)}`;
    if (type === 'DEEZER') return `DEEZER:${safe(payload.trackId || extractDeezerTrackId(safe(payload.url)) || payload.url)}`;
    if (type === 'PLAYBACK') return `PLAYBACK:${safe(payload.runId || payload.run_id)}`;
    if (type === 'TERMINAL') return `TERMINAL:${safe(payload.work_id || payload.id || payload.terminal_id || payload.command)}`;
    if (type === 'APPROVAL') return `APPROVAL:${safe(payload.work_id || payload.approval_key || payload.prompt)}`;
    if (type === 'IMAGE') return `IMAGE:${safe(payload.url || payload.path || payload.file_path || payload.filename)}`;
    if (type === 'LINK') return `LINK:${safe(payload.url || payload.fullContent)}`;
    if (['WEATHER', 'SYSTEM_HEALTH', 'WIKI', 'MAP', 'CHART', 'CODE'].includes(type)) {
        return `${type}:${safe(payload.work_id || payload.query || payload.title || payload.content).slice(0, 160)}`;
    }
    return `${type}:${safe(payload.work_id || payload.url || payload.title || payload.content).slice(0, 160)}`;
};

function useMediaStackManager(preferredStageSignatures = []) {
    const [mediaList, setMediaList] = useState([]);
    const [focusedMediaId, setFocusedMediaId] = useState(null);
    const [stageDismissedIds, setStageDismissedIds] = useState(() => new Set());
    const timersRef = useRef(new Map());

    const clearMediaTimer = (id) => {
        if (timersRef.current.has(id)) {
            clearTimeout(timersRef.current.get(id));
            timersRef.current.delete(id);
        }
    };

    const addMedia = (itemPayload, type = 'IMAGE') => {
        const id = `media_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
        const isPersistent = type === 'APPROVAL';

        // Prevent near-duplicate cards (same type and content/payload within short window)
        // This addresses the user's "various cards coming from same work id" issue
        const isDuplicateSnippet = (payload) => {
            if (isPersistent) return false;
            if (!payload) return false;
            // Check for explicit work_id or unique markers in content
            const content = payload.content || payload.code || payload.url || JSON.stringify(payload);
            const workId = payload.work_id;

            return mediaList.some(m => {
                if (workId && m.payload?.work_id === workId && m.type === type) return true;
                const mContent = m.payload?.content || m.payload?.code || m.payload?.url || JSON.stringify(m.payload);
                return m.type === type && mContent === content && (Date.now() - m.createdAt < 8000);
            });
        };

        if (isDuplicateSnippet(itemPayload)) return null;

        const newItem = {
            id, type, createdAt: Date.now(), status: 'focused', payload: itemPayload,
            expiresAt: isPersistent ? null : Date.now() + HERO_CONSTANTS.MEDIA_EXPIRE_DURATION_MS,
            remainingTime: isPersistent ? null : HERO_CONSTANTS.MEDIA_EXPIRE_DURATION_MS,
            isPinned: isPersistent
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
        setStageDismissedIds(prev => {
            const next = new Set(prev);
            next.delete(id);
            return next;
        });
        clearMediaTimer(`${id}_focus`);
        if (!isPersistent) {
            const t = setTimeout(() => dockMedia(id), HERO_CONSTANTS.MEDIA_FOCUS_DURATION_MS);
            timersRef.current.set(`${id}_focus`, t);
        }
        return id;
    };

    const dockMedia = (id) => {
        clearMediaTimer(`${id}_focus`);
        setFocusedMediaId(prev => (prev === id ? null : prev));
        setStageDismissedIds(prev => {
            const next = new Set(prev);
            next.add(id);
            return next;
        });
        setMediaList(prev => prev.map(m => {
            if (m.id === id) {
                if (m.isPinned) {
                    return { ...m, status: 'docked' };
                }
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

    const setMediaPinned = (id, pinned) => {
        const nextPinned = !!pinned;
        setMediaList(prev => prev.map(m => {
            if (m.id !== id) return m;
            clearMediaTimer(`${id}_expire`);
            if (!nextPinned && m.status === 'docked') {
                const rem = Math.max(0, m.remainingTime || HERO_CONSTANTS.MEDIA_EXPIRE_DURATION_MS);
                const t = setTimeout(() => removeMedia(id), rem);
                timersRef.current.set(`${id}_expire`, t);
                return { ...m, isPinned: false, expiresAt: Date.now() + rem };
            }
            return { ...m, isPinned: nextPinned, expiresAt: nextPinned ? null : m.expiresAt };
        }));
    };

    const focusMedia = (id) => {
        clearMediaTimer(`${id}_expire`);
        setFocusedMediaId(id);
        setStageDismissedIds(prev => {
            const next = new Set(prev);
            next.delete(id);
            return next;
        });
        setMediaList(prev => prev.map(m => ({
            ...m,
            status: m.id === id ? 'focused' : (m.status === 'focused' ? 'docked' : m.status)
        })));
    };

    const removeMedia = (id) => {
        clearMediaTimer(`${id}_focus`); clearMediaTimer(`${id}_expire`);
        setFocusedMediaId(prev => (prev === id ? null : prev));
        setStageDismissedIds(prev => {
            const next = new Set(prev);
            next.delete(id);
            return next;
        });
        setMediaList(prev => prev.filter(m => m.id !== id));
    };

    const patchMediaPayload = (id, payloadPatch) => {
        if (!id || !payloadPatch || typeof payloadPatch !== 'object') return;
        setMediaList(prev => prev.map(m => {
            if (m.id !== id) return m;
            return { ...m, payload: { ...(m.payload || {}), ...payloadPatch } };
        }));
    };

    useEffect(() => () => {
        timersRef.current.forEach(t => clearTimeout(t));
        timersRef.current.clear();
    }, []);

    const stageItems = useMemo(() => {
        const active = (Array.isArray(mediaList) ? mediaList : []).filter((m) => m && m.status !== 'expired' && !stageDismissedIds.has(m.id));
        if (active.length === 0) return [];
        const preferredIndex = new Map(
            (Array.isArray(preferredStageSignatures) ? preferredStageSignatures : [])
                .map((sig, idx) => [String(sig || ''), idx])
                .filter(([sig]) => !!sig)
        );

        const isCriticalRunning = (m) => {
            const type = String(m?.type || '');
            const statusNorm = String(m?.payload?.status || m?.payload?.terminal_status || '').toLowerCase();
            if (type === 'TERMINAL') return ['running', 'active', 'executing'].includes(statusNorm);
            if (type === 'PLAYBACK') return ['running', 'active', 'playback', 'playback.frame'].includes(statusNorm);
            return false;
        };

        const focused = active.find((m) => m.id === focusedMediaId) || null;
        const withPriorityMeta = active
            .map((m) => {
                const type = String(m?.type || '');
                const statusNorm = String(m?.payload?.status || m?.payload?.terminal_status || '').toLowerCase();
                const terminalRunning = type === 'TERMINAL' && ['running', 'active', 'executing'].includes(statusNorm);
                const playbackRunning = type === 'PLAYBACK' && ['running', 'active', 'playback', 'playback.frame'].includes(statusNorm);
                let score = 0;
                if (focused && m.id === focused.id) score += 1000;
                if (m?.isPinned) score += 40;
                if (type === 'APPROVAL') score += 60;
                if (terminalRunning) score += 55;
                if (playbackRunning) score += 52;
                if (type === 'TERMINAL') score += 25;
                if (type === 'PLAYBACK') score += 22;
                const sig = mediaSignatureFromItem(m);
                if (preferredIndex.has(sig)) {
                    const idx = preferredIndex.get(sig);
                    score += Math.max(1, 20 - Number(idx || 0));
                }
                score += Math.floor(Number(m?.createdAt || 0) / 1000); // recency tie-break
                return { m, score, criticalRunning: terminalRunning || playbackRunning };
            })
            .sort((a, b) => b.score - a.score);
        const withPriority = withPriorityMeta.map((x) => x.m);
        const scoreById = new Map(withPriorityMeta.map((x) => [x.m.id, x.score]));
        const criticalItems = withPriority.filter(isCriticalRunning);

        const uniqueTypes = new Set(withPriority.map((m) => String(m?.type || '')));
        let selected = uniqueTypes.size <= 1 ? withPriority.slice(0, 4) : (() => {
            const onePerType = [];
            const seen = new Set();
            for (const m of withPriority) {
                const t = String(m?.type || '');
                if (seen.has(t)) continue;
                seen.add(t);
                onePerType.push(m);
                if (onePerType.length >= 4) break;
            }
            return onePerType;
        })();

        // Hard rule: running TERMINAL/PLAYBACK must be present in stage (up to max 4).
        for (const critical of criticalItems) {
            if (selected.some((s) => s.id === critical.id)) continue;
            if (selected.length < 4) {
                selected.push(critical);
                continue;
            }
            let replaceIdx = -1;
            let lowestScore = Number.POSITIVE_INFINITY;
            for (let i = 0; i < selected.length; i += 1) {
                const candidate = selected[i];
                if (isCriticalRunning(candidate)) continue;
                const sc = Number(scoreById.get(candidate.id) || 0);
                if (sc < lowestScore) {
                    lowestScore = sc;
                    replaceIdx = i;
                }
            }
            if (replaceIdx >= 0) selected[replaceIdx] = critical;
        }
        selected = [...selected].sort((a, b) => Number(scoreById.get(b.id) || 0) - Number(scoreById.get(a.id) || 0)).slice(0, 4);
        return selected;
    }, [mediaList, focusedMediaId, preferredStageSignatures, stageDismissedIds]);

    const stageItemIds = new Set(stageItems.map((m) => m.id));

    return {
        mediaList,
        focusedMediaId,
        mediaState: {
            focusedMediaId,
            focusedItem: mediaList.find(m => m.id === focusedMediaId),
            stageItems,
            popups: mediaList.filter(m => m.status === 'docked' && !stageItemIds.has(m.id))
        },
        addMedia, focusMedia, dockMedia, removeMedia, patchMediaPayload,
        pauseMediaExpiry, resumeMediaExpiry, togglePinMedia, setMediaPinned
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
                                {isAtlas ? 'ATLAS >' : 'USER >'}
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
        <div
            className="hide-scrollbar"
            style={{
                position: 'fixed', top: '76px', right: '16px',
                zIndex: DASHBOARD_Z.POPUP_STACK,
                maxHeight: 'calc(100vh - 160px)',
                overflowY: 'auto',
                pointerEvents: 'none',
                display: 'flex',
                flexDirection: 'column-reverse',
                gap: '8px',
                paddingBottom: '60px', /* Extra space to ensure the last item can be seen through the fade */
                maskImage: 'linear-gradient(to bottom, black 80%, transparent)',
                WebkitMaskImage: 'linear-gradient(to bottom, black 80%, transparent)'
            }}
        >
            {popups.map(item => {
                const ytId = extractYouTubeId(String(item?.payload?.videoId || '')) || extractYouTubeId(String(item?.payload?.url || '')) || '';
                const deezerId = extractDeezerTrackId(String(item?.payload?.trackId || ''))
                    || extractDeezerTrackId(String(item?.payload?.url || ''))
                    || String(item?.payload?.trackId || '')
                    || '';
                const popupThumbUrl = item.type === 'YOUTUBE'
                    ? (ytId ? `https://img.youtube.com/vi/${ytId}/mqdefault.jpg` : '')
                    : item.type === 'DEEZER'
                        ? String(item?.payload?.cover || '')
                        : '';
                const platformFaviconUrl = item.type === 'YOUTUBE'
                    ? '/api/favicon?url=https%3A%2F%2Fyoutube.com'
                    : item.type === 'DEEZER'
                        ? '/api/favicon?url=https%3A%2F%2Fdeezer.com'
                        : '';
                const platformBadgeLabel = item.type === 'YOUTUBE' ? 'YT' : item.type === 'DEEZER' ? 'DZ' : '';
                const platformBadgeBg = item.type === 'YOUTUBE' ? '#ef4444' : item.type === 'DEEZER' ? '#9333ea' : 'rgba(15, 23, 42, 0.9)';
                const deezerTitleFallback = item.type === 'DEEZER'
                    ? (parseDeezerMetaFromText(item?.payload?.content || '').title || 'Music Player')
                    : '';
                const deezerMeta = item.type === 'DEEZER' ? resolveDeezerMeta(item?.payload || {}) : { title: '', artist: '' };
                const deezerExternalUrl = item.type === 'DEEZER'
                    ? String(
                        deezerId
                            ? `https://www.deezer.com/track/${deezerId}`
                            : (item?.payload?.url || '')
                    ).trim()
                    : '';
                const ytExternalUrl = item.type === 'YOUTUBE'
                    ? String(ytId ? `https://www.youtube.com/watch?v=${ytId}` : (item?.payload?.url || '')).trim()
                    : '';
                const itemTitle = item.payload?.title || deezerTitleFallback || (
                    item.type === 'WEATHER' ? 'Weather Info' :
                        item.type === 'SYSTEM_HEALTH' ? 'System Health' :
                            item.type === 'WIKI' ? 'Wiki Insight' :
                                item.type === 'MAP' ? 'Location Map' :
                                    item.type === 'CHART' ? 'Data Analytics' :
                                        item.type === 'DEEZER' ? 'Music Player' :
                                        item.type === 'TERMINAL' ? 'Terminal Stream' :
                                                'System Asset'
                );
                const displayTitle = item.type === 'DEEZER'
                    ? (deezerMeta.title || itemTitle || 'Music Player')
                    : itemTitle;
                const secondaryLine = item.type === 'DEEZER'
                    ? `${deezerMeta.artist ? `${deezerMeta.artist} • ` : ''}${item.isPinned ? 'PINNED' : `${Math.ceil(item.remainingTime / 1000)}s`}`
                    : `${item.type} • ${item.isPinned ? 'PINNED' : `${Math.ceil(item.remainingTime / 1000)}s`}`;
                return (
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

                    <div style={{ width: '44px', height: '44px', borderRadius: '6px', overflow: 'hidden', flexShrink: 0, background: 'var(--bg-color)', position: 'relative', border: '1px solid rgba(255,255,255,0.12)' }}>
                        {item.type === 'IMAGE' ? (
                            <img src={getFileUrl(item.payload, sessionId)} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        ) : (item.type === 'YOUTUBE' || item.type === 'DEEZER') && popupThumbUrl ? (
                            <img src={popupThumbUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        ) : item.type === 'YOUTUBE' ? (
                            <div className="flex-center" style={{ height: '100%', background: '#f00' }}><PlayCircle size={20} color="#fff" /></div>
                        ) : item.type === 'CODE' ? (
                            <div className="flex-center" style={{ height: '100%' }}><Terminal size={20} color="var(--accent-color)" /></div>
                        ) : item.type === 'TERMINAL' ? (
                            <div className="flex-center" style={{ height: '100%', background: 'rgba(16, 185, 129, 0.12)' }}><Terminal size={20} color="#10b981" /></div>
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
                        ) : item.type === 'DEEZER' ? (
                            <div className="flex-center" style={{ height: '100%', background: 'rgba(59, 130, 246, 0.12)' }}><PlayCircle size={20} color="#3b82f6" /></div>
                        ) : item.type === 'APPROVAL' ? (
                            <div className="flex-center" style={{ height: '100%', background: 'rgba(245, 158, 11, 0.12)' }}><Shield size={20} color="#f59e0b" /></div>
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
                        {(item.type === 'YOUTUBE' || item.type === 'DEEZER') && (
                            <div style={{
                                width: '14px',
                                height: '14px',
                                borderRadius: '4px',
                                position: 'absolute',
                                right: '2px',
                                bottom: '2px',
                                border: '1px solid rgba(255,255,255,0.38)',
                                background: platformBadgeBg,
                                color: '#fff',
                                fontSize: '8px',
                                fontWeight: 800,
                                lineHeight: '12px',
                                textAlign: 'center',
                                overflow: 'hidden'
                            }}>
                                {platformBadgeLabel}
                                {platformFaviconUrl && (
                                    <img
                                        src={platformFaviconUrl}
                                        alt=""
                                        style={{ width: '100%', height: '100%', objectFit: 'cover', position: 'absolute', inset: 0 }}
                                        onError={(e) => { e.currentTarget.style.display = 'none'; }}
                                    />
                                )}
                            </div>
                        )}
                    </div>

                    <div style={{ flex: 1, minWidth: 0 }}>
                        <p style={{ fontSize: '11px', fontWeight: '800', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {displayTitle}
                        </p>
                        <p style={{ fontSize: '9px', color: 'var(--text-muted)', margin: '2px 0 0 0', textTransform: 'uppercase' }}>
                            {secondaryLine}
                        </p>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        <button onClick={() => onPin(item.id)} className="btn-ghost" style={{ padding: '4px', color: item.isPinned ? 'var(--accent-color)' : 'var(--text-muted)' }}><Pin size={12} /></button>
                        <button onClick={() => onFocus(item.id)} className="btn-ghost" style={{ padding: '4px' }}><Maximize2 size={12} /></button>
                        {((item.type === 'YOUTUBE' && !!ytExternalUrl)
                            || (item.type === 'DEEZER' && !!deezerExternalUrl)
                            || (item.type !== 'YOUTUBE' && item.type !== 'DEEZER' && !!item.payload?.url)) && (
                            <a
                                href={
                                    item.type === 'YOUTUBE'
                                        ? ytExternalUrl
                                        : item.type === 'DEEZER'
                                            ? deezerExternalUrl
                                            : item.payload.url
                                }
                                target="_blank"
                                rel="noreferrer"
                                className="btn-ghost"
                                style={{ padding: '4px', display: 'flex', color: '#e2e8f0' }}
                            >
                                <ExternalLink size={12} strokeWidth={2.4} />
                            </a>
                        )}
                        {item.type !== 'APPROVAL' && (
                            <button onClick={() => onClose(item.id)} className="btn-ghost" style={{ padding: '4px' }}><X size={12} /></button>
                        )}
                    </div>
                </div>
                );
            })}
        </div>
    );
};

const DashboardApprovalCard = ({ item, sessionId, onResolved }) => {
    const [busy, setBusy] = useState(false);
    const [decision, setDecision] = useState(null);
    const workId = item?.payload?.work_id;
    const prompt = String(
        item?.payload?.approval_prompt
        || item?.payload?.prompt
        || item?.payload?.status_message
        || 'Esta tarefa precisa da sua aprovação para continuar.'
    ).trim();

    const sendDecision = async (command, scope = 'worker', label = '') => {
        if (!workId || busy || decision) return;
        setBusy(true);
        try {
            await api.post(`/tasks/works/${workId}/commands`, {
                command,
                payload: { scope },
                requester_session_id: sessionId,
                source_session_id: sessionId,
            });
            setDecision({ command, scope, label: label || (command === 'deny' ? 'Denied' : `Allowed (${scope})`) });
            setTimeout(() => onResolved?.(item?.id, workId), 1400);
        } catch (err) {
            toast.error(err?.message || 'Failed to send approval decision');
        } finally {
            setBusy(false);
        }
    };

    const statusPillBg = decision
        ? (decision.command === 'deny' ? 'rgba(239, 68, 68, 0.14)' : 'rgba(16, 185, 129, 0.14)')
        : 'rgba(245, 158, 11, 0.16)';
    const statusPillBorder = decision
        ? (decision.command === 'deny' ? '1px solid rgba(239, 68, 68, 0.35)' : '1px solid rgba(16, 185, 129, 0.35)')
        : '1px solid rgba(245, 158, 11, 0.35)';
    const statusPillColor = decision
        ? (decision.command === 'deny' ? '#ef4444' : '#34d399')
        : '#f59e0b';

    return (
        <div style={{
            width: '100%',
            maxWidth: '760px',
            borderRadius: HERO_CONSTANTS.RADIUS.CARD,
            border: '1px solid rgba(245, 158, 11, 0.35)',
            background: 'linear-gradient(180deg, rgba(24, 16, 8, 0.84), rgba(16, 10, 6, 0.75))',
            boxShadow: 'var(--shadow-xl)',
            padding: '16px 18px',
            color: 'var(--text-primary)'
        }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
                    <div className="flex-center" style={{
                        width: '34px', height: '34px', borderRadius: '9px',
                        border: '1px solid rgba(245, 158, 11, 0.3)', background: 'rgba(245, 158, 11, 0.1)', flexShrink: 0
                    }}>
                        <Shield size={18} color="#f59e0b" />
                    </div>
                    <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: '13px', fontWeight: 800, letterSpacing: '0.02em' }}>Permission Required</div>
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                            Work {String(workId || '').slice(0, 8) || 'unknown'}
                        </div>
                    </div>
                </div>
                <div style={{
                    padding: '4px 10px',
                    borderRadius: '999px',
                    background: statusPillBg,
                    border: statusPillBorder,
                    color: statusPillColor,
                    fontSize: '10px',
                    fontWeight: 800,
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                }}>
                    {decision ? decision.label : 'Awaiting approval'}
                </div>
            </div>

            <div style={{ fontSize: '12px', lineHeight: 1.45, color: 'var(--text-primary)', marginBottom: decision ? '0' : '12px' }}>
                {prompt}
            </div>

            {!decision && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    <button className="btn-ghost" disabled={busy} onClick={() => sendDecision('deny', 'worker', 'Deny')} style={{ fontSize: '11px', padding: '6px 10px', border: '1px solid rgba(239, 68, 68, 0.4)', color: '#f87171' }}>
                        Deny
                    </button>
                    <button className="btn-ghost" disabled={busy} onClick={() => sendDecision('approve', 'worker', 'Allow work')} style={{ fontSize: '11px', padding: '6px 10px' }}>
                        Allow work
                    </button>
                    <button className="btn-ghost" disabled={busy} onClick={() => sendDecision('approve', 'session', 'Allow session')} style={{ fontSize: '11px', padding: '6px 10px' }}>
                        Allow session
                    </button>
                    <button className="btn-ghost" disabled={busy} onClick={() => sendDecision('approve', 'global', 'Allow global')} style={{ fontSize: '11px', padding: '6px 10px' }}>
                        Allow global
                    </button>
                </div>
            )}
        </div>
    );
};

const StageOrbLayer = ({ state, voice, ttsIntensity, theme }) => {
    const orbRef = useRef(null);

    // Only render actual Orb visuals if active or in live mode
    const isOrbActive = state.voiceState.isActive || state.executionState.isLive || state.voiceMode === 'live';

    useEffect(() => {
        if (!orbRef.current) return;

        // Determine the semantic state to pass to the Canvas Orb
        let targetState = 'idle';
        let pulseForce = 0;

        // Priority Logic: Voice Status > Execution Status
        if (state.voiceState.status === 'speaking') {
            targetState = 'speaking';
            pulseForce = 0.95;
        } else if (state.voiceState.status === 'thinking' || state.voiceState.status === 'processing') {
            targetState = 'thinking';
        } else if (state.voiceState.status === 'listening') {
            targetState = 'listening';
        } else if (state.executionState.isLive) {
            // Fallback for non-voice execution
            targetState = 'speaking';
            pulseForce = 0.8;
        } else if (state.voiceState.isActive || state.voiceMode === 'live' || voice.isRecording) {
            targetState = 'listening';
        }

        // Apply state and theme
        orbRef.current.setState(targetState, theme);

        // Combine mic intensity (from state.voiceState.intensity if available or hook)
        // and TTS intensity
        const micInt = voice.intensity || 0;
        const outInt = ttsIntensity || 0;
        const totalInt = Math.max(micInt, outInt);

        // React to voice intensity with vibration
        if (totalInt > 0.05) {
            orbRef.current.setVibration(totalInt);
            if (totalInt > 0.3) orbRef.current.pulse({ score: totalInt });
        } else {
            orbRef.current.setVibration(0);
        }

        if (state.executionState.isLive && state.executionState.status !== 'speaking') {
            orbRef.current.pulse({ score: pulseForce, ms: 200 });
        }

    }, [state.voiceState.status, state.voiceState.isActive, state.executionState.status, state.executionState.isLive, state.voiceMode, voice.intensity, ttsIntensity]);

    // Manage Screen Wake Lock to prevent sleep during voice sessions
    useEffect(() => {
        let wakeLock = null;

        const requestWakeLock = async () => {
            try {
                if ('wakeLock' in navigator) {
                    wakeLock = await navigator.wakeLock.request('screen');
                    console.log('Screen Wake Lock is active');
                }
            } catch (err) {
                console.warn(`Wake Lock error: ${err.name}, ${err.message}`);
            }
        };

        if (isOrbActive) {
            requestWakeLock();
        }

        return () => {
            if (wakeLock) {
                wakeLock.release().then(() => {
                    wakeLock = null;
                    console.log('Screen Wake Lock released');
                });
            }
        };
    }, [isOrbActive]);

    // Calculate display label for the pill
    let displayLabel = null;
    if (state.executionState.isLive || state.voiceState.status === 'speaking') {
        displayLabel = 'SPEAKING';
    } else if (state.voiceState.status === 'thinking' || state.voiceState.status === 'processing' || state.executionState.status === 'thinking') {
        displayLabel = 'THINKING';
    } else if (state.voiceState.status === 'listening' || state.voiceState.isActive || voice.isRecording) {
        displayLabel = 'LISTENING';
    }

    // Hide everything if not in an active voice context or live session
    if (!isOrbActive && !displayLabel) return null;

    return (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '20px', opacity: isOrbActive ? 1 : 0.0, transition: 'opacity 0.5s', width: '100%', height: '100%', position: 'relative' }}>
            {isOrbActive ? <AtlasOrbCanvas ref={orbRef} /> : null}

            {displayLabel && (
                <div className="flex-center" style={{
                    padding: '4px 12px', borderRadius: '100px',
                    background: 'rgba(var(--accent-rgb), 0.1)',
                    border: '1px solid var(--accent-color)',
                    fontSize: '10px', color: 'var(--accent-color)',
                    fontWeight: 'bold', letterSpacing: '0.1em',
                    animation: 'fadeIn 0.5s ease-out',
                    position: 'absolute', bottom: '38%', zIndex: DASHBOARD_Z.HUD
                }}>
                    {displayLabel}
                </div>
            )}
        </div>
    );
};

const StageAssistCard = ({ type, payload, sessionId, isMobile = false }) => {
    const assistText =
        String(
            payload?.content
            || payload?.query
            || payload?.title
            || (type === 'WEATHER'
                ? 'weather clima previsao'
                : type === 'SYSTEM_HEALTH'
                    ? 'system health status'
                    : type === 'MAP'
                        ? 'map maps location'
                        : type === 'WIKI'
                            ? 'wikipedia wiki'
                            : '')
        ).trim();
    const {
        weatherCardData, weatherCardLoading,
        systemHealthData, systemHealthLoading,
        wikiCardData, mapCardData, youtubeCardData, parsedDataChart
    } = useAssistCards({
        sessionId,
        workId: payload?.work_id,
        text: assistText,
        isUser: false,
        isStreaming: false,
        skillsUsed: Array.isArray(payload?.skills_used) ? payload.skills_used : [],
        actionsUsed: Array.isArray(payload?.actions_used) ? payload.actions_used : [],
        sourcesUsed: Array.isArray(payload?.sources_used) ? payload.sources_used : [],
    });
    const stageScaleWrap = isMobile
        ? { width: '112%', transform: 'scale(0.88)', transformOrigin: 'top center' }
        : { width: '106%', transform: 'scale(0.94)', transformOrigin: 'top center' };
    const weatherStageWrap = {
        width: '100%',
        maxWidth: isMobile ? '100%' : 'min(84vw, 800px, calc((100vh - 230px) * 1.42))',
        paddingRight: '2px'
    };

    if (type === 'WEATHER') {
        if (weatherCardLoading && !weatherCardData) return <div className="flex-center" style={{ height: '200px', color: 'var(--accent-color)' }}>Loading Weather Data...</div>;
        const hasWeatherCoreData = !!(
            weatherCardData
            && (
                weatherCardData.location
                || weatherCardData?.current?.temp_c != null
                || weatherCardData?.current?.temperature != null
                || (Array.isArray(weatherCardData?.forecast) && weatherCardData.forecast.length > 0)
            )
        );
        if (!hasWeatherCoreData) {
            return (
                <div style={{
                    width: '100%', maxWidth: isMobile ? '100%' : '900px',
                    border: '1px solid var(--card-border)', borderRadius: HERO_CONSTANTS.RADIUS.CARD,
                    background: 'rgba(var(--accent-rgb), 0.05)', padding: isMobile ? '14px' : '18px',
                    color: 'var(--text-primary)'
                }}>
                    <div style={{ fontSize: '12px', fontWeight: 800, marginBottom: '6px' }}>Weather data unavailable</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        I could not load weather data for this request yet. Try again in a moment.
                    </div>
                </div>
            );
        }
        return (
            <div className="custom-scrollbar" style={weatherStageWrap}>
                <WeatherAssistCard data={weatherCardData} isStage={true} />
            </div>
        );
    }
    if (type === 'SYSTEM_HEALTH') {
        if (systemHealthLoading && !systemHealthData) return <div className="flex-center" style={{ height: '200px', color: 'var(--accent-color)' }}>Loading System Health...</div>;
        return <div style={{ ...stageScaleWrap, maxWidth: isMobile ? '100%' : '900px' }}><SystemHealthAssistCard data={systemHealthData} isStage={true} /></div>;
    }
    if (type === 'WIKI') return <div style={{ ...stageScaleWrap, maxWidth: isMobile ? '100%' : '800px' }}><WikiAssistCard data={wikiCardData} isStage={true} /></div>;
    if (type === 'MAP') return <div style={{ width: '100%', height: '100%', minHeight: isMobile ? '42vh' : '60vh' }}><MapAssistCard data={mapCardData} isStage={true} /></div>;
    if (type === 'CHART') return <div style={{ ...stageScaleWrap, maxWidth: isMobile ? '100%' : '1000px' }}><DataChartAssistCard chart={parsedDataChart || tryParseMarkdownTable(payload.content)} isStage={true} /></div>;

    return null;
};

const TerminalStreamCard = ({ payload, onOpenFullscreen }) => {
    const scrollRef = useRef(null);
    const status = String(payload?.terminal_status || payload?.status || '').toLowerCase();
    const isLive = status === 'running';
    const transcript = String(
        payload?.transcript
        || payload?.output_full
        || payload?.output_tail
        || `$ ${String(payload?.command || 'shell command')}\n(waiting for output...)`
    );

    useEffect(() => {
        if (!scrollRef.current) return;
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }, [transcript, isLive]);

    const statusColor = isLive ? '#10b981' : (status === 'success' ? '#22c55e' : status === 'timeout' ? '#f59e0b' : '#ef4444');

    return (
        <div style={{
            width: '100%',
            height: '100%',
            maxHeight: '100%',
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
            background: 'rgba(2, 6, 18, 0.96)',
            overflow: 'hidden'
        }}>
            <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--card-border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                <div style={{ minWidth: 0 }}>
                    <div style={{ fontFamily: '"JetBrains Mono","Fira Code",monospace', fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {String(payload?.command || payload?.terminal_id || 'terminal')}
                    </div>
                    <div style={{ fontFamily: '"JetBrains Mono","Fira Code",monospace', fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {String(payload?.cwd || '')}
                    </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                    <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{Number(payload?.line_count || 0)} lines</span>
                    <button
                        className="btn-ghost"
                        style={{ padding: '4px', borderRadius: '6px' }}
                        title="Abrir terminal em tela cheia"
                        onClick={() => onOpenFullscreen?.()}
                    >
                        <Maximize2 size={12} />
                    </button>
                    <span style={{ fontSize: '9px', fontWeight: 800, color: statusColor, textTransform: 'uppercase' }}>{status || 'running'}</span>
                </div>
            </div>
            <div ref={scrollRef} className="custom-scrollbar" style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px' }}>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '12px', lineHeight: 1.5, color: '#d9e1ff', fontFamily: '"JetBrains Mono","Fira Code",monospace' }}>
                    {transcript}
                </pre>
            </div>
        </div>
    );
};

const DeezerMiniPlayerCard = ({ payload, showHeader = true }) => {
    const trackIds = Array.isArray(payload?.trackIds) ? payload.trackIds.map((id) => String(id || '')).filter(Boolean) : [];
    const initialTrackId = String(payload?.trackId || trackIds[0] || '').trim();
    const [queue, setQueue] = useState(() => {
        const list = [];
        if (initialTrackId) list.push(initialTrackId);
        trackIds.forEach((id) => { if (id && !list.includes(id)) list.push(id); });
        return list;
    });
    const [index, setIndex] = useState(0);
    const [track, setTrack] = useState(null);
    const [loadingTrack, setLoadingTrack] = useState(false);
    const [isPlaying, setIsPlaying] = useState(false);
    const [isBuffering, setIsBuffering] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const audioRef = useRef(null);
    const currentTrackId = queue[index] || '';
    const parsedFromText = parseDeezerMetaFromText(payload?.content || '');
    const platformLabel = /spotify/i.test(String(track?.link || payload?.url || '')) ? 'Spotify' : 'Deezer';
    const platformIconUrl = `/api/favicon?url=${encodeURIComponent(/spotify/i.test(String(track?.link || payload?.url || '')) ? 'https://open.spotify.com' : 'https://www.deezer.com')}`;

    useEffect(() => {
        const merged = [];
        const nextPrimary = String(payload?.trackId || '').trim();
        if (nextPrimary) merged.push(nextPrimary);
        (Array.isArray(payload?.trackIds) ? payload.trackIds : []).forEach((id) => {
            const sid = String(id || '').trim();
            if (sid && !merged.includes(sid)) merged.push(sid);
        });
        if (merged.length > 0) {
            setQueue((prev) => {
                if (prev.length === merged.length && prev.every((id, i) => id === merged[i])) return prev;
                return merged;
            });
            setIndex((prev) => Math.min(prev, Math.max(merged.length - 1, 0)));
        }
    }, [payload?.trackId, payload?.trackIds]);

    useEffect(() => {
        let cancelled = false;
        const loadTrack = async () => {
            if (!currentTrackId) {
                setTrack({
                    id: '',
                    title: String(payload?.title || parsedFromText.title || 'Deezer Track'),
                    artist: String(payload?.artist || parsedFromText.artist || ''),
                    album: '',
                    cover: String(payload?.cover || ''),
                    preview: '',
                    link: String(payload?.url || ''),
                    duration: 30,
                });
                return;
            }
            setLoadingTrack(true);
            try {
                const data = await api.get(`/system/deezer/track/${encodeURIComponent(currentTrackId)}`);
                if (cancelled) return;
                setTrack({
                    id: String(data?.id || currentTrackId),
                    title: String(data?.title || payload?.title || `Track ${currentTrackId}`),
                    artist: String(data?.artist || payload?.artist || parsedFromText.artist || ''),
                    album: String(data?.album || ''),
                    cover: String(data?.cover || payload?.cover || ''),
                    preview: String(data?.preview || ''),
                    link: String(data?.link || payload?.url || ''),
                    duration: Number(data?.duration || 30),
                });
            } catch (_) {
                if (!cancelled) {
                    setTrack({
                        id: currentTrackId,
                        title: String(payload?.title || parsedFromText.title || `Track ${currentTrackId}`),
                        artist: String(payload?.artist || parsedFromText.artist || ''),
                        album: '',
                        cover: String(payload?.cover || ''),
                        preview: '',
                        link: String(payload?.url || ''),
                        duration: 30,
                    });
                }
            } finally {
                if (!cancelled) setLoadingTrack(false);
            }
        };
        loadTrack();
        return () => { cancelled = true; };
    }, [currentTrackId, payload?.artist, payload?.cover, payload?.title, payload?.url, parsedFromText.artist, parsedFromText.title]);

    useEffect(() => {
        const audio = audioRef.current;
        if (!audio || !track?.preview) return;
        audio.src = track.preview;
        audio.load();
        setIsPlaying(false);
        setCurrentTime(0);
    }, [track?.preview, track?.id]);

    useEffect(() => {
        const audio = audioRef.current;
        if (!audio) return undefined;

        const onTime = () => setCurrentTime(Number(audio.currentTime || 0));
        const onPlay = () => setIsPlaying(true);
        const onPause = () => setIsPlaying(false);
        const onWaiting = () => setIsBuffering(true);
        const onCanPlay = () => setIsBuffering(false);
        const onEnded = () => {
            if (queue.length > 1) setIndex((prev) => (prev + 1) % queue.length);
            else setIsPlaying(false);
        };
        audio.addEventListener('timeupdate', onTime);
        audio.addEventListener('play', onPlay);
        audio.addEventListener('pause', onPause);
        audio.addEventListener('waiting', onWaiting);
        audio.addEventListener('canplay', onCanPlay);
        audio.addEventListener('ended', onEnded);
        return () => {
            audio.removeEventListener('timeupdate', onTime);
            audio.removeEventListener('play', onPlay);
            audio.removeEventListener('pause', onPause);
            audio.removeEventListener('waiting', onWaiting);
            audio.removeEventListener('canplay', onCanPlay);
            audio.removeEventListener('ended', onEnded);
        };
    }, [queue.length]);

    const togglePlay = async () => {
        const audio = audioRef.current;
        if (!audio || !track?.preview) return;
        try {
            if (audio.paused) {
                setIsPlaying(true); // Immediate visual feedback while play promise resolves
                await audio.play();
            } else {
                audio.pause();
                setIsPlaying(false);
            }
        } catch (_) {
            setIsPlaying(false);
        }
    };

    const total = Math.max(1, Number(track?.duration || audioRef.current?.duration || 30));
    const progressPct = Math.max(0, Math.min(100, (currentTime / total) * 100));
    const resolvedTrackId = String(
        extractDeezerTrackId(String(track?.link || ''))
        || extractDeezerTrackId(String(payload?.url || ''))
        || payload?.trackId
        || currentTrackId
        || ''
    ).trim();
    const externalUrl = String(track?.link || payload?.url || (resolvedTrackId ? `https://www.deezer.com/track/${resolvedTrackId}` : '')).trim();
    const fmt = (v) => {
        const n = Math.max(0, Number(v || 0));
        const mm = Math.floor(n / 60);
        const ss = Math.floor(n % 60);
        return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
    };

    const handleOpenExternal = () => {
        if (!externalUrl) return;
        window.open(externalUrl, '_blank', 'noopener,noreferrer');
    };

    const handleCopyExternal = async () => {
        if (!externalUrl) return;
        try {
            await navigator.clipboard.writeText(externalUrl);
            toast.success('Link copied');
        } catch (_) {
            toast.error('Failed to copy link');
        }
    };

    return (
        <div style={{ width: '100%', height: 'auto', display: 'flex', flexDirection: 'column', padding: '12px', background: 'linear-gradient(180deg, rgba(9, 14, 25, 0.95), rgba(6, 10, 18, 0.95))' }}>
            <audio ref={audioRef} preload="none" />
            <div style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
                <div style={{ width: '100%', maxWidth: '240px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {showHeader && (
                        <div style={{
                            width: '100%',
                            height: '28px',
                            padding: '0 8px',
                            borderRadius: '8px',
                            border: '1px solid rgba(255,255,255,0.1)',
                            background: 'linear-gradient(180deg, rgba(2, 6, 18, 0.95), rgba(2, 6, 18, 0.74))',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between'
                        }}>
                            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
                                <img
                                    src="/api/favicon?url=https%3A%2F%2Fdeezer.com"
                                    alt=""
                                    style={{ width: '12px', height: '12px', borderRadius: '3px', flexShrink: 0 }}
                                    onError={(e) => { e.currentTarget.style.display = 'none'; }}
                                />
                                <span style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '0.03em', color: '#e5e7eb', textTransform: 'uppercase' }}>
                                    Deezer
                                </span>
                            </div>
                            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                <button
                                    type="button"
                                    className="btn-ghost"
                                    onClick={handleCopyExternal}
                                    disabled={!externalUrl}
                                    title="Copy Deezer link"
                                    style={{ padding: '4px', lineHeight: 0, color: '#e2e8f0', borderRadius: '6px', opacity: externalUrl ? 1 : 0.45 }}
                                >
                                    <Copy size={12} strokeWidth={2.4} />
                                </button>
                                <button
                                    type="button"
                                    className="btn-ghost"
                                    onClick={handleOpenExternal}
                                    disabled={!externalUrl}
                                    title="Open on Deezer"
                                    style={{ padding: '4px', lineHeight: 0, color: '#e2e8f0', borderRadius: '6px', opacity: externalUrl ? 1 : 0.45 }}
                                >
                                    <ExternalLink size={12} strokeWidth={2.4} />
                                </button>
                            </div>
                        </div>
                    )}
                    <div style={{ width: '100%', aspectRatio: '1 / 1', borderRadius: '12px', overflow: 'hidden', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.04)', position: 'relative' }}>
                        {track?.cover ? (
                            <img src={track.cover} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        ) : (
                            <div className="flex-center" style={{ width: '100%', height: '100%' }}><PlayCircle size={30} color="var(--accent-color)" /></div>
                        )}

                        <button
                            className="btn-ghost"
                            onClick={togglePlay}
                            disabled={!track?.preview || loadingTrack}
                            style={{
                                position: 'absolute',
                                left: '50%',
                                top: '50%',
                                transform: 'translate(-50%, -50%)',
                                width: '56px',
                                height: '56px',
                                borderRadius: '50%',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                border: '1px solid rgba(255,255,255,0.32)',
                                background: 'rgba(2, 6, 18, 0.58)',
                                backdropFilter: 'blur(4px)'
                            }}
                            title={isPlaying ? 'Pause' : 'Play'}
                        >
                            {isPlaying ? <Pause size={20} /> : <Play size={20} fill="currentColor" />}
                        </button>

                        <div style={{
                            position: 'absolute',
                            left: '8px',
                            right: '8px',
                            bottom: '8px',
                            padding: '6px 8px',
                            borderRadius: '8px',
                            background: 'rgba(2, 6, 18, 0.48)',
                            border: '1px solid rgba(255,255,255,0.16)',
                            backdropFilter: 'blur(6px)',
                            WebkitBackdropFilter: 'blur(6px)'
                        }}>
                            <div style={{ fontSize: '12px', fontWeight: 800, color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {loadingTrack ? 'Loading track...' : (track?.title || 'Deezer Track')}
                            </div>
                            <div style={{ fontSize: '10px', color: 'rgba(226,232,240,0.95)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: '1px' }}>
                                {track?.artist || 'Unknown artist'}
                            </div>
                        </div>
                    </div>
                    {isBuffering && (
                        <div style={{ fontSize: '9px', color: 'var(--accent-color)', marginTop: '-2px' }}>Buffering...</div>
                    )}
                    <div style={{ width: '100%', height: '4px', borderRadius: '999px', background: 'rgba(255,255,255,0.12)', overflow: 'hidden' }}>
                        <div style={{ width: `${progressPct}%`, height: '100%', background: 'var(--accent-color)', transition: 'width 0.15s linear' }} />
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
                            <img
                                src={platformIconUrl}
                                alt=""
                                style={{ width: '12px', height: '12px', borderRadius: '3px', flexShrink: 0 }}
                                onError={(e) => { e.currentTarget.style.display = 'none'; }}
                            />
                            <span style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{platformLabel}</span>
                        </div>
                        <span style={{ fontSize: '9px', color: 'var(--text-muted)', fontFamily: '"JetBrains Mono","Fira Code",monospace' }}>
                            {fmt(currentTime)} / {fmt(total)}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    );
};

const StageMediaLayer = ({ mediaState, onDockMedia, onResolveApproval, onOpenTerminalFullscreen, sessionId, isMobile = false }) => {
    const stageItems = Array.isArray(mediaState?.stageItems) ? mediaState.stageItems : [];
    const item = mediaState.focusedItem || stageItems[0] || null;
    if (!item) return null;
    const isSingleStage = stageItems.length <= 1;
    const isAssistCard = ['WEATHER', 'SYSTEM_HEALTH', 'WIKI', 'MAP', 'CHART'].includes(item?.type);
    const isWeather = item?.type === 'WEATHER';
    const isLink = item?.type === 'LINK';
    const isYouTube = item?.type === 'YOUTUBE';
    const isDeezer = item?.type === 'DEEZER';
    const isCode = item?.type === 'CODE';
    const isTerminal = item?.type === 'TERMINAL';
    const isImage = item?.type === 'IMAGE';
    const isApproval = item?.type === 'APPROVAL';
    const isPlayback = item?.type === 'PLAYBACK';
    const [isSystemFullscreen, setIsSystemFullscreen] = useState(() => !!document.fullscreenElement);
    const resolvedYouTubeId = isYouTube
        ? (extractYouTubeId(String(item?.payload?.videoId || '')) || extractYouTubeId(String(item?.payload?.url || '')) || '')
        : '';
    const resolvedYouTubeUrl = resolvedYouTubeId
        ? `https://www.youtube.com/watch?v=${resolvedYouTubeId}`
        : String(item?.payload?.url || '').trim();
    const resolvedDeezerUrl = isDeezer
        ? String(
            item?.payload?.url
            || (item?.payload?.trackId ? `https://www.deezer.com/track/${item.payload.trackId}` : '')
        ).trim()
        : '';
    const genericExternalUrl = String(item?.payload?.url || '').trim();
    const shellExternalUrl = isYouTube
        ? resolvedYouTubeUrl
        : isDeezer
            ? resolvedDeezerUrl
            : genericExternalUrl;
    const shellTitle = (
        isYouTube ? 'YouTube' :
            isDeezer ? 'Deezer' :
                item?.type === 'WEATHER' ? 'Weather' :
                    item?.type === 'SYSTEM_HEALTH' ? 'System Health' :
                        item?.type === 'WIKI' ? 'Wiki' :
                            item?.type === 'MAP' ? 'Map' :
                                item?.type === 'CHART' ? 'Chart' :
                                    item?.type === 'TERMINAL' ? 'Terminal' :
                                        item?.type === 'CODE' ? 'Code' :
                                            item?.type === 'IMAGE' ? 'Image' :
                                                item?.type === 'PLAYBACK' ? 'Playback' :
                                                    item?.type === 'LINK' ? 'Link' :
                                                        'Asset'
    ).toUpperCase();
    const shellFavicon = isYouTube
        ? '/api/favicon?url=https%3A%2F%2Fyoutube.com'
        : isDeezer
            ? '/api/favicon?url=https%3A%2F%2Fdeezer.com'
            : '';
    // Extra compact for dashboard focus media.
    const frameMaxWidth = isMobile
        ? (isWeather ? 'min(96vw, 540px)' : isAssistCard ? 'min(98vw, 560px)' : isYouTube ? 'min(88vw, 520px)' : isDeezer ? 'min(82vw, 320px)' : isLink ? 'min(90vw, 420px)' : 'min(90vw, 420px)')
        : (isWeather
            ? (isSingleStage ? 'min(64vw, 920px, calc((100vh - 220px) * 1.55))' : 'min(56vw, 800px, calc((100vh - 220px) * 1.42))')
            : isAssistCard
                ? (isSingleStage ? 'min(68vw, 980px, calc((100vh - 220px) * 1.70))' : 'min(60vw, 880px, calc((100vh - 220px) * 1.56))')
                : isApproval
                    ? (isSingleStage ? 'min(64vw, 900px, calc((100vh - 220px) * 1.52))' : 'min(58vw, 820px, calc((100vh - 220px) * 1.45))')
                    : isYouTube
                        ? (isSingleStage ? 'min(50vw, 700px)' : 'min(42vw, 560px)')
                        : isDeezer
                            ? (isSingleStage ? 'min(34vw, 360px)' : 'min(30vw, 320px)')
                            : isLink
                                ? (isSingleStage ? 'min(50vw, 640px)' : 'min(44vw, 560px)')
                                : (isSingleStage ? 'min(50vw, 640px)' : 'min(44vw, 560px)'));
    const frameMaxHeight = isMobile
        ? (isWeather ? 'min(66vh, 560px)' : isAssistCard ? 'min(72vh, 700px)' : isYouTube ? 'min(58vh, 460px)' : isDeezer ? 'min(66vh, 540px)' : isTerminal ? 'min(52vh, calc(100vh - 260px))' : isCode ? 'min(52vh, 500px)' : isImage ? 'min(42vh, 340px)' : 'min(30vh, 240px)')
        : (isWeather ? 'min(58vh, 560px)' : isAssistCard ? 'min(46vh, 520px)' : isApproval ? 'min(42vh, 460px)' : isYouTube ? 'min(56vh, 520px)' : isDeezer ? 'min(64vh, 560px)' : isTerminal ? 'min(58vh, calc(100vh - 320px))' : isCode ? 'min(54vh, 620px)' : isImage ? 'min(48vh, 460px)' : 'min(30vh, 260px)');
    const topSafe = isMobile ? 56 : (isPlayback ? 34 : isTerminal ? (isSystemFullscreen ? 12 : 36) : 72);
    const bottomSafe = isMobile ? 170 : (isTerminal ? 320 : 230);
    const viewportSafeMaxHeight = `calc(100vh - ${topSafe + bottomSafe}px)`;
    const effectiveFrameMaxHeight = `min(${frameMaxHeight}, ${viewportSafeMaxHeight})`;
    const terminalHardMaxHeightPx = (() => {
        if (typeof window === 'undefined') return 360;
        const vh = window.innerHeight || 900;
        return Math.max(isMobile ? 280 : 320, vh - (isMobile ? 260 : 360));
    })();
    const baseShiftY = isYouTube
        ? (isMobile ? -18 : -56)
        : isPlayback
            ? (isMobile ? -22 : -64)
        : isTerminal
            ? (isMobile ? -24 : (isSystemFullscreen ? -116 : -72))
        : isWeather
            ? (isMobile ? -12 : -42)
            : (isMobile ? -8 : -28);
    const stageFrameRef = useRef(null);
    const [dynamicShiftY, setDynamicShiftY] = useState(baseShiftY);

    useEffect(() => {
        const onFs = () => setIsSystemFullscreen(!!document.fullscreenElement);
        document.addEventListener('fullscreenchange', onFs);
        return () => document.removeEventListener('fullscreenchange', onFs);
    }, []);

    useEffect(() => {
        const el = stageFrameRef.current;
        if (!el) return undefined;

        const calcShift = () => {
            const vh = window.innerHeight || 0;
            const h = el.offsetHeight || 0;
            const maxBottom = vh - bottomSafe;
            const centerTop = (vh - h) / 2;
            const centerBottom = (vh + h) / 2;
            const minShift = topSafe - centerTop;
            const maxShift = maxBottom - centerBottom;
            let shift = baseShiftY;

            if (minShift > maxShift) {
                // Content taller than safe space: keep bottom inside viewport.
                shift = maxShift;
            } else {
                shift = Math.max(minShift, Math.min(maxShift, shift));
            }
            setDynamicShiftY(Math.round(shift));
        };

        calcShift();
        const ro = new ResizeObserver(() => calcShift());
        ro.observe(el);
        window.addEventListener('resize', calcShift);
        return () => {
            ro.disconnect();
            window.removeEventListener('resize', calcShift);
        };
    }, [baseShiftY, isMobile, mediaState.focusedMediaId, item?.type]);

    if (stageItems.length > 1) {
        const multiItems = stageItems.slice(0, 4);
        const cols = multiItems.length >= 3 ? 2 : multiItems.length;
        const rows = Math.ceil(multiItems.length / Math.max(1, cols));
        const stageTopPad = isMobile ? 70 : 86;
        const stageBottomPad = isMobile ? 170 : 220;
        const gridGapPx = 10;
        const viewportH = typeof window !== 'undefined' ? window.innerHeight : 900;
        const safeStageHeight = Math.max(
            isMobile ? 340 : 390,
            viewportH - stageTopPad - stageBottomPad
        );
        const rowHeight = Math.max(
            isMobile ? 156 : 186,
            Math.floor((safeStageHeight - ((rows - 1) * gridGapPx)) / Math.max(1, rows))
        );
        return (
            <div style={{
                width: '100vw', height: '100vh',
                position: 'fixed', inset: 0,
                pointerEvents: 'none',
                zIndex: DASHBOARD_Z.STAGE_CARD,
                display: 'flex',
                alignItems: 'flex-start',
                justifyContent: 'center',
                paddingTop: isMobile ? '72px' : '88px',
                paddingBottom: isMobile ? '132px' : '156px'
            }}>
                <div className="custom-scrollbar" style={{
                    width: isMobile ? '95vw' : 'min(78vw, 1080px)',
                    height: `${safeStageHeight}px`,
                    overflow: 'hidden',
                    pointerEvents: 'auto',
                    display: 'grid',
                    gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
                    gridTemplateRows: `repeat(${rows}, minmax(0, ${rowHeight}px))`,
                    gap: `${gridGapPx}px`
                }}>
                    {multiItems.map((gridItem) => {
                        const gType = String(gridItem?.type || '');
                        const gIsAssist = ['WEATHER', 'SYSTEM_HEALTH', 'WIKI', 'MAP', 'CHART'].includes(gType);
                        const gIsWeather = gType === 'WEATHER';
                        const gIsYouTube = gType === 'YOUTUBE';
                        const gIsDeezer = gType === 'DEEZER';
                        const gIsTerminal = gType === 'TERMINAL';
                        const gIsCode = gType === 'CODE';
                        const gIsImage = gType === 'IMAGE';
                        const gIsApproval = gType === 'APPROVAL';
                        const gIsPlayback = gType === 'PLAYBACK';
                        const gFrameH = Math.max(112, Math.min(isMobile ? 184 : 220, rowHeight - (isMobile ? 112 : 124)));
                        const gYtId = gIsYouTube
                            ? (extractYouTubeId(String(gridItem?.payload?.videoId || '')) || extractYouTubeId(String(gridItem?.payload?.url || '')) || '')
                            : '';
                        const gExternal = gIsYouTube
                            ? String(gYtId ? `https://www.youtube.com/watch?v=${gYtId}` : (gridItem?.payload?.url || '')).trim()
                            : gIsDeezer
                                ? String(gridItem?.payload?.url || (gridItem?.payload?.trackId ? `https://www.deezer.com/track/${gridItem.payload.trackId}` : '')).trim()
                                : String(gridItem?.payload?.url || '').trim();
                        const gTitle = (gIsYouTube ? 'YOUTUBE' : gIsDeezer ? 'DEEZER' : gType || 'ASSET');
                        const gFavicon = gIsYouTube
                            ? '/api/favicon?url=https%3A%2F%2Fyoutube.com'
                            : gIsDeezer
                                ? '/api/favicon?url=https%3A%2F%2Fdeezer.com'
                                : '';

                        return (
                            <div key={gridItem.id} style={{
                                borderRadius: HERO_CONSTANTS.RADIUS.CARD,
                                border: '1px solid rgba(var(--accent-rgb), 0.18)',
                                background: 'var(--card-bg)',
                                boxShadow: 'none',
                                backdropFilter: 'blur(4px)',
                                WebkitBackdropFilter: 'blur(4px)',
                                display: 'flex',
                                flexDirection: 'column',
                                padding: '6px',
                                gap: '4px',
                                minHeight: 0,
                                height: '100%'
                            }}>
                                <div style={{
                                    width: '100%',
                                    minHeight: '22px',
                                    padding: '0 6px',
                                    borderRadius: '6px',
                                    border: '1px solid var(--card-border)',
                                    background: 'transparent',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    gap: '8px',
                                }}>
                                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
                                        {gFavicon ? <img src={gFavicon} alt="" style={{ width: '12px', height: '12px', borderRadius: '3px', flexShrink: 0 }} onError={(e) => { e.currentTarget.style.display = 'none'; }} /> : <Layers size={12} color="#9ca3af" />}
                                        <span style={{ fontSize: '10px', fontWeight: 800, color: 'var(--text-primary)', textTransform: 'uppercase', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{gTitle}</span>
                                    </div>
                                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                        {gExternal && (
                                            <a href={gExternal} target="_blank" rel="noreferrer" className="btn-ghost" title="Open link" style={{ padding: '4px', lineHeight: 0, color: 'var(--text-muted)', borderRadius: '6px' }}>
                                                <ExternalLink size={12} strokeWidth={2.4} />
                                            </a>
                                        )}
                                        <button onClick={() => onDockMedia(gridItem.id)} className="flex-center" style={{ width: '24px', height: '24px', borderRadius: '6px', background: 'transparent', color: 'var(--text-primary)', border: '1px solid var(--card-border)', cursor: 'pointer' }} title="Fechar mídia focada">
                                            <X size={15} strokeWidth={2.8} />
                                        </button>
                                    </div>
                                </div>
                                <div className="custom-scrollbar" style={{ flex: 1, minHeight: 0, borderRadius: '8px', overflow: 'auto', border: '1px solid var(--card-border)', padding: '4px', background: 'transparent' }}>
                                    {gIsApproval ? (
                                        <DashboardApprovalCard item={gridItem} sessionId={sessionId} onResolved={onResolveApproval} />
                                    ) : gIsImage ? (
                                        <img src={getFileUrl(gridItem.payload, sessionId)} alt="" style={{ width: '100%', maxHeight: `${Math.max(120, rowHeight - 92)}px`, objectFit: 'contain' }} />
                                    ) : gIsYouTube ? (
                                        gYtId ? <iframe width="100%" height={String(gFrameH)} src={`https://www.youtube-nocookie.com/embed/${gYtId}?autoplay=0&rel=0&modestbranding=1`} title="YouTube player" frameBorder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen /> : <LinkPreviewCard messageContent={gridItem?.payload?.url || gridItem?.payload?.fullContent || ''} isStage={true} />
                                    ) : gIsAssist ? (
                                        <StageAssistCard type={gridItem.type} payload={gridItem.payload} sessionId={sessionId} isMobile={isMobile} />
                                    ) : gIsCode ? (
                                        <pre style={{ margin: 0, color: '#0f0', fontFamily: "'Fira Code', monospace", fontSize: '12px', whiteSpace: 'pre-wrap' }}>{gridItem?.payload?.code || ''}</pre>
                                    ) : gIsTerminal ? (
                                        <TerminalStreamCard payload={gridItem.payload || {}} onOpenFullscreen={() => onOpenTerminalFullscreen?.(gridItem?.id)} />
                                    ) : gIsDeezer ? (
                                        <DeezerMiniPlayerCard payload={gridItem.payload || {}} showHeader={false} />
                                    ) : gIsPlayback ? (
                                        <PlaybackCard runId={gridItem.payload.runId} sessionId={sessionId} embedMode={true} />
                                    ) : (
                                        <LinkPreviewCard messageContent={gridItem?.payload?.fullContent || gridItem?.payload?.url || ''} isStage={true} />
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    }

    return (
        <div style={{
            width: '100vw', height: '100vh',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            position: 'fixed', inset: 0, padding: 0, pointerEvents: 'none',
            animation: 'scaleUp 0.3s cubic-bezier(0.19, 1, 0.22, 1)', zIndex: DASHBOARD_Z.STAGE_CARD
        }}>
            {/* Media Area (Stage Center) */}
            <div style={{
                flex: 1, width: '100%', display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', position: 'relative',
                padding: '0',
                zIndex: DASHBOARD_Z.STAGE_CARD,
                transform: `translateY(${dynamicShiftY}px)`
            }}>
                {/* HUD Connector Line - Extended to top and bottom */}
                <div style={{
                    position: 'absolute', top: '-20px', left: '50%', transform: 'translateX(-50%)',
                    width: '1px', height: 'calc(100% + 40px)',
                    background: 'linear-gradient(to bottom, var(--accent-color) 0%, transparent 30%, transparent 70%, var(--accent-color) 100%)',
                    opacity: 0.25, pointerEvents: 'none', zIndex: -1
                }} />

                {/* Auto-Sizing Wrapper */}
                <div style={{
                    position: 'relative', display: 'flex', pointerEvents: 'auto',
                    width: '100%',
                    maxWidth: frameMaxWidth,
                    height: '100%',
                    maxHeight: isTerminal ? `${terminalHardMaxHeightPx}px` : effectiveFrameMaxHeight,
                    aspectRatio: isYouTube ? '4 / 3' : 'auto',
                    overflow: 'visible'
                }} ref={stageFrameRef}>

                    {/* HUD Brackets (Corner Decorations) */}
                    <div style={{ position: 'absolute', top: '-6px', left: '-6px', width: '12px', height: '12px', borderTop: '2px solid var(--accent-color)', borderLeft: '2px solid var(--accent-color)', opacity: 0.6, pointerEvents: 'none' }} />
                    <div style={{ position: 'absolute', top: '-6px', right: '-6px', width: '12px', height: '12px', borderTop: '2px solid var(--accent-color)', borderRight: '2px solid var(--accent-color)', opacity: 0.6, pointerEvents: 'none' }} />
                    <div style={{ position: 'absolute', bottom: '-6px', left: '-6px', width: '12px', height: '12px', borderBottom: '2px solid var(--accent-color)', borderLeft: '2px solid var(--accent-color)', opacity: 0.6, pointerEvents: 'none' }} />
                    <div style={{ position: 'absolute', bottom: '-6px', right: '-6px', width: '12px', height: '12px', borderBottom: '2px solid var(--accent-color)', borderRight: '2px solid var(--accent-color)', opacity: 0.6, pointerEvents: 'none' }} />

                    {/* Shared envelope (Deezer style) */}
                    <div style={{
                        width: '100%',
                        height: '100%',
                        maxHeight: '100%',
                        borderRadius: HERO_CONSTANTS.RADIUS.CARD,
                        border: '1px solid var(--card-border)',
                        background: 'linear-gradient(180deg, rgba(8, 12, 24, 0.94), rgba(6, 10, 22, 0.9))',
                        boxShadow: 'var(--shadow-xl)',
                        backdropFilter: 'blur(8px)',
                        WebkitBackdropFilter: 'blur(8px)',
                        display: 'flex',
                        flexDirection: 'column',
                        padding: '8px',
                        gap: '8px',
                        overflow: 'hidden'
                    }}>
                        {!isApproval && (
                            <div style={{
                                width: '100%',
                                minHeight: '28px',
                                padding: '0 8px',
                                borderRadius: '8px',
                                border: '1px solid rgba(255,255,255,0.1)',
                                background: 'linear-gradient(180deg, rgba(2, 6, 18, 0.95), rgba(2, 6, 18, 0.74))',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                gap: '8px',
                                position: 'relative'
                            }}>
                                <div style={{
                                    position: 'absolute',
                                    top: '-1px',
                                    left: '-1px',
                                    width: '12px',
                                    height: '12px',
                                    borderTop: '1px solid rgba(var(--accent-rgb), 0.55)',
                                    borderLeft: '1px solid rgba(var(--accent-rgb), 0.55)',
                                    borderTopLeftRadius: '8px',
                                    pointerEvents: 'none'
                                }} />
                                <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
                                    {shellFavicon ? (
                                        <img
                                            src={shellFavicon}
                                            alt=""
                                            style={{ width: '12px', height: '12px', borderRadius: '3px', flexShrink: 0 }}
                                            onError={(e) => { e.currentTarget.style.display = 'none'; }}
                                        />
                                    ) : (
                                        <Layers size={12} color="#9ca3af" />
                                    )}
                                    <span style={{ fontSize: '11px', fontWeight: 800, letterSpacing: '0.03em', color: '#e5e7eb', textTransform: 'uppercase', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                        {shellTitle}
                                    </span>
                                </div>
                                <div style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
                                    {shellExternalUrl && (
                                        <button
                                            type="button"
                                            className="btn-ghost"
                                            onClick={async () => {
                                                try {
                                                    await navigator.clipboard.writeText(shellExternalUrl);
                                                    toast.success('Link copied');
                                                } catch (_) {
                                                    toast.error('Failed to copy link');
                                                }
                                            }}
                                            title="Copy link"
                                            style={{ padding: '4px', lineHeight: 0, color: '#e2e8f0', borderRadius: '6px' }}
                                        >
                                            <Copy size={12} strokeWidth={2.4} />
                                        </button>
                                    )}
                                    {shellExternalUrl && (
                                        <a
                                            href={shellExternalUrl}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="btn-ghost"
                                            title="Open link"
                                            style={{ padding: '4px', lineHeight: 0, color: '#e2e8f0', borderRadius: '6px' }}
                                        >
                                            <ExternalLink size={12} strokeWidth={2.4} />
                                        </a>
                                    )}
                                    <button
                                        onClick={() => onDockMedia(item.id)}
                                        className="flex-center"
                                        style={{
                                            width: '28px', height: '28px', borderRadius: '8px',
                                            background: 'rgba(0, 0, 0, 0.75)', color: '#fff',
                                            border: '1px solid var(--card-border)', cursor: 'pointer',
                                            boxShadow: 'var(--shadow-lg)', transition: 'transform 0.18s, background 0.18s'
                                        }}
                                        onMouseEnter={e => {
                                            e.currentTarget.style.transform = 'scale(1.05)';
                                            e.currentTarget.style.background = 'rgba(180, 20, 20, 0.92)';
                                        }}
                                        onMouseLeave={e => {
                                            e.currentTarget.style.transform = 'scale(1)';
                                            e.currentTarget.style.background = 'rgba(0, 0, 0, 0.88)';
                                        }}
                                        title="Fechar mídia focada"
                                    >
                                        <X size={15} strokeWidth={2.8} />
                                    </button>
                                </div>
                            </div>
                        )}

                        {/* Media Container (adaptive content area) */}
                        <div style={{
                            borderRadius: '10px',
                            overflow: 'auto',
                            background: (isAssistCard || isApproval)
                                ? 'linear-gradient(180deg, rgba(8, 12, 24, 0.76), rgba(10, 14, 28, 0.7))'
                                : 'transparent',
                            border: '1px solid rgba(255,255,255,0.08)',
                            display: 'flex', alignItems: isDeezer ? 'flex-start' : 'center', justifyContent: 'center',
                            width: '100%',
                            flex: isDeezer ? 'unset' : 1,
                            minHeight: 0
                        }}>
                        {item?.type === 'APPROVAL' ? (
                            <div className="custom-scrollbar" style={{ width: '100%', height: '100%', padding: isMobile ? '10px' : '14px', overflow: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                <DashboardApprovalCard item={item} sessionId={sessionId} onResolved={onResolveApproval} />
                            </div>
                        ) : item?.type === 'IMAGE' ? (
                            <img
                                src={getFileUrl(item.payload, sessionId)}
                                alt=""
                                style={{ width: '100%', height: '100%', maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', objectPosition: 'top center', display: 'block' }}
                            />
                        ) : item?.type === 'YOUTUBE' ? (
                            <div style={{ width: '100%', height: '100%', maxWidth: '100%', maxHeight: '100%', aspectRatio: '16/9', position: 'relative', background: 'rgba(2, 6, 18, 0.92)' }}>
                                {resolvedYouTubeId ? (
                                    <iframe
                                        width="100%" height="100%"
                                        src={`https://www.youtube-nocookie.com/embed/${resolvedYouTubeId}?autoplay=1&rel=0&modestbranding=1`}
                                        title="YouTube player" frameBorder="0"
                                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                                        allowFullScreen
                                    />
                                ) : (
                                    <LinkPreviewCard messageContent={item?.payload?.url || item?.payload?.fullContent || ''} isStage={true} />
                                )}
                            </div>
                        ) : ['WEATHER', 'SYSTEM_HEALTH', 'WIKI', 'MAP', 'CHART'].includes(item?.type) ? (
                            <div className="custom-scrollbar" style={{
                                width: '100%',
                                height: '100%',
                                padding: isMobile ? '10px' : '14px',
                                overflow: 'auto',
                                display: 'flex',
                                alignItems: isWeather ? 'flex-start' : (isMobile ? 'flex-start' : 'center'),
                                justifyContent: isWeather ? 'flex-start' : 'center'
                            }}>
                                <StageAssistCard type={item.type} payload={item.payload} sessionId={sessionId} isMobile={isMobile} />
                            </div>
                        ) : item?.type === 'CODE' ? (
                            <div className="custom-scrollbar" style={{ maxWidth: '100%', height: '100%', padding: '24px', color: '#0f0', fontFamily: "'Fira Code', monospace", fontSize: '12px', overflow: 'auto', textAlign: 'left' }}>
                                <pre style={{ margin: 0 }}>{item.payload.code}</pre>
                            </div>
                        ) : item?.type === 'TERMINAL' ? (
                            <div style={{ width: '100%', height: '100%', maxHeight: '100%', minHeight: 0, overflow: 'hidden' }}>
                                <TerminalStreamCard payload={item.payload || {}} onOpenFullscreen={() => onOpenTerminalFullscreen?.(item?.id)} />
                            </div>
                        ) : item?.type === 'DEEZER' ? (
                            <DeezerMiniPlayerCard payload={item.payload || {}} showHeader={false} />
                        ) : item?.type === 'PLAYBACK' ? (
                            <div style={{ width: '100%', height: '100%', padding: '10px 16px', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', overflow: 'auto' }}>
                                <PlaybackCard runId={item.payload.runId} sessionId={sessionId} embedMode={true} />
                            </div>
                        ) : item?.type === 'LINK' ? (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%', maxWidth: '100%', maxHeight: '100%', overflow: 'hidden' }}>
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
                </div>
            </div>
        </div>
    );
};
// ============================================================================
// DASHBOARD
// ============================================================================
const Dashboard = () => {
    const { theme } = useTheme();
    const [state, dispatch] = useReducer(dashboardReducer, initialState);
    const [preferredStageSignatures, setPreferredStageSignatures] = useState([]);
    const msm = useMediaStackManager(preferredStageSignatures);
    const msmRef = useRef(msm);
    useEffect(() => { msmRef.current = msm; }, [msm]);
    const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 640);

    const [sys, setSys] = useState({ status: null, works: [] });
    const wsRef = useRef(null);
    const msmAddRef = useRef(msm.addMedia);
    const msmRemoveRef = useRef(msm.removeMedia);
    const msmFocusRef = useRef(msm.focusMedia);
    const msmPatchPayloadRef = useRef(msm.patchMediaPayload);
    const msmSetPinnedRef = useRef(msm.setMediaPinned);
    useEffect(() => { msmAddRef.current = msm.addMedia; }, [msm.addMedia]);
    useEffect(() => { msmRemoveRef.current = msm.removeMedia; }, [msm.removeMedia]);
    useEffect(() => { msmFocusRef.current = msm.focusMedia; }, [msm.focusMedia]);
    useEffect(() => { msmPatchPayloadRef.current = msm.patchMediaPayload; }, [msm.patchMediaPayload]);
    useEffect(() => { msmSetPinnedRef.current = msm.setMediaPinned; }, [msm.setMediaPinned]);
    const assistCardGateByWorkRef = useRef(new Map());
    const approvalCardByWorkRef = useRef(new Map());
    const terminalCardByWorkRef = useRef(new Map());
    const terminalTrackerTimersRef = useRef(new Map());
    const terminalDismissedRef = useRef(new Map());
    const playbackCardByRunRef = useRef(new Map());
    const deezerHydrationAttemptedRef = useRef(new Set());

    useEffect(() => {
        const sid = String(state.textState.sessionId || '').trim();
        if (!sid) {
            setPreferredStageSignatures([]);
            return;
        }
        const key = `dashboard_stage_layout_${sid}`;
        try {
            const raw = localStorage.getItem(key);
            if (!raw) {
                setPreferredStageSignatures([]);
                return;
            }
            const parsed = JSON.parse(raw);
            const arr = Array.isArray(parsed?.signatures) ? parsed.signatures.map((v) => String(v || '').trim()).filter(Boolean) : [];
            setPreferredStageSignatures(arr.slice(0, 16));
        } catch (_) {
            setPreferredStageSignatures([]);
        }
    }, [state.textState.sessionId]);

    useEffect(() => {
        const sid = String(state.textState.sessionId || '').trim();
        if (!sid) return;
        const stageNow = Array.isArray(msm.mediaState?.stageItems) ? msm.mediaState.stageItems : [];
        if (stageNow.length === 0) return;
        const signatures = stageNow.map((m) => mediaSignatureFromItem(m)).filter(Boolean).slice(0, 16);
        if (signatures.length === 0) return;
        setPreferredStageSignatures((prev) => {
            const same = Array.isArray(prev) && prev.length === signatures.length && prev.every((v, i) => v === signatures[i]);
            if (same) return prev;
            return signatures;
        });
        try {
            localStorage.setItem(`dashboard_stage_layout_${sid}`, JSON.stringify({
                signatures,
                updatedAt: Date.now(),
            }));
        } catch (_) {
            // ignore storage errors
        }
    }, [msm.mediaState?.stageItems, state.textState.sessionId]);

    const claimAssistCardSlot = useCallback((workId, type) => {
        if (!workId) return true;
        const key = String(workId);
        const gate = assistCardGateByWorkRef.current;
        const existing = gate.get(key) || { hasAssist: false, types: new Set() };
        if (existing.types.has(type) || existing.hasAssist) return false;
        existing.hasAssist = true;
        existing.types.add(type);
        gate.set(key, existing);
        if (gate.size > 300) {
            const oldestKey = gate.keys().next().value;
            gate.delete(oldestKey);
        }
        return true;
    }, []);

    useEffect(() => {
        const list = Array.isArray(msm.mediaList) ? msm.mediaList : [];
        list.forEach((item) => {
            if (item?.type !== 'DEEZER') return;
            const payload = (item?.payload && typeof item.payload === 'object') ? item.payload : {};
            const meta = resolveDeezerMeta(payload);
            const trackId = String(
                payload?.trackId
                || extractDeezerTrackId(String(payload?.url || ''))
                || ''
            ).trim();
            if (!trackId) return;
            const hasCover = !!String(payload?.cover || '').trim();
            const needsMeta = !meta.title || /^deezer track$/i.test(meta.title) || !meta.artist || !hasCover;
            if (!needsMeta) return;

            const key = `${item.id}:${trackId}`;
            if (deezerHydrationAttemptedRef.current.has(key)) return;
            deezerHydrationAttemptedRef.current.add(key);

            (async () => {
                try {
                    const data = await api.get(`/system/deezer/track/${encodeURIComponent(trackId)}`);
                    msmPatchPayloadRef.current?.(item.id, {
                        title: String(data?.title || meta.title || payload?.title || 'Deezer Track'),
                        artist: String(data?.artist || meta.artist || payload?.artist || ''),
                        cover: String(data?.cover || payload?.cover || ''),
                        url: String(data?.link || payload?.url || `https://www.deezer.com/track/${trackId}`),
                        duration: Number(data?.duration || payload?.duration || 0) || payload?.duration || 0,
                    });
                } catch (_) {
                    // Keep compact card stable even if deezer API metadata fails.
                }
            })();
        });
    }, [msm.mediaList]);

    const handleApprovalResolved = useCallback((mediaId, workId) => {
        if (mediaId) msmRemoveRef.current(mediaId);
        if (workId != null) approvalCardByWorkRef.current.delete(String(workId));
    }, []);

    const syncPlaybackCard = useCallback((rawRunId, payloadPatch = {}) => {
        const runId = String(rawRunId || '').trim();
        if (!runId) return;
        const map = playbackCardByRunRef.current;
        const existing = map.get(runId);
        const currentList = Array.isArray(msmRef.current?.mediaList) ? msmRef.current.mediaList : [];
        const existingMediaId = existing?.mediaId ? String(existing.mediaId) : '';
        const stillExists = !!(existingMediaId && currentList.some((m) => m.id === existingMediaId));
        const statusNorm = String(payloadPatch?.status || '').toLowerCase();
        const shouldAutoFocus = ['running', 'active', 'playback', 'playback.frame'].includes(statusNorm);
        const normalizedPatch = {
            runId,
            title: String(payloadPatch?.title || 'Session Playback'),
            ...(payloadPatch || {}),
        };

        if (stillExists) {
            msmPatchPayloadRef.current?.(existingMediaId, normalizedPatch);
            if (shouldAutoFocus && !existing?.autoFocused) {
                msmFocusRef.current?.(existingMediaId);
                map.set(runId, { ...(existing || {}), mediaId: existingMediaId, autoFocused: true });
            }
            return;
        }

        const mediaId = msmAddRef.current?.(normalizedPatch, 'PLAYBACK');
        if (mediaId) {
            map.set(runId, { mediaId, autoFocused: shouldAutoFocus });
            if (shouldAutoFocus) msmFocusRef.current?.(mediaId);
        }
    }, []);

    const extractTerminalFromWorkSnapshot = useCallback((snapshot) => {
        const context = snapshot && typeof snapshot.context === 'object' ? snapshot.context : {};
        const data = context && typeof context.data === 'object' ? context.data : {};
        const shell = data && typeof data.shell === 'object' ? data.shell : {};
        const terminalsMap = shell && typeof shell.terminals === 'object' ? shell.terminals : null;
        const terminals = terminalsMap ? Object.values(terminalsMap).filter(Boolean) : [];
        if (!terminals.length) return null;

        const terminalById = new Map(
            terminals
                .filter((term) => term && typeof term === 'object')
                .map((term) => [String(term.id || ''), term])
        );
        const preferredId = String(shell?.last_terminal_id || '').trim();
        let selected = preferredId ? terminalById.get(preferredId) : null;

        if (!selected) {
            selected = terminals.find((term) => String(term?.status || '').toLowerCase() === 'running') || null;
        }
        if (!selected) {
            selected = terminals
                .slice()
                .sort((a, b) => Number(b?.updated_at || b?.started_at || 0) - Number(a?.updated_at || a?.started_at || 0))[0] || null;
        }
        if (!selected || typeof selected !== 'object') return null;
        return {
            id: String(selected.id || preferredId || ''),
            command: String(selected.command || '').trim(),
            cwd: String(selected.cwd || '').trim(),
            status: String(selected.status || '').toLowerCase(),
            line_count: Number(selected.line_count || 0),
            transcript: String(selected.transcript || ''),
            output_full: String(selected.output_full || ''),
            output_tail: String(selected.output_tail || ''),
            started_at: selected.started_at || null,
            updated_at: selected.updated_at || null,
            exit_code: selected.exit_code,
            timeout_sec: selected.timeout_sec,
        };
    }, []);

    const isTerminalFinal = useCallback((status) => {
        const s = String(status || '').toLowerCase();
        return ['success', 'error', 'timeout', 'failed', 'cancelled', 'complete', 'succeeded'].includes(s);
    }, []);

    const syncTerminalCardForWork = useCallback((workId, terminalState, fallbackStatus = '') => {
        if (!workId || !terminalState) return;
        const key = String(workId);
        let tracked = terminalCardByWorkRef.current.get(key) || {};
        if (tracked.mediaId) {
            const exists = (msmRef.current?.mediaList || []).some((item) => item.id === tracked.mediaId);
            if (!exists) {
                terminalCardByWorkRef.current.delete(key);
                tracked = {};
            }
        }
        const terminalId = String(terminalState.id || '');
        const dismissed = terminalDismissedRef.current.get(key);
        if (dismissed && terminalId && dismissed.terminalId === terminalId) return;

        const effectiveStatus = String(terminalState.status || fallbackStatus || '').toLowerCase() || 'running';
        const running = !isTerminalFinal(effectiveStatus);
        const label = terminalState.command || terminalId || `work ${key.slice(0, 8)}`;
        const payload = {
            work_id: key,
            terminal_id: terminalId,
            terminal_status: effectiveStatus,
            command: terminalState.command || label,
            cwd: terminalState.cwd || '',
            line_count: Number(terminalState.line_count || 0),
            transcript: terminalState.transcript || '',
            output_full: terminalState.output_full || '',
            output_tail: terminalState.output_tail || '',
            updated_at: terminalState.updated_at || Date.now(),
            title: `Terminal · ${label.slice(0, 56)}`,
        };

        if (tracked.mediaId) {
            msmPatchPayloadRef.current(tracked.mediaId, payload);
            msmSetPinnedRef.current(tracked.mediaId, running);
            terminalCardByWorkRef.current.set(key, { mediaId: tracked.mediaId, terminalId, status: effectiveStatus });
            return;
        }

        const mediaId = msmAddRef.current(payload, 'TERMINAL');
        if (!mediaId) return;
        msmSetPinnedRef.current(mediaId, running);
        terminalCardByWorkRef.current.set(key, { mediaId, terminalId, status: effectiveStatus });
    }, [isTerminalFinal]);

    const stopTerminalTracking = useCallback((workId) => {
        const key = String(workId || '');
        if (!key) return;
        const t = terminalTrackerTimersRef.current.get(key);
        if (t) {
            clearInterval(t);
            terminalTrackerTimersRef.current.delete(key);
        }
    }, []);

    const handlePopupClose = useCallback((mediaId) => {
        if (!mediaId) return;
        const item = (msmRef.current?.mediaList || []).find((m) => m.id === mediaId);
        if (item?.type === 'TERMINAL') {
            const workId = String(item?.payload?.work_id || '');
            const terminalId = String(item?.payload?.terminal_id || '');
            if (workId) {
                terminalDismissedRef.current.set(workId, { terminalId, ts: Date.now() });
                stopTerminalTracking(workId);
                terminalCardByWorkRef.current.delete(workId);
            }
        }
        msmRemoveRef.current(mediaId);
    }, [stopTerminalTracking]);

    const startTerminalTracking = useCallback((workId) => {
        const key = String(workId || '');
        if (!key || terminalTrackerTimersRef.current.has(key)) return;

        const poll = async () => {
            try {
                const snap = await api.get(`/tasks/works/${key}?requester_session_id=${encodeURIComponent(state.textState.sessionId || '')}`);
                const terminal = extractTerminalFromWorkSnapshot(snap);
                const workStatus = String(snap?.status || '').toLowerCase();
                if (terminal) {
                    syncTerminalCardForWork(key, terminal, workStatus);
                    if (isTerminalFinal(terminal.status)) {
                        stopTerminalTracking(key);
                    }
                    return;
                }
                if (['complete', 'succeeded', 'failed', 'cancelled'].includes(workStatus)) {
                    stopTerminalTracking(key);
                }
            } catch (_) {
                // Keep silent, tracker will retry while active.
            }
        };

        poll();
        const timer = setInterval(poll, 1000);
        terminalTrackerTimersRef.current.set(key, timer);
    }, [extractTerminalFromWorkSnapshot, isTerminalFinal, state.textState.sessionId, stopTerminalTracking, syncTerminalCardForWork]);

    useEffect(() => () => {
        terminalTrackerTimersRef.current.forEach((timer) => clearInterval(timer));
        terminalTrackerTimersRef.current.clear();
    }, []);

    useEffect(() => {
        terminalTrackerTimersRef.current.forEach((timer) => clearInterval(timer));
        terminalTrackerTimersRef.current.clear();
        terminalCardByWorkRef.current.clear();
        terminalDismissedRef.current.clear();
    }, [state.textState.sessionId]);

    // Voice Integration
    const voice = useVoice({
        sessionId: state.textState.sessionId,
        sendMessage: (msg) => {
            if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify(msg));
            }
        },
        onError: (err) => toast.error("Microphone error: " + err.message)
    });

    // Audio Playback for TTS Streaming
    const audioContextRef = useRef(null);
    const audioQueueRef = useRef([]);
    const isPlayingRef = useRef(false);
    const activeAudioSourceRef = useRef(null); // Ref for immediate cancellation
    const ttsAnalyserRef = useRef(null);
    const [ttsIntensity, setTtsIntensity] = useState(0);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [fullscreenTerminalMediaId, setFullscreenTerminalMediaId] = useState(null);
    const fullscreenTerminalBodyRef = useRef(null);

    const playNextChunk = useCallback(async () => {
        if (audioQueueRef.current.length === 0 || isPlayingRef.current) return;

        isPlayingRef.current = true;
        if (!audioContextRef.current) audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)();

        const b64Data = audioQueueRef.current.shift();
        try {
            const binaryString = window.atob(b64Data);
            const len = binaryString.length;
            const bytes = new Uint8Array(len);
            for (let i = 0; i < len; i++) bytes[i] = binaryString.charCodeAt(i);

            const audioBuffer = await audioContextRef.current.decodeAudioData(bytes.buffer);
            const source = audioContextRef.current.createBufferSource();

            if (!ttsAnalyserRef.current) {
                ttsAnalyserRef.current = audioContextRef.current.createAnalyser();
                ttsAnalyserRef.current.fftSize = 256;
            }

            source.buffer = audioBuffer;
            source.connect(ttsAnalyserRef.current);
            ttsAnalyserRef.current.connect(audioContextRef.current.destination);

            source.onended = () => {
                if (activeAudioSourceRef.current === source) {
                    activeAudioSourceRef.current = null;
                }
                isPlayingRef.current = false;
                setTtsIntensity(0);

                if (audioQueueRef.current.length === 0) {
                    // Auto-Listen: Return to listening state when all audio is done
                    dispatch({ type: 'UPDATE_VOICE', payload: { status: 'listening', isActive: true } });
                } else {
                    playNextChunk();
                }
            };
            activeAudioSourceRef.current = source;
            source.start(0);

            // TTS Level Monitor
            const dataArray = new Uint8Array(ttsAnalyserRef.current.frequencyBinCount);
            const interval = setInterval(() => {
                if (!isPlayingRef.current) {
                    clearInterval(interval);
                    return;
                }
                ttsAnalyserRef.current.getByteFrequencyData(dataArray);
                let sum = 0;
                for (let i = 0; i < 10; i++) sum += dataArray[i];
                setTtsIntensity(sum / 10 / 255);
            }, 50);
        } catch (e) {
            console.error("Audio playback error:", e);
            isPlayingRef.current = false;
            playNextChunk();
        }
    }, []);

    useEffect(() => {
        const handleFullscreenChange = () => {
            const isFS = !!document.fullscreenElement;
            setIsFullscreen(isFS);
            if (isFS) {
                document.body.classList.add('fullscreen-mode');
            } else {
                document.body.classList.remove('fullscreen-mode');
            }
        };

        document.addEventListener('fullscreenchange', handleFullscreenChange);
        return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
    }, []);

    const fullscreenTerminalItem = (msm.mediaList || []).find((m) => m.id === fullscreenTerminalMediaId) || null;
    const fullscreenTerminalPayload = fullscreenTerminalItem?.payload || null;

    useEffect(() => {
        if (!fullscreenTerminalBodyRef.current || !fullscreenTerminalPayload) return;
        fullscreenTerminalBodyRef.current.scrollTop = fullscreenTerminalBodyRef.current.scrollHeight;
    }, [fullscreenTerminalPayload?.transcript, fullscreenTerminalPayload?.output_full, fullscreenTerminalPayload?.output_tail, fullscreenTerminalPayload?.line_count]);

    useEffect(() => {
        if (fullscreenTerminalMediaId && !fullscreenTerminalItem) {
            setFullscreenTerminalMediaId(null);
        }
    }, [fullscreenTerminalMediaId, fullscreenTerminalItem]);

    useEffect(() => {
        const onKeyDown = (e) => {
            if (e.key === 'Escape') setFullscreenTerminalMediaId(null);
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, []);

    const toggleFullscreen = () => {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(err => {
                console.error(`Error attempting to enable full-screen mode: ${err.message}`);
            });
        } else {
            if (document.exitFullscreen) {
                document.exitFullscreen();
            }
        }
    };

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
                    api.get('/system/status'),
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
        const wsUrl = `${protocol}//${window.location.host}/ws/${sessionId}`;
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
                    const statusWorkId = data.payload?.work_id || data.work_id || null;
                    const approvalReq = (data.payload?.approval_request && typeof data.payload.approval_request === 'object')
                        ? data.payload.approval_request
                        : null;

                    if (statusWorkId && (phase === 'waiting_user' || approvalReq)) {
                        const approvalPrompt = String(
                            approvalReq?.prompt
                            || data.payload?.message
                            || data.message
                            || 'Esta tarefa precisa da sua aprovação para continuar.'
                        ).trim();
                        const approvalKey = JSON.stringify({
                            workId: String(statusWorkId),
                            action: String(approvalReq?.action_id || approvalReq?.action || ''),
                            prompt: approvalPrompt,
                            args: approvalReq?.args || null
                        });
                        const existing = approvalCardByWorkRef.current.get(String(statusWorkId));
                        const approvalPayload = {
                            work_id: statusWorkId,
                            approval_request: approvalReq,
                            approval_prompt: approvalPrompt,
                            status_message: data.payload?.message || data.message || '',
                            approval_key: approvalKey,
                            title: 'Permission Required',
                        };

                        if (existing?.mediaId) {
                            msmPatchPayloadRef.current(existing.mediaId, approvalPayload);
                            msmFocusRef.current(existing.mediaId);
                            approvalCardByWorkRef.current.set(String(statusWorkId), { ...existing, approvalKey });
                        } else {
                            const mediaId = msmAddRef.current(approvalPayload, 'APPROVAL');
                            if (mediaId) {
                                approvalCardByWorkRef.current.set(String(statusWorkId), { mediaId, approvalKey });
                                dispatch({
                                    type: 'ADD_MESSAGE',
                                    payload: {
                                        id: `approval_notice_${statusWorkId}_${Date.now()}`,
                                        role: 'assistant',
                                        content: `Preciso da sua aprovação para continuar esta tarefa. ${approvalPrompt}`,
                                        timestamp: Date.now(),
                                        work_id: statusWorkId
                                    }
                                });
                            }
                        }
                    } else if (statusWorkId) {
                        const existing = approvalCardByWorkRef.current.get(String(statusWorkId));
                        if (existing?.mediaId) {
                            msmRemoveRef.current(existing.mediaId);
                            approvalCardByWorkRef.current.delete(String(statusWorkId));
                        }
                    }

                    if (isExecuting) {
                        dispatch({ type: 'START_EXECUTION', payload: { status: phase, message: data.message } });
                    } else if (isTerminal) {
                        dispatch({ type: 'END_EXECUTION' });
                    }

                    if (statusWorkId && !isTerminal) {
                        startTerminalTracking(statusWorkId);
                    } else if (statusWorkId && isTerminal) {
                        stopTerminalTracking(statusWorkId);
                    }

                    const statusPlayback = (data.payload?.playback && typeof data.payload.playback === 'object')
                        ? data.payload.playback
                        : null;
                    if (statusPlayback?.run_id) {
                        syncPlaybackCard(statusPlayback.run_id, {
                            sessionId: String(statusPlayback.session_id || state.textState.sessionId || ''),
                            status: String(statusPlayback.status || phase || ''),
                            work_id: statusWorkId,
                            title: 'Session Playback',
                        });
                    }
                }
                // Voice Protocol Handlers
                else if (data.type === 'voice.state') {
                    const currentStatus = state.voiceState.status;
                    if (data.state === 'listening' && (currentStatus === 'thinking' || currentStatus === 'speaking' || isPlayingRef.current || audioQueueRef.current.length > 0)) return;
                    if (data.state === 'thinking' || data.state === 'idle') {
                        dispatch({ type: 'UPDATE_VOICE', payload: { phrase: '' } });
                    }
                    dispatch({ type: 'UPDATE_VOICE', payload: { status: data.state, isActive: data.state !== 'idle' } });
                } else if (data.type === 'asr.partial' || data.type === 'asr.final') {
                    dispatch({ type: 'UPDATE_VOICE', payload: { phrase: data.text } });
                } else if (data.type === 'orb.intensity') {
                    dispatch({ type: 'UPDATE_VOICE', payload: { intensity: data.intensity } });
                } else if (data.type === 'tts.chunk') {
                    // Transition to speaking state as soon as we get audio chunks
                    dispatch({ type: 'UPDATE_VOICE', payload: { status: 'speaking', isActive: true } });
                    audioQueueRef.current.push(data.b64);
                    playNextChunk();
                } else if (data.type === 'control.cancel') {
                    audioQueueRef.current = [];
                    if (activeAudioSourceRef.current) {
                        try {
                            activeAudioSourceRef.current.stop();
                        } catch (e) { /* ignore if already stopped */ }
                        activeAudioSourceRef.current = null;
                    }
                    isPlayingRef.current = false;
                    setTtsIntensity(0);
                } else if (data.type === 'media') {
                    const mediaType = String(data.payload?.media_type || '').toUpperCase() || 'IMAGE';
                    const payload = data.payload || {};
                    const rawMediaUrl = String(payload?.url || payload?.link || payload?.canonicalUrl || '').trim();
                    const rawMediaContent = String(payload?.content || payload?.fullContent || '').trim();
                    const isYouTubeSystemAsset = mediaType === 'LINK'
                        && !!(extractYouTubeId(rawMediaUrl) || extractYouTubeId(rawMediaContent));
                    if (isYouTubeSystemAsset) return;
                    const mediaWorkId = payload.work_id || payload?.context?.work_id || null;
                    const normalizedPayload = (() => {
                        if (mediaType !== 'DEEZER') return { ...payload, work_id: mediaWorkId };
                        const bestCandidate = (payload?.best && typeof payload.best === 'object')
                            ? payload.best
                            : ((Array.isArray(payload?.results) && payload.results.length > 0 && typeof payload.results[0] === 'object') ? payload.results[0] : {});
                        const explicitTrackId = String(
                            payload?.trackId
                            || payload?.track_id
                            || payload?.id
                            || payload?.best?.id
                            || payload?.result?.id
                            || bestCandidate?.id
                            || ''
                        ).trim();
                        const urls = [
                            payload?.url,
                            payload?.best?.url,
                            payload?.result?.url,
                            ...(Array.isArray(payload?.results) ? payload.results.map((r) => r?.url) : []),
                        ].map((u) => String(u || '').trim()).filter(Boolean);
                        const urlTrackIds = urls.map((u) => extractDeezerTrackId(u)).filter(Boolean);
                        const trackIds = [...new Set([explicitTrackId, ...urlTrackIds].filter(Boolean))];
                        const inferredMeta = parseDeezerMetaFromText(payload?.content || '');
                        const bestArtist = typeof bestCandidate?.artist === 'string'
                            ? bestCandidate.artist
                            : (bestCandidate?.artist?.name || '');
                        return {
                            ...payload,
                            work_id: mediaWorkId,
                            trackId: trackIds[0] || '',
                            trackIds,
                            url: urls[0] || (trackIds[0] ? `https://www.deezer.com/track/${trackIds[0]}` : (payload?.url || '')),
                            title: String(payload?.title || bestCandidate?.title || inferredMeta.title || 'Deezer Track'),
                            artist: String(payload?.artist || bestArtist || inferredMeta.artist || ''),
                            cover: String(payload?.cover || bestCandidate?.cover || ''),
                        };
                    })();
                    if (['WEATHER', 'SYSTEM_HEALTH', 'MAP', 'WIKI', 'CHART'].includes(mediaType)) {
                        if (claimAssistCardSlot(mediaWorkId, mediaType)) {
                            msmAddRef.current(normalizedPayload, mediaType);
                        }
                    } else {
                        msmAddRef.current(normalizedPayload, mediaType);
                    }
                } else if (data.type === 'playback' || data.type === 'terminal_update') {
                    dispatch({ type: 'START_EXECUTION', payload: { status: 'RUNTIME_ACTIVE' } });
                    if (data.type === 'terminal_update') {
                        const termPayload = (data.payload && typeof data.payload === 'object') ? data.payload : {};
                        const termState = (termPayload.terminal && typeof termPayload.terminal === 'object')
                            ? termPayload.terminal
                            : termPayload;
                        const workId = termPayload.work_id || termState.work_id || data.work_id || null;
                        if (workId) {
                            if (termState && typeof termState === 'object' && (termState.id || termState.command || termState.transcript || termState.output_tail || termState.output_full)) {
                                syncTerminalCardForWork(workId, {
                                    id: termState.id || termState.terminal_id || '',
                                    command: termState.command || '',
                                    cwd: termState.cwd || '',
                                    status: termState.status || termState.terminal_status || 'running',
                                    line_count: termState.line_count || 0,
                                    transcript: termState.transcript || '',
                                    output_full: termState.output_full || '',
                                    output_tail: termState.output_tail || '',
                                    updated_at: termState.updated_at || Date.now(),
                                });
                                if (isTerminalFinal(termState.status || termState.terminal_status || '')) {
                                    stopTerminalTracking(workId);
                                } else {
                                    startTerminalTracking(workId);
                                }
                            } else {
                                startTerminalTracking(workId);
                            }
                        }
                    }
                }

                if (data.type === 'message_added' && data.session_id === sessionId) {
                    if (data.message?.role !== 'system') {
                        dispatch({ type: 'ADD_MESSAGE', payload: data.message });

                        const msg = data.message || {};
                        const content = String(msg.content || '').trim();
                        if (!content) return;
                        const workId = msg.work_id || msg?.context?.work_id || null;
                        const skillHints = [
                            ...(Array.isArray(msg?.skills_used) ? msg.skills_used : []),
                            ...(Array.isArray(msg?.context?.data?.skills_used) ? msg.context.data.skills_used : []),
                        ];
                        const actionHints = [
                            ...(Array.isArray(msg?.actions_used) ? msg.actions_used : []),
                            ...(Array.isArray(msg?.context?.data?.actions_used) ? msg.context.data.actions_used : []),
                        ];
                        const sourceHints = [
                            ...(Array.isArray(msg?.sources_used) ? msg.sources_used : []),
                            ...(Array.isArray(msg?.context?.data?.sources_used) ? msg.context.data.sources_used : []),
                        ];

                        const looksLikeNoise =
                            /^(\{|\}|\[|\]|,|:|")+$/.test(content) ||
                            /^(thinking|processando|executando|respondendo|aguarde)\.*$/i.test(content);
                        if (looksLikeNoise) return;

                        const hasSignal = (items, re) => (Array.isArray(items) ? items : []).some((it) => re.test(String(it || '')));
                        const weatherSignal = hasSignal(skillHints, /weather|weather_control|weather\.control/i) || hasSignal(actionHints, /weather|forecast/i);
                        const systemSignal = hasSignal(skillHints, /system[\._-]?health|host[\._-]?health|system[\._-]?status/i) || hasSignal(actionHints, /system[\._-]?health|system[\._-]?status/i);
                        const mapSignal = hasSignal(skillHints, /maps?|google[\._-]?maps|openstreetmap/i) || hasSignal(actionHints, /maps?|map/i);
                        const wikiSignal = hasSignal(skillHints, /wiki|wikipedia/i) || hasSignal(actionHints, /wiki|wikipedia/i);
                        const chartSignal = !!tryParseMarkdownTable(content);
                        const weatherReport = /(temperatura|sens[aã]ção|umidade|vento|weather|forecast|clima)/i.test(content) && /(°c|umidade|vento|humidity|wind)/i.test(content);
                        const systemReport = /(cpu|mem[oó]ria|memory|disk|disco|load|uptime|network|rede)/i.test(content) && /(%|gb|mb|tb|rx|tx)/i.test(content);
                        const mapReport = /(google\.[^ ]*\/maps|openstreetmap\.org|maps\.google)/i.test(content);
                        const wikiReport = /wikipedia\.org\/wiki\//i.test(content);

                        const commonPayload = {
                            content,
                            work_id: workId,
                            skills_used: skillHints,
                            actions_used: actionHints,
                            sources_used: sourceHints,
                        };

                        // 1. YouTube Detection (Synchronized with LinkPreviewCard)
                        const ytMatchId = extractYouTubeId(content);
                        if (ytMatchId && ytMatchId.length === 11) {
                            const urls = extractUrlsFromText(content);
                            const rawYtUrl = urls.find((u) => !!extractYouTubeId(u)) || urls[0] || '';
                            const canonicalYtUrl = `https://www.youtube.com/watch?v=${ytMatchId}`;
                            msmRef.current.addMedia(
                                {
                                    ...commonPayload,
                                    videoId: ytMatchId,
                                    title: 'YouTube Video',
                                    url: rawYtUrl || canonicalYtUrl,
                                    canonicalUrl: canonicalYtUrl
                                },
                                'YOUTUBE'
                            );
                        }
                        // 1.1 Deezer Track Detection (Music mini-player)
                        else {
                            const urls = extractUrlsFromText(content);
                            const deezerTrackIds = urls
                                .map((u) => extractDeezerTrackId(u))
                                .filter(Boolean);
                            if (deezerTrackIds.length > 0) {
                                const uniqueTrackIds = [...new Set(deezerTrackIds)];
                                const primaryId = uniqueTrackIds[0];
                                const primaryUrl = urls.find((u) => extractDeezerTrackId(u) === primaryId) || `https://www.deezer.com/track/${primaryId}`;
                                msmRef.current.addMedia(
                                    {
                                        ...commonPayload,
                                        trackId: primaryId,
                                        trackIds: uniqueTrackIds,
                                        url: primaryUrl,
                                        title: 'Deezer Track',
                                    },
                                    'DEEZER'
                                );
                                return;
                            }
                            const inferred = parseDeezerMetaFromText(content);
                            if ((/deezer/i.test(content) || /m[úu]sica:/i.test(content)) && (inferred.title || inferred.artist)) {
                                msmRef.current.addMedia(
                                    {
                                        ...commonPayload,
                                        trackId: '',
                                        trackIds: [],
                                        url: '',
                                        title: inferred.title || 'Deezer Track',
                                        artist: inferred.artist || '',
                                    },
                                    'DEEZER'
                                );
                                return;
                            }
                        }
                        // 2. Path / Resource Detection (e.g. screenshots from file system)
                        if (content.match(/(\/[a-zA-Z0-9\._\- \/]+\.(png|jpg|jpeg|gif|webp|mp4|webm|pdf|zip|txt|csv|json))/i)) {
                            const pathMatch = content.match(/(\/[a-zA-Z0-9\._\- \/]+\.(png|jpg|jpeg|gif|webp|mp4|webm|pdf|zip|txt|csv|json))/i);
                            msmRef.current.addMedia({ ...commonPayload, path: pathMatch[0], title: pathMatch[0].split('/').pop() }, 'IMAGE');
                        }
                        // 3. Image URL Detection
                        else if (content.match(/\.(jpg|jpeg|png|gif|webp|svg)(\?.*)?$/i) || content.startsWith('IMAGE:')) {
                            const url = content.replace('IMAGE:', '').trim();
                            msmRef.current.addMedia({ ...commonPayload, url }, 'IMAGE');
                        }
                        // 4. Code Detection
                        else if (content.includes('```')) {
                            const codeMatch = content.match(/```(?:\w+)?\s*([\s\S]*?)```/);
                            if (codeMatch && codeMatch[1].trim()) {
                                msmRef.current.addMedia({ ...commonPayload, code: codeMatch[1].trim() }, 'CODE');
                            }
                        }
                        // 5. Assist Cards (strict trigger + one per work_id group)
                        else if (weatherSignal || weatherReport) {
                            if (claimAssistCardSlot(workId, 'WEATHER')) msmRef.current.addMedia(commonPayload, 'WEATHER');
                        }
                        else if (systemSignal || systemReport) {
                            if (claimAssistCardSlot(workId, 'SYSTEM_HEALTH')) msmRef.current.addMedia(commonPayload, 'SYSTEM_HEALTH');
                        }
                        else if (wikiSignal || wikiReport) {
                            if (claimAssistCardSlot(workId, 'WIKI')) msmRef.current.addMedia(commonPayload, 'WIKI');
                        }
                        else if (mapSignal || mapReport) {
                            if (claimAssistCardSlot(workId, 'MAP')) msmRef.current.addMedia(commonPayload, 'MAP');
                        }
                        else if (chartSignal) {
                            if (claimAssistCardSlot(workId, 'CHART')) msmRef.current.addMedia(commonPayload, 'CHART');
                        }
                        // 6. Link Detection (Fallback)
                        else {
                            const urlMatch = content.match(/https?:\/\/[^\s]+/);
                            if (urlMatch) {
                                const fallbackUrl = String(urlMatch[0] || '').trim();
                                const isYouTubeFallbackLink = !!(extractYouTubeId(fallbackUrl) || extractYouTubeId(content));
                                if (!isYouTubeFallbackLink) {
                                    msmRef.current.addMedia({ ...commonPayload, url: fallbackUrl, fullContent: content }, 'LINK');
                                }
                            }
                        }
                    }
                }

                if (data.type === 'playback' || data.type?.startsWith('playback.')) {
                    const playbackRunId = String(
                        data.run_id
                        || data.payload?.run_id
                        || data.payload?.playback?.run_id
                        || ''
                    ).trim();
                    if (playbackRunId) {
                        syncPlaybackCard(playbackRunId, {
                            sessionId: String(data.payload?.session_id || state.textState.sessionId || ''),
                            status: String(data.payload?.status || data.type || ''),
                            title: 'Session Playback',
                        });
                    }
                    if (data.payload?.type === 'image' || data.payload?.type === 'video') {
                        msmRef.current.addMedia(data.payload, data.payload.type.toUpperCase());
                    } else if (data.type === 'playback' && data.run_id) {
                        syncPlaybackCard(data.run_id, { title: 'Session Playback' });
                    }
                }
            } catch (e) {
                console.error("Dashboard WS Parse Error:", e);
            }
        };

        return () => ws.close();
    }, [state.textState.sessionId]);

    useEffect(() => {
        const onResize = () => setIsMobile(window.innerWidth <= 640);
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
    }, []);

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
            height: isMobile ? '100dvh' : '100vh', display: 'flex', overflow: 'hidden', color: 'var(--dashboard-text)',
            background: 'var(--dashboard-bg)',
            position: 'relative'
        }}>
            {/* Background Layer (Orb / System State) - Full Viewport Atmosphere (Moved to Root) */}
            <div style={{
                position: 'absolute', inset: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 0, pointerEvents: 'none',
                overflow: 'hidden'
            }}>
                <StageOrbLayer state={state} voice={voice} ttsIntensity={ttsIntensity} theme={theme} />
            </div>
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
                <header className="dashboard-internal-header" style={{
                    height: isMobile ? '52px' : '60px', padding: isMobile ? '0 12px' : '0 32px', display: 'flex', alignItems: 'center',
                    justifyContent: 'space-between', zIndex: 10, background: 'transparent'
                }}>
                    <div className="flex-center" style={{ gap: isMobile ? '8px' : '12px' }}>
                        <div style={{ color: 'var(--accent-color)', fontWeight: '900', letterSpacing: '0.1em', fontSize: isMobile ? '10px' : '11px', textTransform: 'uppercase' }}>
                            A.T.L.A.S | {state.textState.sessionName || 'DASHBOARD_ACTIVE'}
                        </div>
                        <button onClick={handleReload} className="flex-center" style={{
                            width: '24px', height: '24px', borderRadius: '4px', background: 'transparent',
                            border: '1px solid var(--card-border)', color: 'var(--text-muted)', cursor: 'pointer', transition: 'all 0.2s',
                            marginRight: '8px'
                        }} title="Reset Session">
                            <RefreshCw size={12} />
                        </button>
                        <button onClick={toggleFullscreen} className="flex-center" style={{
                            width: '24px', height: '24px', borderRadius: '4px', background: 'transparent',
                            border: '1px solid var(--card-border)', color: 'var(--text-muted)', cursor: 'pointer', transition: 'all 0.2s'
                        }} title={isFullscreen ? "Sair da Tela Cheia" : "Tela Cheia"}>
                            {isFullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
                        </button>
                    </div>
                </header>

                <div style={{ flex: 1, width: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>
                    {/* Background Layer moved to Root parent for global coverage */}

                    {/* STAGE AREA (Top: Media Overlap) */}
                    <div style={{ flex: 1, position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                        {/* Foreground Layer (Media / Focus) */}
                        <StageMediaLayer
                            mediaState={msm.mediaState}
                            onDockMedia={msm.dockMedia}
                            onResolveApproval={handleApprovalResolved}
                            onOpenTerminalFullscreen={setFullscreenTerminalMediaId}
                            sessionId={state.textState.sessionId}
                            isMobile={isMobile}
                        />

                        {/* Popups (Overlay) */}
                        <OverlayPopupStack
                            popups={msm.mediaState.popups}
                            onFocus={msm.focusMedia} onClose={handlePopupClose}
                            onPause={msm.pauseMediaExpiry} onResume={msm.resumeMediaExpiry}
                            onPin={msm.togglePinMedia} sessionId={state.textState.sessionId}
                        />
                    </div>

                    {/* DIALOGUE AREA (Bottom: Transcript + Input) */}
                    <div style={{
                        display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%',
                        paddingBottom: isMobile ? '8px' : '16px', zIndex: 20,
                        maskImage: 'linear-gradient(to bottom, transparent, black 15%)',
                        WebkitMaskImage: 'linear-gradient(to bottom, transparent, black 15%)'
                    }}>
                        {/* Minimal Transcript Layer */}
                        {!isMobile && <div style={{ width: '100%', maxWidth: '800px', padding: '0 40px', pointerEvents: 'auto', marginBottom: '8px' }}>
                            <HeroTranscriptRenderer
                                history={state.textState.history}
                                isSending={state.textState.isSending}
                                executionStatus={state.executionState.status}
                            />
                        </div>}
                        {/* Floating Interaction Area */}
                        <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: isMobile ? '0 10px' : '0 40px', gap: isMobile ? '8px' : '16px' }}>
                            {/* Mode Toggles (Outside) */}
                            <div className="flex-center" style={{ gap: isMobile ? '6px' : '8px' }}>
                                {/* Mode Toggle: Keyword */}
                                <button
                                    type="button"
                                    onClick={() => dispatch({ type: 'SET_VOICE_MODE', payload: state.voiceMode === 'keyword' ? 'manual' : 'keyword' })}
                                    className="flex-center glass"
                                    disabled={state.voiceMode === 'live'}
                                    style={{
                                        width: isMobile ? '38px' : '42px', height: isMobile ? '38px' : '42px', borderRadius: isMobile ? '12px' : '14px',
                                        background: state.voiceMode === 'keyword' ? 'var(--accent-color)' : 'rgba(var(--accent-rgb), 0.03)',
                                        border: '1px solid var(--card-border)',
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
                                    onClick={() => {
                                        const newMode = state.voiceMode === 'live' ? 'manual' : 'live';
                                        dispatch({ type: 'SET_VOICE_MODE', payload: newMode });
                                        if (newMode === 'live') {
                                            voice.startRecording();
                                        } else {
                                            voice.stopRecording();
                                        }
                                    }}
                                    className="flex-center glass"
                                    disabled={state.voiceMode === 'keyword'}
                                    style={{
                                        width: isMobile ? '38px' : '42px', height: isMobile ? '38px' : '42px', borderRadius: isMobile ? '12px' : '14px',
                                        background: state.voiceMode === 'live' ? 'var(--accent-color)' : 'rgba(var(--accent-rgb), 0.03)',
                                        border: '1px solid var(--card-border)',
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
                                maxWidth: isMobile ? 'none' : '800px',
                                minWidth: 0,
                                display: 'flex',
                                justifyContent: 'center',
                                transition: 'all 0.3s cubic-bezier(0.19, 1, 0.22, 1)'
                            }}>
                                {state.voiceMode === 'live' ? (
                                    <div
                                        className="glass pulse-slow"
                                        onClick={() => {
                                            dispatch({ type: 'SET_VOICE_MODE', payload: 'manual' });
                                            voice.stopRecording();
                                        }}
                                        style={{
                                            width: isMobile ? '46px' : '54px', height: isMobile ? '46px' : '54px', borderRadius: '50%',
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
                                        width: '100%', height: isMobile ? '48px' : '54px', borderRadius: isMobile ? '22px' : '27px',
                                        display: 'flex', alignItems: 'center', padding: isMobile ? '0 12px' : '0 20px', gap: isMobile ? '10px' : '16px',
                                        border: '1px solid var(--card-border)', backdropFilter: 'blur(40px)',
                                        boxShadow: 'var(--shadow-xl)', transition: 'all 0.3s ease'
                                    }}>
                                        <div style={{ color: 'var(--accent-color)', opacity: 0.8 }}><Activity size={isMobile ? 16 : 20} /></div>
                                        <form onSubmit={handleSubmit} style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
                                            <input
                                                value={state.textState.input}
                                                onChange={(e) => dispatch({ type: 'SET_TEXT', payload: { input: e.target.value } })}
                                                placeholder="Ask Atlas anything..."
                                                style={{
                                                    flex: 1, background: 'none', border: 'none', color: 'var(--dashboard-text)',
                                                    fontSize: isMobile ? '14px' : '15px', outline: 'none', fontFamily: 'inherit', minWidth: 0
                                                }}
                                            />
                                            <div className="flex-center" style={{ gap: '10px' }}>
                                                {!isMobile && <div style={{ width: '1px', height: '20px', background: 'rgba(255,255,255,0.1)', margin: '0 4px' }} />}
                                                {!isMobile && <Terminal size={16} style={{ opacity: 0.4 }} />}
                                                <button type="submit" className="flex-center" style={{
                                                    width: isMobile ? '32px' : '36px', height: isMobile ? '32px' : '36px', borderRadius: isMobile ? '9px' : '10px',
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
                <div style={{ height: isMobile ? '8px' : '24px' }} />
            </main>
            {fullscreenTerminalPayload && createPortal(
                <div
                    style={{
                        position: 'fixed',
                        inset: 0,
                        zIndex: DASHBOARD_Z.FULLSCREEN_TERMINAL,
                        background: 'rgba(0,0,0,0.78)',
                        backdropFilter: 'blur(3px)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: '20px',
                    }}
                    onClick={() => setFullscreenTerminalMediaId(null)}
                >
                    <div
                        style={{
                            width: 'min(1200px, 100%)',
                            height: 'min(86vh, 860px)',
                            border: '1px solid var(--card-border)',
                            borderRadius: '12px',
                            overflow: 'hidden',
                            background: 'rgba(2,6,18,0.98)',
                            display: 'flex',
                            flexDirection: 'column',
                        }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', padding: '10px 12px', borderBottom: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.03)' }}>
                            <div style={{ minWidth: 0 }}>
                                <p style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'monospace', fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {String(fullscreenTerminalPayload?.command || fullscreenTerminalPayload?.terminal_id || 'terminal')}
                                </p>
                                <p style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {String(fullscreenTerminalPayload?.cwd || '')}
                                </p>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                                <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{Number(fullscreenTerminalPayload?.line_count || 0)} lines</span>
                                <button className="btn-ghost" style={{ padding: '6px', borderRadius: '8px' }} onClick={() => setFullscreenTerminalMediaId(null)} title="Close">
                                    <X size={14} />
                                </button>
                            </div>
                        </div>
                        <div ref={fullscreenTerminalBodyRef} className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '14px', background: 'rgba(4,7,20,0.8)' }}>
                            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '12px', lineHeight: 1.5, color: '#d9e1ff', fontFamily: '"JetBrains Mono","Fira Code",monospace' }}>
                                {String(fullscreenTerminalPayload?.transcript || fullscreenTerminalPayload?.output_full || fullscreenTerminalPayload?.output_tail || `$ ${String(fullscreenTerminalPayload?.command || 'shell command')}\n(waiting for output...)`)}
                            </pre>
                        </div>
                    </div>
                </div>,
                document.body
            )}
        </div>
    );
};

export default Dashboard;
