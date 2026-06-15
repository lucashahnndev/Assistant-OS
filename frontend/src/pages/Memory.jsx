import { useState, useEffect } from 'react';
import { api } from '../hooks/api';
import {
    Database,
    History,
    PlusCircle,
    Search,
    Tag,
    Clock,
    Brain,
    Trash2,
    Edit3,
    X,
    Save,
    Plus,
    CheckCircle2,
    XCircle,
    AlertCircle
} from 'lucide-react';
import PageHeader from '../components/PageHeader';
import ConfirmDialog from '../components/ConfirmDialog';

const MEMORY_PREVIEW_MAX_CHARS = 120;

const truncateText = (value, max = MEMORY_PREVIEW_MAX_CHARS) => {
    const text = String(value || '').trim();
    if (!text) return '';
    if (text.length <= max) return text;
    return `${text.slice(0, max).trimEnd()}...`;
};

const Memory = () => {
    const [tab, setTab] = useState('semantic');
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [query, setQuery] = useState('');
    const [editingItem, setEditingItem] = useState(null);
    const [showAddModal, setShowAddModal] = useState(false);
    const [newItem, setNewItem] = useState({ content: '', category: 'General' });
    const [deletingItem, setDeletingItem] = useState(null);
    const [isNarrowHeader, setIsNarrowHeader] = useState(window.innerWidth < 980);
    const [isCompactHeader, setIsCompactHeader] = useState(window.innerWidth < 1200);

    useEffect(() => {
        fetchMemory();
    }, [tab]);

    useEffect(() => {
        const onResize = () => {
            setIsNarrowHeader(window.innerWidth < 980);
            setIsCompactHeader(window.innerWidth < 1200);
        };
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
    }, []);

    const fetchMemory = async () => {
        setLoading(true);
        try {
            const endpoint = tab === 'semantic' ? '/memory/semantic' : '/memory/episodic';
            const results = await api.get(endpoint);
            setData(results);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };

    const handleDelete = (item) => {
        setDeletingItem(item);
    };

    const confirmDelete = async () => {
        if (!deletingItem) return;
        try {
            await api.delete(`/memory/${tab}/${deletingItem.id}`);
            setData(data.filter(item => item.id !== deletingItem.id));
            setDeletingItem(null);
        } catch (err) { alert("Failed to delete memory: " + err.message); }
    };

    const handleUpdate = async () => {
        try {
            await api.put(`/memory/${tab}/${editingItem.id}`, {
                content: editingItem.content,
                category: editingItem.metadata?.category,
                action: editingItem.metadata?.action
            });
            setData(data.map(item => item.id === editingItem.id ? editingItem : item));
            setEditingItem(null);
        } catch (err) { alert("Update failed: " + err.message); }
    };

    const handleAdd = async () => {
        try {
            await api.post('/memory/facts', newItem);
            setShowAddModal(false);
            setNewItem({ content: '', category: 'General' });
            fetchMemory();
        } catch (err) { alert("Failed to add fact: " + err.message); }
    };

    const filteredData = data.filter(item =>
        item.content.toLowerCase().includes(query.toLowerCase()) ||
        (item.metadata?.category || item.metadata?.action || '').toLowerCase().includes(query.toLowerCase())
    );

    return (
        <div className="animate-fade-in" style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <PageHeader
                title="Memory Vault"
                subtitle="Long-term semantic storage and episodic recall."
            >
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        rowGap: '8px',
                        width: '100%',
                        justifyContent: 'space-between',
                        flexWrap: isNarrowHeader ? 'wrap' : 'nowrap',
                    }}
                >
                    <div style={{ display: 'flex', gap: '4px', padding: '3px', border: '1px solid var(--card-border)', borderRadius: '9px', background: 'rgba(255,255,255,0.02)', flexShrink: 0 }}>
                        <button
                            onClick={() => setTab('semantic')}
                            className="btn-ghost"
                            style={{
                                padding: '6px 8px',
                                borderRadius: '7px',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '6px',
                                fontSize: '12px',
                                fontWeight: '700',
                                background: tab === 'semantic' ? 'var(--accent-glow)' : 'transparent',
                                color: tab === 'semantic' ? 'var(--accent-color)' : 'var(--text-muted)',
                            }}
                        >
                            <Brain size={14} />
                            <span>Semantic</span>
                        </button>
                        <button
                            onClick={() => setTab('episodic')}
                            className="btn-ghost"
                            style={{
                                padding: '6px 8px',
                                borderRadius: '7px',
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '6px',
                                fontSize: '12px',
                                fontWeight: '700',
                                background: tab === 'episodic' ? 'var(--accent-glow)' : 'transparent',
                                color: tab === 'episodic' ? 'var(--accent-color)' : 'var(--text-muted)',
                            }}
                        >
                            <History size={14} />
                            <span>Episodic</span>
                        </button>
                    </div>

                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            marginLeft: isNarrowHeader ? '0' : 'auto',
                            flexWrap: 'nowrap',
                            minWidth: 0,
                            width: isNarrowHeader ? '100%' : 'auto',
                            justifyContent: isNarrowHeader ? 'space-between' : 'flex-end',
                        }}
                    >
                        <div
                            style={{
                                position: 'relative',
                                width: isNarrowHeader ? 'calc(100% - 42px)' : isCompactHeader ? '240px' : '280px',
                                minWidth: 0,
                            }}
                        >
                            <Search size={14} style={{ position: 'absolute', left: '10px', top: '10px', opacity: 0.5, pointerEvents: 'none' }} />
                            <input
                                type="text"
                                placeholder="Search memories..."
                                className="input-field"
                                style={{ width: '100%', paddingLeft: '32px', height: '34px', fontSize: '13px' }}
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                            />
                        </div>

                        <button
                            onClick={() => setShowAddModal(true)}
                            className="btn-primary"
                            title="Add memory"
                            aria-label="Add memory"
                            style={{
                                width: '34px',
                                minWidth: '34px',
                                height: '34px',
                                padding: '0',
                                borderRadius: '8px',
                                display: 'inline-flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                flexShrink: 0,
                            }}
                        >
                            <Plus size={16} />
                        </button>
                    </div>
                </div>
            </PageHeader>

            <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '0 var(--space-6)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 300px), 1fr))', gap: '14px', paddingBottom: '100px' }}>
                    {loading ? (
                        <div style={{ gridColumn: '1/-1', textAlign: 'center', padding: '100px' }}>
                            <div className="loading-spinner" style={{ margin: '0 auto' }}></div>
                        </div>
                    ) : filteredData.length > 0 ? filteredData.map(item => {
                        const contentPreview = truncateText(item.content, MEMORY_PREVIEW_MAX_CHARS);
                        const chipLabel = item.metadata?.category || item.metadata?.action || 'Memory';
                        return (
                        <div key={item.id} style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px', borderRadius: 'var(--radius-md)', border: '1px solid var(--card-border)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <span
                                    className="badge badge-accent"
                                    title={chipLabel}
                                    style={{
                                        textTransform: 'uppercase',
                                        fontSize: '10px',
                                        maxWidth: '72%',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                        display: 'inline-block',
                                    }}
                                >
                                    {chipLabel}
                                </span>
                                <div style={{ display: 'flex', gap: '4px' }}>
                                    <button onClick={() => setEditingItem(item)} className="btn-ghost" style={{ padding: '5px', borderRadius: '7px' }}>
                                        <Edit3 size={13} />
                                    </button>
                                    <button onClick={() => handleDelete(item)} className="btn-ghost" style={{ padding: '5px', borderRadius: '7px', color: 'var(--error)' }}>
                                        <Trash2 size={13} />
                                    </button>
                                </div>
                            </div>
                            <p
                                style={{
                                    fontSize: '13px',
                                    color: 'var(--text-main)',
                                    lineHeight: '1.45',
                                    flex: 1,
                                    overflowWrap: 'anywhere',
                                    display: '-webkit-box',
                                    WebkitLineClamp: 3,
                                    WebkitBoxOrient: 'vertical',
                                    overflow: 'hidden',
                                    cursor: 'pointer',
                                }}
                                onClick={() => setEditingItem(item)}
                            >
                                {contentPreview}
                            </p>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', fontSize: '10px', color: 'var(--text-muted)', borderTop: '1px solid var(--card-border)', paddingTop: '8px' }}>
                                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                    <Clock size={12} /> {item.metadata?.timestamp ? new Date(item.metadata.timestamp * 1000).toLocaleString() : 'Recent'}
                                </span>
                                {tab === 'episodic' && item.metadata?.status && (
                                    <span style={{ 
                                        color: item.metadata.status === 'success' ? 'color-mix(in srgb, var(--success) 40%, var(--text-muted))' : 'color-mix(in srgb, var(--error) 40%, var(--text-muted))',
                                        fontSize: '9px',
                                        letterSpacing: '0.05em'
                                    }}>
                                        {item.metadata.status.toUpperCase()}
                                    </span>
                                )}
                            </div>
                        </div>
                    );
                    }) : (
                        <p style={{ opacity: 0.5, gridColumn: '1/-1', textAlign: 'center', padding: '40px' }}>No memories found in this sector.</p>
                    )}
                </div>

                {/* Modals */}
                {editingItem && (
                    <div className="modal-overlay" onClick={() => setEditingItem(null)}>
                        <div className="animate-fade-in" style={{ width: 'min(92%, 560px)', minHeight: '420px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '12px', background: 'var(--card-bg)', border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '1.1rem' }}><Database size={18} /> Memory Details</h3>
                                <button onClick={() => setEditingItem(null)} className="btn-ghost" style={{ padding: '6px' }}><X size={18} /></button>
                            </div>
                            <textarea
                                value={editingItem.content}
                                onChange={(e) => setEditingItem({ ...editingItem, content: e.target.value })}
                                className="glass-input"
                                style={{ width: '100%', height: '280px', resize: 'none' }}
                            />
                            <div style={{ display: 'flex' }}>
                                <button onClick={handleUpdate} className="btn-primary" style={{ width: '100%' }}>
                                    <Save size={18} /> Update Memory
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {showAddModal && (
                    <div className="modal-overlay" onClick={() => setShowAddModal(false)}>
                        <div className="animate-fade-in" style={{ width: 'min(90%, 500px)', padding: '32px', display: 'flex', flexDirection: 'column', gap: '20px', background: 'var(--card-bg)', border: '1px solid var(--card-border)', borderRadius: 'var(--radius-md)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <h3 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}><PlusCircle size={20} /> Add New Fact</h3>
                                <button onClick={() => setShowAddModal(false)} className="btn-ghost" style={{ padding: '8px' }}><X size={20} /></button>
                            </div>
                            <div>
                                <label style={{ display: 'block', fontSize: '13px', fontWeight: 'bold', marginBottom: '8px' }}>Category</label>
                                <select
                                    value={newItem.category}
                                    onChange={(e) => setNewItem({ ...newItem, category: e.target.value })}
                                    className="glass-input"
                                    style={{ width: '100%' }}
                                >
                                    <option value="General">General</option>
                                    <option value="Preference">User Preference</option>
                                    <option value="Fact">Knowledge Fact</option>
                                    <option value="Identity">Identity</option>
                                </select>
                            </div>
                            <div>
                                <label style={{ display: 'block', fontSize: '13px', fontWeight: 'bold', marginBottom: '8px' }}>Content</label>
                                <textarea
                                    value={newItem.content}
                                    onChange={(e) => setNewItem({ ...newItem, content: e.target.value })}
                                    placeholder="What would you like the assistant to remember?"
                                    className="glass-input"
                                    style={{ width: '100%', height: '120px', resize: 'none' }}
                                />
                            </div>
                            <div style={{ display: 'flex', gap: '12px' }}>
                                <button onClick={() => setShowAddModal(false)} className="btn-ghost" style={{ flex: 1 }}>Cancel</button>
                                <button onClick={handleAdd} className="btn-primary" style={{ flex: 1 }}>
                                    <Save size={18} /> Seal in Memory
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                <ConfirmDialog
                    isOpen={!!deletingItem}
                    title="Confirm Deletion"
                    message={deletingItem ? `Are you sure you want to permanently delete this memory?\n\n"${deletingItem.content.substring(0, 100)}${deletingItem.content.length > 100 ? '...' : ''}"` : ""}
                    confirmText="Yes, Delete"
                    cancelText="Cancel"
                    onConfirm={confirmDelete}
                    onCancel={() => setDeletingItem(null)}
                    isDestructive={true}
                />
            </div>
        </div>
    );
};

export default Memory;
