import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../hooks/api';
import PlaybackCard from '../components/PlaybackCard';
import ConfirmDialog from '../components/ConfirmDialog';
import toast from 'react-hot-toast';
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
    Zap
} from 'lucide-react';

import { SessionAvatar } from '../components/chat/ChatIcons';
import { ChatHeader } from '../components/chat/ChatHeader';
import { ChatInputArea } from '../components/chat/ChatInputArea';
import { MessageList } from '../components/chat/MessageItem';
import { FilePreviewIcon } from '../components/chat/MessageAttachments';
import { formatDate } from '../utils/chatHistoryTransform';

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
    const [isSessionsCollapsed, setIsSessionsCollapsed] = useState(() => {
        return localStorage.getItem('assistant_chat_sessions_collapsed') === 'true';
    });

    const [isEditingName, setIsEditingName] = useState(false);
    const [editNameValue, setEditNameValue] = useState("");

    const [activeWorkers, setActiveWorkers] = useState([]);
    const [systemHealth, setSystemHealth] = useState({ llm: {}, capabilities: {} });

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
                setSelectedId(sorted[0].session_id);
            }
        } catch (err) {
            console.error("Error fetching sessions:", err);
            toast.error("Error loading sessions.");
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

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsHost = window.location.host;
        let wsUrl = `${protocol}//${wsHost}/ws/${selectedId}`;

        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            if (isSub) setIsConnected(true);
        };

        ws.onmessage = (event) => {
            if (!isSub) return;
            try {
                const raw = JSON.parse(event.data);
                if (raw.type === 'ping') return;

                if (raw.type === 'system_metrics' || raw.type === 'system_health') {
                    if (raw.data?.active_workers) setActiveWorkers(raw.data.active_workers);
                    if (raw.data?.health) setSystemHealth(raw.data.health);
                    return;
                }

                if (raw.type === 'worker_state') {
                    setActiveWorkers(prev => {
                        const next = [...prev];
                        const idx = next.findIndex(w => w.work_id === raw.data?.work_id);
                        if (idx >= 0) next[idx] = { ...next[idx], ...raw.data };
                        else if (raw.data) next.push(raw.data);
                        return next.filter(w => w.status !== 'complete' && w.status !== 'failed');
                    });
                    return;
                }

                if (raw.type === 'playback_stream') {
                    setLatestPlaybackEvent(raw.data);
                    return;
                }

                if (raw.type === 'status') {
                    setStreamingMessage(prev => {
                        const content = prev ? prev.content : '';
                        return {
                            role: 'assistant',
                            content: content,
                            reasoningLines: prev?.reasoningLines || [],
                            reasoningTimeline: prev?.reasoningTimeline || [],
                            statusPhase: raw.phase || 'thinking',
                            statusMessage: raw.message || 'Processing...',
                            isComplete: false,
                            work_id: raw.work_id || prev?.work_id,
                            model_info: raw.model_info || prev?.model_info
                        };
                    });
                    return;
                }

                if (raw.type === 'thought' || raw.type === 'cognitive_thought' || raw.type === 'assistant_thought' || raw.type === 'reasoning_chunk') {
                    setIsThinking(true);
                    const thoughtText = raw.thought || raw.content || '';
                    if (thoughtText) setThought(thoughtText);

                    if (thoughtText && thoughtText.trim()) {
                        pendingReasoningRef.current.push({
                            text: thoughtText.trim(),
                            ts: raw.timestamp ? raw.timestamp : Date.now() / 1000
                        });
                    }

                    if (thoughtTimeoutRef.current) clearTimeout(thoughtTimeoutRef.current);
                    thoughtTimeoutRef.current = setTimeout(() => {
                        setIsThinking(false);
                    }, 5000);

                    setStreamingMessage(prev => {
                        const content = prev ? prev.content : '';
                        const currentLines = prev?.reasoningLines || [];
                        const nextLines = thoughtText ? [...currentLines, thoughtText] : currentLines;
                        return {
                            role: 'assistant',
                            content: content,
                            reasoningLines: nextLines,
                            reasoningTimeline: pendingReasoningRef.current,
                            statusPhase: raw.phase || (prev ? prev.statusPhase : 'thinking'),
                            statusMessage: thoughtText || (prev ? prev.statusMessage : ''),
                            isComplete: false,
                            work_id: raw.work_id || prev?.work_id,
                            model_info: raw.model_info || prev?.model_info
                        };
                    });
                    return;
                }

                if (raw.type === 'stream' || raw.type === 'final_message_chunk') {
                    setIsSending(false);
                    setIsThinking(false);

                    setStreamingMessage(prev => {
                        const currentContent = prev ? prev.content : '';
                        const nextContent = currentContent + (raw.chunk || raw.content || '');
                        return {
                            role: 'assistant',
                            content: nextContent,
                            reasoningLines: prev?.reasoningLines || [],
                            reasoningTimeline: pendingReasoningRef.current,
                            statusPhase: raw.phase || 'responding',
                            statusMessage: raw.status || 'Streaming response...',
                            isComplete: false,
                            work_id: raw.work_id || prev?.work_id,
                            model_info: raw.model_info || prev?.model_info
                        };
                    });
                    return;
                }

                if (raw.type === 'complete' || raw.type === 'msg' || raw.type === 'message' || raw.type === 'assistant_response') {
                    setIsSending(false);
                    setIsThinking(false);

                    if (thoughtTimeoutRef.current) clearTimeout(thoughtTimeoutRef.current);
                    if (completeFlushTimeoutRef.current) clearTimeout(completeFlushTimeoutRef.current);

                    const finalContent = raw.content || raw.message || raw.full_text || streamingMessageRef.current?.content || '';
                    const finalReasoning = [...(pendingReasoningRef.current || [])];
                    const finalWorkId = raw.work_id || streamingMessageRef.current?.work_id;
                    const finalModelInfo = raw.model_info || raw.provenance || streamingMessageRef.current?.model_info;

                    const finalMsg = {
                        id: raw.message_id || `msg-${Date.now()}`,
                        role: raw.role || 'assistant',
                        content: finalContent,
                        timestamp: raw.timestamp ? raw.timestamp / 1000 : Date.now() / 1000,
                        reasoningTimeline: finalReasoning,
                        work_id: finalWorkId,
                        model_info: finalModelInfo,
                        statusPhase: 'complete',
                        isComplete: true,
                        animateTyping: true,
                        attachments: raw.attachments || [],
                        contentSegments: raw.contentSegments || []
                    };

                    setStreamingMessage(null);
                    pendingReasoningRef.current = [];

                    setMessages(prev => {
                        const filtered = prev.filter(m => !m.isSending);
                        if (filtered.some(m => m.id === finalMsg.id)) return filtered;
                        return [...filtered, finalMsg];
                    });

                    setTimeout(() => {
                        if (scrollRef.current) {
                            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
                        }
                    }, 100);

                    fetchSessions();
                    return;
                }
            } catch (err) {
                console.error("WS Parse error:", err, event.data);
            }
        };

        ws.onerror = () => {
            if (isSub) setIsConnected(false);
        };

        ws.onclose = () => {
            if (isSub) setIsConnected(false);
        };

        return () => {
            isSub = false;
            ws.close();
            if (thoughtTimeoutRef.current) clearTimeout(thoughtTimeoutRef.current);
            if (completeFlushTimeoutRef.current) clearTimeout(completeFlushTimeoutRef.current);
        };
    }, [selectedId]);

    const handleRenameSession = async () => {
        if (!selectedId || !isEditingName) return;
        try {
            await api.put(`/sessions/${selectedId}`, { name: editNameValue });
            setSessions(prev => prev.map(s => s.session_id === selectedId ? { ...s, name: editNameValue } : s));
            if (currentSession) setCurrentSession(prev => ({ ...prev, name: editNameValue }));
            toast.success("Session renamed!");
        } catch (err) {
            toast.error("Failed to rename session.");
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
                toast.success('Profile image updated!');
            }
        } catch (err) {
            toast.error("Error uploading image.");
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
            const data = await api.get(`/sessions/${id}`);
            if (selectedId === id) {
                setHasMoreHistory(data.history?.length === 15);
                setHistoryOffset(15);
                setMessages(data.history || []);
                setCurrentSession(data);

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
        const interval = setInterval(tick, 3000);
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
            toast.success("Demonstração Mock injetada com sucesso!");
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

        const userMsg = {
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

                <div ref={chatPaneRef} className={`${isMobile ? 'mobile-view-pane' : ''} glass`} style={{
                    flex: isMobile ? 'none' : 1,
                    display: 'flex',
                    flexDirection: 'column',
                    position: 'relative',
                    overflow: 'hidden',
                    borderRadius: isMobile ? '0' : '8px'
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
