import { useEffect, useMemo, useState } from 'react';
import { api } from './api';
import {
    WEATHER_CARD_CACHE,
    WEATHER_CARD_PENDING,
    WEATHER_CACHE_TTL_MS,
    SYSTEM_HEALTH_CARD_CACHE,
    SYSTEM_HEALTH_CARD_PENDING,
    SYSTEM_HEALTH_CACHE_TTL_MS,
    hasWeatherCue,
    hasSystemHealthCue,
    hasWikipediaCue,
    tryParseMarkdownTable,
} from '../components/AssistCards';

const WORK_CAPABILITY_SIGNALS_CACHE = new Map();
const WORK_CAPABILITY_SIGNALS_PENDING = new Map();
const WORK_CAPABILITY_CACHE_TTL_IDLE_MS = 15000;
const WORK_CAPABILITY_CACHE_TTL_STREAM_MS = 2200;

const WEATHER_CAPABILITY_PATTERNS = [
    /\bweather\b/i,
    /\bweather[\._-]?control\b/i,
    /\bforecast\b/i,
    /\bmeteo\b/i,
];

const SYSTEM_HEALTH_CAPABILITY_PATTERNS = [
    /\bsystem[\._-]?health\b/i,
    /\bhost[\._-]?health\b/i,
    /\bmachine[\._-]?status\b/i,
    /\bsystem\.control\.(status|execute|run|command)\b/i,
    /\bshell[\._-]?control\b/i,
    /\bshell[\._-]?control[\._-]?(execute|run|command)\b/i,
    /\bsystem[\._-]?status\b/i,
];

const WIKIPEDIA_CAPABILITY_PATTERNS = [
    /\bwikipedia\b/i,
    /\bwikipedia[\._-]?search\b/i,
    /\bwiki\b/i,
];

const MAP_CAPABILITY_PATTERNS = [
    /\bmaps?\b/i,
    /\bmaps?[\._-]?search\b/i,
    /\bgoogle[\._-]?maps\b/i,
    /\bopenstreetmap\b/i,
];

const YOUTUBE_CAPABILITY_PATTERNS = [
    /\byoutube\b/i,
    /\byoutube[\._-]?(search|retrieve)\b/i,
    /\bvideo\b/i,
    /\bplayback\b/i,
];

const VISUAL_CAPTURE_PATTERNS = [
    /\bsystem\.control\.screenshot\b/i,
    /\bscreenshot\b/i,
    /\bprint\b/i,
    /\bprint\s+da\s+tela\b/i,
    /\bcaptura\b/i,
    /\bcapture\b/i,
    /\bfoto\b/i,
    /\bimagem\b/i,
    /\bscreen\b/i,
];

const WEGENA_CAPABILITY_PATTERNS = [
    /\bwegena\b/i,
    /\bwegena[\._-]?generate[\._-]?scene\b/i,
    /\bgenerate[\._-]?scene\b/i,
];

const normalizeSignalList = (items = []) => {
    const out = [];
    const seen = new Set();
    (Array.isArray(items) ? items : []).forEach((item) => {
        const value = String(item || '').trim();
        if (!value) return;
        const key = value.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        out.push(value);
    });
    return out;
};

const mergeSignalLists = (...lists) => normalizeSignalList(lists.flatMap((list) => (Array.isArray(list) ? list : [])));

const hasPatternMatch = (items, patterns) =>
    (Array.isArray(items) ? items : []).some((item) => patterns.some((pattern) => pattern.test(String(item || ''))));

const hasSystemHealthActionCue = (text) => {
    const raw = String(text || '').trim();
    if (!raw) return false;
    const hasShellAction = /\b(shell|system)\.control\.(status|execute|run|command)\b/i.test(raw);
    const hasInfraTerms = /\b(cpu|ram|mem[oó]ria|memory|disco|disk|host|sistema|system|uptime|load|rede|network)\b/i.test(raw);
    return hasShellAction && hasInfraTerms;
};

