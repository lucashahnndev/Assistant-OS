/**
 * WegenaEngine - High-performance GPGPU Particle Core
 */
const WEGENA_ENGINE_VERSION = '5.0.0';
const WEGENA_SCENE_SCRIPT_API_VERSION = '1.0.0';
// WEG: Word Engine Generation
const PARTICLE_SHAPE_ALIASES = {
    point: 0,
    circle: 0,
    disc: 0,
    square: 1,
    plane: 1,
    quad: 1,
    triangle: 2,
    diamond: 3,
    star: 4,
    hex: 5,
    hexagon: 5,
    orb: 6,
    sphere: 6,
    cube: 7,
    boxy: 7,
    box: 7,
    crystal: 8,
    gem: 8
};

function parseVersionParts(version) {
    if (typeof version !== 'string') return null;
    const match = version.trim().match(/^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$/);
    if (!match) return null;
    return {
        raw: version.trim(),
        major: Number(match[1] || 0),
        minor: Number(match[2] || 0),
        patch: Number(match[3] || 0)
    };
}

function isVersionCompatible(expectedVersion, currentVersion) {
    const expected = parseVersionParts(expectedVersion);
    const current = parseVersionParts(currentVersion);
    if (!expected || !current) return true;
    if (current.major > expected.major) return true;
    if (current.major < expected.major) return false;
    if (current.minor > expected.minor) return true;
    if (current.minor < expected.minor) return false;
    return current.patch >= expected.patch;
}

class RangeManager {
    constructor(totalParticles) {
        this.totalParticles = totalParticles;
        this.allocations = new Map(); // id -> { start, end }
        this.unallocated = [{ start: 0, end: totalParticles }];
    }

    allocate(id, count) {
        if (this.allocations.has(id)) return this.allocations.get(id);
        const requested = Math.floor(count);
        for (let i = 0; i < this.unallocated.length; i++) {
            const range = this.unallocated[i];
            const size = range.end - range.start;
            if (size >= requested) {
                const start = range.start;
                const end = start + requested;
                const result = { start, end };
                this.allocations.set(id, result);
                if (size === requested) {
                    this.unallocated.splice(i, 1);
                } else {
                    range.start = end;
                }
                return result;
            }
        }
        return null;
    }

    release(id) {
        const range = this.allocations.get(id);
        if (!range) return;
        this.allocations.delete(id);
        this.unallocated.push({ ...range });
        this.unallocated.sort((a, b) => a.start - b.start);
        for (let i = 0; i < this.unallocated.length - 1; i++) {
            const curr = this.unallocated[i], next = this.unallocated[i+1];
            if (curr.end === next.start) { curr.end = next.end; this.unallocated.splice(i+1, 1); i--; }
        }
    }

    clear() {
        this.allocations.clear();
        this.unallocated = [{ start: 0, end: this.totalParticles }];
    }
}

class WegenaEngine {
    constructor(container, options = {}) {
        this.container = container;
        this.options = options;
        this.isDestroyed = false;
        this.animationFrameId = null;
        this.resizeObserver = null;
        this.globalObject = options.globalObject || globalThis;
        this.documentObject = options.documentObject || container?.ownerDocument || this.globalObject.document || null;
        this.fetchImpl = options.fetchImpl || this.globalObject.fetch?.bind(this.globalObject) || null;
        this.requestFrame = options.requestFrame || this.globalObject.requestAnimationFrame?.bind(this.globalObject) || ((cb) => setTimeout(cb, 16));
        this.cancelFrame = options.cancelFrame || this.globalObject.cancelAnimationFrame?.bind(this.globalObject) || clearTimeout;
        this.controlsManager = null;
        this.presetRegistry = options.presetRegistry || this.globalObject.ParticlePresets || this.globalObject.AtlasPresets || {};
        this.version = options.version || WEGENA_ENGINE_VERSION;
        this.sceneScriptApiVersion = options.sceneScriptApiVersion || WEGENA_SCENE_SCRIPT_API_VERSION;
        this.sceneLoadRevision = 0;
        this.pendingSettleRequests = [];
        this.config = {
            particleCount: options.particleCount || 200000, 
            activeCount: options.activeCount || 10000,   
            baseColor: options.baseColor || new THREE.Color(0x00f2ff),
            glowColor: options.glowColor || new THREE.Color(0x0088ff),
            lerpSpeed: options.lerpSpeed || 0.05,
            friction: options.friction || 0.92,
            mouseRadius: options.mouseRadius || { idle: 30, morph: 18 }
        };

        // Performance & Simulation
        this.profiler = new PerformanceProfiler(this);
        this.simulators = {
            cpu: new CPUSimulator(this),
            gpu: new GPUSimulator(this)
        };
        this.currentSimulator = this.simulators.cpu;

        this.visualState = {
            currentShapeType: 'idleField', 
            isMorphing: false,
            transitionProgress: 0,
            mouse: new THREE.Vector3(-1000, -1000, 0),
            clock: new THREE.Clock(),
            budgets: { ambient: 0.5, core: 0.2, expressive: 0.3 },
            sketch: { isDrawing: false, lastX: 0, lastY: 0 },
            transition: { active: false, speed: 0.05, startTime: 0 },
            navigation: {
                mode: 'orbit', // 'orbit' or 'fly'
                rotation: new THREE.Euler(0, 0, 0),
                targetRotation: new THREE.Euler(0, 0, 0),
                pan: { x: 0, y: 0, targetX: 0, targetY: 0 },
                zoom: options.zoom || 120,
                targetZoom: options.zoom || 120,
                isDragging: false,
                isPanning: false,
                lastMouse: { x: 0, y: 0 },
                sensitivity: {
                    orbit: 1.0,
                    fly: 1.0,
                    look: 1.0
                },
                keys: {}, // Track keyboard state
                velocity: new THREE.Vector3(0, 0, 0)
            },
            settle: {
                error: Infinity,
                sampledParticles: 0,
                stableFrames: 0,
                sceneRevision: 0
            },
            reorganization: {
                active: false,
                startedAt: 0,
                fadeDistanceStart: 6,
                fadeDistanceEnd: 42,
                minAlpha: 0.18,
                settleFramesToDisable: 18,
                maxDurationMs: 1100
            },
            env: { rotation: 0, rotationSpeed: 0 },
            updaters: [],
            nodeUpdaters: new Map(), // name -> updater
            onUpdate: null,
            fx: {
                fragments: [],
                nextId: 1
            },
            sceneNodes: {
                byName: {},
                order: []
            },
            lastPayload: null,
            material: {
                type: 'glow',
                roughness: 0.5,
                metalness: 0.5,
                emissive: 1.0
            },
            meshes: {
                byName: {},
                order: []
            }
        };

        this.rangeManager = new RangeManager(this.config.particleCount);
        this.initEventListeners();

        this.initScene();
        this.initResizeObserver();
        this.initParticles();
        this.animate();
        this.setVisualTarget('idleField');

        // Boot Hardware Probing
        this.profiler.probeHardware().then(() => {
            this.profiler.runBenchmark().then(res => {
                if (this.isDestroyed) return;
                this.setDensity(res.density, true);
            });
        });
    }

    _getViewportSize() {
        const width = this.container?.clientWidth || this.options.width || this.globalObject.innerWidth;
        const height = this.container?.clientHeight || this.options.height || this.globalObject.innerHeight;
        return {
            width: Math.max(1, width),
            height: Math.max(1, height)
        };
    }

    _dispatchEngineEvent(name, detail) {
        if (!this.globalObject?.dispatchEvent) return;
        const EventCtor = this.globalObject.CustomEvent || globalThis.CustomEvent;
        if (!EventCtor) return;
        this.globalObject.dispatchEvent(new EventCtor(name, { detail }));
    }

    _resetBackgroundToDefault() {
        this.setBackground({ type: 'solid', color: '#020205' });
    }

    setSimulatorMode(mode) {
        if (!this.simulators[mode]) return;
        this.currentSimulator.deactivate();
        this.currentSimulator = this.simulators[mode];
        this.currentSimulator.activate();
        this.visualState.mode = mode;

        // One-shot density verification on toggle
        const recommended = this.profiler.getRecommendedDensity(mode);
        this.setDensity(recommended, true);

        // Dynamic UI Limits based on mode
        const maxLimit = mode === 'gpu' ? 5000000 : 1000000;
        this._dispatchEngineEvent('engineModeChanged', { mode, maxDensity: maxLimit });
    }

    setQualityMode(mode) {
        const profiles = {
            fast: { density: 25000, size: 1.5, metaballs: false, lines: false },
            balanced: { density: 100000, size: 1.2, metaballs: false, lines: false },
            high: { density: 500000, size: 1.0, metaballs: true, lines: true }
        };
        const p = profiles[mode] || profiles.balanced;
        this.setDensity(p.density, false);
        this.setParticleSize(p.size);
        if (p.metaballs !== undefined) this.setMetaballs(p.metaballs);
        if (p.lines !== undefined) this.setLineConnections(p.lines);
        this._dispatchEngineEvent('qualityModeChanged', { mode });
    }

    initScene() {
        const { width, height } = this._getViewportSize();
        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(104, width / height, 0.1, 10000);
        this.camera.position.set(0, 0, 120);
        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(Math.min(this.globalObject.devicePixelRatio || 1, 2));
        this.renderer.domElement.style.display = 'block';
        this.renderer.domElement.style.width = '100%';
        this.renderer.domElement.style.height = '100%';
        this.container.appendChild(this.renderer.domElement);
        if (!this.documentObject?.createElement) {
            throw new Error('WegenaEngine requires a document-like object with createElement support.');
        }
        this.scratchCanvas = this.documentObject.createElement('canvas');
        this.sCtx = this.scratchCanvas.getContext('2d', { willReadFrequently: true });
        this.initBackground();
        this.initLineConnections();
    }

    initPostProcessing() {
        // Disabled
    }

    initResizeObserver() {
        const ResizeObserverCtor = this.globalObject.ResizeObserver || globalThis.ResizeObserver;
        if (!ResizeObserverCtor || !this.container) return;

        this.resizeObserver = new ResizeObserverCtor(() => {
            this.handleResize();
        });
        this.resizeObserver.observe(this.container);
    }

