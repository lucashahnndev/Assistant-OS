import React, { useEffect, useState } from 'react';
import { CheckCircle, XCircle, AlertTriangle, Info, Loader } from 'lucide-react';

const VARIANTS = {
    success: {
        icon: CheckCircle,
        color: '#10b981',
        bg: 'rgba(16, 185, 129, 0.08)',
        border: 'rgba(16, 185, 129, 0.2)',
        glow: 'rgba(16, 185, 129, 0.12)',
    },
    error: {
        icon: XCircle,
        color: '#ef4444',
        bg: 'rgba(239, 68, 68, 0.08)',
        border: 'rgba(239, 68, 68, 0.2)',
        glow: 'rgba(239, 68, 68, 0.12)',
    },
    warning: {
        icon: AlertTriangle,
        color: '#f59e0b',
        bg: 'rgba(245, 158, 11, 0.08)',
        border: 'rgba(245, 158, 11, 0.2)',
        glow: 'rgba(245, 158, 11, 0.12)',
    },
    info: {
        icon: Info,
        color: '#3b82f6',
        bg: 'rgba(59, 130, 246, 0.08)',
        border: 'rgba(59, 130, 246, 0.2)',
        glow: 'rgba(59, 130, 246, 0.12)',
    },
    loading: {
        icon: Loader,
        color: '#a78bfa',
        bg: 'rgba(167, 139, 250, 0.08)',
        border: 'rgba(167, 139, 250, 0.2)',
        glow: 'rgba(167, 139, 250, 0.12)',
    },
};

const ProgressBar = ({ duration, color, paused }) => {
    const [width, setWidth] = useState(100);

    useEffect(() => {
        if (paused || !duration) return;
        const start = Date.now();
        const interval = setInterval(() => {
            const elapsed = Date.now() - start;
            const remaining = Math.max(0, 100 - (elapsed / duration) * 100);
            setWidth(remaining);
            if (remaining === 0) clearInterval(interval);
        }, 16);
        return () => clearInterval(interval);
    }, [duration, paused]);

    if (!duration) return null;
    return (
        <div style={{
            position: 'absolute',
            bottom: 0, left: 0, right: 0,
            height: '2px',
            background: 'rgba(255,255,255,0.04)',
            borderRadius: '0 0 10px 10px',
            overflow: 'hidden',
        }}>
            <div style={{
                height: '100%',
                width: `${width}%`,
                background: color,
                transition: 'width 0.1s linear',
                boxShadow: `0 0 6px ${color}`,
            }} />
        </div>
    );
};

const SpinnerIcon = ({ color }) => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" style={{ animation: 'atlas-toast-spin 0.8s linear infinite', flexShrink: 0 }}>
        <circle cx="9" cy="9" r="7" stroke={color} strokeOpacity="0.2" strokeWidth="2" />
        <path d="M9 2a7 7 0 0 1 7 7" stroke={color} strokeWidth="2" strokeLinecap="round" />
    </svg>
);

/**
 * AtlasToast — use via the notify util, not directly.
 * Props: type, title, message, duration, t (react-hot-toast object)
 */
export const AtlasToast = ({ t, type = 'info', title, message, duration }) => {
    const v = VARIANTS[type] || VARIANTS.info;
    const IconComp = v.icon;
    const isLoading = type === 'loading';
    const isVisible = t?.visible !== false;

    return (
        <>
            <style>{`
                @keyframes atlas-toast-in {
                    from { opacity: 0; transform: translateX(16px) scale(0.97); }
                    to   { opacity: 1; transform: translateX(0) scale(1); }
                }
                @keyframes atlas-toast-out {
                    from { opacity: 1; transform: translateX(0) scale(1); }
                    to   { opacity: 0; transform: translateX(16px) scale(0.95); }
                }
                @keyframes atlas-toast-spin {
                    from { transform: rotate(0deg); }
                    to   { transform: rotate(360deg); }
                }
            `}</style>
            <div
                role="alert"
                aria-live="polite"
                style={{
                    position: 'relative',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '10px',
                    width: '320px',
                    minHeight: '52px',
                    padding: '12px 14px',
                    background: `linear-gradient(135deg, rgba(10,12,16,0.92) 0%, ${v.bg} 100%)`,
                    border: `1px solid ${v.border}`,
                    borderRadius: '10px',
                    boxShadow: `0 0 0 1px rgba(255,255,255,0.03), 0 8px 24px rgba(0,0,0,0.4), 0 0 16px ${v.glow}`,
                    backdropFilter: 'blur(20px)',
                    WebkitBackdropFilter: 'blur(20px)',
                    animation: isVisible
                        ? 'atlas-toast-in 0.22s cubic-bezier(0.2, 0, 0, 1) forwards'
                        : 'atlas-toast-out 0.18s cubic-bezier(0.4, 0, 1, 1) forwards',
                    overflow: 'hidden',
                    pointerEvents: 'auto',
                }}
            >
                {/* Icon */}
                <div style={{ paddingTop: '1px', flexShrink: 0 }}>
                    {isLoading
                        ? <SpinnerIcon color={v.color} />
                        : <IconComp size={17} color={v.color} strokeWidth={2.2} />
                    }
                </div>

                {/* Content */}
                <div style={{ flex: 1, minWidth: 0 }}>
                    {title && (
                        <div style={{
                            fontSize: '12.5px',
                            fontWeight: 700,
                            color: '#f1f5f9',
                            lineHeight: 1.3,
                            letterSpacing: '0.01em',
                        }}>
                            {title}
                        </div>
                    )}
                    {message && (
                        <div style={{
                            fontSize: '11.5px',
                            fontWeight: 400,
                            color: 'rgba(241,245,249,0.6)',
                            lineHeight: 1.45,
                            marginTop: title ? '2px' : 0,
                            wordBreak: 'break-word',
                        }}>
                            {message}
                        </div>
                    )}
                    {/* Fallback: se só um texto foi passado sem título */}
                    {!title && !message && (
                        <div style={{ fontSize: '12.5px', fontWeight: 600, color: '#f1f5f9' }}>
                            {String(t?.message || '')}
                        </div>
                    )}
                </div>

                {/* Progress bar */}
                {!isLoading && (
                    <ProgressBar
                        duration={duration}
                        color={v.color}
                        paused={!isVisible}
                    />
                )}
            </div>
        </>
    );
};

export default AtlasToast;
