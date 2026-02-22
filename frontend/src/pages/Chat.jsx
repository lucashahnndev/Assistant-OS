import { useState, useEffect, useRef, useMemo, memo } from 'react';
import { useAuth } from '../context/AuthContext';

import { api } from '../hooks/api';
import PlaybackCard from '../components/PlaybackCard';
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
    Download
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

    const handleCopy = () => {
        const text = codeRef.current?.innerText || children.toString();
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        toast.success("Código copiado!");
    };

    if (inline) {
        return <code style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 4px', borderRadius: '4px' }} {...props}>{children}</code>;
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
    if (item.url) return item.url;
    if (!item.path) return null;

    // Standardized path extraction for our proxy route
    if (item.path.includes('/media/')) {
        const parts = item.path.split('/media/');
        return `/api/sessions/${sessionId}/files/media/${parts[parts.length - 1]}`;
    }

    // Legacy /uploads/ support
    if (item.path.includes('/uploads/')) {
        const parts = item.path.split('/uploads/');
        return `/api/sessions/${sessionId}/files/uploads/${parts[parts.length - 1]}`;
    }

    // Fallback for direct data/ paths
    if (item.path.includes('data/')) {
        return `/api/static/${item.path.split('data/')[1]}`;
    }

    return null;
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

        if (date.toDateString() === today.toDateString()) return 'Hoje';
        if (date.toDateString() === yesterday.toDateString()) return 'Ontem';
        return date.toLocaleDateString();
    } catch (e) {
        return '';
    }
};

