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
    constructor(bus, theme = 'dark') {
        this.bus = bus;
        this.state = "idle";
        this.theme = theme;

        this.targetBreathScore = 0.20; // 0..1
        this.breathScore = 0.20;       // smoothed
        this.extraPulse = 0.0;
        this.extraPulseDecay = 240;

        this.stateDefaults = {
            idle: 0.20,
            listening: 0.38,
            thinking: 0.12, // Shrunk
            speaking: 0.82,
        };

        this.vibration = 0.0;
        this.palette = this.getPaletteForState("idle");

        this.bus.on("orb.breathScore", ({ score }) => this.setBreathScore(score));
        this.bus.on("orb.state", ({ state, theme }) => this.setState(state, theme));
        this.bus.on("orb.pulse", (p) => this.pulse(p || {}));
        this.bus.on("orb.storm", ({ on }) => this.setStorm(on));
    }

    setState(stateName, theme) {
        if (!this.stateDefaults[stateName]) return;
        this.state = stateName;
        if (theme) this.theme = theme;
        this.palette = this.getPaletteForState(stateName, this.theme);
        this.setBreathScore(this.stateDefaults[stateName]);
    }

    getPaletteForState(state, theme = 'dark') {
        const darkPalettes = {
            idle: {
                shellEdge: "rgba(80, 120, 255, 0.22)",
                shellFill: "rgba(35, 60, 190, 0.08)",
                coreA: "rgba(200, 235, 255, 1.00)",
                coreB: "rgba(90, 140, 255, 0.95)",
                rays: "rgba(80, 120, 255, 0.20)",
                filaments: "rgba(140, 180, 255, 0.18)",
                node: "rgba(210, 235, 255, 0.65)",
                backLight: "rgba(60, 100, 255, 0.15)"
            },
            listening: {
                shellEdge: "rgba(0, 255, 255, 0.25)",
                shellFill: "rgba(0, 80, 80, 0.10)",
                coreA: "rgba(200, 255, 255, 1.00)",
                coreB: "rgba(0, 220, 255, 0.98)",
                rays: "rgba(0, 255, 255, 0.35)",
                filaments: "rgba(100, 255, 255, 0.30)",
                node: "rgba(200, 255, 255, 0.90)",
                backLight: "rgba(0, 255, 255, 0.25)"
            },
            thinking: {
                shellEdge: "rgba(100, 100, 255, 0.20)",
                shellFill: "rgba(20, 20, 60, 0.08)",
                coreA: "rgba(180, 180, 255, 0.85)",
                coreB: "rgba(70, 70, 220, 0.80)",
                rays: "rgba(100, 100, 255, 0.15)",
                filaments: "rgba(100, 100, 255, 0.15)",
                node: "rgba(160, 160, 255, 0.50)",
                backLight: "rgba(80, 80, 255, 0.12)"
            },
            speaking: {
                shellEdge: "rgba(220, 120, 255, 0.35)",
                shellFill: "rgba(80, 20, 160, 0.12)",
                coreA: "rgba(245, 210, 255, 1.00)",
                coreB: "rgba(200, 80, 255, 0.98)",
                rays: "rgba(220, 100, 255, 0.40)",
                filaments: "rgba(230, 140, 255, 0.35)",
                node: "rgba(245, 220, 255, 0.90)",
                backLight: "rgba(200, 80, 255, 0.30)"
            }
        };

        const lightPalettes = {
            idle: {
                shellEdge: "rgba(90, 150, 255, 0.45)",
                shellFill: "rgba(90, 150, 255, 0.04)",
                coreA: "rgba(70, 130, 255, 1.00)",
                coreB: "rgba(100, 160, 255, 0.90)",
                rays: "rgba(90, 150, 255, 0.40)",
                filaments: "rgba(90, 150, 255, 0.35)",
                node: "rgba(70, 130, 255, 0.85)",
                backLight: "rgba(120, 180, 255, 0.15)"
            },
            listening: {
                shellEdge: "rgba(0, 220, 220, 0.55)",
                shellFill: "rgba(0, 220, 220, 0.06)",
                coreA: "rgba(0, 180, 180, 1.00)",
                coreB: "rgba(40, 220, 240, 0.95)",
                rays: "rgba(0, 220, 220, 0.50)",
                filaments: "rgba(0, 220, 220, 0.45)",
                node: "rgba(0, 180, 180, 0.90)",
                backLight: "rgba(60, 240, 240, 0.20)"
            },
            thinking: {
                shellEdge: "rgba(130, 130, 240, 0.45)",
                shellFill: "rgba(130, 130, 240, 0.04)",
                coreA: "rgba(110, 110, 200, 0.95)",
                coreB: "rgba(130, 130, 220, 0.85)",
                rays: "rgba(130, 130, 240, 0.30)",
                filaments: "rgba(130, 130, 240, 0.30)",
                node: "rgba(110, 110, 200, 0.75)",
                backLight: "rgba(150, 150, 240, 0.15)"
            },
            speaking: {
                shellEdge: "rgba(220, 120, 255, 0.60)",
                shellFill: "rgba(220, 120, 255, 0.06)",
                coreA: "rgba(200, 80, 255, 1.00)",
                coreB: "rgba(220, 120, 255, 1.00)",
                rays: "rgba(220, 120, 255, 0.55)",
                filaments: "rgba(220, 120, 255, 0.50)",
                node: "rgba(200, 80, 255, 0.95)",
                backLight: "rgba(230, 150, 255, 0.25)"
            }
        };

        const activeSet = theme === 'light' ? lightPalettes : darkPalettes;
        return activeSet[state] || activeSet.idle;
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

    setVibration(v) {
        this.vibration = clamp01(v);
    }

    update(dtMs) {
        const smoothing = 1 - Math.pow(0.001, dtMs / 1000);
        this.breathScore += (this.targetBreathScore - this.breathScore) * smoothing;

        if (this.extraPulse > 0) {
            const decay = dtMs / this.extraPulseDecay;
            this.extraPulse = Math.max(0, this.extraPulse - decay);
        }

        // Decay vibration
        if (this.vibration > 0) {
            this.vibration *= Math.max(0, 1 - dtMs / 300);
        }
    }

    getAnimParams(timeSec) {
        let s = clamp01(this.breathScore + this.extraPulse * 0.55);

        // storm just boosts internal activity for preview
        const stormBoost = this.storm ? 0.22 : 0;
        s = clamp01(s + stormBoost);

        const state = this.state;
        const stateChaos = (state === "thinking") ? 1.45 : (state === "speaking" ? 0.95 : (state === "listening" ? 0.55 : 0.35));
        const stateRays = (state === "thinking") ? 0.40 : (state === "speaking" ? 1.25 : 0.85);

        const breathHz = 0.16 + 0.26 * s;        // 0.16..0.42
        const amp = 0.018 + 0.085 * s;      // 1.8%..10.3%
        const jitter = (0.0018 + 0.010 * s + this.vibration * 0.15) * stateChaos;

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
            nodeSpeed,
            palette: this.palette
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
const specks = Array.from({ length: 450 }, () => ({
    x: rand(2.2) - 1.1, // expanded range
    y: rand(2.2) - 1.1,
    z: rand(1),
    w: 0.3 + rand(0.7),
    t: rand(20)
}));

// ---------------- Rendering helpers ----------------
function drawBackground(ctx, w, h, theme = 'dark') {
    // Clear the canvas to make it transparent
    ctx.clearRect(0, 0, w, h);
    if (!ctx.canvas.parentElement) return;

    // subtle vignette + adaptive fog (center) - Expanded to fill entire stage
    const cx = w * 0.5, cy = h * 0.5;
    const fogRadius = Math.max(w, h) * 1.2;
    const fog = ctx.createRadialGradient(cx, cy, 10, cx, cy, fogRadius);
    const fogColor = theme === 'light' ? "rgba(255, 255, 255, 0.2)" : "rgba(10, 20, 60, 0.25)";

    fog.addColorStop(0, fogColor);
    fog.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = fog;
    ctx.fillRect(0, 0, w, h); // Fill whole canvas instead of arc
}

function drawBackLight(ctx, cx, cy, r, s, vibration, p) {
    ctx.save();
    ctx.globalCompositeOperation = "lighter";

    // Core radius for the backlight is smaller than main orb when idling
    // Base scale is 0.85 of orb radius, grows with vibration
    const baseScale = 0.85 + vibration * 0.95;
    const br = r * baseScale;

    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, br * 2.8); // Wider backlight

    const color = p.backLight || "rgba(60, 100, 255, 0.15)";
    const colorPart = color.substring(0, color.lastIndexOf(','));
    const intensity = 0.25 + vibration * 0.45; // slightly dimmer center to benefit corners

    grad.addColorStop(0.0, `${colorPart}, ${intensity})`);
    grad.addColorStop(0.4, `${colorPart}, ${intensity * 0.4})`);
    grad.addColorStop(1.0, "rgba(0,0,0,0)");

    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, br * 2.8, 0, TAU);
    ctx.fill();
    ctx.restore();
}

