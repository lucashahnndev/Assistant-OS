import React, { memo, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
    Activity,
    BookOpen,
    Cloud,
    CloudDrizzle,
    CloudLightning,
    CloudRain,
    Cpu,
    Droplets,
    ExternalLink,
    HardDrive,
    MapPin,
    Maximize2,
    MemoryStick,
    PlayCircle,
    Server,
    Clock3,
    Wifi,
    Sun,
    Thermometer,
    Wind,
    X,
} from 'lucide-react';

export const WEATHER_CARD_CACHE = new Map();
export const WEATHER_CARD_PENDING = new Map();
export const WEATHER_CACHE_TTL_MS = 5 * 60 * 1000;

export const SYSTEM_HEALTH_CARD_CACHE = new Map();
export const SYSTEM_HEALTH_CARD_PENDING = new Map();
export const SYSTEM_HEALTH_CACHE_TTL_MS = 20 * 1000;

const WEATHER_CUE_PATTERNS = [
    /\bclima\b/i,
    /\btemperaturas?\b/i,
    /\btempo\s+agora\b/i,
    /\bprevis[aã]o\b/i,
    /\bsensa[cç][aã]o\s+t[ée]rmica\b/i,
    /\bweather\b/i,
    /\bforecast\b/i,
    /\bumidade\b/i,
    /\bvento(s)?\b/i,
    /\bchuva\b/i,
    /\bcelsius\b/i,
    /°\s*c\b/i,
    /\bfeels?\s+like\b/i,
];

const SYSTEM_HEALTH_CUE_PATTERNS = [
    /\bsystem\s+health\b/i,
    /\bsa[uú]de\s+do\s+sistema\b/i,
    /\bstatus\s+(geral\s+)?do\s+sistema\b/i,
    /\bstatus\s+da\s+m[aá]quina\b/i,
    /\bhost\s+status\b/i,
    /\bstatus\s+do\s+host\b/i,
    /\buso\s+de\s+cpu\b/i,
    /\buso\s+de\s+mem[oó]ria\b/i,
    /\buso\s+de\s+disco\b/i,
    /\buso\s+de\s+rede\b/i,
    /\bcomo\s+est[aá]\s+o\s+sistema\b/i,
    /\bcpu\b/i,
    /\bram\b/i,
    /\bmem[oó]ria\b/i,
    /\bdisco\b/i,
    /\bdisk\b/i,
    /\buptime\b/i,
    /\bload\b/i,
    /\brede\b/i,
    /\bnetwork\b/i,
];

const WIKIPEDIA_CUE_PATTERNS = [
    /\bwikipedia\b/i,
    /\bwiki\b/i,
    /\benciclop[eé]dia\b/i,
];

const MAP_CUE_PATTERNS = [
    /\bmapa(s)?\b/i,
    /\bmaps\b/i,
    /\bgoogle maps\b/i,
    /\brota\b/i,
    /\btrajeto\b/i,
    /\bendere[cç]o\b/i,
    /\blocaliza[cç][aã]o\b/i,
];

const YOUTUBE_CUE_PATTERNS = [
    /\byoutube\b/i,
    /\byt\b/i,
    /\bvideo(s)?\b/i,
    /\bassistir\b/i,
    /\bwatch\b/i,
    /\btocar\b/i,
    /\bplay\b/i,
];

const normalizeNumeric = (value) => {
    if (value === null || value === undefined || value === '') return null;
    const n = Number.parseFloat(String(value).replace(',', '.'));
    return Number.isFinite(n) ? n : null;
};

const fmtTemp = (value) => {
    const n = normalizeNumeric(value);
    return n === null ? '--' : `${n.toFixed(1)}°C`;
};

const fmtPct = (value) => {
    const n = normalizeNumeric(value);
    return n === null ? '--' : `${Math.round(n)}%`;
};

const fmtWind = (value) => {
    const n = normalizeNumeric(value);
    return n === null ? '--' : `${n.toFixed(0)} km/h`;
};

const bytesToHuman = (value) => {
    const n = normalizeNumeric(value);
    if (n === null) return '--';
    if (n < 1024) return `${Math.round(n)} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let size = n;
    let idx = -1;
    while (size >= 1024 && idx < units.length - 1) {
        size /= 1024;
        idx += 1;
    }
    return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[Math.max(0, idx)]}`;
};

const kbpsToHuman = (value) => {
    const n = normalizeNumeric(value);
    if (n === null) return '--';
    if (n < 1024) return `${n.toFixed(n >= 100 ? 0 : 1)} kB/s`;
    return `${(n / 1024).toFixed(2)} MB/s`;
};

const pctColor = (pct) => {
    const n = normalizeNumeric(pct);
    if (n === null) return 'var(--text-muted)';
    if (n >= 85) return '#f87171';
    if (n >= 65) return '#fbbf24';
    return '#34d399';
};

const pctGradient = (pct) => {
    const n = normalizeNumeric(pct);
    if (n === null) return 'linear-gradient(90deg, rgba(148,163,184,0.9), rgba(148,163,184,0.55))';
    if (n >= 85) return 'linear-gradient(90deg, #f97373, #fb7185)';
    if (n >= 65) return 'linear-gradient(90deg, #facc15, #f59e0b)';
    return 'linear-gradient(90deg, #34d399, #22d3ee)';
};

const shortDayLabel = (value) => {
    const raw = String(value || '').trim();
    if (!raw) return '--';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    return weekdays[date.getDay()];
};

const formatLoadAvg = (value) => {
    if (!Array.isArray(value) || value.length === 0) return '--';
    const nums = value.map((v) => normalizeNumeric(v)).filter((v) => v !== null);
    if (nums.length === 0) return '--';
    return nums.slice(0, 3).map((v) => v.toFixed(2)).join(' / ');
};

const weatherIconForDescription = (description) => {
    const text = String(description || '').toLowerCase();
    if (text.includes('trovo') || text.includes('storm') || text.includes('thunder')) {
        return { icon: CloudLightning, color: '#a5b4fc' };
    }
    if (text.includes('garoa') || text.includes('drizzle')) {
        return { icon: CloudDrizzle, color: '#93c5fd' };
    }
    if (text.includes('chuva') || text.includes('rain')) {
        return { icon: CloudRain, color: '#7dd3fc' };
    }
    if (text.includes('nublado') || text.includes('cloud')) {
        return { icon: Cloud, color: '#cbd5e1' };
    }
    return { icon: Sun, color: '#fcd34d' };
};

