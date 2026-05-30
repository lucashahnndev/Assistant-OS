import React, { useState, useEffect } from 'react';
import { Download, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const PWA_DISMISS_KEY = 'atlas_pwa_dismissed_at';
const COOLDOWN_DAYS = 7;

const PwaInstallBanner = () => {
    const { agentName } = useAuth();
    const [deferredPrompt, setDeferredPrompt] = useState(null);
    const [isVisible, setIsVisible] = useState(false);

    useEffect(() => {
        const handleBeforeInstallPrompt = (e) => {
            // Prevent the mini-infobar from appearing on mobile
            e.preventDefault();
            
            // Check if dismissed recently
            const dismissedAt = localStorage.getItem(PWA_DISMISS_KEY);
            if (dismissedAt) {
                const daysSinceDismiss = (Date.now() - parseInt(dismissedAt, 10)) / (1000 * 60 * 60 * 24);
                if (daysSinceDismiss < COOLDOWN_DAYS) {
                    return; // Still in cooldown
                }
            }

            // Stash the event so it can be triggered later.
            setDeferredPrompt(e);
            
            // Wait a few seconds before showing to not overwhelm the user on first load
            setTimeout(() => {
                setIsVisible(true);
            }, 3000);
        };

        window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);

        return () => {
            window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
        };
    }, []);

    // Also listen for successful install to hide the banner
    useEffect(() => {
        const handleAppInstalled = () => {
            setIsVisible(false);
            setDeferredPrompt(null);
        };
        window.addEventListener('appinstalled', handleAppInstalled);
        return () => window.removeEventListener('appinstalled', handleAppInstalled);
    }, []);

    const handleInstall = async () => {
        if (!deferredPrompt) return;
        
        // Show the install prompt
        deferredPrompt.prompt();
        
        // Wait for the user to respond to the prompt
        const { outcome } = await deferredPrompt.userChoice;
        
        if (outcome === 'accepted') {
            setIsVisible(false);
        }
        
        // We can't use the prompt again
        setDeferredPrompt(null);
    };

    const handleDismiss = () => {
        setIsVisible(false);
        localStorage.setItem(PWA_DISMISS_KEY, Date.now().toString());
    };

    if (!isVisible) return null;

    return (
        <div style={{
            position: 'fixed',
            bottom: '24px',
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 9999,
            width: 'calc(100% - 32px)',
            maxWidth: '480px',
            animation: 'slideUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards',
        }}>
            <style>{`
                @keyframes slideUp {
                    from { opacity: 0; transform: translate(-50%, 40px); }
                    to { opacity: 1; transform: translate(-50%, 0); }
                }
            `}</style>
            
            <div className="glass" style={{
                display: 'flex',
                alignItems: 'center',
                gap: '16px',
                padding: '16px',
                borderRadius: '16px',
                background: 'rgba(15, 15, 20, 0.85)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                boxShadow: '0 20px 40px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255,255,255,0.05) inset',
                backdropFilter: 'blur(20px)',
                WebkitBackdropFilter: 'blur(20px)',
            }}>
                <div style={{
                    width: '48px',
                    height: '48px',
                    borderRadius: '12px',
                    overflow: 'hidden',
                    flexShrink: 0,
                    background: 'var(--bg-color)',
                    border: '1px solid rgba(255,255,255,0.05)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                }}>
                    <img 
                        src="/api/static/logo-192x192.png" 
                        alt="Logo" 
                        style={{ width: '32px', height: '32px', objectFit: 'contain' }}
                        onError={(e) => {
                            e.currentTarget.style.display = 'none';
                            e.currentTarget.nextSibling.style.display = 'flex';
                        }}
                    />
                    <div style={{
                        display: 'none',
                        width: '100%',
                        height: '100%',
                        background: 'var(--accent-color)',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'white',
                        fontWeight: '900',
                        fontSize: '1.2rem',
                    }}>
                        {agentName.charAt(0).toUpperCase()}
                    </div>
                </div>

                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <div style={{ fontWeight: '700', fontSize: '15px', color: '#fff', letterSpacing: '-0.01em' }}>
                        Instalar {agentName}
                    </div>
                    <div style={{ fontSize: '13px', color: 'rgba(255,255,255,0.6)', lineHeight: '1.4' }}>
                        Adicione o sistema à tela inicial para uma experiência nativa e mais rápida.
                    </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', flexShrink: 0 }}>
                    <button 
                        onClick={handleInstall}
                        style={{
                            background: 'var(--accent-color)',
                            color: '#fff',
                            border: 'none',
                            padding: '8px 16px',
                            borderRadius: '8px',
                            fontSize: '13px',
                            fontWeight: '600',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '6px',
                            boxShadow: '0 4px 12px rgba(99, 102, 241, 0.3)'
                        }}
                    >
                        <Download size={14} />
                        Instalar
                    </button>
                    <button 
                        onClick={handleDismiss}
                        style={{
                            background: 'transparent',
                            color: 'rgba(255,255,255,0.5)',
                            border: 'none',
                            padding: '4px',
                            fontSize: '12px',
                            fontWeight: '500',
                            cursor: 'pointer',
                        }}
                    >
                        Agora não
                    </button>
                </div>
                
                <button 
                    onClick={handleDismiss}
                    style={{
                        position: 'absolute',
                        top: '-8px',
                        right: '-8px',
                        width: '24px',
                        height: '24px',
                        borderRadius: '12px',
                        background: '#222',
                        border: '1px solid #333',
                        color: '#aaa',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        padding: 0
                    }}
                >
                    <X size={14} />
                </button>
            </div>
        </div>
    );
};

export default PwaInstallBanner;
