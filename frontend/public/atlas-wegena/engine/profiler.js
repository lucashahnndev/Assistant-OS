/**
 * PerformanceProfiler - Manages hardware detection, benchmarking, 
 * and dynamic density scaling for the Wegena Engine.
 */
class PerformanceProfiler {
    constructor(engine) {
        this.engine = engine;
        this.stats = {
            fps: 0,
            frameTime: 0,
            gpuAvailable: false,
            webgpuSupported: false,
            mode: 'cpu', // Default
            tier: 'unknown'
        };

        this.history = {
            frameTimes: [],
            maxHistory: 60
        };

        this.isBenchmarking = false;
        this.lastUpdateTime = 0;
    }

    async probeHardware() {
        this.stats.webgpuSupported = !!navigator.gpu;
        // Basic WebGL check already done by THREE in WegenaEngine, 
        // but we verify GPGPU capability (texture float/half-float)
        const gl = this.engine.renderer.getContext();
        const floatTex = gl.getExtension('OES_texture_float');
        const floatLin = gl.getExtension('OES_texture_float_linear');
        this.stats.gpuAvailable = !!(floatTex || this.stats.webgpuSupported);
        
        console.log(`[Profiler] Hardware Probing: WebGPU=${this.stats.webgpuSupported}, GPGPU-Ready=${this.stats.gpuAvailable}`);
        
        return this.stats;
    }

    /**
     * Runs a quick stress test to determine initial density.
     * Uses binary search to find a stable particle count at 60fps.
     */
    async runBenchmark() {
        const cached = localStorage.getItem('wegena_perf_tier');
        if (cached) {
            const data = JSON.parse(cached);
            this.stats.tier = data.tier;
            this.stats.initialDensity = data.density;
            return data;
        }

        this.isBenchmarking = true;
        console.log("[Profiler] Starting Benchmark...");
        
        // Lightweight benchmark: check frame time at 25k particles
        const testCount = 25000;
        const originalCount = this.engine.config.activeCount;
        this.engine.setDensity(testCount, false);
        
        return new Promise((resolve) => {
            setTimeout(() => {
                const frameCount = this.history.frameTimes.length || 1;
                const avgFrameTime = this.history.frameTimes.reduce((a, b) => a + b, 0) / frameCount;
                let tier = 'low';
                let density = 10000; // Lightweight baseline

                if (avgFrameTime < 7) { tier = 'high'; density = 30000; }
                else if (avgFrameTime < 13) { tier = 'mid'; density = 20000; }
                else if (avgFrameTime < 20) { tier = 'low'; density = 10000; }

                const result = { tier, density, avgFrameTime };
                localStorage.setItem('wegena_perf_tier', JSON.stringify(result));
                
                this.isBenchmarking = false;
                this.engine.setDensity(density, false); // Set to benchmarked value
                console.log("[Profiler] Benchmark Complete (Lightweight):", result);
                resolve(result);
            }, 2000);
        });
    }

    update(delta) {
        const frameTime = delta * 1000;
        this.history.frameTimes.push(frameTime);
        if (this.history.frameTimes.length > this.history.maxHistory) {
            this.history.frameTimes.shift();
        }

        this.stats.frameTime = frameTime;
        this.stats.fps = 1000 / frameTime;
        // Continuous adjustment removed as per user request
    }

    getRecommendedDensity(mode) {
        const tier = this.stats.tier || 'low';
        
        // Mode-specific lightweight scaling targets
        const targets = {
            cpu: { low: 10000, mid: 20000, high: 30000 },
            gpu: { low: 50000, mid: 100000, high: 200000 }
        };

        return targets[mode]?.[tier] || 10000;
    }
}