const buildLinePath = (values, width, height, padX, padY) => {
    if (!Array.isArray(values) || values.length < 2) return '';
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = Math.max(1e-9, max - min);
    const innerW = width - (padX * 2);
    const innerH = height - (padY * 2);
    const points = values.map((v, idx) => {
        const x = padX + ((innerW * idx) / Math.max(1, values.length - 1));
        const y = padY + (innerH - (((v - min) / span) * innerH));
        return { x, y };
    });
    return points.reduce((acc, p, idx, arr) => {
        if (idx === 0) return `M${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
        const prev = arr[idx - 1];
        const cx = ((prev.x + p.x) / 2).toFixed(2);
        return `${acc} Q ${cx} ${prev.y.toFixed(2)}, ${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
    }, '');
};

export const hasWeatherCue = (text) => {
    const normalized = String(text || '').trim();
    if (!normalized) return false;
    return WEATHER_CUE_PATTERNS.some((pattern) => pattern.test(normalized));
};

export const hasSystemHealthCue = (text) => {
    const normalized = String(text || '').trim();
    if (!normalized) return false;
    return SYSTEM_HEALTH_CUE_PATTERNS.some((pattern) => pattern.test(normalized));
};

export const hasWikipediaCue = (text) => {
    const normalized = String(text || '').trim();
    if (!normalized) return false;
    return WIKIPEDIA_CUE_PATTERNS.some((pattern) => pattern.test(normalized));
};

export const hasMapCue = (text) => {
    const normalized = String(text || '').trim();
    if (!normalized) return false;
    return MAP_CUE_PATTERNS.some((pattern) => pattern.test(normalized));
};

export const hasYouTubeCue = (text) => {
    const normalized = String(text || '').trim();
    if (!normalized) return false;
    return YOUTUBE_CUE_PATTERNS.some((pattern) => pattern.test(normalized));
};

export const tryParseMarkdownTable = (text) => {
    const raw = String(text || '');
    if (!raw.includes('|')) return null;

    const lines = raw
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line.includes('|'));

    if (lines.length < 3) return null;

    const headerIdx = lines.findIndex((line, idx) => idx + 1 < lines.length && /^\|?[\s:-]+\|[\s|:-]*$/.test(lines[idx + 1]));
    if (headerIdx < 0 || headerIdx + 2 >= lines.length) return null;

    const splitRow = (line) =>
        line
            .replace(/^\|/, '')
            .replace(/\|$/, '')
            .split('|')
            .map((c) => c.trim());

    const headers = splitRow(lines[headerIdx]).filter(Boolean);
    if (headers.length < 2) return null;

    const rows = [];
    for (let i = headerIdx + 2; i < lines.length; i += 1) {
        const row = splitRow(lines[i]);
        if (row.length < headers.length) continue;
        rows.push(row.slice(0, headers.length));
    }
    if (rows.length < 2) return null;

    const numericColumns = [];
    for (let col = 1; col < headers.length; col += 1) {
        let valid = 0;
        rows.forEach((row) => {
            if (normalizeNumeric(row[col]) !== null) valid += 1;
        });
        if (valid >= Math.max(2, Math.floor(rows.length * 0.7))) numericColumns.push(col);
    }

    if (numericColumns.length === 0) return null;

    const yCol = numericColumns[0];
    const points = rows
        .map((row) => ({
            label: String(row[0] || '').trim(),
            value: normalizeNumeric(row[yCol]),
        }))
        .filter((p) => p.label && p.value !== null);

    if (points.length < 2) return null;

    return {
        title: headers[yCol],
        xLabel: headers[0],
        yLabel: headers[yCol],
        points: points.slice(0, 24),
    };
};

