import React, { useState, useEffect } from 'react';
import { api } from '../hooks/api';
import toast from 'react-hot-toast';
import { Plus, Trash2, ArrowUp, ArrowDown, Settings2, Shield, AlertCircle } from 'lucide-react';
import ConfirmDialog from './ConfirmDialog';
import { createSecret, listSecretRefs } from '../utils/secretsApi';

const ModelPoolManager = ({ modality, currentPool, onPoolUpdated }) => {
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
                toast.success(`Key ${response.key} saved to vault!`);
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
            toast.error(err.message);
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
                toast.success(`Model pool for ${modality} updated and reloaded!`);
                if (onPoolUpdated) onPoolUpdated(response.pool);
            }
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleSaveInstance = () => {
        const newPool = [...pool];
        if (editingIndex >= 0) {
            newPool[editingIndex] = { ...formData };
        } else {
            const generatedId = formData.id || `${formData.provider}-${newPool.length + 1}`;
            newPool.push({
                ...formData,
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
                                        <span style={{ fontWeight: '600', fontSize: '14px' }}>{item.provider}</span>
                                        {item.model && <span style={{ fontSize: '12px', color: 'var(--accent-color)', background: 'rgba(var(--accent-rgb), 0.1)', padding: '2px 8px', borderRadius: '12px' }}>{item.model}</span>}
                                    </div>
                                    <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', marginTop: '4px' }}>
                                        ID: {item.id} | Priority {item.priority || index + 1}
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
                        <button onClick={() => { setIsAdding(false); setIsCreatingKey(false); }} className="btn-ghost" style={{ fontSize: '12px', padding: '4px 8px' }}>Cancel</button>
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
                                {Object.entries(catalog)
                                    .filter(([, c]) => c.supports && c.supports.includes(modality))
                                    .map(([key, c]) => (
                                        <option key={key} value={key}>{c.display_name || key}</option>
                                    ))}
                            </select>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
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

                        {providerSchema && authFields.map(field => (
                            <div key={field.key} className="form-group" style={{ background: 'rgba(var(--accent-rgb), 0.05)', padding: '16px', borderRadius: '12px', border: '1px solid rgba(var(--accent-rgb), 0.2)' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        <Shield size={14} color="var(--accent-color)" /> {field.title} {field.required && '*'}
                                    </label>
                                    <button
                                        onClick={() => {
                                            const nextIsCreating = !(isCreatingKey && secretTargetField === field.key);
                                            setIsCreatingKey(nextIsCreating);
                                            setSecretTargetField(nextIsCreating ? field.key : "");
                                        }}
                                        className="btn-ghost"
                                        style={{ fontSize: '11px', padding: '2px 6px', color: 'var(--accent-color)' }}
                                    >
                                        {isCreatingKey && secretTargetField === field.key ? 'Cancel New Key' : '+ Create New Key'}
                                    </button>
                                </div>
                                <p style={{ fontSize: '11px', color: 'rgba(255,255,255,0.5)', marginBottom: '8px' }}>{field.description}</p>

                                {!(isCreatingKey && secretTargetField === field.key) ? (
                                    <select
                                        className="input-field"
                                        value={formData[field.key] || ''}
                                        onChange={(e) => setFormData({ ...formData, [field.key]: e.target.value })}
                                    >
                                        <option value="">-- Select Environment Key --</option>
                                        {(envKeys || []).map(k => (
                                            <option key={k} value={k}>{k}</option>
                                        ))}
                                    </select>
                                ) : (
                                    <form onSubmit={handleCreateKey} style={{ display: 'flex', flexDirection: 'column', gap: '8px', background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px' }}>
                                        <input
                                            type="text"
                                            className="input-field"
                                            placeholder={field.placeholder || "ENV_MODEL_PROVIDER_SECRET"}
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

                        <div className="flex-between" style={{ marginTop: '16px' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <input
                                    type="checkbox"
                                    className="luxury-checkbox"
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
