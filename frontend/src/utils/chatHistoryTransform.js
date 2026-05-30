export const getFileUrl = (item, sessionId) => {
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

export const formatTime = (ts) => {
    if (!ts) return '';
    try {
        const date = new Date(typeof ts === 'number' && ts < 10000000000 ? ts * 1000 : ts);
        return isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
        return '';
    }
};

export const formatDate = (ts) => {
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

export const tryParseIntentPayload = (content) => {
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

export const normalizeHistoryMessageType = (msg) => {
    return String(msg?.type || msg?.msg_type || 'default').toLowerCase();
};

export const extractReasoningLine = (msg) => {
    const payload = tryParseIntentPayload(msg?.content);
    if (payload) {
        const thought = typeof payload.thought === 'string' ? payload.thought.trim() : '';
        if (thought) return thought;
        const action = typeof payload.action === 'string' ? payload.action.trim() : '';
        if (action && action !== 'reply' && action !== 'none') return `Planned action: ${action}`;
        if (action === 'reply' && payload.thought) return payload.thought;
    }
    
    // Fallback if backend sent pure text with msg_type=reasoning
    if (normalizeHistoryMessageType(msg) === 'reasoning') {
        return String(msg?.content || '').trim();
    }
    return null;
};

export const toReasoningEntry = (line, ts = null) => {
    const text = String(line || '').trim();
    if (!text) return null;
    return { text, ts: ts || null };
};

export const normalizeReasoningTimeline = (msg) => {
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

export const groupHistoryWithReasoning = (rawHistory = []) => {
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
                unit.capabilities_used = mergeUniqueStrings(unit.capabilities_used, msg.capabilities_used);
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
