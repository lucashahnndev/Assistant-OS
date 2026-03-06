import { useState, useEffect } from 'react';
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
    Lock,
    Search as SearchIcon,
    RefreshCw,
    LayoutGrid,
    List,
    SlidersHorizontal
} from 'lucide-react';
import toast from 'react-hot-toast';
import PageHeader from '../components/PageHeader';
import SkillIcon from '../components/SkillIcon';

const SKILLS_VIEW_MODE_KEY = 'skills.hub.view_mode';

const Skills = () => {
    const [skills, setSkills] = useState([]);
    const [loading, setLoading] = useState(true);
    const [configuringSkill, setConfiguringSkill] = useState(null);
    const [detailSkill, setDetailSkill] = useState(null);
    const [configValues, setConfigValues] = useState({});
    const [isSaving, setIsSaving] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [viewMode, setViewMode] = useState(() => {
        try {
            const saved = window.localStorage.getItem(SKILLS_VIEW_MODE_KEY);
            return saved === 'list' ? 'list' : 'grid';
        } catch {
            return 'grid';
        }
    });
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


    useEffect(() => {
        fetchSkills();
    }, []);

    useEffect(() => {
        try {
            window.localStorage.setItem(SKILLS_VIEW_MODE_KEY, viewMode);
        } catch {
            // ignore storage failures
        }
    }, [viewMode]);

    const fetchSkills = async () => {
        try {
            const data = await api.get('/skills/');
            setSkills(data);
        } catch (err) {
            toast.error("Failed to load skills: " + err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleToggle = async (id, currentStatus) => {
        try {
            await api.patch(`/skills/${id}/config`, { enabled: !currentStatus });
            toast.success(`Skill ${!currentStatus ? 'enabled' : 'disabled'}`);
            fetchSkills();
        } catch (err) {
            toast.error(err.message);
        }
    };

    const handleOpenConfig = (skill) => {
        setConfiguringSkill(skill);
        // Ensure we don't clear the config but use what's returned
        setConfigValues(skill.config || {});
    };

    const handleOpenDetails = (skill) => {
        setDetailSkill(skill);
    };

    const handleSaveConfig = async () => {
        setIsSaving(true);
        try {
            await api.patch(`/skills/${configuringSkill.id}/config`, configValues);
            toast.success("Configuration updated successfully!");
            setConfiguringSkill(null);
            fetchSkills();
        } catch (err) {
            const msg = err.response?.data?.detail?.errors?.join(', ') || err.message;
            toast.error("Validation Error: " + msg);
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

    const renderField = (key, schema, path = '') => {
        const fullPath = path ? `${path}.${key}` : key;
        const isSecret = schema['x-secret'] === true;
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
                    {Object.entries(schema.properties).map(([subKey, subSchema]) => renderField(subKey, subSchema, fullPath))}
                </div>
            );
        }

        const widget = ui.widget || (schema.type === 'boolean' ? 'checkbox' : 'text');
        const currentValue = fullPath.split('.').reduce((obj, k) => obj?.[k], configValues);

        return (
            <div key={fullPath} style={{ marginBottom: '9px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>
                    {schema.title || key}
                    {isSecret && <Lock size={12} className="text-accent" />}
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
                        onChange={(e) => updateConfigValue(fullPath, e.target.value)}
                    >
                        {schema.enum?.map(opt => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                ) : (
                    <div style={{ position: 'relative' }}>
                        <input
                            type={widget === 'password' || isSecret ? "password" : "text"}
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
                            onChange={(e) => updateConfigValue(fullPath, e.target.value)}
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
        const schema = configuringSkill?.config_schema;
        if (!schema || !schema.properties) return <p style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>No specific configuration required for this skill.</p>;

        return Object.entries(schema.properties).map(([key, propSchema]) => renderField(key, propSchema));
    };

    const filteredSkills = skills.filter(s =>
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
    const modalOverlayStyle = {
        background: 'rgba(15, 23, 42, 0.10)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        padding: isMobile ? '6px' : '8px',
    };

    return (
        <div className="animate-fade-in" style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <PageHeader
                title="Skills Hub"
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
                            placeholder="Search skills..."
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
                        borderRadius: '10px',
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
                                borderRadius: '8px',
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
                                borderRadius: '8px',
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
                            <p style={{ color: '#64748b' }}>Discovering installed skills...</p>
                        </div>
                    ) : filteredSkills.length > 0 ? filteredSkills.map(skill => (
                        viewMode === 'grid' ? (
                        <div key={skill.id} className="glass-card" style={{
                            padding: isMobile ? '10px' : '10px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '8px',
                            borderRadius: '12px',
                            border: skill.validation_errors?.length > 0 || skill.missing_required?.length > 0
                                ? '1px solid rgba(239, 68, 68, 0.3)'
                                : (!skill.enabled ? '1px solid rgba(148, 163, 184, 0.28)' : '1px solid var(--card-border)'),
                            background: !skill.enabled ? 'linear-gradient(180deg, rgba(148,163,184,0.06), rgba(148,163,184,0.02))' : undefined,
                            opacity: !skill.enabled ? 0.74 : 1,
                            filter: !skill.enabled ? 'grayscale(0.25)' : 'none',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
                                    <SkillIcon
                                        variant="display"
                                        skillId={skill.id}
                                        skillName={skill.name}
                                        iconKey={skill.icon_key}
                                        iconUrl={skill.icon_url}
                                        size={22}
                                    />
                                    <h3 style={{
                                        fontSize: '14px',
                                        fontWeight: '800',
                                        margin: 0,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                        color: !skill.enabled ? '#9ca3af' : 'var(--text-main)',
                                    }}>{skill.name}</h3>
                                </div>
                                {skill.enabled ? (
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
                                {skill.description}
                            </p>

                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                {skill.actions?.slice(0, 2).map(a => (
                                    <span key={a} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.05)', padding: '1px 6px', borderRadius: '100px', color: '#cbd5e1' }}>{a}</span>
                                ))}
                                {skill.actions?.length > 2 && <span style={{ fontSize: '9px', opacity: 0.6 }}>+{skill.actions.length - 2}</span>}
                            </div>

                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                gap: '8px',
                                marginTop: '2px',
                            }}>
                                <button
                                    onClick={() => handleToggle(skill.id, skill.enabled)}
                                    style={{
                                        background: skill.enabled ? 'rgba(16,185,129,0.12)' : 'rgba(148,163,184,0.14)',
                                        border: skill.enabled ? '1px solid rgba(16,185,129,0.35)' : '1px solid rgba(148,163,184,0.28)',
                                        borderRadius: '10px',
                                        cursor: 'pointer',
                                        transition: 'transform 0.2s',
                                        width: '36px',
                                        height: '28px',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                    }}
                                    className="hover:scale-110"
                                    title={skill.enabled ? 'Disable skill' : 'Enable skill'}
                                >
                                    {skill.enabled ? <ToggleRight size={24} color="var(--accent-color)" /> : <ToggleLeft size={24} color="#475569" />}
                                </button>
                                <button
                                    onClick={() => handleOpenDetails(skill)}
                                    className="btn-ghost"
                                    title="Skill details"
                                    aria-label={`Details for ${skill.name}`}
                                    style={{
                                        width: '30px',
                                        minWidth: '30px',
                                        height: '28px',
                                        padding: '0',
                                        justifyContent: 'center',
                                        borderRadius: '8px',
                                    }}
                                >
                                    <SlidersHorizontal size={13} />
                                </button>
                                <button
                                    onClick={() => handleOpenConfig(skill)}
                                    className="btn-secondary"
                                    title="Configure skill"
                                    aria-label={`Configure ${skill.name}`}
                                    style={{
                                        width: '30px',
                                        minWidth: '30px',
                                        height: '28px',
                                        padding: '0',
                                        justifyContent: 'center',
                                        borderRadius: '8px',
                                    }}
                                >
                                    <Settings2 size={13} />
                                </button>
                            </div>

                            {(skill.validation_errors?.length > 0 || skill.missing_required?.length > 0) && (
                                <div style={{ background: 'rgba(239, 68, 68, 0.08)', padding: '7px 8px', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.18)', width: '100%' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f87171', fontSize: '10px', fontWeight: '700', marginBottom: '2px' }}>
                                        <AlertCircle size={11} /> Configuration issue
                                    </div>
                                    <ul style={{ margin: 0, paddingLeft: '16px', fontSize: '10px', color: '#fca5a5' }}>
                                        {skill.missing_required.map(f => <li key={f}>Missing required field: <b>{f}</b></li>)}
                                        {skill.validation_errors.map((e, i) => <li key={i}>{e}</li>)}
                                    </ul>
                                </div>
                            )}
                        </div>
                        ) : (
                            <div key={skill.id} className="glass-card" style={{
                                padding: isMobile ? '10px' : '10px 12px',
                                display: 'flex',
                                flexDirection: isMobile ? 'column' : 'row',
                                alignItems: isMobile ? 'stretch' : 'center',
                                gap: isMobile ? '10px' : '12px',
                                borderRadius: '12px',
                                border: skill.validation_errors?.length > 0 || skill.missing_required?.length > 0
                                    ? '1px solid rgba(239, 68, 68, 0.3)'
                                    : (!skill.enabled ? '1px solid rgba(148, 163, 184, 0.28)' : '1px solid var(--card-border)'),
                                background: !skill.enabled ? 'linear-gradient(180deg, rgba(148,163,184,0.06), rgba(148,163,184,0.02))' : undefined,
                                opacity: !skill.enabled ? 0.74 : 1,
                                filter: !skill.enabled ? 'grayscale(0.22)' : 'none',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
                                    <SkillIcon
                                        variant="display"
                                        skillId={skill.id}
                                        skillName={skill.name}
                                        iconKey={skill.icon_key}
                                        iconUrl={skill.icon_url}
                                        size={24}
                                    />
                                    <div style={{ minWidth: 0, flex: 1 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                                            <h3 style={{ fontSize: '14px', fontWeight: '800', margin: 0, color: !skill.enabled ? '#9ca3af' : 'var(--text-main)' }}>{skill.name}</h3>
                                            {skill.enabled ? (
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
                                            {skill.description}
                                        </p>
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                            {skill.actions?.slice(0, 3).map(a => (
                                                <span key={a} style={{ fontSize: '9px', background: 'rgba(255,255,255,0.05)', padding: '1px 6px', borderRadius: '100px', color: '#cbd5e1' }}>{a}</span>
                                            ))}
                                            {skill.actions?.length > 3 && <span style={{ fontSize: '9px', opacity: 0.6 }}>+{skill.actions.length - 3}</span>}
                                        </div>
                                    </div>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', minWidth: isMobile ? '100%' : '124px' }}>
                                    <button
                                        onClick={() => handleToggle(skill.id, skill.enabled)}
                                        style={{
                                            background: skill.enabled ? 'rgba(16,185,129,0.12)' : 'rgba(148,163,184,0.14)',
                                            border: skill.enabled ? '1px solid rgba(16,185,129,0.35)' : '1px solid rgba(148,163,184,0.28)',
                                            borderRadius: '10px',
                                            cursor: 'pointer',
                                            transition: 'transform 0.2s',
                                            width: '36px',
                                            height: '28px',
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                        }}
                                        className="hover:scale-110"
                                        title={skill.enabled ? 'Disable skill' : 'Enable skill'}
                                    >
                                        {skill.enabled ? <ToggleRight size={24} color="var(--accent-color)" /> : <ToggleLeft size={24} color="#475569" />}
                                    </button>
                                    <button
                                        onClick={() => handleOpenDetails(skill)}
                                        className="btn-ghost"
                                        title="Skill details"
                                        aria-label={`Details for ${skill.name}`}
                                        style={{
                                            width: '30px',
                                            minWidth: '30px',
                                            height: '28px',
                                            padding: '0',
                                            justifyContent: 'center',
                                            borderRadius: '8px',
                                        }}
                                    >
                                        <SlidersHorizontal size={13} />
                                    </button>
                                    <button
                                        onClick={() => handleOpenConfig(skill)}
                                        className="btn-secondary"
                                        title="Configure skill"
                                        aria-label={`Configure ${skill.name}`}
                                        style={{
                                            width: '30px',
                                            minWidth: '30px',
                                            height: '28px',
                                            padding: '0',
                                            justifyContent: 'center',
                                            borderRadius: '8px',
                                        }}
                                    >
                                        <Settings2 size={13} />
                                    </button>
                                </div>
                            </div>
                        )
                    )) : (
                        <div style={{ textAlign: 'center', marginTop: '60px', gridColumn: '1 / -1' }}>
                            <Puzzle size={64} style={{ marginBottom: '24px', opacity: 0.2, margin: '0 auto' }} />
                            <h4 style={{ fontSize: '20px', color: '#94a3b8' }}>No skills discovered</h4>
                        </div>
                    )}
                </div>
            </div>

            {/* Modal - Unified Standard */}
            {detailSkill && (
                <div className="modal-overlay" style={modalOverlayStyle} onClick={() => setDetailSkill(null)}>
                    <div className="modal-content glass" onClick={e => e.stopPropagation()} style={modalShellStyle}>
                        <div style={{ padding: isMobile ? '10px 10px' : '12px 14px', borderBottom: '1px solid var(--card-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <SkillIcon
                                    variant="display"
                                    skillId={detailSkill.id}
                                    skillName={detailSkill.name}
                                    iconKey={detailSkill.icon_key}
                                    iconUrl={detailSkill.icon_url}
                                    size={isMobile ? 24 : 28}
                                />
                                <div>
                                    <h3 style={{ fontSize: isMobile ? '14px' : '16px', fontWeight: '800', color: 'var(--text-main)', margin: 0 }}>{detailSkill.name}</h3>
                                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '2px 0 0' }}>{detailSkill.id}</p>
                                </div>
                            </div>
                            <button onClick={() => setDetailSkill(null)} className="btn-ghost" style={{ padding: '6px' }}>
                                <X size={19} />
                            </button>
                        </div>

                        <div className="custom-scrollbar" style={{ flex: 1, minHeight: 0, padding: isMobile ? '10px 10px 12px' : '14px 16px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: isMobile ? '10px' : '12px' }}>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                {detailSkill.enabled ? (
                                    <span className="badge badge-success">Active</span>
                                ) : (
                                    <span className="badge badge-slate">Disabled</span>
                                )}
                                {detailSkill.validation_errors?.length > 0 || detailSkill.missing_required?.length > 0 ? (
                                    <span className="badge" style={{ background: 'rgba(239,68,68,0.15)', color: '#f87171', border: '1px solid rgba(239,68,68,0.25)' }}>Validation issue</span>
                                ) : (
                                    <span className="badge" style={{ background: 'rgba(34,197,94,0.14)', color: '#86efac', border: '1px solid rgba(34,197,94,0.25)' }}>Validated</span>
                                )}
                                <span className="badge badge-slate">{(detailSkill.actions || []).length} actions</span>
                            </div>

                            <div style={{ border: '1px solid var(--card-border)', borderRadius: '10px', padding: '12px' }}>
                                <div style={{ fontSize: '11px', fontWeight: '900', letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>Description</div>
                                <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-main)', lineHeight: '1.5' }}>{detailSkill.description || 'No description provided.'}</p>
                            </div>

                            <div style={{ border: '1px solid var(--card-border)', borderRadius: '10px', padding: '12px' }}>
                                <div style={{ fontSize: '11px', fontWeight: '900', letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>Actions</div>
                                {(detailSkill.actions || []).length > 0 ? (
                                    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, minmax(0, 1fr))', gap: '6px' }}>
                                        {(detailSkill.actions || []).map((action) => (
                                            <div key={action} style={{ fontSize: '12px', color: '#cbd5e1', background: 'rgba(255,255,255,0.03)', border: '1px solid var(--card-border)', borderRadius: '8px', padding: '6px 8px', fontFamily: 'monospace' }}>
                                                {action}
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)' }}>No actions mapped.</p>
                                )}
                            </div>

                            <div style={{ border: '1px solid var(--card-border)', borderRadius: '10px', padding: '12px' }}>
                                <div style={{ fontSize: '11px', fontWeight: '900', letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '8px' }}>Config Snapshot</div>
                                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: '11px', color: '#cbd5e1', lineHeight: '1.4' }}>
                                    {JSON.stringify(detailSkill.config || {}, null, 2)}
                                </pre>
                            </div>

                            {(detailSkill.validation_errors?.length > 0 || detailSkill.missing_required?.length > 0) && (
                                <div style={{ background: 'rgba(239, 68, 68, 0.08)', padding: '10px 12px', borderRadius: '10px', border: '1px solid rgba(239, 68, 68, 0.18)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#f87171', fontSize: '11px', fontWeight: '700', marginBottom: '4px' }}>
                                        <AlertCircle size={12} /> Validation details
                                    </div>
                                    <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '11px', color: '#fca5a5' }}>
                                        {(detailSkill.missing_required || []).map(f => <li key={f}>Missing required field: <b>{f}</b></li>)}
                                        {(detailSkill.validation_errors || []).map((e, i) => <li key={i}>{e}</li>)}
                                    </ul>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Modal - Unified Standard */}
            {configuringSkill && (
                <div className="modal-overlay" style={modalOverlayStyle} onClick={() => setConfiguringSkill(null)}>
                    <div className="modal-content glass" onClick={e => e.stopPropagation()} style={configModalShellStyle}>
                        <div style={{ padding: isMobile ? '12px 12px' : '14px 16px', borderBottom: '1px solid var(--card-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <SkillIcon
                                    variant="display"
                                    skillId={configuringSkill.id}
                                    skillName={configuringSkill.name}
                                    iconKey={configuringSkill.icon_key}
                                    iconUrl={configuringSkill.icon_url}
                                    size={isMobile ? 24 : 28}
                                />
                                <div>
                                    <h3 style={{ fontSize: isMobile ? '14px' : '15px', fontWeight: '800', color: 'var(--text-main)' }}>{configuringSkill.name}</h3>
                                    <p style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Configuration</p>
                                </div>
                            </div>
                            <button onClick={() => setConfiguringSkill(null)} className="btn-ghost" style={{ padding: '6px' }}>
                                <X size={20} />
                            </button>
                        </div>

                        <div className="custom-scrollbar" style={{ flex: 1, minHeight: 0, padding: isMobile ? '8px' : '8px 10px', overflowY: 'auto' }}>
                            {renderConfigForm()}
                        </div>

                        <div style={{ padding: isMobile ? '8px 10px' : '8px 12px', borderTop: '1px solid var(--card-border)', background: 'rgba(0,0,0,0.04)', display: 'flex', justifyContent: 'flex-end', gap: '7px', borderBottomLeftRadius: isMobile ? '10px' : '12px', borderBottomRightRadius: isMobile ? '10px' : '12px' }}>
                            <button onClick={() => setConfiguringSkill(null)} className="btn-ghost" style={{ padding: isMobile ? '7px 10px' : '8px 12px' }}>Cancel</button>
                            <button
                                onClick={handleSaveConfig}
                                className="btn-primary"
                                disabled={isSaving}
                                style={{ padding: isMobile ? '7px 10px' : '8px 12px', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}
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

export default Skills;
