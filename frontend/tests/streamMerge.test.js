import test from 'node:test';
import assert from 'node:assert/strict';

import { mergeStreamContent } from '../src/utils/streamMerge.js';

test('technical fallback text is replaced by later valid assistant content', () => {
    const merged = mergeStreamContent(
        'Tentei responder, mas ocorreu uma falha técnica antes da mensagem final. Motivo registrado: LLMManager generate_text returned empty output.',
        'Para te informar a temperatura, preciso saber qual é a sua cidade. Poderia me dizer?'
    );

    assert.equal(merged, 'Para te informar a temperatura, preciso saber qual é a sua cidade. Poderia me dizer?');
});

test('valid assistant content is preserved when fallback arrives later in the same stream', () => {
    const merged = mergeStreamContent(
        'Para te informar a temperatura, preciso saber qual é a sua cidade. Poderia me dizer?',
        'Tentei responder, mas ocorreu uma falha técnica antes da mensagem final. Motivo registrado: LLMManager generate_text returned empty output.'
    );

    assert.equal(merged, 'Para te informar a temperatura, preciso saber qual é a sua cidade. Poderia me dizer?');
});

test('ordinary stream chunks still concatenate normally', () => {
    const merged = mergeStreamContent('Olá, ', 'tudo bem?');

    assert.equal(merged, 'Olá, tudo bem?');
});
