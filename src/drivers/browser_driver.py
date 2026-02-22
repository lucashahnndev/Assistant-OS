import asyncio
import threading
from playwright.async_api import async_playwright
from browser_use import Agent, Browser
from langchain_openai import ChatOpenAI
import uuid
import datetime
import os
from utils.event_bus import global_event_bus
from .base_driver import BaseDriver
from utils.logging_config import get_logger
from config import ConfigManager

logger = get_logger("BrowserDriver")

class BrowserDriver(BaseDriver):
    def __init__(self, kernel):
        super().__init__(kernel)
        self.running = False
        self._init_lock = None
        self.playwright_browser = None
        self.page = None

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

            logger.info("Humanized Browser Driver initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Humanized Browser: {e}", exc_info=True)

    def browser_agent(self, task, session_id=None):
        """Runs an autonomous task using browser-use Agent."""
        if not self.loop or not self.running:
            return "Browser driver is not running."
        
        # We need to return a future or wait for result.
        # Since this is a worker-based system, we can block or use callbacks.
        # For now, we'll run it in the loop and return a message.
        future = asyncio.run_coroutine_threadsafe(self._browser_agent_task(task, session_id), self.loop)
        return future.result() # This will block the caller (likely a Worker thread)

    async def _browser_agent_task(self, task, session_id=None):
        try:
            await self._ensure_browser()
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

            logger.info(f"Using vision model '{model_name}' (provider: {provider_name}) for browser automation.")

            # Use native browser-use LLM wrappers
            if provider_name == 'openrouter':
                from browser_use.llm.openrouter.chat import ChatOpenRouter
                llm = ChatOpenRouter(
                    model=model_name,
                    api_key=api_key,
                    extra_body={'max_tokens': 4096}
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
                step_callback=step_callback
            )
            
            result = await agent.run()
            
            # End playback
            if session_id and pb_service and playback_enabled:
                pb_service.end_run(session_id, run_id, "success")
                global_event_bus.emit_threadsafe({
                    "type": "playback.end",
                    "run_id": run_id,
                    "session_id": session_id,
                    "status": "success",
                    "total_steps": len(result.history),
                    "ended_at": datetime.datetime.now().isoformat()
                })

            if session_id:
                await self._update_driver_state(session_id)

            return f"Tarefa concluída: {result.final_result()}"
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
                if current_page and not current_page.is_closed():
                    # Get all pages from the current page's context
                    context = current_page.context
                    for page in context.pages:
                        try:
                            if not page.is_closed():
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
                logger.debug(f"Synced browser state for session {session_id}: {len(pages_info)} pages.")

                # Persist updated browser state when orchestrator is available
                try:
                    if kernel and hasattr(kernel, "orchestrator"):
                        kernel.orchestrator._save_session(session)
                except Exception as save_err:
                    logger.debug(f"Could not persist browser state for session {session_id}: {save_err}")
        except Exception as e:
            logger.error(f"Error syncing browser state: {e}")

    async def _cleanup(self):
        if self.playwright_browser:
            await self.playwright_browser.close()
        self.loop.stop()

    def navigate(self, url, session_id=None):
        """Navigates to a specific URL and waits for completion."""
        if not self.loop or not self.running:
            return "Error: Browser driver not running."
        future = asyncio.run_coroutine_threadsafe(self._navigate_task(url, session_id), self.loop)
        return future.result()

    async def _navigate_task(self, url, session_id=None):
        try:
            await self._ensure_browser()
            if not self.page:
                return "Error: Browser page not initialized properly."
            
            await self.page.goto(url)
            logger.info(f"Successfully navigated to: {url}")
            
            if session_id:
                await self._update_driver_state(session_id)
            return f"Navigated to {url}"
        except Exception as e:
            logger.error(f"Navigation error: {e}")
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
        except Exception as e:
            logger.error(f"Error in play_youtube task: {e}")

    def control_media(self, action, session_id=None):
        """Actions: play, pause, next, mute, etc."""
        if not self.loop or not self.running: return False
        future = asyncio.run_coroutine_threadsafe(self._control_media_task(action, session_id), self.loop)
        return future.result()

    async def _control_media_task(self, action, session_id=None):
        try:
            await self._ensure_browser()
            if not self.page:
                return False
            
            worked = False
            if action == 'pause':
                 await self.page.keyboard.press('k') # YouTube shortcut for play/pause
                 worked = True
            elif action == 'play':
                 await self.page.keyboard.press('k')
                 worked = True
            elif action == 'next':
                 await self.page.keyboard.press('Shift+N')
                 worked = True
            elif action == 'fullscreen':
                 await self.page.keyboard.press('f')
                 worked = True
            elif action == 'mute':
                 await self.page.keyboard.press('m')
                 worked = True
            elif action == 'click':
                 await self.page.evaluate('() => document.body.click()')
                 worked = True
            
            if worked:
                logger.info(f"Browser media control: {action}")
                if session_id:
                    await self._update_driver_state(session_id)
                return True
            else:
                logger.warning(f"Browser media control action '{action}' is not supported.")
                return False
        except Exception as e:
            logger.error(f"Error in browser media control: {e}")
            return False

    def navigate_with_autoplay(self, url, session_id=None):
        """Navigates to a URL and tries to ensure video starts playing."""
        if not self.loop or not self.running:
            return "Error: Browser driver not running."
        future = asyncio.run_coroutine_threadsafe(self._navigate_autoplay_task(url, session_id), self.loop)
        return future.result()

    async def _navigate_autoplay_task(self, url, session_id=None):
        try:
            await self._ensure_browser()
            if not self.page:
                return "Error: Browser page not initialized properly."
            
            # For YouTube/YouTube Music, we often want to append &autoplay=1
            if ("youtube.com" in url or "music.youtube.com" in url) and "autoplay=1" not in url:
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}autoplay=1"
            
            await self.page.goto(url)
            logger.info(f"Navigated to {url} with autoplay intent.")
            
            # Subtle micro-interaction to trigger play if autoplay policy blocks it
            await asyncio.sleep(2)
            try:
                await self.page.evaluate('() => document.body.click()') 
            except:
                pass
                
            if session_id:
                await self._update_driver_state(session_id)
            return f"Opened '{url}' with autoplay attempt."
        except Exception as e:
            logger.error(f"Autoplay navigation error: {e}")
            return f"Error navigating to {url}: {str(e)}"
