class WegenaCanvasControls {
    constructor(engine, options = {}) {
        this.engine = engine;
        this.viewport = options.viewport || null;
        this.globalObject = options.globalObject || window;
        this.THREE = options.THREE || this.globalObject.THREE;
        this.isEnabled = options.enabled !== false;
        this.overlayEnabled = options.overlayEnabled !== false;
        this.onChange = typeof options.onChange === 'function' ? options.onChange : null;
        this.shouldIgnoreTarget = typeof options.shouldIgnoreTarget === 'function'
            ? options.shouldIgnoreTarget
            : () => false;
        this.zoomInButton = options.zoomInButton || null;
        this.zoomOutButton = options.zoomOutButton || null;
        this.resetButton = options.resetButton || null;
        this.zoomIndicator = options.zoomIndicator || null;
        this.navModeSelector = options.navModeSelector || null;
        this.gizmoCanvas = options.gizmoCanvas || null;

        this.isDragging = false;
        this.lastX = 0;
        this.lastY = 0;

        // Touch state
        this.isTouching = false;
        this.lastTouchDistance = 0;
        this.lastTouchX = 0;
        this.lastTouchY = 0;

        this.gizmoRenderer = null;
        this.gizmoScene = null;
        this.gizmoCamera = null;
        this.gizmoAnimationFrameId = null;
        this.lastGizmoQuaternion = null;

        this._bindHandlers();
        this._attach();
        this._initOptionalUi();
        this.emitChange();
    }

    _bindHandlers() {
        this._onMouseDown = (event) => {
            if (!this.isEnabled || this.shouldIgnoreTarget(event.target)) return;
            this.isDragging = true;
            this.lastX = event.clientX;
            this.lastY = event.clientY;
        };

        this._onMouseMove = (event) => {
            if (!this.isEnabled || !this.isDragging) return;
            const dx = event.clientX - this.lastX;
            const dy = event.clientY - this.lastY;
            this.engine.handleRotation(dx, dy);
            this.lastX = event.clientX;
            this.lastY = event.clientY;
            this.emitChange();
        };

        this._onMouseUp = () => {
            this.isDragging = false;
        };

        this._onWheel = (event) => {
            if (!this.isEnabled || this.shouldIgnoreTarget(event.target)) return;
            this.engine.handleZoom(event.deltaY * 0.1);
            this.emitChange();
        };

        this._onResize = () => {
            this.engine.handleResize();
            this.emitChange();
        };

        this._onZoomInClick = () => {
            if (!this.isEnabled) return;
            this.engine.handleZoom(-10);
            this.emitChange();
        };

        this._onZoomOutClick = () => {
            if (!this.isEnabled) return;
            this.engine.handleZoom(10);
            this.emitChange();
        };

        this._onResetClick = () => {
            if (!this.isEnabled) return;
            this.engine.resetNavigation();
            this.emitChange();
        };

        this._onNavModeClick = (event) => {
            const button = event.target.closest('[data-mode]');
            if (!button || !this.isEnabled) return;
            this.engine.setNavigationMode(button.dataset.mode);
        };

        this._onNavModeChanged = (event) => {
            this._syncNavModeUi(event.detail?.mode);
        };

        this._onGizmoMouseDown = (event) => {
            if (!this.isEnabled || !this.gizmoCanvas || !this.gizmoCamera || !this.gizmoScene || !this.THREE) return;
            const rect = this.gizmoCanvas.getBoundingClientRect();
            const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
            const y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
            const raycaster = new this.THREE.Raycaster();
            raycaster.setFromCamera({ x, y }, this.gizmoCamera);
            const intersects = raycaster.intersectObjects(this.gizmoScene.children);
            if (intersects.length === 0) return;

            const color = intersects[0].object.material.color.getHex();
            if (color === 0xff4444) this.engine.alignToAxis('x');
            if (color === 0x44ff44) this.engine.alignToAxis('y');
            if (color === 0x4444ff) this.engine.alignToAxis('z');
            this.emitChange();
        };

        this._onGizmoTouchStart = (event) => {
            if (!this.isEnabled || event.touches.length !== 1) return;
            const touch = event.touches[0];
            const fakeEvent = {
                clientX: touch.clientX,
                clientY: touch.clientY
            };
            this._onGizmoMouseDown(fakeEvent);
        };

        // Touch Handlers
        this._onTouchStart = (event) => {
            if (!this.isEnabled || this.shouldIgnoreTarget(event.target)) return;
            this.isTouching = true;

            if (event.touches.length === 1) {
                this.lastTouchX = event.touches[0].clientX;
                this.lastTouchY = event.touches[0].clientY;
            } else if (event.touches.length === 2) {
                this.lastTouchDistance = this._getTouchDistance(event.touches);
            }
        };

        this._onTouchMove = (event) => {
            if (!this.isEnabled || !this.isTouching) return;

            if (event.touches.length === 1) {
                const dx = event.touches[0].clientX - this.lastTouchX;
                const dy = event.touches[0].clientY - this.lastTouchY;
                this.engine.handleRotation(dx, dy);
                this.lastTouchX = event.touches[0].clientX;
                this.lastTouchY = event.touches[0].clientY;
                this.emitChange();
            } else if (event.touches.length === 2) {
                const distance = this._getTouchDistance(event.touches);
                const delta = this.lastTouchDistance - distance;
                this.engine.handleZoom(delta * 0.5);
                this.lastTouchDistance = distance;
                this.emitChange();
            }
        };

        this._onTouchEnd = () => {
            this.isTouching = false;
        };
    }

