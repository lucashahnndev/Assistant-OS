import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeSessionEvent } from '../src/utils/normalizeSessionEvent.js';

test('status does not create a message bubble', () => {
    const event = normalizeSessionEvent({
        type: 'status',
        event_id: 'evt-1',
        session_id: 'sess-1',
        message: 'Processing...',
        phase: 'thinking',
    });

    assert.equal(event.type, 'status');
    assert.equal(event.eventType, 'status');
    assert.equal(event.category, 'status');
    assert.equal(event.canCreateMessage, false);
    assert.equal(event.canUpdateMessage, false);
    assert.equal(event.isTechnical, true);
});

test('session_updated does not create a message bubble', () => {
    const event = normalizeSessionEvent({
        type: 'session_updated',
        event_id: 'evt-2',
        session_id: 'sess-1',
        data: { session_id: 'sess-1', updated_at: '2026-05-31T00:00:00Z' },
    });

    assert.equal(event.category, 'session');
    assert.equal(event.canCreateMessage, false);
    assert.equal(event.canUpdateMessage, false);
    assert.equal(event.payload.updatedAt, '2026-05-31T00:00:00Z');
});

test('assistant_chunk with stream_id updates a stream', () => {
    const event = normalizeSessionEvent({
        type: 'assistant_chunk',
        event_id: 'evt-3',
        session_id: 'sess-1',
        stream_id: 'stream-1',
        sequence: 3,
        payload: {
            content: 'hello',
            stream_id: 'stream-1',
            reply_to_message_id: 'user-1',
        },
    });

    assert.equal(event.category, 'stream');
    assert.equal(event.streamId, 'stream-1');
    assert.equal(event.sequence, 3);
    assert.equal(event.canUpdateMessage, true);
    assert.equal(event.canCreateMessage, false);
    assert.equal(event.payload.replyToMessageId, 'user-1');
});

test('assistant_chunk without stream_id does not create or update a message', () => {
    const event = normalizeSessionEvent({
        type: 'assistant_chunk',
        event_id: 'evt-4',
        session_id: 'sess-1',
        payload: { content: 'late chunk without correlation' },
    });

    assert.equal(event.category, 'stream');
    assert.equal(event.streamId, null);
    assert.equal(event.canCreateMessage, false);
    assert.equal(event.canUpdateMessage, false);
});

test('final_message_chunk with stream_id updates the stream', () => {
    const event = normalizeSessionEvent({
        type: 'final_message_chunk',
        event_id: 'evt-5',
        session_id: 'sess-1',
        stream_id: 'stream-2',
        payload: {
            message_id: 'msg-2',
            content: 'final',
        },
    });

    assert.equal(event.category, 'stream');
    assert.equal(event.streamId, 'stream-2');
    assert.equal(event.messageId, 'msg-2');
    assert.equal(event.canUpdateMessage, true);
});

test('complete with stream target can finalize a stream', () => {
    const event = normalizeSessionEvent({
        type: 'complete',
        event_id: 'evt-6',
        session_id: 'sess-1',
        target: 'stream',
        stream_id: 'stream-3',
        sequence: 9,
    });

    assert.equal(event.category, 'completion');
    assert.equal(event.target, 'stream');
    assert.equal(event.canCompleteTarget, true);
    assert.equal(event.streamId, 'stream-3');
    assert.equal(event.sequence, 9);
});

test('complete with legacy target does not finalize a reliable visual target', () => {
    const event = normalizeSessionEvent({
        type: 'complete',
        event_id: 'evt-7',
        session_id: 'sess-1',
        target: 'legacy',
    });

    assert.equal(event.category, 'legacy');
    assert.equal(event.isLegacy, true);
    assert.equal(event.canCompleteTarget, false);
    assert.equal(event.isVisual, false);
});

test('worker_state does not create a message bubble', () => {
    const event = normalizeSessionEvent({
        type: 'worker_state',
        event_id: 'evt-8',
        session_id: 'sess-1',
        data: { state: 'busy' },
    });

    assert.equal(event.category, 'worker');
    assert.equal(event.canCreateMessage, false);
    assert.equal(event.canUpdateMessage, false);
});

test('visual Wegena reset does not create a message bubble', () => {
    const event = normalizeSessionEvent({
        type: 'visual.wegena.scene_reset',
        event_id: 'evt-9',
        session_id: 'sess-1',
        payload: { reason: 'scene reset' },
    });

    assert.equal(event.category, 'visual');
    assert.equal(event.isVisual, true);
    assert.equal(event.canCreateMessage, false);
});

test('message_added can create or reconcile a message', () => {
    const event = normalizeSessionEvent({
        type: 'message_added',
        event_id: 'evt-10',
        session_id: 'sess-1',
        message: {
            id: 'msg-10',
            reply_to_message_id: 'user-10',
            content: 'assistant reply',
            nested_value: {
                some_value: 42,
            },
        },
    });

    assert.equal(event.category, 'message');
    assert.equal(event.messageId, 'msg-10');
    assert.equal(event.replyToMessageId, 'user-10');
    assert.equal(event.canCreateMessage, true);
    assert.equal(event.canUpdateMessage, true);
    assert.equal(event.payload.nestedValue.someValue, 42);
});

test('snake_case fields are normalized to camelCase', () => {
    const event = normalizeSessionEvent({
        type: 'message.persisted',
        event_id: 'evt-11',
        session_id: 'sess-1',
        message_id: 'msg-11',
        reply_to_message_id: 'user-11',
        stream_id: 'stream-11',
        payload: {
            reply_to_message_id: 'user-11',
            nested_object: {
                created_at: '2026-05-31T00:00:00Z',
            },
        },
    });

    assert.equal(event.eventType, 'message.persisted');
    assert.equal(event.eventId, 'evt-11');
    assert.equal(event.sessionId, 'sess-1');
    assert.equal(event.messageId, 'msg-11');
    assert.equal(event.replyToMessageId, 'user-11');
    assert.equal(event.streamId, 'stream-11');
    assert.equal(event.payload.replyToMessageId, 'user-11');
    assert.equal(event.payload.nestedObject.createdAt, '2026-05-31T00:00:00Z');
});