function drawAtmosphere(ctx, w, h, s, vibration, p, theme = 'dark') {
    ctx.save();
    ctx.globalCompositeOperation = "lighter";

    const color = p.backLight || "rgba(60, 100, 255, 0.15)";
    const colorPart = color.substring(0, color.lastIndexOf(','));

    // Ambient breathing intensity
    const ambientIntensity = (0.04 + s * 0.08 + vibration * 0.12) * (theme === 'light' ? 0.35 : 1.0);

    // Draw glows in corners
    const cornerRadius = Math.max(w, h) * 0.5;
    const corners = [
        [0, 0], [w, 0], [0, h], [w, h],
        [w * 0.5, h] // Optional bottom-center boost for the 'underglow'
    ];

    corners.forEach(([x, y], i) => {
        const g = ctx.createRadialGradient(x, y, 0, x, y, cornerRadius);
        // Alternate colors slightly or just use backlight
        const mult = i === 4 ? 1.5 : 1.0; // Boost bottom center
        g.addColorStop(0, `${colorPart}, ${ambientIntensity * mult})`);
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
    });

    ctx.restore();
}

function drawOuterHalo(ctx, cx, cy, r, shellIntensity, p) {
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const halo = ctx.createRadialGradient(cx, cy, r * 0.2, cx, cy, r * 2.6);

    // Extract base color from rays or shellEdge
    const color = p.rays || "rgba(80, 120, 255, 0.20)";
    const colorPart = color.substring(0, color.lastIndexOf(','));

    halo.addColorStop(0.00, `${colorPart}, ${0.12 + 0.18 * shellIntensity})`);
    halo.addColorStop(0.35, `${colorPart}, ${0.08 + 0.10 * shellIntensity})`);
    halo.addColorStop(1.00, "rgba(0,0,0,0)");
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 2.6, 0, TAU);
    ctx.fill();
    ctx.restore();
}