    _attach() {
        this.viewport?.addEventListener('mousedown', this._onMouseDown);
        this.viewport?.addEventListener('wheel', this._onWheel, { passive: true });
        this.viewport?.addEventListener('touchstart', this._onTouchStart, { passive: false });
        this.viewport?.addEventListener('touchmove', this._onTouchMove, { passive: false });
        this.viewport?.addEventListener('touchend', this._onTouchEnd);

        this.globalObject.addEventListener('mousemove', this._onMouseMove);
        this.globalObject.addEventListener('mouseup', this._onMouseUp);
        this.globalObject.addEventListener('resize', this._onResize);
    }

    _initOptionalUi() {
        this.zoomInButton?.addEventListener('click', this._onZoomInClick);
        this.zoomOutButton?.addEventListener('click', this._onZoomOutClick);
        this.resetButton?.addEventListener('click', this._onResetClick);
        this.navModeSelector?.addEventListener('click', this._onNavModeClick);
        this.globalObject.addEventListener('navModeChanged', this._onNavModeChanged);
        this._syncNavModeUi(this.engine.visualState?.navigation?.mode);
        this._updateZoomIndicator();
        this._initGizmo();
    }

    _syncNavModeUi(mode) {
        if (!this.navModeSelector) return;
        this.navModeSelector.querySelectorAll('[data-mode]').forEach((button) => {
            button.classList.toggle('active', button.dataset.mode === mode);
        });
    }

    _updateZoomIndicator() {
        if (!this.zoomIndicator) return;
        const zoom = this.engine.visualState?.navigation?.zoom ?? 120;
        const zoomPercent = (zoom - 10) / (1500 - 10);
        this.zoomIndicator.style.bottom = `${Math.max(0, Math.min(1, zoomPercent)) * 100}%`;
    }

    _initGizmo() {
        if (!this.gizmoCanvas || !this.THREE) return;
        this.gizmoRenderer = new this.THREE.WebGLRenderer({
            canvas: this.gizmoCanvas,
            antialias: true,
            alpha: true
        });
        this.gizmoRenderer.setSize(100, 100);

        this.gizmoScene = new this.THREE.Scene();
        this.gizmoCamera = new this.THREE.PerspectiveCamera(50, 1, 0.1, 100);
        this.gizmoCamera.position.z = 5;

        const xAxis = new this.THREE.Mesh(
            new this.THREE.CylinderGeometry(0.1, 0.1, 3),
            new this.THREE.MeshBasicMaterial({ color: 0xff4444 })
        );
        xAxis.rotation.z = Math.PI / 2;
        this.gizmoScene.add(xAxis);

        const yAxis = new this.THREE.Mesh(
            new this.THREE.CylinderGeometry(0.1, 0.1, 3),
            new this.THREE.MeshBasicMaterial({ color: 0x44ff44 })
        );
        this.gizmoScene.add(yAxis);

        const zAxis = new this.THREE.Mesh(
            new this.THREE.CylinderGeometry(0.1, 0.1, 3),
            new this.THREE.MeshBasicMaterial({ color: 0x4444ff })
        );
        zAxis.rotation.x = Math.PI / 2;
        this.gizmoScene.add(zAxis);

        this.gizmoCanvas.addEventListener('mousedown', this._onGizmoMouseDown);
        this.gizmoCanvas.addEventListener('touchstart', this._onGizmoTouchStart, { passive: true });
        if (this.THREE) {
            this.lastGizmoQuaternion = new this.THREE.Quaternion();
        }
        this._animateGizmo();
    }