const MessageItem = memo(({ msg, sessionId, isStreaming = false, onExpand, agentName }) => {
    const [isCognitiveCollapsed, setIsCognitiveCollapsed] = useState(true);
    const [isExpanded, setIsExpanded] = useState(false);
    const isUser = msg.role === 'user';

    useEffect(() => {
        if (msg.isComplete) {
            setIsCognitiveCollapsed(true);
        }
    }, [msg.isComplete]);

    return (
        <div className="animate-fade-in" style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: isUser ? 'flex-end' : 'flex-start',
            width: '100%'
        }}>
            <div className={`msg-bubble ${isUser ? 'msg-user' : 'msg-assistant'}`} style={{
                width: isUser ? 'auto' : '100%',
                maxWidth: isUser ? '85%' : '100%'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', paddingBottom: '8px', borderBottom: isUser ? '1px solid rgba(255,255,255,0.1)' : '1px solid var(--card-border)' }}>
                    <p style={{ fontSize: '11px', fontWeight: 'bold', color: isUser ? '#fff' : 'var(--text-primary)' }}>{isUser ? 'Você' : agentName}</p>
                    {msg.timestamp && <p style={{ fontSize: '10px', color: isUser ? 'rgba(255,255,255,0.7)' : 'var(--text-muted)' }}>{formatTime(msg.timestamp)}</p>}
                </div>
                {isUser && msg.isSending && (
                    <div style={{ position: 'absolute', right: '-25px', top: '50%', transform: 'translateY(-50%)' }}>
                        <RefreshCw size={14} className="animate-spin" color="var(--accent-color)" />
                    </div>
                )}
                {!isUser && (isStreaming) && msg.statusPhase && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px', padding: '10px 14px', background: 'rgba(0,0,0,0.05)', borderRadius: '10px', border: '1px solid var(--card-border)' }}>
                        <div style={{ width: '14px', height: '14px', border: '2px solid rgba(0,0,0,0.1)', borderTopColor: 'var(--accent-color)', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                        <span style={{ fontSize: '12px', fontWeight: '800', textTransform: 'uppercase', color: 'var(--accent-color)', letterSpacing: '0.05em' }}>{msg.statusPhase}</span>
                        {msg.statusMessage && <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: '500' }}>{msg.statusMessage}</span>}
                    </div>
                )}

                {!isUser && msg.reasoningLines && msg.reasoningLines.length > 0 && (
                    !isStreaming && isCognitiveCollapsed ? (
                        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', cursor: 'pointer', padding: '4px 10px', background: 'var(--bg-color)', border: '1px solid var(--card-border)', borderRadius: '12px', marginBottom: '8px', boxShadow: '0 2px 4px rgba(0,0,0,0.05)' }} onClick={() => setIsCognitiveCollapsed(false)} title="Expand Thought">
                            <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981' }} />
                            <span style={{ fontSize: '9px', fontWeight: '800', color: 'var(--text-primary)', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Thought</span>
                        </div>
                    ) : (
                        <div style={{
                            marginBottom: 'var(--space-4)',
                            border: '1px solid var(--card-border)',
                            borderRadius: 'var(--radius-md)',
                            overflow: 'hidden',
                            background: 'rgba(0,0,0,0.02)',
                            fontFamily: '"JetBrains Mono", "Fira Code", monospace'
                        }}>
                            <div style={{
                                padding: 'var(--space-3) var(--space-4)',
                                background: 'rgba(0,0,0,0.04)',
                                borderBottom: '1px solid var(--card-border)',
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                                cursor: 'pointer'
                            }} onClick={() => setIsCognitiveCollapsed(!isCognitiveCollapsed)}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                                    <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: !isStreaming ? '#10b981' : 'var(--accent-color)', animation: !isStreaming ? 'none' : 'pulse 2s infinite' }} />
                                    <span style={{ fontSize: '0.625rem', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                        Cognitive Process // {msg.reasoningLines.length} OP_STEPS
                                    </span>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <button
                                        onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
                                        className="btn-ghost"
                                        style={{ fontSize: '0.625rem', fontWeight: '800', padding: '2px 8px', height: 'auto', borderRadius: '4px' }}
                                    >
                                        {isExpanded ? 'HIDE_RAW' : 'SHOW_RAW'}
                                    </button>
                                    {isCognitiveCollapsed ? <ChevronDown size={14} className="text-muted" /> : <ChevronUp size={14} className="text-muted" />}
                                </div>
                            </div>

                            {isCognitiveCollapsed && isStreaming && msg.reasoningLines.length > 0 && (
                                <div style={{ padding: '8px 16px', borderTop: '1px solid rgba(0,0,0,0.03)' }}>
                                    <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                                        <span style={{ color: 'var(--accent-color)', fontWeight: 'bold', fontSize: '0.75rem' }}>{'>'}</span>
                                        <span style={{
                                            color: 'var(--text-primary)',
                                            fontSize: '0.75rem',
                                            whiteSpace: 'nowrap',
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            opacity: 0.8
                                        }}>
                                            {msg.reasoningLines[msg.reasoningLines.length - 1]}
                                        </span>
                                    </div>
                                </div>
                            )}

                            {!isCognitiveCollapsed && (
                                <>
                                    <div style={{ padding: 'var(--space-4)', fontSize: '0.75rem', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                                        {/* Simplified Timeline View */}
                                        {msg.reasoningLines.slice(-3).map((line, idx) => (
                                            <div key={idx} style={{ display: 'flex', gap: 'var(--space-3)', opacity: idx === (msg.reasoningLines.slice(-3).length - 1) ? 1 : 0.5 }}>
                                                <span style={{ color: 'var(--accent-color)', fontWeight: 'bold' }}>{'>'}</span>
                                                <span style={{ color: 'var(--text-primary)' }}>{line}</span>
                                            </div>
                                        ))}
                                    </div>

                                    {isExpanded && (
                                        <div style={{
                                            padding: 'var(--space-4)',
                                            fontSize: '0.7rem',
                                            background: 'rgba(0,0,0,0.2)',
                                            maxHeight: '200px',
                                            overflowY: 'auto',
                                            borderTop: '1px solid var(--card-border)',
                                            color: 'var(--text-muted)'
                                        }}>
                                            {msg.reasoningLines.map((line, idx) => (
                                                <div key={idx} style={{ marginBottom: '4px' }}>
                                                    <span style={{ opacity: 0.3 }}>[{idx.toString().padStart(2, '0')}]</span> {line}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    )
                )}

                <div style={{ position: 'relative' }}>
                    <MessageAttachments msg={msg} sessionId={sessionId} onExpand={onExpand} />
                    {msg.content ? (
                        <div className="markdown-content">
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
                                {msg.content}
                            </ReactMarkdown>
                        </div>
                    ) : (
                        !isUser && isStreaming && <div style={{ display: 'flex', gap: '6px', padding: '8px 0' }}>
                            {[0, 1, 2].map(i => (
                                <div key={i} style={{ width: '6px', height: '6px', background: 'var(--accent-color)', borderRadius: '50%', animation: `fadeIn 1s infinite ${i * 0.2}s` }} />
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
});

const MessageList = memo(({ messages, sessionId, streamingMessage, onExpand, scrollRef, agentName, onScroll }) => {
    const filteredMessages = useMemo(() =>
        messages.filter(msg => !msg.content.includes('[SYSTEM_NOTIFICATION]')),
        [messages]
    );

    const renderMessagesWithDateDividers = () => {
        const result = [];
        let lastDateStr = null;

        filteredMessages.forEach((msg, i) => {
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
            result.push(<MessageItem key={msg.id || `msg-${i}`} msg={msg} sessionId={sessionId} onExpand={onExpand} agentName={agentName} />);
        });

        if (streamingMessage) {
            result.push(<MessageItem key="streaming" msg={streamingMessage} sessionId={sessionId} isStreaming={true} onExpand={onExpand} agentName={agentName} />);
        }

        return result;
    };

    return (
        <div ref={scrollRef} onScroll={onScroll} className="custom-scrollbar h-full chat-container-bg" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {filteredMessages.length === 0 && !streamingMessage ? (
                <div style={{ margin: 'auto', textAlign: 'center', opacity: 0.8, maxWidth: '400px' }}>
                    <div style={{ width: '64px', height: '64px', background: 'var(--accent-glow)', borderRadius: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px', color: 'var(--accent-color)' }}>
                        <Bot size={32} />
                    </div>
                    <div style={{ padding: '32px', borderRadius: '24px', background: 'var(--card-bg)', border: '1px solid var(--card-border)', boxShadow: '0 10px 30px rgba(0,0,0,0.1)' }}>
                        <h2 style={{ fontSize: '24px', fontWeight: '900', marginBottom: '12px', color: 'var(--text-main)' }}>Sistema Operacional Cognitivo</h2>
                        <p style={{ color: 'var(--text-muted)', fontSize: '15px', lineHeight: '1.6' }}>
                            Pronto para processar. Identificado como <strong>{agentName}</strong>. Qual a sua diretriz?
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
                        <span className="doc-name">{item.name?.split('/').pop() || 'Arquivo'}</span>
                        <span className="doc-meta">{item.mime?.split('/')[1]?.toUpperCase() || 'FILE'}</span>
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

    const scrollRef = useRef(null);
    const inputRef = useRef(null);
    const fileInputRef = useRef(null);
    const avatarUploadRef = useRef(null);
    const attachButtonRef = useRef(null);
    const attachMenuRef = useRef(null);
    const wsRef = useRef(null);
    const thoughtTimeoutRef = useRef(null);
    const skipResetRef = useRef(false); // Flag to skip state clearing during lazy session creation
    const prevLastMsgIdRef = useRef(null); // Tracks last message to intelligently auto-scroll

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

    // Auto-scroll logic: only if near bottom or if it's a NEW message
    const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;
    const lastMsgId = lastMsg?.id || lastMsg?.content;

    useEffect(() => {
        if (scrollRef.current) {
            const container = scrollRef.current;
            const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 150;

            const isNewMessage = prevLastMsgIdRef.current !== lastMsgId;

            if (isNearBottom || (isNewMessage && lastMsg?.role === 'user')) {
                container.scrollTop = container.scrollHeight;
            }

            prevLastMsgIdRef.current = lastMsgId;
        }
    }, [messages, lastMsgId, lastMsg?.role]);

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

        // Cleanup previous
        if (wsRef.current) {
            wsRef.current.close();
        }

        // Connect
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.hostname}:8000/ws/${selectedId}`;

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
                    setStreamingMessage(prev => ({
                        ...(prev || { content: '', reasoningLines: [], role: 'assistant' }),
                        statusPhase: data.phase,
                        statusMessage: data.message,
                        isComplete: false
                    }));
                }


                if (data.type === 'reasoning_chunk') {
                    setStreamingMessage(prev => ({
                        ...(prev || { content: '', reasoningLines: [], role: 'assistant', statusPhase: 'thinking' }),
                        reasoningLines: [...(prev?.reasoningLines || []), data.content]
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
                        const completeMsg = { ...prev, isComplete: true, timestamp: Date.now() / 1000 };
                        // Flush to messages history with deduplication
                        setMessages(history => {
                            // If backend already pushed this via message_added, don't duplicate
                            const alreadyExists = history.some(m =>
                                m.role === completeMsg.role &&
                                m.id &&
                                (m.content === completeMsg.content || (completeMsg.content.length > 0 && m.content.startsWith(completeMsg.content.slice(0, 100))))
                            );
                            if (alreadyExists) return history;
                            return [...history, completeMsg];
                        });
                        return null; // Clear streaming state
                    });
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
                        setMessages(prev => {
                            // 1. Precise Dedup: Check if ID already exists
                            if (prev.some(m => m.id === data.message.id)) return prev;

                            // 2. Fuzzy Dedup/Sync: Try to find a local message (no ID) that matches this one
                            const localMatchIdx = prev.findLastIndex(m =>
                                !m.id &&
                                m.role === data.message.role &&
                                (m.content === data.message.content || (m.content.length > 0 && data.message.content.startsWith(m.content.slice(0, 100))))
                            );

                            if (localMatchIdx !== -1) {
                                const next = [...prev];
                                next[localMatchIdx] = data.message; // Replace with server version (has ID and final timestamp)
                                if (data.role === 'assistant') setStreamingMessage(null);
                                return next;
                            }

                            // 3. Fallback: If it's the user's latest message with a spinner, replace it
                            if (data.role === 'user') {
                                const lastUserIdx = prev.findLastIndex(m => m.role === 'user' && m.isSending);
                                if (lastUserIdx !== -1) {
                                    const next = [...prev];
                                    next[lastUserIdx] = data.message;
                                    return next;
                                }
                            }

                            // 4. Default: Just add it (e.g. system notification or background message)
                            if (data.role === 'assistant') setStreamingMessage(null);
                            return [...prev, data.message];
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
            if (wsRef.current) wsRef.current.close();
        };
    }, [selectedId]);

    // Auto-scroll
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTo({
                top: scrollRef.current.scrollHeight,
                behavior: 'smooth'
            });
        }
    }, [messages]);

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
            toast.success("Nome atualizado");
        } catch (err) {
            console.error("Error renaming session:", err);
            toast.error("Erro ao renomear");
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
                toast.success('Imagem de perfil atualizada!');
            }
        } catch (err) {
            console.error("Error uploading avatar:", err);
            toast.error("Erro ao fazer upload da imagem.");
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

                // Group reasoning messages into their subsequent assistant responses
                const rawHistory = data.history || [];
                const processedHistory = [];
                let currentReasoning = [];

                rawHistory.forEach(msg => {
                    if (msg.type === 'reasoning') {
                        currentReasoning.push(msg.content);
                    } else if (msg.role === 'assistant' && currentReasoning.length > 0) {
                        processedHistory.push({
                            ...msg,
                            reasoningLines: currentReasoning
                        });
                        currentReasoning = [];
                    } else {
                        if (currentReasoning.length > 0) {
                            processedHistory.push({
                                role: 'assistant',
                                content: '',
                                reasoningLines: currentReasoning,
                                isComplete: true
                            });
                            currentReasoning = [];
                        }
                        processedHistory.push(msg);
                    }
                });

                // Handle trailing reasoning if any
                if (currentReasoning.length > 0) {
                    processedHistory.push({
                        role: 'assistant',
                        content: '',
                        reasoningLines: currentReasoning,
                        isComplete: true
                    });
                }

                setMessages(processedHistory);
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

    const fetchMoreHistory = async () => {
        if (!selectedId || isFetchingHistory || !hasMoreHistory) return;

        setIsFetchingHistory(true);
        try {
            const data = await api.get(`/sessions/${selectedId}/history?offset=${historyOffset}&limit=15`);

            if (data && data.history && data.history.length > 0) {
                // Determine if we have more messages to load
                setHasMoreHistory(data.has_more);

                const rawHistory = data.history;
                const processedHistory = [];
                let currentReasoning = [];

                rawHistory.forEach(msg => {
                    if (msg.type === 'reasoning') {
                        currentReasoning.push(msg.content);
                    } else if (msg.role === 'assistant' && currentReasoning.length > 0) {
                        processedHistory.push({
                            ...msg,
                            reasoningLines: currentReasoning
                        });
                        currentReasoning = [];
                    } else {
                        if (currentReasoning.length > 0) {
                            processedHistory.push({
                                role: 'assistant',
                                content: '',
                                reasoningLines: currentReasoning,
                                isComplete: true
                            });
                            currentReasoning = [];
                        }
                        processedHistory.push(msg);
                    }
                });

                if (currentReasoning.length > 0) {
                    processedHistory.push({
                        role: 'assistant',
                        content: '',
                        reasoningLines: currentReasoning,
                        isComplete: true
                    });
                }

                // Save current scroll metrics before state update
                const container = scrollRef.current;
                const oldScrollHeight = container ? container.scrollHeight : 0;
                const oldScrollTop = container ? container.scrollTop : 0;

                setMessages(prev => {
                    // Filter out duplicates using stable IDs
                    const existingIds = new Set(prev.map(m => m.id).filter(id => !!id));
                    const newUnique = processedHistory.filter(m => !m.id || !existingIds.has(m.id));
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

    // Handle infinite scroll + scroll to bottom button
    const handleScroll = (e) => {
        const target = e.target;

        // Infinite scroll (top)
        if (target.scrollTop === 0) {
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
        if (!window.confirm("Deseja realmente excluir esta sessão e todos os seus arquivos?")) return;

        try {
            await api.delete(`/sessions/${id}`);
            if (selectedId === id) {
                setSelectedId(null);
                setMessages([]);
                setCurrentSession(null);
            }
            fetchSessions();
        } catch (err) {
            toast.error("Erro ao excluir sessão.");
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
                    toast.error("Erro ao inicializar sessão.");
                    return;
                }
            } catch (err) {
                toast.error("Erro ao criar sessão.");
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
        setStreamingMessage({
            role: 'assistant',
            content: '',
            reasoningLines: [],
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
                toast.error("Erro ao enviar anexos.");
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
            toast.error("Máximo de 10 arquivos permitidos.");
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
            <p style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 'bold', padding: '4px 10px 8px' }}>Itens Anexados (Máx 10)</p>
            <button onClick={() => { fileInputRef.current.accept = "image/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <Paperclip size={16} color="#ec4899" /> Imagens
            </button>
            <button onClick={() => { fileInputRef.current.accept = "audio/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <Music size={16} color="#10b981" /> Áudio
            </button>
            <button onClick={() => { fileInputRef.current.accept = "video/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <Video size={16} color="#8b5cf6" /> Vídeos
            </button>
            <button onClick={() => { fileInputRef.current.accept = ".pdf,.doc,.docx,.xls,.xlsx,.txt"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <FileText size={16} color="#3b82f6" /> Documentos
            </button>
            <button onClick={() => { fileInputRef.current.accept = "*/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
                <FileIcon size={16} color="#f59e0b" /> Arquivos
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
                                    <Download size={16} /> Baixar Arquivo
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
                    borderRadius: isMobile ? '0' : '16px'
                }}>
                    <div className="glass" style={{
                        padding: (isSessionsCollapsed && !isMobile) ? '8px 0' : '8px 14px',
                        margin: '12px 12px 12px 12px',
                        borderRadius: '12px',
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
                                className={`btn-ghost ${selectedId === s.session_id ? 'active' : ''}`}
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
                                            <p style={{ fontSize: '13px', fontWeight: '600', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{s.name ? s.name : s.session_id.substring(0, 18) + "..."}</p>
                                            <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{new Date(s.updated_at || s.last_active || Date.now()).toLocaleString()}</p>
                                        </div>
                                        {s.unread_count > 0 && (
                                            <div style={{
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
                                                padding: '0 5px'
                                            }}>
                                                {s.unread_count}
                                            </div>
                                        )}
                                        <button
                                            onClick={(e) => deleteSession(e, s.session_id)}
                                            className="btn-ghost delete-session-btn"
                                            style={{ padding: '4px', opacity: isMobile ? 1 : 0, transition: '0.2s', color: 'var(--error)', position: 'absolute', right: '4px' }}
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    </>
                                )}
                            </div>
                        )) : (
                            (!isSessionsCollapsed || isMobile) && <p style={{ textAlign: 'center', marginTop: '20px', fontSize: '12px', color: 'var(--text-muted)' }}>No active sessions.</p>
                        )}
                    </div>
                </div>

                {/* Chat Area (Mobile View Pane 2) */}
                <div className={`${isMobile ? 'mobile-view-pane' : ''} glass`} style={{
                    flex: isMobile ? 'none' : 1,
                    display: 'flex',
                    flexDirection: 'column',
                    position: 'relative',
                    overflow: 'hidden',
                    borderRadius: isMobile ? '0' : '16px'
                }}>
                    <PreviewModal />
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
                                onClick={currentSession.source === 'web' || currentSession.interface === 'web' ? () => avatarUploadRef.current?.click() : undefined}
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
                                        onClick={() => { if (selectedId) { setIsEditingName(true); setEditNameValue(currentSession?.name || ''); } }}
                                    >
                                        {selectedId ? (currentSession?.name || `Session: ${selectedId.substring(0, 8)}...`) : 'Select a session'}
                                    </h3>
                                    {(!isMobile && selectedId) && <Edit size={12} style={{ opacity: 0.5, transition: '0.2s', cursor: 'pointer' }} onClick={(e) => { e.stopPropagation(); setIsEditingName(true); setEditNameValue(currentSession?.name || ''); }} className="hover:opacity-100" />}
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
                                            <Trash2 size={16} /> Excluir Sessão
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
                                            <Edit size={16} /> Renomear
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>


                    {/* Messages Container */}
                    <div className="flex-1 overflow-hidden flex flex-col relative">
                        {/* Playback Overlay (Live) */}
                        {latestPlaybackEvent && latestPlaybackEvent.type !== 'playback.end' && (
                            <div style={{
                                position: 'absolute',
                                top: '10px',
                                right: isMobile ? '10px' : '24px',
                                width: isMobile ? 'calc(100% - 20px)' : '320px',
                                zIndex: 100,
                                pointerEvents: 'auto'
                            }}>
                                <PlaybackCard
                                    runId={latestPlaybackEvent.run_id}
                                    sessionId={selectedId}
                                    liveEvent={latestPlaybackEvent}
                                />
                            </div>
                        )}

                        <MessageList
                            messages={messages}
                            sessionId={selectedId}
                            streamingMessage={streamingMessage}
                            onExpand={setPreviewFile}
                            scrollRef={scrollRef}
                            agentName={agentName}
                            onScroll={handleScroll}
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
                        padding: isMobile ? '4px 10px calc(12px + env(safe-area-inset-bottom))' : '8px 24px 4px',
                        borderTop: '1px solid var(--card-border)',
                        background: 'var(--bg-color)',
                        position: 'relative',
                        zIndex: 10
                    }}>
                        {pendingFiles.length > 0 && (
                            <div className="previews-container animate-fade-in" style={{
                                marginBottom: '12px',
                                padding: '8px',
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
                            borderRadius: isMobile ? '24px' : '16px',
                            boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
                            overflow: 'hidden',
                            transition: 'var(--transition)'
                        }} className="input-container-complex">
                            <textarea
                                ref={inputRef}
                                rows="1"
                                placeholder={(isConnected || !selectedId) ? (uploading ? "Sincronizando..." : "Mensagem...") : "Conectando..."}
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
                                    padding: isMobile ? '12px 48px 12px 48px' : '16px 60px 16px 60px',
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'var(--text-main)',
                                    fontSize: isMobile ? '14px' : '15px',
                                    resize: 'none',
                                    minHeight: isMobile ? '44px' : '56px',
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
                                    position: 'absolute', left: isMobile ? '8px' : '12px', bottom: isMobile ? '6px' : '10px',
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
                                    position: 'absolute', right: isMobile ? '8px' : '12px', bottom: isMobile ? '6px' : '10px',
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
                        {!isMobile && (
                            <div style={{ marginTop: '0px', display: 'flex', justifyContent: 'center' }}>
                                <div style={{
                                    padding: '0 24px',
                                    textAlign: 'center',
                                    flexShrink: 0
                                }}>
                                    <div style={{
                                        display: 'inline-flex',
                                        fontSize: '11px',
                                        color: 'var(--text-muted)',
                                        gap: '4px',
                                        alignItems: 'center',
                                        opacity: 0.8
                                    }}>
                                        Pressione <strong>Enter</strong> para enviar, <strong>Ctrl + Enter</strong> para nova linha.
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Chat;
