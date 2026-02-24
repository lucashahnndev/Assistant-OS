import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck, User, Lock, ArrowRight } from 'lucide-react';

const Setup = () => {
    const [username, setUsername] = useState('admin');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [displayName, setDisplayName] = useState('System Admin');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const { initialized, checkStatus } = useAuth();
    const navigate = useNavigate();

    useEffect(() => {
        if (initialized) navigate('/login');
    }, [initialized]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (password !== confirmPassword) return setError('Passwords do not match');

        setError('');
        setLoading(true);

        try {
            const res = await fetch('/api/auth/bootstrap', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username,
                    password,
                    display_name: displayName
                })
            });

            const data = await res.json();
            if (res.ok) {
                await checkStatus();
                navigate('/login', { state: { message: 'Admin account created successfully!' } });
            } else {
                setError(data.detail || 'Setup failed');
            }
        } catch (err) {
            setError('Connection failed');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex-center" style={{ width: '100vw', height: '100vh', background: 'linear-gradient(135deg, #05070a 0%, #1e1b4b 100%)' }}>
            <form onSubmit={handleSubmit} className="glass animate-fade-in" style={{
                width: '440px',
                padding: '40px',
                display: 'flex',
                flexDirection: 'column',
                gap: '24px'
            }}>
                <div style={{ textAlign: 'center' }}>
                    <div className="flex-center" style={{ width: '64px', height: '64px', margin: '0 auto 16px', borderRadius: '50%', background: 'var(--accent-glow)', color: 'var(--accent-color)' }}>
                        <ShieldCheck size={32} />
                    </div>
                    <h1 className="gradient-text" style={{ fontSize: '28px', fontWeight: '800' }}>System Initialization</h1>
                    <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginTop: '8px' }}>Create your primary administrator account</p>
                </div>

                {error && (
                    <div style={{ background: 'rgba(239, 68, 68, 0.1)', color: 'var(--error)', padding: '12px', borderRadius: '8px', fontSize: '14px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
                        {error}
                    </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <div className="input-group">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px', textTransform: 'uppercase', fontWeight: 'bold' }}>Username</label>
                        <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} required className="glass" style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.05)', color: '#fff' }} />
                    </div>

                    <div className="input-group">
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px', textTransform: 'uppercase', fontWeight: 'bold' }}>Display Name</label>
                        <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required className="glass" style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.05)', color: '#fff' }} />
                    </div>

                    <div style={{ display: 'flex', gap: '16px' }}>
                        <div style={{ flex: 1 }}>
                            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px', textTransform: 'uppercase', fontWeight: 'bold' }}>Password</label>
                            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required className="glass" style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.05)', color: '#fff' }} />
                        </div>
                        <div style={{ flex: 1 }}>
                            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px', textTransform: 'uppercase', fontWeight: 'bold' }}>Confirm</label>
                            <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required className="glass" style={{ width: '100%', padding: '12px', background: 'rgba(255,255,255,0.05)', color: '#fff' }} />
                        </div>
                    </div>
                </div>

                <button type="submit" disabled={loading} className="btn-primary" style={{ padding: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px' }}>
                    {loading ? 'Initializing System...' : <>Finalize Setup <ArrowRight size={18} /></>}
                </button>
            </form>
        </div>
    );
};

export default Setup;
