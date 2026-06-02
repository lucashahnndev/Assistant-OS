import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildThoughtTimelineBlocks,
    formatDurationMs,
    normalizeThoughtTimelineItem,
} from '../src/components/chat/ThoughtTimeline.utils.js';

test('raw reasoning text is sanitized into a label and summary', () => {
    const entry = normalizeThoughtTimelineItem({
        phase: 'response_drafting',
        content: 'The user greeted me. I will respond politely and keep it short.',
    }, {
        source: 'history',
        turnId: 'turn-1',
    });

    assert.equal(entry.phase, 'response_drafting');
    assert.equal(entry.label, 'Montando resposta final');
    assert.equal(entry.summary, 'Montando resposta final');
    assert.equal(entry.rawText, 'The user greeted me. I will respond politely and keep it short.');
});

test('structured thought entries keep capability and metadata visible', () => {
    const entry = normalizeThoughtTimelineItem({
        phase: 'tool_execution',
        capability: 'weather.control.get',
        source: 'mcp',
        summary: 'Fetching current weather data...',
        turn_id: 'turn-2',
        stream_id: 'stream-2',
        work_id: 'work-2',
        thinking_duration_ms: 1420,
    });

    assert.equal(entry.label, 'Consultando clima');
    assert.equal(entry.summary, 'Fetching current weather data...');
    assert.equal(entry.capability, 'weather.control.get');
    assert.equal(entry.turnId, 'turn-2');
    assert.equal(entry.streamId, 'stream-2');
    assert.equal(entry.workId, 'work-2');
    assert.equal(entry.thinkingDurationMs, 1420);
});

test('thought blocks group snapshot and live entries by turn/stream/work', () => {
    const blocks = buildThoughtTimelineBlocks({
        sessionIndices: {
            thoughts: {
                items: [
                    {
                        phase: 'memory_lookup',
                        summary: 'Checking memory for prior context',
                        turn_id: 'turn-a',
                        work_id: 'work-a',
                    },
                ],
            },
        },
        streamingMessage: {
            turn_id: 'turn-a',
            stream_id: 'stream-a',
            reasoningTimeline: [
                {
                    phase: 'thinking',
                    summary: 'Thinking about the final response',
                    ts: '2026-06-02T10:00:00Z',
                },
            ],
        },
    });

    assert.equal(blocks.length, 1);
    assert.equal(blocks[0].turnId, 'turn-a');
    assert.equal(blocks[0].streamId, null);
    assert.equal(blocks[0].entries.length, 2);
    assert.equal(blocks[0].entries[0].label, 'Consultando memória');
    assert.equal(blocks[0].entries[1].label, 'Pensando na próxima etapa');
});

test('duration formatter keeps stable compact labels', () => {
    assert.equal(formatDurationMs(120), '120ms');
    assert.equal(formatDurationMs(1420), '1.4s');
    assert.equal(formatDurationMs(15000), '15s');
    assert.equal(formatDurationMs(125000), '2m 05s');
});

test('thought blocks surface backend duration metadata', () => {
    const blocks = buildThoughtTimelineBlocks({
        sessionIndices: {
            thoughts: {
                items: [
                    {
                        phase: 'response_drafting',
                        summary: 'Drafting the reply',
                        turn_id: 'turn-duration',
                        thinking_duration_ms: 1420,
                        turn_duration_ms: 1800,
                        stream_duration_ms: 500,
                        is_active: false,
                    },
                ],
            },
        },
    });

    assert.equal(blocks.length, 1);
    assert.equal(blocks[0].thinkingDurationMs, 1420);
    assert.equal(blocks[0].turnDurationMs, 1800);
    assert.equal(blocks[0].streamDurationMs, 500);
    assert.equal(blocks[0].isActive, false);
    assert.equal(formatDurationMs(blocks[0].thinkingDurationMs), '1.4s');
});
