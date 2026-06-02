import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { useAuth } from '../context/AuthContext';
import { api } from '../hooks/api';
import PlaybackCard from '../components/PlaybackCard';
import ConfirmDialog from '../components/ConfirmDialog';
import { notify } from '../utils/notify.jsx';
import { useGlobalSession } from '../context/GlobalSessionContext';
import {
    Plus,
    Trash2,
    Globe,
    X,
    ChevronLeft,
    ChevronRight,
    ChevronDown,
    RefreshCw,
    Edit,
    Monitor,
    Download,
    Bot,
    Zap,
    MessageSquare,
    Copy,
    Check
} from 'lucide-react';

import { SessionAvatar } from '../components/chat/ChatIcons';
import { ChatHeader } from '../components/chat/ChatHeader';
import { ChatInputArea } from '../components/chat/ChatInputArea';
import { MessageList } from '../components/chat/MessageItem';
import { FilePreviewIcon } from '../components/chat/MessageAttachments';
import { formatDate } from '../utils/chatHistoryTransform';
import normalizeSessionEvent from '../utils/normalizeSessionEvent';
import { TypewriterMarkdown } from '../components/chat/TypewriterMarkdown';

const normalizeLiveTimestamp = (ts) => {
    if (!ts) return Date.now() / 1000;
    if (typeof ts === 'string') {
        const parsed = Date.parse(ts);
        return isNaN(parsed) ? (Date.now() / 1000) : (parsed / 1000);
    }
    if (typeof ts === 'number' && ts > 10000000000) {
        return ts / 1000;
    }
    return ts;
};

const isPlainObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const normalizeSnapshotMessages = (snapshot) => {
    const chatMessages = Array.isArray(snapshot?.chat) ? snapshot.chat.map((msg) => ({ ...msg })) : [];
    if (chatMessages.length > 0) return chatMessages;

    const indexedMessages = snapshot?.indices?.messages?.items;
    if (!isPlainObject(indexedMessages)) return [];

    return Object.values(indexedMessages).map((item) => ({
        id: item.message_id || item.id,
        role: item.role || 'assistant',
        content: item.content || item.content_preview || '',
        timestamp: item.created_at || item.updated_at || null,
        turn_id: item.turn_id ?? null,
        work_id: item.work_id ?? null,
        reply_to_message_id: item.reply_to_message_id ?? null,
        stream_id: item.stream_id ?? null,
        source: item.source || null,
        is_read: item.role === 'user',
    })).filter((msg) => Boolean(msg.id || msg.content));
};

const getMessageIdentity = (message) => {
    if (!message || typeof message !== 'object') return '';
    const explicitId = message.id || message.message_id || message.messageId;
    if (explicitId) return `id:${String(explicitId)}`;
    const role = String(message.role || '').trim().toLowerCase();
    const content = String(message.content || message.message || '').trim();
    const workId = String(message.work_id || message.workId || '').trim();
    const timestamp = String(message.timestamp || '');
    return `${role}:${content}:${workId}:${timestamp}`;
};

const getUserOptimisticSignature = (message) => {
    if (!message || typeof message !== 'object') return '';
    if (String(message.role || '').toLowerCase() !== 'user') return '';
    const content = String(message.content || message.message || '').trim();
    const attachments = Array.isArray(message.attachments)
        ? message.attachments.map((att) => String(att?.id || att?.name || att?.path || '').trim()).filter(Boolean).join('|')
        : '';
    return `${content}::${attachments}`;
};

const mergeSnapshotMessages = (existingMessages = [], snapshotMessages = []) => {
    const merged = [];
    const seen = new Map();
    const optimisticUserSignatures = new Set(
        (Array.isArray(existingMessages) ? existingMessages : [])
            .filter((message) => message && message.isSending && String(message.role || '').toLowerCase() === 'user')
            .map(getUserOptimisticSignature)
            .filter(Boolean)
    );

    const pushMessage = (message, preferExisting = false) => {
        if (!message || typeof message !== 'object') return;
        const key = getMessageIdentity(message);
        const signature = getUserOptimisticSignature(message);
        if (signature && optimisticUserSignatures.has(signature) && !message.isSending) return;

        if (seen.has(key)) {
            const current = seen.get(key);
            const next = preferExisting ? current : { ...current, ...message };
            seen.set(key, next);
            const index = merged.findIndex((item) => getMessageIdentity(item) === key);
            if (index !== -1) merged[index] = next;
            return;
        }

        seen.set(key, message);
        merged.push(message);
    };

    (Array.isArray(existingMessages) ? existingMessages : []).forEach((message) => pushMessage(message, true));
    (Array.isArray(snapshotMessages) ? snapshotMessages : []).forEach((message) => pushMessage(message, false));
    return merged;
};

const mergeLiveMessage = (existingMessages = [], incomingMessage = {}) => {
    if (!incomingMessage || typeof incomingMessage !== 'object') {
        return Array.isArray(existingMessages) ? existingMessages : [];
    }

    const next = Array.isArray(existingMessages) ? [...existingMessages] : [];
    const incomingIdentity = getMessageIdentity(incomingMessage);
    const incomingSignature = getUserOptimisticSignature(incomingMessage);

    if (incomingSignature) {
        const optimisticIndex = next.findIndex((message) => (
            message
            && message.isSending
            && String(message.role || '').toLowerCase() === 'user'
            && getUserOptimisticSignature(message) === incomingSignature
        ));

        if (optimisticIndex !== -1) {
            next[optimisticIndex] = {
                ...next[optimisticIndex],
                ...incomingMessage,
                isSending: false,
            };
            return next;
        }
    }

    const existingIndex = next.findIndex((message) => getMessageIdentity(message) === incomingIdentity);
    if (existingIndex !== -1) {
        next[existingIndex] = {
            ...next[existingIndex],
            ...incomingMessage,
        };
        return next;
    }

    return [...next, incomingMessage];
};