const extractSignalsFromWorkPayload = (payload) => {
    const context = payload?.context && typeof payload.context === 'object' ? payload.context : {};
    const data = context?.data && typeof context.data === 'object' ? context.data : {};
    const topCapabilities = Array.isArray(payload?.capabilities_used) ? payload.capabilities_used : [];
    const topActions = Array.isArray(payload?.actions_used) ? payload.actions_used : [];
    const dataActions = Array.isArray(data?.actions_used) ? data.actions_used : [];
    const sources = Array.isArray(data?.sources_used) ? data.sources_used : [];
    const media = Array.isArray(data?.media_used) ? data.media_used : [];
    return {
        capabilities: mergeSignalLists(topCapabilities, dataCapabilities),
        actions: mergeSignalLists(topActions, dataActions),
        sources,
        media,
    };
};

const normalizeSourceList = (items = []) => {
    const out = [];
    const seen = new Set();
    (Array.isArray(items) ? items : []).forEach((item) => {
        if (!item || typeof item !== 'object') return;
        const url = String(item.url || '').trim();
        if (!url) return;
        if (seen.has(url)) return;
        seen.add(url);
        out.push({
            url,
            title: String(item.title || '').trim(),
            action: String(item.action || '').trim(),
        });
    });
    return out;
};

const getFirstWikipediaSource = (sources = []) =>
    normalizeSourceList(sources).find((source) => /https?:\/\/([a-z-]+\.)?wikipedia\.org\//i.test(source.url)) || null;
const getFirstMapSource = (sources = []) =>
    normalizeSourceList(sources).find((source) => /https?:\/\/(www\.)?(google\.[^/]+\/maps|maps\.google\.[^/]+|openstreetmap\.org)/i.test(source.url)) || null;
const getFirstYouTubeSource = (sources = []) =>
    normalizeSourceList(sources).find((source) => /https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i.test(source.url)) || null;

const extractWikiTitleFromUrl = (url) => {
    const match = String(url || '').match(/\/wiki\/([^?#]+)/i);
    if (!match || !match[1]) return '';
    try {
        return decodeURIComponent(match[1]).replace(/_/g, ' ').trim();
    } catch {
        return match[1].replace(/_/g, ' ').trim();
    }
};

const summarizeTextForCard = (text, maxLen = 360) => {
    const clean = String(text || '')
        .replace(/\[(.*?)\]\((.*?)\)/g, '$1')
        .replace(/[#>*_`]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    if (!clean) return '';
    if (clean.length <= maxLen) return clean;
    return `${clean.slice(0, maxLen - 1).trimEnd()}…`;
};

const extractYouTubeTitleFromUrl = (url) => {
    const text = String(url || '').trim();
    if (!text) return '';
    try {
        const parsed = new URL(text);
        const path = parsed.pathname || '';
        if (path.startsWith('/watch')) {
            const videoId = parsed.searchParams.get('v');
            if (videoId) return `Video ${videoId}`;
        }
        if (path.startsWith('/shorts/')) {
            const part = path.split('/shorts/')[1];
            if (part) return `Short ${part.split('/')[0]}`;
        }
        if (parsed.hostname.includes('youtu.be')) {
            const part = path.replace(/^\/+/, '').split('/')[0];
            if (part) return `Video ${part}`;
        }
    } catch {
        // noop
    }
    return '';
};

const extractMapTitleFromUrl = (url) => {
    const text = String(url || '').trim();
    if (!text) return '';
    try {
        const parsed = new URL(text);
        const q = parsed.searchParams.get('q') || parsed.searchParams.get('query') || parsed.searchParams.get('destination');
        if (q) return decodeURIComponent(q).replace(/\+/g, ' ').trim();
        const path = parsed.pathname || '';
        const marker = path.match(/\/maps\/place\/([^/]+)/i);
        if (marker && marker[1]) return decodeURIComponent(marker[1]).replace(/\+/g, ' ').trim();
    } catch {
        // noop
    }
    return '';
};

const extractMapQueryFromContent = (content) => {
    const text = String(content || '').trim();
    if (!text) return '';
    const quoted = text.match(/['"]([^'"]{3,120})['"]/);
    if (quoted && quoted[1]) return quoted[1].trim();
    const searchIntent = text.match(/\b(?:buscando|procurando|pesquisando|searching\s+for|looking\s+for)\s+([a-z0-9\u00C0-\u017F\s,.-]{3,120}?)(?:\s+(?:em|na|no|near|for)\b|[.!?\n]|$)/i);
    if (searchIntent && searchIntent[1]) return searchIntent[1].trim();
    const mapsIntent = text.match(/\b(?:mostra|mostrar|me\s+mostre|encontre|localize)\s+([a-z0-9\u00C0-\u017F\s,.-]{3,120}?)\s+(?:no|na|em)\s+(?:google\s+)?maps?\b/i);
    if (mapsIntent && mapsIntent[1]) return mapsIntent[1].trim();
    const loc = text.match(/\b(em|no|na)\s+([a-z0-9\u00C0-\u017F\s,.-]{3,120})$/i);
    if (loc && loc[2]) return loc[2].trim();
    return '';
};

const isGenericMapQuery = (value) => {
    const text = String(value || '')
        .trim()
        .toLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '');
    if (!text) return true;
    const exact = new Set([
        'location',
        'local',
        'map',
        'maps',
        'mapa',
        'mapas',
        'google map',
        'google maps',
        'openstreetmap',
        'endereco',
        'rota',
        'route',
        'direcoes',
        'direcoes no mapa',
        'minha regiao',
        'na minha regiao',
        'sua regiao',
        'na sua regiao',
    ]);
    if (exact.has(text)) return true;
    if (/^(google\s+maps?|mapa(s)?|location|local)\b/.test(text)) return true;
    return false;
};

const hasUsefulMapTargetInUrl = (url) => {
    const raw = String(url || '').trim();
    if (!raw) return false;
    try {
        const parsed = new URL(raw);
        const host = parsed.hostname.toLowerCase();
        const path = (parsed.pathname || '').toLowerCase();
        const q = parsed.searchParams.get('q') || parsed.searchParams.get('query') || parsed.searchParams.get('destination');
        if (q && String(q).trim().length >= 2) return true;
        if (host.includes('google') && path.includes('/maps')) {
            if (path.includes('/place/') || path.includes('/search/') || path.includes('/dir/')) return true;
            return false;
        }
        if (host.includes('openstreetmap')) {
            if (parsed.searchParams.get('mlat') || parsed.searchParams.get('mlon')) return true;
            if (parsed.searchParams.get('query')) return true;
            if (path.includes('/search') || path.includes('/directions')) return true;
            return false;
        }
    } catch {
        return false;
    }
    return false;
};

const buildMapUrls = ({ sourceUrl, title, content, preferQuery = false }) => {
    const query = (title || extractMapQueryFromContent(content) || '').trim();
    const encoded = encodeURIComponent(query);
    const queryUrl = query ? `https://www.google.com/maps/search/?api=1&query=${encoded}` : '';
    const openUrl = preferQuery ? (queryUrl || sourceUrl) : (sourceUrl || queryUrl);
    const embedUrl = query ? `https://www.google.com/maps?q=${encoded}&output=embed` : '';
    return { openUrl, embedUrl };
};

export function useAssistCards({
    sessionId,
    workId,
    text,
    isUser,
    isStreaming,
    capabilitiesUsed = [],
    actionsUsed = [],
    sourcesUsed = [],
    mediaUsed = [],
}) {
    const [weatherCardLoading, setWeatherCardLoading] = useState(false);
    const [weatherCardData, setWeatherCardData] = useState(null);
    const [systemHealthLoading, setSystemHealthLoading] = useState(false);
    const [systemHealthData, setSystemHealthData] = useState(null);
    const [workSignals, setWorkSignals] = useState({ capabilities: [], actions: [], sources: [], media: [] });

    const content = String(text || '').trim();
    const anchorId = String(content.slice(0, 24) || 'msg');
    const hintCapabilities = useMemo(() => normalizeSignalList(capabilitiesUsed), [capabilitiesUsed]);
    const hintActions = useMemo(() => normalizeSignalList(actionsUsed), [actionsUsed]);
    const mergedCapabilities = useMemo(
        () => mergeSignalLists(hintCapabilities, workSignals.capabilities),
        [hintCapabilities, workSignals.capabilities],
    );
    const mergedActions = useMemo(
        () => mergeSignalLists(hintActions, workSignals.actions),
        [hintActions, workSignals.actions],
    );
    const mergedSources = useMemo(
        () => normalizeSourceList([...(Array.isArray(sourcesUsed) ? sourcesUsed : []), ...(Array.isArray(workSignals.sources) ? workSignals.sources : [])]),
        [sourcesUsed, workSignals.sources],
    );
    const mergedMedia = useMemo(
        () => [...(Array.isArray(mediaUsed) ? mediaUsed : []), ...(Array.isArray(workSignals.media) ? workSignals.media : [])],
        [mediaUsed, workSignals.media],
    );
    const weatherByCapability = hasPatternMatch(mergedCapabilities, WEATHER_CAPABILITY_PATTERNS) || hasPatternMatch(mergedActions, WEATHER_CAPABILITY_PATTERNS);
    const systemByCapability = hasPatternMatch(mergedCapabilities, SYSTEM_HEALTH_CAPABILITY_PATTERNS) || hasPatternMatch(mergedActions, SYSTEM_HEALTH_CAPABILITY_PATTERNS);
    const wikiByCapability = hasPatternMatch(mergedCapabilities, WIKIPEDIA_CAPABILITY_PATTERNS) || hasPatternMatch(mergedActions, WIKIPEDIA_CAPABILITY_PATTERNS);
    const mapByCapability = hasPatternMatch(mergedCapabilities, MAP_CAPABILITY_PATTERNS) || hasPatternMatch(mergedActions, MAP_CAPABILITY_PATTERNS);
    const youtubeByCapability = hasPatternMatch(mergedCapabilities, YOUTUBE_CAPABILITY_PATTERNS) || hasPatternMatch(mergedActions, YOUTUBE_CAPABILITY_PATTERNS);
    const wikiSource = getFirstWikipediaSource(mergedSources);
    const mapSource = getFirstMapSource(mergedSources);
    const youtubeSource = getFirstYouTubeSource(mergedSources);
    const wikiBySource = !!wikiSource;
    const mapBySource = !!mapSource;
    const youtubeBySource = !!youtubeSource;

    const wegenaByCapability = hasPatternMatch(mergedCapabilities, WEGENA_CAPABILITY_PATTERNS) || hasPatternMatch(mergedActions, WEGENA_CAPABILITY_PATTERNS);
    const wegenaMediaUrl = mergedMedia.find((m) => String(m).toLowerCase().endsWith('.weg')) || null;
    const wegenaByMedia = !!wegenaMediaUrl;

    const weatherIntent = weatherByCapability || hasWeatherCue(content);
    const captureIntent = hasPatternMatch(mergedCapabilities, VISUAL_CAPTURE_PATTERNS)
        || hasPatternMatch(mergedActions, VISUAL_CAPTURE_PATTERNS)
        || VISUAL_CAPTURE_PATTERNS.some((pattern) => pattern.test(content));
    const explicitSystemIntent = hasSystemHealthCue(content) || hasSystemHealthActionCue(content);
    const systemIntent = explicitSystemIntent || (systemByCapability && !captureIntent);
    const wikiIntent = wikiByCapability || wikiBySource || hasWikipediaCue(content);
    const mapIntent = mapByCapability || mapBySource;
    const youtubeIntent = youtubeByCapability || youtubeBySource;
    const wegenaIntent = wegenaByCapability || wegenaByMedia;

    // Global card priority to avoid visual conflicts:
    // wegena > weather > system > knowledge (map/wiki/youtube) > data chart
    const shouldTryWegenaCard = !isUser && !!sessionId && wegenaIntent;
    const shouldTryWeatherCard = !isUser && !!sessionId && !shouldTryWegenaCard && weatherIntent;
    const shouldTrySystemHealthCard = !isUser && !!sessionId && !shouldTryWegenaCard && !shouldTryWeatherCard && systemIntent;
    const shouldTryMapCard = !isUser && !shouldTryWegenaCard && !shouldTryWeatherCard && !shouldTrySystemHealthCard && mapIntent;
    const shouldTryWikiCard = !isUser && !shouldTryWegenaCard && !shouldTryWeatherCard && !shouldTrySystemHealthCard && wikiIntent;
    const shouldTryYouTubeCard = !isUser && !shouldTryWegenaCard && !shouldTryWeatherCard && !shouldTrySystemHealthCard && youtubeIntent;
    const shouldTryKnowledgeCards = shouldTryMapCard || shouldTryWikiCard || shouldTryYouTubeCard;
    const wikiCardData = useMemo(() => {
        if (!shouldTryWikiCard) return null;
        const sourceUrl = wikiSource?.url || '';
        const languageMatch = sourceUrl.match(/https?:\/\/([a-z-]+)\.wikipedia\.org/i);
        const inferredLanguage = languageMatch?.[1] || '';
        const inferredTitle = wikiSource?.title || extractWikiTitleFromUrl(sourceUrl);
        return {
            title: inferredTitle || 'Wikipedia',
            query: content,
            summary: summarizeTextForCard(content),
            sourceUrl,
            language: inferredLanguage,
        };
    }, [shouldTryWikiCard, wikiSource, content]);
    const mapCardData = useMemo(() => {
        if (!shouldTryMapCard) return null;
        const sourceUrl = mapSource?.url || '';
        const sourceTitle = mapSource?.title || extractMapTitleFromUrl(sourceUrl) || '';
        const queryFromContent = extractMapQueryFromContent(content) || '';
        const contentHasMapFailure = /\b(falh(?:a|ou|aram)|erro|dificuldad(?:e|es)|n[aã]o\s+consegui|indispon[ií]vel|sem\s+resultados?|resultados?\s+irrelevantes?)\b/i.test(content);
        const sourceIsUseful = hasUsefulMapTargetInUrl(sourceUrl);
        const sourceTitleIsSpecific = sourceTitle && !isGenericMapQuery(sourceTitle);
        const contentQueryIsSpecific = queryFromContent && !isGenericMapQuery(queryFromContent);
        const finalQuery = sourceTitleIsSpecific ? sourceTitle : (contentQueryIsSpecific ? queryFromContent : '');
        if (!sourceIsUseful && !finalQuery) {
            return null;
        }
        const mapUrls = buildMapUrls({
            sourceUrl: sourceIsUseful ? sourceUrl : '',
            title: finalQuery,
            content: finalQuery || content,
            preferQuery: contentHasMapFailure,
        });
        if (!mapUrls.openUrl && !mapUrls.embedUrl) return null;
        return {
            title: finalQuery || 'Map',
            query: finalQuery || '',
            description: summarizeTextForCard(content, 220),
            sourceUrl: mapUrls.openUrl,
            embedUrl: mapUrls.embedUrl,
            provider: sourceUrl.includes('openstreetmap') ? 'OpenStreetMap' : 'Google Maps',
        };
    }, [shouldTryMapCard, mapSource, content]);
    const youtubeCardData = useMemo(() => {
        if (!shouldTryYouTubeCard) return null;
        const sourceUrl = youtubeSource?.url || '';
        return {
            title: youtubeSource?.title || extractYouTubeTitleFromUrl(sourceUrl) || 'YouTube Video',
            description: summarizeTextForCard(content, 220),
            sourceUrl,
            channel: '',
        };
    }, [shouldTryYouTubeCard, youtubeSource, content]);
    const parsedDataChart = useMemo(() => {
        if (isUser || isStreaming) return null;
        if (shouldTryWeatherCard || shouldTrySystemHealthCard || shouldTryKnowledgeCards || shouldTryWegenaCard) return null;
        return tryParseMarkdownTable(content);
    }, [isUser, isStreaming, content, shouldTryWeatherCard, shouldTrySystemHealthCard, shouldTryKnowledgeCards, shouldTryWegenaCard]);

    useEffect(() => {
        if (isUser || !workId) return undefined;

        const cacheKey = `${workId}`;
        let cancelled = false;
        let intervalId = null;

        const refreshSignals = async () => {
            const now = Date.now();
            const ttl = isStreaming ? WORK_CAPABILITY_CACHE_TTL_STREAM_MS : WORK_CAPABILITY_CACHE_TTL_IDLE_MS;
            const cached = WORK_CAPABILITY_SIGNALS_CACHE.get(cacheKey);
            if (cached && (now - cached.ts) < ttl) {
                if (!cancelled) setWorkSignals(cached.signals);
                return;
            }

            const pending = WORK_CAPABILITY_SIGNALS_PENDING.get(cacheKey);
            const url = `/tasks/works/${workId}?requester_session_id=${encodeURIComponent(sessionId || '')}`;
            const fetchPromise = pending || api.get(url);
            if (!pending) WORK_CAPABILITY_SIGNALS_PENDING.set(cacheKey, fetchPromise);

            try {
                const payload = await fetchPromise;
                if (cancelled) return;
                const signals = extractSignalsFromWorkPayload(payload || {});
                WORK_CAPABILITY_SIGNALS_CACHE.set(cacheKey, { ts: Date.now(), signals });
                setWorkSignals(signals);
            } catch {
                if (!cancelled) setWorkSignals((prev) => prev || { capabilities: [], actions: [], sources: [], media: [] });
            } finally {
                if (!pending) WORK_CAPABILITY_SIGNALS_PENDING.delete(cacheKey);
            }
        };

        refreshSignals();
        if (isStreaming) {
            intervalId = setInterval(refreshSignals, 1200);
        }

        return () => {
            cancelled = true;
            if (intervalId) clearInterval(intervalId);
        };
    }, [isUser, workId, isStreaming, sessionId]);

    useEffect(() => {
        if (!shouldTryWeatherCard) return undefined;

        const cacheKey = `${sessionId}:weather`;
        const now = Date.now();
        const cached = WEATHER_CARD_CACHE.get(cacheKey);
        if (cached && (now - cached.ts) < WEATHER_CACHE_TTL_MS) {
            setWeatherCardData(cached.data);
            return undefined;
        }

        let cancelled = false;
        const pending = WEATHER_CARD_PENDING.get(cacheKey);
        const weatherHint = encodeURIComponent(content.slice(0, 320));
        const fetchPromise = pending || api.get('/sessions/' + sessionId + `/cards/weather?days=5&hint=${weatherHint}`);
        if (!pending) WEATHER_CARD_PENDING.set(cacheKey, fetchPromise);
        setWeatherCardLoading(true);

        fetchPromise
            .then((payload) => {
                if (cancelled) return;
                WEATHER_CARD_CACHE.set(cacheKey, { ts: Date.now(), data: payload });
                setWeatherCardData(payload);
            })
            .catch(() => {
                if (!cancelled) setWeatherCardData(null);
            })
            .finally(() => {
                if (!pending) WEATHER_CARD_PENDING.delete(cacheKey);
                if (!cancelled) setWeatherCardLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [shouldTryWeatherCard, sessionId, content]);

    useEffect(() => {
        if (!shouldTrySystemHealthCard) return undefined;

        const cacheKey = `${sessionId}:system-health`;
        const now = Date.now();
        const cached = SYSTEM_HEALTH_CARD_CACHE.get(cacheKey);
        if (cached && (now - cached.ts) < SYSTEM_HEALTH_CACHE_TTL_MS) {
            setSystemHealthData(cached.data);
            return undefined;
        }

        let cancelled = false;
        const pending = SYSTEM_HEALTH_CARD_PENDING.get(cacheKey);
        const fetchPromise = pending || api.get(`/sessions/${sessionId}/cards/system-health`);
        if (!pending) SYSTEM_HEALTH_CARD_PENDING.set(cacheKey, fetchPromise);
        setSystemHealthLoading(true);

        fetchPromise
            .then((payload) => {
                if (cancelled) return;
                SYSTEM_HEALTH_CARD_CACHE.set(cacheKey, { ts: Date.now(), data: payload });
                setSystemHealthData(payload);
            })
            .catch((err) => {
                if (!cancelled) {
                    const message = err?.message ? String(err.message) : 'Request failed';
                    setSystemHealthData({ ok: false, message });
                }
            })
            .finally(() => {
                if (!pending) SYSTEM_HEALTH_CARD_PENDING.delete(cacheKey);
                if (!cancelled) setSystemHealthLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [shouldTrySystemHealthCard, sessionId]);

    return {
        anchorId,
        shouldTryWegenaCard,
        shouldTryWeatherCard,
        shouldTrySystemHealthCard,
        shouldTryWikiCard,
        shouldTryMapCard,
        shouldTryYouTubeCard,
        wikiCardData,
        mapCardData,
        youtubeCardData,
        parsedDataChart,
        weatherCardLoading,
        weatherCardData,
        systemHealthLoading,
        systemHealthData,
        wegenaMediaUrl,
    };
}
