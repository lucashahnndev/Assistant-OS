import { useState, useEffect, useRef } from 'react';
import { Play, RotateCw, Save, Clock, Trash2, Power, Terminal, FileText } from 'lucide-react';
import { api } from '../../hooks/api';
import toast from 'react-hot-toast';
import NoteManager from './NoteManager';
import TriggerManager from './TriggerManager';
import ExecutionHistory from './ExecutionHistory';

const TaskDetails = ({ taskId, onDelete }) => {
    const [task, setTask] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('triggers'); // triggers, notes, history, live
    const [logs, setLogs] = useState('');
    const [liveExecution, setLiveExecution] = useState(null);
    const logIntervalRef = useRef(null);

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

    useEffect(() => {
        if (taskId) {
            fetchTask();
            fetchLatestExecution();
            // Poll for latest execution status every 3s
            const interval = setInterval(fetchLatestExecution, 3000);
            return () => clearInterval(interval);
        }
    }, [taskId]);

    const handleRun = async () => {
        try {
            await api.post(`/tasks/definitions/${taskId}/run`);
            toast.success("Task execution started");
            setActiveTab('live');
            setTimeout(fetchLatestExecution, 500);
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
                        onClick={() => onDelete(taskId)}
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
                                boxShadow: 'inset 0 4px 12px rgba(0,0,0,0.1)'
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
        </div>
    );
};

export default TaskDetails;
