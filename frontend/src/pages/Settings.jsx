import { useState, useEffect, useRef } from 'react';
import { api } from '../hooks/api';
import {
    Save,
    RefreshCw,
    Shield,
    Cpu,
    Globe,
    Mic,
    MessageCircle,
    FileJson,
    User as UserIcon,
    CloudSun,
    Terminal,
    Pause,
    Play,
    Download,
    CheckCircle,
    AlertCircle,
    Power,
    Eye,
    EyeOff,
    Monitor,
    Zap,
    Puzzle,
    ExternalLink,
    ChevronLeft,
    ChevronRight,
    Plus
} from 'lucide-react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import PageHeader from '../components/PageHeader';
import ModelPoolManager from '../components/ModelPoolManager';

const Settings = () => {
    const [config, setConfig] = useState(null);
    const [rawJson, setRawJson] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [activeTab, setActiveTab] = useState('general');
    const [isTabsCollapsed, setIsTabsCollapsed] = useState(() => {
        return localStorage.getItem('assistant_settings_tabs_collapsed') === 'true';
    });
    const [envData, setEnvData] = useState({});
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);
    const [isTablet, setIsTablet] = useState(window.innerWidth > 640 && window.innerWidth <= 1024);

    useEffect(() => {
        const handleResize = () => {
            setIsMobile(window.innerWidth <= 640);
            setIsTablet(window.innerWidth > 640 && window.innerWidth <= 1024);
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);


    const [logs, setLogs] = useState([]);
    const [isStreaming, setIsStreaming] = useState(true);
    const [logSources, setLogSources] = useState(['assistant.log']);
    const [activeLogSource, setActiveLogSource] = useState('assistant.log');
    const [showSecrets, setShowSecrets] = useState({});

    const logScrollRef = useRef(null);
    const lineNumbersRef = useRef(null);
    const editorRef = useRef(null);
    const eventSourceRef = useRef(null);

    useEffect(() => {
        fetchConfig();
        fetchEnv();
        fetchLogSources();
        return () => stopLogStream();
    }, []);

    useEffect(() => {
        if (activeTab === 'debug' && isStreaming) {
            startLogStream(activeLogSource);
        } else if (activeTab !== 'debug') {
            stopLogStream();
        }
    }, [activeTab, isStreaming, activeLogSource]);

    useEffect(() => {
        if (logScrollRef.current) {
            logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
        }
    }, [logs]);

    const fetchLogSources = async () => {
        try {
            const data = await api.get('/system/logs/list');
            if (data && data.length > 0) setLogSources(data);
        } catch (err) { console.error(err); }
    };

    const startLogStream = (source = 'assistant.log') => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
        }

        const eventSource = new EventSource(`/api/system/logs?source=${source}`);
        eventSourceRef.current = eventSource;

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'log') {
                setLogs(prev => [...prev.slice(-199), data.msg]);
            }
        };

        eventSource.onerror = () => {
            stopLogStream();
        };
    };

    const stopLogStream = () => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
        }
    };

    const fetchConfig = async () => {
        try {
            const data = await api.get('/system/config');
            setConfig(data);
            setRawJson(JSON.stringify(data, null, 2));
        } catch (err) {
            console.error(err);
            toast.error("Failed to load configuration");
        }
        finally { setLoading(false); }
    };

    const fetchEnv = async () => {
        try {
            const data = await api.get('/system/env');
            setEnvData(data);
        } catch (err) { console.error(err); }
    };

    const handleSaveEnv = async () => {
        try {
            await api.post('/system/env', envData);
            toast.success("Secrets updated. Restart required.");
        } catch (err) { toast.error(err.message); }
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            await Promise.all([
                api.post('/system/config', config),
                api.post('/system/env', envData)
            ]);
            toast.success("Settings & Secrets updated.");
        } catch (err) { toast.error(err.message); }
        finally { setSaving(false); }
    };

    const handleReload = async () => {
        const loadingToast = toast.loading("Applying neural changes (Hot Reload)...");
        try {
            await api.post('/system/reload');
            toast.success("System hot-reloaded successfully!", { id: loadingToast });
        } catch (err) {
            toast.error(`Hot Reload Failed: ${err.message}`, { id: loadingToast });
        }
    };

    const toggleSecret = (key) => {
        setShowSecrets(prev => ({ ...prev, [key]: !prev[key] }));
    };

    const updateNestedValue = (path, value) => {
        const newConfig = { ...config };
        const parts = path.split('.');
        let current = newConfig;
        for (let i = 0; i < parts.length - 1; i++) {
            if (!current[parts[i]]) current[parts[i]] = {};
            current = current[parts[i]];
        }
        current[parts[parts.length - 1]] = value;
        setConfig(newConfig);
        setRawJson(JSON.stringify(newConfig, null, 2));
    };

    const downloadLogs = () => {
        window.open(`/api/system/logs/download?filename=${activeLogSource}`, '_blank');
    };

    if (loading) return (
        <div className="flex-center" style={{ height: '100vh' }}>
            <RefreshCw className="animate-spin" size={32} color="var(--accent-color)" />
        </div>
    );

    const tabs = [
        { id: 'general', label: 'Identity', icon: UserIcon },
        { id: 'interfaces', label: 'Interfaces', icon: Monitor },
        { id: 'media', label: 'Media', icon: Play },
        { id: 'network', label: 'Network', icon: Globe },
        { id: 'llm', label: 'Intelligence', icon: Cpu },
        { id: 'stt', label: 'Voice', icon: Mic },
        { id: 'skills', label: 'Skills', icon: Puzzle },
        { id: 'weather', label: 'Environment', icon: CloudSun },
        { id: 'security', label: 'Secrets', icon: Shield },
        { id: 'debug', label: 'Debug/Logs', icon: Terminal },
        { id: 'advanced', label: 'JSON Editor', icon: FileJson },
    ];

    const handleScrollSync = (e) => {
        if (lineNumbersRef.current) {
            lineNumbersRef.current.scrollTop = e.target.scrollTop;
        }
    };

    const getLineNumbers = () => {
        const lines = rawJson.split('\n').length;
        return Array.from({ length: lines }, (_, i) => i + 1).join('\n');
    };

    const renderHeader = () => (
        <PageHeader
            title="Configuration"
            subtitle={(isMobile || isTablet) ? "" : "Fine-tune the neural parameters and system interfaces."}
        >
            <div style={{ display: 'flex', gap: '8px', width: (isMobile || isTablet) ? '100%' : 'auto', justifyContent: (isMobile || isTablet) ? 'space-between' : 'flex-end', flexWrap: 'wrap' }}>
                <button onClick={fetchConfig} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px', flex: (isMobile || isTablet) ? 1 : 'none' }}>
                    <RefreshCw size={18} /> {(isMobile || isTablet) ? "" : "Revert"}
                </button>
                <button
                    onClick={handleReload}
                    className="btn-ghost"
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-2)',
                        padding: 'var(--space-2) var(--space-3)',
                        borderColor: 'var(--accent-color)',
                        color: 'var(--accent-color)',
                        background: 'rgba(var(--accent-rgb), 0.1)',
                        fontSize: '0.75rem',
                        fontWeight: '700',
                        flex: (isMobile || isTablet) ? 1 : 'none'
                    }}
                    title="Apply changes without restart"
                >
                    <Zap size={16} /> HOT RELOAD
                </button>
                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="btn-primary"
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-2)',
                        padding: 'var(--space-2) var(--space-4)',
                        borderRadius: 'var(--radius-sm)',
                        fontWeight: '800',
                        fontSize: '0.75rem',
                        flex: (isMobile || isTablet) ? 2 : 'none'
                    }}
                >
                    <Save size={18} /> {saving ? '...' : ((isMobile || isTablet) ? 'SAVE' : 'SAVE CHANGES')}
                </button>
            </div>
        </PageHeader>

    );

    const renderGeneral = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>

                <h3 className="section-title">
                    <UserIcon size={20} /> Persona Settings
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                    <div className="form-group">
                        <label>Agent Name</label>
                        <input
                            type="text"
                            className="input-field"
                            value={config.agent?.agent_name || ''}
                            onChange={(e) => updateNestedValue('agent.agent_name', e.target.value)}
                            placeholder="e.g. Atlas, Jarvis..."
                        />
                    </div>
                    <div className="form-group">
                        <label>System Personality (Neural Bias)</label>
                        <textarea
                            className="input-field"
                            style={{ minHeight: '140px' }}
                            value={config.agent?.personality || ''}
                            onChange={(e) => updateNestedValue('agent.personality', e.target.value)}
                            placeholder="Describe how the agent should behave..."
                        />
                    </div>
                </div>
            </section>

            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>
                <h3 className="section-title">
                    <Zap size={20} /> Intent Resolution
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : '1fr 1fr', gap: '24px' }}>

                    <div className="form-group">
                        <label>Resolution Mode</label>
                        <select
                            className="input-field"
                            value={config.intent_resolution?.mode || 'llm_first'}
                            onChange={(e) => updateNestedValue('intent_resolution.mode', e.target.value)}
                        >
                            <option value="llm_first">LLM First (Reasoning)</option>
                            <option value="semantic_first">Semantic First (High Precision)</option>
                        </select>
                    </div>
                    <div className="form-group">
                        <label>LLM Confidence Threshold</label>
                        <input
                            type="number"
                            step="0.05"
                            className="input-field"
                            value={config.intent_resolution?.llm_confidence_threshold || 0.65}
                            onChange={(e) => updateNestedValue('intent_resolution.llm_confidence_threshold', parseFloat(e.target.value))}
                        />
                    </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '16px' }}>
                    <input
                        type="checkbox"
                        className="luxury-checkbox"
                        checked={config.intent_resolution?.semantic_fallback || false}
                        onChange={(e) => updateNestedValue('intent_resolution.semantic_fallback', e.target.checked)}
                    />
                    <span style={{ fontSize: '14px', color: '#cbd5e1' }}>Enable Semantic Fallback</span>
                </div>
            </section>
        </div>
    );

    const renderNetwork = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>
                <h3 className="section-title">
                    <Globe size={20} /> Connectivity
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <div className="toggle-item luxury">
                        <div className="toggle-info">
                            <span className="toggle-label">Public Mode (Expose LAN)</span>
                            <span className="toggle-desc">Allow devices on your network to access this dashboard.</span>
                        </div>
                        <input type="checkbox" className="luxury-checkbox"
                            checked={config.frontend?.public_mode}
                            onChange={(e) => updateNestedValue('frontend.public_mode', e.target.checked)}
                        />
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : '1fr 1fr', gap: '20px', marginTop: '16px' }}>
                        <div className="form-group">
                            <label>Portal Port</label>
                            <input type="number" className="input-field"
                                value={config.frontend?.port || 5173}
                                onChange={(e) => updateNestedValue('frontend.port', parseInt(e.target.value))}
                            />
                        </div>
                        <div className="form-group">
                            <label>API Port</label>
                            <input type="number" className="input-field"
                                value={config.interfaces?.server?.port || 8000}
                                onChange={(e) => updateNestedValue('interfaces.server.port', parseInt(e.target.value))}
                            />
                        </div>
                    </div>

                    <div className="form-group" style={{ marginTop: '16px' }}>
                        <label>CORS Allowed Origins (Comma separated)</label>
                        <input
                            type="text"
                            className="input-field"
                            value={(config.interfaces?.server?.cors_origins || []).join(', ')}
                            onChange={(e) => updateNestedValue('interfaces.server.cors_origins', e.target.value.split(',').map(s => s.trim()))}
                            placeholder="e.g. http://localhost:5173, http://192.168.1.50:5173"
                        />
                    </div>
                </div>
            </section>
        </div>
    );

    const renderMedia = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>
                <h3 className="section-title">
                    <Play size={20} /> Media & Content
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
                    <div className="toggle-item luxury">
                        <div className="toggle-info">
                            <span className="toggle-label">Playback Enabled</span>
                            <span className="toggle-desc">Global toggle for all media playback features.</span>
                        </div>
                        <input type="checkbox" className="luxury-checkbox"
                            checked={config.playback?.enabled ?? true}
                            onChange={(e) => updateNestedValue('playback.enabled', e.target.checked)}
                        />
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : '1fr 1fr', gap: '24px' }}>
                        <div className="form-group">
                            <label>Cache TTL (Hours)</label>
                            <input type="number" className="input-field"
                                value={config.playback?.ttl_hours || 24}
                                onChange={(e) => updateNestedValue('playback.ttl_hours', parseInt(e.target.value))}
                            />
                        </div>
                        <div className="form-group">
                            <label>Max Storage (MB)</label>
                            <input type="number" className="input-field"
                                value={config.playback?.max_total_mb || 512}
                                onChange={(e) => updateNestedValue('playback.max_total_mb', parseInt(e.target.value))}
                            />
                        </div>
                    </div>

                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '20px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <h4 style={{ fontSize: '14px', fontWeight: '700', marginBottom: '16px', color: 'var(--accent-color)' }}>Persistence Strategy</h4>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div className="flex-between">
                                <span style={{ fontSize: '13px' }}>General Persistence</span>
                                <input type="checkbox" className="luxury-checkbox"
                                    checked={config.playback?.persist ?? true}
                                    onChange={(e) => updateNestedValue('playback.persist', e.target.checked)}
                                />
                            </div>
                            <div className="flex-between">
                                <span style={{ fontSize: '13px' }}>Persist on Success</span>
                                <input type="checkbox" className="luxury-checkbox"
                                    checked={config.playback?.persist_on_success ?? true}
                                    onChange={(e) => updateNestedValue('playback.persist_on_success', e.target.checked)}
                                />
                            </div>
                            <div className="flex-between">
                                <span style={{ fontSize: '13px' }}>Persist on Error</span>
                                <input type="checkbox" className="luxury-checkbox"
                                    checked={config.playback?.persist_on_error ?? true}
                                    onChange={(e) => updateNestedValue('playback.persist_on_error', e.target.checked)}
                                />
                            </div>
                        </div>
                    </div>
                </div>
            </section>
        </div>
    );

    const renderInterfaces = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>
                <h3 className="section-title">
                    <Monitor size={20} /> Messaging Bridges
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '24px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                            <div>
                                <h4 style={{ fontSize: '18px', fontWeight: '700' }}>Telegram</h4>
                                <p style={{ fontSize: '13px', color: '#64748b' }}>Connect your agent to a Telegram Bot.</p>
                            </div>
                            <input type="checkbox" className="luxury-checkbox"
                                checked={config.interfaces?.telegram?.enabled}
                                onChange={(e) => updateNestedValue('interfaces.telegram.enabled', e.target.checked)}
                            />
                        </div>

                        {config.interfaces?.telegram?.enabled && (
                            <div className="form-group">
                                <label>Bot Token</label>
                                <div style={{ position: 'relative' }}>
                                    <input
                                        type={showSecrets['telegram_token'] ? 'text' : 'password'}
                                        className="input-field"
                                        style={{ paddingRight: '44px' }}
                                        value={config.interfaces?.telegram?.token || ''}
                                        onChange={(e) => updateNestedValue('interfaces.telegram.token', e.target.value)}
                                        placeholder="Paste your BotFather token here"
                                    />
                                    <button
                                        onClick={() => toggleSecret('telegram_token')}
                                        className="icon-btn"
                                        style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', opacity: 0.5 }}
                                    >
                                        {showSecrets['telegram_token'] ? <EyeOff size={18} /> : <Eye size={18} />}
                                    </button>
                                </div>
                            </div>
                        )}
                        <p style={{ marginTop: '16px', fontSize: '12px', color: '#475569' }}>
                            Future integrations: Discord, WhatsApp (Coming Soon)
                        </p>
                    </div>
                </div>
            </section>
        </div>
    );

    const renderSkills = () => (
        <div className="animate-fade-in">
            <section className="glass" style={{ padding: '32px', borderRadius: '8px', textAlign: 'center' }}>
                <Puzzle size={48} style={{ margin: '0 auto 20px', color: 'var(--accent-color)' }} />
                <h3 style={{ fontSize: '24px', fontWeight: '800', marginBottom: '16px' }}>Cognitive Capabilities</h3>
                <p style={{ color: '#94a3b8', marginBottom: '32px' }}>
                    Skill management has been moved to the dedicated Skills Hub for an improved experience.
                </p>
                <div style={{ display: 'flex', justifyContent: 'center' }}>
                    <Link to="/skills" className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 24px' }}>
                        <ExternalLink size={18} /> Open Skills Hub
                    </Link>
                </div>
            </section>
        </div>
    );

    const renderDebug = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '20px', height: '100%', minHeight: '600px', paddingBottom: '40px' }}>
            <div className="glass" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 24px', borderRadius: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <select
                        className="input-field"
                        style={{ width: '180px', height: '36px', padding: '0 12px', fontSize: '13px' }}
                        value={activeLogSource}
                        onChange={(e) => {
                            setActiveLogSource(e.target.value);
                            setLogs([]);
                        }}
                    >
                        {logSources.map(src => <option key={src} value={src}>{src}</option>)}
                    </select>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(0,0,0,0.2)', padding: '4px 12px', borderRadius: '20px', border: '1px solid rgba(255,255,255,0.05)' }}>
                        <div className={`w-2 h-2 rounded-full ${isStreaming ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
                        <span style={{ fontSize: '11px', fontWeight: '800', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                            {isStreaming ? 'Live Stream' : 'Paused'}
                        </span>
                    </div>
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                    <button onClick={() => setIsStreaming(!isStreaming)} className="icon-btn" style={{ padding: '8px' }} title={isStreaming ? "Pause" : "Resume"}>
                        {isStreaming ? <Pause size={18} /> : <Play size={18} />}
                    </button>
                    <button onClick={() => setLogs([])} className="icon-btn" style={{ padding: '8px' }} title="Clear Logs">
                        <RefreshCw size={18} />
                    </button>
                    <button onClick={downloadLogs} className="icon-btn" style={{ padding: '8px' }} title="Download">
                        <Download size={18} />
                    </button>
                </div>
            </div>

            <div
                ref={logScrollRef}
                className="terminal-view custom-scrollbar"
                style={{
                    flex: 1,
                    background: '#050505',
                    borderRadius: '8px',
                    padding: '24px',
                    overflowY: 'auto',
                    fontFamily: '"Fira Code", monospace',
                    fontSize: '13px',
                    lineHeight: '1.6',
                    border: '1px solid rgba(255,255,255,0.05)',
                    boxShadow: 'inset 0 2px 10px rgba(0,0,0,0.5)'
                }}
            >
                {logs.length === 0 && <div style={{ color: 'var(--text-muted)', textAlign: 'center', marginTop: '40px' }}>Waiting for system events...</div>}
                {logs.map((log, i) => {
                    const isError = log.includes('ERROR');
                    const isWarning = log.includes('WARNING');
                    const isInfo = log.includes('INFO');

                    return (
                        <div key={i} style={{
                            color: isError ? '#ff5f56' : isWarning ? '#ffbd2e' : isInfo ? '#27c93f' : '#e0e0e0',
                            borderBottom: '1px solid rgba(255,255,255,0.03)',
                            padding: '12px 0',
                            whiteSpace: 'pre-wrap',
                            display: 'flex',
                            gap: '16px'
                        }}>
                            <span style={{ color: 'rgba(255,255,255,0.1)', minWidth: '40px', textAlign: 'right', userSelect: 'none' }}>{i + 1}</span>
                            <div style={{ flex: 1 }}>{log}</div>
                        </div>
                    );
                })}
            </div>
        </div>
    );

    const getGeolocation = () => {
        if (!navigator.geolocation) {
            toast.error("Geolocation is not supported by your browser");
            return;
        }
        toast.loading("Detecting location...", { id: 'geo' });
        navigator.geolocation.getCurrentPosition(
            async (position) => {
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                updateNestedValue('location.default.lat', lat.toFixed(6).toString());
                updateNestedValue('location.default.lon', lon.toFixed(6).toString());

                // Reverse geocoding for city/state/country info
                try {
                    const response = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}`);
                    const data = await response.json();
                    if (data.address) {
                        updateNestedValue('location.default.city', data.address.city || data.address.town || data.address.village || "");
                        updateNestedValue('location.default.state', data.address.state || "");
                        updateNestedValue('location.default.country', data.address.country || "");
                    }
                } catch (err) { console.warn("Reverse geocode failed", err); }

                toast.success("Location updated!", { id: 'geo' });
            },
            (err) => {
                console.error(err);
                toast.error("Unable to retrieve location", { id: 'geo' });
            }
        );
    };

    const renderWeather = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>
                <h3 className="section-title">
                    <CloudSun size={20} /> Environmental Data
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '-12px' }}>
                        <button onClick={getGeolocation} className="btn-ghost" style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Globe size={14} /> Get Current Location
                        </button>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : '1fr 1fr', gap: '20px' }}>
                        <div className="form-group">
                            <label>Latitude</label>
                            <input type="text" className="input-field"
                                value={config.location?.default?.lat || ''}
                                onChange={(e) => updateNestedValue('location.default.lat', e.target.value)}
                            />
                        </div>
                        <div className="form-group">
                            <label>Longitude</label>
                            <input type="text" className="input-field"
                                value={config.location?.default?.lon || ''}
                                onChange={(e) => updateNestedValue('location.default.lon', e.target.value)}
                            />
                        </div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : '1fr 1fr 1fr', gap: '20px' }}>
                        <div className="form-group">
                            <label>City</label>
                            <input type="text" className="input-field"
                                value={config.location?.default?.city || ''}
                                onChange={(e) => updateNestedValue('location.default.city', e.target.value)}
                            />
                        </div>
                        <div className="form-group">
                            <label>State</label>
                            <input type="text" className="input-field"
                                value={config.location?.default?.state || ''}
                                onChange={(e) => updateNestedValue('location.default.state', e.target.value)}
                            />
                        </div>
                        <div className="form-group">
                            <label>Country</label>
                            <input type="text" className="input-field"
                                value={config.location?.default?.country || ''}
                                onChange={(e) => updateNestedValue('location.default.country', e.target.value)}
                            />
                        </div>
                    </div>
                </div>
            </section>
        </div>
    );

    const renderSecurity = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                    <h3 className="section-title" style={{ marginBottom: 0 }}>
                        <Shield size={20} /> Vault (Environment Secrets)
                    </h3>
                    <button onClick={() => {
                        const newKey = prompt("Enter new ENV variable name (e.g. ENV_MY_API_KEY):");
                        if (newKey) {
                            setEnvData(prev => ({ ...prev, [newKey]: "" }));
                        }
                    }} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 12px' }}>
                        <Plus size={14} style={{ marginRight: '6px' }} /> Add Secret
                    </button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {Object.entries(envData || {}).map(([key, value]) => (
                        <div key={key} className="form-group">
                            <label style={{ fontSize: '12px', color: '#64748b' }}>{key}</label>
                            <div style={{ position: 'relative' }}>
                                <input
                                    type={showSecrets[key] ? 'text' : 'password'}
                                    className="input-field"
                                    style={{ paddingRight: '44px' }}
                                    value={value}
                                    onChange={(e) => {
                                        const newData = { ...(envData || {}), [key]: e.target.value };
                                        setEnvData(newData);
                                    }}
                                />
                                <button
                                    onClick={() => toggleSecret(key)}
                                    className="icon-btn"
                                    style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', opacity: 0.5 }}
                                >
                                    {showSecrets[key] ? <EyeOff size={18} /> : <Eye size={18} />}
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    );

    const renderLLM = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>
                <h3 className="section-title">
                    <Cpu size={20} /> Chat & Reasoning (Cortex)
                </h3>
                <ModelPoolManager
                    modality="chat"
                    currentPool={config.cortex?.chat || []}
                    onPoolUpdated={(newPool) => updateNestedValue('cortex.chat', newPool)}
                />
            </section>

            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>
                <h3 className="section-title">
                    <Eye size={20} /> Vision & Perception
                </h3>
                <ModelPoolManager
                    modality="vision"
                    currentPool={config.cortex?.vision || []}
                    onPoolUpdated={(newPool) => updateNestedValue('cortex.vision', newPool)}
                />
            </section>
        </div>
    );

    return (
        <div className="animate-fade-in flex-1" style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', height: '100%', gap: '16px', maxHeight: '100%', overflow: 'hidden' }}>
            {/* Sidebar Navigation */}
            <aside className="glass custom-scrollbar" style={{
                width: isMobile ? '100%' : (isTabsCollapsed ? '60px' : '260px'),
                height: isMobile ? 'auto' : '100%',
                display: 'flex',
                flexDirection: isMobile ? 'row' : 'column',
                overflowX: isMobile ? 'auto' : 'hidden',
                overflowY: isMobile ? 'hidden' : 'auto',
                transition: 'var(--transition)',
                borderRadius: '8px',
                flexShrink: 0,
                padding: isMobile ? '4px' : '0'
            }}>
                {!isMobile && (
                    <div className="glass" style={{
                        margin: '12px 12px 12px 12px',
                        padding: isTabsCollapsed ? '8px 0' : '8px 14px',
                        borderRadius: '8px',
                        display: 'flex',
                        flexDirection: isTabsCollapsed ? 'column' : 'row',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '8px',
                        background: 'rgba(255,255,255,0.03)'
                    }}>
                        {!isTabsCollapsed && <h3 style={{ fontSize: '14px', fontWeight: 'bold' }}>Categories</h3>}
                        <button
                            onClick={() => setIsTabsCollapsed(!isTabsCollapsed)}
                            className="btn-ghost"
                            style={{ padding: '4px' }}
                            title={isTabsCollapsed ? "Expand" : "Collapse"}
                        >
                            {isTabsCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
                        </button>
                    </div>
                )}

                <div className={isMobile ? "flex items-center gap-1" : "custom-scrollbar"} style={{
                    flex: 1,
                    padding: isMobile ? '4px' : '12px',
                    overflowX: isMobile ? 'auto' : 'hidden',
                    overflowY: isMobile ? 'hidden' : 'auto',
                    display: 'flex',
                    flexDirection: isMobile ? 'row' : 'column',
                    gap: '4px'
                }}>
                    {tabs.map(tab => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
                            style={{
                                justifyContent: (isTabsCollapsed && !isMobile) ? 'center' : 'flex-start',
                                padding: (isTabsCollapsed && !isMobile) ? '12px' : '10px 16px',
                                minHeight: isMobile ? '36px' : '44px',
                                borderRadius: '10px',
                                width: isMobile ? 'auto' : '100%',
                                whiteSpace: 'nowrap'
                            }}
                            title={tab.label}
                        >
                            <tab.icon size={18} style={{ flexShrink: 0 }} />
                            {(!isTabsCollapsed || isMobile) && <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: isMobile ? '12px' : '14px' }}>{tab.label}</span>}
                        </button>
                    ))}
                </div>
            </aside>

            {/* Main Content Area */}
            <main className="glass" style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                position: 'relative',
                overflow: 'hidden',
                borderRadius: '16px'
            }}>
                {renderHeader()}

                <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '16px' : (isTablet ? '24px' : '32px') }} className="custom-scrollbar">
                    {activeTab === 'general' && renderGeneral()}
                    {activeTab === 'interfaces' && renderInterfaces()}
                    {activeTab === 'media' && renderMedia()}
                    {activeTab === 'network' && renderNetwork()}
                    {activeTab === 'llm' && renderLLM()}
                    {activeTab === 'skills' && renderSkills()}
                    {activeTab === 'stt' && (
                        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '16px' }}>
                                <h3 className="section-title"><Mic size={20} /> Speech Recognition (STT)</h3>
                                <ModelPoolManager
                                    modality="stt"
                                    currentPool={config.cortex?.audio?.stt || []}
                                    onPoolUpdated={(newPool) => updateNestedValue('cortex.audio.stt', newPool)}
                                />
                            </section>

                            <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '16px' }}>
                                <h3 className="section-title"><Play size={20} /> Speech Synthesis (TTS)</h3>
                                <ModelPoolManager
                                    modality="tts"
                                    currentPool={config.cortex?.audio?.tts || []}
                                    onPoolUpdated={(newPool) => updateNestedValue('cortex.audio.tts', newPool)}
                                />
                            </section>
                        </div>
                    )}
                    {activeTab === 'weather' && renderWeather()}
                    {activeTab === 'security' && renderSecurity()}
                    {activeTab === 'debug' && renderDebug()}
                    {activeTab === 'advanced' && (
                        <div className="animate-fade-in" style={{ height: '100%', minHeight: '600px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
                            <div className="glass" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 24px', borderRadius: '16px' }}>
                                <h3 className="section-title" style={{ marginBottom: 0 }}>
                                    <FileJson size={20} /> Master Schema
                                </h3>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                    {(() => {
                                        try {
                                            JSON.parse(rawJson);
                                            return <span className="status-pill online">Valid JSON</span>;
                                        } catch (e) {
                                            return <span className="status-pill offline">Invalid JSON</span>;
                                        }
                                    })()}
                                    <button
                                        onClick={() => {
                                            try {
                                                const pretty = JSON.stringify(JSON.parse(rawJson), null, 4);
                                                setRawJson(pretty);
                                                toast.success("JSON Formatted");
                                            } catch (e) {
                                                toast.error("Cannot format: Invalid JSON");
                                            }
                                        }}
                                        className="btn-ghost"
                                        style={{ fontSize: '12px', padding: '6px 12px' }}
                                    >
                                        Prettify
                                    </button>
                                </div>
                            </div>

                            <div className="glass" style={{
                                flex: 1,
                                display: 'flex',
                                borderRadius: '20px',
                                overflow: 'hidden',
                                border: '1px solid rgba(255,255,255,0.05)',
                                background: '#050505'
                            }}>
                                <div
                                    ref={lineNumbersRef}
                                    style={{
                                        padding: '24px 12px',
                                        background: 'rgba(255,255,255,0.02)',
                                        borderRight: '1px solid rgba(255,255,255,0.05)',
                                        color: 'rgba(255,255,255,0.15)',
                                        fontFamily: '"Fira Code", monospace',
                                        fontSize: '13px',
                                        lineHeight: '1.6',
                                        textAlign: 'right',
                                        minWidth: '45px',
                                        userSelect: 'none',
                                        overflow: 'hidden',
                                        whiteSpace: 'pre'
                                    }}
                                >
                                    {getLineNumbers()}
                                </div>
                                <textarea
                                    ref={editorRef}
                                    onScroll={handleScrollSync}
                                    className="custom-scrollbar"
                                    style={{
                                        flex: 1,
                                        height: '100%',
                                        background: 'transparent',
                                        border: 'none',
                                        outline: 'none',
                                        color: '#e0e0e0',
                                        padding: '24px',
                                        fontFamily: '"Fira Code", monospace',
                                        fontSize: '13px',
                                        lineHeight: '1.6',
                                        resize: 'none',
                                        whiteSpace: 'pre',
                                        overflowX: 'auto'
                                    }}
                                    value={rawJson}
                                    onChange={(e) => {
                                        setRawJson(e.target.value);
                                        try {
                                            const parsed = JSON.parse(e.target.value);
                                            setConfig(parsed);
                                        } catch { }
                                    }}
                                />
                            </div>
                        </div>
                    )}
                </div>
            </main>

            <style>{`
                .section-title {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    font-size: 20px;
                    font-weight: 800;
                    margin-bottom: 24px;
                }
                .form-group {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }
                .form-group label {
                    font-size: 13px;
                    font-weight: 700;
                    color: var(--text-muted);
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                }
                .input-field {
                    width: 100%;
                    padding: 12px 16px;
                    background: var(--bg-color);
                    border: 1px solid var(--card-border);
                    border-radius: 8px;
                    color: var(--text-main);
                    font-size: 14px;
                    transition: all 0.2s;
                }
                .input-field:focus {
                    outline: none;
                    border-color: var(--accent-color);
                    box-shadow: 0 0 0 4px var(--accent-glow);
                }
                .nav-item {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 14px 18px;
                    border-radius: 12px;
                    border: none;
                    background: transparent;
                    color: var(--text-muted);
                    font-size: 15px;
                    font-weight: 500;
                    transition: all 0.2s;
                    text-align: left;
                    width: 100%;
                    cursor: pointer;
                    flex-shrink: 0;
                }
                .flex-between {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                .nav-item:hover {
                    background: rgba(255,255,255,0.03);
                    color: #fff;
                }
                .nav-item.active {
                    background: rgba(59, 130, 246, 0.1);
                    color: var(--accent-color);
                    font-weight: 700;
                }
                .toggle-item {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 20px;
                    border-radius: 16px;
                    background: rgba(255,255,255,0.02);
                    border: 1px solid rgba(255,255,255,0.05);
                }
                .toggle-label {
                    display: block;
                    font-weight: 700;
                    font-size: 15px;
                }
                .toggle-desc {
                    display: block;
                    font-size: 12px;
                    color: var(--text-muted);
                    margin-top: 2px;
                }
                .divider {
                    height: 1px;
                    background: rgba(255,255,255,0.05);
                    margin: 8px 0;
                }
                .skill-card {
                    padding: 16px;
                    border-radius: 14px;
                    transition: all 0.2s;
                }
                .skill-card:hover {
                    background: rgba(255,255,255,0.05);
                    transform: translateY(-2px);
                }
                .env-row {
                    display: grid;
                    grid-template-columns: 200px 1fr;
                    gap: 20px;
                    align-items: center;
                }
                .env-label {
                    font-family: 'Fira Code', monospace;
                    font-size: 13px;
                    color: var(--text-muted);
                }
                .status-pill {
                    padding: 4px 10px;
                    border-radius: 20px;
                    font-size: 11px;
                    font-weight: 800;
                    text-transform: uppercase;
                }
                .status-pill.online { background: rgba(34, 197, 94, 0.1); color: #4ade80; }
                .status-pill.offline { background: rgba(239, 68, 68, 0.1); color: #f87171; }
                
                .custom-scrollbar::-webkit-scrollbar { width: 6px; }
                .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
                .custom-scrollbar::-webkit-scrollbar-thumb { 
                    background: rgba(255,255,255,0.1); 
                    border-radius: 10px; 
                }
            `}</style>
        </div>
    );
};

export default Settings;
