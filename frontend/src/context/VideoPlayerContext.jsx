import { createContext, useContext, useState, useCallback } from 'react';

const VideoPlayerContext = createContext(null);

export function VideoPlayerProvider({ children }) {
    // activeVideoId: the videoId currently playing inline (only 1 at a time)
    const [activeVideoId, setActiveVideoId] = useState(null);
    // fullscreen modal state
    const [fullscreenVideo, setFullscreenVideo] = useState(null); // { videoId, title }

    const playVideo = useCallback((videoId) => {
        setActiveVideoId(videoId);
    }, []);

    const stopVideo = useCallback((videoId) => {
        setActiveVideoId(prev => prev === videoId ? null : prev);
    }, []);

    const openFullscreen = useCallback((videoId, title = '') => {
        setFullscreenVideo({ videoId, title });
    }, []);

    const closeFullscreen = useCallback(() => {
        setFullscreenVideo(null);
    }, []);

    return (
        <VideoPlayerContext.Provider value={{
            activeVideoId,
            fullscreenVideo,
            playVideo,
            stopVideo,
            openFullscreen,
            closeFullscreen,
        }}>
            {children}
        </VideoPlayerContext.Provider>
    );
}

export function useVideoPlayer() {
    const ctx = useContext(VideoPlayerContext);
    if (!ctx) throw new Error('useVideoPlayer must be used within VideoPlayerProvider');
    return ctx;
}
