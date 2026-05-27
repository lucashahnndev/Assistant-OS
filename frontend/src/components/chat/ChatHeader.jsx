import React from 'react';
import { ChevronLeft, ChevronRight, Bot, MoreHorizontal, Trash2, Edit } from 'lucide-react';
import { SessionAvatar } from './ChatIcons';

export const ChatHeader = ({
    isMobile,
    setMobileView,
    selectedId,
    currentSession,
    isConnected,
    isEditingName,
    setIsEditingName,
    editNameValue,
    setEditNameValue,
    handleRenameSession,
    showActionsMenu,
    setShowActionsMenu,
    deleteSession,
    setShowChatProfile,
}) => {
    return (
        <div style={{ padding: isMobile ? '6px 12px' : '8px 16px', borderBottom: '1px solid var(--card-border)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            {isMobile && (
                <button className="btn-ghost" onClick={() => setMobileView('sessions')} style={{ padding: '0.4rem', marginLeft: '-0.4rem' }}>
                    <ChevronLeft size={20} />
                </button>
            )}
            {selectedId && currentSession ? (
                <SessionAvatar
                    session={currentSession}
                    size={isMobile ? 28 : 32}
                    showBadge={false}
                    onClick={() => setShowChatProfile(true)}
                />
            ) : (
                <div className="flex-center" style={{ width: isMobile ? '28px' : '32px', height: isMobile ? '28px' : '32px', background: isConnected ? 'var(--success)' : 'var(--text-muted)', color: '#fff', borderRadius: '50%' }}>
                    <Bot size={isMobile ? 16 : 18} />
                </div>
            )}
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                {isEditingName ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                        <input
                            autoFocus
                            value={editNameValue}
                            onChange={(e) => setEditNameValue(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') handleRenameSession();
                                if (e.key === 'Escape') setIsEditingName(false);
                            }}
                            onBlur={handleRenameSession}
                            style={{
                                background: 'rgba(255,255,255,0.05)',
                                border: '1px solid var(--accent-color)',
                                borderRadius: '6px',
                                padding: '2px 6px',
                                color: '#fff',
                                fontSize: isMobile ? '13px' : '14px',
                                fontWeight: 'bold',
                                outline: 'none',
                                width: '100%'
                            }}
                        />
                    </div>
                ) : (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <h3
                            style={{ fontSize: isMobile ? '13px' : '14px', fontWeight: 'bold', margin: 0, cursor: selectedId ? 'pointer' : 'default', whiteSpace: 'nowrap', textOverflow: 'ellipsis', overflow: 'hidden' }}
                            onClick={() => { if (selectedId) setShowChatProfile(true); }}
                        >
                            {selectedId ? (currentSession?.name || `Session: ${selectedId.substring(0, 8)}...`) : 'Select a session'}
                        </h3>
                        {(!isMobile && selectedId) && <ChevronRight size={14} style={{ opacity: 0.5, transition: '0.2s', cursor: 'pointer' }} onClick={() => setShowChatProfile(true)} className="hover:opacity-100" />}
                        <div
                            title={isConnected ? 'Connected' : 'Disconnected'}
                            style={{
                                width: '8px',
                                height: '8px',
                                borderRadius: '50%',
                                marginLeft: '4px',
                                backgroundColor: isConnected ? 'var(--success)' : 'var(--text-muted)',
                                boxShadow: isConnected ? '0 0 6px var(--success-glow, rgba(16, 185, 129, 0.4))' : 'none',
                                flexShrink: 0
                            }}
                        />
                    </div>
                )}
            </div>

            {selectedId && (
                <div style={{ position: 'relative' }}>
                    <button
                        className="btn-ghost"
                        onClick={() => setShowActionsMenu(!showActionsMenu)}
                        style={{ padding: '8px' }}
                    >
                        <MoreHorizontal size={20} />
                    </button>
                    {showActionsMenu && (
                        <div className="glass" style={{
                            position: 'absolute',
                            top: '100%',
                            right: 0,
                            marginTop: '8px',
                            padding: '8px',
                            zIndex: 1000,
                            minWidth: '160px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '4px',
                            background: 'var(--card-bg)',
                            boxShadow: '0 10px 30px rgba(0,0,0,0.5)'
                        }}>
                            <button
                                className="btn-ghost"
                                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', fontSize: '13px', justifyContent: 'flex-start', color: 'var(--error)' }}
                                onClick={(e) => {
                                    deleteSession(e, selectedId);
                                    setShowActionsMenu(false);
                                }}
                            >
                                <Trash2 size={16} /> Delete Session
                            </button>
                            <button
                                className="btn-ghost"
                                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', fontSize: '13px', justifyContent: 'flex-start' }}
                                onClick={() => {
                                    setIsEditingName(true);
                                    setEditNameValue(currentSession?.name || '');
                                    setShowActionsMenu(false);
                                }}
                            >
                                <Edit size={16} /> Rename
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};