    _animateGizmo() {
        if (!this.gizmoRenderer || !this.gizmoScene || !this.gizmoCamera) return;
        this.gizmoAnimationFrameId = this.globalObject.requestAnimationFrame(() => this._animateGizmo());
        if (this.engine.points) {
            const currentQuat = this.engine.points.quaternion;
            if (!this.lastGizmoQuaternion || !this.lastGizmoQuaternion.equals(currentQuat)) {
                this.gizmoScene.quaternion.copy(currentQuat).invert();
                if (!this.lastGizmoQuaternion && this.THREE) {
                    this.lastGizmoQuaternion = new this.THREE.Quaternion();
                }
                if (this.lastGizmoQuaternion) {
                    this.lastGizmoQuaternion.copy(currentQuat);
                }
                this.gizmoRenderer.render(this.gizmoScene, this.gizmoCamera);
            }
        }
    }

    emitChange() {
        this._updateZoomIndicator();
        this.onChange?.(this.engine.getRenderSnapshot());
    }

    setEnabled(enabled) {
        this.isEnabled = !!enabled;
    }

    setOverlayEnabled(enabled) {
        this.overlayEnabled = !!enabled;
    }

    getState() {
        return {
            enabled: this.isEnabled,
            overlayEnabled: this.overlayEnabled,
            isDragging: this.isDragging || this.isTouching
        };
    }

    _getTouchDistance(touches) {
        const dx = touches[0].clientX - touches[1].clientX;
        const dy = touches[0].clientY - touches[1].clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }

    destroy() {
        this.viewport?.removeEventListener('mousedown', this._onMouseDown);
        this.viewport?.removeEventListener('wheel', this._onWheel, { passive: true });
        this.globalObject.removeEventListener('mousemove', this._onMouseMove);
        this.globalObject.removeEventListener('mouseup', this._onMouseUp);
        this.globalObject.removeEventListener('resize', this._onResize);
        
        this.viewport?.removeEventListener('touchstart', this._onTouchStart);
        this.viewport?.removeEventListener('touchmove', this._onTouchMove);
        this.viewport?.removeEventListener('touchend', this._onTouchEnd);

        this.zoomInButton?.removeEventListener('click', this._onZoomInClick);
        this.zoomOutButton?.removeEventListener('click', this._onZoomOutClick);
        this.resetButton?.removeEventListener('click', this._onResetClick);
        this.navModeSelector?.removeEventListener('click', this._onNavModeClick);
        this.globalObject.removeEventListener('navModeChanged', this._onNavModeChanged);
        this.gizmoCanvas?.removeEventListener('mousedown', this._onGizmoMouseDown);
        this.gizmoCanvas?.removeEventListener('touchstart', this._onGizmoTouchStart);

        if (this.gizmoAnimationFrameId !== null) {
            this.globalObject.cancelAnimationFrame(this.gizmoAnimationFrameId);
            this.gizmoAnimationFrameId = null;
        }

        this.gizmoScene?.traverse((node) => {
            node.geometry?.dispose?.();
            node.material?.dispose?.();
        });
        this.gizmoRenderer?.dispose?.();
        this.gizmoRenderer = null;
        this.gizmoScene = null;
        this.gizmoCamera = null;
        this.isDragging = false;
    }
}

window.WegenaCanvasControls = WegenaCanvasControls;
