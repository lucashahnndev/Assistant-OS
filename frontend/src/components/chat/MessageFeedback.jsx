import React, { memo, useEffect, useMemo, useState } from 'react';
import { ThumbsUp, ThumbsDown } from 'lucide-react';

import { api } from '../../hooks/api';
import { notify } from '../../utils/notify.jsx';

const normalizeMessageId = (message) => {
    if (!message || typeof message !== 'object') return '';
    return String(message.id || message.message_id || message.messageId || '').trim();
};

const findFeedbackRecord = (sessionIndices, messageId) => {
    const normalizedId = String(messageId || '').trim();
    if (!normalizedId) return null;

    const feedbackItems = sessionIndices?.feedback?.items;
    if (!feedbackItems || typeof feedbackItems !== 'object') return null;

    const keyed = feedbackItems[`${sessionIndices?.session_id || ''}:${normalizedId}`];
    if (keyed && typeof keyed === 'object') return keyed;

    return Object.values(feedbackItems).find((record) => (
        record
        && typeof record === 'object'
        && String(record.message_id || '').trim() === normalizedId
    )) || null;
};

export const MessageFeedback = memo(({ sessionId, message, sessionIndices, isStreaming = false, className = '' }) => {
    const messageId = normalizeMessageId(message);
    const role = String(message?.role || '').trim().toLowerCase();
    const msgType = String(message?.type || message?.msg_type || '').trim().toLowerCase();
    const isAssistantResponse = role === 'assistant' && !isStreaming && msgType !== 'reasoning' && msgType !== 'internal_event';

    const snapshotFeedback = useMemo(
        () => findFeedbackRecord(sessionIndices, messageId),
        [sessionIndices, messageId]
    );

    const [rating, setRating] = useState(snapshotFeedback?.rating || null);
    const [commentDraft, setCommentDraft] = useState(snapshotFeedback?.comment || '');
    const [commentOpen, setCommentOpen] = useState(false);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        setRating(snapshotFeedback?.rating || null);
        setCommentDraft(snapshotFeedback?.comment || '');
        if (snapshotFeedback?.comment) {
            setCommentOpen(false);
        }
    }, [snapshotFeedback?.rating, snapshotFeedback?.comment, messageId]);

    if (!sessionId || !messageId || !isAssistantResponse) return null;

    const persistFeedback = async (nextRating, nextComment = null) => {
        const previousRating = rating || null;
        const previousComment = commentDraft || '';
        setRating(nextRating);
        if (typeof nextComment === 'string') {
            setCommentDraft(nextComment);
        }
        setBusy(true);
        try {
            await api.post(`/sessions/${sessionId}/messages/${messageId}/feedback`, {
                rating: nextRating,
                reason: null,
                comment: typeof nextComment === 'string' ? nextComment : null,
            });
            if (nextRating === 'like') {
                notify.success('Obrigado pelo feedback');
            } else if (nextRating === 'dislike') {
                notify.success('Feedback registrado');
            } else {
                notify.success('Feedback removido');
            }
            if (typeof nextComment === 'string') {
                setCommentOpen(false);
            }
        } catch (err) {
            setRating(previousRating);
            setCommentDraft(previousComment);
            notify.error(err?.message || 'Failed to save feedback');
        } finally {
            setBusy(false);
        }
    };

    const handleClick = (nextRating) => {
        if (busy) return;
        const normalizedNext = nextRating === 'like' || nextRating === 'dislike' ? nextRating : null;
        const effectiveNext = rating === normalizedNext ? null : normalizedNext;
        persistFeedback(effectiveNext);
    };

    const handleCommentSave = async () => {
        if (busy) return;
        const trimmedComment = commentDraft.trim();
        const nextRating = rating || 'dislike';
        await persistFeedback(nextRating, trimmedComment || null);
    };

    return (
        <div
            className={className}
            style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                marginLeft: '4px',
                opacity: busy ? 0.55 : 0.75,
            }}
        >
            <button
                type="button"
                onClick={() => handleClick('like')}
                disabled={busy}
                title={rating === 'like' ? 'Remove like' : 'Like'}
                aria-pressed={rating === 'like'}
                style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '22px',
                    height: '22px',
                    border: 'none',
                    borderRadius: '999px',
                    background: rating === 'like' ? 'rgba(16,185,129,0.12)' : 'transparent',
                    color: rating === 'like' ? '#10b981' : 'var(--text-muted)',
                    cursor: busy ? 'not-allowed' : 'pointer',
                    transition: 'all 0.15s ease',
                    padding: 0,
                }}
            >
                <ThumbsUp size={12} fill={rating === 'like' ? 'currentColor' : 'none'} />
            </button>
            <button
                type="button"
                onClick={() => handleClick('dislike')}
                disabled={busy}
                title={rating === 'dislike' ? 'Remove dislike' : 'Dislike'}
                aria-pressed={rating === 'dislike'}
                style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '22px',
                    height: '22px',
                    border: 'none',
                    borderRadius: '999px',
                    background: rating === 'dislike' ? 'rgba(239,68,68,0.12)' : 'transparent',
                    color: rating === 'dislike' ? '#ef4444' : 'var(--text-muted)',
                    cursor: busy ? 'not-allowed' : 'pointer',
                    transition: 'all 0.15s ease',
                    padding: 0,
                }}
            >
                <ThumbsDown size={12} fill={rating === 'dislike' ? 'currentColor' : 'none'} />
            </button>
            {rating === 'dislike' && (
                <button
                    type="button"
                    onClick={() => setCommentOpen((prev) => !prev)}
                    disabled={busy}
                    title={commentOpen ? 'Hide comment' : 'Add comment'}
                    style={{
                        border: 'none',
                        background: 'transparent',
                        color: 'var(--text-muted)',
                        fontSize: '10px',
                        letterSpacing: '0.03em',
                        textTransform: 'uppercase',
                        cursor: busy ? 'not-allowed' : 'pointer',
                        padding: '0 4px',
                        opacity: 0.7,
                    }}
                >
                    {commentOpen ? 'Cancelar' : 'Adicionar comentário'}
                </button>
            )}
            {commentOpen && rating === 'dislike' && (
                <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px',
                    width: '100%',
                    marginTop: '6px',
                }}>
                    <textarea
                        value={commentDraft}
                        onChange={(e) => setCommentDraft(e.target.value)}
                        placeholder="Conte o que poderia ter sido melhor..."
                        rows={2}
                        disabled={busy}
                        style={{
                            width: '100%',
                            resize: 'vertical',
                            minHeight: '48px',
                            maxHeight: '120px',
                            borderRadius: '8px',
                            border: '1px solid var(--card-border)',
                            background: 'rgba(255,255,255,0.03)',
                            color: 'var(--text-main)',
                            fontSize: '12px',
                            lineHeight: '1.4',
                            padding: '8px 10px',
                            outline: 'none',
                        }}
                    />
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <button
                            type="button"
                            onClick={handleCommentSave}
                            disabled={busy}
                            style={{
                                border: 'none',
                                borderRadius: '999px',
                                background: 'rgba(59,130,246,0.12)',
                                color: 'var(--accent-color)',
                                fontSize: '10px',
                                fontWeight: 700,
                                letterSpacing: '0.04em',
                                textTransform: 'uppercase',
                                padding: '6px 10px',
                                cursor: busy ? 'not-allowed' : 'pointer',
                            }}
                        >
                            Salvar comentário
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setCommentDraft(snapshotFeedback?.comment || '');
                                setCommentOpen(false);
                            }}
                            disabled={busy}
                            style={{
                                border: 'none',
                                background: 'transparent',
                                color: 'var(--text-muted)',
                                fontSize: '10px',
                                cursor: busy ? 'not-allowed' : 'pointer',
                                padding: '6px 4px',
                            }}
                        >
                            Fechar
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
});

export default MessageFeedback;
