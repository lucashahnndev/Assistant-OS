import test from 'node:test';
import assert from 'node:assert/strict';

import {
    buildThoughtTimelineBlocks,
    buildThoughtTimelineRenderRows,
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
    assert.equal(entry.summary, 'The user greeted me. I will respond politely and keep it short.');
    assert.equal(entry.displaySummary, 'The user greeted me. I will respond politely and keep it short.');
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
    assert.equal(blocks[0].entries[0].displaySummary, 'Checking memory for prior context');
    assert.equal(blocks[0].entries[1].label, 'Pensando na próxima etapa');
    assert.equal(blocks[0].entries[1].displaySummary, 'Thinking about the final response');
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

test('thought render rows expose title and sanitized summary separately', () => {
    const rows = buildThoughtTimelineRenderRows({
        entries: [
            normalizeThoughtTimelineItem({
                phase: 'response_drafting',
                content: 'The user has initiated contact with a greeting. I will acknowledge the greeting and confirm my readiness to assist as A.T.L.A.S.',
            }, {
                source: 'history',
                turnId: 'turn-render',
            }),
        ],
    });

    assert.equal(rows.length, 1);
    assert.equal(rows[0].displayTitle, 'Montando resposta final');
    assert.equal(rows[0].displaySummary, 'The user has initiated contact with a greeting. I will acknowledge the greeting and confirm my readiness to assist as A.T.L.A.S.');
    assert.equal(rows[0].isLatest, true);
});

test('summary-like labels do not suppress richer thought content', () => {
    const entry = normalizeThoughtTimelineItem({
        phase: 'memory_lookup',
        summary: 'Consultando memória',
        content: 'I need to recover a prior context detail before answering the user.',
    }, {
        source: 'history',
        turnId: 'turn-memory',
    });

    assert.equal(entry.displayTitle, 'Consultando memória');
    assert.equal(entry.displaySummary, 'I need to recover a prior context detail before answering the user.');
});

test('memory/context language beats greeting fallback for richer thoughts', () => {
    const entry = normalizeThoughtTimelineItem({
        phase: 'memory_lookup',
        summary: 'Consultando memória',
        content: "The user is repeating 'oi 2', which likely refers to a specific task or context labeled 'oi 2' in the system instructions. I will acknowledge the request and confirm readiness to proceed with the objective associated with 'oi 2'.",
    }, {
        source: 'history',
        turnId: 'turn-oi-2',
    });

    assert.equal(entry.displayTitle, 'Consultando memória');
    assert.equal(entry.displaySummary, "The user is repeating 'oi 2', which likely refers to a specific task or context labeled 'oi 2' in the system instructions. I will acknowledge the request and confirm readiness to proceed with the o…");
});
