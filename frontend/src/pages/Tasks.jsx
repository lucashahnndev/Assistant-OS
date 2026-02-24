import { useState, useEffect } from 'react';
import { api } from '../hooks/api';
import toast from 'react-hot-toast';
import {
    Activity,
    Plus,
    Layout,
    XCircle,
    Clock,
    Zap,
    RefreshCw,
    CheckCircle2,
    ChevronRight,
    Search
} from 'lucide-react';
import TaskDetails from '../components/tasks/TaskDetails';
import PageHeader from '../components/PageHeader';

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
    const [workKeywordFilter, setWorkKeywordFilter] = useState('');
    const [workTypeFilter, setWorkTypeFilter] = useState('all'); // all | no-cron | cron | manual | automated | media | active | completed
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 640);
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
        <div style={{ padding: isMobile ? '12px' : '16px 24px 12px' }}>
            {/* Compact Title Row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div className="flex-center" style={{ width: '32px', height: '32px', borderRadius: '10px', background: 'var(--accent-glow)', color: 'var(--accent-color)' }}>
                        <Zap size={16} />
                    </div>
                    <div>
                        <h3 style={{ fontSize: '1rem', fontWeight: '800' }}>Tasks</h3>
                        <p style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>Worker fleet and execution history.</p>
                    </div>
                </div>
                <button
                    onClick={() => setShowNewTaskModal(true)}
                    className="btn-primary"
                    style={{
                        padding: '7px 14px',
                        borderRadius: '8px',
                        fontWeight: '800',
                        fontSize: '0.6875rem'
                    }}
                >
                    <Plus size={14} /> NEW TASK
                </button>
            </div>

            {/* Compact Stats Row */}
            <div style={{ display: 'flex', gap: '8px', marginBottom: '0', flexWrap: 'wrap', alignItems: 'stretch' }}>
                <div style={{ padding: '8px 12px', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--card-border)', minWidth: '120px' }}>
                    <div className="flex-center" style={{ width: '28px', height: '28px', borderRadius: '8px', background: 'rgba(16, 185, 129, 0.1)', color: 'var(--success)' }}>
                        <Activity size={14} className={activeAgents.length > 0 ? "animate-pulse" : ""} />
                    </div>
                    <div>
                        <p style={{ fontSize: '9px', color: 'var(--text-muted)', fontWeight: '800', textTransform: 'uppercase' }}>Active</p>
                        <p style={{ fontSize: '14px', fontWeight: '800' }}>{activeAgents.length}</p>
                    </div>
                </div>
                <div style={{ padding: '8px 12px', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--card-border)', minWidth: '120px' }}>
                    <div className="flex-center" style={{ width: '28px', height: '28px', borderRadius: '8px', background: 'var(--accent-glow)', color: 'var(--accent-color)' }}>
                        <Layout size={14} />
                    </div>
                    <div>
                        <p style={{ fontSize: '9px', color: 'var(--text-muted)', fontWeight: '800', textTransform: 'uppercase' }}>Total</p>
                        <p style={{ fontSize: '14px', fontWeight: '800' }}>{works.length}</p>
                    </div>
                </div>
                <div style={{ padding: '6px', borderRadius: '10px', display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--card-border)', flex: 1, minWidth: '200px' }}>
                    <div style={{ display: 'flex', gap: '2px', background: 'rgba(0,0,0,0.2)', padding: '3px', borderRadius: '8px' }}>
                        {['live', 'archive'].map(tab => (
                            <button
                                key={tab}
                                onClick={() => setWorkViewTab(tab)}
                                style={{
                                    padding: '5px 14px',
                                    fontSize: '10px',
                                    fontWeight: '800',
                                    borderRadius: '6px',
                                    transition: 'var(--transition-fast)',
                                    background: workViewTab === tab ? 'var(--accent-color)' : 'transparent',
                                    color: workViewTab === tab ? '#fff' : 'var(--text-muted)',
                                    border: 'none'
                                }}
                            >
                                {tab.toUpperCase()}
                            </button>
                        ))}
                    </div>
                    <div style={{ position: 'relative', flex: 1 }}>
                        <Search size={13} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                        <input
                            type="text"
                            value={workKeywordFilter}
                            onChange={(e) => setWorkKeywordFilter(e.target.value)}
                            placeholder="Search workers..."
                            style={{
                                width: '100%',
                                padding: '7px 10px 7px 28px',
                                fontSize: '11px',
                                borderRadius: '8px',
                                background: 'transparent',
                                border: '1px solid var(--card-border)',
                                color: 'var(--text-primary)',
                                outline: 'none'
                            }}
                        />
                    </div>
                </div>
            </div>
        </div>
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
        const recentWorks = liveWorks.filter(w => !classifyWork(w).isActive).slice(0, 12);

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
                    borderRadius: '16px',
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

        if (workViewTab === 'archive') {
            return (
                <div style={{ padding: '0 var(--space-6) var(--space-6) var(--space-6)' }}>
                    <div className="glass" style={{ padding: '24px', borderRadius: '20px' }}>
                        <h3 style={{ fontSize: '0.875rem', fontWeight: '800', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)' }}>
                            <Clock size={16} /> History
                        </h3>
                        <div style={{ display: 'grid', gap: '12px' }}>
                            {archiveWorks.map(work => (
                                <div key={work.work_id} className="table-row-hover" style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    padding: '12px 16px',
                                    borderRadius: '12px',
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
                            ))}
                        </div>
                    </div>
                </div>
            );
        }

        return (
            <div style={{ padding: '0 var(--space-6) var(--space-6) var(--space-6)', display: 'flex', flexDirection: 'column', gap: '32px' }}>
                {/* Active Sector */}
                <div>
                    <h3 style={{ fontSize: '0.75rem', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Zap size={12} /> Active
                    </h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '16px' }}>
                        {topActive.length > 0 ? topActive.map(work => (
                            <WorkerCard key={work.work_id} work={work} />
                        )) : (
                            <div className="glass" style={{ padding: '30px', borderRadius: '12px', textAlign: 'center', gridColumn: '1 / -1', borderStyle: 'dashed' }}>
                                <p style={{ color: 'var(--text-muted)', fontSize: '12px' }}>No active workers.</p>
                            </div>
                        )}
                    </div>
                </div>

                {/* Recent Sector */}
                <div>
                    <h3 style={{ fontSize: '0.75rem', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <RefreshCw size={12} /> Recent
                    </h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '12px' }}>
                        {recentWorks.map(work => (
                            <div key={work.work_id} className="glass" style={{
                                padding: '12px 16px',
                                borderRadius: '14px',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '14px',
                                background: 'rgba(255,255,255,0.01)',
                                border: '1px solid var(--card-border)',
                                cursor: 'pointer'
                            }} onClick={() => loadWorkOverwatch(work.work_id)}>
                                <div className="flex-center" style={{ width: '36px', height: '36px', borderRadius: '10px', background: work.status === 'succeeded' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)', color: work.status === 'succeeded' ? 'var(--success)' : 'var(--error)' }}>
                                    {work.status === 'succeeded' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
                                </div>
                                <div style={{ minWidth: 0, flex: 1 }}>
                                    <div style={{ fontSize: '12px', fontWeight: '800', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{work.label || work.key}</div>
                                    <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{new Date(work.updated_at || Date.now()).toLocaleTimeString()}</div>
                                </div>
                                <ChevronRight size={14} color="var(--text-muted)" />
                            </div>
                        ))}
                    </div>
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

        return (
            <div className="modal-overlay" onClick={() => { setSelectedWorkId(null); setWorkOverwatch(null); }}>
                <div className="modal-content glass" onClick={e => e.stopPropagation()} style={{ width: isMobile ? '96vw' : 'min(96vw, 1000px)', maxHeight: '92vh', overflow: 'auto', padding: isMobile ? '14px' : '20px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', gap: '8px', flexWrap: 'wrap' }}>
                        <div>
                            <div style={{ fontSize: '1rem', fontWeight: '800' }}>Worker Details</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{work.work_id?.slice(0, 12)}... · {work.status}</div>
                        </div>
                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                            {String(work.status).toLowerCase() === 'paused' ? (
                                <button className="btn-primary" onClick={resume}>Resume</button>
                            ) : (
                                <button className="btn-ghost" onClick={pause}>Pause</button>
                            )}
                            <button className="btn-ghost" onClick={() => setSelectedWorkId(null)}>Close</button>
                        </div>
                    </div>

                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '14px' }}>
                        {['overview', 'planner', 'flow', 'skills', 'media', 'triggers', 'executions', 'notes', 'queue'].map(tab => (
                            <button key={tab} className="btn-ghost" style={{ border: overwatchTab === tab ? '1px solid var(--accent-color)' : undefined }} onClick={() => setOverwatchTab(tab)}>
                                {tab.toUpperCase()}
                            </button>
                        ))}
                    </div>

                    {overwatchTab === 'overview' && (
                        <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
                            <div><b>Summary:</b> {summary.goal || '-'} | {summary.cursor || '-'}</div>
                            <div><b>Last Thought:</b> {summary.last_thought || '-'}</div>
                            <div><b>Last Action:</b> {summary.last_action || '-'}</div>
                            <div><b>Trigger:</b> {work?.context?.data?.trigger_id || '-'}</div>
                            <div><b>Origin Session:</b> {origin.owner_session_id || '-'}</div>
                            <div><b>Favorite Session:</b> {origin.favorite_session_id || '-'}</div>
                            <div><b>Owner Identity:</b> {origin.owner_sender_id || '-'}</div>
                            <div><b>Favorite Identity:</b> {origin.favorite_sender_id || '-'}</div>
                            <div><b>Planner Steps:</b> {Array.isArray(planner.steps) ? planner.steps.length : 0}</div>
                        </div>
                    )}
                    {overwatchTab === 'planner' && (
                        <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
                            <div><b>Planner</b></div>
                            {Array.isArray(planner.steps) && planner.steps.length > 0 ? (
                                <div style={{ marginTop: '10px', display: 'grid', gap: '8px' }}>
                                    {planner.steps.map((step, idx) => (
                                        <div key={`planner-step-${idx}`} style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '8px 10px' }}>
                                            <div style={{ fontSize: '12px', fontWeight: '800' }}>
                                                {idx + 1}. {step?.step || step?.title || 'Untitled step'}
                                            </div>
                                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                                status: {step?.status || 'pending'}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div style={{ marginTop: '10px', color: 'var(--text-muted)' }}>No planner steps available for this worker.</div>
                            )}
                            <div style={{ marginTop: '12px' }}>
                                <b>Planner Raw Payload</b>
                                <pre style={{ whiteSpace: 'pre-wrap', fontSize: '11px' }}>{JSON.stringify(planner, null, 2)}</pre>
                            </div>
                        </div>
                    )}
                    {overwatchTab === 'flow' && (
                        <div className="glass" style={{ padding: '14px', borderRadius: '12px', maxHeight: '58vh', overflow: 'auto' }}>
                            {events.map((ev, idx) => (
                                <div key={`${ev.ts}-${idx}`} style={{ borderBottom: '1px solid var(--card-border)', padding: '8px 0' }}>
                                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{ev.ts}</div>
                                    <div style={{ fontWeight: '700' }}>{ev.event}</div>
                                    <pre style={{ whiteSpace: 'pre-wrap', fontSize: '11px' }}>{JSON.stringify(ev.payload || {}, null, 2)}</pre>
                                </div>
                            ))}
                            {events.length === 0 && <div style={{ color: 'var(--text-muted)' }}>No flow events.</div>}
                        </div>
                    )}
                    {overwatchTab === 'skills' && (
                        <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
                            <div><b>Skills Used:</b></div>
                            <ul>{skills.map(s => <li key={s}>{s}</li>)}</ul>
                            <div style={{ marginTop: '10px' }}><b>Actions Used:</b></div>
                            <ul>{(workOverwatch.actions_used || []).slice(-50).map((a, i) => <li key={`${a}-${i}`}>{a}</li>)}</ul>
                        </div>
                    )}
                    {overwatchTab === 'media' && (
                        <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
                            <div><b>Media Used:</b></div>
                            <ul>{media.map((m, i) => <li key={`${m}-${i}`}>{m}</li>)}</ul>
                            {media.length === 0 && <div style={{ color: 'var(--text-muted)' }}>No media captured.</div>}
                        </div>
                    )}
                    {overwatchTab === 'triggers' && (
                        <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
                            <div><b>Task ID:</b> {task.task_id || '-'}</div>
                            <div><b>Triggers:</b> {task.trigger_count || 0}</div>
                            <pre style={{ whiteSpace: 'pre-wrap', fontSize: '11px' }}>{JSON.stringify(task.triggers || [], null, 2)}</pre>
                        </div>
                    )}
                    {overwatchTab === 'executions' && (
                        <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
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
                        <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
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
                        <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
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
                borderRadius: '16px'
            }}>
                {renderHeader()}
                {renderWorksMonitor()}

                <div className="flex-1 overflow-hidden relative">
                    {selectedTaskId ? (
                        <TaskDetails taskId={selectedTaskId} onDelete={handleTaskDeleted} />
                    ) : (
                        <div className="h-full flex flex-col items-center justify-center" style={{ color: 'var(--text-muted)' }}>
                            <Layout size={48} className="mb-4 opacity-20" />
                            <p className="text-lg">Select a task to manage triggers and history</p>
                            <button
                                onClick={() => setShowNewTaskModal(true)}
                                className="mt-4 px-4 py-2 rounded-lg transition-colors btn-ghost"
                                style={{ background: 'var(--accent-glow)', color: 'var(--accent-color)' }}
                            >
                                <Plus size={16} className="inline mr-2" /> Create New Task
                            </button>
                        </div>
                    )}
                </div>
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
