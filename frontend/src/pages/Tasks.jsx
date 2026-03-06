import { useState, useEffect } from 'react';
import { api } from '../hooks/api';
import toast from 'react-hot-toast';
import {
    Activity,
    Plus,
    LayoutGrid,
    List,
    Brain,
    Wrench,
    AlertTriangle,
    CheckCircle2,
    CircleDot,
    Clock3,
    Code2,
    Terminal,
    Pause,
    Play,
    X,
    XCircle,
    Clock,
    Search
} from 'lucide-react';
import TaskDetails from '../components/tasks/TaskDetails';
import PageHeader from '../components/PageHeader';
import SkillIcon from '../components/SkillIcon';

const TASKS_LAYOUT_MODE_KEY = 'tasks_layout_mode';

const Tasks = () => {
    const [tasks, setTasks] = useState([]);
    const [works, setWorks] = useState([]);
    const [activeAgents, setActiveAgents] = useState([]);
    const [selectedTaskId, setSelectedTaskId] = useState(null);
    const [loading, setLoading] = useState(true);
    const [showNewTaskModal, setShowNewTaskModal] = useState(false);
    const [newTaskName, setNewTaskName] = useState('');
    const [newTaskContext, setNewTaskContext] = useState('');
    const [selectedWorkId, setSelectedWorkId] = useState(null);
    const [workOverwatch, setWorkOverwatch] = useState(null);
    const [overwatchTab, setOverwatchTab] = useState('overview');
    const [queuedMessage, setQueuedMessage] = useState('');
    const [workNote, setWorkNote] = useState('');
    const [workViewTab, setWorkViewTab] = useState('live'); // live | archive
    const [plannerViewMode, setPlannerViewMode] = useState('checklist'); // checklist | raw
    const [workKeywordFilter, setWorkKeywordFilter] = useState('');
    const [isOverviewThoughtExpanded, setIsOverviewThoughtExpanded] = useState(false);
    const [workTypeFilter, setWorkTypeFilter] = useState('all'); // all | no-cron | cron | manual | automated | media | active | completed
    const [layoutMode, setLayoutMode] = useState(() => {
        try {
            const saved = window.localStorage.getItem(TASKS_LAYOUT_MODE_KEY);
            return saved === 'list' ? 'list' : 'grid';
        } catch {
            return 'grid';
        }
    });
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);
    const [isNarrowHeader, setIsNarrowHeader] = useState(window.innerWidth < 1120);
    const [isCompactHeader, setIsCompactHeader] = useState(window.innerWidth < 1280);

    useEffect(() => {
        const handleResize = () => {
            setIsMobile(window.innerWidth <= 640);
            setIsNarrowHeader(window.innerWidth < 1120);
            setIsCompactHeader(window.innerWidth < 1280);
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    const fetchData = async () => {
        try {
            const [tasksRes, worksRes] = await Promise.all([
                api.get('/tasks/definitions'),
                api.get('/tasks/works?include_completed=true&limit=120')
            ]);
            setTasks(tasksRes);
            const normalizedWorks = Array.isArray(worksRes) ? worksRes : [];
            setWorks(normalizedWorks);
            setActiveAgents(
                normalizedWorks.filter(w => ['queued', 'running', 'waiting_user'].includes((w?.status || '').toLowerCase()))
            );
        } catch (error) {
            console.error("Error fetching data:", error);
            // toast.error("Failed to load tasks"); // suppress noise
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 5000);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        if (!selectedWorkId) return undefined;
        const interval = setInterval(() => {
            loadWorkOverwatch(selectedWorkId, { preserveTab: true, silent: true });
        }, 1800);
        return () => clearInterval(interval);
    }, [selectedWorkId]);

    useEffect(() => {
        if (overwatchTab !== 'planner') return;
        setPlannerViewMode('checklist');
    }, [selectedWorkId, overwatchTab]);

    useEffect(() => {
        if (overwatchTab !== 'overview') return;
        setIsOverviewThoughtExpanded(false);
    }, [selectedWorkId, overwatchTab]);

    useEffect(() => {
        try {
            window.localStorage.setItem(TASKS_LAYOUT_MODE_KEY, layoutMode);
        } catch {
            // no-op
        }
    }, [layoutMode]);

    const handleCreateTask = async (e) => {
        e.preventDefault();
        const name = String(newTaskName || '').trim();
        const context = String(newTaskContext || '').trim();
        if (!name || !context) {
            toast.error("Task name and context are required");
            return;
        }
        try {
            const res = await api.post('/tasks/definitions', {
                name,
                context
            });
            toast.success("Task definition created");
            setNewTaskName('');
            setNewTaskContext('');
            setShowNewTaskModal(false);

            // Optimistic local update so manual creation is visible immediately.
            if (res && res.task_id) {
                setTasks(prev => {
                    const alreadyExists = prev.some(t => t.task_id === res.task_id);
                    return alreadyExists ? prev : [res, ...prev];
                });
                setSelectedTaskId(res.task_id);
            }

            // Sync with backend in background (works endpoint may fail independently).
            fetchData();
        } catch (error) {
            toast.error(error?.message || "Failed to create task");
        }
    };

    const handleTaskDeleted = () => {
        setSelectedTaskId(null);
        fetchData();
    };

    const loadWorkOverwatch = async (workId, opts = {}) => {
        const preserveTab = Boolean(opts?.preserveTab);
        const silent = Boolean(opts?.silent);
        try {
            const data = await api.get(`/tasks/works/${workId}/overwatch?events_limit=300`);
            setWorkOverwatch(data);
            setSelectedWorkId(workId);
            if (!preserveTab) setOverwatchTab('overview');
        } catch (error) {
            if (!silent) toast.error("Failed to load worker overwatch");
        }
    };

    const renderHeader = () => (
        <PageHeader
            title="Tasks"
            subtitle="Worker fleet and execution history."
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
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                    <div
                        style={{
                            height: '34px',
                            padding: '0 12px',
                            borderRadius: '9px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '8px',
                            background: 'rgba(255,255,255,0.02)',
                            border: 'none',
                            color: 'var(--text-main)',
                            fontSize: '13px',
                            fontWeight: '700',
                            whiteSpace: 'nowrap',
                        }}
                    >
                        <Activity size={13} color="var(--success)" className={activeAgents.length > 0 ? "animate-pulse" : ""} />
                        <span>{activeAgents.length} ativas de {works.length}</span>
                    </div>
                </div>

                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        marginLeft: isNarrowHeader ? '0' : 'auto',
                        minWidth: 0,
                        width: isNarrowHeader ? '100%' : 'auto',
                        justifyContent: isNarrowHeader ? 'space-between' : 'flex-end',
                        flexWrap: 'nowrap',
                    }}
                >
                    <div style={{ display: 'flex', gap: '4px', padding: '3px', borderRadius: '9px', border: '1px solid var(--card-border)', background: 'rgba(255,255,255,0.02)', flexShrink: 0 }}>
                        {['live', 'archive'].map(tab => (
                            <button
                                key={tab}
                                onClick={() => setWorkViewTab(tab)}
                                className="btn-ghost"
                                style={{
                                    padding: '6px 8px',
                                    fontSize: '12px',
                                    fontWeight: '700',
                                    borderRadius: '7px',
                                    transition: 'var(--transition-fast)',
                                    background: workViewTab === tab ? 'var(--accent-glow)' : 'transparent',
                                    color: workViewTab === tab ? 'var(--accent-color)' : 'var(--text-muted)',
                                    textTransform: 'capitalize',
                                    border: 'none',
                                }}
                            >
                                {tab}
                            </button>
                        ))}
                    </div>

                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        border: '1px solid var(--card-border)',
                        borderRadius: '10px',
                        padding: '3px',
                        background: 'rgba(255,255,255,0.02)',
                        flexShrink: 0,
                    }}>
                        <button
                            className="btn-ghost"
                            onClick={() => setLayoutMode('grid')}
                            title="Grid view"
                            style={{
                                padding: '6px 8px',
                                borderRadius: '8px',
                                background: layoutMode === 'grid' ? 'var(--accent-glow)' : 'transparent',
                                color: layoutMode === 'grid' ? 'var(--accent-color)' : 'var(--text-muted)'
                            }}
                        >
                            <LayoutGrid size={14} />
                        </button>
                        <button
                            className="btn-ghost"
                            onClick={() => setLayoutMode('list')}
                            title="List view"
                            style={{
                                padding: '6px 8px',
                                borderRadius: '8px',
                                background: layoutMode === 'list' ? 'var(--accent-glow)' : 'transparent',
                                color: layoutMode === 'list' ? 'var(--accent-color)' : 'var(--text-muted)'
                            }}
                        >
                            <List size={14} />
                        </button>
                    </div>

                    <div style={{ position: 'relative', width: isNarrowHeader ? 'calc(100% - 196px)' : isCompactHeader ? '220px' : '280px', minWidth: 0 }}>
                        <Search size={14} style={{ position: 'absolute', left: '10px', top: '10px', opacity: 0.5, pointerEvents: 'none' }} />
                        <input
                            type="text"
                            value={workKeywordFilter}
                            onChange={(e) => setWorkKeywordFilter(e.target.value)}
                            placeholder="Search workers..."
                            className="input-field"
                            style={{
                                width: '100%',
                                paddingLeft: '32px',
                                fontSize: '13px',
                                borderRadius: '8px',
                                height: '34px',
                            }}
                        />
                    </div>

                    <button
                        onClick={() => setShowNewTaskModal(true)}
                        className="btn-primary"
                        title="New task"
                        aria-label="New task"
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
                            fontWeight: '800',
                        }}
                    >
                        <Plus size={16} />
                    </button>
                </div>
            </div>
        </PageHeader>
    );

    const renderWorksMonitor = () => {
        const classifyWork = (work) => {
            const status = String(work?.status || '').toLowerCase();
            const isCompleted = ['succeeded', 'failed', 'cancelled'].includes(status);
            const isActive = ['queued', 'running', 'waiting_user', 'paused'].includes(status);
            const data = work?.context?.data || {};
            const isScheduled = data.origin === 'scheduled' || Boolean(data.task_id);
            const hasCron = Boolean(data.trigger_id);
            const isManualTaskRun = isScheduled && !hasCron;
            const isArchived = isCompleted && !isManualTaskRun;
            const key = String(work?.key || '').toLowerCase();
            return { isCompleted, isActive, isScheduled, hasCron, isManualTaskRun, isArchived };
        };

        const matchesFilters = (work) => {
            const keyword = String(workKeywordFilter || '').trim().toLowerCase();
            if (keyword) {
                const blob = [work?.label, work?.key, work?.work_id, work?.status].map(v => String(v || '')).join(' ').toLowerCase();
                if (!blob.includes(keyword)) return false;
            }
            return true;
        };

        const archiveWorks = works.filter(w => classifyWork(w).isArchived && matchesFilters(w));
        const liveWorks = works.filter(w => !classifyWork(w).isArchived && matchesFilters(w));
        const topActive = liveWorks.filter(w => ['queued', 'running', 'waiting_user', 'paused'].includes(String(w?.status || '').toLowerCase())).slice(0, 8);

        const sendCommand = async (workId, command, payload = {}) => {
            try {
                await api.post(`/tasks/works/${workId}/commands`, { command, payload });
                toast.success(`Sent ${command}`);
                fetchData();
            } catch {
                toast.error("Failed to send command");
            }
        };

        const WorkerCard = ({ work }) => {
            const summary = work?.context?.summary || {};
            const status = String(work.status).toLowerCase();
            const getStatusColor = () => {
                if (status === 'running') return 'var(--accent-color)';
                if (status === 'waiting_user') return 'var(--warning)';
                if (status === 'paused') return 'var(--text-muted)';
                if (status === 'failed') return 'var(--error)';
                if (status === 'succeeded') return 'var(--success)';
                return 'var(--text-muted)';
            };

            return (
                <div className="glass" style={{
                    padding: '16px',
                    borderRadius: '8px',
                    background: 'rgba(255,255,255,0.01)',
                    border: '1px solid var(--card-border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px',
                    transition: 'var(--transition-fast)',
                    position: 'relative',
                    overflow: 'hidden'
                }} onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--accent-color)'}
                    onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--card-border)'}>

                    <div style={{ position: 'absolute', top: 0, left: 0, width: '4px', height: '100%', background: getStatusColor() }}></div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div>
                            <div style={{ fontSize: '13px', fontWeight: '900', color: 'var(--text-primary)', marginBottom: '2px' }}>
                                {work.label || work.key}
                            </div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <Terminal size={10} /> {work.work_id.slice(0, 8)}...
                            </div>
                        </div>
                        <div style={{
                            fontSize: '10px',
                            fontWeight: '800',
                            padding: '4px 8px',
                            borderRadius: '6px',
                            background: `${getStatusColor()}15`,
                            color: getStatusColor(),
                            textTransform: 'uppercase'
                        }}>
                            {status}
                        </div>
                    </div>

                    <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.4', height: '34px', overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                        {summary.last_thought || summary.cursor || 'Operation standby...'}
                    </p>

                    <div style={{ display: 'flex', gap: '6px', marginTop: '4px' }}>
                        <button className="btn-ghost" style={{ flex: 1, padding: '6px', fontSize: '10px', fontWeight: '800', background: 'rgba(255,255,255,0.03)' }} onClick={() => loadWorkOverwatch(work.work_id)}>
                            DETAILS
                        </button>
                        {status === 'waiting_user' && (
                            <button className="btn-primary" style={{ padding: '6px 12px', fontSize: '10px', fontWeight: '800' }} onClick={() => sendCommand(work.work_id, 'approve')}>
                                APPROVE
                            </button>
                        )}
                        {['running', 'waiting_user'].includes(status) && (
                            <button className="btn-ghost" style={{ padding: '6px', color: 'var(--error)' }} onClick={() => sendCommand(work.work_id, 'cancel')}>
                                <XCircle size={14} />
                            </button>
                        )}
                    </div>
                </div >
            );
        };

        const ArchiveRow = ({ work }) => (
            <div className="table-row-hover" style={{
                display: 'flex',
                alignItems: 'center',
                padding: '12px 16px',
                borderRadius: '8px',
                background: 'rgba(255,255,255,0.01)',
                border: '1px solid var(--card-border)',
                gap: '16px'
            }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: work.status === 'succeeded' ? 'var(--success)' : 'var(--error)', flexShrink: 0 }}></div>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '13px', fontWeight: '700' }}>{work.label || work.key}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{work.work_id} · {work.status}</div>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', flex: 2, display: 'none', md: 'block' }}>
                    {String(work.context?.summary?.last_thought || '-').slice(0, 100)}...
                </div>
                <button className="btn-ghost" style={{ padding: '6px 12px', fontSize: '11px' }} onClick={() => loadWorkOverwatch(work.work_id)}>Open</button>
            </div>
        );

        const ActiveRow = ({ work }) => {
            const status = String(work.status).toLowerCase();
            return (
                <div className="table-row-hover" style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '10px 12px',
                    borderRadius: '8px',
                    background: 'rgba(255,255,255,0.01)',
                    border: '1px solid var(--card-border)',
                    gap: '12px'
                }}>
                    <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: status === 'running' ? 'var(--accent-color)' : status === 'waiting_user' ? 'var(--warning)' : 'var(--text-muted)', flexShrink: 0 }}></div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: '13px', fontWeight: '700', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{work.label || work.key}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{work.work_id.slice(0, 8)}... · {status}</div>
                    </div>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <button className="btn-ghost" style={{ padding: '6px 10px', fontSize: '11px' }} onClick={() => loadWorkOverwatch(work.work_id)}>
                            Details
                        </button>
                        {status === 'waiting_user' && (
                            <button className="btn-primary" style={{ padding: '6px 10px', fontSize: '11px' }} onClick={() => sendCommand(work.work_id, 'approve')}>
                                Approve
                            </button>
                        )}
                        {['running', 'waiting_user'].includes(status) && (
                            <button className="btn-ghost" style={{ padding: '6px', color: 'var(--error)' }} onClick={() => sendCommand(work.work_id, 'cancel')}>
                                <XCircle size={13} />
                            </button>
                        )}
                    </div>
                </div>
            );
        };

        if (workViewTab === 'archive') {
            return (
                <div style={{ padding: '0 var(--space-6)', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
                    <h3 style={{ fontSize: '0.875rem', fontWeight: '800', margin: '0 0 12px 0', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)' }}>
                        <Clock size={16} /> History
                    </h3>
                    <div
                        className="custom-scrollbar"
                        style={{
                            overflowY: 'auto',
                            flex: 1,
                            minHeight: 0,
                            display: layoutMode === 'grid' ? 'grid' : 'flex',
                            gridTemplateColumns: layoutMode === 'grid' ? 'repeat(auto-fill, minmax(280px, 1fr))' : undefined,
                            flexDirection: layoutMode === 'list' ? 'column' : undefined,
                            gap: '12px',
                            alignContent: 'start',
                        }}
                    >
                        {archiveWorks.map(work => (
                            layoutMode === 'grid' ? (
                                <div key={work.work_id} className="glass" style={{
                                    padding: '14px',
                                    borderRadius: '8px',
                                    background: 'rgba(255,255,255,0.01)',
                                    border: '1px solid var(--card-border)',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '8px'
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                                        <div style={{ fontSize: '13px', fontWeight: '800', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{work.label || work.key}</div>
                                        <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: work.status === 'succeeded' ? 'var(--success)' : 'var(--error)', flexShrink: 0 }}></div>
                                    </div>
                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{work.work_id.slice(0, 8)}... · {work.status}</div>
                                    <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.35, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                                        {String(work.context?.summary?.last_thought || 'No summary.')}
                                    </p>
                                    <button className="btn-ghost" style={{ marginTop: '2px', padding: '6px 10px', fontSize: '11px', alignSelf: 'flex-start' }} onClick={() => loadWorkOverwatch(work.work_id)}>
                                        Open
                                    </button>
                                </div>
                            ) : (
                                <ArchiveRow key={work.work_id} work={work} />
                            )
                        ))}
                    </div>
                </div>
            );
        }

        return (
            <div style={{ padding: '0 var(--space-6)', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
                <div
                    className="custom-scrollbar"
                    style={{
                        overflowY: 'auto',
                        flex: 1,
                        minHeight: 0,
                        display: layoutMode === 'grid' ? 'grid' : 'flex',
                        gridTemplateColumns: layoutMode === 'grid' ? 'repeat(auto-fill, minmax(280px, 1fr))' : undefined,
                        flexDirection: layoutMode === 'list' ? 'column' : undefined,
                        gap: layoutMode === 'grid' ? '16px' : '12px',
                        alignContent: 'start',
                    }}
                >
                    {topActive.length > 0 ? topActive.map(work => (
                        layoutMode === 'grid' ? (
                            <WorkerCard key={work.work_id} work={work} />
                        ) : (
                            <ActiveRow key={work.work_id} work={work} />
                        )
                    )) : (
                        <div
                            style={{
                                gridColumn: layoutMode === 'grid' ? '1 / -1' : undefined,
                                minHeight: '100%',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                textAlign: 'center',
                                border: 'none',
                                boxShadow: 'none',
                                background: 'transparent',
                            }}
                        >
                            <p style={{ color: 'var(--text-muted)', fontSize: '12px', margin: 0 }}>No active workers.</p>
                        </div>
                    )}
                </div>
            </div>
        );
    };

    const renderOverwatchModal = () => {
        if (!selectedWorkId || !workOverwatch) return null;

        const work = workOverwatch.work || {};
        const summary = workOverwatch.summary || {};
        const planner = workOverwatch.planner || {};
        const events = workOverwatch.events || [];
        const task = workOverwatch.task || {};
        const origin = workOverwatch.origin || {};
        const skills = workOverwatch.skills_used || [];
        const media = workOverwatch.media_used || [];
        const queued = workOverwatch.queued_messages || [];
        const notes = (work?.context?.notes || []);
        const recentExecutions = workOverwatch.recent_executions || [];

        const queueMsg = async (direct = false) => {
            if (!queuedMessage.trim()) return;
            const path = direct ? 'direct_message' : 'queue_message';
            try {
                await api.post(`/tasks/works/${selectedWorkId}/${path}`, { note: queuedMessage.trim() });
                toast.success(direct ? "Direct message sent" : "Message queued");
                setQueuedMessage('');
                loadWorkOverwatch(selectedWorkId);
            } catch {
                toast.error("Failed to send message");
            }
        };

        const saveNote = async () => {
            if (!workNote.trim()) return;
            try {
                await api.post(`/tasks/works/${selectedWorkId}/notes`, { note: workNote.trim() });
                toast.success("Note saved");
                setWorkNote('');
                loadWorkOverwatch(selectedWorkId);
            } catch {
                toast.error("Failed to save note");
            }
        };

        const pause = async () => { await api.post(`/tasks/works/${selectedWorkId}/pause`); loadWorkOverwatch(selectedWorkId); fetchData(); };
        const resume = async () => { await api.post(`/tasks/works/${selectedWorkId}/resume`); loadWorkOverwatch(selectedWorkId); fetchData(); };
        const isPaused = String(work.status).toLowerCase() === 'paused';
        const formatFlowDateTime = (value) => {
            const d = new Date(value);
            if (Number.isNaN(d.getTime())) return String(value || '-');
            return `${d.toLocaleDateString()} ${d.toLocaleTimeString()}`;
        };
        const toMs = (value) => {
            const t = Date.parse(String(value || ''));
            return Number.isNaN(t) ? null : t;
        };
        const formatDelta = (ms) => {
            if (ms == null || !Number.isFinite(ms)) return null;
            if (ms < 1000) return `${Math.round(ms)}ms`;
            const sec = ms / 1000;
            if (sec < 60) return `${sec.toFixed(sec < 10 ? 1 : 0)}s`;
            const min = Math.floor(sec / 60);
            const rem = Math.round(sec % 60);
            return `${min}m ${rem}s`;
        };
        const pickFlowIcon = (eventName = '', payload = {}) => {
            const name = String(eventName).toLowerCase();
            const status = String(payload?.status || '').toLowerCase();
            if (name.includes('error') || name.includes('fail') || status.includes('fail') || status.includes('error')) return AlertTriangle;
            if (name.includes('complete') || status.includes('success') || status.includes('done')) return CheckCircle2;
            if (name.includes('thought') || name.includes('plan')) return Brain;
            if (name.includes('skill') || name.includes('tool') || name.includes('action') || payload?.key) return Wrench;
            if (name.includes('status') || name.includes('state') || name.includes('created')) return Clock3;
            return CircleDot;
        };

        return (
            <div
                className="modal-overlay"
                style={{ background: 'rgba(15, 23, 42, 0.08)', backdropFilter: 'blur(4px)', WebkitBackdropFilter: 'blur(4px)' }}
                onClick={() => { setSelectedWorkId(null); setWorkOverwatch(null); }}
            >
                <div className="modal-content glass" onClick={e => e.stopPropagation()} style={{ width: isMobile ? '95vw' : 'min(90vw, 840px)', height: isMobile ? 'min(88vh, 660px)' : 'min(86vh, 760px)', maxHeight: '90vh', overflow: 'hidden', padding: 0, display: 'flex', flexDirection: 'column', borderRadius: isMobile ? '9px' : '10px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: isMobile ? '10px 10px' : '10px 12px', gap: '8px', borderBottom: '1px solid var(--card-border)' }}>
                        <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '700', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                worker {work.work_id?.slice(0, 12)} | {String(work.status || '-').toLowerCase()}
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                            <button
                                className={isPaused ? "btn-primary" : "btn-ghost"}
                                onClick={isPaused ? resume : pause}
                                title={isPaused ? 'Resume worker' : 'Pause worker'}
                                aria-label={isPaused ? 'Resume worker' : 'Pause worker'}
                                style={{ width: '28px', minWidth: '28px', height: '28px', padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', borderRadius: '7px' }}
                            >
                                {isPaused ? <Play size={14} /> : <Pause size={14} />}
                            </button>
                            <button
                                className="btn-ghost"
                                onClick={() => setSelectedWorkId(null)}
                                title="Close details"
                                aria-label="Close details"
                                style={{ width: '28px', minWidth: '28px', height: '28px', padding: 0, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', borderRadius: '7px' }}
                            >
                                <X size={15} />
                            </button>
                        </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'nowrap', overflowX: 'auto', padding: isMobile ? '6px 8px' : '8px 10px', borderBottom: '1px solid var(--card-border)' }} className="custom-scrollbar">
                        {['overview', 'planner', 'flow', 'skills', 'media', 'triggers', 'executions', 'notes', 'queue'].map(tab => (
                            <button
                                key={tab}
                                style={{
                                    appearance: 'none',
                                    WebkitAppearance: 'none',
                                    textDecoration: 'none',
                                    outline: 'none',
                                    boxShadow: 'none',
                                    border: overwatchTab === tab ? '1px solid var(--accent-color)' : '1px solid transparent',
                                    background: overwatchTab === tab ? 'var(--accent-glow)' : 'transparent',
                                    color: overwatchTab === tab ? 'var(--accent-color)' : 'var(--text-muted)',
                                    padding: '5px 8px',
                                    fontSize: '10px',
                                    fontWeight: '700',
                                    textTransform: 'uppercase',
                                    borderRadius: '7px',
                                    whiteSpace: 'nowrap',
                                    flexShrink: 0,
                                    lineHeight: 1,
                                    cursor: 'pointer',
                                    transition: 'var(--transition-fast)',
                                    position: 'relative',
                                    zIndex: overwatchTab === tab ? 2 : 1,
                                    verticalAlign: 'middle',
                                }}
                                onClick={() => setOverwatchTab(tab)}
                            >
                                {tab}
                            </button>
                        ))}
                    </div>

                    <div className="custom-scrollbar" style={{ overflowY: 'auto', flex: 1, minHeight: 0, padding: isMobile ? '8px' : '10px' }}>
                    {overwatchTab === 'overview' && (
                        <div className="glass" style={{ padding: '12px', borderRadius: '8px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, minmax(0, 1fr))', gap: '8px', marginBottom: '10px' }}>
                                <div style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '8px' }}>
                                    <div style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 700 }}>Summary</div>
                                    <div style={{ fontSize: '13px', fontWeight: 700, marginTop: '2px' }}>{summary.goal || '-'}</div>
                                </div>
                                <div style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '8px' }}>
                                    <div style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 700 }}>Cursor</div>
                                    <div style={{ fontSize: '13px', fontWeight: 700, marginTop: '2px' }}>{summary.cursor || '-'}</div>
                                </div>
                                <div style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '8px' }}>
                                    <div style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 700 }}>Planner Steps</div>
                                    <div style={{ fontSize: '13px', fontWeight: 700, marginTop: '2px' }}>{Array.isArray(planner.steps) ? planner.steps.length : 0}</div>
                                </div>
                            </div>

                            <div style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '8px', marginBottom: '10px' }}>
                                <div style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '4px' }}>Last Thought</div>
                                <div
                                    style={{
                                        fontSize: '13px',
                                        lineHeight: 1.45,
                                        color: 'var(--text-primary)',
                                        display: isOverviewThoughtExpanded ? 'block' : '-webkit-box',
                                        WebkitLineClamp: isOverviewThoughtExpanded ? 'unset' : 5,
                                        WebkitBoxOrient: 'vertical',
                                        overflow: 'hidden',
                                        overflowWrap: 'anywhere',
                                    }}
                                >
                                    {summary.last_thought || '-'}
                                </div>
                                {String(summary.last_thought || '').length > 260 && (
                                    <button
                                        className="btn-ghost"
                                        onClick={() => setIsOverviewThoughtExpanded(prev => !prev)}
                                        style={{ marginTop: '6px', padding: '4px 6px', fontSize: '11px', fontWeight: 700 }}
                                    >
                                        {isOverviewThoughtExpanded ? 'Show less' : 'Show more'}
                                    </button>
                                )}
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, minmax(0, 1fr))', gap: '8px' }}>
                                {[
                                    ['Last Action', summary.last_action || '-'],
                                    ['Trigger', work?.context?.data?.trigger_id || '-'],
                                    ['Origin Session', origin.owner_session_id || '-'],
                                    ['Favorite Session', origin.favorite_session_id || '-'],
                                    ['Owner Identity', origin.owner_sender_id || '-'],
                                    ['Favorite Identity', origin.favorite_sender_id || '-'],
                                ].map(([label, value]) => (
                                    <div key={label} style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '8px' }}>
                                        <div style={{ fontSize: '10px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 700 }}>{label}</div>
                                        <div style={{ fontSize: '13px', marginTop: '2px', overflowWrap: 'anywhere' }}>{value}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    {overwatchTab === 'planner' && (
                        <div className="glass" style={{ padding: '12px', borderRadius: '8px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', marginBottom: '8px' }}>
                                <div><b>Planner</b></div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '4px', border: '1px solid var(--card-border)', borderRadius: '8px', padding: '2px', background: 'rgba(255,255,255,0.02)' }}>
                                    <button
                                        className="btn-ghost"
                                        onClick={() => setPlannerViewMode('checklist')}
                                        style={{
                                            border: 'none',
                                            background: plannerViewMode === 'checklist' ? 'var(--accent-glow)' : 'transparent',
                                            color: plannerViewMode === 'checklist' ? 'var(--accent-color)' : 'var(--text-muted)',
                                            padding: '5px 8px',
                                            fontSize: '10px',
                                            fontWeight: '700',
                                            borderRadius: '6px',
                                            textTransform: 'uppercase',
                                        }}
                                    >
                                        Checklist
                                    </button>
                                    <button
                                        className="btn-ghost"
                                        onClick={() => setPlannerViewMode('raw')}
                                        style={{
                                            border: 'none',
                                            background: plannerViewMode === 'raw' ? 'var(--accent-glow)' : 'transparent',
                                            color: plannerViewMode === 'raw' ? 'var(--accent-color)' : 'var(--text-muted)',
                                            padding: '5px 8px',
                                            fontSize: '10px',
                                            fontWeight: '700',
                                            borderRadius: '6px',
                                            textTransform: 'uppercase',
                                        }}
                                    >
                                        Raw
                                    </button>
                                </div>
                            </div>
                            {plannerViewMode === 'checklist' ? (
                                Array.isArray(planner.steps) && planner.steps.length > 0 ? (
                                <ul style={{ margin: 0, listStyle: 'none', padding: 0, display: 'grid', gap: 0 }}>
                                    {planner.steps.map((step, idx) => (
                                        (() => {
                                            const status = String(step?.status || 'pending').toLowerCase();
                                            const isSuccess = ['done', 'completed', 'success', 'succeeded'].includes(status);
                                            const isError = ['failed', 'failure', 'error', 'cancelled', 'canceled'].includes(status);
                                            const marker = isSuccess ? '✓' : isError ? '✕' : '';
                                            return (
                                            <li key={`planner-step-${idx}`} style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0, padding: 0, minHeight: '30px', borderBottom: '1px solid rgba(148,163,184,0.14)' }}>
                                                <span
                                                    aria-hidden="true"
                                                    style={{
                                                        width: '16px',
                                                        minWidth: '16px',
                                                        height: '16px',
                                                        borderRadius: '4px',
                                                        border: '1px solid var(--card-border)',
                                                        display: 'inline-flex',
                                                        alignItems: 'center',
                                                        justifyContent: 'center',
                                                        fontSize: '11px',
                                                        fontWeight: '800',
                                                        color: isSuccess ? 'var(--success)' : isError ? 'var(--error)' : 'var(--text-muted)',
                                                    }}
                                                >
                                                    {marker}
                                                </span>
                                                <div style={{ minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                    <span style={{ fontSize: '12px', fontWeight: '700', textDecoration: isSuccess ? 'line-through' : 'none', color: isSuccess ? 'var(--text-muted)' : 'var(--text-primary)' }}>
                                                        {idx + 1}. {step?.step || step?.title || 'Untitled step'}
                                                    </span>
                                                </div>
                                            </li>
                                            );
                                        })()
                                    ))}
                                </ul>
                            ) : (
                                <div style={{ marginTop: '10px', color: 'var(--text-muted)' }}>No planner steps available for this worker.</div>
                            )
                            ) : (
                                <pre className="custom-scrollbar" style={{ whiteSpace: 'pre-wrap', fontSize: '11px', margin: 0, maxHeight: isMobile ? '44vh' : '52vh', overflow: 'auto', border: '1px solid var(--card-border)', borderRadius: '8px', padding: '10px' }}>
                                    {JSON.stringify(planner, null, 2)}
                                </pre>
                            )}
                        </div>
                    )}
                    {overwatchTab === 'flow' && (
                        <div className="glass" style={{ padding: '12px', borderRadius: '8px', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                            {events.length > 0 ? (
                                <div className="custom-scrollbar" style={{ position: 'relative', paddingLeft: '22px', display: 'grid', gap: '10px', overflowY: 'auto', minHeight: 0, flex: 1 }}>
                                    <div style={{ position: 'absolute', left: '7px', top: 0, bottom: 0, width: '1px', background: 'rgba(148,163,184,0.26)' }} />
                                    {events.map((ev, idx) => {
                                        const payload = ev?.payload || {};
                                        const Icon = pickFlowIcon(ev?.event, payload);
                                        const currentMs = toMs(ev?.ts);
                                        const prevMs = idx > 0 ? toMs(events[idx - 1]?.ts) : null;
                                        const deltaLabel = formatDelta(currentMs != null && prevMs != null ? Math.abs(currentMs - prevMs) : null);
                                        const payloadDuration = Number(payload?.duration_ms ?? payload?.elapsed_ms);
                                        const durationLabel = Number.isFinite(payloadDuration) ? formatDelta(payloadDuration) : null;
                                        const skillLabel = payload?.skill || payload?.tool || (String(payload?.key || '').includes('.') ? payload.key : null);
                                        const actionLabel = payload?.action || payload?.event || null;
                                        return (
                                            <div key={`${ev.ts}-${idx}`} style={{ position: 'relative' }}>
                                                <div style={{ position: 'absolute', left: '-22px', top: '10px', width: '14px', height: '14px', borderRadius: '50%', background: 'var(--card-bg)', border: '1px solid var(--card-border)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
                                                    <Icon size={10} />
                                                </div>
                                                <div style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '8px 10px', background: 'rgba(255,255,255,0.01)' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
                                                        <div style={{ fontSize: '12px', fontWeight: 800 }}>{String(ev?.event || 'event')}</div>
                                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{formatFlowDateTime(ev?.ts)}</div>
                                                    </div>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', marginBottom: '6px' }}>
                                                        {deltaLabel && <span style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '2px 6px' }}>+{deltaLabel}</span>}
                                                        {durationLabel && <span style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '2px 6px' }}>exec {durationLabel}</span>}
                                                        {skillLabel && <span style={{ fontSize: '10px', color: 'var(--accent-color)', background: 'var(--accent-glow)', borderRadius: '999px', padding: '2px 6px' }}>skill: {String(skillLabel)}</span>}
                                                        {actionLabel && <span style={{ fontSize: '10px', color: 'var(--text-muted)', border: '1px solid var(--card-border)', borderRadius: '999px', padding: '2px 6px' }}>action: {String(actionLabel)}</span>}
                                                    </div>
                                                    <details style={{ fontSize: '11px' }}>
                                                        <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                                                            <Code2 size={12} /> payload json
                                                        </summary>
                                                        <pre className="custom-scrollbar" style={{ whiteSpace: 'pre-wrap', fontSize: '11px', marginTop: '6px', maxHeight: '220px', overflow: 'auto', border: '1px solid var(--card-border)', borderRadius: '6px', padding: '8px' }}>
                                                            {JSON.stringify(payload, null, 2)}
                                                        </pre>
                                                    </details>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <div style={{ color: 'var(--text-muted)' }}>No flow events.</div>
                            )}
                        </div>
                    )}
                    {overwatchTab === 'skills' && (
                        <div className="glass" style={{ padding: '12px', borderRadius: '8px' }}>
                            <div><b>Skills Used:</b></div>
                            <ul>
                                {skills.map(s => (
                                    <li key={s} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <SkillIcon variant="inline" skillId={s} skillName={s} />
                                        <span>{s}</span>
                                    </li>
                                ))}
                            </ul>
                            <div style={{ marginTop: '10px' }}><b>Actions Used:</b></div>
                            <ul>{(workOverwatch.actions_used || []).slice(-50).map((a, i) => <li key={`${a}-${i}`}>{a}</li>)}</ul>
                        </div>
                    )}
                    {overwatchTab === 'media' && (
                        <div className="glass" style={{ padding: '12px', borderRadius: '8px' }}>
                            <div><b>Media Used:</b></div>
                            <ul>{media.map((m, i) => <li key={`${m}-${i}`}>{m}</li>)}</ul>
                            {media.length === 0 && <div style={{ color: 'var(--text-muted)' }}>No media captured.</div>}
                        </div>
                    )}
                    {overwatchTab === 'triggers' && (
                        <div className="glass" style={{ padding: '12px', borderRadius: '8px' }}>
                            <div><b>Task ID:</b> {task.task_id || '-'}</div>
                            <div><b>Triggers:</b> {task.trigger_count || 0}</div>
                            <pre style={{ whiteSpace: 'pre-wrap', fontSize: '11px' }}>{JSON.stringify(task.triggers || [], null, 2)}</pre>
                        </div>
                    )}
                    {overwatchTab === 'executions' && (
                        <div className="glass" style={{ padding: '12px', borderRadius: '8px' }}>
                            <div><b>Execution Count:</b> {task.execution_count || 0}</div>
                            <div><b>Status:</b> {work.status}</div>
                            <div style={{ marginTop: '12px' }}><b>Recent Executions:</b></div>
                            {recentExecutions.length === 0 ? (
                                <div style={{ color: 'var(--text-muted)', marginTop: '6px' }}>No executions found.</div>
                            ) : (
                                <div style={{ marginTop: '8px', display: 'grid', gap: '8px' }}>
                                    {recentExecutions.map((row) => (
                                        <div key={row.execution_id} style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '8px 10px' }}>
                                            <div style={{ fontSize: '12px', fontWeight: '800' }}>{row.execution_id}</div>
                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                                {row.status} · start {row.start_time || '-'} · end {row.end_time || '-'}
                                            </div>
                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>trigger: {row.trigger_id || '-'}</div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                    {overwatchTab === 'notes' && (
                        <div className="glass" style={{ padding: '12px', borderRadius: '8px' }}>
                            <textarea className="input-field" style={{ minHeight: '100px' }} value={workNote} onChange={e => setWorkNote(e.target.value)} placeholder="Add notes/context for AI..." />
                            <div style={{ marginTop: '8px' }}>
                                <button className="btn-primary" onClick={saveNote}>Save Note</button>
                            </div>
                            <div style={{ marginTop: '12px' }}>
                                {notes.map((n, i) => (
                                    <div key={`${n.ts}-${i}`} style={{ marginBottom: '8px' }}>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{n.ts} · {n.author}</div>
                                        <div>{n.text}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                    {overwatchTab === 'queue' && (
                        <div className="glass" style={{ padding: '12px', borderRadius: '8px' }}>
                            <textarea className="input-field" style={{ minHeight: '100px' }} value={queuedMessage} onChange={e => setQueuedMessage(e.target.value)} placeholder="Message to worker queue..." />
                            <div style={{ marginTop: '8px', display: 'flex', gap: '8px' }}>
                                <button className="btn-ghost" onClick={() => queueMsg(false)}>Queue Message</button>
                                <button className="btn-primary" onClick={() => queueMsg(true)}>Pause + Direct Message</button>
                            </div>
                            <div style={{ marginTop: '12px' }}>
                                <b>Queued Messages Seen:</b>
                                <ul>{queued.map((q, i) => <li key={`${q}-${i}`}>{q}</li>)}</ul>
                            </div>
                        </div>
                    )}
                    </div>
                </div>
            </div>
        );
    };

    return (
        <div className="animate-fade-in flex-1" style={{ display: 'flex', height: '100%', maxHeight: '100%', overflow: 'hidden' }}>
            <main className="glass" style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                position: 'relative',
                overflow: 'hidden',
                borderRadius: '8px'
            }}>
                {renderHeader()}
                {renderWorksMonitor()}

                {selectedTaskId && (
                    <div className="flex-1 overflow-hidden relative">
                        <TaskDetails taskId={selectedTaskId} onDelete={handleTaskDeleted} />
                    </div>
                )}
            </main>

            {/* New Task Modal */}
            {showNewTaskModal && (
                <div className="modal-overlay" onClick={() => setShowNewTaskModal(false)}>
                    <div className="modal-content glass" onClick={e => e.stopPropagation()} style={{ width: isMobile ? '94vw' : 'min(90vw, 460px)', padding: isMobile ? '20px' : '24px' }}>
                        <h3 style={{ fontSize: '1rem', fontWeight: '800', marginBottom: '16px' }}>New Task</h3>
                        <form onSubmit={handleCreateTask} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                            <div className="form-group">
                                <label>Task Name</label>
                                <input
                                    type="text"
                                    required
                                    value={newTaskName}
                                    onChange={e => setNewTaskName(e.target.value)}
                                    className="input-field"
                                    placeholder="e.g. Daily Email Summary"
                                />
                            </div>
                            <div className="form-group">
                                <label>Context / Instruction</label>
                                <textarea
                                    required
                                    value={newTaskContext}
                                    onChange={e => setNewTaskContext(e.target.value)}
                                    className="input-field"
                                    style={{ height: '120px', resize: 'none' }}
                                    placeholder="What should the agent do?"
                                />
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '12px' }}>
                                <button
                                    type="button"
                                    onClick={() => setShowNewTaskModal(false)}
                                    className="btn-ghost"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    className="btn-primary"
                                >
                                    Create Task
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
            {renderOverwatchModal()}
        </div>
    );
};

export default Tasks;
