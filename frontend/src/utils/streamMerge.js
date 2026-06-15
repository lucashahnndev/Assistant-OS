const TECHNICAL_FALLBACK_PATTERNS = [
    /tentei responder, mas ocorreu uma falha técnica/i,
    /i tried to respond, but a technical failure/i,
    /llmmanager generate_text returned empty output/i,
    /motivo registrado:\s*llmmanager generate_text returned empty output/i,
    /recorded reason:\s*llmmanager generate_text returned empty output/i,
];

const normalizeText = (value) => String(value || '').replace(/\s+/g, ' ').trim();

export const isTechnicalFallbackText = (value) => {
    const text = normalizeText(value);
    if (!text) return false;
    return TECHNICAL_FALLBACK_PATTERNS.some((pattern) => pattern.test(text));
};

export const mergeStreamContent = (previous = '', incoming = '') => {
    const prev = String(previous || '');
    const next = String(incoming || '');
    if (!next) return prev;
    if (!prev) return next;
    if (next === prev) return prev;
    if (next.startsWith(prev)) return next;
    if (prev.startsWith(next)) return prev;
    if (prev.includes(next)) return prev;
    if (next.includes(prev)) return next;

    const prevIsFallback = isTechnicalFallbackText(prev);
    const nextIsFallback = isTechnicalFallbackText(next);
    if (prevIsFallback && !nextIsFallback) return next;
    if (nextIsFallback && !prevIsFallback) return prev;

    return `${prev}${next}`;
};
