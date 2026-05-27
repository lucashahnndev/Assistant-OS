import React from 'react';
import { X, Paperclip, Music, Video, FileText, File as FileIcon, Cpu, Send } from 'lucide-react';
import { FilePreviewIcon, truncateFileName } from './MessageAttachments';

export const AttachmentMenu = ({ attachMenuRef, fileInputRef }) => (
    <div ref={attachMenuRef} className="glass" style={{
        position: 'absolute',
        bottom: 'calc(100% + 15px)',
        left: '20px',
        padding: '12px',
        borderRadius: '16px',
        zIndex: 10000,
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
        minWidth: '220px',
        boxShadow: '0 15px 50px rgba(0,0,0,0.6)',
        background: 'rgba(15, 20, 30, 0.95)',
        border: '1px solid rgba(255,255,255,0.12)',
        animation: 'slide-up 0.2s ease-out'
    }}>
        <p style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 'bold', padding: '4px 10px 8px' }}>Attached Items (Max 10)</p>
        <button onClick={() => { fileInputRef.current.accept = "image/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
            <Paperclip size={16} color="#ec4899" /> Imagens
        </button>
        <button onClick={() => { fileInputRef.current.accept = "audio/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
            <Music size={16} color="#10b981" /> Audio
        </button>
        <button onClick={() => { fileInputRef.current.accept = "video/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
            <Video size={16} color="#8b5cf6" /> Videos
        </button>
        <button onClick={() => { fileInputRef.current.accept = ".pdf,.doc,.docx,.xls,.xlsx,.txt"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
            <FileText size={16} color="#3b82f6" /> Documentos
        </button>
        <button onClick={() => { fileInputRef.current.accept = "*/*"; fileInputRef.current.click(); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px', borderRadius: '10px' }}>
            <FileIcon size={16} color="#f59e0b" /> Files
        </button>
    </div>
);

export const ChatInputArea = ({
    isMobile,
    isConnected,
    selectedId,
    input,
    setInput,
    handleSend,
    isSending,
    uploading,
    pendingFiles,
    removePendingFile,
    setPreviewFile,
    showAttachMenu,
    setShowAttachMenu,
    fileInputRef,
    inputRef,
    attachButtonRef,
    attachMenuRef,
}) => {
    return (
        <div style={{
            padding: isMobile ? '2px 8px calc(8px + env(safe-area-inset-bottom))' : '4px 14px 4px',
            borderTop: '1px solid var(--card-border)',
            background: 'var(--bg-color)',
            position: 'relative',
            zIndex: 10
        }}>
            {pendingFiles.length > 0 && (
                <div className="previews-container animate-fade-in" style={{
                    marginBottom: '8px',
                    padding: '6px',
                    background: 'rgba(255,255,255,0.02)',
                    borderRadius: '12px',
                    border: '1px solid var(--card-border)'
                }}>
                    {pendingFiles.map((file, idx) => (
                        <div key={idx} className="preview-item" onClick={() => setPreviewFile(file)}>
                            <button
                                onClick={(e) => { e.stopPropagation(); removePendingFile(idx); }}
                                className="preview-remove"
                            >
                                <X size={10} />
                            </button>
                            {file.type === 'image' && <img src={file.previewUrl} alt="preview" />}
                            {file.type === 'video' && <video src={file.previewUrl} />}
                            {(file.type !== 'image' && file.type !== 'video') && <FilePreviewIcon type={file.type} />}
                            <div className="file-name-tag">{truncateFileName(file.name)}</div>
                        </div>
                    ))}
                </div>
            )}

            {showAttachMenu && <AttachmentMenu attachMenuRef={attachMenuRef} fileInputRef={fileInputRef} />}
            
            <div style={{
                position: 'relative',
                display: 'flex',
                flexDirection: 'column',
                background: 'var(--card-bg)',
                border: '1px solid var(--card-border)',
                borderRadius: isMobile ? '12px' : '8px',
                boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
                overflow: 'hidden',
                transition: 'var(--transition)'
            }} className="input-container-complex">
                <textarea
                    ref={inputRef}
                    rows="1"
                    placeholder={(isConnected || !selectedId) ? (uploading ? "Syncing..." : "Message...") : "Connecting..."}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            if (e.ctrlKey) {
                                e.preventDefault();
                                const start = e.target.selectionStart;
                                const end = e.target.selectionEnd;
                                const val = e.target.value;
                                setInput(val.substring(0, start) + "\n" + val.substring(end));
                                setTimeout(() => {
                                    e.target.selectionStart = e.target.selectionEnd = start + 1;
                                    e.target.style.height = 'auto';
                                    e.target.style.height = `${e.target.scrollHeight}px`;
                                }, 0);
                            } else if (!e.shiftKey) {
                                e.preventDefault();
                                handleSend(e);
                            }
                        }
                    }}
                    disabled={(!isConnected && selectedId) || isSending || uploading}
                    className="custom-scrollbar"
                    style={{
                        width: '100%',
                        padding: isMobile ? '10px 44px 10px 44px' : '12px 56px 12px 56px',
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--text-main)',
                        fontSize: isMobile ? '14px' : '15px',
                        resize: 'none',
                        minHeight: isMobile ? '40px' : '48px',
                        maxHeight: '200px',
                        overflowY: 'auto',
                        lineHeight: '1.4',
                        outline: 'none',
                        whiteSpace: 'pre-wrap'
                    }}
                />
                <button
                    ref={attachButtonRef}
                    type="button"
                    disabled={uploading}
                    onClick={() => setShowAttachMenu(!showAttachMenu)}
                    className="flex-center"
                    style={{
                        position: 'absolute', left: isMobile ? '8px' : '12px', bottom: isMobile ? '4px' : '6px',
                        width: isMobile ? '32px' : '36px', height: isMobile ? '32px' : '36px', borderRadius: '50%',
                        color: uploading ? 'var(--warning)' : 'var(--text-muted)',
                        background: 'rgba(255,255,255,0.05)',
                        border: 'none',
                        transition: 'var(--transition)',
                        zIndex: 5
                    }}
                >
                    {uploading ? <Cpu size={18} className="animate-spin" /> : <Paperclip size={isMobile ? 18 : 22} />}
                </button>
                <button
                    onClick={handleSend}
                    disabled={(!input.trim() && pendingFiles.length === 0) || isSending || uploading}
                    className="flex-center"
                    style={{
                        position: 'absolute', right: isMobile ? '8px' : '12px', bottom: isMobile ? '4px' : '6px',
                        width: isMobile ? '32px' : '36px', height: isMobile ? '32px' : '36px', borderRadius: '50%',
                        background: (input.trim() || pendingFiles.length > 0) && !isSending && !uploading ? 'var(--accent-color)' : 'rgba(255,255,255,0.05)',
                        color: '#fff',
                        transition: 'var(--transition)',
                        border: 'none',
                        cursor: (input.trim() || pendingFiles.length > 0) && !isSending && !uploading ? 'pointer' : 'default',
                        zIndex: 5
                    }}
                >
                    {isSending || uploading ? <Cpu size={16} className="animate-spin" /> : <Send size={isMobile ? 16 : 18} />}
                </button>
            </div>
        </div>
    );
};
