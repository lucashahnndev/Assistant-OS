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
    RefreshCw
} from 'lucide-react';
import toast from 'react-hot-toast';
import PageHeader from '../components/PageHeader';

const Skills = () => {
    const [skills, setSkills] = useState([]);
    const [loading, setLoading] = useState(true);
    const [configuringSkill, setConfiguringSkill] = useState(null);
    const [configValues, setConfigValues] = useState({});
    const [isSaving, setIsSaving] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
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
                    marginBottom: '32px',
                    padding: '24px',
                    background: 'rgba(255,255,255,0.01)',
                    borderRadius: '16px',
                    border: '1px solid rgba(255,255,255,0.05)'
                }}>
                    <h4 style={{
                        fontSize: '13px',
                        fontWeight: '800',
                        marginBottom: '20px',
                        color: 'var(--accent-color)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.1em',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px'
                    }}>
                        <div style={{ width: '4px', height: '4px', background: 'var(--accent-color)', borderRadius: '50%' }}></div>
                        {schema.title || key}
                    </h4>
                    {Object.entries(schema.properties).map(([subKey, subSchema]) => renderField(subKey, subSchema, fullPath))}
                </div>
            );
        }

        const widget = ui.widget || (schema.type === 'boolean' ? 'checkbox' : 'text');
        const currentValue = fullPath.split('.').reduce((obj, k) => obj?.[k], configValues);

        return (
            <div key={fullPath} style={{ marginBottom: '24px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', fontSize: '14px', fontWeight: '600', color: 'var(--text-main)' }}>
                    {schema.title || key}
                    {isSecret && <Lock size={12} className="text-accent" />}
                </label>

                {schema.description && (
                    <p style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '12px', lineHeight: '1.5' }}>
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
                                padding: '12px 16px',
                                paddingRight: isSecret ? '40px' : '16px',
                                background: 'var(--bg-color)',
                                border: '1px solid var(--card-border)',
                                borderRadius: '8px',
                                color: 'var(--text-main)'
                            }}
                            placeholder={ui.placeholder || schema.default || ''}
                            value={currentValue || ''}
                            onChange={(e) => updateConfigValue(fullPath, e.target.value)}
                        />
                        {isSecret && <div style={{ position: 'absolute', right: '12px', top: '12px', opacity: 0.5 }}><Shield size={16} /></div>}
                    </div>
                )}

                {currentValue === '********' && (
                    <p style={{ fontSize: '11px', color: 'var(--accent-color)', marginTop: '8px' }}>
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

    return (
        <div className="animate-fade-in" style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <PageHeader
                title="Skills Hub"
                subtitle="Manage and monitor your agent's modular capabilities."
            >
                <div style={{ position: 'relative', width: '100%', maxWidth: '320px' }} className="full-width-mobile">
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
            </PageHeader>

            <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto', padding: isMobile ? '0 var(--space-2)' : '0 var(--space-4)' }}>
                <div className="skills-grid" style={{
                    display: 'grid',
                    gridTemplateColumns: isMobile ? '1fr' : (isTablet ? 'repeat(2, 1fr)' : 'repeat(auto-fill, minmax(360px, 1fr))'),
                    gap: '20px',
                    paddingBottom: '100px',
                    padding: isMobile ? '12px' : '0'
                }}>
                    {loading ? (
                        <div style={{ gridColumn: '1/-1', textAlign: 'center', padding: '100px' }}>
                            <div className="loading-spinner" style={{ margin: '0 auto 20px' }}></div>
                            <p style={{ color: '#64748b' }}>Discovering installed skills...</p>
                        </div>
                    ) : skills.length > 0 ? skills.filter(s =>
                        s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        s.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
                        s.actions?.some(a => a.toLowerCase().includes(searchQuery.toLowerCase()))
                    ).map(skill => (
                        <div key={skill.id} className="glass-card" style={{
                            padding: 'var(--space-6)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 'var(--space-4)',
                            borderRadius: 'var(--radius-md)',
                            border: skill.validation_errors?.length > 0 || skill.missing_required?.length > 0 ? '1px solid rgba(239, 68, 68, 0.3)' : '1px solid var(--card-border)'
                        }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                    <h3 style={{ fontSize: '20px', fontWeight: '700' }}>{skill.name}</h3>
                                    {skill.enabled ? (
                                        <span className="badge badge-success">Active</span>
                                    ) : (
                                        <span className="badge badge-slate">Disabled</span>
                                    )}
                                </div>
                                <button
                                    onClick={() => handleToggle(skill.id, skill.enabled)}
                                    style={{ background: 'transparent', border: 'none', cursor: 'pointer', transition: 'transform 0.2s' }}
                                    className="hover:scale-110"
                                >
                                    {skill.enabled ? <ToggleRight size={36} color="var(--accent-color)" /> : <ToggleLeft size={36} color="#475569" />}
                                </button>
                            </div>

                            <p style={{ fontSize: '14px', color: '#94a3b8', lineHeight: '1.6', flex: 1 }}>{skill.description}</p>

                            {(skill.validation_errors?.length > 0 || skill.missing_required?.length > 0) && (
                                <div style={{ background: 'rgba(239, 68, 68, 0.1)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#f87171', fontSize: '12px', fontWeight: '600', marginBottom: '4px' }}>
                                        <AlertCircle size={14} /> Configuration Issue
                                    </div>
                                    <ul style={{ margin: 0, paddingLeft: '22px', fontSize: '11px', color: '#fca5a5' }}>
                                        {skill.missing_required.map(f => <li key={f}>Missing required field: <b>{f}</b></li>)}
                                        {skill.validation_errors.map((e, i) => <li key={i}>{e}</li>)}
                                    </ul>
                                </div>
                            )}

                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                {skill.actions?.slice(0, 3).map(a => (
                                    <span key={a} style={{ fontSize: '10px', background: 'rgba(255,255,255,0.05)', padding: '2px 8px', borderRadius: '100px', color: '#cbd5e1' }}>{a}</span>
                                ))}
                                {skill.actions?.length > 3 && <span style={{ fontSize: '10px', opacity: 0.5 }}>+{skill.actions.length - 3} mais</span>}
                            </div>

                            <button
                                onClick={() => handleOpenConfig(skill)}
                                className="btn-secondary"
                                style={{ width: '100%', marginTop: '8px' }}
                            >
                                <Settings2 size={16} /> Configure
                            </button>
                        </div>
                    )) : (
                        <div style={{ gridColumn: '1/-1', textAlign: 'center', marginTop: '60px' }}>
                            <Puzzle size={64} style={{ marginBottom: '24px', opacity: 0.2, margin: '0 auto' }} />
                            <h4 style={{ fontSize: '20px', color: '#94a3b8' }}>No skills discovered</h4>
                        </div>
                    )}
                </div>
            </div>

            {/* Modal - Unified Standard */}
            {configuringSkill && (
                <div className="modal-overlay" onClick={() => setConfiguringSkill(null)}>
                    <div className="modal-content glass" onClick={e => e.stopPropagation()} style={{ width: 'min(90vw, 600px)', maxHeight: '85vh' }}>
                        <div style={{ padding: '24px 32px', borderBottom: '1px solid var(--card-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                <div style={{ padding: '8px', background: 'var(--accent-glow)', borderRadius: '10px', color: 'var(--accent-color)' }}>
                                    <Settings2 size={20} />
                                </div>
                                <div>
                                    <h3 style={{ fontSize: '18px', fontWeight: '800', color: 'var(--text-main)' }}>{configuringSkill.name}</h3>
                                    <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Advanced Neural Parameters</p>
                                </div>
                            </div>
                            <button onClick={() => setConfiguringSkill(null)} className="btn-ghost" style={{ padding: '8px' }}>
                                <X size={20} />
                            </button>
                        </div>

                        <div className="custom-scrollbar" style={{ flex: 1, padding: '32px', overflowY: 'auto' }}>
                            {renderConfigForm()}
                        </div>

                        <div style={{ padding: '24px 32px', borderTop: '1px solid var(--card-border)', background: 'rgba(0,0,0,0.1)', display: 'flex', justifyContent: 'flex-end', gap: '12px', borderBottomLeftRadius: '24px', borderBottomRightRadius: '24px' }}>
                            <button onClick={() => setConfiguringSkill(null)} className="btn-ghost" style={{ padding: '10px 20px' }}>Cancel</button>
                            <button
                                onClick={handleSaveConfig}
                                className="btn-primary"
                                disabled={isSaving}
                                style={{ padding: '10px 24px', borderRadius: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}
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

