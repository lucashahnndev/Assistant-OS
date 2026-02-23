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
from core.scheduler import Scheduler, WorkStatus
from core.worker import WorkerManager
import queue
import time
import json
from typing import Dict, Any, List
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
            from drivers.browser_driver import BrowserDriver
            logger.info("Initializing Browser Driver (Playwright)...")
            self.browser_driver = BrowserDriver(self)
            self.drivers.append(self.browser_driver)
            self.orchestrator.set_browser_driver(self.browser_driver)
        else:
            logger.info("Browser Driver disabled (browser_automator skill is inactive).")
            self.browser_driver = None
        
        self.sessions = {} # Dict[str, Session]
        self.session_locks = {} # Concurrency guards
        self.start_time = time.time()

        # Give Orchestrator access to drivers it might need to control
        self.orchestrator.set_system_driver(self.system_driver)

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
                print(f"DEBUG: Starting driver {driver}")
                driver.start()
            except Exception as e:
                logger.error(f"Error starting driver {driver}: {e}")
        
        logger.info("Kernel Running. Press Ctrl+C to stop.")
        # Keep main thread alive or join threads
        try:
            while self.running:
                # Main loop handles periodic maintenance
                self.worker_manager.watchdog_check()
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
                logger.debug(f"Event Consumer received {event_type} for work {work_id}")
                
                # Retrieve Driver Instance for this session
                # (We need to store this mapping in process_input)
                driver = self.driver_instances.get(session_id)
                if not driver:
                    continue

                if event_type == "work_progress":
                    # Status updates are now real-time. No rate-limiting needed 
                    # as these are the agent's intermediate "thoughts" or step feedback.
                    msg = event.get('message')
                    if hasattr(driver, 'send_reasoning_chunk'):
                        driver.send_reasoning_chunk(session_id, msg)
                    elif hasattr(driver, 'send_status'):
                        driver.send_status(session_id, 'thinking', msg)
                    elif hasattr(driver, 'send_response'):
                        driver.send_response(msg, target=session_id)

                
                elif event_type == "work_status_change":
                    status = event.get("status")
                    if status == "succeeded":
                        work = self.scheduler.get_work(work_id)
                        if work and work.result:
                            # Server-side drivers handle their own streaming via callbacks to avoid duplicates
                            if not hasattr(driver, 'send_reasoning_chunk'):
                                driver.send_response(work.result, target=session_id)
                            elif hasattr(driver, 'send_complete'):
                                # Ensure complete signal is sent if result is final but not yet signaled
                                # driver.send_complete(session_id) 
                                pass
                    elif status == "failed":
                        driver.send_response(f"❌ Erro na tarefa {work_id}: Ocorreu um problema interno.", target=session_id)

                elif event_type == "scheduled_job_trigger":
                    # Handle Scheduled Task Execution
                    task_id = event.get("task_id")
                    execution_id = event.get("execution_id")
                    input_text = event.get("input_text")
                    
                    logger.info(f"Kernel spawning worker for Scheduled Task {task_id} (Exec: {execution_id})")
                    
                    # We create a dummy work_id for the worker thread name/tracking, 
                    # but the worker will use execution_id for status updates.
                    dummy_work_id = f"exec-{execution_id[:8]}"
                    
                    self.worker_manager.spawn_worker(
                        dummy_work_id,
                        self.orchestrator.process,
                        input_text,
                        session_id="system_scheduler",
                        user_data={"execution_id": execution_id}, # Context for orchestrator
                        execution_id=execution_id # Direct arg for Worker
                    )

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
        
        # PREEMPTION: Cancel previous active work for this session to prevent interleaving
        self.scheduler.cancel_session_work(session_id)
        
        # Map session to driver for back-routing responses
        self.driver_instances[session_id] = driver_instance

        # IMMEDIATE FEEDBACK: Let the user know we're working BEFORE the synchronous LLM intent resolution
        try:
            driver_instance.send_status(session_id, 'thinking', 'Iniciando processamento...')
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
            plan, _, session = self.orchestrator.get_initial_intent(text, session_id=session_id, user_data=user_data, context=context, attachments=attachments, name=user_name)
            
            # ENSURE PERSISTENCE: Add user message to history before processing the plan
            # (unless it's an internal/hidden trigger which we don't have yet in this flow)
            if session:
                session.add_message("user", text, attachments=attachments)
                self.orchestrator._save_session(session)

            if not plan:
                return driver_instance.send_response("I couldn't process your request right now.", target=session_id)

            # 2. Quick Path (Reply Action)
            if plan.action_id == 'reply':
                # LLM straight reply or reflex
                session.add_message("assistant", plan.thought, msg_type="reasoning")
                session.add_message("assistant", plan.response_text)
                self.orchestrator._save_session(session)

                # Send reasoning chunk if available
                if hasattr(driver_instance, 'send_reasoning_chunk') and plan.thought:
                    driver_instance.send_reasoning_chunk(session_id, plan.thought)

                # Send response as chunks to trigger the correct responding UI
                driver_instance.send_response(plan.response_text, target=session_id, is_chunk=True, attachments=plan.attachments)
                
                # Crucial: Send complete to clear the "Thinking" block in Web UI
                if hasattr(driver_instance, 'send_complete'):
                    driver_instance.send_complete(session_id)
                
                return session_id
            # 3. Background Path (Work/Worker)
            label = None
            if hasattr(plan, 'metadata') and isinstance(plan.metadata, dict):
                label = plan.metadata.get('task_label')
            
            if not label: label = f"Executing {plan.action_id}"

            work = self.scheduler.create_work(session_id, text, label=label, key=plan.action_id)
            
            # Prepare callbacks
            callbacks = {}
            if hasattr(driver_instance, 'send_file'):
                callbacks['send_file'] = lambda path, cap=None: driver_instance.send_file(session_id, path, cap)
            
            callbacks['send_status'] = lambda phase, payload=None: driver_instance.send_status(session_id, phase, payload)
            callbacks['send_reasoning_chunk'] = lambda content: driver_instance.send_reasoning_chunk(session_id, content)
            callbacks['send_complete'] = lambda: driver_instance.send_complete(session_id)
            callbacks['send_response'] = lambda text, is_chunk=False, attachments=None: driver_instance.send_response(text, target=session_id, is_chunk=is_chunk, attachments=attachments)

            # Spawn Worker
            self.worker_manager.spawn_worker(
                work.work_id,
                self.orchestrator.process,
                text,
                session_id=session_id,
                user_data=user_data,
                callbacks=callbacks,
                initial_plan=plan, # Resume from this resolved plan
                context=context,
                attachments=attachments
            )

            # 4. Natural Acknowledgment (Optional, based on confidence/plan)
            ack_msg = plan.response_text if plan.response_text else f"Understood, I will {label.lower()} and let you know!"
            driver_instance.send_status(session_id, 'thinking', ack_msg)
            
            # Record acknowledgment in history for context continuity
            session.add_message("assistant", ack_msg, msg_type="reasoning")
            self.orchestrator._save_session(session)
            
            return work.work_id
        
        except Exception as e:
            logger.error(f"Kernel Error spawning work: {e}", exc_info=True)

if __name__ == "__main__":
    kernel = Kernel()
    kernel.start()
