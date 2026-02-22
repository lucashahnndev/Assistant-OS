import React, { useState, useEffect, useMemo } from 'react';
import {
    Shield,
    User,
    Users,
    MessageSquare,
    Settings,
    CheckCircle,
    XCircle,
    Slash,
    Search,
    Filter,
    Edit,
    Save,
    Lock,
    Unlock,
    Activity,
    AlertTriangle,
    Plus,
    Trash2,
    Layers
} from 'lucide-react';
import { api } from '../hooks/api';
import { toast } from 'react-hot-toast';
import PageHeader from '../components/PageHeader';

const API_BASE = '/messaging_access';
const INTERFACE_META = {
    telegram: {
        label: 'Telegram',
        description: 'Canal oficial do bot no Telegram.',
        internal: false
    },
    web: {
        label: 'Web',
        description: 'Canal do painel web autenticado.',
        internal: false
    },
    cli: {
        label: 'CLI',
        description: 'Canal local de terminal/bridge para operações e testes.',
        internal: false
    },
    validator: {
        label: 'Validator (Legado)',
        description: 'Alias legado, redirecionado para CLI.',
        internal: true
    },
    terminal_bridge: {
        label: 'Terminal Bridge (Legado)',
        description: 'Alias legado, redirecionado para CLI.',
        internal: true
    }
};

const INTERFACE_ORDER = {
    telegram: 1,
    web: 2,
    cli: 3,
    validator: 98,
    terminal_bridge: 99
};

