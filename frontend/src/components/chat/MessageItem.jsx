import { notify } from '../../utils/notify.jsx';
import React, { useState, useEffect, useMemo, memo } from 'react';
import {
    Brain, RefreshCw, Square, CloudSun, HeartPulse, BarChart3,
    BookOpen, Globe, Video, Music, FileText, ChevronUp, ChevronDown, Bot
} from 'lucide-react';

import { api } from '../../hooks/api';
import { useAssistCards } from '../../hooks/useAssistCards';
import {
    WeatherAssistCard, SystemHealthAssistCard, DataChartAssistCard,
    WikiAssistCard, MapAssistCard, WegenaAssistCard
} from '../AssistCards';
import PlaybackCard from '../PlaybackCard';
import LinkPreviewCard from '../LinkPreviewCard';
import { WorkUnitInspector } from './WorkUnitInspector';
import { TypewriterMarkdown } from './TypewriterMarkdown';
import { MessageAttachments } from './MessageAttachments';
import { formatTime, formatDate, normalizeReasoningTimeline, groupHistoryWithReasoning } from '../../utils/chatHistoryTransform';
import { buildThoughtTimelineBlocks, normalizeThoughtTimelineItem, formatDurationMs } from './ThoughtTimeline.utils';
import { ThoughtTimeline } from './ThoughtTimeline';

