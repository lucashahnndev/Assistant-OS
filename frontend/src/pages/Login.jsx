import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useLocation } from 'react-router-dom';
import { Lock, User, Sun, Moon, Monitor, Eye, EyeOff } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';

const Login = () => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [cursorGlow, setCursorGlow] = useState(() => ({
        x: typeof window !== 'undefined' ? window.innerWidth / 2 : 0,
        y: typeof window !== 'undefined' ? window.innerHeight / 2 : 0,
        active: false,
        enabled: false,
    }));

    const { login, agentName } = useAuth();
    const { theme, setTheme } = useTheme();
    const navigate = useNavigate();
    const location = useLocation();
    const from = location.state?.from?.pathname || '/';

    useEffect(() => {
        if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
        const media = window.matchMedia('(pointer: fine)');
        const update = () => {
            setCursorGlow(prev => ({ ...prev, enabled: media.matches, active: false }));
        };
        update();
        if (typeof media.addEventListener === 'function') {
            media.addEventListener('change', update);
            return () => media.removeEventListener('change', update);
        }
        media.addListener(update);
        return () => media.removeListener(update);
    }, []);

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
            backgroundSize: '16px 16px',
            position: 'relative',
            overflow: 'hidden'
        }}
            onMouseMove={(e) => {
                if (!cursorGlow.enabled) return;
                setCursorGlow(prev => ({ ...prev, x: e.clientX, y: e.clientY, active: true }));
            }}
            onMouseLeave={() => {
                if (!cursorGlow.enabled) return;
                setCursorGlow(prev => ({ ...prev, active: false }));
            }}
        >
            {/* Subtle mesh enhancer */}
            <div style={{
                position: 'absolute',
                inset: 0,
                backgroundImage: 'radial-gradient(circle at 1px 1px, color-mix(in srgb, var(--accent-color) 34%, transparent) 1.15px, transparent 0)',
                backgroundSize: '18px 18px',
                opacity: theme === 'light' ? 0.18 : 0.34,
                pointerEvents: 'none',
                zIndex: 0
            }} />

            {/* Soft Radial Mask for Grid Depth */}
            <div style={{
                position: 'absolute',
                top: 0, left: 0, right: 0, bottom: 0,
                background: theme === 'light' ? 'radial-gradient(circle at center, transparent 0%, var(--bg-color) 100%)' : 'radial-gradient(circle at center, transparent 0%, var(--bg-color) 80%)',
                pointerEvents: 'none',
                zIndex: 1
            }} />

            {/* Wash layer: keeps mesh visible between glows, but softens grid inside glow cores */}
            <div style={{
                position: 'absolute',
                inset: 0,
                background: `
                    radial-gradient(420px 420px at 50% 50%, color-mix(in srgb, var(--bg-color) 72%, transparent) 0%, transparent 74%),
                    radial-gradient(320px 320px at 30% 20%, color-mix(in srgb, var(--bg-color) 68%, transparent) 0%, transparent 76%),
                    radial-gradient(360px 360px at 88% 88%, color-mix(in srgb, var(--bg-color) 70%, transparent) 0%, transparent 78%)
                `,
                pointerEvents: 'none',
                zIndex: 2
            }} />

            {/* Controlled Glows */}
            <div className="login-glow login-glow--core" style={{
                position: 'absolute',
                top: '50%', left: '50%',
                width: '600px', height: '600px',
                borderRadius: '50%',
                background: theme === 'light'
                    ? 'radial-gradient(circle, rgba(75, 106, 149, 0.20) 0%, rgba(0,0,0,0) 70%)'
                    : 'radial-gradient(circle, rgba(75, 106, 149, 0.38) 0%, rgba(0,0,0,0) 70%)',
                filter: 'blur(68px)',
                zIndex: 3,
            }} />

            <div className="login-glow login-glow--northwest" style={{
                position: 'absolute',
                top: '20%', left: '30%',
                width: '400px', height: '400px',
                borderRadius: '50%',
                background: theme === 'light'
                    ? 'radial-gradient(circle, rgba(75, 106, 149, 0.13) 0%, rgba(0,0,0,0) 70%)'
                    : 'radial-gradient(circle, rgba(75, 106, 149, 0.25) 0%, rgba(0,0,0,0) 70%)',
                filter: 'blur(72px)',
                zIndex: 3,
            }} />

            <div className="login-glow login-glow--southeast" style={{
                position: 'absolute',
                right: '-120px',
                bottom: '-160px',
                width: '440px',
                height: '440px',
                borderRadius: '50%',
                background: theme === 'light'
                    ? 'radial-gradient(circle, rgba(86, 95, 175, 0.22) 0%, rgba(0,0,0,0) 72%)'
                    : 'radial-gradient(circle, rgba(86, 95, 175, 0.42) 0%, rgba(0,0,0,0) 72%)',
                filter: 'blur(84px)',
                zIndex: 3,
                pointerEvents: 'none'
            }} />

            <div className="login-glow login-glow--cursor" style={{
                position: 'absolute',
                left: `${cursorGlow.x}px`,
                top: `${cursorGlow.y}px`,
                width: '220px',
                height: '220px',
                borderRadius: '50%',
                background: theme === 'light'
                    ? 'radial-gradient(circle, rgba(75, 106, 149, 0.24) 0%, rgba(75,106,149,0.06) 38%, rgba(0,0,0,0) 72%)'
                    : 'radial-gradient(circle, rgba(99, 125, 205, 0.38) 0%, rgba(75,106,149,0.14) 40%, rgba(0,0,0,0) 72%)',
                filter: 'blur(38px)',
                zIndex: 3,
                pointerEvents: 'none',
                mixBlendMode: theme === 'light' ? 'multiply' : 'screen',
                opacity: cursorGlow.enabled && cursorGlow.active ? 0.72 : 0,
                transition: 'opacity 180ms ease, left 78ms linear, top 78ms linear'
            }} />
            <div className="login-cursor-ring" style={{
                position: 'absolute',
                left: `${cursorGlow.x}px`,
                top: `${cursorGlow.y}px`,
                width: '126px',
                height: '126px',
                borderRadius: '50%',
                border: theme === 'light'
                    ? '2.4px solid rgba(36, 52, 88, 0.72)'
                    : '2.4px solid rgba(255,255,255,0.82)',
                background: 'transparent',
                boxShadow: theme === 'light'
                    ? '0 0 18px rgba(40, 56, 94, 0.20), inset 0 0 6px rgba(40, 56, 94, 0.12)'
                    : '0 0 26px rgba(255,255,255,0.20), inset 0 0 12px rgba(255,255,255,0.10)',
                zIndex: 3,
                pointerEvents: 'none',
                transform: 'translate(-50%, -50%)',
                opacity: cursorGlow.enabled && cursorGlow.active ? 0.7 : 0,
                transition: 'opacity 180ms ease, left 78ms linear, top 78ms linear',
                animation: 'loginCursorRingPulse 2s ease-in-out infinite'
            }} />

            <form onSubmit={handleSubmit} style={{
                width: '360px',
                maxWidth: 'calc(100vw - 28px)',
                padding: '28px 24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '14px',
                borderRadius: '12px',
                background: 'var(--card-bg)',
                border: '1px solid var(--card-border)',
                boxShadow: '0 8px 32px rgba(0, 0, 0, 0.15), 0 0 0 1px var(--card-border)',
                zIndex: 10,
                position: 'relative',
                animation: 'slide-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards'
            }}>
                <div style={{ textAlign: 'center', marginBottom: '2px' }}>
                    <h1 style={{ fontSize: '22px', fontWeight: '900', letterSpacing: '-0.02em', color: 'var(--text-primary)', margin: 0 }}>{agentName}</h1>
                    <h2 style={{ fontSize: '12px', fontWeight: '700', color: 'var(--text-secondary)', marginTop: '4px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Sign in to continue</h2>
                    <p style={{ color: 'var(--text-muted)', fontSize: '12px', marginTop: '8px', fontWeight: '500' }}>Secure access to your runtime environment.</p>
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
                                className="input-field"
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
                                className="input-field"
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
                        className="btn-primary"
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

            <style>{`
                .login-glow {
                    will-change: transform, opacity, filter;
                    animation-iteration-count: infinite;
                    animation-timing-function: linear;
                }
                .login-glow--core {
                    animation-name: loginGlowOrbitCore;
                    animation-duration: 22s;
                }
                .login-glow--northwest {
                    animation-name: loginGlowOrbitNW;
                    animation-duration: 27s;
                }
                .login-glow--southeast {
                    animation-name: loginGlowOrbitSE;
                    animation-duration: 31s;
                }
                .login-glow--cursor {
                    animation-name: loginGlowBreath;
                    animation-duration: 2.3s;
                    animation-timing-function: ease-in-out;
                }
                @keyframes loginGlowOrbitCore {
                    0% { transform: translate(-50%, -50%) translate3d(-48px, -30px, 0) scale(0.98); opacity: 0.78; }
                    25% { transform: translate(-50%, -50%) translate3d(42px, -26px, 0) scale(1.06); opacity: 0.96; }
                    50% { transform: translate(-50%, -50%) translate3d(54px, 34px, 0) scale(1.02); opacity: 0.88; }
                    75% { transform: translate(-50%, -50%) translate3d(-28px, 44px, 0) scale(1.07); opacity: 0.97; }
                    100% { transform: translate(-50%, -50%) translate3d(-48px, -30px, 0) scale(0.98); opacity: 0.78; }
                }
                @keyframes loginGlowOrbitNW {
                    0% { transform: translate3d(-42px, -30px, 0) scale(0.95); opacity: 0.72; }
                    33% { transform: translate3d(26px, -18px, 0) scale(1.06); opacity: 0.9; }
                    66% { transform: translate3d(18px, 34px, 0) scale(1.01); opacity: 0.82; }
                    100% { transform: translate3d(-42px, -30px, 0) scale(0.95); opacity: 0.72; }
                }
                @keyframes loginGlowOrbitSE {
                    0% { transform: translate3d(34px, 30px, 0) scale(0.98); opacity: 0.78; }
                    33% { transform: translate3d(-40px, 16px, 0) scale(1.08); opacity: 0.98; }
                    66% { transform: translate3d(-18px, -36px, 0) scale(1.02); opacity: 0.84; }
                    100% { transform: translate3d(34px, 30px, 0) scale(0.98); opacity: 0.78; }
                }
                @keyframes loginGlowBreath {
                    0% { transform: translate(-50%, -50%) scale(0.97); filter: blur(32px); }
                    50% { transform: translate(-50%, -50%) scale(1.05); filter: blur(40px); }
                    100% { transform: translate(-50%, -50%) scale(0.99); filter: blur(34px); }
                }
                @keyframes loginCursorRingPulse {
                    0% { transform: translate(-50%, -50%) scale(0.95); opacity: 0.54; }
                    50% { transform: translate(-50%, -50%) scale(1.03); opacity: 0.82; }
                    100% { transform: translate(-50%, -50%) scale(0.97); opacity: 0.6; }
                }
                @media (prefers-reduced-motion: reduce) {
                    .login-glow { animation: none !important; }
                    .login-cursor-ring { animation: none !important; }
                }
            `}</style>
        </div>
    );
};

export default Login;
