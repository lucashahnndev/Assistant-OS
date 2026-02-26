import sys
import os
import time
import asyncio
import signal
import threading
from dotenv import load_dotenv
load_dotenv()
from core.orchestrator import AgentOrchestrator
from core.identity import PrincipalContext
# Drivers are imported dynamically in Kernel.__init__
from core.scheduler import Scheduler, WorkStatus, SYSTEM_WORKER_ANCHOR_SESSION_ID
from core.worker import WorkerManager
import queue
import time
import json
import datetime
from typing import Dict, Any, List, Tuple
from utils.logging_config import setup_logging, get_logger

# Setup Logging
setup_logging()
logger = get_logger("Kernel")

PID_FILE = "atlas.pid"

def check_single_instance():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # Check if process actually exists
            os.kill(old_pid, 0)
            logger.error(f"❌ Another instance of Atlas is already running (PID: {old_pid}). Exiting.")
            sys.exit(1)
        except (ProcessLookupError, ValueError, FileNotFoundError):
            # Process not running or dead PID file, we can take over
            pass
    
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

def remove_pid_file():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

# Add src to path if needed (though running from src/main.py usually accounts for this)
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

class Kernel:
    def __init__(self):
        check_single_instance()
        self.running = False
        self.drivers: list = []
        self.driver_instances: Dict[str, Any] = {} # For back-routing
        
        # Async Infrastructure
        self.event_bus = queue.Queue()
        self.scheduler = Scheduler(self.event_bus)
        self.worker_manager = WorkerManager(self.scheduler)
        self.last_status_update: Dict[str, float] = {} # For rate-limiting
        
        # 1. Load Config first (it determines the base_data_dir)
        from config.manager import ConfigManager
        self.config_manager = ConfigManager()
        self.base_data_dir = self.config_manager.base_data_dir
        
        # 2. Initialize Infrastructure Services with consistent paths
        from services.workspace_service import WorkspaceService
        self.workspace_service = WorkspaceService() # Now defaults to AOSD data dir internally
        
        from services.playback_service import PlaybackService
        self.playback_service = PlaybackService(
            workspace_service=self.workspace_service,
            config_manager=self.config_manager
        )
        
        # 3. Initialize Orchestrator and Kernel Logic
        self.orchestrator = AgentOrchestrator(self.config_manager)
        self.orchestrator.set_kernel(self)
        self.llm_manager = self.orchestrator.llm_manager # Expose for easier skill access
        self.skill_registry = self.orchestrator.skill_registry
        self.principal_context = None # To be set by drivers/commands
        
        # 4. Storage paths used during runtime
        self.logs_dir = os.path.join(self.base_data_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)
        
        from core.access_controller import IdentityService
        self.identity_service = IdentityService(self.base_data_dir)
        
        interfaces_config = self.config_manager.get_interfaces_config()

        # Initialize Drivers Dynamically
        if interfaces_config.get('voice', {}).get('enabled', True):
            from drivers.voice_driver import VoiceDriver
            logger.info("Initializing Voice Driver...")
            self.voice_driver = VoiceDriver(self, parent_dir)
            self.drivers.append(self.voice_driver)
        
        if interfaces_config.get('telegram', {}).get('enabled', True):
             from drivers.telegram_driver import TelegramDriver
             logger.info("Initializing Telegram Driver...")
             self.telegram_driver = TelegramDriver(self, parent_dir)
             self.drivers.append(self.telegram_driver)

        if interfaces_config.get('server', {}).get('enabled', True):
             from drivers.server_driver import ServerDriver
             logger.info("Initializing Server Driver (IPC/Web)...")
             self.server_driver = ServerDriver(self, parent_dir)
             self.drivers.append(self.server_driver)
             
        # Initialize System Driver (Host control)
        from drivers.system_driver import SystemDriver
        logger.info("Initializing System Driver (Host Control)...")
        self.system_driver = SystemDriver(self)
        self.drivers.append(self.system_driver)

        # Initialize Browser Driver (Internal tool, linked to browser_automator skill)
        browser_skill_config = self.config_manager.get_skill_config("browser_automator")
        if browser_skill_config.get('enabled', False):
            # Keep browser-use state inside project data dir to avoid permission issues in ~/.config.
            os.environ.setdefault(
                "BROWSER_USE_CONFIG_DIR",
                os.path.join(self.base_data_dir, "browser_use"),
            )
            try:
                from drivers.browser_driver import BrowserDriver
                logger.info("Initializing Browser Driver (Playwright)...")
                self.browser_driver = BrowserDriver(self)
                self.drivers.append(self.browser_driver)
                self.orchestrator.set_browser_driver(self.browser_driver)
            except Exception as e:
                logger.error(f"Browser Driver disabled due to initialization error: {e}")
                self.browser_driver = None
        else:
            logger.info("Browser Driver disabled (browser_automator skill is inactive).")
            self.browser_driver = None
        
        self.sessions = {} # Dict[str, Session]
        self.session_locks = {} # Concurrency guards
        self.start_time = time.time()
        self.pending_approval_queue: Dict[str, List[Dict[str, Any]]] = {}
        self.last_approval_notification_ts: Dict[str, float] = {}

        # Give Orchestrator access to drivers it might need to control
        self.orchestrator.set_system_driver(self.system_driver)

    @staticmethod
    def _is_media_action(action_id: str) -> bool:
        action = str(action_id or "").strip().lower()
        if not action:
            return False
        media_prefixes = (
            "browser.automator.play_url",
            "browser.automator.control",
            "browser.automator.open",
            "youtube.search.",
            "deezer.search.",
            "spotify.search.",
        )
        return any(action.startswith(prefix) for prefix in media_prefixes)

    def _resolve_admission_policy(self, action_id: str) -> str:
        work_cfg = self.config_manager.get("work_execution", {})
        policy_cfg = work_cfg.get("admission_policy", {}) if isinstance(work_cfg, dict) else {}
        if not isinstance(policy_cfg, dict):
            policy_cfg = {}
        default_policy = str(policy_cfg.get("default", "queue")).strip().lower() or "queue"
        media_policy = str(policy_cfg.get("media", "cancel_previous")).strip().lower() or "cancel_previous"
        return media_policy if self._is_media_action(action_id) else default_policy

    def _admission_gate(self, session_id: str, action_id: str) -> Tuple[str, List[str]]:
        active = self.scheduler.get_active_works(session_id=session_id)
        if not active:
            return "allow", []

        if self._is_media_action(action_id):
            blockers = [w for w in active if self._is_media_action(w.key or "")]
        else:
            blockers = active
        blockers = [w for w in blockers if not bool(getattr(w, "cancel_requested", False))]

        # Ignore stale self-conflicts where key/action is empty.
        blocker_ids = [w.work_id for w in blockers if w.work_id]
        if not blocker_ids:
            return "allow", []

        if self._is_media_action(action_id):
            return "confirm_takeover", blocker_ids

        policy = self._resolve_admission_policy(action_id)
        if policy == "cancel_previous":
            for wid in blocker_ids:
                self.scheduler.request_cancel(wid)
            return "allow", blocker_ids
        if policy == "reject":
            return "reject", blocker_ids
        # Current runtime has no persisted queue dispatcher for chat-initiated works.
        # For now, "queue" behaves as safe reject to avoid session lock collisions.
        return "reject", blocker_ids

    @staticmethod
    def _is_affirmative(text: str) -> bool:
        normalized = (text or "").strip().lower()
        return normalized in {
            "yes", "y", "ok", "approve", "approved", "autorizo", "sim", "s", "pode", "confirm", "confirmar"
        }

    @staticmethod
    def _is_negative(text: str) -> bool:
        normalized = (text or "").strip().lower()
        return normalized in {
            "no", "n", "deny", "denied", "cancel", "cancelar", "nao", "não", "recusar"
        }

    def _resolve_driver_for_session(self, session_id: str):
        if not session_id:
            return None
        if session_id == SYSTEM_WORKER_ANCHOR_SESSION_ID:
            return None
        driver = self.driver_instances.get(session_id)
        if driver:
            return driver
        if session_id.startswith("telegram_") and hasattr(self, "telegram_driver"):
            return self.telegram_driver
        if session_id.startswith("voice") and hasattr(self, "voice_driver"):
            return self.voice_driver
        if hasattr(self, "server_driver"):
            return self.server_driver
        return None

    def _send_to_session(self, session_id: str, text: str, phase: str = "thinking"):
        driver = self._resolve_driver_for_session(session_id)
        if not driver:
            return False
        try:
            if hasattr(driver, "send_status"):
                driver.send_status(session_id, phase, {"message": text})
            if hasattr(driver, "send_response"):
                driver.send_response(text, target=session_id, is_chunk=True)
            if hasattr(driver, "send_complete"):
                driver.send_complete(session_id)
            return True
        except Exception as e:
            logger.debug(f"Failed sending routed message to {session_id}: {e}")
            return False

    def _enqueue_approval_request(self, owner_session_id: str, work_id: str, prompt: str):
        bucket = self.pending_approval_queue.setdefault(owner_session_id, [])
        for item in bucket:
            if item.get("work_id") == work_id:
                item["prompt"] = prompt
                item["updated_at"] = datetime.datetime.now().isoformat()
                return
        bucket.append(
            {
                "work_id": work_id,
                "prompt": prompt,
                "created_at": datetime.datetime.now().isoformat(),
                "updated_at": datetime.datetime.now().isoformat(),
            }
        )
        bucket.sort(key=lambda item: item.get("updated_at", ""), reverse=True)

    def _remove_approval_request(self, owner_session_id: str, work_id: str):
        bucket = self.pending_approval_queue.get(owner_session_id) or []
        if not bucket:
            return
        filtered = [item for item in bucket if item.get("work_id") != work_id]
        if filtered:
            self.pending_approval_queue[owner_session_id] = filtered
        else:
            self.pending_approval_queue.pop(owner_session_id, None)

    def _build_approval_digest_message(self, owner_session_id: str) -> str:
        pending = self.pending_approval_queue.get(owner_session_id) or []
        if not pending:
            return ""
        top = pending[0]
        total = len(pending)
        if total == 1:
            return (
                "On another topic, a running task is waiting for your approval.\n"
                f"{top.get('prompt')}\n"
                "Reply: yes (approve) or no (deny)."
            )
        return (
            "On another topic, there are pending approvals for running tasks.\n"
            f"- First pending: {top.get('prompt')}\n"
            f"- Additional pending requests: {max(0, total - 1)}\n"
            "Reply: yes (approve first) or no (deny first)."
        )

    def _maybe_send_approval_digest(self, owner_session_id: str):
        pending = self.pending_approval_queue.get(owner_session_id) or []
        if not pending:
            return
        cfg = self.config_manager.get("approval_notifications", {})
        cooldown = int(cfg.get("digest_cooldown_sec", 120))
        now = time.time()
        last = float(self.last_approval_notification_ts.get(owner_session_id, 0))
        if now - last < max(10, cooldown):
            return
        msg = self._build_approval_digest_message(owner_session_id)
        if msg and self._send_to_session(owner_session_id, msg, phase="thinking"):
            self.last_approval_notification_ts[owner_session_id] = now

    def _handle_pending_work_control(self, text: str, session_id: str, driver_instance) -> bool:
        session = self.orchestrator.get_session_robust(session_id)
        if not session or not isinstance(session.pending_action, dict):
            return False

        pending = session.pending_action
        pending_type = str(pending.get("type") or "").strip().lower()
        if pending_type == "media_takeover":
            blocked_work_ids = [str(wid) for wid in (pending.get("blocked_work_ids") or []) if str(wid).strip()]
            original_text = str(pending.get("original_text") or "").strip()
            original_user_data = pending.get("original_user_data") if isinstance(pending.get("original_user_data"), dict) else {}

            if self._is_affirmative(text):
                for wid in blocked_work_ids:
                    self.scheduler.force_takeover_cancel(wid, reason=f"takeover_by_{session_id}")
                session.pending_action = None
                self.orchestrator._save_session(session)

                message = self.orchestrator.i18n.t(
                    "reply.media_takeover_started",
                    locale=self.orchestrator._session_locale(session),
                )
                driver_instance.send_response(message, target=session_id, is_chunk=True)
                if hasattr(driver_instance, "send_complete"):
                    driver_instance.send_complete(session_id)

                if original_text:
                    resumed_user_data = dict(original_user_data)
                    resumed_user_data["resume_takeover"] = True
                    self.process_input(
                        original_text,
                        driver_instance,
                        user_id=session_id,
                        user_data=resumed_user_data,
                    )
                return True

            if self._is_negative(text):
                session.pending_action = None
                self.orchestrator._save_session(session)
                message = self.orchestrator.i18n.t(
                    "reply.media_takeover_cancelled",
                    locale=self.orchestrator._session_locale(session),
                )
                driver_instance.send_response(message, target=session_id, is_chunk=True)
                if hasattr(driver_instance, "send_complete"):
                    driver_instance.send_complete(session_id)
                return True
            return False

        work_id = str(pending.get("work_id") or "").strip()
        if not work_id:
            return False

        if self._is_affirmative(text):
            ok = self.scheduler.push_work_command(
                work_id,
                "approve",
                payload={"note": text},
                source_session_id=session_id,
            )
            session.pending_action = None
            self.orchestrator._save_session(session)
            self._remove_approval_request(session_id, work_id)
            message = "Approval received. The worker will continue."
            if ok:
                driver_instance.send_response(message, target=session_id, is_chunk=True)
            else:
                driver_instance.send_response("Could not find the target worker for approval.", target=session_id, is_chunk=True)
            if hasattr(driver_instance, "send_complete"):
                driver_instance.send_complete(session_id)
            return True

        if self._is_negative(text):
            ok = self.scheduler.push_work_command(
                work_id,
                "deny",
                payload={"note": text},
                source_session_id=session_id,
            )
            session.pending_action = None
            self.orchestrator._save_session(session)
            self._remove_approval_request(session_id, work_id)
            message = "Request denied. The worker was instructed to stop that sensitive action."
            if ok:
                driver_instance.send_response(message, target=session_id, is_chunk=True)
            else:
                driver_instance.send_response("Could not find the target worker for denial.", target=session_id, is_chunk=True)
            if hasattr(driver_instance, "send_complete"):
                driver_instance.send_complete(session_id)
            return True

        return False

    def reload_config(self):
        """Orchestrates a hot reload of all configuration-dependent services."""
        logger.warning("🔄 Initiating Global Hot Reload...")
        try:
            # 1. Reload Physical Config
            self.config_manager.load()
            
            # 2. Reload LLM Providers
            if hasattr(self.orchestrator, 'llm_manager'):
                self.orchestrator.llm_manager.reload()
                
            logger.info("✅ Hot Reload Complete.")
            return True
        except Exception as e:
            logger.error(f"❌ Hot Reload Failed: {e}", exc_info=True)
            return False

    def start(self):
        logger.info("Kernel Starting...")
        self.running = True

        # Start Event Consumer (after self.running is True)
        self.consumer_thread = threading.Thread(target=self._event_consumer_loop, daemon=True)
        self.consumer_thread.start()

        # Start Scheduler
        if hasattr(self, 'scheduler'):
            self.scheduler.start()

        for driver in self.drivers:
            try:
                logger.debug(f"Starting driver {driver}")
                driver.start()
            except Exception as e:
                logger.error(f"Error starting driver {driver}: {e}")
        
        logger.info("Kernel Running. Press Ctrl+C to stop.")
        # Keep main thread alive or join threads
        try:
            while self.running:
                # Main loop handles periodic maintenance
                self.worker_manager.watchdog_check()
                # Periodically re-notify pending approvals for idle sessions (digest mode).
                for owner_session_id in list(self.pending_approval_queue.keys()):
                    session = self.orchestrator.get_session_robust(owner_session_id)
                    idle_seconds = None
                    if session:
                        idle_seconds = max(0, int(time.time() - float(getattr(session, "last_interaction", time.time()))))
                    notify_after = int(self.config_manager.get("approval_notifications", {}).get("idle_notify_after_sec", 120))
                    if idle_seconds is None or idle_seconds >= notify_after:
                        self._maybe_send_approval_digest(owner_session_id)
                threading.Event().wait(10.0)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.running = False
        if hasattr(self, 'scheduler'):
            self.scheduler.stop()
        logger.info("Kernel Stopping...")
        for driver in self.drivers:
            driver.stop()
        remove_pid_file()
        sys.exit(0)

    def _event_consumer_loop(self):
        """Processes events from the workers and routes them to drivers."""
        logger.info("Event Consumer Loop started.")
        while self.running:
            try:
                event = self.event_bus.get(timeout=1.0)
                event_type = event.get("type")
                work_id = event.get("work_id")
                session_id = event.get("session_id")
                owner_session_id = event.get("owner_session_id")
                favorite_session_id = event.get("favorite_session_id")
                owner_sender_id = event.get("owner_sender_id")
                favorite_sender_id = event.get("favorite_sender_id")
                logger.debug(f"Event Consumer received {event_type} for work {work_id}")

                if event_type == "scheduled_job_trigger":
                    # Handle scheduled execution independent from chat driver routing.
                    task_id = event.get("task_id")
                    execution_id = event.get("execution_id")
                    input_text = event.get("input_text")
                    owner_session_id = event.get("owner_session_id") or None
                    favorite_session_id = event.get("favorite_session_id") or owner_session_id
                    # Global scheduled tasks (without owner session) run in a transient runtime session.
                    raw_session_id = event.get("session_id") or None
                    if raw_session_id and raw_session_id != SYSTEM_WORKER_ANCHOR_SESSION_ID:
                        session_id = raw_session_id
                    elif owner_session_id and owner_session_id != SYSTEM_WORKER_ANCHOR_SESSION_ID:
                        session_id = owner_session_id
                    else:
                        session_id = f"global-task-{task_id}-{str(execution_id)[:8]}"
                    owner_sender_id = event.get("owner_sender_id")
                    favorite_sender_id = event.get("favorite_sender_id") or owner_sender_id

                    logger.info(f"Kernel spawning worker for Scheduled Task {task_id} (Exec: {execution_id})")

                    work = self.scheduler.create_work(
                        session_id=session_id,
                        input_text=input_text,
                        label=f"Scheduled task {task_id}",
                        key=task_id,
                        owner_session_id=owner_session_id,
                        favorite_session_id=favorite_session_id,
                        owner_sender_id=owner_sender_id,
                        favorite_sender_id=favorite_sender_id,
                        scope="global",
                        initial_context={
                            "data": {
                                "execution_id": execution_id,
                                "task_id": task_id,
                                "origin": "scheduled",
                            }
                        },
                    )

                    self.worker_manager.spawn_worker(
                        work.work_id,
                        self.orchestrator.process,
                        input_text,
                        session_id=session_id,
                        user_data={
                            "execution_id": execution_id,
                            "task_id": task_id,
                            "origin": "scheduled",
                            "transient_session": owner_session_id in {None, SYSTEM_WORKER_ANCHOR_SESSION_ID},
                            "__worker_run": True,
                        },
                        execution_id=execution_id,
                    )
                    continue
                
                # Retrieve Driver Instance for this session
                # Route by owner session first so worker-originated permission/status
                # lands in the chat that created the worker.
                candidate_targets = [favorite_session_id, owner_session_id, session_id]
                target_session = next(
                    (
                        sid for sid in candidate_targets
                        if sid and sid != SYSTEM_WORKER_ANCHOR_SESSION_ID
                    ),
                    None,
                )
                driver = self._resolve_driver_for_session(target_session)
                if not driver:
                    continue

                if event_type == "work_progress":
                    # Status updates are now real-time. No rate-limiting needed 
                    # as these are the agent's intermediate "thoughts" or step feedback.
                    msg = event.get('message')
                    if hasattr(driver, 'send_reasoning_chunk'):
                        driver.send_reasoning_chunk(target_session, msg)
                    elif hasattr(driver, 'send_status'):
                        driver.send_status(target_session, 'thinking', msg)
                    elif hasattr(driver, 'send_response'):
                        driver.send_response(msg, target=target_session)

                
                elif event_type == "work_status_change":
                    status = event.get("status")
                    status_text = {
                        "queued": "Task queued.",
                        "running": "Task running.",
                        "paused": "Task paused.",
                        "waiting_user": "Task waiting for your approval.",
                        "succeeded": "Task completed successfully.",
                        "failed": "Task failed.",
                        "cancelled": "Task cancelled.",
                    }.get(str(status or "").lower(), f"Task status: {status}")

                    if hasattr(driver, "send_status"):
                        try:
                            driver.send_status(
                                target_session,
                                "thinking" if status in {"queued", "running", "paused", "waiting_user"} else "complete",
                                {"status": status, "message": status_text, "work_id": work_id},
                            )
                        except Exception as e:
                            logger.debug(f"Failed to forward work status to session {target_session}: {e}")

                    if status == "succeeded":
                        work = self.scheduler.get_work(work_id)
                        if work and work.result:
                            # Server-side drivers handle their own streaming via callbacks to avoid duplicates
                            if not hasattr(driver, 'send_reasoning_chunk'):
                                driver.send_response(work.result, target=target_session)
                        self._remove_approval_request(target_session, work_id)
                    elif status == "failed":
                        driver.send_response(f"❌ Task error {work_id}: An internal problem occurred.", target=target_session)
                        self._remove_approval_request(target_session, work_id)
                    elif status == "waiting_user":
                        snapshot = self.scheduler.get_work_snapshot(work_id, include_context=True)
                        summary = (snapshot or {}).get("context", {}).get("summary", {}) if snapshot else {}
                        prompt = summary.get("approval_prompt") or "This worker needs your approval to continue."
                        self._enqueue_approval_request(target_session, work_id, prompt)
                        session = self.orchestrator.get_session_robust(target_session)
                        idle_seconds = None
                        if session:
                            idle_seconds = max(0, int(time.time() - float(getattr(session, "last_interaction", time.time()))))
                        notify_after = int(self.config_manager.get("approval_notifications", {}).get("idle_notify_after_sec", 120))
                        if idle_seconds is None or idle_seconds >= notify_after:
                            self._maybe_send_approval_digest(target_session)
                    elif status in {"succeeded", "failed", "cancelled"}:
                        if hasattr(driver, "send_complete"):
                            driver.send_complete(target_session)
                        self._remove_approval_request(target_session, work_id)

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in Event Consumer: {e}")

    def process_input(self, text, driver_instance, user_id=None, user_data: dict = None, context: PrincipalContext = None, attachments: List[str] = None):
        """
        Asynchronous processing logic.
        Creates a 'Work', spawns a 'Worker', and returns acknowledgment.
        """
        if not text:
            return

        session_id = user_id if user_id else "default"
        logger.info(f"Kernel received input from {driver_instance.__class__.__name__} (Session: {session_id}): {text}")

        if self._handle_pending_work_control(text, session_id, driver_instance):
            return session_id

        pending_items = self.pending_approval_queue.get(session_id) or []
        effective_text = text
        if pending_items and not self._is_affirmative(text) and not self._is_negative(text):
            top = pending_items[0]
            approval_context = (
                "\n\n[PENDING_APPROVAL_CONTEXT]\n"
                f"- work_id: {top.get('work_id')}\n"
                f"- prompt: {top.get('prompt')}\n"
                "- Ask the user naturally for approve/deny when appropriate."
            )
            effective_text = f"{text}{approval_context}"
        
        # Configurable preemption policy: keep main conversation responsive without
        # automatically canceling active background work unless explicitly enabled.
        work_cfg = self.config_manager.get("work_execution", {})
        preempt_on_new_input = bool(work_cfg.get("preempt_on_new_input", False))
        if preempt_on_new_input:
            self.scheduler.cancel_session_work(session_id)
        
        # Map session to driver for back-routing responses
        self.driver_instances[session_id] = driver_instance

        # IMMEDIATE FEEDBACK: Let the user know we're working BEFORE the synchronous LLM intent resolution
        try:
            existing_session = self.orchestrator.get_session_robust(session_id)
            session_fallback_locale = "en"
            if existing_session and isinstance(getattr(existing_session, "context", None), dict):
                session_fallback_locale = str(existing_session.context.get("user_language") or "en")
            session_locale = self.orchestrator._normalize_locale(
                self.orchestrator._detect_user_language(text, fallback=session_fallback_locale)
            )
            start_msg = self.orchestrator.i18n.t("status.processing_start", locale=session_locale)
            driver_instance.send_status(session_id, 'thinking', start_msg)
        except Exception as e:
            logger.debug(f"Failed to send early status: {e}")

        try:
            # Inject driver capabilities into context
            caps = driver_instance.get_capabilities() if hasattr(driver_instance, 'get_capabilities') else {}
            if user_data is None: 
                user_data = {}
            user_data['driver_capabilities'] = caps
            
            # Extract user_name from user_data to name the session
            user_name = user_data.get('user_name', "")

            # 1. Get Initial Resolution (Reflex or Chain)
            plan, _, session = self.orchestrator.get_initial_intent(effective_text, session_id=session_id, user_data=user_data, context=context, attachments=attachments, name=user_name)
            
            # ENSURE PERSISTENCE: Add user message to history before processing the plan
            # (unless it's an internal/hidden trigger which we don't have yet in this flow)
            if session:
                session.add_message("user", text, attachments=attachments)
                self.orchestrator._save_session(session)

            if not plan:
                return driver_instance.send_response(
                    self.orchestrator.i18n.t(
                        "reply.no_plan_resolved",
                        locale=self.orchestrator._session_locale(session),
                    ),
                    target=session_id,
                )

            # 2. Quick Path (Reply Action)
            if plan.action_id == 'reply':
                # LLM straight reply or reflex
                coached_response = self.orchestrator.apply_conversation_coaching(session, text, plan.response_text or "")
                coached_response = self.orchestrator._enforce_response_language(session, coached_response)
                if plan.thought:
                    session.add_message("system", plan.thought, msg_type="reasoning")
                session.add_message("assistant", coached_response)
                self.orchestrator._save_session(session)

                # Send reasoning chunk if available
                if hasattr(driver_instance, 'send_reasoning_chunk') and plan.thought:
                    driver_instance.send_reasoning_chunk(session_id, plan.thought)

                # Send response as chunks to trigger the correct responding UI
                driver_instance.send_response(coached_response, target=session_id, is_chunk=True, attachments=plan.attachments)
                
                # Crucial: Send complete to clear the "Thinking" block in Web UI
                if hasattr(driver_instance, 'send_complete'):
                    driver_instance.send_complete(session_id)
                
                return session_id
            # 3. Background Path (Work/Worker)
            label = None
            if hasattr(plan, 'metadata') and isinstance(plan.metadata, dict):
                label = plan.metadata.get('task_label')
            
            if not label: label = f"Executing {plan.action_id}"

            admission_decision, blocked_work_ids = self._admission_gate(session_id, plan.action_id)
            if admission_decision == "confirm_takeover":
                prompt = self.orchestrator.i18n.t(
                    "reply.media_busy_takeover_prompt",
                    locale=self.orchestrator._session_locale(session),
                )
                session.pending_action = {
                    "type": "media_takeover",
                    "blocked_work_ids": blocked_work_ids,
                    "original_text": text,
                    "original_user_data": user_data if isinstance(user_data, dict) else {},
                    "requested_action": plan.action_id,
                    "requested_at": datetime.datetime.now().isoformat(),
                }
                session.add_message("assistant", prompt)
                self.orchestrator._save_session(session)
                if hasattr(driver_instance, "send_status"):
                    driver_instance.send_status(
                        session_id,
                        "thinking",
                        {
                            "code": "media_busy",
                            "message": prompt,
                            "blocked_work_ids": blocked_work_ids,
                        },
                    )
                driver_instance.send_response(prompt, target=session_id, is_chunk=True)
                if hasattr(driver_instance, "send_complete"):
                    driver_instance.send_complete(session_id)
                return session_id

            if admission_decision == "reject":
                busy_msg = self.orchestrator.i18n.t(
                    "reply.session_busy",
                    locale=self.orchestrator._session_locale(session),
                )
                if hasattr(driver_instance, "send_status"):
                    driver_instance.send_status(
                        session_id,
                        "error",
                        {
                            "code": "admission_reject",
                            "message": busy_msg,
                            "blocked_work_ids": blocked_work_ids,
                        },
                    )
                driver_instance.send_response(busy_msg, target=session_id, is_chunk=True)
                if hasattr(driver_instance, "send_complete"):
                    driver_instance.send_complete(session_id)
                session.add_message("assistant", busy_msg)
                self.orchestrator._save_session(session)
                return session_id

            work_scope = str(work_cfg.get("default_scope", "global")).lower()
            planner_seed = {}
            if isinstance(plan.metadata, dict):
                planner_seed = {
                    "plan": plan.metadata.get("plan"),
                    "state_summary": plan.metadata.get("state_summary"),
                }

            work = self.scheduler.create_work(
                session_id,
                text,
                label=label,
                key=plan.action_id,
                owner_session_id=session_id,
                favorite_session_id=session_id,
                owner_sender_id=(context.sender_id if context else None),
                favorite_sender_id=(context.sender_id if context else None),
                scope=work_scope,
                initial_context={
                    "planner": planner_seed,
                    "data": {
                        "initial_action": plan.action_id,
                        "initial_args": plan.args,
                        "resource_key": f"media:{session_id}" if self._is_media_action(plan.action_id) else f"session:{session_id}",
                        "admission_blocked_work_ids": blocked_work_ids,
                    },
                },
            )
            
            # Prepare callbacks
            callbacks = {}
            if hasattr(driver_instance, 'send_file'):
                callbacks['send_file'] = lambda path, cap=None: driver_instance.send_file(session_id, path, cap)
            
            callbacks['send_status'] = lambda phase, payload=None: driver_instance.send_status(session_id, phase, payload)
            callbacks['send_reasoning_chunk'] = lambda content: driver_instance.send_reasoning_chunk(session_id, content)
            callbacks['send_complete'] = lambda: driver_instance.send_complete(session_id)
            callbacks['send_response'] = lambda text, is_chunk=False, attachments=None: driver_instance.send_response(text, target=session_id, is_chunk=is_chunk, attachments=attachments)

            worker_user_data = dict(user_data or {})
            worker_user_data["__worker_run"] = True

            # Spawn Worker
            self.worker_manager.spawn_worker(
                work.work_id,
                self.orchestrator.process,
                text,
                session_id=session_id,
                user_data=worker_user_data,
                callbacks=callbacks,
                initial_plan=plan, # Resume from this resolved plan
                context=context,
                attachments=attachments
            )

            # 4. Immediate user-facing acknowledgment for async work start.
            # This keeps the chat responsive while the worker runs in background.
            ack_msg = self.orchestrator.build_work_start_ack(
                session,
                plan.action_id,
                explicit_text=(plan.response_text or ""),
                action_args=(plan.args if isinstance(plan.args, dict) else {}),
            )
            driver_instance.send_status(
                session_id,
                "thinking",
                {
                    "message": self.orchestrator.i18n.t("status.task_started", locale=self.orchestrator._session_locale(session)),
                    "work_id": work.work_id,
                },
            )
            driver_instance.send_response(ack_msg, target=session_id, is_chunk=True)
            session.add_message("assistant", ack_msg)
            self.orchestrator._save_session(session)
            
            return work.work_id
        
        except Exception as e:
            logger.error(f"Kernel Error spawning work: {e}", exc_info=True)

if __name__ == "__main__":
    kernel = Kernel()
    kernel.start()
