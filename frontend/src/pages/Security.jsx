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
    Layers,
    ShieldAlert,
    X,
    Send,
    Globe,
    Terminal,
    Zap,
    Eye
} from 'lucide-react';
import { api } from '../hooks/api';
import { toast } from 'react-hot-toast';
import ConfirmDialog from '../components/ConfirmDialog';
import CapabilityIcon from '../components/CapabilityIcon';

const API_BASE = '/messaging_access';
const INTERFACE_META = {
    telegram: {
        label: 'Telegram',
        description: 'Official Telegram bot channel.',
        internal: false
    },
    web: {
        label: 'Web',
        description: 'Authenticated web panel channel.',
        internal: false
    },
    cli: {
        label: 'CLI',
        description: 'Local terminal/bridge channel for operations and testing.',
        internal: false
    },
    validator: {
        label: 'Validator (Legado)',
        description: 'Legacy alias, redirected to CLI.',
        internal: true
    },
    terminal_bridge: {
        label: 'Terminal Bridge (Legado)',
        description: 'Legacy alias, redirected to CLI.',
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

const WORKER_SCOPE_OPTIONS = [
    { value: 'self_session', label: 'Only Same Session' },
    { value: 'owner_session', label: 'Any Owner Session' },
    { value: 'owner_identity', label: 'Same Identity' },
    { value: 'global', label: 'Global' }
];

const Security = () => {
    const [interfaces, setInterfaces] = useState({});
    const [activeInterface, setActiveInterface] = useState('telegram');
    const [users, setUsers] = useState([]);
    const [chats, setChats] = useState([]);
    const [registry, setRegistry] = useState([]);
    const [groups, setGroups] = useState([]);
    const [approvalAudit, setApprovalAudit] = useState([]);
    const [approvalAuditFilter, setApprovalAuditFilter] = useState('all');
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [filterStatus, setFilterStatus] = useState('all');
    const [activeTab, setActiveTab] = useState('channels');
    const [assignmentsView, setAssignmentsView] = useState('users');
    const [editingOverrides, setEditingOverrides] = useState(null); // {type: 'user'|'chat', data: entity}
    const [editingGroup, setEditingGroup] = useState(null);
    const [deletingGroup, setDeletingGroup] = useState(null);
    const [newGroup, setNewGroup] = useState({
        id: '',
        name: '',
        description: '',
        allow_actions: '',
        deny_actions: '',
        allow_capabilities: '',
        deny_capabilities: '',
        worker_view_scope: 'owner_identity',
        worker_control_scope: 'owner_identity'
    });
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);
    const [showInternalInterfaces, setShowInternalInterfaces] = useState(false);
    const [groupActionSearch, setGroupActionSearch] = useState('');
    const [editGroupActionSearch, setEditGroupActionSearch] = useState('');
    const [showAdvancedCreate, setShowAdvancedCreate] = useState(false);
    const [showAdvancedEdit, setShowAdvancedEdit] = useState(false);
    const [showCreateProfileModal, setShowCreateProfileModal] = useState(false);
    const [aclProfileSearch, setAclProfileSearch] = useState('');
    const [profileEditorTab, setProfileEditorTab] = useState('profile_details');

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
            const [intRes, userRes, chatRes, regRes, groupRes, auditRes] = await Promise.all([
                api.get(`${API_BASE}/interfaces`),
                api.get(`${API_BASE}/users`),
                api.get(`${API_BASE}/chats`),
                api.get('/capabilities/registry'),
                api.get(`${API_BASE}/groups`),
                api.get(`${API_BASE}/approval-audit?limit=150`)
            ]);
            setInterfaces(intRes);
            setUsers(userRes);
            setChats(chatRes);
            setRegistry(regRes);
            setGroups(Array.isArray(groupRes) ? groupRes : []);
            setApprovalAudit(Array.isArray(auditRes?.items) ? auditRes.items : []);
        } catch (error) {
            try {
                const groupsRes = await api.get(`${API_BASE}/groups`);
                setGroups(groupsRes);
            } catch (_) {
                setGroups([]);
            }
            setApprovalAudit([]);
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

    const handleCopyApprovalToInterface = async (targetInterface, approvalPolicy) => {
        const target = String(targetInterface || '').trim().toLowerCase();
        if (!target || target === String(activeInterface || '').toLowerCase()) {
            toast.error("Select a different interface to copy");
            return;
        }
        try {
            const res = await api.patch(`${API_BASE}/interfaces/${target}`, { approval_decisions: approvalPolicy });
            setInterfaces(prev => ({ ...prev, [target]: res }));
            const fromLabel = INTERFACE_META[activeInterface]?.label || activeInterface;
            const toLabel = INTERFACE_META[target]?.label || target;
            toast.success(`Permission policy copied: ${fromLabel} -> ${toLabel}`);
        } catch (error) {
            toast.error("Failed to copy permission policy");
        }
    };

    const handleCopyApprovalToAll = async (approvalPolicy) => {
        const targets = visibleInterfaces.filter(
            itf => String(itf || '').toLowerCase() !== String(activeInterface || '').toLowerCase()
        );
        if (targets.length === 0) {
            toast.error("No target interfaces available");
            return;
        }
        const fromLabel = INTERFACE_META[activeInterface]?.label || activeInterface;
        const confirmed = window.confirm(
            `Copy permission policy from ${fromLabel} to ${targets.length} interface(s)?`
        );
        if (!confirmed) return;
        try {
            const results = await Promise.all(
                targets.map(itf => api.patch(`${API_BASE}/interfaces/${itf}`, { approval_decisions: approvalPolicy }))
            );
            setInterfaces(prev => {
                const next = { ...prev };
                targets.forEach((itf, idx) => {
                    next[itf] = results[idx];
                });
                return next;
            });
            toast.success(`Permission policy copied to ${targets.length} interface(s)`);
        } catch (error) {
            toast.error("Failed to copy permission policy to all interfaces");
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
            allow_capabilities: joinPatterns(group.allow_capabilities),
            deny_capabilities: joinPatterns(group.deny_capabilities),
            worker_view_scope: group.worker_view_scope || 'owner_identity',
            worker_control_scope: group.worker_control_scope || 'owner_identity'
        });
        setEditGroupActionSearch('');
        setShowAdvancedEdit(false);
        setProfileEditorTab('profile_details');
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
            toast.success("ACL profile assignment updated");
            fetchData();
        } catch (error) {
            toast.error("Failed to update ACL profile assignment");
        }
    };

    const handleCreateGroup = async () => {
        if (!newGroup.id.trim() || !newGroup.name.trim()) {
            toast.error("ACL profile id and name are required");
            return;
        }
        try {
            await api.post(`${API_BASE}/groups`, {
                id: newGroup.id,
                name: newGroup.name,
                description: newGroup.description,
                allow_actions: splitPatterns(newGroup.allow_actions),
                deny_actions: splitPatterns(newGroup.deny_actions),
                allow_capabilities: splitPatterns(newGroup.allow_capabilities),
                deny_capabilities: splitPatterns(newGroup.deny_capabilities),
                worker_view_scope: newGroup.worker_view_scope,
                worker_control_scope: newGroup.worker_control_scope
            });
            toast.success("ACL profile created");
            setNewGroup({
                id: '',
                name: '',
                description: '',
                allow_actions: '',
                deny_actions: '',
                allow_capabilities: '',
                deny_capabilities: '',
                worker_view_scope: 'owner_identity',
                worker_control_scope: 'owner_identity'
            });
            setGroupActionSearch('');
            setShowAdvancedCreate(false);
            setShowCreateProfileModal(false);
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
                allow_capabilities: splitPatterns(editingGroup.allow_capabilities),
                deny_capabilities: splitPatterns(editingGroup.deny_capabilities),
                worker_view_scope: editingGroup.worker_view_scope,
                worker_control_scope: editingGroup.worker_control_scope
            });
            toast.success("ACL profile updated");
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
                (action.capability_name || '').toLowerCase().includes(query) ||
                (action.description || '').toLowerCase().includes(query)
            );
        });

        return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ position: 'relative' }}>
                    <Search size={16} style={{ position: 'absolute', left: '16px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                    <input
                        value={searchValue}
                        onChange={(e) => onSearchChange(e.target.value)}
                        placeholder="Search kernel actions..."
                        className="input-field"
                        style={{ width: '100%', paddingLeft: '44px', borderRadius: '16px', background: 'rgba(0,0,0,0.2)' }}
                    />
                </div>

                <div className="custom-scrollbar" style={{ borderRadius: '16px', maxHeight: '400px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {actions.map(action => {
                        const decision = getActionDecision(allowText, denyText, action.id);
                        const riskStyle = getRiskTagStyle(action.risk_level);

                        return (
                            <div
                                key={`picker-${action.id}`}
                                className="glass"
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    padding: '12px 16px',
                                    borderRadius: '14px',
                                    background: 'rgba(255,255,255,0.01)',
                                    border: '1px solid var(--card-border)',
                                    gap: '16px'
                                }}
                            >
                                <div style={{ minWidth: 0, flex: 1 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                                        <CapabilityIcon
                                            variant="inline"
                                            capabilityId={action.capability_id}
                                            assets={action.assets}
                                        />
                                        <span style={{ fontSize: '13px', fontWeight: '800' }}>{action.id}</span>
                                        <span style={{
                                            fontSize: '9px',
                                            fontWeight: '900',
                                            padding: '2px 6px',
                                            borderRadius: '4px',
                                            textTransform: 'uppercase',
                                            ...riskStyle
                                        }}>
                                            {action.risk_level || 'low'}
                                        </span>
                                    </div>
                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                        {action.description || 'No description provided.'}
                                    </div>
                                </div>

                                <div style={{ display: 'flex', gap: '2px', background: 'rgba(0,0,0,0.2)', padding: '4px', borderRadius: '12px' }}>
                                    {['allow', 'default', 'deny'].map(mode => (
                                        <button
                                            key={mode}
                                            onClick={() => onDecisionChange(action.id, mode)}
                                            style={{
                                                padding: '6px 12px',
                                                fontSize: '10px',
                                                fontWeight: '800',
                                                borderRadius: '8px',
                                                transition: 'var(--transition-fast)',
                                                background: decision === mode
                                                    ? (mode === 'allow' ? soberBg.success : mode === 'deny' ? soberBg.danger : soberBg.neutral)
                                                    : 'transparent',
                                                color: decision === mode ? 'var(--text-main)' : 'var(--text-muted)',
                                                border: 'none'
                                            }}
                                        >
                                            {mode.toUpperCase()}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        );
                    })}
                    {actions.length === 0 && (
                        <div style={{ padding: '16px', color: 'var(--text-muted)', fontSize: '13px' }}>
                            No actions found for this filter.
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
        description: 'Interface metadata not available.'
    };

    const handleDeleteGroup = async (group) => {
        if (group.is_system) {
            toast.error("System groups cannot be deleted");
            return;
        }
        setDeletingGroup(group);
    };

    const confirmDeleteGroup = async () => {
        if (!deletingGroup) return;
        try {
            await api.delete(`${API_BASE}/groups/${deletingGroup.id}`);
            toast.success("ACL profile deleted");
            fetchData();
        } catch (error) {
            toast.error("Failed to delete group");
        } finally {
            setDeletingGroup(null);
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
    const filteredAclProfiles = groups.filter(group => {
        const q = aclProfileSearch.trim().toLowerCase();
        if (!q) return true;
        return (
            String(group.name || '').toLowerCase().includes(q) ||
            String(group.id || '').toLowerCase().includes(q) ||
            String(group.description || '').toLowerCase().includes(q)
        );
    });

    const assignmentsType = assignmentsView === 'users' ? 'user' : 'chat';
    const assignmentsData = assignmentsView === 'users' ? filteredUsers : filteredChats;

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
    const currentApproval = (() => {
        const value = currentConf.approval_decisions;
        if (!value || typeof value !== 'object') {
            return { enabled: true, allowed_groups: ['master'], denied_groups: [] };
        }
        return {
            enabled: Boolean(value.enabled ?? true),
            allowed_groups: Array.isArray(value.allowed_groups) ? value.allowed_groups : ['master'],
            denied_groups: Array.isArray(value.denied_groups) ? value.denied_groups : []
        };
    })();
    const getProfileApprovalMode = (groupId) => {
        const groupToken = String(groupId || '').trim().toLowerCase();
        if (!groupToken) return 'default';
        const denied = new Set((currentApproval.denied_groups || []).map(v => String(v || '').trim().toLowerCase()).filter(Boolean));
        if (denied.has(groupToken)) return 'deny';
        const allowed = new Set((currentApproval.allowed_groups || []).map(v => String(v || '').trim().toLowerCase()).filter(Boolean));
        // Visual mode reflects explicit per-profile override only.
        // Wildcards (* / all) still affect runtime policy, but should not mask "default" state in UI.
        if (allowed.has(groupToken)) return 'allow';
        return 'default';
    };
    const setProfileApprovalMode = (groupId, mode) => {
        const groupToken = String(groupId || '').trim().toLowerCase();
        if (!groupToken) return;
        const allowed = new Set((currentApproval.allowed_groups || []).map(v => String(v || '').trim().toLowerCase()).filter(Boolean));
        const denied = new Set((currentApproval.denied_groups || []).map(v => String(v || '').trim().toLowerCase()).filter(Boolean));
        allowed.delete(groupToken);
        denied.delete(groupToken);
        if (mode === 'allow') allowed.add(groupToken);
        if (mode === 'deny') denied.add(groupToken);
        handleInterfaceUpdate({
            approval_decisions: {
                ...currentApproval,
                allowed_groups: Array.from(allowed),
                denied_groups: Array.from(denied),
            }
        });
    };
    const filteredApprovalAudit = (approvalAudit || []).filter(item => {
        const sourceInterface = String(item?.source_interface || '').toLowerCase();
        if (sourceInterface !== String(activeInterface || '').toLowerCase()) return false;
        if (approvalAuditFilter === 'all') return true;
        return String(item?.command || '').toLowerCase() === approvalAuditFilter;
    });
    const copyInterfaceOptions = visibleInterfaces.filter(
        itf => String(itf || '').toLowerCase() !== String(activeInterface || '').toLowerCase()
    );
    const shellCardStyle = {
        padding: '10px',
        borderRadius: '8px',
        background: 'rgba(255,255,255,0.015)',
        border: '1px solid var(--card-border)',
        minHeight: '100%'
    };
    const inputTone = 'color-mix(in srgb, var(--card-bg) 84%, var(--text-main) 4%)';
    const inputBorderTone = 'color-mix(in srgb, var(--card-border) 80%, var(--text-main) 20%)';
    const compactFieldStyle = {
        width: '100%',
        borderRadius: '6px',
        background: inputTone,
        border: `1px solid ${inputBorderTone}`,
        minHeight: '34px',
        fontSize: '11px',
        padding: '5px 9px'
    };
    const soberBg = {
        success: 'color-mix(in srgb, #22c55e 16%, var(--card-bg) 84%)',
        danger: 'color-mix(in srgb, #ef4444 14%, var(--card-bg) 86%)',
        warn: 'color-mix(in srgb, #eab308 14%, var(--card-bg) 86%)',
        neutral: 'color-mix(in srgb, var(--text-main) 8%, var(--card-bg) 92%)'
    };

    return (
        <div className="animate-in scroll-container security-refine" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div style={{ flex: 1, overflowY: 'auto', padding: 0, paddingBottom: '24px' }}>
                <section style={{ padding: isMobile ? '8px' : '12px', borderRadius: 0, border: 'none', background: 'var(--card-bg)', backdropFilter: 'var(--surface-blur)', WebkitBackdropFilter: 'var(--surface-blur)', boxShadow: 'none' }}>
                    <div
                        style={{
                            position: 'sticky',
                            top: 0,
                            zIndex: 5,
                            background: 'var(--card-bg)',
                            backdropFilter: 'var(--surface-blur)',
                            WebkitBackdropFilter: 'var(--surface-blur)',
                            margin: isMobile ? '-8px -8px 8px -8px' : '-12px -12px 8px -12px',
                            padding: isMobile ? '8px 8px 0 8px' : '8px 12px 0 12px',
                            borderBottom: '1px solid var(--card-border)',
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: isMobile ? 'wrap' : 'nowrap', paddingBottom: '8px' }}>
                            <div style={{ minWidth: 0 }}>
                                <h2 style={{ fontSize: isMobile ? '1rem' : '1.15rem', fontWeight: '800', margin: 0 }}>Security Hub</h2>
                                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '1px' }}>Interface-wide access control and permission orchestration.</p>
                            </div>
                            <div style={{ display: 'flex', gap: '4px', padding: '2px', borderRadius: '8px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)', flexShrink: 0 }}>
                                {visibleInterfaces.map(itf => (
                                    <button
                                        key={itf}
                                        onClick={() => setActiveInterface(itf)}
                                        className="btn-ghost"
                                        style={{
                                            padding: '5px 8px',
                                            borderRadius: '6px',
                                            fontSize: '10px',
                                            fontWeight: '700',
                                            background: activeInterface === itf ? 'var(--accent-glow)' : 'transparent',
                                            color: activeInterface === itf ? 'var(--accent-color)' : 'var(--text-muted)',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '6px',
                                            textTransform: 'uppercase',
                                        }}
                                    >
                                        {itf === 'telegram' && <Send size={12} />}
                                        {itf === 'web' && <Globe size={12} />}
                                        {itf === 'cli' && <Terminal size={12} />}
                                        {INTERFACE_META[itf]?.label || itf}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Tabs */}
                        <nav style={{ display: 'flex', gap: '6px', borderTop: '1px solid var(--card-border)', borderBottom: '1px solid var(--card-border)', padding: '6px 0' }}>
                            {[
                                { id: 'channels', label: 'Channels' },
                                { id: 'acl_profiles', label: 'ACL Profiles' },
                                { id: 'assignments', label: 'Assignments' },
                                { id: 'audit', label: 'Audit' }
                            ].map(tab => (
                                <button
                                    key={tab.id}
                                    onClick={() => setActiveTab(tab.id)}
                                    style={{
                                        padding: '5px 9px',
                                        background: activeTab === tab.id ? 'var(--accent-glow)' : 'transparent',
                                        border: '1px solid',
                                        borderColor: activeTab === tab.id ? 'var(--accent-color)' : 'transparent',
                                        borderRadius: '7px',
                                        color: activeTab === tab.id ? 'var(--accent-color)' : 'var(--text-muted)',
                                        fontWeight: activeTab === tab.id ? '800' : '600',
                                        cursor: 'pointer',
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.05em',
                                        fontSize: '0.6rem',
                                        transition: 'var(--transition-fast)'
                                    }}
                                >
                                    {tab.label}
                                </button>
                            ))}
                        </nav>
                    </div>

                    {/* Content */}
                    {(activeTab === 'channels' || activeTab === 'audit') && (
                        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '12px', alignItems: 'stretch' }}>
                            {activeTab === 'channels' && (
                                <>
                            <div className="security-card" style={shellCardStyle}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                                    <div className="flex-center" style={{ width: '28px', height: '28px', borderRadius: '7px', background: 'var(--accent-glow)', color: 'var(--accent-color)' }}>
                                        <Shield size={15} />
                                    </div>
                                    <h3 style={{ fontSize: '0.82rem', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Access Strategy</h3>
                                </div>

                                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '10px' }}>
                                        <div>
                                            <label style={{ display: 'block', fontSize: '9px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '4px', textTransform: 'uppercase' }}>Private Messages</label>
                                            <select
                                                value={currentConf.dm_mode}
                                                onChange={(e) => handleInterfaceUpdate({ dm_mode: e.target.value })}
                                                className="input-field"
                                                style={compactFieldStyle}
                                            >
                                                <option value="approved_only">Approved Only</option>
                                                <option value="auto_approve">Auto Approve</option>
                                                <option value="anyone">Anyone</option>
                                            </select>
                                        </div>
                                        <div>
                                            <label style={{ display: 'block', fontSize: '9px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '4px', textTransform: 'uppercase' }}>Groups / Channels</label>
                                            <select
                                                value={currentConf.group_mode}
                                                onChange={(e) => handleInterfaceUpdate({ group_mode: e.target.value })}
                                                className="input-field"
                                                style={compactFieldStyle}
                                            >
                                                <option value="approved_only">Approved Only</option>
                                                <option value="auto_approve">Auto Approve</option>
                                                <option value="anyone">Anyone</option>
                                            </select>
                                        </div>
                                    </div>

                                    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '10px' }}>
                                        {[
                                            { label: 'Default User ACL Profile', key: 'default_user_group', prefix: 'dug' },
                                            { label: 'Auto-Approve User ACL Profile', key: 'auto_approve_user_group', prefix: 'aug' },
                                            { label: 'Default Chat ACL Profile', key: 'default_chat_group', prefix: 'dcg' },
                                            { label: 'Auto-Approve Chat ACL Profile', key: 'auto_approve_chat_group', prefix: 'acg' }
                                        ].map(field => (
                                            <div key={field.key}>
                                                <label style={{ display: 'block', fontSize: '9px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '4px', textTransform: 'uppercase' }}>{field.label}</label>
                                                <select
                                                    value={currentConf[field.key] || ''}
                                                    onChange={(e) => handleInterfaceUpdate({ [field.key]: e.target.value })}
                                                    className="input-field"
                                                    style={compactFieldStyle}
                                                >
                                                    {groupOptions.map(g => (
                                                        <option key={`${field.prefix}-${g.value}`} value={g.value}>{g.label}</option>
                                                    ))}
                                                </select>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            <div className="security-card" style={shellCardStyle}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
                                    <div className="flex-center" style={{ width: '28px', height: '28px', borderRadius: '7px', background: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' }}>
                                        <Activity size={15} />
                                    </div>
                                    <h3 style={{ fontSize: '0.82rem', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Traffic Control</h3>
                                </div>

                                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px', borderRadius: '8px', background: 'rgba(0,0,0,0.16)' }}>
                                        <div>
                                            <div style={{ fontSize: '11px', fontWeight: '800' }}>Global Rate Limit</div>
                                            <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>Prevent API exhaustion</div>
                                        </div>
                                        <div
                                            onClick={() => handleInterfaceUpdate({ rate_limit_enabled: !currentConf.rate_limit_enabled })}
                                            style={{
                                                width: '44px',
                                                height: '24px',
                                                borderRadius: '12px',
                                                background: currentConf.rate_limit_enabled ? 'var(--accent-color)' : 'rgba(255,255,255,0.1)',
                                                position: 'relative',
                                                cursor: 'pointer',
                                                transition: 'var(--transition-fast)'
                                            }}
                                        >
                                            <div style={{
                                                width: '18px',
                                                height: '18px',
                                                borderRadius: '50%',
                                                background: '#fff',
                                                position: 'absolute',
                                                top: '3px',
                                                left: currentConf.rate_limit_enabled ? '23px' : '3px',
                                                transition: 'var(--transition-fast)',
                                                boxShadow: 'var(--shadow-sm)'
                                            }} />
                                        </div>
                                    </div>

                                    <div style={{ opacity: currentConf.rate_limit_enabled ? 1 : 0.4, pointerEvents: currentConf.rate_limit_enabled ? 'auto' : 'none', transition: 'opacity 0.2s' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                                            <label style={{ fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', textTransform: 'uppercase' }}>MSG / MINUTE (BURST)</label>
                                            <span style={{ fontSize: '12px', fontWeight: '900', color: 'var(--accent-color)' }}>{currentConf.max_msgs_per_min || 0}</span>
                                        </div>
                                        <input
                                            type="range"
                                            min="0"
                                            max="120"
                                            step="5"
                                            value={currentConf.max_msgs_per_min || 0}
                                            onChange={(e) => handleInterfaceUpdate({ max_msgs_per_min: parseInt(e.target.value) })}
                                            style={{ width: '100%', accentColor: 'var(--accent-color)' }}
                                        />
                                    </div>

                                    <div style={{ marginTop: 'auto', padding: '10px', borderRadius: '8px', background: soberBg.danger, border: '1px solid color-mix(in srgb, var(--card-border) 72%, #ef4444 28%)' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-main)', marginBottom: '4px' }}>
                                            <Zap size={14} />
                                            <span style={{ fontSize: '11px', fontWeight: '900', textTransform: 'uppercase' }}>Emergency Stop</span>
                                        </div>
                                        <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Instantly disable all communication for this interface.</p>
                                        <button className="btn-ghost" style={{ width: '100%', marginTop: '12px', fontSize: '11px', fontWeight: '800', background: 'color-mix(in srgb, #ef4444 20%, var(--card-bg) 80%)', color: 'var(--text-main)' }}>
                                            ACTIVATE LOCKDOWN
                                        </button>
                                    </div>
                                </div>
                            </div>
                                </>
                            )}

                            {(activeTab === 'audit') && (
                            <div className="security-card" style={{ padding: '12px', borderRadius: '8px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--card-border)', gridColumn: '1 / -1' }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                        <div className="flex-center" style={{ width: '30px', height: '30px', borderRadius: '8px', background: 'rgba(56,189,248,0.1)', color: '#38bdf8' }}>
                                            <ShieldAlert size={15} />
                                        </div>
                                        <div>
                                            <h3 style={{ fontSize: '0.875rem', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Approval Audit ({(INTERFACE_META[activeInterface]?.label || activeInterface).toUpperCase()})</h3>
                                            <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Review historical approve/deny decisions for the selected interface.</p>
                                        </div>
                                    </div>
                                </div>
                                {activeTab === 'audit' && <div style={{ marginTop: '16px', borderTop: '1px solid var(--card-border)', paddingTop: '14px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', gap: '8px', flexWrap: 'wrap' }}>
                                        <label style={{ fontSize: '10px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Approval Audit ({(INTERFACE_META[activeInterface]?.label || activeInterface).toUpperCase()})</label>
                                        <div style={{ display: 'flex', gap: '6px' }}>
                                            {['all', 'approve', 'deny'].map(mode => (
                                                <button
                                                    key={`audit-${mode}`}
                                                    onClick={() => setApprovalAuditFilter(mode)}
                                                    style={{
                                                        padding: '5px 9px',
                                                        borderRadius: '8px',
                                                        border: '1px solid',
                                                        borderColor: approvalAuditFilter === mode ? 'var(--accent-color)' : 'var(--card-border)',
                                                        background: approvalAuditFilter === mode ? 'var(--accent-glow)' : 'rgba(255,255,255,0.02)',
                                                        color: approvalAuditFilter === mode ? 'var(--accent-color)' : 'var(--text-muted)',
                                                        fontSize: '10px',
                                                        fontWeight: '800',
                                                        textTransform: 'uppercase'
                                                    }}
                                                >
                                                    {mode}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                    <div className="custom-scrollbar" style={{ maxHeight: '220px', overflowY: 'auto', border: '1px solid var(--card-border)', borderRadius: '10px' }}>
                                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                            <thead>
                                                <tr style={{ background: 'rgba(255,255,255,0.02)' }}>
                                                    <th style={{ textAlign: 'left', padding: '8px 10px', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Time</th>
                                                    <th style={{ textAlign: 'left', padding: '8px 10px', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Decision</th>
                                                    <th style={{ textAlign: 'left', padding: '8px 10px', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Worker</th>
                                                    <th style={{ textAlign: 'left', padding: '8px 10px', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Source Session</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {filteredApprovalAudit.map((item, idx) => (
                                                    <tr key={`approval-row-${idx}`} style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                                                        <td style={{ padding: '8px 10px', fontSize: '11px', color: 'var(--text-muted)' }}>
                                                            {item?.ts ? new Date(item.ts).toLocaleString() : '-'}
                                                        </td>
                                                        <td
                                                            style={{
                                                                padding: 0,
                                                                background: item?.command === 'approve'
                                                                    ? soberBg.success
                                                                    : item?.command === 'deny'
                                                                        ? soberBg.danger
                                                                        : soberBg.warn
                                                            }}
                                                        >
                                                            <div style={{ padding: '8px 10px', fontSize: '10px', fontWeight: '900', textTransform: 'uppercase', color: 'var(--text-main)' }}>
                                                                {item?.command || '-'}
                                                            </div>
                                                        </td>
                                                        <td style={{ padding: '8px 10px', fontSize: '11px' }}>
                                                            {item?.work_label || item?.work_key || item?.work_id || '-'}
                                                        </td>
                                                        <td style={{ padding: '8px 10px', fontSize: '11px', color: 'var(--text-muted)' }}>
                                                            {item?.source_session_id || '-'}
                                                        </td>
                                                    </tr>
                                                ))}
                                                {filteredApprovalAudit.length === 0 && (
                                                    <tr>
                                                        <td colSpan={4} style={{ padding: '10px', fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                                                            No decisions for this interface yet.
                                                        </td>
                                                    </tr>
                                                )}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>}
                            </div>
                            )}
                        </div>
                    )}

                    {activeTab === 'acl_profiles' && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                            <div className="security-card" style={{ padding: isMobile ? '8px' : '10px', borderRadius: '8px', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--card-border)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <div style={{ position: 'relative', flex: 1 }}>
                                        <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                                        <input
                                            className="input-field"
                                            value={aclProfileSearch}
                                            onChange={(e) => setAclProfileSearch(e.target.value)}
                                            placeholder="Search ACL profiles..."
                                            style={{ width: '100%', paddingLeft: '32px' }}
                                        />
                                    </div>
                                    <button
                                        onClick={() => setShowCreateProfileModal(true)}
                                        className="btn-primary"
                                        style={{ width: '32px', height: '32px', minWidth: '32px', padding: 0, borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                                        title="Add ACL profile"
                                    >
                                        <Plus size={15} />
                                    </button>
                                </div>
                            </div>

                            {/* Existing ACL Profiles */}
                            <div>
                                <div style={{ fontSize: '0.6875rem', fontWeight: '800', color: 'var(--text-muted)', letterSpacing: '0.08em', marginBottom: '12px', textTransform: 'uppercase' }}>
                                    Existing ACL Profiles ({filteredAclProfiles.length}{aclProfileSearch.trim() ? `/${groups.length}` : ''})
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
                                    {filteredAclProfiles.map(group => (
                                        <div
                                            key={group.id}
                                            style={{
                                                padding: '16px',
                                                borderRadius: '14px',
                                                background: 'rgba(255,255,255,0.02)',
                                                border: '1px solid var(--card-border)',
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'flex-start',
                                                position: 'relative',
                                                overflow: 'hidden',
                                                transition: 'var(--transition-fast)'
                                            }}
                                        >
                                            {group.is_system && (
                                                <div style={{ position: 'absolute', top: 0, right: 0, padding: '3px 8px', background: 'var(--accent-glow)', color: 'var(--accent-color)', fontSize: '8px', fontWeight: '900', borderRadius: '0 0 0 8px' }}>SYSTEM</div>
                                            )}
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                                                    <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: group.is_system ? 'var(--accent-color)' : '#4ade80', flexShrink: 0 }}></div>
                                                    <h4 style={{ fontSize: '0.8125rem', fontWeight: '800' }}>{group.name}</h4>
                                                    <code style={{ fontSize: '9px', opacity: 0.5 }}>{group.id}</code>
                                                </div>
                                                <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '10px', lineHeight: '1.4' }}>{group.description || 'No description.'}</p>

                                                <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                                                    <div style={{ fontSize: '9px', display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--text-muted)', padding: '3px 8px', background: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                                                        <Eye size={10} /> {group.worker_view_scope || 'owner'}
                                                    </div>
                                                    <div style={{ fontSize: '9px', display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--text-muted)', padding: '3px 8px', background: 'rgba(255,255,255,0.03)', borderRadius: '6px' }}>
                                                        <Zap size={10} /> {group.worker_control_scope || 'owner'}
                                                    </div>
                                                    <div style={{
                                                        fontSize: '9px',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        gap: '4px',
                                                        color: 'var(--text-main)',
                                                        padding: '3px 8px',
                                                        background: getProfileApprovalMode(group.id) === 'allow'
                                                            ? soberBg.success
                                                            : getProfileApprovalMode(group.id) === 'deny'
                                                                ? soberBg.danger
                                                                : soberBg.neutral,
                                                        borderRadius: '6px',
                                                        textTransform: 'uppercase',
                                                        fontWeight: '700'
                                                    }}>
                                                        <ShieldAlert size={10} /> {getProfileApprovalMode(group.id)}
                                                    </div>
                                                </div>
                                            </div>
                                            <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
                                                <button className="btn-ghost" style={{ padding: '6px', borderRadius: '8px' }} onClick={() => openGroupEditor(group)}>
                                                    <Edit size={14} />
                                                </button>
                                                {!group.is_system && (
                                                    <button className="btn-ghost" style={{ padding: '6px', borderRadius: '8px', color: 'var(--text-main)', background: soberBg.danger }} onClick={() => handleDeleteGroup(group)}>
                                                        <Trash2 size={14} />
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                    {filteredAclProfiles.length === 0 && (
                                        <div style={{ padding: '16px', borderRadius: '8px', border: '1px solid var(--card-border)', color: 'var(--text-muted)', fontSize: '12px' }}>
                                            No ACL profiles found for this filter.
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {(activeTab === 'assignments') && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                            <div style={{ display: 'flex', gap: '4px', padding: '2px', borderRadius: '8px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)', width: 'fit-content' }}>
                                {[
                                    { id: 'users', label: 'USER' },
                                    { id: 'chats', label: 'CHAT_GROUP' }
                                ].map(view => (
                                    <button
                                        key={view.id}
                                        onClick={() => setAssignmentsView(view.id)}
                                        style={{
                                            padding: '5px 8px',
                                            borderRadius: '6px',
                                            border: '1px solid transparent',
                                            borderColor: assignmentsView === view.id ? 'var(--accent-color)' : 'transparent',
                                            background: assignmentsView === view.id ? 'var(--accent-glow)' : 'transparent',
                                            color: assignmentsView === view.id ? 'var(--accent-color)' : 'var(--text-muted)',
                                            fontSize: '10px',
                                            fontWeight: '700',
                                            textTransform: 'uppercase',
                                            letterSpacing: '0.04em',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '6px'
                                        }}
                                    >
                                        {view.label}
                                    </button>
                                ))}
                            </div>
                            {/* Search + Filters */}
                            <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: '10px', alignItems: isMobile ? 'stretch' : 'center' }}>
                                <div style={{ position: 'relative', flex: 1 }}>
                                    <Search size={14} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                                    <input
                                        placeholder={`Search ${assignmentsView}...`}
                                        value={searchTerm}
                                        onChange={(e) => setSearchTerm(e.target.value)}
                                        className="input-field"
                                        style={{ width: '100%', paddingLeft: '36px', borderRadius: '10px', background: 'rgba(0,0,0,0.2)', padding: '8px 12px 8px 36px', fontSize: '12px' }}
                                    />
                                </div>
                                <div style={{ display: 'flex', gap: '4px', overflowX: 'auto', paddingBottom: isMobile ? '4px' : '0' }}>
                                    {['all', 'pending', 'approved', 'blocked'].map(status => (
                                        <button
                                            key={status}
                                            onClick={() => setFilterStatus(status)}
                                            style={{
                                                padding: '6px 12px',
                                                borderRadius: '8px',
                                                fontSize: '10px',
                                                fontWeight: '800',
                                                textTransform: 'uppercase',
                                                letterSpacing: '0.03em',
                                                background: filterStatus === status ? 'var(--accent-glow)' : 'rgba(255,255,255,0.02)',
                                                color: filterStatus === status ? 'var(--accent-color)' : 'var(--text-muted)',
                                                border: '1px solid',
                                                borderColor: filterStatus === status ? 'var(--accent-color)' : 'var(--card-border)',
                                                transition: 'var(--transition-fast)',
                                                whiteSpace: 'nowrap'
                                            }}
                                        >
                                            {status}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Table / Cards */}
                            <div className="security-card" style={{ overflow: 'hidden', borderRadius: '8px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--card-border)' }}>
                                {!isMobile ? (
                                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                                        <thead>
                                            <tr style={{ background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid var(--card-border)' }}>
                                                <th style={{ padding: '12px 16px', fontSize: '10px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Name</th>
                                                <th style={{ padding: '12px 16px', fontSize: '10px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase' }}>ID</th>
                                                <th style={{ padding: '12px 16px', fontSize: '10px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase' }}>ACL Profile</th>
                                                <th style={{ padding: '12px 16px', fontSize: '10px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Status</th>
                                                <th style={{ padding: '12px 16px', fontSize: '10px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Last Active</th>
                                                <th style={{ padding: '12px 16px', fontSize: '10px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase', textAlign: 'right' }}>Actions</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {assignmentsData.map(item => (
                                                <tr key={item.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', transition: 'background 0.2s' }} className="hover-highlight">
                                                    <td style={{ padding: '12px 16px' }}>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                                            <div className="flex-center" style={{ width: '28px', height: '28px', borderRadius: '50%', background: 'linear-gradient(135deg, var(--accent-color) 0%, #a855f7 100%)', color: '#fff', fontSize: '11px', fontWeight: '900', flexShrink: 0 }}>
                                                                {(assignmentsView === 'users' ? item.display_name : item.title)?.charAt(0) || '?'}
                                                            </div>
                                                            <span style={{ fontSize: '12px', fontWeight: '700' }}>{assignmentsView === 'users' ? item.display_name : item.title}</span>
                                                        </div>
                                                    </td>
                                                    <td style={{ padding: '12px 16px' }}>
                                                        <code style={{ fontSize: '10px', color: 'var(--text-muted)', background: 'rgba(0,0,0,0.2)', padding: '3px 6px', borderRadius: '4px' }}>{item.id}</code>
                                                    </td>
                                                    <td style={{ padding: '12px 16px' }}>
                                                        <select
                                                            value={item.group_id || ''}
                                                            onChange={(e) => handleAssignGroup(assignmentsType, item, e.target.value)}
                                                            className="input-field"
                                                            style={{ fontSize: '11px', padding: '5px 8px', background: 'rgba(0,0,0,0.1)', borderRadius: '6px', minWidth: '120px' }}
                                                        >
                                                            {groupOptions.map(g => (
                                                                <option key={`row-${item.id}-${g.value}`} value={g.value}>{g.label}</option>
                                                            ))}
                                                        </select>
                                                    </td>
                                                    <td
                                                        style={{
                                                            padding: 0,
                                                            background: item.status === 'approved' ? soberBg.success : item.status === 'blocked' ? soberBg.danger : soberBg.warn
                                                        }}
                                                    >
                                                        <div
                                                            style={{
                                                                padding: '12px 16px',
                                                                fontSize: '10px',
                                                                fontWeight: '900',
                                                                textTransform: 'uppercase',
                                                                color: 'var(--text-main)'
                                                            }}
                                                        >
                                                            {item.status}
                                                        </div>
                                                    </td>
                                                    <td style={{ padding: '12px 16px', fontSize: '11px', color: 'var(--text-muted)' }}>
                                                        {new Date(item.last_seen_at * 1000).toLocaleDateString()}
                                                    </td>
                                                    <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                                                        <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                                                            <button
                                                                onClick={() => handleStatusUpdate(assignmentsType, item.interface, item.id, item.status === 'approved' ? 'pending' : 'approved')}
                                                                className="btn-ghost"
                                                                style={{ padding: '6px', borderRadius: '8px', color: 'var(--text-main)', background: item.status === 'approved' ? soberBg.danger : soberBg.success }}
                                                                title={item.status === 'approved' ? "Revoke" : "Approve"}
                                                            >
                                                                {item.status === 'approved' ? <Slash size={14} /> : <CheckCircle size={14} />}
                                                            </button>
                                                            <button
                                                                onClick={() => setEditingOverrides({ type: assignmentsType, data: JSON.parse(JSON.stringify(item)) })}
                                                                className="btn-ghost"
                                                                style={{ padding: '6px', borderRadius: '8px' }}
                                                                title="Edit capability overrides"
                                                            >
                                                                <Edit size={14} />
                                                            </button>
                                                        </div>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                ) : (
                                    /* Mobile Cards */
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1px', background: 'var(--card-border)' }}>
                                        {assignmentsData.map(item => (
                                            <div key={item.id} style={{ padding: '14px 16px', background: 'var(--card-bg)' }}>
                                                {/* Top: Avatar + Name + Status */}
                                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
                                                        <div className="flex-center" style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'var(--accent-glow)', color: 'var(--accent-color)', fontSize: '12px', fontWeight: '900', flexShrink: 0 }}>
                                                            {(assignmentsView === 'users' ? item.display_name : item.title)?.charAt(0) || '?'}
                                                        </div>
                                                        <div style={{ minWidth: 0 }}>
                                                            <div style={{ fontWeight: '700', fontSize: '13px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{assignmentsView === 'users' ? item.display_name : item.title}</div>
                                                            <code style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{item.id}</code>
                                                        </div>
                                                    </div>
                                                    <span style={{
                                                        fontSize: '9px', fontWeight: '900', padding: '3px 8px', borderRadius: '6px', textTransform: 'uppercase', flexShrink: 0,
                                                        background: item.status === 'approved' ? soberBg.success : item.status === 'blocked' ? soberBg.danger : soberBg.warn,
                                                        color: 'var(--text-main)'
                                                    }}>
                                                        {item.status}
                                                    </span>
                                                </div>

                                                {/* Middle: Group + Last Active */}
                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '10px' }}>
                                                    <div>
                                                        <label style={{ display: 'block', fontSize: '9px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '3px', textTransform: 'uppercase' }}>ACL Profile</label>
                                                        <select
                                                            value={item.group_id || ''}
                                                            onChange={(e) => handleAssignGroup(assignmentsType, item, e.target.value)}
                                                            className="input-field"
                                                            style={{ width: '100%', padding: '6px 8px', fontSize: '11px', background: 'rgba(0,0,0,0.1)', borderRadius: '6px' }}
                                                        >
                                                            {groupOptions.map(g => (
                                                                <option key={`mrow-${item.id}-${g.value}`} value={g.value}>{g.label}</option>
                                                            ))}
                                                        </select>
                                                    </div>
                                                    <div>
                                                        <label style={{ display: 'block', fontSize: '9px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '3px', textTransform: 'uppercase' }}>Last Active</label>
                                                        <div style={{ fontSize: '12px', fontWeight: '600', padding: '6px 0' }}>{new Date(item.last_seen_at * 1000).toLocaleDateString()}</div>
                                                    </div>
                                                </div>

                                                {/* Bottom: Action Buttons */}
                                                <div style={{ display: 'flex', gap: '6px' }}>
                                                    <button
                                                        onClick={() => handleStatusUpdate(assignmentsType, item.interface, item.id, item.status === 'approved' ? 'pending' : 'approved')}
                                                        style={{ flex: 1, padding: '8px', borderRadius: '8px', background: item.status === 'approved' ? soberBg.danger : soberBg.success, color: 'var(--text-main)', fontSize: '10px', fontWeight: '800', border: 'none' }}
                                                    >
                                                        {item.status === 'approved' ? 'REVOKE' : 'APPROVE'}
                                                    </button>
                                                    <button
                                                        onClick={() => setEditingOverrides({ type: assignmentsType, data: JSON.parse(JSON.stringify(item)) })}
                                                        style={{ padding: '8px 14px', borderRadius: '8px', background: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)', border: 'none', fontSize: '10px', fontWeight: '800' }}
                                                    >
                                                        OVERRIDES
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {assignmentsData.length === 0 && (
                                    <div style={{ padding: '48px 20px', textAlign: 'center' }}>
                                        <div className="flex-center" style={{ width: '40px', height: '40px', borderRadius: '50%', background: 'rgba(255,255,255,0.02)', margin: '0 auto 12px' }}>
                                            <Search size={20} style={{ opacity: 0.2 }} />
                                        </div>
                                        <h4 style={{ fontSize: '0.8125rem', fontWeight: '800', marginBottom: '4px' }}>No records found</h4>
                                        <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Try adjusting your search or filters.</p>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </section>
            </div>

            {/* Overrides Modal */}
            {
                editingOverrides && (
                    <div
                        style={{
                            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                            background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: isMobile ? 'flex-end' : 'center',
                            justifyContent: 'center', zIndex: 1000, padding: isMobile ? '0' : '20px',
                            backdropFilter: 'blur(8px)'
                        }}
                        onClick={() => setEditingOverrides(null)}
                    >
                        <div className="glass animate-pop" onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: isMobile ? '100%' : '720px', maxHeight: isMobile ? '90vh' : '85vh', overflowY: 'auto', borderRadius: isMobile ? '20px 20px 0 0' : '24px', position: 'relative', border: '1px solid var(--card-border)' }}>
                            <div style={{ padding: isMobile ? '16px' : '24px', borderBottom: '1px solid var(--card-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.01)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                                    <div className="flex-center" style={{ width: '36px', height: '36px', borderRadius: '10px', background: 'var(--accent-glow)', color: 'var(--accent-color)', flexShrink: 0 }}>
                                        <ShieldAlert size={18} />
                                    </div>
                                    <div style={{ minWidth: 0 }}>
                                        <h3 style={{ fontSize: '1rem', fontWeight: '800' }}>Capability Overrides</h3>
                                        <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {editingOverrides.data.display_name || editingOverrides.data.title}
                                        </p>
                                    </div>
                                </div>
                                <button onClick={() => setEditingOverrides(null)} className="btn-ghost" style={{ width: '36px', height: '36px', borderRadius: '10px', flexShrink: 0 }}>
                                    <X size={18} />
                                </button>
                            </div>

                            <div style={{ padding: isMobile ? '16px' : '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div style={{ padding: '10px 12px', borderRadius: '10px', background: 'rgba(245, 158, 11, 0.05)', border: '1px solid rgba(245, 158, 11, 0.1)', display: 'flex', gap: '8px', alignItems: 'center' }}>
                                    <Activity size={14} style={{ color: '#f59e0b', flexShrink: 0 }} />
                                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: '1.4' }}>
                                        Overrides take precedence over group policies.
                                    </p>
                                </div>

                                <section>
                                    <div style={{ fontSize: '10px', fontWeight: '900', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '16px' }}>Explicit Capability Permissions</div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                        {registry.map(action => {
                                            const isAllowed = editingOverrides.data.overrides.allow_capabilities.includes(action.id);
                                            const isDenied = editingOverrides.data.overrides.deny_capabilities.includes(action.id);

                                            return (
                                                <div key={action.id} className="glass" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderRadius: '14px', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--card-border)' }}>
                                                    <div style={{ flex: 1, minWidth: 0 }}>
                                                        <div style={{ fontWeight: '800', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                            {action.id}
                                                            <span style={{ fontSize: '9px', padding: '2px 6px', borderRadius: '4px', background: 'rgba(0,0,0,0.2)', color: 'var(--text-muted)', fontWeight: '900' }}>CAPABILITY</span>
                                                        </div>
                                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{action.description}</div>
                                                    </div>
                                                    <div style={{ display: 'flex', gap: '4px', background: 'rgba(0,0,0,0.2)', padding: '4px', borderRadius: '12px' }}>
                                                        {[
                                                            { id: 'allow', label: 'ALLOW', active: isAllowed, color: 'var(--text-main)', bg: soberBg.success },
                                                            { id: 'none', label: 'INHERIT', active: !isAllowed && !isDenied, color: 'var(--text-main)', bg: soberBg.neutral },
                                                            { id: 'deny', label: 'DENY', active: isDenied, color: 'var(--text-main)', bg: soberBg.danger }
                                                        ].map(mode => (
                                                            <button
                                                                key={mode.id}
                                                                onClick={() => {
                                                                    const o = editingOverrides.data.overrides;
                                                                    if (mode.id === 'allow') {
                                                                        o.allow_capabilities = [action.id]; // simplifying for UI, assuming one override at a time per row or similar
                                                                        o.deny_capabilities = o.deny_capabilities.filter(s => s !== action.id);
                                                                    } else if (mode.id === 'deny') {
                                                                        o.deny_capabilities = [action.id];
                                                                        o.allow_capabilities = o.allow_capabilities.filter(s => s !== action.id);
                                                                    } else {
                                                                        o.allow_capabilities = o.allow_capabilities.filter(s => s !== action.id);
                                                                        o.deny_capabilities = o.deny_capabilities.filter(s => s !== action.id);
                                                                    }
                                                                    setEditingOverrides({ ...editingOverrides });
                                                                }}
                                                                style={{
                                                                    padding: '6px 12px',
                                                                    fontSize: '10px',
                                                                    fontWeight: '800',
                                                                    borderRadius: '8px',
                                                                    transition: 'var(--transition-fast)',
                                                                    background: mode.active ? mode.bg : 'transparent',
                                                                    color: mode.active ? mode.color : 'var(--text-muted)',
                                                                    border: 'none'
                                                                }}
                                                            >
                                                                {mode.label}
                                                            </button>
                                                        ))}
                                                    </div>
                                                </div>
                                            )
                                        })}
                                    </div>
                                </section>
                            </div>

                            <div style={{ padding: isMobile ? '12px 16px' : '16px 24px', background: 'rgba(255,255,255,0.02)', borderTop: '1px solid var(--card-border)', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                                <button onClick={() => setEditingOverrides(null)} className="btn-ghost" style={{ padding: '10px 20px', borderRadius: '10px', fontWeight: '800', fontSize: '12px' }}>Cancel</button>
                                <button onClick={handleSaveOverrides} className="btn-primary" style={{ padding: '10px 24px', borderRadius: '10px', fontWeight: '800', fontSize: '12px' }}>Apply</button>
                            </div>
                        </div>
                    </div>
                )
            }

            {/* Create ACL Profile Modal */}
            {showCreateProfileModal && (
                <div
                    style={{
                        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                        background: 'rgba(0,0,0,0.72)', display: 'flex', alignItems: isMobile ? 'flex-end' : 'center',
                        justifyContent: 'center', zIndex: 1000, padding: isMobile ? '0' : '20px',
                        backdropFilter: 'blur(10px)'
                    }}
                    onClick={() => { setShowCreateProfileModal(false); setShowAdvancedCreate(false); }}
                >
                    <div className="glass animate-pop" onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: isMobile ? '100%' : '820px', maxHeight: isMobile ? '92vh' : '90vh', overflowY: 'auto', borderRadius: isMobile ? '16px 16px 0 0' : '16px', border: '1px solid var(--card-border)' }}>
                        <div style={{ padding: isMobile ? '14px' : '16px', borderBottom: '1px solid var(--card-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.01)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
                                <div className="flex-center" style={{ width: '30px', height: '30px', borderRadius: '8px', background: 'var(--accent-glow)', color: 'var(--accent-color)', flexShrink: 0 }}>
                                    <Plus size={15} />
                                </div>
                                <div style={{ minWidth: 0 }}>
                                    <h3 style={{ fontSize: '0.92rem', fontWeight: '800' }}>Create ACL Profile</h3>
                                    <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Define permission rules and worker scopes.</p>
                                </div>
                            </div>
                            <button onClick={() => { setShowCreateProfileModal(false); setShowAdvancedCreate(false); }} className="btn-ghost" style={{ width: '32px', height: '32px', borderRadius: '8px', flexShrink: 0 }}>
                                <X size={16} />
                            </button>
                        </div>

                        <div style={{ padding: isMobile ? '14px' : '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 1.5fr', gap: '10px' }}>
                                <div>
                                    <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '5px', textTransform: 'uppercase' }}>ACL Profile ID</label>
                                    <input
                                        className="input-field"
                                        placeholder="e.g. support_staff"
                                        value={newGroup.id}
                                        onChange={(e) => setNewGroup(prev => ({ ...prev, id: e.target.value }))}
                                        style={compactFieldStyle}
                                    />
                                </div>
                                <div>
                                    <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '5px', textTransform: 'uppercase' }}>Profile Name</label>
                                    <input
                                        className="input-field"
                                        placeholder="Internal Support"
                                        value={newGroup.name}
                                        onChange={(e) => setNewGroup(prev => ({ ...prev, name: e.target.value }))}
                                        style={compactFieldStyle}
                                    />
                                </div>
                                <div>
                                    <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '5px', textTransform: 'uppercase' }}>Description</label>
                                    <input
                                        className="input-field"
                                        placeholder="Purpose of this profile..."
                                        value={newGroup.description}
                                        onChange={(e) => setNewGroup(prev => ({ ...prev, description: e.target.value }))}
                                        style={compactFieldStyle}
                                    />
                                </div>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '10px' }}>
                                <div>
                                    <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '5px', textTransform: 'uppercase' }}>View Scope</label>
                                    <select
                                        className="input-field"
                                        value={newGroup.worker_view_scope}
                                        onChange={(e) => setNewGroup(prev => ({ ...prev, worker_view_scope: e.target.value }))}
                                        style={compactFieldStyle}
                                    >
                                        {WORKER_SCOPE_OPTIONS.map(opt => (
                                            <option key={`modal-new-view-${opt.value}`} value={opt.value}>{opt.label}</option>
                                        ))}
                                    </select>
                                </div>
                                <div>
                                    <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', marginBottom: '5px', textTransform: 'uppercase' }}>Control Scope</label>
                                    <select
                                        className="input-field"
                                        value={newGroup.worker_control_scope}
                                        onChange={(e) => setNewGroup(prev => ({ ...prev, worker_control_scope: e.target.value }))}
                                        style={compactFieldStyle}
                                    >
                                        {WORKER_SCOPE_OPTIONS.map(opt => (
                                            <option key={`modal-new-control-${opt.value}`} value={opt.value}>{opt.label}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>

                            <details>
                                <summary style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 10px', borderRadius: '8px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--card-border)', fontSize: '11px', fontWeight: '800', color: 'var(--text-secondary)', listStyle: 'none' }}>
                                    <span>⚙ Capability Permissions (optional)</span>
                                    <span style={{ display: 'flex', gap: '8px' }}>
                                        <span style={{ fontSize: '10px', fontWeight: '900', color: 'var(--text-main)', background: soberBg.success, padding: '2px 6px', borderRadius: '999px' }}>+{newGroupAllowCount}</span>
                                        <span style={{ fontSize: '10px', fontWeight: '900', color: 'var(--text-main)', background: soberBg.danger, padding: '2px 6px', borderRadius: '999px' }}>-{newGroupDenyCount}</span>
                                    </span>
                                </summary>
                                <div style={{ marginTop: '10px' }}>
                                    {renderActionPicker({
                                        searchValue: groupActionSearch,
                                        onSearchChange: setGroupActionSearch,
                                        allowText: newGroup.allow_actions,
                                        denyText: newGroup.deny_actions,
                                        onDecisionChange: setNewGroupActionDecision
                                    })}

                                    {showAdvancedCreate && (
                                        <div className="animate-in" style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '10px', marginTop: '10px' }}>
                                            <textarea
                                                className="input-field"
                                                placeholder="Allow patterns (e.g. system.*)..."
                                                value={newGroup.allow_actions}
                                                onChange={(e) => setNewGroup(prev => ({ ...prev, allow_actions: e.target.value }))}
                                                style={{ minHeight: '68px', fontSize: '11px', background: soberBg.success, borderRadius: '8px' }}
                                            />
                                            <textarea
                                                className="input-field"
                                                placeholder="Deny patterns (e.g. shell.*)..."
                                                value={newGroup.deny_actions}
                                                onChange={(e) => setNewGroup(prev => ({ ...prev, deny_actions: e.target.value }))}
                                                style={{ minHeight: '68px', fontSize: '11px', background: soberBg.danger, borderRadius: '8px' }}
                                            />
                                        </div>
                                    )}
                                </div>
                            </details>
                        </div>

                        <div style={{ padding: isMobile ? '10px 14px' : '12px 16px', background: 'rgba(255,255,255,0.02)', borderTop: '1px solid var(--card-border)', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                            <button
                                className="btn-ghost"
                                onClick={() => setShowAdvancedCreate(prev => !prev)}
                                style={{ padding: '8px 10px', borderRadius: '8px', background: 'rgba(255,255,255,0.04)' }}
                                title="Toggle raw pattern editor"
                            >
                                <Settings size={15} />
                            </button>
                            <button
                                onClick={handleCreateGroup}
                                className="btn-primary"
                                style={{ padding: '8px 14px', borderRadius: '8px', fontWeight: '800', fontSize: '0.72rem' }}
                            >
                                <Plus size={13} /> CREATE PROFILE
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Group Editor Modal */}
            {
                editingGroup && (
                    <div
                        style={{
                            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                            background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: isMobile ? 'flex-end' : 'center',
                            justifyContent: 'center', zIndex: 1000, padding: isMobile ? '0' : '20px',
                            backdropFilter: 'blur(12px)'
                        }}
                        onClick={() => { setEditingGroup(null); setShowAdvancedEdit(false); }}
                    >
                        <div className="glass animate-pop" onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: isMobile ? '100%' : '800px', maxHeight: isMobile ? '92vh' : '90vh', overflowY: 'auto', borderRadius: isMobile ? '20px 20px 0 0' : '24px', border: '1px solid var(--card-border)' }}>
                            <div style={{ padding: isMobile ? '16px' : '24px', borderBottom: '1px solid var(--card-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.01)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                                    <div className="flex-center" style={{ width: '36px', height: '36px', borderRadius: '10px', background: 'var(--accent-glow)', color: 'var(--accent-color)', flexShrink: 0 }}>
                                        <Shield size={18} />
                                    </div>
                                    <div style={{ minWidth: 0 }}>
                                        <h3 style={{ fontSize: '1rem', fontWeight: '800' }}>Edit ACL Profile</h3>
                                        <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {editingGroup.name}
                                        </p>
                                    </div>
                                </div>
                                <button onClick={() => { setEditingGroup(null); setShowAdvancedEdit(false); }} className="btn-ghost" style={{ width: '36px', height: '36px', borderRadius: '10px', flexShrink: 0 }}>
                                    <X size={18} />
                                </button>
                            </div>

                            <div style={{ padding: isMobile ? '16px' : '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                                <div style={{ display: 'flex', gap: '6px', borderBottom: '1px solid var(--card-border)', paddingBottom: '10px', flexWrap: 'wrap' }}>
                                    {[
                                        { id: 'profile_details', label: 'Profile Detail' },
                                        { id: 'capability_manager', label: 'Capability Manager' },
                                        { id: 'command_scope', label: 'Command Scope' },
                                    ].map(tab => (
                                        <button
                                            key={`profile-tab-${tab.id}`}
                                            onClick={() => setProfileEditorTab(tab.id)}
                                            className="btn-ghost"
                                            style={{
                                                padding: '6px 10px',
                                                borderRadius: '8px',
                                                fontSize: '10px',
                                                fontWeight: '800',
                                                textTransform: 'uppercase',
                                                letterSpacing: '0.03em',
                                                border: '1px solid',
                                                borderColor: profileEditorTab === tab.id ? 'var(--accent-color)' : 'var(--card-border)',
                                                background: profileEditorTab === tab.id ? 'var(--accent-glow)' : 'rgba(255,255,255,0.02)',
                                                color: profileEditorTab === tab.id ? 'var(--accent-color)' : 'var(--text-muted)',
                                            }}
                                        >
                                            {tab.label}
                                        </button>
                                    ))}
                                </div>

                                {profileEditorTab === 'profile_details' && (
                                    <>
                                        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '12px' }}>
                                            <div>
                                                <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Profile Name</label>
                                                <input
                                                    className="input-field"
                                                    value={editingGroup.name}
                                                    onChange={(e) => setEditingGroup(prev => ({ ...prev, name: e.target.value }))}
                                                    placeholder="Profile Name"
                                                    style={{ width: '100%', background: 'rgba(0,0,0,0.2)', padding: '10px 12px', borderRadius: '10px', fontSize: '12px' }}
                                                />
                                            </div>
                                            <div>
                                                <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Description</label>
                                                <input
                                                    className="input-field"
                                                    value={editingGroup.description || ''}
                                                    onChange={(e) => setEditingGroup(prev => ({ ...prev, description: e.target.value }))}
                                                    placeholder="Purpose of this group..."
                                                    style={{ width: '100%', background: 'rgba(0,0,0,0.2)', padding: '10px 12px', borderRadius: '10px', fontSize: '12px' }}
                                                />
                                            </div>
                                        </div>

                                        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '12px' }}>
                                            <div>
                                                <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>View Scope</label>
                                                <select
                                                    className="input-field"
                                                    value={editingGroup.worker_view_scope || 'owner_identity'}
                                                    onChange={(e) => setEditingGroup(prev => ({ ...prev, worker_view_scope: e.target.value }))}
                                                    style={{ width: '100%', background: 'rgba(0,0,0,0.2)', padding: '10px 12px', borderRadius: '10px', fontSize: '12px' }}
                                                >
                                                    {WORKER_SCOPE_OPTIONS.map(opt => (
                                                        <option key={`edit-view-${opt.value}`} value={opt.value}>{opt.label}</option>
                                                    ))}
                                                </select>
                                            </div>
                                            <div>
                                                <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Control Scope</label>
                                                <select
                                                    className="input-field"
                                                    value={editingGroup.worker_control_scope || 'owner_identity'}
                                                    onChange={(e) => setEditingGroup(prev => ({ ...prev, worker_control_scope: e.target.value }))}
                                                    style={{ width: '100%', background: 'rgba(0,0,0,0.2)', padding: '10px 12px', borderRadius: '10px', fontSize: '12px' }}
                                                >
                                                    {WORKER_SCOPE_OPTIONS.map(opt => (
                                                        <option key={`edit-control-${opt.value}`} value={opt.value}>{opt.label}</option>
                                                    ))}
                                                </select>
                                            </div>
                                        </div>
                                    </>
                                )}

                                {profileEditorTab === 'capability_manager' && (
                                    <div style={{ borderTop: '1px solid var(--card-border)', paddingTop: '12px' }}>
                                        <div style={{ display: 'flex', alignItems: isMobile ? 'flex-start' : 'center', justifyContent: 'space-between', marginBottom: '12px', flexDirection: isMobile ? 'column' : 'row', gap: '8px' }}>
                                            <div>
                                                <div style={{ fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Capability Permissions</div>
                                                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                                                    {splitPatterns(editingGroup.allow_actions).length} allowed | {splitPatterns(editingGroup.deny_actions).length} denied
                                                </div>
                                            </div>
                                            <button
                                                className="btn-ghost"
                                                onClick={() => setShowAdvancedEdit(prev => !prev)}
                                                style={{ fontSize: '10px', fontWeight: '800', textTransform: 'uppercase', color: 'var(--accent-color)', padding: '6px 12px', borderRadius: '8px' }}
                                            >
                                                {showAdvancedEdit ? 'Standard' : 'Advanced'}
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
                                            <div style={{ marginTop: '16px', display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '12px' }}>
                                                <div>
                                                    <label style={{ display: 'block', fontSize: '10px', color: 'var(--text-muted)', fontWeight: '800', marginBottom: '4px' }}>ALLOW PATTERNS</label>
                                                    <textarea
                                                        className="input-field"
                                                        value={editingGroup.allow_actions}
                                                        onChange={(e) => setEditingGroup(prev => ({ ...prev, allow_actions: e.target.value }))}
                                                        placeholder="e.g. kernel.*"
                                                        style={{ width: '100%', minHeight: '80px', background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: '10px', fontSize: '11px', fontFamily: 'monospace' }}
                                                    />
                                                </div>
                                                <div>
                                                    <label style={{ display: 'block', fontSize: '10px', color: 'var(--text-muted)', fontWeight: '800', marginBottom: '4px' }}>DENY PATTERNS</label>
                                                    <textarea
                                                        className="input-field"
                                                        value={editingGroup.deny_actions}
                                                        onChange={(e) => setEditingGroup(prev => ({ ...prev, deny_actions: e.target.value }))}
                                                        placeholder="e.g. fs.remove"
                                                        style={{ width: '100%', minHeight: '80px', background: 'rgba(0,0,0,0.2)', padding: '10px', borderRadius: '10px', fontSize: '11px', fontFamily: 'monospace' }}
                                                    />
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {profileEditorTab === 'command_scope' && (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                        <div style={{ padding: '10px', borderRadius: '8px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
                                            <div>
                                                <div style={{ fontSize: '11px', fontWeight: '800' }}>Decision policy for {INTERFACE_META[activeInterface]?.label || activeInterface}</div>
                                                <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Enable/disable approval mediation for sensitive commands.</div>
                                            </div>
                                            <button
                                                className="btn-ghost"
                                                style={{ fontSize: '10px', fontWeight: '800', background: currentApproval.enabled ? soberBg.success : soberBg.danger, color: 'var(--text-main)' }}
                                                onClick={() => handleInterfaceUpdate({ approval_decisions: { ...currentApproval, enabled: !currentApproval.enabled } })}
                                            >
                                                {currentApproval.enabled ? 'Enabled' : 'Disabled'}
                                            </button>
                                        </div>

                                        <div style={{ padding: '10px', borderRadius: '8px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)' }}>
                                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '800', marginBottom: '6px' }}>
                                                Profile command mediation
                                            </div>
                                            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' }}>
                                                {['allow', 'default', 'deny'].map(mode => (
                                                    <button
                                                        key={`approval-mode-${mode}`}
                                                        className="btn-ghost"
                                                        onClick={() => setProfileApprovalMode(editingGroup.id, mode)}
                                                        style={{
                                                            fontSize: '10px',
                                                            fontWeight: '800',
                                                            textTransform: 'uppercase',
                                                            padding: '5px 10px',
                                                            borderRadius: '8px',
                                                            background: getProfileApprovalMode(editingGroup.id) === mode
                                                                ? (mode === 'allow' ? soberBg.success : mode === 'deny' ? soberBg.danger : soberBg.neutral)
                                                                : 'rgba(255,255,255,0.02)',
                                                            color: getProfileApprovalMode(editingGroup.id) === mode ? 'var(--text-main)' : 'var(--text-muted)',
                                                            border: '1px solid var(--card-border)',
                                                        }}
                                                    >
                                                        {mode}
                                                    </button>
                                                ))}
                                            </div>
                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                                Current: <b style={{ color: 'var(--text-main)', textTransform: 'uppercase' }}>{getProfileApprovalMode(editingGroup.id)}</b>
                                            </div>
                                        </div>

                                        <div style={{ padding: '10px', borderRadius: '8px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)' }}>
                                            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                                                {copyInterfaceOptions.map(itf => (
                                                    <button
                                                        key={`copy-profile-scope-${editingGroup.id}-${itf}`}
                                                        className="btn-ghost"
                                                        style={{ fontSize: '10px', fontWeight: '800', padding: '6px 9px', borderRadius: '8px' }}
                                                        onClick={() => handleCopyApprovalToInterface(itf, currentApproval)}
                                                    >
                                                        Copy Policy to {INTERFACE_META[itf]?.label || itf}
                                                    </button>
                                                ))}
                                                <button
                                                    className="btn-ghost"
                                                    style={{ fontSize: '10px', fontWeight: '800', padding: '6px 9px', borderRadius: '8px' }}
                                                    onClick={() => handleCopyApprovalToAll(currentApproval)}
                                                >
                                                    Copy Policy To All
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>

                            <div style={{ padding: isMobile ? '12px 16px' : '16px 24px', background: 'rgba(255,255,255,0.02)', borderTop: '1px solid var(--card-border)', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                                <button onClick={() => { setEditingGroup(null); setShowAdvancedEdit(false); }} className="btn-ghost" style={{ padding: '10px 20px', borderRadius: '10px', fontSize: '12px' }}>Cancel</button>
                                <button onClick={handleSaveGroup} className="btn-primary" style={{ padding: '10px 24px', borderRadius: '10px', fontWeight: '800', fontSize: '12px' }}>Save Changes</button>
                            </div>
                        </div>
                    </div>
                )
            }

            <ConfirmDialog
                isOpen={!!deletingGroup}
                title="Delete ACL Profile"
                message={deletingGroup ? `Are you sure you want to delete the ACL profile "${deletingGroup.name}"?` : ""}
                confirmText="Yes, Delete"
                cancelText="Cancel"
                onConfirm={confirmDeleteGroup}
                onCancel={() => setDeletingGroup(null)}
                isDestructive={true}
            />
        </div >
    );
};

export default Security;
