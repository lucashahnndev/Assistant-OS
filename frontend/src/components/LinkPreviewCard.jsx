import { useState, useEffect, memo } from 'react';
import { ExternalLink, Play, Globe, Link as LinkIcon, Maximize2, Minimize2, X } from 'lucide-react';
import { api } from '../hooks/api';
import { useVideoPlayer } from '../context/VideoPlayerContext';

// ── URL extraction ──────────────────────────────────────────────────────
const URL_RE = /https?:\/\/[^\s<>)"'\]]+/gi;

const YOUTUBE_RE =
    /(?:youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|shorts\/)|youtu\.be\/|\[RESOURCE\]\?v=)([\w-]{11})/i;

function extractUrls(text) {
    if (!text || typeof text !== 'string') return [];
    return [...new Set((text.match(URL_RE) || []))];
}

function extractYouTubeId(url) {
    const m = url.match(YOUTUBE_RE);
    return m ? m[1] : null;
}

// ── YouTube Inline Player ───────────────────────────────────────────────
const YouTubeInlinePlayer = memo(({ videoId, isStage }) => {
    const { openFullscreen, stopVideo } = useVideoPlayer();
    const embedUrl = `https://www.youtube-nocookie.com/embed/${videoId}?rel=0&modestbranding=1`;
    const ytUrl = `https://www.youtube.com/watch?v=${videoId}`;

    return (
        <div className={`yt-inline-player ${isStage ? 'is-stage' : ''}`}>
            <div className="yt-inline-header">
                <span className="yt-inline-label">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
                        <path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19.13C5.12 19.56 12 19.56 12 19.56s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.43z" fill="#FF0000" />
                        <polygon points="9.75,15.02 15.5,11.75 9.75,8.48" fill="white" />
                    </svg>
                    YouTube
                </span>
                <div style={{ display: 'flex', gap: '2px' }}>
                    <a
                        href={ytUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="vp-btn-sm"
                        title="Open in YouTube"
                        onClick={e => e.stopPropagation()}
                    >
                        <ExternalLink size={12} />
                    </a>
                    <button
                        className="vp-btn-sm"
                        onClick={() => openFullscreen(videoId, '')}
                        title="Fullscreen"
                    >
                        <Maximize2 size={12} />
                    </button>
                    <button
                        className="vp-btn-sm"
                        onClick={() => stopVideo(videoId)}
                        title="Minimize"
                    >
                        <Minimize2 size={12} />
                    </button>
                </div>
            </div>
            <div className="yt-inline-body">
                <iframe
                    src={embedUrl}
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
                    allowFullScreen
                    title="YouTube video"
                    className="yt-inline-iframe"
                />
            </div>
        </div>
    );
});

// ── YouTube Preview Card (thumbnail + play button) ──────────────────────
const YouTubePreviewCard = memo(({ videoId, isStage }) => {
    const { playVideo, activeVideoId } = useVideoPlayer();
    const thumbUrl = `https://img.youtube.com/vi/${videoId}/mqdefault.jpg`;

    // Dashboard Stage optimization: Always auto-play the video if in stage mode
    useEffect(() => {
        if (isStage && activeVideoId !== videoId) {
            playVideo(videoId);
        }
    }, [isStage, videoId, activeVideoId, playVideo]);

    // If THIS video is the active one, render the inline player instead
    if (activeVideoId === videoId || isStage) {
        return <YouTubeInlinePlayer videoId={videoId} isStage={isStage} />;
    }

    return (
        <div
            className="link-preview-card yt-preview-card"
            onClick={() => playVideo(videoId)}
            role="button"
            tabIndex={0}
            onKeyDown={e => e.key === 'Enter' && playVideo(videoId)}
        >
            <div className="yt-thumb-wrapper">
                <img src={thumbUrl} alt="Video thumbnail" className="yt-thumb" loading="lazy" />
                <div className="yt-play-overlay">
                    <Play size={28} fill="white" color="white" />
                </div>
            </div>
            <div className="link-preview-info">
                <span className="link-preview-domain">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
                        <path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19.13C5.12 19.56 12 19.56 12 19.56s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.43z" fill="#FF0000" />
                        <polygon points="9.75,15.02 15.5,11.75 9.75,8.48" fill="white" />
                    </svg>
                    youtube.com
                </span>
                <span className="link-preview-title" style={{ fontSize: '12px' }}>Click to play video</span>
            </div>
        </div>
    );
});

// ── Generic Link Preview Card ───────────────────────────────────────────
const GenericPreviewCard = memo(({ url, isStage }) => {
    const [state, setState] = useState('loading'); // loading | ready | error
    const [data, setData] = useState(null);

    useEffect(() => {
        let cancelled = false;
        setState('loading');

        api.post('/link-preview', { url })
            .then(res => {
                if (!cancelled) {
                    setData(res);
                    setState('ready');
                }
            })
            .catch(() => {
                if (!cancelled) setState('error');
            });

        return () => { cancelled = true; };
    }, [url]);

    if (state === 'loading') {
        return (
            <div className="link-preview-card link-preview-skeleton">
                <div className="skeleton-line" style={{ width: '60%', height: '12px' }} />
                <div className="skeleton-line" style={{ width: '40%', height: '10px', marginTop: '6px' }} />
                <div className="skeleton-line" style={{ width: '80%', height: '10px', marginTop: '4px' }} />
            </div>
        );
    }

    if (state === 'error' || !data) {
        const domain = (() => { try { return new URL(url).hostname; } catch { return url; } })();
        return (
            <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="link-preview-card link-preview-fallback"
                style={{ width: '420px', maxWidth: '100%', alignItems: 'center' }}
            >
                <img
                    src={`/api/favicon?url=${encodeURIComponent(url)}`}
                    alt=""
                    style={{ width: '16px', height: '16px', flexShrink: 0, borderRadius: '4px' }}
                    onError={(e) => { e.currentTarget.style.display = 'none'; }}
                />
                <span className="link-preview-domain" style={{ fontSize: '11px', fontWeight: '800', opacity: 0.8 }}>{domain}</span>
            </a>
        );
    }

    return (
        <a
            href={data.url || url}
            target="_blank"
            rel="noopener noreferrer"
            className={`link-preview-card ${isStage ? 'is-stage' : ''}`}
        >
            {data.image && (
                <img src={data.image} alt="" className="link-preview-thumb" loading="lazy" />
            )}
            <div className="link-preview-info">
                <span className="link-preview-domain">
                    <img
                        src={`/api/favicon?url=${encodeURIComponent(data.url || url)}`}
                        alt=""
                        style={{ width: '12px', height: '12px', marginRight: '4px', flexShrink: 0, borderRadius: '2px' }}
                        onError={(e) => { e.currentTarget.style.display = 'none'; }}
                    />
                    {data.domain}
                </span>
                {data.title && <span className="link-preview-title">{data.title}</span>}
                {data.description && <span className="link-preview-desc">{data.description}</span>}
            </div>
        </a>
    );
});

// ── Main Component ──────────────────────────────────────────────────────
const LinkPreviewCard = memo(({ messageContent, isStage }) => {
    const urls = extractUrls(messageContent);
    if (urls.length === 0) return null;

    const firstUrl = urls[0];
    const extraCount = urls.length - 1;
    const ytId = extractYouTubeId(firstUrl);

    return (
        <div className={`link-preview-wrapper ${isStage ? 'is-stage' : ''}`}>
            {ytId ? (
                <YouTubePreviewCard videoId={ytId} isStage={isStage} />
            ) : (
                <GenericPreviewCard url={firstUrl} isStage={isStage} />
            )}
            {extraCount > 0 && (
                <span className="link-preview-more">
                    <LinkIcon size={11} />
                    +{extraCount} more link{extraCount > 1 ? 's' : ''}
                </span>
            )}
        </div>
    );
});

export default LinkPreviewCard;
