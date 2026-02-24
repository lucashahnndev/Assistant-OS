import { X, Minimize2, ExternalLink } from 'lucide-react';
import { useVideoPlayer } from '../context/VideoPlayerContext';

/**
 * VideoPlayerDock — now ONLY renders the fullscreen modal overlay.
 * The inline player lives inside LinkPreviewCard / message bubbles.
 */
export default function VideoPlayerDock() {
    const { fullscreenVideo, closeFullscreen } = useVideoPlayer();

    if (!fullscreenVideo) return null;

    const { videoId, title } = fullscreenVideo;
    const embedUrl = `https://www.youtube-nocookie.com/embed/${videoId}?rel=0&modestbranding=1&autoplay=1`;
    const ytUrl = `https://www.youtube.com/watch?v=${videoId}`;

    return (
        <div className="video-player-modal-overlay" onClick={closeFullscreen}>
            <div className="video-player-modal" onClick={e => e.stopPropagation()}>
                <div className="video-player-modal-header">
                    <span className="video-player-modal-title">{title || 'YouTube Video'}</span>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        <a
                            href={ytUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="vp-btn"
                            title="Open in YouTube"
                        >
                            <ExternalLink size={14} />
                        </a>
                        <button className="vp-btn" onClick={closeFullscreen} title="Close">
                            <X size={14} />
                        </button>
                    </div>
                </div>
                <div className="video-player-modal-body">
                    <iframe
                        src={embedUrl}
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
                        allowFullScreen
                        title="YouTube video"
                        style={{ width: '100%', height: '100%', border: 'none', borderRadius: '0 0 var(--radius-md) var(--radius-md)' }}
                    />
                </div>
            </div>
        </div>
    );
}
