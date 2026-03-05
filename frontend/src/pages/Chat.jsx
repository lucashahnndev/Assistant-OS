import { useState, useEffect, useRef, useMemo, memo } from 'react';
import { createPortal } from 'react-dom';
import { useAuth } from '../context/AuthContext';
import {
    WeatherAssistCard,
    SystemHealthAssistCard,
    DataChartAssistCard,
    WikiAssistCard,
    MapAssistCard,
} from '../components/AssistCards';
import { useAssistCards } from '../hooks/useAssistCards';

import { api } from '../hooks/api';
import PlaybackCard from '../components/PlaybackCard';
import LinkPreviewCard from '../components/LinkPreviewCard';
import ConfirmDialog from '../components/ConfirmDialog';
import toast from 'react-hot-toast';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import remarkBreaks from 'remark-breaks';
import {
    Send,
    Terminal,
    Plus,
    MessageSquare,
    Hash,
    Bot,
    Trash2,
    Globe,
    Cpu,
    Smartphone,
    Paperclip,
    File as FileIcon,
    X,
    CheckCircle2,
    Copy as CopyIcon,
    Files as FilesIcon,
    Check,
    Video,
    Music,
    FileText,
    MoreHorizontal,
    ChevronLeft,
    ChevronRight,
    ChevronDown,
    ChevronUp,
    RefreshCw,
    Edit,
    SendHorizontal,
    MessageCircle,
    Mic,
    FileCode,
    Archive,
    Table,
    Download,
    Monitor,
    Maximize2,
    ArrowUpRight,
    Square,
    CloudSun,
    HeartPulse,
    BarChart3,
    BookOpen
} from 'lucide-react';

const SessionIcon = ({ source, size = 16 }) => {
    let icon = <Hash size={size} color="var(--text-muted)" />;
    let bgColor = 'rgba(255,255,255,0.1)';

    switch (source) {
        case 'telegram':
            icon = <SendHorizontal size={size} color="#fff" style={{ transform: 'rotate(-45deg)', marginTop: '-1px' }} />;
            bgColor = '#229ED9';
            break;
        case 'web':
        case 'portal':
            icon = <MessageCircle size={size} color="#fff" />;
            bgColor = 'var(--accent-color)';
            break;
        case 'console':
        case 'terminal':
            icon = <Terminal size={size} color="#fff" />;
            bgColor = '#1e293b';
            break;
        case 'voice':
            icon = <Mic size={size} color="#fff" />;
            bgColor = 'var(--success)';
            break;
    }

    return (
        <div style={{
            width: '100%',
            height: '100%',
            borderRadius: '50%',
            background: bgColor,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
        }}>
            {icon}
        </div>
    );
};

const SessionAvatar = ({ session, size = 40, showBadge = true, onClick }) => {
    const sessId = session?.session_id || session?.id;
    const initial = (session?.name || sessId || '?').charAt(0).toUpperCase();
    const colors = ['#ec4899', '#8b5cf6', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#84cc16'];
    const colorIndex = sessId ? sessId.charCodeAt(sessId.length - 1) % colors.length : 0;
    const bgColor = colors[colorIndex];
    const avatarUrl = session?.profile_picture ? `/api/sessions/${sessId}/files/${session.profile_picture}` : null;

    return (
        <div
            onClick={onClick}
            style={{
                position: 'relative',
                width: `${size}px`,
                height: `${size}px`,
                borderRadius: '50%',
                background: avatarUrl ? 'transparent' : bgColor,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontWeight: 'bold',
                fontSize: `${size * 0.45}px`,
                flexShrink: 0,
                cursor: onClick ? 'pointer' : 'default',
                boxShadow: '0 4px 10px rgba(0,0,0,0.15)',
                border: '1px solid rgba(255,255,255,0.05)',
                transition: 'var(--transition)'
            }}
            className={onClick ? "hover:ring-2 hover:ring-[var(--accent-color)]" : ""}
            title={onClick ? "Change Profile Picture" : ""}
        >
            {avatarUrl ? (
                <img
                    src={avatarUrl}
                    alt="Avatar"
                    style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }}
                    onError={(e) => {
                        e.target.style.display = 'none';
                        if (e.target.nextSibling) e.target.nextSibling.style.display = 'block';
                    }}
                />
            ) : null}
            <span style={{ display: avatarUrl ? 'none' : 'block' }}>{initial}</span>

            {showBadge && (
                <div style={{
                    position: 'absolute',
                    bottom: '-2px',
                    right: '-2px',
                    width: `${size * 0.38}px`,
                    height: `${size * 0.38}px`,
                    background: 'var(--card-bg)',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    border: '1px solid rgba(255,255,255,0.1)',
                    boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
                }}>
                    <SessionIcon source={session?.interface || session?.source} size={Math.max(8, size * 0.25)} />
                </div>
            )}
        </div>
    );
};

const CodeBlock = ({ node, inline, className, children, ...props }) => {
    const [copied, setCopied] = useState(false);
    const codeRef = useRef(null);
    const match = /language-(\w+)/.exec(className || '');
    const language = match ? match[1] : '';

    // Force block rendering if the content has newlines, even if parsed as inline markdown
    const hasNewlines = String(children).includes('\n');
    const isInline = (inline || !className) && !hasNewlines;

    const handleCopy = () => {
        const text = codeRef.current?.innerText || children.toString();
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        toast.success("Code copied!");
    };

    if (isInline) {
        return <code style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 4px', borderRadius: '4px', fontFamily: 'monospace', fontSize: '13px' }} {...props}>{children}</code>;
    }

    return (
        <div style={{
            position: 'relative',
            margin: '16px 0',
            borderRadius: '12px',
            overflow: 'hidden',
            border: '1px solid rgba(255,255,255,0.1)',
            background: 'rgba(0,0,0,0.3)'
        }}>
            {/* Header / Toolbar */}
            <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '8px 16px',
                background: 'rgba(255,255,255,0.05)',
                borderBottom: '1px solid rgba(255,255,255,0.05)'
            }}>
                <span style={{
                    fontSize: '11px',
                    fontWeight: '800',
                    textTransform: 'uppercase',
                    opacity: 0.5,
                    letterSpacing: '0.05em'
                }}>
                    {language || 'code'}
                </span>
                <button
                    onClick={handleCopy}
                    className="btn-ghost"
                    style={{
                        padding: '4px 10px',
                        height: 'auto',
                        minWidth: '60px',
                        background: 'rgba(255,255,255,0.08)',
                        borderRadius: '6px',
                        fontSize: '10px',
                        fontWeight: '800',
                        color: copied ? 'var(--success)' : 'var(--text-main)',
                        transition: 'var(--transition)',
                        border: '1px solid rgba(255,255,255,0.1)'
                    }}
                >
                    {copied ? 'COPIED' : 'COPY'}
                </button>
            </div>
            <pre style={{
                margin: 0,
                padding: '16px',
                overflow: 'auto',
                background: 'transparent'
            }}>
                <code className={className} {...props} ref={codeRef} style={{ fontSize: '13px', lineHeight: '1.6' }}>
                    {children}
                </code>
            </pre>
        </div>
    );
};

const getFileUrl = (item, sessionId) => {
    if (!item) return null;
    if (item.url) return item.url;
    if (!sessionId) return null;

    const rawPath = item.path || item.file_path || item.filename || item.name;
    if (!rawPath) return null;
    const normalizedPath = String(rawPath).replace(/\\/g, '/');

    // If the path already carries a session id on disk (e.g. .../data/sessions/{sid}/media/...),
    // preserve that source session instead of forcing the currently opened one.
    const diskSessionMatch = normalizedPath.match(/\/sessions\/([^/]+)\/(media|uploads)\/(.+)$/);
    if (diskSessionMatch) {
        const [, sourceSessionId, bucket, rest] = diskSessionMatch;
        return `/api/sessions/${sourceSessionId}/files/${bucket}/${rest}`;
    }

    if (normalizedPath.startsWith('/api/sessions/') && normalizedPath.includes('/files/')) {
        return normalizedPath;
    }

    if (normalizedPath.includes('/media/')) {
        const parts = normalizedPath.split('/media/');
        return `/api/sessions/${sessionId}/files/media/${parts[parts.length - 1]}`;
    }
    if (normalizedPath.startsWith('media/')) {
        return `/api/sessions/${sessionId}/files/${normalizedPath}`;
    }

    if (normalizedPath.includes('/uploads/')) {
        const parts = normalizedPath.split('/uploads/');
        return `/api/sessions/${sessionId}/files/uploads/${parts[parts.length - 1]}`;
    }
    if (normalizedPath.startsWith('uploads/')) {
        return `/api/sessions/${sessionId}/files/${normalizedPath}`;
    }

    if (normalizedPath.includes('data/')) {
        return `/api/static/${normalizedPath.split('data/')[1]}`;
    }

    return `/api/sessions/${sessionId}/files/${normalizedPath.replace(/^\/+/, '')}`;
};

const formatTime = (ts) => {
    if (!ts) return '';
    try {
        const date = new Date(typeof ts === 'number' && ts < 10000000000 ? ts * 1000 : ts);
        return isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
        return '';
    }
};

const formatDate = (ts) => {
    if (!ts) return '';
    try {
        const date = new Date(typeof ts === 'number' && ts < 10000000000 ? ts * 1000 : ts);
        if (isNaN(date.getTime())) return '';

        const today = new Date();
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        if (date.toDateString() === today.toDateString()) return 'Today';
        if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
        return date.toLocaleDateString();
    } catch (e) {
        return '';
    }
};

const tryParseIntentPayload = (content) => {
    if (typeof content !== 'string') return null;
    const text = content.trim();
    if (!text.startsWith('{') || !text.endsWith('}')) return null;

    try {
        const parsed = JSON.parse(text);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
        const keys = ['thought', 'plan', 'action', 'params'];
        const hasIntentKey = keys.some((k) => Object.prototype.hasOwnProperty.call(parsed, k));
        return hasIntentKey ? parsed : null;
    } catch {
        return null;
    }
};

const looksLikeInternalMonologue = (content) => {
    if (typeof content !== 'string') return false;
    const text = content.trim().toLowerCase();
    if (!text) return false;

    // High-confidence monologue starts only.
    if (
        text.startsWith('o usuário') ||
        text.startsWith('o usuario') ||
        text.startsWith('the user') ||
        text.startsWith('vou usar') ||
        text.startsWith('i will use')
    ) {
        return true;
    }

    // Avoid false positives on long, user-facing answers (e.g. vision descriptions with logs/markdown).
    if (text.length > 420) return false;

    // Strict planning cues: require clear action-planning language, not generic words.
    const strictCues = [
        'vou usar a ação',
        'vou usar a acao',
        'i will use the action',
        'my plan is',
        'plan:',
        '"action":',
        '"params":',
        'returning results'
    ];
    return strictCues.some((cue) => text.includes(cue));
};

const normalizeHistoryMessageType = (msg) => {
    const explicitType = String(msg?.type || msg?.msg_type || 'default').toLowerCase();
    if (explicitType !== 'default') return explicitType;
    if (msg?.role === 'assistant') {
        const payload = tryParseIntentPayload(msg?.content);
        if (payload && (payload.thought || payload.action)) return 'reasoning';
        if (looksLikeInternalMonologue(msg?.content)) return 'reasoning';
    }
    return explicitType;
};

const extractReasoningLine = (msg) => {
    const payload = tryParseIntentPayload(msg?.content);
    if (payload) {
        const thought = typeof payload.thought === 'string' ? payload.thought.trim() : '';
        if (thought) return thought;
        const action = typeof payload.action === 'string' ? payload.action.trim() : '';
        if (action && action !== 'reply' && action !== 'none') return `Planned action: ${action}`;
        if (action === 'reply' && payload.thought) return payload.thought;
    }
    if (looksLikeInternalMonologue(msg?.content)) {
        return String(msg.content || '').trim();
    }
    return null;
};

const toReasoningEntry = (line, ts = null) => {
    const text = String(line || '').trim();
    if (!text) return null;
    return { text, ts: ts || null };
};

const normalizeReasoningTimeline = (msg) => {
    if (Array.isArray(msg?.reasoningTimeline) && msg.reasoningTimeline.length > 0) {
        return msg.reasoningTimeline
            .map((entry) => {
                if (typeof entry === 'string') return toReasoningEntry(entry, msg?.timestamp);
                if (entry && typeof entry === 'object') return toReasoningEntry(entry.text || entry.line || entry.content, entry.ts || entry.timestamp || msg?.timestamp);
                return null;
            })
            .filter(Boolean);
    }
    if (Array.isArray(msg?.reasoningLines) && msg.reasoningLines.length > 0) {
        return msg.reasoningLines.map((line) => toReasoningEntry(line, msg?.timestamp)).filter(Boolean);
    }
    return [];
};

const groupHistoryWithReasoning = (rawHistory = []) => {
    const mergeUniqueStrings = (base = [], incoming = []) => {
        const out = [];
        const seen = new Set();
        [...(Array.isArray(base) ? base : []), ...(Array.isArray(incoming) ? incoming : [])].forEach((value) => {
            const s = String(value || '').trim();
            if (!s) return;
            const key = s.toLowerCase();
            if (seen.has(key)) return;
            seen.add(key);
            out.push(s);
        });
        return out;
    };
    // Infer missing work_id for assistant/system messages that are immediately
    // followed by a same-turn assistant message that does carry work_id.
    const history = rawHistory.map((msg) => ({ ...msg }));
    for (let i = 0; i < history.length; i += 1) {
        const current = history[i];
        if (!current || current.work_id || current.role === 'user') continue;
        if (current.role !== 'assistant' && current.role !== 'system') continue;
        for (let j = i + 1; j < history.length; j += 1) {
            const next = history[j];
            if (!next) break;
            if (next.role === 'user') break;
            if ((next.role === 'assistant' || next.role === 'system') && next.work_id) {
                current.work_id = next.work_id;
                break;
            }
        }
    }

    // Pass 1: collect all work units preserving insertion order
    const workUnitMap = new Map(); // work_id -> unit object
    const orderedKeys = [];        // work_ids in first-seen order (to preserve timeline)

    history.forEach((msg, rawIdx) => {
        const workId = msg.work_id;
        const role = msg.role;
        const type = normalizeHistoryMessageType(msg);

        // User messages always get their own bubble
        if (role === 'user') {
            const key = `__user_${rawIdx}`;
            orderedKeys.push(key);
            workUnitMap.set(key, msg);
            return;
        }

        // Assistant / system messages with a work_id → merge into Work Unit
        if (workId) {
            if (!workUnitMap.has(workId)) {
                // New work unit
                const unit = {
                    ...msg,
                    reasoningLines: [],
                    reasoningTimeline: [],
                    contentSegments: []
                };
                if (type === 'reasoning') {
                    const line = extractReasoningLine(msg);
                    if (line) {
                        unit.reasoningLines.push(line);
                        const entry = toReasoningEntry(line, msg.timestamp);
                        if (entry) unit.reasoningTimeline.push(entry);
                    }
                } else {
                    unit.contentSegments.push({
                        content: msg.content || '',
                        playback: msg.playback,
                        attachments: msg.attachments,
                        type
                    });
                }
                orderedKeys.push(workId);
                workUnitMap.set(workId, unit);
            } else {
                // Enrich existing unit
                const unit = workUnitMap.get(workId);
                if (type === 'reasoning') {
                    const line = extractReasoningLine(msg);
                    if (line && !unit.reasoningLines.includes(line)) {
                        unit.reasoningLines.push(line);
                        const entry = toReasoningEntry(line, msg.timestamp);
                        if (entry) unit.reasoningTimeline.push(entry);
                    }
                } else {
                    const segContent = msg.content || '';
                    if (segContent || msg.playback || (msg.attachments && msg.attachments.length > 0)) {
                        unit.contentSegments.push({
                            content: segContent,
                            playback: msg.playback,
                            attachments: msg.attachments,
                            type
                        });
                    }
                }
                // Keep latest timestamp / status
                if (msg.timestamp) unit.timestamp = msg.timestamp;
                if (msg.statusPhase) unit.statusPhase = msg.statusPhase;
                if (msg.statusMessage) unit.statusMessage = msg.statusMessage;
                if (msg.approvalRequest) unit.approvalRequest = msg.approvalRequest;
                if (msg.playback && !unit.playback) unit.playback = msg.playback;
                if (msg.isStreaming !== undefined) unit.isStreaming = msg.isStreaming;
                unit.skills_used = mergeUniqueStrings(unit.skills_used, msg.skills_used);
                unit.actions_used = mergeUniqueStrings(unit.actions_used, msg.actions_used);
            }
            return;
        }

        // Standalone assistant message (no work_id)
        const key = `__standalone_${rawIdx}`;
        orderedKeys.push(key);
        workUnitMap.set(key, { ...msg, reasoningLines: [], reasoningTimeline: [], contentSegments: [] });
    });

    // Pass 2: build output in timeline order (deduplicated)
    const seen = new Set();
    return orderedKeys.filter(k => {
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
    }).map(k => workUnitMap.get(k));
};

const SegmentDivider = () => (
    <div style={{
        padding: '12px 0',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        opacity: 0.15
    }}>
        <div style={{ flex: 1, height: '1px', background: 'var(--card-border)' }} />
        <span style={{ fontSize: '8px', fontWeight: '900', letterSpacing: '0.4em', color: 'var(--text-muted)', textTransform: 'uppercase' }}>_____</span>
        <div style={{ flex: 1, height: '1px', background: 'var(--card-border)' }} />
    </div>
);

