import { normalizeReasoningTimeline } from '../../utils/chatHistoryTransform';

const isPlainObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

export const normalizeThoughtEntry = (entry, fallback = {}) => {
    if (!entry) return null;

    if (typeof entry === 'string') {
        const text = entry.trim();
        if (!text) return null;
        return {
            id: fallback.id || `${fallback.key || 'thought'}-${text.slice(0, 24)}`,
            text,
            ts: fallback.ts || null,
            turnId: fallback.turnId ?? null,
            streamId: fallback.streamId ?? null,
            workId: fallback.workId ?? null,
            messageId: fallback.messageId ?? null,
            source: fallback.source || 'reasoning',
        };
    }

    if (!isPlainObject(entry)) return null;

    const text = String(
        entry.text
        || entry.content
        || entry.summary
        || entry.thought
        || entry.message
        || entry.content_ref
        || ''
    ).trim();
    if (!text) return null;

    const turnId = entry.turn_id ?? entry.turnId ?? fallback.turnId ?? null;
    const streamId = entry.stream_id ?? entry.streamId ?? fallback.streamId ?? null;
    const workId = entry.work_id ?? entry.workId ?? fallback.workId ?? null;
    const messageId = entry.message_id ?? entry.messageId ?? fallback.messageId ?? null;
    const ts = entry.ts ?? entry.timestamp ?? entry.created_at ?? entry.updated_at ?? fallback.ts ?? null;
    const source = entry.source || entry.kind || fallback.source || 'reasoning';

    return {
        id: entry.thought_id || entry.event_id || entry.id || fallback.id || `${turnId || streamId || workId || messageId || 'thought'}-${text.slice(0, 24)}`,
        text,
        ts,
        turnId,
        streamId,
        workId,
        messageId,
        source,
    };
};

const thoughtBlockKey = (entry) => {
    if (!entry) return 'thought:global';
    if (entry.turnId !== null && entry.turnId !== undefined && entry.turnId !== '') return `turn:${entry.turnId}`;
    if (entry.streamId) return `stream:${entry.streamId}`;
    if (entry.workId) return `work:${entry.workId}`;
    if (entry.messageId) return `message:${entry.messageId}`;
    return 'thought:global';
};

const summarizeBlock = (block) => {
    if (!block) return 'Thoughts';
    if (block.turnId !== null && block.turnId !== undefined && block.turnId !== '') return `Turn ${block.turnId}`;
    if (block.workId) return `Work ${String(block.workId).slice(0, 8)}`;
    if (block.streamId) return `Stream ${String(block.streamId).slice(0, 8)}`;
    return 'Thoughts';
};

export const buildThoughtTimelineBlocks = ({ sessionIndices, streamingMessage } = {}) => {
    const collected = [];

    const thoughtIndexItems = sessionIndices?.thoughts?.items;
    const thoughtItems = Array.isArray(thoughtIndexItems)
        ? thoughtIndexItems
        : Object.values(isPlainObject(thoughtIndexItems) ? thoughtIndexItems : {});

    thoughtItems.forEach((item, idx) => {
        const normalized = normalizeThoughtEntry(item, {
            key: `snapshot-${idx}`,
            source: 'snapshot',
            turnId: item?.turn_id ?? item?.turnId ?? null,
            streamId: item?.stream_id ?? item?.streamId ?? null,
            workId: item?.work_id ?? item?.workId ?? null,
            messageId: item?.message_id ?? item?.messageId ?? null,
            ts: item?.timestamp ?? item?.created_at ?? item?.updated_at ?? null,
        });
        if (normalized) collected.push(normalized);
    });

    const liveReasoning = normalizeReasoningTimeline(streamingMessage).map((entry, idx) => normalizeThoughtEntry(entry, {
        key: `live-${idx}`,
        source: 'live',
        turnId: streamingMessage?.turn_id ?? streamingMessage?.turnId ?? null,
        streamId: streamingMessage?.stream_id ?? streamingMessage?.streamId ?? null,
        workId: streamingMessage?.work_id ?? streamingMessage?.workId ?? null,
        messageId: streamingMessage?.id ?? streamingMessage?.message_id ?? null,
        ts: streamingMessage?.timestamp ?? null,
    })).filter(Boolean);

    collected.push(...liveReasoning);

    const grouped = new Map();
    collected.forEach((entry, idx) => {
        const key = thoughtBlockKey(entry);
        if (!grouped.has(key)) {
            grouped.set(key, {
                key,
                turnId: entry.turnId ?? null,
                streamId: entry.streamId ?? null,
                workId: entry.workId ?? null,
                messageId: entry.messageId ?? null,
                title: summarizeBlock(entry),
                entries: [],
                isLive: false,
                order: idx,
            });
        }

        const block = grouped.get(key);
        const dedupeKey = `${entry.id || ''}:${entry.text}:${entry.ts || ''}`;
        if (!block._seen) block._seen = new Set();
        if (block._seen.has(dedupeKey)) return;
        block._seen.add(dedupeKey);
        block.entries.push(entry);
        if (entry.source === 'live') block.isLive = true;
    });

    return Array.from(grouped.values())
        .map((block) => {
            const entries = block.entries.slice().sort((a, b) => {
                const ta = a.ts ? new Date(a.ts).getTime() : 0;
                const tb = b.ts ? new Date(b.ts).getTime() : 0;
                return ta - tb;
            });
            return {
                key: block.key,
                turnId: block.turnId,
                streamId: block.streamId,
                workId: block.workId,
                messageId: block.messageId,
                title: block.title,
                entries,
                isLive: block.isLive,
                order: block.order,
            };
        })
        .sort((a, b) => {
            const ta = a.entries[0]?.ts ? new Date(a.entries[0].ts).getTime() : 0;
            const tb = b.entries[0]?.ts ? new Date(b.entries[0].ts).getTime() : 0;
            if (ta !== tb) return ta - tb;
            return a.order - b.order;
        });
};