export const SegmentDivider = () => (
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

const TERMINAL_WORK_STATUSES = new Set(['complete', 'succeeded', 'failed', 'cancelled']);
const ACTIVE_WORK_STATUSES = new Set(['queued', 'running', 'waiting_user', 'paused', 'thinking', 'responding']);

const getThoughtDisplayKey = (message) => {
    if (!message || typeof message !== 'object') return 'thought:global';
    const turnId = message.turn_id ?? message.turnId ?? null;
    if (turnId !== null && turnId !== undefined && turnId !== '') return `turn:${turnId}`;
    if (message.stream_id || message.streamId) return `stream:${message.stream_id || message.streamId}`;
    if (message.work_id || message.workId) return `work:${message.work_id || message.workId}`;
    if (message.id || message.message_id || message.messageId) return `message:${message.id || message.message_id || message.messageId}`;
    return 'thought:global';
};

const stripReasoningPresentation = (message) => {
    if (!message || typeof message !== 'object') return null;

    const role = String(message.role || '').trim().toLowerCase();
    const msgType = String(message.type || message.msg_type || '').trim().toLowerCase();
    if (msgType === 'reasoning' || (role === 'system' && msgType === 'reasoning')) {
        return null;
    }

    const next = { ...message };
    delete next.reasoningLines;
    delete next.reasoningTimeline;
    return next;
};

export const WorkControlButton = memo(({ workId, sessionId, isStreaming, statusPhase }) => {
    const [busy, setBusy] = useState(false);
    const [workStatus, setWorkStatus] = useState(null);

    const fetchWorkStatus = async () => {
        if (!workId) return;
        try {
            const data = await api.get(`/tasks/works/${workId}`);
            const nextStatus = String(data?.status || '').toLowerCase();
            if (nextStatus) setWorkStatus(nextStatus);
        } catch {
            // silent catch
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
                notify.success(`Worker restarted${restartedId}`);
            } else {
                await api.post(`/tasks/works/${workId}/commands`, {
                    command: 'cancel',
                    payload: { reason: 'Stopped from chat' },
                    requester_session_id: sessionId,
                    source_session_id: sessionId,
                });
                notify.success('Stop signal sent');
                setTimeout(() => fetchWorkStatus(), 700);
            }
        } catch (err) {
            notify.error(err?.message || 'Failed to control worker');
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

export const InlineApprovalBar = memo(({ workId, sessionId, statusPhase, approvalRequest, statusMessage }) => {
    const [busy, setBusy] = useState(false);
    const [snapshot, setSnapshot] = useState(null);
    const [localDecision, setLocalDecision] = useState(null);

    const fetchSnapshot = async () => {
        if (!workId) return;
        try {
            const data = await api.get(`/tasks/works/${workId}?requester_session_id=${encodeURIComponent(sessionId || '')}`);
            setSnapshot(data || null);
        } catch {
            // silent catch
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
            notify.error(err?.message || 'Failed to send decision');
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

export const ChatCollapsibleAssistCard = memo(({
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

export const MessageItem = memo(({ msg, sessionId, isStreaming = false, onExpand, agentName, latestPlaybackEvent, thoughtBlock = null }) => {
    const [isWorkDetailsOpen, setIsWorkDetailsOpen] = useState(false);
    const [isThoughtOpen, setIsThoughtOpen] = useState(false);
    const [isCopied, setIsCopied] = useState(false);
    
    const handleCopy = () => {
        const textToCopy = msg.contentSegments?.map(s => s.content).join('\n') || msg.content || '';
        if (!textToCopy) return;
        navigator.clipboard.writeText(textToCopy);
        setIsCopied(true);
        setTimeout(() => setIsCopied(false), 2000);
    };
    const isUser = msg.role === 'user';
    const reasoningTimeline = normalizeReasoningTimeline(msg);
    const displayReasoningTimeline = useMemo(() => {
        const baseTimeline = reasoningTimeline
        .map((entry, idx) => normalizeThoughtTimelineItem(entry, {
            id: `${msg?.id || msg?.message_id || 'msg'}-reasoning-${idx}`,
            key: `${msg?.id || msg?.message_id || 'msg'}-reasoning-${idx}`,
            source: 'history',
            turnId: msg.turn_id ?? msg.turnId ?? null,
            streamId: msg.stream_id ?? msg.streamId ?? null,
            workId: msg.work_id ?? msg.workId ?? null,
            messageId: msg.id ?? msg.message_id ?? msg.messageId ?? null,
            ts: entry?.ts ?? msg.timestamp ?? null,
            summary: entry?.summary || entry?.description || entry?.message || '',
            capability: entry?.capability || entry?.capability_name || entry?.capability_id || null,
            kind: entry?.kind || entry?.type || entry?.event_type || 'reasoning',
            visibility: entry?.visibility || null,
        }))
        .filter(Boolean);

        const blockEntries = Array.isArray(thoughtBlock?.entries) ? thoughtBlock.entries : [];
        blockEntries.forEach((entry, idx) => {
            const normalized = normalizeThoughtTimelineItem(entry, {
                id: `${thoughtBlock?.key || msg?.id || 'thought'}-${idx}`,
                key: `${thoughtBlock?.key || msg?.id || 'thought'}-${idx}`,
                source: thoughtBlock?.source || 'snapshot',
                turnId: thoughtBlock?.turnId ?? msg.turn_id ?? msg.turnId ?? null,
                streamId: thoughtBlock?.streamId ?? msg.stream_id ?? msg.streamId ?? null,
                workId: thoughtBlock?.workId ?? msg.work_id ?? msg.workId ?? null,
                messageId: thoughtBlock?.messageId ?? msg.id ?? msg.message_id ?? msg.messageId ?? null,
                ts: entry?.ts ?? entry?.timestamp ?? thoughtBlock?.timestamp ?? msg.timestamp ?? null,
                summary: entry?.summary || entry?.description || entry?.message || entry?.content || '',
                capability: entry?.capability || entry?.capability_name || entry?.capability_id || thoughtBlock?.capability || null,
                kind: entry?.kind || entry?.type || entry?.event_type || thoughtBlock?.kind || 'reasoning',
                visibility: entry?.visibility || thoughtBlock?.visibility || null,
                raw: entry?.raw || null,
            });
            if (normalized) baseTimeline.push(normalized);
        });

        return baseTimeline;
    }, [
        reasoningTimeline,
        thoughtBlock,
        msg?.id,
        msg?.message_id,
        msg?.messageId,
        msg?.turn_id,
        msg?.turnId,
        msg?.stream_id,
        msg?.streamId,
        msg?.work_id,
        msg?.workId,
        msg?.timestamp,
    ]);
    const hasReasoning = !isUser && displayReasoningTimeline.length > 0;
    const statusPhaseNormalized = String(msg?.statusPhase || '').toLowerCase();
    const getPhaseColor = (phase) => {
        if (['thinking', 'reasoning'].includes(phase)) return '#a855f7';
        if (['tool_use', 'executing', 'action'].includes(phase)) return '#3b82f6';
        if (['error', 'failed', 'refusal'].includes(phase)) return '#ef4444';
        return 'var(--accent-color)';
    };
    const phaseColor = getPhaseColor(statusPhaseNormalized);
    const isTerminalPhase = ['complete', 'completed', 'succeeded', 'success', 'done', 'failed', 'error', 'aborted', 'cancelled', 'canceled'].includes(statusPhaseNormalized);
    const isActivelyStreaming = isStreaming && !isTerminalPhase;
    const reasoningBlock = useMemo(() => ({
        key: `message-${msg?.id || msg?.message_id || msg?.messageId || 'reasoning'}`,
        title: 'Pensamento',
        entries: displayReasoningTimeline,
        isLive: isActivelyStreaming,
        defaultOpen: false,
    }), [displayReasoningTimeline, isActivelyStreaming, msg?.id, msg?.message_id, msg?.messageId]);
    const latestReasoningEntry = displayReasoningTimeline[displayReasoningTimeline.length - 1] || null;
    const reasoningDurationText = formatDurationMs(
        latestReasoningEntry?.thinkingDurationMs
        ?? reasoningBlock?.thinkingDurationMs
        ?? reasoningBlock?.streamDurationMs
        ?? reasoningBlock?.turnDurationMs
        ?? null
    );

    useEffect(() => {
        if (!hasReasoning) {
            setIsThoughtOpen(false);
            return;
        }

        if (isActivelyStreaming) {
            setIsThoughtOpen(true);
            return;
        }

        if (msg.statusPhase === 'complete' || msg.isComplete || ['completed', 'succeeded', 'done', 'success'].includes(statusPhaseNormalized)) {
            setIsThoughtOpen(false);
        }
    }, [hasReasoning, isActivelyStreaming, msg.statusPhase, msg.isComplete, statusPhaseNormalized]);

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
    const capabilityHints = useMemo(() => {
        const contextCapabilities = msg?.context?.data?.capabilities_used;
        return [
            ...(Array.isArray(msg?.capabilities_used) ? msg.capabilities_used : []),
            ...(Array.isArray(contextCapabilities) ? contextCapabilities : []),
        ];
    }, [msg?.capabilities_used, msg?.context?.data?.capabilities_used]);
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
        shouldTryWegenaCard,
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
        wegenaMediaUrl
    } = useAssistCards({
        sessionId,
        workId: msg?.work_id,
        text: cardDetectionText,
        isUser,
        isStreaming: isActivelyStreaming,
        capabilitiesUsed: capabilityHints,
        actionsUsed: actionHints,
        sourcesUsed: sourceHints,
    });

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
                        <p style={{ fontSize: '11px', fontWeight: 'bold', color: isUser ? '#fff' : 'var(--text-primary)', flexShrink: 0 }}>
                            {isUser ? 'You' : (agentName || 'A.T.L.A.S.')}
                        </p>

                        {!isUser && msg.model_info && (
                            <div style={{
                                fontSize: '9px',
                                fontWeight: '800',
                                color: 'var(--accent-color)',
                                background: 'rgba(59, 130, 246, 0.12)',
                                padding: '2px 8px',
                                borderRadius: '100px',
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                border: '1px solid rgba(59, 130, 246, 0.25)',
                                backdropFilter: 'blur(4px)',
                                boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
                                flexShrink: 0,
                                marginLeft: '8px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px'
                            }}>
                                <span style={{ opacity: 0.7 }}>PROVENANCE:</span>
                                {msg.model_info}
                            </div>
                        )}

                        {msg.timestamp && <p style={{ fontSize: '10px', color: isUser ? 'rgba(255,255,255,0.7)' : 'var(--text-muted)', flexShrink: 0, marginLeft: '4px' }}>{formatTime(msg.timestamp)}</p>}
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

                        {!isUser && hasReasoning && (
                            <button
                                type="button"
                                onClick={() => setIsThoughtOpen((prev) => !prev)}
                                className="btn-ghost"
                                title={isThoughtOpen ? 'Hide reasoning' : 'Show reasoning'}
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: reasoningDurationText ? '6px' : '0',
                                    width: 'auto',
                                    height: '22px',
                                    minWidth: '22px',
                                    padding: reasoningDurationText ? '0 2px' : 0,
                                    border: 'none',
                                    background: 'transparent',
                                    color: 'var(--text-muted)',
                                    flexShrink: 0,
                                    opacity: isThoughtOpen ? 1 : 0.7,
                                    transition: 'opacity 0.15s ease',
                                }}
                            >
                                <Brain size={11} color="var(--accent-color)" />
                                {reasoningDurationText && (
                                    <span style={{
                                        fontSize: '9px',
                                        fontWeight: 800,
                                        color: 'var(--text-muted)',
                                        opacity: 0.8,
                                        letterSpacing: '0.04em',
                                        whiteSpace: 'nowrap',
                                    }}>
                                        {reasoningDurationText}
                                    </span>
                                )}
                            </button>
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
                                    borderTopColor: phaseColor,
                                    borderRadius: '50%',
                                    animation: 'spin 1s linear infinite',
                                    flexShrink: 0
                                }} />
                                <span style={{
                                    fontSize: '9px',
                                    fontWeight: '800',
                                    textTransform: 'uppercase',
                                    color: phaseColor,
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

                {!isUser && shouldTryWegenaCard && (
                    <ChatCollapsibleAssistCard
                        sessionId={sessionId}
                        anchorId={anchorId}
                        cardType="wegena"
                        title="Visual Scene"
                        defaultOpen={true}
                    >
                        <WegenaAssistCard context="chat" data={{ id: msg?.id || anchorId, title: "Cena Gerada", description: "Wegena Engine Visual", scriptUrl: wegenaMediaUrl }} />
                    </ChatCollapsibleAssistCard>
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
                </div>

                {hasReasoning && isThoughtOpen && (
                    <ThoughtTimeline block={reasoningBlock} />
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
                                    animateTyping={!isUser && (msg.animateTyping || (!msg.timestamp || msg.timestamp > (Date.now() / 1000 - 30)))}
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
                                animateTyping={!isUser && (msg.animateTyping || (!msg.timestamp || msg.timestamp > (Date.now() / 1000 - 30)))}
                            />
                        ) : null}
                        {!isUser && isActivelyStreaming && !msg.content && !hasReasoning && !msg.playback && (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', opacity: 0.6, padding: '4px 0' }}>
                                <div style={{ height: '10px', width: '80%', background: 'var(--card-border)', borderRadius: '4px', animation: 'pulse 1.5s infinite ease-in-out' }} />
                                <div style={{ height: '10px', width: '60%', background: 'var(--card-border)', borderRadius: '4px', animation: 'pulse 1.5s infinite ease-in-out', animationDelay: '0.2s' }} />
                            </div>
                        )}
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

export const MessageList = memo(({ messages, sessionId, streamingMessage, onExpand, scrollRef, agentName, onScroll, latestPlaybackEvent, playbackRuns, onSuggestionClick, sessionIndices }) => {
    const displayStreamingMessage = useMemo(() => stripReasoningPresentation(streamingMessage), [streamingMessage]);

    const thoughtBlocks = useMemo(() => buildThoughtTimelineBlocks({
        sessionIndices,
        streamingMessage,
    }), [sessionIndices, streamingMessage]);

    const thoughtBlockMap = useMemo(() => {
        const map = new Map();
        thoughtBlocks.forEach((block) => {
            map.set(block.key, block);
        });
        return map;
    }, [thoughtBlocks]);

    const combinedMessages = useMemo(() => {
        const history = (Array.isArray(messages) ? messages : [])
            .filter((msg) => msg && typeof msg === 'object')
            .filter((msg) => !String(msg.content || '').includes('[SYSTEM_NOTIFICATION]'));
        if (displayStreamingMessage) {
            return [...history, displayStreamingMessage];
        }
        return history;
    }, [messages, displayStreamingMessage]);

    const groupedHistory = useMemo(() => groupHistoryWithReasoning(combinedMessages), [combinedMessages]);
    const displayHistory = useMemo(() => groupedHistory
        .map(stripReasoningPresentation)
        .filter(Boolean), [groupedHistory]);

    const renderMessagesWithDateDividers = () => {
        const result = [];
        let lastDateStr = null;

        displayHistory.forEach((msg, i) => {
            const thoughtKey = getThoughtDisplayKey(msg);
            const thoughtBlock = thoughtBlockMap.get(thoughtKey);

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
                msg.id === displayStreamingMessage?.id ||
                (msg.stream_id && msg.stream_id === displayStreamingMessage?.stream_id) ||
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
                thoughtBlock={thoughtBlock}
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
