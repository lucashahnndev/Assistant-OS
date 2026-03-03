import React, { useEffect, useRef, useImperativeHandle, forwardRef } from 'react';

// ---------------- Utilities ----------------
const clamp01 = (v) => Math.max(0, Math.min(1, v));
const lerp = (a, b, t) => a + (b - a) * t;
const smoothstep = (t) => t * t * (3 - 2 * t);
const rand = (a = 1) => Math.random() * a;
const TAU = Math.PI * 2;

// A tiny deterministic-ish noise from sine combos (cheap & good enough)
function pseudoNoise(x, y, t) {
    return Math.sin(x * 1.31 + t * 0.8) * 0.45
        + Math.sin(y * 1.73 + t * 0.6) * 0.35
        + Math.sin((x + y) * 0.87 + t * 0.9) * 0.20;
}

// ---------------- Event bus ----------------
class EventBus {
    constructor() { this.handlers = new Map(); }
    on(name, fn) {
        if (!this.handlers.has(name)) this.handlers.set(name, []);
        this.handlers.get(name).push(fn);
    }
    emit(name, payload) {
        const list = this.handlers.get(name) || [];
        for (const fn of list) fn(payload);
    }
}

// ---------------- Orb state/controller ----------------
class AtlasOrb {
    constructor(bus) {
        this.bus = bus;
        this.state = "idle";

        this.targetBreathScore = 0.20; // 0..1
        this.breathScore = 0.20;       // smoothed
        this.extraPulse = 0.0;
        this.extraPulseDecay = 240;

        this.stateDefaults = {
            idle: 0.20,
            listening: 0.38,
            thinking: 0.68,
            speaking: 0.82,
        };

        // "storm" mode for testing internal intensity
        this.storm = false;

        this.bus.on("orb.breathScore", ({ score }) => this.setBreathScore(score));
        this.bus.on("orb.state", ({ state }) => this.setState(state));
        this.bus.on("orb.pulse", (p) => this.pulse(p || {}));
        this.bus.on("orb.storm", ({ on }) => this.setStorm(on));
    }

    setState(stateName) {
        if (!this.stateDefaults[stateName]) return;
        this.state = stateName;
        this.setBreathScore(this.stateDefaults[stateName]);
    }

    setBreathScore(score) {
        this.targetBreathScore = clamp01(Number(score));
    }

    pulse({ score = 0.9, ms = 260 } = {}) {
        const s = clamp01(Number(score));
        this.extraPulse = Math.max(this.extraPulse, s);
        this.extraPulseDecay = Math.max(90, Number(ms));
    }

    setStorm(on) { this.storm = !!on; }

    update(dtMs) {
        const smoothing = 1 - Math.pow(0.001, dtMs / 1000);
        this.breathScore += (this.targetBreathScore - this.breathScore) * smoothing;

        if (this.extraPulse > 0) {
            const decay = dtMs / this.extraPulseDecay;
            this.extraPulse = Math.max(0, this.extraPulse - decay);
        }
    }

    getAnimParams(timeSec) {
        let s = clamp01(this.breathScore + this.extraPulse * 0.55);

        // storm just boosts internal activity for preview
        const stormBoost = this.storm ? 0.22 : 0;
        s = clamp01(s + stormBoost);

        const state = this.state;
        const stateChaos = (state === "thinking") ? 1.15 : (state === "speaking" ? 0.95 : (state === "listening" ? 0.55 : 0.35));
        const stateRays = (state === "thinking") ? 1.20 : (state === "speaking" ? 1.05 : 0.75);

        const breathHz = 0.16 + 0.26 * s;        // 0.16..0.42
        const amp = 0.018 + 0.085 * s;      // 1.8%..10.3%
        const jitter = (0.0018 + 0.010 * s) * stateChaos;

        const coreIntensity = 0.40 + 1.05 * s;  // multiplier
        const shellIntensity = 0.20 + 0.65 * s;

        // imperfect breathing wave
        const base = Math.sin(TAU * breathHz * timeSec);
        const wobble = 0.28 * Math.sin(TAU * (breathHz * 2.07) * timeSec + 1.3);
        const breath = base + wobble;

        const radiusScale = 1 + amp * breath;

        // Rays: stronger with "thinking/speaking"
        const raysStrength = (0.10 + 0.55 * s) * stateRays;

        // Internal density controls how many particles/filaments show up
        const density = 0.20 + 0.80 * s;

        // Orbiting node speed
        const nodeSpeed = 0.12 + 0.35 * s;

        return {
            s, state,
            radiusScale,
            coreIntensity,
            shellIntensity,
            jitter,
            raysStrength,
            density,
            nodeSpeed
        };
    }
}

