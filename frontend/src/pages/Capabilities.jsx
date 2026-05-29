import { notify } from '../utils/notify.jsx';
import { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from '../hooks/api';
import {
    Puzzle,
    Settings2,
    ToggleRight,
    ToggleLeft,
    CheckCircle2,
    XCircle,
    HelpCircle,
    X,
    Save,
    Shield,
    AlertCircle,
    Search as SearchIcon,
    RefreshCw,
    LayoutGrid,
    List,
    SlidersHorizontal
} from 'lucide-react';

import PageHeader from '../components/PageHeader';
import CapabilityIcon from '../components/CapabilityIcon';
import { createSecret, listSecretRefs } from '../utils/secretsApi';

const CAPABILITIES_VIEW_MODE_KEY = 'capabilities.hub.view_mode';

const Capabilities = () => {
    const [capabilities, setCapabilities] = useState([]);
    const [loading, setLoading] = useState(true);
    const [configuringCapability, setConfiguringCapability] = useState(null);
    const [detailCapability, setDetailCapability] = useState(null);
    const [configValues, setConfigValues] = useState({});
    const [envKeys, setEnvKeys] = useState([]);
    const [secretEditor, setSecretEditor] = useState({ target: '', key: '', value: '' });
    const [isSaving, setIsSaving] = useState(false);
    const [retrievalControlPlane, setRetrievalControlPlane] = useState(null);
    const [retrievalControlPlaneLoading, setRetrievalControlPlaneLoading] = useState(false);
    const [retrievalOffers, setRetrievalOffers] = useState([]);
    const [retrievalOffersLoading, setRetrievalOffersLoading] = useState(false);
    const [retrievalControlPlaneSaving, setRetrievalControlPlaneSaving] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [viewMode, setViewMode] = useState(() => {
        try {
            const saved = window.localStorage.getItem(CAPABILITIES_VIEW_MODE_KEY);
            return saved === 'list' ? 'list' : 'grid';
        } catch {
            return 'grid';
        }
    });
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);
    const [isTablet, setIsTablet] = useState(window.innerWidth > 640 && window.innerWidth <= 1024);
    const getConfigValue = useCallback(
        (path, source = configValues) => path.split('.').reduce((obj, k) => obj?.[k], source),
        [configValues]
    );
    const authFieldsByPath = useMemo(() => {
        const auth = configuringCapability?.auth;
        const fields = Array.isArray(auth?.fields) ? auth.fields : [];
        const map = {};
        for (const field of fields) {
            if (!field || typeof field !== 'object') continue;
            const path = String(field.config_path || '').trim();
            if (!path) continue;
            map[path] = field;
        }
        return map;
    }, [configuringCapability]);
    const authSourceConfigPath = useMemo(() => {
        const auth = configuringCapability?.auth;
        return typeof auth?.source_config_path === 'string' ? auth.source_config_path : '';
    }, [configuringCapability]);
    const authSources = useMemo(() => {
        const auth = configuringCapability?.auth;
        return Array.isArray(auth?.sources) ? auth.sources : [];
    }, [configuringCapability]);
    const selectedAuthSource = useMemo(() => {
        if (!authSourceConfigPath) return '';
        const current = getConfigValue(authSourceConfigPath, configValues);
        return String(current || configuringCapability?.auth?.default_source || '').trim();
    }, [authSourceConfigPath, configValues, configuringCapability, getConfigValue]);

    useEffect(() => {
        const handleResize = () => {
            setIsMobile(window.innerWidth <= 640);
            setIsTablet(window.innerWidth > 640 && window.innerWidth <= 1024);
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);


    useEffect(() => {
        fetchCapabilities();
        fetchEnvKeys();
    }, []);

    useEffect(() => {
        try {
            window.localStorage.setItem(CAPABILITIES_VIEW_MODE_KEY, viewMode);
        } catch {
            // ignore storage failures
        }
    }, [viewMode]);

    const fetchCapabilities = async () => {
        try {
            const data = await api.get('/capabilities/');
            setCapabilities(data);
        } catch (err) {
            notify.error("Failed to load capabilities: " + err.message);
        } finally {
            setLoading(false);
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

    const handleToggle = async (id, currentStatus) => {
        try {
            await api.patch(`/capabilities/${id}/config`, { enabled: !currentStatus });
            notify.success(`Capability ${!currentStatus ? 'enabled' : 'disabled'}`);
            fetchCapabilities();
        } catch (err) {
            notify.error(err.message);
        }
    };

    const handleOpenConfig = (capability) => {
        setConfiguringCapability(capability);
        const nextConfig = { ...(capability.config || {}) };
        const auth = capability?.auth || {};
        if (auth?.mode === 'hybrid' && auth?.source_config_path) {
            const existing = getConfigValue(auth.source_config_path, nextConfig);
            if (!existing && auth.default_source) {
                nextConfig[auth.source_config_path] = auth.default_source;
            }
        }
        setConfigValues(nextConfig);
        setSecretEditor({ target: '', key: '', value: '' });
        fetchEnvKeys();
    };

    const handleOpenDetails = (capability) => {
        setDetailCapability(capability);
        if (capability?.id === 'research_retrieve') {
            setRetrievalControlPlaneLoading(true);
            setRetrievalOffersLoading(true);
            Promise.all([
                api.get('/capabilities/retrieval/control-plane'),
                api.get('/capabilities/retrieval/offers'),
            ])
                .then(([controlPlaneData, offersData]) => {
                    setRetrievalControlPlane(controlPlaneData || null);
                    setRetrievalOffers(Array.isArray(offersData?.offers) ? offersData.offers : []);
                })
                .catch(() => {
                    setRetrievalControlPlane(null);
                    setRetrievalOffers([]);
                })
                .finally(() => {
                    setRetrievalControlPlaneLoading(false);
                    setRetrievalOffersLoading(false);
                });
        } else {
            setRetrievalControlPlane(null);
            setRetrievalOffers([]);
            setRetrievalControlPlaneLoading(false);
            setRetrievalOffersLoading(false);
        }
    };

    const isProviderDisabled = (providerId) => {
        const overrides = retrievalControlPlane?.overrides;
        if (!overrides || typeof overrides !== 'object') return false;
        const row = overrides[providerId];
        return !!(row && typeof row === 'object' && row.disabled);
    };

    const getProviderOverride = (providerId) => {
        const overrides = retrievalControlPlane?.overrides;
        if (!overrides || typeof overrides !== 'object') return {};
        const row = overrides[providerId];
        if (!row || typeof row !== 'object') return {};
        return row;
    };

    const toggleProviderFlag = async (providerId, flag) => {
        if (!providerId || !flag || retrievalControlPlaneSaving) return;
        setRetrievalControlPlaneSaving(true);
        try {
            const currentOverrides = (retrievalControlPlane?.overrides && typeof retrievalControlPlane.overrides === 'object')
                ? retrievalControlPlane.overrides
                : {};
            const currentRow = (currentOverrides[providerId] && typeof currentOverrides[providerId] === 'object')
                ? currentOverrides[providerId]
                : {};
            const nextValue = !currentRow[flag];
            const payload = {
                overrides: {
                    [providerId]: {
                        ...currentRow,
                        [flag]: nextValue,
                    },
                },
            };
            const updated = await api.patch('/capabilities/retrieval/control-plane', payload);
            setRetrievalControlPlane(updated || null);
            notify.success(`${providerId} ${flag}=${nextValue ? 'on' : 'off'}`);
        } catch (err) {
            notify.error(err.message || 'Failed to update retrieval control plane');
        } finally {
            setRetrievalControlPlaneSaving(false);
        }
    };

    const handleSaveConfig = async () => {
        setIsSaving(true);
        try {
            await api.patch(`/capabilities/${configuringCapability.id}/config`, configValues);
            notify.success("Configuration updated successfully!");
            setConfiguringCapability(null);
            fetchCapabilities();
        } catch (err) {
            const msg = err.response?.data?.detail?.errors?.join(', ') || err.message;
            notify.error("Validation Error: " + msg);
        } finally {
            setIsSaving(false);
        }
    };

    const updateConfigValue = (path, value) => {
        const keys = path.split('.');
        if (keys.length === 1) {
            setConfigValues({ ...configValues, [path]: value });
        } else {
            const newValues = { ...configValues };
            let current = newValues;
            for (let i = 0; i < keys.length - 1; i++) {
                const key = keys[i];
                current[key] = { ...current[key] };
                current = current[key];
            }
            current[keys[keys.length - 1]] = value;
            setConfigValues(newValues);
        }
    };

    const suggestedEnvName = (capabilityId, fullPath) => {
        const capToken = String(capabilityId || 'capability').toUpperCase().replace(/[^A-Z0-9]+/g, '_');
        const fieldToken = String(fullPath || 'SECRET').toUpperCase().replace(/[^A-Z0-9]+/g, '_');
        return `ENV_${capToken}_${fieldToken}`;
    };

    const openSecretEditor = (targetPath, capabilityId) => {
        const current = getConfigValue(targetPath);
        setSecretEditor({
            target: targetPath,
            key: typeof current === 'string' && current.startsWith('ENV_') ? current : suggestedEnvName(capabilityId, targetPath),
            value: '',
        });
    };

    const createSecretAndBind = async (targetPath) => {
        const key = String(secretEditor.key || '').trim();
        const value = String(secretEditor.value || '').trim();
        if (!key || !value) {
            notify.error("Key and value are required.");
            return;
        }
        try {
            const res = await createSecret({ key, value });
            if (res?.success) {
                const boundKey = String(res?.key || key).trim();
                updateConfigValue(targetPath, boundKey);
                setSecretEditor({ target: '', key: '', value: '' });
                await fetchEnvKeys();
                notify.success(`Secret ${boundKey} created and linked.`);
            }
        } catch (err) {
            notify.error(err.message || 'Failed to create secret');
        }
    };

    const renderAuthStrategyBlock = () => {
        const auth = configuringCapability?.auth;
        if (!auth || auth.mode !== 'hybrid' || !authSourceConfigPath || authSources.length === 0) {
            return null;
        }

        return (
            <div style={{
                marginBottom: '12px',
                padding: '12px',
                background: 'rgba(255,255,255,0.02)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid rgba(148,163,184,0.15)'
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    <Shield size={13} color="var(--accent-color)" />
                    <strong style={{ fontSize: '12px' }}>Authentication Strategy</strong>
                </div>
                <p style={{ fontSize: '10px', color: '#94a3b8', marginBottom: '10px', lineHeight: '1.35' }}>
                    This capability supports multiple authentication sources. Choose the source of truth explicitly.
                </p>
                <select
                    className="glass-input"
                    style={{ height: '34px', minHeight: '34px', padding: '6px 8px', borderRadius: '6px', fontSize: '12px', width: '100%', marginBottom: '10px' }}
                    value={selectedAuthSource || configuringCapability?.auth?.default_source || ''}
                    onChange={(e) => updateConfigValue(authSourceConfigPath, e.target.value)}
                >
                    {authSources.map((source) => (
                        <option key={source.id} value={source.id}>{source.title}</option>
                    ))}
                </select>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {authSources.map((source) => {
                        const active = source.id === selectedAuthSource;
                        return (
                            <div
                                key={source.id}
                                style={{
                                    padding: '10px',
                                    borderRadius: 'var(--radius-md)',
                                    border: active ? '1px solid rgba(var(--accent-rgb), 0.35)' : '1px solid rgba(148,163,184,0.12)',
                                    background: active ? 'rgba(var(--accent-rgb), 0.07)' : 'rgba(255,255,255,0.02)'
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                                    <span style={{ fontSize: '11px', fontWeight: '700' }}>{source.title}</span>
                                    <span style={{ fontSize: '9px', color: active ? 'var(--accent-color)' : '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                                        {String(source.type || '').replace('_', ' ')}
                                    </span>
                                </div>
                                {source.description && (
                                    <p style={{ fontSize: '10px', color: '#94a3b8', margin: 0, lineHeight: '1.35' }}>
                                        {source.description}
                                    </p>
                                )}
                                {source.provider && (
                                    <p style={{ fontSize: '10px', color: '#64748b', marginTop: '4px', marginBottom: 0 }}>
                                        Provider: {source.provider}
                                    </p>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    };

    const renderField = (key, schema, path = '') => {
        const fullPath = path ? `${path}.${key}` : key;
        if (!path && authSourceConfigPath && fullPath === authSourceConfigPath) {
            return null;
        }
        const authField = authFieldsByPath[fullPath];
        const isSecret = authField?.type === 'secret_ref';
        const ui = schema['x-ui'] || {};

        // Handle nested objects
        if (schema.type === 'object' && schema.properties) {
            return (
                <div key={fullPath} style={{
                    marginBottom: '10px',
                    padding: '8px 10px',
                    background: 'rgba(255,255,255,0.01)',
                    borderRadius: '7px',
                    border: '1px solid rgba(255,255,255,0.04)'
                }}>
                    <h4 style={{
                        fontSize: '11px',
                        fontWeight: '800',
                        marginBottom: '8px',
                        color: 'var(--text-muted)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.07em',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px'
                    }}>
                        <div style={{ width: '3px', height: '3px', background: 'var(--text-muted)', borderRadius: '50%' }}></div>
                        {schema.title || key}
                    </h4>
                    {schema.description && (
                        <p style={{
                            margin: '0 0 8px 0',
                            fontSize: '10px',
                            color: '#94a3b8',
                            lineHeight: '1.35'
                        }}>
                            {schema.description}
                        </p>
                    )}
                    {Object.entries(schema.properties).map(([subKey, subSchema]) => renderField(subKey, subSchema, fullPath))}
                </div>
            );
        }

        const widget = ui.widget || (schema.enum ? 'select' : (schema.type === 'boolean' ? 'checkbox' : 'text'));
        const currentValue = getConfigValue(fullPath);
        const parseInputBySchema = (rawValue) => {
            if (rawValue === '') return '';
            if (schema?.type === 'integer') {
                const parsed = Number(rawValue);
                if (Number.isNaN(parsed)) return rawValue;
                return Math.trunc(parsed);
            }
            if (schema?.type === 'number') {
                const parsed = Number(rawValue);
                if (Number.isNaN(parsed)) return rawValue;
                return parsed;
            }
            return rawValue;
        };

        if (isSecret) {
            const creating = secretEditor.target === fullPath;
            const currentRef = typeof currentValue === 'string' ? currentValue : '';
            const options = Array.from(new Set([...(envKeys || []), ...(currentRef && currentRef !== '********' ? [currentRef] : [])]));
            return (
                <div key={fullPath} className="form-group" style={{ marginBottom: '10px', background: 'rgba(var(--accent-rgb), 0.05)', padding: '10px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(var(--accent-rgb), 0.18)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: 0, fontSize: '11px', fontWeight: '700', color: 'var(--text-main)' }}>
                            <Shield size={12} color="var(--accent-color)" />
                            {authField?.title || schema.title || key}
                        </label>
                        <button
                            onClick={() => creating ? setSecretEditor({ target: '', key: '', value: '' }) : openSecretEditor(fullPath, configuringCapability?.id)}
                            className="btn-ghost"
                            style={{ fontSize: '10px', padding: '3px 8px', color: 'var(--accent-color)' }}
                        >
                            {creating ? 'Cancel' : '+ Create New Key'}
                        </button>
                    </div>

                    {((authField?.description || schema.description) || (configuringCapability?.auth?.mode === 'hybrid' && selectedAuthSource === 'linked_account')) && (
                        <p style={{ fontSize: '10px', color: '#94a3b8', marginBottom: '6px', lineHeight: '1.3' }}>
                            {authField?.description || schema.description || ''}
                            {configuringCapability?.auth?.mode === 'hybrid' && selectedAuthSource === 'linked_account'
                                ? `${(authField?.description || schema.description) ? ' ' : ''}Stored only as an optional fallback while this capability is configured to use linked account only.`
                                : ''}
                        </p>
                    )}

                    {!creating ? (
                        <select
                            className="glass-input"
                            style={{ height: '32px', minHeight: '32px', padding: '5px 8px', borderRadius: '6px', fontSize: '12px', width: '100%' }}
                            value={currentRef === '********' ? '' : currentRef}
                            onChange={(e) => updateConfigValue(fullPath, e.target.value)}
                        >
                            <option value="">-- Select Environment Key --</option>
                            {options.map((envKey) => (
                                <option key={envKey} value={envKey}>{envKey}</option>
                            ))}
                        </select>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '7px', background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: 'var(--radius-md)' }}>
                            <input
                                type="text"
                                className="glass-input"
                                style={{ height: '32px', minHeight: '32px', padding: '5px 8px', borderRadius: '6px', fontSize: '12px', width: '100%' }}
                                value={secretEditor.key}
                                placeholder={ui.placeholder || `ENV_${String(authField?.id || 'CAPABILITY_SECRET').toUpperCase()}`}
                                onChange={(e) => setSecretEditor(prev => ({ ...prev, key: e.target.value }))}
                            />
                            <input
                                type="password"
                                className="glass-input"
                                style={{ height: '32px', minHeight: '32px', padding: '5px 8px', borderRadius: '6px', fontSize: '12px', width: '100%' }}
                                value={secretEditor.value}
                                placeholder="Paste the secret value here..."
                                onChange={(e) => setSecretEditor(prev => ({ ...prev, value: e.target.value }))}
                            />
                            <button
                                onClick={() => createSecretAndBind(fullPath)}
                                className="btn-primary"
                                style={{ alignSelf: 'flex-start', fontSize: '12px', padding: '6px 10px' }}
                            >
                                Save to Vault
                            </button>
                        </div>
                    )}
                </div>
            );
        }

        return (
            <div key={fullPath} style={{ marginBottom: '9px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>
                    {schema.title || key}
                </label>

                {schema.description && (
                    <p style={{ fontSize: '10px', color: '#94a3b8', marginBottom: '5px', lineHeight: '1.3' }}>
                        {schema.description}
                    </p>
                )}

                {widget === 'checkbox' ? (
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => updateConfigValue(fullPath, !currentValue)}
                            className={`flex items-center gap-2 p-2 rounded ${currentValue ? 'text-accent' : 'text-slate-500'}`}
                        >
                            {currentValue ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
                            <span className="text-sm">{currentValue ? 'Active' : 'Inactive'}</span>
                        </button>
                    </div>
                ) : widget === 'select' ? (
                    <select
                        className="glass-input"
                        style={{ height: '32px', minHeight: '32px', padding: '5px 8px', borderRadius: '6px', fontSize: '12px' }}
                        value={currentValue || ''}
                        onChange={(e) => updateConfigValue(fullPath, parseInputBySchema(e.target.value))}
                    >
                        {schema.enum?.map(opt => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                ) : (
                    <div style={{ position: 'relative' }}>
                        <input
                            type={
                                widget === 'password' || isSecret
                                    ? 'password'
                                    : (schema?.type === 'integer' || schema?.type === 'number')
                                        ? 'number'
                                        : 'text'
                            }
                            className="glass-input"
                            style={{
                                width: '100%',
                                height: '32px',
                                minHeight: '32px',
                                padding: '5px 8px',
                                paddingRight: isSecret ? '28px' : '8px',
                                background: 'var(--bg-color)',
                                border: '1px solid var(--card-border)',
                                borderRadius: '6px',
                                color: 'var(--text-main)',
                                fontSize: '12px',
                            }}
                            placeholder={ui.placeholder || schema.default || ''}
                            value={currentValue || ''}
                            step={schema?.type === 'integer' ? '1' : (schema?.type === 'number' ? 'any' : undefined)}
                            onChange={(e) => updateConfigValue(fullPath, parseInputBySchema(e.target.value))}
                        />
                        {isSecret && <div style={{ position: 'absolute', right: '8px', top: '8px', opacity: 0.5 }}><Shield size={12} /></div>}
                    </div>
                )}

                {currentValue === '********' && (
                    <p style={{ fontSize: '9px', color: 'var(--accent-color)', marginTop: '4px' }}>
                        Secret is masked. Type to overwrite.
                    </p>
                )}
            </div>
        );
    };

    const renderConfigForm = () => {
        const schema = configuringCapability?.config_schema;
        if (!schema || !schema.properties) return <p style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>No specific configuration required for this capability.</p>;

        return (
            <>
                {renderAuthStrategyBlock()}
                {Object.entries(schema.properties).map(([key, propSchema]) => renderField(key, propSchema))}
            </>
        );
    };

    const getRetrievalSetupIssues = (capability) => {
        const runtime = capability?.retrieval_runtime;
        if (!runtime || typeof runtime !== 'object') return [];
        const profile = capability?.retrieval_profile;
        if (!profile || typeof profile !== 'object' || !profile.enabled) return [];
        const setupReady = runtime.setup_ready;
        const missing = Array.isArray(runtime.missing_required_fields) ? runtime.missing_required_fields : [];
        if (setupReady === false && missing.length > 0) {
            return missing.map((field) => `Retrieval setup missing: ${field}`);
        }
        if (runtime.operational_state === 'disabled') return ['Retrieval provider is disabled by runtime control plane.'];
        if (runtime.operational_state === 'degraded') return ['Retrieval provider is marked as degraded in runtime control plane.'];
        if (runtime.operational_state === 'quota_exceeded') return ['Retrieval provider quota exceeded in runtime control plane.'];
        if (runtime.operational_state === 'error_previous') return ['Retrieval provider temporarily blocked due to previous runtime error.'];
        return [];
    };

    const getRetrievalRuntime = (capability) => {
        const runtime = capability?.retrieval_runtime;
        if (!runtime || typeof runtime !== 'object') return null;
        return runtime;
    };

    const getRetrievalStateLabel = (capability) => {
        const runtime = getRetrievalRuntime(capability);
        const state = String(runtime?.operational_state || '').trim();
        if (!state) return null;
        if (state === 'ready') return 'RAG ready';
        if (state === 'setup_pending') return 'RAG setup pending';
        if (state === 'disabled') return 'RAG disabled';
        if (state === 'degraded') return 'RAG degraded';
        if (state === 'quota_exceeded') return 'RAG quota exceeded';
        if (state === 'error_previous') return 'RAG temporary error';
        return `RAG ${state}`;
    };

    const filteredCapabilities = capabilities.filter(s =>
        s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.actions?.some(a => a.toLowerCase().includes(searchQuery.toLowerCase()))
    );
    const modalShellStyle = {
        width: isMobile ? 'calc(100% - 14px)' : 'min(94%, 700px)',
        maxHeight: 'calc(100% - 12px)',
        display: 'flex',
        flexDirection: 'column',
        borderRadius: isMobile ? '10px' : '12px',
        margin: '6px auto',
        border: '1px solid rgba(148,163,184,0.24)',
        boxShadow: '0 12px 42px rgba(2,6,23,0.18)',
    };
    const configModalShellStyle = {
        width: isMobile ? 'calc(100% - 14px)' : 'min(92%, 560px)',
        maxHeight: 'calc(100% - 12px)',
        display: 'flex',
        flexDirection: 'column',
        borderRadius: isMobile ? '10px' : '12px',
        margin: '6px auto',
        border: '1px solid rgba(148,163,184,0.24)',
        boxShadow: '0 12px 42px rgba(2,6,23,0.18)',
    };
    // Using global modal-overlay

    return (
        <div className="animate-fade-in" style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <PageHeader
                title="Capabilities Hub"
                subtitle="Manage and monitor your agent's modular capabilities."
            >
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    width: '100%',
                    justifyContent: 'flex-end',
                    flexDirection: isMobile ? 'column' : 'row',
                }}>
                    <div
                        style={{
                            position: 'relative',
                            width: isMobile ? '100%' : '320px',
                            maxWidth: '100%',
                        }}
                        className="full-width-mobile"
                    >
                        <SearchIcon size={16} style={{ position: 'absolute', left: '12px', top: '10px', color: '#64748b', pointerEvents: 'none' }} />
                        <input
                            type="text"
                            placeholder="Search capabilities..."
                            className="glass-input"
                            style={{ paddingLeft: '36px', width: '100%', height: '36px', borderRadius: 'var(--radius-sm)', fontSize: '0.8125rem' }}
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        border: '1px solid var(--card-border)',
                        borderRadius: 'var(--radius-md)',
                        padding: '3px',
                        background: 'rgba(255,255,255,0.02)',
                        alignSelf: isMobile ? 'flex-end' : 'auto',
                    }}>
                        <button
                            className="btn-ghost"
                            onClick={() => setViewMode('grid')}
                            title="Grid view"
                            style={{
                                padding: '6px 8px',
                                borderRadius: 'var(--radius-md)',
                                background: viewMode === 'grid' ? 'var(--accent-glow)' : 'transparent',
                                color: viewMode === 'grid' ? 'var(--accent-color)' : 'var(--text-muted)'
                            }}
                        >
                            <LayoutGrid size={14} />
                        </button>
                        <button
                            className="btn-ghost"
                            onClick={() => setViewMode('list')}
                            title="List view"
                            style={{
                                padding: '6px 8px',
                                borderRadius: 'var(--radius-md)',
                                background: viewMode === 'list' ? 'var(--accent-glow)' : 'transparent',
                                color: viewMode === 'list' ? 'var(--accent-color)' : 'var(--text-muted)'
                            }}
                        >
                            <List size={14} />
                        </button>
                    </div>
                </div>
            </PageHeader>

            <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '0 var(--space-2)' : '0 6px' }}>
                <div style={{
                    display: viewMode === 'grid' ? 'grid' : 'flex',
                    flexDirection: viewMode === 'list' ? 'column' : undefined,
                    gridTemplateColumns: viewMode === 'grid' ? (isMobile ? 'repeat(2, minmax(0, 1fr))' : (isTablet ? 'repeat(3, minmax(0, 1fr))' : 'repeat(auto-fill, minmax(220px, 1fr))')) : undefined,
                    gap: viewMode === 'grid' ? (isMobile ? '10px' : '12px') : (isMobile ? '10px' : '8px'),
                    paddingBottom: '100px',
                    padding: isMobile ? '8px 0' : '0',
                    width: '100%',
                }}>
                    {loading ? (
                        <div style={{ textAlign: 'center', padding: '100px', gridColumn: '1 / -1' }}>
                            <div className="loading-spinner" style={{ margin: '0 auto 20px' }}></div>
                            <p style={{ color: '#64748b' }}>Discovering installed capabilities...</p>
                        </div>
                    ) : filteredCapabilities.length > 0 ? filteredCapabilities.map(capability => (
                        (() => {
                            const retrievalIssues = getRetrievalSetupIssues(capability);
                            const hasIssues = (capability.validation_errors?.length > 0 || capability.missing_required?.length > 0 || retrievalIssues.length > 0);
                            return (
                        viewMode === 'grid' ? (
                        <div key={capability.id} className="glass-card" style={{
                            padding: isMobile ? '10px' : '10px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '8px',
                            borderRadius: 'var(--radius-md)',
                            border: hasIssues
                                ? '1px solid rgba(239, 68, 68, 0.3)'
                                : (!capability.enabled ? '1px solid rgba(148, 163, 184, 0.28)' : '1px solid var(--card-border)'),
                            background: !capability.enabled ? 'linear-gradient(180deg, rgba(148,163,184,0.06), rgba(148,163,184,0.02))' : undefined,
                            opacity: !capability.enabled ? 0.74 : 1,
                            filter: !capability.enabled ? 'grayscale(0.25)' : 'none',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
                                    <CapabilityIcon
                                        variant="display"
                                        capabilityId={capability.id}
                                        assets={capability.assets}
                                        size={22}
                                    />
                                    <h3 style={{
                                        fontSize: '14px',
                                        fontWeight: '800',
                                        margin: 0,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                        color: !capability.enabled ? '#9ca3af' : 'var(--text-main)',
                                    }}>{capability.name}</h3>
                                </div>
                                {capability.enabled ? (
                                    <span className="badge badge-success" style={{ fontSize: '9px', padding: '2px 6px' }}>Active</span>
                                ) : (
                                    <span className="badge badge-slate" style={{ fontSize: '9px', padding: '2px 6px' }}>Off</span>
                                )}
                            </div>

                            <p style={{
                                fontSize: '11px',
                                color: '#94a3b8',
                                lineHeight: '1.35',
                                margin: 0,
                                minHeight: '30px',
                                display: '-webkit-box',
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: 'vertical',
                                overflow: 'hidden'
                            }}>
                                {capability.description}
                            </p>

                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                {capability.actions?.slice(0, 2).map(a => (
                                    <span key={a} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.05)', padding: '1px 6px', borderRadius: '100px', color: '#cbd5e1' }}>{a}</span>
                                ))}
                                {capability.actions?.length > 2 && <span style={{ fontSize: '9px', opacity: 0.6 }}>+{capability.actions.length - 2}</span>}
                                {capability.retrieval_profile?.enabled && (
                                    <span
                                        style={{
                                            fontSize: '9px',
                                            background: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(capability)?.operational_state || ''))
                                                ? 'rgba(239,68,68,0.18)'
                                                : (String(getRetrievalRuntime(capability)?.operational_state || '') === 'degraded'
                                                    ? 'rgba(245,158,11,0.16)'
                                                    : 'rgba(34,197,94,0.16)'),
                                            color: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(capability)?.operational_state || ''))
                                                ? '#fca5a5'
                                                : (String(getRetrievalRuntime(capability)?.operational_state || '') === 'degraded' ? '#fcd34d' : '#86efac'),
                                            padding: '1px 6px',
                                            borderRadius: '100px',
                                            border: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(capability)?.operational_state || ''))
                                                ? '1px solid rgba(239,68,68,0.24)'
                                                : (String(getRetrievalRuntime(capability)?.operational_state || '') === 'degraded'
                                                    ? '1px solid rgba(245,158,11,0.24)'
                                                    : '1px solid rgba(34,197,94,0.24)'),
                                        }}
                                    >
                                        {getRetrievalStateLabel(capability) || 'RAG ready'}
                                    </span>
                                )}
                            </div>

                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                gap: '8px',
                                marginTop: '2px',
                            }}>
                                <button
                                    onClick={() => handleToggle(capability.id, capability.enabled)}
                                    style={{
                                        background: capability.enabled ? 'rgba(16,185,129,0.12)' : 'rgba(148,163,184,0.14)',
                                        border: capability.enabled ? '1px solid rgba(16,185,129,0.35)' : '1px solid rgba(148,163,184,0.28)',
                                        borderRadius: 'var(--radius-md)',
                                        cursor: 'pointer',
                                        transition: 'transform 0.2s',
                                        width: '36px',
                                        height: '28px',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                    }}
                                    className="hover:scale-110"
                                    title={capability.enabled ? 'Disable capability' : 'Enable capability'}
                                >
                                    {capability.enabled ? <ToggleRight size={24} color="var(--accent-color)" /> : <ToggleLeft size={24} color="#475569" />}
                                </button>
                                <button
                                    onClick={() => handleOpenDetails(capability)}
                                    className="btn-ghost"
                                    title="Capability details"
                                    aria-label={`Details for ${capability.name}`}
                                    style={{
                                        width: '30px',
                                        minWidth: '30px',
                                        height: '28px',
                                        padding: '0',
                                        justifyContent: 'center',
                                        borderRadius: 'var(--radius-md)',
                                    }}
                                >
                                    <SlidersHorizontal size={13} />
                                </button>
                                <button
                                    onClick={() => handleOpenConfig(capability)}
                                    className="btn-secondary"
                                    title="Configure capability"
                                    aria-label={`Configure ${capability.name}`}
                                    style={{
                                        width: '30px',
                                        minWidth: '30px',
                                        height: '28px',
                                        padding: '0',
                                        justifyContent: 'center',
                                        borderRadius: 'var(--radius-md)',
                                    }}
                                >
                                    <Settings2 size={13} />
                                </button>
                            </div>

                            {hasIssues && (
                                <div style={{ background: 'rgba(239, 68, 68, 0.08)', padding: '7px 8px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(239, 68, 68, 0.18)', width: '100%' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f87171', fontSize: '10px', fontWeight: '700', marginBottom: '2px' }}>
                                        <AlertCircle size={11} /> Configuration issue
                                    </div>
                                    <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '10px', color: '#fca5a5' }}>
                                        {capability.missing_required.map(f => <li key={f}>Missing required field: <b>{f}</b></li>)}
                                        {capability.validation_errors.map((e, i) => <li key={i}>{e}</li>)}
                                        {retrievalIssues.map((e, i) => <li key={`retrieval-${i}`}>{e}</li>)}
                                    </ul>
                                </div>
                            )}
                        </div>
                        ) : (
                            <div key={capability.id} className="glass-card" style={{
                                padding: isMobile ? '10px' : '10px 12px',
                                display: 'flex',
                                flexDirection: isMobile ? 'column' : 'row',
                                alignItems: isMobile ? 'stretch' : 'center',
                                gap: isMobile ? '10px' : '12px',
                                borderRadius: 'var(--radius-md)',
                                border: hasIssues
                                    ? '1px solid rgba(239, 68, 68, 0.3)'
                                    : (!capability.enabled ? '1px solid rgba(148, 163, 184, 0.28)' : '1px solid var(--card-border)'),
                                background: !capability.enabled ? 'linear-gradient(180deg, rgba(148,163,184,0.06), rgba(148,163,184,0.02))' : undefined,
                                opacity: !capability.enabled ? 0.74 : 1,
                                filter: !capability.enabled ? 'grayscale(0.22)' : 'none',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
                                    <CapabilityIcon
                                        variant="display"
                                        capabilityId={capability.id}
                                        assets={capability.assets}
                                        size={24}
                                    />
                                    <div style={{ minWidth: 0, flex: 1 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                                            <h3 style={{ fontSize: '14px', fontWeight: '800', margin: 0, color: !capability.enabled ? '#9ca3af' : 'var(--text-main)' }}>{capability.name}</h3>
                                            {capability.enabled ? (
                                                <span className="badge badge-success" style={{ fontSize: '9px', padding: '2px 6px' }}>Active</span>
                                            ) : (
                                                <span className="badge badge-slate" style={{ fontSize: '9px', padding: '2px 6px' }}>Off</span>
                                            )}
                                        </div>
                                        <p style={{
                                            fontSize: '11px',
                                            color: '#94a3b8',
                                            lineHeight: '1.3',
                                            margin: '3px 0 4px',
                                            display: '-webkit-box',
                                            WebkitLineClamp: 1,
                                            WebkitBoxOrient: 'vertical',
                                            overflow: 'hidden'
                                        }}>
                                            {capability.description}
                                        </p>
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                            {capability.actions?.slice(0, 3).map(a => (
                                                <span key={a} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.05)', padding: '1px 6px', borderRadius: '100px', color: '#cbd5e1' }}>{a}</span>
                                            ))}
                                            {capability.actions?.length > 3 && <span style={{ fontSize: '9px', opacity: 0.6 }}>+{capability.actions.length - 3}</span>}
                                            {capability.retrieval_profile?.enabled && (
                                                <span
                                                    style={{
                                                        fontSize: '9px',
                                                        background: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(capability)?.operational_state || ''))
                                                            ? 'rgba(239,68,68,0.18)'
                                                            : (String(getRetrievalRuntime(capability)?.operational_state || '') === 'degraded'
                                                                ? 'rgba(245,158,11,0.16)'
                                                                : 'rgba(34,197,94,0.16)'),
                                                        color: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(capability)?.operational_state || ''))
                                                            ? '#fca5a5'
                                                            : (String(getRetrievalRuntime(capability)?.operational_state || '') === 'degraded' ? '#fcd34d' : '#86efac'),
                                                        padding: '1px 6px',
                                                        borderRadius: '100px',
                                                        border: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(capability)?.operational_state || ''))
                                                            ? '1px solid rgba(239,68,68,0.24)'
                                                            : (String(getRetrievalRuntime(capability)?.operational_state || '') === 'degraded'
                                                                ? '1px solid rgba(245,158,11,0.24)'
                                                                : '1px solid rgba(34,197,94,0.24)'),
                                                    }}
                                                >
                                                    {getRetrievalStateLabel(capability) || 'RAG ready'}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', minWidth: isMobile ? '100%' : '124px' }}>
                                    <button
                                        onClick={() => handleToggle(capability.id, capability.enabled)}
                                        style={{
                                            background: capability.enabled ? 'rgba(16,185,129,0.12)' : 'rgba(148,163,184,0.14)',
                                            border: capability.enabled ? '1px solid rgba(16,185,129,0.35)' : '1px solid rgba(148,163,184,0.28)',
                                            borderRadius: 'var(--radius-md)',
                                            cursor: 'pointer',
                                            transition: 'transform 0.2s',
                                            width: '36px',
                                            height: '28px',
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                        }}
                                        className="hover:scale-110"
                                        title={capability.enabled ? 'Disable capability' : 'Enable capability'}
                                    >
                                        {capability.enabled ? <ToggleRight size={24} color="var(--accent-color)" /> : <ToggleLeft size={24} color="#475569" />}
                                    </button>
                                    <button
                                        onClick={() => handleOpenDetails(capability)}
                                        className="btn-ghost"
                                        title="Capability details"
                                        aria-label={`Details for ${capability.name}`}
                                        style={{
                                            width: '30px',
                                            minWidth: '30px',
                                            height: '28px',
                                            padding: '0',
                                            justifyContent: 'center',
                                            borderRadius: 'var(--radius-md)',
                                        }}
                                    >
                                        <SlidersHorizontal size={13} />
                                    </button>
                                    <button
                                        onClick={() => handleOpenConfig(capability)}
                                        className="btn-secondary"
                                        title="Configure capability"
                                        aria-label={`Configure ${capability.name}`}
                                        style={{
                                            width: '30px',
                                            minWidth: '30px',
                                            height: '28px',
                                            padding: '0',
                                            justifyContent: 'center',
                                            borderRadius: 'var(--radius-md)',
                                        }}
                                    >
                                        <Settings2 size={13} />
                                    </button>
                                </div>
                            </div>
                        )
                            );
                        })()
                    )) : (
                        <div style={{ textAlign: 'center', marginTop: '60px', gridColumn: '1 / -1' }}>
                            <Puzzle size={64} style={{ marginBottom: '24px', opacity: 0.2, margin: '0 auto' }} />
                            <h4 style={{ fontSize: '20px', color: '#94a3b8' }}>No capabilities discovered</h4>
                        </div>
                    )}
                </div>
            </div>

            {/* Modal - Unified Standard */}
            {detailCapability && (
                <div className="modal-overlay" onClick={() => setDetailCapability(null)}>
                    <div className="modal-content glass" onClick={e => e.stopPropagation()} style={modalShellStyle}>
                        <div style={{ padding: isMobile ? '10px 10px' : '12px 14px', borderBottom: '1px solid var(--card-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <CapabilityIcon
                                    variant="display"
                                    capabilityId={detailCapability.id}
                                    assets={detailCapability.assets}
                                    size={isMobile ? 24 : 28}
                                />
                                <div>
                                    <h3 style={{ fontSize: isMobile ? '14px' : '16px', fontWeight: '800', color: 'var(--text-main)', margin: 0 }}>{detailCapability.name}</h3>
                                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '2px 0 0' }}>{detailCapability.id}</p>
                                </div>
                            </div>
                            <button onClick={() => setDetailCapability(null)} className="btn-ghost" style={{ padding: '6px' }}>
                                <X size={19} />
                            </button>
                        </div>

                        <div className="custom-scrollbar" style={{ flex: 1, minHeight: 0, padding: isMobile ? '10px 10px 12px' : '14px 16px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: isMobile ? '10px' : '12px' }}>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                {detailCapability.enabled ? (
                                    <span className="badge badge-success">Active</span>
                                ) : (
                                    <span className="badge badge-slate">Disabled</span>
                                )}
                                {detailCapability.retrieval_profile?.enabled && (
                                    <span
                                        className="badge"
                                        style={{
                                            background: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(detailCapability)?.operational_state || ''))
                                                ? 'rgba(239,68,68,0.15)'
                                                : (String(getRetrievalRuntime(detailCapability)?.operational_state || '') === 'degraded'
                                                    ? 'rgba(245,158,11,0.15)'
                                                    : 'rgba(34,197,94,0.14)'),
                                            color: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(detailCapability)?.operational_state || ''))
                                                ? '#f87171'
                                                : (String(getRetrievalRuntime(detailCapability)?.operational_state || '') === 'degraded' ? '#fcd34d' : '#86efac'),
                                            border: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(detailCapability)?.operational_state || ''))
                                                ? '1px solid rgba(239,68,68,0.25)'
                                                : (String(getRetrievalRuntime(detailCapability)?.operational_state || '') === 'degraded'
                                                    ? '1px solid rgba(245,158,11,0.25)'
                                                    : '1px solid rgba(34,197,94,0.25)'),
                                        }}
                                    >
                                        {getRetrievalStateLabel(detailCapability)?.replace('RAG', 'Retrieval') || 'Retrieval ready'}
                                    </span>
                                )}
                                {detailCapability.validation_errors?.length > 0 || detailCapability.missing_required?.length > 0 || getRetrievalSetupIssues(detailCapability).length > 0 ? (
                                    <span className="badge" style={{ background: 'rgba(239,68,68,0.15)', color: '#f87171', border: '1px solid rgba(239,68,68,0.25)' }}>Validation issue</span>
                                ) : (
                                    <span className="badge" style={{ background: 'rgba(34,197,94,0.14)', color: '#86efac', border: '1px solid rgba(34,197,94,0.25)' }}>Validated</span>
                                )}
                                <span className="badge badge-slate">{(detailCapability.actions || []).length} actions</span>
                            </div>

                            <div style={{ border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                                <div style={{ fontSize: '11px', fontWeight: '900', letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Description</div>
                                <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-main)', lineHeight: '1.5' }}>{detailCapability.description || 'No description provided.'}</p>
                            </div>

                            <div style={{ border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                                <div style={{ fontSize: '11px', fontWeight: '900', letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>Actions</div>
                                {(detailCapability.actions || []).length > 0 ? (
                                    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, minmax(0, 1fr))', gap: '6px' }}>
                                        {(detailCapability.actions || []).map((action) => (
                                            <div key={action} style={{ fontSize: '12px', color: '#cbd5e1', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)', padding: '6px 8px', fontFamily: 'monospace' }}>
                                                {action}
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>No actions mapped.</p>
                                )}
                            </div>

                            {detailCapability.retrieval_profile?.enabled && (
                                <div style={{ border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                                    <div style={{ fontSize: '11px', fontWeight: '900', letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>Retrieval Runtime</div>
                                    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                                        <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                            <strong style={{ color: '#e2e8f0' }}>Operational State:</strong>{' '}
                                            {String(getRetrievalRuntime(detailCapability)?.operational_state || 'n/a')}
                                        </div>
                                        <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                            <strong style={{ color: '#e2e8f0' }}>Setup Ready:</strong>{' '}
                                            {getRetrievalRuntime(detailCapability)?.setup_ready === false ? 'No' : 'Yes'}
                                        </div>
                                        <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                            <strong style={{ color: '#e2e8f0' }}>Trust Tier:</strong>{' '}
                                            {detailCapability.retrieval_profile?.quality?.trust_tier || 'n/a'}
                                        </div>
                                        <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                            <strong style={{ color: '#e2e8f0' }}>Domains:</strong>{' '}
                                            {(detailCapability.retrieval_profile?.domains || []).join(', ') || 'n/a'}
                                        </div>
                                        <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                            <strong style={{ color: '#e2e8f0' }}>Roles:</strong>{' '}
                                            {(detailCapability.retrieval_profile?.roles || []).join(', ') || 'n/a'}
                                        </div>
                                    </div>
                                    {(getRetrievalRuntime(detailCapability)?.missing_required_fields || []).length > 0 && (
                                        <div style={{ marginTop: '10px', background: 'rgba(239, 68, 68, 0.08)', padding: '8px 10px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(239, 68, 68, 0.18)' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f87171', fontSize: '11px', fontWeight: '700', marginBottom: '4px' }}>
                                                <AlertCircle size={12} /> Missing retrieval fields
                                            </div>
                                            <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '11px', color: '#fca5a5' }}>
                                                {(getRetrievalRuntime(detailCapability)?.missing_required_fields || []).map((f) => (
                                                    <li key={f}><b>{f}</b></li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}
                                </div>
                            )}

                            {detailCapability.id === 'research_retrieve' && (
                                <div style={{ border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                                    <div style={{ fontSize: '11px', fontWeight: '900', letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>Retrieval Control Plane</div>
                                    {retrievalControlPlaneLoading ? (
                                        <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>Loading control plane...</p>
                                    ) : retrievalControlPlane ? (
                                        <>
                                            <div style={{ marginBottom: '10px' }}>
                                                <div style={{ fontSize: '11px', fontWeight: '700', color: 'var(--text-main)', marginBottom: '6px' }}>Provider Overrides</div>
                                                {retrievalOffersLoading ? (
                                                    <p style={{ margin: 0, fontSize: '11px', color: 'var(--text-muted)' }}>Loading providers...</p>
                                                ) : retrievalOffers.length > 0 ? (
                                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                                        {retrievalOffers.map((offer) => {
                                                            const providerId = String(offer?.capability_id || '').trim();
                                                            if (!providerId) return null;
                                                            const disabled = isProviderDisabled(providerId);
                                                            const row = getProviderOverride(providerId);
                                                            const degraded = !!row.degraded;
                                                            const forceFallback = !!row.force_fallback;
                                                            const quotaExceeded = !!row.quota_exceeded;
                                                            const errorPrevious = !!row.error_previous;
                                                            return (
                                                                <div
                                                                    key={providerId}
                                                                    style={{
                                                                        display: 'flex',
                                                                        alignItems: 'center',
                                                                        gap: '6px',
                                                                        padding: '5px 6px',
                                                                        borderRadius: 'var(--radius-md)',
                                                                        border: '1px solid var(--card-border)',
                                                                        background: 'rgba(255,255,255,0.03)',
                                                                    }}
                                                                >
                                                                    <span style={{ fontSize: '10px', color: '#cbd5e1', minWidth: '110px' }}>{providerId}</span>
                                                                    <button
                                                                        className="btn-ghost"
                                                                        disabled={retrievalControlPlaneSaving}
                                                                        onClick={() => toggleProviderFlag(providerId, 'disabled')}
                                                                        style={{
                                                                            fontSize: '9px',
                                                                            padding: '3px 6px',
                                                                            borderRadius: '999px',
                                                                            border: disabled ? '1px solid rgba(239,68,68,0.35)' : '1px solid rgba(34,197,94,0.35)',
                                                                            color: disabled ? '#fca5a5' : '#86efac',
                                                                            background: disabled ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)',
                                                                        }}
                                                                        title="Toggle disabled"
                                                                    >
                                                                        disabled:{disabled ? 'on' : 'off'}
                                                                    </button>
                                                                    <button
                                                                        className="btn-ghost"
                                                                        disabled={retrievalControlPlaneSaving}
                                                                        onClick={() => toggleProviderFlag(providerId, 'degraded')}
                                                                        style={{
                                                                            fontSize: '9px',
                                                                            padding: '3px 6px',
                                                                            borderRadius: '999px',
                                                                            border: degraded ? '1px solid rgba(245,158,11,0.35)' : '1px solid rgba(148,163,184,0.35)',
                                                                            color: degraded ? '#fcd34d' : '#cbd5e1',
                                                                            background: degraded ? 'rgba(245,158,11,0.12)' : 'rgba(148,163,184,0.10)',
                                                                        }}
                                                                        title="Toggle degraded"
                                                                    >
                                                                        degraded:{degraded ? 'on' : 'off'}
                                                                    </button>
                                                                    <button
                                                                        className="btn-ghost"
                                                                        disabled={retrievalControlPlaneSaving}
                                                                        onClick={() => toggleProviderFlag(providerId, 'force_fallback')}
                                                                        style={{
                                                                            fontSize: '9px',
                                                                            padding: '3px 6px',
                                                                            borderRadius: '999px',
                                                                            border: forceFallback ? '1px solid rgba(168,85,247,0.35)' : '1px solid rgba(148,163,184,0.35)',
                                                                            color: forceFallback ? '#d8b4fe' : '#cbd5e1',
                                                                            background: forceFallback ? 'rgba(168,85,247,0.12)' : 'rgba(148,163,184,0.10)',
                                                                        }}
                                                                        title="Toggle force fallback"
                                                                    >
                                                                        force_fallback:{forceFallback ? 'on' : 'off'}
                                                                    </button>
                                                                    <button
                                                                        className="btn-ghost"
                                                                        disabled={retrievalControlPlaneSaving}
                                                                        onClick={() => toggleProviderFlag(providerId, 'quota_exceeded')}
                                                                        style={{
                                                                            fontSize: '9px',
                                                                            padding: '3px 6px',
                                                                            borderRadius: '999px',
                                                                            border: quotaExceeded ? '1px solid rgba(239,68,68,0.35)' : '1px solid rgba(148,163,184,0.35)',
                                                                            color: quotaExceeded ? '#fca5a5' : '#cbd5e1',
                                                                            background: quotaExceeded ? 'rgba(239,68,68,0.12)' : 'rgba(148,163,184,0.10)',
                                                                        }}
                                                                        title="Toggle quota exceeded"
                                                                    >
                                                                        quota_exceeded:{quotaExceeded ? 'on' : 'off'}
                                                                    </button>
                                                                    <button
                                                                        className="btn-ghost"
                                                                        disabled={retrievalControlPlaneSaving}
                                                                        onClick={() => toggleProviderFlag(providerId, 'error_previous')}
                                                                        style={{
                                                                            fontSize: '9px',
                                                                            padding: '3px 6px',
                                                                            borderRadius: '999px',
                                                                            border: errorPrevious ? '1px solid rgba(239,68,68,0.35)' : '1px solid rgba(148,163,184,0.35)',
                                                                            color: errorPrevious ? '#fca5a5' : '#cbd5e1',
                                                                            background: errorPrevious ? 'rgba(239,68,68,0.12)' : 'rgba(148,163,184,0.10)',
                                                                        }}
                                                                        title="Toggle previous error"
                                                                    >
                                                                        error_previous:{errorPrevious ? 'on' : 'off'}
                                                                    </button>
                                                                </div>
                                                            );
                                                        })}
                                                    </div>
                                                ) : (
                                                    <p style={{ margin: 0, fontSize: '11px', color: 'var(--text-muted)' }}>No retrieval providers indexed.</p>
                                                )}
                                            </div>
                                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, minmax(0, 1fr))', gap: '8px', marginBottom: '8px' }}>
                                                <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                                    <strong style={{ color: '#e2e8f0' }}>Overrides:</strong>{' '}
                                                    {Object.keys(retrievalControlPlane.overrides || {}).length}
                                                </div>
                                                <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                                    <strong style={{ color: '#e2e8f0' }}>Scorecards:</strong>{' '}
                                                    {Object.keys(retrievalControlPlane.scorecard || {}).length}
                                                </div>
                                            </div>
                                            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: '11px', color: '#cbd5e1', lineHeight: '1.4' }}>
                                                {JSON.stringify(retrievalControlPlane, null, 2)}
                                            </pre>
                                        </>
                                    ) : (
                                        <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>Control plane data unavailable.</p>
                                    )}
                                </div>
                            )}

                            <div style={{ border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)', padding: '12px' }}>
                                <div style={{ fontSize: '11px', fontWeight: '900', letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>Config Snapshot</div>
                                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: '11px', color: '#cbd5e1', lineHeight: '1.4' }}>
                                    {JSON.stringify(detailCapability.config || {}, null, 2)}
                                </pre>
                            </div>

                            {(detailCapability.validation_errors?.length > 0 || detailCapability.missing_required?.length > 0 || getRetrievalSetupIssues(detailCapability).length > 0) && (
                                <div style={{ background: 'rgba(239, 68, 68, 0.08)', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(239, 68, 68, 0.18)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f87171', fontSize: '11px', fontWeight: '700', marginBottom: '4px' }}>
                                        <AlertCircle size={12} /> Validation details
                                    </div>
                                    <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '11px', color: '#fca5a5' }}>
                                        {(detailCapability.missing_required || []).map(f => <li key={f}>Missing required field: <b>{f}</b></li>)}
                                        {(detailCapability.validation_errors || []).map((e, i) => <li key={i}>{e}</li>)}
                                        {getRetrievalSetupIssues(detailCapability).map((e, i) => <li key={`retrieval-detail-${i}`}>{e}</li>)}
                                    </ul>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Modal - Unified Standard */}
            {configuringCapability && (
                <div className="modal-overlay" onClick={() => setConfiguringCapability(null)}>
                    <div className="modal-content glass" onClick={e => e.stopPropagation()} style={configModalShellStyle}>
                        <div style={{ padding: isMobile ? '12px 12px' : '14px 16px', borderBottom: '1px solid var(--card-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <CapabilityIcon
                                    variant="display"
                                    capabilityId={configuringCapability.id}
                                    assets={configuringCapability.assets}
                                    size={isMobile ? 24 : 28}
                                />
                                <div>
                                    <h3 style={{ fontSize: isMobile ? '14px' : '15px', fontWeight: '800', color: 'var(--text-main)' }}>{configuringCapability.name}</h3>
                                    <p style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Configuration</p>
                                </div>
                            </div>
                            <button onClick={() => setConfiguringCapability(null)} className="btn-ghost" style={{ padding: '6px' }}>
                                <X size={20} />
                            </button>
                        </div>

                        <div className="custom-scrollbar" style={{ flex: 1, minHeight: 0, padding: isMobile ? '8px' : '8px 10px', overflowY: 'auto' }}>
                            {renderConfigForm()}
                        </div>

                        <div style={{ padding: isMobile ? '8px 10px' : '8px 12px', borderTop: '1px solid var(--card-border)', background: 'rgba(0,0,0,0.04)', display: 'flex', justifyContent: 'flex-end', gap: '7px', borderBottomLeftRadius: isMobile ? '10px' : '12px', borderBottomRightRadius: isMobile ? '10px' : '12px' }}>
                            <button onClick={() => setConfiguringCapability(null)} className="btn-ghost" style={{ padding: isMobile ? '7px 10px' : '8px 12px' }}>Cancel</button>
                            <button
                                onClick={handleSaveConfig}
                                className="btn-primary"
                                disabled={isSaving}
                                style={{ padding: isMobile ? '7px 10px' : '8px 12px', borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}
                            >
                                {isSaving ? <RefreshCw size={18} className="animate-spin" /> : <Save size={18} />}
                                <span>Save Changes</span>
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Capabilities;
