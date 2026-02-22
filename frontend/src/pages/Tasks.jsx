import { useState, useEffect } from 'react';
import { api } from '../hooks/api';
import toast from 'react-hot-toast';
import { Activity, Plus, Layout } from 'lucide-react';
import TaskSidebar from '../components/tasks/TaskSidebar';
import TaskDetails from '../components/tasks/TaskDetails';
import PageHeader from '../components/PageHeader';

const Tasks = () => {
    const [tasks, setTasks] = useState([]);
    const [activeAgents, setActiveAgents] = useState([]);
    const [selectedTaskId, setSelectedTaskId] = useState(null);
    const [isListCollapsed, setIsListCollapsed] = useState(() => {
        return localStorage.getItem('assistant_tasks_list_collapsed') === 'true';
    });
    const [loading, setLoading] = useState(true);
    const [showNewTaskModal, setShowNewTaskModal] = useState(false);
    const [newTaskName, setNewTaskName] = useState('');
    const [newTaskContext, setNewTaskContext] = useState('');

    const fetchData = async () => {
        try {
            const [tasksRes, activeRes] = await Promise.all([
                api.get('/tasks/definitions'),
                api.get('/tasks/active')
            ]);
            setTasks(tasksRes);
            setActiveAgents(activeRes);
        } catch (error) {
            console.error("Error fetching data:", error);
            // toast.error("Failed to load tasks"); // suppress noise
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        localStorage.setItem('assistant_tasks_list_collapsed', isListCollapsed);
    }, [isListCollapsed]);

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 5000);
        return () => clearInterval(interval);
    }, []);

    const handleCreateTask = async (e) => {
        e.preventDefault();
        try {
            const res = await api.post('/tasks/definitions', {
                name: newTaskName,
                context: newTaskContext
            });
            toast.success("Task definition created");
            setNewTaskName('');
            setNewTaskContext('');
            setShowNewTaskModal(false);
            fetchData();
            setSelectedTaskId(res.data.task_id); // Auto-select new task
        } catch (error) {
            toast.error("Failed to create task");
        }
    };

    const handleTaskDeleted = () => {
        setSelectedTaskId(null);
        fetchData();
    };

    const renderHeader = () => (
        <PageHeader
            title="Task Overwatch"
            subtitle="System Activity & Automation"
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
                    <Activity size={16} className={activeAgents.length > 0 ? "text-green-400 animate-pulse" : ""} />
                    <span style={{ fontWeight: '600' }}>{activeAgents.length} ACTIVE</span>
                </div>
                <button
                    onClick={() => setShowNewTaskModal(true)}
                    className="btn-primary"
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-2)',
                        padding: 'var(--space-2) var(--space-4)',
                        borderRadius: 'var(--radius-sm)',
                        fontWeight: '800',
                        fontSize: '0.75rem'
                    }}
                >
                    <Plus size={16} /> NEW TASK
                </button>
            </div>
        </PageHeader>
    );

    return (
        <div className="animate-fade-in flex-1" style={{ display: 'flex', height: '100%', gap: '16px', maxHeight: '100%', overflow: 'hidden' }}>
            {/* Sidebar Navigation */}
            <TaskSidebar
                tasks={tasks}
                selectedTaskId={selectedTaskId}
                onSelectTask={setSelectedTaskId}
                onNewTask={() => setShowNewTaskModal(true)}
                isCollapsed={isListCollapsed}
                onToggle={() => setIsListCollapsed(!isListCollapsed)}
            />

            {/* Main Content Area */}
            <main className="glass" style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                position: 'relative',
                overflow: 'hidden',
                borderRadius: '16px'
            }}>
                {renderHeader()}

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
                    <div className="modal-content glass" onClick={e => e.stopPropagation()} style={{ width: 'min(90vw, 500px)', padding: '32px' }}>
                        <h3 style={{ fontSize: '20px', fontWeight: '800', marginBottom: '24px' }}>Create New Task Definition</h3>
                        <form onSubmit={handleCreateTask} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
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
        </div>
    );
};

export default Tasks;