const TypewriterMarkdown = ({ text, isStreaming, isComplete, isUser }) => {
    const [displayedText, setDisplayedText] = useState(text);

    useEffect(() => {
        if (!isStreaming || isComplete) {
            setDisplayedText(text);
            return;
        }
        if (text.length < displayedText.length) {
            setDisplayedText(text);
            return;
        }
        if (displayedText.length === text.length) return;

        const timeout = setTimeout(() => {
            setDisplayedText(prev => text.slice(0, prev.length + 2)); // Slightly faster reveal
        }, 8);

        return () => clearTimeout(timeout);
    }, [text, isStreaming, isComplete, displayedText]);

    return (
        <div className="markdown-content" style={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                rehypePlugins={[rehypeRaw]}
                components={{
                    code: CodeBlock,
                    p: ({ node, children, ...props }) => <div style={{ marginBottom: '12px' }} {...props}>{children}</div>,
                    ul: ({ node, ...props }) => <ul style={{ paddingLeft: '24px', marginBottom: '16px' }} {...props} />,
                    ol: ({ node, ...props }) => <ol style={{ paddingLeft: '24px', marginBottom: '16px', listStyleType: 'decimal' }} {...props} />,
                    li: ({ node, ...props }) => <li style={{ marginBottom: '8px' }} {...props} />,
                    strong: ({ node, ...props }) => <strong style={{ color: isUser ? '#fff' : 'var(--accent-color)', fontWeight: '800' }} {...props} />,
                    a: ({ node, ...props }) => <a style={{ color: isUser ? '#fff' : 'var(--accent-color)', textDecoration: 'underline', fontWeight: 'bold' }} target="_blank" rel="noreferrer" {...props} />
                }}
            >
                {displayedText}
            </ReactMarkdown>
            {isStreaming && !isComplete && displayedText.length > 0 && (
                <span style={{
                    display: 'inline-block',
                    width: '6px',
                    height: '14px',
                    background: 'var(--accent-color)',
                    marginLeft: '4px',
                    verticalAlign: 'middle',
                    animation: 'pulse 1s infinite'
                }} />
            )}
        </div>
    );
};

// ─── Work Unit Inspector ──────────────────────────────────────────────────────
const INSPECTOR_TABS = [
    { id: 'plan', label: 'Plan', emoji: '📋' },
    { id: 'thought', label: 'Thought', emoji: '🧠' },
    { id: 'terminal', label: 'Terminal', emoji: '🖥️' },
    { id: 'skills', label: 'Skills', emoji: '🛠️' },
    { id: 'media', label: 'Media', emoji: '📦' },
    { id: 'sources', label: 'Sources', emoji: '🔗' },
];

const stepStatusIcon = (status) => {
    switch (status) {
        case 'done': return { icon: '✓', color: '#10b981' };
        case 'in_progress': return { icon: '◉', color: 'var(--accent-color)' };
        case 'blocked': return { icon: '✕', color: '#ef4444' };
        default: return { icon: '○', color: 'var(--text-muted)' };
    }
};

const normalizeInspectorList = (value) => {
    if (!Array.isArray(value)) return [];
    return value
        .map((item) => {
            if (typeof item === 'string') return item;
            if (item && typeof item === 'object') {
                return item.name || item.id || item.key || item.path || item.file || JSON.stringify(item);
            }
            return String(item || '');
        })
        .map((entry) => String(entry || '').trim())
        .filter(Boolean);
};

const URL_EXTRACT_RE = /https?:\/\/[^\s<>)"'\]]+/gi;

const extractUrlsFromAny = (value) => {
    const text = typeof value === 'string' ? value : JSON.stringify(value || {});
    return [...new Set((String(text).match(URL_EXTRACT_RE) || []).map((u) => u.replace(/[.,;!?]+$/, '')))];
};

const WorkUnitInspector = ({ workId, sessionId, onExpand, inline = false, open: controlledOpen, onToggle, hideButton = false, hidePanel = false }) => {
    const [open, setOpen] = useState(false);
    const [activeTab, setActiveTab] = useState('plan');
    const [context, setContext] = useState(null);
    const [overwatch, setOverwatch] = useState(null);
    const [sessionPlaybackRuns, setSessionPlaybackRuns] = useState([]);
    const [expandedPlaybackRunId, setExpandedPlaybackRunId] = useState(null);
    const [fullscreenTerminalId, setFullscreenTerminalId] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const hasLoadedOnceRef = useRef(false);
    const fullscreenTerminalBodyRef = useRef(null);

    const uniqueStrings = (items = []) => {
        const seen = new Set();
        const out = [];
        for (const item of items) {
            const value = String(item || '').trim();
            if (!value || seen.has(value)) continue;
            seen.add(value);
            out.push(value);
        }
        return out;
    };

    const isEqualObject = (a, b) => {
        if (a === b) return true;
        try {
            return JSON.stringify(a) === JSON.stringify(b);
        } catch {
            return false;
        }
    };

    const mergeContextIncremental = (prev, next) => {
        if (!next || typeof next !== 'object') return prev || null;
        if (!prev || typeof prev !== 'object') return next;

        const prevPlanner = prev.planner && typeof prev.planner === 'object' ? prev.planner : {};
        const nextPlanner = next.planner && typeof next.planner === 'object' ? next.planner : {};
        const prevData = prev.data && typeof prev.data === 'object' ? prev.data : {};
        const nextData = next.data && typeof next.data === 'object' ? next.data : {};

        const mergedPlanLines = uniqueStrings([
            ...(Array.isArray(prevPlanner.plan) ? prevPlanner.plan : []),
            ...(Array.isArray(nextPlanner.plan) ? nextPlanner.plan : []),
        ]);
        const prevSteps = Array.isArray(prevPlanner.steps) ? prevPlanner.steps : [];
        const nextSteps = Array.isArray(nextPlanner.steps) ? nextPlanner.steps : [];
        const stepMap = new Map();
        prevSteps.forEach((s, i) => {
            const key = String(s?.id || `prev-${i}`);
            stepMap.set(key, s);
        });
        nextSteps.forEach((s, i) => {
            const key = String(s?.id || `next-${i}`);
            if (!stepMap.has(key)) {
                stepMap.set(key, s);
            }
        });
        const mergedSteps = [...stepMap.values()];

        const mergedData = {
            ...prevData,
            ...nextData,
            actions_used: uniqueStrings([
                ...(Array.isArray(prevData.actions_used) ? prevData.actions_used : []),
                ...(Array.isArray(nextData.actions_used) ? nextData.actions_used : []),
            ]),
            skills_used: uniqueStrings([
                ...(Array.isArray(prevData.skills_used) ? prevData.skills_used : []),
                ...(Array.isArray(nextData.skills_used) ? nextData.skills_used : []),
            ]),
            media_used: uniqueStrings([
                ...(Array.isArray(prevData.media_used) ? prevData.media_used : []),
                ...(Array.isArray(nextData.media_used) ? nextData.media_used : []),
            ]),
            sources_used: (() => {
                const all = [
                    ...(Array.isArray(prevData.sources_used) ? prevData.sources_used : []),
                    ...(Array.isArray(nextData.sources_used) ? nextData.sources_used : []),
                ];
                const seen = new Set();
                const out = [];
                for (const src of all) {
                    const url = String(src?.url || '').trim();
                    if (!url || seen.has(url)) continue;
                    seen.add(url);
                    out.push(src);
                }
                return out;
            })(),
        };

        const merged = {
            ...prev,
            ...next,
            planner: {
                ...prevPlanner,
                ...nextPlanner,
                plan: mergedPlanLines,
                steps: mergedSteps,
            },
            data: mergedData,
        };

        return isEqualObject(prev, merged) ? prev : merged;
    };

    const mergeOverwatchIncremental = (prev, next) => {
        if (!next || typeof next !== 'object') return prev || null;
        if (!prev || typeof prev !== 'object') return next;

        const prevEvents = Array.isArray(prev.events) ? prev.events : [];
        const nextEvents = Array.isArray(next.events) ? next.events : [];
        const seen = new Set(prevEvents.map((e) => `${e?.ts || ''}|${e?.event || ''}|${JSON.stringify(e?.payload || {})}`));
        const mergedEvents = [...prevEvents];
        for (const event of nextEvents) {
            const fp = `${event?.ts || ''}|${event?.event || ''}|${JSON.stringify(event?.payload || {})}`;
            if (seen.has(fp)) continue;
            seen.add(fp);
            mergedEvents.push(event);
        }

        const merged = {
            ...prev,
            ...next,
            events: mergedEvents,
        };
        return isEqualObject(prev, merged) ? prev : merged;
    };

    const load = async (force = false, silent = false) => {
        if (!force && (context || loading)) return;
        if (!silent) {
            if (!hasLoadedOnceRef.current) setLoading(true);
            setError(null);
        }
        try {
            const [ctxRes, owRes] = await Promise.allSettled([
                api.get(`/system/works/${workId}/context`),
                api.get(`/tasks/works/${workId}/overwatch?events_limit=400`),
            ]);
            if (ctxRes.status === 'fulfilled') {
                const nextContext = ctxRes.value?.context || ctxRes.value || {};
                setContext(prev => mergeContextIncremental(prev, nextContext));
                hasLoadedOnceRef.current = true;
            }
            if (owRes.status === 'fulfilled') {
                const nextOw = owRes.value || null;
                setOverwatch(prev => mergeOverwatchIncremental(prev, nextOw));
            }
            if (ctxRes.status !== 'fulfilled' && owRes.status !== 'fulfilled') {
                throw new Error('both context and overwatch failed');
            }
        } catch (e) {
            if (!silent) setError('Could not load work details.');
        } finally {
            if (!silent) setLoading(false);
        }
    };

    const isOpen = typeof controlledOpen === 'boolean' ? controlledOpen : open;

    const toggle = () => {
        if (!isOpen && !hidePanel) load(true);
        if (onToggle) onToggle(!isOpen);
        else setOpen(v => !v);
    };

    useEffect(() => {
        if (!isOpen || !workId || hidePanel) return undefined;

        load(true, false);
        const interval = setInterval(() => {
            load(true, true);
        }, 1000);

        return () => clearInterval(interval);
    }, [isOpen, workId]);

    useEffect(() => {
        if (!isOpen || !sessionId || hidePanel) return undefined;
        let cancelled = false;
        const fetchSessionPlaybackRuns = async () => {
            try {
                const response = await api.get(`/sessions/${sessionId}/playback`);
                if (cancelled) return;
                setSessionPlaybackRuns(Array.isArray(response?.runs) ? response.runs : []);
            } catch {
                if (!cancelled) setSessionPlaybackRuns([]);
            }
        };
        fetchSessionPlaybackRuns();
        return () => {
            cancelled = true;
        };
    }, [isOpen, sessionId, hidePanel]);

    const planner = context?.planner || {};
    const data = context?.data || {};
    const summary = context?.summary || {};
    const events = Array.isArray(overwatch?.events) ? overwatch.events : [];
    const steps = Array.isArray(planner.steps) ? planner.steps : [];
    const plan = Array.isArray(planner.plan) ? planner.plan : [];
    const skills = normalizeInspectorList(data.skills_used);
    const actions = normalizeInspectorList(data.actions_used);
    const media = normalizeInspectorList(data.media_used);
    const playbackRunIds = (() => {
        const ids = new Set();
        const fromContext = Array.isArray(data?.playback_runs) ? data.playback_runs : [];
        fromContext.forEach((id) => {
            const value = String(id || '').trim();
            if (value) ids.add(value);
        });
        const lastRun = String(data?.last_playback_run_id || '').trim();
        if (lastRun) ids.add(lastRun);
        return [...ids];
    })();
    const relatedPlaybackRuns = (() => {
        if (!Array.isArray(sessionPlaybackRuns) || sessionPlaybackRuns.length === 0) return [];
        if (playbackRunIds.length === 0) return [];
        const wanted = new Set(playbackRunIds);
        return sessionPlaybackRuns.filter((run) => wanted.has(String(run?.run_id || '').trim()));
    })();
    const thoughtTimeline = (() => {
        const entries = [];
        events.forEach((event) => {
            const payload = event?.payload || {};
            const thought = payload?.summary?.last_thought || payload?.thought || payload?.details;
            if (typeof thought === 'string' && thought.trim()) {
                entries.push({ text: thought.trim(), ts: event?.ts || null });
            }
        });
        if (entries.length === 0 && typeof summary?.last_thought === 'string' && summary.last_thought.trim()) {
            entries.push({ text: summary.last_thought.trim(), ts: context?.updated_at || null });
        }
        const dedup = [];
        entries.forEach((entry) => {
            if (!dedup.some((d) => d.text === entry.text)) dedup.push(entry);
        });
        return dedup;
    })();
    const sources = (() => {
        const set = new Set();
        extractUrlsFromAny(plan).forEach((u) => set.add(u));
        extractUrlsFromAny(data).forEach((u) => set.add(u));
        events.forEach((event) => extractUrlsFromAny(event?.payload || {}).forEach((u) => set.add(u)));
        return [...set];
    })();
    const shellTerminals = (() => {
        const terminalsMap = data?.shell?.terminals;
        if (!terminalsMap || typeof terminalsMap !== 'object') return [];
        return Object.values(terminalsMap)
            .filter((item) => item && typeof item === 'object')
            .sort((a, b) => {
                const ta = Number(a?.started_at || 0);
                const tb = Number(b?.started_at || 0);
                return tb - ta;
            });
    })();
    const fullscreenTerminal = shellTerminals.find((term) => String(term?.id || '') === String(fullscreenTerminalId || '')) || null;

    useEffect(() => {
        if (!fullscreenTerminalBodyRef.current || !fullscreenTerminalId) return;
        fullscreenTerminalBodyRef.current.scrollTop = fullscreenTerminalBodyRef.current.scrollHeight;
    }, [fullscreenTerminalId, shellTerminals]);

    const renderPlan = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {steps.length > 0 ? steps.map((s, i) => {
                const { icon, color } = stepStatusIcon(s.status);
                return (
                    <div key={s.id || i} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                        <span style={{ color, fontWeight: '900', fontSize: '12px', flexShrink: 0, minWidth: '12px', marginTop: '1px' }}>{icon}</span>
                        <span style={{ fontSize: '12px', color: s.status === 'done' ? 'var(--text-muted)' : 'var(--text-primary)', textDecoration: s.status === 'done' ? 'line-through' : 'none', opacity: s.status === 'done' ? 0.6 : 1 }}>
                            {s.title}
                        </span>
                    </div>
                );
            }) : plan.length > 0 ? plan.map((line, i) => (
                <div key={i} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                    <span style={{ color: 'var(--text-muted)', fontSize: '12px', flexShrink: 0 }}>{'›'}</span>
                    <span style={{ fontSize: '12px', color: 'var(--text-primary)' }}>{String(line).replace(/^\[.\]\s*/, '')}</span>
                </div>
            )) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No plan recorded.</span>}
        </div>
    );

    const renderSkills = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {skills.length > 0 && (
                <div>
                    <p style={{ fontSize: '9px', fontWeight: '900', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-muted)', marginBottom: '6px' }}>Skills</p>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {skills.map((s, i) => (
                            <span key={i} style={{ padding: '3px 10px', background: 'var(--accent-glow)', border: '1px solid var(--accent-color)', borderRadius: '20px', fontSize: '11px', color: 'var(--accent-color)', fontWeight: '700' }}>
                                {s}
                            </span>
                        ))}
                    </div>
                </div>
            )}
            {actions.length > 0 && (
                <div>
                    <p style={{ fontSize: '9px', fontWeight: '900', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-muted)', marginBottom: '6px' }}>Actions performed</p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {[...new Set(actions)].map((a, i) => (
                            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: 'var(--text-muted)', flexShrink: 0 }} />
                                <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{a}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {skills.length === 0 && actions.length === 0 && (
                <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No skills recorded.</span>
            )}
        </div>
    );

    const renderThought = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {thoughtTimeline.length > 0 ? thoughtTimeline.map((entry, i) => (
                <div key={i} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', padding: '8px', border: '1px solid var(--card-border)', borderRadius: '8px', background: 'rgba(0,0,0,0.04)' }}>
                    <span style={{ fontSize: '14px', lineHeight: 1 }}>🧠</span>
                    <div style={{ minWidth: 0 }}>
                        <p style={{ fontSize: '12px', color: 'var(--text-primary)' }}>{entry.text}</p>
                        {entry.ts && <p style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '3px' }}>{formatTime(entry.ts)}</p>}
                    </div>
                </div>
            )) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No thought timeline recorded.</span>}
        </div>
    );

    const renderTerminal = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {shellTerminals.length > 0 ? shellTerminals.map((term, i) => {
                const status = String(term?.status || '').toLowerCase();
                const termId = String(term?.id || `terminal-${i}`);
                const cmd = String(term?.command || '').trim();
                const lines = Number(term?.line_count || 0);
                const description = cmd || termId;
                const statusLabel = status === 'running'
                    ? 'running'
                    : (status === 'success' ? 'completed' : (status || 'error'));
                const statusColor = status === 'running' ? '#10b981' : status === 'success' ? '#22c55e' : status === 'timeout' ? '#f59e0b' : '#ef4444';
                return (
                    <div key={termId} style={{ border: '1px solid var(--card-border)', borderRadius: '8px', background: 'rgba(0,0,0,0.05)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', padding: '7px 9px' }}>
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace', minWidth: 0, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={description}>
                                {description}
                            </span>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                                <span style={{ fontSize: '9px', fontWeight: 800, color: statusColor, textTransform: 'lowercase', letterSpacing: '0.01em' }}>
                                    {statusLabel}
                                </span>
                                <button
                                    className="btn-ghost"
                                    style={{ padding: '2px', borderRadius: '6px' }}
                                    title="Open terminal fullscreen"
                                    onClick={() => setFullscreenTerminalId(termId)}
                                >
                                    <ArrowUpRight size={12} />
                                </button>
                            </div>
                        </div>
                        <div style={{ padding: '0 9px 7px', fontSize: '9px', color: 'var(--text-muted)' }}>
                            {lines} lines
                        </div>
                    </div>
                );
            }) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No terminal activity recorded.</span>}
        </div>
    );

    const renderMedia = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {relatedPlaybackRuns.length > 0 && (
                <div style={{ marginBottom: '6px' }}>
                    <p style={{ fontSize: '9px', fontWeight: '900', textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-muted)', marginBottom: '6px' }}>Playback</p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {relatedPlaybackRuns.map((run) => (
                            <div key={run.run_id} style={{ border: '1px solid var(--card-border)', borderRadius: '8px', background: 'rgba(0,0,0,0.04)' }}>
                                {expandedPlaybackRunId === run.run_id ? (
                                    <div style={{ padding: '8px' }}>
                                        <button
                                            className="btn-ghost"
                                            style={{ marginBottom: '8px', padding: '4px 8px', fontSize: '10px', fontWeight: '700', color: 'var(--accent-color)' }}
                                            onClick={() => setExpandedPlaybackRunId(null)}
                                        >
                                            ← Back
                                        </button>
                                        <PlaybackCard runId={run.run_id} sessionId={sessionId} />
                                    </div>
                                ) : (
                                    <button
                                        onClick={() => setExpandedPlaybackRunId(run.run_id)}
                                        style={{
                                            width: '100%',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '10px',
                                            padding: '8px',
                                            background: 'transparent',
                                            border: 'none',
                                            textAlign: 'left',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        {run.thumbnail ? (
                                            <img
                                                src={run.thumbnail}
                                                alt=""
                                                style={{
                                                    width: '48px',
                                                    height: '34px',
                                                    borderRadius: '6px',
                                                    objectFit: 'cover',
                                                    border: '1px solid rgba(255,255,255,0.06)',
                                                    flexShrink: 0,
                                                }}
                                            />
                                        ) : (
                                            <div style={{
                                                width: '48px',
                                                height: '34px',
                                                borderRadius: '6px',
                                                border: '1px solid rgba(255,255,255,0.06)',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                flexShrink: 0,
                                            }}>
                                                <Monitor size={12} color="var(--text-muted)" />
                                            </div>
                                        )}
                                        <div style={{ minWidth: 0, flex: 1 }}>
                                            <p style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                {run.title || 'Browser Session'}
                                            </p>
                                            <p style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                                                {run.total_steps || 0} frames · {run.status === 'running' ? 'LIVE' : run.status === 'completed' || run.status === 'success' ? '✓' : '—'}
                                            </p>
                                        </div>
                                        <ChevronRight size={12} className="text-muted" />
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {media.length > 0 ? media.map((m, i) => {
                const name = String(m).split('/').pop();
                const ext = name.split('.').pop()?.toLowerCase();
                const isImg = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext);
                const url = getFileUrl({ path: m, name, type: isImg ? 'image' : 'file' }, sessionId);
                return (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px', background: 'rgba(0,0,0,0.05)', borderRadius: '8px', border: '1px solid var(--card-border)' }}>
                        <div style={{ width: '42px', height: '42px', borderRadius: '6px', overflow: 'hidden', border: '1px solid var(--card-border)', background: 'rgba(0,0,0,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                            {isImg ? (
                                <img src={url} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                            ) : (
                                <span style={{ fontSize: '18px', flexShrink: 0 }}>{ext === 'mp4' ? '🎬' : ext === 'mp3' ? '🎵' : ext === 'pdf' ? '📄' : '📎'}</span>
                            )}
                        </div>
                        <div style={{ minWidth: 0, flex: 1 }}>
                            <p style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</p>
                            <p style={{ fontSize: '10px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m}</p>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
                            {isImg && (
                                <button
                                    className="btn-ghost"
                                    style={{ padding: '6px', borderRadius: '8px' }}
                                    title="Expand"
                                    onClick={() => onExpand?.({ type: 'image', name, previewUrl: url, path: m })}
                                >
                                    <Maximize2 size={12} />
                                </button>
                            )}
                            <a
                                href={url}
                                download={name}
                                className="btn-ghost"
                                style={{ padding: '6px', borderRadius: '8px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                                title="Download"
                            >
                                <Download size={12} />
                            </a>
                        </div>
                    </div>
                );
            }) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No media recorded.</span>}
        </div>
    );

    const renderSources = () => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {sources.length > 0 ? sources.map((url, i) => (
                <a
                    key={i}
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        padding: '8px',
                        borderRadius: '8px',
                        border: '1px solid var(--card-border)',
                        background: 'rgba(0,0,0,0.04)',
                        fontSize: '11px',
                        color: 'var(--accent-color)',
                        textDecoration: 'underline',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                    }}
                    title={url}
                >
                    <span
                        style={{
                            position: 'relative',
                            width: '14px',
                            height: '14px',
                            borderRadius: '4px',
                            overflow: 'hidden',
                            flexShrink: 0,
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: 'rgba(255,255,255,0.08)',
                        }}
                    >
                        <span style={{ fontSize: '9px', lineHeight: 1, opacity: 0.75 }}>🌐</span>
                        <img
                            src={`/api/favicon?url=${encodeURIComponent(url)}`}
                            alt=""
                            loading="lazy"
                            style={{
                                position: 'absolute',
                                inset: 0,
                                width: '100%',
                                height: '100%',
                                objectFit: 'cover',
                            }}
                            onError={(e) => {
                                e.currentTarget.style.display = 'none';
                            }}
                        />
                    </span>
                    <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {url}
                    </span>
                </a>
            )) : <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No sources recorded.</span>}
        </div>
    );

    const tabRenderers = { plan: renderPlan, thought: renderThought, terminal: renderTerminal, skills: renderSkills, media: renderMedia, sources: renderSources };

    return (
        <>
        <div style={{ marginTop: (inline || hideButton) ? '0' : '12px', position: 'relative', display: inline ? 'inline-flex' : 'block' }}>
            {!hideButton && (
                <button
                    onClick={toggle}
                    title="Work Unit Details"
                    style={{
                        display: 'inline-flex', alignItems: 'center', gap: '6px',
                        padding: '2px 2px',
                        background: 'transparent',
                        border: 'none',
                        borderRadius: '0',
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                    }}
                >
                    <span style={{ fontSize: '12px' }}>⚡</span>
                    <span style={{ fontSize: '9px', fontWeight: '800', color: isOpen ? 'var(--accent-color)' : 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                        {isOpen ? 'Hide Details' : 'Work Details'}
                    </span>
                </button>
            )}

            {/* Panel */}
            {isOpen && !hidePanel && (
                <div style={{
                    marginTop: inline ? '0' : '10px',
                    position: inline ? 'absolute' : 'relative',
                    top: inline ? 'calc(100% + 8px)' : 'auto',
                    left: 0,
                    zIndex: inline ? 40 : 'auto',
                    minWidth: inline ? '320px' : 'auto',
                    border: '1px solid var(--card-border)',
                    borderRadius: '10px',
                    overflow: 'hidden',
                    background: 'rgba(0,0,0,0.03)',
                    animation: 'fadeIn 0.2s ease'
                }}>
                    {/* Tab Bar */}
                    <div style={{ display: 'flex', borderBottom: '1px solid var(--card-border)', background: 'rgba(0,0,0,0.04)' }}>
                        {INSPECTOR_TABS.map(tab => (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                style={{
                                    flex: 1, padding: '8px 4px',
                                    background: 'transparent', border: 'none', cursor: 'pointer',
                                    borderBottom: activeTab === tab.id ? '2px solid var(--accent-color)' : '2px solid transparent',
                                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px',
                                    transition: 'background 0.15s',
                                }}
                            >
                                <span style={{ fontSize: '14px' }}>{tab.emoji}</span>
                                <span style={{ fontSize: '9px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.06em', color: activeTab === tab.id ? 'var(--accent-color)' : 'var(--text-muted)' }}>
                                    {tab.label}
                                </span>
                            </button>
                        ))}
                    </div>

                    {/* Tab Content */}
                    <div style={{ padding: '14px', maxHeight: '260px', minHeight: '130px', overflowY: 'auto' }}>
                        {loading && !context && <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px', padding: '12px' }}>Loading…</div>}
                        {error && <div style={{ color: '#ef4444', fontSize: '12px' }}>{error}</div>}
                        {!loading && !error && context && tabRenderers[activeTab]?.()}
                    </div>
                </div>
            )}
        </div>
        {fullscreenTerminal && createPortal((
            <div
                style={{
                    position: 'fixed',
                    inset: 0,
                    zIndex: 1200,
                    background: 'rgba(0,0,0,0.78)',
                    backdropFilter: 'blur(3px)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '20px',
                }}
                onClick={() => setFullscreenTerminalId(null)}
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
                                {String(fullscreenTerminal?.command || fullscreenTerminal?.id || 'terminal')}
                            </p>
                            <p style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {String(fullscreenTerminal?.cwd || '')}
                            </p>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{Number(fullscreenTerminal?.line_count || 0)} lines</span>
                            <button className="btn-ghost" style={{ padding: '6px', borderRadius: '8px' }} onClick={() => setFullscreenTerminalId(null)} title="Close">
                                <X size={14} />
                            </button>
                        </div>
                    </div>
                    <div ref={fullscreenTerminalBodyRef} className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '14px', background: 'rgba(4,7,20,0.8)' }}>
                        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '12px', lineHeight: 1.5, color: '#d9e1ff', fontFamily: '"JetBrains Mono","Fira Code",monospace' }}>
                            {String(fullscreenTerminal?.transcript || fullscreenTerminal?.output_full || fullscreenTerminal?.output_tail || `$ ${String(fullscreenTerminal?.command || 'shell command')}\n(waiting for output...)`)}
                        </pre>
                    </div>
                </div>
            </div>
        ), document.body)}
        </>
    );
};
// ─────────────────────────────────────────────────────────────────────────────

const TERMINAL_WORK_STATUSES = new Set(['complete', 'succeeded', 'failed', 'cancelled']);
const ACTIVE_WORK_STATUSES = new Set(['queued', 'running', 'waiting_user', 'paused', 'thinking', 'responding']);

const WorkControlButton = memo(({ workId, sessionId, isStreaming, statusPhase }) => {
    const [busy, setBusy] = useState(false);
    const [workStatus, setWorkStatus] = useState(null);

    const fetchWorkStatus = async () => {
        if (!workId) return;
        try {
            const data = await api.get(`/tasks/works/${workId}`);
            const nextStatus = String(data?.status || '').toLowerCase();
            if (nextStatus) setWorkStatus(nextStatus);
        } catch {
            // Keep UX resilient even if status fetch fails.
        }
    };

    useEffect(() => {
        fetchWorkStatus();
    }, [workId]);

    const phase = String(statusPhase || '').toLowerCase();
    const effectiveStatus = workStatus || (isStreaming ? 'running' : phase);
    const isLikelyActive = isStreaming || ACTIVE_WORK_STATUSES.has(effectiveStatus) || ACTIVE_WORK_STATUSES.has(phase);
    const isTerminal = TERMINAL_WORK_STATUSES.has(effectiveStatus) || TERMINAL_WORK_STATUSES.has(phase) || !isLikelyActive;
    const canShow = !!workId;
    if (!canShow) return null;

    const onClick = async () => {
        if (busy) return;
        setBusy(true);
        try {
            if (isTerminal) {
                const data = await api.post(`/tasks/works/${workId}/restart`, { requester_session_id: sessionId });
                const restartedId = data?.restarted_work_id ? ` (${String(data.restarted_work_id).slice(0, 8)})` : '';
                toast.success(`Worker restarted${restartedId}`);
            } else {
                await api.post(`/tasks/works/${workId}/commands`, {
                    command: 'cancel',
                    payload: { reason: 'Stopped from chat' },
                    requester_session_id: sessionId,
                    source_session_id: sessionId,
                });
                toast.success('Stop signal sent');
                setTimeout(() => fetchWorkStatus(), 700);
            }
        } catch (err) {
            toast.error(err?.message || 'Failed to control worker');
        } finally {
            setBusy(false);
        }
    };

    return (
        <button
            onClick={onClick}
            className="btn-ghost"
            title={isTerminal ? 'Restart worker' : 'Stop worker'}
            disabled={busy}
            style={{
                padding: '4px 8px',
                borderRadius: '8px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                minHeight: '24px',
                opacity: busy ? 0.7 : 1,
                border: isTerminal ? '1px solid var(--card-border)' : '1px solid rgba(239,68,68,0.35)',
                color: isTerminal ? 'var(--text-muted)' : '#ef4444'
            }}
        >
            {isTerminal ? (
                <RefreshCw size={12} style={busy ? { animation: 'spin 1s linear infinite' } : undefined} />
            ) : (
                <Square size={12} fill="currentColor" />
            )}
            <span style={{ fontSize: '9px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                {isTerminal ? 'Reload' : 'Stop'}
            </span>
        </button>
    );
});

const InlineApprovalBar = memo(({ workId, sessionId, statusPhase, approvalRequest, statusMessage }) => {
    const [busy, setBusy] = useState(false);
    const [snapshot, setSnapshot] = useState(null);
    const [localDecision, setLocalDecision] = useState(null); // { type: 'approved'|'denied', scope, ts }

    const fetchSnapshot = async () => {
        if (!workId) return;
        try {
            const data = await api.get(`/tasks/works/${workId}?requester_session_id=${encodeURIComponent(sessionId || '')}`);
            setSnapshot(data || null);
        } catch {
            // Keep silent to avoid noisy UI.
        }
    };

    useEffect(() => {
        fetchSnapshot();
    }, [workId, sessionId]);

    const statusPhaseNorm = String(statusPhase || '').toLowerCase();
    const terminalStatuses = new Set(['complete', 'succeeded', 'failed', 'cancelled']);
    const snapshotStatus = String(snapshot?.status || '').toLowerCase();
    const runtimeStatus = (() => {
        if (statusPhaseNorm === 'waiting_user' || snapshotStatus === 'waiting_user') return 'waiting_user';
        if (terminalStatuses.has(statusPhaseNorm)) return statusPhaseNorm;
        if (terminalStatuses.has(snapshotStatus)) return snapshotStatus;
        return snapshotStatus || statusPhaseNorm || '';
    })();
    const summary = snapshot?.context?.summary && typeof snapshot.context.summary === 'object' ? snapshot.context.summary : {};
    const snapshotApproval = (snapshot?.approval_request && typeof snapshot.approval_request === 'object')
        ? snapshot.approval_request
        : (summary?.approval_request && typeof summary.approval_request === 'object' ? summary.approval_request : null);
    const effectiveApprovalRequest = (approvalRequest && typeof approvalRequest === 'object')
        ? approvalRequest
        : snapshotApproval;
    const resolvedPrompt = String(
        effectiveApprovalRequest?.prompt
        || summary?.approval_prompt
        || statusMessage
        || 'Sensitive action detected. Do you authorize execution?'
    ).trim();
    const approvalKey = JSON.stringify({
        workId: String(workId || ''),
        prompt: resolvedPrompt,
        action: String(effectiveApprovalRequest?.action_id || effectiveApprovalRequest?.action || summary?.approval_action || ''),
        args: effectiveApprovalRequest?.args || summary?.approval_args || null,
    });
    const waitingUser = runtimeStatus === 'waiting_user' || (
        !!effectiveApprovalRequest
        && !terminalStatuses.has(runtimeStatus)
    );
    const hasLocalDecision = !!localDecision && localDecision.approvalKey === approvalKey;

    useEffect(() => {
        if (!workId) return undefined;
        if (waitingUser || !!effectiveApprovalRequest || hasLocalDecision) {
            const t = setInterval(fetchSnapshot, 1000);
            return () => clearInterval(t);
        }
        return undefined;
    }, [workId, waitingUser, effectiveApprovalRequest, hasLocalDecision]);

    useEffect(() => {
        // New approval request arrived -> clear previous local decision marker.
        if (!localDecision) return;
        if (localDecision.approvalKey !== approvalKey) {
            setLocalDecision(null);
        }
    }, [approvalKey, localDecision]);

    if (!waitingUser && !hasLocalDecision) return null;

    const sendApprovalDecision = async (decision, scope = 'worker') => {
        if (!workId || busy) return;
        setBusy(true);
        try {
            await api.post(`/tasks/works/${workId}/commands`, {
                command: decision === 'deny' ? 'deny' : 'approve',
                payload: { scope },
                requester_session_id: sessionId,
                source_session_id: sessionId,
            });
            setLocalDecision({
                type: decision === 'deny' ? 'denied' : 'approved',
                scope,
                ts: Date.now(),
                approvalKey,
            });
            toast.success(
                decision === 'deny' ? 'Denied' : `Allowed (${scope})`
            );
            setTimeout(() => { fetchSnapshot(); }, 350);
            setTimeout(() => { fetchSnapshot(); }, 1200);
        } catch (err) {
            toast.error(err?.message || 'Failed to send decision');
        } finally {
            setBusy(false);
        }
    };

    return (
        <div style={{
            marginBottom: '12px',
            padding: '10px 12px',
            borderRadius: '10px',
            border: waitingUser
                ? '1px solid rgba(245,158,11,0.35)'
                : (localDecision?.type === 'approved' ? '1px solid rgba(16,185,129,0.35)' : '1px solid rgba(239,68,68,0.35)'),
            background: waitingUser
                ? 'rgba(245,158,11,0.08)'
                : (localDecision?.type === 'approved' ? 'rgba(16,185,129,0.10)' : 'rgba(239,68,68,0.10)'),
        }}>
            <div style={{ fontSize: '12px', color: 'var(--text-primary)', marginBottom: '8px' }}>
                {hasLocalDecision
                    ? (localDecision?.type === 'approved'
                        ? `Approval sent (${localDecision.scope}). Worker resumed.`
                        : 'Denied. Worker will stop the sensitive action.')
                    : resolvedPrompt}
            </div>
            {waitingUser && !hasLocalDecision && (
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    <button className="btn-ghost" disabled={busy} onClick={() => sendApprovalDecision('deny')} style={{ fontSize: '10px', padding: '5px 8px', color: '#f87171', border: '1px solid rgba(248,113,113,0.4)' }}>
                        Deny
                    </button>
                    <button className="btn-ghost" disabled={busy} onClick={() => sendApprovalDecision('approve', 'worker')} style={{ fontSize: '10px', padding: '5px 8px' }}>
                        Allow Worker
                    </button>
                    <button className="btn-ghost" disabled={busy} onClick={() => sendApprovalDecision('approve', 'session')} style={{ fontSize: '10px', padding: '5px 8px' }}>
                        Allow Session
                    </button>
                    <button className="btn-ghost" disabled={busy} onClick={() => sendApprovalDecision('approve', 'global')} style={{ fontSize: '10px', padding: '5px 8px' }}>
                        Allow Global
                    </button>
                </div>
            )}
        </div>
    );
});

const MessageItem = memo(({ msg, sessionId, isStreaming = false, onExpand, agentName, latestPlaybackEvent }) => {
    const [isCognitiveCollapsed, setIsCognitiveCollapsed] = useState(true);
    const [isExpanded, setIsExpanded] = useState(false);
    const [isWorkDetailsOpen, setIsWorkDetailsOpen] = useState(false);
    const isUser = msg.role === 'user';
    const reasoningTimeline = normalizeReasoningTimeline(msg);
    const hasReasoning = !isUser && reasoningTimeline.length > 0;
    const showInlineThoughtToggle = hasReasoning && !isStreaming && isCognitiveCollapsed;
    const statusPhaseNormalized = String(msg?.statusPhase || '').toLowerCase();
    const isTerminalPhase = ['complete', 'completed', 'succeeded', 'success', 'done', 'failed', 'error', 'aborted', 'cancelled', 'canceled'].includes(statusPhaseNormalized);
    const isActivelyStreaming = isStreaming && !isTerminalPhase;
    const previewMessageContent = useMemo(() => {
        if (Array.isArray(msg?.contentSegments) && msg.contentSegments.length > 0) {
            return msg.contentSegments
                .map((segment) => String(segment?.content || '').trim())
                .filter(Boolean)
                .join('\n');
        }
        return String(msg?.content || '').trim();
    }, [msg?.contentSegments, msg?.content]);
    const cardDetectionText = useMemo(() => {
        if (Array.isArray(msg?.contentSegments) && msg.contentSegments.length > 0) {
            const lastNonEmpty = [...msg.contentSegments]
                .reverse()
                .map((segment) => String(segment?.content || '').trim())
                .find(Boolean);
            if (lastNonEmpty) return lastNonEmpty;
        }
        return String(msg?.content || '').trim();
    }, [msg?.contentSegments, msg?.content]);
    const skillHints = useMemo(() => {
        const contextSkills = msg?.context?.data?.skills_used;
        return [
            ...(Array.isArray(msg?.skills_used) ? msg.skills_used : []),
            ...(Array.isArray(contextSkills) ? contextSkills : []),
        ];
    }, [msg?.skills_used, msg?.context?.data?.skills_used]);
    const actionHints = useMemo(() => {
        const contextActions = msg?.context?.data?.actions_used;
        return [
            ...(Array.isArray(msg?.actions_used) ? msg.actions_used : []),
            ...(Array.isArray(contextActions) ? contextActions : []),
        ];
    }, [msg?.actions_used, msg?.context?.data?.actions_used]);
    const sourceHints = useMemo(() => {
        const contextSources = msg?.context?.data?.sources_used;
        return [
            ...(Array.isArray(msg?.sources_used) ? msg.sources_used : []),
            ...(Array.isArray(contextSources) ? contextSources : []),
        ];
    }, [msg?.sources_used, msg?.context?.data?.sources_used]);
    const {
        anchorId,
        shouldTryWeatherCard,
        shouldTrySystemHealthCard,
        shouldTryWikiCard,
        shouldTryMapCard,
        wikiCardData,
        mapCardData,
        parsedDataChart,
        weatherCardLoading,
        weatherCardData,
        systemHealthLoading,
        systemHealthData,
    } = useAssistCards({
        sessionId,
        workId: msg?.work_id,
        text: cardDetectionText,
        isUser,
        isStreaming: isActivelyStreaming,
        skillsUsed: skillHints,
        actionsUsed: actionHints,
        sourcesUsed: sourceHints,
    });

    useEffect(() => {
        if (msg.isComplete || msg.statusPhase === 'complete') {
            setIsCognitiveCollapsed(true);
        }
    }, [msg.isComplete, msg.statusPhase]);

    return (
        <div className="animate-fade-in" style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: isUser ? 'flex-end' : 'flex-start',
            width: '100%'
        }}>
            <div className={`msg-bubble ${isUser ? 'msg-user' : 'msg-assistant'}`} style={{
                width: isUser ? 'auto' : '100%',
                maxWidth: isUser ? '85%' : 'min(92%, 56rem)',
                overflowWrap: 'anywhere',
                wordBreak: 'break-word',
                padding: '16px'
            }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '8px',
                    marginBottom: '12px',
                    paddingBottom: '8px',
                    borderBottom: isUser ? '1px solid rgba(255,255,255,0.1)' : '1px solid var(--card-border)',
                    minHeight: '24px'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, overflow: 'hidden' }}>
                        <p style={{ fontSize: '11px', fontWeight: 'bold', color: isUser ? '#fff' : 'var(--text-primary)', flexShrink: 0 }}>{isUser ? 'You' : agentName}</p>
                        {msg.timestamp && <p style={{ fontSize: '10px', color: isUser ? 'rgba(255,255,255,0.7)' : 'var(--text-muted)', flexShrink: 0 }}>{formatTime(msg.timestamp)}</p>}
                        {!isUser && msg.work_id && (
                            <WorkUnitInspector
                                workId={msg.work_id}
                                sessionId={sessionId}
                                onExpand={onExpand}
                                inline
                                open={isWorkDetailsOpen}
                                onToggle={setIsWorkDetailsOpen}
                                hidePanel
                            />
                        )}

                        {!isUser && isActivelyStreaming && msg.statusPhase && (
                            <div style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '6px',
                                padding: '2px 4px',
                                marginLeft: '4px',
                                minWidth: 0,
                                flexShrink: 1,
                                minHeight: '18px',
                                lineHeight: '1'
                            }}>
                                <div style={{
                                    width: '10px', height: '10px',
                                    border: '1.5px solid rgba(0,0,0,0.1)',
                                    borderTopColor: 'var(--accent-color)',
                                    borderRadius: '50%',
                                    animation: 'spin 1s linear infinite',
                                    flexShrink: 0
                                }} />
                                <span style={{
                                    fontSize: '9px',
                                    fontWeight: '800',
                                    textTransform: 'uppercase',
                                    color: 'var(--accent-color)',
                                    letterSpacing: '0.05em',
                                    whiteSpace: 'nowrap'
                                }}>
                                    {msg.statusPhase}
                                </span>
                                {msg.statusMessage && (
                                    <span
                                        title={String(msg.statusMessage)}
                                        style={{
                                            fontSize: '9px',
                                            fontWeight: '700',
                                            color: 'var(--text-muted)',
                                            maxWidth: '280px',
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                            lineHeight: 1.2,
                                            opacity: 0.9,
                                        }}
                                    >
                                        {String(msg.statusMessage)}
                                    </span>
                                )}
                            </div>
                        )}
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                        {!isUser && msg.work_id && (
                            <WorkControlButton
                                workId={msg.work_id}
                                sessionId={sessionId}
                                isStreaming={isStreaming}
                                statusPhase={msg.statusPhase}
                            />
                        )}
                        {showInlineThoughtToggle && (
                            <button
                                onClick={() => setIsCognitiveCollapsed(false)}
                                title="Expand Thought"
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                    cursor: 'pointer',
                                    padding: '2px 8px',
                                    background: 'var(--bg-color)',
                                    border: '1px solid var(--card-border)',
                                    borderRadius: '6px',
                                    flexShrink: 0
                                }}
                            >
                                <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981' }} />
                                <span style={{ fontSize: '9px', fontWeight: '800', color: 'var(--text-primary)', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Thought</span>
                            </button>
                        )}
                    </div>
                </div>

                {!isUser && msg.work_id && isWorkDetailsOpen && (
                    <div style={{ marginBottom: '12px' }}>
                        <WorkUnitInspector
                            workId={msg.work_id}
                            sessionId={sessionId}
                            onExpand={onExpand}
                            open={isWorkDetailsOpen}
                            onToggle={setIsWorkDetailsOpen}
                            hideButton
                        />
                    </div>
                )}

                {!isUser && msg.work_id && (
                    <InlineApprovalBar
                        workId={msg.work_id}
                        sessionId={sessionId}
                        statusPhase={msg.statusPhase}
                        approvalRequest={msg.approvalRequest}
                        statusMessage={msg.statusMessage}
                    />
                )}

                {!isUser && shouldTryWeatherCard && (
                    <>
                        {weatherCardLoading && (
                            <ChatCollapsibleAssistCard
                                sessionId={sessionId}
                                anchorId={anchorId}
                                cardType="weather"
                                title="Weather"
                                defaultOpen={true}
                            >
                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Loading weather data...</div>
                            </ChatCollapsibleAssistCard>
                        )}
                        {!weatherCardLoading && weatherCardData?.ok && (
                            <ChatCollapsibleAssistCard
                                sessionId={sessionId}
                                anchorId={anchorId}
                                cardType="weather"
                                title="Weather"
                                defaultOpen={true}
                            >
                                <WeatherAssistCard data={weatherCardData} />
                            </ChatCollapsibleAssistCard>
                        )}
                    </>
                )}

                {!isUser && shouldTrySystemHealthCard && (
                    <>
                        {systemHealthLoading && (
                            <ChatCollapsibleAssistCard
                                sessionId={sessionId}
                                anchorId={anchorId}
                                cardType="system-health"
                                title="System Health"
                                defaultOpen={true}
                            >
                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Loading system metrics...</div>
                            </ChatCollapsibleAssistCard>
                        )}
                        {!systemHealthLoading && systemHealthData?.ok && (
                            <ChatCollapsibleAssistCard
                                sessionId={sessionId}
                                anchorId={anchorId}
                                cardType="system-health"
                                title="System Health"
                                defaultOpen={true}
                            >
                                <SystemHealthAssistCard data={systemHealthData} />
                            </ChatCollapsibleAssistCard>
                        )}
                        {!systemHealthLoading && systemHealthData && !systemHealthData?.ok && (
                            <ChatCollapsibleAssistCard
                                sessionId={sessionId}
                                anchorId={anchorId}
                                cardType="system-health"
                                title="System Health"
                                defaultOpen={true}
                            >
                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                    Unable to load system metrics now.
                                    {systemHealthData?.message ? ` ${String(systemHealthData.message)}` : ''}
                                </div>
                            </ChatCollapsibleAssistCard>
                        )}
                    </>
                )}

                {!isUser && parsedDataChart && (
                    <ChatCollapsibleAssistCard
                        sessionId={sessionId}
                        anchorId={anchorId}
                        cardType={`data-chart:${parsedDataChart?.yLabel || 'default'}`}
                        title="Data Chart"
                        defaultOpen={true}
                    >
                        <DataChartAssistCard chart={parsedDataChart} />
                    </ChatCollapsibleAssistCard>
                )}

                {!isUser && shouldTryWikiCard && wikiCardData && (
                    <ChatCollapsibleAssistCard
                        sessionId={sessionId}
                        anchorId={anchorId}
                        cardType="wikipedia"
                        title="Wikipedia"
                        defaultOpen={true}
                    >
                        <WikiAssistCard data={wikiCardData} />
                    </ChatCollapsibleAssistCard>
                )}

                {!isUser && shouldTryMapCard && mapCardData && (
                    <ChatCollapsibleAssistCard
                        sessionId={sessionId}
                        anchorId={anchorId}
                        cardType="maps"
                        title="Maps"
                        defaultOpen={true}
                    >
                        <MapAssistCard data={mapCardData} />
                    </ChatCollapsibleAssistCard>
                )}

                {hasReasoning && (
                    (!isStreaming && isCognitiveCollapsed) ? null : (
                        <div style={{
                            marginBottom: '16px',
                            border: '1px solid var(--card-border)',
                            borderRadius: '8px',
                            overflow: 'hidden',
                            background: 'rgba(0,0,0,0.02)',
                            fontFamily: '"JetBrains Mono", "Fira Code", monospace'
                        }}>
                            <div style={{
                                padding: '8px 12px',
                                background: 'rgba(0,0,0,0.04)',
                                borderBottom: '1px solid var(--card-border)',
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                cursor: 'pointer'
                            }} onClick={() => setIsCognitiveCollapsed(!isCognitiveCollapsed)}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: !isStreaming ? '#10b981' : 'var(--accent-color)', animation: !isStreaming ? 'none' : 'pulse 2s infinite' }} />
                                    <span style={{ fontSize: '10px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                                        Thinking Process {isStreaming ? '...' : ''}
                                    </span>
                                </div>
                                {isCognitiveCollapsed ? <ChevronDown size={14} className="text-muted" /> : <ChevronUp size={14} className="text-muted" />}
                            </div>

                            {!isCognitiveCollapsed && (
                                <div style={{ padding: '12px', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                    {reasoningTimeline.map((entry, idx) => (
                                        <div key={idx} style={{ display: 'flex', gap: '12px', opacity: idx === (reasoningTimeline.length - 1) ? 1 : 0.6 }}>
                                            <span style={{ color: 'var(--accent-color)', fontWeight: 'bold' }}>{'>'}</span>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                                <span style={{ color: 'var(--text-primary)' }}>{entry.text}</span>
                                                {entry.ts && (
                                                    <span style={{ fontSize: '10px', color: 'var(--text-muted)', opacity: 0.9 }}>
                                                        {formatTime(entry.ts)}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )
                )}

                {/* Segments (Playback, Response, etc.) */}
                {msg.contentSegments && msg.contentSegments.length > 0 ? (
                    msg.contentSegments.map((segment, idx) => (
                        <div key={idx} style={{ position: 'relative' }}>
                            {(idx > 0 || hasReasoning) && <SegmentDivider />}

                            {segment.playback && (
                                <div style={{ marginBottom: '16px' }}>
                                    <PlaybackCard
                                        runId={segment.playback.run_id}
                                        sessionId={sessionId}
                                        liveEvent={latestPlaybackEvent}
                                    />
                                </div>
                            )}

                            {segment.content ? (
                                <TypewriterMarkdown
                                    text={segment.content}
                                    isStreaming={!isUser && isStreaming && idx === msg.contentSegments.length - 1}
                                    isComplete={msg.statusPhase === 'complete'}
                                    isUser={isUser}
                                />
                            ) : null}

                            {segment.attachments && segment.attachments.length > 0 && (
                                <div style={{ marginTop: '12px' }}>
                                    <MessageAttachments msg={{ attachments: segment.attachments }} sessionId={sessionId} onExpand={onExpand} />
                                </div>
                            )}
                        </div>
                    ))
                ) : (
                    /* Fallback for standalone messages */
                    <>
                        {hasReasoning && <SegmentDivider />}
                        {msg.playback && (
                            <div style={{ marginBottom: '16px' }}>
                                <PlaybackCard runId={msg.playback.run_id} sessionId={sessionId} liveEvent={latestPlaybackEvent} />
                            </div>
                        )}
                        {msg.content ? (
                            <TypewriterMarkdown
                                text={msg.content}
                                isStreaming={!isUser && isStreaming}
                                isComplete={msg.statusPhase === 'complete'}
                                isUser={isUser}
                            />
                        ) : null}
                        <MessageAttachments msg={msg} sessionId={sessionId} onExpand={onExpand} />
                    </>
                )}

                {!isUser && previewMessageContent && !isStreaming && (
                    <div style={{ display: 'flex', justifyContent: 'center', marginTop: 'var(--space-3)' }}>
                        <LinkPreviewCard messageContent={previewMessageContent} />
                    </div>
                )}

            </div>
        </div>
    );
});

const ChatCollapsibleAssistCard = memo(({
    sessionId,
    anchorId,
    cardType,
    title,
    defaultOpen = true,
    children,
}) => {
    const storageKey = useMemo(
        () => `assistant_chat_card:${sessionId || 'global'}:${anchorId || 'unknown'}:${cardType || 'card'}`,
        [sessionId, anchorId, cardType]
    );

    const [isOpen, setIsOpen] = useState(() => {
        try {
            const raw = localStorage.getItem(storageKey);
            if (raw === '0') return false;
            if (raw === '1') return true;
        } catch {
            // ignore localStorage failures
        }
        return defaultOpen;
    });

    useEffect(() => {
        try {
            localStorage.setItem(storageKey, isOpen ? '1' : '0');
        } catch {
            // ignore localStorage failures
        }
    }, [storageKey, isOpen]);

    const headerMeta = useMemo(() => {
        const key = String(cardType || title || '').toLowerCase();
        if (key.includes('weather') || key.includes('clima')) return { Icon: CloudSun, color: '#facc15' };
        if (key.includes('system') || key.includes('health')) return { Icon: HeartPulse, color: '#34d399' };
        if (key.includes('chart') || key.includes('data')) return { Icon: BarChart3, color: '#f59e0b' };
        if (key.includes('wiki') || key.includes('wikipedia')) return { Icon: BookOpen, color: '#cbd5e1' };
        if (key.includes('map')) return { Icon: Globe, color: '#34d399' };
        if (key.includes('youtube')) return { Icon: Video, color: '#ef4444' };
        if (key.includes('playback') || key.includes('music') || key.includes('audio')) return { Icon: Music, color: '#a78bfa' };
        if (key.includes('video')) return { Icon: Video, color: '#f87171' };
        return { Icon: FileText, color: 'var(--text-muted)' };
    }, [cardType, title]);
    const HeaderIcon = headerMeta.Icon;

    return (
        <div style={{ marginBottom: '16px', border: '1px solid var(--card-border)', borderRadius: '10px', overflow: 'hidden', background: 'var(--card-bg)' }}>
            <button
                type="button"
                onClick={() => setIsOpen((prev) => !prev)}
                style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '8px',
                    border: 'none',
                    borderBottom: isOpen ? '1px solid var(--card-border)' : 'none',
                    background: 'transparent',
                    padding: '10px 12px',
                    cursor: 'pointer',
                }}
            >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '10px', fontWeight: 900, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    {!isOpen && <HeaderIcon size={12} color={headerMeta.color} />}
                    <span>{title}</span>
                </span>
                {isOpen ? <ChevronUp size={14} className="text-muted" /> : <ChevronDown size={14} className="text-muted" />}
            </button>
            {isOpen && <div style={{ padding: '10px 12px' }}>{children}</div>}
        </div>
    );
});

const MessageList = memo(({ messages, sessionId, streamingMessage, onExpand, scrollRef, agentName, onScroll, latestPlaybackEvent, playbackRuns }) => {
    const combinedMessages = useMemo(() => {
        const history = (Array.isArray(messages) ? messages : [])
            .filter((msg) => msg && typeof msg === 'object')
            .filter((msg) => !String(msg.content || '').includes('[SYSTEM_NOTIFICATION]'));
        if (streamingMessage) {
            return [...history, streamingMessage];
        }
        return history;
    }, [messages, streamingMessage]);

    const groupedHistory = useMemo(() => groupHistoryWithReasoning(combinedMessages), [combinedMessages]);

    const renderMessagesWithDateDividers = () => {
        const result = [];
        let lastDateStr = null;

        groupedHistory.forEach((msg, i) => {
            if (msg.timestamp) {
                const dateStr = formatDate(msg.timestamp);

                if (dateStr && dateStr !== lastDateStr) {
                    result.push(
                        <div key={`date-${lastDateStr}-${i}`} style={{
                            display: 'flex', justifyContent: 'center', margin: '16px 0', opacity: 0.8
                        }}>
                            <div style={{
                                background: 'rgba(255,255,255,0.05)',
                                padding: '4px 12px',
                                borderRadius: '12px',
                                fontSize: '11px',
                                fontWeight: 'bold',
                                color: 'var(--text-muted)'
                            }}>
                                {dateStr}
                            </div>
                        </div>
                    );
                    lastDateStr = dateStr;
                }
            }

            const isLatestStreaming = streamingMessage && (
                (msg.work_id && msg.work_id === streamingMessage.work_id) ||
                msg.id === streamingMessage.id ||
                msg === streamingMessage
            );

            result.push(<MessageItem
                key={msg.id || `msg-${i}`}
                msg={msg}
                sessionId={sessionId}
                isStreaming={!!isLatestStreaming}
                onExpand={onExpand}
                agentName={agentName}
                latestPlaybackEvent={latestPlaybackEvent}
            />);
        });

        return result;
    };

    return (
        <div ref={scrollRef} onScroll={onScroll} className="custom-scrollbar h-full chat-container-bg" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {combinedMessages.length === 0 ? (
                <div style={{ margin: 'auto', textAlign: 'center', opacity: 0.8, maxWidth: '400px' }}>
                    <div style={{ width: '64px', height: '64px', background: 'var(--accent-glow)', borderRadius: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px', color: 'var(--accent-color)' }}>
                        <Bot size={32} />
                    </div>
                    <div style={{ padding: '32px', borderRadius: '24px', background: 'var(--card-bg)', border: '1px solid var(--card-border)', boxShadow: '0 10px 30px rgba(0,0,0,0.1)' }}>
                        <h2 style={{ fontSize: '24px', fontWeight: '900', marginBottom: '12px', color: 'var(--text-main)' }}>Cognitive Operating System</h2>
                        <p style={{ color: 'var(--text-muted)', fontSize: '15px', lineHeight: '1.6' }}>
                            Ready to process. Identified as <strong>{agentName}</strong>. What is your directive?
                        </p>
                    </div>
                </div>
            ) : (
                <>
                    {renderMessagesWithDateDividers()}
                </>
            )}
        </div>
    );
});

const AttachmentGrid = ({ items, sessionId, onExpand }) => {
    if (!items || items.length === 0) return null;
    const limit = 4;
    const displayItems = items.slice(0, limit);
    const remaining = items.length - limit;

    return (
        <div className={`attachment-grid grid-${Math.min(items.length, limit)} ${items.length > 4 ? 'grid-more' : ''}`}>
            {displayItems.map((item, idx) => {
                const url = getFileUrl(item, sessionId);
                return (
                    <div key={idx} className="grid-item" onClick={() => onExpand({ ...item, previewUrl: url })}>
                        {item.type === 'image' && (
                            <img src={url} alt={item.name} />
                        )}
                        {item.type === 'video' && (
                            <video src={url} />
                        )}
                        {idx === limit - 1 && remaining > 0 && (
                            <div className="grid-overlay">+{remaining}</div>
                        )}
                    </div>
                )
            })}
        </div>
    );
};

const truncateFileName = (name, length = 12) => {
    if (!name || name.length <= length) return name;
    const extIdx = name.lastIndexOf('.');
    if (extIdx === -1 || name.length - extIdx > 4) {
        return name.substring(0, length) + '...';
    }
    const ext = name.substring(extIdx);
    const base = name.substring(0, extIdx);
    return base.substring(0, length - ext.length - 2) + '..' + ext;
};

const FilePreviewIcon = ({ type }) => {
    switch (type) {
        case 'image': return <FileIcon size={24} color="#ec4899" />;
        case 'video': return <Video size={24} color="#8b5cf6" />;
        case 'audio': return <Music size={24} color="#10b981" />;
        case 'pdf': return <FileText size={24} color="#ef4444" />;
        case 'doc': return <FileText size={24} color="#3b82f6" />;
        case 'code': return <FileCode size={24} color="#f59e0b" />;
        case 'zip':
        case 'archive': return <Archive size={24} color="#6b7280" />;
        case 'csv':
        case 'xls':
        case 'xlsx': return <Table size={24} color="#10b981" />;
        default: return <FileIcon size={24} color="var(--text-muted)" />;
    }
};

const AttachmentList = ({ items, sessionId, onExpand }) => {
    if (!items || items.length === 0) return null;
    return (
        <div className="attachment-list">
            {items.length === 1 && (items[0].type === 'pdf' || items[0].name.endsWith('.txt')) && (
                <div style={{ width: '100%', height: '150px', borderRadius: '10px', overflow: 'hidden', border: '1px solid var(--card-border)', marginBottom: '8px' }}>
                    <iframe
                        src={getFileUrl(items[0], sessionId)}
                        style={{ width: '100%', height: '100%', border: 'none' }}
                        title="Preview"
                    />
                </div>
            )}
            {items.map((item, idx) => (
                <div key={idx} className="doc-item" onClick={() => {
                    if (item.type === 'audio') return;
                    onExpand({ ...item, previewUrl: getFileUrl(item, sessionId) });
                }}>
                    <FilePreviewIcon type={item.type} />
                    <div className="doc-info">
                        {/* Only show filename basename for better UX */}
                        <span className="doc-name">{item.name?.split('/').pop() || 'File'}</span>
                        <span className="doc-meta">{item.mime ? (item.mime.split('/')[1]?.toUpperCase() || 'FILE') : (item.name?.split('.').pop()?.toUpperCase() || 'FILE')}</span>
                    </div>
                </div>
            ))}
            {items.some(i => i.type === 'audio') && (
                <div className="audio-player-container">
                    {items.filter(i => i.type === 'audio').map((item, idx) => (
                        <audio key={idx} controls src={getFileUrl(item, sessionId)} />
                    ))}
                </div>
            )}
        </div>
    );
};

const MessageAttachments = ({ msg, sessionId, onExpand }) => {
    const allAttachments = msg.attachments || (msg.file ? [msg.file] : []);
    if (allAttachments.length === 0) return null;

    const visuals = allAttachments.filter(a => a.type === 'image' || a.type === 'video');
    const docs = allAttachments.filter(a => a.type !== 'image' && a.type !== 'video');

    return (
        <div style={{ marginBottom: '12px' }}>
            <AttachmentGrid items={visuals} sessionId={sessionId} onExpand={onExpand} />
            <AttachmentList items={docs} sessionId={sessionId} onExpand={onExpand} />
        </div>
    );
};


const Chat = () => {
    const { agentName } = useAuth();
    const [sessions, setSessions] = useState([]);
    const [selectedId, setSelectedId] = useState(null);
    const [deletingSessionId, setDeletingSessionId] = useState(null);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [isConnected, setIsConnected] = useState(false);
    const [currentSession, setCurrentSession] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [showAttachMenu, setShowAttachMenu] = useState(false);
    const [thought, setThought] = useState('');
    const [isThinking, setIsThinking] = useState(false);
    const [streamingMessage, setStreamingMessage] = useState(null); // { statusPhase, reasoningLines, content, isComplete }
    const [pendingFiles, setPendingFiles] = useState([]); // { file, previewUrl, type, name }
    const [isSending, setIsSending] = useState(false);
    const [latestPlaybackEvent, setLatestPlaybackEvent] = useState(null);
    const [playbackRuns, setPlaybackRuns] = useState([]);
    const [activeProfileTab, setActiveProfileTab] = useState('media'); // 'media' | 'docs' | 'links' | 'playback' | 'metrics'
    const [expandedProfilePlayback, setExpandedProfilePlayback] = useState(null); // run_id of currently expanded playback
    const [isSessionsCollapsed, setIsSessionsCollapsed] = useState(() => {
        return localStorage.getItem('assistant_chat_sessions_collapsed') === 'true';
    });

    // Rename state
    const [isEditingName, setIsEditingName] = useState(false);
    const [editNameValue, setEditNameValue] = useState("");

    // Pagination State
    const [hasMoreHistory, setHasMoreHistory] = useState(false);
    const [historyOffset, setHistoryOffset] = useState(0);
    const [isFetchingHistory, setIsFetchingHistory] = useState(false);

    const [previewFile, setPreviewFile] = useState(null); // File to show in modal

    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);
    const [mobileView, setMobileView] = useState('sessions'); // 'sessions' | 'chat'
    const [showScrollButton, setShowScrollButton] = useState(false);
    const [showActionsMenu, setShowActionsMenu] = useState(false);
    const [showChatProfile, setShowChatProfile] = useState(false);
    const [sessionMedia, setSessionMedia] = useState({ files: [], links: [] });
    const [loadingMedia, setLoadingMedia] = useState(false);
    const [chatPaneWidth, setChatPaneWidth] = useState(0);

    const scrollRef = useRef(null);
    const inputRef = useRef(null);
    const fileInputRef = useRef(null);
    const avatarUploadRef = useRef(null);
    const attachButtonRef = useRef(null);
    const attachMenuRef = useRef(null);
    const chatPaneRef = useRef(null);
    const wsRef = useRef(null);
    const thoughtTimeoutRef = useRef(null);
    const completeFlushTimeoutRef = useRef(null);
    const skipResetRef = useRef(false); // Flag to skip state clearing during lazy session creation
    const prevLastMsgIdRef = useRef(null); // Tracks last message to intelligently auto-scroll
    const pendingReasoningRef = useRef([]); // Accumulates reasoning timeline entries until the next assistant final message
    const streamingMessageRef = useRef(null);

    useEffect(() => {
        streamingMessageRef.current = streamingMessage;
    }, [streamingMessage]);

    const pushPendingReasoning = (line, ts = null) => {
        const entry = toReasoningEntry(line, ts);
        if (!entry) return;

        const existing = pendingReasoningRef.current || [];
        if (existing[existing.length - 1]?.text === entry.text) return;
        pendingReasoningRef.current = [...existing, entry];
    };

    useEffect(() => {
        localStorage.setItem('assistant_chat_sessions_collapsed', isSessionsCollapsed);
    }, [isSessionsCollapsed]);

    // Auto-expand textarea
    useEffect(() => {
        if (inputRef.current) {
            inputRef.current.style.height = 'auto';
            inputRef.current.style.height = `${Math.min(inputRef.current.scrollHeight, 200)}px`;
        }
    }, [input]);

    useEffect(() => {
        const handleResize = () => {
            setIsMobile(window.innerWidth <= 640);
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    useEffect(() => {
        if (selectedId && isMobile) {
            setMobileView('chat');
        }
    }, [selectedId, isMobile]);

    useEffect(() => {
        const pane = chatPaneRef.current;
        if (!pane) return;

        const updatePaneWidth = () => setChatPaneWidth(pane.clientWidth || 0);
        updatePaneWidth();

        if (typeof ResizeObserver !== 'undefined') {
            const observer = new ResizeObserver((entries) => {
                const entry = entries[0];
                if (!entry) return;
                setChatPaneWidth(entry.contentRect.width || 0);
            });
            observer.observe(pane);
            return () => observer.disconnect();
        }

        window.addEventListener('resize', updatePaneWidth);
        return () => window.removeEventListener('resize', updatePaneWidth);
    }, []);

    // Auto-scroll logic: only for live flow, never while paginating older history
    const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;
    const lastMsgId = lastMsg?.id || lastMsg?.content;

    useEffect(() => {
        if (scrollRef.current) {
            if (isFetchingHistory) {
                // Keep anchor restoration from fetchMoreHistory in control.
                prevLastMsgIdRef.current = lastMsgId;
                return;
            }

            const container = scrollRef.current;
            const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 150;

            const isNewMessage = prevLastMsgIdRef.current !== lastMsgId;

            if (isNearBottom || (isNewMessage && lastMsg?.role === 'user')) {
                container.scrollTop = container.scrollHeight;
            }

            prevLastMsgIdRef.current = lastMsgId;
        }
    }, [messages, lastMsgId, lastMsg?.role, isFetchingHistory]);

    // Initial Load
    useEffect(() => {
        const fetchSystemInfo = async () => {
            // No longer needed here as agentName comes from AuthContext
        };
        const initializeSessions = async () => {
            try {
                // 1. Get active session for auto-open
                const activeData = await api.get('/sessions/active?interface=web');
                if (activeData && activeData.id) {
                    setSelectedId(activeData.id);
                }

                // 2. Fetch all sessions for the list
                await fetchSessions();
            } catch (err) {
                console.error("Error initializing sessions:", err);
                fetchSessions(); // Fallback
            }
        };

        // fetchSystemInfo(); // No longer needed
        initializeSessions();
        const handleClickOutside = (e) => {
            if (attachMenuRef.current &&
                !attachMenuRef.current.contains(e.target) &&
                attachButtonRef.current &&
                !attachButtonRef.current.contains(e.target)) {
                setShowAttachMenu(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // WebSocket Connection
    useEffect(() => {
        if (!selectedId) return;

        // ISOLATION FIX: Clear state immediately for new session
        // Skip if we just created this session via handleSend (lazy creation)
        if (skipResetRef.current) {
            skipResetRef.current = false;
        } else {
            setMessages([]);
            setCurrentSession(null);
            setIsConnected(false);
            setStreamingMessage(null);
            setIsSending(false);
            setIsThinking(false);
            setThought('');
            setPendingFiles([]);
        }
        pendingReasoningRef.current = [];

        // Cleanup previous
        if (wsRef.current) {
            wsRef.current.close();
        }

        // Connect
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${selectedId}`;

        console.log("Connecting to WS:", wsUrl);
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            console.log("WS Connected");
            setIsConnected(true);
            toast.success("Neural Link Active", { id: 'ws-status' });
        };

        ws.onclose = () => {
            console.log("WS Disconnected");
            setIsConnected(false);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'pong') return;

                if (data.type === 'status') {
                    setIsSending(false); // Backend acknowledged and started processing
                    const playbackData = data.payload?.playback;
                    const payloadWorkId = data.payload?.work_id || data.work_id;
                    const payloadStatus = String(data.payload?.status || '').toLowerCase();
                    if (playbackData) {
                        setLatestPlaybackEvent({
                            ...playbackData,
                            type: 'playback.run_update'
                        });
                    }
                    setStreamingMessage(prev => ({
                        ...(prev || { content: '', reasoningLines: [], role: 'assistant' }),
                        work_id: payloadWorkId || prev?.work_id,
                        statusPhase: payloadStatus || data.phase,
                        statusMessage: data.message,
                        approvalRequest: data.payload?.approval_request || prev?.approvalRequest || null,
                        playback: playbackData || prev?.playback,
                        isComplete: false
                    }));
                }


                if (data.type === 'reasoning_chunk') {
                    pushPendingReasoning(data.content, data.timestamp || Date.now());
                    setStreamingMessage(prev => ({
                        ...(prev || { content: '', reasoningLines: [], reasoningTimeline: [], role: 'assistant', statusPhase: 'thinking' }),
                        reasoningLines: (() => {
                            const next = [...(prev?.reasoningLines || [])];
                            const line = String(data.content || '').trim();
                            if (line && next[next.length - 1] !== line) next.push(line);
                            return next;
                        })(),
                        reasoningTimeline: (() => {
                            const next = [...(prev?.reasoningTimeline || [])];
                            const entry = toReasoningEntry(data.content, data.timestamp || Date.now());
                            if (entry && next[next.length - 1]?.text !== entry.text) next.push(entry);
                            return next;
                        })(),
                    }));
                }

                if (data.type === 'final_message_chunk') {
                    setStreamingMessage(prev => ({
                        ...(prev || { reasoningLines: [], role: 'assistant', statusPhase: 'responding' }),
                        content: (prev?.content || '') + data.content
                    }));
                }

                if (data.type === 'complete') {
                    setStreamingMessage(prev => {
                        if (!prev) return null;
                        // Do not flush here to avoid duplicated assistant bubbles.
                        // Authoritative history sync comes from `message_added`.
                        const pendingReasoning = pendingReasoningRef.current || [];
                        return {
                            ...prev,
                            reasoningLines: (prev?.reasoningLines?.length ? prev.reasoningLines : pendingReasoning.map((r) => r.text)),
                            reasoningTimeline: (prev?.reasoningTimeline?.length ? prev.reasoningTimeline : pendingReasoning),
                            isComplete: true,
                            statusPhase: 'complete'
                        };
                    });
                    if (completeFlushTimeoutRef.current) {
                        clearTimeout(completeFlushTimeoutRef.current);
                    }
                    completeFlushTimeoutRef.current = setTimeout(() => {
                        setStreamingMessage(current => {
                            if (!current || !String(current.content || '').trim()) return current;
                            const localFinal = {
                                ...current,
                                id: `local-stream-${Date.now()}`,
                                timestamp: new Date().toISOString(),
                                role: 'assistant',
                                isComplete: true
                            };
                            setMessages(prev => {
                                const alreadyExists = prev.some(
                                    m => m.role === 'assistant' && String(m.content || '').trim() === String(localFinal.content || '').trim()
                                );
                                return alreadyExists ? prev : [...prev, localFinal];
                            });
                            return null;
                        });
                    }, 1200);
                }

                if (data.type === 'session_updated') {
                    // Update session name in the list and current session
                    setSessions(prev => prev.map(s =>
                        s.session_id === data.session_id ? { ...s, name: data.name } : s
                    ));
                    setCurrentSession(prev =>
                        prev && prev.id === data.session_id ? { ...prev, name: data.name } : prev
                    );
                }

                // Legacy support (optional, but keeping for robustness)
                if (data.type === 'assistant_thought') {
                    setThought(data.content);
                    setIsThinking(true);
                    if (thoughtTimeoutRef.current) clearTimeout(thoughtTimeoutRef.current);
                    thoughtTimeoutRef.current = setTimeout(() => setIsThinking(false), 8000);
                }

                if (data.type === 'assistant_response' || data.type === 'msg') {
                    setIsThinking(false);
                    // Update streaming message instead of adding new history entry to avoid duplication
                    // The 'complete' event will handle flushing it to the history list
                    setStreamingMessage(prev => {
                        if (prev) {
                            return {
                                ...prev,
                                content: data.content,
                                file: data.file,
                                statusPhase: 'complete'
                            };
                        } else {
                            // If no streaming active (message came in a single chunk or system push), 
                            // we'll rely on 'message_added' to sync it if it's not already there.
                            return null;
                        }
                    });
                }

                if (data.type?.startsWith('playback.')) {
                    setLatestPlaybackEvent(data);
                    return;
                }

                if (data.type === 'unread_count_updated') {
                    setSessions(prev => prev.map(s =>
                        s.session_id === data.session_id ? { ...s, unread_count: data.unread_count } : s
                    ));
                }

                if (data.type === 'message_added') {
                    // Update unread count for the session list sidebar
                    setSessions(prev => prev.map(s =>
                        s.session_id === data.session_id ? { ...s, unread_count: data.unread_count || s.unread_count } : s
                    ));

                    // If it's the current session, ensure the message is synced in history
                    if (data.session_id === selectedId) {
                        const incoming = data.message || {};
                        const incomingRole = incoming.role;
                        const incomingType = normalizeHistoryMessageType(incoming);

                        // Realtime UX: internal reasoning/system traces should feed Thought stream,
                        // not be rendered as standalone chat bubbles.
                        if (incomingType !== 'default') {
                            if (incomingType === 'reasoning') {
                                const reasoningLine = extractReasoningLine(incoming) || (typeof incoming.content === 'string' ? incoming.content.trim() : '');
                                if (reasoningLine) {
                                    pushPendingReasoning(reasoningLine, incoming.timestamp || Date.now());
                                }
                                setStreamingMessage(prev => ({
                                    ...(prev || { content: '', reasoningLines: [], reasoningTimeline: [], role: 'assistant', statusPhase: 'thinking' }),
                                    reasoningLines: (() => {
                                        const next = [...(prev?.reasoningLines || [])];
                                        if (reasoningLine && next[next.length - 1] !== reasoningLine) next.push(reasoningLine);
                                        return next;
                                    })(),
                                    reasoningTimeline: (() => {
                                        const next = [...(prev?.reasoningTimeline || [])];
                                        const entry = toReasoningEntry(reasoningLine, incoming.timestamp || Date.now());
                                        if (entry && next[next.length - 1]?.text !== entry.text) next.push(entry);
                                        return next;
                                    })(),
                                }));
                            }
                            return;
                        }

                        if (incomingRole === 'system') {
                            return;
                        }

                        const incomingForHistory = (() => {
                            if (incomingRole !== 'assistant') return incoming;
                            const pendingReasoning = pendingReasoningRef.current || [];
                            const streamSnapshot = streamingMessageRef.current || {};
                            const enriched = {
                                ...incoming,
                                work_id: incoming.work_id || streamSnapshot.work_id,
                                playback: incoming.playback || streamSnapshot.playback,
                                statusPhase: incoming.statusPhase || streamSnapshot.statusPhase,
                                statusMessage: incoming.statusMessage || streamSnapshot.statusMessage,
                                approvalRequest: incoming.approvalRequest || streamSnapshot.approvalRequest,
                            };
                            if (pendingReasoning.length > 0) {
                                enriched.reasoningLines = pendingReasoning.map((entry) => entry.text);
                                enriched.reasoningTimeline = [...pendingReasoning];
                            }
                            return enriched;
                        })();

                        if (incomingRole === 'assistant') {
                            if (completeFlushTimeoutRef.current) {
                                clearTimeout(completeFlushTimeoutRef.current);
                                completeFlushTimeoutRef.current = null;
                            }
                            pendingReasoningRef.current = [];
                            setStreamingMessage(null);
                        }

                        setMessages(prev => {
                            // 1. Precise Dedup: Check if ID already exists
                            if (incomingForHistory.id && prev.some(m => m.id === incomingForHistory.id)) return prev;

                            // 2. Fuzzy Dedup/Sync: Try to find a local message (no ID) that matches this one
                            const localMatchIdx = prev.findLastIndex(m =>
                                !m.id &&
                                m.role === incomingRole &&
                                (m.content === incomingForHistory.content || (m.content.length > 0 && String(incomingForHistory.content || '').startsWith(m.content.slice(0, 100))))
                            );

                            if (localMatchIdx !== -1) {
                                const next = [...prev];
                                next[localMatchIdx] = incomingForHistory; // Replace with server version (has ID and final timestamp)
                                return next;
                            }

                            // 3. Fallback: If it's the user's latest message with a spinner, replace it
                            if (incomingRole === 'user') {
                                const lastUserIdx = prev.findLastIndex(m => m.role === 'user' && m.isSending);
                                if (lastUserIdx !== -1) {
                                    const next = [...prev];
                                    next[lastUserIdx] = incomingForHistory;
                                    return next;
                                }
                            }

                            // 4. Default: Just add it (e.g. system notification or background message)
                            return [...prev, incomingForHistory];
                        });
                    }
                }
            } catch (e) {
                console.error("WS Parse Error:", e);
            }
        };


        // Fetch History
        fetchSessionDetail(selectedId);

        // Mark as open and READ in backend
        markSessionOpen(selectedId);
        markSessionRead(selectedId);

        return () => {
            if (completeFlushTimeoutRef.current) {
                clearTimeout(completeFlushTimeoutRef.current);
                completeFlushTimeoutRef.current = null;
            }
            if (wsRef.current) wsRef.current.close();
        };
    }, [selectedId]);

    const fetchSessions = async () => {
        try {
            const data = await api.get('/sessions?interface=web');
            setSessions(data || []);
        } catch (err) {
            console.error(err);
        }
    };

    const handleRenameSession = async () => {
        if (!selectedId || !editNameValue.trim()) {
            setIsEditingName(false);
            return;
        }
        try {
            await api.patch(`/sessions/${selectedId}`, { name: editNameValue.trim() });
            setCurrentSession(prev => prev ? { ...prev, name: editNameValue.trim() } : prev);
            setSessions(prev => prev.map(s => s.session_id === selectedId ? { ...s, name: editNameValue.trim() } : s));
            toast.success("Name updated");
        } catch (err) {
            console.error("Error renaming session:", err);
            toast.error("Error renaming");
        }
        setIsEditingName(false);
    };

    const handleAvatarUpload = async (e) => {
        const file = e.target.files?.[0];
        if (!file || !selectedId) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await api.post(`/sessions/${selectedId}/profile_picture`, formData);
            if (res && res.profile_picture) {
                // Update current session
                setCurrentSession(prev => prev ? { ...prev, profile_picture: res.profile_picture } : prev);
                // Update in sessions list
                setSessions(prev => prev.map(s => s.session_id === selectedId ? { ...s, profile_picture: res.profile_picture } : s));
                toast.success('Profile image updated!');
            }
        } catch (err) {
            console.error("Error uploading avatar:", err);
            toast.error("Error uploading image.");
        }

        // Reset input
        if (avatarUploadRef.current) avatarUploadRef.current.value = '';
    };

    const markSessionRead = async (id) => {
        if (!id) return;
        try {
            await api.put(`/sessions/${id}/read`);
            setSessions(prev => prev.map(s => s.session_id === id ? { ...s, unread_count: 0 } : s));
        } catch (err) {
            console.error("Error marking session as read:", err);
        }
    };

    const markSessionOpen = async (id) => {
        try {
            await api.post(`/sessions/${id}/open`);
        } catch (err) {
            console.error("Error marking session as open:", err);
        }
    };

    const fetchSessionDetail = async (id) => {
        try {
            const data = await api.get(`/sessions/${id}`);
            // Safety check: ensure we're still on the same session
            if (selectedId === id) {
                // Determine if we have more messages to load
                setHasMoreHistory(data.history?.length === 15);
                setHistoryOffset(15);

                const rawHistory = data.history || [];
                setMessages(rawHistory);
                setCurrentSession(data);

                // Scroll to bottom on initial load
                setTimeout(() => {
                    if (scrollRef.current) {
                        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                    }
                }, 50);
            }
        } catch (err) { console.error(err); }
    };

    const fetchSessionMedia = async (id) => {
        if (!id) return;
        setLoadingMedia(true);
        try {
            const response = await api.get(`/sessions/${id}/media`);
            setSessionMedia(response || { files: [], links: [] });
        } catch (error) {
            console.error("Error fetching session media:", error);
        } finally {
            setLoadingMedia(false);
        }
    };

    const fetchPlaybackRuns = async (id) => {
        if (!id) return;
        try {
            const response = await api.get(`/sessions/${id}/playback`);
            setPlaybackRuns(response?.runs || []);
        } catch (error) {
            console.error("Error fetching playback runs:", error);
        }
    };

    useEffect(() => {
        if (showChatProfile && selectedId) {
            fetchSessionMedia(selectedId);
            fetchPlaybackRuns(selectedId);
        }
    }, [showChatProfile, selectedId]);

    useEffect(() => {
        if (!showChatProfile || !selectedId) return;
        let cancelled = false;
        const tick = async () => {
            try {
                const data = await api.get(`/sessions/${selectedId}`);
                if (cancelled || !data) return;
                setCurrentSession(prev => (prev ? { ...prev, runtime_metrics: data.runtime_metrics || {} } : prev));
            } catch (error) {
                // Silent refresh loop for metrics.
            }
        };
        tick();
        const interval = setInterval(tick, 3000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [showChatProfile, selectedId]);

    // Also fetch playback runs on session load for inline rendering
    useEffect(() => {
        if (selectedId) {
            fetchPlaybackRuns(selectedId);
        }
    }, [selectedId]);

    const renderChatProfile = ({ desktopFullWidth = false }) => {
        const normalizeAssetPath = (value) => String(value || '').replace(/\\/g, '/').replace(/^\.?\//, '').toLowerCase();
        const profilePicturePath = normalizeAssetPath(currentSession?.profile_picture || '');
        const profilePictureName = profilePicturePath ? profilePicturePath.split('/').pop() : '';

        const isProfileAsset = (file) => {
            const filePath = normalizeAssetPath(file?.path || file?.file_path || '');
            const fileName = normalizeAssetPath(file?.name || file?.filename || '').split('/').pop();

            if (!filePath && !fileName) return false;
            if (profilePicturePath && filePath === profilePicturePath) return true;
            if (profilePictureName && fileName === profilePictureName) return true;
            if (fileName.startsWith('avatar_')) return true;
            if (filePath.startsWith('media/profile_picture/') || filePath.includes('/profile_picture/')) return true;
            return false;
        };

        const files = (sessionMedia?.files || []).filter(f => !isProfileAsset(f));
        const photos = files.filter(f => f.type === 'image');
        const docs = files.filter(f => f.type !== 'image');

        const isInternalLink = (link) => {
            const messageType = String(link?.message_type || link?.type || '').toLowerCase();
            if (messageType && messageType !== 'default') return true;
            if (link?.is_internal === true) return true;
            const source = String(link?.source || '').toLowerCase();
            if (source.includes('reasoning') || source.includes('thought') || source.includes('internal')) return true;
            return false;
        };

        const links = (sessionMedia?.links || []).filter(l => !isInternalLink(l));
        const runtimeMetrics = currentSession?.runtime_metrics || {};
        const promptMetrics = runtimeMetrics.prompt || {};
        const turnMetrics = runtimeMetrics.turn || {};
        const obsMetrics = runtimeMetrics.latest_observation || {};
        const contextResetReplyBlocked = runtimeMetrics.context_reset_reply_blocked || 0;
        const llmReplyWithoutTextRecovered = runtimeMetrics.llm_reply_without_text_recovered || 0;
        const desktopSplitProfileWidth = chatPaneWidth > 0
            ? Math.min(Math.max(Math.round(chatPaneWidth * 0.5), 440), 900)
            : 540;

        return (
            <div className="glass animate-slide-in-right" style={{
                width: (isMobile || desktopFullWidth) ? '100%' : `${desktopSplitProfileWidth}px`,
                height: isMobile ? '100svh' : '100%',
                display: 'flex',
                flexDirection: 'column',
                background: 'var(--card-bg)',
                borderLeft: (isMobile || desktopFullWidth) ? 'none' : '1px solid var(--card-border)',
                borderRadius: desktopFullWidth ? '0' : (isMobile ? '0' : '8px 0 0 8px'),
                zIndex: 2500,
                position: isMobile ? 'fixed' : 'relative',
                right: 0,
                top: 0,
                left: isMobile ? 0 : 'auto',
                boxShadow: (isMobile || desktopFullWidth) ? 'none' : '-10px 0 30px rgba(0,0,0,0.2)'
            }}>
                <div style={{ padding: isMobile ? '12px 12px 0' : '10px 12px 0', display: 'flex', alignItems: 'center' }}>
                    <button className="btn-ghost" onClick={() => setShowChatProfile(false)} style={{ padding: '8px' }}>
                        <X size={20} />
                    </button>
                </div>

                <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '12px 20px 24px' : '8px 24px 24px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: '20px' }}>
                        <div style={{ position: 'relative', marginBottom: '16px' }}>
                            <SessionAvatar session={currentSession} size={112} showBadge={false} onClick={() => avatarUploadRef.current?.click()} />
                            <div style={{ position: 'absolute', bottom: 0, right: 0, background: 'var(--accent-color)', color: '#fff', padding: '6px', borderRadius: '50%', border: '2px solid var(--card-bg)', cursor: 'pointer' }} onClick={() => avatarUploadRef.current?.click()}>
                                <Edit size={14} />
                            </div>
                        </div>
                        <h2 style={{ fontSize: '18px', fontWeight: 'bold', marginBottom: '4px', textAlign: 'center' }}>{currentSession?.name || 'Session'}</h2>
                        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{currentSession?.interface?.toUpperCase() || currentSession?.source?.toUpperCase() || 'CHAT'} · {(currentSession?.session_id || selectedId || '').substring(0, 8)}</p>
                    </div>

                    <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', borderBottom: '1px solid var(--card-border)', paddingBottom: '12px' }}>
                        {['media', 'docs', 'links', 'metrics'].map(tab => (
                            <button
                                key={tab}
                                onClick={() => setActiveProfileTab(tab)}
                                style={{
                                    flex: 1,
                                    padding: '8px',
                                    fontSize: '12px',
                                    fontWeight: 'bold',
                                    borderRadius: '8px',
                                    background: activeProfileTab === tab ? 'var(--accent-glow)' : 'transparent',
                                    color: activeProfileTab === tab ? 'var(--accent-color)' : 'var(--text-muted)',
                                    textTransform: 'uppercase',
                                    transition: '0.2s'
                                }}
                            >
                                {tab === 'media' ? 'Fotos' : tab === 'docs' ? 'Files' : tab === 'links' ? 'Links' : tab === 'metrics' ? 'Metrics' : 'Playback'}
                            </button>
                        ))}
                        {playbackRuns.length > 0 && (
                            <button
                                onClick={() => setActiveProfileTab('playback')}
                                style={{
                                    flex: 1,
                                    padding: '8px',
                                    fontSize: '12px',
                                    fontWeight: 'bold',
                                    borderRadius: '8px',
                                    background: activeProfileTab === 'playback' ? 'var(--accent-glow)' : 'transparent',
                                    color: activeProfileTab === 'playback' ? 'var(--accent-color)' : 'var(--text-muted)',
                                    textTransform: 'uppercase',
                                    transition: '0.2s'
                                }}
                            >
                                Playback
                            </button>
                        )}
                    </div>

                    {loadingMedia ? (
                        <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
                            <RefreshCw className="animate-spin text-muted" size={24} />
                        </div>
                    ) : (
                        <div style={{ minHeight: '200px' }}>
                            {activeProfileTab === 'media' && (
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
                                    {photos.length > 0 ? photos.map((f, i) => (
                                        <div key={i} className="aspect-square cursor-pointer overflow-hidden rounded-lg border border-white/5 hover:border-accent" onClick={() => setPreviewFile({ ...f, previewUrl: `/api/sessions/${selectedId}/files/${f.path}` })}>
                                            <img src={`/api/sessions/${selectedId}/files/${f.path}`} alt={f.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                                        </div>
                                    )) : (
                                        <div style={{ gridColumn: 'span 3', textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontSize: '13px' }}>Nenhuma foto.</div>
                                    )}
                                </div>
                            )}

                            {activeProfileTab === 'docs' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                    {docs.length > 0 ? docs.map((f, i) => (
                                        <div key={i} className="doc-item" onClick={() => setPreviewFile({ ...f, previewUrl: `/api/sessions/${selectedId}/files/${f.path}` })}>
                                            <FilePreviewIcon type={f.type} />
                                            <div className="doc-info" style={{ flex: 1, minWidth: 0 }}>
                                                <span className="doc-name" style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                                                <span className="doc-meta">{(f.size / 1024).toFixed(1)} KB · {f.mime ? (f.mime.split('/')[1]?.toUpperCase() || 'FILE') : 'FILE'}</span>
                                            </div>
                                            <Download size={16} className="text-muted" />
                                        </div>
                                    )) : (
                                        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontSize: '13px' }}>Nenhum documento.</div>
                                    )}
                                </div>
                            )}

                            {activeProfileTab === 'links' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                    {links.length > 0 ? links.map((l, i) => (
                                        <a key={i} href={l.url} target="_blank" rel="noreferrer" style={{
                                            display: 'flex',
                                            alignItems: 'flex-start',
                                            gap: '12px',
                                            padding: '12px',
                                            background: 'rgba(255,255,255,0.03)',
                                            borderRadius: '12px',
                                            textDecoration: 'none',
                                            border: '1px solid var(--card-border)',
                                            transition: '0.2s'
                                        }} className="hover:bg-white/5 group">
                                            <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'var(--accent-glow)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                                <Globe size={16} className="text-accent" />
                                            </div>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <span style={{ fontSize: '13px', color: 'var(--text-main)', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: '600' }}>{l.url}</span>
                                                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{formatDate(l.timestamp)} · {l.role === 'user' ? 'You' : 'Assistente'}</span>
                                            </div>
                                            <ChevronRight size={14} className="text-muted group-hover:text-accent" />
                                        </a>
                                    )) : (
                                        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontSize: '13px' }}>Nenhum link.</div>
                                    )}
                                </div>
                            )}

                            {activeProfileTab === 'playback' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                    {playbackRuns.length > 0 ? playbackRuns.map((run) => (
                                        <div key={run.run_id}>
                                            {expandedProfilePlayback === run.run_id ? (
                                                <div>
                                                    <button
                                                        onClick={() => setExpandedProfilePlayback(null)}
                                                        className="btn-ghost"
                                                        style={{ marginBottom: '8px', fontSize: '11px', fontWeight: '700', color: 'var(--accent-color)' }}
                                                    >
                                                        ← Voltar
                                                    </button>
                                                    <PlaybackCard
                                                        runId={run.run_id}
                                                        sessionId={selectedId}
                                                    />
                                                </div>
                                            ) : (
                                                <div
                                                    onClick={() => setExpandedProfilePlayback(run.run_id)}
                                                    style={{
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        gap: '12px',
                                                        padding: '10px 12px',
                                                        background: 'rgba(255,255,255,0.03)',
                                                        borderRadius: '12px',
                                                        border: '1px solid var(--card-border)',
                                                        cursor: 'pointer',
                                                        transition: '0.2s',
                                                    }}
                                                    className="hover:bg-white/5"
                                                >
                                                    {run.thumbnail ? (
                                                        <img
                                                            src={run.thumbnail}
                                                            alt=""
                                                            style={{
                                                                width: '56px',
                                                                height: '42px',
                                                                objectFit: 'cover',
                                                                borderRadius: '6px',
                                                                flexShrink: 0,
                                                                border: '1px solid rgba(255,255,255,0.05)',
                                                            }}
                                                        />
                                                    ) : (
                                                        <div style={{
                                                            width: '56px',
                                                            height: '42px',
                                                            borderRadius: '6px',
                                                            background: 'rgba(255,255,255,0.05)',
                                                            display: 'flex',
                                                            alignItems: 'center',
                                                            justifyContent: 'center',
                                                            flexShrink: 0,
                                                        }}>
                                                            <Monitor size={16} color="var(--text-muted)" />
                                                        </div>
                                                    )}
                                                    <div style={{ flex: 1, minWidth: 0 }}>
                                                        <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                            {run.title || 'Browser Session'}
                                                        </span>
                                                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                                            {run.total_steps} frames · {run.status === 'success' ? '✓' : run.status === 'running' ? '▶' : '—'}
                                                        </span>
                                                    </div>
                                                    <ChevronRight size={14} className="text-muted" />
                                                </div>
                                            )}
                                        </div>
                                    )) : (
                                        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontSize: '13px' }}>Nenhum playback.</div>
                                    )}
                                </div>
                            )}

                            {activeProfileTab === 'metrics' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                    <div style={{ padding: '12px', borderRadius: '10px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)' }}>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Prompt</div>
                                        <div style={{ fontSize: '13px', color: 'var(--text-main)' }}>Total: ~{promptMetrics.prompt_tokens_approx || 0} tokens</div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Actions: ~{promptMetrics?.block_tokens_approx?.['[AVAILABLE ACTIONS]'] || 0} · Dynamic: ~{promptMetrics?.block_tokens_approx?.['[DYNAMIC CONTEXT]'] || 0}</div>
                                    </div>

                                    <div style={{ padding: '12px', borderRadius: '10px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)' }}>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Turn</div>
                                        <div style={{ fontSize: '13px', color: 'var(--text-main)' }}>Latency: {turnMetrics.duration_ms || 0} ms</div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Loops: {turnMetrics.loops || 0} · Lock wait: {turnMetrics.lock_wait_ms || 0} ms</div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Last action: {turnMetrics.last_action || '-'}</div>
                                        <div style={{ marginTop: '8px' }}>
                                            <span style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                gap: '6px',
                                                fontSize: '11px',
                                                fontWeight: '700',
                                                padding: '4px 8px',
                                                borderRadius: '999px',
                                                color: contextResetReplyBlocked > 0 ? '#7f1d1d' : 'var(--text-muted)',
                                                background: contextResetReplyBlocked > 0 ? 'rgba(248, 113, 113, 0.2)' : 'rgba(255,255,255,0.04)',
                                                border: contextResetReplyBlocked > 0 ? '1px solid rgba(248, 113, 113, 0.45)' : '1px solid var(--card-border)',
                                            }}>
                                                Context-reset replies blocked: {contextResetReplyBlocked}
                                            </span>
                                        </div>
                                        <div style={{ marginTop: '8px' }}>
                                            <span style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                gap: '6px',
                                                fontSize: '11px',
                                                fontWeight: '700',
                                                padding: '4px 8px',
                                                borderRadius: '999px',
                                                color: llmReplyWithoutTextRecovered > 0 ? '#78350f' : 'var(--text-muted)',
                                                background: llmReplyWithoutTextRecovered > 0 ? 'rgba(251, 191, 36, 0.2)' : 'rgba(255,255,255,0.04)',
                                                border: llmReplyWithoutTextRecovered > 0 ? '1px solid rgba(245, 158, 11, 0.45)' : '1px solid var(--card-border)',
                                            }}>
                                                LLM reply recovered: {llmReplyWithoutTextRecovered}
                                            </span>
                                        </div>
                                    </div>

                                    <div style={{ padding: '12px', borderRadius: '10px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)' }}>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Observation</div>
                                        <div style={{ fontSize: '13px', color: 'var(--text-main)' }}>Raw: ~{obsMetrics.raw_tokens_approx || 0} · Truncated: ~{obsMetrics.truncated_tokens_approx || 0}</div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Summarized: {obsMetrics.summarized ? 'yes' : 'no'} · Total observations: {runtimeMetrics.observation_count || 0}</div>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    <div style={{ marginTop: '32px', borderTop: '1px solid var(--card-border)', paddingTop: '20px' }}>
                        <button
                            className="btn-ghost"
                            onClick={(e) => { deleteSession(e, selectedId); setShowChatProfile(false); }}
                            style={{ width: '100%', display: 'flex', alignItems: 'center', gap: '12px', padding: '12px', color: 'var(--error)', borderRadius: '12px', fontSize: '14px', justifyContent: 'flex-start' }}
                        >
                            <Trash2 size={18} /> Delete Conversation
                        </button>
                    </div>
                </div>
            </div>
        );
    };

    const fetchMoreHistory = async () => {
        if (!selectedId || isFetchingHistory || !hasMoreHistory) return;

        setIsFetchingHistory(true);
        try {
            const data = await api.get(`/sessions/${selectedId}/history?offset=${historyOffset}&limit=15`);

            if (data && data.history && data.history.length > 0) {
                // Determine if we have more messages to load
                setHasMoreHistory(data.has_more);

                const rawHistory = data.history;

                // Save current scroll metrics before state update
                const container = scrollRef.current;
                const oldScrollHeight = container ? container.scrollHeight : 0;
                const oldScrollTop = container ? container.scrollTop : 0;

                setMessages(prev => {
                    // Filter out duplicates using stable IDs
                    const existingIds = new Set(prev.map(m => m.id).filter(id => !!id));
                    const newUnique = rawHistory.filter(m => !m.id || !existingIds.has(m.id));
                    return [...newUnique, ...prev];
                });

                setHistoryOffset(prev => prev + data.history.length);

                // Restore scroll position so it doesn't jump
                if (container) {
                    // We use requestAnimationFrame or a very short timeout to wait for React render
                    requestAnimationFrame(() => {
                        const newScrollHeight = container.scrollHeight;
                        container.scrollTop = oldScrollTop + (newScrollHeight - oldScrollHeight);
                    });
                }
            } else {
                setHasMoreHistory(false);
            }
        } catch (err) {
            console.error("Error fetching more history:", err);
        } finally {
            setIsFetchingHistory(false);
        }
    };

    // If initial/history chunk is too short to create scroll, prefetch older pages automatically.
    useEffect(() => {
        if (!selectedId || !hasMoreHistory || isFetchingHistory) return;
        const container = scrollRef.current;
        if (!container) return;

        const noScrollableOverflow = container.scrollHeight <= (container.clientHeight + 24);
        if (noScrollableOverflow) {
            fetchMoreHistory();
        }
    }, [selectedId, hasMoreHistory, isFetchingHistory, historyOffset, messages.length]);

    // Handle infinite scroll + scroll to bottom button
    const handleScroll = (e) => {
        const target = e.target;

        // Infinite scroll (top) with threshold to avoid strict equality issues.
        const isNearTop = target.scrollTop <= 60;
        if (isNearTop && hasMoreHistory && !isFetchingHistory) {
            fetchMoreHistory();
        }

        // Scroll to bottom button visibility
        const isAtBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 100;
        setShowScrollButton(!isAtBottom);
    };

    const scrollToBottom = () => {
        if (scrollRef.current) {
            scrollRef.current.scrollTo({
                top: scrollRef.current.scrollHeight,
                behavior: 'smooth'
            });
        }
    };

    const deleteSession = async (e, id) => {
        e.stopPropagation();
        setDeletingSessionId(id);
    };

    const confirmDeleteSession = async () => {
        if (!deletingSessionId) return;
        try {
            await api.delete(`/sessions/${deletingSessionId}`);
            if (selectedId === deletingSessionId) {
                setSelectedId(null);
                setMessages([]);
                setCurrentSession(null);
            }
            fetchSessions();
        } catch (err) {
            toast.error("Error deleting session.");
        } finally {
            setDeletingSessionId(null);
        }
    };

    const createNewSession = () => {
        setSelectedId(null);
        setMessages([]);
        setCurrentSession(null);
        setPendingFiles([]);
        setStreamingMessage(null);
        if (isMobile) {
            setMobileView('chat');
        }
    };

    const handleSend = async (e) => {
        if (e) e.preventDefault();
        if (isSending || uploading) return; // Guard against double sends
        if ((!input.trim() && pendingFiles.length === 0)) return;

        let activeId = selectedId;

        // Lazy creation if no session is selected
        if (!activeId) {
            try {
                const data = await api.post('/sessions', { interface: 'web' });
                if (data && data.id) {
                    activeId = data.id;
                    skipResetRef.current = true; // Tell WebSocket useEffect not to clear our optimistic state
                    setSelectedId(activeId);
                    fetchSessions();
                } else {
                    toast.error("Error initializing session.");
                    return;
                }
            } catch (err) {
                toast.error("Error creating session.");
                return;
            }
        }

        const text = input.trim();
        setInput('');
        setIsSending(true);

        // Capture Geolocation (Dynamic Context)
        let location = null;
        if (navigator.geolocation) {
            try {
                const pos = await new Promise((resolve, reject) => {
                    navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 3000 });
                });
                location = {
                    latitude: pos.coords.latitude,
                    longitude: pos.coords.longitude
                };
            } catch (err) { console.debug("Geolocation skipped or timed out"); }
        }

        // Optimistic "Thinking" state for current agent
        pendingReasoningRef.current = [];
        setStreamingMessage({
            role: 'assistant',
            content: '',
            reasoningLines: [],
            reasoningTimeline: [],
            statusPhase: 'thinking',
            statusMessage: 'Starting sequence...',
            isComplete: false
        });

        // 1. Upload pending files first if any
        let uploadedFiles = [];
        if (pendingFiles.length > 0) {
            setUploading(true);
            const formData = new FormData();
            pendingFiles.forEach(item => formData.append('files', item.file));

            try {
                const response = await api.post(`/sessions/${activeId}/upload`, formData);
                uploadedFiles = response.files || [];
                // Pre-revoke URLs to avoid memory leaks
                pendingFiles.forEach(item => { if (item.previewUrl) URL.revokeObjectURL(item.previewUrl); });
                setPendingFiles([]);
            } catch (err) {
                toast.error("Error sending attachments.");
                setUploading(false);
                setIsSending(false);
                setStreamingMessage(null);
                return;
            }
            setUploading(false);
        }

        const userMsgContent = text || (uploadedFiles.length > 0 ? `Enviou ${uploadedFiles.length} anexo(s)` : '');
        if (!userMsgContent) {
            setIsSending(false);
            setStreamingMessage(null);
            return;
        }

        // 3. Send Message (Optimistic UI)
        const userMsg = {
            role: 'user',
            content: userMsgContent,
            timestamp: Date.now() / 1000,
            isSending: true,
            attachments: uploadedFiles
        };
        setMessages(prev => [...prev, userMsg]);

        // Optimistic "Thinking" state for current agent is now set at the top

        const payload = {
            type: 'msg',
            content: userMsgContent,
            attachments: uploadedFiles, // Send metadata to handle text + files unified
            timestamp: Date.now(),
            user_data: {
                location: location
            }
        };

        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && activeId) {
            wsRef.current.send(JSON.stringify(payload));
        } else {
            try {
                await api.post(`/sessions/${activeId}/message`, {
                    message: userMsgContent,
                    attachments: uploadedFiles,
                    user_data: { location }
                });
            } catch (err) {
                toast.error("Failed to send");
                setIsSending(false);
                setStreamingMessage(null);
            }
        }

        // Note: isSending and streamingMessage will be updated by WS events
    };


    const handleFileUpload = (e) => {
        const files = Array.from(e.target.files || []);
        if (files.length === 0) return;

        if (pendingFiles.length + files.length > 10) {
            toast.error("Maximum of 10 files allowed.");
            return;
        }

        const newPending = files.map(file => {
            let type = 'file';
            if (file.type.startsWith('image/')) type = 'image';
            else if (file.type.startsWith('video/')) type = 'video';
            else if (file.type.startsWith('audio/')) type = 'audio';
            else if (file.type.includes('pdf') || file.name.endsWith('.pdf')) type = 'pdf';
            else if (file.name.match(/\.(doc|docx|xls|xlsx|txt)$/)) type = 'doc';

            return {
                file,
                name: file.name,
                type,
                previewUrl: type === 'image' || type === 'video' ? URL.createObjectURL(file) : null
            };
        });

        setPendingFiles(prev => [...prev, ...newPending]);
        setShowAttachMenu(false);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const removePendingFile = (index) => {
        setPendingFiles(prev => {
            const fileToRemove = prev[index];
            if (fileToRemove.previewUrl) URL.revokeObjectURL(fileToRemove.previewUrl);
            return prev.filter((_, i) => i !== index);
        });
    };

    const AttachmentMenu = () => (
        // ... previous menu ...
        <div ref={attachMenuRef} className="glass" style={{
            position: 'absolute',
            bottom: 'calc(100% + 15px)',
            left: '20px',
            padding: '12px',
            borderRadius: '16px',
            zIndex: 10000,
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            minWidth: '220px',
            boxShadow: '0 15px 50px rgba(0,0,0,0.6)',
            background: 'rgba(15, 20, 30, 0.95)',
            border: '1px solid rgba(255,255,255,0.12)',
            animation: 'slide-up 0.2s ease-out'
        }}>
            <p style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 'bold', padding: '4px 10px 8px' }}>Attached Items (Max 10)</p>
            <button onClick={() => { fileInputRef.current.accept = "image/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <Paperclip size={16} color="#ec4899" /> Imagens
            </button>
            <button onClick={() => { fileInputRef.current.accept = "audio/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <Music size={16} color="#10b981" /> Audio
            </button>
            <button onClick={() => { fileInputRef.current.accept = "video/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <Video size={16} color="#8b5cf6" /> Videos
            </button>
            <button onClick={() => { fileInputRef.current.accept = ".pdf,.doc,.docx,.xls,.xlsx,.txt"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <FileText size={16} color="#3b82f6" /> Documentos
            </button>
            <button onClick={() => { fileInputRef.current.accept = "*/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <FileIcon size={16} color="#f59e0b" /> Files
            </button>
        </div>
    );

    const PreviewModal = () => {
        if (!previewFile) return null;
        const isPending = pendingFiles.some(f => f.name === previewFile.name);

        return (
            <div className="preview-modal-overlay" onClick={() => setPreviewFile(null)}>
                <div className="preview-modal-content" onClick={e => e.stopPropagation()}>
                    <button
                        onClick={() => setPreviewFile(null)}
                        className="btn-ghost"
                        style={{
                            position: 'absolute',
                            top: '16px',
                            right: '16px',
                            color: 'white',
                            background: 'rgba(0,0,0,0.5)',
                            borderRadius: '50%',
                            width: '40px',
                            height: '40px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            zIndex: 100
                        }}
                    >
                        <X size={24} />
                    </button>

                    <div className="preview-modal-media-container">
                        {previewFile.type === 'image' && <img src={previewFile.previewUrl} alt="Preview" />}
                        {previewFile.type === 'video' && <video src={previewFile.previewUrl} controls autoPlay />}
                    </div>

                    <div className="preview-modal-footer">
                        <p style={{ fontWeight: '600', color: 'white', marginBottom: '4px' }}>{previewFile.name}</p>
                        <div style={{ display: 'flex', gap: '12px' }}>
                            {!isPending && (
                                <a
                                    href={previewFile.previewUrl}
                                    download={previewFile.name}
                                    className="btn-primary"
                                    style={{ flex: 1, padding: '10px', fontSize: '0.8rem' }}
                                    onClick={(e) => e.stopPropagation()}
                                >
                                    <Download size={16} /> Baixar File
                                </a>
                            )}
                            {isPending && (
                                <button
                                    onClick={() => {
                                        const idx = pendingFiles.findIndex(f => f.name === previewFile.name);
                                        if (idx !== -1) removePendingFile(idx);
                                        setPreviewFile(null);
                                    }}
                                    className="btn-ghost"
                                    style={{ flex: 1, padding: '10px', color: '#ff4444', background: 'rgba(255,68,68,0.1)', border: '1px solid rgba(255,68,68,0.2)' }}
                                >
                                    <Trash2 size={16} /> Remover
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    const DESKTOP_PROFILE_SPLIT_MIN_WIDTH = 1150;
    const shouldUseFullProfileDesktop = !isMobile && showChatProfile && chatPaneWidth > 0 && chatPaneWidth < DESKTOP_PROFILE_SPLIT_MIN_WIDTH;

    return (
        <div className={`animate-fade-in flex-1 ${isMobile ? 'mobile-nav-active' : ''}`} style={{ display: 'flex', flex: 1, minHeight: 0, gap: isMobile ? '0' : '16px', overflow: 'hidden' }}>
            {/* Hidden File Input */}
            <input
                type="file"
                multiple
                ref={fileInputRef}
                style={{ display: 'none' }}
                onChange={handleFileUpload}
            />
            <input
                type="file"
                accept="image/*"
                ref={avatarUploadRef}
                style={{ display: 'none' }}
                onChange={handleAvatarUpload}
            />

            {/* Navigation Container for Mobile (Slide Effect) */}
            <div className={`mobile-view-container ${mobileView === 'chat' ? 'show-chat' : ''}`} style={{ display: isMobile ? 'flex' : 'contents' }}>

                {/* Sidebar - Sessions List (Mobile View Pane 1) */}
                <div className={`${isMobile ? 'mobile-view-pane' : ''} glass`} style={{
                    width: isMobile ? '50%' : (isSessionsCollapsed ? '60px' : '300px'),
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    overflow: 'hidden',
                    transition: 'var(--transition)',
                    borderRadius: isMobile ? '0' : '8px'
                }}>
                    <div className="glass" style={{
                        padding: (isSessionsCollapsed && !isMobile) ? '8px 0' : '8px 14px',
                        margin: '12px 12px 12px 12px',
                        borderRadius: '8px',
                        display: 'flex',
                        flexDirection: (isSessionsCollapsed && !isMobile) ? 'column' : 'row',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '8px',
                        background: 'rgba(255,255,255,0.03)'
                    }}>
                        {(!isSessionsCollapsed || isMobile) && <h3 style={{ fontSize: '14px', fontWeight: 'bold' }}>Sessions</h3>}
                        <div style={{ display: 'flex', flexDirection: (isSessionsCollapsed && !isMobile) ? 'column' : 'row', gap: '8px' }}>
                            <button onClick={createNewSession} className="btn-ghost" style={{ padding: '4px' }} title="New Session">
                                <Plus size={16} />
                            </button>
                            {!isMobile && (
                                <button
                                    onClick={() => setIsSessionsCollapsed(!isSessionsCollapsed)}
                                    className="btn-ghost"
                                    style={{ padding: '4px' }}
                                    title={isSessionsCollapsed ? "Expand" : "Collapse"}
                                >
                                    {isSessionsCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
                                </button>
                            )}
                        </div>
                    </div>
                    <div className="custom-scrollbar" style={{ flex: 1, padding: '8px', overflowX: 'hidden' }}>
                        {sessions.length > 0 ? sessions.map(s => (
                            <div
                                key={s.session_id}
                                onClick={() => {
                                    setSelectedId(s.session_id);
                                    if (isMobile) setMobileView('chat');
                                }}
                                className={`btn-ghost session-item ${selectedId === s.session_id ? 'active' : ''}`}
                                style={{
                                    padding: '12px',
                                    borderRadius: '8px',
                                    marginBottom: '4px',
                                    background: selectedId === s.session_id ? 'var(--accent-glow)' : 'transparent',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: (isSessionsCollapsed && !isMobile) ? 'center' : 'flex-start',
                                    gap: '12px',
                                    cursor: 'pointer',
                                    position: 'relative'
                                }}
                                title={s.session_id}
                            >
                                <SessionAvatar session={s} size={(isSessionsCollapsed && !isMobile) ? 32 : 36} showBadge={true} />
                                {(!isSessionsCollapsed || isMobile) && (
                                    <>
                                        <div style={{ flex: 1, overflow: 'hidden' }}>
                                            <p style={{ fontSize: '13px', fontWeight: '600', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>{s.name ? s.name : s.session_id.substring(0, 18) + "..."}</p>
                                            <p style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>{new Date(s.updated_at || s.last_active || Date.now()).toLocaleString()}</p>
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
                                            {s.unread_count > 0 && (
                                                <div className="unread-badge" style={{
                                                    background: 'var(--error)',
                                                    color: '#fff',
                                                    fontSize: '10px',
                                                    fontWeight: 'bold',
                                                    minWidth: '18px',
                                                    height: '18px',
                                                    borderRadius: '9px',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    justifyContent: 'center',
                                                    padding: '0 5px',
                                                    transition: '0.2s'
                                                }}>
                                                    {s.unread_count}
                                                </div>
                                            )}
                                            <button
                                                onClick={(e) => deleteSession(e, s.session_id)}
                                                className="btn-ghost delete-session-btn"
                                                style={{ padding: '4px', opacity: isMobile ? 1 : 0, transition: '0.2s', color: 'var(--error)' }}
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    </>
                                )}
                            </div>
                        )) : (
                            (!isSessionsCollapsed || isMobile) && <p style={{ textAlign: 'center', marginTop: '20px', fontSize: '12px', color: 'var(--text-muted)' }}>No active sessions.</p>
                        )}
                    </div>
                </div>

                {/* Chat Area (Mobile View Pane 2) */}
                <div ref={chatPaneRef} className={`${isMobile ? 'mobile-view-pane' : ''} glass`} style={{
                    flex: isMobile ? 'none' : 1,
                    display: 'flex',
                    flexDirection: 'column',
                    position: 'relative',
                    overflow: 'hidden',
                    borderRadius: isMobile ? '0' : '8px'
                }}>
                    <PreviewModal />

                    {/* Main Chat Body (Messages + Profile on Desktop) */}
                    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
                        {!shouldUseFullProfileDesktop && (
                            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                                {/* Header */}
                                <div style={{ padding: isMobile ? '6px 12px' : '8px 16px', borderBottom: '1px solid var(--card-border)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    {isMobile && (
                                        <button className="btn-ghost" onClick={() => setMobileView('sessions')} style={{ padding: '0.4rem', marginLeft: '-0.4rem' }}>
                                            <ChevronLeft size={20} />
                                        </button>
                                    )}
                                    {selectedId && currentSession ? (
                                        <SessionAvatar
                                            session={currentSession}
                                            size={isMobile ? 28 : 32}
                                            showBadge={false}
                                            onClick={() => setShowChatProfile(true)}
                                        />
                                    ) : (
                                        <div className="flex-center" style={{ width: isMobile ? '28px' : '32px', height: isMobile ? '28px' : '32px', background: isConnected ? 'var(--success)' : 'var(--text-muted)', color: '#fff', borderRadius: '50%' }}>
                                            <Bot size={isMobile ? 16 : 18} />
                                        </div>
                                    )}
                                    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                                        {isEditingName ? (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                                                <input
                                                    autoFocus
                                                    value={editNameValue}
                                                    onChange={(e) => setEditNameValue(e.target.value)}
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter') handleRenameSession();
                                                        if (e.key === 'Escape') setIsEditingName(false);
                                                    }}
                                                    onBlur={handleRenameSession}
                                                    style={{
                                                        background: 'rgba(255,255,255,0.05)',
                                                        border: '1px solid var(--accent-color)',
                                                        borderRadius: '6px',
                                                        padding: '2px 6px',
                                                        color: '#fff',
                                                        fontSize: isMobile ? '13px' : '14px',
                                                        fontWeight: 'bold',
                                                        outline: 'none',
                                                        width: '100%'
                                                    }}
                                                />
                                            </div>
                                        ) : (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                <h3
                                                    style={{ fontSize: isMobile ? '13px' : '14px', fontWeight: 'bold', margin: 0, cursor: selectedId ? 'pointer' : 'default', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}
                                                    onClick={() => { if (selectedId) setShowChatProfile(true); }}
                                                >
                                                    {selectedId ? (currentSession?.name || `Session: ${selectedId.substring(0, 8)}...`) : 'Select a session'}
                                                </h3>
                                                {(!isMobile && selectedId) && <ChevronRight size={14} style={{ opacity: 0.5, transition: '0.2s', cursor: 'pointer' }} onClick={() => setShowChatProfile(true)} className="hover:opacity-100" />}
                                                <div
                                                    title={isConnected ? 'Connected' : 'Disconnected'}
                                                    style={{
                                                        width: '8px',
                                                        height: '8px',
                                                        borderRadius: '50%',
                                                        marginLeft: '4px',
                                                        backgroundColor: isConnected ? 'var(--success)' : 'var(--text-muted)',
                                                        boxShadow: isConnected ? '0 0 6px var(--success-glow, rgba(16, 185, 129, 0.4))' : 'none',
                                                        flexShrink: 0
                                                    }}
                                                />
                                            </div>
                                        )}
                                    </div>

                                    {selectedId && (
                                        <div style={{ position: 'relative' }}>
                                            <button
                                                className="btn-ghost"
                                                onClick={() => setShowActionsMenu(!showActionsMenu)}
                                                style={{ padding: '8px' }}
                                            >
                                                <MoreHorizontal size={20} />
                                            </button>
                                            {showActionsMenu && (
                                                <div className="glass" style={{
                                                    position: 'absolute',
                                                    top: '100%',
                                                    right: 0,
                                                    marginTop: '8px',
                                                    padding: '8px',
                                                    zIndex: 1000,
                                                    minWidth: '160px',
                                                    display: 'flex',
                                                    flexDirection: 'column',
                                                    gap: '4px',
                                                    background: 'var(--card-bg)',
                                                    boxShadow: '0 10px 30px rgba(0,0,0,0.5)'
                                                }}>
                                                    <button
                                                        className="btn-ghost"
                                                        style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', fontSize: '13px', justifyContent: 'flex-start', color: 'var(--error)' }}
                                                        onClick={(e) => {
                                                            deleteSession(e, selectedId);
                                                            setShowActionsMenu(false);
                                                        }}
                                                    >
                                                        <Trash2 size={16} /> Delete Session
                                                    </button>
                                                    <button
                                                        className="btn-ghost"
                                                        style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', fontSize: '13px', justifyContent: 'flex-start' }}
                                                        onClick={() => {
                                                            setIsEditingName(true);
                                                            setEditNameValue(currentSession?.name || '');
                                                            setShowActionsMenu(false);
                                                        }}
                                                    >
                                                        <Edit size={16} /> Rename
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                {/* Messages Container */}
                                <div className="flex-1 overflow-hidden flex flex-col relative">


                                    <MessageList
                                        messages={messages}
                                        sessionId={selectedId}
                                        streamingMessage={streamingMessage}
                                        onExpand={setPreviewFile}
                                        scrollRef={scrollRef}
                                        agentName={agentName}
                                        onScroll={handleScroll}
                                        latestPlaybackEvent={latestPlaybackEvent}
                                        playbackRuns={playbackRuns}
                                    />

                                    {/* WhatsApp-like scroll to bottom button */}
                                    {showScrollButton && (
                                        <button
                                            onClick={scrollToBottom}
                                            className="glass flex-center"
                                            style={{
                                                position: 'absolute',
                                                bottom: '20px',
                                                right: '20px',
                                                width: '40px',
                                                height: '40px',
                                                borderRadius: '50%',
                                                zIndex: 50,
                                                color: 'var(--accent-color)',
                                                boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                                                animation: 'fadeIn 0.2s ease'
                                            }}
                                        >
                                            <ChevronDown size={24} />
                                        </button>
                                    )}
                                </div>

                                {/* Input Area */}
                                <div style={{
                                    padding: isMobile ? '2px 8px calc(8px + env(safe-area-inset-bottom))' : '4px 14px 4px',
                                    borderTop: '1px solid var(--card-border)',
                                    background: 'var(--bg-color)',
                                    position: 'relative',
                                    zIndex: 10
                                }}>
                                    {pendingFiles.length > 0 && (
                                        <div className="previews-container animate-fade-in" style={{
                                            marginBottom: '8px',
                                            padding: '6px',
                                            background: 'rgba(255,255,255,0.02)',
                                            borderRadius: '12px',
                                            border: '1px solid var(--card-border)'
                                        }}>
                                            {pendingFiles.map((file, idx) => (
                                                <div key={idx} className="preview-item" onClick={() => setPreviewFile(file)}>
                                                    <button
                                                        onClick={(e) => { e.stopPropagation(); removePendingFile(idx); }}
                                                        className="preview-remove"
                                                    >
                                                        <X size={10} />
                                                    </button>
                                                    {file.type === 'image' && <img src={file.previewUrl} alt="preview" />}
                                                    {file.type === 'video' && <video src={file.previewUrl} />}
                                                    {(file.type !== 'image' && file.type !== 'video') && <FilePreviewIcon type={file.type} />}
                                                    <div className="file-name-tag">{truncateFileName(file.name)}</div>
                                                </div>
                                            ))}
                                        </div>
                                    )}

                                    {showAttachMenu && <AttachmentMenu />}
                                    <div style={{
                                        position: 'relative',
                                        display: 'flex',
                                        flexDirection: 'column',
                                        background: 'var(--card-bg)',
                                        border: '1px solid var(--card-border)',
                                        borderRadius: isMobile ? '12px' : '8px',
                                        boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
                                        overflow: 'hidden',
                                        transition: 'var(--transition)'
                                    }} className="input-container-complex">
                                        <textarea
                                            ref={inputRef}
                                            rows="1"
                                            placeholder={(isConnected || !selectedId) ? (uploading ? "Syncing..." : "Message...") : "Connecting..."}
                                            value={input}
                                            onChange={(e) => setInput(e.target.value)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') {
                                                    if (e.ctrlKey) {
                                                        e.preventDefault();
                                                        const start = e.target.selectionStart;
                                                        const end = e.target.selectionEnd;
                                                        const val = e.target.value;
                                                        setInput(val.substring(0, start) + "\n" + val.substring(end));
                                                        setTimeout(() => {
                                                            e.target.selectionStart = e.target.selectionEnd = start + 1;
                                                            e.target.style.height = 'auto';
                                                            e.target.style.height = `${e.target.scrollHeight}px`;
                                                        }, 0);
                                                    } else if (!e.shiftKey) {
                                                        e.preventDefault();
                                                        handleSend(e);
                                                    }
                                                }
                                            }}
                                            disabled={!isConnected && selectedId || isSending || uploading}
                                            className="custom-scrollbar"
                                            style={{
                                                width: '100%',
                                                padding: isMobile ? '10px 44px 10px 44px' : '12px 56px 12px 56px',
                                                background: 'transparent',
                                                border: 'none',
                                                color: 'var(--text-main)',
                                                fontSize: isMobile ? '14px' : '15px',
                                                resize: 'none',
                                                minHeight: isMobile ? '40px' : '48px',
                                                maxHeight: '200px',
                                                overflowY: 'auto',
                                                lineHeight: '1.4',
                                                outline: 'none',
                                                whiteSpace: 'pre-wrap'
                                            }}
                                        />
                                        <button
                                            ref={attachButtonRef}
                                            type="button"
                                            disabled={uploading}
                                            onClick={() => setShowAttachMenu(!showAttachMenu)}
                                            className="flex-center"
                                            style={{
                                                position: 'absolute', left: isMobile ? '8px' : '12px', bottom: isMobile ? '4px' : '6px',
                                                width: isMobile ? '32px' : '36px', height: isMobile ? '32px' : '36px', borderRadius: '50%',
                                                color: uploading ? 'var(--warning)' : 'var(--text-muted)',
                                                background: 'rgba(255,255,255,0.05)',
                                                border: 'none',
                                                transition: 'var(--transition)',
                                                zIndex: 5
                                            }}
                                        >
                                            {uploading ? <Cpu size={18} className="animate-spin" /> : <Paperclip size={isMobile ? 18 : 22} />}
                                        </button>
                                        <button
                                            onClick={handleSend}
                                            disabled={(!input.trim() && pendingFiles.length === 0) || isSending || uploading}
                                            className="flex-center"
                                            style={{
                                                position: 'absolute', right: isMobile ? '8px' : '12px', bottom: isMobile ? '4px' : '6px',
                                                width: isMobile ? '32px' : '36px', height: isMobile ? '32px' : '36px', borderRadius: '50%',
                                                background: (input.trim() || pendingFiles.length > 0) && !isSending && !uploading ? 'var(--accent-color)' : 'rgba(255,255,255,0.05)',
                                                color: '#fff',
                                                transition: 'var(--transition)',
                                                border: 'none',
                                                cursor: (input.trim() || pendingFiles.length > 0) && !isSending && !uploading ? 'pointer' : 'default',
                                                zIndex: 5
                                            }}
                                        >
                                            {isSending || uploading ? <Cpu size={16} className="animate-spin" /> : <Send size={isMobile ? 16 : 18} />}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}
                        {!isMobile && showChatProfile && renderChatProfile({ desktopFullWidth: shouldUseFullProfileDesktop })}
                    </div>
                    {isMobile && showChatProfile && renderChatProfile({ desktopFullWidth: false })}
                </div>
            </div>

            <ConfirmDialog
                isOpen={!!deletingSessionId}
                title="Delete Session"
                message="Do you really want to delete this session and all its files? This action cannot be undone."
                confirmText="Yes, Delete"
                cancelText="Cancel"
                onConfirm={confirmDeleteSession}
                onCancel={() => setDeletingSessionId(null)}
                isDestructive={true}
            />
        </div>
    );
};

export default Chat;
