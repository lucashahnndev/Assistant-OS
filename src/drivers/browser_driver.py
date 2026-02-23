import asyncio
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from browser_use import Agent, Browser
import uuid
import datetime
import os
import json
import tempfile
import io
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
                await self._setup_browser()
                return

            # browser-use session can be closed internally (e.g., by an agent run).
            # Detect stale clients and recover transparently.
            if not await self._is_browser_usable():
                logger.warning("Detected stale browser client. Reinitializing browser session.")
                await self._reset_browser_state()
                await self._setup_browser()

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

    async def _resolve_media_page(self, device_id: str = "default", force_new: bool = False, create_if_missing: bool = True):
        media_tab = self.tab_registry.get_media_slot(device_id)
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
            return {
                "run_id": run_id,
                "session_id": session_id,
                "pb_service": pb_service,
                "step": 0,
                "action_id": action_id,
                "ended": False,
            }
        except Exception as e:
            logger.debug(f"Could not start playback run for {action_id}: {e}")
            return None

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
            if not frame_bytes:
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
            logger.debug(f"Could not emit playback frame: {e}")

    def _end_playback_run(self, run_ctx: dict | None, status: str = "success") -> None:
        if not run_ctx:
            return
        if run_ctx.get("ended"):
            return
        try:
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
                f"--window-size={width},{height}",
                "--window-position=50,50" # Slight offset from top-left
            ]
            
            # Ensure absolute path for user_data_dir
            if user_data_dir and not user_data_dir.startswith('/'):
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                user_data_dir = os.path.join(base_dir, user_data_dir)
            
            if user_data_dir:
                os.makedirs(user_data_dir, exist_ok=True)
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
                    screen=screen
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
        try:
            await self._ensure_browser()
            if media_task:
                await self._resolve_media_page(device_id=device_id)
            else:
                await self._get_current_page()
            # Collaborative lightweight path: text LLM controls, vision only observes.
            # For media tasks, this is the first attempt before full browser-use escalation.
            if media_task:
                collaborative = await self._run_collaborative_media_task(task, session_id=session_id)
                if collaborative.get("status") == "success":
                    self._mark_media_verified(source="collaborative_media")
                    return f"Tarefa concluída: {collaborative.get('message')}"
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
                            return "Tarefa concluída: Reprodução confirmada após verificação local adicional."
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
            
            if session_id and pb_service and playback_enabled:
                pb_service.start_run(session_id, run_id, "Execução do Navegador", {"skill": "browser", "action_id": "browser.run_task"})
                global_event_bus.emit_threadsafe({
                    "type": "playback.start",
                    "run_id": run_id,
                    "session_id": session_id,
                    "title": "Browser Agent",
                    "source": { "skill": "browser", "action_id": "browser.run_task" },
                    "mode": "frames",
                    "created_at": datetime.datetime.now().isoformat()
                })

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

            # Use native browser-use LLM wrappers
            if provider_name == 'openrouter':
                from browser_use.llm.openrouter.chat import ChatOpenRouter
                llm = ChatOpenRouter(
                    model=model_name,
                    api_key=api_key,
                    extra_body={'max_tokens': vision_max_tokens}
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

                        step_num = len(state.history)
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

            agent = Agent(
                task=task,
                llm=llm,
                browser=self.playwright_browser,
                step_callback=step_callback,
                # Reduce prompt footprint for free-tier vision models.
                vision_detail_level="low",
                llm_screenshot_size=(768, 432),
                max_clickable_elements_length=1800,
                max_actions_per_step=2,
                use_thinking=False,
                message_compaction=True,
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
                failure_reason = (
                    f"completed={completed}, successful={successful}, "
                    f"has_errors={had_errors}, final_result={'present' if final_result else 'empty'}"
                )
                if error_list:
                    failure_reason += f", errors={error_list[:2]}"
                await self._enforce_task_tab_limit()
                return f"FATAL TOOL ERROR na execução da tarefa: browser automation incomplete ({failure_reason}). NÃO ALUCINE SUCESSO."

            if media_task:
                post_verify = await self._verify_playback_state()
                if bool(post_verify.get("playback_confirmed")):
                    self._mark_media_verified(source="browser_use_agent")
            await self._enforce_task_tab_limit()
            return f"Tarefa concluída: {final_result}"
        except Exception as e:
            logger.error(f"Error in browser_agent task: {e}", exc_info=True)
            error_msg = str(e)
            
            # Quota/Rate Limit handling (Gemini/Google/OpenRouter)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                 return (f"FATAL TOOL ERROR: Cota de API excedida (429 RESOURCE_EXHAUSTED). "
                         "O limite do modelo de visão (Gemini) foi atingido. "
                         "VOCÊ DEVE PARAR E PEDIR AO USUÁRIO PARA AGUARDAR ALGUNS MINUTOS OU ALTERAR O MODELO NO CONFIG.JSON.")

            # Help user debug vision errors
            if "image input" in error_msg.lower() or "404" in error_msg:
                 return (f"FATAL TOOL ERROR: O modelo '{model_name}' falhou (Erro 404 ou falta de visão). "
                         "VOCÊ NÃO PODE DIZER QUE TEVE SUCESSO. Informe ao usuário que o modelo de navegação está configurado incorretamente "
                         "no config.json (interfaces.browser.model deve ser um modelo com visão como google/gemini-flash-1.5).")
            
            return f"FATAL TOOL ERROR na execução da tarefa: {error_msg}. NÃO ALUCINE SUCESSO."
        finally:
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
        run_ctx = self._start_playback_run(session_id, "browser.automator.open", "Navegação no Browser")
        try:
            await self._ensure_browser()
            page = await self._resolve_media_page(device_id=device_id) if purpose == "media" else await self._get_current_page()
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

    async def _probe_media_state(self, page=None) -> dict:
        page = page or self.page or await self._get_current_page()
        if not page:
            return {"has_media": False, "playing": False, "current_time": 0.0}
        try:
            return await page.evaluate(
                """() => {
                    const media = document.querySelector('video, audio');
                    if (!media) {
                        return { has_media: false, playing: false, current_time: 0 };
                    }
                    return {
                        has_media: true,
                        playing: !media.paused && !media.ended,
                        current_time: Number(media.currentTime || 0)
                    };
                }"""
            )
        except Exception:
            return {"has_media": False, "playing": False, "current_time": 0.0}

    @staticmethod
    def _normalize_media_state(state: object) -> dict:
        if isinstance(state, dict):
            return state
        if isinstance(state, str):
            text = state.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
        return {"has_media": False, "playing": False, "current_time": 0.0}

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
        confirmed = browser_playing or time_progress
        system_audio_active = await self._probe_system_audio_activity()
        return {
            "playback_confirmed": confirmed,
            "state": second,
            "verification": {
                "source": "browser_media_probe",
                "browser_playing": browser_playing,
                "time_progress": time_progress,
                "delta_current_time": round(dt, 4),
                "system_audio_active": system_audio_active,
            },
        }

    async def _send_page_play_signal(self, page=None) -> None:
        page = page or self.page or await self._get_current_page()
        if not page:
            return
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
                    try { media.play(); } catch (_) {}
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
        run_ctx = self._start_playback_run(session_id, "browser.automator.control", f"Controle de Mídia ({action})")
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
        run_ctx = self._start_playback_run(session_id, "browser.automator.play_url", "Navegação com Autoplay")
        try:
            await self._ensure_browser()
            page = await self._resolve_media_page(device_id=device_id, force_new=force_new_media_tab)
            if not page:
                self._end_playback_run(run_ctx, status="failure")
                return "Error: Browser page not initialized properly."
            
            # For YouTube/YouTube Music, we often want to append &autoplay=1
            if ("youtube.com" in url or "music.youtube.com" in url) and "autoplay=1" not in url:
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}autoplay=1"
            
            await self._emit_playback_frame(run_ctx, "before_autoplay_navigate", target=url, phase="executing")
            await page.goto(url)
            self.page = page
            logger.info(f"Navigated to {url} with autoplay intent.")
            await self._emit_playback_frame(run_ctx, "after_autoplay_navigate", target=url, phase="executing")
            await self._wait_for_page_ready(page=page, timeout_s=10.0)
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
            },
            "observer": {
                "state": str((observer_parsed or {}).get("state", ""))[:120],
                "next_hint": str((observer_parsed or {}).get("next_hint", ""))[:40],
                "play_selector": str((observer_parsed or {}).get("play_selector", ""))[:120],
                "cookie_selector": str((observer_parsed or {}).get("cookie_selector", ""))[:120],
                "blocker": str((observer_parsed or {}).get("blocker", ""))[:120],
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
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
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
            "Você é um observador visual para automação de navegador.\n"
            "Objetivo atual (alvo DOM resumido): " + compact_objective + "\n"
            "Ignore histórico de sessão e responda apenas com base na imagem atual.\n"
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

    def _plan_next_collab_action(self, task: str, media_state: dict, observer: dict) -> dict:
        llm_manager = self._get_llm_manager()
        if not llm_manager or not getattr(llm_manager, "active_chat_provider", None):
            return {"type": observer.get("next_hint") or "press_space"}

        compact_objective = self._compact_dom_objective(task)
        compact_snapshot = self._compact_dom_snapshot(media_state, observer.get("parsed") or {})
        prompt = (
            "Você é o controlador textual de um agente web para alvo DOM.\n"
            "Considere somente objetivo curto + snapshot atual (sem contexto de sessão).\n"
            f"Objetivo curto: {compact_objective}\n"
            f"Snapshot DOM atual: {json.dumps(compact_snapshot, ensure_ascii=False)}\n"
            "Escolha UMA ação e retorne SOMENTE JSON:\n"
            "{\"type\":\"accept_cookie|click_play|press_space|media_play_js|none\"}\n"
            "Sem texto extra."
        )
        raw = llm_manager.active_chat_provider.generate_text(
            prompt,
            system_prompt="Seja estrito e retorne apenas JSON válido."
        )
        parsed = self._extract_first_json_object(raw) or {}
        action_type = str(parsed.get("type") or "").strip().lower()
        if action_type not in {"accept_cookie", "click_play", "press_space", "media_play_js", "none"}:
            action_type = observer.get("next_hint") or "press_space"
        return {"type": action_type}

    async def _execute_collab_action(self, action: dict, observer: dict) -> None:
        page = self.page or await self._get_current_page()
        if not page:
            return

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

        # none: no-op

    async def _run_collaborative_media_task(self, task: str, session_id: str | None) -> dict:
        page = self.page or await self._get_current_page()
        await self._wait_for_page_ready(page=page, timeout_s=12.0)
        final_state = {"has_media": False, "playing": False, "current_time": 0.0}
        last_observer = {}
        for idx in range(1, 5):
            before_state = self._normalize_media_state(await self._probe_media_state(page=page))
            final_state = before_state
            if before_state.get("playing"):
                return {
                    "ok": True,
                    "status": "success",
                    "message": "Playback confirmado no player da página.",
                    "details": before_state,
                }

            observer = await self._vision_observe_page(task, session_id, idx)
            last_observer = observer
            action = self._plan_next_collab_action(task, before_state, observer)
            await self._execute_collab_action(action, observer)
            await asyncio.sleep(1.0)

            first = self._normalize_media_state(await self._probe_media_state(page=page))
            await asyncio.sleep(0.6)
            second = self._normalize_media_state(await self._probe_media_state(page=page))
            progressed = (second.get("current_time", 0.0) - first.get("current_time", 0.0)) > 0.05
            final_state = second
            if second.get("playing") or progressed:
                return {
                    "ok": True,
                    "status": "success",
                    "message": "Playback confirmado após controle colaborativo.",
                    "details": second,
                }

        return {
            "ok": True,
            "status": "partial",
            "message": "Controle colaborativo não conseguiu confirmar playback.",
            "blocker": str(last_observer.get("blocker") or "playback_not_confirmed"),
            "screenshot_path": last_observer.get("screenshot_path"),
            "details": final_state,
        }
