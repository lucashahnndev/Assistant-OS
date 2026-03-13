import { useEffect, useRef, useState } from 'react';
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
    const sceneRef = useRef(null);
    const meshCanvasRef = useRef(null);
    const mouseRef = useRef({ x: 0, y: 0, vx: 0, vy: 0, speed: 0, active: false, enabled: false });
    const lagMouseRef = useRef({ x: 0, y: 0, ready: false });
    const fieldPersistenceRef = useRef(0);
    const trailRef = useRef([]);
    const rippleRef = useRef([]);

    const { login, agentName } = useAuth();
    const { theme, setTheme } = useTheme();
    const navigate = useNavigate();
    const location = useLocation();
    const from = location.state?.from?.pathname || '/';

    useEffect(() => {
        if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
        const media = window.matchMedia('(pointer: fine)');
        const update = () => {
            mouseRef.current.enabled = media.matches;
            mouseRef.current.active = false;
        };
        update();
        if (typeof media.addEventListener === 'function') {
            media.addEventListener('change', update);
            return () => media.removeEventListener('change', update);
        }
        media.addListener(update);
        return () => media.removeListener(update);
    }, []);

    useEffect(() => {
        const canvas = meshCanvasRef.current;
        if (!canvas) return undefined;
        const ctx = canvas.getContext('2d');
        if (!ctx) return undefined;

        let rafId;

        const resize = () => {
            const rect = canvas.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            canvas.width = Math.floor(rect.width * dpr);
            canvas.height = Math.floor(rect.height * dpr);
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        };

        const render = () => {
            const rect = canvas.getBoundingClientRect();
            ctx.clearRect(0, 0, rect.width, rect.height);

            const mouse = mouseRef.current;
            const trailNow = performance.now();
            const lag = lagMouseRef.current;
            if (!lag.ready) {
                lag.x = mouse.x;
                lag.y = mouse.y;
                lag.ready = true;
            }
            // Particle inertia: delayed tracking toward cursor.
            lag.x += (mouse.x - lag.x) * 0.14;
            lag.y += (mouse.y - lag.y) * 0.14;
            // Field persistence: slower fade-out after mouse stops/leaves.
            fieldPersistenceRef.current += ((mouse.enabled && mouse.active) ? 1 : 0 - fieldPersistenceRef.current) * 0.08;

            trailRef.current = trailRef.current.filter(p => trailNow - p.t < 620);
            rippleRef.current = rippleRef.current.filter(r => trailNow - r.t < 1300);

            const spacing = 20;
            const radius = 230;
            const edgeFade = 500;
            const outerRadius = radius + edgeFade;
            const outerRadiusSq = outerRadius * outerRadius;
            const influenceBoost = theme === 'light' ? 0.34 : 0.46;
            const now = trailNow;
            // Ping-pong cycle (forward/backward) avoids hard reset jumps.
            const cycle = (now % 12000) / 12000;
            const pingPong = cycle < 0.5 ? (cycle * 2) : (2 - cycle * 2);
            // Constrain to the stable upper-half profile window.
            const phase = 0.58 + pingPong * 0.34;
            const clamp01 = (n) => Math.max(0, Math.min(1, n));
            const smoothstep = (a, b, x) => {
                const t = clamp01((x - a) / (b - a));
                return t * t * (3 - 2 * t);
            };
            const repelWeight = 1 - smoothstep(0.03, 0.28, phase);
            const ringIn = smoothstep(0.20, 0.40, phase);
            const ringOut = 1 - smoothstep(0.56, 0.78, phase);
            const ringWeight = clamp01(ringIn * ringOut);
            const magneticWeight = smoothstep(0.60, 0.92, phase);
            const coreHoleRadius = 14;
            const repelRadius = 58;
            const guardRadius = 26;
            const shieldAhead = 96;
            const shieldHalfWidth = 64;
            const ringRadius = 92 + (pingPong - 0.5) * 8;
            const rippleSpeed = 0.58; // px/ms
            const rippleBand = 46;
            const rippleFadeMs = 1300;
            const baseAlpha = theme === 'light' ? 0.18 : 0.22;
            const baseDotSize = theme === 'light' ? 0.95 : 1.0;

            for (let y = 0; y <= rect.height + spacing; y += spacing) {
                for (let x = 0; x <= rect.width + spacing; x += spacing) {
                    const dx = lag.x - x;
                    const dy = lag.y - y;
                    const distSq = dx * dx + dy * dy;
                    const inMouseField = fieldPersistenceRef.current > 0.02 && distSq <= outerRadiusSq;

                    let px = x;
                    let py = y;
                    let alpha = baseAlpha;
                    let dotSize = baseDotSize;

                    if (inMouseField) {
                        const dist = Math.sqrt(distSq) || 0.0001;
                        const coreT = clamp01(1 - dist / radius);
                        const edgeT = clamp01(1 - Math.max(0, dist - radius) / edgeFade);
                        // Fade profile:
                        // - starts fading earlier (smaller core radius)
                        // - keeps a long tail to farther distances
                        // Stronger near cursor + smoother long-tail fade.
                        const edgeNearDrop = Math.pow(edgeT, 2.1);
                        const edgeLongTail = Math.pow(edgeT, 0.46);
                        const edgeProfile = clamp01(edgeNearDrop * 0.48 + edgeLongTail * 0.52);
                        const t = clamp01(coreT * 0.82 + edgeProfile * 0.18);
                        const persistence = fieldPersistenceRef.current;
                        const pull = t * t * (9 + magneticWeight * 8) * (0.75 + persistence * 0.25);
                        const swirl = t * (2.4 + magneticWeight * 4.8) * (0.75 + persistence * 0.25);
                        const nx = dx / dist;
                        const ny = dy / dist;

                        // Hard exclusion zone: no dots under/overlapping cursor.
                        if (dist <= coreHoleRadius) continue;

                        px = x + nx * pull + (-ny) * swirl;
                        py = y + ny * pull + nx * swirl;
                        alpha = Math.max(alpha, (0.14 + t * (influenceBoost + ringWeight * 0.12 + repelWeight * 0.08)) * edgeProfile * (0.55 + persistence * 0.45));
                        dotSize = Math.max(dotSize, 1.1 + t * (1.0 + ringWeight * 0.62 + repelWeight * 0.44) * edgeProfile);

                        if (dist < repelRadius) {
                            const rt = 1 - dist / repelRadius;
                            const repel = rt * rt * (18 + (coreHoleRadius / Math.max(dist, 0.1)) * 6) * repelWeight;
                            px -= nx * repel;
                            py -= ny * repel;
                        }
                            // Dense protective collar around cursor, preventing touch and shaping a guard ring.
                        if (dist < guardRadius) {
                            const guardPush = (guardRadius - dist) * 1.8;
                            px -= nx * guardPush;
                            py -= ny * guardPush;
                            alpha += 0.08;
                        }

                            // Anticipatory shield in movement direction:
                            // particles are deflected to front + sides before reaching cursor.
                        if (mouse.speed > 0.35) {
                                const vlen = Math.hypot(mouse.vx, mouse.vy) || 0.0001;
                                const dirX = mouse.vx / vlen;
                                const dirY = mouse.vy / vlen;
                                const relX = x - lag.x;
                                const relY = y - lag.y;
                                const ahead = relX * dirX + relY * dirY;
                                const sideProj = relX * (-dirY) + relY * dirX;
                                const lateral = Math.abs(sideProj);

                                if (ahead > 0 && ahead < shieldAhead && lateral < shieldHalfWidth) {
                                    const aheadT = 1 - ahead / shieldAhead;
                                    const latT = 1 - lateral / shieldHalfWidth;
                                    const st = aheadT * latT;
                                    const sideSign = sideProj >= 0 ? 1 : -1;
                                    const sidePush = st * (8.5 + mouse.speed * 0.24);
                                    const forwardPush = st * (6.2 + mouse.speed * 0.2);
                                    const radialPush = st * (7.5 + mouse.speed * 0.18);

                                    // push forward and sideways to form an arc/shield in front of cursor
                                    px += dirX * forwardPush + (-dirY) * sideSign * sidePush;
                                    py += dirY * forwardPush + dirX * sideSign * sidePush;
                                    // additional away-from-cursor component
                                    px -= nx * radialPush;
                                    py -= ny * radialPush;
                                    alpha += st * 0.1;
                                }
                        }

                        if (ringWeight > 0.001) {
                            const ringSign = Math.sign(dist - ringRadius);
                            const ringMag = Math.min(Math.abs(dist - ringRadius), 24) * 0.44 * t * ringWeight;
                            px += nx * ringSign * ringMag;
                            py += ny * ringSign * ringMag;
                        }
                    }

                    // Laminar wake trail: aligns dots behind cursor path (no chaotic turbulence).
                    if (inMouseField && trailRef.current.length > 0) {
                            const wakeHalfWidth = 44;
                            const wakeLength = 140;
                            for (let i = trailRef.current.length - 1; i >= 0; i--) {
                                const p = trailRef.current[i];
                                const age = (trailNow - p.t) / 620;
                                if (age >= 1) continue;
                                const vlen = Math.hypot(p.vx, p.vy);
                                if (vlen < 0.001) continue;
                                const dirX = p.vx / vlen;
                                const dirY = p.vy / vlen;

                                // Vector from trail sample to this dot.
                                const rx = x - p.x;
                                const ry = y - p.y;
                                const longitudinal = rx * dirX + ry * dirY;

                                // Keep wake mostly behind movement direction, with tiny lead allowance.
                                if (longitudinal > 18 || longitudinal < -wakeLength) continue;

                                const latX = rx - dirX * longitudinal;
                                const latY = ry - dirY * longitudinal;
                                const lateralDist = Math.hypot(latX, latY);
                                if (lateralDist > wakeHalfWidth) continue;

                                const behindT = longitudinal < 0 ? Math.min(1, -longitudinal / wakeLength) : 0.2;
                                const lateralT = 1 - lateralDist / wakeHalfWidth;
                                const ageT = 1 - age;
                                const wt = behindT * lateralT * ageT;
                                if (wt <= 0.001) continue;

                                // Pull toward trail centerline and gently advect forward to realign.
                                const latNx = lateralDist > 0.0001 ? latX / lateralDist : 0;
                                const latNy = lateralDist > 0.0001 ? latY / lateralDist : 0;
                                const centerPull = wt * 6.2;
                                const flowPush = wt * 2.8;

                                px -= latNx * centerPull;
                                py -= latNy * centerPull;
                                px += dirX * flowPush;
                                py += dirY * flowPush;
                                alpha += wt * 0.1;
                            }
                    }

                    // Propagating ripple waves: travel outward and fade.
                    for (let i = rippleRef.current.length - 1; i >= 0; i--) {
                            const r = rippleRef.current[i];
                            const ageMs = now - r.t;
                            if (ageMs <= 0 || ageMs > rippleFadeMs) continue;
                            const rx = x - r.x;
                            const ry = y - r.y;
                            const rd = Math.sqrt(rx * rx + ry * ry) || 0.0001;
                            const front = ageMs * rippleSpeed;
                            const delta = Math.abs(rd - front);
                            if (delta > rippleBand) continue;

                            const dirx = rx / rd;
                            const diry = ry / rd;
                            const bandFalloff = 1 - delta / rippleBand;
                            const ageFalloff = 1 - ageMs / rippleFadeMs;
                            const osc = Math.sin((rd - front) * 0.22);
                            const amp = bandFalloff * ageFalloff * (3.4 + r.p * 2.6);

                            px += dirx * amp * osc;
                            py += diry * amp * osc;
                            alpha = Math.max(alpha, 0.11 + bandFalloff * ageFalloff * (0.18 + r.p * 0.12));
                            dotSize = Math.max(dotSize, 1.0 + bandFalloff * (0.72 + r.p * 0.34));
                    }

                    ctx.fillStyle = theme === 'light'
                        ? `rgba(34, 52, 88, ${alpha.toFixed(3)})`
                        : `rgba(168, 191, 235, ${alpha.toFixed(3)})`;
                    ctx.beginPath();
                    ctx.arc(px, py, dotSize, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
            rafId = requestAnimationFrame(render);
        };

        resize();
        rafId = requestAnimationFrame(render);
        window.addEventListener('resize', resize);

        return () => {
            cancelAnimationFrame(rafId);
            window.removeEventListener('resize', resize);
        };
    }, [theme]);

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
            ref={sceneRef}
            className="flex-center"
            style={{
            width: '100vw',
            height: '100vh',
            background: theme === 'light'
                ? 'radial-gradient(120% 90% at 16% 18%, #eef3fb 0%, #dce5f2 54%, #cfd9ea 100%)'
                : 'radial-gradient(120% 100% at 18% 18%, rgba(46, 92, 198, 0.30) 0%, rgba(13, 31, 78, 0.12) 46%, rgba(0,0,0,0) 70%), radial-gradient(96% 86% at 86% 84%, rgba(58, 132, 224, 0.22) 0%, rgba(11, 34, 86, 0.10) 44%, rgba(0,0,0,0) 72%), linear-gradient(138deg, #020817 0%, #07142e 46%, #0d2b5b 100%)',
            position: 'relative',
            overflow: 'hidden'
        }}
            onMouseMove={(e) => {
                if (!mouseRef.current.enabled || !meshCanvasRef.current) return;
                const rect = meshCanvasRef.current.getBoundingClientRect();
                const nx = e.clientX - rect.left;
                const ny = e.clientY - rect.top;
                const prevX = mouseRef.current.x;
                const prevY = mouseRef.current.y;
                const vx = nx - prevX;
                const vy = ny - prevY;
                const speed = Math.hypot(vx, vy);
                mouseRef.current.x = nx;
                mouseRef.current.y = ny;
                mouseRef.current.vx = vx;
                mouseRef.current.vy = vy;
                mouseRef.current.speed = speed;
                mouseRef.current.active = true;
                trailRef.current.push({
                    x: nx,
                    y: ny,
                    vx,
                    vy,
                    t: performance.now()
                });
                if (trailRef.current.length > 18) {
                    trailRef.current.splice(0, trailRef.current.length - 18);
                }
            }}
            onMouseDown={(e) => {
                if (!mouseRef.current.enabled || !meshCanvasRef.current) return;
                const rect = meshCanvasRef.current.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                const now = performance.now();
                rippleRef.current.push({ x, y, t: now, p: 0.95 });
                rippleRef.current.push({ x, y, t: now + 58, p: 0.62 });
                if (rippleRef.current.length > 28) {
                    rippleRef.current.splice(0, rippleRef.current.length - 28);
                }
            }}
            onMouseLeave={() => {
                mouseRef.current.active = false;
                trailRef.current = [];
            }}
        >
            <canvas
                ref={meshCanvasRef}
                aria-hidden="true"
                style={{
                    position: 'absolute',
                    top: '-5vh',
                    left: '-5vw',
                    width: '110vw',
                    height: '110vh',
                    zIndex: 1,
                    pointerEvents: 'none',
                    opacity: 1
                }}
            />

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
                    : 'radial-gradient(circle, rgba(90, 132, 216, 0.16) 0%, rgba(90,132,216,0.05) 44%, rgba(0,0,0,0) 76%)',
                filter: 'blur(78px)',
                zIndex: 1,
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
                    : 'radial-gradient(circle, rgba(78, 196, 220, 0.12) 0%, rgba(78,196,220,0.04) 40%, rgba(0,0,0,0) 74%)',
                filter: 'blur(90px)',
                zIndex: 1,
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
                zIndex: 2
            }} />

            {/* Vignette */}
            <div style={{
                position: 'absolute',
                inset: 0,
                background: theme === 'light'
                    ? 'radial-gradient(circle at center, transparent 44%, rgba(168,178,197,0.22) 100%)'
                    : 'radial-gradient(circle at center, transparent 48%, rgba(0,0,0,0.42) 100%)',
                pointerEvents: 'none',
                zIndex: 3
            }} />

            <form onSubmit={handleSubmit} style={{
                width: '360px',
                maxWidth: 'calc(100vw - 28px)',
                padding: '28px 24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '14px',
                borderRadius: '16px',
                background: theme === 'light' ? 'rgba(244, 247, 253, 0.66)' : 'rgba(20, 22, 32, 0.55)',
                backdropFilter: 'blur(16px)',
                border: theme === 'light' ? '1px solid rgba(20, 28, 46, 0.14)' : '1px solid rgba(255, 255, 255, 0.12)',
                boxShadow: theme === 'light'
                    ? '0 30px 84px rgba(28, 42, 68, 0.24), 0 0 38px rgba(94,122,178,0.08)'
                    : '0 40px 120px rgba(0,0,0,0.65), 0 0 60px rgba(100,130,190,0.08)',
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
                    border-color: rgba(120, 150, 200, 0.45) !important;
                    box-shadow: 0 0 18px rgba(120, 150, 200, 0.12) !important;
                }
                .login-submit {
                    background: linear-gradient(135deg, rgba(110,130,190,0.90), rgba(80,100,160,0.90)) !important;
                    transition: transform 180ms ease, filter 180ms ease, box-shadow 180ms ease !important;
                    box-shadow: 0 8px 20px rgba(28, 40, 66, 0.26);
                }
                .login-submit:hover:not(:disabled) {
                    transform: translateY(-1px);
                    filter: brightness(1.04);
                    box-shadow: 0 10px 24px rgba(28, 40, 66, 0.32);
                }
                .login-submit:active:not(:disabled) {
                    transform: translateY(0);
                    filter: brightness(0.98);
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
