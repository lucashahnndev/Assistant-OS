import ReactMarkdown from 'react-markdown';
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
    SlidersHorizontal,
    FileText,
    Zap,
    Loader2
} from 'lucide-react';

import PageHeader from '../components/PageHeader';
import CapabilityIcon from '../components/CapabilityIcon';
import ErrorBoundary from '../components/ErrorBoundary';
import { createSecret, listSecretRefs } from '../utils/secretsApi';

const CAPABILITIES_VIEW_MODE_KEY = 'capabilities.hub.view_mode';

const getDomainColor = (capId) => {
    const id = String(capId || '').toLowerCase();
    
    if (id.includes('search') || id.includes('crawl')) return '#3b82f6'; // Blue
    if (id.includes('memory') || id.includes('brain')) return '#a855f7'; // Purple
    if (id.includes('calendar') || id.includes('mail')) return '#f97316'; // Orange
    if (id.includes('weather') || id.includes('cloud') || id.includes('maps')) return '#0ea5e9'; // Cyan
    if (id.includes('code') || id.includes('script') || id.includes('terminal') || id.includes('github') || id.includes('git')) return '#22c55e'; // Green
    if (id.includes('browser') || id.includes('web') || id.includes('control')) return '#ec4899'; // Pink
    if (id.includes('audio') || id.includes('music') || id.includes('deezer') || id.includes('youtube')) return '#f43f5e'; // Rose
    if (id.includes('data') || id.includes('chart') || id.includes('analysis')) return '#eab308'; // Yellow
    if (id.includes('system') || id.includes('core')) return '#64748b'; // Slate

    return 'var(--hub-card-border)';
};

