import React from 'react';
import { Hash, Terminal, SendHorizontal, MessageCircle, Mic, Activity } from 'lucide-react';

export const SessionIcon = ({ source, size = 16 }) => {
    let icon = <Hash size={size} color="var(--text-muted)" />;
    let bgColor = 'rgba(255,255,255,0.1)';

    switch (source) {
        case 'telegram':
            icon = <SendHorizontal size={size} color="#fff" style={{ transform: 'rotate(-45deg)', marginTop: '-1px' }} />;
            bgColor = '#229ED9';
            break;
        case 'web':
        case 'portal':
            icon = <MessageCircle size={size} color="#fff" />;
            bgColor = 'var(--accent-color)';
            break;
        case 'console':
        case 'terminal':
            icon = <Terminal size={size} color="#fff" />;
            bgColor = '#1e293b';
            break;
        case 'voice':
            icon = <Mic size={size} color="#fff" />;
            bgColor = 'var(--success)';
            break;
        case 'nexus':
            icon = <Activity size={size} color="#1e293b" />;
            bgColor = '#00f2ff';
            break;
        default:
            break;
    }

    return (
        <div style={{
            width: '100%',
            height: '100%',
            borderRadius: '50%',
            background: bgColor,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
        }}>
            {icon}
        </div>
    );
};

export const SessionAvatar = ({ session, size = 40, showBadge = true, onClick }) => {
    const sessId = session?.session_id || session?.id;
    const initial = (session?.name || sessId || '?').charAt(0).toUpperCase();
    const colors = ['#ec4899', '#8b5cf6', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#84cc16'];
    const colorIndex = sessId ? sessId.charCodeAt(sessId.length - 1) % colors.length : 0;
    const bgColor = colors[colorIndex];
    const avatarUrl = session?.profile_picture ? `/api/sessions/${sessId}/files/${session.profile_picture}` : null;

    return (
        <div
            onClick={onClick}
            style={{
                position: 'relative',
                width: `${size}px`,
                height: `${size}px`,
                borderRadius: '50%',
                background: avatarUrl ? 'transparent' : bgColor,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontWeight: 'bold',
                fontSize: `${size * 0.45}px`,
                flexShrink: 0,
                cursor: onClick ? 'pointer' : 'default',
                boxShadow: '0 4px 10px rgba(0,0,0,0.15)',
                border: '1px solid rgba(255,255,255,0.05)',
                transition: 'var(--transition)'
            }}
            className={onClick ? "hover:ring-2 hover:ring-[var(--accent-color)]" : ""}
            title={onClick ? "Change Profile Picture" : ""}
        >
            {avatarUrl ? (
                <img
                    src={avatarUrl}
                    alt="Avatar"
                    style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }}
                    onError={(e) => {
                        e.target.style.display = 'none';
                        if (e.target.nextSibling) e.target.nextSibling.style.display = 'block';
                    }}
                />
            ) : null}
            <span style={{ display: avatarUrl ? 'none' : 'block' }}>{initial}</span>

            {showBadge && (
                <div style={{
                    position: 'absolute',
                    bottom: '-2px',
                    right: '-2px',
                    width: `${size * 0.38}px`,
                    height: `${size * 0.38}px`,
                    background: 'var(--card-bg)',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    border: '1px solid rgba(255,255,255,0.1)',
                    boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
                }}>
                    <SessionIcon source={session?.interface || session?.source} size={Math.max(8, size * 0.25)} />
                </div>
            )}
        </div>
    );
};
