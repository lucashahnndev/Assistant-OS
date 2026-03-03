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
    Building2,
    Zap,
    Puzzle,
    ExternalLink,
    ChevronLeft,
    ChevronRight,
    ChevronDown,
    ChevronUp,
    Plus,
    Trash2,
    Link2,
    Settings2
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
    const [envKeys, setEnvKeys] = useState([]);
    const [externalCatalog, setExternalCatalog] = useState([]);
    const [externalCatalogLoading, setExternalCatalogLoading] = useState(false);
    const [externalTab, setExternalTab] = useState('accounts');
    const [editingProviderKey, setEditingProviderKey] = useState('');
    const [externalSecretEditor, setExternalSecretEditor] = useState({ target: '', key: '', value: '' });
    const [selectedConnectProvider, setSelectedConnectProvider] = useState('');
    const [connectingProvider, setConnectingProvider] = useState('');
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

    const withExternalAccountsDefaults = (sourceConfig) => {
        const next = sourceConfig && typeof sourceConfig === 'object' ? { ...sourceConfig } : {};
        const external = next.external_accounts && typeof next.external_accounts === 'object' ? { ...next.external_accounts } : {};
        const providers = external.providers && typeof external.providers === 'object' ? { ...external.providers } : {};
        const accounts = Array.isArray(external.accounts) ? [...external.accounts] : [];

        next.external_accounts = {
            enabled: external.enabled ?? true,
            providers,
            accounts
        };
        return next;
    };

    useEffect(() => {
        fetchConfig();
        fetchEnv();
        fetchLogSources();
        return () => stopLogStream();
    }, []);

    useEffect(() => {
        if (activeTab === 'external_accounts') {
            fetchExternalProviders();
            fetchEnvKeys();
            fetchLinkedAccounts();
        }
    }, [activeTab]);

    useEffect(() => {
        const onOAuthMessage = (event) => {
            const data = event?.data;
            if (!data || data.type !== 'external-oauth-callback') return;

            const providerKey = String(data.provider || '').trim().toLowerCase();
            if (!providerKey) return;

            setConfig((prev) => {
                if (!prev || typeof prev !== 'object') return prev;
                const next = { ...prev };
                if (!next.external_accounts || typeof next.external_accounts !== 'object') {
                    next.external_accounts = { enabled: true, providers: {}, accounts: [] };
                }
                const list = Array.isArray(next.external_accounts.accounts) ? [...next.external_accounts.accounts] : [];
                const status = String(data.status || '').toLowerCase();
                const pendingIndex = list.findIndex(
                    (item) =>
                        String(item?.provider || '').toLowerCase() === providerKey &&
                        String(item?.status || '').toLowerCase() === 'pending'
                );

                if (pendingIndex >= 0) {
                    const profile = data?.profile || {};
                    const accountLabel =
                        profile?.email ||
                        profile?.name ||
                        (status === 'success' ? 'OAuth account connected' : (data.error || 'OAuth failed'));
                    list[pendingIndex] = {
                        ...list[pendingIndex],
                        status: status === 'success' ? 'connected' : 'error',
                        account: accountLabel,
                        profile: status === 'success' ? {
                            name: profile?.name || '',
                            email: profile?.email || '',
                            picture: profile?.picture || '',
                            locale: profile?.locale || ''
                        } : undefined,
                        connected_at: new Date().toISOString()
                    };
                } else {
                    const profile = data?.profile || {};
                    const accountLabel =
                        profile?.email ||
                        profile?.name ||
                        (status === 'success' ? 'OAuth account connected' : (data.error || 'OAuth failed'));
                    list.push({
                        id: `acc_${providerKey}_${Date.now()}`,
                        provider: providerKey,
                        account: accountLabel,
                        status: status === 'success' ? 'connected' : 'error',
                        profile: status === 'success' ? {
                            name: profile?.name || '',
                            email: profile?.email || '',
                            picture: profile?.picture || '',
                            locale: profile?.locale || ''
                        } : undefined,
                        connected_at: new Date().toISOString()
                    });
                }

                next.external_accounts.accounts = list;
                setRawJson(JSON.stringify(next, null, 2));
                return next;
            });

            if (String(data.status || '').toLowerCase() === 'success') {
                toast.success(`${providerKey} connected successfully.`);
                fetchLinkedAccounts();
            } else {
                toast.error(`OAuth failed for ${providerKey}: ${data.error || 'unknown error'}`);
            }
        };

        window.addEventListener('message', onOAuthMessage);
        return () => window.removeEventListener('message', onOAuthMessage);
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
            const normalized = withExternalAccountsDefaults(data);
            setConfig(normalized);
            setRawJson(JSON.stringify(normalized, null, 2));
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

    const fetchEnvKeys = async () => {
        try {
            const data = await api.get('/models/env-keys');
            setEnvKeys(Array.isArray(data?.keys) ? data.keys : []);
        } catch (err) {
            console.error(err);
            setEnvKeys([]);
        }
    };

    const fetchExternalProviders = async () => {
        setExternalCatalogLoading(true);
        try {
            const data = await api.get('/external-accounts/providers');
            setExternalCatalog(Array.isArray(data?.providers) ? data.providers : []);
        } catch (err) {
            console.error(err);
            setExternalCatalog([]);
        } finally {
            setExternalCatalogLoading(false);
        }
    };

    const fetchLinkedAccounts = async () => {
        try {
            const data = await api.get('/external-accounts/connections');
            const linked = Array.isArray(data?.connections) ? data.connections : [];
            setConfig((prev) => {
                if (!prev || typeof prev !== 'object') return prev;
                const next = { ...prev };
                if (!next.external_accounts || typeof next.external_accounts !== 'object') {
                    next.external_accounts = { enabled: true, providers: {}, accounts: [] };
                }
                const pending = Array.isArray(next.external_accounts.accounts)
                    ? next.external_accounts.accounts.filter((item) => String(item?.status || '').toLowerCase() === 'pending')
                    : [];
                next.external_accounts.accounts = [...linked, ...pending];
                setRawJson(JSON.stringify(next, null, 2));
                return next;
            });
        } catch (err) {
            console.error(err);
        }
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
        { id: 'external_accounts', label: 'External Accounts', icon: Link2 },
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
                            placeholder="e.g. Assistant, Jarvis..."
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

    const renderExternalAccounts = () => {
        const providers = config.external_accounts?.providers || {};
        const entries = Object.entries(providers);
        const accounts = Array.isArray(config.external_accounts?.accounts) ? config.external_accounts.accounts : [];
        const temporarilyHiddenProviders = new Set(['microsoft', 'aws', 'cloudflare']);
        const visibleExternalCatalog = (externalCatalog || []).filter(
            (item) => !temporarilyHiddenProviders.has(String(item?.key || '').toLowerCase())
        );
        const providerCatalogByKey = (externalCatalog || []).reduce((acc, item) => {
            const key = String(item?.key || '').toLowerCase();
            if (key) acc[key] = item;
            return acc;
        }, {});
        const getProviderVisual = (providerKey) => {
            const key = String(providerKey || '').toLowerCase();
            if (key === 'google') return { color: '#34d399', iconUrl: 'https://www.google.com/s2/favicons?domain=google.com&sz=64' };
            if (key === 'youtube') return { color: '#ef4444', iconUrl: 'https://www.google.com/s2/favicons?domain=youtube.com&sz=64' };
            if (key === 'maps' || key === 'google_maps') return { color: '#22c55e', iconUrl: 'https://www.google.com/s2/favicons?domain=maps.google.com&sz=64' };
            if (key === 'microsoft') return { color: '#60a5fa', iconUrl: 'https://www.google.com/s2/favicons?domain=microsoft.com&sz=64' };
            if (key === 'aws') return { color: '#f59e0b', iconUrl: 'https://www.google.com/s2/favicons?domain=aws.amazon.com&sz=64' };
            if (key === 'cloudflare') return { color: '#f97316', iconUrl: 'https://www.google.com/s2/favicons?domain=cloudflare.com&sz=64' };
            return { color: '#a78bfa', iconUrl: '' };
        };
        const ProviderBrandIcon = ({ providerKey, size = 14 }) => {
            const visual = getProviderVisual(providerKey);
            if (visual.iconUrl) {
                return (
                    <img
                        src={visual.iconUrl}
                        alt={`${providerKey} icon`}
                        width={size}
                        height={size}
                        style={{ width: `${size}px`, height: `${size}px`, borderRadius: '4px', objectFit: 'cover' }}
                        onError={(e) => {
                            e.currentTarget.style.display = 'none';
                        }}
                    />
                );
            }
            return <Link2 size={size} color={visual.color} />;
        };
        const configuredProviderKeys = entries.map(([key]) => key);
        const connectProviders = configuredProviderKeys
            .map((key) => ({ key, meta: providerCatalogByKey[String(key).toLowerCase()] || null }))
            .filter((item) => {
                const key = String(item?.key || '').toLowerCase();
                const modes = Array.isArray(item?.meta?.auth_modes) ? item.meta.auth_modes.map((m) => String(m).toLowerCase()) : [];
                if (temporarilyHiddenProviders.has(key)) return false;
                if (!item?.meta) return false; // only providers backed by plugins
                if (key === 'youtube') return false; // YouTube OAuth flows should piggyback Google account
                return modes.includes('oauth2');
            });
        const secretFieldMap = {
            client_id: { label: 'Client ID Ref', placeholder: 'ENV_PROVIDER_CLIENT_ID' },
            client_secret: { label: 'Client Secret Ref', placeholder: 'ENV_PROVIDER_CLIENT_SECRET' },
            api_key_ref: { label: 'API Key Ref', placeholder: 'ENV_PROVIDER_API_KEY' }
        };
        const getProviderExtraFields = (providerKey) => {
            const key = String(providerKey || '').toLowerCase();
            if (key === 'microsoft') {
                return [
                    { name: 'tenant', label: 'Tenant', placeholder: 'common | organizations | <tenant-id>' }
                ];
            }
            if (key === 'aws') {
                return [
                    { name: 'region', label: 'Region', placeholder: 'us-east-1' },
                    { name: 'role_arn', label: 'Role ARN', placeholder: 'arn:aws:iam::123456789012:role/MyRole' }
                ];
            }
            if (key === 'cloudflare') {
                return [
                    { name: 'account_id', label: 'Account ID', placeholder: 'Cloudflare account id' }
                ];
            }
            return [];
        };

        const addProvider = () => {
            const providerKey = prompt("Provider key (example: google_drive):");
            if (!providerKey) return;
            const trimmed = providerKey.trim().toLowerCase();
            if (!trimmed) return;
            if (providers[trimmed]) {
                toast.error("Provider already exists.");
                return;
            }

            updateNestedValue(`external_accounts.providers.${trimmed}`, {
                enabled: false,
                auth_mode: "oauth2",
                client_id: "",
                client_secret: "",
                scopes: [],
                redirect_uri: ""
            });
        };

        const addProviderFromPlugin = (plugin) => {
            if (!plugin?.key) return;
            if (providers[plugin.key]) {
                toast.error("Provider already exists.");
                return;
            }
            updateNestedValue(`external_accounts.providers.${plugin.key}`, {
                enabled: false,
                auth_mode: Array.isArray(plugin.auth_modes) && plugin.auth_modes.length > 0 ? plugin.auth_modes[0] : "oauth2",
                client_id: "",
                client_secret: "",
                scopes: Array.isArray(plugin.default_scopes) ? plugin.default_scopes : [],
                redirect_uri: "",
                tenant: plugin.key === "microsoft" ? "common" : ""
            });
        };

        const removeProvider = (providerKey) => {
            const nextProviders = { ...providers };
            delete nextProviders[providerKey];
            updateNestedValue('external_accounts.providers', nextProviders);
        };

        const suggestedEnvName = (providerKey, fieldName) => {
            const providerToken = String(providerKey || 'provider').toUpperCase().replace(/[^A-Z0-9]+/g, '_');
            const fieldToken = String(fieldName || 'KEY').toUpperCase().replace(/[^A-Z0-9]+/g, '_');
            return `ENV_${providerToken}_${fieldToken}`;
        };

        const openSecretEditor = (target, providerKey, fieldName) => {
            const current = providers?.[providerKey]?.[fieldName];
            setExternalSecretEditor({
                target,
                key: typeof current === 'string' && current.startsWith('ENV_') ? current : suggestedEnvName(providerKey, fieldName),
                value: ''
            });
        };

        const createSecretAndBind = async (targetPath) => {
            const key = String(externalSecretEditor.key || '').trim();
            const value = String(externalSecretEditor.value || '').trim();
            if (!key || !value) {
                toast.error("Key and value are required.");
                return;
            }
            try {
                const res = await api.post('/models/env-keys', { key, value });
                if (res?.success) {
                    updateNestedValue(targetPath, key);
                    setEnvData(prev => ({ ...(prev || {}), [key]: value }));
                    await fetchEnvKeys();
                    setExternalSecretEditor({ target: '', key: '', value: '' });
                    toast.success(`Secret ${key} created and linked.`);
                }
            } catch (err) {
                toast.error(err.message || 'Failed to create secret');
            }
        };

        const renderSecretRefField = (providerKey, provider, fieldName) => {
            const targetPath = `external_accounts.providers.${providerKey}.${fieldName}`;
            const fieldMeta = secretFieldMap[fieldName] || { label: fieldName, placeholder: 'ENV_KEY' };
            const currentValue = provider?.[fieldName] || '';
            const options = Array.from(new Set([...(envKeys || []), ...(currentValue ? [currentValue] : [])]));
            const creating = externalSecretEditor.target === targetPath;

            return (
                <div key={`${providerKey}_${fieldName}`} className="form-group" style={{ background: 'rgba(var(--accent-rgb), 0.05)', padding: '14px', borderRadius: '10px', border: '1px solid rgba(var(--accent-rgb), 0.2)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Shield size={14} color="var(--accent-color)" /> {fieldMeta.label}
                        </label>
                        <button
                            onClick={() => creating ? setExternalSecretEditor({ target: '', key: '', value: '' }) : openSecretEditor(targetPath, providerKey, fieldName)}
                            className="btn-ghost"
                            style={{ fontSize: '11px', padding: '2px 8px', color: 'var(--accent-color)' }}
                        >
                            {creating ? 'Cancel' : '+ Create New Key'}
                        </button>
                    </div>

                    {!creating && (
                        <select
                            className="input-field"
                            value={currentValue}
                            onChange={(e) => updateNestedValue(targetPath, e.target.value)}
                        >
                            <option value="">-- Select Environment Key --</option>
                            {options.map((key) => (
                                <option key={key} value={key}>{key}</option>
                            ))}
                        </select>
                    )}

                    {creating && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px' }}>
                            <input
                                type="text"
                                className="input-field"
                                value={externalSecretEditor.key}
                                placeholder={fieldMeta.placeholder}
                                onChange={(e) => setExternalSecretEditor(prev => ({ ...prev, key: e.target.value }))}
                            />
                            <input
                                type="password"
                                className="input-field"
                                value={externalSecretEditor.value}
                                placeholder="Paste the secret value here..."
                                onChange={(e) => setExternalSecretEditor(prev => ({ ...prev, value: e.target.value }))}
                            />
                            <button
                                onClick={() => createSecretAndBind(targetPath)}
                                className="btn-primary"
                                style={{ alignSelf: 'flex-start', fontSize: '12px', padding: '6px 12px' }}
                            >
                                Save to Vault
                            </button>
                        </div>
                    )}
                </div>
            );
        };

        const startOAuthConnection = async () => {
            const providerKey = String(selectedConnectProvider || '').trim().toLowerCase();
            if (!providerKey) {
                toast.error("Select a provider first.");
                return;
            }
            const providerDraft = providers?.[providerKey] || {};
            const authMode = String(providerDraft?.auth_mode || '').trim().toLowerCase();
            const redirectUri = String(providerDraft?.redirect_uri || '').trim();
            const clientRef = String(providerDraft?.client_id || '').trim();
            if (authMode && authMode !== 'oauth2') {
                toast.error(`Provider ${providerKey} is not in oauth2 mode.`);
                return;
            }
            if (!redirectUri || !clientRef) {
                toast.error(`Configure ${providerKey} client_id and redirect_uri in Providers before connecting.`);
                return;
            }
            setConnectingProvider(providerKey);
            try {
                // Persist latest in-memory settings so auth/start uses the same config shown in UI.
                await api.post('/system/config', config);
                const data = await api.post('/external-accounts/auth/start', {
                    provider_key: providerKey,
                    state: `settings_${Date.now()}`
                });
                const url = data?.authorize_url;
                if (!url) {
                    throw new Error("Provider did not return authorize URL.");
                }
                const popup = window.open(url, `oauth_${providerKey}`, 'popup=yes,width=560,height=760');
                if (!popup) {
                    // Fallback: open in same tab to avoid losing opener communication.
                    window.location.href = url;
                    return;
                }

                const hasPending = accounts.some(
                    (item) => String(item?.provider || '').toLowerCase() === providerKey && String(item?.status || '').toLowerCase() === 'pending'
                );
                if (!hasPending) {
                    const next = [...accounts, {
                        id: `acc_${providerKey}_${Date.now()}`,
                        provider: providerKey,
                        account: 'OAuth authorization pending',
                        status: 'pending',
                        connected_at: new Date().toISOString()
                    }];
                    updateNestedValue('external_accounts.accounts', next);
                }
                toast.success(`OAuth started for ${providerKey}. Complete it in the opened window.`);
            } catch (err) {
                toast.error(err.message || `Failed to start OAuth for ${providerKey}.`);
            } finally {
                setConnectingProvider('');
            }
        };

        const removeLinkedAccount = async (accountId) => {
            try {
                if (typeof accountId === 'number') {
                    await api.delete(`/external-accounts/connections/${accountId}`);
                    await fetchLinkedAccounts();
                    toast.success('Linked account removed.');
                    return;
                }
            } catch (err) {
                toast.error(err.message || 'Failed to remove linked account');
                return;
            }

            const next = accounts.filter((item) => item?.id !== accountId);
            updateNestedValue('external_accounts.accounts', next);
        };

        return (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                <section className="glass" style={{ padding: isMobile ? '20px' : '32px', borderRadius: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                        <h3 className="section-title" style={{ marginBottom: 0 }}>
                            <Link2 size={20} /> External Accounts
                        </h3>
                        <div style={{ display: 'flex', gap: '8px' }}>
                            <button
                                onClick={() => setExternalTab('accounts')}
                                className="btn-ghost"
                                style={{ fontSize: '12px', padding: '6px 12px', borderColor: externalTab === 'accounts' ? 'var(--accent-color)' : undefined, color: externalTab === 'accounts' ? 'var(--accent-color)' : undefined }}
                            >
                                Accounts
                            </button>
                            <button
                                onClick={() => setExternalTab('providers')}
                                className="btn-ghost"
                                style={{ fontSize: '12px', padding: '6px 12px', borderColor: externalTab === 'providers' ? 'var(--accent-color)' : undefined, color: externalTab === 'providers' ? 'var(--accent-color)' : undefined }}
                            >
                                Providers
                            </button>
                        </div>
                    </div>

                    <div className="toggle-item luxury" style={{ marginBottom: '16px' }}>
                        <div className="toggle-info">
                            <span className="toggle-label">Enable External Accounts</span>
                            <span className="toggle-desc">Master switch for OAuth/API integrations.</span>
                        </div>
                        <input
                            type="checkbox"
                            className="luxury-checkbox"
                            checked={config.external_accounts?.enabled ?? true}
                            onChange={(e) => updateNestedValue('external_accounts.enabled', e.target.checked)}
                        />
                    </div>

                    {externalTab === 'accounts' && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px', padding: '14px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                                    <strong style={{ fontSize: '13px' }}>Connect New Account</strong>
                                    <button
                                        onClick={startOAuthConnection}
                                        className="btn-primary"
                                        disabled={!selectedConnectProvider || connectingProvider !== ''}
                                        style={{ fontSize: '12px', padding: '6px 12px' }}
                                    >
                                        {connectingProvider ? 'Connecting...' : 'Connect with OAuth'}
                                    </button>
                                </div>
                                {connectProviders.length === 0 && (
                                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                        No configured providers found. Configure one in the Providers tab first.
                                    </div>
                                )}
                                {connectProviders.length > 0 && (
                                    <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                                        {connectProviders.map((item) => {
                                            const isSelected = selectedConnectProvider === item.key;
                                            const visual = getProviderVisual(item.key);
                                            const Icon = visual.icon;
                                            return (
                                                <button
                                                    key={item.key}
                                                    onClick={() => setSelectedConnectProvider(item.key)}
                                                    className="btn-ghost"
                                                    style={{
                                                        border: isSelected ? `1px solid ${visual.color}` : '1px solid rgba(255,255,255,0.08)',
                                                        background: isSelected ? 'rgba(255,255,255,0.06)' : 'rgba(255,255,255,0.02)',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        justifyContent: 'space-between',
                                                        gap: '10px',
                                                        padding: '10px 12px',
                                                        borderRadius: '8px'
                                                    }}
                                                >
                                                    <span style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                                                        <ProviderBrandIcon providerKey={item.key} size={14} />
                                                        <span style={{ textTransform: 'capitalize', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                            {item.meta?.display_name || item.key}
                                                        </span>
                                                    </span>
                                                    {isSelected && <CheckCircle size={14} color={visual.color} />}
                                                </button>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <strong style={{ fontSize: '13px' }}>Linked Accounts</strong>
                                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Managed via OAuth flow</span>
                            </div>
                            {accounts.length === 0 && (
                                <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                                    No linked accounts yet. Use this area for Google account links.
                                </div>
                            )}
                            {accounts.length > 0 && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                    {accounts.map((account, idx) => (
                                        <div key={account?.id || `acc_${idx}`} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                                {account?.profile?.picture && (
                                                    <img
                                                        src={account.profile.picture}
                                                        alt="profile"
                                                        width={28}
                                                        height={28}
                                                        style={{ width: '28px', height: '28px', borderRadius: '999px', objectFit: 'cover', border: '1px solid rgba(255,255,255,0.15)' }}
                                                    />
                                                )}
                                                <div>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                    <ProviderBrandIcon providerKey={account?.provider} size={13} />
                                                    <strong style={{ textTransform: 'capitalize', fontSize: '13px' }}>{account?.provider || 'provider'}</strong>
                                                </div>
                                                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{account?.account || 'account'}</div>
                                                {account?.profile?.name && account?.profile?.email && (
                                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                                        {account.profile.name}
                                                    </div>
                                                )}
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{account?.status || 'connected'}</div>
                                                </div>
                                            </div>
                                            <button
                                                onClick={() => removeLinkedAccount(account?.id)}
                                                className="icon-btn"
                                                style={{ padding: '6px' }}
                                                title="Remove linked account"
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {externalTab === 'providers' && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                <button onClick={addProvider} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 12px' }}>
                                    <Plus size={14} style={{ marginRight: '6px' }} /> Add Provider
                                </button>
                            </div>
                            <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px', padding: '14px', marginBottom: '4px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                                    <strong style={{ fontSize: '13px' }}>Provider Plugins</strong>
                                    <button onClick={fetchExternalProviders} className="btn-ghost" style={{ fontSize: '11px', padding: '4px 8px' }}>
                                        <RefreshCw size={12} style={{ marginRight: '6px' }} /> Refresh
                                    </button>
                                </div>
                                {externalCatalogLoading && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Loading plugins...</div>}
                                {!externalCatalogLoading && visibleExternalCatalog.length === 0 && (
                                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>No plugins discovered.</div>
                                )}
                                {!externalCatalogLoading && visibleExternalCatalog.length > 0 && (
                                    <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                                        {visibleExternalCatalog.map((plugin) => (
                                            <div key={plugin.key} style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', padding: '10px' }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                                                    <div>
                                                        <strong style={{ fontSize: '12px' }}>{plugin.display_name || plugin.key}</strong>
                                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{plugin.description || 'External provider plugin'}</div>
                                                    </div>
                                                    <button
                                                        onClick={() => addProviderFromPlugin(plugin)}
                                                        className="btn-ghost"
                                                        disabled={Boolean(providers[plugin.key])}
                                                        style={{ fontSize: '11px', padding: '4px 8px', whiteSpace: 'nowrap' }}
                                                    >
                                                        {providers[plugin.key] ? 'Added' : 'Add'}
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {entries.length === 0 && (
                                <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                                    No providers configured yet.
                                </div>
                            )}

                            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                {entries.map(([providerKey, provider]) => (
                                    <div key={providerKey} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px 14px' }}>
                                        <div style={{ minWidth: 0 }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <span style={{ width: '8px', height: '8px', borderRadius: '999px', background: provider?.enabled ? '#22c55e' : '#ef4444', display: 'inline-block' }} />
                                                <strong style={{ textTransform: 'capitalize', fontSize: '14px' }}>{providerKey.replace(/_/g, ' ')}</strong>
                                                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{provider?.auth_mode || 'oauth2'}</span>
                                            </div>
                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                                {provider?.redirect_uri || 'No redirect URI configured'}
                                            </div>
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginLeft: '12px' }}>
                                            <input
                                                type="checkbox"
                                                className="luxury-checkbox"
                                                checked={provider?.enabled ?? false}
                                                onChange={(e) => updateNestedValue(`external_accounts.providers.${providerKey}.enabled`, e.target.checked)}
                                            />
                                            <button
                                                onClick={() => setEditingProviderKey(editingProviderKey === providerKey ? '' : providerKey)}
                                                className="icon-btn"
                                                title={editingProviderKey === providerKey ? 'Collapse editor' : 'Expand editor'}
                                                style={{ padding: '7px' }}
                                            >
                                                {editingProviderKey === providerKey ? <ChevronUp size={14} /> : <Settings2 size={14} />}
                                            </button>
                                            <button
                                                onClick={() => removeProvider(providerKey)}
                                                className="icon-btn"
                                                title={`Remove ${providerKey}`}
                                                style={{ padding: '7px' }}
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    </div>
                                ))}

                                {editingProviderKey && providers?.[editingProviderKey] && (
                                    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px', padding: '16px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                                            <strong style={{ textTransform: 'capitalize' }}>
                                                Edit Provider: {editingProviderKey.replace(/_/g, ' ')}
                                            </strong>
                                            <button
                                                onClick={() => setEditingProviderKey('')}
                                                className="btn-ghost"
                                                style={{ fontSize: '11px', padding: '4px 8px' }}
                                            >
                                                <ChevronDown size={12} style={{ marginRight: '6px' }} /> Collapse
                                            </button>
                                        </div>
                                        <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : '1fr 1fr', gap: '12px' }}>
                                            {(() => {
                                                const currentAuthMode = String(providers?.[editingProviderKey]?.auth_mode || '').trim().toLowerCase();
                                                const showsApiKey = currentAuthMode.includes('api') || currentAuthMode === 'custom' || currentAuthMode === '';
                                                return (
                                                    <>
                                            <div className="form-group">
                                                <label>Auth Mode</label>
                                                <input
                                                    type="text"
                                                    className="input-field"
                                                    value={providers?.[editingProviderKey]?.auth_mode || ''}
                                                    onChange={(e) => updateNestedValue(`external_accounts.providers.${editingProviderKey}.auth_mode`, e.target.value)}
                                                    placeholder="oauth2 | api_key | custom"
                                                />
                                            </div>
                                            <div className="form-group">
                                                <label>Redirect URI</label>
                                                <input
                                                    type="text"
                                                    className="input-field"
                                                    value={providers?.[editingProviderKey]?.redirect_uri || ''}
                                                    onChange={(e) => updateNestedValue(`external_accounts.providers.${editingProviderKey}.redirect_uri`, e.target.value)}
                                                    placeholder="http://localhost:8000/api/auth/callback"
                                                />
                                            </div>
                                            {renderSecretRefField(editingProviderKey, providers?.[editingProviderKey], 'client_id')}
                                            {renderSecretRefField(editingProviderKey, providers?.[editingProviderKey], 'client_secret')}
                                            {showsApiKey && renderSecretRefField(editingProviderKey, providers?.[editingProviderKey], 'api_key_ref')}
                                            <div className="form-group">
                                                <label>Scopes (comma separated)</label>
                                                <input
                                                    type="text"
                                                    className="input-field"
                                                    value={Array.isArray(providers?.[editingProviderKey]?.scopes) ? providers[editingProviderKey].scopes.join(', ') : ''}
                                                    onChange={(e) => updateNestedValue(`external_accounts.providers.${editingProviderKey}.scopes`, e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                                                    placeholder="openid, email, profile"
                                                />
                                            </div>
                                            {getProviderExtraFields(editingProviderKey).map((field) => (
                                                <div className="form-group" key={`${editingProviderKey}_${field.name}`}>
                                                    <label>{field.label}</label>
                                                    <input
                                                        type="text"
                                                        className="input-field"
                                                        value={providers?.[editingProviderKey]?.[field.name] || ''}
                                                        onChange={(e) => updateNestedValue(`external_accounts.providers.${editingProviderKey}.${field.name}`, e.target.value)}
                                                        placeholder={field.placeholder}
                                                    />
                                                </div>
                                            ))}
                                                    </>
                                                );
                                            })()}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </section>
            </div>
        );
    };

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
                    {activeTab === 'external_accounts' && renderExternalAccounts()}
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
