import {
    BookOpen,
    Brain,
    CloudSun,
    Database,
    Globe,
    MapPin,
    MonitorCog,
    Music2,
    Puzzle,
    Search,
    Terminal,
    Video,
} from 'lucide-react';

const ICON_LIBRARY = {
    browser: { key: 'browser', label: 'Browser', logoUrl: 'https://www.chromium.org', Icon: MonitorCog, color: '#60a5fa' },
    data: { key: 'data', label: 'Data', logoUrl: '', Icon: Database, color: '#22d3ee' },
    deezer: { key: 'deezer', label: 'Deezer', logoUrl: 'https://www.deezer.com', Icon: Music2, color: '#a78bfa' },
    maps: { key: 'maps', label: 'Maps', logoUrl: 'https://maps.google.com', Icon: MapPin, color: '#34d399' },
    memory: { key: 'memory', label: 'Memory', logoUrl: '', Icon: Brain, color: '#fb7185' },
    search: { key: 'search', label: 'Search', logoUrl: '', Icon: Search, color: '#38bdf8' },
    shell: { key: 'shell', label: 'Shell', logoUrl: '', Icon: Terminal, color: '#f59e0b' },
    spotify: { key: 'spotify', label: 'Spotify', logoUrl: 'https://open.spotify.com', Icon: Music2, color: '#22c55e' },
    system: { key: 'system', label: 'System', logoUrl: '', Icon: Terminal, color: '#94a3b8' },
    vision: { key: 'vision', label: 'Vision', logoUrl: '', Icon: MonitorCog, color: '#e879f9' },
    weather: { key: 'weather', label: 'Weather', logoUrl: '', Icon: CloudSun, color: '#facc15' },
    web: { key: 'web', label: 'Web', logoUrl: '', Icon: Globe, color: '#22d3ee' },
    wikipedia: { key: 'wikipedia', label: 'Wikipedia', logoUrl: 'https://wikipedia.org', Icon: BookOpen, color: '#cbd5e1' },
    youtube: { key: 'youtube', label: 'YouTube', logoUrl: 'https://www.youtube.com', Icon: Video, color: '#ef4444' },
};

const FALLBACK_VISUAL = { key: 'default', label: 'Skill', logoUrl: '', Icon: Puzzle, color: '#a78bfa' };

const normalize = (value) => String(value || '').trim().toLowerCase();

const resolveByText = (text) => {
    if (!text) return null;
    if (/(^|[\s._-])youtube($|[\s._-])|youtu\.?be/.test(text)) return ICON_LIBRARY.youtube;
    if (/(^|[\s._-])wikipedia($|[\s._-])|(^|[\s._-])wiki($|[\s._-])/.test(text)) return ICON_LIBRARY.wikipedia;
    if (/(^|[\s._-])maps?($|[\s._-])|google[\s._-]?maps|openstreetmap/.test(text)) return ICON_LIBRARY.maps;
    if (/browser[\s._-]?control|chrom(e|ium)|cdp/.test(text)) return ICON_LIBRARY.browser;
    if (/spotify/.test(text)) return ICON_LIBRARY.spotify;
    if (/deezer/.test(text)) return ICON_LIBRARY.deezer;
    if (/weather|forecast|meteo/.test(text)) return ICON_LIBRARY.weather;
    if (/web[\s._-]?(search|retrieve)|search|retrieve|rag/.test(text)) return ICON_LIBRARY.web;
    if (/shell|terminal/.test(text)) return ICON_LIBRARY.shell;
    if (/system[\s._-]?control|system[\s._-]?logs/.test(text)) return ICON_LIBRARY.system;
    if (/memory|deep[\s._-]?memory/.test(text)) return ICON_LIBRARY.memory;
    if (/vision|image|screenshot/.test(text)) return ICON_LIBRARY.vision;
    if (/data[\s._-]?analysis/.test(text)) return ICON_LIBRARY.data;
    return null;
};

export const getSkillVisual = ({ skillId = '', skillName = '', actionId = '', iconKey = '', iconUrl = '' } = {}) => {
    const explicitKey = normalize(iconKey);
    if (explicitKey && ICON_LIBRARY[explicitKey]) {
        const base = ICON_LIBRARY[explicitKey];
        return { ...base, logoUrl: iconUrl || base.logoUrl };
    }

    const combined = normalize([skillId, skillName, actionId].filter(Boolean).join(' '));
    const inferred = resolveByText(combined);
    if (inferred) {
        return { ...inferred, logoUrl: iconUrl || inferred.logoUrl };
    }

    return { ...FALLBACK_VISUAL, logoUrl: iconUrl || '' };
};
