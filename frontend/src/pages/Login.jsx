import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useLocation } from 'react-router-dom';
import { Lock, User, Sun, Moon, Monitor } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';

const Login = () => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const { login, agentName } = useAuth();
    const { theme, setTheme } = useTheme();
    const navigate = useNavigate();
    const location = useLocation();
    const from = location.state?.from?.pathname || '/';

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        const result = await login(username, password);
        if (result.success) {
            navigate(from, { replace: true });
        } else {
            setError(result.error);
        }
        setLoading(false);
    };

    return (
        <div className="flex-center" style={{
            width: '100vw',
            height: '100vh',
            background: 'var(--bg-color)',
            backgroundImage: 'var(--grid-pattern)',
            backgroundSize: '24px 24px',
            position: 'relative',
            overflow: 'hidden'
        }}>
            {/* Soft Radial Mask for Grid Depth */}
            <div style={{
                position: 'absolute',
                top: 0, left: 0, right: 0, bottom: 0,
                background: theme === 'light' ? 'radial-gradient(circle at center, transparent 0%, var(--bg-color) 100%)' : 'radial-gradient(circle at center, transparent 0%, var(--bg-color) 80%)',
                pointerEvents: 'none',
                zIndex: 1
            }} />

            {/* Controlled Glows */}
            <div style={{
                position: 'absolute',
                top: '50%', left: '50%',
                transform: 'translate(-50%, -50%)',
                width: '600px', height: '600px',
                borderRadius: '50%',
                background: theme === 'light' ? 'radial-gradient(circle, rgba(75, 106, 149, 0.06) 0%, rgba(0,0,0,0) 70%)' : 'radial-gradient(circle, rgba(75, 106, 149, 0.12) 0%, rgba(0,0,0,0) 70%)',
                filter: 'blur(50px)',
                zIndex: 2,
                animation: 'pulse 15s ease-in-out infinite alternate'
            }} />

            <div style={{
                position: 'absolute',
                top: '20%', left: '30%',
                width: '400px', height: '400px',
                borderRadius: '50%',
                background: theme === 'light' ? 'radial-gradient(circle, rgba(75, 106, 149, 0.03) 0%, rgba(0,0,0,0) 70%)' : 'radial-gradient(circle, rgba(75, 106, 149, 0.06) 0%, rgba(0,0,0,0) 70%)',
                filter: 'blur(60px)',
                zIndex: 2,
            }} />

            <form onSubmit={handleSubmit} style={{
                width: '380px',
                padding: '40px 32px',
                display: 'flex',
                flexDirection: 'column',
                gap: '24px',
                borderRadius: '16px',
                background: 'var(--card-bg)',
                border: '1px solid var(--card-border)',
                boxShadow: '0 8px 32px rgba(0, 0, 0, 0.15), 0 0 0 1px var(--card-border)',
                zIndex: 10,
                position: 'relative',
                animation: 'slide-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards'
            }}>
                <div style={{ textAlign: 'center', marginBottom: '8px' }}>
                    <div className="flex-center" style={{ width: '48px', height: '48px', borderRadius: '12px', background: 'var(--accent-glow)', margin: '0 auto 16px', color: 'var(--accent-color)', border: '1px solid var(--card-border)' }}>
                        <Monitor size={24} />
                    </div>
                    <h1 style={{ fontSize: '24px', fontWeight: '900', letterSpacing: '-0.03em', color: 'var(--text-primary)', margin: 0 }}>{agentName}</h1>
                    <h2 style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-secondary)', marginTop: '4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Control Plane</h2>
                    <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '12px', fontWeight: '500' }}>Secure access to your runtime environment.</p>
                </div>

                {error && (
                    <div style={{
                        background: 'rgba(239, 68, 68, 0.1)',
                        color: 'var(--error)',
                        padding: '12px',
                        borderRadius: '8px',
                        fontSize: '14px',
                        border: '1px solid rgba(239, 68, 68, 0.2)'
                    }}>
                        {error}
                    </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <div style={{ position: 'relative' }}>
                        <User size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                        <input
                            type="text"
                            placeholder="Username"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            required
                            className="input-field"
                            style={{ width: '100%', paddingLeft: '40px', borderRadius: '5px' }}
                        />
                    </div>

                    <div style={{ position: 'relative' }}>
                        <Lock size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                        <input
                            type="password"
                            placeholder="Password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                            className="input-field"
                            style={{ width: '100%', paddingLeft: '40px', borderRadius: '5px' }}
                        />
                    </div>
                </div>

                <button
                    type="submit"
                    disabled={loading}
                    className="btn-primary"
                    style={{ padding: '14px', borderRadius: '8px', marginTop: '8px' }}
                >
                    {loading ? 'Authenticating...' : 'Login'}
                </button>
            </form>

            {/* Theme Toggle Island */}
            <div className="glass" style={{
                position: 'fixed',
                bottom: '32px',
                right: '32px',
                padding: '6px',
                display: 'flex',
                gap: '8px',
                borderRadius: '12px',
                border: '1px solid var(--card-border)',
                zIndex: 1000,
                background: 'var(--card-bg)',
                boxShadow: 'var(--shadow-lg)'
            }}>
                <button
                    onClick={() => setTheme('light')}
                    className={`nav-item ${theme === 'light' ? 'active' : ''}`}
                    style={{ padding: '8px', borderRadius: '8px', border: 'none', background: 'transparent' }}
                    title="Light"
                >
                    <Sun size={18} />
                </button>
                <button
                    onClick={() => setTheme('dark')}
                    className={`nav-item ${theme === 'dark' ? 'active' : ''}`}
                    style={{ padding: '8px', borderRadius: '8px', border: 'none', background: 'transparent' }}
                    title="Dark"
                >
                    <Moon size={18} />
                </button>
                <button
                    onClick={() => setTheme('system')}
                    className={`nav-item ${theme === 'system' ? 'active' : ''}`}
                    style={{ padding: '8px', borderRadius: '8px', border: 'none', background: 'transparent' }}
                    title="System"
                >
                    <Monitor size={18} />
                </button>
            </div>
        </div>
    );
};

export default Login;