// ---------------- Palette ----------------
const palette = {
    bg0: "#03040a",
    bg1: "rgba(10, 20, 60, 0.25)",  // subtle blue fog
    shellEdge: "rgba(80, 120, 255, 0.22)",
    shellFill: "rgba(35, 60, 190, 0.10)",
    coreA: "rgba(200, 235, 255, 1.00)",
    coreB: "rgba(90, 140, 255, 0.95)",
    rays: "rgba(80, 120, 255, 0.20)",
    filaments: "rgba(140, 180, 255, 0.18)",
    dust: "rgba(200, 230, 255, 0.12)",
    node: "rgba(210, 235, 255, 0.65)"
};

// ---------------- Pre-generate particles/dust ----------------
const specks = Array.from({ length: 220 }, () => ({
    x: rand(2) - 1,
    y: rand(2) - 1,
    z: rand(1),
    w: 0.4 + rand(0.6),
    t: rand(10)
})).filter(p => (p.x * p.x + p.y * p.y) <= 1);

// ---------------- Rendering helpers ----------------
function drawBackground(ctx, w, h) {
    // Clear the canvas to make it transparent instead of painting a solid background
    ctx.clearRect(0, 0, w, h);

    // subtle vignette + blue fog (center)
    const cx = w * 0.5, cy = h * 0.5;
    const fog = ctx.createRadialGradient(cx, cy, 10, cx, cy, Math.min(w, h) * 0.7);
    fog.addColorStop(0, palette.bg1);
    fog.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = fog;
    ctx.beginPath();
    ctx.arc(cx, cy, Math.min(w, h) * 0.7, 0, TAU);
    ctx.fill();
}

function drawOuterHalo(ctx, cx, cy, r, shellIntensity) {
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const halo = ctx.createRadialGradient(cx, cy, r * 0.2, cx, cy, r * 2.6);
    halo.addColorStop(0.00, `rgba(60, 90, 255, ${0.06 + 0.10 * shellIntensity})`);
    halo.addColorStop(0.35, `rgba(30, 60, 220, ${0.04 + 0.06 * shellIntensity})`);
    halo.addColorStop(1.00, "rgba(0,0,0,0)");
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 2.6, 0, TAU);
    ctx.fill();
    ctx.restore();
}

function drawShell(ctx, cx, cy, r, shellIntensity) {
    const shellGrad = ctx.createRadialGradient(cx - r * 0.25, cy - r * 0.28, r * 0.15, cx, cy, r * 1.10);
    shellGrad.addColorStop(0.0, `rgba(190, 220, 255, ${0.06 + 0.10 * shellIntensity})`);
    shellGrad.addColorStop(0.5, `rgba(60, 100, 255, ${0.05 + 0.10 * shellIntensity})`);
    shellGrad.addColorStop(1.0, `rgba(10, 20, 60, ${0.12 + 0.18 * shellIntensity})`);

    ctx.fillStyle = shellGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, TAU);
    ctx.fill();

    // membrane edge
    ctx.strokeStyle = `rgba(120, 160, 255, ${0.06 + 0.18 * shellIntensity})`;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, TAU);
    ctx.stroke();
}

function drawInternalRays(ctx, cx, cy, r, t, strength, jitter, density) {
    const rayCount = Math.floor(4 + 5 * density); // 4..9
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.clip(circlePath(cx, cy, r));

    for (let i = 0; i < rayCount; i++) {
        const baseA = (i / rayCount) * 0.55 - 0.20; // keep rays mostly vertical-ish
        const a = baseA + 0.10 * Math.sin(t * 0.45 + i) + pseudoNoise(i * 0.3, 0.2, t) * 0.04;

        const x = cx + Math.sin(a) * r * 0.22;
        const y = cy - r * 0.95;

        const g = ctx.createLinearGradient(x, y, x + Math.sin(a) * r * 0.2, cy + r * 0.95);
        const alphaTop = 0.00;
        const alphaMid = 0.10 * strength;
        const alphaBot = 0.00;

        g.addColorStop(0.00, `rgba(80,120,255,${alphaTop})`);
        g.addColorStop(0.45, `rgba(80,120,255,${alphaMid})`);
        g.addColorStop(1.00, `rgba(80,120,255,${alphaBot})`);

        ctx.strokeStyle = g;
        ctx.lineWidth = 2 + 8 * strength;
        ctx.beginPath();
        const bend = (Math.sin(t * 0.8 + i) * jitter) * r * 18;
        ctx.moveTo(x, y);
        ctx.quadraticCurveTo(cx + bend, cy, cx + bend * 0.4, cy + r * 0.95);
        ctx.stroke();
    }

    ctx.restore();
}

