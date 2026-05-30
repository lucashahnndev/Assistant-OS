import React, { useState, useEffect } from 'react';
import { X, Maximize, Minimize } from 'lucide-react';
import WegenaParticleCanvas from './WegenaParticleCanvas';

export const WegenaSceneModal = () => {
    const [isOpen, setIsOpen] = useState(false);
    const [sceneData, setSceneData] = useState(null);
    const [isFullscreen, setIsFullscreen] = useState(false);

    useEffect(() => {
        const handleOpen = (e) => {
            if (e.detail?.data) {
                setSceneData(e.detail.data);
                setIsOpen(true);
            }
        };
        window.addEventListener('app_action_view_wegena', handleOpen);
        return () => window.removeEventListener('app_action_view_wegena', handleOpen);
    }, []);

    if (!isOpen || !sceneData) return null;

    const handleClose = () => {
        setIsOpen(false);
        setSceneData(null);
        setIsFullscreen(false);
    };

    return (
        <div style={{
            position: 'fixed',
            inset: 0,
            zIndex: 99999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'rgba(0,0,0,0.85)',
            backdropFilter: 'blur(8px)',
            padding: isFullscreen ? '0' : '5vh 5vw'
        }}>
            <div style={{
                position: 'relative',
                width: isFullscreen ? '100vw' : '100%',
                height: isFullscreen ? '100vh' : '100%',
                backgroundColor: '#000',
                borderRadius: isFullscreen ? '0' : '16px',
                overflow: 'hidden',
                boxShadow: '0 25px 50px -12px rgba(0,0,0,0.7)',
                border: isFullscreen ? 'none' : '1px solid rgba(255,255,255,0.1)',
                display: 'flex',
                flexDirection: 'column'
            }}>
                {/* Header Overlay */}
                <div style={{
                    position: 'absolute',
                    top: 0, left: 0, right: 0,
                    padding: '16px 20px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    background: 'linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, transparent 100%)',
                    zIndex: 10
                }}>
                    <div style={{ color: '#fff', fontWeight: 600, fontSize: '14px', textShadow: '0 2px 4px rgba(0,0,0,0.8)' }}>
                        {sceneData.title || 'Wegena Scene'}
                    </div>
                    <div style={{ display: 'flex', gap: '12px' }}>
                        <button
                            onClick={() => setIsFullscreen(!isFullscreen)}
                            style={{
                                background: 'rgba(255,255,255,0.1)',
                                border: 'none',
                                color: '#fff',
                                width: '32px', height: '32px',
                                borderRadius: '8px',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                cursor: 'pointer',
                                backdropFilter: 'blur(4px)'
                            }}
                        >
                            {isFullscreen ? <Minimize size={16} /> : <Maximize size={16} />}
                        </button>
                        <button
                            onClick={handleClose}
                            style={{
                                background: 'rgba(239, 68, 68, 0.2)',
                                border: 'none',
                                color: '#ef4444',
                                width: '32px', height: '32px',
                                borderRadius: '8px',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                cursor: 'pointer',
                                backdropFilter: 'blur(4px)'
                            }}
                        >
                            <X size={16} />
                        </button>
                    </div>
                </div>

                {/* Canvas Container */}
                <div style={{ flex: 1, position: 'relative', width: '100%', height: '100%' }}>
                    {sceneData.scriptUrl ? (
                        <WegenaParticleCanvas 
                            sceneUrl={sceneData.scriptUrl}
                            isActive={isOpen}
                            onReady={() => {}}
                        />
                    ) : (
                        <div style={{ color: 'red', padding: '20px' }}>Error: No script URL provided</div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default WegenaSceneModal;
