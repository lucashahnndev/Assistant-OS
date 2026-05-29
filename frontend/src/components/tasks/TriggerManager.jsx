import { notify } from '../../utils/notify.jsx';
import { useState, useEffect } from 'react';
import { api } from '../../hooks/api';
import {
    Clock,
    Calendar,
    Activity,
    Trash2,
    Plus,
    CheckCircle,
    XCircle
} from 'lucide-react';

import ConfirmDialog from '../ConfirmDialog';

const TriggerManager = ({ taskId }) => {
    const [triggers, setTriggers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showAddModal, setShowAddModal] = useState(false);
    const [deletingTriggerId, setDeletingTriggerId] = useState(null);

    // Form State
    const [scheduleType, setScheduleType] = useState('interval');
    const [scheduleValue, setScheduleValue] = useState('');
    const [holidayRules, setHolidayRules] = useState({ exclude: false, only: false, country: 'BR' });

    // Weekly/Monthly State
    const [selectedDays, setSelectedDays] = useState([]);
    const [selectedTime, setSelectedTime] = useState('09:00');

    const DAYS_OF_WEEK = [
        { id: '1', label: 'Seg', full: 'Segunda-feira' },
        { id: '2', label: 'Ter', full: 'Terça-feira' },
        { id: '3', label: 'Qua', full: 'Quarta-feira' },
        { id: '4', label: 'Qui', full: 'Quinta-feira' },
        { id: '5', label: 'Sex', full: 'Sexta-feira' },
        { id: '6', label: 'Sáb', full: 'Sábado' },
        { id: '0', label: 'Dom', full: 'Domingo' }
    ];

    const DAYS_OF_MONTH = Array.from({ length: 31 }, (_, i) => i + 1);

    const fetchTriggers = async () => {
        try {
            const res = await api.get(`/tasks/definitions/${taskId}/triggers`);
            setTriggers(res);
        } catch (error) {
            console.error("Error fetching triggers:", error);
            notify.error("Failed to load triggers");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (taskId) {
            fetchTriggers();
            const interval = setInterval(fetchTriggers, 5000);
            return () => clearInterval(interval);
        }
    }, [taskId]);

    const generateCron = () => {
        const [hour, minute] = selectedTime.split(':');
        if (scheduleType === 'weekly') {
            if (selectedDays.length === 0) return null;
            const days = selectedDays.join(',');
            return `${minute} ${hour} * * ${days}`;
        } else if (scheduleType === 'monthly') {
            if (selectedDays.length === 0) return null;
            const days = selectedDays.join(',');
            return `${minute} ${hour} ${days} * *`;
        }
        return scheduleValue; // For raw cron or interval
    };

    const handleAddTrigger = async (e) => {
        e.preventDefault();
        try {
            let finalType = scheduleType;
            let finalValue = scheduleValue;
            let finalRules = {};

            if (scheduleType === 'weekly' || scheduleType === 'monthly') {
                finalType = 'cron'; // Convert to cron for backend
                finalValue = generateCron();
                if (!finalValue) {
                    notify.error("Por favor, selecione os dias.");
                    return;
                }
                finalRules = holidayRules;
            } else if (scheduleType === 'cron') {
                finalRules = holidayRules;
            }

            const payload = {
                task_id: taskId,
                schedule_type: finalType,
                schedule_value: finalValue,
                holiday_rules: finalRules
            };

            await api.post('/tasks/triggers', payload);
            notify.success("Trigger added!");
            setShowAddModal(false);
            setScheduleValue('');
            setSelectedDays([]);
            fetchTriggers();
        } catch (error) {
            notify.error("Failed to add trigger");
        }
    };

    const handleDelete = async (triggerId) => {
        setDeletingTriggerId(triggerId);
    };

    const confirmDeleteTrigger = async () => {
        if (!deletingTriggerId) return;
        try {
            await api.delete(`/tasks/triggers/${deletingTriggerId}`);
            notify.success("Trigger deleted");
            fetchTriggers();
        } catch (error) {
            notify.error("Failed to delete trigger");
        } finally {
            setDeletingTriggerId(null);
        }
    };

    const handleToggle = async (triggerId, currentStatus) => {
        try {
            await api.post(`/tasks/triggers/${triggerId}/toggle`, { enabled: !currentStatus });
            notify.success(currentStatus ? "Trigger disabled" : "Trigger enabled");
            fetchTriggers();
        } catch (error) {
            notify.error("Failed to toggle trigger");
        }
    };

    const toggleDay = (day) => {
        setSelectedDays(prev =>
            prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day]
        );
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ fontSize: '18px', fontWeight: '800', display: 'flex', alignItems: 'center', gap: '10px', margin: 0 }}>
                    <Clock size={20} style={{ color: 'var(--accent-color)' }} />
                    Agendamentos
                </h3>
                <button
                    onClick={() => setShowAddModal(true)}
                    className="btn-ghost"
                    style={{ background: 'var(--accent-glow)', color: 'var(--accent-color)', fontWeight: '700', borderRadius: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}
                >
                    <Plus size={16} /> Novo Agendamento
                </button>
            </div>

            {loading ? (
                <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>Carregando agendamentos...</div>
            ) : triggers.length === 0 ? (
                <div className="glass" style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)', borderRadius: '16px' }}>
                    Nenhum agendamento ativo. Configure um gatilho para automação.
                </div>
            ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '16px' }}>
                    {triggers.map(trigger => (
                        <div key={trigger.trigger_id} className="glass" style={{
                            padding: '24px',
                            borderRadius: '16px',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '16px',
                            opacity: trigger.enabled ? 1 : 0.6,
                            border: trigger.enabled ? '1px solid var(--card-border)' : '1px solid rgba(255,255,255,0.05)'
                        }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                    <div style={{ padding: '10px', background: 'rgba(255,255,255,0.05)', borderRadius: '10px', color: 'var(--accent-color)' }}>
                                        {trigger.schedule_type === 'interval' && <Clock size={20} />}
                                        {trigger.schedule_type === 'cron' && <Activity size={20} />}
                                        {trigger.schedule_type === 'date' && <Calendar size={20} />}
                                    </div>
                                    <div>
                                        <div style={{ fontSize: '10px', fontWeight: '900', color: 'var(--accent-color)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{trigger.schedule_type}</div>
                                        <div style={{ fontSize: '16px', fontWeight: '800', fontFamily: 'monospace' }}>
                                            {trigger.schedule_value}{trigger.schedule_type === 'interval' && 's'}
                                        </div>
                                    </div>
                                </div>

                                <div style={{ display: 'flex', gap: '8px' }}>
                                    <button
                                        onClick={() => handleToggle(trigger.trigger_id, trigger.enabled)}
                                        className="btn-ghost"
                                        style={{ padding: '8px', color: trigger.enabled ? 'var(--success)' : 'var(--warning)' }}
                                    >
                                        {trigger.enabled ? <CheckCircle size={18} /> : <XCircle size={18} />}
                                    </button>
                                    <button
                                        onClick={() => handleDelete(trigger.trigger_id)}
                                        className="btn-ghost"
                                        style={{ padding: '8px', color: 'var(--error)' }}
                                    >
                                        <Trash2 size={18} />
                                    </button>
                                </div>
                            </div>

                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '12px' }}>
                                <b>Próxima Execução:</b> {trigger.next_run ? new Date(trigger.next_run).toLocaleString() : 'Não Agendada'}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Add Trigger Modal */}
            {showAddModal && (
                <div className="modal-overlay" onClick={() => setShowAddModal(false)}>
                    <div className="modal-content glass" onClick={e => e.stopPropagation()} style={{ width: 'min(90vw, 500px)', padding: '32px' }}>
                        <h3 style={{ fontSize: '20px', fontWeight: '800', marginBottom: '24px' }}>Novo Agendamento</h3>
                        <form onSubmit={handleAddTrigger} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                            <div className="form-group">
                                <label>Tipo de Agendamento</label>
                                <select
                                    value={scheduleType}
                                    onChange={e => {
                                        setScheduleType(e.target.value);
                                        setSelectedDays([]);
                                        setScheduleValue('');
                                    }}
                                    className="input-field"
                                >
                                    <option value="interval">Intervalo (Segundos)</option>
                                    <option value="weekly">Semanal (Dias da Semana)</option>
                                    <option value="monthly">Mensal (Dias do Mês)</option>
                                    <option value="date">Data Específica</option>
                                    <option value="cron">Avançado (Cron)</option>
                                </select>
                            </div>

                            {/* Dynamic Fields */}
                            {scheduleType === 'interval' && (
                                <div className="form-group">
                                    <label>Segundos</label>
                                    <input
                                        type="number"
                                        value={scheduleValue}
                                        onChange={e => setScheduleValue(e.target.value)}
                                        className="input-field"
                                        placeholder="Ex: 3600 (1 hora)"
                                        required
                                    />
                                </div>
                            )}

                            {(scheduleType === 'weekly' || scheduleType === 'monthly') && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                                    <div className="form-group">
                                        <label>Horário</label>
                                        <input
                                            type="time"
                                            value={selectedTime}
                                            onChange={e => setSelectedTime(e.target.value)}
                                            className="input-field"
                                            required
                                        />
                                    </div>

                                    {scheduleType === 'weekly' && (
                                        <div className="form-group">
                                            <label>Dias da Semana</label>
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                                {DAYS_OF_WEEK.map(day => (
                                                    <button
                                                        key={day.id}
                                                        type="button"
                                                        onClick={() => toggleDay(day.id)}
                                                        className="btn-ghost"
                                                        style={{
                                                            padding: '8px 12px',
                                                            fontSize: '12px',
                                                            borderRadius: '8px',
                                                            background: selectedDays.includes(day.id) ? 'var(--accent-color)' : 'rgba(255,255,255,0.05)',
                                                            color: selectedDays.includes(day.id) ? '#fff' : 'var(--text-muted)'
                                                        }}
                                                    >
                                                        {day.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {scheduleType === 'monthly' && (
                                        <div className="form-group">
                                            <label>Dias do Mês</label>
                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '6px' }}>
                                                {DAYS_OF_MONTH.map(day => (
                                                    <button
                                                        key={day}
                                                        type="button"
                                                        onClick={() => toggleDay(day.toString())}
                                                        className="btn-ghost"
                                                        style={{
                                                            padding: '6px',
                                                            fontSize: '11px',
                                                            borderRadius: '6px',
                                                            background: selectedDays.includes(day.toString()) ? 'var(--accent-color)' : 'rgba(255,255,255,0.05)',
                                                            color: selectedDays.includes(day.toString()) ? '#fff' : 'var(--text-muted)',
                                                            aspectRatio: '1'
                                                        }}
                                                    >
                                                        {day}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}

                            {scheduleType === 'date' && (
                                <div className="form-group">
                                    <label>Data e Hora</label>
                                    <input
                                        type="datetime-local"
                                        value={scheduleValue}
                                        onChange={e => setScheduleValue(e.target.value)}
                                        className="input-field"
                                        required
                                    />
                                </div>
                            )}

                            {scheduleType === 'cron' && (
                                <div className="form-group">
                                    <label>Expressão Cron</label>
                                    <input
                                        type="text"
                                        value={scheduleValue}
                                        onChange={e => setScheduleValue(e.target.value)}
                                        className="input-field"
                                        style={{ fontFamily: 'monospace' }}
                                        placeholder="* * * * *"
                                        required
                                    />
                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                        Formato: min hora dia mês sem
                                    </div>
                                </div>
                            )}

                            {/* Holiday Rules */}
                            {['cron', 'weekly', 'monthly'].includes(scheduleType) && (
                                <div style={{ paddingTop: '16px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                                    <label style={{ display: 'block', fontSize: '12px', fontWeight: '800', marginBottom: '12px', color: 'var(--text-muted)' }}>REGRAS DE FERIADOS</label>
                                    <div style={{ display: 'flex', gap: '16px' }}>
                                        <button
                                            type="button"
                                            onClick={() => setHolidayRules({ ...holidayRules, exclude: !holidayRules.exclude, only: false })}
                                            className="btn-ghost"
                                            style={{ flex: 1, fontSize: '12px', background: holidayRules.exclude ? 'var(--accent-glow)' : 'transparent', border: holidayRules.exclude ? '1px solid var(--accent-color)' : '1px solid var(--card-border)' }}
                                        >
                                            Pular Feriados
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setHolidayRules({ ...holidayRules, only: !holidayRules.only, exclude: false })}
                                            className="btn-ghost"
                                            style={{ flex: 1, fontSize: '12px', background: holidayRules.only ? 'var(--accent-glow)' : 'transparent', border: holidayRules.only ? '1px solid var(--accent-color)' : '1px solid var(--card-border)' }}
                                        >
                                            Apenas Feriados
                                        </button>
                                    </div>
                                </div>
                            )}

                            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '12px' }}>
                                <button
                                    type="button"
                                    onClick={() => setShowAddModal(false)}
                                    className="btn-ghost"
                                >
                                    Cancelar
                                </button>
                                <button
                                    type="submit"
                                    className="btn-primary"
                                >
                                    Adicionar
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            <ConfirmDialog
                isOpen={!!deletingTriggerId}
                title="Delete Trigger"
                message="Are you sure you want to delete this trigger?"
                confirmText="Yes, Delete"
                cancelText="Cancel"
                onConfirm={confirmDeleteTrigger}
                onCancel={() => setDeletingTriggerId(null)}
                isDestructive={true}
            />
        </div>
    );
};

export default TriggerManager;
