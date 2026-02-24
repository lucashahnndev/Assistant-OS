import asyncio
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from browser_use import Agent, Browser
import uuid
import datetime
import os
import json
import re
import inspect
import tempfile
import io
import base64
from urllib.parse import urlparse
from utils.event_bus import global_event_bus
from .base_driver import BaseDriver
from .browser_tab_registry import TabRegistry
from utils.logging_config import get_logger

logger = get_logger("BrowserDriver")

class BrowserDriver(BaseDriver):
    def __init__(self, kernel):
        super().__init__(kernel)
        self.running = False
        self._init_lock = None
        self.playwright_browser = None
        self.page = None
        self.tab_registry = TabRegistry()
        self.max_task_tabs = 5

    def start(self):
        """Starts the browser in a separate thread with its own asyncio loop."""
        self.running = True
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("BrowserDriver started background thread.")

    def send_response(self, text, target=None, is_chunk=False, attachments=None):
        """
        Since BrowserDriver is a control driver, it doesn't directly 
        send text responses to the user, but we implement it to satisfy BaseDriver.
        """
        logger.debug(f"BrowserDriver 'send_response' called with: {text}")

    def send_file(self, target, file_path, caption=None):
        """
        BrowserDriver does not support sending files to a user.
        """
        logger.warning(f"BrowserDriver received request to send file to {target}: {file_path}. Ignoring.")

    def send_status(self, target, phase, payload=None):
        """BrowserDriver does not support visible status yet."""
        pass

    def send_reasoning_chunk(self, target, content):
        """BrowserDriver does not support reasoning chunks."""
        pass

    def send_complete(self, target):
        """BrowserDriver does not support completion events."""
        pass


    def stop(self):
        self.running = False
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._cleanup(), self.loop)
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        # Browser initialization moved to _ensure_browser (lazy loading)
        self.loop.run_forever()

    async def _ensure_browser(self):
        """Ensures the browser is initialized before any task."""
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
            
        async with self._init_lock:
            if self.playwright_browser is None:
                logger.info("Initializing browser on demand (lazy load)...")
                try:
                    await self._setup_browser()
                except Exception as e:
                    logger.warning(f"Initial browser setup failed ({e}). Retrying once after cleanup.")
                    await self._reset_browser_state()
                    self._kill_local_browser_processes()
                    await asyncio.sleep(0.5)
                    await self._setup_browser()
                return

            # browser-use session can be closed internally (e.g., by an agent run).
            # Detect stale clients and recover transparently.
            if not await self._is_browser_usable():
                logger.warning("Detected stale browser client. Reinitializing browser session.")
                await self._reset_browser_state()
                try:
                    await self._setup_browser()
                except Exception as e:
                    logger.warning(f"Browser reinit failed ({e}). Retrying once after cleanup.")
                    self._kill_local_browser_processes()
                    await asyncio.sleep(0.5)
                    await self._setup_browser()

    @staticmethod
    def _kill_local_browser_processes():
        try:
            import subprocess
            for pattern in ["google-chrome", "chrome --type=", "chromium", "chromedriver"]:
                subprocess.run(["pkill", "-f", pattern], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    @staticmethod
    def _is_provider_quota_error(text: str) -> bool:
        lowered = str(text or "").lower()
        markers = (
            "429",
            "free-models-per-day",
            "rate limit exceeded",
            "resource_exhausted",
            "requires more credits",
            "out of credits",
            "prompt tokens limit exceeded",
            "no fallback_llm configured",
        )
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _patch_browser_use_security_watchdog():
        """
        browser-use 0.11.11 may emit TabCreatedEvent with empty URL during bootstrap.
        SecurityWatchdog treats empty URL as disallowed and closes the only tab,
        causing focus/session collapse. Patch URL check to tolerate empty values.
        """
        try:
            from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog
        except Exception:
            return

        if getattr(SecurityWatchdog, "_aosd_empty_url_patch", False):
            return

        original = SecurityWatchdog._is_url_allowed

        def _patched_is_url_allowed(self_wd, url):
            try:
                if url is None:
                    return True
                if isinstance(url, str) and not url.strip():
                    return True
            except Exception:
                return True
            return original(self_wd, url)

        SecurityWatchdog._is_url_allowed = _patched_is_url_allowed
        SecurityWatchdog._aosd_empty_url_patch = True
        logger.info("Applied browser-use SecurityWatchdog empty-url compatibility patch.")

    async def _is_browser_usable(self) -> bool:
        if not self.playwright_browser:
            return False
        try:
            page = await self.playwright_browser.get_current_page()
            if not page:
                return False
            # browser_use wrappers differ across versions. Keep health check tolerant:
            # treat page as usable when it exposes navigable primitives.
            url_attr = getattr(page, "url", None)
            if callable(url_attr):
                _ = url_attr()
            else:
                _ = url_attr
            if not hasattr(page, "goto"):
                return False
            return True
        except Exception as e:
            logger.warning(f"Browser health check failed: {e}")
            return False

    async def _reset_browser_state(self):
        try:
            if self.playwright_browser:
                await self.playwright_browser.close()
        except Exception as e:
            logger.debug(f"Ignoring browser close error during reset: {e}")
        self.playwright_browser = None
        self.page = None
        self.context = None
        self.tab_registry.clear()

    async def _get_current_page(self):
        if not self.playwright_browser:
            return None
        try:
            page = await self.playwright_browser.get_current_page()
            if page:
                self.page = page
                await self._register_page(page, purpose="task")
            return page
        except Exception as e:
            logger.warning(f"Failed to fetch current page: {e}")
            return self.page

    async def _register_page(self, page, purpose: str = "task", device_id: str | None = None):
        if not page:
            return None
        record = self.tab_registry.get_by_page(page)
        if record:
            self.tab_registry.touch(record.tab_id, url=str(getattr(page, "url", "") or ""))
            return record
        tab_id = f"tab_{uuid.uuid4().hex[:8]}"
        record = self.tab_registry.register_tab(
            tab_id=tab_id,
            page_ref=page,
            purpose=purpose,
            status="idle",
            device_id=device_id,
        )
        await self._attach_page_events(page, tab_id)
        return record

    async def _attach_page_events(self, page, tab_id: str):
        close_attr = getattr(page, "on", None)
        if not callable(close_attr):
            return
        try:
            page.on("close", lambda: self.tab_registry.close(tab_id))
            page.on("crash", lambda: self.tab_registry.close(tab_id))
            page.on(
                "framenavigated",
                lambda frame: self.tab_registry.touch(tab_id, url=str(getattr(frame, "url", "") or "")),
            )
        except Exception:
            # wrapper compatibility across browser-use/playwright versions
            pass

    async def _open_new_page(self, purpose: str = "task", device_id: str | None = None):
        current = await self._get_current_page()
        if not current:
            return None
        context = getattr(current, "context", None)
        if not context:
            return current
        try:
            new_page = await context.new_page()
            self.page = new_page
            record = await self._register_page(new_page, purpose=purpose, device_id=device_id)
            if record:
                self.tab_registry.mark_status(record.tab_id, "idle")
            return new_page
        except Exception as e:
            logger.warning(f"Failed to open new page. Reusing current page: {e}")
            return current

    @staticmethod
    def _infer_media_provider(url: str) -> str:
        text = str(url or "").strip()
        if not text:
            return ""
        try:
            host = (urlparse(text).hostname or "").lower()
        except Exception:
            host = text.lower()
        if "youtube.com" in host or "youtu.be" in host or "music.youtube.com" in host:
            return "youtube"
        if "spotify.com" in host:
            return "spotify"
        if "deezer.com" in host:
            return "deezer"
        if "netflix.com" in host:
            return "netflix"
        if host.startswith("www."):
            host = host[4:]
        return host

    def _media_app_mode_enabled(self) -> bool:
        cfg = self.kernel.config_manager.get_skill_config("browser_automator") if self.kernel else {}
        return bool((cfg or {}).get("media_app_mode", False))

    def _replace_media_on_provider_change_enabled(self) -> bool:
        cfg = self.kernel.config_manager.get_skill_config("browser_automator") if self.kernel else {}
        return bool((cfg or {}).get("replace_media_tab_on_provider_change", True))

    async def _open_new_media_window(self, target_url: str | None = None, device_id: str = "default"):
        """
        Best-effort app-like media window.
        """
        current = await self._get_current_page()
        if not current:
            return None
        context = getattr(current, "context", None)
        if not context:
            return await self._open_new_page(purpose="media", device_id=device_id)
        pages_before = list(getattr(context, "pages", []) or [])
        try:
            await current.evaluate(
                """(url) => {
                    const target = url || 'about:blank';
                    window.open(
                        target,
                        '_blank',
                        'popup=yes,width=1280,height=720,menubar=no,toolbar=no,location=no,status=no'
                    );
                    return true;
                }""",
                str(target_url or "about:blank"),
            )
            await asyncio.sleep(0.25)
            pages_after = list(getattr(context, "pages", []) or [])
            new_pages = [p for p in pages_after if p not in pages_before]
            page = new_pages[-1] if new_pages else None
            if not page:
                page = await context.new_page()
                if target_url:
                    await page.goto(target_url)
            self.page = page
            record = await self._register_page(page, purpose="media", device_id=device_id)
            if record:
                self.tab_registry.mark_status(record.tab_id, "idle")
            return page
        except Exception as e:
            logger.debug(f"Could not open popup-style media window: {e}")
            return await self._open_new_page(purpose="media", device_id=device_id)

    async def _sync_tabs_from_context(self):
        page = self.page or await self._get_current_page()
        if not page:
            return
        context = getattr(page, "context", None)
        pages = getattr(context, "pages", None) if context else None
        if not pages:
            return
        for p in pages:
            try:
                is_closed = getattr(p, "is_closed", None)
                if callable(is_closed) and is_closed():
                    rec = self.tab_registry.get_by_page(p)
                    if rec:
                        self.tab_registry.close(rec.tab_id)
                    continue
            except Exception:
                pass
            await self._register_page(p, purpose="task")

    async def _enforce_task_tab_limit(self):
        await self._sync_tabs_from_context()
        open_task_tabs = [r for r in self.tab_registry.list_open() if r.purpose == "task" and not r.pinned]
        if len(open_task_tabs) <= self.max_task_tabs:
            return
        open_task_tabs.sort(key=lambda r: r.last_used_at)
        to_close = open_task_tabs[: max(0, len(open_task_tabs) - self.max_task_tabs)]
        for rec in to_close:
            try:
                await rec.page_ref.close()
            except Exception:
                pass
            self.tab_registry.close(rec.tab_id)

    async def _resolve_media_page(
        self,
        device_id: str = "default",
        force_new: bool = False,
        create_if_missing: bool = True,
        target_url: str | None = None,
    ):
        media_tab = self.tab_registry.get_media_slot(device_id)
        if media_tab and target_url and self._replace_media_on_provider_change_enabled():
            old_provider = self._infer_media_provider(media_tab.last_url)
            new_provider = self._infer_media_provider(target_url)
            if old_provider and new_provider and old_provider != new_provider:
                try:
                    await media_tab.page_ref.close()
                except Exception:
                    pass
                self.tab_registry.close(media_tab.tab_id)
                self.tab_registry.set_media_slot(device_id, None)
                media_tab = None
                force_new = True

        if media_tab and media_tab.status != "closed" and not force_new:
            page = media_tab.page_ref
            self.page = page
            self.tab_registry.mark_status(media_tab.tab_id, "busy")
            return page

        if not create_if_missing and not force_new:
            current = await self._get_current_page()
            if current:
                try:
                    has_media = await current.evaluate(
                        "() => !!document.querySelector('video, audio')"
                    )
                except Exception:
                    has_media = False
                if has_media:
                    record = await self._register_page(current, purpose="media", device_id=device_id)
                    if record:
                        self.tab_registry.set_media_slot(device_id, record.tab_id)
                        self.tab_registry.mark_status(record.tab_id, "busy")
                    return current
            return None

        if self._media_app_mode_enabled():
            page = await self._open_new_media_window(target_url=target_url, device_id=device_id)
        else:
            page = await self._open_new_page(purpose="media", device_id=device_id)
        if not page:
            page = await self._get_current_page()
        record = await self._register_page(page, purpose="media", device_id=device_id)
        if record:
            record.purpose = "media"
            record.device_id = device_id
            self.tab_registry.set_media_slot(device_id, record.tab_id)
            self.tab_registry.mark_status(record.tab_id, "busy")
        return page

    async def _release_media_page(self, device_id: str = "default"):
        media_tab = self.tab_registry.get_media_slot(device_id)
        if media_tab:
            self.tab_registry.mark_status(media_tab.tab_id, "idle")

    def _start_playback_run(self, session_id: str | None, action_id: str, title: str) -> dict | None:
        if not session_id:
            return None
        pb_service = getattr(self.kernel, "playback_service", None) if self.kernel else None
        pb_config = self.kernel.config_manager.get("playback", {}) if self.kernel else {}
        playback_enabled = bool(pb_config.get("enabled", True))
        if not pb_service or not playback_enabled:
            return None

        run_id = f"browser_{uuid.uuid4().hex[:8]}"
        try:
            pb_service.start_run(session_id, run_id, title, {"skill": "browser", "action_id": action_id})
            global_event_bus.emit_threadsafe({
                "type": "playback.start",
                "run_id": run_id,
                "session_id": session_id,
                "title": title,
                "source": {"skill": "browser", "action_id": action_id},
                "mode": "frames",
                "created_at": datetime.datetime.now().isoformat(),
            })
            run_ctx = {
                "run_id": run_id,
                "session_id": session_id,
                "pb_service": pb_service,
                "step": 0,
                "action_id": action_id,
                "ended": False,
            }
            self._maybe_start_playback_sampler(run_ctx, phase="executing")
            return run_ctx
        except Exception as e:
            logger.debug(f"Could not start playback run for {action_id}: {e}")
            return None

    def _resolve_playback_fps(self) -> float:
        """Continuous miniplayer capture rate. Defaults to 3 FPS."""
        fps = 3.0
        try:
            pb_cfg = self.kernel.config_manager.get("playback", {}) if self.kernel else {}
            if isinstance(pb_cfg, dict):
                fps = float(pb_cfg.get("frame_capture_fps", fps))
        except Exception:
            fps = 3.0
        try:
            skill_cfg = self.kernel.config_manager.get_skill_config("browser_automator") if self.kernel else {}
            if isinstance(skill_cfg, dict) and skill_cfg.get("playback_fps") is not None:
                fps = float(skill_cfg.get("playback_fps"))
        except Exception:
            pass
        if fps < 0:
            fps = 0
        return fps

    @staticmethod
    def _normalize_frame_bytes(frame_payload):
        if frame_payload is None:
            return None
        if isinstance(frame_payload, (bytes, bytearray)):
            return bytes(frame_payload)
        if isinstance(frame_payload, memoryview):
            return frame_payload.tobytes()
        if isinstance(frame_payload, str):
            payload = frame_payload.strip()
            if payload.startswith("data:image"):
                try:
                    payload = payload.split(",", 1)[1]
                except Exception:
                    return None
            try:
                return base64.b64decode(payload, validate=False)
            except Exception:
                try:
                    return payload.encode("utf-8")
                except Exception:
                    return None
        return None

    async def _playback_sampler_loop(self, run_ctx: dict, phase: str = "executing"):
        fps = self._resolve_playback_fps()
        if fps <= 0:
            return
        interval = max(0.05, 1.0 / fps)
        try:
            while run_ctx and not run_ctx.get("ended", False):
                await self._emit_playback_frame(run_ctx, "live_sample", target="", phase=phase)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Playback sampler stopped due error: {e}")

    def _maybe_start_playback_sampler(self, run_ctx: dict | None, phase: str = "executing") -> None:
        if not run_ctx:
            return
        if run_ctx.get("sampler_task"):
            return
        fps = self._resolve_playback_fps()
        if fps <= 0:
            return
        try:
            run_ctx["sampler_task"] = asyncio.create_task(self._playback_sampler_loop(run_ctx, phase=phase))
        except Exception as e:
            logger.debug(f"Could not start playback sampler: {e}")

    async def _emit_playback_frame(self, run_ctx: dict | None, action_name: str, target: str = "", phase: str = "executing") -> None:
        if not run_ctx:
            return
        try:
            page = self.page or await self._get_current_page()
            if not page:
                return
            frame_bytes = None
            try:
                frame_bytes = await page.screenshot(type='jpeg', quality=70)
            except Exception:
                frame_bytes = await page.screenshot()
            frame_bytes = self._normalize_frame_bytes(frame_bytes)
            if not frame_bytes:
                logger.warning("Playback frame skipped: empty screenshot payload.")
                return

            run_ctx["step"] = int(run_ctx.get("step", 0)) + 1
            step_num = run_ctx["step"]
            action = {"name": action_name, "target": target}
            pb_service = run_ctx["pb_service"]
            session_id = run_ctx["session_id"]
            run_id = run_ctx["run_id"]
            step_meta = pb_service.add_frame(session_id, run_id, step_num, action, frame_bytes)
            global_event_bus.emit_threadsafe({
                "type": "playback.frame",
                "run_id": run_id,
                "session_id": session_id,
                "step": step_num,
                "phase": phase,
                "action": action,
                "frame": {
                    "url": f"/api/sessions/{session_id}/playback/{run_id}/{step_meta.get('frame_filename', '')}",
                    "filename": step_meta.get("frame_filename"),
                    "sha256": step_meta.get("frame_sha256"),
                    "mime": "image/jpeg",
                    "width": step_meta.get("width", 960),
                    "height": step_meta.get("height", 540),
                    "bytes": step_meta.get("bytes", len(frame_bytes)),
                },
                "ts": datetime.datetime.now().isoformat()
            })
        except Exception as e:
            logger.warning(f"Could not emit playback frame: {e}")

    def _end_playback_run(self, run_ctx: dict | None, status: str = "success") -> None:
        if not run_ctx:
            return
        if run_ctx.get("ended"):
            return
        try:
            sampler_task = run_ctx.get("sampler_task")
            if sampler_task:
                try:
                    sampler_task.cancel()
                except Exception:
                    pass
            pb_service = run_ctx["pb_service"]
            session_id = run_ctx["session_id"]
            run_id = run_ctx["run_id"]
            pb_service.end_run(session_id, run_id, status=status)
            global_event_bus.emit_threadsafe({
                "type": "playback.end",
                "run_id": run_id,
                "session_id": session_id,
                "status": status,
                "total_steps": int(run_ctx.get("step", 0)),
                "ended_at": datetime.datetime.now().isoformat(),
            })
            run_ctx["ended"] = True
        except Exception as e:
            logger.debug(f"Could not end playback run: {e}")

    def _mark_media_verified(self, page=None, source: str = "browser_media_probe"):
        page_ref = page or self.page
        if not page_ref:
            return
        try:
            self.tab_registry.mark_verified_by_page(page_ref, source=source)
        except Exception as e:
            logger.debug(f"Failed to mark media tab as verified: {e}")

    async def _setup_browser(self):
        try:
            import subprocess
            self._patch_browser_use_security_watchdog()
            
            def _get_screen_resolution():
                try:
                    # Try to get resolution using xrandr (Linux)
                    output = subprocess.check_output("xrandr --current | grep '*' | awk '{print $1}'", shell=True).decode().strip()
                    if output:
                        res = output.split('\n')[0] # Take first monitor
                        w, h = map(int, res.split('x'))
                        return w, h
                except Exception as e:
                    logger.debug(f"Could not detection resolution via xrandr: {e}")
                return 1280, 720 # Fallback

            # 1. Load Configuration
            browser_config = self.kernel.config_manager.get_skill_config("browser_automator")
            
            # Handle profilePath env override
            profile_path = browser_config.get('profilePath')
            if not profile_path or "ENV_" in profile_path:
                profile_path = os.getenv("BROWSER_PROFILE_PATH") or browser_config.get('user_data_dir', 'data/browser/profile')
            
            user_data_dir = profile_path
            cdp_url = browser_config.get('cdp_url')
            headless = browser_config.get('headless', False)
            keep_alive = bool(browser_config.get("keep_alive", True))
            viewport_config = browser_config.get('viewport')
            
            # Detect screen resolution
            screen_w, screen_h = _get_screen_resolution()
            
            if viewport_config:
                width = viewport_config.get('width', 1280)
                height = viewport_config.get('height', 720)
            else:
                # Default to 80% of screen size if not specified
                width = int(screen_w * 0.8)
                height = int(screen_h * 0.8)
                logger.info(f"Auto-detected resolution: {screen_w}x{screen_h}. Target window: {width}x{height}")

            viewport = {'width': width, 'height': height}
            screen = {'width': screen_w, 'height': screen_h}
            
            logger.info(f"Browser Resolution Config: Viewport={viewport}, Screen={screen}")
            
            # Prepare Chromium args to enforce physical window size
            extra_args = [
                "--disable-blink-features=AutomationControlled",
                "--autoplay-policy=no-user-gesture-required",
                f"--window-size={width},{height}",
                "--window-position=50,50" # Slight offset from top-left
            ]
            
            # Ensure absolute path for user_data_dir
            if user_data_dir and not user_data_dir.startswith('/'):
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                user_data_dir = os.path.join(base_dir, user_data_dir)
            
            if user_data_dir:
                os.makedirs(user_data_dir, exist_ok=True)
                # Remove stale Chromium singleton locks from previous crashes/runs.
                for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                    lock_path = os.path.join(user_data_dir, lock_name)
                    try:
                        if os.path.exists(lock_path):
                            os.remove(lock_path)
                    except Exception:
                        pass
                logger.info(f"Using persistent browser profile: {user_data_dir}")

            # 2. Initialize browser-use Browser with Native Persistence
            from browser_use.browser.profile import BrowserProfile, ViewportSize
            
            # Convert dicts to ViewportSize objects for BrowserProfile
            v_size = ViewportSize(width=width, height=height)
            s_size = ViewportSize(width=screen_w, height=screen_h)

            if cdp_url:
                logger.info(f"Connecting via CDP: {cdp_url}")
                # For CDP, we can pass it directly to BrowserSession (aliased as Browser)
                self.playwright_browser = Browser(
                    cdp_url=cdp_url,
                    headless=headless,
                    user_data_dir=user_data_dir,
                    viewport=viewport,
                    screen=screen,
                    keep_alive=keep_alive,
                )
                # Ensure the browser is started
                await self.playwright_browser.start()
                
                # Get context/page for legacy commands if needed
                # browser-use manages this via session_manager (alias Browser is BrowserSession)
                self.page = await self.playwright_browser.get_current_page()
                self.context = None # context is not directly exposed as Playwright object anymore
                await self._register_page(self.page, purpose="task")
                
                logger.warning("CDP connected via BrowserSession wrapper.")
            else:
                profile = BrowserProfile(
                    headless=headless,
                    disable_security=True,
                    user_data_dir=user_data_dir,
                    keep_alive=keep_alive,
                    enable_default_extensions=False,
                    extra_chromium_args=extra_args,
                    viewport=v_size,
                    window_size=v_size,
                    screen=s_size,
                    no_viewport=False,
                    device_scale_factor=1.0
                )
                
                self.playwright_browser = Browser(browser_profile=profile)
                
                # Start browser session
                await self.playwright_browser.start()
                
                # Get or create context/page for legacy commands
                self.page = await self.playwright_browser.get_current_page()
                self.context = None
                await self._register_page(self.page, purpose="task")

            logger.info("Humanized Browser Driver initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Humanized Browser: {e}", exc_info=True)
            raise

    def _resolve_browser_use_token_budget(self, provider_name: str, provider_config: dict, vision_max_tokens: int) -> int:
        """
        Resolves an effective browser-use max token budget.
        Policy:
        - If an inherited/kernel-like limit exists, force browser-use below it.
        - Otherwise keep the current bounded token budget.
        """
        inherited_limit = None
        try:
            # "Fake inherited from kernel" (pre-kernel wiring): optional fields in config.
            browser_cfg = self.kernel.config_manager.get_skill_config("browser_automator") if self.kernel else {}
            if isinstance(browser_cfg, dict):
                inherited_limit = browser_cfg.get("inherited_token_limit") or browser_cfg.get("kernel_token_limit")
        except Exception:
            inherited_limit = None

        # Optional fallback path if config evolves before kernel wiring.
        if inherited_limit is None:
            try:
                limits_cfg = self.kernel.config_manager.get("cortex", {}).get("limits", {}) if self.kernel else {}
                inherited_limit = limits_cfg.get("model_max_tokens")
            except Exception:
                inherited_limit = None

        try:
            inherited_limit = int(inherited_limit) if inherited_limit is not None else None
        except Exception:
            inherited_limit = None

        effective = int(vision_max_tokens)
        if inherited_limit and inherited_limit > 64:
            # Force browser-use below inherited cap.
            forced = int(inherited_limit * 0.75)
            forced = min(forced, inherited_limit - 1)
            effective = min(effective, forced)
            logger.info(
                "Applying inherited token cap for browser-use | provider=%s inherited=%s effective=%s",
                provider_name,
                inherited_limit,
                effective,
            )

        return max(64, effective)

    def browser_agent(self, task, session_id=None, device_id: str = "default"):
        """Runs an autonomous task using browser-use Agent."""
        if not self.loop or not self.running:
            return "Browser driver is not running."
        
        # We need to return a future or wait for result.
        # Since this is a worker-based system, we can block or use callbacks.
        # For now, we'll run it in the loop and return a message.
        future = asyncio.run_coroutine_threadsafe(self._browser_agent_task(task, session_id, device_id=device_id), self.loop)
        return future.result() # Expected to run longer than navigation/control ops.

    async def _browser_agent_task(self, task, session_id=None, device_id: str = "default"):
        media_task = self._is_media_playback_task(task)
        dom_only_attempted = False
        dom_playback_ctx = None
        try:
            browser_skill_cfg = self.kernel.config_manager.get_skill_config("browser_automator") if self.kernel else {}
            dom_only_enabled = bool((browser_skill_cfg or {}).get("dom_only_fallback_enabled", True))
            dom_only_force = bool((browser_skill_cfg or {}).get("dom_only_force", False))
            dom_only_strategy = str((browser_skill_cfg or {}).get("dom_only_strategy", "llm")).strip().lower()
            if dom_only_strategy not in {"llm", "deterministic"}:
                dom_only_strategy = "llm"
            # For DOM-only forced media flows, start playback immediately so frontend sees startup.
            if media_task and dom_only_enabled and dom_only_force:
                dom_playback_ctx = self._start_playback_run(
                    session_id,
                    "browser.automator.play_url",
                    "Autoplay Navigation (DOM-only)",
                )

            await self._ensure_browser()
            if dom_playback_ctx:
                await self._emit_playback_frame(dom_playback_ctx, "browser_opened", target="", phase="loading")
            pre_navigated = False
            task_target_url = self._extract_first_url(task)
            if media_task and task_target_url:
                task_target_url = self._normalize_media_autoplay_url(task_target_url)
            if media_task:
                try:
                    page = await self._resolve_media_page(device_id=device_id, target_url=task_target_url)
                except TypeError:
                    # Backward-compat for tests/mocks that still provide the older signature.
                    page = await self._resolve_media_page(device_id=device_id)
                if page and task_target_url:
                    try:
                        current_url = str(getattr(page, "url", "") or "")
                        if not current_url.startswith(task_target_url):
                            await page.goto(task_target_url)
                            pre_navigated = True
                    except Exception as e:
                        logger.debug(f"Pre-navigation failed for media task: {e}")
            else:
                page = await self._get_current_page()
                if page and task_target_url:
                    try:
                        current_url = str(getattr(page, "url", "") or "")
                        if not current_url.startswith(task_target_url):
                            await page.goto(task_target_url)
                            pre_navigated = True
                    except Exception as e:
                        logger.debug(f"Pre-navigation failed for task: {e}")

            # Optional hard switch: skip vision/browser-use and run DOM-only pipeline directly.
            if media_task and dom_only_enabled and dom_only_force:
                logger.info("DOM-only force mode enabled. Skipping browser-use vision agent.")
                dom_only_attempted = True
                dom_result = {"playback_confirmed": False, "message": "DOM-only strategy failed"}
                if dom_only_strategy == "llm":
                    collab_dom = await self._run_collaborative_media_task(task, session_id=session_id, use_vision=False)
                    if collab_dom.get("status") == "success":
                        self._mark_media_verified(source="dom_only_llm")
                        self._end_playback_run(dom_playback_ctx, status="success")
                        await self._enforce_task_tab_limit()
                        return f"Task completed: {collab_dom.get('message')}"
                    self._end_playback_run(dom_playback_ctx, status="failure")
                    await self._enforce_task_tab_limit()
                    return (
                        "FATAL TOOL ERROR while executing task: "
                        f"{collab_dom.get('message') or 'DOM-only LLM did not confirm playback'} "
                        "DO NOT HALLUCINATE SUCCESS."
                    )
                dom_result = await self._run_dom_only_media_fallback(task, session_id=session_id, run_ctx=dom_playback_ctx)
                await self._enforce_task_tab_limit()
                if bool(dom_result.get("playback_confirmed")):
                    self._end_playback_run(dom_playback_ctx, status="success")
                    return f"Task completed: {dom_result.get('message')}"
                self._end_playback_run(dom_playback_ctx, status="failure")
                return (
                    "FATAL TOOL ERROR while executing task: "
                    f"{dom_result.get('message') or 'DOM-only fallback failed'} "
                    "DO NOT HALLUCINATE SUCCESS."
                )
            # Collaborative lightweight path: text LLM controls, vision only observes.
            # For media tasks, this is the first attempt before full browser-use escalation.
            if media_task:
                collaborative = await self._run_collaborative_media_task(task, session_id=session_id)
                if collaborative.get("status") == "success":
                    self._mark_media_verified(source="collaborative_media")
                    return f"Task completed: {collaborative.get('message')}"
                logger.info(
                    "Collaborative media task did not confirm playback (%s). Running one extra local verification pass.",
                    collaborative.get("status"),
                )
                # Keep one extra local deterministic attempt before full-agent escalation.
                try:
                    page = self.page or await self._get_current_page()
                    if page:
                        extra_attempt = await self._attempt_playback_start(page=page, attempts=2, settle_s=0.8)
                        if bool(extra_attempt.get("playback_confirmed")):
                            self._mark_media_verified(page=page, source="deterministic_post_collab")
                            return "Task completed: Playback confirmed after additional local verification."
                except Exception as e:
                    logger.debug(f"Extra local playback verification failed: {e}")
                logger.info(
                    "Collaborative media flow incomplete (blocker=%s). Escalating to full browser-use agent.",
                    str(collaborative.get("blocker") or "playback_not_confirmed"),
                )

            # 1. Setup Playback
            run_id = f"playback_{uuid.uuid4().hex[:8]}"
            pb_service = getattr(self.kernel, "playback_service", None) if self.kernel else None
            pb_config = self.kernel.config_manager.get("playback", {}) if self.kernel else {}
            playback_enabled = pb_config.get("enabled", True)
            run_ctx = None
            
            if session_id and pb_service and playback_enabled:
                pb_service.start_run(session_id, run_id, "Browser Execution", {"skill": "browser", "action_id": "browser.run_task"})
                global_event_bus.emit_threadsafe({
                    "type": "playback.start",
                    "run_id": run_id,
                    "session_id": session_id,
                    "title": "Browser Agent",
                    "source": { "skill": "browser", "action_id": "browser.run_task" },
                    "mode": "frames",
                    "created_at": datetime.datetime.now().isoformat()
                })
                run_ctx = {
                    "run_id": run_id,
                    "session_id": session_id,
                    "pb_service": pb_service,
                    "step": 1,
                    "action_id": "browser.run_task",
                    "ended": False,
                }
                self._maybe_start_playback_sampler(run_ctx, phase="loading")
                # Emit bootstrap/loading frames before the first agent action so UI shows
                # navigation/load context immediately (instead of waiting step callback).
                try:
                    page_boot = self.page or await self._get_current_page()
                    if page_boot:
                        current_target = str(getattr(page_boot, "url", "") or "")
                        frame_boot = await page_boot.screenshot(type='jpeg', quality=70)
                        frame_boot = self._normalize_frame_bytes(frame_boot)
                        if frame_boot:
                            step_meta = pb_service.add_frame(
                                session_id,
                                run_id,
                                0,
                                {"name": "loader_bootstrap", "target": current_target},
                                frame_boot,
                            )
                            global_event_bus.emit_threadsafe({
                                "type": "playback.frame",
                                "run_id": run_id,
                                "session_id": session_id,
                                "step": 0,
                                "phase": "loading",
                                "action": {"name": "loader_bootstrap", "target": current_target},
                                "frame": {
                                    "url": f"/api/sessions/{session_id}/playback/{run_id}/{step_meta['frame_filename']}",
                                    "filename": step_meta['frame_filename'],
                                    "sha256": step_meta['frame_sha256'],
                                    "mime": "image/jpeg",
                                    "width": step_meta['width'],
                                    "height": step_meta['height'],
                                    "bytes": step_meta['bytes']
                                },
                                "ts": datetime.datetime.now().isoformat()
                            })

                        # Small delayed capture often catches intermediate loader/spinner state.
                        await asyncio.sleep(0.35)
                        frame_loader = await page_boot.screenshot(type='jpeg', quality=70)
                        frame_loader = self._normalize_frame_bytes(frame_loader)
                        if frame_loader:
                            step_meta2 = pb_service.add_frame(
                                session_id,
                                run_id,
                                1,
                                {"name": "loader_probe", "target": current_target},
                                frame_loader,
                            )
                            global_event_bus.emit_threadsafe({
                                "type": "playback.frame",
                                "run_id": run_id,
                                "session_id": session_id,
                                "step": 1,
                                "phase": "loading",
                                "action": {"name": "loader_probe", "target": current_target},
                                "frame": {
                                    "url": f"/api/sessions/{session_id}/playback/{run_id}/{step_meta2['frame_filename']}",
                                    "filename": step_meta2['frame_filename'],
                                    "sha256": step_meta2['frame_sha256'],
                                    "mime": "image/jpeg",
                                    "width": step_meta2['width'],
                                    "height": step_meta2['height'],
                                    "bytes": step_meta2['bytes']
                                },
                                "ts": datetime.datetime.now().isoformat()
                            })
                except Exception as e:
                    logger.debug(f"Could not emit initial loader frames: {e}")

            # 2. Get Vision LLM Configuration
            vision_config = self.kernel.config_manager.get_vision_config()
            
            provider_name = vision_config.get('provider', 'google')
            provider_config = vision_config.get('providers', {}).get(provider_name, {})
            
            api_key = provider_config.get('api_key')
            # Fallback to general LLM api key if not specific
            if not api_key:
                llm_config = self.kernel.config_manager.get_llm_config()
                api_key = llm_config.get('providers', {}).get(provider_name, {}).get('api_key')

            model_name = provider_config.get('model', 'gemini-2.0-flash')
            try:
                vision_max_tokens = int(
                    provider_config.get(
                        "vision_max_tokens",
                        provider_config.get("max_tokens", vision_config.get("max_tokens", 512))
                    )
                )
            except Exception:
                vision_max_tokens = 512
            # Keep conservative bounds for browser automation calls on free/low-credit plans.
            vision_max_tokens = max(128, min(vision_max_tokens, 1024))
            vision_max_tokens = self._resolve_browser_use_token_budget(provider_name, provider_config, vision_max_tokens)

            logger.info(
                f"Using vision model '{model_name}' (provider: {provider_name}) "
                f"for browser automation | max_tokens={vision_max_tokens}"
            )
            vision_usable = self._vision_provider_is_usable(provider_name, model_name, api_key)
            if media_task and dom_only_enabled and not vision_usable:
                logger.warning(
                    "Vision provider unavailable (provider=%s, model=%s). Switching to DOM-only fallback.",
                    provider_name,
                    model_name,
                )
                dom_only_attempted = True
                if dom_only_strategy == "llm":
                    collab_dom = await self._run_collaborative_media_task(task, session_id=session_id, use_vision=False)
                    if collab_dom.get("status") == "success":
                        self._mark_media_verified(source="dom_only_llm")
                        await self._enforce_task_tab_limit()
                        return f"Task completed: {collab_dom.get('message')}"
                    await self._enforce_task_tab_limit()
                    return (
                        "FATAL TOOL ERROR while executing task: "
                        f"{collab_dom.get('message') or 'DOM-only LLM did not confirm playback'} "
                        "DO NOT HALLUCINATE SUCCESS."
                    )
                dom_result = await self._run_dom_only_media_fallback(task, session_id=session_id, run_ctx=run_ctx)
                await self._enforce_task_tab_limit()
                if bool(dom_result.get("playback_confirmed")):
                    return f"Task completed: {dom_result.get('message')}"
                return (
                    "FATAL TOOL ERROR while executing task: "
                    f"{dom_result.get('message') or 'DOM-only fallback failed'} "
                    "DO NOT HALLUCINATE SUCCESS."
                )

            # Use native browser-use LLM wrappers
            if provider_name == 'openrouter':
                from drivers.browser_use_openrouter_chat import ChatOpenRouterSystemRole
                instruction_mode = "system_role"
                openrouter_max_retries = 0
                openrouter_timeout_s = None
                try:
                    instruction_mode = str(
                        (browser_skill_cfg or {}).get("openrouter_instruction_mode", "system_role")
                    ).strip().lower()
                    openrouter_max_retries = int((browser_skill_cfg or {}).get("openrouter_max_retries", 0))
                    timeout_val = (browser_skill_cfg or {}).get("openrouter_timeout_s")
                    openrouter_timeout_s = float(timeout_val) if timeout_val is not None else None
                except Exception:
                    instruction_mode = "system_role"
                    openrouter_max_retries = 0
                    openrouter_timeout_s = None

                # Practical default for OpenRouter+Gemma family where system/developer may be rejected.
                if "gemma" in str(model_name).lower() and instruction_mode == "system_role":
                    instruction_mode = "user_only"

                llm = ChatOpenRouterSystemRole(
                    model=model_name,
                    api_key=api_key,
                    extra_body={'max_tokens': vision_max_tokens},
                    instruction_mode=instruction_mode,
                    max_retries=max(0, openrouter_max_retries),
                    timeout=openrouter_timeout_s,
                )
                logger.info(
                    "OpenRouter browser-use params | instruction_mode=%s max_retries=%s timeout=%s",
                    instruction_mode,
                    max(0, openrouter_max_retries),
                    openrouter_timeout_s,
                )
            elif provider_name == 'ollama':
                from browser_use.llm.ollama.chat import ChatOllama
                llm = ChatOllama(
                    model=model_name,
                    base_url=provider_config.get('base_url', 'http://localhost:11434')
                )
            elif provider_name == 'google':
                from browser_use.llm.google.chat import ChatGoogle
                llm = ChatGoogle(
                    model=model_name,
                    api_key=api_key
                )
            else:
                # Default to native OpenAI wrapper
                from browser_use.llm.openai.chat import ChatOpenAI
                llm = ChatOpenAI(
                    model=model_name,
                    api_key=api_key,
                    base_url=provider_config.get('base_url')
                )

            async def step_callback(state):
                if session_id and pb_service and playback_enabled:
                    try:
                        # Capture frame from the active page
                        page = await self.playwright_browser.get_current_page()
                        frame_bytes = await page.screenshot(type='jpeg', quality=70)
                        frame_bytes = self._normalize_frame_bytes(frame_bytes)
                        if not frame_bytes:
                            return
                        
                        # Extract last action from history
                        last_action = {"name": "browser_step", "target": ""}
                        if state.history and state.history[-1].model_output and state.history[-1].model_output.action:
                             # Browser-use AgentState model structure
                             for action in state.history[-1].model_output.action:
                                 last_action = {
                                     "name": action.__class__.__name__.lower(),
                                     "target": str(getattr(action, 'target', ''))
                                 }
                                 break # Just take the first one for simplicity in frame playback

                        # Reserve step 0/1 for pre-action loader frames.
                        step_num = len(state.history) + 2
                        step_meta = pb_service.add_frame(session_id, run_id, step_num, last_action, frame_bytes)
                        
                        global_event_bus.emit_threadsafe({
                            "type": "playback.frame",
                            "run_id": run_id,
                            "session_id": session_id,
                            "step": step_num,
                            "phase": "executing",
                            "action": last_action,
                            "frame": {
                                "url": f"/api/sessions/{session_id}/playback/{run_id}/{step_meta['frame_filename']}",
                                "filename": step_meta['frame_filename'],
                                "sha256": step_meta['frame_sha256'],
                                "mime": "image/jpeg",
                                "width": step_meta['width'],
                                "height": step_meta['height'],
                                "bytes": step_meta['bytes']
                            },
                            "ts": datetime.datetime.now().isoformat()
                        })
                    except Exception as e:
                        logger.error(f"Error in playback step callback: {e}")

            model_lower = str(model_name).lower()
            is_free_or_slow_model = (":free" in model_lower) or ("gemma" in model_lower)
            agent_llm_timeout = int((browser_skill_cfg or {}).get("llm_timeout_s", 90 if is_free_or_slow_model else 45))
            agent_step_timeout = int((browser_skill_cfg or {}).get("step_timeout_s", 150 if is_free_or_slow_model else 90))
            agent_flash_mode = bool((browser_skill_cfg or {}).get("flash_mode", is_free_or_slow_model))
            screenshot_size = tuple((browser_skill_cfg or {}).get("llm_screenshot_size", [640, 360] if is_free_or_slow_model else [768, 432]))
            if len(screenshot_size) != 2:
                screenshot_size = (640, 360) if is_free_or_slow_model else (768, 432)

            agent = Agent(
                task=task,
                llm=llm,
                browser=self.playwright_browser,
                step_callback=step_callback,
                # Reduce prompt footprint for free-tier vision models.
                vision_detail_level="low",
                llm_screenshot_size=(int(screenshot_size[0]), int(screenshot_size[1])),
                max_clickable_elements_length=1800,
                max_actions_per_step=2,
                use_thinking=False,
                message_compaction=True,
                enable_planning=False,
                use_judge=False,
                flash_mode=agent_flash_mode,
                llm_timeout=max(20, agent_llm_timeout),
                step_timeout=max(30, agent_step_timeout),
                directly_open_url=not pre_navigated,
            )
            
            result = await agent.run()
            final_result = result.final_result()
            completed = bool(result.is_done())
            successful = bool(result.is_successful())
            had_errors = bool(result.has_errors())
            error_list = [e for e in (result.errors() or []) if e]
            
            # End playback
            if session_id and pb_service and playback_enabled:
                pb_service.end_run(session_id, run_id, "success" if (completed and successful and final_result) else "failure")
                global_event_bus.emit_threadsafe({
                    "type": "playback.end",
                    "run_id": run_id,
                    "session_id": session_id,
                    "status": "success" if (completed and successful and final_result) else "failure",
                    "total_steps": len(result.history),
                    "ended_at": datetime.datetime.now().isoformat()
                })

            if session_id:
                await self._update_driver_state(session_id)

            if not completed or not successful or not final_result:
                errors_text = " | ".join(str(e) for e in error_list).lower() if error_list else ""
                if self._is_provider_quota_error(errors_text):
                    await self._enforce_task_tab_limit()
                    return (
                        "FATAL TOOL ERROR: provider quota/rate limit reached for browser automation "
                        "(e.g. 429 free-models-per-day). Task aborted early to avoid retries/loops."
                    )
                if media_task and dom_only_enabled and not dom_only_attempted:
                    logger.warning("Browser-use did not complete. Attempting DOM-only fallback before failing.")
                    dom_only_attempted = True
                    dom_only_strategy = str((browser_skill_cfg or {}).get("dom_only_strategy", "llm")).strip().lower()
                    if dom_only_strategy not in {"llm", "deterministic"}:
                        dom_only_strategy = "llm"
                    if dom_only_strategy == "llm":
                        collab_dom = await self._run_collaborative_media_task(task, session_id=session_id, use_vision=False)
                        if collab_dom.get("status") == "success":
                            self._mark_media_verified(source="dom_only_llm")
                            await self._enforce_task_tab_limit()
                            return f"Task completed: {collab_dom.get('message')}"
                        await self._enforce_task_tab_limit()
                        return (
                            "FATAL TOOL ERROR while executing task: "
                            f"{collab_dom.get('message') or 'DOM-only LLM did not confirm playback'} "
                            "DO NOT HALLUCINATE SUCCESS."
                        )
                    dom_result = await self._run_dom_only_media_fallback(task, session_id=session_id, run_ctx=run_ctx)
                    if bool(dom_result.get("playback_confirmed")):
                        await self._enforce_task_tab_limit()
                        return f"Task completed: {dom_result.get('message')}"
                if "timed out" in errors_text or "timeout" in errors_text:
                    await self._enforce_task_tab_limit()
                    return (
                        "FATAL TOOL ERROR: the model exceeded timeout across multiple steps in browser-use. "
                        "Try again with a faster model or after reducing load/quota."
                    )

                failure_reason = (
                    f"completed={completed}, successful={successful}, "
                    f"has_errors={had_errors}, final_result={'present' if final_result else 'empty'}"
                )
                if error_list:
                    failure_reason += f", errors={error_list[:2]}"
                await self._enforce_task_tab_limit()
                return f"FATAL TOOL ERROR while executing task: browser automation incomplete ({failure_reason}). DO NOT HALLUCINATE SUCCESS."

            if media_task:
                post_verify = await self._verify_playback_state()
                if bool(post_verify.get("playback_confirmed")):
                    self._mark_media_verified(source="browser_use_agent")
            await self._enforce_task_tab_limit()
            return f"Task completed: {final_result}"
        except Exception as e:
            logger.error(f"Error in browser_agent task: {e}", exc_info=True)
            error_msg = str(e)
            if self._is_provider_quota_error(error_msg):
                 return (
                     "FATAL TOOL ERROR: provider quota/rate limit exceeded for browser automation (429/credits). "
                     "Task aborted to avoid retry loops."
                 )
            try:
                browser_skill_cfg = self.kernel.config_manager.get_skill_config("browser_automator") if self.kernel else {}
                dom_only_enabled = bool((browser_skill_cfg or {}).get("dom_only_fallback_enabled", True))
                dom_only_strategy = str((browser_skill_cfg or {}).get("dom_only_strategy", "llm")).strip().lower()
                if dom_only_strategy not in {"llm", "deterministic"}:
                    dom_only_strategy = "llm"
                if media_task and dom_only_enabled and not dom_only_attempted:
                    if dom_only_strategy == "llm":
                        collab_dom = await self._run_collaborative_media_task(task, session_id=session_id, use_vision=False)
                        if collab_dom.get("status") == "success":
                            return f"Task completed: {collab_dom.get('message')}"
                        return (
                            "FATAL TOOL ERROR while executing task: "
                            f"{collab_dom.get('message') or 'DOM-only LLM did not confirm playback'} "
                            "DO NOT HALLUCINATE SUCCESS."
                        )
                    dom_result = await self._run_dom_only_media_fallback(task, session_id=session_id, run_ctx=None)
                    if bool(dom_result.get("playback_confirmed")):
                        return f"Task completed: {dom_result.get('message')}"
            except Exception as dom_e:
                logger.debug(f"DOM-only fallback on exception failed: {dom_e}")

            # Help user debug vision errors
            if "image input" in error_msg.lower() or "404" in error_msg:
                 return (f"FATAL TOOL ERROR: Model '{model_name}' failed (Error 404 or missing vision). "
                         "DO NOT CLAIM SUCCESS. Inform the user that the navigation model is misconfigured "
                         "no config.json (interfaces.browser.model must be a vision-capable model such as google/gemini-flash-1.5).")
            
            return f"FATAL TOOL ERROR while executing task: {error_msg}. DO NOT HALLUCINATE SUCCESS."
        finally:
            if dom_playback_ctx:
                self._end_playback_run(dom_playback_ctx, status="failure")
            if media_task:
                await self._release_media_page(device_id=device_id)

    async def _update_driver_state(self, session_id):
        """Updates the session with the current browser state (active pages)."""
        if not session_id or not self.playwright_browser:
            return
            
        try:
            pages_info = []
            # browser-use 0.11.x: BrowserSession doesn't expose playwright_browser directly
            # Use get_current_page() to access the active page and its context
            try:
                current_page = await self.playwright_browser.get_current_page()
                current_page_open = False
                if current_page:
                    is_closed_attr = getattr(current_page, "is_closed", None)
                    if callable(is_closed_attr):
                        try:
                            current_page_open = not is_closed_attr()
                        except Exception:
                            current_page_open = True
                    else:
                        current_page_open = True
                if current_page and current_page_open:
                    # Get all pages from the current page's context
                    context = current_page.context
                    for page in context.pages:
                        try:
                            page_open = True
                            page_is_closed = getattr(page, "is_closed", None)
                            if callable(page_is_closed):
                                try:
                                    page_open = not page_is_closed()
                                except Exception:
                                    page_open = True
                            if page_open:
                                title = await page.title()
                                url = page.url
                                pages_info.append({
                                    "title": title,
                                    "url": url,
                                    "active": page == current_page
                                })
                        except:
                            continue
            except Exception as e:
                logger.debug(f"Could not enumerate browser pages: {e}")

            # Update session
            kernel = self.kernel
            session = None
            if kernel and hasattr(kernel, "orchestrator"):
                session = kernel.orchestrator.sessions.get(session_id)
            elif kernel and hasattr(kernel, "sessions"):
                # Legacy fallback
                session = kernel.sessions.get(session_id)

            if session:
                if "browser" not in session.drivers_state:
                    session.drivers_state["browser"] = {}
                session.drivers_state["browser"]["active_pages"] = pages_info
                session.drivers_state["browser"]["media_slots"] = self.tab_registry.snapshot_media_slots()
                logger.debug(f"Synced browser state for session {session_id}: {len(pages_info)} pages.")
                # IMPORTANT: do not persist here.
                # Browser actions are usually executed while orchestrator holds the session lock.
                # Persisting from this thread can deadlock waiting for that same lock.
                # The orchestrator persists state at the end of the action loop.
        except Exception as e:
            logger.error(f"Error syncing browser state: {e}")

    async def _cleanup(self):
        await self._reset_browser_state()
        self.loop.stop()

    def navigate(self, url, session_id=None, purpose: str = "task", device_id: str = "default"):
        """Navigates to a specific URL and waits for completion."""
        if not self.loop or not self.running:
            return "Error: Browser driver not running."
        future = asyncio.run_coroutine_threadsafe(
            self._navigate_task(url, session_id, purpose=purpose, device_id=device_id),
            self.loop,
        )
        try:
            return future.result(timeout=45)
        except FutureTimeoutError:
            future.cancel()
            logger.error(f"Navigation timeout for URL: {url}")
            return f"Error navigating to {url}: operation timed out."

    async def _navigate_task(self, url, session_id=None, purpose: str = "task", device_id: str = "default"):
        run_ctx = self._start_playback_run(session_id, "browser.automator.open", "Browser Navigation")
        try:
            await self._ensure_browser()
            page = (
                await self._resolve_media_page(device_id=device_id, target_url=url)
                if purpose == "media"
                else await self._get_current_page()
            )
            if not page:
                self._end_playback_run(run_ctx, status="failure")
                return "Error: Browser page not initialized properly."
            
            await self._emit_playback_frame(run_ctx, "before_navigate", target=url, phase="executing")
            await page.goto(url)
            self.page = page
            logger.info(f"Successfully navigated to: {url}")
            await self._emit_playback_frame(run_ctx, "after_navigate", target=url, phase="executing")
            rec = self.tab_registry.get_by_page(page)
            if rec:
                rec.purpose = purpose
                rec.device_id = device_id if purpose == "media" else rec.device_id
                self.tab_registry.touch(rec.tab_id, url=url)
                if purpose == "media":
                    self.tab_registry.set_media_slot(device_id, rec.tab_id)
            
            if session_id:
                await self._update_driver_state(session_id)
            await self._enforce_task_tab_limit()
            if purpose == "media":
                await self._release_media_page(device_id=device_id)
            self._end_playback_run(run_ctx, status="success")
            return f"Navigated to {url}"
        except Exception as e:
            logger.error(f"Navigation error: {e}")
            self._end_playback_run(run_ctx, status="failure")
            return f"Error navigating to {url}: {str(e)}"

    def play_youtube(self, query, session_id=None):
        """High level command to search and play a video."""
        asyncio.run_coroutine_threadsafe(self._play_youtube_task(query, session_id), self.loop)

    async def _play_youtube_task(self, query, session_id=None):
        try:
            await self._ensure_browser()
            if not self.page:
                logger.error("Browser page not initialized.")
                return

            search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            await self.page.goto(search_url)
            
            # Use evaluate for legacy support as Page actor doesn't have wait_for_selector/click
            # This is more robust for browser-use 1.10.x
            await asyncio.sleep(2) # Give it a moment to load
            await self.page.evaluate('() => document.querySelector("ytd-video-renderer a#video-title")?.click()')
            
            logger.info(f"Playing YouTube video for: {query}")
            if session_id:
                await self._update_driver_state(session_id)
            await self._enforce_task_tab_limit()
        except Exception as e:
            logger.error(f"Error in play_youtube task: {e}")

    def control_media(self, action, session_id=None, device_id: str = "default"):
        """Actions: play, pause, next, mute, etc."""
        if not self.loop or not self.running:
            return {
                "ok": False,
                "status": "error",
                "action": action,
                "message": "Browser driver not running.",
                "playback_confirmed": False,
            }
        future = asyncio.run_coroutine_threadsafe(
            self._control_media_task(action, session_id, device_id=device_id),
            self.loop,
        )
        try:
            return future.result(timeout=25)
        except FutureTimeoutError:
            future.cancel()
            logger.error(f"Media control timeout for action: {action}")
            return {
                "ok": False,
                "status": "error",
                "action": action,
                "message": f"Media control timeout for action: {action}",
                "playback_confirmed": False,
            }

    async def _wait_for_page_ready(self, page=None, timeout_s: float = 10.0) -> bool:
        page = page or self.page or await self._get_current_page()
        if not page:
            return False
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            try:
                ready = await page.evaluate(
                    """() => {
                        const state = document.readyState;
                        const hasBody = !!document.body;
                        const visible = hasBody && document.visibilityState !== 'hidden';
                        return { ready: state, hasBody, visible };
                    }"""
                )
                if ready and ready.get("hasBody") and ready.get("visible") and ready.get("ready") in {"interactive", "complete"}:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.25)
        return False

    async def _resolve_page_mouse(self, page):
        """Resolves mouse handle across different page wrappers."""
        if not page:
            return None
        try:
            attr = getattr(page, "mouse", None)
        except Exception:
            return None
        if attr is None:
            return None
        try:
            if inspect.isawaitable(attr):
                return await attr
            if callable(attr):
                out = attr()
                if inspect.isawaitable(out):
                    return await out
                return out
            return attr
        except Exception:
            return None

    async def _probe_media_state(self, page=None) -> dict:
        page = page or self.page or await self._get_current_page()
        if not page:
            return {"has_media": False, "playing": False, "current_time": 0.0, "yt_player_state": None}
        try:
            return await page.evaluate(
                """() => {
                    const items = Array.from(document.querySelectorAll('video, audio'));
                    let ytPlayerState = null;
                    try {
                        const yt = document.querySelector('#movie_player');
                        if (yt && typeof yt.getPlayerState === 'function') {
                            ytPlayerState = Number(yt.getPlayerState());
                        }
                    } catch (_) {}
                    if (!items.length) {
                        return { has_media: false, playing: false, current_time: 0, yt_player_state: ytPlayerState };
                    }
                    let best = null;
                    for (const media of items) {
                        const state = {
                            playing: !media.paused && !media.ended,
                            current_time: Number(media.currentTime || 0),
                        };
                        if (!best) {
                            best = state;
                            continue;
                        }
                        if (state.playing && !best.playing) {
                            best = state;
                            continue;
                        }
                        if (state.current_time > best.current_time) {
                            best = state;
                        }
                    }
                    return {
                        has_media: true,
                        playing: !!best.playing,
                        current_time: Number(best.current_time || 0),
                        yt_player_state: ytPlayerState,
                    };
                }"""
            )
        except Exception:
            return {"has_media": False, "playing": False, "current_time": 0.0, "yt_player_state": None}

    @staticmethod
    def _normalize_media_state(state: object) -> dict:
        if isinstance(state, dict):
            state.setdefault("yt_player_state", None)
            return state
        if isinstance(state, str):
            text = state.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        parsed.setdefault("yt_player_state", None)
                        return parsed
                except Exception:
                    pass
        return {"has_media": False, "playing": False, "current_time": 0.0, "yt_player_state": None}

    async def _probe_system_audio_activity(self) -> bool | None:
        """
        Optional secondary signal from host system.
        This must not be treated as primary source of truth because support is OS/driver dependent.
        """
        system_driver = getattr(self.kernel, "system_driver", None) if self.kernel else None
        if not system_driver:
            return None
        try:
            if hasattr(system_driver, "is_audio_output_active"):
                return bool(system_driver.is_audio_output_active())
            if hasattr(system_driver, "is_audio_playing"):
                return bool(system_driver.is_audio_playing())
        except Exception as e:
            logger.debug(f"System audio probe unavailable: {e}")
        return None

    async def _verify_playback_state(self, page=None, sample_gap_s: float = 0.6) -> dict:
        page = page or self.page or await self._get_current_page()
        first = self._normalize_media_state(await self._probe_media_state(page=page))
        await asyncio.sleep(max(0.1, sample_gap_s))
        second = self._normalize_media_state(await self._probe_media_state(page=page))
        dt = float(second.get("current_time", 0.0)) - float(first.get("current_time", 0.0))
        time_progress = dt > 0.05
        browser_playing = bool(second.get("playing"))
        yt_state = second.get("yt_player_state")
        yt_playing = yt_state == 1
        confirmed = browser_playing or time_progress or yt_playing
        system_audio_active = await self._probe_system_audio_activity()
        return {
            "playback_confirmed": confirmed,
            "state": second,
            "verification": {
                "source": "browser_media_probe",
                "browser_playing": browser_playing,
                "yt_playing": yt_playing,
                "yt_player_state": yt_state,
                "time_progress": time_progress,
                "delta_current_time": round(dt, 4),
                "system_audio_active": system_audio_active,
            },
        }

    async def _send_page_play_signal(self, page=None) -> None:
        page = page or self.page or await self._get_current_page()
        if not page:
            return
        # Try center clicks on the main media viewport (trusted pointer events).
        try:
            rect = await page.evaluate(
                """() => {
                    const el = document.querySelector('video, #movie_player, .html5-video-player');
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    if (!r || !r.width || !r.height) return null;
                    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
                }"""
            )
            if isinstance(rect, dict) and "x" in rect and "y" in rect:
                mouse = await self._resolve_page_mouse(page)
                if mouse:
                    await mouse.click(float(rect["x"]), float(rect["y"]))
                    await asyncio.sleep(0.12)
                    await mouse.click(float(rect["x"]), float(rect["y"]))
        except Exception:
            pass
        # Trusted clicks first (players often ignore synthetic JS events for autoplay).
        click_targets = [
            ".ytp-large-play-button",
            ".ytp-play-button",
            "#movie_player .ytp-play-button",
            "button[data-testid='play_button_track']",
            "button[data-testid='play_button']",
            "button[data-testid*='play']",
            "button[aria-label*='Play']",
            "button[aria-label*='Reproduzir']",
            "button[aria-label*='Tocar']",
            "button[title*='Play']",
            "button[title*='Reproduzir']",
            "button[title*='Tocar']",
            "video",
        ]
        for selector in click_targets:
            try:
                await page.click(selector, timeout=900)
                break
            except Exception:
                continue
        # Prefer trusted key events through Playwright before JS-dispatched events.
        try:
            await page.bring_to_front()
        except Exception:
            pass
        try:
            await page.click("body", timeout=1200)
        except Exception:
            pass
        try:
            keyboard = getattr(page, "keyboard", None)
            if keyboard:
                await keyboard.press("Space")
                await keyboard.press("MediaPlayPause")
                await keyboard.press("k")  # YouTube fallback
        except Exception:
            pass
        await page.evaluate(
            """() => {
                const clickVisible = (selectors) => {
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (!el) continue;
                        const style = window.getComputedStyle(el);
                        const visible = style && style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
                        if (!visible) continue;
                        el.click();
                        return true;
                    }
                    return false;
                };

                // Consent/cookie quick pass.
                const consentButtons = Array.from(document.querySelectorAll('button, tp-yt-paper-button'));
                for (const btn of consentButtons) {
                    const t = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                    if (!t) continue;
                    if (
                        t.includes('accept') ||
                        t.includes('aceitar') ||
                        t.includes('agree') ||
                        t.includes('concord') ||
                        t.includes('ok')
                    ) {
                        btn.click();
                        break;
                    }
                }

                clickVisible([
                    '.ytp-play-button',
                    '[data-testid="play_button_track"]',
                    'button[data-testid*="play"]',
                    'button[aria-label*="Play"]',
                    'button[aria-label*="Reproduzir"]',
                    'button[title*="Play"]',
                    'button[title*="Reproduzir"]'
                ]);

                // Standard media key gesture at page level (not OS-level).
                const target = document.activeElement || document.body || document.documentElement;
                const down = new KeyboardEvent('keydown', { key: ' ', code: 'Space', keyCode: 32, which: 32, bubbles: true, cancelable: true });
                const up = new KeyboardEvent('keyup', { key: ' ', code: 'Space', keyCode: 32, which: 32, bubbles: true, cancelable: true });
                target.dispatchEvent(down);
                target.dispatchEvent(up);
                document.dispatchEvent(down);
                document.dispatchEvent(up);

                const media = document.querySelector('video, audio');
                if (media && media.paused && typeof media.play === 'function') {
                    try {
                        media.muted = false;
                        media.play();
                    } catch (_) {}
                }
                const yt = document.querySelector('#movie_player');
                if (yt && typeof yt.playVideo === 'function') {
                    try {
                        if (typeof yt.unMute === 'function') yt.unMute();
                        yt.playVideo();
                    } catch (_) {}
                }
            }"""
        )

    async def _attempt_playback_start(self, page=None, attempts: int = 3, settle_s: float = 1.0) -> dict:
        page = page or self.page or await self._get_current_page()
        last_state = {"has_media": False, "playing": False, "current_time": 0.0}
        last_verification = {
            "source": "browser_media_probe",
            "browser_playing": False,
            "time_progress": False,
            "delta_current_time": 0.0,
            "system_audio_active": None,
        }
        for _ in range(max(1, attempts)):
            await self._send_page_play_signal(page=page)
            await asyncio.sleep(settle_s)
            verification = await self._verify_playback_state(page=page, sample_gap_s=0.6)
            second = self._normalize_media_state(verification.get("state", {}))
            last_state = second
            last_verification = verification.get("verification", last_verification)
            if bool(verification.get("playback_confirmed")):
                return {
                    "playback_confirmed": True,
                    "state": second,
                    "verification": verification.get("verification"),
                }

        return {
            "playback_confirmed": False,
            "state": last_state,
            "verification": last_verification,
        }

    async def _control_media_task(self, action, session_id=None, device_id: str = "default"):
        run_ctx = self._start_playback_run(session_id, "browser.automator.control", f"Media Control ({action})")
        try:
            await self._ensure_browser()
            create_if_missing = action in {"play", "click"}
            page = await self._resolve_media_page(
                device_id=device_id,
                create_if_missing=create_if_missing,
            )
            if not page:
                self._end_playback_run(run_ctx, status="failure")
                return {
                    "ok": False,
                    "status": "error",
                    "action": action,
                    "message": "No media tab available for this device.",
                    "playback_confirmed": False,
                }
            await self._emit_playback_frame(run_ctx, "control_start", target=action, phase="executing")
            
            worked = False
            playback_confirmed = None
            details = {}
            verification = None
            if action == 'pause':
                 result = await page.evaluate(
                    """() => {
                        const media = document.querySelector('video, audio');
                        if (!media) return false;
                        if (!media.paused) media.pause();
                        return media.paused === true;
                    }"""
                 )
                 worked = bool(result)
                 playback_confirmed = False
                 if worked:
                     self._mark_media_verified(page=page, source="deterministic_pause")
            elif action == 'play':
                 await self._wait_for_page_ready(page=page, timeout_s=8.0)
                 try:
                     await page.bring_to_front()
                     await page.keyboard.press("Space")
                 except Exception:
                     pass
                 play_attempt = await self._attempt_playback_start(page=page, attempts=3, settle_s=0.9)
                 playback_confirmed = bool(play_attempt.get("playback_confirmed"))
                 details = play_attempt.get("state", {})
                 verification = play_attempt.get("verification")
                 worked = playback_confirmed
                 if worked:
                     self._mark_media_verified(page=page, source="deterministic_play")
            elif action == 'next':
                 result = await page.evaluate(
                    """() => {
                        const clickVisible = (selectors) => {
                            for (const sel of selectors) {
                                const el = document.querySelector(sel);
                                if (!el) continue;
                                const style = window.getComputedStyle(el);
                                const visible = style && style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
                                if (!visible) continue;
                                el.click();
                                return true;
                            }
                            return false;
                        };
                        return clickVisible([
                            'button[aria-label*="Next"]',
                            'button[aria-label*="Próxima"]',
                            'button[aria-label*="Proxima"]',
                            'button[data-testid*="next"]'
                        ]);
                    }"""
                 )
                 worked = bool(result)
            elif action == 'fullscreen':
                 result = await page.evaluate(
                    """() => {
                        const video = document.querySelector('video');
                        if (!video) return false;
                        try {
                            if (document.fullscreenElement) return true;
                            if (video.requestFullscreen) {
                                video.requestFullscreen();
                                return true;
                            }
                        } catch (_) {}
                        return false;
                    }"""
                 )
                 worked = bool(result)
            elif action == 'mute':
                 result = await page.evaluate(
                    """() => {
                        const media = document.querySelector('video, audio');
                        if (!media) return false;
                        media.muted = !media.muted;
                        return true;
                    }"""
                 )
                 worked = bool(result)
            elif action == 'click':
                 await page.evaluate('() => document.body.click()')
                 worked = True
            elif action == 'status':
                 status_probe = await self._verify_playback_state(page=page, sample_gap_s=0.4)
                 details = self._normalize_media_state(status_probe.get("state", {}))
                 worked = True
                 playback_confirmed = bool(status_probe.get("playback_confirmed"))
                 verification = status_probe.get("verification")
                 if playback_confirmed:
                     self._mark_media_verified(page=page, source="status_probe")
            
            if worked:
                logger.info(f"Browser media control: {action}")
                if session_id:
                    await self._update_driver_state(session_id)
                await self._emit_playback_frame(run_ctx, "control_success", target=action, phase="executing")
                self._end_playback_run(run_ctx, status="success")
                return {
                    "ok": True,
                    "status": "success",
                    "action": action,
                    "message": f"Browser media control '{action}' executed successfully.",
                    "playback_confirmed": bool(playback_confirmed) if playback_confirmed is not None else None,
                    "details": details,
                    "verification": verification,
                }
            else:
                if action == "play":
                    state = details or await self._probe_media_state(page=page)
                    state = self._normalize_media_state(state)
                    await self._emit_playback_frame(run_ctx, "control_partial", target=action, phase="executing")
                    self._end_playback_run(run_ctx, status="failure")
                    return {
                        "ok": True,
                        "status": "partial",
                        "action": action,
                        "message": "Play signal sent, but playback could not be confirmed.",
                        "playback_confirmed": False,
                        "blocker": "playback_not_confirmed",
                        "details": state,
                        "verification": verification,
                    }
                logger.warning(f"Browser media control action '{action}' is not supported.")
                self._end_playback_run(run_ctx, status="failure")
                return {
                    "ok": False,
                    "status": "error",
                    "action": action,
                    "message": f"Browser media control failed for action '{action}'.",
                    "playback_confirmed": False,
                }
        except Exception as e:
            logger.error(f"Error in browser media control: {e}")
            self._end_playback_run(run_ctx, status="failure")
            return {
                "ok": False,
                "status": "error",
                "action": action,
                "message": f"Error in browser media control: {str(e)}",
                "playback_confirmed": False,
            }
        finally:
            await self._release_media_page(device_id=device_id)

    def navigate_with_autoplay(self, url, session_id=None, device_id: str = "default", force_new_media_tab: bool = False):
        """Navigates to a URL and tries to ensure video starts playing."""
        if not self.loop or not self.running:
            return "Error: Browser driver not running."
        future = asyncio.run_coroutine_threadsafe(
            self._navigate_autoplay_task(
                url,
                session_id,
                device_id=device_id,
                force_new_media_tab=force_new_media_tab,
            ),
            self.loop,
        )
        try:
            return future.result(timeout=60)
        except FutureTimeoutError:
            future.cancel()
            logger.error(f"Autoplay navigation timeout for URL: {url}")
            return f"Error navigating to {url}: autoplay operation timed out."

    async def _navigate_autoplay_task(self, url, session_id=None, device_id: str = "default", force_new_media_tab: bool = False):
        run_ctx = self._start_playback_run(session_id, "browser.automator.play_url", "Autoplay Navigation")
        try:
            await self._ensure_browser()
            url = self._normalize_media_autoplay_url(url)
            page = await self._resolve_media_page(
                device_id=device_id,
                force_new=force_new_media_tab,
                target_url=url,
            )
            if not page:
                self._end_playback_run(run_ctx, status="failure")
                return "Error: Browser page not initialized properly."
            
            await self._emit_playback_frame(run_ctx, "before_autoplay_navigate", target=url, phase="executing")
            await page.goto(url)
            self.page = page
            logger.info(f"Navigated to {url} with autoplay intent.")
            await self._emit_playback_frame(run_ctx, "after_autoplay_navigate", target=url, phase="executing")
            await self._wait_for_page_ready(page=page, timeout_s=10.0)
            try:
                await page.wait_for_selector("video, audio", timeout=8000)
            except Exception:
                pass
            try:
                await page.bring_to_front()
                await page.keyboard.press("Space")
            except Exception:
                pass
            play_attempt = await self._attempt_playback_start(page=page, attempts=4, settle_s=1.0)
            playback_confirmed = bool(play_attempt.get("playback_confirmed"))
            probe_state = self._normalize_media_state(play_attempt.get("state", {}))
            verification = play_attempt.get("verification")

            media_record = self.tab_registry.get_by_page(page)
            if media_record:
                media_record.purpose = "media"
                media_record.device_id = device_id
                self.tab_registry.set_media_slot(device_id, media_record.tab_id)
                self.tab_registry.touch(media_record.tab_id, url=url)

            if session_id:
                await self._update_driver_state(session_id)

            if playback_confirmed:
                self._mark_media_verified(page=page, source="deterministic_autoplay")
                await self._emit_playback_frame(run_ctx, "autoplay_confirmed", target=url, phase="executing")
                self._end_playback_run(run_ctx, status="success")
                return {
                    "ok": True,
                    "status": "success",
                    "url": url,
                    "playback_confirmed": True,
                    "message": f"Opened '{url}' and confirmed playback.",
                    "details": probe_state,
                    "verification": verification,
                }

            return {
                "ok": True,
                "status": "partial",
                "url": url,
                "playback_confirmed": False,
                "blocker": "playback_not_confirmed",
                "message": f"Opened '{url}', but playback could not be confirmed automatically.",
                "details": probe_state,
                "verification": verification,
            }
        except Exception as e:
            logger.error(f"Autoplay navigation error: {e}")
            self._end_playback_run(run_ctx, status="failure")
            return f"Error navigating to {url}: {str(e)}"
        finally:
            if run_ctx:
                # if not already closed on success, close as failure for partial/no-confirmation.
                self._end_playback_run(run_ctx, status="failure")
            await self._release_media_page(device_id=device_id)

    @staticmethod
    def _extract_first_json_object(value: object) -> dict | None:
        if isinstance(value, dict):
            return value
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(text[idx:])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
        return None

    @staticmethod
    def _compact_dom_objective(task: str, max_chars: int = 240) -> str:
        """Creates a short DOM target objective, intentionally detached from session context."""
        text = " ".join(str(task or "").strip().split())
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    @staticmethod
    def _compact_dom_snapshot(media_state: dict, observer_parsed: dict) -> dict:
        return {
            "media_state": {
                "has_media": bool((media_state or {}).get("has_media", False)),
                "playing": bool((media_state or {}).get("playing", False)),
                "current_time": float((media_state or {}).get("current_time", 0.0)),
                "yt_player_state": (media_state or {}).get("yt_player_state"),
            },
            "observer": {
                "state": str((observer_parsed or {}).get("state", ""))[:120],
                "next_hint": str((observer_parsed or {}).get("next_hint", ""))[:40],
                "play_selector": str((observer_parsed or {}).get("play_selector", ""))[:120],
                "cookie_selector": str((observer_parsed or {}).get("cookie_selector", ""))[:120],
                "blocker": str((observer_parsed or {}).get("blocker", ""))[:120],
                "title": str((observer_parsed or {}).get("title", ""))[:120],
                "url": str((observer_parsed or {}).get("url", ""))[:180],
                "buttons_preview": (observer_parsed or {}).get("buttons_preview", [])[:6],
                "media_paused": (observer_parsed or {}).get("media_paused"),
                "candidates": (observer_parsed or {}).get("candidates", [])[:10],
            },
        }

    @staticmethod
    def _is_media_playback_task(task: str) -> bool:
        text = (task or "").lower()
        if not text:
            return False
        playback_cues = ("play", "reproduz", "reproduzir", "toca", "tocar", "ouvir")
        media_cues = ("youtube", "yt", "music", "deezer", "spotify", "música", "musica")
        return any(cue in text for cue in playback_cues) and any(cue in text for cue in media_cues)

    @staticmethod
    def _extract_first_url(text: str) -> str:
        content = str(text or "")
        match = re.search(r"https?://[^\s'\"<>]+", content)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _with_query_param(url: str, key: str, value: str) -> str:
        if not url:
            return url
        needle = f"{key}="
        if needle in url:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{key}={value}"

    @classmethod
    def _normalize_media_autoplay_url(cls, url: str) -> str:
        text = str(url or "").strip()
        if not text:
            return text
        lowered = text.lower()
        if "youtube.com/" in lowered or "youtu.be/" in lowered or "music.youtube.com/" in lowered:
            text = cls._with_query_param(text, "autoplay", "1")
        return text

    @staticmethod
    def _is_unresolved_secret(value: object) -> bool:
        text = str(value or "").strip()
        return (not text) or text.startswith("ENV_")

    def _vision_provider_is_usable(self, provider_name: str, model_name: str, api_key: object) -> bool:
        if not str(model_name or "").strip():
            return False
        provider = str(provider_name or "").strip().lower()
        # Local providers may not require keys.
        if provider in {"ollama"}:
            return True
        return not self._is_unresolved_secret(api_key)

    async def _run_dom_only_media_fallback(self, task: str, session_id: str | None = None, run_ctx: dict | None = None) -> dict:
        """
        Deterministic fallback that avoids vision calls.
        Intended for cases where vision model is unavailable/failing.
        """
        await self._ensure_browser()
        page = self.page or await self._get_current_page()
        if not page:
            target_url = self._normalize_media_autoplay_url(self._extract_first_url(task))
            if target_url:
                try:
                    page = await self._resolve_media_page(device_id="default", target_url=target_url)
                    if page:
                        await page.goto(target_url)
                        self.page = page
                except Exception as e:
                    logger.debug(f"DOM-only fallback could not reopen target URL: {e}")
        if not page:
            # Last retry after potential reset from browser-use failure.
            try:
                await self._reset_browser_state()
                await self._ensure_browser()
                page = self.page or await self._get_current_page()
            except Exception:
                page = None
        if not page:
            return {
                "ok": False,
                "status": "error",
                "message": "No active page for DOM-only fallback.",
                "playback_confirmed": False,
                "blocker": "no_active_page",
            }

        target_url = self._normalize_media_autoplay_url(self._extract_first_url(task))
        if target_url:
            try:
                current_url = str(getattr(page, "url", "") or "")
                if not current_url.startswith(target_url):
                    await page.goto(target_url)
                    self.page = page
            except Exception as e:
                logger.debug(f"DOM-only fallback target navigation failed: {e}")

        await self._wait_for_page_ready(page=page, timeout_s=10.0)
        try:
            await page.wait_for_selector("video, audio", timeout=8000)
        except Exception:
            pass

        async def _click_first_visible(selectors: list[str]) -> str:
            try:
                clicked = await page.evaluate(
                    """(selectors) => {
                        const isVisible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            if (!style) return false;
                            if (style.display === 'none' || style.visibility === 'hidden') return false;
                            const rect = el.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0;
                        };
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (!isVisible(el)) continue;
                            el.click();
                            return sel;
                        }
                        return '';
                    }""",
                    selectors,
                )
                return str(clicked or "")
            except Exception:
                return ""

        for idx in range(1, 7):
            if run_ctx:
                await self._emit_playback_frame(run_ctx, "dom_only_before", target=f"attempt_{idx}", phase="loading")

            # Explicit consent and play selectors before generic signals.
            await _click_first_visible(
                [
                    "button[aria-label*='Aceitar']",
                    "button[aria-label*='Accept']",
                    "button[title*='Aceitar']",
                    "button[title*='Accept']",
                    "button.fc-cta-consent",
                    "button#L2AGLb",
                ]
            )
            await _click_first_visible(
                [
                    ".ytp-play-button",
                    "#movie_player .ytp-play-button",
                    "button[data-testid*='play']",
                    "button[aria-label*='Play']",
                    "button[aria-label*='Reproduzir']",
                    "button[title*='Play']",
                    "button[title*='Reproduzir']",
                    "[data-testid='play_button_track']",
                    "button[data-testid='play_button']",
                    "button[aria-label*='Tocar']",
                    "button[title*='Tocar']",
                ]
            )

            try:
                await self._send_page_play_signal(page=page)
            except Exception as e:
                # Common after browser-use failure: page client got reset.
                if "Client is not started" in str(e):
                    try:
                        await self._reset_browser_state()
                        await self._ensure_browser()
                        page = self.page or await self._get_current_page()
                        target_url = self._normalize_media_autoplay_url(self._extract_first_url(task))
                        if page and target_url:
                            await page.goto(target_url)
                        if page:
                            await self._send_page_play_signal(page=page)
                    except Exception as retry_e:
                        logger.debug(f"DOM-only fallback recovery after client reset failed: {retry_e}")
                else:
                    logger.debug(f"DOM-only play signal error: {e}")
            await asyncio.sleep(0.85)
            verify = await self._verify_playback_state(page=page, sample_gap_s=0.45)
            state = self._normalize_media_state(verify.get("state", {}))
            if bool(verify.get("playback_confirmed")):
                self._mark_media_verified(page=page, source="dom_only_fallback")
                if run_ctx:
                    await self._emit_playback_frame(run_ctx, "dom_only_success", target=f"attempt_{idx}", phase="executing")
                if session_id:
                    await self._update_driver_state(session_id)
                return {
                    "ok": True,
                    "status": "success",
                    "message": "DOM-only fallback confirmed playback.",
                    "playback_confirmed": True,
                    "details": state,
                    "verification": verify.get("verification"),
                }

        final_probe = await self._verify_playback_state(page=page, sample_gap_s=0.45)
        return {
            "ok": False,
            "status": "partial",
            "message": "DOM-only fallback attempted, but playback was not confirmed.",
            "playback_confirmed": False,
            "blocker": "playback_not_confirmed",
            "details": self._normalize_media_state(final_probe.get("state", {})),
            "verification": final_probe.get("verification"),
        }

    async def _capture_collab_screenshot(self, session_id: str | None, step_idx: int) -> str | None:
        page = self.page or await self._get_current_page()
        if not page:
            return None
        filename = f"collab_step_{step_idx}_{uuid.uuid4().hex[:6]}.jpg"
        path = None
        ws = getattr(self.kernel, "workspace_service", None) if self.kernel else None
        if session_id and ws:
            media_dir = os.path.join(ws.get_session_dir(session_id), "media", "image")
            os.makedirs(media_dir, exist_ok=True)
            path = os.path.join(media_dir, filename)
        else:
            path = os.path.join(tempfile.gettempdir(), filename)
        try:
            # browser-use page wrappers commonly accept no kwargs and return bytes.
            image_bytes = await page.screenshot()
            image_bytes = self._normalize_frame_bytes(image_bytes)
            if not image_bytes:
                return None
            # Vision-lite: aggressively shrink payload to reduce token/cost pressure.
            try:
                from PIL import Image
                with Image.open(io.BytesIO(image_bytes)) as img:
                    img = img.convert("RGB")
                    max_w = 896
                    max_h = 504
                    if img.width > max_w or img.height > max_h:
                        img.thumbnail((max_w, max_h))
                    img.save(path, format="JPEG", quality=52, optimize=True)
            except Exception:
                # Fallback to raw bytes if Pillow processing fails.
                with open(path, "wb") as f:
                    f.write(image_bytes)
            return path
        except Exception as e:
            logger.warning(f"Collaborative screenshot failed: {e}")
            return None

    def _get_llm_manager(self):
        if self.kernel and hasattr(self.kernel, "llm_manager") and self.kernel.llm_manager:
            return self.kernel.llm_manager
        orchestrator = getattr(self.kernel, "orchestrator", None) if self.kernel else None
        if orchestrator and hasattr(orchestrator, "llm_manager"):
            return orchestrator.llm_manager
        return None

    async def _vision_observe_page(self, task: str, session_id: str | None, step_idx: int) -> dict:
        screenshot_path = await self._capture_collab_screenshot(session_id, step_idx)
        if not screenshot_path:
            return {"ok": False, "next_hint": "press_space", "raw": "no_screenshot", "screenshot_path": None}

        llm_manager = self._get_llm_manager()
        if not llm_manager:
            return {"ok": False, "next_hint": "press_space", "raw": "llm_manager_unavailable", "screenshot_path": screenshot_path}

        compact_objective = self._compact_dom_objective(task)
        prompt = (
            "You are a visual observer for browser automation.\n"
            "Objetivo atual (alvo DOM resumido): " + compact_objective + "\n"
            "Ignore session history and answer only based on the current image.\n"
            "Retorne SOMENTE JSON com este formato:\n"
            "{"
            "\"state\":\"resumo curto\","
            "\"next_hint\":\"accept_cookie|click_play|press_space|none\","
            "\"play_selector\":\"seletor css curto ou vazio\","
            "\"cookie_selector\":\"seletor css curto ou vazio\","
            "\"blocker\":\"nenhum|texto curto\""
            "}\n"
            "Sem markdown, sem texto extra."
        )
        raw = llm_manager.analyze_image(screenshot_path, prompt)
        parsed = self._extract_first_json_object(raw) or {}
        next_hint = str(parsed.get("next_hint") or "").strip().lower()
        if next_hint not in {"accept_cookie", "click_play", "press_space", "none"}:
            next_hint = "press_space"
        return {
            "ok": True,
            "raw": raw,
            "parsed": parsed,
            "next_hint": next_hint,
            "play_selector": str(parsed.get("play_selector") or "").strip(),
            "cookie_selector": str(parsed.get("cookie_selector") or "").strip(),
            "blocker": str(parsed.get("blocker") or "").strip(),
            "screenshot_path": screenshot_path,
        }

    async def _dom_observe_page(self, task: str) -> dict:
        page = self.page or await self._get_current_page()
        if not page:
            return {
                "ok": False,
                "raw": "no_page",
                "parsed": {"state": "no_page", "next_hint": "press_space", "blocker": "no_page"},
                "next_hint": "press_space",
                "play_selector": "",
                "cookie_selector": "",
                "blocker": "no_page",
                "screenshot_path": None,
            }
        try:
            observed = await page.evaluate(
                """() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (!style) return false;
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };
                    const pickFirstVisible = (selectors) => {
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (isVisible(el)) return sel;
                        }
                        return '';
                    };
                    const cookieSelector = pickFirstVisible([
                        "button[aria-label*='Aceitar']",
                        "button[aria-label*='Accept']",
                        "button[title*='Aceitar']",
                        "button[title*='Accept']",
                        "button.fc-cta-consent",
                        "button#L2AGLb",
                    ]);
                    const playSelector = pickFirstVisible([
                        ".ytp-large-play-button",
                        ".ytp-play-button",
                        "#movie_player .ytp-play-button",
                        "button[data-testid='play_button_track']",
                        "button[data-testid='play_button']",
                        "button[data-testid*='play']",
                        "button[aria-label*='Play']",
                        "button[aria-label*='Reproduzir']",
                        "button[aria-label*='Tocar']",
                        "button[title*='Play']",
                        "button[title*='Reproduzir']",
                        "button[title*='Tocar']",
                    ]);
                    const buttonsPreview = Array.from(document.querySelectorAll('button, [role=\"button\"]'))
                        .filter(isVisible)
                        .slice(0, 8)
                        .map((el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 40))
                        .filter(Boolean);
                    const buildSelector = (el) => {
                        if (!el) return '';
                        if (el.id) {
                            const id = (window.CSS && CSS.escape) ? CSS.escape(el.id) : el.id.replace(/[^a-zA-Z0-9_-]/g, '');
                            if (id) return `#${id}`;
                        }
                        const parts = [];
                        let cur = el;
                        let depth = 0;
                        while (cur && cur.nodeType === 1 && depth < 6) {
                            if (cur.id) {
                                const id = (window.CSS && CSS.escape) ? CSS.escape(cur.id) : cur.id.replace(/[^a-zA-Z0-9_-]/g, '');
                                if (id) {
                                    parts.unshift(`#${id}`);
                                    break;
                                }
                            }
                            let tag = (cur.tagName || '').toLowerCase();
                            if (!tag) break;
                            const parent = cur.parentElement;
                            if (parent) {
                                const sameTag = Array.from(parent.children).filter((c) => (c.tagName || '').toLowerCase() === tag);
                                if (sameTag.length > 1) {
                                    const idx = sameTag.indexOf(cur) + 1;
                                    tag += `:nth-of-type(${idx})`;
                                }
                            }
                            parts.unshift(tag);
                            cur = cur.parentElement;
                            depth += 1;
                        }
                        return parts.join(' > ');
                    };
                    const scoreCandidate = (txt, aria, sel) => {
                        const blob = `${txt} ${aria} ${sel}`.toLowerCase();
                        let score = 0;
                        if (blob.includes('play') || blob.includes('reproduzir') || blob.includes('tocar')) score += 5;
                        if (blob.includes('accept') || blob.includes('aceitar') || blob.includes('agree') || blob.includes('ok')) score += 4;
                        if (blob.includes('cookie') || blob.includes('consent')) score += 2;
                        if (blob.includes('ytp-play-button')) score += 5;
                        return score;
                    };
                    const candidates = [];
                    const seen = new Set();
                    const pushCandidate = (el, selectorHint = '') => {
                        if (!el) return;
                        const visible = isVisible(el);
                        const text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
                        const aria = (el.getAttribute('aria-label') || '').trim().slice(0, 60);
                        const selector = selectorHint || buildSelector(el);
                        if (!selector) return;
                        const key = `${selector}|${text}|${aria}`;
                        if (seen.has(key)) return;
                        seen.add(key);
                        const rect = el.getBoundingClientRect();
                        const cx = Math.round(rect.left + rect.width / 2);
                        const cy = Math.round(rect.top + rect.height / 2);
                        let score = scoreCandidate(text, aria, selector) + 6;
                        if (!visible) score -= 2;
                        candidates.push({
                            id: `c${candidates.length + 1}`,
                            selector,
                            text,
                            aria,
                            tag: (el.tagName || '').toLowerCase(),
                            visible,
                            score,
                            x: cx,
                            y: cy,
                        });
                    };
                    const prioritySelectors = [
                        ".ytp-large-play-button",
                        ".ytp-play-button",
                        "#movie_player .ytp-play-button",
                        "#movie_player button.ytp-play-button",
                        "video",
                        "button[aria-label*='Play']",
                        "button[aria-label*='Reproduzir']",
                        "button[aria-label*='Tocar']",
                        "button[aria-label*='Accept']",
                        "button[aria-label*='Aceitar']",
                        "button#L2AGLb",
                    ];
                    for (const sel of prioritySelectors) {
                        const el = document.querySelector(sel);
                        if (el) pushCandidate(el, sel);
                    }
                    // Controlled expansion: only visible action buttons with play/cookie semantics.
                    const allButtons = Array.from(document.querySelectorAll('button, [role=\"button\"]')).filter(isVisible);
                    for (const el of allButtons) {
                        const t = ((el.innerText || el.textContent || '') + ' ' + (el.getAttribute('aria-label') || '')).toLowerCase();
                        if (
                            t.includes('play') || t.includes('reproduzir') || t.includes('tocar') ||
                            t.includes('accept') || t.includes('aceitar') || t.includes('agree') || t.includes('cookie')
                        ) {
                            pushCandidate(el);
                        }
                    }
                    candidates.sort((a, b) => b.score - a.score);
                    if (candidates.length === 0) {
                        const fallbackSelectors = [".ytp-large-play-button", ".ytp-play-button", "#movie_player .ytp-play-button", "video", "button#L2AGLb"];
                        for (const sel of fallbackSelectors) {
                            candidates.push({
                                id: `c${candidates.length + 1}`,
                                selector: sel,
                                text: "",
                                aria: "",
                                tag: "fallback",
                                visible: false,
                                score: scoreCandidate("", "", sel),
                                x: 640,
                                y: 360,
                            });
                        }
                    }
                    const media = document.querySelector('video, audio');
                    const mediaPaused = !!media && !!media.paused;

                    let nextHint = 'press_space';
                    if (cookieSelector) nextHint = 'accept_cookie';
                    else if (playSelector) nextHint = 'click_play';

                    return {
                        state: 'dom_observed',
                        next_hint: nextHint,
                        play_selector: playSelector,
                        cookie_selector: cookieSelector,
                        blocker: '',
                        title: document.title || '',
                        url: location.href || '',
                        buttons_preview: buttonsPreview,
                        media_paused: mediaPaused,
                        candidates: candidates.slice(0, 18),
                    };
                }"""
            )
        except Exception as e:
            observed = {
                "state": "dom_probe_error",
                "next_hint": "press_space",
                "play_selector": "",
                "cookie_selector": "",
                "blocker": str(e),
                "title": "",
                "url": "",
                "buttons_preview": [],
                "media_paused": None,
                "candidates": [],
            }

        parsed = observed if isinstance(observed, dict) else {}
        if not parsed and isinstance(observed, str):
            parsed = self._extract_first_json_object(observed) or {}
        next_hint = str(parsed.get("next_hint") or "").strip().lower()
        if next_hint not in {"accept_cookie", "click_play", "press_space", "none"}:
            next_hint = "press_space"
        return {
            "ok": True,
            "raw": json.dumps(parsed, ensure_ascii=False),
            "parsed": parsed,
            "next_hint": next_hint,
            "play_selector": str(parsed.get("play_selector") or "").strip(),
            "cookie_selector": str(parsed.get("cookie_selector") or "").strip(),
            "blocker": str(parsed.get("blocker") or "").strip(),
            "screenshot_path": None,
        }

    def _plan_next_collab_action(
        self,
        task: str,
        media_state: dict,
        observer: dict,
        avoid_action: str = "",
        stagnation_count: int = 0,
        excluded_candidates: list[str] | None = None,
    ) -> dict:
        llm_manager = self._get_llm_manager()
        if not llm_manager or not getattr(llm_manager, "active_chat_provider", None):
            return {"type": observer.get("next_hint") or "press_space"}

        compact_objective = self._compact_dom_objective(task)
        compact_snapshot = self._compact_dom_snapshot(media_state, observer.get("parsed") or {})
        prompt = (
            "You are the textual controller of a web agent for a DOM target.\n"
            "Consider only the short goal + current snapshot (no session context).\n"
            f"Objetivo curto: {compact_objective}\n"
            f"Snapshot DOM atual: {json.dumps(compact_snapshot, ensure_ascii=False)}\n"
            "Choose ONE action and return JSON ONLY.\n"
            "IMPORTANT: if media_state.playing=false, DO NOT return 'none'.\n"
            "Se escolher clique em elemento, prefira candidate_id presente em observer.candidates.\n"
            "{\"type\":\"click_candidate|accept_cookie|click_play|press_space|media_play_js|click_button_text\",\"candidate_id\":\"opcional\",\"text\":\"opcional\"}\n"
            "Sem texto extra."
        )
        if excluded_candidates:
            prompt += f"\nDo not use candidate_id in: {excluded_candidates}."
        if avoid_action and stagnation_count >= 2:
            prompt += (
                f"\nEstado sem progresso por {stagnation_count} passos. "
                f"DO NOT repeat action '{avoid_action}'. Choose a different action."
            )
        raw = llm_manager.active_chat_provider.generate_text(
            prompt,
            system_prompt="Be strict and return only valid JSON."
        )
        parsed = self._extract_first_json_object(raw) or {}
        action_type = str(parsed.get("type") or "").strip().lower()
        if action_type not in {"click_candidate", "accept_cookie", "click_play", "press_space", "media_play_js", "click_button_text"}:
            action_type = observer.get("next_hint") or "press_space"
        if avoid_action and stagnation_count >= 2 and action_type == avoid_action:
            # Keep LLM in control but avoid endless no-op loops when state does not change.
            action_type = "press_space" if avoid_action != "press_space" else "media_play_js"
        text = str(parsed.get("text") or "").strip()
        candidate_id = str(parsed.get("candidate_id") or "").strip()
        return {"type": action_type, "text": text, "candidate_id": candidate_id}

    async def _execute_collab_action(self, action: dict, observer: dict) -> None:
        page = self.page or await self._get_current_page()
        if not page:
            return
        parsed = observer.get("parsed") if isinstance(observer, dict) else {}
        candidates = parsed.get("candidates") if isinstance(parsed, dict) else []
        if not isinstance(candidates, list):
            candidates = []

        action_type = str(action.get("type") or "").strip().lower()
        if action_type == "accept_cookie":
            selector = observer.get("cookie_selector", "")
            if selector:
                try:
                    await page.click(selector, timeout=1200)
                    return
                except Exception:
                    pass
            await self._send_page_play_signal(page=page)
            return

        if action_type == "click_play":
            selector = observer.get("play_selector", "")
            if selector:
                try:
                    await page.click(selector, timeout=1400)
                    return
                except Exception:
                    pass
            # Candidate-guided click (market-standard target table fallback)
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                sel = str(item.get("selector") or "").strip()
                blob = f"{item.get('text','')} {item.get('aria','')} {sel}".lower()
                if not sel:
                    continue
                if "play" in blob or "reproduzir" in blob or "tocar" in blob or "ytp-play-button" in blob:
                    try:
                        await page.click(sel, timeout=1500)
                        return
                    except Exception:
                        continue
            await self._send_page_play_signal(page=page)
            return

        if action_type == "click_candidate":
            cid = str(action.get("candidate_id") or "").strip()
            selector = ""
            click_x = None
            click_y = None
            if cid and isinstance(candidates, list):
                # Accept either stable ids (c1, c2, ...) or plain numeric indices (0,1,2...).
                if cid.isdigit():
                    idx = int(cid)
                    if idx < 0:
                        idx = 0
                    if idx < len(candidates):
                        item = candidates[idx]
                        if isinstance(item, dict):
                            selector = str(item.get("selector") or "").strip()
                            click_x = item.get("x")
                            click_y = item.get("y")
                    elif (idx - 1) >= 0 and (idx - 1) < len(candidates):
                        item = candidates[idx - 1]
                        if isinstance(item, dict):
                            selector = str(item.get("selector") or "").strip()
                            click_x = item.get("x")
                            click_y = item.get("y")
                for item in candidates:
                    if isinstance(item, dict) and str(item.get("id") or "").strip() == cid:
                        selector = str(item.get("selector") or "").strip()
                        click_x = item.get("x")
                        click_y = item.get("y")
                        break
            if click_x is not None and click_y is not None:
                try:
                    mouse = await self._resolve_page_mouse(page)
                    if mouse:
                        await mouse.click(float(click_x), float(click_y))
                        return
                except Exception:
                    pass
            if selector:
                try:
                    await page.click(selector, timeout=1600)
                    return
                except Exception:
                    pass
            await self._send_page_play_signal(page=page)
            return

        if action_type == "press_space":
            try:
                await page.bring_to_front()
            except Exception as e:
                logger.debug(f"bring_to_front failed before space press: {e}")
            try:
                await page.keyboard.press("Space")
            except Exception as e:
                logger.debug(f"keyboard.press('Space') failed: {e}")
            await self._send_page_play_signal(page=page)
            return

        if action_type == "media_play_js":
            await self._send_page_play_signal(page=page)
            return

        if action_type == "click_button_text":
            wanted = str(action.get("text") or "").strip().lower()
            if wanted:
                try:
                    clicked = await page.evaluate(
                        """(wanted) => {
                            const isVisible = (el) => {
                                if (!el) return false;
                                const style = window.getComputedStyle(el);
                                if (!style) return false;
                                if (style.display === 'none' || style.visibility === 'hidden') return false;
                                const rect = el.getBoundingClientRect();
                                return rect.width > 0 && rect.height > 0;
                            };
                            const cands = Array.from(document.querySelectorAll('button, [role=\"button\"]'));
                            for (const el of cands) {
                                if (!isVisible(el)) continue;
                                const t = (el.innerText || el.textContent || '').trim().toLowerCase();
                                if (!t) continue;
                                if (t.includes(wanted)) {
                                    el.click();
                                    return true;
                                }
                            }
                            return false;
                        }""",
                        wanted,
                    )
                    if clicked:
                        return
                except Exception:
                    pass
            await self._send_page_play_signal(page=page)
            return

        # none: no-op

    async def _run_collaborative_media_task(self, task: str, session_id: str | None, use_vision: bool = True) -> dict:
        page = self.page or await self._get_current_page()
        if not page:
            try:
                await self._ensure_browser()
            except Exception:
                pass
            page = self.page or await self._get_current_page()
        if not page:
            return {
                "ok": False,
                "status": "error",
                "message": "No active page available for DOM-only LLM control.",
                "blocker": "no_active_page",
                "details": {"has_media": False, "playing": False, "current_time": 0.0},
            }
        await self._wait_for_page_ready(page=page, timeout_s=12.0)
        final_state = {"has_media": False, "playing": False, "current_time": 0.0}
        last_observer = {}
        prev_before_state = None
        last_action_type = ""
        stagnation_count = 0
        tried_candidate_ids: list[str] = []
        for idx in range(1, 9):
            before_state = self._normalize_media_state(await self._probe_media_state(page=page))
            final_state = before_state
            if prev_before_state is not None:
                state_changed = (
                    bool(before_state.get("playing")) != bool(prev_before_state.get("playing"))
                    or abs(float(before_state.get("current_time", 0.0)) - float(prev_before_state.get("current_time", 0.0))) > 0.02
                )
                stagnation_count = 0 if state_changed else (stagnation_count + 1)
            prev_before_state = dict(before_state)
            if before_state.get("playing"):
                return {
                    "ok": True,
                    "status": "success",
                    "message": "Playback confirmed in the page player.",
                    "details": before_state,
                }

            observer = (
                await self._vision_observe_page(task, session_id, idx)
                if use_vision
                else await self._dom_observe_page(task)
            )
            last_observer = observer
            action = self._plan_next_collab_action(
                task,
                before_state,
                observer,
                avoid_action=last_action_type,
                stagnation_count=stagnation_count,
                excluded_candidates=tried_candidate_ids[-8:],
            )
            last_action_type = str(action.get("type") or "")
            if action.get("type") == "click_candidate":
                cid = str(action.get("candidate_id") or "").strip()
                if cid:
                    tried_candidate_ids.append(cid)
            cand_preview = []
            parsed_obs = observer.get("parsed") if isinstance(observer, dict) else {}
            page_title = ""
            page_url = ""
            if isinstance(parsed_obs, dict):
                page_title = str(parsed_obs.get("title") or "")
                page_url = str(parsed_obs.get("url") or "")
                for c in (parsed_obs.get("candidates") or [])[:3]:
                    if isinstance(c, dict):
                        cand_preview.append(f"{c.get('id')}:{str(c.get('selector') or '')[:32]}")
            logger.info(
                "DOM-LLM step=%s action=%s candidate=%s text=%s media_before={has_media:%s,playing:%s,time:%s} hint=%s cands=%s title=%s url=%s",
                idx,
                action.get("type"),
                action.get("candidate_id"),
                action.get("text"),
                before_state.get("has_media"),
                before_state.get("playing"),
                before_state.get("current_time"),
                observer.get("next_hint"),
                cand_preview,
                page_title[:70],
                page_url[:120],
            )
            await self._execute_collab_action(action, observer)
            await asyncio.sleep(1.3)

            first = self._normalize_media_state(await self._probe_media_state(page=page))
            await asyncio.sleep(0.6)
            second = self._normalize_media_state(await self._probe_media_state(page=page))
            progressed = (second.get("current_time", 0.0) - first.get("current_time", 0.0)) > 0.05
            final_state = second
            if second.get("playing") or progressed:
                return {
                    "ok": True,
                    "status": "success",
                    "message": "Playback confirmed after collaborative control.",
                    "details": second,
                }

        return {
            "ok": True,
            "status": "partial",
            "message": "Collaborative control could not confirm playback.",
            "blocker": str(last_observer.get("blocker") or "playback_not_confirmed"),
            "screenshot_path": last_observer.get("screenshot_path"),
            "details": final_state,
        }
