import { notify } from '../utils/notify.jsx';
import React, { useState, useEffect } from 'react';
import { api } from '../hooks/api';

import { Plus, Trash2, ArrowUp, ArrowDown, Settings2, Shield, AlertCircle, X } from 'lucide-react';
import ConfirmDialog from './ConfirmDialog';
import { createSecret, listSecretRefs } from '../utils/secretsApi';

const ModelPoolManager = ({
    modality,
    currentPool,
    onPoolUpdated,
    getToolsDiscoveryMode = null,
    onToolsDiscoveryModeChange = null,
    getGlobalToolsDiscoveryMode = null,
}) => {
    const LOCAL_PROVIDER_KEYS = new Set(['ollama', 'llama_server']);

    const [catalog, setCatalog] = useState({});
    const [envKeys, setEnvKeys] = useState([]);

    const [isAdding, setIsAdding] = useState(false);
    const [selectedProvider, setSelectedProvider] = useState("");

    // Form state for creating/editing an instance
    const [editingIndex, setEditingIndex] = useState(-1);
    const [formData, setFormData] = useState({});
    const [deletingIndex, setDeletingIndex] = useState(-1);

    // New Key Creation State
    const [isCreatingKey, setIsCreatingKey] = useState(false);
    const [newKeyName, setNewKeyName] = useState("");
    const [newKeyValue, setNewKeyValue] = useState("");
    const [secretTargetField, setSecretTargetField] = useState("");
    const pool = currentPool || [];

    useEffect(() => {
        let cancelled = false;

        const loadInitialData = async () => {
            try {
                const [catalogData, envKeyData] = await Promise.all([
                    api.get('/models/catalog'),
                    listSecretRefs(),
                ]);
                if (cancelled) return;
                setCatalog(catalogData);
                setEnvKeys(envKeyData);
            } catch (err) {
                if (cancelled) return;
                console.error("Failed to load model configuration metadata", err);
            }
        };

        loadInitialData();
        return () => {
            cancelled = true;
        };
    }, []);

    const handleCreateKey = async (e) => {
        e.preventDefault();
        try {
            const response = await createSecret({ key: newKeyName, value: newKeyValue });
            if (response.success) {
                notify.success(`Key ${response.key} saved to vault!`);
                const keys = await listSecretRefs();
                setEnvKeys(keys);
                if (secretTargetField) {
                    setFormData(prev => ({ ...prev, [secretTargetField]: response.key }));
                }
                setIsCreatingKey(false);
                setNewKeyName("");
                setNewKeyValue("");
                setSecretTargetField("");
            }
        } catch (err) {
            notify.error(err.message);
        }
    };

    const moveItem = (index, direction) => {
        const newPool = [...pool];
        if (direction === -1 && index > 0) {
            [newPool[index - 1], newPool[index]] = [newPool[index], newPool[index - 1]];
        } else if (direction === 1 && index < newPool.length - 1) {
            [newPool[index + 1], newPool[index]] = [newPool[index], newPool[index + 1]];
        }

        // Reassign priorities
        newPool.forEach((item, idx) => {
            item.priority = idx + 1;
        });

        savePool(newPool);
    };

    const deleteItem = (index) => {
        setDeletingIndex(index);
    };

    const confirmDeleteItem = () => {
        if (deletingIndex < 0) return;
        const newPool = pool.filter((_, i) => i !== deletingIndex);
        savePool(newPool);
        setDeletingIndex(-1);
    };

    const savePool = async (updatedPool) => {
        try {
            const response = await api.post(`/models/pool/${modality}`, updatedPool);
            if (response.success) {
                notify.success(`Model pool for ${modality} updated and reloaded!`);
                if (onPoolUpdated) onPoolUpdated(response.pool);
            }
        } catch (err) {
            notify.error(err.message);
        }
    };

    const handleSaveInstance = () => {
        const newPool = [...pool];
        const normalizedFormData = { ...formData };
        if (typeof normalizedFormData.secret_ref === 'string' && normalizedFormData.secret_ref && !normalizedFormData.secret_ref.startsWith('ENV_')) {
            normalizedFormData.secret_ref = `ENV_${normalizedFormData.secret_ref.replace(/^ENV_/, '')}`;
        }
        if (editingIndex >= 0) {
            newPool[editingIndex] = { ...normalizedFormData };
        } else {
            const generatedId = normalizedFormData.id || `${normalizedFormData.provider}-${newPool.length + 1}`;
            newPool.push({
                ...normalizedFormData,
                id: generatedId,
                priority: newPool.length + 1,
                enabled: true
            });
        }
        savePool(newPool);

        setEditingIndex(-1);
        setIsAdding(false);
        setFormData({});
        setSelectedProvider("");
        setSecretTargetField("");
    };

    const startEdit = (index) => {
        setEditingIndex(index);
        setFormData({ ...pool[index] });
        setSelectedProvider(pool[index].provider);
        setIsAdding(true);
    };

    const providerSchema = catalog[selectedProvider];
    const authFields = Array.isArray(providerSchema?.auth?.fields) ? providerSchema.auth.fields : [];
    const settingsFields = Array.isArray(providerSchema?.settings_fields) ? providerSchema.settings_fields : [];
    const supportsDiscoveryPolicy = modality === 'chat' && typeof onToolsDiscoveryModeChange === 'function';
    const discoveryModeValue = getToolsDiscoveryMode ? (getToolsDiscoveryMode(formData?.model || '') || 'inherit') : 'inherit';
    const isDiscoveryInherited = discoveryModeValue === 'inherit';
    const getDiscoveryModeLabel = (mode) => {
        const normalized = String(mode || '').trim().toLowerCase();
        if (normalized === 'agentic_only') return 'Agentic only';
        if (normalized === 'hybrid') return 'Hybrid';
        if (normalized === 'deterministic') return 'Deterministic';
        if (normalized === 'off') return 'Off';
        if (normalized === 'inherit') return 'Automatic';
        return normalized || 'Automatic';
    };

    const isLocalProvider = (providerKey) => LOCAL_PROVIDER_KEYS.has(String(providerKey || '').trim().toLowerCase());

    const getProviderDisplayName = (providerKey) => {
        const schema = catalog[providerKey];
        if (String(providerKey || '').trim().toLowerCase() === 'openai') return 'OpenAI';
        return String(schema?.display_name || providerKey || '').trim();
    };

    const getProviderSubtitle = (providerKey) => {
        const key = String(providerKey || '').trim().toLowerCase();
        if (key === 'ollama') return 'Ollama runtime';
        if (key === 'llama_server') return 'llama.cpp runtime';
        return '';
    };

    const groupedProviderOptions = Object.entries(catalog)
        .filter(([, c]) => c.supports && c.supports.includes(modality))
        .map(([key, schema]) => ({ key, schema }))
        .sort((a, b) => {
            const aLocal = isLocalProvider(a.key) ? 0 : 1;
            const bLocal = isLocalProvider(b.key) ? 0 : 1;
            if (aLocal !== bLocal) return aLocal - bLocal;
            return getProviderDisplayName(a.key).localeCompare(getProviderDisplayName(b.key));
        });

    const localProviderOptions = groupedProviderOptions.filter((item) => isLocalProvider(item.key));
    const otherProviderOptions = groupedProviderOptions.filter((item) => !isLocalProvider(item.key));

    const secretFieldTitle = 'API Key (optional)';

    const renderSecretRefEditor = (fieldKey = 'secret_ref', title = secretFieldTitle, description = 'Optional: store the key in the vault and bind it to this model instance.') => {
        const targetValue = formData[fieldKey] || '';
        const creating = isCreatingKey && secretTargetField === fieldKey;
        return (
            <div className="form-group" style={{ background: 'rgba(var(--accent-rgb), 0.05)', padding: '16px', borderRadius: '12px', border: '1px solid rgba(var(--accent-rgb), 0.2)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'center' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Shield size={14} color="var(--accent-color)" /> {title}
                    </label>
                    <button
                        onClick={() => {
                            const nextIsCreating = !(isCreatingKey && secretTargetField === fieldKey);
                            setIsCreatingKey(nextIsCreating);
                            setSecretTargetField(nextIsCreating ? fieldKey : "");
                        }}
                        className="btn-ghost"
                        style={{ fontSize: '11px', padding: '2px 6px', color: 'var(--accent-color)' }}
                    >
                        {creating ? <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><X size={12} /> Cancel New Key</span> : '+ Create New Key'}
                    </button>
                </div>
                <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)', marginBottom: '8px' }}>{description}</p>

                {!creating ? (
                    <select
                        className="input-field"
                        value={targetValue}
                        onChange={(e) => setFormData({ ...formData, [fieldKey]: e.target.value })}
                    >
                        <option value="">-- No API key --</option>
                        {(envKeys || []).map(k => (
                            <option key={k} value={k}>{k}</option>
                        ))}
                    </select>
                ) : (
                    <form onSubmit={handleCreateKey} style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px' }}>
                        <input
                            type="text"
                            className="input-field"
                            placeholder="ENV_MODEL_PROVIDER_SECRET"
                            value={newKeyName}
                            onChange={e => setNewKeyName(e.target.value)}
                            required
                        />
                        <input
                            type="password"
                            className="input-field"
                            placeholder="Paste the secret value here..."
                            value={newKeyValue}
                            onChange={e => setNewKeyValue(e.target.value)}
                            required
                        />
                        <button type="submit" className="btn-primary" style={{ alignSelf: 'flex-start', fontSize: '12px', padding: '6px 12px' }}>Save to Vault</button>
                    </form>
                )}
            </div>
        );
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h4 style={{ fontSize: '15px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '1px', color: 'rgba(255,255,255,0.7)' }}>
                    Active {modality} Models
                </h4>
                {!isAdding && (
                    <button
                        onClick={() => {
                            setIsAdding(true);
                            setEditingIndex(-1);
                            setFormData({});
                            setSelectedProvider(Object.keys(catalog)[0] || "");
                        }}
                        className="btn-primary"
                        style={{ padding: '6px 12px', fontSize: '12px', borderRadius: '8px' }}
                    >
                        <Plus size={14} style={{ marginRight: '6px' }} /> Add Model
                    </button>
                )}
            </div>

            {/* List View */}
            {!isAdding && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {pool.length === 0 ? (
                        <div style={{ padding: '24px', textAlign: 'center', background: 'rgba(255,255,255,0.02)', borderRadius: '12px', border: '1px dashed rgba(255,255,255,0.1)' }}>
                            <AlertCircle size={24} style={{ margin: '0 auto 8px', opacity: 0.5 }} />
                            <p style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)' }}>No models configured. Add one below.</p>
                        </div>
                    ) : (
                        pool.map((item, index) => (
                            <div key={item.id} style={{ display: 'flex', alignItems: 'center', background: 'rgba(255,255,255,0.03)', padding: '12px 16px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginRight: '16px' }}>
                                    <button onClick={() => moveItem(index, -1)} disabled={index === 0} className="icon-btn" style={{ padding: '2px', opacity: index === 0 ? 0.2 : 1 }}><ArrowUp size={14} /></button>
                                    <button onClick={() => moveItem(index, 1)} disabled={index === pool.length - 1} className="icon-btn" style={{ padding: '2px', opacity: index === pool.length - 1 ? 0.2 : 1 }}><ArrowDown size={14} /></button>
                                </div>

                                <div style={{ flex: 1 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <div className={`w-2 h-2 rounded-full ${item.enabled ? 'bg-green-500' : 'bg-red-500'}`} />
                                        <span style={{ fontWeight: '600', fontSize: '14px' }}>
                                            {isLocalProvider(item.provider) ? 'Local model' : getProviderDisplayName(item.provider)}
                                        </span>
                                        {isLocalProvider(item.provider) && (
                                            <span style={{ fontSize: '11px', color: 'rgba(255,255,255,0.55)' }}>
                                                {getProviderDisplayName(item.provider)}
                                            </span>
                                        )}
                                        {item.model && <span style={{ fontSize: '12px', color: 'var(--accent-color)', background: 'rgba(var(--accent-rgb), 0.1)', padding: '2px 8px', borderRadius: '12px' }}>{item.model}</span>}
                                    </div>
                                    <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', marginTop: '4px' }}>
                                        ID: {item.id} | Priority {item.priority || index + 1}
                                        {isLocalProvider(item.provider) && getProviderSubtitle(item.provider) ? ` | ${getProviderSubtitle(item.provider)}` : ''}
                                    </div>
                                </div>

                                <div style={{ display: 'flex', gap: '8px' }}>
                                    <button onClick={() => startEdit(index)} className="icon-btn" style={{ padding: '8px', background: 'rgba(255,255,255,0.05)' }}><Settings2 size={16} /></button>
                                    <button onClick={() => deleteItem(index)} className="icon-btn" style={{ padding: '8px', background: 'rgba(255,50,50,0.1)', color: '#ff5f56' }}><Trash2 size={16} /></button>
                                </div>
                            </div>
                        ))
                    )}
                </div>
            )}

            {/* Editor View */}
            {isAdding && (
                <div style={{ background: 'rgba(0,0,0,0.2)', padding: '20px', borderRadius: '16px', border: '1px solid rgba(255,255,255,0.1)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
                        <h5 style={{ fontWeight: '700' }}>{editingIndex >= 0 ? 'Edit Instance' : 'New Instance'}</h5>
                        <button onClick={() => { setIsAdding(false); setIsCreatingKey(false); }} className="btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', padding: '6px 12px' }}><X size={14} /> Cancel</button>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                        <div className="form-group">
                            <label>Provider</label>
                            <select
                                className="input-field"
                                value={selectedProvider}
                                onChange={(e) => {
                                    setSelectedProvider(e.target.value);
                                    setFormData({ provider: e.target.value });
                                    setSecretTargetField("");
                                }}
                                disabled={editingIndex >= 0}
                            >
                                <option value="" disabled>Select a model family</option>
                                {localProviderOptions.length > 0 && (
                                    <optgroup label="Local models">
                                        {localProviderOptions.map(({ key }) => (
                                            <option key={key} value={key}>{getProviderDisplayName(key)}</option>
                                        ))}
                                    </optgroup>
                                )}
                                {otherProviderOptions.length > 0 && (
                                    <optgroup label="Other models">
                                        {otherProviderOptions.map(({ key }) => (
                                            <option key={key} value={key}>{getProviderDisplayName(key)}</option>
                                        ))}
                                    </optgroup>
                                )}
                            </select>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                            {selectedProvider !== 'openai' && (
                                <div className="form-group">
                                    <label>Instance ID</label>
                                    <input
                                        type="text"
                                        className="input-field"
                                        placeholder={`${selectedProvider}-1`}
                                        value={formData.id || ''}
                                        onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                                    />
                                </div>
                            )}
                            <div className="form-group">
                                <label>Priority</label>
                                <input
                                    type="number"
                                    className="input-field"
                                    placeholder={editingIndex >= 0 ? String(pool[editingIndex]?.priority || 1) : String(pool.length + 1)}
                                    value={formData.priority !== undefined ? formData.priority : ''}
                                    onChange={(e) => setFormData({ ...formData, priority: parseInt(e.target.value) || 1 })}
                                />
                            </div>
                        </div>

                        {renderSecretRefEditor()}

                        {providerSchema && authFields
                            .filter((field) => String(field?.key || '').trim() !== 'secret_ref')
                            .map(field => (
                                <div key={field.key} className="form-group" style={{ background: 'rgba(var(--accent-rgb), 0.05)', padding: '16px', borderRadius: '12px', border: '1px solid rgba(var(--accent-rgb), 0.2)' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                            <Shield size={14} color="var(--accent-color)" /> {field.title} {field.required && '*'}
                                        </label>
                                    </div>
                                    <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)', marginBottom: '8px' }}>{field.description}</p>
                                    <input
                                        type="text"
                                        className="input-field"
                                        placeholder={field.placeholder || ''}
                                        value={formData[field.key] || ''}
                                        onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                                    />
                                </div>
                            ))}

                        {providerSchema && settingsFields.map(field => (
                            <div key={field.key} className="form-group">
                                <label>{field.title} {field.required && '*'}</label>
                                <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', marginBottom: '4px' }}>{field.description}</p>
                                <input
                                    type={field.type === 'int' || field.type === 'number' ? 'number' : 'text'}
                                    className="input-field"
                                    placeholder={String(field.default || '')}
                                    value={formData[field.key] !== undefined ? formData[field.key] : ''}
                                    onChange={(e) => {
                                        const val = field.type === 'int' || field.type === 'number' ? parseInt(e.target.value || '0', 10) || 0 : e.target.value;
                                        setFormData({ ...formData, [field.key]: val });
                                    }}
                                    required={field.required}
                                />
                            </div>
                        ))}

                        {supportsDiscoveryPolicy && (
                            <div style={{ background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.18)', borderRadius: '12px', padding: '16px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '12px' }}>
                                    <div>
                                        <div style={{ fontSize: '13px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'rgba(255,255,255,0.75)' }}>
                                            Tool Discovery
                                        </div>
                                        <div style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)', marginTop: '4px' }}>
                                            Discovery policy for the active chat model. Execution remains gated by the kernel.
                                        </div>
                                    </div>
                                    {getToolsDiscoveryMode && getGlobalToolsDiscoveryMode && (
                                        <span className="status-pill online" style={{ background: 'rgba(16,185,129,0.12)', color: '#34d399' }}>
                                            Effective: {getDiscoveryModeLabel(
                                                getToolsDiscoveryMode(formData?.model || '') ||
                                                getGlobalToolsDiscoveryMode() ||
                                                'agentic_only'
                                            )}
                                        </span>
                                    )}
                                </div>
                                <div className="form-group">
                                    <label>Discovery Mode</label>
                                    <select
                                        className="input-field"
                                        value={discoveryModeValue}
                                        onChange={(e) => onToolsDiscoveryModeChange(formData?.model || '', e.target.value)}
                                    >
                                        <option value="inherit">Automatic (inherit global)</option>
                                        <option value="agentic_only">Agentic only</option>
                                        <option value="hybrid">Hybrid</option>
                                        <option value="deterministic">Deterministic</option>
                                        <option value="off">Off</option>
                                    </select>
                                    <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.42)', marginTop: '6px' }}>
                                        {isDiscoveryInherited
                                            ? 'No override is set. This model inherits the global discovery policy.'
                                            : 'This model overrides the global discovery policy.'}
                                    </div>
                                </div>
                            </div>
                        )}

                        <div className="flex-between" style={{ marginTop: '16px' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <input
                                    type="checkbox"
                                    className="toggle-switch"
                                    checked={formData.enabled !== false}
                                    onChange={(e) => setFormData({ ...formData, enabled: e.target.checked })}
                                />
                                Enable this Provider
                            </label>
                            <button onClick={handleSaveInstance} className="btn-primary" style={{ padding: '8px 16px' }}>
                                Save Instance
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <ConfirmDialog
                isOpen={deletingIndex >= 0}
                title="Remove Instance"
                message="Are you sure you want to remove this model instance from the pool?"
                confirmText="Yes, Remove"
                cancelText="Cancel"
                onConfirm={confirmDeleteItem}
                onCancel={() => setDeletingIndex(-1)}
                isDestructive={true}
            />
        </div>
    );
};

export default ModelPoolManager;