function drawShell(ctx, cx, cy, r, shellIntensity, p) {
    const shellGrad = ctx.createRadialGradient(cx - r * 0.25, cy - r * 0.28, r * 0.15, cx, cy, r * 1.10);
    shellGrad.addColorStop(0.0, p.coreA);
    shellGrad.addColorStop(0.5, p.shellEdge);
    shellGrad.addColorStop(1.0, p.shellFill);

    ctx.fillStyle = shellGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, TAU);
    ctx.fill();

    // membrane edge
    ctx.strokeStyle = p.shellEdge;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, TAU);
    ctx.stroke();
}

function drawInternalRays(ctx, cx, cy, r, t, strength, jitter, density, p) {
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
        const alphaMid = 0.25 * strength;

        const color = p.rays;
        const colorPart = color.substring(0, color.lastIndexOf(','));

        g.addColorStop(0.00, `${colorPart}, 0)`);
        g.addColorStop(0.45, `${colorPart}, ${alphaMid})`);
        g.addColorStop(1.00, `${colorPart}, 0)`);

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

function drawFilaments(ctx, cx, cy, r, t, jitter, density, p) {
    const count = Math.floor(22 + 38 * density); // 22..60
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.clip(circlePath(cx, cy, r));

    ctx.strokeStyle = p.filaments;
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

function drawSpecks(ctx, cx, cy, r, t, density, w, h) {
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    // REMOVED: ctx.clip(circlePath(cx, cy, r)); -- now global particles

    for (let i = 0; i < specks.length; i++) {
        const p = specks[i];
        const drift = 0.02 + 0.05 * density;
        const nx = p.x + 0.05 * Math.sin(t * drift + p.t);
        const ny = p.y + 0.05 * Math.cos(t * drift + p.t * 0.7);

        // Map relative -1..1 to 0..w/h with some padding
        const px = cx + nx * (w * 0.6);
        const py = cy + ny * (h * 0.6);

        // Check if on screen
        if (px < -20 || px > w + 20 || py < -20 || py > h + 20) continue;

        const depth = 0.25 + 0.75 * p.z;
        const a = (0.01 + 0.04 * density) * depth * p.w;

        ctx.fillStyle = `rgba(200,230,255,${a})`;
        ctx.beginPath();
        ctx.arc(px, py, 0.5 + 1.2 * p.z, 0, TAU);
        ctx.fill();
    }

    ctx.restore();
}

function drawCore(ctx, cx, cy, r, t, coreIntensity, density, p) {
    ctx.save();
    ctx.globalCompositeOperation = "lighter";

    const coreR = r * (0.23 + 0.10 * density);
    const pulse = 0.06 * Math.sin(t * 1.7) + 0.04 * Math.sin(t * 2.4 + 1.2);
    const rr = coreR * (1 + pulse);

    const coreGrad = ctx.createRadialGradient(cx - rr * 0.25, cy - rr * 0.25, rr * 0.12, cx, cy, rr * 1.9);

    // Extract alpha part for coreGrad
    const coreA = p.coreA;
    const aPartA = coreA.substring(0, coreA.lastIndexOf(','));
    const coreB = p.coreB;
    const aPartB = coreB.substring(0, coreB.lastIndexOf(','));

    coreGrad.addColorStop(0.00, `${aPartA}, ${0.48 * coreIntensity})`);
    coreGrad.addColorStop(0.35, `${aPartB}, ${0.26 * coreIntensity})`);
    coreGrad.addColorStop(1.00, "rgba(0,0,0,0)");

    ctx.fillStyle = coreGrad;
    ctx.beginPath();
    ctx.arc(cx, cy, rr * 1.9, 0, TAU);
    ctx.fill();

    ctx.restore();
}

function drawOrbitNode(ctx, cx, cy, r, t, s, speed, p) {
    const orbitR = r * 0.62;
    const a = t * speed + 1.1;
    const x = cx + Math.cos(a) * orbitR;
    const y = cy + Math.sin(a) * orbitR * 0.55;

    // glow
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const g = ctx.createRadialGradient(x, y, 0.5, x, y, 18);

    const nodeC = p.node;
    const nPart = nodeC.substring(0, nodeC.lastIndexOf(','));

    g.addColorStop(0.0, `${nPart}, ${0.22 + 0.20 * s})`);
    g.addColorStop(1.0, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, 18, 0, TAU);
    ctx.fill();

    // dot
    ctx.fillStyle = `${nPart}, ${0.35 + 0.30 * s})`;
    ctx.beginPath();
    ctx.arc(x, y, 4.5, 0, TAU);
    ctx.fill();

    // subtle outline
    ctx.strokeStyle = p.filaments;
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

        // Use ResizeObserver for more robust sizing (e.g., sidebar toggles)
        const resizeObserver = new ResizeObserver(resize);
        if (canvas.parentElement) {
            resizeObserver.observe(canvas.parentElement);
        }

        // Initial resize
        resize();

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
            const cy = ph * 0.38; // Shifted up further from 0.43

            const params = orbCtrl.getAnimParams(t);
            // Smaller radius ratio based on height for better proportionality
            const baseR = ph * 0.18;
            const r = baseR * params.radiusScale;

            drawBackground(ctx, pw, ph, orbCtrl.theme);
            drawAtmosphere(ctx, pw, ph, params.s, orbCtrl.vibration, params.palette, orbCtrl.theme);
            drawBackLight(ctx, cx, cy, r, params.s, orbCtrl.vibration, params.palette);
            drawOuterHalo(ctx, cx, cy, r, params.shellIntensity, params.palette);
            drawInternalRays(ctx, cx, cy, r, t, params.raysStrength, params.jitter, params.density, params.palette);
            drawFilaments(ctx, cx, cy, r, t, params.jitter, params.density, params.palette);
            drawSpecks(ctx, cx, cy, r, t, params.density, pw, ph);
            drawShell(ctx, cx, cy, r, params.shellIntensity, params.palette);
            drawCore(ctx, cx, cy, r, t, params.coreIntensity, params.density, params.palette);
            drawOrbitNode(ctx, cx, cy, r, t, params.s, params.nodeSpeed, params.palette);

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
        setState: (state, theme) => busRef.current?.emit("orb.state", { state, theme }),
        pulse: ({ score, ms } = {}) => busRef.current?.emit("orb.pulse", { score, ms }),
        setVibration: (v) => orbRef.current?.setVibration(v),
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