const MessagingAccess = () => {
    const [interfaces, setInterfaces] = useState({});
    const [activeInterface, setActiveInterface] = useState('telegram');
    const [users, setUsers] = useState([]);
    const [chats, setChats] = useState([]);
    const [registry, setRegistry] = useState([]);
    const [groups, setGroups] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [filterStatus, setFilterStatus] = useState('all');
    const [activeTab, setActiveTab] = useState('config'); // 'config', 'groups', 'users', 'chats'
    const [editingOverrides, setEditingOverrides] = useState(null); // {type: 'user'|'chat', data: entity}
    const [editingGroup, setEditingGroup] = useState(null);
    const [newGroup, setNewGroup] = useState({
        id: '',
        name: '',
        description: '',
        allow_actions: '',
        deny_actions: '',
        allow_skills: '',
        deny_skills: ''
    });
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);
    const [showInternalInterfaces, setShowInternalInterfaces] = useState(false);
    const [groupActionSearch, setGroupActionSearch] = useState('');
    const [editGroupActionSearch, setEditGroupActionSearch] = useState('');
    const [showAdvancedCreate, setShowAdvancedCreate] = useState(false);
    const [showAdvancedEdit, setShowAdvancedEdit] = useState(false);

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 640);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);


    useEffect(() => {
        fetchData();
    }, []);

    useEffect(() => {
        const interfaceIds = Object.keys(interfaces || {});
        if (interfaceIds.length === 0) return;

        const visible = interfaceIds.filter(itf => showInternalInterfaces || !INTERFACE_META[itf]?.internal);
        const fallback = visible.length > 0 ? visible : interfaceIds;
        if (!fallback.includes(activeInterface)) {
            setActiveInterface(fallback[0]);
        }
    }, [interfaces, showInternalInterfaces, activeInterface]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const [intRes, userRes, chatRes, regRes, groupRes] = await Promise.all([
                api.get(`${API_BASE}/interfaces`),
                api.get(`${API_BASE}/users`),
                api.get(`${API_BASE}/chats`),
                api.get('/skills/registry'),
                api.get(`${API_BASE}/groups`)
            ]);
            setInterfaces(intRes);
            setUsers(userRes);
            setChats(chatRes);
            setRegistry(regRes);
            setGroups(Array.isArray(groupRes) ? groupRes : []);
        } catch (error) {
            try {
                const groupsRes = await api.get(`${API_BASE}/groups`);
                setGroups(groupsRes);
            } catch (_) {
                setGroups([]);
            }
            toast.error("Failed to load messaging access data");
        } finally {
            setLoading(false);
        }
    };

    const handleInterfaceUpdate = async (update) => {
        try {
            const res = await api.patch(`${API_BASE}/interfaces/${activeInterface}`, update);
            setInterfaces(prev => ({ ...prev, [activeInterface]: res }));
            const label = INTERFACE_META[activeInterface]?.label || activeInterface;
            toast.success(`Settings saved for ${label}`);
        } catch (error) {
            toast.error("Failed to update interface settings");
        }
    };

    const handleStatusUpdate = async (type, interface_name, id, status) => {
        const endpoint = type === 'user' ? 'users' : 'chats';
        try {
            await api.post(`${API_BASE}/${endpoint}/${interface_name}/${id}/status`, { status });
            toast.success(`${type === 'user' ? 'User' : 'Chat'} ${status} successfully`);
            fetchData();
        } catch (error) {
            toast.error(`Failed to update ${status}`);
        }
    };

    const handleSaveOverrides = async () => {
        const { type, data } = editingOverrides;
        const endpoint = type === 'user' ? 'users' : 'chats';
        try {
            await api.patch(`${API_BASE}/${endpoint}/${data.interface}/${data.id}/overrides`, data.overrides);
            toast.success("Overrides saved");
            setEditingOverrides(null);
            fetchData();
        } catch (error) {
            toast.error("Failed to save overrides");
        }
    };

    const splitPatterns = (text) => {
        if (!text) return [];
        return text
            .split('\n')
            .map(v => v.trim())
            .filter(Boolean);
    };

    const joinPatterns = (items) => (items || []).join('\n');

    const openGroupEditor = (group) => {
        setEditingGroup({
            ...group,
            allow_actions: joinPatterns(group.allow_actions),
            deny_actions: joinPatterns(group.deny_actions),
            allow_skills: joinPatterns(group.allow_skills),
            deny_skills: joinPatterns(group.deny_skills)
        });
        setEditGroupActionSearch('');
        setShowAdvancedEdit(false);
    };

    const getActionDecision = (allowText, denyText, actionId) => {
        const deny = splitPatterns(denyText);
        if (deny.includes(actionId)) return 'deny';
        const allow = splitPatterns(allowText);
        if (allow.includes(actionId)) return 'allow';
        return 'default';
    };

    const upsertActionDecision = (allowText, denyText, actionId, decision) => {
        const allowSet = new Set(splitPatterns(allowText));
        const denySet = new Set(splitPatterns(denyText));
        allowSet.delete(actionId);
        denySet.delete(actionId);
        if (decision === 'allow') allowSet.add(actionId);
        if (decision === 'deny') denySet.add(actionId);
        return {
            allow_actions: joinPatterns(Array.from(allowSet)),
            deny_actions: joinPatterns(Array.from(denySet))
        };
    };

    const setNewGroupActionDecision = (actionId, decision) => {
        setNewGroup(prev => ({
            ...prev,
            ...upsertActionDecision(prev.allow_actions, prev.deny_actions, actionId, decision)
        }));
    };

    const setEditingGroupActionDecision = (actionId, decision) => {
        setEditingGroup(prev => {
            if (!prev) return prev;
            return {
                ...prev,
                ...upsertActionDecision(prev.allow_actions, prev.deny_actions, actionId, decision)
            };
        });
    };

    const handleAssignGroup = async (type, entity, groupId) => {
        const endpoint = type === 'user' ? 'users' : 'chats';
        try {
            await api.post(`${API_BASE}/${endpoint}/${entity.interface}/${entity.id}/group`, { group_id: groupId });
            toast.success("Group assignment updated");
            fetchData();
        } catch (error) {
            toast.error("Failed to update group assignment");
        }
    };

    const handleCreateGroup = async () => {
        if (!newGroup.id.trim() || !newGroup.name.trim()) {
            toast.error("Group id and name are required");
            return;
        }
        try {
            await api.post(`${API_BASE}/groups`, {
                id: newGroup.id,
                name: newGroup.name,
                description: newGroup.description,
                allow_actions: splitPatterns(newGroup.allow_actions),
                deny_actions: splitPatterns(newGroup.deny_actions),
                allow_skills: splitPatterns(newGroup.allow_skills),
                deny_skills: splitPatterns(newGroup.deny_skills)
            });
            toast.success("Permission group created");
            setNewGroup({
                id: '',
                name: '',
                description: '',
                allow_actions: '',
                deny_actions: '',
                allow_skills: '',
                deny_skills: ''
            });
            setGroupActionSearch('');
            setShowAdvancedCreate(false);
            fetchData();
        } catch (error) {
            toast.error("Failed to create group");
        }
    };

    const handleSaveGroup = async () => {
        if (!editingGroup) return;
        try {
            await api.patch(`${API_BASE}/groups/${editingGroup.id}`, {
                name: editingGroup.name,
                description: editingGroup.description,
                allow_actions: splitPatterns(editingGroup.allow_actions),
                deny_actions: splitPatterns(editingGroup.deny_actions),
                allow_skills: splitPatterns(editingGroup.allow_skills),
                deny_skills: splitPatterns(editingGroup.deny_skills)
            });
            toast.success("Group updated");
            setEditingGroup(null);
            setShowAdvancedEdit(false);
            fetchData();
        } catch (error) {
            toast.error("Failed to update group");
        }
    };

    const getRiskTagStyle = (risk) => {
        if (risk === 'high') {
            return { color: '#fca5a5', background: 'rgba(239,68,68,0.12)' };
        }
        if (risk === 'medium') {
            return { color: '#fcd34d', background: 'rgba(234,179,8,0.12)' };
        }
        return { color: '#86efac', background: 'rgba(34,197,94,0.12)' };
    };

    const renderActionPicker = ({
        searchValue,
        onSearchChange,
        allowText,
        denyText,
        onDecisionChange
    }) => {
        const query = (searchValue || '').trim().toLowerCase();
        const actions = registry.filter(action => {
            if (!query) return true;
            return (
                action.id.toLowerCase().includes(query) ||
                (action.skill_name || '').toLowerCase().includes(query) ||
                (action.description || '').toLowerCase().includes(query)
            );
        });

        return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div className="input-field" style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '0 12px' }}>
                    <Search size={16} color="var(--text-muted)" />
                    <input
                        value={searchValue}
                        onChange={(e) => onSearchChange(e.target.value)}
                        placeholder="Buscar ação por nome, skill ou descrição..."
                        style={{ width: '100%', border: 'none', outline: 'none', background: 'none', color: 'inherit', padding: '10px 0' }}
                    />
                </div>

                <div className="glass" style={{ borderRadius: '12px', padding: '6px', maxHeight: '320px', overflowY: 'auto' }}>
                    {actions.map(action => {
                        const decision = getActionDecision(allowText, denyText, action.id);
                        const riskStyle = getRiskTagStyle(action.risk_level);

                        return (
                            <div
                                key={`picker-${action.id}`}
                                style={{
                                    display: 'flex',
                                    flexDirection: isMobile ? 'column' : 'row',
                                    alignItems: isMobile ? 'flex-start' : 'center',
                                    justifyContent: 'space-between',
                                    gap: '10px',
                                    padding: '10px',
                                    borderRadius: '10px',
                                    border: '1px solid rgba(255,255,255,0.04)',
                                    background: 'rgba(255,255,255,0.02)',
                                    marginBottom: '6px'
                                }}
                            >
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                                        <code style={{ fontSize: '12px', color: 'var(--text-main)' }}>{action.id}</code>
                                        <span style={{
                                            fontSize: '10px',
                                            textTransform: 'uppercase',
                                            letterSpacing: '0.05em',
                                            borderRadius: '6px',
                                            padding: '2px 6px',
                                            ...riskStyle
                                        }}>
                                            {action.risk_level || 'low'}
                                        </span>
                                    </div>
                                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '3px' }}>
                                        {action.description || 'Sem descrição'}
                                    </div>
                                </div>

                                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                                    <button
                                        className="btn-ghost"
                                        onClick={() => onDecisionChange(action.id, 'default')}
                                        style={{
                                            padding: '6px 10px',
                                            border: '1px solid',
                                            borderColor: decision === 'default' ? 'var(--accent-color)' : 'var(--card-border)',
                                            color: decision === 'default' ? 'var(--accent-color)' : 'var(--text-muted)'
                                        }}
                                    >
                                        Padrão
                                    </button>
                                    <button
                                        className="btn-ghost"
                                        onClick={() => onDecisionChange(action.id, 'allow')}
                                        style={{
                                            padding: '6px 10px',
                                            border: '1px solid',
                                            borderColor: decision === 'allow' ? '#4ade80' : 'var(--card-border)',
                                            color: decision === 'allow' ? '#4ade80' : 'var(--text-muted)'
                                        }}
                                    >
                                        Permitir
                                    </button>
                                    <button
                                        className="btn-ghost"
                                        onClick={() => onDecisionChange(action.id, 'deny')}
                                        style={{
                                            padding: '6px 10px',
                                            border: '1px solid',
                                            borderColor: decision === 'deny' ? '#f87171' : 'var(--card-border)',
                                            color: decision === 'deny' ? '#f87171' : 'var(--text-muted)'
                                        }}
                                    >
                                        Negar
                                    </button>
                                </div>
                            </div>
                        );
                    })}
                    {actions.length === 0 && (
                        <div style={{ padding: '16px', color: 'var(--text-muted)', fontSize: '13px' }}>
                            Nenhuma ação encontrada para esse filtro.
                        </div>
                    )}
                </div>
            </div>
        );
    };

    const allInterfaces = useMemo(() => {
        return Object.keys(interfaces || {}).sort((a, b) => {
            const aOrder = INTERFACE_ORDER[a] ?? 50;
            const bOrder = INTERFACE_ORDER[b] ?? 50;
            if (aOrder !== bOrder) return aOrder - bOrder;
            return a.localeCompare(b);
        });
    }, [interfaces]);

    const visibleInterfaces = useMemo(() => {
        const filtered = allInterfaces.filter(itf => showInternalInterfaces || !INTERFACE_META[itf]?.internal);
        return filtered.length > 0 ? filtered : allInterfaces;
    }, [allInterfaces, showInternalInterfaces]);

    const activeInterfaceMeta = INTERFACE_META[activeInterface] || {
        label: activeInterface || 'Unknown',
        description: 'Interface sem metadados.'
    };

    const handleDeleteGroup = async (group) => {
        if (group.is_system) {
            toast.error("System groups cannot be deleted");
            return;
        }
        if (!window.confirm(`Delete group "${group.name}"?`)) return;
        try {
            await api.delete(`${API_BASE}/groups/${group.id}`);
            toast.success("Group deleted");
            fetchData();
        } catch (error) {
            toast.error("Failed to delete group");
        }
    };

    const filteredUsers = users.filter(u =>
        u.interface === activeInterface &&
        (filterStatus === 'all' || u.status === filterStatus) &&
        (u.display_name?.toLowerCase().includes(searchTerm.toLowerCase()) || u.id.includes(searchTerm))
    );

    const filteredChats = chats.filter(c =>
        c.interface === activeInterface &&
        (filterStatus === 'all' || c.status === filterStatus) &&
        (c.title?.toLowerCase().includes(searchTerm.toLowerCase()) || c.id.includes(searchTerm))
    );

    if (loading) {
        return (
            <div className="flex-center" style={{ height: 'calc(100vh - 100px)' }}>
                <div className="animate-pulse gradient-text" style={{ fontSize: '20px', fontWeight: '600' }}>
                    Loading Security Console...
                </div>
            </div>
        );
    }

    const currentConf = interfaces[activeInterface] || {};
    const groupOptions = groups.map(g => ({ value: g.id, label: `${g.name} (${g.id})` }));
    const newGroupAllowCount = splitPatterns(newGroup.allow_actions).length;
    const newGroupDenyCount = splitPatterns(newGroup.deny_actions).length;

    return (
        <div className="animate-in scroll-container" style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
            <PageHeader
                title="Messaging Access"
                subtitle="Manage authorization and skill overrides across interfaces."
            >
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: isMobile ? 'stretch' : 'flex-end', gap: '8px' }}>
                    <div className="glass" style={{ display: 'flex', padding: 'var(--space-1)', borderRadius: 'var(--radius-sm)', background: 'rgba(255,255,255,0.05)', overflowX: 'auto', maxWidth: isMobile ? '100%' : '460px' }}>
                        {visibleInterfaces.map(itf => (
                            <button
                                key={itf}
                                onClick={() => setActiveInterface(itf)}
                                className={`btn-ghost ${activeInterface === itf ? 'active' : ''}`}
                                style={{
                                    padding: 'var(--space-2) var(--space-4)',
                                    textTransform: 'capitalize',
                                    borderRadius: 'var(--radius-xs)',
                                    fontSize: '0.75rem',
                                    fontWeight: activeInterface === itf ? '800' : '700',
                                    whiteSpace: 'nowrap',
                                    color: activeInterface === itf ? 'var(--accent-color)' : 'var(--text-muted)'
                                }}
                            >
                                {INTERFACE_META[itf]?.label || itf}
                            </button>
                        ))}
                    </div>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--text-muted)' }}>
                        <input
                            type="checkbox"
                            checked={showInternalInterfaces}
                            onChange={(e) => setShowInternalInterfaces(e.target.checked)}
                        />
                        Mostrar interfaces internas/legadas
                    </label>
                </div>
            </PageHeader>

            <nav style={{ display: 'flex', gap: isMobile ? 'var(--space-4)' : 'var(--space-8)', padding: `0 ${isMobile ? 'var(--space-4)' : 'var(--space-8)'}`, marginBottom: '0', borderBottom: '1px solid var(--card-border)', overflowX: isMobile ? 'auto' : 'visible' }}>
                {['config', 'groups', 'users', 'chats'].map(tab => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab)}
                        style={{
                            padding: 'var(--space-4) var(--space-1)',
                            background: 'none',
                            border: 'none',
                            color: activeTab === tab ? 'var(--accent-color)' : 'var(--text-muted)',
                            fontWeight: activeTab === tab ? '800' : '600',
                            borderBottom: activeTab === tab ? '2px solid var(--accent-color)' : '2px solid transparent',
                            cursor: 'pointer',
                            textTransform: 'uppercase',
                            letterSpacing: '0.05em',
                            fontSize: '0.75rem',
                            transition: 'var(--transition)',
                            whiteSpace: 'nowrap'
                        }}
                    >
                        {tab}
                    </button>
                ))}
            </nav>

            <div className="glass" style={{ margin: `0 ${isMobile ? 'var(--space-4)' : 'var(--space-6)'}`, padding: '12px 14px', borderRadius: '12px', display: 'flex', flexDirection: isMobile ? 'column' : 'row', justifyContent: 'space-between', gap: '6px' }}>
                <div style={{ fontSize: '13px' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Canal ativo para alterações:</span>{' '}
                    <strong style={{ color: 'var(--accent-color)' }}>{activeInterfaceMeta.label}</strong>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    {activeInterfaceMeta.description}
                </div>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '0 var(--space-6) 100px var(--space-6)' }}>
                {activeTab === 'config' && (
                    <div className={isMobile ? "flex flex-col" : "grid-2"} style={{ gap: '24px' }}>
                        <section className="glass p-6 rounded-2xl">
                            <h3 style={{ fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '20px' }}>
                                <Settings size={20} /> Access Strategy
                            </h3>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                                <div className="space-y-2">
                                    <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)' }}>Private Messages (DMs)</label>
                                    <select
                                        value={currentConf.dm_mode}
                                        onChange={(e) => handleInterfaceUpdate({ dm_mode: e.target.value })}
                                        className="input-field"
                                    >
                                        <option value="approved_only">Approved Only (Strict)</option>
                                        <option value="auto_approve">Auto Approve (Trust first)</option>
                                        <option value="anyone">Anyone (Low-Risk Only)</option>
                                    </select>
                                </div>
                                <div className="space-y-2">
                                    <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)' }}>Groups / Channels</label>
                                    <select
                                        value={currentConf.group_mode}
                                        onChange={(e) => handleInterfaceUpdate({ group_mode: e.target.value })}
                                        className="input-field"
                                    >
                                        <option value="approved_only">Approved Only</option>
                                        <option value="auto_approve">Auto Approve</option>
                                        <option value="anyone">Anyone (Low-Risk Only)</option>
                                    </select>
                                </div>
                                <div className="space-y-2">
                                    <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)' }}>Default User Group</label>
                                    <select
                                        value={currentConf.default_user_group || ''}
                                        onChange={(e) => handleInterfaceUpdate({ default_user_group: e.target.value })}
                                        className="input-field"
                                    >
                                        {groupOptions.map(g => (
                                            <option key={`dug-${g.value}`} value={g.value}>{g.label}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="space-y-2">
                                    <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)' }}>Auto-Approve User Group</label>
                                    <select
                                        value={currentConf.auto_approve_user_group || ''}
                                        onChange={(e) => handleInterfaceUpdate({ auto_approve_user_group: e.target.value })}
                                        className="input-field"
                                    >
                                        {groupOptions.map(g => (
                                            <option key={`aug-${g.value}`} value={g.value}>{g.label}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="space-y-2">
                                    <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)' }}>Default Chat Group</label>
                                    <select
                                        value={currentConf.default_chat_group || ''}
                                        onChange={(e) => handleInterfaceUpdate({ default_chat_group: e.target.value })}
                                        className="input-field"
                                    >
                                        {groupOptions.map(g => (
                                            <option key={`dcg-${g.value}`} value={g.value}>{g.label}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="space-y-2">
                                    <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)' }}>Auto-Approve Chat Group</label>
                                    <select
                                        value={currentConf.auto_approve_chat_group || ''}
                                        onChange={(e) => handleInterfaceUpdate({ auto_approve_chat_group: e.target.value })}
                                        className="input-field"
                                    >
                                        {groupOptions.map(g => (
                                            <option key={`acg-${g.value}`} value={g.value}>{g.label}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                        </section>

                        <section className="glass p-6 rounded-2xl">
                            <h3 style={{ fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '20px' }}>
                                <Activity size={20} /> Rate Limits
                            </h3>
                            <div className="space-y-6">
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                    <span style={{ fontSize: '14px' }}>Enable Rate Limiting</span>
                                    <button
                                        onClick={() => handleInterfaceUpdate({ rate_limit_enabled: !currentConf.rate_limit_enabled })}
                                        style={{ padding: 0, width: '48px', height: '24px', borderRadius: '12px', background: currentConf.rate_limit_enabled ? 'var(--accent-color)' : '#334155', position: 'relative' }}
                                    >
                                        <div style={{ position: 'absolute', top: '2px', left: currentConf.rate_limit_enabled ? '26px' : '2px', width: '20px', height: '20px', borderRadius: '50%', background: '#fff', transition: 'all 0.2s' }} />
                                    </button>
                                </div>
                                <div className="space-y-2">
                                    <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)' }}>Messages per Minute (Burst)</label>
                                    <input
                                        type="number"
                                        value={currentConf.max_msgs_per_min}
                                        onChange={(e) => handleInterfaceUpdate({ max_msgs_per_min: parseInt(e.target.value) })}
                                        className="input-field"
                                        style={{ textAlign: 'left' }}
                                    />
                                </div>
                            </div>
                        </section>
                    </div>
                )}

                {activeTab === 'groups' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                        <section className="glass p-6 rounded-2xl">
                            <h3 style={{ fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '20px' }}>
                                <Plus size={20} /> Create Permission Group
                            </h3>
                            <div className="grid-2" style={{ gap: '12px' }}>
                                <input
                                    className="input-field"
                                    placeholder="group_id (ex: support_team)"
                                    value={newGroup.id}
                                    onChange={(e) => setNewGroup(prev => ({ ...prev, id: e.target.value }))}
                                />
                                <input
                                    className="input-field"
                                    placeholder="Group Name"
                                    value={newGroup.name}
                                    onChange={(e) => setNewGroup(prev => ({ ...prev, name: e.target.value }))}
                                />
                                <input
                                    className="input-field"
                                    placeholder="Description"
                                    value={newGroup.description}
                                    onChange={(e) => setNewGroup(prev => ({ ...prev, description: e.target.value }))}
                                    style={{ gridColumn: isMobile ? 'auto' : '1 / -1' }}
                                />
                                <div style={{ gridColumn: isMobile ? 'auto' : '1 / -1', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                                    <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                                        Fluxo simples: escolha as ações e marque como <strong>Permitir</strong> ou <strong>Negar</strong>.
                                    </div>
                                    <button
                                        className="btn-ghost"
                                        onClick={() => setShowAdvancedCreate(prev => !prev)}
                                        style={{ border: '1px solid var(--card-border)', padding: '6px 10px' }}
                                    >
                                        {showAdvancedCreate ? 'Ocultar modo avançado' : 'Modo avançado (patterns)'}
                                    </button>
                                </div>
                                <div style={{ gridColumn: isMobile ? 'auto' : '1 / -1', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                                    <span style={{ fontSize: '12px', color: '#4ade80', background: 'rgba(34,197,94,0.1)', borderRadius: '8px', padding: '4px 8px' }}>
                                        Permitidas: {newGroupAllowCount}
                                    </span>
                                    <span style={{ fontSize: '12px', color: '#f87171', background: 'rgba(239,68,68,0.1)', borderRadius: '8px', padding: '4px 8px' }}>
                                        Negadas: {newGroupDenyCount}
                                    </span>
                                </div>
                                <div style={{ gridColumn: isMobile ? 'auto' : '1 / -1' }}>
                                    {renderActionPicker({
                                        searchValue: groupActionSearch,
                                        onSearchChange: setGroupActionSearch,
                                        allowText: newGroup.allow_actions,
                                        denyText: newGroup.deny_actions,
                                        onDecisionChange: setNewGroupActionDecision
                                    })}
                                </div>
                                {showAdvancedCreate && (
                                    <>
                                        <textarea
                                            className="input-field"
                                            placeholder="allow_actions (um pattern por linha, ex: web.*)"
                                            value={newGroup.allow_actions}
                                            onChange={(e) => setNewGroup(prev => ({ ...prev, allow_actions: e.target.value }))}
                                            style={{ minHeight: '100px', resize: 'vertical' }}
                                        />
                                        <textarea
                                            className="input-field"
                                            placeholder="deny_actions (um pattern por linha, ex: shell.*)"
                                            value={newGroup.deny_actions}
                                            onChange={(e) => setNewGroup(prev => ({ ...prev, deny_actions: e.target.value }))}
                                            style={{ minHeight: '100px', resize: 'vertical' }}
                                        />
                                        <textarea
                                            className="input-field"
                                            placeholder="allow_skills (opcional avançado)"
                                            value={newGroup.allow_skills}
                                            onChange={(e) => setNewGroup(prev => ({ ...prev, allow_skills: e.target.value }))}
                                            style={{ minHeight: '100px', resize: 'vertical' }}
                                        />
                                        <textarea
                                            className="input-field"
                                            placeholder="deny_skills (opcional avançado)"
                                            value={newGroup.deny_skills}
                                            onChange={(e) => setNewGroup(prev => ({ ...prev, deny_skills: e.target.value }))}
                                            style={{ minHeight: '100px', resize: 'vertical' }}
                                        />
                                    </>
                                )}
                            </div>
                            <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'flex-end' }}>
                                <button className="btn-primary px-6" onClick={handleCreateGroup}>Create Group</button>
                            </div>
                        </section>

                        <section className="glass p-6 rounded-2xl">
                            <h3 style={{ fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                                <Layers size={20} /> Existing Groups
                            </h3>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                {groups.map(group => (
                                    <div
                                        key={group.id}
                                        style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                            padding: '12px',
                                            borderRadius: '12px',
                                            background: 'rgba(255,255,255,0.03)',
                                            border: '1px solid var(--card-border)'
                                        }}
                                    >
                                        <div>
                                            <div style={{ fontWeight: 700 }}>{group.name} <code style={{ opacity: 0.8 }}>{group.id}</code></div>
                                            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                                {group.description || 'No description'}
                                            </div>
                                        </div>
                                        <div style={{ display: 'flex', gap: '8px' }}>
                                            <button className="btn-ghost p-2" onClick={() => openGroupEditor(group)}>
                                                <Edit size={16} />
                                            </button>
                                            <button
                                                className="btn-ghost p-2"
                                                onClick={() => handleDeleteGroup(group)}
                                                style={{ color: group.is_system ? 'var(--text-muted)' : '#f87171' }}
                                                disabled={group.is_system}
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        </div>
                                    </div>
                                ))}
                                {groups.length === 0 && (
                                    <div style={{ color: 'var(--text-muted)', padding: '10px 0' }}>
                                        No permission groups available.
                                    </div>
                                )}
                            </div>
                        </section>
                    </div>
                )}

                {(activeTab === 'users' || activeTab === 'chats') && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                        <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: '12px' }}>
                            <div className="input-field" style={{ flex: 1, display: 'flex', alignItems: 'center', padding: '0 16px' }}>
                                <Search size={18} color="var(--text-muted)" />
                                <input
                                    placeholder={`Search ${activeTab}...`}
                                    value={searchTerm}
                                    onChange={(e) => setSearchTerm(e.target.value)}
                                    style={{ background: 'none', border: 'none', padding: '12px', color: 'inherit', width: '100%', outline: 'none' }}
                                />
                            </div>
                            <select
                                value={filterStatus}
                                onChange={(e) => setFilterStatus(e.target.value)}
                                className="input-field"
                                style={{ width: isMobile ? '100%' : '160px' }}
                            >
                                <option value="all">All Status</option>
                                <option value="pending">Pending</option>
                                <option value="approved">Approved</option>
                                <option value="blocked">Blocked</option>
                            </select>
                        </div>

                        <div className={`${!isMobile ? 'glass overflow-hidden rounded-2xl' : ''}`}>
                            {!isMobile ? (
                                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                                    <thead style={{ background: 'rgba(255,255,255,0.03)', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                        <tr>
                                            <th style={{ padding: '16px' }}>Identity</th>
                                            <th style={{ padding: '16px' }}>ID</th>
                                            <th style={{ padding: '16px' }}>Group</th>
                                            <th style={{ padding: '16px' }}>Status</th>
                                            <th style={{ padding: '16px' }}>Seen</th>
                                            <th style={{ padding: '16px', textAlign: 'right' }}>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(activeTab === 'users' ? filteredUsers : filteredChats).map(item => (
                                            <tr key={item.id} className="table-row-hover" style={{ borderTop: '1px solid var(--card-border)', transition: 'var(--transition-base)' }}>
                                                <td style={{ padding: 'var(--space-4) var(--space-4)' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                                                        <div style={{ padding: 'var(--space-2)', borderRadius: 'var(--radius-sm)', background: 'rgba(255,255,255,0.05)' }}>
                                                            {activeTab === 'users' ? <User size={16} /> : <MessageSquare size={16} />}
                                                        </div>
                                                        <span style={{ fontWeight: '700', fontSize: '0.875rem' }}>{activeTab === 'users' ? item.display_name : item.title}</span>
                                                    </div>
                                                </td>
                                                <td style={{ padding: 'var(--space-4)' }}>
                                                    <code style={{ fontSize: '0.75rem', color: 'var(--text-muted)', background: 'rgba(0,0,0,0.2)', padding: '2px 6px', borderRadius: '4px' }}>{item.id}</code>
                                                </td>
                                                <td style={{ padding: 'var(--space-4)' }}>
                                                    <select
                                                        value={item.group_id || ''}
                                                        onChange={(e) => handleAssignGroup(activeTab.slice(0, -1), item, e.target.value)}
                                                        className="input-field"
                                                        style={{ minWidth: '170px', padding: '8px 10px', fontSize: '12px' }}
                                                    >
                                                        {groupOptions.map(g => (
                                                            <option key={`row-${item.id}-${g.value}`} value={g.value}>{g.label}</option>
                                                        ))}
                                                    </select>
                                                </td>
                                                <td style={{ padding: 'var(--space-4)' }}>
                                                    <span
                                                        style={{
                                                            padding: '4px 8px',
                                                            borderRadius: '6px',
                                                            fontSize: '11px',
                                                            fontWeight: 'bold',
                                                            textTransform: 'uppercase',
                                                            background: item.status === 'approved' ? 'rgba(34, 197, 94, 0.1)' : item.status === 'pending' ? 'rgba(234, 179, 8, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                                                            color: item.status === 'approved' ? '#4ade80' : item.status === 'pending' ? '#facc15' : '#f87171'
                                                        }}
                                                    >
                                                        {item.status}
                                                    </span>
                                                </td>
                                                <td style={{ padding: 'var(--space-4)', fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
                                                    {new Date(item.last_seen_at * 1000).toLocaleDateString()}
                                                </td>
                                                <td style={{ padding: 'var(--space-4)', textAlign: 'right' }}>
                                                    <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                                        {item.status !== 'approved' && (
                                                            <button
                                                                onClick={() => handleStatusUpdate(activeTab.slice(0, -1), item.interface, item.id, 'approved')}
                                                                className="btn-ghost p-2" title="Approve" style={{ color: '#4ade80' }}
                                                            >
                                                                <CheckCircle size={18} />
                                                            </button>
                                                        )}
                                                        {item.status !== 'blocked' && (
                                                            <button
                                                                onClick={() => handleStatusUpdate(activeTab.slice(0, -1), item.interface, item.id, 'blocked')}
                                                                className="btn-ghost p-2" title="Block" style={{ color: '#f87171' }}
                                                            >
                                                                <Slash size={18} />
                                                            </button>
                                                        )}
                                                        <button
                                                            onClick={() => setEditingOverrides({ type: activeTab.slice(0, -1), data: JSON.parse(JSON.stringify(item)) })}
                                                            className="btn-ghost p-2" title="Edit Overrides"
                                                        >
                                                            <Edit size={18} />
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            ) : (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                    {(activeTab === 'users' ? filteredUsers : filteredChats).map(item => (
                                        <div key={item.id} className="glass p-4 rounded-xl flex flex-col gap-4">
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                                    <div style={{ padding: '8px', borderRadius: '8px', background: 'rgba(255,255,255,0.05)' }}>
                                                        {activeTab === 'users' ? <User size={20} /> : <MessageSquare size={20} />}
                                                    </div>
                                                    <div>
                                                        <div style={{ fontWeight: '700', fontSize: '14px' }}>{activeTab === 'users' ? item.display_name : item.title}</div>
                                                        <code style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{item.id}</code>
                                                    </div>
                                                </div>
                                                <span
                                                    style={{
                                                        padding: '4px 8px',
                                                        borderRadius: '6px',
                                                        fontSize: '10px',
                                                        fontWeight: 'bold',
                                                        textTransform: 'uppercase',
                                                        background: item.status === 'approved' ? 'rgba(34, 197, 94, 0.1)' : item.status === 'pending' ? 'rgba(234, 179, 8, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                                                        color: item.status === 'approved' ? '#4ade80' : item.status === 'pending' ? '#facc15' : '#f87171'
                                                    }}
                                                >
                                                    {item.status}
                                                </span>
                                            </div>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                                    Last seen: {new Date(item.last_seen_at * 1000).toLocaleDateString()}
                                                </span>
                                                <div style={{ display: 'flex', gap: '4px' }}>
                                                    {item.status !== 'approved' && (
                                                        <button
                                                            onClick={() => handleStatusUpdate(activeTab.slice(0, -1), item.interface, item.id, 'approved')}
                                                            className="btn-ghost p-2" style={{ color: '#4ade80' }}
                                                        >
                                                            <CheckCircle size={20} />
                                                        </button>
                                                    )}
                                                    {item.status !== 'blocked' && (
                                                        <button
                                                            onClick={() => handleStatusUpdate(activeTab.slice(0, -1), item.interface, item.id, 'blocked')}
                                                            className="btn-ghost p-2" style={{ color: '#f87171' }}
                                                        >
                                                            <Slash size={20} />
                                                        </button>
                                                    )}
                                                    <button
                                                        onClick={() => setEditingOverrides({ type: activeTab.slice(0, -1), data: JSON.parse(JSON.stringify(item)) })}
                                                        className="btn-ghost p-2"
                                                    >
                                                        <Edit size={20} />
                                                    </button>
                                                </div>
                                            </div>
                                            <div>
                                                <label style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>
                                                    Permission Group
                                                </label>
                                                <select
                                                    value={item.group_id || ''}
                                                    onChange={(e) => handleAssignGroup(activeTab.slice(0, -1), item, e.target.value)}
                                                    className="input-field"
                                                    style={{ width: '100%', padding: '8px 10px', fontSize: '12px' }}
                                                >
                                                    {groupOptions.map(g => (
                                                        <option key={`mrow-${item.id}-${g.value}`} value={g.value}>{g.label}</option>
                                                    ))}
                                                </select>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                            {(activeTab === 'users' ? filteredUsers : filteredChats).length === 0 && (
                                <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
                                    No {activeTab} found for this interface.
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Overrides Modal */}
            {editingOverrides && (
                <div
                    style={{
                        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                        background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center',
                        justifyContent: 'center', zIndex: 1000, padding: '20px'
                    }}
                >
                    <div className="glass animate-pop" style={{ width: '100%', maxWidth: '800px', maxHeight: '90vh', overflowY: 'auto', borderRadius: '24px', position: 'relative' }}>
                        <div style={{ padding: '24px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ fontSize: '20px', fontWeight: '700' }}>
                                Skill Overrides: <span style={{ color: 'var(--accent-color)' }}>{editingOverrides.data.display_name || editingOverrides.data.title}</span>
                            </h3>
                            <button onClick={() => setEditingOverrides(null)} className="btn-ghost p-2">
                                <XCircle size={24} />
                            </button>
                        </div>

                        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '32px' }}>
                            <section>
                                <h4 style={{ fontSize: '14px', color: 'var(--text-muted)', marginBottom: '16px', textTransform: 'uppercase' }}>Allowed & Denied Skills</h4>
                                <div className="grid-1" style={{ gap: '12px' }}>
                                    {registry.map(action => {
                                        const isAllowed = editingOverrides.data.overrides.allow_skills.includes(action.id);
                                        const isDenied = editingOverrides.data.overrides.deny_skills.includes(action.id);

                                        return (
                                            <div key={action.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px', borderRadius: '12px', background: 'rgba(255,255,255,0.03)' }}>
                                                <div>
                                                    <div style={{ fontWeight: '600', fontSize: '14px' }}>{action.id}</div>
                                                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{action.description}</div>
                                                </div>
                                                <div style={{ display: 'flex', gap: '8px' }}>
                                                    <button
                                                        onClick={() => {
                                                            const o = editingOverrides.data.overrides;
                                                            if (isAllowed) o.allow_skills = o.allow_skills.filter(s => s !== action.id);
                                                            else {
                                                                o.allow_skills.push(action.id);
                                                                o.deny_skills = o.deny_skills.filter(s => s !== action.id);
                                                            }
                                                            setEditingOverrides({ ...editingOverrides });
                                                        }}
                                                        className={`btn-ghost px-3 py-1 text-xs`}
                                                        style={{
                                                            border: '1px solid',
                                                            borderColor: isAllowed ? '#4ade80' : 'var(--border-color)',
                                                            color: isAllowed ? '#4ade80' : '#fff'
                                                        }}
                                                    >
                                                        {isAllowed ? 'Explicitly Allowed' : 'Allow'}
                                                    </button>
                                                    <button
                                                        onClick={() => {
                                                            const o = editingOverrides.data.overrides;
                                                            if (isDenied) o.deny_skills = o.deny_skills.filter(s => s !== action.id);
                                                            else {
                                                                o.deny_skills.push(action.id);
                                                                o.allow_skills = o.allow_skills.filter(s => s !== action.id);
                                                            }
                                                            setEditingOverrides({ ...editingOverrides });
                                                        }}
                                                        className={`btn-ghost px-3 py-1 text-xs`}
                                                        style={{
                                                            border: '1px solid',
                                                            borderColor: isDenied ? '#f87171' : 'var(--border-color)',
                                                            color: isDenied ? '#f87171' : '#fff'
                                                        }}
                                                    >
                                                        {isDenied ? 'Explicitly Denied' : 'Deny'}
                                                    </button>
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            </section>
                        </div>

                        <div style={{ padding: '24px', background: 'rgba(255,255,255,0.03)', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                            <button onClick={() => setEditingOverrides(null)} className="btn-ghost px-6">Cancel</button>
                            <button onClick={handleSaveOverrides} className="btn-primary px-8">Save Changes</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Group Editor Modal */}
            {editingGroup && (
                <div
                    style={{
                        position: 'fixed',
                        top: 0,
                        left: 0,
                        right: 0,
                        bottom: 0,
                        background: 'rgba(0,0,0,0.8)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        zIndex: 1000,
                        padding: '20px'
                    }}
                >
                    <div className="glass animate-pop" style={{ width: '100%', maxWidth: '900px', maxHeight: '90vh', overflowY: 'auto', borderRadius: '24px' }}>
                        <div style={{ padding: '24px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ fontSize: '20px', fontWeight: '700' }}>
                                Edit Group: <span style={{ color: 'var(--accent-color)' }}>{editingGroup.name}</span>
                            </h3>
                            <button onClick={() => { setEditingGroup(null); setShowAdvancedEdit(false); }} className="btn-ghost p-2">
                                <XCircle size={24} />
                            </button>
                        </div>

                        <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                            <input
                                className="input-field"
                                value={editingGroup.name}
                                onChange={(e) => setEditingGroup(prev => ({ ...prev, name: e.target.value }))}
                                placeholder="Group Name"
                            />
                            <input
                                className="input-field"
                                value={editingGroup.description || ''}
                                onChange={(e) => setEditingGroup(prev => ({ ...prev, description: e.target.value }))}
                                placeholder="Description"
                            />
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                                <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                                    Permitidas: {splitPatterns(editingGroup.allow_actions).length} | Negadas: {splitPatterns(editingGroup.deny_actions).length}
                                </div>
                                <button
                                    className="btn-ghost"
                                    onClick={() => setShowAdvancedEdit(prev => !prev)}
                                    style={{ border: '1px solid var(--card-border)', padding: '6px 10px' }}
                                >
                                    {showAdvancedEdit ? 'Ocultar modo avançado' : 'Modo avançado (patterns)'}
                                </button>
                            </div>
                            {renderActionPicker({
                                searchValue: editGroupActionSearch,
                                onSearchChange: setEditGroupActionSearch,
                                allowText: editingGroup.allow_actions,
                                denyText: editingGroup.deny_actions,
                                onDecisionChange: setEditingGroupActionDecision
                            })}
                            {showAdvancedEdit && (
                                <div className="grid-2" style={{ gap: '12px' }}>
                                    <textarea
                                        className="input-field"
                                        value={editingGroup.allow_actions}
                                        onChange={(e) => setEditingGroup(prev => ({ ...prev, allow_actions: e.target.value }))}
                                        placeholder="allow_actions (um pattern por linha)"
                                        style={{ minHeight: '120px', resize: 'vertical' }}
                                    />
                                    <textarea
                                        className="input-field"
                                        value={editingGroup.deny_actions}
                                        onChange={(e) => setEditingGroup(prev => ({ ...prev, deny_actions: e.target.value }))}
                                        placeholder="deny_actions (um pattern por linha)"
                                        style={{ minHeight: '120px', resize: 'vertical' }}
                                    />
                                    <textarea
                                        className="input-field"
                                        value={editingGroup.allow_skills}
                                        onChange={(e) => setEditingGroup(prev => ({ ...prev, allow_skills: e.target.value }))}
                                        placeholder="allow_skills (opcional avançado)"
                                        style={{ minHeight: '120px', resize: 'vertical' }}
                                    />
                                    <textarea
                                        className="input-field"
                                        value={editingGroup.deny_skills}
                                        onChange={(e) => setEditingGroup(prev => ({ ...prev, deny_skills: e.target.value }))}
                                        placeholder="deny_skills (opcional avançado)"
                                        style={{ minHeight: '120px', resize: 'vertical' }}
                                    />
                                </div>
                            )}
                        </div>

                        <div style={{ padding: '24px', background: 'rgba(255,255,255,0.03)', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                            <button onClick={() => { setEditingGroup(null); setShowAdvancedEdit(false); }} className="btn-ghost px-6">Cancel</button>
                            <button onClick={handleSaveGroup} className="btn-primary px-8">Save Group</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default MessagingAccess;
