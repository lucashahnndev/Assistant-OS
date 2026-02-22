import { Plus, Search, FileText, ChevronLeft, ChevronRight } from 'lucide-react';

const TaskSidebar = ({ tasks, selectedTaskId, onSelectTask, onNewTask, isCollapsed, onToggle }) => {
    return (
        <aside className="glass custom-scrollbar" style={{
            width: isCollapsed ? '72px' : '320px',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            transition: 'var(--transition)',
            borderRadius: '16px',
            flexShrink: 0
        }}>
            <div className="glass" style={{
                margin: '12px 12px 12px 12px',
                padding: isCollapsed ? '8px 0' : '8px 14px',
                borderRadius: '12px',
                display: 'flex',
                flexDirection: isCollapsed ? 'column' : 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '8px',
                background: 'rgba(255,255,255,0.03)'
            }}>
                {!isCollapsed && <h3 style={{ fontSize: '14px', fontWeight: 'bold' }}>Tasks</h3>}
                <div style={{ display: 'flex', flexDirection: isCollapsed ? 'column' : 'row', gap: '8px' }}>
                    {!isCollapsed && (
                        <button onClick={onNewTask} className="btn-ghost" title="New Task" style={{ padding: '6px' }}>
                            <Plus size={16} />
                        </button>
                    )}
                    <button
                        className="btn-ghost"
                        onClick={onToggle}
                        style={{ padding: '6px' }}
                        title={isCollapsed ? "Expand" : "Collapse"}
                    >
                        {isCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
                    </button>
                </div>
            </div>

            <div className="custom-scrollbar" style={{ flex: 1, padding: '12px', overflowY: 'auto' }}>
                {tasks.length === 0 ? (
                    !isCollapsed && (
                        <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px' }}>
                            No tasks defined yet.
                        </div>
                    )
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                        {tasks.map(task => (
                            <button
                                key={task.task_id}
                                onClick={() => onSelectTask(task.task_id)}
                                className={`nav-item ${selectedTaskId === task.task_id ? 'active' : ''}`}
                                style={{
                                    justifyContent: isCollapsed ? 'center' : 'flex-start',
                                    padding: isCollapsed ? '12px' : '14px 18px',
                                    minHeight: '56px',
                                    borderRadius: '14px'
                                }}
                                title={task.name}
                            >
                                <FileText size={18} style={{ flexShrink: 0, color: selectedTaskId === task.task_id ? 'var(--accent-color)' : 'inherit' }} />
                                {!isCollapsed && (
                                    <div style={{ overflow: 'hidden', flex: 1 }}>
                                        <div style={{ fontWeight: '700', fontSize: '14px' }} className="truncate">{task.name}</div>
                                        <div style={{ fontSize: '11px', opacity: 0.6, marginTop: '2px' }} className="truncate">
                                            {task.context}
                                        </div>
                                    </div>
                                )}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </aside>
    );
};

export default TaskSidebar;
