import { useState, useEffect } from 'react';
import { api } from '../hooks/api';
import {
    Activity,
    Cpu,
    Layers,
    Zap,
    CheckCircle2,
    AlertCircle
} from 'lucide-react';
import PageHeader from '../components/PageHeader';

const Dashboard = () => {
    const [status, setStatus] = useState(null);
    const [activity, setActivity] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const statusData = await api.get('/system/status');
                setStatus(statusData);

                const activityData = await api.get('/system/activity');
                setActivity(activityData);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
        const interval = setInterval(fetchData, 5000);
        return () => clearInterval(interval);
    }, []);

    const stats = [
        { label: 'System Status', value: status?.status || 'Active', icon: Activity, color: 'var(--success)' },
        { label: 'Loaded Skills', value: status?.loaded_skills?.length || 0, icon: Cpu, color: 'var(--accent-color)' },
        { label: 'Active Drivers', value: status?.drivers?.length || 0, icon: Layers, color: 'var(--warning)' },
        { label: 'Uptime', value: status?.uptime || '---', icon: Zap, color: '#a855f7' },
    ];

    return (
        <div className="scroll-container animate-fade-in" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <PageHeader
                title="Dashboard"
                subtitle="Overview of your agent's current state and infrastructure."
            />

            <div style={{ flex: 1, overflowY: 'auto', padding: '0 var(--space-6) 100px var(--space-6)' }}>

                {/* Stats Grid */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                    gap: '20px',
                    marginBottom: '40px'
                }}>
                    {stats.map((stat) => (
                        <div key={stat.label} className="glass" style={{ padding: 'var(--space-6)', display: 'flex', alignItems: 'center', gap: 'var(--space-5)', borderRadius: 'var(--radius-md)' }}>
                            <div className="flex-center" style={{
                                width: '48px',
                                height: '48px',
                                borderRadius: '12px',
                                background: `rgba(${stat.color === 'var(--success)' ? '16, 185, 129' : '59, 130, 246'}, 0.1)`,
                                color: stat.color
                            }}>
                                <stat.icon size={24} />
                            </div>
                            <div>
                                <p style={{ fontSize: '12px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 'bold', letterSpacing: '0.05em' }}>{stat.label}</p>
                                <p style={{ fontSize: '20px', fontWeight: '700' }}>{stat.value}</p>
                            </div>
                        </div>
                    ))}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 2fr 1fr))', gap: '24px', alignItems: 'start' }}>
                    {/* Recent Activity / Logs */}
                    <section className="glass" style={{ padding: '24px', minHeight: '300px' }}>
                        <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <Activity size={18} /> Recent Activity
                        </h3>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            {activity.length > 0 ? activity.map((log) => (
                                <div key={log.id} style={{ display: 'flex', gap: '12px', padding: '12px', borderRadius: '8px', background: 'rgba(255,255,255,0.02)' }}>
                                    <CheckCircle2 size={16} color="var(--success)" style={{ marginTop: '2px' }} />
                                    <div>
                                        <p style={{ fontSize: '14px' }}><strong>{log.username}</strong>: {log.action.replace('_', ' ')} on <strong>{log.target}</strong></p>
                                        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{new Date(log.timestamp).toLocaleString()}</p>
                                    </div>
                                </div>
                            )) : (
                                <p style={{ color: 'var(--text-muted)', fontSize: '14px', textAlign: 'center', marginTop: '40px' }}>No recent activity found.</p>
                            )}
                        </div>
                    </section>

                    {/* System Health */}
                    <section className="glass" style={{ padding: '24px' }}>
                        <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '20px' }}>Health Check</h3>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span style={{ fontSize: '14px' }}>Kernel Connectivity</span>
                                <span style={{ fontSize: '12px', padding: '4px 8px', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.1)', color: 'var(--success)' }}>ONLINE</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span style={{ fontSize: '14px' }}>LLM Provider (Gemini)</span>
                                <span style={{ fontSize: '12px', padding: '4px 8px', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.1)', color: 'var(--success)' }}>OK</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span style={{ fontSize: '14px' }}>ChromaDB Memory</span>
                                <span style={{ fontSize: '12px', padding: '4px 8px', borderRadius: '4px', background: 'rgba(245, 158, 11, 0.1)', color: 'var(--warning)' }}>SYNCING</span>
                            </div>
                        </div>
                    </section>
                </div>
            </div>
        </div>
    );
};

export default Dashboard;
