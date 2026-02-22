import { useState, useEffect } from 'react';
import { api } from '../../hooks/api';
import { History, CheckCircle, XCircle, Clock, FileText } from 'lucide-react';
import toast from 'react-hot-toast';

const ExecutionHistory = ({ taskId }) => {
    const [history, setHistory] = useState([]);
    const [loading, setLoading] = useState(true);

    const fetchHistory = async () => {
        try {
            const res = await api.get(`/tasks/definitions/${taskId}/executions`);
            setHistory(res);
        } catch (error) {
            console.error(error);
            toast.error("Failed to load history");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (taskId) {
            setLoading(true);
            fetchHistory();
            const interval = setInterval(fetchHistory, 10000);
            return () => clearInterval(interval);
        }
    }, [taskId]);

    const getStatusIcon = (status) => {
        switch (status) {
            case 'success': return <CheckCircle size={16} className="text-green-400" />;
            case 'failed': return <XCircle size={16} className="text-red-400" />;
            case 'running': return <Clock size={16} className="text-blue-400 animate-pulse" />;
            default: return <History size={16} className="text-gray-400" />;
        }
    };

    if (loading && history.length === 0) return <div className="text-gray-500 text-sm p-4">Loading history...</div>;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: '800', display: 'flex', alignItems: 'center', gap: '10px', margin: 0 }}>
                <History size={20} style={{ color: 'var(--accent-color)' }} />
                Execution Timeline
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {history.length === 0 ? (
                    <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px' }}>
                        No execution history found.
                    </div>
                ) : (
                    history.map(exec => (
                        <div key={exec.execution_id} className="glass" style={{
                            padding: '20px',
                            borderRadius: '16px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '12px',
                            position: 'relative'
                        }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    {getStatusIcon(exec.status)}
                                    <span style={{
                                        fontSize: '11px',
                                        fontWeight: '900',
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.05em',
                                        color: exec.status === 'success' ? 'var(--success)' :
                                            exec.status === 'failed' ? 'var(--error)' : 'var(--accent-color)'
                                    }}>
                                        {exec.status}
                                    </span>
                                </div>
                                <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                                    {new Date(exec.start_time).toLocaleString()}
                                </span>
                            </div>

                            <div style={{ fontSize: '12px', color: 'var(--text-main)', opacity: 0.8 }}>
                                <b>Duração:</b> {exec.end_time ?
                                    `${((new Date(exec.end_time) - new Date(exec.start_time)) / 1000).toFixed(2)}s`
                                    : 'Processando...'}
                            </div>

                            {exec.log_file && (
                                <button className="btn-ghost" style={{ padding: '4px 8px', fontSize: '11px', alignSelf: 'flex-start', color: 'var(--text-muted)' }}>
                                    <FileText size={12} /> View Log
                                </button>
                            )}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

export default ExecutionHistory;
