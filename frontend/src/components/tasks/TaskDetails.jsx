import { useState, useEffect } from 'react';
import { Play, RotateCw, Clock, Trash2, Power, Terminal, FileText } from 'lucide-react';
import { api } from '../../hooks/api';
import toast from 'react-hot-toast';
import NoteManager from './NoteManager';
import TriggerManager from './TriggerManager';
import ExecutionHistory from './ExecutionHistory';
import ConfirmDialog from '../ConfirmDialog';

const TaskDetails = ({ taskId, onDelete }) => {
    const [task, setTask] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('triggers'); // triggers, notes, history, live
    const [logs, setLogs] = useState('');
    const [liveExecution, setLiveExecution] = useState(null);
    const [overwatch, setOverwatch] = useState(null);
    const [latestTaskWork, setLatestTaskWork] = useState(null);
    const [isDeleting, setIsDeleting] = useState(false);

    const fetchTask = async () => {
        try {
            const res = await api.get(`/tasks/definitions/${taskId}`);
            setTask(res);
        } catch (error) {
            console.error("Error fetching task:", error);
            // toast.error("Failed to load task details");
        } finally {
            setLoading(false);
        }
    };

    const fetchLatestExecution = async () => {
        try {
            const history = await api.get(`/tasks/definitions/${taskId}/executions`);
            if (history && history.length > 0) {
                // Sort inside just in case backend didn't
                const sorted = history.sort((a, b) => new Date(b.start_time) - new Date(a.start_time));
                const latest = sorted[0];
                setLiveExecution(latest);

                // If running, poll logs
                if (latest.status === 'running') {
                    fetchLogs(latest.execution_id);
                }
            }
        } catch (error) {
            console.error("Error fetching execution history:", error);
        }
    };

    const fetchLogs = async (executionId) => {
        try {
            const res = await api.get(`/tasks/executions/${executionId}/logs`);
            if (res && res.logs) {
                setLogs(res.logs);
            }
        } catch (error) {
            console.error("Error fetching logs:", error);
        }
    };

    const fetchTaskOverwatch = async () => {
        try {
            const works = await api.get('/tasks/works?include_completed=true&limit=200');
            const rows = Array.isArray(works) ? works : [];
            const related = rows.filter((w) => {
                const data = w?.context?.data || {};
                return data?.task_id === taskId || w?.key === taskId || String(w?.label || '').includes(taskId);
            });
            if (related.length === 0) {
                setLatestTaskWork(null);
                setOverwatch(null);
                return;
            }
            const sorted = related.sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0));
            const latest = sorted[0];
            setLatestTaskWork(latest);
            const data = await api.get(`/tasks/works/${latest.work_id}/overwatch?events_limit=200`);
            setOverwatch(data);
        } catch (error) {
            console.error("Error fetching task overwatch:", error);
        }
    };

    useEffect(() => {
        if (taskId) {
            fetchTask();
            fetchLatestExecution();
            fetchTaskOverwatch();
            // Poll for latest execution status every 3s
            const interval = setInterval(() => {
                fetchLatestExecution();
                fetchTaskOverwatch();
            }, 3000);
            return () => clearInterval(interval);
        }
    }, [taskId]);

    const handleRun = async () => {
        try {
            await api.post(`/tasks/definitions/${taskId}/run`);
            toast.success("Task execution started");
            setActiveTab('live');
            setTimeout(() => {
                fetchLatestExecution();
                fetchTaskOverwatch();
            }, 500);
        } catch (error) {
            toast.error("Failed to start task");
        }
    };

    const handleStop = async () => {
        if (!liveExecution || liveExecution.status !== 'running') return;
        try {
            await api.post(`/tasks/executions/${liveExecution.execution_id}/cancel`);
            toast.success("Cancellation requested");
        } catch (error) {
            toast.error("Failed to stop task");
        }
    };

    const handleDeleteTask = async () => {
        setIsDeleting(true);
    };

    const confirmDeleteTask = async () => {
        try {
            await api.delete(`/tasks/definitions/${taskId}`);
            toast.success("Task deleted");
            if (typeof onDelete === 'function') onDelete(taskId);
        } catch (error) {
            toast.error("Failed to delete task");
        } finally {
            setIsDeleting(false);
        }
    };

    if (loading) return <div className="p-8 text-center text-gray-500">Loading details...</div>;
    if (!task) return <div className="p-8 text-center text-gray-500">Task not found.</div>;

    return (
        <div className="h-full flex flex-col gap-6" style={{ flex: 1 }}>
            <div className="glass" style={{ padding: '24px 32px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderRadius: '16px' }}>
                <div>
                    <h2 style={{ fontSize: '24px', fontWeight: '900', margin: 0 }} className="gradient-text">
                        {task.name}
                    </h2>
                    <p style={{ color: 'var(--text-muted)', fontSize: '14px', margin: '4px 0 0', maxWidth: '600px' }}>{task.context}</p>
                </div>
                <div style={{ display: 'flex', gap: '12px' }}>
                    <button
                        onClick={handleRun}
                        className="btn-primary"
                        style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px', borderRadius: '12px' }}
                    >
                        <Play size={18} />
                        <span style={{ fontWeight: '700' }}>Executar Agora</span>
                    </button>
                    <button
                        onClick={handleDeleteTask}
                        className="btn-ghost"
                        style={{ color: 'var(--error)', padding: '10px' }}
                        title="Delete Task"
                    >
                        <Trash2 size={20} />
                    </button>
                </div>
            </div>

            <div className="glass" style={{ display: 'flex', padding: '0 24px', borderRadius: '16px', flexShrink: 0 }}>
                {[
                    { id: 'overwatch', label: 'OVERWATCH', icon: Terminal },
                    { id: 'live', label: 'AO VIVO', icon: Terminal },
                    { id: 'triggers', label: 'AGENDAMENTOS', icon: Clock },
                    { id: 'notes', label: 'NOTAS', icon: FileText },
                    { id: 'history', label: 'HISTÓRICO', icon: RotateCw },
                ].map(tab => (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        style={{
                            padding: '16px 12px',
                            background: 'none',
                            border: 'none',
                            color: activeTab === tab.id ? 'var(--accent-color)' : 'var(--text-muted)',
                            fontWeight: activeTab === tab.id ? '800' : '600',
                            borderBottom: activeTab === tab.id ? '3px solid var(--accent-color)' : '3px solid transparent',
                            cursor: 'pointer',
                            fontSize: '11px',
                            letterSpacing: '0.05em',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            transition: 'var(--transition)'
                        }}
                    >
                        <tab.icon size={14} />
                        {tab.label}
                    </button>
                ))}
            </div>

            <div className="custom-scrollbar" style={{ flex: 1, overflowY: 'auto' }}>
                {activeTab === 'triggers' && <TriggerManager taskId={taskId} />}

                {activeTab === 'notes' && <NoteManager notes={task.notes} taskId={taskId} onUpdate={fetchTask} />}

                {activeTab === 'history' && <ExecutionHistory taskId={taskId} />}

                {activeTab === 'overwatch' && (
                    <div className="h-full flex flex-col gap-4">
                        {!latestTaskWork || !overwatch ? (
                            <div style={{ color: 'var(--text-muted)' }}>No worker data for this task yet.</div>
                        ) : (
                            <>
                                <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
                                    <div><b>Work ID:</b> {latestTaskWork.work_id}</div>
                                    <div><b>Status:</b> {latestTaskWork.status}</div>
                                    <div><b>Last Thought:</b> {overwatch?.summary?.last_thought || '-'}</div>
                                    <div><b>Last Action:</b> {overwatch?.summary?.last_action || '-'}</div>
                                    <div><b>Cursor:</b> {overwatch?.summary?.cursor || '-'}</div>
                                    <div><b>Last Error:</b> {overwatch?.summary?.last_error || '-'}</div>
                                </div>
                                <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
                                    <div><b>Planner</b></div>
                                    {Array.isArray(overwatch?.planner?.steps) && overwatch.planner.steps.length > 0 ? (
                                        <div style={{ marginTop: '10px', display: 'grid', gap: '8px' }}>
                                            {overwatch.planner.steps.map((step, idx) => (
                                                <div key={`task-ow-step-${idx}`} style={{ border: '1px solid var(--card-border)', borderRadius: '8px', padding: '8px 10px' }}>
                                                    <div style={{ fontSize: '12px', fontWeight: '800' }}>{idx + 1}. {step?.step || step?.title || 'Untitled step'}</div>
                                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>status: {step?.status || 'pending'}</div>
                                                </div>
                                            ))}
                                        </div>
                                    ) : (
                                        <div style={{ marginTop: '8px', color: 'var(--text-muted)' }}>No planner steps available.</div>
                                    )}
                                </div>
                                <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
                                    <div><b>Capabilities Used:</b> {(overwatch?.capabilities_used || []).join(', ') || '-'}</div>
                                    <div style={{ marginTop: '8px' }}><b>Actions Used:</b></div>
                                    <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-muted)' }}>
                                        {(overwatch?.actions_used || []).slice(-30).join(' | ') || 'No actions recorded yet.'}
                                    </div>
                                </div>
                                <div className="glass" style={{ padding: '14px', borderRadius: '12px' }}>
                                    <div><b>Recent Flow Events</b></div>
                                    <div style={{ marginTop: '10px', maxHeight: '240px', overflow: 'auto' }}>
                                        {(overwatch?.events || []).slice(-12).map((ev, idx) => (
                                            <div key={`task-ow-ev-${idx}`} style={{ borderBottom: '1px solid var(--card-border)', padding: '8px 0' }}>
                                                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{ev.ts}</div>
                                                <div style={{ fontSize: '12px', fontWeight: '700' }}>{ev.event}</div>
                                            </div>
                                        ))}
                                        {(overwatch?.events || []).length === 0 && (
                                            <div style={{ color: 'var(--text-muted)' }}>No events captured.</div>
                                        )}
                                    </div>
                                </div>
                            </>
                        )}
                    </div>
                )}

                {activeTab === 'live' && (
                    <div className="h-full flex flex-col gap-4">
                        <div className="flex justify-between items-center">
                            <div className="flex items-center gap-3">
                                <div className={`w-3 h-3 rounded-full ${liveExecution?.status === 'running' ? 'bg-green-500 animate-pulse' :
                                    liveExecution?.status === 'failed' ? 'bg-red-500' :
                                        liveExecution?.status === 'cancelled' ? 'bg-yellow-500' :
                                            'bg-gray-500'
                                    }`} />
                                <div>
                                    <div className="text-sm font-bold" style={{ color: 'var(--text-main)' }}>Status: {liveExecution?.status || "N/A"}</div>
                                    <div className="text-xs" style={{ color: 'var(--text-muted)' }}>Execution ID: {liveExecution?.execution_id || "-"}</div>
                                </div>
                            </div>

                            {liveExecution?.status === 'running' && (
                                <button
                                    onClick={handleStop}
                                    className="flex items-center gap-2 px-4 py-2 bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500/20 rounded-xl text-sm font-bold transition-all"
                                >
                                    <Power size={14} /> Parar Tarefa
                                </button>
                            )}
                        </div>

                        <div className="flex-1 rounded-xl p-5 font-mono text-xs custom-scrollbar"
                            style={{
                                background: 'rgba(0,0,0,0.2)',
                                color: 'var(--text-main)',
                                border: '1px solid var(--card-border)',
                                boxShadow: 'inset 0 2px 8px rgba(0,0,0,0.1)'
                            }}>
                            {logs ? (
                                <pre className="whitespace-pre-wrap">{logs}</pre>
                            ) : (
                                <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Aguardando logs do sistema...</div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            <ConfirmDialog
                isOpen={isDeleting}
                title="Delete Task"
                message="Are you sure you want to delete this task definition and its triggers?"
                confirmText="Yes, Delete"
                cancelText="Cancel"
                onConfirm={confirmDeleteTask}
                onCancel={() => setIsDeleting(false)}
                isDestructive={true}
            />
        </div>
    );
};

export default TaskDetails;