function drawFilaments(ctx, cx, cy, r, t, jitter, density) {
    const count = Math.floor(22 + 38 * density); // 22..60
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.clip(circlePath(cx, cy, r));

    ctx.strokeStyle = palette.filaments;
    ctx.lineWidth = 1;

    for (let i = 0; i < count; i++) {
        const a = (i / count) * TAU + t * (0.10 + 0.35 * density);
        const wob = (Math.sin(t * 1.1 + i * 0.7) + pseudoNoise(i * 0.2, 0.4, t)) * jitter * r * 26;

        const x1 = cx + Math.cos(a) * (r * (0.12 + 0.12 * density) + wob);
        const y1 = cy + Math.sin(a) * (r * (0.12 + 0.12 * density) - wob);

        const x2 = cx + Math.cos(a + 1.25) * (r * (0.92 - 0.10 * density) - wob);
        const y2 = cy + Math.sin(a + 1.25) * (r * (0.92 - 0.10 * density) + wob);

        ctx.globalAlpha = 0.55 + 0.35 * Math.sin(i * 0.6 + t * 0.7);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.quadraticCurveTo(
            cx + Math.cos(a + 0.6) * (r * 0.22),
            cy + Math.sin(a + 0.6) * (r * 0.22),
            x2, y2
        );
        ctx.stroke();
    }

    ctx.restore();
    ctx.globalAlpha = 1;
}

function drawSpecks(ctx, cx, cy, r, t, density) {
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.clip(circlePath(cx, cy, r));

    for (let i = 0; i < specks.length; i++) {
        const p = specks[i];
        const drift = 0.03 + 0.08 * density;
        const nx = p.x + 0.08 * Math.sin(t * drift + p.t);
        const ny = p.y + 0.08 * Math.cos(t * drift + p.t * 0.7);

        const d = (nx * nx + ny * ny);
        if (d > 1) continue;

        const depth = 0.35 + 0.65 * p.z; // closer -> brighter
        const px = cx + nx * r * (0.92 - 0.10 * p.z);
        const py = cy + ny * r * (0.92 - 0.10 * p.z);

        const a = (0.02 + 0.08 * density) * depth * p.w;
        ctx.fillStyle = `rgba(200,230,255,${a})`;
        ctx.beginPath();
        ctx.arc(px, py, 0.6 + 1.4 * p.z, 0, TAU);
        ctx.fill();
    }

    ctx.restore();
}

function drawCore(ctx, cx, cy, r, t, coreIntensity, density) {
    ctx.save();
    ctx.globalCompositeOperation = "lighter";

    const coreR = r * (0.23 + 0.10 * density);
    const pulse = 0.06 * Math.sin(t * 1.7) + 0.04 * Math.sin(t * 2.4 + 1.2);
    const rr = coreR * (1 + pulse);

    const coreGrad = ctx.createRadialGradient(cx - rr * 0.25, cy - rr * 0.25, rr * 0.12, cx, cy, rr * 1.9);
    coreGrad.addColorStop(0.00, `rgba(230,255,255,${0.48 * coreIntensity})`);
    coreGrad.addColorStop(0.35, `rgba(120,170,255,${0.26 * coreIntensity})`);
    coreGrad.addColorStop(1.00, "rgba(0,0,0,0)");

    ctx.fillStyle = coreGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, rr * 1.9, 0, TAU);
    ctx.fill();

    ctx.restore();
}