const Capabilities = () => {
    const [capabilities, setCapabilities] = useState([]);
    const [loading, setLoading] = useState(true);
    const [activeModalCapability, setActiveModalCapability] = useState(null);
    const [activeModalTab, setActiveModalTab] = useState('details'); // 'details' or 'config'
    const [configValues, setConfigValues] = useState({});
    const [envKeys, setEnvKeys] = useState([]);
    const [secretEditor, setSecretEditor] = useState({ target: '', key: '', value: '' });
    const [isSaving, setIsSaving] = useState(false);
    const [retrievalControlPlane, setRetrievalControlPlane] = useState(null);
    const [retrievalControlPlaneLoading, setRetrievalControlPlaneLoading] = useState(false);
    const [retrievalOffers, setRetrievalOffers] = useState([]);
    const [retrievalOffersLoading, setRetrievalOffersLoading] = useState(false);
    
    // Artifact Viewer State
    const [isArtifactModalOpen, setIsArtifactModalOpen] = useState(false);
    const [activeArtifact, setActiveArtifact] = useState(null);
    const [artifactContent, setArtifactContent] = useState('');
    const [artifactLoading, setArtifactLoading] = useState(false);
    const [artifactError, setArtifactError] = useState(false);
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
        const auth = activeModalCapability?.auth;
        const fields = Array.isArray(auth?.fields) ? auth.fields : [];
        const map = {};
        for (const field of fields) {
            if (!field || typeof field !== 'object') continue;
            const path = String(field.config_path || '').trim();
            if (!path) continue;
            map[path] = field;
        }
        return map;
    }, [activeModalCapability]);
    const authSourceConfigPath = useMemo(() => {
        const auth = activeModalCapability?.auth;
        return typeof auth?.source_config_path === 'string' ? auth.source_config_path : '';
    }, [activeModalCapability]);
    const authSources = useMemo(() => {
        const auth = activeModalCapability?.auth;
        return Array.isArray(auth?.sources) ? auth.sources : [];
    }, [activeModalCapability]);
    const selectedAuthSource = useMemo(() => {
        if (!authSourceConfigPath) return '';
        const current = getConfigValue(authSourceConfigPath, configValues);
        return String(current || activeModalCapability?.auth?.default_source || '').trim();
    }, [authSourceConfigPath, configValues, activeModalCapability, getConfigValue]);

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

    const fetchArtifact = async (capabilityId, filename) => {
        setActiveArtifact(filename);
        setIsArtifactModalOpen(true);
        setArtifactLoading(true);
        setArtifactContent('');
        setArtifactError(false);
        try {
            const token = localStorage.getItem('token');
            const res = await fetch(`/api/capabilities/${capabilityId}/artifacts/${filename}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            const text = await res.text();
            setArtifactContent(text);
        } catch (err) {
            setArtifactError(true);
            setArtifactContent('');
        } finally {
            setArtifactLoading(false);
        }
    };

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

    const handleOpenModal = (capability, initialTab = 'details') => {
        setActiveModalCapability(capability);
        setActiveModalTab(initialTab);
        setActiveArtifact(null);
        setArtifactContent('');

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
        if (!activeModalCapability) return;
        setIsSaving(true);
        try {
            await api.patch(`/capabilities/${activeModalCapability.id}/config`, { config: configValues });
            notify.success('Configuration saved successfully');
            setActiveModalCapability(null);
            fetchCapabilities();
        } catch (err) {
            notify.error("Failed to save: " + err.message);
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
        const auth = activeModalCapability?.auth;
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
                <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginBottom: '10px', lineHeight: '1.35' }}>
                    This capability supports multiple authentication sources. Choose the source of truth explicitly.
                </p>
                <select
                    className="glass-input"
                    style={{ height: '34px', minHeight: '34px', padding: '6px 8px', borderRadius: '6px', fontSize: '12px', width: '100%', marginBottom: '10px' }}
                    value={selectedAuthSource || activeModalCapability?.auth?.default_source || ''}
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
                                    <span style={{ fontSize: '9px', color: active ? 'var(--accent-color)' : 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                                        {String(source.type || '').replace('_', ' ')}
                                    </span>
                                </div>
                                {source.description && (
                                    <p style={{ fontSize: '10px', color: 'var(--text-secondary)', margin: 0, lineHeight: '1.35' }}>
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
                        fontWeight: '600',
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
                            color: 'var(--text-secondary)',
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
                            onClick={() => creating ? setSecretEditor({ target: '', key: '', value: '' }) : openSecretEditor(fullPath, activeModalCapability?.id)}
                            className="btn-ghost"
                            style={{ fontSize: '10px', padding: '3px 8px', color: 'var(--accent-color)' }}
                        >
                            {creating ? 'Cancel' : '+ Create New Key'}
                        </button>
                    </div>

                    {((authField?.description || schema.description) || (activeModalCapability?.auth?.mode === 'hybrid' && selectedAuthSource === 'linked_account')) && (
                        <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginBottom: '6px', lineHeight: '1.3' }}>
                            {authField?.description || schema.description || ''}
                            {activeModalCapability?.auth?.mode === 'hybrid' && selectedAuthSource === 'linked_account'
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
                    <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginBottom: '5px', lineHeight: '1.3' }}>
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
        const schema = activeModalCapability?.config_schema;
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

    const renderStructuredParameters = (parameters) => {
        const properties = parameters?.properties || {};
        const required = parameters?.required || [];
        if (Object.keys(properties).length === 0) {
            return <p style={{ margin: 0, fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic' }}>No parameters required.</p>;
        }
        return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '6px' }}>
                {Object.entries(properties).map(([name, schema]) => {
                    const isRequired = required.includes(name);
                    return (
                        <div key={name} style={{ display: 'flex', flexDirection: 'column', padding: '10px', background: 'rgba(255,255,255,0.02)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.04)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                                <span style={{ fontFamily: 'monospace', fontSize: '12px', color: 'var(--card-accent)', fontWeight: '600' }}>
                                    {name} {isRequired && <span style={{ color: '#ef4444' }}>*</span>}
                                </span>
                                <span style={{ fontSize: '10px', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: '4px' }}>
                                    {schema.type || 'any'}
                                </span>
                            </div>
                            {schema.description && (
                                <span style={{ fontSize: '11px', color: '#cbd5e1', lineHeight: '1.4' }}>{schema.description}</span>
                            )}
                            {schema.default !== undefined && (
                                <span style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                    Default: <code style={{ background: 'rgba(0,0,0,0.2)', padding: '2px 4px', borderRadius: '3px' }}>{String(schema.default)}</code>
                                </span>
                            )}
                        </div>
                    );
                })}
            </div>
        );
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
        borderRadius: '6px',
        margin: '6px auto',
        border: '1px solid rgba(148,163,184,0.24)',
        boxShadow: '0 12px 42px rgba(2,6,23,0.18)',
    };
    const configModalShellStyle = {
        width: isMobile ? 'calc(100% - 14px)' : 'min(92%, 560px)',
        maxHeight: 'calc(100% - 12px)',
        display: 'flex',
        flexDirection: 'column',
        borderRadius: '6px',
        margin: '6px auto',
        border: '1px solid rgba(148,163,184,0.24)',
        boxShadow: '0 12px 42px rgba(2,6,23,0.18)',
    };
    // Using global modal-overlay

    return (
        <div className="animate-fade-in" style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative', background: 'transparent' }}>

            <div style={{ position: 'relative', zIndex: 10, display: 'flex', flexDirection: 'column', height: '100%', width: '100%' }}>
                <PageHeader
                    title="Capabilities Hub"
                    subtitle="Operational modules available to the Atlas runtime."
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

            <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '0 var(--space-2)' : '0 16px' }}>
                <div style={{
                    display: viewMode === 'grid' ? 'grid' : 'flex',
                    flexDirection: viewMode === 'list' ? 'column' : undefined,
                    gridTemplateColumns: viewMode === 'grid' ? (isMobile ? 'repeat(2, minmax(0, 1fr))' : (isTablet ? 'repeat(3, minmax(0, 1fr))' : 'repeat(auto-fill, minmax(280px, 1fr))')) : undefined,
                    gap: viewMode === 'grid' ? (isMobile ? '12px' : '16px') : '12px',
                    paddingBottom: '100px',
                    padding: isMobile ? '8px 0' : '16px 0',
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
                            <div key={capability.id} className="module-card" style={{
                            padding: '12px 16px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '12px',
                            background: 'var(--card-bg)',
                            borderRadius: 'var(--radius-md)',
                            border: '1px solid var(--card-border)',
                            '--card-accent': capability.enabled ? getDomainColor(capability.id) : undefined,
                            transition: 'border-color 0.2s, background 0.2s',
                            cursor: 'pointer'
                        }}
                        onClick={() => handleOpenModal(capability, 'details')}
                        onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.1)'; e.currentTarget.style.background = 'rgba(255, 255, 255, 0.02)'; }}
                        onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--card-border)'; e.currentTarget.style.background = 'var(--card-bg)'; }}
                        >
                            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0, flex: 1 }}>
                                    <div style={{ color: capability.enabled ? 'var(--card-accent)' : 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                        <CapabilityIcon variant="inline" size={28} capabilityId={capability.id} assets={capability.assets} />
                                    </div>
                                    <div style={{ minWidth: 0 }}>
                                        <h3 style={{ fontSize: '14px', fontWeight: '800', color: capability.enabled ? 'var(--text-main)' : 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{capability.name}</h3>
                                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>{capability.id}</div>
                                    </div>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    {hasIssues && <AlertCircle size={14} color="#eab308" />}
                                    <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: capability.enabled ? 'var(--success)' : 'var(--text-muted)', opacity: capability.enabled ? 1 : 0.3 }} />
                                </div>
                            </div>

                            <p className="hub-description" style={{ minHeight: '30px' }}>
                                {capability.description}
                            </p>

                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                {capability.retrieval_profile?.enabled && (
                                    <span
                                        style={{
                                            fontSize: '10px',
                                            color: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(capability)?.operational_state || ''))
                                                ? '#fca5a5'
                                                : (String(getRetrievalRuntime(capability)?.operational_state || '') === 'degraded' ? '#fcd34d' : 'var(--text-secondary)'),
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
                                        background: capability.enabled ? 'rgba(16,185,129,0.12)' : 'var(--hub-control-bg)',
                                        border: capability.enabled ? '1px solid rgba(16,185,129,0.35)' : '1px solid var(--hub-control-border)',
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
                                    {capability.enabled ? <ToggleRight size={24} color="var(--accent-color)" /> : <ToggleLeft size={24} color="var(--text-muted)" />}
                                </button>
                                    <button
                                        onClick={() => handleOpenModal(capability, 'details')}
                                        className="btn-ghost"
                                        title="Manage capability"
                                        aria-label={`Manage ${capability.name}`}
                                        style={{ width: '32px', minWidth: '32px', height: '28px', borderRadius: 'var(--radius-md)' }}
                                    >
                                        <Settings2 size={14} />
                                    </button>
                            </div>


                        </div>
                        ) : (
                            <div key={capability.id} className="module-card" style={{
                                padding: '12px 16px',
                                display: 'flex',
                                flexDirection: isMobile ? 'column' : 'row',
                                alignItems: isMobile ? 'stretch' : 'center',
                                gap: '16px',
                                background: 'var(--card-bg)',
                                borderRadius: 'var(--radius-md)',
                                border: '1px solid var(--card-border)',
                                '--card-accent': capability.enabled ? getDomainColor(capability.id) : undefined,
                                transition: 'border-color 0.2s, background 0.2s',
                                cursor: 'pointer'
                            }}
                            onClick={() => handleOpenModal(capability, 'details')}
                            onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.1)'; e.currentTarget.style.background = 'rgba(255, 255, 255, 0.02)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--card-border)'; e.currentTarget.style.background = 'var(--card-bg)'; }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0, flex: 1 }}>
                                    <div style={{ color: capability.enabled ? 'var(--card-accent)' : 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                        <CapabilityIcon variant="inline" size={28} capabilityId={capability.id} assets={capability.assets} />
                                    </div>
                                    <div style={{ minWidth: 0, flex: 1 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                            <h3 style={{ fontSize: '14px', fontWeight: '800', color: capability.enabled ? 'var(--text-main)' : 'var(--text-muted)' }}>{capability.name}</h3>
                                            {hasIssues && <AlertCircle size={14} color="#eab308" />}
                                            <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: capability.enabled ? 'var(--success)' : 'var(--text-muted)', opacity: capability.enabled ? 1 : 0.3, marginLeft: 'auto' }} />
                                        </div>
                                        <p className="hub-description" style={{ fontSize: '11px', margin: '3px 0 4px', WebkitLineClamp: 1 }}>
                                            {capability.description}
                                        </p>
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                            {capability.retrieval_profile?.enabled && (
                                                <span
                                                    style={{
                                                        fontSize: '10px',
                                                        color: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(capability)?.operational_state || ''))
                                                            ? '#fca5a5'
                                                            : (String(getRetrievalRuntime(capability)?.operational_state || '') === 'degraded' ? '#fcd34d' : 'var(--text-secondary)'),
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
                                            background: capability.enabled ? 'rgba(16,185,129,0.12)' : 'var(--hub-control-bg)',
                                            border: capability.enabled ? '1px solid rgba(16,185,129,0.35)' : '1px solid var(--hub-control-border)',
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
                                        {capability.enabled ? <ToggleRight size={24} color="var(--accent-color)" /> : <ToggleLeft size={24} color="var(--text-muted)" />}
                                    </button>
                                        <button
                                            onClick={() => handleOpenModal(capability, 'details')}
                                            className="btn-ghost"
                                            title="Manage capability"
                                            aria-label={`Manage ${capability.name}`}
                                            style={{ width: '32px', minWidth: '32px', height: '28px', borderRadius: 'var(--radius-md)' }}
                                        >
                                            <Settings2 size={14} />
                                        </button>
                                </div>
                            </div>
                        )
                            );
                        })()
                    )) : (
                        <div style={{ textAlign: 'center', marginTop: '60px', gridColumn: '1 / -1' }}>
                            <Puzzle size={64} style={{ marginBottom: '24px', opacity: 0.2, margin: '0 auto' }} />
                            <h4 style={{ fontSize: '20px', color: 'var(--text-secondary)' }}>No capabilities discovered</h4>
                        </div>
                    )}
                </div>
            </div>

            
            {/* Modal - Unified Tabbed Standard */}
            {activeModalCapability && (
                <div className="modal-overlay" onClick={() => setActiveModalCapability(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{...modalShellStyle, background: 'var(--card-bg)', '--card-accent': getDomainColor(activeModalCapability.id)}}>
                        {/* Modal Header */}
                        <div style={{ padding: isMobile ? '16px' : '20px', borderBottom: '1px solid var(--card-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'color-mix(in srgb, var(--card-accent) 2%, var(--card-bg))' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                                <div style={{ 
                                    width: '40px', height: '40px', borderRadius: '10px', 
                                    background: activeModalCapability.enabled ? 'color-mix(in srgb, var(--card-accent) 15%, transparent)' : 'rgba(255,255,255,0.02)',
                                    color: activeModalCapability.enabled ? 'var(--card-accent)' : 'var(--text-muted)',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    border: `1px solid color-mix(in srgb, var(--card-accent) 30%, transparent)`
                                }}>
                                    <CapabilityIcon variant="inline" capabilityId={activeModalCapability.id} assets={activeModalCapability.assets} />
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                                    <h3 style={{ fontSize: '18px', fontWeight: '800', color: 'var(--text-main)', margin: 0, letterSpacing: '-0.02em', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        {activeModalCapability.name}
                                        {activeModalCapability.enabled ? (
                                            <span style={{ fontSize: '9px', padding: '2px 6px', borderRadius: '4px', background: 'rgba(34, 197, 94, 0.1)', color: '#4ade80', border: '1px solid rgba(34,197,94,0.2)' }}>ACTIVE</span>
                                        ) : (
                                            <span style={{ fontSize: '9px', padding: '2px 6px', borderRadius: '4px', background: 'rgba(148, 163, 184, 0.1)', color: '#94a3b8', border: '1px solid rgba(148,163,184,0.2)' }}>OFF</span>
                                        )}
                                    </h3>
                                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: 0, fontFamily: 'monospace' }}>{activeModalCapability.id}</p>
                                </div>
                            </div>
                            <button onClick={() => setActiveModalCapability(null)} className="btn-ghost" style={{ padding: '6px' }}>
                                <X size={19} />
                            </button>
                        </div>
                        
                        {/* Modal Tabs - Flat Underline Segments */}
                        <div style={{ display: 'flex', gap: '24px', borderBottom: '1px solid var(--card-border)', padding: '0 20px', background: 'rgba(0,0,0,0.1)' }}>
                            <button
                                onClick={() => setActiveModalTab('details')}
                                style={{
                                    padding: '12px 4px',
                                    background: 'transparent',
                                    border: 'none',
                                    borderBottom: activeModalTab === 'details' ? '2px solid var(--card-accent)' : '2px solid transparent',
                                    color: activeModalTab === 'details' ? 'var(--text-main)' : 'var(--text-muted)',
                                    fontWeight: activeModalTab === 'details' ? '800' : '600',
                                    cursor: 'pointer',
                                    fontSize: '11px',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.05em',
                                    transition: 'color 0.2s',
                                    outline: 'none'
                                }}
                            >
                                Details
                            </button>
                            <button
                                onClick={() => setActiveModalTab('config')}
                                style={{
                                    padding: '12px 4px',
                                    background: 'transparent',
                                    border: 'none',
                                    borderBottom: activeModalTab === 'config' ? '2px solid var(--card-accent)' : '2px solid transparent',
                                    color: activeModalTab === 'config' ? 'var(--text-main)' : 'var(--text-muted)',
                                    fontWeight: activeModalTab === 'config' ? '800' : '600',
                                    cursor: 'pointer',
                                    fontSize: '11px',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.05em',
                                    transition: 'color 0.2s',
                                    outline: 'none'
                                }}
                            >
                                Configuration
                            </button>
                            <button
                                onClick={() => setActiveModalTab('agent')}
                                style={{
                                    padding: '12px 4px',
                                    background: 'transparent',
                                    border: 'none',
                                    borderBottom: activeModalTab === 'agent' ? '2px solid var(--card-accent)' : '2px solid transparent',
                                    color: activeModalTab === 'agent' ? 'var(--text-main)' : 'var(--text-muted)',
                                    fontWeight: activeModalTab === 'agent' ? '800' : '600',
                                    cursor: 'pointer',
                                    fontSize: '11px',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.05em',
                                    transition: 'color 0.2s',
                                    outline: 'none'
                                }}
                            >
                                Agent Context
                            </button>
                            <button
                                onClick={() => setActiveModalTab('security')}
                                style={{
                                    padding: '12px 4px',
                                    background: 'transparent',
                                    border: 'none',
                                    borderBottom: activeModalTab === 'security' ? '2px solid var(--card-accent)' : '2px solid transparent',
                                    color: activeModalTab === 'security' ? 'var(--text-main)' : 'var(--text-muted)',
                                    fontWeight: activeModalTab === 'security' ? '800' : '600',
                                    cursor: 'pointer',
                                    fontSize: '11px',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.05em',
                                    transition: 'color 0.2s',
                                    outline: 'none'
                                }}
                            >
                                Security & ACLs
                            </button>
                        </div>

                        {/* Modal Body */}
                        <div className="custom-scrollbar" style={{ flex: 1, minHeight: 0, padding: isMobile ? '16px' : '24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: isMobile ? '16px' : '20px' }}>
                            {activeModalTab === 'details' && (
                                <>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                        {activeModalCapability.enabled ? (
                                            <span className="badge badge-success">Active</span>
                                        ) : (
                                            <span className="badge badge-slate">Disabled</span>
                                        )}
                                        {activeModalCapability.retrieval_profile?.enabled && (
                                            <span
                                                className="badge"
                                                style={{
                                                    background: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(activeModalCapability)?.operational_state || ''))
                                                        ? 'rgba(239,68,68,0.15)'
                                                        : (String(getRetrievalRuntime(activeModalCapability)?.operational_state || '') === 'degraded'
                                                            ? 'rgba(245,158,11,0.15)'
                                                            : 'rgba(34,197,94,0.14)'),
                                                    color: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(activeModalCapability)?.operational_state || ''))
                                                        ? '#f87171'
                                                        : (String(getRetrievalRuntime(activeModalCapability)?.operational_state || '') === 'degraded' ? '#fcd34d' : '#86efac'),
                                                    border: ['disabled', 'quota_exceeded', 'error_previous', 'setup_pending'].includes(String(getRetrievalRuntime(activeModalCapability)?.operational_state || ''))
                                                        ? '1px solid rgba(239,68,68,0.25)'
                                                        : (String(getRetrievalRuntime(activeModalCapability)?.operational_state || '') === 'degraded'
                                                            ? '1px solid rgba(245,158,11,0.25)'
                                                            : '1px solid rgba(34,197,94,0.25)'),
                                                }}
                                            >
                                                {getRetrievalStateLabel(activeModalCapability)?.replace('RAG', 'Retrieval') || 'Retrieval ready'}
                                            </span>
                                        )}
                                        {activeModalCapability.validation_errors?.length > 0 || activeModalCapability.missing_required?.length > 0 || getRetrievalSetupIssues(activeModalCapability).length > 0 ? (
                                            <span className="badge" style={{ background: 'rgba(239,68,68,0.15)', color: '#f87171', border: '1px solid rgba(239,68,68,0.25)' }}>Validation issue</span>
                                        ) : (
                                            <span className="badge" style={{ background: 'rgba(34,197,94,0.14)', color: '#86efac', border: '1px solid rgba(34,197,94,0.25)' }}>Validated</span>
                                        )}
                                        <span className="badge badge-slate">{(activeModalCapability.actions || []).length} actions</span>
                                    </div>

                                    <div style={{ background: 'rgba(255,255,255,0.015)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
                                        <div style={{ fontSize: '10px', fontWeight: '600', letterSpacing: '0.06em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '12px' }}>Description</div>
                                        <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-main)', lineHeight: '1.5' }}>{activeModalCapability.description || 'No description provided.'}</p>
                                    </div>

                                    <div style={{ background: 'rgba(255,255,255,0.015)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
                                        <div style={{ fontSize: '10px', fontWeight: '600', letterSpacing: '0.06em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '12px' }}>Actions</div>
                                        {(activeModalCapability.actions || []).length > 0 ? (
                                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, minmax(0, 1fr))', gap: '6px' }}>
                                                {(activeModalCapability.actions || []).map((action) => (
                                                    <div key={action} style={{ fontSize: '12px', color: '#cbd5e1', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)', padding: '6px 8px', fontFamily: 'monospace' }}>
                                                        {action}
                                                    </div>
                                                ))}
                                            </div>
                                        ) : (
                                            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>No actions mapped.</p>
                                        )}
                                    </div>

                                    {activeModalCapability.retrieval_profile?.enabled && (
                                        <div style={{ background: 'rgba(255,255,255,0.015)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
                                            <div style={{ fontSize: '10px', fontWeight: '600', letterSpacing: '0.06em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '12px' }}>Retrieval Runtime</div>
                                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                                                <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                                    <strong style={{ color: '#e2e8f0' }}>Operational State:</strong>{' '}
                                                    {String(getRetrievalRuntime(activeModalCapability)?.operational_state || 'n/a')}
                                                </div>
                                                <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                                    <strong style={{ color: '#e2e8f0' }}>Setup Ready:</strong>{' '}
                                                    {getRetrievalRuntime(activeModalCapability)?.setup_ready === false ? 'No' : 'Yes'}
                                                </div>
                                                <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                                    <strong style={{ color: '#e2e8f0' }}>Trust Tier:</strong>{' '}
                                                    {activeModalCapability.retrieval_profile?.quality?.trust_tier || 'n/a'}
                                                </div>
                                                <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                                    <strong style={{ color: '#e2e8f0' }}>Domains:</strong>{' '}
                                                    {(activeModalCapability.retrieval_profile?.domains || []).join(', ') || 'n/a'}
                                                </div>
                                                <div style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                                    <strong style={{ color: '#e2e8f0' }}>Roles:</strong>{' '}
                                                    {(activeModalCapability.retrieval_profile?.roles || []).join(', ') || 'n/a'}
                                                </div>
                                            </div>
                                            {(getRetrievalRuntime(activeModalCapability)?.missing_required_fields || []).length > 0 && (
                                                <div style={{ marginTop: '10px', background: 'rgba(239, 68, 68, 0.08)', padding: '8px 10px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(239, 68, 68, 0.18)' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f87171', fontSize: '11px', fontWeight: '700', marginBottom: '4px' }}>
                                                        <AlertCircle size={12} /> Missing retrieval fields
                                                    </div>
                                                    <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '11px', color: '#fca5a5' }}>
                                                        {(getRetrievalRuntime(activeModalCapability)?.missing_required_fields || []).map((f) => (
                                                            <li key={f}><b>{f}</b></li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {activeModalCapability.id === 'research_retrieve' && (
                                        <div style={{ background: 'rgba(255,255,255,0.015)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
                                            <div style={{ fontSize: '10px', fontWeight: '600', letterSpacing: '0.06em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '12px' }}>Retrieval Control Plane</div>
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

                                    
                                    <div style={{ background: 'rgba(255,255,255,0.015)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
                                        <div style={{ fontSize: '10px', fontWeight: '600', letterSpacing: '0.06em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '12px' }}>Config Snapshot</div>
                                        {(!activeModalCapability.config || Object.keys(activeModalCapability.config).length === 0) ? (
                                            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>No configuration overrides present.</p>
                                        ) : (
                                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '12px' }}>
                                                {Object.entries(activeModalCapability.config).map(([key, value]) => (
                                                    <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                        <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '500' }}>{key.replace(/_/g, ' ')}</span>
                                                        {typeof value === 'boolean' ? (
                                                            <span className={`badge ${value ? 'badge-success' : 'badge-slate'}`} style={{ width: 'fit-content' }}>
                                                                {value ? 'True' : 'False'}
                                                            </span>
                                                        ) : (
                                                            <div style={{ fontSize: '12px', color: 'var(--text-main)', background: 'rgba(255,255,255,0.03)', padding: '4px 8px', borderRadius: '4px', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                                                                {value === null ? 'null' : String(value)}
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>

                                    {(activeModalCapability.validation_errors?.length > 0 || activeModalCapability.missing_required?.length > 0 || getRetrievalSetupIssues(activeModalCapability).length > 0) && (
                                        <div style={{ background: 'rgba(239, 68, 68, 0.08)', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid rgba(239, 68, 68, 0.18)' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f87171', fontSize: '11px', fontWeight: '700', marginBottom: '4px' }}>
                                                <AlertCircle size={12} /> Validation details
                                            </div>
                                            <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '11px', color: '#fca5a5' }}>
                                                {(activeModalCapability.missing_required || []).map(f => <li key={f}>Missing required field: <b>{f}</b></li>)}
                                                {(activeModalCapability.validation_errors || []).map((e, i) => <li key={i}>{e}</li>)}
                                                {getRetrievalSetupIssues(activeModalCapability).map((e, i) => <li key={`retrieval-detail-${i}`}>{e}</li>)}
                                            </ul>
                                        </div>
                                    )}
                                </>
                            )}
                            {activeModalTab === 'agent' && (
                                <>
                                    <div style={{ background: 'rgba(255,255,255,0.015)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
                                        <div style={{ fontSize: '10px', fontWeight: '600', letterSpacing: '0.06em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '12px' }}>Agent Actions & System Prompts</div>
                                        {(!activeModalCapability.actions_meta || activeModalCapability.actions_meta.length === 0) ? (
                                            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>No actions exposed to agent.</p>
                                        ) : (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                                {activeModalCapability.actions_meta.map((action) => (
                                                    <div key={action.id} style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '12px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)' }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                            <div style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                                <Zap size={14} color="var(--card-accent)" /> {action.title} <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 'normal' }}>({action.id})</span>
                                                            </div>
                                                        </div>
                                                        <p style={{ margin: 0, fontSize: '12px', color: '#cbd5e1', lineHeight: '1.4' }}>{action.description}</p>
                                                        
                                                        {action.side_effect && (
                                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                                                <strong style={{ color: '#e2e8f0' }}>Side Effect:</strong> {action.side_effect}
                                                            </div>
                                                        )}
                                                        {action.when_to_use && (
                                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                                                <strong style={{ color: '#e2e8f0' }}>When to use:</strong> {action.when_to_use}
                                                            </div>
                                                        )}

                                                        <div style={{ marginTop: '6px' }}>
                                                            <div style={{ fontSize: '10px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Structured Parameters</div>
                                                            {renderStructuredParameters(action.parameters)}
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>

                                    <div style={{ background: 'rgba(255,255,255,0.015)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
                                        <div style={{ fontSize: '10px', fontWeight: '600', letterSpacing: '0.06em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '12px' }}>Agent Context Artifacts</div>
                                        {(!activeModalCapability.agent_artifacts || activeModalCapability.agent_artifacts.length === 0) ? (
                                            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>No markdown artifacts found in capability directory.</p>
                                        ) : (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                                    {activeModalCapability.agent_artifacts.map((file) => (
                                                        <button
                                                            key={file}
                                                            onClick={() => fetchArtifact(activeModalCapability.id, file)}
                                                            style={{
                                                                padding: '6px 12px',
                                                                background: activeArtifact === file ? 'color-mix(in srgb, var(--card-accent) 20%, transparent)' : 'rgba(255,255,255,0.05)',
                                                                border: activeArtifact === file ? '1px solid var(--card-accent)' : '1px solid var(--card-border)',
                                                                color: activeArtifact === file ? 'var(--card-accent)' : 'var(--text-main)',
                                                                borderRadius: 'var(--radius-md)',
                                                                fontSize: '12px',
                                                                cursor: 'pointer',
                                                                display: 'flex',
                                                                alignItems: 'center',
                                                                gap: '6px',
                                                                transition: 'all 0.2s'
                                                            }}
                                                        >
                                                            <FileText size={14} /> {file}
                                                        </button>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </>
                            )}
                            {activeModalTab === 'security' && (
                                <>
                                    <div style={{ background: 'rgba(255,255,255,0.015)', borderRadius: 'var(--radius-md)', padding: '16px' }}>
                                        <div style={{ fontSize: '10px', fontWeight: '600', letterSpacing: '0.06em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '12px' }}>Capability Security & ACL Linkage</div>
                                        {(!activeModalCapability.actions_meta || activeModalCapability.actions_meta.length === 0) ? (
                                            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>No action permissions to manage.</p>
                                        ) : (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                                {activeModalCapability.actions_meta.map((action) => (
                                                    <div key={action.id} style={{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '14px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)' }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '8px' }}>
                                                            <div style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                                <Shield size={14} color="var(--card-accent)" /> {action.title} <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 'normal' }}>({action.id})</span>
                                                            </div>
                                                            <span className={`badge ${action.risk_level === 'high' ? 'badge-error' : action.risk_level === 'medium' ? 'badge-warning' : 'badge-slate'}`}>
                                                                {action.risk_level.toUpperCase()} RISK
                                                            </span>
                                                        </div>

                                                        <div>
                                                            <div style={{ fontSize: '10px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Access Control List (ACL) Rules</div>
                                                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '10px' }}>
                                                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px', background: 'rgba(255,255,255,0.01)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.03)' }}>
                                                                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Allow Anyone:</span>
                                                                    <span className={`badge ${action.permissions?.allow_anyone ? 'badge-success' : 'badge-slate'}`}>
                                                                        {action.permissions?.allow_anyone ? 'Yes' : 'No'}
                                                                    </span>
                                                                </div>
                                                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px', background: 'rgba(255,255,255,0.01)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.03)' }}>
                                                                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Requires Approval:</span>
                                                                    <span className={`badge ${action.permissions?.requires_approval ? 'badge-warning' : 'badge-slate'}`}>
                                                                        {action.permissions?.requires_approval ? 'Yes' : 'No'}
                                                                    </span>
                                                                </div>
                                                            </div>
                                                        </div>

                                                        {action.permissions?.scopes && action.permissions.scopes.length > 0 && (
                                                            <div style={{ marginTop: '4px' }}>
                                                                <div style={{ fontSize: '10px', fontWeight: '600', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Required Access Scopes</div>
                                                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                                                    {action.permissions.scopes.map(scope => (
                                                                        <span key={scope} className="badge badge-slate" style={{ fontFamily: 'monospace', fontSize: '10px' }}>
                                                                            {scope}
                                                                        </span>
                                                                    ))}
                                                                </div>
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </>
                            )}
                            {activeModalTab === 'config' && (
                                <>
                                    {renderConfigForm()}
                                </>
                            )}
                        </div>
                        
                        {activeModalTab === 'config' && (
                            <div style={{ padding: isMobile ? '12px 16px' : '12px 20px', borderTop: '1px solid var(--card-border)', background: 'rgba(0,0,0,0.04)', display: 'flex', justifyContent: 'flex-end', gap: '8px', borderBottomLeftRadius: isMobile ? '10px' : '12px', borderBottomRightRadius: isMobile ? '10px' : '12px' }}>
                                <button onClick={() => setActiveModalCapability(null)} className="btn-ghost" style={{ padding: '8px 16px' }}>Cancel</button>
                                <button
                                    onClick={handleSaveConfig}
                                    className="btn-primary"
                                    disabled={isSaving}
                                    style={{ padding: '8px 16px', borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}
                                >
                                    {isSaving ? <RefreshCw size={18} className="animate-spin" /> : <Save size={18} />}
                                    <span>Save Changes</span>
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            )}

            </div>
            
            {/* Artifact Viewer Sub-Modal */}
            {isArtifactModalOpen && activeArtifact && (
                <div className="modal-overlay" style={{ zIndex: 10005, background: 'rgba(5, 7, 10, 0.9)', backdropFilter: 'blur(20px)' }} onClick={() => setIsArtifactModalOpen(false)}>
                    <div 
                        className="modal-content glass-panel" 
                        onClick={e => e.stopPropagation()} 
                        style={{
                            width: isMobile ? '100%' : 'min(90%, 900px)',
                            height: isMobile ? '100%' : '90vh',
                            maxHeight: isMobile ? '100%' : '90vh',
                            display: 'flex',
                            flexDirection: 'column',
                            borderRadius: isMobile ? '0' : '8px',
                            border: '1px solid rgba(255,255,255,0.08)',
                            boxShadow: '0 24px 60px rgba(0,0,0,0.4)'
                        }}
                    >
                        {/* Artifact Header */}
                        <div style={{ padding: '16px 24px', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.02)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <FileText size={18} color="var(--text-secondary)" />
                                <div>
                                    <h3 style={{ fontSize: '15px', fontWeight: '500', color: 'var(--text-main)', margin: 0, fontFamily: 'monospace' }}>{activeArtifact}</h3>
                                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '2px 0 0' }}>{activeModalCapability?.name} ({activeModalCapability?.id})</p>
                                </div>
                            </div>
                            <button onClick={() => setIsArtifactModalOpen(false)} className="btn-ghost" style={{ padding: '8px', background: 'rgba(255,255,255,0.05)', borderRadius: '6px' }}>
                                <X size={18} />
                            </button>
                        </div>
                        
                        {/* Artifact Content */}
                        <div className="custom-scrollbar" style={{ flex: 1, padding: isMobile ? '20px' : '40px', overflowY: 'auto', background: 'rgba(0,0,0,0.2)' }}>
                            <div style={{ maxWidth: '800px', margin: '0 auto' }}>
                                {artifactLoading ? (
                                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '200px', gap: '16px', color: 'var(--text-muted)' }}>
                                        <Loader2 size={24} className="animate-spin" />
                                        <span style={{ fontSize: '13px' }}>Carregando conteúdo...</span>
                                    </div>
                                ) : artifactError ? (
                                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', color: '#f87171', padding: '32px', background: 'rgba(239,68,68,0.05)', borderRadius: '8px', border: '1px solid rgba(239,68,68,0.1)' }}>
                                        <AlertCircle size={32} /> 
                                        <span style={{ fontSize: '14px', textAlign: 'center' }}>Não foi possível carregar este artefato. O arquivo pode estar vazio ou corrompido.</span>
                                    </div>
                                ) : (
                                    <div className="markdown-body" style={{ fontSize: '14px', color: '#f1f5f9', lineHeight: '1.7' }}>
                                        {artifactContent ? (
                                            <ErrorBoundary>
                                                <ReactMarkdown skipHtml>{artifactContent}</ReactMarkdown>
                                            </ErrorBoundary>
                                        ) : (
                                            <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '40px', fontStyle: 'italic' }}>
                                                Este documento está vazio.
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Capabilities;
