import { normalizeReasoningTimeline } from '../../utils/chatHistoryTransform.js';

const isPlainObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

export const THOUGHT_PHASE_LABELS = {
    thinking: 'Pensando na próxima etapa',
    planning: 'Montando plano',
    capability_search: 'Pesquisando capacidades',
    memory_lookup: 'Consultando memória',
    file_reading: 'Lendo arquivo',
    image_analysis: 'Analisando imagem',
    external_search: 'Realizando busca externa',
    tool_execution: 'Executando ferramenta',
    worker_spawn: 'Spawnando worker',
    worker_running: 'Executando worker',
    result_processing: 'Processando resultado',
    response_drafting: 'Montando resposta final',
    finalizing: 'Finalizando',
    error_recovery: 'Tentando recuperar execução',
};

const THOUGHT_PHASE_HINTS = [
    [/memory|memória|context/i, 'memory_lookup'],
    [/file|arquivo|document|doc/i, 'file_reading'],
    [/image|imagem|vision|screenshot|picture/i, 'image_analysis'],
    [/weather|clima|forecast/i, 'tool_execution'],
    [/search|web|browser|naveg/i, 'external_search'],
    [/tool|ferramenta|execution|executando/i, 'tool_execution'],
    [/worker|runner|job/i, 'worker_running'],
    [/plan|planej|outline/i, 'planning'],
    [/draft|reply|resposta|respond/i, 'response_drafting'],
    [/recover|retry|fallback|recuper/i, 'error_recovery'],
];

const normalizeText = (value) => String(value || '').replace(/\s+/g, ' ').trim();

