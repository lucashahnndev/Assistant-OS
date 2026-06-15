import React from 'react';
import { File as FileIcon, Video, Music, FileText, FileCode, Archive, Table } from 'lucide-react';
import { getFileUrl } from '../../utils/chatHistoryTransform';

export const AttachmentGrid = ({ items, sessionId, onExpand }) => {
    if (!items || items.length === 0) return null;
    const limit = 4;
    const displayItems = items.slice(0, limit);
    const remaining = items.length - limit;

    return (
        <div className={`attachment-grid grid-${Math.min(items.length, limit)} ${items.length > 4 ? 'grid-more' : ''}`}>
            {displayItems.map((item, idx) => {
                const url = getFileUrl(item, sessionId);
                return (
                    <div key={idx} className="grid-item" onClick={() => onExpand({ ...item, previewUrl: url })}>
                        {item.type === 'image' && (
                            <img src={url} alt={item.name} />
                        )}
                        {item.type === 'video' && (
                            <video src={url} />
                        )}
                        {idx === limit - 1 && remaining > 0 && (
                            <div className="grid-overlay">+{remaining}</div>
                        )}
                    </div>
                );
            })}
        </div>
    );
};

export const truncateFileName = (name, length = 12) => {
    if (!name || name.length <= length) return name;
    const extIdx = name.lastIndexOf('.');
    if (extIdx === -1 || name.length - extIdx > 4) {
        return name.substring(0, length) + '...';
    }
    const ext = name.substring(extIdx);
    const base = name.substring(0, extIdx);
    return base.substring(0, length - ext.length - 2) + '..' + ext;
};

export const FilePreviewIcon = ({ type }) => {
    switch (type) {
        case 'image': return <FileIcon size={24} color="#ec4899" />;
        case 'video': return <Video size={24} color="#8b5cf6" />;
        case 'audio': return <Music size={24} color="#10b981" />;
        case 'pdf': return <FileText size={24} color="#ef4444" />;
        case 'doc': return <FileText size={24} color="#3b82f6" />;
        case 'code': return <FileCode size={24} color="#f59e0b" />;
        case 'zip':
        case 'archive': return <Archive size={24} color="#6b7280" />;
        case 'csv':
        case 'xls':
        case 'xlsx': return <Table size={24} color="#10b981" />;
        default: return <FileIcon size={24} color="var(--text-muted)" />;
    }
};

export const AttachmentList = ({ items, sessionId, onExpand }) => {
    if (!items || items.length === 0) return null;
    return (
        <div className="attachment-list">
            {items.length === 1 && (items[0].type === 'pdf' || items[0].name?.endsWith('.txt')) && (
                <div style={{ width: '100%', height: '150px', borderRadius: '10px', overflow: 'hidden', border: '1px solid var(--card-border)', marginBottom: '8px' }}>
                    <iframe
                        src={getFileUrl(items[0], sessionId)}
                        style={{ width: '100%', height: '100%', border: 'none' }}
                        title="Preview"
                    />
                </div>
            )}
            {items.map((item, idx) => (
                <div key={idx} className="doc-item" onClick={() => {
                    if (item.type === 'audio') return;
                    onExpand({ ...item, previewUrl: getFileUrl(item, sessionId) });
                }}>
                    <FilePreviewIcon type={item.type} />
                    <div className="doc-info">
                        <span className="doc-name">{item.name?.split('/').pop() || 'File'}</span>
                        <span className="doc-meta">{item.mime ? (item.mime.split('/')[1]?.toUpperCase() || 'FILE') : (item.name?.split('.').pop()?.toUpperCase() || 'FILE')}</span>
                    </div>
                </div>
            ))}
            {items.some(i => i.type === 'audio') && (
                <div className="audio-player-container">
                    {items.filter(i => i.type === 'audio').map((item, idx) => (
                        <audio key={idx} controls src={getFileUrl(item, sessionId)} />
                    ))}
                </div>
            )}
        </div>
    );
};

export const MessageAttachments = ({ msg, sessionId, onExpand }) => {
    const allAttachments = msg?.attachments || (msg?.file ? [msg.file] : []);
    if (allAttachments.length === 0) return null;

    const normalizeAttachment = (a) => {
        if (typeof a === 'string') {
            const name = a.split('/').pop();
            const ext = name.split('.').pop()?.toLowerCase();
            let type = 'file';
            if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) type = 'image';
            else if (['mp4', 'webm', 'ogg'].includes(ext)) type = 'video';
            else if (['mp3', 'wav'].includes(ext)) type = 'audio';
            else if (ext === 'pdf') type = 'pdf';
            return { path: a, name, type };
        }
        let type = a.type;
        if (!type && a.mime) {
            if (a.mime.startsWith('image/')) type = 'image';
            else if (a.mime.startsWith('video/')) type = 'video';
            else if (a.mime.startsWith('audio/')) type = 'audio';
            else if (a.mime === 'application/pdf') type = 'pdf';
        }
        if (!type && (a.name || a.path || a.file)) {
            const name = a.name || a.path || a.file || '';
            const ext = name.split('.').pop()?.toLowerCase();
            if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) type = 'image';
            else if (['mp4', 'webm', 'ogg'].includes(ext)) type = 'video';
            else if (['mp3', 'wav'].includes(ext)) type = 'audio';
            else if (ext === 'pdf') type = 'pdf';
        }
        return { ...a, type: type || 'file' };
    };

    const normalized = allAttachments.map(normalizeAttachment);
    const visuals = normalized.filter(a => a.type === 'image' || a.type === 'video');
    const docs = normalized.filter(a => a.type !== 'image' && a.type !== 'video');

    return (
        <div style={{ marginBottom: '12px' }}>
            <AttachmentGrid items={visuals} sessionId={sessionId} onExpand={onExpand} />
            <AttachmentList items={docs} sessionId={sessionId} onExpand={onExpand} />
        </div>
    );
};
