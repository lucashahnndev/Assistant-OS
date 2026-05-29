import React, { useEffect, useRef, forwardRef, useImperativeHandle } from 'react';

const DEFAULT_PRESET_ID = 'ai-orb-classic';

const WegenaParticleCanvas = forwardRef(({ state, voice, ttsIntensity, theme = 'dark', wegScript = '', sceneStreamActive = false, defaultPresetId = DEFAULT_PRESET_ID, overrideConfig = null, onSceneLoaded }, ref) => {
    const containerRef = useRef(null);
    const engineRef = useRef(null);
    const controlsRef = useRef(null);
    const wegScriptRef = useRef(wegScript);
    const sceneStreamActiveRef = useRef(sceneStreamActive);
    const loadingDefaultRef = useRef(false);
    const currentModeRef = useRef('default');
    const appliedDefaultPresetIdRef = useRef(null);
    const defaultSceneRetryTimerRef = useRef(null);
    const defaultSceneRetryCountRef = useRef(0);
    const defaultSceneScriptCacheRef = useRef({});

    const injectOverrides = (script) => {
        if (!script || !overrideConfig) return script;
        let injected = script;
        if (overrideConfig.particleSize !== undefined && overrideConfig.particleSize !== '') {
            injected += `\n@World { size: ${overrideConfig.particleSize} }`;
        }
        return injected;
    };

    const buildAtlasSignal = () => {
        const voiceStatus = state?.voiceState?.status || 'idle';
        const isRecording = !!voice?.isRecording;
        const micIntensity = voiceStatus === 'listening' && isRecording
            ? Number(voice?.intensity || state?.voiceState?.intensity || 0)
            : 0;
        return {
            status: voiceStatus || 'idle',
            micIntensity,
            ttsIntensity: Number(ttsIntensity || 0),
            isRecording,
            theme: theme || 'dark',
        };
    };

    const syncAtlasSignal = () => {
        const engine = engineRef.current;
        if (!engine) return;
        engine.visualState.atlasSignal = buildAtlasSignal();
    };

    const fetchDefaultSceneScript = async () => {
        if (defaultSceneScriptCacheRef.current[defaultPresetId]) {
            return defaultSceneScriptCacheRef.current[defaultPresetId];
        }
        const response = await window.fetch(`/presets/${defaultPresetId}/scene-script.weg?v=${Date.now()}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch default Wegena scene '${defaultPresetId}' (${response.status})`);
        }
        const script = await response.text();
        defaultSceneScriptCacheRef.current[defaultPresetId] = script;
        return script;
    };

    const clearDefaultRetryTimer = () => {
        if (defaultSceneRetryTimerRef.current) {
            window.clearTimeout(defaultSceneRetryTimerRef.current);
            defaultSceneRetryTimerRef.current = null;
        }
    };

    const scheduleDefaultSceneVerification = () => {
        clearDefaultRetryTimer();
        defaultSceneRetryTimerRef.current = window.setTimeout(async () => {
            const engine = engineRef.current;
            if (!engine) return;
            if (currentModeRef.current !== 'default' || sceneStreamActiveRef.current) return;

            if (defaultSceneRetryCountRef.current >= 8) return;

            defaultSceneRetryCountRef.current += 1;
            if (engine.visualState.currentShapeType !== 'script') {
                try {
                    const wegDefaultScript = await fetchDefaultSceneScript();
                    engine.applySceneWEG(injectOverrides(wegDefaultScript));
                    syncAtlasSignal();
                } catch (error) {
                    console.error('Failed to re-apply Atlas default Wegena preset:', error);
                }
            }
            scheduleDefaultSceneVerification();
        }, 1200);
    };

    const loadDefaultScene = async ({ force = false } = {}) => {
        const engine = engineRef.current;
        if (!engine || loadingDefaultRef.current) return;
        if (!force && currentModeRef.current === 'default' && appliedDefaultPresetIdRef.current === defaultPresetId) {
            syncAtlasSignal();
            return;
        }
        loadingDefaultRef.current = true;
        clearDefaultRetryTimer();
        defaultSceneRetryCountRef.current = 0;
        try {
            currentModeRef.current = 'default';
            sceneStreamActiveRef.current = false;
            engine.clearSceneNodes();
            engine.clearFxFragments();
            const wegDefaultScript = await fetchDefaultSceneScript();
            engine.applySceneWEG(injectOverrides(wegDefaultScript));
            appliedDefaultPresetIdRef.current = defaultPresetId;
            syncAtlasSignal();
            scheduleDefaultSceneVerification();
            if (typeof onSceneLoaded === 'function') onSceneLoaded();
        } catch (e) {
            console.error('Failed to load Atlas default Wegena preset:', e);
        } finally {
            loadingDefaultRef.current = false;
        }
    };

    useEffect(() => {
        wegScriptRef.current = wegScript;
        sceneStreamActiveRef.current = sceneStreamActive;
        syncAtlasSignal();
    }, [state, voice, ttsIntensity, theme, wegScript, sceneStreamActive, defaultPresetId]);

    useImperativeHandle(ref, () => ({
        applySceneInit: ({ config } = {}) => {
            const engine = engineRef.current;
            if (!engine) return;
            try {
                currentModeRef.current = 'stream';
                sceneStreamActiveRef.current = true;
                engine.loadScene({
                    version: '1.0',
                    config: config || {},
                    content: { type: 'composition', elements: [] }
                }, false);
            } catch (e) {
                console.error('Error applying streamed scene init:', e);
            }
        },
        applyScenePatch: (element) => {
            const engine = engineRef.current;
            if (!engine || !element) return;
            try {
                currentModeRef.current = 'stream';
                sceneStreamActiveRef.current = true;
                engine.updateSceneNode(element);
            } catch (e) {
                console.error('Error applying streamed scene patch:', e);
            }
        },
        removeSceneNode: (name) => {
            const engine = engineRef.current;
            if (!engine || !name) return;
            try {
                currentModeRef.current = 'stream';
                sceneStreamActiveRef.current = true;
                engine.deleteSceneNode(name);
            } catch (e) {
                console.error('Error removing streamed scene node:', e);
            }
        },
        applySceneEnv: ({ background, camera, particles } = {}) => {
            const engine = engineRef.current;
            if (!engine) return;
            try {
                if (background) engine.setBackground(background);
                if (particles?.density) engine.setDensity(particles.density, false);
                if (particles?.size !== undefined) engine.setParticleSize(particles.size);
                if (camera?.zoom !== undefined) engine.visualState.navigation.targetZoom = camera.zoom;
                if (camera?.rotation) {
                    if (camera.rotation.x !== undefined) engine.visualState.navigation.targetRotation.x = camera.rotation.x;
                    if (camera.rotation.y !== undefined) engine.visualState.navigation.targetRotation.y = camera.rotation.y;
                }
            } catch (e) {
                console.error('Error applying streamed scene env:', e);
            }
        },
        clearScene: async () => {
            await loadDefaultScene();
        }
    }));

    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const WegenaEngineClass = window.WegenaEngine || (typeof WegenaEngine !== 'undefined' ? WegenaEngine : null);
        if (!WegenaEngineClass) {
            console.error('WegenaEngine was not found in the global scope. Verify that the scripts are loaded in index.html.');
            return;
        }

        try {
            const engine = new WegenaEngineClass(container, {
                particleCount: 70000,
                activeCount: 45000,
                zoom: 165,
                baseColor: new window.THREE.Color('#3b82f6'),
                glowColor: new window.THREE.Color('#00f2ff')
            });

            engine.setSimulatorMode('cpu');
            engineRef.current = engine;
            if (import.meta.env.DEV && typeof window !== 'undefined') {
                window.__atlasWegenaEngine = engine;
            }
            syncAtlasSignal();

            loadDefaultScene();

            const WegenaCanvasControlsClass = window.WegenaCanvasControls || (typeof WegenaCanvasControls !== 'undefined' ? WegenaCanvasControls : null);
            if (WegenaCanvasControlsClass) {
                const controls = new WegenaCanvasControlsClass(engine, {
                    viewport: window.document.body,
                    THREE: window.THREE,
                    shouldIgnoreTarget: (target) => {
                        return !!target.closest('.chat-input-area, textarea, input, button, .sidebar, .glass, a, label');
                    }
                });
                engine.setControlsManager(controls);
                controlsRef.current = controls;
            }
        } catch (err) {
            console.error('Failed to initialize WegenaEngine host:', err);
        }

        return () => {
            clearDefaultRetryTimer();
            if (controlsRef.current) {
                try {
                    controlsRef.current.destroy();
                } catch (_) {}
                controlsRef.current = null;
            }
            if (engineRef.current) {
                try {
                    engineRef.current.destroy();
                } catch (e) {
                    console.error('Error during WegenaEngine destruction:', e);
                }
                engineRef.current = null;
            }
            if (import.meta.env.DEV && typeof window !== 'undefined' && window.__atlasWegenaEngine) {
                delete window.__atlasWegenaEngine;
            }
        };
    }, []);

    useEffect(() => {
        const engine = engineRef.current;
        if (!engine) return;

        const applySceneMode = async () => {
            if (wegScript && wegScript.trim()) {
                try {
                    currentModeRef.current = 'script';
                    sceneStreamActiveRef.current = true;
                    appliedDefaultPresetIdRef.current = null;
                    engine.applySceneWEG(injectOverrides(wegScript));
                } catch (err) {
                    console.error('Failed to compile or apply Wegena script:', err);
                }
                return;
            }

            if (!sceneStreamActiveRef.current) {
                await loadDefaultScene({
                    force: currentModeRef.current !== 'default' || appliedDefaultPresetIdRef.current !== defaultPresetId
                });
            }
        };

        applySceneMode();
    }, [wegScript, sceneStreamActive, defaultPresetId]);

    // Apply real-time overrideConfig from HUD
    useEffect(() => {
        const engine = engineRef.current;
        if (!engine || !overrideConfig) return;
        
        try {
            // Preset change
            if (overrideConfig.preset && appliedDefaultPresetIdRef.current !== overrideConfig.preset) {
                // Change default scene gracefully
                appliedDefaultPresetIdRef.current = overrideConfig.preset;
                currentModeRef.current = 'default';
                sceneStreamActiveRef.current = false;
                engine.clearSceneNodes();
                engine.clearFxFragments();
                window.fetch(`/presets/${overrideConfig.preset}/scene-script.weg?v=${Date.now()}`)
                    .then(res => res.text())
                    .then(script => {
                        engine.applySceneWEG(injectOverrides(script));
                        syncAtlasSignal();
                    }).catch(console.error);
            }
            
            // Particle tweaks
            if (overrideConfig.particleCount && typeof engine.setDensity === 'function') {
                if (engine.config.particleCount !== overrideConfig.particleCount) {
                    engine.setDensity(overrideConfig.particleCount, true);
                    // Re-apply script to fix roles after density resize
                    window.fetch(`/presets/${overrideConfig.preset || appliedDefaultPresetIdRef.current}/scene-script.weg?v=${Date.now()}`)
                        .then(res => res.text())
                        .then(script => engine.applySceneWEG(injectOverrides(script)))
                        .catch(console.error);
                }
            }
            
            if (overrideConfig.particleSize !== undefined && typeof engine.setParticleSize === 'function') {
                if (engine.matUniforms && engine.matUniforms.u_size && Math.abs(engine.matUniforms.u_size.value - overrideConfig.particleSize) > 0.001) {
                    window.fetch(`/presets/${overrideConfig.preset || appliedDefaultPresetIdRef.current}/scene-script.weg?v=${Date.now()}`)
                        .then(res => res.text())
                        .then(script => engine.applySceneWEG(injectOverrides(script)))
                        .catch(console.error);
                }
            }
        } catch (err) {
            console.error('Failed to apply Wegena override config', err);
        }
    }, [overrideConfig]);

    return (
        <div
            ref={containerRef}
            style={{
                width: '100%',
                height: '100%',
                position: 'absolute',
                inset: 0,
                overflow: 'hidden',
                background: 'transparent'
            }}
        />
    );
});

export default WegenaParticleCanvas;
