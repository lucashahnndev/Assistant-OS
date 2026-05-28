import { useState, useEffect, useRef } from 'react';
import { api } from '../hooks/api';
import {
    Save,
    RefreshCw,
    Shield,
    Cpu,
    Clock,
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
    Monitor,
    Building2,
    Zap,
    Puzzle,
    ExternalLink,
    ChevronLeft,
    ChevronRight,
    ChevronDown,
    ChevronUp,
    Trash2,
    Link2,
    Settings2,
    Bot,
    Loader,
    Server,
    FolderOpen,
    Cloud
} from 'lucide-react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import PageHeader from '../components/PageHeader';
import ModelPoolManager from '../components/ModelPoolManager';
import { createSecret, deleteSecret, listSecretEntries, listSecretRefs, auditEnvSecrets, importEnvSecrets } from '../utils/secretsApi';
import { QRCodeSVG } from 'qrcode.react';

const Settings = () => {
    const [config, setConfig] = useState(null);
    const [rawJson, setRawJson] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [activeTab, setActiveTab] = useState('general');
    const [isTabsCollapsed, setIsTabsCollapsed] = useState(() => {
        return localStorage.getItem('assistant_settings_tabs_collapsed') === 'true';
    });
    const [vaultEntries, setVaultEntries] = useState([]);
    const [vaultDraft, setVaultDraft] = useState({ key: '', value: '' });
    const [editingVaultKey, setEditingVaultKey] = useState('');
    const [envAudit, setEnvAudit] = useState(null);
    const [envKeys, setEnvKeys] = useState([]);
    const [externalCatalog, setExternalCatalog] = useState([]);
    const [externalCatalogLoading, setExternalCatalogLoading] = useState(false);
    const [externalTab, setExternalTab] = useState('accounts');
    const [editingProviderKey, setEditingProviderKey] = useState('');
    const [externalSecretEditor, setExternalSecretEditor] = useState({ target: '', key: '', value: '' });
    const [selectedConnectProvider, setSelectedConnectProvider] = useState('');
    const [connectingProvider, setConnectingProvider] = useState('');
    const [mcpStatus, setMcpStatus] = useState({ servers: [], resources: [], refresh: {} });
    const [mcpLoading, setMcpLoading] = useState(false);
    const [mcpCollapsedServers, setMcpCollapsedServers] = useState({});
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);
    const [isTablet, setIsTablet] = useState(window.innerWidth > 640 && window.innerWidth <= 1024);
    const [isCompressing, setIsCompressing] = useState(false);
    const [networkTunnels, setNetworkTunnels] = useState([]);
    const [networkTunnelsLoading, setNetworkTunnelsLoading] = useState(false);
    const [activeTunnels, setActiveTunnels] = useState([]);
    const [tunnelLoadingState, setTunnelLoadingState] = useState({});

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

    const withMcpDefaults = (sourceConfig) => {
        const next = sourceConfig && typeof sourceConfig === 'object' ? { ...sourceConfig } : {};
        const mcp = next.mcp && typeof next.mcp === 'object' ? { ...next.mcp } : {};
        const servers = Array.isArray(mcp.servers) ? mcp.servers.map((server, index) => normalizeMcpServer(server, index)) : [];
        next.mcp = {
            enabled: mcp.enabled ?? false,
            servers,
        };
        return next;
    };

    const normalizeMcpServer = (server, index = 0) => {
        const raw = server && typeof server === 'object' ? { ...server } : {};
        const transport = raw.transport && typeof raw.transport === 'object' ? { ...raw.transport } : {};
        const policy = raw.policy && typeof raw.policy === 'object' ? { ...raw.policy } : {};
        return {
            id: String(raw.id || `server_${index + 1}`).trim().toLowerCase(),
            title: String(raw.title || `Server ${index + 1}`).trim(),
            enabled: raw.enabled ?? true,
            transport: {
                kind: String(transport.kind || 'http').trim().toLowerCase(),
                endpoint: String(transport.endpoint || '').trim(),
                command: String(transport.command || '').trim(),
                args: Array.isArray(transport.args) ? [...transport.args] : [],
                env: transport.env && typeof transport.env === 'object' ? { ...transport.env } : {},
                headers: transport.headers && typeof transport.headers === 'object' ? { ...transport.headers } : {},
                startup_timeout_s: transport.startup_timeout_s ?? 20,
            },
            policy: {
                trust_tier: String(policy.trust_tier || 'partner').trim().toLowerCase(),
                namespace: String(policy.namespace || 'mcp').trim().toLowerCase(),
                allow_tool_discovery: policy.allow_tool_discovery ?? true,
                allow_resources: policy.allow_resources ?? true,
                allow_prompts: policy.allow_prompts ?? false,
                default_requires_approval: policy.default_requires_approval ?? null,
                tool_allowlist: Array.isArray(policy.tool_allowlist) ? [...policy.tool_allowlist] : [],
                tool_denylist: Array.isArray(policy.tool_denylist) ? [...policy.tool_denylist] : [],
            },
            metadata: raw.metadata && typeof raw.metadata === 'object' ? { ...raw.metadata } : {},
        };
    };

    useEffect(() => {
        fetchConfig();
        fetchVaultEntries();
        fetchLogSources();
        fetchNetworkTunnels();
        return () => stopLogStream();
    }, []);

    useEffect(() => {
        if (activeTab === 'external_accounts') {
            fetchExternalProviders();
            fetchEnvKeys();
            fetchLinkedAccounts();
        }
        if (activeTab === 'interfaces' || activeTab === 'security') {
            fetchEnvKeys();
        }
        if (activeTab === 'mcp') {
            fetchMcpStatus();
        }
        
        let intervalId;
        if (activeTab === 'network') {
            fetchActiveTunnels();
            intervalId = setInterval(fetchActiveTunnels, 5000);
        }
        return () => {
            if (intervalId) clearInterval(intervalId);
        };
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

    const handleCompressPersonality = async () => {
        if (!config?.agent?.personality) {
            toast.error("Please enter a natural text personality first.");
            return;
        }
        setIsCompressing(true);
        try {
            const data = await api.post('/system/compress-personality', { text: config.agent.personality });
            if (data?.compressed) {
                updateNestedValue('agent.personality_compressed', data.compressed);
                toast.success("Personality successfully compressed!");
            }
        } catch (err) {
            toast.error(err.response?.data?.detail || "Failed to compress personality");
        } finally {
            setIsCompressing(false);
        }
    };

    const fetchConfig = async () => {
        try {
            const data = await api.get('/system/config');
            const normalized = withMcpDefaults(withExternalAccountsDefaults(data));
            setConfig(normalized);
            setRawJson(JSON.stringify(normalized, null, 2));
        } catch (err) {
            console.error(err);
            toast.error("Failed to load configuration");
        }
        finally { setLoading(false); }
    };

    const fetchNetworkTunnels = async () => {
        setNetworkTunnelsLoading(true);
        try {
            const caps = await api.get('/capabilities/');
            if (Array.isArray(caps)) {
                setNetworkTunnels(caps.filter(c => c.id && c.id.endsWith('_tunnel')));
            }
        } catch (err) {
            console.error("Failed to fetch network tunnels", err);
        } finally {
            setNetworkTunnelsLoading(false);
        }
    };

    const fetchActiveTunnels = async () => {
        try {
            const data = await api.get('/system/tunnels/status');
            if (Array.isArray(data?.active_tunnels)) {
                setActiveTunnels(data.active_tunnels);
            }
        } catch (err) {
            console.error("Failed to fetch active tunnels", err);
        }
    };

    const handleToggleTunnel = async (tunnelId, isRunning) => {
        const action = isRunning ? 'stop' : 'start';
        setTunnelLoadingState(prev => ({ ...prev, [tunnelId]: true }));
        try {
            const res = await api.post(`/capabilities/${tunnelId}/actions/${tunnelId}.${action}`, {});
            const result = res?.result || {};
            if (result.ok === false) {
                toast.error(`Failed to ${action} tunnel: ${result.error_details || 'Unknown error'}`);
            } else {
                toast.success(`Tunnel ${action} signal sent successfully.`);
            }
            await fetchActiveTunnels();
        } catch (err) {
            console.error(err);
            toast.error(`Failed to ${action} tunnel: ` + (err.response?.data?.detail || err.message));
        } finally {
            setTunnelLoadingState(prev => ({ ...prev, [tunnelId]: false }));
        }
    };

    const handleToggleAutostart = async (tunnelId, nextVal) => {
        try {
            await api.patch(`/capabilities/${tunnelId}/config`, { autostart: nextVal });
            updateNestedValue(`capabilities.${tunnelId}.autostart`, nextVal);
            toast.success(`Auto-start ${nextVal ? 'enabled' : 'disabled'} for tunnel`);
        } catch (err) {
            console.error(err);
            toast.error("Failed to save auto-start preference");
        }
    };

    const fetchVaultEntries = async () => {
        try {
            const data = await listSecretEntries();
            setVaultEntries(Array.isArray(data?.entries) ? data.entries : []);
        } catch (err) {
            console.error(err);
            setVaultEntries([]);
        }
    };

    const fetchEnvKeys = async () => {
        try {
            const keys = await listSecretRefs();
            setEnvKeys(keys);
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

    const fetchMcpStatus = async () => {
        setMcpLoading(true);
        try {
            const data = await api.get('/system/mcp/status');
            setMcpStatus({
                servers: Array.isArray(data?.servers) ? data.servers : [],
                resources: Array.isArray(data?.resources) ? data.resources : [],
                refresh: data?.refresh && typeof data.refresh === 'object' ? data.refresh : {},
            });
        } catch (err) {
            console.error(err);
            setMcpStatus({ servers: [], resources: [], refresh: {} });
        } finally {
            setMcpLoading(false);
        }
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            await api.post('/system/config', config);
            toast.success("Settings updated.");
            return true;
        } catch (err) { toast.error(err.message); }
        finally { setSaving(false); }
        return false;
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

    const refreshMcpRuntime = async () => {
        const loadingToast = toast.loading("Refreshing MCP runtime...");
        try {
            await api.post('/system/mcp/refresh', {});
            await fetchMcpStatus();
            toast.success("MCP runtime refreshed.", { id: loadingToast });
        } catch (err) {
            toast.error(`MCP refresh failed: ${err.message}`, { id: loadingToast });
        }
    };

    const saveMcpServerAndCollapse = async (server, index) => {
        const saved = await handleSave();
        if (saved) {
            setMcpServerCollapsed(server, index, true);
        }
    };



    const openVaultEditor = (key = '') => {
        setEditingVaultKey(key);
        setVaultDraft({ key, value: '' });
    };

    const resetVaultEditor = () => {
        setEditingVaultKey('');
        setVaultDraft({ key: '', value: '' });
    };

    const saveVaultSecret = async () => {
        const key = String(vaultDraft.key || '').trim();
        const value = String(vaultDraft.value || '').trim();
        if (!key || !value) {
            toast.error('Key and value are required.');
            return;
        }
        try {
            await createSecret({ key, value, overwrite: Boolean(editingVaultKey) });
            toast.success(editingVaultKey ? `Secret ${key} updated.` : `Secret ${key} created.`);
            resetVaultEditor();
            await Promise.all([fetchVaultEntries(), fetchEnvKeys()]);
        } catch (err) {
            toast.error(err.message || 'Failed to save secret');
        }
    };

    const removeVaultSecret = async (key) => {
        if (!window.confirm(`Delete ${key}?`)) return;
        try {
            await deleteSecret(key);
            toast.success(`Secret ${key} deleted.`);
            if (editingVaultKey === key) resetVaultEditor();
            await Promise.all([fetchVaultEntries(), fetchEnvKeys()]);
        } catch (err) {
            toast.error(err.message || 'Failed to delete secret');
        }
    };

    const runEnvAudit = async () => {
        try {
            const data = await auditEnvSecrets();
            setEnvAudit(data);
            toast.success('Environment source audited.');
        } catch (err) {
            toast.error(err.message || 'Failed to audit .env source');
        }
    };

    const runEnvImport = async (overwrite = false) => {
        try {
            const data = await importEnvSecrets({ overwrite });
            setEnvAudit(data);
            await Promise.all([fetchVaultEntries(), fetchEnvKeys()]);
            toast.success(overwrite ? 'Vault synchronized from .env source.' : 'Missing secrets imported from .env source.');
        } catch (err) {
            toast.error(err.message || 'Failed to import .env source');
        }
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

    const updateNestedValues = (updates) => {
        const newConfig = { ...config };
        updates.forEach(({ path, value }) => {
            const parts = path.split('.');
            let current = newConfig;
            for (let i = 0; i < parts.length - 1; i++) {
                if (!current[parts[i]]) current[parts[i]] = {};
                current = current[parts[i]];
            }
            current[parts[parts.length - 1]] = value;
        });
        setConfig(newConfig);
        setRawJson(JSON.stringify(newConfig, null, 2));
    };

    const updateMcpServers = (nextServers) => {
        const next = { ...(config || {}) };
        next.mcp = {
            ...(next.mcp || {}),
            enabled: next.mcp?.enabled ?? false,
            servers: nextServers,
        };
        setConfig(next);
        setRawJson(JSON.stringify(next, null, 2));
    };

    const getMcpServerKey = (server, index = 0) => String(server?.id || `server_${index + 1}`).trim().toLowerCase();

    const setMcpServerCollapsed = (server, index, collapsed) => {
        const key = getMcpServerKey(server, index);
        setMcpCollapsedServers((prev) => ({
            ...prev,
            [key]: collapsed,
        }));
    };

    const isMcpServerCollapsed = (server, index) => Boolean(mcpCollapsedServers[getMcpServerKey(server, index)]);

    const updateMcpValue = (path, value) => {
        const next = { ...(config || {}) };
        const parts = String(path || '').split('.');
        let current = next;
        for (let i = 0; i < parts.length - 1; i++) {
            const key = parts[i];
            if (!current[key] || typeof current[key] !== 'object') {
                current[key] = {};
            }
            current = current[key];
        }
        current[parts[parts.length - 1]] = value;
        if (!next.mcp || typeof next.mcp !== 'object') {
            next.mcp = { enabled: false, servers: [] };
        }
        setConfig(next);
        setRawJson(JSON.stringify(next, null, 2));
    };

    const updateMcpServer = (index, updater) => {
        const servers = Array.isArray(config?.mcp?.servers) ? [...config.mcp.servers] : [];
        const current = normalizeMcpServer(servers[index], index);
        const nextServer = typeof updater === 'function' ? updater(current) : current;
        servers[index] = nextServer;
        updateMcpServers(servers);
        const previousKey = getMcpServerKey(current, index);
        const nextKey = getMcpServerKey(nextServer, index);
        if (previousKey !== nextKey) {
            setMcpCollapsedServers((prev) => {
                if (!(previousKey in prev)) return prev;
                const next = { ...prev, [nextKey]: prev[previousKey] };
                delete next[previousKey];
                return next;
            });
        }
    };

    const addMcpServer = () => {
        const servers = Array.isArray(config?.mcp?.servers) ? [...config.mcp.servers] : [];
        const nextServer = normalizeMcpServer({}, servers.length);
        servers.push(nextServer);
        updateMcpServers(servers);
        setMcpServerCollapsed(nextServer, servers.length, false);
    };

    const removeMcpServer = (index) => {
        const servers = Array.isArray(config?.mcp?.servers) ? [...config.mcp.servers] : [];
        const removedServer = normalizeMcpServer(servers[index], index);
        servers.splice(index, 1);
        updateMcpServers(servers);
        setMcpCollapsedServers((prev) => {
            const next = { ...prev };
            delete next[getMcpServerKey(removedServer, index)];
            return next;
        });
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
        { id: 'capabilities', label: 'Capabilities', icon: Puzzle },
        { id: 'mcp', label: 'MCP', icon: Server },
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
            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>

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
                        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
                            <button
                                className="action-button primary"
                                onClick={handleCompressPersonality}
                                disabled={isCompressing || !config.agent?.personality}
                                style={{ padding: '6px 12px', fontSize: '0.85rem' }}
                            >
                                {isCompressing ? <Loader className="spin" size={14} /> : <Zap size={14} />}
                                <span>{isCompressing ? 'Compressing...' : '✨ Auto-Compress (Save Tokens)'}</span>
                            </button>
                        </div>
                    </div>

                    {config.agent?.personality_compressed && (
                        <div className="form-group animate-fade-in" style={{ marginTop: '-8px' }}>
                            <label style={{ color: 'var(--text-muted)' }}>
                                <Bot size={14} style={{ display: 'inline', marginRight: '4px', verticalAlign: 'middle' }} />
                                Compressed Mirror (System View)
                            </label>
                            <textarea
                                className="input-field"
                                style={{ 
                                    minHeight: '80px', 
                                    opacity: 0.8,
                                    fontSize: '0.85rem',
                                    fontFamily: 'monospace',
                                    backgroundColor: 'rgba(0,0,0,0.2)'
                                }}
                                value={config.agent.personality_compressed}
                                readOnly
                                title="This highly dense string is what the agent actually reads to save context window space."
                            />
                        </div>
                    )}
                </div>
            </section>

        </div>
    );

    const renderNetwork = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
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

            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h3 className="section-title" style={{ margin: 0 }}>
                        <Cloud size={20} /> Remote Access
                    </h3>
                    <Link to="/capabilities" className="btn-primary" style={{ padding: '8px 16px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Settings2 size={16} /> Manage in Hub
                    </Link>
                </div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '14px', marginBottom: '16px' }}>
                    Remote access is now powered by dedicated capabilities (plugins). 
                    Install and configure Ngrok or Cloudflare Tunnel directly from the Capabilities Hub.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '16px' }}>
                    {networkTunnelsLoading ? (
                        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
                            <Loader className="spin" size={24} style={{ margin: '0 auto 12px' }} />
                            <div style={{ fontSize: '13px' }}>Loading tunnel plugins...</div>
                        </div>
                    ) : (
                        (() => {
                            const enabledTunnels = networkTunnels.filter(t => config.capabilities?.[t.id]?.enabled);
                            
                            if (enabledTunnels.length === 0) {
                                return (
                                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(255,255,255,0.05)' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)', fontSize: '13px' }}>
                                            <CheckCircle size={16} color="var(--accent-color)" /> 
                                            Enable a Remote Access plugin in the Capabilities Hub to manage it here.
                                        </div>
                                    </div>
                                );
                            }

                            return enabledTunnels.map(tunnel => {
                                const tunnelConfig = config.capabilities?.[tunnel.id] || {};
                                const activeStatus = activeTunnels.find(a => a.id === tunnel.id) || {};
                                const isRunning = activeStatus.status === 'running';
                                const publicUrl = activeStatus.public_url || '';
                                const errorDetails = activeStatus.error || null;
                                const isLoading = tunnelLoadingState[tunnel.id] || false;

                                return (
                                    <div key={tunnel.id} style={{ background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(255,255,255,0.05)' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <Puzzle size={16} color="var(--accent-color)" />
                                                <h4 style={{ margin: 0, fontSize: '14px', fontWeight: '600' }}>{tunnel.title || tunnel.name}</h4>
                                                <span style={{ fontSize: '10px', padding: '2px 6px', background: isRunning ? 'rgba(16, 185, 129, 0.1)' : 'rgba(255,255,255,0.1)', color: isRunning ? '#10b981' : 'var(--text-secondary)', borderRadius: '12px', border: isRunning ? '1px solid rgba(16, 185, 129, 0.2)' : '1px solid rgba(255,255,255,0.1)' }}>
                                                    {isRunning ? 'ONLINE' : 'OFFLINE'}
                                                </span>
                                            </div>
                                            <div className="toggle-item" style={{ padding: 0, border: 'none', background: 'transparent' }}>
                                                {isLoading ? (
                                                    <Loader className="spin" size={20} color="var(--accent-color)" />
                                                ) : (
                                                    <input type="checkbox" className="luxury-checkbox"
                                                        checked={isRunning}
                                                        onChange={() => handleToggleTunnel(tunnel.id, isRunning)}
                                                    />
                                                )}
                                            </div>
                                        </div>

                                        {isRunning && publicUrl && (
                                            <div style={{ padding: '16px', background: 'rgba(16, 185, 129, 0.05)', borderRadius: '8px', border: '1px solid rgba(16, 185, 129, 0.2)', marginBottom: '16px', display: 'flex', gap: '16px', alignItems: 'center' }}>
                                                <div style={{ background: '#fff', padding: '8px', borderRadius: '8px' }}>
                                                    <QRCodeSVG value={publicUrl} size={64} />
                                                </div>
                                                <div style={{ flex: 1, minWidth: 0 }}>
                                                    <div style={{ fontSize: '12px', color: '#10b981', fontWeight: '600', marginBottom: '4px' }}>PUBLIC URL</div>
                                                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                                        <a href={publicUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--text-primary)', fontSize: '14px', wordBreak: 'break-all', textDecoration: 'none' }} className="hover-underline">
                                                            {publicUrl}
                                                        </a>
                                                        <ExternalLink size={14} color="var(--text-muted)" />
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                        
                                        {!isRunning && errorDetails && (
                                            <div style={{ padding: '12px 16px', background: 'rgba(239, 68, 68, 0.05)', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.2)', marginBottom: '16px', display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                                                <XCircle size={16} color="#ef4444" style={{ flexShrink: 0, marginTop: '2px' }} />
                                                <div style={{ flex: 1, minWidth: 0 }}>
                                                    <div style={{ fontSize: '12px', color: '#ef4444', fontWeight: '600', marginBottom: '4px' }}>TUNNEL ERROR</div>
                                                    <div style={{ color: 'var(--text-secondary)', fontSize: '13px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'monospace' }}>
                                                        {errorDetails}
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                        
                                        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                                            <div className="form-group">
                                                <label>Target Port {isRunning && <span style={{fontSize: '10px', color: 'var(--text-muted)'}}>(Requires restart)</span>}</label>
                                                <input type="number" className="input-field"
                                                    value={tunnelConfig.target_port || ''}
                                                    placeholder={config.frontend?.port || 5173}
                                                    onChange={(e) => updateNestedValue(`capabilities.${tunnel.id}.target_port`, e.target.value ? parseInt(e.target.value) : undefined)}
                                                />
                                            </div>
                                            <div className="form-group">
                                                <label>Custom Domain {isRunning && <span style={{fontSize: '10px', color: 'var(--text-muted)'}}>(Requires restart)</span>}</label>
                                                <input type="text" className="input-field"
                                                    value={tunnelConfig.domain || ''}
                                                    placeholder="e.g. app.meudominio.com"
                                                    onChange={(e) => updateNestedValue(`capabilities.${tunnel.id}.domain`, e.target.value)}
                                                />
                                            </div>
                                        </div>
                                        
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px', background: 'rgba(0,0,0,0.2)', borderRadius: '8px' }}>
                                            <div>
                                                <div style={{ fontSize: '13px', fontWeight: '500' }}>Auto-Start on Boot</div>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Automatically start this tunnel when the system loads.</div>
                                            </div>
                                            <input type="checkbox" className="luxury-checkbox"
                                                checked={tunnelConfig.autostart || false}
                                                onChange={(e) => handleToggleAutostart(tunnel.id, e.target.checked)}
                                            />
                                        </div>
                                    </div>
                                );
                            });
                        })()
                    )}
                </div>
            </section>
        </div>
    );

    const renderMedia = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
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

                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '20px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(255,255,255,0.05)' }}>
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

    const openTelegramSecretEditor = () => {
        const current = config?.interfaces?.telegram?.secret_ref;
        setExternalSecretEditor({
            target: 'interfaces.telegram.secret_ref',
            key: typeof current === 'string' && current.startsWith('ENV_') ? current : 'ENV_TELEGRAM_KEY',
            value: ''
        });
    };

    const createAndBindExternalSecret = async (targetPath) => {
        const key = String(externalSecretEditor.key || '').trim();
        const value = String(externalSecretEditor.value || '').trim();
        if (!key || !value) {
            toast.error("Key and value are required.");
            return;
        }
        try {
            const res = await createSecret({ key, value });
            if (res?.success) {
                const boundKey = String(res?.key || key).trim();
                updateNestedValue(targetPath, boundKey);
                await fetchEnvKeys();
                setExternalSecretEditor({ target: '', key: '', value: '' });
                toast.success(`Secret ${boundKey} created and linked.`);
            }
        } catch (err) {
            toast.error(err.message || 'Failed to create secret');
        }
    };

    const renderTelegramSecretField = () => {
        const currentValue = config?.interfaces?.telegram?.secret_ref || '';
        const creating = externalSecretEditor.target === 'interfaces.telegram.secret_ref';
        const options = Array.from(new Set([...(envKeys || []), ...(currentValue ? [currentValue] : [])]));

        return (
            <div className="form-group" style={{ background: 'rgba(var(--accent-rgb), 0.05)', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(var(--accent-rgb), 0.2)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Shield size={14} color="var(--accent-color)" /> Bot Token
                    </label>
                    <button
                        onClick={() => creating ? setExternalSecretEditor({ target: '', key: '', value: '' }) : openTelegramSecretEditor()}
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
                        onChange={(e) => updateNestedValue('interfaces.telegram.secret_ref', e.target.value)}
                    >
                        <option value="">-- Select Environment Key --</option>
                        {options.map((key) => (
                            <option key={key} value={key}>{key}</option>
                        ))}
                    </select>
                )}

                {creating && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
                        <input
                            type="text"
                            className="input-field"
                            value={externalSecretEditor.key}
                            placeholder="ENV_TELEGRAM_KEY"
                            onChange={(e) => setExternalSecretEditor(prev => ({ ...prev, key: e.target.value }))}
                        />
                        <input
                            type="password"
                            className="input-field"
                            value={externalSecretEditor.value}
                            placeholder="Paste your BotFather token here"
                            onChange={(e) => setExternalSecretEditor(prev => ({ ...prev, value: e.target.value }))}
                        />
                        <button
                            onClick={() => createAndBindExternalSecret('interfaces.telegram.secret_ref')}
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

    const renderInterfaces = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
                <h3 className="section-title">
                    <Monitor size={20} /> Messaging Bridges
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '24px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(255,255,255,0.05)' }}>
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

                        {config.interfaces?.telegram?.enabled && renderTelegramSecretField()}
                        <p style={{ marginTop: '16px', fontSize: '12px', color: '#475569' }}>
                            Future integrations: Discord, WhatsApp (Coming Soon)
                        </p>
                    </div>
                </div>
            </section>
        </div>
    );

    const renderCapabilities = () => (
        <div className="animate-fade-in">
            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)', textAlign: 'center' }}>
                <Puzzle size={48} style={{ margin: '0 auto 20px', color: 'var(--accent-color)' }} />
                <h3 style={{ fontSize: '24px', fontWeight: '800', marginBottom: '16px' }}>Cognitive Capabilities</h3>
                <p style={{ color: '#94a3b8', marginBottom: '32px' }}>
                    Capability management has been moved to the dedicated Capabilities Hub for an improved experience.
                </p>
                <div style={{ display: 'flex', justifyContent: 'center' }}>
                    <Link to="/capabilities" className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 24px' }}>
                        <ExternalLink size={18} /> Open Capabilities Hub
                    </Link>
                </div>
            </section>
        </div>
    );

    const renderMcp = () => {
        const mcp = config?.mcp || { enabled: false, servers: [] };
        const servers = Array.isArray(mcp.servers) ? mcp.servers : [];
        const enabledServers = servers.filter((s) => s?.enabled).length;
        const resourceCount = Array.isArray(mcpStatus.resources) ? mcpStatus.resources.length : 0;

        return (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '18px' }}>
                        <div>
                            <h3 className="section-title" style={{ marginBottom: '4px' }}>
                                <Server size={20} /> MCP Runtime
                            </h3>
                            <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>Configure MCP servers and inspect live discovery status.</div>
                        </div>
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                            <button onClick={fetchMcpStatus} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <RefreshCw size={16} /> Refresh Status
                            </button>
                            <button onClick={refreshMcpRuntime} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <Zap size={16} /> Refresh Runtime
                            </button>
                            <button onClick={addMcpServer} className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <FolderOpen size={16} /> Add Server
                            </button>
                        </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : 'repeat(4, minmax(0, 1fr))', gap: '12px', marginBottom: '20px' }}>
                        <div className="glass" style={{ padding: '14px', borderRadius: 'var(--radius-md)' }}>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>MCP Enabled</div>
                            <div style={{ fontSize: '22px', fontWeight: '800', marginTop: '6px' }}>{mcp.enabled ? 'Yes' : 'No'}</div>
                        </div>
                        <div className="glass" style={{ padding: '14px', borderRadius: 'var(--radius-md)' }}>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Servers</div>
                            <div style={{ fontSize: '22px', fontWeight: '800', marginTop: '6px' }}>{servers.length}</div>
                        </div>
                        <div className="glass" style={{ padding: '14px', borderRadius: 'var(--radius-md)' }}>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Active</div>
                            <div style={{ fontSize: '22px', fontWeight: '800', marginTop: '6px' }}>{enabledServers}</div>
                        </div>
                        <div className="glass" style={{ padding: '14px', borderRadius: 'var(--radius-md)' }}>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Resources</div>
                            <div style={{ fontSize: '22px', fontWeight: '800', marginTop: '6px' }}>{resourceCount}</div>
                        </div>
                    </div>

                    <div className="toggle-item luxury" style={{ marginBottom: '20px' }}>
                        <div className="toggle-info">
                            <span className="toggle-label">MCP Integration Enabled</span>
                            <span className="toggle-desc">Enable discovery, registration, and resource retrieval from configured MCP servers.</span>
                        </div>
                        <input
                            type="checkbox"
                            className="luxury-checkbox"
                            checked={Boolean(mcp.enabled)}
                            onChange={(e) => updateMcpValue('mcp.enabled', e.target.checked)}
                        />
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                        {servers.length === 0 && (
                            <div style={{ padding: '20px', border: '1px dashed rgba(148, 163, 184, 0.25)', borderRadius: 'var(--radius-md)', color: 'var(--text-muted)' }}>
                                No MCP servers configured yet. Add one for Obsidian or any other compatible server.
                            </div>
                        )}

                        {servers.map((server, index) => {
                            const transport = server.transport || {};
                            const policy = server.policy || {};
                            const statusServer = (mcpStatus.servers || []).find((item) => String(item?.id || '') === String(server.id || '').trim().toLowerCase());
                            const statusLabel = statusServer ? `${statusServer.resource_count || 0} resources` : 'No live status';
                            const serverKey = getMcpServerKey(server, index);
                            const collapsed = isMcpServerCollapsed(server, index);

                            return (
                                <div key={`${serverKey}_${index}`} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148,163,184,0.15)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '12px' }}>
                                        <div>
                                            <strong style={{ fontSize: '14px' }}>{server.title || `Server ${index + 1}`}</strong>
                                            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{server.id || `server_${index + 1}`} - {statusLabel}</div>
                                        </div>
                                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                                            <button onClick={() => setMcpServerCollapsed(server, index, !collapsed)} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 10px' }}>
                                                {collapsed ? <><ChevronDown size={14} /> Expand</> : <><ChevronUp size={14} /> Collapse</>}
                                            </button>
                                            <button onClick={() => saveMcpServerAndCollapse(server, index)} className="btn-primary" style={{ fontSize: '12px', padding: '6px 10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                <Save size={14} /> Save & Collapse
                                            </button>
                                            <button onClick={() => updateMcpServer(index, (current) => ({ ...current, enabled: !current.enabled }))} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 10px' }}>
                                                {server.enabled ? 'Disable' : 'Enable'}
                                            </button>
                                            <button onClick={() => removeMcpServer(index)} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 10px', color: '#f87171' }}>
                                                <Trash2 size={14} /> Remove
                                            </button>
                                        </div>
                                    </div>

                                    {collapsed ? (
                                        <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : 'repeat(4, minmax(0, 1fr))', gap: '10px' }}>
                                            <div className="glass" style={{ padding: '12px', borderRadius: 'var(--radius-md)' }}>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Transport</div>
                                                <div style={{ fontSize: '13px', fontWeight: '700', marginTop: '4px' }}>{transport.kind || 'http'}</div>
                                            </div>
                                            <div className="glass" style={{ padding: '12px', borderRadius: 'var(--radius-md)' }}>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Endpoint</div>
                                                <div style={{ fontSize: '13px', fontWeight: '700', marginTop: '4px', wordBreak: 'break-word' }}>{transport.endpoint || transport.command || 'Not set'}</div>
                                            </div>
                                            <div className="glass" style={{ padding: '12px', borderRadius: 'var(--radius-md)' }}>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Discovery</div>
                                                <div style={{ fontSize: '13px', fontWeight: '700', marginTop: '4px' }}>{policy.allow_tool_discovery ? 'On' : 'Off'}</div>
                                            </div>
                                            <div className="glass" style={{ padding: '12px', borderRadius: 'var(--radius-md)' }}>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Resources</div>
                                                <div style={{ fontSize: '13px', fontWeight: '700', marginTop: '4px' }}>{policy.allow_resources ? 'On' : 'Off'}</div>
                                            </div>
                                        </div>
                                    ) : (
                                        <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : '1fr 1fr', gap: '14px' }}>
                                            <div className="form-group">
                                                <label>Server ID</label>
                                                <input className="input-field" value={server.id || ''} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, id: e.target.value }))} placeholder="obsidian" />
                                            </div>
                                            <div className="form-group">
                                                <label>Title</label>
                                                <input className="input-field" value={server.title || ''} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, title: e.target.value }))} placeholder="Obsidian Vault" />
                                            </div>
                                            <div className="form-group">
                                                <label>Transport Kind</label>
                                                <select className="input-field" value={transport.kind || 'http'} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, transport: { ...current.transport, kind: e.target.value } }))}>
                                                    <option value="http">http</option>
                                                    <option value="stdio">stdio</option>
                                                </select>
                                            </div>
                                            <div className="form-group">
                                                <label>Trust Tier</label>
                                                <select className="input-field" value={policy.trust_tier || 'partner'} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, policy: { ...current.policy, trust_tier: e.target.value } }))}>
                                                    <option value="trusted">trusted</option>
                                                    <option value="partner">partner</option>
                                                    <option value="untrusted">untrusted</option>
                                                </select>
                                            </div>
                                            <div className="form-group">
                                                <label>Endpoint</label>
                                                <input className="input-field" value={transport.endpoint || ''} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, transport: { ...current.transport, endpoint: e.target.value } }))} placeholder="http://127.0.0.1:8765/mcp" />
                                            </div>
                                            <div className="form-group">
                                                <label>Command</label>
                                                <input className="input-field" value={transport.command || ''} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, transport: { ...current.transport, command: e.target.value } }))} placeholder="npx -y ..." />
                                            </div>
                                            <div className="form-group">
                                                <label>Namespace</label>
                                                <input className="input-field" value={policy.namespace || 'mcp'} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, policy: { ...current.policy, namespace: e.target.value } }))} placeholder="mcp" />
                                            </div>
                                            <div className="form-group">
                                                <label>Startup Timeout (s)</label>
                                                <input type="number" className="input-field" value={transport.startup_timeout_s ?? 20} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, transport: { ...current.transport, startup_timeout_s: parseFloat(e.target.value || '0') || 20 } }))} />
                                            </div>
                                            <div className="toggle-item luxury" style={{ gridColumn: (isMobile || isTablet) ? 'auto' : '1 / -1' }}>
                                                <div className="toggle-info">
                                                    <span className="toggle-label">Allow Tool Discovery</span>
                                                    <span className="toggle-desc">Register tools from this server as dynamic Atlas capabilities.</span>
                                                </div>
                                                <input type="checkbox" className="luxury-checkbox" checked={Boolean(policy.allow_tool_discovery)} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, policy: { ...current.policy, allow_tool_discovery: e.target.checked } }))} />
                                            </div>
                                            <div className="toggle-item luxury" style={{ gridColumn: (isMobile || isTablet) ? 'auto' : '1 / -1' }}>
                                                <div className="toggle-info">
                                                    <span className="toggle-label">Allow Resources</span>
                                                    <span className="toggle-desc">Expose resources so Atlas can read vault content as evidence.</span>
                                                </div>
                                                <input type="checkbox" className="luxury-checkbox" checked={Boolean(policy.allow_resources)} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, policy: { ...current.policy, allow_resources: e.target.checked } }))} />
                                            </div>
                                            <div className="form-group">
                                                <label>Tool Allowlist</label>
                                                <textarea className="input-field" style={{ minHeight: '84px' }} value={Array.isArray(policy.tool_allowlist) ? policy.tool_allowlist.join(', ') : ''} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, policy: { ...current.policy, tool_allowlist: e.target.value.split(',').map(s => s.trim()).filter(Boolean) } }))} placeholder="search_notes, read_note" />
                                            </div>
                                            <div className="form-group">
                                                <label>Tool Denylist</label>
                                                <textarea className="input-field" style={{ minHeight: '84px' }} value={Array.isArray(policy.tool_denylist) ? policy.tool_denylist.join(', ') : ''} onChange={(e) => updateMcpServer(index, (current) => ({ ...current, policy: { ...current.policy, tool_denylist: e.target.value.split(',').map(s => s.trim()).filter(Boolean) } }))} placeholder="delete_vault" />
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </section>

                <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
                        <div>
                            <h3 style={{ fontSize: '18px', fontWeight: '800', margin: 0 }}>Live MCP Resources</h3>
                            <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>What the backend discovered from configured servers.</div>
                        </div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                            {mcpLoading ? 'Refreshing...' : `${resourceCount} discovered resource(s)`}
                        </div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        {resourceCount === 0 && (
                            <div style={{ color: 'var(--text-muted)', padding: '16px', border: '1px dashed rgba(148,163,184,0.2)', borderRadius: 'var(--radius-md)' }}>
                                No live resources yet. Enable a server and refresh runtime.
                            </div>
                        )}
                        {(mcpStatus.resources || []).slice(0, 24).map((resource) => (
                            <div key={`${resource.server_id || 'server'}_${resource.uri}`} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 'var(--radius-md)', padding: '12px 14px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
                                    <div>
                                        <strong style={{ fontSize: '13px' }}>{resource.title || resource.uri}</strong>
                                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{resource.uri}</div>
                                    </div>
                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                                        {resource.server_id} · {resource.mime_type || 'unknown'}
                                    </div>
                                </div>
                                {resource.description && (
                                    <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-secondary)' }}>{resource.description}</div>
                                )}
                            </div>
                        ))}
                    </div>
                </section>
            </div>
        );
    };

    const renderDebug = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '20px', height: '100%', minHeight: '600px', paddingBottom: '40px' }}>
            <div className="glass" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 24px', borderRadius: 'var(--radius-md)' }}>
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
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(0,0,0,0.2)', padding: '4px 12px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(255,255,255,0.05)' }}>
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
                    borderRadius: 'var(--radius-md)',
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

    const getBrowserTimezone = () => {
        const tz = Intl?.DateTimeFormat?.().resolvedOptions?.().timeZone;
        if (!tz) {
            toast.error("Unable to detect timezone");
            return;
        }
        updateNestedValues([
            { path: 'location.default.timezone', value: tz },
            { path: 'environment.timezone', value: tz }
        ]);
        toast.success("Timezone updated");
    };

    const getBrowserLanguage = () => {
        const lang = navigator?.language || (Array.isArray(navigator?.languages) ? navigator.languages[0] : "");
        if (!lang) {
            toast.error("Unable to detect language");
            return;
        }
        updateNestedValues([
            { path: 'i18n.default_locale', value: lang },
            { path: 'location.default.language', value: lang }
        ]);
        toast.success("Language updated");
    };

    const getTimezoneOptions = () => {
        if (typeof Intl !== 'undefined' && typeof Intl.supportedValuesOf === 'function') {
            try {
                return Intl.supportedValuesOf('timeZone') || [];
            } catch (err) {
                console.warn("Timezone list unavailable", err);
            }
        }
        return [
            "UTC",
            "America/Sao_Paulo",
            "America/New_York",
            "America/Los_Angeles",
            "Europe/London",
            "Europe/Berlin",
            "Asia/Tokyo",
            "Asia/Shanghai"
        ];
    };

    const getLanguageOptions = () => {
        const base = Array.isArray(navigator?.languages) ? navigator.languages : [];
        const fallback = ["pt-BR", "en", "en-US", "es", "es-ES"];
        const combined = [...base, ...fallback]
            .map((value) => String(value || "").trim())
            .filter(Boolean);
        return Array.from(new Set(combined));
    };

    const renderWeather = () => {
        const timezoneValue =
            config?.location?.default?.timezone
            || config?.environment?.timezone
            || config?.environment?.tz
            || '';
        const languageValue =
            config?.location?.default?.language
            || config?.i18n?.default_locale
            || config?.i18n?.fallback_locale
            || config?.environment?.language
            || config?.environment?.locale
            || config?.environment?.lang
            || '';

        return (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
                    <h3 className="section-title">
                        <CloudSun size={20} /> Environmental Data
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '-12px', gap: '8px', flexWrap: 'wrap' }}>
                        <button onClick={getGeolocation} className="btn-ghost" style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Globe size={14} /> Get Current Location
                        </button>
                        <button onClick={getBrowserTimezone} className="btn-ghost" style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Clock size={14} /> Get Timezone
                        </button>
                        <button onClick={getBrowserLanguage} className="btn-ghost" style={{ fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <MessageCircle size={14} /> Get Language
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
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '-6px' }}>
                        <div style={{ fontSize: '12px', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(148,163,184,0.8)' }}>
                            Locale Defaults
                        </div>
                        <div style={{ flex: 1, height: '1px', background: 'rgba(148,163,184,0.15)' }} />
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
                    <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : '1fr 1fr', gap: '20px' }}>
                        <div className="form-group">
                            <label>Timezone</label>
                            <select
                                className="input-field"
                                value={timezoneValue}
                                onChange={(e) => updateNestedValues([
                                    { path: 'location.default.timezone', value: e.target.value },
                                    { path: 'environment.timezone', value: e.target.value }
                                ])}
                            >
                                <option value="" disabled>Select a timezone</option>
                                {(() => {
                                    const current = String(timezoneValue || "").trim();
                                    const options = getTimezoneOptions();
                                    const values = options.includes(current) || !current
                                        ? options
                                        : [current, ...options];
                                    return values.map((tz) => (
                                        <option key={tz} value={tz}>{tz}</option>
                                    ));
                                })()}
                            </select>
                        </div>
                        <div className="form-group">
                            <label>Language</label>
                            <select
                                className="input-field"
                                value={languageValue}
                                onChange={(e) => updateNestedValues([
                                    { path: 'i18n.default_locale', value: e.target.value },
                                    { path: 'location.default.language', value: e.target.value }
                                ])}
                            >
                                <option value="" disabled>Select a language</option>
                                {(() => {
                                    const current = String(languageValue || "").trim();
                                    const options = getLanguageOptions();
                                    const values = options.includes(current) || !current
                                        ? options
                                        : [current, ...options];
                                    return values.map((lang) => (
                                        <option key={lang} value={lang}>{lang}</option>
                                    ));
                                })()}
                            </select>
                        </div>
                    </div>
                    </div>
                </section>
            </div>
        );
    };

    const renderSecurity = () => (
        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '24px', flexWrap: 'wrap' }}>
                    <div>
                        <h3 className="section-title" style={{ marginBottom: '6px' }}>
                            <Shield size={20} /> Vault
                        </h3>
                        <div style={{ fontSize: '12px', color: '#64748b' }}>Create, rotate, audit, and delete secret references without editing raw .env values.</div>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        <button onClick={fetchVaultEntries} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 12px' }}>Refresh</button>
                        <button onClick={runEnvAudit} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 12px' }}>Audit .env</button>
                        <button onClick={() => runEnvImport(false)} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 12px' }}>Import Missing</button>
                        <button onClick={() => runEnvImport(true)} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 12px' }}>Sync Divergent</button>
                    </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: (isMobile || isTablet) ? '1fr' : '1.1fr 1.4fr', gap: '20px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        <div className="form-group" style={{ background: 'rgba(255,255,255,0.03)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(148, 163, 184, 0.15)' }}>
                            <label style={{ fontSize: '12px', color: '#94a3b8' }}>{editingVaultKey ? 'Edit Secret' : 'Create Secret'}</label>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '10px' }}>
                                <input
                                    type="text"
                                    className="input-field"
                                    placeholder="ENV_MY_API_KEY"
                                    value={vaultDraft.key}
                                    disabled={Boolean(editingVaultKey)}
                                    onChange={(e) => setVaultDraft(prev => ({ ...prev, key: e.target.value }))}
                                />
                                <input
                                    type="password"
                                    className="input-field"
                                    placeholder={editingVaultKey ? 'Enter the new secret value' : 'Enter the secret value'}
                                    value={vaultDraft.value}
                                    onChange={(e) => setVaultDraft(prev => ({ ...prev, value: e.target.value }))}
                                />
                                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                    <button onClick={saveVaultSecret} className="btn-primary">{editingVaultKey ? 'Update Secret' : 'Create Secret'}</button>
                                    {(editingVaultKey || vaultDraft.key || vaultDraft.value) && (
                                        <button onClick={resetVaultEditor} className="btn-ghost">Cancel</button>
                                    )}
                                </div>
                            </div>
                        </div>


                        {envAudit && (
                            <div style={{ background: 'rgba(255,255,255,0.03)', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(148, 163, 184, 0.15)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                                    <AlertCircle size={16} color="#fbbf24" />
                                    <strong>Import Audit</strong>
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px', fontSize: '12px', color: '#94a3b8' }}>
                                    <div>Missing: {envAudit?.summary?.missing ?? envAudit?.summary?.imported ?? 0}</div>
                                    <div>Divergent: {envAudit?.summary?.divergent ?? envAudit?.summary?.updated ?? 0}</div>
                                    <div>Matched: {envAudit?.summary?.matched ?? 0}</div>
                                    <div>Ignored: {envAudit?.summary?.ignored ?? 0}</div>
                                </div>
                            </div>
                        )}
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        {(vaultEntries || []).length === 0 ? (
                            <div style={{ padding: '24px', border: '1px dashed rgba(148, 163, 184, 0.2)', borderRadius: 'var(--radius-md)', color: '#94a3b8' }}>No secrets stored in the vault.</div>
                        ) : (
                            (vaultEntries || []).map((entry) => (
                                <div key={entry.key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', padding: '14px 16px', borderRadius: 'var(--radius-md)', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(148, 163, 184, 0.15)' }}>
                                    <div style={{ minWidth: 0 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                                            <CheckCircle size={14} color={entry.has_value ? '#34d399' : '#f59e0b'} />
                                            <span style={{ wordBreak: 'break-all' }}>{entry.key}</span>
                                        </div>
                                        <div style={{ marginTop: '6px', fontSize: '12px', color: '#94a3b8' }}>
                                            Updated: {entry.updated_at || 'n/a'}
                                        </div>
                                    </div>
                                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                        <button onClick={() => openVaultEditor(entry.key)} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 12px' }}>Edit</button>
                                        <button onClick={() => removeVaultSecret(entry.key)} className="btn-ghost" style={{ fontSize: '12px', padding: '6px 12px', color: '#f87171' }}>Delete</button>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </section>
        </div>
    );

    const renderExternalAccounts = () => {
        const providers = config.external_accounts?.providers || {};
        const entries = Object.entries(providers);
        const accounts = Array.isArray(config.external_accounts?.accounts) ? config.external_accounts.accounts : [];
        const visibleExternalCatalog = externalCatalog || [];
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
                const authMode = String(item?.meta?.auth?.mode || '').toLowerCase();
                const connectable = item?.meta?.auth?.connectable === true;
                if (!item?.meta) return false; // only providers backed by plugins
                if (key === 'youtube') return false; // YouTube OAuth flows should piggyback Google account
                return connectable && authMode === 'oauth2';
            });
        const getProviderMeta = (providerKey) => providerCatalogByKey[String(providerKey || '').toLowerCase()] || null;
        const getProviderAuthFields = (providerKey) => {
            const fields = getProviderMeta(providerKey)?.auth?.fields;
            return Array.isArray(fields) ? fields : [];
        };
        const getProviderConfigFields = (providerKey) => {
            const fields = getProviderMeta(providerKey)?.config_fields;
            return Array.isArray(fields) ? fields : [];
        };
        const buildProviderDefaults = (providerKey, plugin = null) => {
            const meta = plugin || getProviderMeta(providerKey) || {};
            const next = { enabled: false };
            for (const field of Array.isArray(meta?.auth?.fields) ? meta.auth.fields : []) {
                next[field.key] = '';
            }
            for (const field of Array.isArray(meta?.config_fields) ? meta.config_fields : []) {
                next[field.key] = field.default ?? '';
            }
            next.scopes = Array.isArray(meta?.default_scopes) ? meta.default_scopes : [];
            return next;
        };

        const addProviderFromPlugin = (plugin) => {
            if (!plugin?.key) return;
            if (providers[plugin.key]) {
                toast.error("Provider already exists.");
                return;
            }
            updateNestedValue(`external_accounts.providers.${plugin.key}`, buildProviderDefaults(plugin.key, plugin));
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

        const renderSecretRefField = (providerKey, provider, fieldMeta) => {
            const fieldKey = String(fieldMeta?.key || '').trim();
            if (!fieldKey) return null;
            const targetPath = `external_accounts.providers.${providerKey}.${fieldKey}`;
            const currentValue = provider?.[fieldKey] || '';
            const options = Array.from(new Set([...(envKeys || []), ...(currentValue ? [currentValue] : [])]));
            const creating = externalSecretEditor.target === targetPath;

            return (
                <div key={`${providerKey}_${fieldKey}`} className="form-group" style={{ background: 'rgba(var(--accent-rgb), 0.05)', padding: '14px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(var(--accent-rgb), 0.2)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Shield size={14} color="var(--accent-color)" /> {fieldMeta.title}
                        </label>
                        <button
                            onClick={() => creating ? setExternalSecretEditor({ target: '', key: '', value: '' }) : openSecretEditor(targetPath, providerKey, fieldKey)}
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
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: 'var(--radius-md)' }}>
                            <input
                                type="text"
                                className="input-field"
                                value={externalSecretEditor.key}
                                placeholder={fieldMeta.placeholder || 'ENV_PROVIDER_SECRET'}
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
                                onClick={() => createAndBindExternalSecret(targetPath)}
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
            const providerMeta = getProviderMeta(providerKey);
            const redirectUri = String(providerDraft?.redirect_uri || '').trim();
            const clientRef = String(providerDraft?.client_id || '').trim();
            if (String(providerMeta?.auth?.mode || '').toLowerCase() !== 'oauth2') {
                toast.error(`Provider ${providerKey} is not OAuth2-enabled.`);
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
                <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
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
                            <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 'var(--radius-md)', padding: '14px' }}>
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
                                                        borderRadius: 'var(--radius-md)'
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
                                        <div key={account?.id || `acc_${idx}`} style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 'var(--radius-md)', padding: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
                            <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 'var(--radius-md)', padding: '14px', marginBottom: '4px' }}>
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
                                            <div key={plugin.key} style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: 'var(--radius-md)', padding: '10px' }}>
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
                                    <div key={providerKey} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 'var(--radius-md)', padding: '12px 14px' }}>
                                        <div style={{ minWidth: 0 }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <span style={{ width: '8px', height: '8px', borderRadius: '999px', background: provider?.enabled ? '#22c55e' : '#ef4444', display: 'inline-block' }} />
                                                <strong style={{ textTransform: 'capitalize', fontSize: '14px' }}>{providerKey.replace(/_/g, ' ')}</strong>
                                                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{getProviderMeta(providerKey)?.auth?.mode || 'custom'}</span>
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
                                    <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
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
                                                const authFields = getProviderAuthFields(editingProviderKey);
                                                const configFields = getProviderConfigFields(editingProviderKey);
                                                return (
                                                    <>
                                            {authFields.map((field) => renderSecretRefField(editingProviderKey, providers?.[editingProviderKey], field))}
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
                                            {configFields.map((field) => (
                                                <div className="form-group" key={`${editingProviderKey}_${field.key}`}>
                                                    <label>{field.title}</label>
                                                    <input
                                                        type="text"
                                                        className="input-field"
                                                        value={providers?.[editingProviderKey]?.[field.key] ?? ''}
                                                        onChange={(e) => updateNestedValue(`external_accounts.providers.${editingProviderKey}.${field.key}`, e.target.value)}
                                                        placeholder={field.placeholder || ''}
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
            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
                <h3 className="section-title">
                    <Cpu size={20} /> Chat & Reasoning (Cortex)
                </h3>
                <ModelPoolManager
                    modality="chat"
                    currentPool={config.cortex?.chat || []}
                    onPoolUpdated={(newPool) => updateNestedValue('cortex.chat', newPool)}
                />
            </section>

            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
                <h3 className="section-title">
                    <Monitor size={20} /> Vision & Perception
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
        <div className="animate-fade-in flex-1" style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', height: '100%', gap: 0, maxHeight: '100%', overflow: 'hidden' }}>
            {/* Sidebar Navigation */}
            <aside className="glass custom-scrollbar" style={{
                width: isMobile ? '100%' : (isTabsCollapsed ? '60px' : '260px'),
                height: isMobile ? 'auto' : '100%',
                display: 'flex',
                flexDirection: isMobile ? 'row' : 'column',
                overflowX: isMobile ? 'auto' : 'hidden',
                overflowY: isMobile ? 'hidden' : 'auto',
                transition: 'var(--transition)',
                borderRadius: 'var(--radius-md)',
                flexShrink: 0,
                padding: isMobile ? '4px' : '0'
            }}>
                {!isMobile && (
                    <div className="glass" style={{
                        margin: '12px 12px 12px 12px',
                        padding: isTabsCollapsed ? '8px 0' : '8px 14px',
                        borderRadius: 'var(--radius-md)',
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
                                borderRadius: 'var(--radius-md)',
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
                borderRadius: 'var(--radius-md)'
            }}>
                {renderHeader()}

                <div style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '16px' : (isTablet ? '24px' : '32px') }} className="custom-scrollbar">
                    {activeTab === 'general' && renderGeneral()}
                    {activeTab === 'interfaces' && renderInterfaces()}
                    {activeTab === 'media' && renderMedia()}
                    {activeTab === 'network' && renderNetwork()}
                    {activeTab === 'external_accounts' && renderExternalAccounts()}
                    {activeTab === 'llm' && renderLLM()}
                    {activeTab === 'capabilities' && renderCapabilities()}
                    {activeTab === 'mcp' && renderMcp()}
                    {activeTab === 'stt' && (
                        <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
                                <h3 className="section-title"><Mic size={20} /> Speech Recognition (STT)</h3>
                                <ModelPoolManager
                                    modality="stt"
                                    currentPool={config.cortex?.audio?.stt || []}
                                    onPoolUpdated={(newPool) => updateNestedValue('cortex.audio.stt', newPool)}
                                />
                            </section>

                            <section className="glass-card" style={{ padding: '24px', borderRadius: 'var(--radius-md)' }}>
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
                            <div className="glass" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 24px', borderRadius: 'var(--radius-md)' }}>
                                <h3 className="section-title" style={{ marginBottom: 0 }}>
                                    <FileJson size={20} /> Master Schema
                                </h3>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                    {(() => {
                                        try {
                                            JSON.parse(rawJson);
                                            return <span className="status-pill online">Valid JSON</span>;
                                        } catch {
                                            return <span className="status-pill offline">Invalid JSON</span>;
                                        }
                                    })()}
                                    <button
                                        onClick={() => {
                                            try {
                                                const pretty = JSON.stringify(JSON.parse(rawJson), null, 4);
                                                setRawJson(pretty);
                                                toast.success("JSON Formatted");
                                            } catch {
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
                                borderRadius: 'var(--radius-md)',
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
                                        } catch {
                                            // Keep raw editor permissive while JSON is temporarily invalid.
                                        }
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
                    background: rgba(0, 0, 0, 0.25);
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: 6px;
                    color: var(--text-main);
                    font-size: 14px;
                    transition: all 0.2s ease;
                }
                .input-field:focus {
                    outline: none;
                    border-color: rgba(0, 242, 255, 0.3);
                    box-shadow: 0 0 15px rgba(0, 242, 255, 0.05), inset 0 0 0 1px rgba(0, 242, 255, 0.1);
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
                    padding: 16px 20px;
                    border-radius: 10px;
                    background: rgba(0, 0, 0, 0.15);
                    border: 1px solid rgba(255, 255, 255, 0.04);
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
                .capability-card {
                    padding: 16px;
                    border-radius: 14px;
                    transition: all 0.2s;
                }
                .capability-card:hover {
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
