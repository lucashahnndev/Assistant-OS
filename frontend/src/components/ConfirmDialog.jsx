import React, { useEffect, useRef } from 'react';
import { X, AlertCircle, Trash2 } from 'lucide-react';

const ConfirmDialog = ({
    isOpen,
    title,
    message,
    confirmText = "Confirm",
    cancelText = "Cancel",
    onConfirm,
    onCancel,
    isDestructive = true
}) => {
    const overlayRef = useRef(null);

    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.key === 'Escape' && isOpen) onCancel();
            // Optional: allow Enter to confirm, but be careful with destructive actions
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, onCancel]);

    if (!isOpen) return null;

    const handleOverlayClick = (e) => {
        if (e.target === overlayRef.current) {
            onCancel();
        }
    };

    return (
        <div
            ref={overlayRef}
            onClick={handleOverlayClick}
            style={{
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                background: 'rgba(0,0,0,0.8)',
                backdropFilter: 'blur(8px)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 9999
            }}
        >
            <div
                className="glass animate-fade-in"
                style={{
                    width: 'min(90%, 400px)',
                    padding: '32px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '20px',
                    border: isDestructive ? '1px solid var(--error)' : '1px solid var(--card-border)'
                }}
            >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3 style={{ display: 'flex', alignItems: 'center', gap: '10px', color: isDestructive ? 'var(--error)' : 'var(--text-primary)' }}>
                        {isDestructive ? <Trash2 size={20} /> : <AlertCircle size={20} />}
                        {title}
                    </h3>
                    <button onClick={onCancel} className="btn-ghost" style={{ padding: '8px' }}>
                        <X size={20} />
                    </button>
                </div>

                {message && (
                    <p style={{ color: 'var(--text-secondary)', fontSize: '14px', lineHeight: '1.5' }}>
                        {message}
                    </p>
                )}

                <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
                    <button onClick={onCancel} className="btn-ghost" style={{ flex: 1 }}>
                        {cancelText}
                    </button>
                    <button
                        onClick={onConfirm}
                        className="btn-primary"
                        style={{
                            flex: 1,
                            background: isDestructive ? 'var(--error)' : 'var(--accent-color)',
                            borderColor: isDestructive ? 'var(--error)' : 'var(--accent-color)'
                        }}
                    >
                        {confirmText}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ConfirmDialog;