export const WeatherAssistCard = memo(({ data, isStage = false }) => {
    const [showDetails, setShowDetails] = useState(true);
    const [metricTab, setMetricTab] = useState('temp');
    const [selectedDayIndex, setSelectedDayIndex] = useState(0);
    const [hoveredPoint, setHoveredPoint] = useState(null);
    const current = data?.current || {};
    const forecast = Array.isArray(data?.forecast) ? data.forecast : [];
    const location = String(data?.location || 'Unknown');
    const pickNumber = (obj, keys) => {
        for (const key of keys) {
            const n = normalizeNumeric(obj?.[key]);
            if (n !== null) return n;
        }
        return null;
    };
    const currentTemp = pickNumber(current, ['temp_c', 'temp', 'temperature', 'current_temperature']);
    const currentFeels = pickNumber(current, ['feels_like_c', 'feelslike_c', 'feels_like', 'feelsLike']);
    const currentHumidity = pickNumber(current, ['humidity', 'humidity_percent']);
    const currentWind = pickNumber(current, ['wind_kph', 'wind_speed', 'wind', 'windSpeed']);
    const currentPop = pickNumber(current, ['pop', 'precipitation_probability', 'rain_probability']) ?? 0;
    const todayDateKey = useMemo(() => {
        const now = new Date();
        const y = now.getFullYear();
        const m = String(now.getMonth() + 1).padStart(2, '0');
        const d = String(now.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    }, []);

    const days = useMemo(() => {
        const entries = [
            {
                label: 'Hoje',
                isNow: true,
                description: current?.description,
                tempMax: currentTemp,
                tempMin: currentTemp !== null ? currentTemp - 2 : null,
                humidity: currentHumidity,
                wind: currentWind,
                pop: currentPop,
                date: null,
            },
        ];
        let skippedTodayForecast = false;
        forecast.slice(0, 7).forEach((day) => {
            const forecastDate = String(day?.date || '').trim();
            if (!skippedTodayForecast && forecastDate && forecastDate === todayDateKey) {
                skippedTodayForecast = true;
                return;
            }
            entries.push({
                label: shortDayLabel(day?.date),
                isNow: false,
                description: day?.description,
                tempMax: pickNumber(day, ['temp_max', 'temp_c', 'temp', 'temperature']),
                tempMin: pickNumber(day, ['temp_min', 'min_temp', 'temperature_min']),
                humidity: pickNumber(day, ['humidity', 'humidity_percent']),
                wind: pickNumber(day, ['wind_kph', 'wind_speed', 'wind']),
                pop: pickNumber(day, ['pop', 'precipitation_probability', 'rain_probability']) ?? 0,
                date: day?.date || null,
            });
        });
        return entries;
    }, [forecast, current?.description, currentHumidity, currentPop, currentTemp, currentWind, todayDateKey]);

    const selectedDay = days[Math.max(0, Math.min(selectedDayIndex, days.length - 1))] || days[0] || null;

    const metricConfig = useMemo(() => {
        if (metricTab === 'pop') {
            return { key: 'pop', unit: '%', stroke: '#60a5fa', fill: 'rgba(96,165,250,0.20)', tab: 'Chuva' };
        }
        if (metricTab === 'wind') {
            return { key: 'wind', unit: ' km/h', stroke: '#22d3ee', fill: 'rgba(34,211,238,0.18)', tab: 'Vento' };
        }
        return { key: 'temp', unit: '°C', stroke: '#facc15', fill: 'rgba(250,204,21,0.22)', tab: 'Temperatura' };
    }, [metricTab]);

    const chartSeries = useMemo(() => {
        if (!selectedDay) return [];
        const labels = ['06h', '09h', '12h', '15h', '18h', '21h', '00h', '03h'];
        const baseMax = normalizeNumeric(selectedDay.tempMax);
        const baseMin = normalizeNumeric(selectedDay.tempMin);
        const tempMax = baseMax ?? currentTemp ?? 26;
        const tempMin = baseMin ?? (tempMax - 6);
        const amplitude = Math.max(2, tempMax - tempMin);
        const popBase = Math.max(0, Math.min(100, normalizeNumeric(selectedDay.pop) ?? currentPop ?? 0));
        const windBase = Math.max(0, normalizeNumeric(selectedDay.wind) ?? currentWind ?? 9);
        const seedRaw = `${selectedDay.date || ''}|${selectedDay.description || ''}|${selectedDay.label || ''}`;
        let seed = 0;
        for (let i = 0; i < seedRaw.length; i += 1) seed = ((seed * 31) + seedRaw.charCodeAt(i)) % 9973;
        const phase = (seed % 360) * (Math.PI / 180);
        const dayShift = (seed % 7) / 30;

        return labels.map((label, idx) => {
            const t = idx / Math.max(1, labels.length - 1);
            const tempFactor = Math.max(0.14, Math.min(1, 0.52 + (0.43 * Math.sin((t * Math.PI * 1.6) - 0.9 + phase + dayShift))));
            const popFactor = Math.max(0.08, Math.min(1.3, 0.72 + (0.5 * Math.cos((t * Math.PI * 2.2) + (phase * 0.7)))));
            const windFactor = Math.max(0.38, Math.min(1.45, 0.9 + (0.33 * Math.sin((t * Math.PI * 2.4) + (phase * 0.45) + 0.35))));
            const temp = tempMin + (amplitude * tempFactor);
            const pop = Math.max(0, Math.min(100, popBase * popFactor));
            const wind = Math.max(0, windBase * windFactor);
            return { label, temp, pop, wind };
        });
    }, [selectedDay, currentPop, currentTemp, currentWind]);

    const CHART_W = 520;
    const CHART_H = 92;
    const CHART_PAD_X = 10;
    const CHART_PAD_Y = 8;
    const chartValues = chartSeries.map((p) => normalizeNumeric(p?.[metricConfig.key]));
    const safeValues = chartValues.map((v) => (v === null ? 0 : v));
    const trendPath = useMemo(() => buildLinePath(safeValues, CHART_W, CHART_H, CHART_PAD_X, CHART_PAD_Y), [safeValues]);
    const trendMin = safeValues.length > 0 ? Math.min(...safeValues) : null;
    const trendMax = safeValues.length > 0 ? Math.max(...safeValues) : null;
    const feelsLike = fmtTemp(currentFeels);
    const graphPoints = useMemo(() => {
        if (safeValues.length < 2) return [];
        const min = Math.min(...safeValues);
        const max = Math.max(...safeValues);
        const span = Math.max(1e-9, max - min);
        const width = CHART_W;
        const height = CHART_H;
        const padX = CHART_PAD_X;
        const padY = CHART_PAD_Y;
        const innerW = width - (padX * 2);
        const innerH = height - (padY * 2);
        return safeValues.map((v, idx) => ({
            x: padX + ((innerW * idx) / Math.max(1, safeValues.length - 1)),
            y: padY + (innerH - (((v - min) / span) * innerH)),
            value: v,
            label: chartSeries[idx]?.label || String(idx),
        }));
    }, [safeValues, chartSeries, CHART_H, CHART_PAD_X, CHART_PAD_Y, CHART_W]);
    const metricValueFmt = (value) => {
        if (value === null || value === undefined || Number.isNaN(value)) return '--';
        if (metricTab === 'temp') return `${value.toFixed(1)}°`;
        if (metricTab === 'pop') return `${Math.round(value)}%`;
        return `${value.toFixed(1)} km/h`;
    };
    const selectedDayIconMeta = weatherIconForDescription(selectedDay?.description);
    const SelectedDayIcon = selectedDayIconMeta.icon;

    useEffect(() => {
        setHoveredPoint(null);
    }, [metricTab, selectedDayIndex]);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div
                style={{
                    border: isStage ? '1px solid rgba(var(--accent-rgb), 0.2)' : '1px solid var(--card-border)',
                    borderRadius: '12px',
                    padding: isStage ? '20px' : '10px',
                    background: isStage
                        ? 'radial-gradient(circle at 0% 0%, rgba(var(--accent-rgb), 0.1), transparent 60%)'
                        : 'radial-gradient(circle at 0% 0%, rgba(125,211,252,0.14), transparent 45%), linear-gradient(120deg, rgba(14,116,144,0.2), rgba(59,130,246,0.09))',
                    boxShadow: isStage ? 'none' : 'inset 0 1px 0 rgba(255,255,255,0.05)',
                    backdropFilter: isStage ? 'blur(10px)' : 'none',
                }}
            >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div
                            style={{
                                width: '46px',
                                height: '46px',
                                borderRadius: '50%',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                background: 'linear-gradient(180deg, rgba(255,255,255,0.12), rgba(255,255,255,0.04))',
                                border: '1px solid rgba(255,255,255,0.12)',
                            }}
                        >
                            <SelectedDayIcon size={22} color={selectedDayIconMeta.color} />
                        </div>
                        <div>
                            <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '0.01em' }}>{location}</div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{String(selectedDay?.description || current?.description || '--')}</div>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={() => setShowDetails((prev) => !prev)}
                        style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-primary)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '4px 10px', background: 'rgba(255,255,255,0.03)', cursor: 'pointer' }}
                    >
                        {showDetails ? 'Hide details' : 'Show details'}
                    </button>
                </div>

                <div
                    style={{
                        marginTop: '8px',
                        border: '1px solid var(--card-border)',
                        borderRadius: '11px',
                        padding: '10px',
                        background: 'linear-gradient(180deg, rgba(2,6,23,0.36), rgba(15,23,42,0.16))',
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                            <span style={{ fontSize: '42px', lineHeight: 1, fontWeight: 300, color: 'var(--text-primary)', letterSpacing: '-0.03em' }}>
                                {fmtTemp(selectedDay?.tempMax ?? currentTemp).replace('°C', '')}
                            </span>
                            <span style={{ fontSize: '16px', color: 'var(--text-muted)', paddingBottom: '6px' }}>°C</span>
                        </div>
                        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                            <span style={{ fontSize: '10px', color: 'var(--text-primary)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '2px 7px', background: 'rgba(255,255,255,0.03)' }}>
                                Feels like {feelsLike}
                            </span>
                            {selectedDay?.label && (
                                <span style={{ fontSize: '10px', color: 'var(--text-primary)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '2px 7px', background: 'rgba(255,255,255,0.03)' }}>
                                    {selectedDay.label}
                                </span>
                            )}
                            {trendMin !== null && trendMax !== null && (
                                <span style={{ fontSize: '10px', color: 'var(--text-primary)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '2px 7px', background: 'rgba(255,255,255,0.03)' }}>
                                    {metricValueFmt(trendMin)} / {metricValueFmt(trendMax)}
                                </span>
                            )}
                        </div>
                    </div>
                    {showDetails && safeValues.length >= 2 && (
                        <div style={{ marginTop: '10px', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '8px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                                {[
                                    { id: 'temp', label: 'Temperatura' },
                                    { id: 'pop', label: 'Chuva' },
                                    { id: 'wind', label: 'Vento' },
                                ].map((tab) => (
                                    <button
                                        key={tab.id}
                                        type="button"
                                        onClick={() => setMetricTab(tab.id)}
                                        style={{
                                            fontSize: '11px',
                                            fontWeight: metricTab === tab.id ? 700 : 500,
                                            padding: '2px 0',
                                            border: 'none',
                                            borderBottom: metricTab === tab.id ? `2px solid ${metricConfig.stroke}` : '2px solid transparent',
                                            background: 'transparent',
                                            color: metricTab === tab.id ? 'var(--text-primary)' : 'var(--text-muted)',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        {tab.label}
                                    </button>
                                ))}
                            </div>
                            <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" style={{ width: '100%', height: '76px', display: 'block' }}>
                                <defs>
                                    <linearGradient id="weatherTrendFill" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="0%" stopColor={metricConfig.stroke} stopOpacity="0.28" />
                                        <stop offset="100%" stopColor={metricConfig.stroke} stopOpacity="0.02" />
                                    </linearGradient>
                                    <linearGradient id="weatherTrendStroke" x1="0" y1="0" x2="1" y2="0">
                                        <stop offset="0%" stopColor={metricConfig.stroke} />
                                        <stop offset="100%" stopColor={metricConfig.stroke} />
                                    </linearGradient>
                                </defs>
                                {[0.25, 0.5, 0.75].map((r) => (
                                    <line
                                        key={`grid-y-${r}`}
                                        x1={CHART_PAD_X}
                                        y1={CHART_PAD_Y + ((CHART_H - (CHART_PAD_Y * 2)) * r)}
                                        x2={CHART_W - CHART_PAD_X}
                                        y2={CHART_PAD_Y + ((CHART_H - (CHART_PAD_Y * 2)) * r)}
                                        stroke="rgba(255,255,255,0.08)"
                                        strokeWidth="0.7"
                                        strokeDasharray="2 4"
                                    />
                                ))}
                                <path d={`${trendPath} L${CHART_W - CHART_PAD_X} ${CHART_H - CHART_PAD_Y} L${CHART_PAD_X} ${CHART_H - CHART_PAD_Y} Z`} fill="url(#weatherTrendFill)" />
                                <path d={trendPath} fill="none" stroke={metricConfig.stroke} strokeOpacity="0.35" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
                                <path d={trendPath} fill="none" stroke="url(#weatherTrendStroke)" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" />
                                {graphPoints.map((p, idx) => (
                                    <g key={`pt-${idx}`}>
                                        {(hoveredPoint === idx || idx === selectedDayIndex % Math.max(1, graphPoints.length)) && (
                                            <circle
                                                cx={p.x}
                                                cy={p.y}
                                                r={6.5}
                                                fill={metricConfig.stroke}
                                                opacity="0.2"
                                            />
                                        )}
                                        <circle
                                            cx={p.x}
                                            cy={p.y}
                                            r={hoveredPoint === idx ? 3.5 : 2.2}
                                            fill={metricConfig.stroke}
                                            opacity={hoveredPoint === null || hoveredPoint === idx ? 1 : 0.72}
                                            onMouseEnter={() => setHoveredPoint(idx)}
                                            onMouseLeave={() => setHoveredPoint(null)}
                                        />
                                    </g>
                                ))}
                            </svg>
                            <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.max(1, chartSeries.length)}, minmax(0, 1fr))`, gap: '4px', marginTop: '5px' }}>
                                {chartSeries.map((p, idx) => (
                                    <div
                                        key={`lbl-${idx}`}
                                        style={{ fontSize: '8px', color: hoveredPoint === idx ? 'var(--text-primary)' : 'var(--text-muted)', textAlign: 'center', letterSpacing: '0.01em' }}
                                        title={`${p.label}: ${metricValueFmt(normalizeNumeric(p[metricConfig.key]))}`}
                                    >
                                        {p.label}
                                    </div>
                                ))}
                            </div>
                            {hoveredPoint !== null && graphPoints[hoveredPoint] && (
                                <div style={{ marginTop: '6px', fontSize: '10px', color: 'var(--text-primary)' }}>
                                    <strong>{graphPoints[hoveredPoint].label}</strong>: {metricValueFmt(graphPoints[hoveredPoint].value)}
                                </div>
                            )}
                        </div>
                    )}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '8px', marginTop: '10px' }}>
                    <div style={{ border: '1px solid var(--card-border)', borderRadius: '10px', padding: '8px', background: 'rgba(255,255,255,0.03)' }}>
                        <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}><Thermometer size={10} style={{ marginRight: '4px', verticalAlign: 'text-top' }} />Temp</div>
                        <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--text-primary)' }}>{fmtTemp(currentTemp)}</div>
                    </div>
                    <div style={{ border: '1px solid var(--card-border)', borderRadius: '10px', padding: '8px', background: 'rgba(255,255,255,0.03)' }}>
                        <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}><Droplets size={10} style={{ marginRight: '4px', verticalAlign: 'text-top' }} />Humidity</div>
                        <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--text-primary)' }}>{fmtPct(currentHumidity)}</div>
                    </div>
                    <div style={{ border: '1px solid var(--card-border)', borderRadius: '10px', padding: '8px', background: 'rgba(255,255,255,0.03)' }}>
                        <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}><Wind size={10} style={{ marginRight: '4px', verticalAlign: 'text-top' }} />Wind</div>
                        <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--text-primary)' }}>{fmtWind(currentWind)}</div>
                    </div>
                </div>

                {showDetails && forecast.length > 0 && (
                    <div style={{ marginTop: '10px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(96px, 1fr))', gap: '8px' }}>
                        {days.slice(0, 7).map((day, idx) => {
                            const info = weatherIconForDescription(day?.description || current?.description);
                            const DayIcon = info.icon;
                            const isActive = idx === selectedDayIndex;
                            return (
                                <div
                                    key={`${day?.date || 'day'}-${idx}-${day?.label || ''}`}
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => setSelectedDayIndex(idx)}
                                    onKeyDown={(event) => {
                                        if (event.key === 'Enter' || event.key === ' ') {
                                            event.preventDefault();
                                            setSelectedDayIndex(idx);
                                        }
                                    }}
                                    style={{
                                        border: '1px solid var(--card-border)',
                                        borderRadius: '10px',
                                        padding: '8px',
                                        cursor: 'pointer',
                                        background: isActive ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.02)',
                                        boxShadow: isActive ? 'inset 0 1px 0 rgba(255,255,255,0.09)' : 'none',
                                    }}
                                >
                                    <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{day?.label || shortDayLabel(day?.date)}</div>
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                        <DayIcon size={14} color={info.color} />
                                        <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{fmtPct(day?.pop ?? 0)}</span>
                                    </div>
                                    <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', marginTop: '4px' }}>{fmtTemp(day?.tempMax)}</div>
                                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{fmtTemp(day?.tempMin)}</div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
});

export const SystemHealthAssistCard = memo(({ data, isStage = false }) => {
    const [showDetails, setShowDetails] = useState(true);
    const cpu = normalizeNumeric(data?.cpu_usage_percent) ?? 0;
    const mem = normalizeNumeric(data?.memory_percent) ?? 0;
    const disk = normalizeNumeric(data?.disk_percent) ?? 0;
    const net = normalizeNumeric(data?.network_percent) ?? 0;
    const rx = normalizeNumeric(data?.network_rx_kbps) ?? 0;
    const tx = normalizeNumeric(data?.network_tx_kbps) ?? 0;
    const loadAvg = formatLoadAvg(data?.load_avg);
    const temperature = normalizeNumeric(data?.temperature_c);
    const pressure = Math.max(cpu, mem, disk, net);
    const healthState = pressure >= 85 ? 'Critical' : pressure >= 65 ? 'Attention' : 'Healthy';
    const healthStateColor = pressure >= 85 ? '#f87171' : pressure >= 65 ? '#fbbf24' : '#34d399';
    const rows = [
        { label: 'CPU', value: cpu, icon: Cpu },
        { label: 'RAM', value: mem, icon: MemoryStick },
        { label: 'Disk', value: disk, icon: HardDrive },
        { label: 'Net', value: net, icon: Wifi },
    ];
    const top = Array.isArray(data?.top_processes) ? data.top_processes : [];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', width: '100%' }}>
            <div style={{
                border: isStage ? '1px solid rgba(var(--accent-rgb), 0.2)' : '1px solid var(--card-border)',
                borderRadius: '12px',
                padding: isStage ? '20px' : '10px',
                background: isStage
                    ? 'radial-gradient(circle at 100% 0%, rgba(var(--accent-rgb), 0.1), transparent 60%)'
                    : 'radial-gradient(circle at 100% 0%, rgba(16,185,129,0.14), transparent 40%), linear-gradient(120deg, rgba(15,23,42,0.35), rgba(16,185,129,0.09) 42%, rgba(59,130,246,0.07))',
                boxShadow: isStage ? 'none' : 'inset 0 1px 0 rgba(255,255,255,0.04)',
                backdropFilter: isStage ? 'blur(10px)' : 'none'
            }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', marginBottom: '10px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                        <div
                            style={{
                                width: '34px',
                                height: '34px',
                                borderRadius: '10px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                border: '1px solid rgba(255,255,255,0.12)',
                                background: 'linear-gradient(160deg, rgba(16,185,129,0.22), rgba(59,130,246,0.1))',
                            }}
                        >
                            <Server size={16} color="var(--text-primary)" />
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                            <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>System Health</span>
                            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Host status overview</span>
                        </div>
                    </div>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '10px', color: healthStateColor, border: `1px solid ${healthStateColor}55`, borderRadius: '999px', padding: '2px 7px', background: `${healthStateColor}12`, fontWeight: 700 }}>{healthState}</span>
                        <span style={{ fontSize: '10px', color: 'var(--text-primary)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '2px 7px', background: 'rgba(255,255,255,0.03)' }}>
                            <Clock3 size={10} style={{ marginRight: '4px', verticalAlign: 'text-top' }} />
                            {String(data?.uptime || '--')}
                        </span>
                        <span style={{ fontSize: '10px', color: 'var(--text-primary)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '2px 7px', background: 'rgba(255,255,255,0.03)' }}>
                            <Activity size={10} style={{ marginRight: '4px', verticalAlign: 'text-top' }} />
                            Load {loadAvg}
                        </span>
                        {temperature !== null && (
                            <span style={{ fontSize: '10px', color: '#facc15', border: '1px solid rgba(250,204,21,0.35)', borderRadius: '999px', padding: '2px 7px', background: 'rgba(250,204,21,0.08)' }}>{temperature.toFixed(1)}°C</span>
                        )}
                        <button
                            type="button"
                            onClick={() => setShowDetails((prev) => !prev)}
                            style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-primary)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '4px 10px', background: 'rgba(255,255,255,0.03)', cursor: 'pointer' }}
                        >
                            {showDetails ? 'Hide details' : 'Show details'}
                        </button>
                    </div>
                </div>

                <div style={{ display: 'grid', gap: '8px', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', marginBottom: showDetails ? '10px' : '0' }}>
                    {rows.map((row) => {
                        const Icon = row.icon;
                        return (
                            <div key={`summary-${row.label}`} style={{ border: '1px solid var(--card-border)', borderRadius: '10px', padding: '8px 9px', background: 'rgba(255,255,255,0.04)' }}>
                                <div style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '5px' }}>
                                    <Icon size={10} />
                                    {row.label}
                                </div>
                                <div style={{ fontSize: '16px', fontWeight: 800, color: pctColor(row.value), marginTop: '2px' }}>{row.value.toFixed(0)}%</div>
                                <div style={{ marginTop: '6px', height: '6px', borderRadius: '999px', background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
                                    <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, row.value))}%`, background: pctGradient(row.value), transition: 'width 180ms ease' }} />
                                </div>
                            </div>
                        );
                    })}
                </div>

                {showDetails && (
                    <>
                        <div style={{ display: 'grid', gap: '8px' }}>
                            {rows.map((row) => (
                                <div key={row.label}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{row.label}</span>
                                        <span style={{ fontSize: '10px', color: pctColor(row.value), fontWeight: 700 }}>{row.value.toFixed(0)}%</span>
                                    </div>
                                    <div style={{ height: '7px', borderRadius: '999px', background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
                                        <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, row.value))}%`, background: pctGradient(row.value), transition: 'width 180ms ease', boxShadow: '0 0 10px rgba(255,255,255,0.16)' }} />
                                    </div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '3px', fontSize: '9px', color: 'var(--text-muted)' }}>
                                        <span>0</span>
                                        <span>50</span>
                                        <span>100</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div style={{ marginTop: '8px', display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '8px', padding: '7px 8px', background: 'rgba(255,255,255,0.03)' }}>
                                Memory Free: <strong style={{ color: 'var(--text-primary)' }}>{bytesToHuman(data?.memory_available)}</strong>
                            </div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '8px', padding: '7px 8px', background: 'rgba(255,255,255,0.03)' }}>
                                Disk Free: <strong style={{ color: 'var(--text-primary)' }}>{bytesToHuman(data?.disk_free)}</strong>
                            </div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '8px', padding: '7px 8px', background: 'rgba(255,255,255,0.03)' }}>
                                RX: <strong style={{ color: 'var(--text-primary)' }}>{kbpsToHuman(rx)}</strong>
                            </div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '8px', padding: '7px 8px', background: 'rgba(255,255,255,0.03)' }}>
                                TX: <strong style={{ color: 'var(--text-primary)' }}>{kbpsToHuman(tx)}</strong>
                            </div>
                        </div>
                    </>
                )}
            </div>

            {showDetails && (
                <div style={{ border: '1px solid var(--card-border)', borderRadius: '10px', overflow: 'hidden' }}>
                    <div style={{ padding: '8px 10px', fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', background: 'rgba(255,255,255,0.02)' }}>
                        Top Processes
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: '8px', alignItems: 'center', padding: '6px 10px', fontSize: '9px', color: 'var(--text-muted)', borderTop: '1px solid var(--card-border)' }}>
                        <span>Name</span>
                        <span>CPU</span>
                        <span>MEM</span>
                    </div>
                    {top.length === 0 && (
                        <div style={{ padding: '10px', fontSize: '11px', color: 'var(--text-muted)' }}>
                            No process data available.
                        </div>
                    )}
                    {top.slice(0, 5).map((proc, idx) => (
                        <div key={`${proc?.pid || idx}-${idx}`} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: '8px', alignItems: 'center', padding: '7px 10px', borderTop: '1px solid var(--card-border)' }}>
                            <span style={{ fontSize: '11px', color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {String(proc?.name || 'process')} <span style={{ color: 'var(--text-muted)' }}>#{String(proc?.pid || '--')}</span>
                            </span>
                            <span style={{ fontSize: '11px', color: pctColor(proc?.cpu_percent), fontWeight: 700 }}>{(normalizeNumeric(proc?.cpu_percent) || 0).toFixed(1)}%</span>
                            <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 700 }}>{(normalizeNumeric(proc?.memory_percent) || 0).toFixed(1)}%</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
});

export const DataChartAssistCard = memo(({ chart, isStage = false }) => {
    const [mode, setMode] = useState('line');
    const points = Array.isArray(chart?.points) ? chart.points : [];
    if (points.length < 2) return null;

    const values = points.map((p) => normalizeNumeric(p.value)).filter((v) => v !== null);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const avg = values.reduce((a, b) => a + b, 0) / Math.max(1, values.length);
    const width = 420;
    const height = 120;
    const padX = 12;
    const padY = 10;
    const innerW = width - (padX * 2);

    const normalized = points.map((p, idx) => {
        const x = padX + ((innerW * idx) / Math.max(1, points.length - 1));
        const n = normalizeNumeric(p.value) || 0;
        const span = Math.max(1e-9, max - min);
        const y = padY + ((height - (padY * 2)) - (((n - min) / span) * (height - (padY * 2))));
        return { ...p, x, y, valueNum: n };
    });

    const linePath = buildLinePath(normalized.map((p) => p.valueNum), width, height, padX, padY);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                <div>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>{chart?.title || 'Data Analysis'}</div>
                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{chart?.xLabel || 'X'} vs {chart?.yLabel || 'Y'}</div>
                </div>
                <div style={{ display: 'flex', gap: '6px' }}>
                    {['line', 'bar'].map((option) => (
                        <button
                            key={option}
                            type="button"
                            onClick={() => setMode(option)}
                            style={{
                                fontSize: '9px',
                                fontWeight: 700,
                                borderRadius: '999px',
                                padding: '3px 8px',
                                border: mode === option ? '1px solid rgba(59,130,246,0.45)' : '1px solid var(--card-border)',
                                background: mode === option ? 'rgba(59,130,246,0.12)' : 'transparent',
                                color: mode === option ? 'var(--text-primary)' : 'var(--text-muted)',
                                cursor: 'pointer',
                            }}
                        >
                            {option === 'line' ? 'Line' : 'Bar'}
                        </button>
                    ))}
                </div>
            </div>

            <div style={{
                border: isStage ? '1px solid rgba(var(--accent-rgb), 0.2)' : '1px solid var(--card-border)',
                borderRadius: '10px',
                padding: isStage ? '16px' : '8px 10px',
                background: isStage
                    ? 'radial-gradient(circle at 0% 0%, rgba(var(--accent-rgb), 0.1), transparent 60%)'
                    : 'radial-gradient(circle at 0% 0%, rgba(96,165,250,0.14), transparent 45%), linear-gradient(120deg, rgba(30,41,59,0.24), rgba(59,130,246,0.12))',
                boxShadow: isStage ? 'none' : 'inset 0 1px 0 rgba(255,255,255,0.05)',
                backdropFilter: isStage ? 'blur(10px)' : 'none'
            }}>
                <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: '100%', height: '92px', display: 'block' }}>
                    <defs>
                        <linearGradient id="dataChartFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#60a5fa" stopOpacity="0.35" />
                            <stop offset="100%" stopColor="#60a5fa" stopOpacity="0.03" />
                        </linearGradient>
                    </defs>
                    {mode === 'line' ? (
                        <>
                            <path d={`${linePath} L${(width - padX).toFixed(2)} ${(height - padY).toFixed(2)} L${padX.toFixed(2)} ${(height - padY).toFixed(2)} Z`} fill="url(#dataChartFill)" />
                            <path d={linePath} fill="none" stroke="#60a5fa" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                        </>
                    ) : (
                        normalized.map((p, idx) => {
                            const barW = innerW / Math.max(3, normalized.length * 1.35);
                            const h = Math.max(2, (height - padY) - p.y);
                            return (
                                <rect
                                    key={idx}
                                    x={Math.max(padX, p.x - (barW / 2))}
                                    y={p.y}
                                    width={barW}
                                    height={h}
                                    rx="2"
                                    fill="rgba(96,165,250,0.85)"
                                />
                            );
                        })
                    )}
                </svg>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '6px' }}>
                <div style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '6px 8px' }}>
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>Min</div>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>{min.toFixed(2)}</div>
                </div>
                <div style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '6px 8px' }}>
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>Avg</div>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>{avg.toFixed(2)}</div>
                </div>
                <div style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '6px 8px' }}>
                    <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>Max</div>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>{max.toFixed(2)}</div>
                </div>
            </div>
        </div>
    );
});

export const WikiAssistCard = memo(({ data, isStage = false }) => {
    const title = String(data?.title || 'Wikipedia');
    const query = String(data?.query || '').trim();
    const summary = String(data?.summary || '').trim();
    const sourceUrl = String(data?.sourceUrl || '').trim();
    const language = String(data?.language || '').trim();

    if (!title && !summary && !sourceUrl) return null;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div
                style={{
                    border: isStage ? '1px solid rgba(var(--accent-rgb), 0.2)' : '1px solid var(--card-border)',
                    borderRadius: '12px',
                    padding: isStage ? '20px' : '10px',
                    background: isStage
                        ? 'radial-gradient(circle at 0% 0%, rgba(var(--accent-rgb), 0.1), transparent 60%)'
                        : 'radial-gradient(circle at 0% 0%, rgba(148,163,184,0.14), transparent 45%), linear-gradient(120deg, rgba(30,41,59,0.24), rgba(71,85,105,0.12))',
                    boxShadow: isStage ? 'none' : 'inset 0 1px 0 rgba(255,255,255,0.05)',
                    backdropFilter: isStage ? 'blur(10px)' : 'none',
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <BookOpen size={16} color="#cbd5e1" />
                        <div>
                            <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-primary)' }}>{title}</div>
                            <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
                                {query ? `Query: ${query}` : 'Wikipedia summary'}
                                {language ? ` · ${language.toUpperCase()}` : ''}
                            </div>
                        </div>
                    </div>
                    {sourceUrl && (
                        <a
                            href={sourceUrl}
                            target="_blank"
                            rel="noreferrer"
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '5px',
                                fontSize: '10px',
                                fontWeight: 700,
                                color: 'var(--text-primary)',
                                textDecoration: 'none',
                                border: '1px solid var(--card-border)',
                                borderRadius: '999px',
                                padding: '4px 8px',
                                background: 'rgba(255,255,255,0.03)',
                            }}
                        >
                            Open source <ExternalLink size={11} />
                        </a>
                    )}
                </div>

                {summary && (
                    <div style={{ marginTop: '9px', fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.45 }}>
                        {summary}
                    </div>
                )}
            </div>
        </div>
    );
});

export const MapAssistCard = memo(({ data, isStage = false }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const title = String(data?.title || 'Map');
    const description = String(data?.description || '').trim();
    const sourceUrl = String(data?.sourceUrl || '').trim();
    const embedUrl = String(data?.embedUrl || '').trim();
    const provider = String(data?.provider || 'Maps').trim();

    if (!sourceUrl && !title) return null;

    return (
        <div style={{
            padding: isStage ? '20px' : '10px',
            background: isStage ? 'rgba(var(--accent-rgb), 0.05)' : 'var(--card-bg)',
            border: isStage ? '1px solid rgba(var(--accent-rgb), 0.2)' : '1px solid var(--card-border)',
            borderRadius: '12px',
            width: '100%',
            height: isStage ? '100%' : 'auto',
            display: 'flex',
            flexDirection: 'column',
            backdropFilter: isStage ? 'blur(10px)' : 'none'
        }}>
            <div style={{ display: 'flex', flex: isStage ? 1 : 'unset', flexDirection: 'column' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'rgba(52, 211, 153, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <MapPin size={18} color="#34d399" />
                        </div>
                        <div style={{ minWidth: 0 }}>
                            <p style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {title || 'Map'}
                            </p>
                            <p style={{ fontSize: '10px', color: 'var(--text-muted)', margin: 0 }}>
                                {provider}
                            </p>
                        </div>
                    </div>
                    {!isStage && embedUrl && (
                        <div style={{ display: 'flex', gap: '6px' }}>
                            <button
                                type="button"
                                onClick={() => setIsExpanded(true)}
                                style={{ padding: '6px', borderRadius: '8px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.03)', color: 'var(--text-primary)', cursor: 'pointer' }}
                                title="Expand"
                            >
                                <Maximize2 size={14} />
                            </button>
                            {sourceUrl && (
                                <a
                                    href={sourceUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                    style={{ padding: '6px', borderRadius: '8px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.03)', color: 'var(--text-primary)', display: 'flex' }}
                                    title="Open Source"
                                >
                                    <ExternalLink size={14} />
                                </a>
                            )}
                        </div>
                    )}
                </div>
                {description && (
                    <div style={{ marginTop: '9px', fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.45 }}>
                        {description}
                    </div>
                )}
                {embedUrl && (
                    <div style={{
                        marginTop: '9px',
                        border: '1px solid var(--card-border)',
                        borderRadius: '6px',
                        overflow: 'hidden',
                        background: 'rgba(2,6,23,0.35)',
                        flex: isStage ? 1 : 'unset'
                    }}>
                        <iframe
                            title={`map-${title}`}
                            src={embedUrl}
                            allowFullScreen
                            loading="lazy"
                            referrerPolicy="no-referrer-when-downgrade"
                            style={{ width: '100%', height: isStage ? '100%' : '260px', border: '0', display: 'block' }}
                        />
                    </div>
                )}
            </div>
            {isExpanded && embedUrl && createPortal(
                <div
                    style={{
                        position: 'fixed',
                        inset: 0,
                        zIndex: 1600,
                        background: 'rgba(0,0,0,0.72)',
                        backdropFilter: 'blur(2px)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        padding: '20px',
                    }}
                    onClick={() => setIsExpanded(false)}
                >
                    <div
                        style={{
                            width: 'min(1220px, 100%)',
                            height: 'min(86vh, 900px)',
                            border: '1px solid var(--card-border)',
                            borderRadius: '12px',
                            overflow: 'hidden',
                            background: 'rgba(2,6,18,0.98)',
                            display: 'flex',
                            flexDirection: 'column',
                        }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', padding: '10px 12px', borderBottom: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.03)' }}>
                            <div style={{ minWidth: 0 }}>
                                <p style={{ fontSize: '12px', color: 'var(--text-primary)', fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {title || 'Map'}
                                </p>
                                <p style={{ fontSize: '10px', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {provider}
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={() => setIsExpanded(false)}
                                style={{ padding: '6px', borderRadius: '8px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.03)', color: 'var(--text-primary)', cursor: 'pointer' }}
                                title="Close"
                            >
                                <X size={14} />
                            </button>
                        </div>
                        <iframe
                            title={`map-expanded-${title}`}
                            src={embedUrl}
                            allowFullScreen
                            loading="lazy"
                            referrerPolicy="no-referrer-when-downgrade"
                            style={{ width: '100%', flex: 1, border: 0, display: 'block' }}
                        />
                    </div>
                </div>,
                document.body,
            )}
        </div>
    );
});

export const YouTubeAssistCard = memo(({ data, isStage = false }) => {
    const title = String(data?.title || 'YouTube Video');
    const description = String(data?.description || '').trim();
    const sourceUrl = String(data?.sourceUrl || '').trim();
    const channel = String(data?.channel || '').trim();

    if (!sourceUrl && !title) return null;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', width: '100%' }}>
            <div
                style={{
                    border: isStage ? '1px solid rgba(var(--accent-rgb), 0.2)' : '1px solid var(--card-border)',
                    borderRadius: '12px',
                    padding: isStage ? '20px' : '10px',
                    background: isStage
                        ? 'radial-gradient(circle at 0% 0%, rgba(239, 68, 68, 0.1), transparent 60%)'
                        : 'radial-gradient(circle at 0% 0%, rgba(239,68,68,0.16), transparent 45%), linear-gradient(120deg, rgba(127,29,29,0.24), rgba(239,68,68,0.12))',
                    boxShadow: isStage ? 'none' : 'inset 0 1px 0 rgba(255,255,255,0.05)',
                    backdropFilter: isStage ? 'blur(10px)' : 'none',
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <PlayCircle size={16} color="#f87171" />
                        <div>
                            <div style={{ fontSize: '11px', fontWeight: 800, color: 'var(--text-primary)' }}>{title}</div>
                            <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
                                YouTube{channel ? ` · ${channel}` : ''}
                            </div>
                        </div>
                    </div>
                    {sourceUrl && (
                        <a
                            href={sourceUrl}
                            target="_blank"
                            rel="noreferrer"
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '5px',
                                fontSize: '10px',
                                fontWeight: 700,
                                color: 'var(--text-primary)',
                                textDecoration: 'none',
                                border: '1px solid var(--card-border)',
                                borderRadius: '999px',
                                padding: '4px 8px',
                                background: 'rgba(255,255,255,0.03)',
                            }}
                        >
                            Open video <ExternalLink size={11} />
                        </a>
                    )}
                </div>
                {description && (
                    <div style={{ marginTop: '9px', fontSize: '11px', color: 'var(--text-primary)', lineHeight: 1.45 }}>
                        {description}
                    </div>
                )}
            </div>
        </div>
    );
});
