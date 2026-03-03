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

const Memory = () => {
    const [tab, setTab] = useState('semantic');
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [query, setQuery] = useState('');
    const [editingItem, setEditingItem] = useState(null);
    const [showAddModal, setShowAddModal] = useState(false);
    const [newItem, setNewItem] = useState({ content: '', category: 'General' });
    const [deletingItem, setDeletingItem] = useState(null);

    useEffect(() => {
        fetchMemory();
    }, [tab]);

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
                <button onClick={() => setShowAddModal(true)} className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', padding: 'var(--space-2) var(--space-4)', borderRadius: 'var(--radius-sm)', fontWeight: '800', fontSize: '0.8125rem' }}>
                    <PlusCircle size={18} /> SEAL IN MEMORY
                </button>
            </PageHeader>

            <div style={{ flexShrink: 0, padding: '0 var(--space-6) var(--space-6) var(--space-6)' }}>

                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        <button onClick={() => setTab('semantic')} className={`btn-ghost ${tab === 'semantic' ? 'active' : ''}`} style={{ background: tab === 'semantic' ? 'rgba(59, 130, 246, 0.1)' : '', color: tab === 'semantic' ? 'var(--accent-color)' : '' }}>
                            <Brain size={18} /> Semantic Facts
                        </button>
                        <button onClick={() => setTab('episodic')} className={`btn-ghost ${tab === 'episodic' ? 'active' : ''}`} style={{ background: tab === 'episodic' ? 'rgba(59, 130, 246, 0.1)' : '', color: tab === 'episodic' ? 'var(--accent-color)' : '' }}>
                            <History size={18} /> Episodic Log
                        </button>
                    </div>

                    <div style={{ position: 'relative', width: 'min(100%, 320px)' }}>
                        <Search size={16} style={{ position: 'absolute', left: '14px', top: '12px', opacity: 0.5, pointerEvents: 'none' }} />
                        <input
                            type="text"
                            placeholder="Search memories..."
                            className="input-field"
                            style={{ width: '100%', paddingLeft: '40px', height: '40px' }}
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                        />
                    </div>
                </div>
            </div>

            <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: '0 var(--space-6)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 340px), 1fr))', gap: '20px', paddingBottom: '100px' }}>
                    {loading ? (
                        <div style={{ gridColumn: '1/-1', textAlign: 'center', padding: '100px' }}>
                            <div className="loading-spinner" style={{ margin: '0 auto' }}></div>
                        </div>
                    ) : filteredData.length > 0 ? filteredData.map(item => (
                        <div key={item.id} className="glass-card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <span className="badge badge-accent" style={{ textTransform: 'uppercase', fontSize: '10px' }}>
                                    {item.metadata?.category || item.metadata?.action || 'Memory'}
                                </span>
                                <div style={{ display: 'flex', gap: '4px' }}>
                                    <button onClick={() => setEditingItem(item)} className="btn-ghost" style={{ padding: '6px', borderRadius: '8px' }}>
                                        <Edit3 size={14} />
                                    </button>
                                    <button onClick={() => handleDelete(item)} className="btn-ghost" style={{ padding: '6px', borderRadius: '8px', color: 'var(--error)' }}>
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            </div>
                            <p style={{ fontSize: '15px', color: 'var(--text-main)', lineHeight: '1.5', flex: 1 }}>{item.content}</p>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid var(--card-border)', paddingTop: '10px' }}>
                                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                    <Clock size={12} /> {item.metadata?.timestamp ? new Date(item.metadata.timestamp * 1000).toLocaleString() : 'Recent'}
                                </span>
                                {tab === 'episodic' && item.metadata?.status && (
                                    <span style={{ color: item.metadata.status === 'success' ? 'var(--success)' : 'var(--error)' }}>
                                        {item.metadata.status.toUpperCase()}
                                    </span>
                                )}
                            </div>
                        </div>
                    )) : (
                        <p style={{ opacity: 0.5, gridColumn: '1/-1', textAlign: 'center', padding: '40px' }}>No memories found in this sector.</p>
                    )}
                </div>

                {/* Modals */}
                {editingItem && (
                    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
                        <div className="glass animate-fade-in" style={{ width: 'min(90%, 500px)', padding: '32px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <h3 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}><Edit3 size={20} /> Edit Memory</h3>
                                <button onClick={() => setEditingItem(null)} className="btn-ghost" style={{ padding: '8px' }}><X size={20} /></button>
                            </div>
                            <textarea
                                value={editingItem.content}
                                onChange={(e) => setEditingItem({ ...editingItem, content: e.target.value })}
                                className="glass-input"
                                style={{ width: '100%', height: '150px', resize: 'none' }}
                            />
                            <div style={{ display: 'flex', gap: '12px' }}>
                                <button onClick={() => setEditingItem(null)} className="btn-ghost" style={{ flex: 1 }}>Cancel</button>
                                <button onClick={handleUpdate} className="btn-primary" style={{ flex: 1 }}>
                                    <Save size={18} /> Update Memory
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {showAddModal && (
                    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
                        <div className="glass animate-fade-in" style={{ width: 'min(90%, 500px)', padding: '32px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
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
