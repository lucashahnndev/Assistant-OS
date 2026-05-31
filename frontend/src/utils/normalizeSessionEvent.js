const LEGACY_EVENT_TYPES = new Set([
    'msg',
    'assistant_response',
]);

const MESSAGE_CREATING_EVENTS = new Set([
    'user_message.created',
    'message_added',
    'message.persisted',
    'assistant_stream.started',
    'assistant_message.created',
]);

const MESSAGE_UPDATING_EVENTS = new Set([
    'assistant_chunk',
    'final_message_chunk',
    'message_added',
    'message.persisted',
]);

const isPlainObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const toCamelCaseKey = (key) => String(key).replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());

const normalizeValue = (value) => {
    if (Array.isArray(value)) {
        return value.map((item) => normalizeValue(item));
    }
    if (!isPlainObject(value)) return value;
    return Object.fromEntries(
        Object.entries(value).map(([key, entryValue]) => [toCamelCaseKey(key), normalizeValue(entryValue)])
    );
};

const pickFirst = (...values) => values.find((value) => value !== undefined && value !== null && value !== '');

const getNormalizedEventType = (rawEvent) => {
    const candidate = pickFirst(rawEvent?.event_type, rawEvent?.type, rawEvent?.eventType);
    return String(candidate || 'unknown').trim() || 'unknown';
};

const getTopLevelField = (rawEvent, payload, keys = []) => {
    for (const key of keys) {
        const value = pickFirst(rawEvent?.[key], payload?.[toCamelCaseKey(key)]);
        if (value !== undefined && value !== null && value !== '') return value;
    }
    return null;
};

const getCategory = (eventType, target, rawEvent) => {
    if (!eventType || eventType === 'unknown') return 'unknown';
    if (target === 'legacy' || LEGACY_EVENT_TYPES.has(eventType)) return 'legacy';
    if (eventType.startsWith('visual.') || eventType === 'weg_scene_reset') return 'visual';
    if (eventType.startsWith('card.')) return 'card';
    if (eventType.startsWith('artifact.')) return 'artifact';
    if (eventType.startsWith('media.')) return 'media';
    if (eventType === 'complete') return 'completion';
    if (eventType === 'assistant_chunk' || eventType === 'final_message_chunk' || eventType === 'assistant_stream.started' || eventType === 'stream') return 'stream';
    if (eventType === 'user_message.created' || eventType === 'message_added' || eventType === 'message.persisted' || eventType === 'assistant_message.created') return 'message';
    if (eventType === 'status' || eventType === 'system_metrics' || eventType === 'system_health') return 'status';
    if (eventType === 'session_updated') return 'session';
    if (eventType === 'worker_state' || eventType === 'worker.updated') return 'worker';
    if (eventType === 'thought' || eventType === 'cognitive_thought' || eventType === 'assistant_thought' || eventType === 'reasoning_chunk') return 'reasoning';
    if (rawEvent?.category && typeof rawEvent.category === 'string') return String(rawEvent.category);
    return 'unknown';
};

const hasCorrelation = (eventType, messageId, streamId) => {
    if (eventType === 'assistant_chunk') return Boolean(streamId);
    if (eventType === 'final_message_chunk') return Boolean(streamId || messageId);
    if (eventType === 'assistant_stream.started') return Boolean(streamId || messageId);
    if (MESSAGE_CREATING_EVENTS.has(eventType)) return Boolean(messageId || streamId);
    return Boolean(messageId || streamId);
};

export const normalizeSessionEvent = (rawEvent = {}) => {
    const raw = isPlainObject(rawEvent) ? rawEvent : {};
    const eventType = getNormalizedEventType(raw);
    const payloadSource = pickFirst(raw.payload, raw.data, raw.message, raw.event, null);
    const payload = normalizeValue(payloadSource);
    const target = getTopLevelField(raw, payload, ['target']);

    const sessionId = getTopLevelField(raw, payload, ['session_id', 'sessionId']);
    const turnId = getTopLevelField(raw, payload, ['turn_id', 'turnId']);
    const messageId = getTopLevelField(raw, payload, ['message_id', 'messageId', 'id']);
    const replyToMessageId = getTopLevelField(raw, payload, ['reply_to_message_id', 'replyToMessageId']);
    const streamId = getTopLevelField(raw, payload, ['stream_id', 'streamId']);
    const workId = getTopLevelField(raw, payload, ['work_id', 'workId']);
    const sequence = getTopLevelField(raw, payload, ['sequence']);
    const channel = getTopLevelField(raw, payload, ['channel']);
    const interfaceName = getTopLevelField(raw, payload, ['interface']);
    const source = getTopLevelField(raw, payload, ['source']);
    const eventId = getTopLevelField(raw, payload, ['event_id', 'eventId', 'id']);
    const timestamp = getTopLevelField(raw, payload, ['timestamp', 'ts', 'created_at', 'createdAt']);

    const category = getCategory(eventType, target, raw);
    const isLegacy = target === 'legacy' || LEGACY_EVENT_TYPES.has(eventType);
    const isVisual = category === 'visual' || category === 'card' || category === 'artifact' || category === 'media';
    const isTechnical = ['status', 'worker', 'session', 'reasoning', 'legacy', 'unknown'].includes(category);
    const canCreateMessage = MESSAGE_CREATING_EVENTS.has(eventType) && hasCorrelation(eventType, messageId, streamId);
    const canUpdateMessage = MESSAGE_UPDATING_EVENTS.has(eventType) && hasCorrelation(eventType, messageId, streamId);
    const canCompleteTarget = eventType === 'complete' && Boolean(target) && target !== 'legacy';

    return {
        type: raw.type ?? eventType,
        eventType,
        eventId: eventId ?? null,
        sessionId: sessionId ?? null,
        turnId: turnId ?? null,
        messageId: messageId ?? null,
        replyToMessageId: replyToMessageId ?? null,
        streamId: streamId ?? null,
        workId: workId ?? null,
        target: target ?? null,
        sequence: sequence ?? null,
        timestamp: timestamp ?? null,
        channel: channel ?? null,
        interface: interfaceName ?? null,
        source: source ?? null,
        category,
        canCreateMessage,
        canUpdateMessage,
        canCompleteTarget,
        isTechnical,
        isVisual,
        isLegacy,
        payload: payload ?? null,
        raw,
    };
};

export default normalizeSessionEvent;
