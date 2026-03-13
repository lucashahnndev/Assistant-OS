import React, { useState, useEffect, useRef } from 'react';
import { Activity, Cpu, Server, Clock, GitBranch, Zap, Maximize2, Minimize2 } from 'lucide-react';

const SystemMetricsFloatingCard = ({ sys, isMobile }) => {
    const [expanded, setExpanded] = useState(false);
    const cardRef = useRef(null);

    // Auto-collapse when clicking outside
    useEffect(() => {
        const handleClickOutside = (e) => {
            if (cardRef.current && !cardRef.current.contains(e.target)) {
                setExpanded(false);
            }
        };

        if (expanded) {
            document.addEventListener('mousedown', handleClickOutside);
        } else {
            document.removeEventListener('mousedown', handleClickOutside);
        }
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [expanded]);

    if (!sys || !sys.status) return null;

    const { status } = sys;

    const baseStyle = {
        position: 'absolute',
        left: isMobile ? '8px' : '16px',
        top: '50%',
        transform: 'translateY(-50%)',
        zIndex: 10900, // Matching DASHBOARD_Z.STAGE_CARD
        transition: 'all 0.3s cubic-bezier(0.19, 1, 0.22, 1)',
        backdropFilter: 'var(--surface-blur)',
        WebkitBackdropFilter: 'var(--surface-blur)',
        background: 'var(--card-bg)',
        border: '1px solid var(--card-border)',
        boxShadow: expanded ? 'var(--shadow-lg)' : '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        cursor: expanded ? 'default' : 'pointer',
    };

    const expandedStyle = {
        ...baseStyle,
        width: '280px',
        borderRadius: '12px',
        padding: '16px',
        opacity: 1,
    };

    const collapsedStyle = {
        ...baseStyle,
        width: '44px',
        height: '44px',
        borderRadius: '50%',
        padding: '0',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: 0.8,
    };

    const MetricItem = ({ icon: Icon, label, value }) => (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)' }}>
                <Icon size={14} color="var(--accent-color)" />
                <span style={{ fontSize: '11px', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
            </div>
            <span style={{ fontSize: '13px', fontWeight: '800', color: 'var(--text-primary)' }}>{value}</span>
        </div>
    );

    return (
        <div 
            ref={cardRef}
            style={expanded ? expandedStyle : collapsedStyle}
            onClick={() => !expanded && setExpanded(true)}
            onMouseEnter={() => !expanded && (cardRef.current.style.opacity = '1')}
            onMouseLeave={() => !expanded && (cardRef.current.style.opacity = '0.8')}
            className="system-metrics-card glass"
        >
            {expanded ? (
                <>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', paddingBottom: '12px', borderBottom: '1px solid rgba(var(--accent-rgb), 0.2)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <Activity size={16} color="var(--accent-color)" />
                            <h3 style={{ margin: 0, fontSize: '12px', fontWeight: '900', letterSpacing: '0.1em', color: 'var(--accent-color)' }}>SYSTEM METRICS</h3>
                        </div>
                        <button 
                            onClick={(e) => { e.stopPropagation(); setExpanded(false); }}
                            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px', display: 'flex' }}
                        >
                            <Minimize2 size={14} />
                        </button>
                    </div>
                    
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <MetricItem icon={Clock} label="Uptime" value={status.uptime || '00:00:00'} />
                        <MetricItem icon={Cpu} label="Agent" value={status.agent_name || 'A.T.L.A.S'} />
                        <MetricItem icon={Zap} label="Mode" value={status.public_mode ? 'Public' : 'Private'} />
                        <MetricItem icon={GitBranch} label="Drivers" value={status.drivers?.length || 0} />
                        <MetricItem icon={Server} label="Capabilities" value={status.loaded_capabilities?.length || 0} />
                    </div>
                </>
            ) : (
                <div style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', width: '100%', height: '100%' }}>
                    <Activity size={20} color="var(--accent-color)" />
                    {status && status.status === 'running' && (
                       <span style={{ 
                           position: 'absolute', 
                           top: '8px', 
                           right: '8px', 
                           width: '6px', 
                           height: '6px', 
                           borderRadius: '50%', 
                           background: '#10b981',
                           boxShadow: '0 0 4px #10b981'
                       }} />
                    )}
                </div>
            )}
        </div>
    );
};

export default SystemMetricsFloatingCard;