    initMetaballs() {
        this.metaballsEnabled = false;
        const { width: w, height: h } = this._getViewportSize();
        this.metaRT = new THREE.WebGLRenderTarget(w, h, { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, format: THREE.RGBAFormat });
        this.metaScene = new THREE.Scene();
        const quadVert = `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position, 1.0); }`;
        const quadFrag = `
            varying vec2 vUv;
            uniform sampler2D u_tex;
            uniform vec2 u_res;   
            uniform float u_blur;  
            uniform float u_thresh;
            void main() {
                vec4 sum = vec4(0.0); float total = 0.0;
                float weights[3]; weights[0] = 0.4; weights[1] = 0.25; weights[2] = 0.05;
                for (int x = -2; x <= 2; x++) {
                    for (int y = -2; y <= 2; y++) {
                        float dist = length(vec2(x, y)); if (dist > 2.2) continue;
                        float w = exp(-dist * dist * 0.8);
                        vec2 off = vec2(float(x), float(y)) * u_res * u_blur;
                        sum += texture2D(u_tex, vUv + off) * w; total += w;
                    }
                }
                vec4 blurred = sum / total;
                float a = smoothstep(u_thresh - 0.05, u_thresh + 0.05, blurred.a);
                if (a < 0.01) discard;
                gl_FragColor = vec4(blurred.rgb / max(blurred.a, 0.001), a);
            }
        `;
        this.metaUniforms = { u_tex: { value: this.metaRT.texture }, u_res: { value: new THREE.Vector2(1 / w, 1 / h) }, u_blur: { value: 4.0 }, u_thresh: { value: 0.28 } };
        const quadMat = new THREE.ShaderMaterial({ uniforms: this.metaUniforms, vertexShader: quadVert, fragmentShader: quadFrag, transparent: true, depthWrite: false, depthTest: false });
        const quadGeo = new THREE.BufferGeometry();
        quadGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1,-1,0, 1,-1,0, 1,1,0, -1,-1,0, 1,1,0, -1,1,0]), 3));
        quadGeo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array([0,0, 1,0, 1,1, 0,0, 1,1, 0,1]), 2));
        this.metaQuad = new THREE.Mesh(quadGeo, quadMat);
        this.metaQuadScene = new THREE.Scene();
        this.metaQuadScene.add(this.metaQuad);
        this.metaOrtho = new THREE.OrthographicCamera(-1,1,1,-1, 0, 1);
    }

    setMetaballs(enabled, blur, threshold) {
        // Removed as it was causing issues with the particle system
    }

    setBloom(enabled, strength, radius, threshold) {
        // Feature removed as requested (user found it buggy)
    }

    setMaterialProperties(type, roughness, metalness, emissive) {
        if (!this.matUniforms) return;
        if (roughness !== undefined) this.matUniforms.u_roughness.value = roughness;
        if (metalness !== undefined) this.matUniforms.u_metalness.value = metalness;
        if (emissive !== undefined) this.matUniforms.u_emissive.value = emissive;
        
        // If type is provided, we can map it to our internal material roles
        if (type) {
            const t = type.toLowerCase();
            if (t === 'metal') this.setParticleMaterial(2);
            else if (t === 'chrome') this.setParticleMaterial(3);
            else if (t === 'plastic' || t === 'glossy') this.setParticleMaterial(12);
            else if (t === 'matte') this.setParticleMaterial(1);
        }
    }

    initEventListeners() {
        this._boundOnKeyDown = (e) => {
            this.visualState.navigation.keys[e.code] = true;
            // Immediate shortcuts
            if (e.code === 'KeyR') this.resetNavigation();
            if (e.code === 'KeyF') this.focusScene();
            if (e.code === 'Tab') {
                e.preventDefault();
                this.setNavigationMode(this.visualState.navigation.mode === 'orbit' ? 'fly' : 'orbit');
            }
        };
        this._boundOnKeyUp = (e) => {
            this.visualState.navigation.keys[e.code] = false;
        };
        this.globalObject.addEventListener('keydown', this._boundOnKeyDown);
        this.globalObject.addEventListener('keyup', this._boundOnKeyUp);
    }

    setNavigationMode(mode) {
        this.visualState.navigation.mode = mode;
        if (mode === 'fly') {
            this.visualState.navigation.velocity.set(0, 0, 0);
        }
        // Emit event for UI to update
        this._dispatchEngineEvent('navModeChanged', { mode });
    }

    focusScene() {
        const bounds = new THREE.Box3();
        bounds.setFromArray(this.positions);
        const center = new THREE.Vector3();
        bounds.getCenter(center);
        const size = new THREE.Vector3();
        bounds.getSize(size);
        const maxDim = Math.max(size.x, size.y, size.z);
        
        const nav = this.visualState.navigation;
        nav.pan.targetX = center.x;
        nav.pan.targetY = center.y;
        nav.targetZoom = maxDim * 1.5;
        nav.targetRotation.set(0, 0, 0);
    }

    alignToAxis(axis) {
        const nav = this.visualState.navigation;
        nav.targetRotation.set(0, 0, 0);
        if (axis === 'x') nav.targetRotation.y = Math.PI / 2;
        if (axis === 'y') nav.targetRotation.x = Math.PI / 2;
        if (axis === 'z') nav.targetRotation.y = 0;
        if (axis === '-x') nav.targetRotation.y = -Math.PI / 2;
        if (axis === '-y') nav.targetRotation.x = -Math.PI / 2;
        if (axis === '-z') nav.targetRotation.y = Math.PI;
    }

    _normalizeVector(v, def = 0) {
        if (typeof v === 'number') return { x: v, y: v, z: v };
        if (!v) return { x: def, y: def, z: def };
        return {
            x: v.x !== undefined ? v.x : (v[0] !== undefined ? v[0] : def),
            y: v.y !== undefined ? v.y : (v[1] !== undefined ? v[1] : def),
            z: v.z !== undefined ? v.z : (v[2] !== undefined ? v[2] : def)
        };
    }

    _renderMetaballs() {
        if (!this.metaballsEnabled || !this.pointsPhysical) return;
        const prevBg = this.scene.background; this.scene.background = null;
        if (this.matUniforms) this.matUniforms.u_metaPass.value = true;
        this.scene.remove(this.pointsPhysical); this.metaScene.add(this.pointsPhysical);
        this.renderer.setRenderTarget(this.metaRT); this.renderer.setClearColor(0x000000, 0); this.renderer.clear();
        this.renderer.render(this.metaScene, this.camera);
        if (this.matUniforms) this.matUniforms.u_metaPass.value = false;
        this.metaScene.remove(this.pointsPhysical); this.scene.add(this.pointsPhysical);
        this.scene.background = prevBg; this.renderer.setRenderTarget(null);
        this.renderer.render(this.metaQuadScene, this.metaOrtho);
    }

    initLineConnections() {
        this.linesEnabled = false; this.lineMaxDist = 12.0; this.lineCount = 2000;
        const geo = new THREE.BufferGeometry();
        this.linePosAttr = new THREE.BufferAttribute(new Float32Array(this.lineCount * 6), 3);
        this.lineColAttr = new THREE.BufferAttribute(new Float32Array(this.lineCount * 6), 3);
        geo.setAttribute('position', this.linePosAttr); geo.setAttribute('color', this.lineColAttr);
        const mat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false });
        this.lines = new THREE.LineSegments(geo, mat); this.lines.visible = false; this.scene.add(this.lines);
    }

    setLineConnections(enabled, maxDist = 12.0) {
        this.linesEnabled = enabled; this.lineMaxDist = maxDist;
        if (this.lines) this.lines.visible = enabled;
    }

    _updateLineConnections() {
        if (!this.linesEnabled || !this.lines) return;
        const pos = this.positions; 
        const linePos = this.linePosAttr.array; 
        const lineCol = this.lineColAttr.array;
        
        let lineIdx = 0; 
        let l6 = 0;
        const maxD2 = this.lineMaxDist * this.lineMaxDist;
        const count = Math.min(this.config.particleCount, 2000);
        const lineCount = this.lineCount;
        
        let i3 = 0;
        for (let i = 0; i < count; i++) {
            if (lineIdx >= lineCount) break;
            const x1 = pos[i3], y1 = pos[i3+1], z1 = pos[i3+2];
            const endJ = Math.min(i + 50, count);
            
            let j3 = i3 + 3;
            for (let j = i + 1; j < endJ; j++) {
                if (lineIdx >= lineCount) break;
                
                const dx = x1 - pos[j3];
                const dy = y1 - pos[j3+1];
                const dz = z1 - pos[j3+2];
                const dist2 = dx*dx + dy*dy + dz*dz;
                
                if (dist2 < maxD2) {
                    linePos[l6] = x1; 
                    linePos[l6+1] = y1; 
                    linePos[l6+2] = z1;
                    linePos[l6+3] = pos[j3]; 
                    linePos[l6+4] = pos[j3+1]; 
                    linePos[l6+5] = pos[j3+2];
                    
                    const colors = this.colors;
                    lineCol[l6] = colors[i3]; 
                    lineCol[l6+1] = colors[i3+1]; 
                    lineCol[l6+2] = colors[i3+2];
                    lineCol[l6+3] = colors[j3]; 
                    lineCol[l6+4] = colors[j3+1]; 
                    lineCol[l6+5] = colors[j3+2];
                    
                    lineIdx++;
                    l6 += 6;
                }
                j3 += 3;
            }
            i3 += 3;
        }
        this.linePosAttr.needsUpdate = true; 
        this.lineColAttr.needsUpdate = true;
        this.lines.geometry.setDrawRange(0, lineIdx * 2);
    }

    initBackground() {
        // Procedural Skybox using a large sphere
        const geometry = new THREE.SphereGeometry(6000, 16, 8); // 16×8 = 256 tris (was 32×32 = 2048)
        const vertexShader = `
            varying vec3 vWorldPosition;
            void main() {
                vec4 worldPosition = modelMatrix * vec4(position, 1.0);
                vWorldPosition = worldPosition.xyz;
                gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            }
        `;
        const fragmentShader = `
            varying vec3 vWorldPosition;
            uniform vec3 u_topColor;
            uniform vec3 u_bottomColor;
            uniform vec3 u_lightColor[3];
            uniform vec3 u_lightPos[3];
            uniform float u_lightIntensity[3];
            uniform float u_exponent;
            uniform float u_offset;

            void main() {
                vec3 viewDir = normalize(vWorldPosition);
                float h = viewDir.y;
                float f = max(0.0, h + u_offset);
                vec3 sky = mix(u_bottomColor, u_topColor, pow(f, u_exponent));
                
                // Add Multi-point Lights (HDRI-like spots)
                vec3 lights = vec3(0.0);
                for(int i = 0; i < 3; i++) {
                    float d = max(0.0, dot(viewDir, normalize(u_lightPos[i])));
                    lights += u_lightColor[i] * pow(d, 40.0) * u_lightIntensity[i]; // Tight spot
                    lights += u_lightColor[i] * pow(d, 4.0) * u_lightIntensity[i] * 0.3; // Soft glow
                }
                
                gl_FragColor = vec4(sky + lights, 1.0);
            }
        `;
        this.bgUniforms = {
            u_topColor: { value: new THREE.Color('#020205') },
            u_bottomColor: { value: new THREE.Color('#020205') },
            u_lightColor: { value: [new THREE.Color(0,0,0), new THREE.Color(0,0,0), new THREE.Color(0,0,0)] },
            u_lightPos: { value: [new THREE.Vector3(1,1,1), new THREE.Vector3(-1,0.5,-1), new THREE.Vector3(0,-1,0)] },
            u_lightIntensity: { value: [0, 0, 0] },
            u_exponent: { value: 0.6 },
            u_offset: { value: 0.1 }
        };
        const material = new THREE.ShaderMaterial({
            vertexShader, fragmentShader, uniforms: this.bgUniforms, side: THREE.BackSide, depthWrite: false
        });
        this.skybox = new THREE.Mesh(geometry, material);
        this.scene.add(this.skybox);
        
        this.bgState = { 
            current: { top: '#020205', bottom: '#020205' }, 
            target: { top: '#020205', bottom: '#020205' }, 
            progress: 1.0, speed: 0.02 
        };
        // Pre-allocated temp color objects for _tickBackground — avoids GC churn at 60fps
        this._bgTmp1 = new THREE.Color();
        this._bgTmp2 = new THREE.Color();
    }

    setBackground(desc) {
        if (typeof desc === 'string') {
            desc = { type: 'solid', color: desc };
        }
        
        let top = '#020205', bottom = '#020205';
        let lights = [
            { color: '#000000', pos: [1, 1, 1], intensity: 0 },
            { color: '#000000', pos: [-1, 0.5, -1], intensity: 0 },
            { color: '#000000', pos: [0, -1, 0], intensity: 0 }
        ];

        if (desc.type === 'solid') {
            top = bottom = desc.color || '#020205';
            // Subtle ambient spot even for solid
            lights[0] = { color: top, pos: [0, 1, 0], intensity: 0.2 };
        } else if (desc.type === 'linear' || desc.type === 'radial') {
            const stops = desc.stops || [];
            if (stops.length >= 1) top = stops[0].color;
            if (stops.length >= 2) bottom = stops[stops.length - 1].color;
            
            if (desc.type === 'radial') {
                // Bright center spot
                lights[0] = { color: top, pos: [0, 1, 0.5], intensity: 1.0 };
                lights[1] = { color: top, pos: [0.5, 0.5, -0.5], intensity: 0.3 };
            } else {
                // Linear: add horizontal "glow"
                lights[0] = { color: top, pos: [0, 1, 0], intensity: 0.5 };
                lights[1] = { color: bottom, pos: [0, -1, 0], intensity: 0.2 };
            }
        } else if (desc.type === 'hdri' || desc.type === 'space') {
            top = desc.sky?.top || '#4488ff';  // Vibrant sky blue
            bottom = desc.sky?.bottom || '#e3f2fd'; // Soft light blue
            if (desc.lights) {
                const lArr = Array.isArray(desc.lights) ? desc.lights : [desc.lights];
                lArr.forEach((l, i) => { if (i < 3) lights[i] = { ...lights[i], ...l }; });
            }
        }

        this.bgState.current = { 
            top: '#' + this.bgUniforms.u_topColor.value.getHex().toString(16).padStart(6, '0'), 
            bottom: '#' + this.bgUniforms.u_bottomColor.value.getHex().toString(16).padStart(6, '0'),
            lights: this.bgUniforms.u_lightColor.value.map((c, i) => ({
                color: '#' + c.getHex().toString(16).padStart(6, '0'),
                intensity: this.bgUniforms.u_lightIntensity.value[i],
                pos: [this.bgUniforms.u_lightPos.value[i].x, this.bgUniforms.u_lightPos.value[i].y, this.bgUniforms.u_lightPos.value[i].z]
            }))
        };
        
        this.bgState.target = { top, bottom, lights };
        this.bgState.progress = 0.0;
    }

    _tickBackground() {
        const s = this.bgState;
        if (s.progress < 1.0) {
            s.progress = Math.min(1.0, s.progress + s.speed);
            // Reuse pre-allocated color objects to avoid GC churn at 60fps
            this._bgTmp1.set(s.current.top).lerp(this._bgTmp2.set(s.target.top), s.progress);
            this.bgUniforms.u_topColor.value.copy(this._bgTmp1);
            this._bgTmp1.set(s.current.bottom).lerp(this._bgTmp2.set(s.target.bottom), s.progress);
            this.bgUniforms.u_bottomColor.value.copy(this._bgTmp1);

            // Lerp Lights
            for(let i = 0; i < 3; i++) {
                const targetLight = s.target.lights[i];
                const currentLight = s.current.lights[i] || { color: '#000000', intensity: 0, pos: [0,1,0] };
                
                if (targetLight) {
                    this._bgTmp1.set(currentLight.color).lerp(this._bgTmp2.set(targetLight.color), s.progress);
                    const lInt = currentLight.intensity + (targetLight.intensity - currentLight.intensity) * s.progress;
                    
                    this.bgUniforms.u_lightColor.value[i].copy(this._bgTmp1);
                    this.bgUniforms.u_lightIntensity.value[i] = lInt;
                    
                    if (targetLight.pos && currentLight.pos) {
                        this.bgUniforms.u_lightPos.value[i].set(
                            currentLight.pos[0] + (targetLight.pos[0] - currentLight.pos[0]) * s.progress,
                            currentLight.pos[1] + (targetLight.pos[1] - currentLight.pos[1]) * s.progress,
                            currentLight.pos[2] + (targetLight.pos[2] - currentLight.pos[2]) * s.progress
                        );
                    }
                } else {
                    this.bgUniforms.u_lightIntensity.value[i] *= (1.0 - s.speed); // Fade out
                }
            }
        }
        // Keep skybox centered on camera to prevent parralax issues for the infinite background
        if (this.skybox && this.camera) {
            this.skybox.position.copy(this.camera.position);
        }
    }

    initParticles() {
        this.geometry = new THREE.BufferGeometry();
        const pCount = this.config.particleCount;
        this.positions = new Float32Array(pCount * 3); this.targetPositions = new Float32Array(pCount * 3);
        this.basePositions = new Float32Array(pCount * 3);
        this.colors = new Float32Array(pCount * 3); this.targetColors = new Float32Array(pCount * 3);
        this.roles = new Float32Array(pCount); this.materialTypes = new Float32Array(pCount); this.particleShapes = new Float32Array(pCount); this.transitionAlpha = new Float32Array(pCount); this.reorganizationInfluence = new Float32Array(pCount);
        this.roughness = new Float32Array(pCount); this.metalness = new Float32Array(pCount); this.emissive = new Float32Array(pCount);
        for (let i = 0; i < pCount; i++) {
            const i3 = i * 3; const radius = 300 + Math.random() * 900; const theta = Math.random() * Math.PI * 2; const phi = Math.acos(2 * Math.random() - 1);
            this.positions[i3] = radius * Math.sin(phi) * Math.cos(theta); this.positions[i3+1] = radius * Math.sin(phi) * Math.sin(theta); this.positions[i3+2] = radius * Math.cos(phi);
            this.colors[i3] = this.config.baseColor.r; this.colors[i3+1] = this.config.baseColor.g; this.colors[i3+2] = this.config.baseColor.b;
            this.targetColors[i3] = this.config.baseColor.r; this.targetColors[i3+1] = this.config.baseColor.g; this.targetColors[i3+2] = this.config.baseColor.b;
            this.roles[i] = 0;
            this.particleShapes[i] = 0;
            this.transitionAlpha[i] = 1;
            this.reorganizationInfluence[i] = 0;
        }
        this.geometry.setAttribute('position', new THREE.BufferAttribute(this.positions, 3));
        this.geometry.setAttribute('color', new THREE.BufferAttribute(this.colors, 3));
        this.geometry.setAttribute('materialType', new THREE.BufferAttribute(this.materialTypes, 1));
        this.geometry.setAttribute('particleShape', new THREE.BufferAttribute(this.particleShapes, 1));
        this.geometry.setAttribute('transitionAlpha', new THREE.BufferAttribute(this.transitionAlpha, 1));
        this.geometry.setAttribute('role', new THREE.BufferAttribute(this.roles, 1));
        this.geometry.setAttribute('roughness', new THREE.BufferAttribute(this.roughness, 1));
        this.geometry.setAttribute('metalness', new THREE.BufferAttribute(this.metalness, 1));
        this.geometry.setAttribute('emissiveAttr', new THREE.BufferAttribute(this.emissive, 1));
        this.geometry.setDrawRange(0, this.config.activeCount);

        const vertexShader = `
            attribute float materialType; attribute float role; attribute float particleShape; attribute float transitionAlpha;
            attribute float roughness; attribute float metalness; attribute float emissiveAttr;
            varying vec3 vColor; varying float vMaterial; varying float vShape; varying float vTransitionAlpha;
            varying float vRoughness; varying float vMetalness; varying float vEmissive;
            varying vec3 vViewPos;
            uniform float u_size; uniform bool u_metaPass;
            void main() {
                if (u_metaPass && int(role + 0.5) == 0) { gl_PointSize = 0.0; gl_Position = vec4(-2.0, -2.0, -2.0, 1.0); return; }
                vColor = color; vMaterial = materialType; vShape = particleShape; vTransitionAlpha = transitionAlpha;
                vRoughness = roughness; vMetalness = metalness; vEmissive = emissiveAttr;
                vec4 mv = modelViewMatrix * vec4(position, 1.0);
                vViewPos = mv.xyz; // Pass view-space position for correct PBR viewDir in fragment
                float ps = u_size * (300.0 / -mv.z);
                if (materialType > 0.5 && materialType < 2.5) ps *= 1.6;
                if (materialType > 3.5 && materialType < 4.5) ps *= 2.2;
                gl_PointSize = ps; gl_Position = projectionMatrix * mv;
            }
        `;
        // Shared GLSL shape/SDF functions — injected into both fragment shaders to avoid duplication
        const SHARED_SHAPE_GLSL = `
            float sdTriangle(vec2 p) {
                const float k = 1.7320508;
                p.x = abs(p.x) - 0.5;
                p.y = p.y + 0.2886751;
                if (p.x + k * p.y > 0.0) p = vec2(p.x - k * p.y, -k * p.x - p.y) / 2.0;
                p.x -= clamp(p.x, -1.0, 0.0);
                return -length(p) * sign(p.y);
            }
            float sdHexagon(vec2 p, float r) {
                vec3 k = vec3(-0.8660254, 0.5, 0.5773503);
                p = abs(p);
                p -= 2.0 * min(dot(k.xy, p), 0.0) * k.xy;
                p -= vec2(clamp(p.x, -k.z * r, k.z * r), r);
                return length(p) * sign(p.y);
            }
            float shapeAlpha(vec2 co, int shape) {
                float dist = length(co);
                if (shape == 1 || shape == 7) { float edge = max(abs(co.x), abs(co.y)); return edge <= 0.5 ? 1.0 : 0.0; }
                if (shape == 2) { return sdTriangle(co * 1.8) <= 0.0 ? 1.0 : 0.0; }
                if (shape == 3 || shape == 8) { float edge = abs(co.x) + abs(co.y); return edge <= 0.5 ? 1.0 : 0.0; }
                if (shape == 4) { float a = atan(co.y, co.x); float r = length(co); float spikes = 0.23 * cos(a * 5.0); float outer = 0.34 + spikes; return r <= outer ? 1.0 : 0.0; }
                if (shape == 5) { return sdHexagon(co * 1.55, 0.5) <= 0.0 ? 1.0 : 0.0; }
                if (shape == 6) { float edge = dist * 1.08 + pow(abs(co.x * co.y), 0.6) * 0.18; return edge <= 0.5 ? 1.0 : 0.0; }
                return dist <= 0.5 ? 1.0 : 0.0;
            }
        `;

        const fragmentShader = `
            varying vec3 vColor; varying float vMaterial; varying float vShape; varying float vTransitionAlpha; uniform float u_time;
            ${SHARED_SHAPE_GLSL}
            void main() {
                vec2 co = gl_PointCoord - 0.5; float dist = length(co); int mt = int(floor(vMaterial + 0.5)); int sh = int(floor(vShape + 0.5));
                float alphaShape = shapeAlpha(co, sh);
                if (mt == 1 || mt == 2 || mt == 3) discard;
                if (alphaShape < 0.01) discard;
                // Soft AA edge for glow particles
                float edgeAA = smoothstep(0.5, 0.35, dist);
                if (mt == 0) { float a = (sh == 1 || sh == 7 || sh == 3 || sh == 8) ? (alphaShape * vTransitionAlpha) : (exp(-dist * dist * 7.0) * 0.95 * alphaShape * edgeAA * vTransitionAlpha); gl_FragColor = vec4(vColor * (1.0 + a * 1.5), a); }
                else if (mt == 4 || sh == 4) { float core = exp(-dist * dist * 22.0); float spike = max(exp(-abs(co.x) * 22.0) * exp(-co.y * co.y * 3.0), exp(-abs(co.y) * 22.0) * exp(-co.x * co.x * 3.0)); float a = max(core, spike * 0.55) * alphaShape * vTransitionAlpha; if (a < 0.01) discard; gl_FragColor = vec4(vColor * (1.0 + core * 3.5), a); }
                else { float ring = smoothstep(0.05, 0.25, dist) * smoothstep(0.5, 0.3, dist); float shift = dist * 3.14 + u_time * 0.8; vec3 tint = vec3(0.5 + 0.5*sin(shift), 0.5 + 0.5*sin(shift+2.1), 0.5 + 0.5*sin(shift+4.2)); float a = (exp(-dist * dist * 5.5) * 0.9 + ring * 0.5) * alphaShape * vTransitionAlpha; gl_FragColor = vec4(mix(vColor, tint, ring * 0.6), a); }
            }
        `;
        const fragmentShaderPhysical = `
            varying vec3 vColor; varying float vMaterial; varying float vShape; varying float vTransitionAlpha;
            varying float vRoughness; varying float vMetalness; varying float vEmissive;
            varying vec3 vViewPos;
            uniform float u_time;
            uniform float u_roughness; uniform float u_metalness; uniform float u_emissive;
            uniform vec3 u_topColor; uniform vec3 u_bottomColor;
            uniform vec3 u_lightPos[3]; uniform vec3 u_lightColor[3]; uniform float u_lightIntensity[3];
            ${SHARED_SHAPE_GLSL}
            void main() {
                vec2 co = gl_PointCoord - 0.5; float dist = length(co); int mt = int(floor(vMaterial + 0.5)); int sh = int(floor(vShape + 0.5));
                float mask = shapeAlpha(co, sh);
                if (mt == 0 || mt == 4 || mt == 5) discard;
                if (mask < 0.01) discard;
                
                // Normal mapping
                vec3 norm;
                if (sh != 0 && sh != 6) {
                    float bevel = smoothstep(0.42, 0.5, max(abs(co.x), abs(co.y)));
                    norm = normalize(vec3(co * 2.0 * bevel, 1.0));
                } else {
                    vec2 n2 = co * 2.0;
                    float nz = sqrt(max(0.001, 1.0 - dot(n2, n2)));
                    norm = normalize(vec3(n2, nz));
                }
                
                // Material Presets based on mt index
                float roughness = vRoughness;
                float metalness = vMetalness;
                float specBoost = 1.0;
                
                if (mt == 2) { roughness = 0.35; metalness = 0.8; } // Standard Metal
                else if (mt == 3) { roughness = 0.05; metalness = 1.0; specBoost = 2.5; } // Polished Chrome
                else if (mt == 11) { roughness = 0.6; metalness = 0.7; } // Brushed Metal
                else if (mt == 12) { roughness = 0.2; metalness = 0.0; } // Plastic/Glossy
                
                // Allow uniform overrides if attributes are default (0.5)
                if (abs(roughness - 0.5) < 0.001) roughness = u_roughness;
                if (abs(metalness - 0.5) < 0.001) metalness = u_metalness;
                float emissive = abs(vEmissive - 1.0) < 0.001 ? u_emissive : vEmissive;
                
                // Advanced PBR-like lighting
                vec3 lightAcc = vec3(0.0);
                vec3 specAcc = vec3(0.0);
                
                // 1. Environment Reflection (MatCap with Fresnel, using real per-fragment view direction)
                vec3 viewDir = normalize(-vViewPos); // #8: perspective-correct, was hardcoded (0,0,-1)
                vec3 reflDir = reflect(-viewDir, norm);
                float envMask = reflDir.y * 0.5 + 0.5;
                float fresnel = pow(1.0 - max(dot(norm, viewDir), 0.0), 3.0);
                
                // Base environment from sky colors
                vec3 envCol = mix(u_bottomColor, u_topColor, envMask);
                
                // Add "Studio/Fake" environment if scene is too dark
                float skyBrightness = length(u_topColor) + length(u_bottomColor);
                if (skyBrightness < 0.2) {
                    // Subtle pale blue "nebulas/studio lights" for space scenes
                    vec3 fakeEnv = mix(vec3(0.05, 0.07, 0.1), vec3(0.15, 0.18, 0.25), envMask);
                    envCol += fakeEnv;
                }
                
                // Scale environment reflection by material properties
                envCol *= (0.4 + fresnel * 0.6 * metalness);
                
                // 2. Multi-light accumulation
                for(int i = 0; i < 3; i++) {
                    if (u_lightIntensity[i] > 0.05) {
                        vec3 ldir = normalize(u_lightPos[i]);
                        float d = max(dot(norm, ldir), 0.0);
                        float s = pow(max(dot(norm, ldir), 0.0), mix(128.0, 8.0, roughness)) * (1.0 - roughness);
                        lightAcc += u_lightColor[i] * d * u_lightIntensity[i];
                        specAcc += u_lightColor[i] * s * u_lightIntensity[i] * specBoost;
                    }
                }
                
                // Final Color Assembly
                // Increased ambient (0.1) and envCol factor (0.8)
                vec3 diffuseCol = vColor * (0.1 + lightAcc + envCol * 0.8) * (1.0 - metalness * 0.75);
                // Metal reflects the environment in its specular too
                vec3 specularCol = mix(vec3(1.0), vColor, metalness) * (specAcc * 3.0 + envCol * metalness * 0.6);
                vec3 emissiveCol = vColor * emissive * 0.15;
                
                if (mt == 1) { 
                    gl_FragColor = vec4(vColor, mask * vTransitionAlpha); 
                } else if (mt == 2 || mt == 3 || mt == 11 || mt == 12) { 
                    gl_FragColor = vec4(diffuseCol + specularCol + emissiveCol, mask * vTransitionAlpha); 
                } else { 
                    gl_FragColor = vec4(vColor * 0.8, mask * vTransitionAlpha); 
                }
            }
        `;
        this.matUniforms = { 
            u_size: { value: 1.0 }, 
            u_time: { value: 0.0 }, 
            u_metaPass: { value: false },
            u_roughness: { value: 0.5 },
            u_metalness: { value: 0.5 },
            u_emissive: { value: 1.0 },
            // Shared lighting uniforms
            u_topColor: this.bgUniforms.u_topColor,
            u_bottomColor: this.bgUniforms.u_bottomColor,
            u_lightPos: this.bgUniforms.u_lightPos,
            u_lightColor: this.bgUniforms.u_lightColor,
            u_lightIntensity: this.bgUniforms.u_lightIntensity
        };
        this.material = new THREE.ShaderMaterial({ uniforms: this.matUniforms, vertexShader, fragmentShader, vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
        this.points = new THREE.Points(this.geometry, this.material);
        this.materialPhysical = new THREE.ShaderMaterial({ uniforms: this.matUniforms, vertexShader, fragmentShader: fragmentShaderPhysical, vertexColors: true, transparent: true, blending: THREE.NormalBlending, depthWrite: true });
        this.pointsPhysical = new THREE.Points(this.geometry, this.materialPhysical);
        this.scene.add(this.pointsPhysical); this.scene.add(this.points);
    }

    setParticleMaterial(typeIndex) {
        for (let i = 0; i < this.config.particleCount; i++) this.materialTypes[i] = typeIndex;
        this.geometry.getAttribute('materialType').needsUpdate = true;
    }

    setParticleRangeMaterial(start, end, typeIndex) {
        const s = Math.max(0, start);
        const e = Math.min(this.config.particleCount, end);
        for (let i = s; i < e; i++) this.materialTypes[i] = typeIndex;
        this.geometry.getAttribute('materialType').needsUpdate = true;
    }

    resolveParticleShape(shape) {
        if (typeof shape === 'number' && Number.isFinite(shape)) {
            return Math.max(0, Math.min(8, Math.round(shape)));
        }
        const key = String(shape || 'point').trim().toLowerCase();
        return PARTICLE_SHAPE_ALIASES[key] ?? 0;
    }

    setParticleShape(shape) {
        const resolved = this.resolveParticleShape(shape);
        for (let i = 0; i < this.config.particleCount; i++) this.particleShapes[i] = resolved;
        this.geometry.getAttribute('particleShape').needsUpdate = true;
    }

    setParticleRangeShape(start, end, shape) {
        const resolved = this.resolveParticleShape(shape);
        const s = Math.max(0, start);
        const e = Math.min(this.config.particleCount, end);
        for (let i = s; i < e; i++) this.particleShapes[i] = resolved;
        this.geometry.getAttribute('particleShape').needsUpdate = true;
    }

    setParticleSize(v) { if (this.matUniforms) this.matUniforms.u_size.value = v; }

    clearFxFragments() {
        this.visualState.fx.fragments = [];
    }

    clearSceneNodes() {
        this.visualState.sceneNodes.byName = {};
        this.visualState.sceneNodes.order = [];
    }

    registerSceneNode(name, descriptor = {}) {
        if (!name || typeof name !== 'string') {
            throw new Error('Scene node name is required.');
        }
        const normalizedName = name.trim();
        if (!normalizedName) {
            throw new Error('Scene node name is required.');
        }

        const prev = this.visualState.sceneNodes.byName[normalizedName] || {};
        
        let start = descriptor.start;
        let end = descriptor.end;

        // Stable Allocation Logic
        if (start === undefined || end === undefined) {
            const budget = descriptor.budget || prev.budget || 0.1;
            const count = Math.floor(this.config.activeCount * budget);
            const range = this.rangeManager.allocate(normalizedName, count);
            if (range) {
                start = range.start;
                end = range.end;
            } else {
                console.warn(`Could not allocate stable range for node ${normalizedName}`);
                start = start ?? 0;
                end = end ?? 1000;
            }
        }

        const next = {
            name: normalizedName,
            start: start,
            end: end,
            get range() { return { start: this.start, end: this.end }; },
            budget: descriptor.budget ?? prev.budget ?? null,
            kind: descriptor.kind ?? prev.kind ?? null,
            material: descriptor.material ?? prev.material ?? null,
            shape: descriptor.shape ?? prev.shape ?? null,
            tags: Array.isArray(descriptor.tags) ? [...descriptor.tags] : (prev.tags || []),
            meta: descriptor.meta ? { ...descriptor.meta } : (prev.meta || {}),
            source: descriptor.source ?? prev.source ?? null
        };
        this.visualState.sceneNodes.byName[normalizedName] = next;
        if (!this.visualState.sceneNodes.order.includes(normalizedName)) {
            this.visualState.sceneNodes.order.push(normalizedName);
        }
        return next;
    }

    nameRange(name, start, end, descriptor = {}) {
        return this.registerSceneNode(name, {
            ...descriptor,
            start,
            end
        });
    }

    getSceneNode(name) {
        return this.visualState.sceneNodes.byName[name] || null;
    }

    listSceneNodes() {
        return this.visualState.sceneNodes.order.map((name) => this.visualState.sceneNodes.byName[name]).filter(Boolean);
    }

    _spawnFxFragment(options = {}) {
        const pCount = this.config.particleCount;
        const start = Math.max(0, Math.min(pCount - 1, options.start ?? 0));
        const end = Math.max(start, Math.min(pCount, options.end ?? start));
        const center = options.center || { x: 0, y: 0, z: 0 };
        const velocity = options.velocity || { x: 0, y: 0, z: 0 };
        const color = options.color ? new THREE.Color(options.color) : null;
        const secondaryColor = options.secondaryColor ? new THREE.Color(options.secondaryColor) : null;
        const spread = options.spread || { x: 0, y: 0, z: 0 };
        const rotation = options.rotation || 0;
        const angularVelocity = options.angularVelocity || 0;
        const fragment = {
            id: this.visualState.fx.nextId++,
            start,
            end,
            center: { x: center.x || 0, y: center.y || 0, z: center.z || 0 },
            velocity: { x: velocity.x || 0, y: velocity.y || 0, z: velocity.z || 0 },
            gravity: options.gravity ?? -18,
            drag: options.drag ?? 0.985,
            bounce: options.bounce ?? 0.35,
            floorY: options.floorY ?? -60,
            life: options.life ?? 1.4,
            age: 0,
            rotation,
            angularVelocity,
            fade: options.fade ?? true,
            kind: options.kind || 'generic',
            color,
            secondaryColor,
            material: options.material,
            shape: this.resolveParticleShape(options.shape),
            waveAmp: options.waveAmp ?? 0,
            waveFreq: options.waveFreq ?? 0,
            drift: options.drift || { x: 0, y: 0, z: 0 },
            spread: { x: spread.x || 0, y: spread.y || 0, z: spread.z || 0 }
        };

        for (let i = start; i < end; i++) {
            const i3 = i * 3;
            const rx = (Math.random() - 0.5) * fragment.spread.x;
            const ry = (Math.random() - 0.5) * fragment.spread.y;
            const rz = (Math.random() - 0.5) * fragment.spread.z;
            this.basePositions[i3] = this.targetPositions[i3] = fragment.center.x + rx;
            this.basePositions[i3 + 1] = this.targetPositions[i3 + 1] = fragment.center.y + ry;
            this.basePositions[i3 + 2] = this.targetPositions[i3 + 2] = fragment.center.z + rz;
            if (fragment.color) {
                this.targetColors[i3] = fragment.color.r;
                this.targetColors[i3 + 1] = fragment.color.g;
                this.targetColors[i3 + 2] = fragment.color.b;
            }
            this.roles[i] = 2;
            this.particleShapes[i] = fragment.shape;
        }

        if (fragment.material !== undefined) {
            this.setParticleRangeMaterial(start, end, fragment.material);
        }

        if (options.name) {
            this.nameRange(options.name, start, end, {
                kind: options.kind || 'fx',
                material: fragment.material,
                shape: options.shape ?? null,
                tags: options.tags || ['fx'],
                source: 'fx'
            });
        }

        this.visualState.fx.fragments.push(fragment);
        return fragment;
    }

    spawnBurst(options = {}) {
        const count = Math.max(1, options.count ?? 1200);
        const start = Math.max(0, Math.min(this.config.particleCount - 1, options.start ?? 0));
        const end = Math.max(start + 1, Math.min(this.config.particleCount, options.end ?? (start + count)));
        const center = options.center || { x: 0, y: 0, z: 0 };
        const baseSpeed = options.speed ?? 36;
        const spread = options.spread || 10;
        const velocityJitter = options.velocityJitter ?? 0.45;
        const color = options.color || '#ffb347';
        const material = options.material ?? 0;
        const fragmentCount = Math.max(3, options.fragments ?? 12);
        const fragmentSize = Math.max(1, Math.floor((end - start) / fragmentCount));
        const created = [];

        for (let f = 0; f < fragmentCount; f++) {
            const fragStart = start + f * fragmentSize;
            const fragEnd = f === fragmentCount - 1 ? end : Math.min(end, fragStart + fragmentSize);
            const theta = Math.random() * Math.PI * 2;
            const phi = Math.acos(2 * Math.random() - 1);
            const dir = {
                x: Math.sin(phi) * Math.cos(theta),
                y: Math.sin(phi) * Math.sin(theta),
                z: Math.cos(phi)
            };
            const speed = baseSpeed * (0.6 + Math.random() * 0.9);
            created.push(this._spawnFxFragment({
                start: fragStart,
                end: fragEnd,
                center,
                velocity: {
                    x: dir.x * speed * (1 + (Math.random() - 0.5) * velocityJitter),
                    y: dir.y * speed * (1 + (Math.random() - 0.5) * velocityJitter) + (options.upwardBias || 0),
                    z: dir.z * speed * (1 + (Math.random() - 0.5) * velocityJitter)
                },
                gravity: options.gravity ?? -22,
                drag: options.drag ?? 0.976,
                bounce: options.bounce ?? 0.26,
                floorY: options.floorY ?? -60,
                life: options.life ?? 1.2,
                color,
                material,
                shape: options.shape ?? 'star',
                angularVelocity: (Math.random() - 0.5) * 5,
                spread: { x: spread, y: spread, z: spread }
            }));
        }

        return created;
    }

    spawnDebris(options = {}) {
        return this.spawnBurst({
            ...options,
            material: options.material ?? 3,
            color: options.color || '#8a6a52',
            shape: options.shape ?? 'cube',
            gravity: options.gravity ?? -30,
            drag: options.drag ?? 0.982,
            bounce: options.bounce ?? 0.38,
            speed: options.speed ?? 24,
            life: options.life ?? 1.8,
            upwardBias: options.upwardBias ?? 8
        });
    }

    spawnSmokeColumn(options = {}) {
        const count = Math.max(1, options.count ?? 1000);
        const start = Math.max(0, Math.min(this.config.particleCount - 1, options.start ?? 0));
        const end = Math.max(start + 1, Math.min(this.config.particleCount, options.end ?? (start + count)));
        const center = options.center || { x: 0, y: 0, z: 0 };
        const fragmentCount = Math.max(3, options.fragments ?? 8);
        const fragmentSize = Math.max(1, Math.floor((end - start) / fragmentCount));
        const created = [];

        for (let f = 0; f < fragmentCount; f++) {
            const fragStart = start + f * fragmentSize;
            const fragEnd = f === fragmentCount - 1 ? end : Math.min(end, fragStart + fragmentSize);
            created.push(this._spawnFxFragment({
                start: fragStart,
                end: fragEnd,
                center: {
                    x: center.x + (Math.random() - 0.5) * 6,
                    y: center.y + Math.random() * 6,
                    z: center.z + (Math.random() - 0.5) * 6
                },
                velocity: {
                    x: (Math.random() - 0.5) * 3,
                    y: 8 + Math.random() * 6,
                    z: (Math.random() - 0.5) * 3
                },
                gravity: options.gravity ?? -2,
                drag: options.drag ?? 0.992,
                bounce: 0,
                floorY: options.floorY ?? -1000,
                life: options.life ?? 2.4,
                color: options.color || '#b0b0b0',
                material: options.material ?? 0,
                shape: options.shape ?? 'orb',
                angularVelocity: (Math.random() - 0.5) * 1.5,
                spread: { x: 8, y: 8, z: 8 }
            }));
        }
        return created;
    }

    spawnFireJet(options = {}) {
        const count = Math.max(1, options.count ?? 1800);
        const start = Math.max(0, Math.min(this.config.particleCount - 1, options.start ?? 0));
        const end = Math.max(start + 1, Math.min(this.config.particleCount, options.end ?? (start + count)));
        const center = options.center || { x: 0, y: 0, z: 0 };
        const fragmentCount = Math.max(4, options.fragments ?? 12);
        const fragmentSize = Math.max(1, Math.floor((end - start) / fragmentCount));
        const created = [];

        for (let f = 0; f < fragmentCount; f++) {
            const fragStart = start + f * fragmentSize;
            const fragEnd = f === fragmentCount - 1 ? end : Math.min(end, fragStart + fragmentSize);
            created.push(this._spawnFxFragment({
                start: fragStart,
                end: fragEnd,
                center: {
                    x: center.x + (Math.random() - 0.5) * 4,
                    y: center.y + Math.random() * 2,
                    z: center.z + (Math.random() - 0.5) * 4
                },
                velocity: {
                    x: (Math.random() - 0.5) * 4,
                    y: 12 + Math.random() * 8,
                    z: (Math.random() - 0.5) * 4
                },
                gravity: options.gravity ?? -6,
                drag: options.drag ?? 0.988,
                bounce: 0,
                floorY: options.floorY ?? -1000,
                life: options.life ?? 1.5,
                color: options.color || '#ff9c3c',
                secondaryColor: options.secondaryColor || '#ff3c1f',
                material: options.material ?? 0,
                shape: options.shape ?? 'orb',
                kind: 'fire',
                angularVelocity: (Math.random() - 0.5) * 2.4,
                waveAmp: options.waveAmp ?? 1.6,
                waveFreq: options.waveFreq ?? 4.2,
                spread: { x: 4, y: 6, z: 4 }
            }));
        }
        return created;
    }

    spawnEngineExhaust(options = {}) {
        const count = Math.max(1, options.count ?? 3200);
        const start = Math.max(0, Math.min(this.config.particleCount - 1, options.start ?? 0));
        const end = Math.max(start + 1, Math.min(this.config.particleCount, options.end ?? (start + count)));
        const center = options.center || options.origin || { x: 0, y: 0, z: 0 };
        const direction = options.direction || { x: 0, y: -1, z: 0 };
        const fragmentCount = Math.max(6, options.fragments ?? 18);
        const fragmentSize = Math.max(1, Math.floor((end - start) / fragmentCount));
        const created = [];
        const dirLen = Math.hypot(direction.x || 0, direction.y || 0, direction.z || 0) || 1;
        const dir = {
            x: (direction.x || 0) / dirLen,
            y: (direction.y || -1) / dirLen,
            z: (direction.z || 0) / dirLen
        };
        const speed = options.speed ?? 26;
        const coneSpread = options.coneSpread ?? 0.42;
        const plumeLength = options.plumeLength ?? 5.5;

        for (let f = 0; f < fragmentCount; f++) {
            const fragStart = start + f * fragmentSize;
            const fragEnd = f === fragmentCount - 1 ? end : Math.min(end, fragStart + fragmentSize);
            const t = fragmentCount <= 1 ? 0 : f / (fragmentCount - 1);
            const lateralScale = 1.5 + t * 8.5;
            const coreBrightness = 1 - t * 0.6;
            created.push(this._spawnFxFragment({
                start: fragStart,
                end: fragEnd,
                center: {
                    x: center.x + dir.x * plumeLength * t,
                    y: center.y + dir.y * plumeLength * t,
                    z: center.z + dir.z * plumeLength * t
                },
                velocity: {
                    x: dir.x * (speed + Math.random() * 8) + (Math.random() - 0.5) * coneSpread * lateralScale,
                    y: dir.y * (speed + Math.random() * 10) + (Math.random() - 0.5) * coneSpread * lateralScale * 0.65,
                    z: dir.z * (speed + Math.random() * 8) + (Math.random() - 0.5) * coneSpread * lateralScale
                },
                gravity: options.gravity ?? 0,
                drag: options.drag ?? 0.982,
                bounce: 0,
                floorY: options.floorY ?? -1000,
                life: options.life ?? (0.8 + t * 0.7),
                color: t < 0.28 ? (options.coreColor || '#fff4cf') : (options.color || '#ffd166'),
                secondaryColor: t < 0.35 ? (options.secondaryColor || '#ff8a2a') : (options.tailColor || '#ff4d1f'),
                material: options.material ?? 0,
                shape: options.shape ?? (t < 0.3 ? 'orb' : 'crystal'),
                kind: 'engine_exhaust',
                angularVelocity: (Math.random() - 0.5) * 1.4,
                waveAmp: options.waveAmp ?? (0.8 + t * 1.6),
                waveFreq: options.waveFreq ?? (5.4 + t * 1.2),
                drift: {
                    x: (Math.random() - 0.5) * 0.4,
                    y: 0,
                    z: (Math.random() - 0.5) * 0.4
                },
                spread: {
                    x: 1.2 + lateralScale * coreBrightness,
                    y: 1.6 + t * 3.4,
                    z: 1.2 + lateralScale * coreBrightness
                }
            }));
        }
        return created;
    }

    spawnWaterFlow(options = {}) {
        const count = Math.max(1, options.count ?? 2000);
        const start = Math.max(0, Math.min(this.config.particleCount - 1, options.start ?? 0));
        const end = Math.max(start + 1, Math.min(this.config.particleCount, options.end ?? (start + count)));
        const center = options.center || { x: 0, y: 0, z: 0 };
        const direction = options.direction || { x: 1, y: 0, z: 0 };
        const fragmentCount = Math.max(4, options.fragments ?? 14);
        const fragmentSize = Math.max(1, Math.floor((end - start) / fragmentCount));
        const created = [];
        const dirLen = Math.hypot(direction.x || 0, direction.y || 0, direction.z || 0) || 1;
        const dir = {
            x: (direction.x || 0) / dirLen,
            y: (direction.y || 0) / dirLen,
            z: (direction.z || 0) / dirLen
        };
        const speed = options.speed ?? 14;

        for (let f = 0; f < fragmentCount; f++) {
            const fragStart = start + f * fragmentSize;
            const fragEnd = f === fragmentCount - 1 ? end : Math.min(end, fragStart + fragmentSize);
            created.push(this._spawnFxFragment({
                start: fragStart,
                end: fragEnd,
                center: {
                    x: center.x + dir.x * f * 4,
                    y: center.y + (Math.random() - 0.5) * 2,
                    z: center.z + dir.z * f * 4
                },
                velocity: {
                    x: dir.x * speed + (Math.random() - 0.5) * 2,
                    y: dir.y * speed + (Math.random() - 0.5) * 0.8,
                    z: dir.z * speed + (Math.random() - 0.5) * 2
                },
                gravity: options.gravity ?? -4,
                drag: options.drag ?? 0.993,
                bounce: options.bounce ?? 0.12,
                floorY: options.floorY ?? center.y - 2,
                life: options.life ?? 2.2,
                color: options.color || '#3cb6ff',
                secondaryColor: options.secondaryColor || '#8cecff',
                material: options.material ?? 0,
                shape: options.shape ?? 'crystal',
                kind: 'water',
                angularVelocity: (Math.random() - 0.5) * 0.8,
                waveAmp: options.waveAmp ?? 1.2,
                waveFreq: options.waveFreq ?? 2.8,
                spread: { x: 6, y: 2, z: 6 }
            }));
        }
        return created;
    }

    _updateFxFragments(delta) {
        const fragments = this.visualState.fx.fragments;
        if (!fragments?.length) return;
        const alive = [];
        for (const fragment of fragments) {
            fragment.age += delta;
            if (fragment.age >= fragment.life) {
                continue;
            }

            fragment.velocity.x *= fragment.drag;
            fragment.velocity.y = fragment.velocity.y * fragment.drag + fragment.gravity * delta;
            fragment.velocity.z *= fragment.drag;
            fragment.center.x += fragment.velocity.x * delta;
            fragment.center.y += fragment.velocity.y * delta;
            fragment.center.z += fragment.velocity.z * delta;
            fragment.center.x += (fragment.drift?.x || 0) * delta;
            fragment.center.y += (fragment.drift?.y || 0) * delta;
            fragment.center.z += (fragment.drift?.z || 0) * delta;
            fragment.rotation += fragment.angularVelocity * delta;

            if (fragment.center.y < fragment.floorY) {
                fragment.center.y = fragment.floorY;
                if (Math.abs(fragment.velocity.y) > 0.5) {
                    fragment.velocity.y = Math.abs(fragment.velocity.y) * fragment.bounce;
                    fragment.velocity.x *= 0.92;
                    fragment.velocity.z *= 0.92;
                } else {
                    fragment.velocity.y = 0;
                }
            }

            const fadeT = fragment.fade ? Math.max(0, 1 - fragment.age / fragment.life) : 1;
            const cos = Math.cos(fragment.rotation);
            const sin = Math.sin(fragment.rotation);
            const wave = fragment.waveAmp
                ? Math.sin(fragment.age * fragment.waveFreq + fragment.id * 0.37) * fragment.waveAmp
                : 0;
            for (let i = fragment.start; i < fragment.end; i++) {
                const i3 = i * 3;
                const localX = this.basePositions[i3] - fragment.center.x;
                const localY = this.basePositions[i3 + 1] - fragment.center.y;
                const localZ = this.basePositions[i3 + 2] - fragment.center.z;
                const rotX = localX * cos - localZ * sin;
                const rotZ = localX * sin + localZ * cos;
                let targetX = fragment.center.x + rotX;
                let targetY = fragment.center.y + localY;
                let targetZ = fragment.center.z + rotZ;

                if (fragment.kind === 'fire') {
                    targetX += Math.sin(fragment.age * 6 + i * 0.01) * (0.4 + wave * 0.2);
                    targetZ += Math.cos(fragment.age * 5 + i * 0.013) * (0.4 + wave * 0.2);
                    targetY += Math.abs(wave) * 0.6;
                } else if (fragment.kind === 'engine_exhaust') {
                    targetX += Math.sin(fragment.age * 7.5 + i * 0.012) * (0.28 + Math.abs(wave) * 0.18);
                    targetZ += Math.cos(fragment.age * 6.8 + i * 0.011) * (0.28 + Math.abs(wave) * 0.18);
                    targetY += wave * 0.18;
                } else if (fragment.kind === 'water') {
                    targetY += wave * 0.35;
                    targetX += Math.sin(fragment.age * 3 + i * 0.005) * 0.25;
                    targetZ += Math.cos(fragment.age * 2.7 + i * 0.006) * 0.25;
                }

                this.targetPositions[i3] = targetX;
                this.targetPositions[i3 + 1] = targetY;
                this.targetPositions[i3 + 2] = targetZ;

                if (fragment.color) {
                    const mixT = fragment.secondaryColor
                        ? Math.max(0, Math.min(1, (fragment.kind === 'fire' || fragment.kind === 'engine_exhaust') ? (1 - fadeT) : (0.5 + wave * 0.08)))
                        : 0;
                    const r = fragment.secondaryColor ? (fragment.color.r * (1 - mixT) + fragment.secondaryColor.r * mixT) : fragment.color.r;
                    const g = fragment.secondaryColor ? (fragment.color.g * (1 - mixT) + fragment.secondaryColor.g * mixT) : fragment.color.g;
                    const b = fragment.secondaryColor ? (fragment.color.b * (1 - mixT) + fragment.secondaryColor.b * mixT) : fragment.color.b;
                    const alphaTint = fragment.kind === 'water' ? (0.7 + fadeT * 0.3) : fadeT;
                    this.targetColors[i3] = r * alphaTint;
                    this.targetColors[i3 + 1] = g * alphaTint;
                    this.targetColors[i3 + 2] = b * alphaTint;
                }
            }

            alive.push(fragment);
        }
        this.visualState.fx.fragments = alive;
    }

    setControlsManager(manager) {
        this.controlsManager = manager || null;
    }

    getControlsManager() {
        return this.controlsManager;
    }

    getPresetRegistry() {
        return this.presetRegistry || {};
    }

    setPresetRegistry(registry) {
        this.presetRegistry = registry || {};
    }

    getRenderSnapshot() {
        const nav = this.visualState.navigation;
        return {
            engineVersion: this.version,
            sceneScriptApiVersion: this.sceneScriptApiVersion,
            sceneRevision: this.sceneLoadRevision,
            density: this.config.activeCount,
            particleCount: this.config.particleCount,
            particleSize: this.matUniforms?.u_size?.value ?? null,
            zoom: nav.zoom,
            targetZoom: nav.targetZoom,
            navigationMode: nav.mode,
            metaballsEnabled: !!this.metaballsEnabled,
            lineConnectionsEnabled: !!this.linesEnabled,
            simulatorMode: this.visualState.mode || 'cpu',
            viewport: this._getViewportSize(),
            controls: this.controlsManager?.getState?.() || null,
            settle: { ...this.visualState.settle }
        };
    }

    getRuntimeInfo() {
        return {
            engineVersion: this.version,
            sceneScriptApiVersion: this.sceneScriptApiVersion
        };
    }

    _now() {
        return this.globalObject?.performance?.now?.() ?? Date.now();
    }

    _beginSceneRevision() {
        this.sceneLoadRevision += 1;
        this.visualState.settle = {
            error: Infinity,
            sampledParticles: 0,
            stableFrames: 0,
            sceneRevision: this.sceneLoadRevision
        };
    }

    _activateReorganization() {
        this.visualState.reorganization.active = true;
        this.visualState.reorganization.startedAt = this._now();
        const fadeStart = this.visualState.reorganization.fadeDistanceStart ?? 6;
        const fadeEnd = Math.max(fadeStart + 0.001, this.visualState.reorganization.fadeDistanceEnd ?? 42);
        const activeCount = Math.min(this.config.activeCount, this.config.particleCount);
        
        let hasDynamicRoles = false;
        let i3 = 0;
        for (let i = 0; i < activeCount; i++) {
            if (this.roles[i] === 0 || this.roles[i] === 1) {
                hasDynamicRoles = true;
            }
            const dx = this.targetPositions[i3] - this.positions[i3];
            const dy = this.targetPositions[i3 + 1] - this.positions[i3 + 1];
            const dz = this.targetPositions[i3 + 2] - this.positions[i3 + 2];
            const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
            const normalized = Math.max(0, Math.min(1, (distance - fadeStart) / (fadeEnd - fadeStart)));
            this.reorganizationInfluence[i] = normalized;
            i3 += 3;
        }
        this.visualState.hasDynamicRoles = hasDynamicRoles;
    }

    _deactivateReorganization() {
        this.visualState.reorganization.active = false;
        if (!this.transitionAlpha) return;
        const activeCount = Math.min(this.config.activeCount, this.config.particleCount);
        let i3 = 0;
        for (let i = 0; i < activeCount; i++) {
            this.positions[i3] = this.targetPositions[i3];
            this.positions[i3 + 1] = this.targetPositions[i3 + 1];
            this.positions[i3 + 2] = this.targetPositions[i3 + 2];
            
            if (this.colors) {
                this.colors[i3] = this.targetColors[i3];
                this.colors[i3 + 1] = this.targetColors[i3 + 1];
                this.colors[i3 + 2] = this.targetColors[i3 + 2];
            }
            
            this.transitionAlpha[i] = 1;
            this.reorganizationInfluence[i] = 0;
            i3 += 3;
        }
        
        if (this.geometry) {
            const posAttr = this.geometry.getAttribute('position');
            if (posAttr) posAttr.needsUpdate = true;
            
            const colAttr = this.geometry.getAttribute('color');
            if (colAttr) colAttr.needsUpdate = true;
            
            const transAttr = this.geometry.getAttribute('transitionAlpha');
            if (transAttr) transAttr.needsUpdate = true;
        }
    }

    _measureSceneSettle() {
        const { activeCount: particleCount } = this.config;
        if (!particleCount || !this.positions || !this.targetPositions || !this.roles) {
            return { error: Infinity, sampledParticles: 0 };
        }

        const desiredSamples = 96;
        const step = Math.max(1, Math.floor(particleCount / desiredSamples));
        let sampledParticles = 0;
        let errorSum = 0;

        for (let i = 0; i < particleCount; i += step) {
            if (this.roles[i] !== 2) continue;
            const i3 = i * 3;
            const dx = this.targetPositions[i3] - this.positions[i3];
            const dy = this.targetPositions[i3 + 1] - this.positions[i3 + 1];
            const dz = this.targetPositions[i3 + 2] - this.positions[i3 + 2];
            errorSum += Math.abs(dx) + Math.abs(dy) + Math.abs(dz);
            sampledParticles += 1;
        }

        if (!sampledParticles) {
            return { error: Infinity, sampledParticles: 0 };
        }

        return {
            error: errorSum / sampledParticles,
            sampledParticles
        };
    }

    _processSettleRequests(sample) {
        if (!this.pendingSettleRequests.length) return;

        const now = this._now();
        this.pendingSettleRequests = this.pendingSettleRequests.filter((request) => {
            if (request.revision !== this.sceneLoadRevision) {
                request.resolve({
                    settled: false,
                    reason: 'superseded',
                    revision: request.revision,
                    currentRevision: this.sceneLoadRevision
                });
                return false;
            }

            request.observedFrames += 1;
            const elapsedMs = now - request.startedAt;
            const hasStaticSample = sample.sampledParticles > 0;
            if (hasStaticSample && sample.error <= request.threshold) {
                request.stableFrames += 1;
            } else {
                request.stableFrames = 0;
            }

            if (
                elapsedMs >= request.minElapsedMs &&
                request.observedFrames >= request.minFrames &&
                hasStaticSample &&
                request.stableFrames >= request.stableFramesRequired
            ) {
                request.resolve({
                    settled: true,
                    reason: 'settled',
                    revision: request.revision,
                    sampledParticles: sample.sampledParticles,
                    error: sample.error,
                    elapsedMs
                });
                return false;
            }

            if ((now - request.startedAt) >= request.timeoutMs) {
                request.resolve({
                    settled: false,
                    reason: 'timeout',
                    revision: request.revision,
                    sampledParticles: sample.sampledParticles,
                    error: sample.error,
                    elapsedMs
                });
                return false;
            }

            return true;
        });
    }

    waitForSceneSettle(options = {}) {
        const revision = options.revision ?? this.sceneLoadRevision;
        return new Promise((resolve) => {
            this.pendingSettleRequests.push({
                resolve,
                revision,
                threshold: options.threshold ?? 0.45,
                stableFramesRequired: options.stableFrames ?? 18,
                minFrames: options.minFrames ?? 14,
                minElapsedMs: options.minElapsedMs ?? 1500,
                timeoutMs: options.timeoutMs ?? 8000,
                startedAt: this._now(),
                stableFrames: 0,
                observedFrames: 0
            });
        });
    }

    captureCanvasDataUrl(options = {}) {
        const canvas = this.renderer?.domElement;
        if (!canvas?.toDataURL) {
            throw new Error('Canvas screenshot capture is unavailable.');
        }
        return canvas.toDataURL(options.type || 'image/png', options.quality);
    }

    _normalizePublicSourcePath(path) {
        if (typeof path !== 'string' || !path.trim()) return null;
        return path.startsWith('/') ? path : `/${path}`;
    }

    async captureScreenshotOnNextSettle(options = {}) {
        const revision = options.revision ?? this.sceneLoadRevision;
        const settleResult = await this.waitForSceneSettle({ ...options, revision });
        const canCaptureOnTimeout = options.captureOnTimeout !== false;
        const timedOutButReady = canCaptureOnTimeout &&
            settleResult?.reason === 'timeout' &&
            (settleResult.elapsedMs ?? 0) >= (options.minElapsedMs ?? 1500);

        if (!settleResult?.settled && !timedOutButReady) {
            return null;
        }
        return {
            ...settleResult,
            dataUrl: this.captureCanvasDataUrl(options)
        };
    }

    _resolveSceneScriptModule(exportsValue, moduleValue) {
        const exported = moduleValue?.exports ?? exportsValue;
        if (typeof exported === 'function') {
            return {
                handler: exported,
                meta: exported.meta || exported.metadata || null
            };
        }

        if (exported && typeof exported === 'object' && typeof exported.run === 'function') {
            return {
                handler: exported.run,
                meta: exported.meta || exported.metadata || exported.run.meta || null
            };
        }

        throw new Error('Scene script must export a function or an object with run(engine).');
    }

    _validateSceneScriptMeta(meta) {
        if (!meta || typeof meta !== 'object') return null;

        const normalized = {
            scriptVersion: meta.scriptVersion || meta.version || null,
            engineVersion: meta.engineVersion || meta.engine || null,
            sceneScriptApiVersion: meta.sceneScriptApiVersion || meta.apiVersion || null,
            label: meta.label || meta.name || null,
            minParticles: meta.minParticles ? parseInt(meta.minParticles) : null,
            maxParticles: meta.maxParticles ? parseInt(meta.maxParticles) : null
        };

        if (normalized.engineVersion && !isVersionCompatible(normalized.engineVersion, this.version)) {
            throw new Error(
                `Scene script expects engine ${normalized.engineVersion}, but runtime is ${this.version}.`
            );
        }

        if (normalized.sceneScriptApiVersion && !isVersionCompatible(normalized.sceneScriptApiVersion, this.sceneScriptApiVersion)) {
            throw new Error(
                `Scene script expects API ${normalized.sceneScriptApiVersion}, but runtime API is ${this.sceneScriptApiVersion}.`
            );
        }

        return normalized;
    }

    applySceneScriptSource(scriptSource, isDensityChange = false) {
        if (!scriptSource) return;

        // Auto-detect Wegena even if called via script channel
        const trimmed = scriptSource.trim();
        if (trimmed.startsWith('@') || trimmed.startsWith('[Nodes:') || trimmed.startsWith('// Wegena')) {
            console.warn("Detected Wegena content in script source. Redirecting to native WEG handler.");
            return this.applySceneWEG(scriptSource, isDensityChange);
        }

        const module = { exports: null };
        const exports = {};
        try {
            const runtime = new Function('module', 'exports', 'THREE', 'window', scriptSource);
            runtime(module, exports, THREE, this.globalObject);
            const { handler, meta } = this._resolveSceneScriptModule(exports, module);
            const normalizedMeta = this._validateSceneScriptMeta(meta);
            this._beginSceneRevision();

            // Set state once
            this.visualState.currentShapeType = 'script';
            this.visualState.lastPayload = {
                scriptSource,
                scriptMeta: normalizedMeta,
                engineVersion: this.version,
                sceneScriptApiVersion: this.sceneScriptApiVersion,
                sceneRevision: this.sceneLoadRevision
            };
            
            // Clean dynamic state
            for (let i = 0; i < this.config.particleCount; i++) this.roles[i] = 0;
            this.visualState.updaters = [];
            this.visualState.onUpdate = null;
            if (!isDensityChange) {
                this.visualState.env.rotationSpeed = 0;
                this.visualState.env.rotation = 0;
                this.clearFxFragments();
                this._resetBackgroundToDefault();
            }
            this.clearSceneNodes();
            this.rangeManager.clear();

            this.visualState.isDensityChanging = isDensityChange;
            handler(this);
            this.visualState.isDensityChanging = false;
            this.visualState.compiledActiveCount = this.config.activeCount;
            this._clearUnusedBufferStates();
            this._activateReorganization();
        } catch (e) {
            console.error("Error executing scene script:", e);
        }
    }

    applySceneWEG(wegSource, isDensityChange = false) {
        if (!wegSource) return;
        const CompilerClass = window.WEGCompiler || window.WDSCompiler || window.wdsCompiler;
        if (!CompilerClass && typeof WEGCompiler === 'undefined') {
            console.error("WEGCompiler not found. Native weg support requires weg_compiler.js.");
            return;
        }
        const compiler = new (CompilerClass || WEGCompiler)();
        const scriptSource = compiler.compile(wegSource);
        this.applySceneScriptSource(scriptSource, isDensityChange);
    }

    applySceneWDS(wdsSource) {
        return this.applySceneWEG(wdsSource);
    }

    runScript(scriptSource) {
        return this.applySceneScriptSource(scriptSource);
    }

    async loadSceneScript(scriptUrl) {
        if (!this.fetchImpl) {
            throw new Error('loadSceneScript requires fetch support.');
        }

        const response = await this.fetchImpl(scriptUrl);
        if (!response.ok) {
            throw new Error(`Failed to load scene script: ${scriptUrl} (${response.status})`);
        }

        const scriptSource = await response.text();
        this.applySceneScriptSource(scriptSource);
        this._dispatchEngineEvent('fileSceneLoaded', {
            sourcePath: this._normalizePublicSourcePath(scriptUrl),
            kind: 'script'
        });
        return scriptSource;
    }

    async setVisualTarget(type, payload = null) {
        this.visualState.currentShapeType = type; this.visualState.lastPayload = payload; this.visualState.isMorphing = (type !== 'idleField');
        for (let i = 0; i < this.config.particleCount; i++) this.roles[i] = 0;
        if (payload?.version && payload?.config) return this.loadScene(payload);
        if (['text', 'sketch', 'matrix', 'path', 'orb', 'idleField'].includes(type)) {
            this.setParticleMaterial(0); this.setBackground({ type: 'solid', color: '#020205' });
            this.visualState.onUpdate = null; this.visualState.env.rotationSpeed = 0; this.visualState.env.rotation = 0;
        }
        this._applySubConfig(payload?.config);
        const presets = this.getPresetRegistry();
        switch(type) {
            case 'script': 
                if (payload?.scriptSource) this.applySceneScriptSource(payload.scriptSource);
                break;
            case 'galaxy': presets.generateGalaxy?.(this); break;
            case 'solarSystem': presets.generateSolarSystem?.(this); break;
            case 'landscape': presets.generateLandscape?.(this); break;
            case "earth": presets.generateEarth?.(this); break;
            case 'text': this.textToPoints(payload); break;
            case 'sketch': this.sketchToPoints(); break;
            case 'matrix': this.matrixToPoints(payload); break;
            case 'path': this.pathToPoints(payload); break;
            case 'orb': this.composeOrb(); break;
            default: this.composeStarfield(); break;
        }

        this._clearUnusedBufferStates();
        if (this.geometry) {
            if (this.geometry.attributes.role) this.geometry.attributes.role.needsUpdate = true;
            if (this.geometry.attributes.particleShape) this.geometry.attributes.particleShape.needsUpdate = true;
            if (this.geometry.attributes.materialType) this.geometry.attributes.materialType.needsUpdate = true;
            if (this.geometry.attributes.color) this.geometry.attributes.color.needsUpdate = true;
        }
    }

    _clearUnusedBufferStates() {
        // Use activeCount, not particleCount — avoids iterating the entire 200k buffer
        // when only 10k–30k particles are actually in use.
        const pCount = Math.min(this.config.activeCount, this.config.particleCount);
        for (let i = 0; i < pCount; i++) {
            if (this.roles[i] === 0) {
                const i3 = i * 3;
                this.targetPositions[i3] = 0; this.targetPositions[i3+1] = 0; this.targetPositions[i3+2] = 0;
                this.positions[i3] = 0; this.positions[i3+1] = 0; this.positions[i3+2] = 0;
                this.basePositions[i3] = 0; this.basePositions[i3+1] = 0; this.basePositions[i3+2] = 0;
                
                this.targetColors[i3] = 0; this.targetColors[i3+1] = 0; this.targetColors[i3+2] = 0;
                this.colors[i3] = 0; this.colors[i3+1] = 0; this.colors[i3+2] = 0;
                
                this.particleShapes[i] = 0;
                this.materialTypes[i] = 0;
                this.transitionAlpha[i] = 0;
            }
        }
        if (this.geometry) {
            const transAttr = this.geometry.getAttribute?.('transitionAlpha');
            if (transAttr) transAttr.needsUpdate = true;
        }
    }

    loadScene(scene, incremental = false, isDensityChange = false) {
        if (!scene || !scene.config) return; const { config, content, animation } = scene;
        if (!incremental) {
            for (let i = 0; i < this.config.particleCount; i++) this.roles[i] = 0;
            if (!isDensityChange) this._resetBackgroundToDefault();
            this.clearSceneNodes();
            this.rangeManager.clear();
        }
        if (!isDensityChange && config.optics?.fov) { this.setFOV(config.optics.fov); }
        if (config.particles) { 
            if (config.particles.density && !isDensityChange) this.setDensity(config.particles.density, false); 
            if (config.particles.size !== undefined) this.setParticleSize(config.particles.size); 
            if (config.particles.material !== undefined) this.setParticleMaterial(config.particles.material); 
        }
        if (!isDensityChange && config.env) { if (config.env.background) this.setBackground(config.env.background); if (config.env.rotationSpeed !== undefined) this.visualState.env.rotationSpeed = config.env.rotationSpeed; }
        if (!isDensityChange && config.camera) { const nav = this.visualState.navigation; if (config.camera.zoom !== undefined) nav.targetZoom = config.camera.zoom; if (config.camera.rotation) { if (config.camera.rotation.x !== undefined) nav.targetRotation.x = config.camera.rotation.x; if (config.camera.rotation.y !== undefined) nav.targetRotation.y = config.camera.rotation.y; } if (config.camera.pan) { if (config.camera.pan.x !== undefined) nav.pan.targetX = config.camera.pan.x; if (config.camera.pan.y !== undefined) nav.pan.targetY = config.camera.pan.y; } }
        if (content) { 
            if (!incremental) this.visualState.updaters = []; 
            if (content.type === 'composition' && content.elements) { 
                content.elements.forEach(el => { this._loadElement(el); }); 
            } else { 
                this._loadElement(content); 
            } 
            this.visualState.onUpdate = (time, delta) => {
                this.visualState.updaters.forEach(fn => fn(time, delta));
                this.visualState.nodeUpdaters.forEach(fn => fn(time, delta));
            };
        }
        if (!isDensityChange && animation && animation.type) this._applyAnimation(animation, this.visualState);
        this.visualState.compiledActiveCount = this.config.activeCount;
        this._clearUnusedBufferStates();
    }

    updateSceneNode(el) {
        if (!el.name) return;
        this._loadElement(el);
        this._activateReorganization();
    }

    deleteSceneNode(name) {
        if (this.visualState.sceneNodes.byName[name]) {
            const node = this.visualState.sceneNodes.byName[name];
            // Clear role and alpha for the range to effectively "hide" particles
            for (let i = node.start; i < node.end; i++) {
                this.roles[i] = 0;
                this.transitionAlpha[i] = 0;
            }
            this.rangeManager.release(name);
            delete this.visualState.sceneNodes.byName[name];
            this.visualState.sceneNodes.order = this.visualState.sceneNodes.order.filter(n => n !== name);
            this._activateReorganization();
        }
    }

    _loadElement(el, forcedStart = null, forcedEnd = null) {
        const { generator, modifiers, animation, data = {}, type, elements, name } = el;
        const nodeName = name || el.name || data.name || generator?.data?.name;
        
        // Smart Mesh Propagation
        const isMesh = el.mesh === true || el.mesh === 'true' || data.mesh === true || data.mesh === 'true';
        if (isMesh) {
            if (generator && generator.data) {
                generator.data.aligned = true;
                generator.data.mesh = true;
            }
            data.aligned = true;
            data.mesh = true;
            el.shape = 'square';
        }
        
        let start = forcedStart;
        let end = forcedEnd;

        if (start === null || end === null) {
            if (nodeName) {
                const range = this.rangeManager.allocate(nodeName, Math.floor(this.config.activeCount * (el.budget || 0.1)));
                if (range) {
                    start = range.start;
                    end = range.end;
                }
            }
            if (start === null) {
                // Fallback for unnamed composition parts
                start = 0;
                end = Math.floor(this.config.activeCount * 0.1);
            }
        }

        if (type === 'composition' || generator?.type === 'composition') {
            const list = elements || generator?.elements || []; let pos = 0; const range = end - start;
            list.forEach(sub => { const b = sub.budget || (1/list.length); const mData = { ...data, ...(sub.data || {}) }; if (data.offset && sub.data?.offset) mData.offset = { x: (data.offset.x||0)+(sub.data.offset.x||0), y: (data.offset.y||0)+(sub.data.offset.y||0), z: (data.offset.z||0)+(sub.data.offset.z||0) }; else if (data.offset) mData.offset = data.offset; this._loadElement({ ...sub, data: mData }, start + Math.floor(pos*range), start + Math.min(range, Math.floor((pos+b)*range))); pos += b; });
            return;
        }
        this._runGenerator(generator?.type || type || 'starfield', generator?.data || data || {}, start, end);
        if (modifiers) this._applyModifiers(start, end, modifiers);
        if (animation) this._registerLocalAnimation(animation, start, end);
        if (el.material !== undefined) this.setParticleRangeMaterial(start, end, el.material);
        if (el.shape !== undefined || data.shape !== undefined || generator?.data?.shape !== undefined) {
            this.setParticleRangeShape(start, end, el.shape ?? data.shape ?? generator?.data?.shape);
        }
        if (nodeName) {
            this.nameRange(nodeName, start, end, {
                kind: generator?.type || type || 'starfield',
                material: el.material,
                shape: el.shape ?? data.shape ?? generator?.data?.shape ?? null,
                tags: data.tags || el.tags || [],
                meta: {
                    animation: animation?.type || null
                },
                source: 'loadElement'
            });
        }
    }

    _runGenerator(type, data, start, end) {
        const color = data.color ? new THREE.Color(data.color) : null;
        const aligned = data.aligned === true || data.grid === true;
        const total = end - start;
        switch(type) {
            case 'sphere':
                const rad = data.radius || 30; const off = data.offset || {x:0,y:0,z:0};
                for (let i = start; i < end; i++) {
                    const i3 = i * 3; this.roles[i] = 2;
                    let rx = 0, ry = 0, rz = 0;
                    if (aligned && total > 0) {
                        const idx = i - start;
                        const phi = Math.acos(1 - 2 * (idx + 0.5) / total);
                        const theta = Math.PI * (1 + Math.sqrt(5)) * (idx + 0.5);
                        const r = data.hollow ? rad : rad * Math.pow((idx + 0.5) / total, 1/3);
                        rx = r * Math.sin(phi) * Math.cos(theta);
                        ry = r * Math.sin(phi) * Math.sin(theta);
                        rz = r * Math.cos(phi);
                    } else {
                        const u = Math.random(), v = Math.random(), theta = 2*Math.PI*u, phi = Math.acos(2*v-1), r = data.hollow ? rad : rad*Math.pow(Math.random(), 1/3);
                        rx = r*Math.sin(phi)*Math.cos(theta);
                        ry = r*Math.sin(phi)*Math.sin(theta);
                        rz = r*Math.cos(phi);
                    }
                    this.basePositions[i3] = rx + off.x;
                    this.basePositions[i3+1] = ry + off.y;
                    this.basePositions[i3+2] = rz + off.z;
                    this.targetPositions[i3] = this.basePositions[i3];
                    this.targetPositions[i3+1] = this.basePositions[i3+1];
                    this.targetPositions[i3+2] = this.basePositions[i3+2];
                    if (color) { this.targetColors[i3] = color.r; this.targetColors[i3+1] = color.g; this.targetColors[i3+2] = color.b; }
                }
                break;
            case 'ring':
                const rr = data.radius||50, ri = data.innerRadius||rr*0.8, rt = (data.tilt||0)*(Math.PI/180), ro = data.offset||{x:0,y:0,z:0};
                for (let i=start; i<end; i++) {
                    const i3=i*3; this.roles[i]=2;
                    let r = 0, theta = 0;
                    if (aligned && total > 0) {
                        const idx = i - start;
                        r = ri + (idx / total) * (rr - ri);
                        theta = (idx / total) * Math.PI * 2;
                    } else {
                        r = ri+Math.random()*(rr-ri);
                        theta = Math.random()*Math.PI*2;
                    }
                    const x=r*Math.cos(theta), z=r*Math.sin(theta);
                    this.basePositions[i3]=x+ro.x;
                    this.basePositions[i3+1]=z*Math.sin(rt)+ro.y;
                    this.basePositions[i3+2]=z*Math.cos(rt)+ro.z;
                    this.targetPositions[i3] = this.basePositions[i3];
                    this.targetPositions[i3+1] = this.basePositions[i3+1];
                    this.targetPositions[i3+2] = this.basePositions[i3+2];
                    if(color){this.targetColors[i3]=color.r;this.targetColors[i3+1]=color.g;this.targetColors[i3+2]=color.b;}
                }
                break;
            case 'spiral':
                const sa=data.arms||2, sr=data.radius||100, st=data.tightness||2.5, so=data.offset||{x:0,y:0,z:0};
                for(let i=start;i<end;i++){
                    const i3=i*3;this.roles[i]=2;
                    let dist = 0, ang = 0;
                    if (aligned && total > 0) {
                        const idx = i - start;
                        const arm = idx % sa;
                        const armO = (arm * Math.PI * 2) / sa;
                        dist = Math.pow(idx / total, 0.5) * sr;
                        ang = st * Math.log(dist + 1) + armO;
                    } else {
                        const arm=i%sa, armO=(arm*Math.PI*2)/sa, distVal=Math.pow(Math.random(),0.5)*sr;
                        dist = distVal;
                        ang=st*Math.log(distVal+1)+armO;
                    }
                    this.basePositions[i3]=Math.cos(ang)*dist+so.x;
                    this.basePositions[i3+1]=Math.sin(ang)*dist+so.y;
                    this.basePositions[i3+2]=(aligned ? 0 : (Math.random()-0.5)*(dist*0.1))+so.z;
                    this.targetPositions[i3] = this.basePositions[i3];
                    this.targetPositions[i3+1] = this.basePositions[i3+1];
                    this.targetPositions[i3+2] = this.basePositions[i3+2];
                    if(color){this.targetColors[i3]=color.r;this.targetColors[i3+1]=color.g;this.targetColors[i3+2]=color.b;}
                }
                break;
            case 'box':
                const bs=data.size||{x:50,y:50,z:50}, bo=data.offset||{x:0,y:0,z:0};
                let bnx = 1, bny = 1, bnz = 1;
                if (aligned && total > 0) {
                    const activeDims = (bs.x > 0.001 ? 1 : 0) + (bs.y > 0.001 ? 1 : 0) + (bs.z > 0.001 ? 1 : 0);
                    if (activeDims === 1) {
                        bnx = bs.x > 0.001 ? total : 1;
                        bny = bs.y > 0.001 ? total : 1;
                        bnz = bs.z > 0.001 ? total : 1;
                    } else if (activeDims === 2) {
                        const area = (bs.x || 1) * (bs.y || 1) * (bs.z || 1);
                        const k = Math.sqrt(total / area);
                        bnx = bs.x > 0.001 ? Math.max(1, Math.round(bs.x * k)) : 1;
                        bny = bs.y > 0.001 ? Math.max(1, Math.round(bs.y * k)) : 1;
                        bnz = bs.z > 0.001 ? Math.max(1, Math.round(bs.z * k)) : 1;
                    } else {
                        const vol = bs.x * bs.y * bs.z || 1;
                        const k = Math.pow(total / vol, 1/3);
                        bnx = Math.max(1, Math.round(bs.x * k));
                        bny = Math.max(1, Math.round(bs.y * k));
                        bnz = Math.max(1, Math.round(bs.z * k));
                    }
                    while (bnx * bny * bnz < total) {
                        if (bnx <= bny && bnx <= bnz) bnx++;
                        else if (bny <= bnx && bny <= bnz) bny++;
                        else bnz++;
                    }
                }
                for(let i=start;i<end;i++){
                    const i3=i*3;this.roles[i]=2;
                    let rx = 0, ry = 0, rz = 0;
                    if (aligned) {
                        const idx = i - start;
                        const ix = idx % bnx;
                        const iy = Math.floor(idx / bnx) % bny;
                        const iz = Math.floor(idx / (bnx * bny)) % bnz;
                        const fx = bnx > 1 ? (ix / (bnx - 1) - 0.5) : 0;
                        const fy = bny > 1 ? (iy / (bny - 1) - 0.5) : 0;
                        const fz = bnz > 1 ? (iz / (bnz - 1) - 0.5) : 0;
                        rx = fx * bs.x;
                        ry = fy * bs.y;
                        rz = fz * bs.z;
                    } else {
                        rx = (Math.random()-0.5)*bs.x;
                        ry = (Math.random()-0.5)*bs.y;
                        rz = (Math.random()-0.5)*bs.z;
                    }
                    this.basePositions[i3]=rx+bo.x;
                    this.basePositions[i3+1]=ry+bo.y;
                    this.basePositions[i3+2]=rz+bo.z;
                    this.targetPositions[i3] = this.basePositions[i3];
                    this.targetPositions[i3+1] = this.basePositions[i3+1];
                    this.targetPositions[i3+2] = this.basePositions[i3+2];
                    if(color){this.targetColors[i3]=color.r;this.targetColors[i3+1]=color.g;this.targetColors[i3+2]=color.b;}}
                break;
            case 'matrix': this.matrixToPoints(data, start, end); break;
            case 'path': this.pathToPoints(data, start, end); break;
            case 'text': this.textToPoints(data, start, end); break;
            case 'orb': this.composeOrb(data, start, end); break;
            default: this.composeStarfield(start, end); break;
        }
    }

    _applyModifiers(start, end, modifiers) {
        modifiers.forEach(mod => {
            const { type, amount = 1.0, scale = 1.0 } = mod;
            if (type === 'jitter') {
                for (let i = start; i < end; i++) {
                    const i3 = i * 3;
                    this.targetPositions[i3] += (Math.random() - 0.5) * amount;
                    this.targetPositions[i3 + 1] += (Math.random() - 0.5) * amount;
                    this.targetPositions[i3 + 2] += (Math.random() - 0.5) * amount;
                }
            } else if (type === 'noise') {
                const s = scale * 0.1;
                for (let i = start; i < end; i++) {
                    const i3 = i * 3;
                    const x = this.targetPositions[i3] * s;
                    const y = this.targetPositions[i3 + 1] * s;
                    const z = this.targetPositions[i3 + 2] * s;
                    const n = Math.sin(x) * Math.cos(y) * Math.sin(z) * amount;
                    this.targetPositions[i3] += n;
                    this.targetPositions[i3 + 1] += n;
                    this.targetPositions[i3 + 2] += n;
                }
            } else if (type === 'twist') {
                for (let i = start; i < end; i++) {
                    const i3 = i * 3;
                    const angle = this.targetPositions[i3 + 2] * amount;
                    const cos = Math.cos(angle), sin = Math.sin(angle);
                    const tx = this.targetPositions[i3], ty = this.targetPositions[i3 + 1];
                    this.targetPositions[i3] = tx * cos - ty * sin;
                    this.targetPositions[i3 + 1] = tx * sin + ty * cos;
                }
            }
        });
    }

    _registerLocalAnimation(anim, start, end) {
        const { type, params: p = {} } = anim; const speed = p.speed || 1.0;
        if (type === 'orbit') {
            this.visualState.updaters.push((time) => {
                const angle = time * speed;
                const cos = Math.cos(angle), sin = Math.sin(angle);
                for (let i = start; i < end; i++) {
                    const i3 = i * 3;
                    const bx = this.basePositions[i3], bz = this.basePositions[i3+2];
                    this.targetPositions[i3] = bx * cos - bz * sin;
                    this.targetPositions[i3+2] = bx * sin + bz * cos;
                }
            });
        }
        else if (type === 'pulse') {
            const amp = p.amplitude || 0.1;
            this.visualState.updaters.push((time) => {
                const b = 1.0 + Math.sin(time * speed) * amp;
                for (let i = start; i < end; i++) {
                    const i3 = i * 3;
                    this.targetPositions[i3] = this.basePositions[i3] * b;
                    this.targetPositions[i3+1] = this.basePositions[i3+1] * b;
                    this.targetPositions[i3+2] = this.basePositions[i3+2] * b;
                }
            });
        }
    }

    _applyAnimation(anim, state) {
        const { type, params: p = {} } = anim; const speed = p.speed || 1.0; const amp = p.amplitude || 0.2;
        const prev = state.onUpdate;
        const initialSize = this.matUniforms.u_size.value;
        state.onUpdate = (time) => {
            if (prev) prev(time);
            if (type === 'pulse') {
                const b = 1.0 + Math.sin(time * speed) * amp;
                this.setParticleSize(initialSize * b);
            }
            else if (type === 'rotate') { const nav = this.visualState.navigation; if (!nav.isDragging && !nav.isPanning) nav.targetRotation.y += speed * 0.01; }
            else if (type === 'orbit') { const r = p.radius || 50, nav = this.visualState.navigation; if (!nav.isDragging && !nav.isPanning) { nav.pan.targetX = Math.cos(time * speed) * r; nav.pan.targetY = Math.sin(time * speed) * r; } }
        };
    }

    _applySubConfig(config) {
        if (!config) return;
        if (config.camera) { const c = config.camera; if (c.zoom !== undefined) this.visualState.navigation.targetZoom = c.zoom; if (c.rotation) { if (c.rotation.x !== undefined) this.visualState.navigation.targetRotation.x = c.rotation.x; if (c.rotation.y !== undefined) this.visualState.navigation.targetRotation.y = c.rotation.y; } if (c.pan) { if (c.pan.x !== undefined) this.visualState.navigation.pan.targetX = c.pan.x; if (c.pan.y !== undefined) this.visualState.navigation.pan.targetY = c.pan.y; } }
        if (config.env) { const e = config.env; if (e.rotationSpeed !== undefined) this.visualState.env.rotationSpeed = e.rotationSpeed; if (e.rotation !== undefined) this.visualState.env.rotation = e.rotation; }
    }

    createLight(options = {}) {
        const name = options.name || `light_${Math.random().toString(36).substr(2, 9)}`;
        const pos = options.pos || options.center || [0, 10, 0];
        const color = options.color || "#ffffff";
        const intensity = options.intensity ?? 1.0;

        // Manage up to 3 lights. Reuse slots if names match, or use next available.
        if (!this.lightSlots) this.lightSlots = {};
        if (!this.lightSlotOrder) this.lightSlotOrder = [];

        let slot = -1;
        if (this.lightSlots[name] !== undefined) {
            slot = this.lightSlots[name];
        } else if (this.lightSlotOrder.length < 3) {
            slot = this.lightSlotOrder.length;
            this.lightSlots[name] = slot;
            this.lightSlotOrder.push(name);
        } else {
            // Replace the oldest light if no slots left
            const oldest = this.lightSlotOrder.shift();
            delete this.lightSlots[oldest];
            slot = 2;
            this.lightSlots[name] = slot;
            this.lightSlotOrder.push(name);
        }

        if (slot >= 0 && slot < 3) {
            const lPos = Array.isArray(pos) ? pos : [pos.x||0, pos.y||10, pos.z||0];
            const lCol = new THREE.Color(color);
            
            // Update target state for smooth transition
            if (this.bgState && this.bgState.target) {
                this.bgState.target.lights[slot] = { 
                    color: color, 
                    intensity: intensity, 
                    pos: lPos 
                };
                this.bgState.progress = 0.5; // Trigger a quick transition
            } else {
                // Fallback for immediate update
                this.bgUniforms.u_lightColor.value[slot].copy(lCol);
                this.bgUniforms.u_lightIntensity.value[slot] = intensity;
                this.bgUniforms.u_lightPos.value[slot].set(lPos[0], lPos[1], lPos[2]);
            }
        }
        return { name, slot };
    }

    createShape(options = {}) {
        const name = options.name || `shape_${Date.now()}`;
        const type = (options.type || 'box').toLowerCase();
        const pos = options.pos || options.center || [0, 0, 0];
        const size = options.size || 10;
        const color = options.color || '#ffffff';
        const roughness = options.roughness !== undefined ? options.roughness : 0.5;
        const metalness = options.metalness !== undefined ? options.metalness : 0.0;
        const emissive = options.emissive !== undefined ? options.emissive : 0.0;

        let geometry;
        const s = Array.isArray(size) ? size : [size, size, size];
        
        if (type === 'sphere') geometry = new THREE.SphereGeometry(s[0]/2, 32, 32);
        else if (type === 'cylinder') geometry = new THREE.CylinderGeometry(s[0]/2, s[0]/2, s[1], 32);
        else if (type === 'torus') geometry = new THREE.TorusGeometry(s[0]/2, s[1]/4, 16, 100);
        else geometry = new THREE.BoxGeometry(s[0], s[1], s[2]);

        const material = new THREE.MeshStandardMaterial({
            color: new THREE.Color(color),
            roughness: roughness,
            metalness: metalness,
            emissive: new THREE.Color(color).multiplyScalar(emissive),
            transparent: true,
            opacity: options.opacity ?? 1.0
        });

        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.set(pos[0], pos[1], pos[2]);
        if (options.rotation) mesh.rotation.set(options.rotation[0], options.rotation[1], options.rotation[2]);
        
        this.scene.add(mesh);
        this.visualState.meshes.byName[name] = mesh;
        this.visualState.meshes.order.push(name);
        
        return { name, mesh };
    }

    createVolume(options = {}) {
        const name = options.name || `volume_${Date.now()}`;
        const count = options.budget !== undefined 
            ? Math.floor(this.config.activeCount * options.budget) 
            : (options.count || 1000);
        const range = this.rangeManager.allocate(name, count);
        if (!range) return null;

        const { start, end } = range;
        const center = options.center || { x: 0, y: 0, z: 0 };
        const size = options.size !== undefined ? options.size : 10;
        const sSize = this._normalizeVector(size, 10);
        const color = options.color ? new THREE.Color(options.color) : new THREE.Color(0xffffff);
        const material = options.material !== undefined ? options.material : 1;
        const isMesh = options.mesh === true || options.mesh === 'true';
        const shape = isMesh ? 'square' : (options.shape || 'cube');
        const noise = options.noise || 0;
        const aligned = options.aligned === true || options.grid === true || isMesh;

        const cx = center.x;
        const cy = center.y;
        const cz = center.z;
        const sx = sSize.x;
        const sy = sSize.y;
        const sz = sSize.z;
        const cr = color.r;
        const cg = color.g;
        const cb = color.b;
        const roughnessVal = options.roughness !== undefined ? options.roughness : 0.5;
        const metalnessVal = options.metalness !== undefined ? options.metalness : 0.5;
        const emissiveVal = options.emissive !== undefined ? options.emissive : 1.0;

        const total = end - start;
        let nx = 1, ny = 1, nz = 1;
        
        const isStandard = shape === 'sphere' || shape === 'cube' || shape === 'square' || shape === 'box';
        
        if (!isStandard) {
            const genData = {
                ...options,
                offset: center,
                radius: options.radius || sx || 30,
                color: options.color
            };
            this._runGenerator(shape, genData, start, end);
            for (let i = start; i < end; i++) {
                this.roughness[i] = roughnessVal;
                this.metalness[i] = metalnessVal;
                this.emissive[i] = emissiveVal;
            }
        } else {
            if (aligned && total > 0) {
                if (shape !== 'sphere') {
                    const activeDims = (sx > 0.001 ? 1 : 0) + (sy > 0.001 ? 1 : 0) + (sz > 0.001 ? 1 : 0);
                    if (activeDims === 1) {
                        nx = sx > 0.001 ? total : 1;
                        ny = sy > 0.001 ? total : 1;
                        nz = sz > 0.001 ? total : 1;
                    } else if (activeDims === 2) {
                        const area = (sx || 1) * (sy || 1) * (sz || 1);
                        const k = Math.sqrt(total / area);
                        nx = sx > 0.001 ? Math.max(1, Math.round(sx * k)) : 1;
                        ny = sy > 0.001 ? Math.max(1, Math.round(sy * k)) : 1;
                        nz = sz > 0.001 ? Math.max(1, Math.round(sz * k)) : 1;
                    } else {
                        const volume = sx * sy * sz || 1;
                        const k = Math.pow(total / volume, 1/3);
                        nx = Math.max(1, Math.round(sx * k));
                        ny = Math.max(1, Math.round(sy * k));
                        nz = Math.max(1, Math.round(sz * k));
                    }
                    while (nx * ny * nz < total) {
                        if (nx <= ny && nx <= nz) nx++;
                        else if (ny <= nx && ny <= nz) ny++;
                        else nz++;
                    }
                }
            }

            if (aligned && shape !== 'sphere') {
                let idx = 0;
                const divX = nx > 1 ? nx - 1 : 1;
                const divY = ny > 1 ? ny - 1 : 1;
                const divZ = nz > 1 ? nz - 1 : 1;
                
                for (let iz = 0; iz < nz && idx < total; iz++) {
                    const fz = nz > 1 ? (iz / divZ - 0.5) : 0;
                    const rz = fz * sz;
                    for (let iy = 0; iy < ny && idx < total; iy++) {
                        const fy = ny > 1 ? (iy / divY - 0.5) : 0;
                        const ry = fy * sy;
                        for (let ix = 0; ix < nx && idx < total; ix++) {
                            const fx = nx > 1 ? (ix / divX - 0.5) : 0;
                            const rx = fx * sx;
                            
                            const i = start + idx;
                            const i3 = i * 3;
                            this.roles[i] = 2; // Fixed
                            
                            const px = cx + rx + (Math.random() - 0.5) * noise;
                            const py = cy + ry + (Math.random() - 0.5) * noise;
                            const pz = cz + rz + (Math.random() - 0.5) * noise;
                            
                            this.basePositions[i3] = px;
                            this.basePositions[i3 + 1] = py;
                            this.basePositions[i3 + 2] = pz;
                            
                            this.targetPositions[i3] = px;
                            this.targetPositions[i3 + 1] = py;
                            this.targetPositions[i3 + 2] = pz;
                            
                            this.targetColors[i3] = cr;
                            this.targetColors[i3 + 1] = cg;
                            this.targetColors[i3 + 2] = cb;
                            
                            this.roughness[i] = roughnessVal;
                            this.metalness[i] = metalnessVal;
                            this.emissive[i] = emissiveVal;
                            
                            idx++;
                        }
                    }
                }
            } else if (aligned && shape === 'sphere') {
                const goldenAngle = Math.PI * (1 + Math.sqrt(5));
                const invTotal = 1.0 / total;
                const powExp = 0.3333333333333333;
                
                for (let i = start; i < end; i++) {
                    this.roles[i] = 2;
                    const i3 = i * 3;
                    const idx = i - start;
                    const val = (idx + 0.5) * invTotal;
                    
                    const phi = Math.acos(1 - 2 * val);
                    const theta = goldenAngle * (idx + 0.5);
                    const r = options.hollow ? 0.5 : 0.5 * Math.pow(val, powExp);
                    
                    const rx = r * Math.sin(phi) * Math.cos(theta) * sx;
                    const ry = r * Math.sin(phi) * Math.sin(theta) * sy;
                    const rz = r * Math.cos(phi) * sz;
                    
                    const px = cx + rx + (Math.random() - 0.5) * noise;
                    const py = cy + ry + (Math.random() - 0.5) * noise;
                    const pz = cz + rz + (Math.random() - 0.5) * noise;
                    
                    this.basePositions[i3] = px;
                    this.basePositions[i3 + 1] = py;
                    this.basePositions[i3 + 2] = pz;
                    
                    this.targetPositions[i3] = px;
                    this.targetPositions[i3 + 1] = py;
                    this.targetPositions[i3 + 2] = pz;
                    
                    this.targetColors[i3] = cr;
                    this.targetColors[i3 + 1] = cg;
                    this.targetColors[i3 + 2] = cb;
                    
                    this.roughness[i] = roughnessVal;
                    this.metalness[i] = metalnessVal;
                    this.emissive[i] = emissiveVal;
                }
            } else {
                // Random/non-aligned distribution
                const isSphere = shape === 'sphere';
                const PI2 = 2.0 * Math.PI;
                const powExp = 0.3333333333333333;
                
                for (let i = start; i < end; i++) {
                    this.roles[i] = 2;
                    const i3 = i * 3;
                    let rx = 0, ry = 0, rz = 0;
                    
                    if (isSphere) {
                        const u = Math.random(), v = Math.random();
                        const theta = PI2 * u;
                        const phi = Math.acos(2 * v - 1);
                        const r = options.hollow ? 0.5 : 0.5 * Math.pow(Math.random(), powExp);
                        rx = r * Math.sin(phi) * Math.cos(theta) * sx;
                        ry = r * Math.sin(phi) * Math.sin(theta) * sy;
                        rz = r * Math.cos(phi) * sz;
                    } else {
                        rx = (Math.random() - 0.5) * sx;
                        ry = (Math.random() - 0.5) * sy;
                        rz = (Math.random() - 0.5) * sz;
                    }
                    
                    const px = cx + rx + (Math.random() - 0.5) * noise;
                    const py = cy + ry + (Math.random() - 0.5) * noise;
                    const pz = cz + rz + (Math.random() - 0.5) * noise;
                    
                    this.basePositions[i3] = px;
                    this.basePositions[i3 + 1] = py;
                    this.basePositions[i3 + 2] = pz;
                    
                    this.targetPositions[i3] = px;
                    this.targetPositions[i3 + 1] = py;
                    this.targetPositions[i3 + 2] = pz;
                    
                    this.targetColors[i3] = cr;
                    this.targetColors[i3 + 1] = cg;
                    this.targetColors[i3 + 2] = cb;
                    
                    this.roughness[i] = roughnessVal;
                    this.metalness[i] = metalnessVal;
                    this.emissive[i] = emissiveVal;
                }
            }
        }

        this.geometry.attributes.roughness.needsUpdate = true;
        this.geometry.attributes.metalness.needsUpdate = true;
        this.geometry.attributes.emissiveAttr.needsUpdate = true;

        this.setParticleRangeMaterial(start, end, material);
        this.setParticleRangeShape(start, end, shape);
        this.registerSceneNode(name, { kind: 'volume', shape, material, notes: options.notes });
        if (options.animation) {
            this._registerLocalAnimation(options.animation, start, end);
        }
        return { name, start, end };
    }

    createTerrain(options = {}) {
        const name = options.name || `terrain_${Date.now()}`;
        const count = options.budget !== undefined 
            ? Math.floor(this.config.activeCount * options.budget) 
            : (options.count || 10000);
        const range = this.rangeManager.allocate(name, count);
        if (!range) return null;

        const { start, end } = range;
        const center = options.center || { x: 0, y: -0.5, z: 0 };
        const size = options.size !== undefined ? options.size : { x: 300, z: 300 };
        const sSize = this._normalizeVector(size, 300);
        const amplitude = options.amplitude || 12;
        const frequency = options.frequency || 0.015;
        const color = options.color ? new THREE.Color(options.color) : new THREE.Color(0x3a5a40);
        const material = options.material !== undefined ? options.material : 3;
        const flattenCenter = options.flattenCenter !== false;

        const cx = center.x;
        const cy = center.y;
        const cz = center.z;
        const sx = sSize.x;
        const sz = sSize.z;
        const cr = color.r;
        const cg = color.g;
        const cb = color.b;
        const roughnessVal = options.roughness !== undefined ? options.roughness : 0.5;
        const metalnessVal = options.metalness !== undefined ? options.metalness : 0.5;
        const emissiveVal = options.emissive !== undefined ? options.emissive : 1.0;

        for (let i = start; i < end; i++) {
            this.roles[i] = 2;
            const i3 = i * 3;
            const tx = (Math.random() - 0.5) * sx;
            const tz = (Math.random() - 0.5) * sz;
            
            // Procedural hills with a flatter center for buildings
            let ty = Math.sin(tx * frequency) * Math.cos(tz * frequency) * amplitude;
            if (flattenCenter) {
                const dist = Math.sqrt(tx*tx + tz*tz);
                const factor = THREE.MathUtils.smoothstep(dist, 0, 80); // Flatten up to 80 units
                ty *= factor;
            }

            const px = cx + tx;
            const py = cy + ty;
            const pz = cz + tz;

            this.basePositions[i3] = px;
            this.basePositions[i3 + 1] = py;
            this.basePositions[i3 + 2] = pz;

            this.targetPositions[i3] = px;
            this.targetPositions[i3 + 1] = py;
            this.targetPositions[i3 + 2] = pz;

            const lum = 0.7 + Math.random() * 0.4;
            this.targetColors[i3] = cr * lum;
            this.targetColors[i3 + 1] = cg * lum;
            this.targetColors[i3 + 2] = cb * lum;

            this.roughness[i] = roughnessVal;
            this.metalness[i] = metalnessVal;
            this.emissive[i] = emissiveVal;
        }

        this.geometry.attributes.roughness.needsUpdate = true;
        this.geometry.attributes.metalness.needsUpdate = true;
        this.geometry.attributes.emissiveAttr.needsUpdate = true;

        this.setParticleRangeMaterial(start, end, material);
        this.setParticleRangeShape(start, end, 'square');
        this.registerSceneNode(name, { kind: 'terrain', shape: 'square', material, notes: options.notes });
        if (options.animation) {
            this._registerLocalAnimation(options.animation, start, end);
        }
        return { name, start, end };
    }

    animateNode(name, props = {}) {
        const node = this.visualState.sceneNodes.byName[name];
        if (!node) return;

        const { start, end } = node;
        const type = props.type || 'float';
        const speed = props.speed || 1.0;
        const amplitude = props.amplitude || 1.0;
        const axis = props.axis || 'y';

        const updater = (time, delta) => {
            if (type === 'float') {
                const offset = Math.sin(time * speed) * amplitude;
                for (let i = start; i < end; i++) {
                    const i3 = i * 3;
                    if (axis === 'y') this.targetPositions[i3 + 1] = this.basePositions[i3 + 1] + offset;
                    else if (axis === 'x') this.targetPositions[i3] = this.basePositions[i3] + offset;
                    else if (axis === 'z') this.targetPositions[i3 + 2] = this.basePositions[i3 + 2] + offset;
                }
            } else if (type === 'orbit') {
                const radius = props.radius || 30;
                const center = props.center || { x: 0, y: 0, z: 0 };
                const cos = Math.cos(time * speed);
                const sin = Math.sin(time * speed);
                for (let i = start; i < end; i++) {
                    const i3 = i * 3;
                    const lx = this.basePositions[i3] - center.x;
                    const lz = this.basePositions[i3 + 2] - center.z;
                    this.targetPositions[i3] = center.x + lx * cos - lz * sin;
                    this.targetPositions[i3 + 2] = center.z + lx * sin + lz * cos;
                }
            } else if (type === 'pulse') {
                const b = 1.0 + Math.sin(time * speed) * amplitude;
                for (let i = start; i < end; i++) {
                    const i3 = i * 3;
                    this.targetPositions[i3] = this.basePositions[i3] * b;
                    this.targetPositions[i3 + 1] = this.basePositions[i3 + 1] * b;
                    this.targetPositions[i3 + 2] = this.basePositions[i3 + 2] * b;
                }
            }
        };

        this.visualState.nodeUpdaters.set(name, updater);
    }

    composeStarfield(rangeStart = -1, rangeEnd = -1) {
        const start = rangeStart === -1 ? 0 : rangeStart; const end = rangeEnd === -1 ? this.config.particleCount : rangeEnd;
        for (let i = start; i < end; i++) { this.roles[i] = 0; const i3 = i * 3; const radius = 600 + Math.random() * 1400; const theta = Math.random() * Math.PI * 2, phi = Math.acos(2 * Math.random() - 1); this.basePositions[i3] = radius * Math.sin(phi) * Math.cos(theta); this.basePositions[i3 + 1] = radius * Math.sin(phi) * Math.sin(theta); this.basePositions[i3 + 2] = radius * Math.cos(phi); this.targetPositions[i3] = this.basePositions[i3]; this.targetPositions[i3+1] = this.basePositions[i3+1]; this.targetPositions[i3+2] = this.basePositions[i3+2]; }
    }

    composeOrb(data = {}, rangeStart = -1, rangeEnd = -1) {
        const start = rangeStart === -1 ? 0 : rangeStart; const end = rangeEnd === -1 ? Math.floor(this.config.particleCount * this.visualState.budgets.core) : rangeEnd;
        const radius = data.radius || 35, offset = data.offset || { x: 0, y: 0, z: 0 }, col = data.color ? new THREE.Color(data.color) : null;
        for (let i = start; i < end; i++) { if (i >= this.config.particleCount) break; this.roles[i] = 1; const i3 = i * 3, u = Math.random(), v = Math.random(), theta = 2 * Math.PI * u, phi = Math.acos(2 * v - 1); this.basePositions[i3] = radius * Math.sin(phi) * Math.cos(theta) + offset.x; this.basePositions[i3 + 1] = radius * Math.sin(phi) * Math.sin(theta) + offset.y; this.basePositions[i3 + 2] = radius * Math.cos(phi) + offset.z; this.targetPositions[i3] = this.basePositions[i3]; this.targetPositions[i3+1] = this.basePositions[i3+1]; this.targetPositions[i3+2] = this.basePositions[i3+2]; if (col) { this.targetColors[i3] = col.r; this.targetColors[i3+1] = col.g; this.targetColors[i3+2] = col.b; } }
    }

    matrixToPoints({ matrix, palette = null, x = 0.5, y = 0.5, width = 0.4, height = 0.4 }, rangeStart = -1, rangeEnd = -1) {
        const rows = matrix.length, cols = matrix[0].length; this.scratchCanvas.width = 800; this.scratchCanvas.height = 800; this.sCtx.clearRect(0, 0, 800, 800); const cellW = (800 * width) / cols, cellH = (800 * height) / rows;
        for (let r = 0; r < rows; r++) { for (let c = 0; c < cols; c++) { const val = matrix[r][c]; if (val !== 0) { this.sCtx.fillStyle = (palette && palette[val]) ? palette[val] : (typeof val === 'string' ? val : '#fff'); this.sCtx.beginPath(); this.sCtx.roundRect((800 * x) - (800 * width) / 2 + c * cellW, (800 * y) - (800 * height) / 2 + r * cellH, cellW * 0.9, cellH * 0.9, cellW * 0.2); this.sCtx.fill(); } } }
        this.mapPixelsToParticles(this.sCtx, 800, 800, 0.2, rangeStart, rangeEnd);
    }

    pathToPoints({ path, x = 0.5, y = 0.5, scale = 0.3, strokeWidth = 5 }, rangeStart = -1, rangeEnd = -1) {
        this.scratchCanvas.width = 1000; this.scratchCanvas.height = 1000; this.sCtx.clearRect(0, 0, 1000, 1000); this.sCtx.translate(1000 * x, 1000 * y); this.sCtx.scale(1000 * scale, 1000 * scale); this.sCtx.strokeStyle = '#fff'; this.sCtx.lineWidth = strokeWidth / (1000 * scale); this.sCtx.beginPath();
        if (path.length > 0) { this.sCtx.moveTo(path[0].x, path[0].y); for (let i = 1; i < path.length; i++) this.sCtx.lineTo(path[i].x, path[i].y); }
        this.sCtx.stroke(); this.mapPixelsToParticles(this.sCtx, 1000, 1000, 0.2, rangeStart, rangeEnd);
    }

    async loadMap(src) {
        return new Promise((resolve) => {
            const img = new Image();
            img.crossOrigin = "anonymous";
            img.src = src;
            img.onload = () => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                canvas.width = img.width;
                canvas.height = img.height;
                ctx.drawImage(img, 0, 0);
                const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
                resolve({
                    width: canvas.width,
                    height: canvas.height,
                    sample: (u, v) => {
                        const x = Math.floor(u * (canvas.width - 1));
                        const y = Math.floor(v * (canvas.height - 1));
                        const idx = (y * canvas.width + x) * 4;
                        return {
                            r: data[idx] / 255,
                            g: data[idx + 1] / 255,
                            b: data[idx + 2] / 255,
                            a: data[idx + 3] / 255
                        };
                    },
                    sampleRandom: () => {
                        const u = Math.random();
                        const v = Math.random();
                        const s = this.sample(u, v);
                        return { u, v, ...s };
                    }
                });
            };
            img.onerror = () => resolve(null);
        });
    }

    handleResize() {
        const { width, height } = this._getViewportSize();
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
        if (this.metaRT) {
            this.metaRT.setSize(width, height);
        }
        if (this.metaUniforms?.u_res?.value) {
            this.metaUniforms.u_res.value.set(1 / width, 1 / height);
        }
        if (this.composer) {
            this.composer.setSize(width, height);
        }
    }

    handleMouseMove(x, y) {
        this.visualState.mouse.x = x; this.visualState.mouse.y = y; const v = new THREE.Vector3(x, y, 0.5); v.unproject(this.camera);
        const dir = v.sub(this.camera.position).normalize(); this.visualState.mouse = this.camera.position.clone().add(dir.multiplyScalar(-this.camera.position.z/dir.z));
    }

    handleRotation(dx, dy) { this.visualState.navigation.targetRotation.y += dx * 0.008; this.visualState.navigation.targetRotation.x += dy * 0.008; }

    handlePan(dx, dy) {
        const zoomFactor = Math.max(0.2, this.visualState.navigation.zoom / 200);
        this.visualState.navigation.pan.targetX -= dx * 0.05 * zoomFactor;
        this.visualState.navigation.pan.targetY += dy * 0.05 * zoomFactor;
    }

    handleZoom(delta) { this.visualState.navigation.targetZoom = Math.max(10, Math.min(1500, this.visualState.navigation.targetZoom + delta)); }

    resetNavigation() {
        this.visualState.navigation.targetRotation.set(0, 0, 0);
        this.visualState.navigation.pan.targetX = 0;
        this.visualState.navigation.pan.targetY = 0;
        this.visualState.navigation.targetZoom = 120;
    }

    async applyPreset(type) {
        if (!this.fetchImpl) {
            throw new Error('applyPreset requires fetch support.');
        }

        const manifestPath = `/presets/${type}/manifest.json`;
        try {
            const response = await this.fetchImpl(manifestPath);
            if (!response.ok) {
                throw new Error(`Manifest not found (${response.status})`);
            }

            const manifest = await response.json();
            const format = (manifest.format || 'script').toLowerCase();
            const entrypoint = manifest.entrypoint;

            if (format === 'script') {
                const sourcePath = this._normalizePublicSourcePath(`/presets/${type}/${entrypoint || 'scene-script.js'}`);
                await this.loadSceneScript(sourcePath);
                return manifest;
            }

            if (format === 'declarative') {
                const sourcePath = this._normalizePublicSourcePath(`/presets/${type}/${entrypoint || 'scene.json'}`);
                const sceneResp = await this.fetchImpl(sourcePath);
                if (!sceneResp.ok) {
                    throw new Error(`Failed to load declarative scene (${sceneResp.status})`);
                }
                const scene = await sceneResp.json();
                this.loadScene(scene);
                this._dispatchEngineEvent('fileSceneLoaded', {
                    sourcePath,
                    kind: 'scene'
                });
                return manifest;
            }

            if (format === 'builtin') {
                const builtinTarget = manifest.builtinTarget || manifest.id || type;
                this.setVisualTarget(builtinTarget);
                return manifest;
            }

            if (format === 'weg' || format === 'wds') {
                const sourcePath = this._normalizePublicSourcePath(`/presets/${type}/${entrypoint || 'scene-script.weg'}`);
                const buster = `?v=${Date.now()}`;
                const resp = await this.fetchImpl(sourcePath + buster);
                if (!resp.ok) throw new Error(`Failed to fetch ${format} preset (${resp.status})`);
                const wegText = await resp.text();
                
                this.applySceneWEG(wegText);
                this._dispatchEngineEvent('fileSceneLoaded', {
                    sourcePath,
                    kind: 'script'
                });
                return manifest;
            }

            if (format === 'js' || format === 'javascript') {
                const sourcePath = this._normalizePublicSourcePath(`/presets/${type}/${entrypoint || 'scene-script.js'}`);
                const buster = `?v=${Date.now()}`;
                const resp = await this.fetchImpl(sourcePath + buster);
                if (!resp.ok) throw new Error(`Failed to fetch js preset (${resp.status})`);
                const jsText = await resp.text();
                
                this.applySceneScriptSource(jsText);
                this._dispatchEngineEvent('fileSceneLoaded', {
                    sourcePath,
                    kind: 'script'
                });
                return manifest;
            }

            throw new Error(`Unsupported preset format: ${format}`);
        } catch (error) {
            console.error(`Preset load error: ${type}`, error);
        }

        const presets = this.getPresetRegistry();
        const preset = presets[type];
        if (preset) {
            if (preset.type === 'path') this.setVisualTarget('path', preset);
            else if (preset.type === 'matrix') this.setVisualTarget('matrix', { matrix: preset.data, ...preset.config });
            else this.setVisualTarget(type);
            return preset;
        }

        this.setVisualTarget(type);
    }

    textToPoints(text, rangeStart = -1, rangeEnd = -1) {
        this.scratchCanvas.width = 1200; this.scratchCanvas.height = 800; this.sCtx.clearRect(0, 0, 1200, 800); let fontSize = 120;
        const fitText = () => { this.sCtx.font = `bold ${fontSize}px Orbitron`; if (this.sCtx.measureText(text).width > 1100 && fontSize > 20) { fontSize -= 5; fitText(); } }
        fitText(); this.sCtx.fillStyle = 'white'; this.sCtx.textAlign = 'center'; this.sCtx.textBaseline = 'middle'; this.sCtx.fillText(text, 600, 400);
        this.mapPixelsToParticles(this.sCtx, 1200, 800, 0.15, rangeStart, rangeEnd);
    }

    sketchToPoints(externalCtx, width, height) { this.mapPixelsToParticles(externalCtx, width, height, 0.2); }

    mapPixelsToParticles(ctx, width, height, scale, rangeStart = -1, rangeEnd = -1) {
        const imageData = ctx.getImageData(0, 0, width, height).data; const points = []; const step = 2; 
        for (let y = 0; y < height; y += step) { for (let x = 0; x < width; x += step) { const index = (y * width + x) * 4; if (imageData[index + 3] > 100) { points.push({ x: (x - width / 2) * scale, y: (height / 2 - y) * scale, color: { r: imageData[index]/255, g: imageData[index+1]/255, b: imageData[index+2]/255 } }); } } }
        if (points.length === 0) return; const start = rangeStart === -1 ? 0 : rangeStart, end = rangeEnd === -1 ? Math.floor(this.config.particleCount * 0.85) : rangeEnd;
        const count = end - start, ppp = count / points.length, jitter = 0.5 * Math.min(2.5, Math.log10(ppp + 1));
        for (let i = start; i < end; i++) { const i3 = i * 3; if (i >= this.config.particleCount) break; this.roles[i] = 2; const p = points[i % points.length]; this.basePositions[i3] = p.x + (Math.random()-0.5)*jitter; this.basePositions[i3+1] = p.y + (Math.random()-0.5)*jitter; this.basePositions[i3+2] = (Math.random()-0.5)*2 + (Math.random()-0.5)*jitter; this.targetPositions[i3] = this.basePositions[i3]; this.targetPositions[i3+1] = this.basePositions[i3+1]; this.targetPositions[i3+2] = this.basePositions[i3+2]; if (p.color) { this.targetColors[i3] = p.color.r; this.targetColors[i3+1] = p.color.g; this.targetColors[i3+2] = p.color.b; } }
    }

    setDensity(val, rerender = true) {
        if (this.isDestroyed) return;
        if (this.visualState?.isDensityChanging) return;
        
        let density = val;
        const activeMeta = this.visualState?.lastPayload?.scriptMeta;
        if (activeMeta) {
            if (activeMeta.maxParticles && density > activeMeta.maxParticles) {
                density = activeMeta.maxParticles;
            }
            if (activeMeta.minParticles && density < activeMeta.minParticles) {
                console.warn(`[Wegena] Density (${density}) is below the recommended minimum of ${activeMeta.minParticles} for '${activeMeta.label || 'Active Scene'}'.`);
            }
        }

        const previousActiveCount = this.config.activeCount;
        if (density === previousActiveCount) return;

        this.config.activeCount = density;

        if (this.geometry) {
            this.geometry.setDrawRange(0, density);
        }

        if (!rerender) return;

        // --- Paradigm Shift: Dynamic Vector Re-evaluation of the Scene ---
        const type = this.visualState.currentShapeType;
        const payload = this.visualState.lastPayload;

        if (type === 'script' && payload?.scriptSource) {
            // Re-apply the compiled JavaScript scene using the new activeCount/budget
            this.applySceneScriptSource(payload.scriptSource, true);
        } else if (payload?.version && payload?.config) {
            // Re-apply the declarative JSON scene using the new activeCount/budget
            this.loadScene(payload, false, true);
        } else {
            // Regeneration fallback for classic shapes
            const presets = this.getPresetRegistry();
            switch(type) {
                case 'galaxy': presets.generateGalaxy?.(this); break;
                case 'solarSystem': presets.generateSolarSystem?.(this); break;
                case 'landscape': presets.generateLandscape?.(this); break;
                case "earth": presets.generateEarth?.(this); break;
                case 'text': this.textToPoints(payload); break;
                case 'sketch': this.sketchToPoints(); break;
                case 'matrix': this.matrixToPoints(payload); break;
                case 'path': this.pathToPoints(payload); break;
                case 'orb': this.composeOrb(); break;
                default: this.composeStarfield(); break;
            }
        }

        // Trigger gorgeous morph easing transitions
        this._activateReorganization();

        if (this.geometry) {
            if (this.geometry.attributes.position) this.geometry.attributes.position.needsUpdate = true;
            if (this.geometry.attributes.color) this.geometry.attributes.color.needsUpdate = true;
            if (this.geometry.attributes.role) this.geometry.attributes.role.needsUpdate = true;
            if (this.geometry.attributes.particleShape) this.geometry.attributes.particleShape.needsUpdate = true;
            if (this.geometry.attributes.materialType) this.geometry.attributes.materialType.needsUpdate = true;
            if (this.geometry.attributes.roughness) this.geometry.attributes.roughness.needsUpdate = true;
            if (this.geometry.attributes.metalness) this.geometry.attributes.metalness.needsUpdate = true;
            if (this.geometry.attributes.emissiveAttr) this.geometry.attributes.emissiveAttr.needsUpdate = true;
            
            const transAttr = this.geometry.getAttribute?.('transitionAlpha');
            if (transAttr) transAttr.needsUpdate = true;
        }
        
        this._dispatchEngineEvent('densityChanged', { value: density });
    }

    setFOV(val) { this.camera.fov = val; this.camera.updateProjectionMatrix(); }

    _updateFlyNavigation(delta) {
        const nav = this.visualState.navigation;
        const keys = nav.keys;
        const moveSpeed = (keys['ShiftLeft'] || keys['ShiftRight']) ? 200 : (keys['ControlLeft'] || keys['ControlRight']) ? 20 : 80;
        
        const direction = new THREE.Vector3();
        if (keys['KeyW']) direction.z -= 1;
        if (keys['KeyS']) direction.z += 1;
        if (keys['KeyA']) direction.x -= 1;
        if (keys['KeyD']) direction.x += 1;
        if (keys['KeyQ']) direction.y -= 1;
        if (keys['KeyE']) direction.y += 1;
        
        if (direction.length() > 0) {
            direction.normalize();
            // Rotate direction by camera orientation
            const rotation = new THREE.Quaternion().setFromEuler(nav.rotation);
            direction.applyQuaternion(rotation);
            
            nav.velocity.copy(direction).multiplyScalar(moveSpeed * delta);
            nav.pan.targetX += nav.velocity.x;
            nav.pan.targetY += nav.velocity.y;
            nav.targetZoom += nav.velocity.z;
        }
    }

    animate() {
        if (this.isDestroyed) return;
        this.animationFrameId = this.requestFrame(() => this.animate());
        const { activeCount: pCount } = this.config;
        const delta = this.visualState.clock.getDelta();
        const time = this.visualState.clock.getElapsedTime();
        
        if (this.visualState.navigation.mode === 'fly') {
            this._updateFlyNavigation(delta);
        }

        // Run Modular Simulation
        if (this.currentSimulator) {
            this.currentSimulator.update(time, delta);
        }
        
        // Update Profiler
        this.profiler.update(delta);

        const nav = this.visualState.navigation; nav.zoom += (nav.targetZoom - nav.zoom) * 0.1; this.camera.position.z = nav.zoom;
        nav.rotation.x += (nav.targetRotation.x - nav.rotation.x) * 0.05; nav.rotation.y += (nav.targetRotation.y - nav.rotation.y) * 0.05;
        this.camera.position.x = nav.pan.x += (nav.pan.targetX - nav.pan.x) * 0.1; this.camera.position.y = nav.pan.y += (nav.pan.targetY - nav.pan.y) * 0.1;
        this.points.rotation.x = this.pointsPhysical.rotation.x = (this.points.rotation.x + (nav.rotation.x - this.points.rotation.x) * 0.1); this.points.rotation.y = this.pointsPhysical.rotation.y = (this.points.rotation.y + (nav.rotation.y - this.points.rotation.y) * 0.1);
        this._tickBackground(time); if (this.visualState.onUpdate) this.visualState.onUpdate(time, this.visualState.clock.getDelta());
        this._updateFxFragments(delta);
        if (this.matUniforms) this.matUniforms.u_time.value = time; 
        const hasActiveFx = this.visualState.fxFragments && this.visualState.fxFragments.length > 0;
        const needsBufferUpdate = this.visualState.reorganization.active || this.visualState.hasDynamicRoles || hasActiveFx;
        if (needsBufferUpdate) {
            this.geometry.attributes.position.needsUpdate = true; 
            this.geometry.attributes.color.needsUpdate = true; 
            this.geometry.attributes.transitionAlpha.needsUpdate = true;
        }
        
        this._updateLineConnections(); 
        
        this.renderer.render(this.scene, this.camera);
        
        let settleSample = { error: 0, sampledParticles: 0 };
        let nextStableFrames = 0;
        
        if (this.visualState.reorganization.active || this.pendingSettleRequests.length > 0) {
            settleSample = this._measureSceneSettle();
            nextStableFrames = Number.isFinite(settleSample.error) && settleSample.error <= 0.18
                ? (this.visualState.settle.stableFrames || 0) + 1
                : 0;
            
            const reorgElapsedMs = this._now() - (this.visualState.reorganization.startedAt || 0);
            if (
                this.visualState.reorganization.active &&
                (
                    nextStableFrames >= this.visualState.reorganization.settleFramesToDisable ||
                    reorgElapsedMs >= (this.visualState.reorganization.maxDurationMs || 1100)
                )
            ) {
                this._deactivateReorganization();
            }
        }
        
        this.visualState.settle = {
            error: settleSample.error,
            sampledParticles: settleSample.sampledParticles,
            stableFrames: nextStableFrames,
            sceneRevision: this.sceneLoadRevision
        };
        this._processSettleRequests(settleSample);
    }

    destroy() {
        if (this.isDestroyed) return;
        this.isDestroyed = true;

        if (this.animationFrameId !== null) {
            this.cancelFrame(this.animationFrameId);
            this.animationFrameId = null;
        }

        this.resizeObserver?.disconnect?.();
        this.resizeObserver = null;

        this.pendingSettleRequests.forEach((request) => request.resolve({
            settled: false,
            reason: 'destroyed',
            revision: request.revision,
            currentRevision: this.sceneLoadRevision
        }));
        this.pendingSettleRequests = [];

        if (this._boundOnKeyDown) {
            this.globalObject.removeEventListener('keydown', this._boundOnKeyDown);
            this._boundOnKeyDown = null;
        }
        if (this._boundOnKeyUp) {
            this.globalObject.removeEventListener('keyup', this._boundOnKeyUp);
            this._boundOnKeyUp = null;
        }

        this.controlsManager?.destroy?.();
        this.controlsManager = null;

        this.currentSimulator?.deactivate?.();
        this.geometry?.dispose?.();
        this.material?.dispose?.();
        this.materialPhysical?.dispose?.();
        this.metaRT?.dispose?.();
        this.metaQuad?.geometry?.dispose?.();
        this.metaQuad?.material?.dispose?.();
        this.lines?.geometry?.dispose?.();
        this.lines?.material?.dispose?.();
        this.skybox?.geometry?.dispose?.();
        this.skybox?.material?.dispose?.();
        this.renderer?.dispose?.();

        const canvas = this.renderer?.domElement;
        if (canvas?.parentNode === this.container) {
            this.container.removeChild(canvas);
        }
    }
}

WegenaEngine.VERSION = WEGENA_ENGINE_VERSION;
WegenaEngine.SCENE_SCRIPT_API_VERSION = WEGENA_SCENE_SCRIPT_API_VERSION;