export const formatDurationMs = (value) => {
    const ms = Number(value);
    if (!Number.isFinite(ms) || ms < 0) return '';
    if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(ms >= 10_000 ? 0 : 1)}s`;
    const totalSeconds = Math.round(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
};

const isLikelyRawNarration = (value) => {
    const text = normalizeText(value).toLowerCase();
    if (!text) return false;
    if (text.length > 120) return true;
    return [
        /^the user\b/,
        /^the assistant\b/,
        /^i (?:will|need|should|can|must)\b/,
        /^we (?:will|need|should|can|must)\b/,
        /^to (?:answer|respond|help|do|explain)\b/,
        /\b(i need to|i will|i should)\b/,
    ].some((regex) => regex.test(text));
};

export const sanitizeThoughtText = (value, fallback = '') => {
    const text = normalizeText(value);
    if (!text) return normalizeText(fallback);
    return text.length > 200 ? `${text.slice(0, 197)}…` : text;
};

const resolveVisibleThoughtSummary = (entry = {}, label = '') => {
    const explicitSummary = normalizeText(
        entry.summary
        || entry.description
        || entry.message
        || entry.caption
        || ''
    );

    if (explicitSummary) {
        if (isLikelyRawNarration(explicitSummary) || (/[.!?]/.test(explicitSummary) && explicitSummary.length > 60)) {
            return normalizeText(label);
        }
        return sanitizeThoughtText(explicitSummary, label);
    }

    return normalizeText(label);
};

export const normalizeThoughtPhase = (entry = {}) => {
    const rawPhase = normalizeText(
        entry.phase
        || entry.state
        || entry.statusPhase
        || entry.kind
        || entry.msg_type
        || entry.type
        || entry.event_type
        || ''
    ).toLowerCase();

    if (rawPhase && THOUGHT_PHASE_LABELS[rawPhase]) return rawPhase;

    if (rawPhase) {
        for (const [regex, phase] of THOUGHT_PHASE_HINTS) {
            if (regex.test(rawPhase)) return phase;
        }
    }

    const summarySource = normalizeText(entry.summary || entry.message || entry.content || entry.text || entry.content_ref || '');
    if (summarySource) {
        for (const [regex, phase] of THOUGHT_PHASE_HINTS) {
            if (regex.test(summarySource)) return phase;
        }
    }

    const capability = normalizeText(entry.capability || entry.capability_name || entry.capability_id || '');
    if (capability) {
        if (/memory/i.test(capability)) return 'memory_lookup';
        if (/file|doc/i.test(capability)) return 'file_reading';
        if (/image|vision|screenshot/i.test(capability)) return 'image_analysis';
        if (/weather|clima/i.test(capability)) return 'tool_execution';
        if (/search|web|browser/i.test(capability)) return 'external_search';
        if (/worker/i.test(capability)) return 'worker_running';
        return 'tool_execution';
    }

    return rawPhase || 'thinking';
};

export const getThoughtDisplayLabel = (entry = {}) => {
    const phase = normalizeThoughtPhase(entry);
    const explicitLabel = normalizeText(entry.label || entry.displayLabel || entry.title || entry.phase_label || '');
    if (explicitLabel) return explicitLabel;

    const capability = normalizeText(entry.capability || entry.capability_name || entry.capability_id || '');
    if (capability) {
        if (/weather|clima/i.test(capability)) return 'Consultando clima';
        if (/memory/i.test(capability)) return 'Consultando memória';
        if (/file|doc|document/i.test(capability)) return 'Lendo arquivo';
        if (/image|vision|screenshot/i.test(capability)) return 'Analisando imagem';
        if (/search|web|browser/i.test(capability)) return 'Realizando busca externa';
        if (/worker/i.test(capability)) return 'Executando worker';
        return 'Executando ferramenta';
    }

    return THOUGHT_PHASE_LABELS[phase] || 'Pensando na próxima etapa';
};

export const normalizeThoughtTimelineItem = (entry, fallback = {}) => {
    if (!entry) return null;

    if (typeof entry === 'string') {
        const text = entry.trim();
        if (!text) return null;
        const phase = normalizeThoughtPhase({ ...fallback, content: text });
        const label = getThoughtDisplayLabel({ ...fallback, phase, summary: text, content: text });
        const summary = resolveVisibleThoughtSummary(fallback, label);
        return {
            id: fallback.id || `${fallback.key || 'thought'}-${text.slice(0, 24)}`,
            text,
            rawText: text,
            label,
            summary,
            phase,
            ts: fallback.ts || null,
            turnId: fallback.turnId ?? null,
            streamId: fallback.streamId ?? null,
            workId: fallback.workId ?? null,
            messageId: fallback.messageId ?? null,
            source: fallback.source || 'reasoning',
            capability: fallback.capability ?? null,
            visibility: fallback.visibility ?? null,
            kind: fallback.kind ?? null,
            thinkingStartedAt: fallback.thinkingStartedAt ?? null,
            thinkingUpdatedAt: fallback.thinkingUpdatedAt ?? null,
            thinkingCompletedAt: fallback.thinkingCompletedAt ?? null,
            thinkingDurationMs: fallback.thinkingDurationMs ?? null,
            turnDurationMs: fallback.turnDurationMs ?? null,
            streamDurationMs: fallback.streamDurationMs ?? null,
            isActive: fallback.isActive ?? null,
            isCompact: text.length > 120,
            raw: fallback.raw || null,
        };
    }

    if (!isPlainObject(entry)) return null;

    const rawText = String(
        entry.text
        || entry.content
        || entry.summary
        || entry.thought
        || entry.message
        || entry.content_ref
        || ''
    ).trim();
    const phase = normalizeThoughtPhase(entry);
    const label = getThoughtDisplayLabel({ ...entry, phase, summary: entry.summary || entry.content || entry.text });
    const summary = resolveVisibleThoughtSummary(entry, label);
    if (!summary && !rawText) return null;

    const turnId = entry.turn_id ?? entry.turnId ?? fallback.turnId ?? null;
    const streamId = entry.stream_id ?? entry.streamId ?? fallback.streamId ?? null;
    const workId = entry.work_id ?? entry.workId ?? fallback.workId ?? null;
    const messageId = entry.message_id ?? entry.messageId ?? fallback.messageId ?? null;
    const ts = entry.ts ?? entry.timestamp ?? entry.created_at ?? entry.updated_at ?? fallback.ts ?? null;
    const source = entry.source || entry.kind || fallback.source || 'reasoning';
    const capability = entry.capability ?? entry.capability_name ?? entry.capability_id ?? fallback.capability ?? null;
    const visibility = entry.visibility ?? fallback.visibility ?? null;
    const kind = entry.kind || entry.msg_type || entry.type || entry.event_type || fallback.kind || null;

    return {
        id: entry.thought_id || entry.event_id || entry.id || fallback.id || `${turnId || streamId || workId || messageId || 'thought'}-${summary.slice(0, 24)}`,
        text: summary || label,
        rawText,
        label,
        summary: summary || label,
        phase,
        ts,
        turnId,
        streamId,
        workId,
        messageId,
        source,
        capability,
        visibility,
        kind,
        thinkingStartedAt: entry.thinking_started_at ?? entry.thinkingStartedAt ?? fallback.thinkingStartedAt ?? null,
        thinkingUpdatedAt: entry.thinking_updated_at ?? entry.thinkingUpdatedAt ?? fallback.thinkingUpdatedAt ?? null,
        thinkingCompletedAt: entry.thinking_completed_at ?? entry.thinkingCompletedAt ?? fallback.thinkingCompletedAt ?? null,
        thinkingDurationMs: entry.thinking_duration_ms ?? entry.thinkingDurationMs ?? fallback.thinkingDurationMs ?? null,
        turnDurationMs: entry.turn_duration_ms ?? entry.turnDurationMs ?? fallback.turnDurationMs ?? null,
        streamDurationMs: entry.stream_duration_ms ?? entry.streamDurationMs ?? fallback.streamDurationMs ?? null,
        isActive: entry.is_active ?? entry.isActive ?? fallback.isActive ?? null,
        isCompact: normalizeText(rawText).length > 120 || /worker|tool|action|result/i.test(phase),
        raw: isPlainObject(entry.raw) ? entry.raw : null,
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
        const normalized = normalizeThoughtTimelineItem(item, {
            key: `snapshot-${idx}`,
            source: 'snapshot',
            turnId: item?.turn_id ?? item?.turnId ?? null,
            streamId: item?.stream_id ?? item?.streamId ?? null,
            workId: item?.work_id ?? item?.workId ?? null,
            messageId: item?.message_id ?? item?.messageId ?? null,
            ts: item?.timestamp ?? item?.created_at ?? item?.updated_at ?? null,
            summary: item?.summary || item?.content || item?.message || item?.thought || '',
            capability: item?.capability || item?.capability_name || item?.capability_id || null,
            kind: item?.kind || item?.msg_type || item?.type || item?.event_type || null,
            visibility: item?.visibility || null,
        });
        if (normalized) collected.push(normalized);
    });

    const liveReasoningSource = Array.isArray(streamingMessage?.reasoningTimeline) && streamingMessage.reasoningTimeline.length > 0
        ? streamingMessage.reasoningTimeline
        : normalizeReasoningTimeline(streamingMessage);

    const liveReasoning = liveReasoningSource.map((entry, idx) => normalizeThoughtTimelineItem(entry, {
        key: `live-${idx}`,
        source: 'live',
        turnId: streamingMessage?.turn_id ?? streamingMessage?.turnId ?? null,
        streamId: streamingMessage?.stream_id ?? streamingMessage?.streamId ?? null,
        workId: streamingMessage?.work_id ?? streamingMessage?.workId ?? null,
        messageId: streamingMessage?.id ?? streamingMessage?.message_id ?? null,
        ts: streamingMessage?.timestamp ?? null,
        phase: entry?.phase || streamingMessage?.statusPhase || streamingMessage?.phase || 'thinking',
        summary: entry?.summary || entry?.message || entry?.content || '',
        capability: entry?.capability || streamingMessage?.capability || null,
        kind: entry?.kind || streamingMessage?.kind || 'reasoning',
        visibility: entry?.visibility || streamingMessage?.visibility || null,
        raw: entry?.raw || null,
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
                phase: block.entries[0]?.phase || null,
                thinkingStartedAt: block.entries[0]?.thinkingStartedAt || null,
                thinkingUpdatedAt: block.entries[block.entries.length - 1]?.thinkingUpdatedAt || null,
                thinkingCompletedAt: block.entries[block.entries.length - 1]?.thinkingCompletedAt || null,
                thinkingDurationMs: block.entries[block.entries.length - 1]?.thinkingDurationMs || null,
                turnDurationMs: block.entries[block.entries.length - 1]?.turnDurationMs || null,
                streamDurationMs: block.entries[block.entries.length - 1]?.streamDurationMs || null,
                isActive: block.entries.some((entry) => entry.isActive),
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
