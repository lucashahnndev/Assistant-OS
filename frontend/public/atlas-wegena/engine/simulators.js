/**
 * Base Simulator Interface for Wegena Engine
 */
class BaseSimulator {
    constructor(engine) {
        this.engine = engine;
    }

    // Called once per frame
    update(time, delta) {}

    // Called when switching to this simulator
    activate() {}

    // Called when switching away from this simulator
    deactivate() {}

    // Synchronize data if needed
    sync(otherSimulator) {}
}

/**
 * CPUSimulator - Legacy CPU-based particle dynamics
 */
class CPUSimulator extends BaseSimulator {
    update(time, delta) {
        const reorg = this.engine.visualState?.reorganization || {};
        const reorgActive = !!reorg.active;
        const hasDynamicRoles = !!this.engine.visualState?.hasDynamicRoles;
        const hasActiveFx = this.engine.visualState?.fxFragments && this.engine.visualState.fxFragments.length > 0;
        
        // Zero CPU overhead for settled, static scenes!
        if (!reorgActive && !hasDynamicRoles && !hasActiveFx) {
            return;
        }

        const { activeCount: pCount } = this.engine.config;
        const { positions, basePositions, targetPositions, colors, targetColors, roles, transitionAlpha, reorganizationInfluence } = this.engine;
        const minAlpha = reorg.minAlpha ?? 0.18;
        const maxDurationMs = reorg.maxDurationMs ?? 1100;
        const elapsedMs = reorgActive ? (this.engine._now() - (reorg.startedAt || 0)) : 0;
        const envelope = reorgActive ? Math.max(0, 1 - (elapsedMs / Math.max(1, maxDurationMs))) : 0;
        
        let i3 = 0;
        for (let i = 0; i < pCount; i++) {
            const role = roles[i];
            let tx = targetPositions[i3], ty = targetPositions[i3+1], tz = targetPositions[i3+2];
            
            if (role === 0) {
                const bx = basePositions[i3], by = basePositions[i3+1], bz = basePositions[i3+2];
                tx = bx + Math.sin(time*0.2+i)*5;
                ty = by + Math.cos(time*0.15+i*0.5)*5;
                tz = bz + Math.sin(time*0.1+i*2)*5;
            } else if (role === 1) {
                const bx = basePositions[i3], by = basePositions[i3+1], bz = basePositions[i3+2];
                const angle = time * 0.2, cos = Math.cos(angle), sin = Math.sin(angle), rx = bx*cos + bz*sin, rz = -bx*sin + bz*cos, b=1 + Math.sin(time+i*0.1)*0.02;
                tx = rx*b; ty = by*b; tz = rz*b;
            }
            
            positions[i3] += (tx - positions[i3]) * 0.05;
            positions[i3+1] += (ty - positions[i3+1]) * 0.05;
            positions[i3+2] += (tz - positions[i3+2]) * 0.05;

            if (transitionAlpha) {
                if (reorgActive) {
                    const influence = reorganizationInfluence ? (reorganizationInfluence[i] || 0) : 0;
                    const smooth = influence * influence * (3 - 2 * influence);
                    transitionAlpha[i] = 1 - (smooth * envelope) * (1 - minAlpha);
                } else {
                    transitionAlpha[i] = 1;
                }
            }
            
            colors[i3] += (targetColors[i3] - colors[i3]) * 0.05;
            colors[i3+1] += (targetColors[i3+1] - colors[i3+1]) * 0.05;
            colors[i3+2] += (targetColors[i3+2] - colors[i3+2]) * 0.05;
            
            i3 += 3;
        }
    }
}

/**
 * GPUSimulator - GPGPU-based particle simulation (Placeholder)
 * This will be expanded in Phase 3.
 */
class GPUSimulator extends BaseSimulator {
    constructor(engine) {
        super(engine);
        this.isGpuReady = false;
    }

    activate() {
        console.warn("[GPUSimulator] Activated. Running in bridge mode.");
    }

    update(time, delta) {
        // Fallback to CPU calculation for now until Shaders are ready
        // This ensures the toggle works visually without freezing the UI
        this.engine.simulators.cpu.update(time, delta);
    }
}
