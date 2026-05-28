import { useState, useEffect, useRef } from 'react';
import { Cloud, CheckCircle, Copy, Link as LinkIcon } from 'lucide-react';
import { api } from '../hooks/api';
import { QRCodeSVG } from 'qrcode.react';
import toast from 'react-hot-toast';

const RemoteAccessIndicator = () => {
    const [tunnels, setTunnels] = useState([]);
    const [isOpen, setIsOpen] = useState(false);
    const popoverRef = useRef(null);

    const fetchStatus = async () => {
        try {
            const res = await api.get('/system/tunnels/status');
            if (res?.active_tunnels) {
                setTunnels(res.active_tunnels.filter(t => t.status === 'running'));
            }
        } catch (error) {
            console.error("Failed to fetch tunnel status", error);
        }
    };

    useEffect(() => {
        fetchStatus();
        const interval = setInterval(fetchStatus, 10000);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (popoverRef.current && !popoverRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        };
        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
        }
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isOpen]);

    const copyToClipboard = (url) => {
        navigator.clipboard.writeText(url);
        toast.success("Link copiado!");
    };

    if (tunnels.length === 0) return null;

    return (
        <div style={{ position: 'relative' }} ref={popoverRef}>
            <button
                className="btn-ghost"
                onClick={() => setIsOpen(!isOpen)}
                style={{ padding: '0.45rem', color: isOpen ? 'var(--accent-color)' : 'var(--text-muted)', display: 'flex', alignItems: 'center' }}
                title="Acesso Remoto Ativo"
            >
                <Cloud size={18} />
                <div style={{
                    width: '6px', height: '6px', borderRadius: '50%', background: '#10b981', position: 'absolute', top: '4px', right: '4px'
                }} />
            </button>

            {isOpen && (
                <div className="glass-card animate-fade-in" style={{
                    position: 'absolute', top: '120%', right: '0', minWidth: '280px', padding: '16px',
                    borderRadius: 'var(--radius-md)', zIndex: 3000, boxShadow: 'var(--shadow-lg)'
                }}>
                    <h4 style={{ fontSize: '13px', fontWeight: '800', marginBottom: '12px', borderBottom: '1px solid var(--card-border)', paddingBottom: '8px' }}>
                        Túneis Ativos
                    </h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        {tunnels.map((tunnel, idx) => (
                            <div key={idx} style={{ background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: 'var(--radius-sm)' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                    <span style={{ fontSize: '12px', fontWeight: 'bold', textTransform: 'uppercase' }}>{tunnel.provider}</span>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', color: '#10b981' }}>
                                        <CheckCircle size={12} /> Online
                                    </div>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                    {tunnel.public_url && (
                                        <>
                                            <div style={{ background: 'white', padding: '4px', borderRadius: '4px' }}>
                                                <QRCodeSVG value={tunnel.public_url} size={64} />
                                            </div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', flex: 1, overflow: 'hidden' }}>
                                                <a href={tunnel.public_url} target="_blank" rel="noreferrer" style={{ fontSize: '11px', color: 'var(--accent-color)', wordBreak: 'break-all', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                                    <LinkIcon size={12} /> Abrir Link
                                                </a>
                                                <button onClick={() => copyToClipboard(tunnel.public_url)} className="btn-ghost" style={{ fontSize: '11px', padding: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', background: 'rgba(255,255,255,0.05)' }}>
                                                    <Copy size={12} /> Copiar
                                                </button>
                                            </div>
                                        </>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};

export default RemoteAccessIndicator;
