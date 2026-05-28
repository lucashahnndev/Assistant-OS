import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useLocation } from 'react-router-dom';
import { Lock, User, Sun, Moon, Monitor, Eye, EyeOff } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import WegenaParticleCanvas from '../components/WegenaParticleCanvas';

const Login = () => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [sceneLoaded, setSceneLoaded] = useState(false);

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
        <div
            className="flex-center"
            style={{
                width: '100vw',
                height: '100vh',
                background: theme === 'light'
                    ? 'radial-gradient(120% 90% at 16% 18%, #eef3fb 0%, #dce5f2 54%, #cfd9ea 100%)'
                    : 'radial-gradient(120% 100% at 18% 18%, rgba(46, 92, 198, 0.15) 0%, rgba(13, 31, 78, 0.05) 46%, rgba(0,0,0,0) 70%), linear-gradient(138deg, #020817 0%, #050a14 46%, #050a14 100%)',
                position: 'relative',
                overflow: 'hidden'
            }}
        >
            <div style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                zIndex: 1,
                opacity: 0.8
            }}>
                <WegenaParticleCanvas
                    defaultPresetId="neon-waves"
                    onSceneLoaded={() => setTimeout(() => setSceneLoaded(true), 1500)}
                />
            </div>

            {/* Scene Loader Cover */}
            <div
                className="flex-center"
                style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'var(--bg-color)',
                    zIndex: 2147483647,
                    opacity: sceneLoaded ? 0 : 1,
                    pointerEvents: sceneLoaded ? 'none' : 'all',
                    transition: 'opacity 0.8s ease-in-out',
                    overflow: 'hidden'
                }}
            >
                <style>{`
                    @keyframes loaderGlow {
                        from { opacity: 0; }
                        to { opacity: 1; }
                    }
                `}</style>
                <div style={{
                    position: 'absolute', inset: 0,
                    background: 'linear-gradient(180deg, #000000 0%, rgba(40, 15, 75, 0.35) 50%, #000000 100%)',
                    animation: 'loaderGlow 2s ease-in-out forwards'
                }} />
                <div className="gradient-text" style={{ fontSize: '42px', fontWeight: '900', letterSpacing: '0.15em', zIndex: 1, filter: 'drop-shadow(0 4px 8px rgba(0, 0, 0, 0.6))' }}>
                    {agentName}
                </div>
            </div>

            {/* Ambient glows */}
            <div className="login-ambient login-ambient--a" style={{
                position: 'absolute',
                top: '14%',
                left: '24%',
                width: '560px',
                height: '560px',
                borderRadius: '50%',
                background: theme === 'light'
                    ? 'radial-gradient(circle, rgba(90, 122, 188, 0.12) 0%, rgba(90,122,188,0.03) 42%, rgba(0,0,0,0) 75%)'
                    : 'radial-gradient(circle, rgba(37, 99, 235, 0.08) 0%, rgba(37,99,235,0.02) 44%, rgba(0,0,0,0) 76%)',
                filter: 'blur(78px)',
                zIndex: 2,
            }} />
            <div className="login-ambient login-ambient--b" style={{
                position: 'absolute',
                right: '8%',
                bottom: '8%',
                width: '500px',
                height: '500px',
                borderRadius: '50%',
                background: theme === 'light'
                    ? 'radial-gradient(circle, rgba(108, 146, 205, 0.10) 0%, rgba(108,146,205,0.02) 40%, rgba(0,0,0,0) 74%)'
                    : 'radial-gradient(circle, rgba(14, 165, 233, 0.06) 0%, rgba(14,165,233,0.02) 40%, rgba(0,0,0,0) 74%)',
                filter: 'blur(90px)',
                zIndex: 2,
                pointerEvents: 'none'
            }} />

            {/* Soft radial wash */}
            <div style={{
                position: 'absolute',
                inset: 0,
                background: theme === 'light'
                    ? 'radial-gradient(circle at center, rgba(255,255,255,0) 10%, rgba(226,233,245,0.52) 66%, rgba(214,222,238,0.86) 100%)'
                    : 'radial-gradient(circle at center, rgba(0,0,0,0.0) 10%, rgba(7,12,24,0.12) 62%, rgba(3,7,14,0.30) 100%)',
                pointerEvents: 'none',
                zIndex: 3
            }} />

            {/* Vignette */}
            <div style={{
                position: 'absolute',
                inset: 0,
                background: theme === 'light'
                    ? 'radial-gradient(circle at center, transparent 44%, rgba(168,178,197,0.22) 100%)'
                    : 'radial-gradient(circle at center, transparent 48%, rgba(0,0,0,0.6) 100%)',
                pointerEvents: 'none',
                zIndex: 4
            }} />

            <form onSubmit={handleSubmit} style={{
                width: '360px',
                maxWidth: 'calc(100vw - 28px)',
                padding: '28px 24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '14px',
                borderRadius: '16px',
                background: theme === 'light' ? 'rgba(244, 247, 253, 0.66)' : 'rgba(10, 12, 16, 0.6)',
                backdropFilter: 'blur(32px)',
                WebkitBackdropFilter: 'blur(32px)',
                border: theme === 'light' ? '1px solid rgba(20, 28, 46, 0.14)' : '1px solid rgba(255, 255, 255, 0.05)',
                boxShadow: theme === 'light'
                    ? '0 30px 84px rgba(28, 42, 68, 0.24), 0 0 38px rgba(94,122,178,0.08)'
                    : '0 40px 120px rgba(0,0,0,0.65), 0 0 60px rgba(37,99,235,0.08)',
                zIndex: 10,
                position: 'relative',
                animation: 'loginCardIn 250ms ease forwards'
            }}>
                <div style={{ textAlign: 'center', marginBottom: '2px' }}>
                    <h1 style={{ fontSize: '35px', fontWeight: '600', letterSpacing: '0.28em', color: 'var(--text-primary)', margin: 0, opacity: 0.96, lineHeight: 1 }}>{agentName}</h1>
                    <h2 style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-secondary)', marginTop: '8px', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Sign in to continue</h2>
                    <p style={{ color: 'var(--text-muted)', fontSize: '12px', marginTop: '8px', fontWeight: '500' }}>Secure access to the Atlas cognitive runtime.</p>
                </div>

                {error && (
                    <div style={{
                        background: 'rgba(239, 68, 68, 0.1)',
                        color: 'var(--error)',
                        padding: '9px 10px',
                        borderRadius: '6px',
                        fontSize: '12px',
                        border: '1px solid rgba(239, 68, 68, 0.2)'
                    }}>
                        {error}
                    </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', width: '100%' }}>
                    <div>
                        <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '5px' }}>Username</label>
                        <div style={{ position: 'relative' }}>
                            <User size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none' }} />
                            <input
                                type="text"
                                placeholder="Username"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                autoFocus
                                required
                                className="input-field login-input"
                                style={{
                                    width: '100%',
                                    paddingLeft: '38px',
                                    borderRadius: '6px',
                                    minHeight: '38px',
                                    borderColor: error ? 'rgba(239,68,68,0.35)' : undefined
                                }}
                            />
                        </div>
                    </div>

                    <div>
                        <label style={{ display: 'block', fontSize: '10px', fontWeight: '800', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '5px' }}>Password</label>
                        <div style={{ position: 'relative' }}>
                            <Lock size={18} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none' }} />
                            <input
                                type={showPassword ? 'text' : 'password'}
                                placeholder="Password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                className="input-field login-input"
                                style={{
                                    width: '100%',
                                    paddingLeft: '38px',
                                    paddingRight: '36px',
                                    borderRadius: '6px',
                                    minHeight: '38px',
                                    borderColor: error ? 'rgba(239,68,68,0.35)' : undefined
                                }}
                            />
                            <button
                                type="button"
                                onClick={() => setShowPassword(prev => !prev)}
                                className="btn-ghost"
                                aria-label={showPassword ? 'Hide password' : 'Show password'}
                                style={{
                                    position: 'absolute',
                                    right: '8px',
                                    top: '50%',
                                    transform: 'translateY(-50%)',
                                    width: '24px',
                                    height: '24px',
                                    padding: 0,
                                    borderRadius: '6px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center'
                                }}
                            >
                                {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                            </button>
                        </div>
                    </div>
                </div>

                <div style={{ width: '100%', marginTop: '4px' }}>
                    <button
                        type="submit"
                        disabled={loading}
                        className="btn-primary login-submit"
                        style={{ width: '100%', padding: '12px', borderRadius: '8px', fontWeight: 800 }}
                    >
                        {loading ? 'Signing in...' : 'Login'}
                    </button>
                </div>
            </form>

            {/* Theme Toggle Island */}
            <div className="glass" style={{
                position: 'fixed',
                bottom: '32px',
                right: '32px',
                padding: '6px 7px',
                display: 'flex',
                gap: '6px',
                borderRadius: '11px',
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

            <style>{`
                .login-ambient {
                    will-change: transform, opacity, filter;
                    animation-iteration-count: infinite;
                    animation-timing-function: ease-in-out;
                }
                .login-ambient--a {
                    animation-name: loginAmbientDriftA;
                    animation-duration: 24s;
                }
                .login-ambient--b {
                    animation-name: loginAmbientDriftB;
                    animation-duration: 28s;
                }
                .login-input {
                    background: ${theme === 'light' ? 'rgba(255,255,255,0.72)' : 'rgba(0,0,0,0.45)'} !important;
                    border: 1px solid ${theme === 'light' ? 'rgba(20,34,58,0.18)' : 'rgba(255,255,255,0.08)'} !important;
                    box-shadow: ${theme === 'light' ? '0 1px 6px rgba(22,34,56,0.08)' : '0 2px 8px rgba(0,0,0,0.22)'} !important;
                    transition: border-color 180ms ease, box-shadow 180ms ease, background 180ms ease !important;
                }
                .login-input:focus {
                    border-color: rgba(37, 99, 235, 0.45) !important;
                    box-shadow: 0 0 18px rgba(37, 99, 235, 0.12) !important;
                }
                .login-submit {
                    background: var(--accent-color) !important;
                    transition: transform 180ms ease, filter 180ms ease, box-shadow 180ms ease !important;
                    box-shadow: 0 8px 20px rgba(28, 40, 66, 0.26);
                }
                .login-submit:hover:not(:disabled) {
                    transform: translateY(-1px);
                    filter: brightness(1.1);
                    box-shadow: 0 10px 24px rgba(37, 99, 235, 0.32);
                }
                .login-submit:active:not(:disabled) {
                    transform: translateY(0);
                    filter: brightness(0.95);
                }
                @keyframes loginCardIn {
                    from {
                        opacity: 0;
                        transform: translateY(6px) scale(0.995);
                    }
                    to {
                        opacity: 1;
                        transform: translateY(0) scale(1);
                    }
                }
                @keyframes loginAmbientDriftA {
                    0% { transform: translate3d(-20px, -12px, 0) scale(0.98); opacity: 0.68; }
                    50% { transform: translate3d(34px, 18px, 0) scale(1.03); opacity: 0.86; }
                    100% { transform: translate3d(-20px, -12px, 0) scale(0.98); opacity: 0.68; }
                }
                @keyframes loginAmbientDriftB {
                    0% { transform: translate3d(24px, 14px, 0) scale(1); opacity: 0.64; }
                    50% { transform: translate3d(-26px, -20px, 0) scale(1.04); opacity: 0.84; }
                    100% { transform: translate3d(24px, 14px, 0) scale(1); opacity: 0.64; }
                }
                @media (prefers-reduced-motion: reduce) {
                    .login-ambient { animation: none !important; }
                }
            `}</style>
        </div>
    );
};

export default Login;