const buildCanonicalMessageFromEvent = (event, fallbackRole = 'assistant') => {
    const rawData = isPlainObject(event?.raw) ? event.raw : {};
    const payload = isPlainObject(event?.payload) ? event.payload : {};
    const data = { ...rawData, ...payload };
    const role = String(data.role || fallbackRole || 'assistant').toLowerCase() || 'assistant';
    const attachments = Array.isArray(data.attachments) ? data.attachments : [];
    const contentSegments = Array.isArray(data.contentSegments) ? data.contentSegments : [];

    return {
        id: event?.messageId || data.message_id || data.messageId || data.id || `msg-${Date.now()}`,
        role,
        content: data.content || data.message || data.text || data.full_text || '',
        timestamp: normalizeLiveTimestamp(data.timestamp || event?.timestamp || rawData.timestamp),
        turn_id: event?.turnId ?? data.turn_id ?? data.turnId ?? null,
        reply_to_message_id: event?.replyToMessageId ?? data.reply_to_message_id ?? data.replyToMessageId ?? null,
        stream_id: event?.streamId ?? data.stream_id ?? data.streamId ?? null,
        work_id: event?.workId ?? data.work_id ?? data.workId ?? null,
        model_info: data.model_info || rawData.model_info || null,
        reasoningTimeline: Array.isArray(data.reasoningTimeline) ? data.reasoningTimeline : [],
        statusPhase: role === 'assistant' ? (data.statusPhase || 'complete') : data.statusPhase,
        statusMessage: data.statusMessage || data.status || '',
        isComplete: role === 'assistant' ? (data.isComplete !== undefined ? Boolean(data.isComplete) : true) : Boolean(data.isComplete),
        animateTyping: role === 'assistant' ? (data.animateTyping !== undefined ? Boolean(data.animateTyping) : true) : Boolean(data.animateTyping),
        attachments,
        contentSegments,
    };
};

