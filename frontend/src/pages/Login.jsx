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
        <div className="flex-center" style={{ width: '100vw', height: '100vh', background: 'var(--bg-color)' }}>
            <form onSubmit={handleSubmit} className="glass animate-fade-in" style={{
                width: '380px',
                padding: '40px 32px',
                display: 'flex',
                flexDirection: 'column',
                gap: '24px',
                borderRadius: 'var(--radius-lg)'
            }}>
                <div style={{ textAlign: 'center' }}>
                    <h1 className="gradient-text" style={{ fontSize: '36px', fontWeight: '900', letterSpacing: '-0.02em' }}>{agentName}</h1>
                    <p style={{ color: 'var(--text-muted)', fontSize: '15px', marginTop: '8px', fontWeight: '500' }}>Welcome back. Please authenticate.</p>
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
                            style={{ width: '100%', paddingLeft: '40px' }}
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
                            style={{ width: '100%', paddingLeft: '40px' }}
                        />
                    </div>
                </div>

                <button
                    type="submit"
                    disabled={loading}
                    className="btn-primary"
                    style={{ padding: '14px' }}
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
                boxShadow: '0 8px 32px rgba(0,0,0,0.2)'
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
