import { useState, useEffect } from 'react';
import { api } from '../hooks/api';
import {
    Activity,
    Cpu,
    Layers,
    Zap,
    CheckCircle2,
    Clock,
    User,
    Shield,
    Box,
    Terminal,
    RefreshCw
} from 'lucide-react';

const Dashboard = () => {
    const [status, setStatus] = useState(null);
    const [activity, setActivity] = useState([]);
    const [works, setWorks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 640);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    const fetchData = async () => {
        try {
            const [statusData, activityData, worksRes] = await Promise.all([
                api.get('/system/status'),
                api.get('/system/activity'),
                api.get('/tasks/works?include_completed=false&limit=5')
            ]);
            setStatus(statusData);
            setActivity(activityData);
            setWorks(Array.isArray(worksRes) ? worksRes : []);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 5000);
        return () => clearInterval(interval);
    }, []);

    const Widget = ({ title, icon: Icon, children, extra, height = 'auto' }) => (
        <section className="glass premium-widget animate-fade-in" style={{
            padding: isMobile ? '14px' : '16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            height: height,
            position: 'relative',
            borderRadius: '16px'
        }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', zIndex: 1 }}>
                <h3 style={{ fontSize: '0.8125rem', fontWeight: '800', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-primary)' }}>
                    <div className="flex-center" style={{ width: '28px', height: '28px', borderRadius: '8px', background: 'var(--accent-glow)' }}>
                        <Icon size={15} style={{ color: 'var(--accent-color)' }} />
                    </div>
                    {title}
                </h3>
                {extra}
            </div>
            <div style={{ flex: 1, overflowY: 'auto', zIndex: 1 }} className="custom-scrollbar">
                {children}
            </div>
        </section>
    );

    const StatCard = ({ label, value, icon: Icon, color }) => (
        <div style={{
            padding: '10px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            borderRadius: '10px',
            background: 'rgba(255,255,255,0.02)',
            border: '1px solid var(--card-border)',
            transition: 'var(--transition-fast)'
        }}>
            <div className="flex-center" style={{
                width: '34px',
                height: '34px',
                borderRadius: '8px',
                background: `${color}15`,
                color: color,
                flexShrink: 0
            }}>
                <Icon size={17} />
            </div>
            <div style={{ minWidth: 0 }}>
                <p style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '800', marginBottom: '1px' }}>{label}</p>
                <p style={{ fontSize: '14px', fontWeight: '800', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</p>
            </div>
        </div>
    );

    return (
        <div className="scroll-container animate-fade-in" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '12px' : '0 var(--space-6) 80px var(--space-6)' }}>

                {/* Header inside content area */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', padding: isMobile ? '4px 0' : '16px 0 0' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <div className="flex-center" style={{ width: '32px', height: '32px', borderRadius: '10px', background: 'var(--accent-glow)', color: 'var(--accent-color)' }}>
                            <Activity size={16} />
                        </div>
                        <div>
                            <h2 style={{ fontSize: '1rem', fontWeight: '800' }}>Dashboard</h2>
                            <p style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>System overview and live status.</p>
                        </div>
                    </div>
                    <div style={{ fontSize: '9px', fontWeight: '800', padding: '3px 8px', borderRadius: '4px', background: 'var(--accent-glow)', color: 'var(--accent-color)' }}>
                        LIVE
                    </div>
                </div>

                {/* Main Grid Layout */}
                <div className="dashboard-grid">

                    {/* System Status Widget */}
                    <Widget title="System Status" icon={Activity}>
                        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : '1fr 1fr', gap: '8px' }}>
                            <StatCard label="Uptime" value={status?.uptime || '---'} icon={Clock} color="#a855f7" />
                            <StatCard label="Memory" value={status?.memory || '—'} icon={Layers} color="#3b82f6" />
                            <StatCard label="Skills" value={status?.loaded_skills?.length || 0} icon={Cpu} color="#10b981" />
                            <StatCard label="Drivers" value={status?.drivers?.length || 0} icon={Terminal} color="#f59e0b" />
                        </div>
                    </Widget>

                    {/* Active Workers Widget */}
                    <Widget title="Active Workers" icon={Zap} height="320px">
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            {works.length > 0 ? works.map(work => (
                                <div key={work.work_id} style={{ padding: '12px', borderRadius: '10px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--card-border)' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', alignItems: 'center' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
                                            <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--accent-color)', flexShrink: 0 }} className="animate-pulse"></div>
                                            <span style={{ fontSize: '12px', fontWeight: '800', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{work.label || work.key}</span>
                                        </div>
                                        <span style={{ fontSize: '9px', color: 'var(--accent-color)', fontWeight: '800', textTransform: 'uppercase', background: 'var(--accent-glow)', padding: '2px 6px', borderRadius: '4px', flexShrink: 0 }}>{work.status}</span>
                                    </div>
                                    <div style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginBottom: '8px' }}>
                                        {work.context?.summary?.cursor || 'Starting...'}
                                    </div>
                                    <div style={{ height: '3px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px', overflow: 'hidden' }}>
                                        <div className="progress-bar-glow" style={{ height: '100%', width: '65%', background: 'var(--accent-color)', transition: 'width 1s ease-in-out' }}></div>
                                    </div>
                                </div>
                            )) : (
                                <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', opacity: 0.5 }}>
                                    <Box size={28} style={{ margin: '0 auto 8px' }} />
                                    <p style={{ fontSize: '12px' }}>No active workers.</p>
                                </div>
                            )}
                        </div>
                    </Widget>

                    {/* Loaded Skills Widget */}
                    <Widget title="Loaded Skills" icon={Cpu} height="280px">
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                            {status?.loaded_skills?.slice(0, 8).map(skill => (
                                <div key={skill} style={{
                                    padding: '8px 10px',
                                    borderRadius: '8px',
                                    background: 'rgba(255,255,255,0.03)',
                                    border: '1px solid var(--card-border)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '6px'
                                }}>
                                    <div style={{ width: '5px', height: '5px', borderRadius: '50%', background: '#4ade80', flexShrink: 0 }}></div>
                                    <span style={{ fontSize: '10px', fontWeight: '600', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{skill}</span>
                                </div>
                            ))}
                            {(!status?.loaded_skills || status.loaded_skills.length === 0) && (
                                <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '30px 0', color: 'var(--text-muted)', fontSize: '11px' }}>No skills loaded.</div>
                            )}
                        </div>
                    </Widget>

                    {/* Recent Activity Widget */}
                    <Widget title="Recent Activity" icon={RefreshCw} height="280px">
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                            {activity.length > 0 ? activity.slice(0, 6).map((log) => (
                                <div key={log.id} style={{
                                    display: 'flex',
                                    gap: '10px',
                                    padding: '8px 10px',
                                    borderRadius: '8px',
                                    background: 'rgba(255,255,255,0.02)',
                                    border: '1px solid transparent',
                                    transition: 'var(--transition-fast)',
                                    alignItems: 'center'
                                }} onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--card-border)'}
                                    onMouseLeave={e => e.currentTarget.style.borderColor = 'transparent'}>
                                    <div className="flex-center" style={{ width: '28px', height: '28px', borderRadius: '8px', background: 'rgba(16, 185, 129, 0.1)', flexShrink: 0 }}>
                                        <CheckCircle2 size={13} color="var(--success)" />
                                    </div>
                                    <div style={{ minWidth: 0 }}>
                                        <p style={{ fontSize: '11px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                            <strong style={{ color: 'var(--accent-color)' }}>{log.username}</strong>: {log.action.replace('_', ' ')}
                                        </p>
                                        <p style={{ fontSize: '9px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '3px' }}>
                                            <Clock size={9} /> {new Date(log.timestamp).toLocaleTimeString()} · {log.target}
                                        </p>
                                    </div>
                                </div>
                            )) : (
                                <p style={{ color: 'var(--text-muted)', fontSize: '11px', textAlign: 'center', marginTop: '30px' }}>No recent activity.</p>
                            )}
                        </div>
                    </Widget>

                    {/* Security Status Widget */}
                    <Widget title="Security" icon={Shield} height="180px">
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', borderRadius: '8px', background: 'rgba(16, 185, 129, 0.05)', border: '1px solid rgba(16, 185, 129, 0.15)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <Shield size={12} style={{ color: '#4ade80' }} />
                                    <span style={{ fontSize: '11px', fontWeight: '700' }}>Skill Guards</span>
                                </div>
                                <span style={{ fontSize: '9px', fontWeight: '800', color: 'var(--success)' }}>ACTIVE</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', borderRadius: '8px', background: 'rgba(59, 130, 246, 0.05)', border: '1px solid rgba(59, 130, 246, 0.15)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <User size={12} style={{ color: '#60a5fa' }} />
                                    <span style={{ fontSize: '11px', fontWeight: '700' }}>Auth</span>
                                </div>
                                <span style={{ fontSize: '9px', fontWeight: '800', color: 'var(--accent-color)' }}>ENFORCED</span>
                            </div>
                        </div>
                    </Widget>

                </div>
            </div>
        </div>
    );
};

export default Dashboard;