const buildSessionFromSnapshot = (snapshot, legacySession) => {
    const baseSession = isPlainObject(snapshot?.session) ? snapshot.session : {};
    const current = isPlainObject(snapshot?.current) ? snapshot.current : {};
    const legacy = isPlainObject(legacySession) ? legacySession : {};
    const mergedContext = isPlainObject(current.context)
        ? current.context
        : (isPlainObject(baseSession.context) ? baseSession.context : (isPlainObject(legacy.context) ? legacy.context : {}));

    return {
        ...legacy,
        ...baseSession,
        name: baseSession.name || current.name || legacy.name || '',
        profile_picture: baseSession.profile_picture || current.profile_picture || legacy.profile_picture || '',
        source: baseSession.source || current.source || legacy.source || 'web',
        interface: baseSession.interface || current.interface || baseSession.source || current.source || legacy.interface || legacy.source || 'web',
        runtime_metrics: snapshot?.runtime_metrics || baseSession.runtime_metrics || legacy.runtime_metrics || {},
        turn_id: current.turn_id ?? baseSession.turn_id ?? legacy.turn_id ?? 0,
        current_turn_id: current.current_turn_id ?? baseSession.context?.current_turn_id ?? legacy.current_turn_id ?? baseSession.turn_id ?? legacy.turn_id ?? 0,
        legacy_turn_id: current.legacy_turn_id ?? baseSession.turn_id ?? legacy.turn_id ?? 0,
        context: mergedContext,
        scratchpad: current.scratchpad ?? baseSession.scratchpad ?? legacy.scratchpad ?? '',
    };
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
    const [streamingMessage, setStreamingMessage] = useState(null);
    const [pendingFiles, setPendingFiles] = useState([]);
    const [isSending, setIsSending] = useState(false);
    const [latestPlaybackEvent, setLatestPlaybackEvent] = useState(null);
    const [playbackRuns, setPlaybackRuns] = useState([]);
    const [activeProfileTab, setActiveProfileTab] = useState('media');
    const [expandedProfilePlayback, setExpandedProfilePlayback] = useState(null);
    const [sessionSnapshot, setSessionSnapshot] = useState(null);
    const [sessionIndices, setSessionIndices] = useState(null);
    const [isSessionsCollapsed, setIsSessionsCollapsed] = useState(() => {
        return localStorage.getItem('assistant_chat_sessions_collapsed') === 'true';
    });

    const [isEditingName, setIsEditingName] = useState(false);
    const [editNameValue, setEditNameValue] = useState("");

    const [systemHealth, setSystemHealth] = useState({ llm: {}, capabilities: {} });

    const { addWebSocketListener, removeWebSocketListener, sendWebSocketMessage, connectionStatus, setActiveSessionId, workers: activeWorkers } = useGlobalSession();

    const [hasMoreHistory, setHasMoreHistory] = useState(false);
    const [historyOffset, setHistoryOffset] = useState(0);
    const [isFetchingHistory, setIsFetchingHistory] = useState(false);

    const [previewFile, setPreviewFile] = useState(null);

    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);
    const [mobileView, setMobileView] = useState('sessions');
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
    const skipResetRef = useRef(false);
    const prevLastMsgIdRef = useRef(null);
    const pendingReasoningRef = useRef([]);
    const streamingMessageRef = useRef(null);
    const streamingMessageDraftRef = useRef(null);
    const messagesSessionIdRef = useRef(null);

    useEffect(() => {
        streamingMessageRef.current = streamingMessage;
    }, [streamingMessage]);

    useEffect(() => {
        const handleResize = () => {
            const mobile = window.innerWidth <= 640;
            setIsMobile(mobile);
            if (chatPaneRef.current) {
                setChatPaneWidth(chatPaneRef.current.clientWidth);
            }
        };
        window.addEventListener('resize', handleResize);
        handleResize();
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    useEffect(() => {
        localStorage.setItem('assistant_chat_sessions_collapsed', isSessionsCollapsed);
    }, [isSessionsCollapsed]);

    useEffect(() => {
        const handleClickOutside = (e) => {
            if (showAttachMenu && attachMenuRef.current && !attachMenuRef.current.contains(e.target) && attachButtonRef.current && !attachButtonRef.current.contains(e.target)) {
                setShowAttachMenu(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [showAttachMenu]);

    const fetchSessions = async () => {
        try {
            const data = await api.get('/sessions');
            const sorted = (Array.isArray(data) ? data : data?.sessions || []).sort((a, b) => {
                const ta = new Date(a.updated_at || a.last_active || 0).getTime();
                const tb = new Date(b.updated_at || b.last_active || 0).getTime();
                return tb - ta;
            });
            setSessions(sorted);
            if (!selectedId && sorted.length > 0) {
                const defaultSession = sorted.find(s => s.source !== 'nexus') || sorted[0];
                setSelectedId(defaultSession.session_id);
            }
        } catch (err) {
            console.error("Error fetching sessions:", err);
            notify.error("Error loading sessions.");
        }
    };

    useEffect(() => {
        fetchSessions();
    }, []);

    useEffect(() => {
        let isSub = true;
        if (!selectedId) return;

        fetchSessionDetail(selectedId);
        markSessionRead(selectedId);
        markSessionOpen(selectedId);
        setActiveSessionId(selectedId);

        if (connectionStatus === 'online') setIsConnected(true);
        else setIsConnected(false);

        const handleWebSocketMessage = (raw) => {
            if (!isSub) return;
            try {
                const event = normalizeSessionEvent(raw);
                const liveData = isPlainObject(event.payload) ? event.payload : {};
                const rawData = isPlainObject(event.raw) ? event.raw : {};
                const eventData = { ...rawData, ...liveData };
                const eventType = event.eventType;
                if (eventType === 'ping') return;

                if (eventType === 'system_metrics' || eventType === 'system_health') {
                    if (eventData.health) setSystemHealth(eventData.health);
                    return;
                }

                if (eventType === 'worker_state') {
                    // Handled by GlobalSessionContext now
                    return;
                }

                if (eventType === 'playback_stream') {
                    setLatestPlaybackEvent(eventData);
                    return;
                }

                if (event.category === 'status' && !event.isLegacy) {
                    setStreamingMessage(prev => {
                        const content = prev ? prev.content : '';
                        const nextStreamingMessage = {
                            role: 'assistant',
                            content: content,
                            reasoningLines: prev?.reasoningLines || [],
                            reasoningTimeline: prev?.reasoningTimeline || [],
                            statusPhase: eventData.phase || 'thinking',
                            statusMessage: eventData.message || eventData.status || 'Processing...',
                            isComplete: false,
                            work_id: eventData.work_id || prev?.work_id,
                            model_info: eventData.model_info || prev?.model_info,
                            streamId: event.streamId || prev?.streamId || null,
                        };
                        streamingMessageDraftRef.current = nextStreamingMessage;
                        return nextStreamingMessage;
                    });
                    return;
                }

                if (event.category === 'reasoning') {
                    setIsThinking(true);
                    
                    let safeThought = '';
                    const rawThought = eventData.thought || eventData.content;
                    if (typeof rawThought === 'string') {
                        safeThought = rawThought;
                    } else if (Array.isArray(rawThought)) {
                        safeThought = rawThought.map(item => (typeof item === 'string' ? item : JSON.stringify(item))).join('\n');
                    } else if (typeof rawThought === 'object' && rawThought !== null) {
                        safeThought = rawThought.text || rawThought.thought || rawThought.content || rawThought.message || rawThought.summary || rawThought.value || JSON.stringify(rawThought);
                    } else if (rawThought !== undefined && rawThought !== null) {
                        safeThought = String(rawThought);
                    }

                    if (safeThought) setThought(safeThought);

                    const trimmedThought = typeof safeThought === 'string' ? safeThought.trim() : String(safeThought).trim();

                    if (trimmedThought) {
                        pendingReasoningRef.current.push({
                            text: trimmedThought,
                            ts: normalizeLiveTimestamp(raw.timestamp)
                        });
                    }

                    if (thoughtTimeoutRef.current) clearTimeout(thoughtTimeoutRef.current);
                    thoughtTimeoutRef.current = setTimeout(() => {
                        setIsThinking(false);
                    }, 5000);

                    setStreamingMessage(prev => {
                        const content = prev ? prev.content : '';
                        const currentLines = prev?.reasoningLines || [];
                        const nextLines = trimmedThought ? [...currentLines, trimmedThought] : currentLines;
                        const nextStreamingMessage = {
                            role: 'assistant',
                            content: content,
                            reasoningLines: nextLines,
                            reasoningTimeline: [...pendingReasoningRef.current],
                            statusPhase: eventData.phase || (prev ? prev.statusPhase : 'thinking'),
                            statusMessage: trimmedThought || (prev ? prev.statusMessage : ''),
                            isComplete: false,
                            work_id: eventData.work_id || prev?.work_id,
                            model_info: eventData.model_info || prev?.model_info,
                            streamId: event.streamId || prev?.streamId || null,
                        };
                        streamingMessageDraftRef.current = nextStreamingMessage;
                        return nextStreamingMessage;
                    });
                    return;
                }

                if (event.category === 'stream' && event.canUpdateMessage) {
                    setIsSending(false);
                    setIsThinking(false);

                    setStreamingMessage(prev => {
                        const currentContent = prev ? prev.content : (streamingMessageDraftRef.current?.content || '');
                        const nextContent = currentContent + (eventData.chunk || eventData.content || '');
                        const nextStreamingMessage = {
                            role: 'assistant',
                            content: nextContent,
                            reasoningLines: prev?.reasoningLines || [],
                            reasoningTimeline: [...pendingReasoningRef.current],
                            statusPhase: eventData.phase || 'responding',
                            statusMessage: eventData.status || 'Streaming response...',
                            isComplete: false,
                            work_id: eventData.work_id || prev?.work_id,
                            model_info: eventData.model_info || prev?.model_info,
                            streamId: event.streamId || prev?.streamId || null,
                        };
                        streamingMessageDraftRef.current = nextStreamingMessage;
                        return nextStreamingMessage;
                    });
                    return;
                }

                if ((event.eventType === 'message_added' || event.eventType === 'message.persisted' || event.eventType === 'user_message.created' || event.eventType === 'assistant_message.created') && (event.canCreateMessage || event.messageId || event.streamId)) {
                    setIsSending(false);
                    setIsThinking(false);

                    const finalMessage = buildCanonicalMessageFromEvent(event, String(eventData.role || (event.eventType === 'user_message.created' ? 'user' : 'assistant') || 'assistant').toLowerCase() || 'assistant');
                    if (String(finalMessage.role || '').toLowerCase() === 'assistant') {
                        streamingMessageDraftRef.current = finalMessage;
                        setStreamingMessage(null);
                        if (thoughtTimeoutRef.current) clearTimeout(thoughtTimeoutRef.current);
                        if (completeFlushTimeoutRef.current) clearTimeout(completeFlushTimeoutRef.current);
                        pendingReasoningRef.current = [];
                    }

                    setMessages(prev => {
                        const nextMsgs = mergeLiveMessage(prev, finalMessage);
                        return String(finalMessage.role || '').toLowerCase() === 'user'
                            ? nextMsgs
                            : nextMsgs.map((message) => (message.isSending ? { ...message, isSending: false } : message));
                    });

                    pendingReasoningRef.current = [];

                    setTimeout(() => {
                        if (scrollRef.current) {
                            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                        }
                    }, 100);

                    fetchSessions();
                    return;
                }

                if (event.category === 'completion' || event.eventType === 'assistant_response') {
                    setIsSending(false);
                    setIsThinking(false);

                    if (thoughtTimeoutRef.current) clearTimeout(thoughtTimeoutRef.current);
                    if (completeFlushTimeoutRef.current) clearTimeout(completeFlushTimeoutRef.current);

                    const activeStreamMessage = streamingMessageDraftRef.current || streamingMessageRef.current;
                    const activeStreamId = activeStreamMessage?.streamId || null;
                    const canFinalizeStream = event.target === 'stream' && event.streamId && (!activeStreamId || activeStreamId === event.streamId);
                    const legacyAssistantResponse = event.eventType === 'assistant_response';

                    if (!canFinalizeStream && !legacyAssistantResponse) {
                        if (event.target === 'legacy' || event.isLegacy) return;
                        if (!event.canCompleteTarget) return;
                    }

                    const finalContent = eventData.content || eventData.message || eventData.full_text || activeStreamMessage?.content || '';
                    const finalReasoning = [...(pendingReasoningRef.current || [])];
                    const finalWorkId = event.workId || activeStreamMessage?.work_id;
                    const finalModelInfo = eventData.model_info || eventData.provenance || activeStreamMessage?.model_info;

                    if (event.target === 'stream' && !String(finalContent || '').trim()) {
                        setStreamingMessage(null);
                        pendingReasoningRef.current = [];
                        return;
                    }

                    const finalMsg = {
                        id: event.messageId || eventData.message_id || activeStreamMessage?.id || `msg-${Date.now()}`,
                        role: String(eventData.role || 'assistant').toLowerCase() || 'assistant',
                        content: finalContent,
                        timestamp: normalizeLiveTimestamp(event.timestamp || eventData.timestamp),
                        reasoningTimeline: finalReasoning,
                        work_id: finalWorkId,
                        model_info: finalModelInfo,
                        statusPhase: 'complete',
                        isComplete: true,
                        animateTyping: true,
                        attachments: eventData.attachments || [],
                        contentSegments: eventData.contentSegments || [],
                        turn_id: event.turnId ?? eventData.turn_id ?? null,
                        reply_to_message_id: event.replyToMessageId ?? eventData.reply_to_message_id ?? null,
                        stream_id: event.streamId ?? eventData.stream_id ?? null,
                    };

                    setStreamingMessage(null);
                    pendingReasoningRef.current = [];

                    setMessages(prev => {
                        const nextMsgs = mergeLiveMessage(prev, finalMsg);
                        return nextMsgs.map((message) => (message.isSending ? { ...message, isSending: false } : message));
                    });

                    setTimeout(() => {
                        if (scrollRef.current) {
                            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                        }
                    }, 100);

                    fetchSessions();
                    return;
                }

                if (event.eventType === 'session_updated' || event.category === 'session') {
                    const sessionPatch = {
                        ...eventData,
                        session_id: event.sessionId || eventData.session_id || selectedId,
                    };
                    setCurrentSession(prev => {
                        if (!prev) return prev;
                        if (selectedId && prev.session_id && prev.session_id !== selectedId) return prev;
                        return {
                            ...prev,
                            ...sessionPatch,
                            runtime_metrics: sessionPatch.runtime_metrics || prev.runtime_metrics || {},
                        };
                    });
                    setSessions(prev => prev.map((session) => (
                        session.session_id === (event.sessionId || selectedId)
                            ? { ...session, ...sessionPatch }
                            : session
                    )));
                    return;
                }
            } catch (err) {
                console.error("WS Parse error:", err, raw);
            }
        };

        addWebSocketListener(handleWebSocketMessage);

        return () => {
            isSub = false;
            removeWebSocketListener(handleWebSocketMessage);
            if (thoughtTimeoutRef.current) clearTimeout(thoughtTimeoutRef.current);
            if (completeFlushTimeoutRef.current) clearTimeout(completeFlushTimeoutRef.current);
        };
    }, [selectedId, connectionStatus, addWebSocketListener, removeWebSocketListener]);

    const handleRenameSession = async () => {
        if (!selectedId || !isEditingName) return;
        try {
            await api.put(`/sessions/${selectedId}`, { name: editNameValue });
            setSessions(prev => prev.map(s => s.session_id === selectedId ? { ...s, name: editNameValue } : s));
            if (currentSession) setCurrentSession(prev => ({ ...prev, name: editNameValue }));
            notify.success("Session renamed!");
        } catch (err) {
            notify.error("Failed to rename session.");
        } finally {
            setIsEditingName(false);
        }
    };

    const handleAvatarUpload = async (e) => {
        const file = e.target.files?.[0];
        if (!file || !selectedId) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await api.post(`/sessions/${selectedId}/profile_picture`, formData);
            if (res && res.profile_picture) {
                setCurrentSession(prev => prev ? { ...prev, profile_picture: res.profile_picture } : prev);
                setSessions(prev => prev.map(s => s.session_id === selectedId ? { ...s, profile_picture: res.profile_picture } : s));
                notify.success('Profile image updated!');
            }
        } catch (err) {
            notify.error("Error uploading image.");
        }

        if (avatarUploadRef.current) avatarUploadRef.current.value = '';
    };

    const markSessionRead = async (id) => {
        if (!id) return;
        try {
            await api.put(`/sessions/${id}/read`);
            setSessions(prev => prev.map(s => s.session_id === id ? { ...s, unread_count: 0 } : s));
        } catch (err) {}
    };

    const markSessionOpen = async (id) => {
        try {
            await api.post(`/sessions/${id}/open`);
        } catch (err) {}
    };

    const fetchSessionDetail = async (id) => {
        try {
            const isSameSession = messagesSessionIdRef.current === id;
            if (!isSameSession) {
                setStreamingMessage(null);
                setIsThinking(false);
                setIsSending(false);
                pendingReasoningRef.current = [];
            }

            let snapshot = null;
            try {
                snapshot = await api.get(`/sessions/${id}/snapshot`);
            } catch {
                snapshot = null;
            }

            if (selectedId === id) {
                if (snapshot) {
                    const snapshotMessages = normalizeSnapshotMessages(snapshot);
                    setSessionSnapshot(snapshot);
                    setSessionIndices(snapshot.indices || null);
                    setHasMoreHistory(snapshotMessages.length >= 15);
                    setHistoryOffset(snapshotMessages.length ? Math.min(15, snapshotMessages.length) : 0);
                    setMessages(prev => (isSameSession ? mergeSnapshotMessages(prev, snapshotMessages) : snapshotMessages));
                    setCurrentSession(prev => buildSessionFromSnapshot(snapshot, prev?.session_id === id ? prev : null));
                } else {
                    const data = await api.get(`/sessions/${id}`);
                    const legacyMessages = Array.isArray(data?.history) ? data.history : [];
                    setSessionSnapshot(null);
                    setSessionIndices(null);
                    setHasMoreHistory(legacyMessages.length === 15);
                    setHistoryOffset(15);
                    setMessages(prev => (isSameSession ? mergeSnapshotMessages(prev, legacyMessages) : legacyMessages));
                    setCurrentSession(data);
                }

                messagesSessionIdRef.current = id;

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
        } finally {
            setLoadingMedia(false);
        }
    };

    const fetchPlaybackRuns = async (id) => {
        if (!id) return;
        try {
            const response = await api.get(`/sessions/${id}/playback`);
            setPlaybackRuns(response?.runs || []);
        } catch (error) {}
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
            } catch (error) {}
        };
        tick();
        const interval = setInterval(tick, 15000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [showChatProfile, selectedId]);

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
            <div className="animate-slide-in-right" style={{
                width: (isMobile || desktopFullWidth) ? '100%' : `${desktopSplitProfileWidth}px`,
                height: isMobile ? '100svh' : '100%',
                display: 'flex',
                flexDirection: 'column',
                background: 'transparent',
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
                        {['media', 'docs', 'links', 'tasks', 'metrics', 'health'].map(tab => (
                            <button
                                key={tab}
                                onClick={() => setActiveProfileTab(tab)}
                                style={{
                                    flex: 1,
                                    padding: '8px',
                                    fontSize: '11px',
                                    fontWeight: 'bold',
                                    borderRadius: '8px',
                                    background: activeProfileTab === tab ? 'var(--accent-glow)' : 'transparent',
                                    color: activeProfileTab === tab ? 'var(--accent-color)' : 'var(--text-muted)',
                                    textTransform: 'uppercase',
                                    transition: '0.2s',
                                    whiteSpace: 'nowrap'
                                }}
                            >
                                {tab === 'media' ? 'Fotos' : tab === 'docs' ? 'Files' : tab === 'links' ? 'Links' : tab === 'tasks' ? 'Tasks' : tab === 'metrics' ? 'Metrics' : 'Health'}
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

                            {activeProfileTab === 'tasks' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                    {activeWorkers.filter(w => w.session_id === selectedId).length > 0 ? (
                                        activeWorkers.filter(w => w.session_id === selectedId).map(w => (
                                            <div 
                                                key={w.work_id} 
                                                style={{
                                                    padding: '12px',
                                                    borderRadius: '12px',
                                                    background: 'rgba(59, 130, 246, 0.05)',
                                                    border: '1px solid var(--card-border)',
                                                    transition: 'var(--transition)'
                                                }}
                                            >
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                                                    <Zap size={14} color="var(--accent-color)" className="animate-pulse" />
                                                    <span style={{ fontSize: '13px', fontWeight: 'bold', color: 'var(--text-main)' }}>
                                                        {w.label || w.work_id.substring(0, 8)}
                                                    </span>
                                                </div>
                                                <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0, lineHeight: '1.4' }}>
                                                    {w.context?.summary?.last_thought || 'Thinking...'}
                                                </p>
                                                <div style={{ marginTop: '10px', display: 'flex', justifyContent: 'flex-end' }}>
                                                    <span style={{ fontSize: '10px', color: 'var(--accent-color)', fontWeight: 'bold', textTransform: 'uppercase' }}>
                                                        {w.status || 'Active'}
                                                    </span>
                                                </div>
                                            </div>
                                        ))
                                    ) : (
                                        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontSize: '13px' }}>
                                            No active workers for this session.
                                        </div>
                                    )}
                                </div>
                            )}

                            {activeProfileTab === 'metrics' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                    <div style={{ padding: '12px', borderRadius: '10px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)' }}>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Prompt</div>
                                        <div style={{ fontSize: '13px', color: 'var(--text-main)' }}>Total: ~{promptMetrics.prompt_tokens_approx || 0} tokens</div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                            Actions: ~{promptMetrics?.block_tokens_approx?.['[ACTIONS]'] || 0} · 
                                            State: ~{promptMetrics?.block_tokens_approx?.['[INTERNAL STATE (TOON)]'] || 0} · 
                                            Context: ~{promptMetrics?.block_tokens_approx?.['[SYSTEM CONTEXT]'] || 0}
                                        </div>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                                            Broker: ~{promptMetrics?.block_tokens_approx?.['[BROKER EVIDENCE]'] || 0} · 
                                            Summary: ~{promptMetrics?.block_tokens_approx?.['[SESSION SUMMARY]'] || 0}
                                        </div>
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

                            {activeProfileTab === 'health' && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                                    <div>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '10px', letterSpacing: '0.05em' }}>LLM Providers</div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                            {Object.entries(systemHealth.llm).map(([id, health]) => (
                                                <div key={id} style={{ 
                                                    padding: '12px', 
                                                    borderRadius: '12px', 
                                                    background: health.status === 'online' ? 'rgba(34, 197, 94, 0.05)' : 'rgba(239, 68, 68, 0.05)',
                                                    border: '1px solid var(--card-border)',
                                                    display: 'flex',
                                                    flexDirection: 'column',
                                                    gap: '4px'
                                                }}>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                        <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)' }}>{id}</span>
                                                        <span style={{ 
                                                            fontSize: '10px', 
                                                            padding: '2px 8px', 
                                                            borderRadius: '99px', 
                                                            background: health.status === 'online' ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                                                            color: health.status === 'online' ? '#4ade80' : '#f87171',
                                                            fontWeight: 'bold',
                                                            textTransform: 'uppercase'
                                                        }}>
                                                            {health.status}
                                                        </span>
                                                    </div>
                                                    {health.last_error && (
                                                        <div style={{ 
                                                            fontSize: '11px', 
                                                            color: '#fca5a5', 
                                                            marginTop: '4px',
                                                            fontFamily: 'monospace',
                                                            padding: '6px',
                                                            background: 'rgba(0,0,0,0.2)',
                                                            borderRadius: '6px',
                                                            wordBreak: 'break-all'
                                                        }}>
                                                            {health.last_error}
                                                        </div>
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                    </div>

                                    <div>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '10px', letterSpacing: '0.05em' }}>Capabilities</div>
                                        <div style={{ 
                                            padding: '12px', 
                                            borderRadius: '12px', 
                                            background: 'rgba(255,255,255,0.02)',
                                            border: '1px solid var(--card-border)'
                                        }}>
                                            <div style={{ fontSize: '13px', color: 'var(--text-main)', display: 'flex', justifyContent: 'space-between' }}>
                                                <span>Loaded</span>
                                                <span style={{ fontWeight: 'bold' }}>{systemHealth.capabilities.total || 0}</span>
                                            </div>
                                            <div style={{ fontSize: '13px', color: systemHealth.capabilities.failed > 0 ? '#f87171' : 'var(--text-main)', display: 'flex', justifyContent: 'space-between', marginTop: '6px' }}>
                                                <span>Failed Contracts</span>
                                                <span style={{ fontWeight: 'bold' }}>{systemHealth.capabilities.failed || 0}</span>
                                            </div>
                                        </div>
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
                setHasMoreHistory(data.has_more);
                const rawHistory = data.history;
                const container = scrollRef.current;
                const oldScrollHeight = container ? container.scrollHeight : 0;
                const oldScrollTop = container ? container.scrollTop : 0;

                setMessages(prev => {
                    const existingIds = new Set(prev.map(m => m.id).filter(id => !!id));
                    const newUnique = rawHistory.filter(m => !m.id || !existingIds.has(m.id));
                    return [...newUnique, ...prev];
                });

                setHistoryOffset(prev => prev + data.history.length);

                if (container) {
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

    useEffect(() => {
        if (!selectedId || !hasMoreHistory || isFetchingHistory) return;
        const container = scrollRef.current;
        if (!container) return;

        const noScrollableOverflow = container.scrollHeight <= (container.clientHeight + 24);
        if (noScrollableOverflow) {
            fetchMoreHistory();
        }
    }, [selectedId, hasMoreHistory, isFetchingHistory, historyOffset, messages.length]);

    const handleScroll = (e) => {
        const target = e.target;
        const isNearTop = target.scrollTop <= 60;
        if (isNearTop && hasMoreHistory && !isFetchingHistory) {
            fetchMoreHistory();
        }

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
                setSessionSnapshot(null);
                setSessionIndices(null);
                messagesSessionIdRef.current = null;
            }
            fetchSessions();
        } catch (err) {
            notify.error("Error deleting session.");
        } finally {
            setDeletingSessionId(null);
        }
    };

    const createNewSession = () => {
        setSelectedId(null);
        setMessages([]);
        setCurrentSession(null);
        setSessionSnapshot(null);
        setSessionIndices(null);
        messagesSessionIdRef.current = null;
        setPendingFiles([]);
        setStreamingMessage(null);
        if (isMobile) {
            setMobileView('chat');
        }
    };

    const handleSend = async (e) => {
        if (e) e.preventDefault();
        if (isSending || uploading) return;
        if ((!input.trim() && pendingFiles.length === 0)) return;

        let activeId = selectedId;

        if (!activeId) {
            try {
                const data = await api.post('/sessions', { interface: 'web' });
                if (data && data.id) {
                    activeId = data.id;
                    skipResetRef.current = true;
                    setSelectedId(activeId);
                    setActiveSessionId(activeId);
                    fetchSessions();
                } else {
                    notify.error("Error initializing session.");
                    return;
                }
            } catch (err) {
                notify.error("Error creating session.");
                return;
            }
        }

        const text = input.trim();
        setInput('');

        if (text === '/mock' || text === '/demo') {
            const demoMsgs = [
                {
                    id: 'mock-1',
                    role: 'user',
                    content: 'Gere um relatório de vendas trimestrais e infraestrutura do sistema.',
                    timestamp: Date.now() / 1000 - 60
                },
                {
                    id: 'mock-2',
                    role: 'assistant',
                    content: `Aqui está o relatório de infraestrutura e vendas trimestrais:

| Mês | Vendas | Meta |
|---|---|---|
| Jan | 12000 | 10000 |
| Fev | 15500 | 14000 |
| Mar | 18200 | 16000 |

E aqui está o script de monitoramento do servidor em Python:
\`\`\`python
import psutil
import time

def monitor_system():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    print(f"CPU: {cpu}% | RAM: {mem}%")
    return {"status": "healthy", "cpu": cpu}
\`\`\`
`,
                    timestamp: Date.now() / 1000 - 30,
                    statusPhase: 'complete',
                    isComplete: true,
                    animateTyping: true,
                    work_id: 'work-demo-777',
                    model_info: 'Llama-3.3-70B-Versatile',
                    reasoningTimeline: [
                        { text: 'Analisando os dados do banco de vendas trimestrais...', ts: Date.now() / 1000 - 55 },
                        { text: 'Compilando os gráficos e gerando o script de monitoramento...', ts: Date.now() / 1000 - 40 }
                    ],
                    attachments: [
                        { name: 'relatorio_vendas.pdf', type: 'pdf', url: '/api/static/relatorio_vendas.pdf' },
                        { name: 'dashboard_preview.png', type: 'image', url: '/api/static/dashboard_preview.png' }
                    ]
                },
                {
                    id: 'mock-3',
                    role: 'assistant',
                    content: 'Como está o clima e a saúde do sistema hoje?',
                    timestamp: Date.now() / 1000 - 15,
                    statusPhase: 'complete',
                    isComplete: true,
                    animateTyping: true,
                    capabilities_used: ['weather', 'system_health']
                }
            ];
            setMessages(prev => [...prev, ...demoMsgs]);
            notify.success("Demonstração Mock injetada com sucesso!");
            setTimeout(() => {
                if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
            }, 100);
            return;
        }

        setIsSending(true);

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
            } catch (err) {}
        }

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

        let uploadedFiles = [];
        if (pendingFiles.length > 0) {
            setUploading(true);
            const formData = new FormData();
            pendingFiles.forEach(item => formData.append('files', item.file));

            try {
                const response = await api.post(`/sessions/${activeId}/upload`, formData);
                uploadedFiles = response.files || [];
                pendingFiles.forEach(item => { if (item.previewUrl) URL.revokeObjectURL(item.previewUrl); });
                setPendingFiles([]);
            } catch (err) {
                notify.error("Error sending attachments.");
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

        const userMsg = {
            id: `msg-optimistic-${Date.now()}`,
            role: 'user',
            content: userMsgContent,
            timestamp: Date.now() / 1000,
            isSending: true,
            attachments: uploadedFiles
        };
        setMessages(prev => [...prev, userMsg]);

        const payload = {
            type: 'msg',
            content: userMsgContent,
            attachments: uploadedFiles,
            timestamp: Date.now(),
            user_data: {
                location: location
            }
        };

        if (connectionStatus === 'online' && activeId) {
            sendWebSocketMessage(payload);
        } else {
            try {
                await api.post(`/sessions/${activeId}/message`, {
                    message: userMsgContent,
                    attachments: uploadedFiles,
                    user_data: { location }
                });
            } catch (err) {
                notify.error("Failed to send");
                setIsSending(false);
                setStreamingMessage(null);
            }
        }
    };

    const handleFileUpload = (e) => {
        const files = Array.from(e.target.files || []);
        if (files.length === 0) return;

        if (pendingFiles.length + files.length > 10) {
            notify.error("Maximum of 10 files allowed.");
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

    const PreviewModal = () => {
        const [mdContent, setMdContent] = useState(null);
        const [isTextDocument, setIsTextDocument] = useState(false);
        const [fileExt, setFileExt] = useState('');
        const [isLoadingMd, setIsLoadingMd] = useState(false);
        const [copied, setCopied] = useState(false);
        const [downloaded, setDownloaded] = useState(false);

        useEffect(() => {
            if (!previewFile) return;
            const ext = previewFile.name?.split('.').pop()?.toLowerCase() || '';
            setFileExt(ext);
            
            const mimeType = (previewFile.mime || previewFile.type || previewFile.file?.type || '').toLowerCase();
            const textExtensions = ['md', 'mdx', 'txt', 'js', 'jsx', 'ts', 'tsx', 'py', 'json', 'css', 'html', 'xml', 'csv', 'log', 'sh', 'yaml', 'yml', 'env', 'ini', 'conf', 'toml', 'c', 'cpp', 'h', 'java', 'go', 'rs', 'rb', 'php', 'swift', 'kt', 'sql', 'vue', 'svelte'];
            const isText = textExtensions.includes(ext) || mimeType.startsWith('text/') || mimeType === 'application/json' || mimeType === 'application/javascript';
            
            if (isText) {
                setIsTextDocument(true);
                const formatText = (text) => {
                    if (ext === 'md' || ext === 'mdx') return text;
                    return `\`\`\`${ext || 'txt'}\n${text}\n\`\`\``;
                };

                if (previewFile.file && !previewFile.previewUrl) {
                    const reader = new FileReader();
                    reader.onload = (e) => setMdContent(formatText(e.target.result));
                    reader.readAsText(previewFile.file);
                } else if (previewFile.previewUrl) {
                    setIsLoadingMd(true);
                    fetch(previewFile.previewUrl)
                        .then(res => res.text())
                        .then(text => {
                            setMdContent(formatText(text));
                            setIsLoadingMd(false);
                        })
                        .catch(err => {
                            setMdContent('Failed to load text content.');
                            setIsLoadingMd(false);
                        });
                }
            } else {
                setIsTextDocument(false);
                setMdContent(null);
            }
        }, [previewFile]);

        if (!previewFile) return null;
        const isPending = pendingFiles.some(f => f.name === previewFile.name);

        const handleCopy = (e) => {
            e.stopPropagation();
            if (mdContent) {
                // If we wrapped it, we unwrap it for the copy button, but TypewriterMarkdown already has a copy button for code blocks anyway.
                // It's safer to copy exactly what is being rendered, or we can just copy raw. 
                // Let's copy raw content without the markdown backticks if it's not MD.
                let rawCopy = mdContent;
                if (fileExt !== 'md' && fileExt !== 'mdx' && mdContent.startsWith('```')) {
                    const lines = mdContent.split('\n');
                    rawCopy = lines.slice(1, -1).join('\n');
                }
                navigator.clipboard.writeText(rawCopy);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
            }
        };

        const handleDownload = (e) => {
            e.stopPropagation();
            setDownloaded(true);
            setTimeout(() => setDownloaded(false), 2000);
        };

        return (
            <div className="modal-overlay" style={{ zIndex: 10005, background: 'rgba(5, 7, 10, 0.9)', backdropFilter: 'blur(20px)' }} onClick={() => setPreviewFile(null)}>
                <div className="modal-content glass-panel" onClick={e => e.stopPropagation()} style={{
                    width: isMobile ? '100%' : (isTextDocument ? 'min(90%, 900px)' : 'fit-content'),
                    height: isMobile ? '100%' : (isTextDocument ? '90vh' : 'auto'),
                    maxHeight: isMobile ? '100%' : '90vh',
                    display: 'flex',
                    flexDirection: 'column',
                    borderRadius: isMobile ? '0' : '8px',
                    border: '1px solid rgba(255,255,255,0.08)',
                    boxShadow: '0 24px 60px rgba(0,0,0,0.4)',
                    overflow: 'hidden'
                }}>
                    <div style={{ padding: '16px 24px', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.02)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                            <FilePreviewIcon type={previewFile.type || 'file'} />
                            <div>
                                <h3 style={{ fontSize: '15px', fontWeight: '500', color: 'var(--text-main)', margin: 0, fontFamily: 'monospace' }}>{previewFile.name}</h3>
                                <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '2px 0 0' }}>
                                    {isTextDocument ? (fileExt === 'md' || fileExt === 'mdx' ? 'Markdown Document' : 'Text Document') : 'File Preview'}
                                </p>
                            </div>
                        </div>
                        <button
                            onClick={() => setPreviewFile(null)}
                            className="btn-ghost"
                            style={{ padding: '8px', background: 'rgba(255,255,255,0.05)', borderRadius: '6px', cursor: 'pointer' }}
                        >
                            <X size={18} />
                        </button>
                    </div>

                    <div className="preview-modal-media-container custom-scrollbar" style={{ flex: 1, background: 'rgba(0,0,0,0.2)', padding: 0, position: 'relative', display: 'flex', flexDirection: 'column', overflowY: 'hidden' }}>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '4px', padding: '12px 24px 0', position: 'absolute', top: 0, right: 0, zIndex: 10 }}>
                            {!isPending && isTextDocument && (
                                <button
                                    onClick={handleCopy}
                                    title="Copy Text"
                                    className="btn-ghost"
                                    style={{ padding: '6px', color: copied ? 'var(--success)' : 'var(--text-muted)', background: 'transparent', cursor: 'pointer', borderRadius: '6px' }}
                                >
                                    {copied ? <Check size={16} /> : <Copy size={16} />}
                                </button>
                            )}
                            {!isPending && (
                                <a
                                    href={previewFile.previewUrl}
                                    download={previewFile.name}
                                    title="Download File"
                                    onClick={handleDownload}
                                    className="btn-ghost"
                                    style={{ padding: '6px', color: downloaded ? 'var(--success)' : 'var(--text-muted)', background: 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', borderRadius: '6px' }}
                                >
                                    {downloaded ? <Check size={16} /> : <Download size={16} />}
                                </a>
                            )}
                            {isPending && (
                                <button
                                    onClick={() => {
                                        const idx = pendingFiles.findIndex(f => f.name === previewFile.name);
                                        if (idx !== -1) removePendingFile(idx);
                                        setPreviewFile(null);
                                    }}
                                    title="Remove File"
                                    className="btn-ghost"
                                    style={{ padding: '6px', color: '#ff4444', background: 'transparent', cursor: 'pointer', borderRadius: '6px' }}
                                >
                                    <Trash2 size={16} />
                                </button>
                            )}
                        </div>

                        {previewFile.type === 'image' && !isTextDocument && <img src={previewFile.previewUrl} alt="Preview" style={{ padding: '24px', maxWidth: '100%', objectFit: 'contain' }} />}
                        {previewFile.type === 'video' && !isTextDocument && <video src={previewFile.previewUrl} controls autoPlay style={{ padding: '24px', maxWidth: '100%' }} />}
                        {isTextDocument && (
                            <div className="custom-scrollbar" style={{ flex: 1, padding: isMobile ? '20px' : '40px', overflowY: 'auto' }}>
                                <div style={{ maxWidth: '800px', margin: '0 auto', paddingTop: '20px' }}>
                                    {isLoadingMd ? (
                                        <div style={{ textAlign: 'center', color: 'var(--text-muted)' }}>Carregando conteúdo...</div>
                                    ) : (fileExt === 'md' || fileExt === 'mdx') ? (
                                        <div className="markdown-body" style={{ fontSize: '14px', color: '#f1f5f9', lineHeight: '1.7' }}>
                                            <ReactMarkdown skipHtml>{mdContent || ''}</ReactMarkdown>
                                        </div>
                                    ) : (
                                        <pre style={{ 
                                            fontSize: '13px', 
                                            color: '#f1f5f9', 
                                            lineHeight: '1.6', 
                                            whiteSpace: 'pre-wrap', 
                                            wordBreak: 'break-word', 
                                            fontFamily: 'monospace',
                                            margin: 0
                                        }}>
                                            {mdContent || ''}
                                        </pre>
                                    )}
                                </div>
                            </div>
                        )}
                        {!isTextDocument && previewFile.type !== 'image' && previewFile.type !== 'video' && (
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', color: 'white', padding: '48px' }}>
                                <FilePreviewIcon type={previewFile.type || 'file'} />
                                <span>No preview available</span>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        );
    };

    const DESKTOP_PROFILE_SPLIT_MIN_WIDTH = 1150;
    const shouldUseFullProfileDesktop = !isMobile && showChatProfile && chatPaneWidth > 0 && chatPaneWidth < DESKTOP_PROFILE_SPLIT_MIN_WIDTH;

    return (
        <div className={`animate-fade-in flex-1 ${isMobile ? 'mobile-nav-active' : ''}`} style={{ display: 'flex', flex: 1, minHeight: 0, gap: '0', overflow: 'hidden' }}>
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

            <div className={`mobile-view-container ${mobileView === 'chat' ? 'show-chat' : ''}`} style={{ display: isMobile ? 'flex' : 'contents' }}>
                <div className={`${isMobile ? 'mobile-view-pane' : ''}`} style={{
                    width: isMobile ? '50%' : (isSessionsCollapsed ? '60px' : '300px'),
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    overflow: 'hidden',
                    transition: 'var(--transition)',
                    borderRadius: '0',
                    borderRight: '1px solid var(--card-border)',
                    borderLeft: 'none'
                }}>
                    <div style={{
                        padding: (isSessionsCollapsed && !isMobile) ? '4px 0' : '4px 16px',
                        minHeight: '52px',
                        display: 'flex',
                        flexDirection: (isSessionsCollapsed && !isMobile) ? 'column' : 'row',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '8px',
                        borderBottom: '1px solid var(--card-border)',
                        background: 'transparent'
                    }}>
                        {(!isSessionsCollapsed || isMobile) && <h3 style={{ fontSize: '14px', fontWeight: 'bold', margin: 0 }}>Sessions</h3>}
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
                                            <p style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}>
                                                {new Date(s.updated_at || s.last_active || Date.now()).toLocaleString()}
                                            </p>
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
                            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', opacity: 0.5, gap: '12px', padding: '20px', textAlign: 'center' }}>
                                <MessageSquare size={24} />
                                <p style={{ fontSize: '11px', margin: 0 }}>Nenhuma sessão ativa.<br/>Crie uma nova sessão para iniciar.</p>
                            </div>
                        )}
                    </div>
                </div>

                <div ref={chatPaneRef} className={`${isMobile ? 'mobile-view-pane' : ''}`} style={{
                    flex: isMobile ? 'none' : 1,
                    display: 'flex',
                    flexDirection: 'column',
                    position: 'relative',
                    overflow: 'hidden',
                    borderRadius: '0',
                    borderLeft: 'none',
                    borderRight: 'none'
                }}>
                    <PreviewModal />

                    <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
                        {!shouldUseFullProfileDesktop && (
                            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                                <ChatHeader
                                    isMobile={isMobile}
                                    setMobileView={setMobileView}
                                    selectedId={selectedId}
                                    currentSession={currentSession}
                                    isConnected={isConnected}
                                    isEditingName={isEditingName}
                                    setIsEditingName={setIsEditingName}
                                    editNameValue={editNameValue}
                                    setEditNameValue={setEditNameValue}
                                    handleRenameSession={handleRenameSession}
                                    showActionsMenu={showActionsMenu}
                                    setShowActionsMenu={setShowActionsMenu}
                                    deleteSession={deleteSession}
                                    setShowChatProfile={setShowChatProfile}
                                />

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
                                        sessionSnapshot={sessionSnapshot}
                                        sessionIndices={sessionIndices}
                                    />

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

                                <ChatInputArea
                                    isMobile={isMobile}
                                    isConnected={isConnected}
                                    selectedId={selectedId}
                                    input={input}
                                    setInput={setInput}
                                    handleSend={handleSend}
                                    isSending={isSending}
                                    uploading={uploading}
                                    pendingFiles={pendingFiles}
                                    removePendingFile={removePendingFile}
                                    setPreviewFile={setPreviewFile}
                                    showAttachMenu={showAttachMenu}
                                    setShowAttachMenu={setShowAttachMenu}
                                    fileInputRef={fileInputRef}
                                    inputRef={inputRef}
                                    attachButtonRef={attachButtonRef}
                                    attachMenuRef={attachMenuRef}
                                />
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
