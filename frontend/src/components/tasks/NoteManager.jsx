import { useState } from 'react';
import { api } from '../../hooks/api';
import { Plus, StickyNote, Send, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';

const NoteManager = ({ taskId, notes = [], onNotesUpdated }) => {
    const [newNote, setNewNote] = useState('');
    const [submitting, setSubmitting] = useState(false);

    const handleAddNote = async (e) => {
        e.preventDefault();
        if (!newNote.trim()) return;

        setSubmitting(true);
        try {
            await api.post(`/tasks/definitions/${taskId}/notes`, { note: newNote });
            toast.success("Note added");
            setNewNote('');
            if (onNotesUpdated) onNotesUpdated();
        } catch (error) {
            console.error(error);
            toast.error("Failed to add note");
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', height: '100%' }}>
            <h3 style={{ fontSize: '18px', fontWeight: '800', display: 'flex', alignItems: 'center', gap: '10px', margin: 0 }}>
                <StickyNote size={20} style={{ color: 'var(--warning)' }} />
                Notes & Context
            </h3>

            <div className="custom-scrollbar" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', minHeight: '100px' }}>
                {notes.length === 0 ? (
                    <div className="glass" style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', borderRadius: '16px' }}>
                        No notes added yet.
                    </div>
                ) : (
                    notes.map((note, idx) => (
                        <div key={idx} className="glass" style={{
                            padding: '20px',
                            borderRadius: '16px',
                            fontSize: '14px',
                            lineHeight: '1.6',
                            background: 'rgba(255, 255, 100, 0.03)',
                            borderLeft: '4px solid var(--warning)'
                        }}>
                            {note}
                        </div>
                    ))
                )}
            </div>

            <form onSubmit={handleAddNote} style={{ display: 'flex', gap: '12px', paddingTop: '12px', borderTop: '1px solid var(--card-border)' }}>
                <input
                    type="text"
                    value={newNote}
                    onChange={(e) => setNewNote(e.target.value)}
                    placeholder="Add a note or instruction..."
                    className="input-field"
                    style={{ flex: 1 }}
                    disabled={submitting}
                />
                <button
                    type="submit"
                    disabled={submitting}
                    className="btn-primary"
                    style={{ width: '48px', height: '48px', padding: 0, borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}
                >
                    {submitting ? <Loader2 size={20} className="animate-spin" /> : <Send size={20} />}
                </button>
            </form>
        </div>
    );
};

export default NoteManager;