function drawOrbitNode(ctx, cx, cy, r, t, s, speed) {
    const orbitR = r * 0.62;
    const a = t * speed + 1.1;
    const x = cx + Math.cos(a) * orbitR;
    const y = cy + Math.sin(a) * orbitR * 0.55;

    // glow
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const g = ctx.createRadialGradient(x, y, 0.5, x, y, 18);
    g.addColorStop(0.0, `rgba(210,235,255,${0.22 + 0.20 * s})`);
    g.addColorStop(1.0, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, 18, 0, TAU);
    ctx.fill();

    // dot
    ctx.fillStyle = `rgba(230,250,255,${0.35 + 0.30 * s})`;
    ctx.beginPath();
    ctx.arc(x, y, 4.5, 0, TAU);
    ctx.fill();

    // subtle outline
    ctx.strokeStyle = `rgba(140,180,255,${0.18 + 0.18 * s})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(x, y, 7.0, 0, TAU);
    ctx.stroke();

    ctx.restore();
}

function circlePath(cx, cy, r) {
    const p = new Path2D();
    p.arc(cx, cy, r, 0, TAU);
    return p;
}

// ---------------- React Component ----------------
const AtlasOrbCanvas = forwardRef((props, ref) => {
    const canvasRef = useRef(null);
    const orbRef = useRef(null);
    const busRef = useRef(null);
    const reqRef = useRef(null);
    const lastTimeRef = useRef(0);

    // Initialize logic
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d", { alpha: true });

        busRef.current = new EventBus();
        orbRef.current = new AtlasOrb(busRef.current);

        function resize() {
            if (!canvas.parentElement) return;
            const pw = canvas.parentElement.clientWidth;
            const ph = canvas.parentElement.clientHeight;
            const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));

            canvas.width = Math.floor(pw * dpr);
            canvas.height = Math.floor(ph * dpr);
            canvas.style.width = pw + "px";
            canvas.style.height = ph + "px";
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }
        window.addEventListener("resize", resize);
        // Initial resize
        setTimeout(resize, 0); // Need to wait for DOM attach if width is expanding

        // Main animation loop
        lastTimeRef.current = performance.now();
        function frame(now) {
            const dt = Math.min(50, now - lastTimeRef.current);
            lastTimeRef.current = now;

            const orbCtrl = orbRef.current;
            orbCtrl.update(dt);

            const t = now / 1000;
            const pw = canvas.parentElement?.clientWidth || window.innerWidth;
            const ph = canvas.parentElement?.clientHeight || window.innerHeight;
            const cx = pw * 0.5;
            const cy = ph * 0.5;

            const params = orbCtrl.getAnimParams(t);
            // Smaller radius ratio if in a tight area like dashboard hero
            const baseR = Math.min(pw, ph) * 0.22;
            const r = baseR * params.radiusScale;

            drawBackground(ctx, pw, ph);
            drawOuterHalo(ctx, cx, cy, r, params.shellIntensity);
            drawInternalRays(ctx, cx, cy, r, t, params.raysStrength, params.jitter, params.density);
            drawFilaments(ctx, cx, cy, r, t, params.jitter, params.density);
            drawSpecks(ctx, cx, cy, r, t, params.density);
            drawShell(ctx, cx, cy, r, params.shellIntensity);
            drawCore(ctx, cx, cy, r, t, params.coreIntensity, params.density);
            drawOrbitNode(ctx, cx, cy, r, t, params.s, params.nodeSpeed);

            reqRef.current = requestAnimationFrame(frame);
        }

        reqRef.current = requestAnimationFrame(frame);

        return () => {
            window.removeEventListener("resize", resize);
            cancelAnimationFrame(reqRef.current);
        };
    }, []);

    // Expose APIs
    useImperativeHandle(ref, () => ({
        setBreathScore: (score) => busRef.current?.emit("orb.breathScore", { score }),
        setState: (state) => busRef.current?.emit("orb.state", { state }),
        pulse: ({ score, ms } = {}) => busRef.current?.emit("orb.pulse", { score, ms }),
        storm: (on) => busRef.current?.emit("orb.storm", { on })
    }));

    return (
        <canvas
            ref={canvasRef}
            style={{
                display: 'block',
                width: '100%',
                height: '100%',
                position: 'absolute',
                inset: 0,
                zIndex: 0,
                pointerEvents: 'none' // Background element
            }}
        />
    );
});

export default AtlasOrbCanvas;
