import os
import uuid
import json
import logging
import threading
import re
import time
import datetime
import platform
import shutil
from collections import deque
from typing import Optional, List, Dict, Callable, Any
from services.llm.manager import LLMManager
from core.session import Session
from core.identity import PrincipalContext
from core.access_controller import AccessController
from services.memory.memory_service import MemoryService
from services.memory.episodic_memory import EpisodicMemoryService
from services.memory.scratchpad_service import ScratchpadService
from services.specialist_manager import SpecialistManager
from services.safety_service import SafetyService
from services.workspace_service import WorkspaceService
from services.playback_service import PlaybackService
from services.i18n import I18nService
from services.llm.prompt_composer import PromptComposer
from config.manager import ConfigManager
from services.location.location_service import LocationService
from utils.logging_config import get_logger, read_recent_logs
from utils.event_bus import global_event_bus
from utils.toon_codec import encode_reasoning_step, encode_state_summary, dumps_toon

# New Resolution and Skill imports
from core.resolution.chain_resolver import FallbackChainResolver
from core.resolution.llm_resolver import LLMResolver
from core.reflex.registry import ReflexRegistry
from core.reflex.resolver import ReflexResolver
from core.resolution.action_plan import ActionPlan
from core.scheduler import WorkStatus
from skills.registry import SkillRegistry
from skills.loader import SkillLoader
from core.sessions_index import SessionIndexManager

# Configure logging
logger = get_logger("AgentOrchestrator")

class AgentOrchestrator:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(AgentOrchestrator, cls).__new__(cls)
        return cls._instance

    def __init__(self, config_manager=None):
        if hasattr(self, 'initialized') and self.initialized:
            if config_manager:
                self.config_manager = config_manager
            return
        
        self.config_manager = config_manager if config_manager else ConfigManager()
        self.llm_manager = LLMManager()
        self.prompt_composer = PromptComposer()
        self.memory_service = MemoryService()
        self.episodic_memory = EpisodicMemoryService()
        self.workspace_service = WorkspaceService()
        self.playback_service = PlaybackService(self.workspace_service, self.config_manager)
        self.scratchpad_service = ScratchpadService(self.workspace_service)
        self.specialist_manager = SpecialistManager()
        self.safety_service = SafetyService()
        self.safety_service.set_workspace_dir(self.workspace_service.get_workspace_dir())
        self.i18n = I18nService(default_locale="en")
        self.access_controller = AccessController(self.config_manager.base_data_dir)
        self.location_service = LocationService()
        self.sessions = {} # Dict[str, Session]
        self.session_locks = {} # Concurrency guards + persistence serialization (RLock per session)
        self.browser_driver = None
        self.system_driver = None
        self._instruction_pack_cache: Dict[str, str] = {}
        self._prompt_metrics_cache: Dict[str, Dict[str, Any]] = {}
        self._turn_metrics_cache: Dict[str, Dict[str, Any]] = {}
        self._observation_metrics_cache: Dict[str, deque] = {}
        # Persistence Path
        self.base_data_dir = self.config_manager.base_data_dir
        self.sessions_dir = os.path.join(self.base_data_dir, 'sessions')
        if not os.path.exists(self.sessions_dir):
            os.makedirs(self.sessions_dir)

        # Start GC for Playback
        self._start_playback_gc()

        # Session Persistence Queue (P1: Decoupling)
        from queue import Queue
        from threading import Thread
        self._session_writer_queue = Queue()
        self._session_writer_thread = Thread(target=self._session_writer_loop, daemon=True, name="SessionWriter")
        self._session_writer_thread.start()
        
        # 0. Session Index Manager
        self.index_manager = SessionIndexManager(self.sessions_dir)
        self.index_manager.reconcile()
        
        
        # 1. Skill System
        self.skill_registry = SkillRegistry()
        self.skill_loader = SkillLoader(self.skill_registry, config_manager=self.config_manager)
        
        # Core skills should now be in the skills directory and loaded via SkillLoader
        
        # Load external skills
        skills_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'skills')
        self.skill_loader.load_from_directory(skills_path)

        # 2. Reflex System (Centralized)
        # NOTE: intent resolution is LLM-only by design. Reflex rules stay loaded only
        # for compatibility/inspection and are not used to route user intents.
        self.reflex_registry = ReflexRegistry()
        for skill in self.skill_registry.skills.values():
            for rule in skill.get_reflex_rules():
                self.reflex_registry.register(
                    pattern=rule['pattern'],
                    action_id=rule['action_id'],
                    handler=rule.get('handler')
                )
        self.reflex_resolver = ReflexResolver(self.reflex_registry)

        # 3. Intent Resolution Chain (LLM-only, no semantic/reflex routing config)
        self.llm_resolver = LLMResolver(
            self.llm_manager,
            threshold=0.65,
            skill_registry=self.skill_registry,
        )

        self.intent_resolver_chain = FallbackChainResolver([self.llm_resolver])
        
        self.kernel = None
        self.proactive_running = False
        
        logger.info("Agent Orchestrator Initialized with LLM-Only Intent Resolution")
        
        self.initialized = True

    @staticmethod
    def _is_transient_runtime_session(session: Optional[Session]) -> bool:
        if not session:
            return False
        if not isinstance(getattr(session, "context", None), dict):
            return False
        return bool(session.context.get("__transient_session"))

    def _start_playback_gc(self):
        """Starts a background thread for playback garbage collection."""
        def gc_loop():
            # Initial wait to let system stabilize
            time.sleep(60)
            while True:
                try:
                    logger.info("Running Playback GC...")
                    self.playback_service.cleanup_expired()
                except Exception as e:
                    logger.error(f"Error in Playback GC: {e}")
                time.sleep(1800) # Every 30 minutes
        
        thread = threading.Thread(target=gc_loop, name="PlaybackGC", daemon=True)
        thread.start()

        # Proactive Pulse Thread (DISABLED to prevent subject mixing)
        self.proactive_running = False
        # self.proactive_thread = threading.Thread(target=self._start_proactive_loop, daemon=True)
        # self.proactive_thread.start()

    def _start_proactive_loop(self):
        """
        Background thread that periodically triggers a 'proactive' session check.
        """
        import time
        logger.info("Starting Proactive Pulse Loop (Heartbeat)")
        
        # Wait a bit after startup
        time.sleep(30)
        
        while self.proactive_running:
            try:
                # Heartbeat Guard: Only trigger if no other session was active recently
                # This prevents interrupting the user during active tasks
                now_ts = time.time()
                active_sessions = [s for s in self.sessions.values() if s.session_id != 'proactive' and (now_ts - s.last_interaction) < 60]
                
                if not active_sessions:
                    # IMPROVEMENT: Scan for triggers instead of fixed pulse
                    triggers = self._scan_system_triggers()
                    if triggers:
                        logger.info(f"Triggering proactive session for: {triggers}")
                        self.process(f"[SYSTEM_TRIGGER: {triggers}]", session_id="proactive")
                    else:
                        logger.debug("Pulse: No triggers found, system status normal.")
                else:
                    logger.debug("Skipping Heartbeat: Active user session detected.")
            except Exception as e:
                logger.error(f"Error in proactive loop: {e}")
            
            time.sleep(600) # 10 minutes

    def on_event(self, event_type: str, data: Dict):
        """
        Handles spontaneous system events (proactivity).
        """
        logger.info(f"System Event Received: {event_type} | Data: {data}")
        # In a real scenario, this would trigger a process() call with 'session_id="system"'
        # and a predefined system prompt or message like "Ocorreu um erro: {data}"
        # For now, we just log it.
        pass

    def _get_or_create_session_lock(self, session_id: str) -> threading.RLock:
        lock = self.session_locks.get(session_id)
        if lock is None:
            lock = threading.RLock()
            self.session_locks[session_id] = lock
        return lock



    def get_session_robust(self, session_id: str) -> Optional[Session]:
        """
        Retrieves a session from memory or loads it from disk if available.
        Does NOT automatically create a session in memory/disk unless it exists.
        """
        if not session_id:
            return None

        if session_id in self.sessions:
            return self.sessions[session_id]
        
        session = self._load_session(session_id)
        if session:
            self.sessions[session_id] = session
            return session
            
        return None

    def create_session(self, session_id: str, interface: str = "web", name: str = "") -> Session:
        """Explicitly creates a new session with the folder structure."""
        logger.info(f"Creating new session: {session_id} for {interface}")
        session = Session(session_id)
        session.source = interface
        session.name = name
        self.sessions[session_id] = session
        
        # Ensure directory exists
        sess_dir = os.path.join(self.sessions_dir, session_id)
        os.makedirs(sess_dir, exist_ok=True)
        
        self._save_session(session)
        return session

    def get_sessions_list(self, interface: str = "all") -> List[Dict]:
        if hasattr(self, 'index_manager'):
            return self.index_manager.list_sessions(interface)
        return []

    def get_active_session(self, interface: str = "all") -> Optional[Session]:
        if hasattr(self, 'index_manager'):
            active_info = self.index_manager.get_active_session(interface)
            if active_info:
                return self.get_session_robust(active_info['session_id'])
        return None

    def open_session(self, session_id: str):
        session = self.get_session_robust(session_id)
        if session:
            session.last_opened_at = time.time()
            self._save_session(session)
            return session
        return None

    def _cleanup_session_state(self, session: Session):
        """Resets the internal state summary to prevent state pollution."""
        session.state_summary = {
            "goal": "Standby/Listening",
            "cursor": "0/0 (step: init)",
            "done_steps": [],
            "last_outcome": "Ready for new command.",
            "last_error": "None",
            "retry_count": 0,
            "backoff_strategy": "None",
            "memory_notes": session.state_summary.get("memory_notes", "None")
        }
        session.plan = []
        session.scratchpad = ""

    def _standardize_attachments(self, session: Session, attachments: List[str]) -> List[Dict]:
        """Copies attachments to a standardized session media folder and returns structured metadata."""
        if not attachments:
            return []
        
        import uuid
        import shutil
        import mimetypes
        
        standardized = []
        session_dir = os.path.join(self.sessions_dir, session.session_id)
        session_media_root = os.path.abspath(os.path.join(session_dir, "media"))
        cache_key = "_standardized_attachment_cache"
        cache = session.context.get(cache_key)
        if not isinstance(cache, dict):
            cache = {}
            session.context[cache_key] = cache

        def _extract_path(entry: Any) -> str:
            if isinstance(entry, str):
                return entry
            if isinstance(entry, dict):
                for key in ("path", "file_path", "filename", "url", "name"):
                    value = entry.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            return ""

        def _resolve_existing_path(raw_path: str) -> str:
            value = (raw_path or "").strip().replace("\\", "/")
            if not value:
                return ""

            candidates = []
            if os.path.isabs(value):
                candidates.append(value)
            else:
                session_dir = os.path.join(self.sessions_dir, session.session_id)
                candidates.extend(
                    [
                        os.path.join(session_dir, value),
                        os.path.join(session_dir, "media", value),
                        os.path.join(session_dir, "media", "image", value),
                        os.path.join(session_dir, "uploads", value),
                        os.path.join(self.workspace_service.get_workspace_dir(), value),
                    ]
                )

            base_name = os.path.basename(value)
            if base_name:
                session_dir = os.path.join(self.sessions_dir, session.session_id)
                candidates.extend(
                    [
                        os.path.join(session_dir, "media", "image", base_name),
                        os.path.join(session_dir, "media", "video", base_name),
                        os.path.join(session_dir, "media", "audio", base_name),
                        os.path.join(session_dir, "media", "file", base_name),
                        os.path.join(session_dir, "uploads", base_name),
                        os.path.join(self.workspace_service.get_workspace_dir(), base_name),
                    ]
                )

            seen = set()
            for candidate in candidates:
                normalized = os.path.normpath(candidate)
                if normalized in seen:
                    continue
                seen.add(normalized)
                if os.path.isfile(normalized):
                    return normalized
            return value

        for entry in attachments:
            original_ref = _extract_path(entry)
            file_path = _resolve_existing_path(original_ref)
            if not file_path or not os.path.isfile(file_path):
                logger.warning(f"Attachment not found during standardization: {entry}")
                continue
            
            abs_source_path = os.path.abspath(file_path)
            cached_target = cache.get(abs_source_path)
            if isinstance(cached_target, str) and cached_target and os.path.isfile(cached_target):
                orig_name = os.path.basename(cached_target)
                mime_type, _ = mimetypes.guess_type(cached_target)
                mime_type = mime_type or "application/octet-stream"
                file_type = "file"
                if mime_type.startswith("image/"): file_type = "image"
                elif mime_type.startswith("video/"): file_type = "video"
                elif mime_type.startswith("audio/"): file_type = "audio"
                elif "pdf" in mime_type: file_type = "pdf"
                elif cached_target.endswith(('.doc', '.docx', '.xls', '.xlsx', '.txt')): file_type = "doc"
                standardized.append({
                    "name": orig_name,
                    "path": cached_target,
                    "type": file_type,
                    "mime": mime_type
                })
                continue

            orig_name = os.path.basename(file_path)
            mime_type, _ = mimetypes.guess_type(file_path)
            mime_type = mime_type or "application/octet-stream"
            
            # Determine type
            file_type = "file"
            if mime_type.startswith("image/"): file_type = "image"
            elif mime_type.startswith("video/"): file_type = "video"
            elif mime_type.startswith("audio/"): file_type = "audio"
            elif "pdf" in mime_type: file_type = "pdf"
            elif file_path.endswith(('.doc', '.docx', '.xls', '.xlsx', '.txt')): file_type = "doc"
            
            # If already persisted in this session media tree, keep the same file.
            if abs_source_path.startswith(session_media_root + os.sep):
                target_path = abs_source_path
            else:
                # Target directory: data/sessions/{session_id}/media/{file_type}
                target_dir = os.path.join(self.sessions_dir, session.session_id, "media", file_type)
                os.makedirs(target_dir, exist_ok=True)
                new_filename = f"{uuid.uuid4().hex[:8]}_{orig_name}"
                target_path = os.path.join(target_dir, new_filename)
            
            try:
                # If it's already in the target location, don't copy again.
                if abs_source_path != os.path.abspath(target_path):
                    shutil.copy2(file_path, target_path)
                cache[abs_source_path] = target_path
                if isinstance(original_ref, str) and original_ref.strip():
                    cache[str(original_ref).strip()] = target_path
                    
                standardized.append({
                    "name": orig_name,
                    "path": target_path,
                    "type": file_type,
                    "mime": mime_type
                })
                logger.info(f"Standardized attachment: {os.path.basename(target_path)} -> {file_type}")
            except Exception as e:
                logger.error(f"Failed to standardize attachment {file_path}: {e}")
                
        return standardized

    def set_browser_driver(self, driver):
        """Sets the browser driver for advanced controls."""
        self.browser_driver = driver

    def set_system_driver(self, driver):
        """Sets the system driver for host control."""
        self.system_driver = driver

    def set_kernel(self, kernel):
        """Link back to kernel for system skills."""
        self.kernel = kernel
        self.skill_loader.kernel = kernel

    def _get_planner_config(self) -> Dict[str, Any]:
        cfg = self.config_manager.get("planner", {})
        return {
            "base_max_steps": int(cfg.get("base_max_steps", 15)),
            "hard_max_steps": int(cfg.get("hard_max_steps", 60)),
            "replan_budget": int(cfg.get("replan_budget", 4)),
        }

    def _compute_dynamic_max_steps(self, user_input: str, initial_plan: Optional[ActionPlan]) -> int:
        planner_cfg = self._get_planner_config()
        base = max(5, planner_cfg["base_max_steps"])
        hard = max(base, planner_cfg["hard_max_steps"])

        text = (user_input or "").lower()
        complexity_markers = (
            "then",
            "after",
            "and",
            "pipeline",
            "workflow",
            "multiple",
            "batch",
            "refactor",
            "analyze",
            "implement",
        )
        complexity_score = sum(1 for marker in complexity_markers if marker in text)
        if len(text) > 350:
            complexity_score += 2

        if initial_plan and isinstance(initial_plan.metadata, dict):
            seed_plan = initial_plan.metadata.get("plan")
            if isinstance(seed_plan, list):
                complexity_score += min(5, len(seed_plan))

        dynamic = base + min(25, complexity_score * 2)
        return min(hard, dynamic)

    @staticmethod
    def _normalize_plan_tree(raw_plan: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_plan, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(raw_plan, start=1):
            if isinstance(item, str):
                title = item.strip()
                if not title:
                    continue
                status = "pending"
                lower = title.lower()
                if "[x]" in lower:
                    status = "done"
                    title = title.replace("[x]", "").replace("[X]", "").strip()
                elif "[/]" in lower:
                    status = "in_progress"
                    title = title.replace("[/]", "").strip()
                elif "[!]" in lower:
                    status = "blocked"
                    title = title.replace("[!]", "").strip()
                elif "[ ]" in lower:
                    title = title.replace("[ ]", "").strip()
                normalized.append(
                    {
                        "id": f"s{idx}",
                        "title": title,
                        "status": status,
                        "substeps": [],
                    }
                )
                continue

            if isinstance(item, dict):
                title = str(item.get("title") or item.get("step") or item.get("name") or "").strip()
                if not title:
                    continue
                status = str(item.get("status") or "pending").strip().lower()
                if status not in {"pending", "in_progress", "done", "blocked", "skipped"}:
                    status = "pending"
                raw_sub = item.get("substeps") or item.get("children") or []
                substeps = []
                if isinstance(raw_sub, list):
                    for sidx, sub in enumerate(raw_sub, start=1):
                        if isinstance(sub, str):
                            sub_title = sub.strip()
                            if not sub_title:
                                continue
                            substeps.append(
                                {
                                    "id": f"s{idx}.{sidx}",
                                    "title": sub_title,
                                    "status": "pending",
                                }
                            )
                        elif isinstance(sub, dict):
                            sub_title = str(sub.get("title") or sub.get("step") or "").strip()
                            if not sub_title:
                                continue
                            sub_status = str(sub.get("status") or "pending").strip().lower()
                            if sub_status not in {"pending", "in_progress", "done", "blocked", "skipped"}:
                                sub_status = "pending"
                            substeps.append(
                                {
                                    "id": f"s{idx}.{sidx}",
                                    "title": sub_title,
                                    "status": sub_status,
                                }
                            )
                normalized.append(
                    {
                        "id": str(item.get("id") or f"s{idx}"),
                        "title": title,
                        "status": status,
                        "substeps": substeps,
                    }
                )
        return normalized

    @staticmethod
    def _flatten_plan_lines(plan_tree: List[Dict[str, Any]]) -> List[str]:
        lines: List[str] = []
        for idx, step in enumerate(plan_tree, start=1):
            marker = {
                "pending": "[ ]",
                "in_progress": "[/]",
                "done": "[x]",
                "blocked": "[!]",
                "skipped": "[-]",
            }.get(step.get("status", "pending"), "[ ]")
            lines.append(f"{marker} {idx}. {step.get('title', 'step')}")
            for sidx, sub in enumerate(step.get("substeps", []), start=1):
                sub_marker = {
                    "pending": "[ ]",
                    "in_progress": "[/]",
                    "done": "[x]",
                    "blocked": "[!]",
                    "skipped": "[-]",
                }.get(sub.get("status", "pending"), "[ ]")
                lines.append(f"  {sub_marker} {idx}.{sidx} {sub.get('title', 'substep')}")
        return lines

    @staticmethod
    def _progress_cursor(plan_tree: List[Dict[str, Any]], loops: int, max_steps: int) -> str:
        total = max(1, len(plan_tree))
        done = sum(1 for step in plan_tree if step.get("status") == "done")
        current = next((step for step in plan_tree if step.get("status") == "in_progress"), None)
        current_title = current.get("title", "planning") if current else "planning"
        return f"{done}/{total} (loop {loops}/{max_steps}: {current_title})"

    @staticmethod
    def _planner_has_unfinished(plan_tree: List[Dict[str, Any]]) -> bool:
        if not plan_tree:
            return False
        active_states = {"pending", "in_progress", "blocked"}
        for step in plan_tree:
            if not isinstance(step, dict):
                continue
            if str(step.get("status") or "").strip() in active_states:
                return True
            substeps = step.get("substeps")
            if isinstance(substeps, list):
                for sub in substeps:
                    if not isinstance(sub, dict):
                        continue
                    if str(sub.get("status") or "").strip() in active_states:
                        return True
        return False

    @staticmethod
    def _advance_planner_on_success(plan_tree: List[Dict[str, Any]]) -> None:
        if not plan_tree:
            return
        current_step = next((s for s in plan_tree if isinstance(s, dict) and s.get("status") == "in_progress"), None)
        if not current_step:
            current_step = next((s for s in plan_tree if isinstance(s, dict) and s.get("status") == "pending"), None)
            if current_step:
                current_step["status"] = "in_progress"
        if not current_step:
            return

        substeps = current_step.get("substeps")
        if not isinstance(substeps, list) or not substeps:
            current_step["status"] = "done"
            next_pending = next((s for s in plan_tree if isinstance(s, dict) and s.get("status") == "pending"), None)
            if next_pending:
                next_pending["status"] = "in_progress"
            return

        current_sub = next((s for s in substeps if isinstance(s, dict) and s.get("status") == "in_progress"), None)
        if not current_sub:
            current_sub = next((s for s in substeps if isinstance(s, dict) and s.get("status") == "pending"), None)
            if current_sub:
                current_sub["status"] = "in_progress"
        if current_sub:
            current_sub["status"] = "done"

        next_pending_sub = next((s for s in substeps if isinstance(s, dict) and s.get("status") == "pending"), None)
        if next_pending_sub:
            next_pending_sub["status"] = "in_progress"
            return

        current_step["status"] = "done"
        next_pending_step = next((s for s in plan_tree if isinstance(s, dict) and s.get("status") == "pending"), None)
        if next_pending_step:
            next_pending_step["status"] = "in_progress"

    @staticmethod
    def _mark_planner_blocked(plan_tree: List[Dict[str, Any]]) -> None:
        if not plan_tree:
            return
        current_step = next((s for s in plan_tree if isinstance(s, dict) and s.get("status") == "in_progress"), None)
        if not current_step:
            return
        substeps = current_step.get("substeps")
        if isinstance(substeps, list) and substeps:
            current_sub = next((s for s in substeps if isinstance(s, dict) and s.get("status") == "in_progress"), None)
            if current_sub:
                current_sub["status"] = "blocked"
                return
        current_step["status"] = "blocked"

    def _touch_work_context(self, work_id: Optional[str], patch: Dict[str, Any]) -> None:
        if not work_id:
            return
        kernel = getattr(self, "kernel", None)
        scheduler = getattr(kernel, "scheduler", None)
        if not scheduler:
            return
        try:
            scheduler.update_work_context(work_id, patch)
        except Exception as e:
            logger.debug(f"Could not update work context for {work_id}: {e}")

    def _get_work_record(self, work_id: Optional[str]):
        if not work_id:
            return None
        kernel = getattr(self, "kernel", None)
        scheduler = getattr(kernel, "scheduler", None)
        if not scheduler:
            return None
        return scheduler.get_work(work_id)

    def _wait_for_work_decision(
        self,
        work_id: str,
        cancel_check: Optional[Callable[[], bool]],
        timeout_seconds: int = 1800,
    ) -> Dict[str, Any]:
        kernel = getattr(self, "kernel", None)
        scheduler = getattr(kernel, "scheduler", None)
        if not scheduler:
            return {"decision": "deny", "note": "Scheduler unavailable"}

        started = time.time()
        while True:
            if cancel_check and cancel_check():
                return {"decision": "cancel", "note": "Task cancelled"}
            if time.time() - started > timeout_seconds:
                return {"decision": "timeout", "note": "Approval timeout"}

            commands = scheduler.pop_work_commands(work_id)
            for cmd in commands:
                name = str(cmd.get("command") or "").strip().lower()
                payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}
                if name in {"approve", "approve_worker", "approve_session", "approve_global", "deny", "cancel"}:
                    if name in {"approve_worker", "approve_session", "approve_global"}:
                        scope = name.split("_", 1)[1]
                    else:
                        scope = str(payload.get("scope") or "worker").strip().lower()
                        if scope not in {"worker", "session", "global"}:
                            scope = "worker"
                    decision = "approve" if name.startswith("approve") else name
                    payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}
                    return {"decision": decision, "note": payload.get("note"), "scope": scope}
                if name == "inject_message":
                    payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}
                    note = str(payload.get("message") or "").strip()
                    if note:
                        return {"decision": "inject", "note": note}
            time.sleep(0.8)

    def delete_session(self, session_id: str):
        """Deletes all data associated with a session (JSON, uploads, workspace)."""
        logger.info(f"Deleting session data for: {session_id}")
        
        # 1. Remove from memory
        if session_id in self.sessions:
            del self.sessions[session_id]
        if session_id in self.session_locks:
            del self.session_locks[session_id]

        # 2. Delete Session Folder (JSON, Uploads, Artifacts)
        sess_dir = os.path.join(self.sessions_dir, session_id)
        if os.path.exists(sess_dir):
            import shutil
            shutil.rmtree(sess_dir)
            logger.info(f"Deleted session folder: {sess_dir}")

        # Note: Shared workspace is NOT deleted on per-session basis anymore

        # 5. Remove from Index
        if hasattr(self, 'index_manager'):
            self.index_manager.delete_session(session_id)

    def get_session_media(self, session_id: str) -> Dict[str, List]:
        """Scans the session media directory and message history for media files and links."""
        session = self.get_session_robust(session_id)
        if not session:
            return {"files": [], "links": []}
        
        def _normalize_rel_path(path: str) -> str:
            return (path or "").replace("\\", "/").lstrip("./")

        profile_picture_path = _normalize_rel_path(getattr(session, "profile_picture", ""))
        profile_picture_name = os.path.basename(profile_picture_path).lower() if profile_picture_path else ""

        def _is_internal_trace_content(content: str) -> bool:
            text = (content or "").strip()
            if not text:
                return True

            upper_text = text.upper()
            if upper_text.startswith("RESULT OF ACTION"):
                return True
            if upper_text.startswith("WARNING: YOU HAVE ATTEMPTED"):
                return True

            # Some internal thought payloads were historically persisted as JSON text.
            if text.startswith("{") and text.endswith("}"):
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = None
                if isinstance(payload, dict) and any(k in payload for k in ("thought", "plan", "action", "params")):
                    return True

            return False

        # Scan multiple possible locations for files
        search_dirs = [
            os.path.join(self.sessions_dir, session_id, "media"),
            os.path.join(self.sessions_dir, session_id, "uploads")
        ]
        
        files = []
        import mimetypes
        
        for media_dir in search_dirs:
            if os.path.exists(media_dir):
                for root, _, filenames in os.walk(media_dir):
                    for filename in filenames:
                        file_path = os.path.join(root, filename)
                        relative_path = os.path.relpath(file_path, os.path.join(self.sessions_dir, session_id))
                        normalized_rel = _normalize_rel_path(relative_path)
                        normalized_rel_lower = normalized_rel.lower()
                        filename_lower = filename.lower()

                        # Hide profile pictures from "Media" tab to avoid mixing chat media with avatars.
                        if profile_picture_path and normalized_rel == profile_picture_path:
                            continue
                        if profile_picture_name and filename_lower == profile_picture_name:
                            continue
                        if filename_lower.startswith("avatar_"):
                            continue
                        if filename_lower.startswith("collab_step_"):
                            try:
                                os.remove(file_path)
                            except Exception:
                                pass
                            continue
                        if normalized_rel_lower.startswith("media/profile_picture/") or "/profile_picture/" in normalized_rel_lower:
                            continue
                        
                        mime_type, _ = mimetypes.guess_type(file_path)
                        mime_type = mime_type or "application/octet-stream"
                        
                        file_type = "file"
                        if mime_type.startswith("image/"): file_type = "image"
                        elif mime_type.startswith("video/"): file_type = "video"
                        elif mime_type.startswith("audio/"): file_type = "audio"
                        elif "pdf" in mime_type: file_type = "pdf"
                        # Fallback for common extensions if mime fails
                        ext = os.path.splitext(filename)[1].lower()
                        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']: file_type = "image"
                        elif ext in ['.mp4', '.mov', '.webm']: file_type = "video"
                        elif ext in ['.mp3', '.wav', '.ogg']: file_type = "audio"
                        elif ext in ['.pdf']: file_type = "pdf"
                        elif ext in ['.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt']: file_type = "doc"
                        
                        files.append({
                            "name": filename,
                            "path": relative_path,
                            "type": file_type,
                            "mime": mime_type,
                            "size": os.path.getsize(file_path),
                            "timestamp": os.path.getmtime(file_path)
                        })

        # Sort files by timestamp descending
        files.sort(key=lambda x: x["timestamp"], reverse=True)

        # Extract links from history
        links = []
        seen_links = set()
        link_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*'
        for msg in session.history:
            # Ignore internal reasoning/system traces to keep links tab user-facing.
            msg_type = str(msg.get("type", "default") or "default").strip().lower()
            if msg_type != "default":
                continue
            if msg.get("role") not in {"user", "assistant"}:
                continue
            content = msg.get("content", "")
            if not isinstance(content, str) or not content:
                continue
            if _is_internal_trace_content(content):
                continue
            found_links = re.findall(link_pattern, content)
            for url in found_links:
                # Remove trailing punctuation often captured by regex
                clean_url = url.rstrip('.,;:)!?"\'')
                if not clean_url or clean_url in seen_links:
                    continue
                seen_links.add(clean_url)
                links.append({
                    "url": clean_url,
                    "timestamp": msg.get("timestamp"),
                    "role": msg.get("role"),
                    "message_type": msg_type
                })

        return {"files": files, "links": links}

    @staticmethod
    def _atomic_write_json(file_path: str, payload: Any) -> None:
        """Writes JSON atomically to avoid partial/truncated files under concurrent saves."""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        tmp_path = f"{file_path}.tmp.{os.getpid()}.{threading.get_ident()}"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, file_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    @staticmethod
    def _recover_chat_messages_from_raw(raw_content: str) -> List[Dict]:
        """
        Best-effort parser for corrupted chat.json:
        extracts every decodable JSON object that looks like a chat message.
        """
        if not isinstance(raw_content, str) or not raw_content.strip():
            return []

        recovered: List[Dict] = []
        decoder = json.JSONDecoder()
        idx = 0
        size = len(raw_content)

        while idx < size:
            if raw_content[idx] != "{":
                idx += 1
                continue
            try:
                obj, end = decoder.raw_decode(raw_content, idx)
            except json.JSONDecodeError:
                idx += 1
                continue

            if isinstance(obj, dict) and "role" in obj and "content" in obj:
                recovered.append(obj)
            idx = end

        return recovered

    def _load_chat_history_resilient(self, chat_file_path: str, session_id: str) -> List[Dict]:
        """Loads chat history with corruption recovery + self-heal write-back."""
        if not os.path.exists(chat_file_path):
            return []

        try:
            with open(chat_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            logger.warning(
                f"Invalid chat.json format for session {session_id}: expected list, got {type(data).__name__}"
            )
        except Exception as e:
            logger.error(f"Error reading chat.json for {session_id}: {e}")

        # Recovery path for malformed/truncated JSON.
        try:
            with open(chat_file_path, 'r', encoding='utf-8') as f:
                raw = f.read()
        except Exception as e:
            logger.error(f"Failed to read raw chat.json for recovery ({session_id}): {e}")
            return []

        recovered = self._recover_chat_messages_from_raw(raw)
        if not recovered:
            logger.error(f"Could not recover messages from corrupted chat.json for {session_id}.")
            return []

        backup_path = f"{chat_file_path}.corrupt-{int(time.time())}.bak"
        try:
            shutil.copy2(chat_file_path, backup_path)
            logger.warning(
                f"Recovered {len(recovered)} messages from corrupted chat.json for {session_id}. "
                f"Backup saved to {backup_path}."
            )
        except Exception as e:
            logger.warning(f"Recovered chat.json for {session_id}, but backup copy failed: {e}")

        try:
            self._atomic_write_json(chat_file_path, recovered)
        except Exception as e:
            logger.error(f"Failed to persist recovered chat.json for {session_id}: {e}")

        return recovered

    def get_chat_history(self, session_id: str) -> List[Dict]:
        """Returns full chat history from chat.json (authoritative source for message timeline)."""
        chat_file_path = os.path.join(self.sessions_dir, session_id, "chat.json")
        if not os.path.exists(chat_file_path):
            # Self-heal missing chat.json from session.json snapshot if available.
            session_file_path = os.path.join(self.sessions_dir, session_id, "session.json")
            try:
                if os.path.exists(session_file_path):
                    with open(session_file_path, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)
                    fallback_history = session_data.get("history", [])
                    if isinstance(fallback_history, list):
                        self._atomic_write_json(chat_file_path, fallback_history)
                        logger.warning(
                            f"chat.json was missing for {session_id}; recreated from session.json snapshot "
                            f"with {len(fallback_history)} messages."
                        )
                        return fallback_history
            except Exception as e:
                logger.error(f"Failed to recreate missing chat.json for {session_id} via get_chat_history: {e}")
            return []

        return self._load_chat_history_resilient(chat_file_path, session_id)

    @staticmethod
    def _history_message_key(msg: Dict) -> Optional[tuple]:
        """Best-effort stable key for deduplicating timeline entries."""
        if not isinstance(msg, dict):
            return None

        msg_id = msg.get("id")
        if msg_id:
            return ("id", str(msg_id))

        return (
            "sig",
            str(msg.get("role", "")),
            str(msg.get("type", "")),
            str(msg.get("timestamp", "")),
            str(msg.get("content", "")),
        )

    def _merge_chat_history_append_only(self, disk_history: List[Dict], memory_history: List[Dict]) -> List[Dict]:
        """
        Append-only merge for chat timeline:
        - Never removes existing disk entries.
        - Appends only new unique messages from in-memory history.
        - UPDATED: If an ID matches, use the memory version (it might have enriched metadata like 'playback' or 'work_id').
        """
        disk_map = {}
        for msg in (disk_history or []):
            key = self._history_message_key(msg)
            if key:
                disk_map[key] = msg
        
        memory_map = {}
        for msg in (memory_history or []):
            key = self._history_message_key(msg)
            if key:
                memory_map[key] = msg
                
        # Build merged result:
        # 1. All disk keys (with memory replacement if available)
        # 2. Any new memory keys
        merged = []
        seen_keys = set()
        
        # Keep disk order
        for msg in (disk_history or []):
            key = self._history_message_key(msg)
            if key in memory_map:
                merged.append(memory_map[key])
            else:
                merged.append(msg)
            seen_keys.add(key)
            
        # Append new ones from memory
        for msg in (memory_history or []):
            key = self._history_message_key(msg)
            if key not in seen_keys:
                merged.append(msg)
                seen_keys.add(key)
                
        return merged

    def _save_session(self, session: Session):
        """
        Enqueues a session save task. This is non-blocking.
        """
        try:
            if self._is_transient_runtime_session(session):
                return
            
            # Create a snapshot of the session to avoid race conditions during async write
            # (only history and context need to be stable)
            session_snapshot = session.to_dict()
            self._session_writer_queue.put((session.session_id, session_snapshot))
        except Exception as e:
            logger.error(f"Error enqueuing session save {session.session_id}: {e}")

    def _session_writer_loop(self):
        """
        Background loop to process session saves sequentially.
        """
        while True:
            try:
                session_id, session_data = self._session_writer_queue.get()
                self._process_save_session_logic(session_id, session_data)
                self._session_writer_queue.task_done()
            except Exception as e:
                logger.error(f"Error in SessionWriter loop: {e}")
                time.sleep(1)

    def _process_save_session_logic(self, session_id: str, session_data: Dict[str, Any]):
        """
        Actual persistence logic moved from _save_session.
        """
        try:
            lock = self._get_or_create_session_lock(session_id)
            with lock:
                sess_dir = os.path.join(self.sessions_dir, session_id)
                os.makedirs(sess_dir, exist_ok=True)
                
                chat_file_path = os.path.join(sess_dir, "chat.json")
                context_history = session_data.get("history", [])
                disk_history: List[Dict] = self._load_chat_history_resilient(chat_file_path, session_id)

                merged_chat_history = self._merge_chat_history_append_only(disk_history, context_history)
                self._atomic_write_json(chat_file_path, merged_chat_history)

                # Save recent mutable AI context to session.json
                file_path = os.path.join(sess_dir, "session.json")
                
                # Keep only the last 50 messages in session.json
                session_data["history"] = context_history[-50:] if len(context_history) > 50 else context_history
                
                self._atomic_write_json(file_path, session_data)
                
                # Update Index (lightweight check)
                if hasattr(self, 'index_manager'):
                    # Search for the session object in memory if available, 
                    # or just skip index update for background writes if duplicate.
                    pass 
        except Exception as e:
            logger.error(f"Error processing session save logic for {session_id}: {e}")

    def _load_session(self, session_id: str) -> Optional[Session]:
        try:
            file_path = os.path.join(self.sessions_dir, session_id, "session.json")
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                session_history = data.get("history", [])
                if not isinstance(session_history, list):
                    session_history = []

                # Validate/repair chat timeline file if it exists (context still comes from session.json).
                chat_file_path = os.path.join(self.sessions_dir, session_id, "chat.json")
                if os.path.exists(chat_file_path):
                    _ = self._load_chat_history_resilient(chat_file_path, session_id)
                else:
                    # Self-heal missing chat.json using session.json history snapshot.
                    try:
                        self._atomic_write_json(chat_file_path, session_history)
                        logger.warning(f"chat.json was missing for {session_id}; recreated from session.json history.")
                    except Exception as e:
                        logger.error(f"Failed to recreate missing chat.json for {session_id}: {e}")

                # Context source of truth remains session.json.
                data["history"] = session_history
                return Session.from_dict(data)
        except Exception as e:
            logger.error(f"Error loading session {session_id}: {e}")
        return None

    def _format_response(self, text, channel):
        """Adapts response formatting to the output channel.
        Currently delegates formatting to the drivers, returning raw markdown."""
        if not text: return text
        
        # Web/Portal/System/Telegram all receive raw Markdown. Default driver behavior 
        # is expected to normalize it to the platform.
        return text

    @staticmethod
    def _detect_user_language(user_input: str, fallback: str = "en") -> str:
        text = str(user_input or "").strip().lower()
        if not text:
            return fallback

        pt_markers = [
            " você ", " voce ", " para ", " tarefa ", " criar ", "agendar", "hoje", "amanhã", "amanha",
            "obrigado", "precisa", "pode", "quero", "como", "porque", "talvez", "melhor", "resumo",
            "não", "nao", "ção", "ções", "ç",
        ]
        en_markers = [
            " you ", " task ", "create ", "schedule", "today", "tomorrow", "please", "should", "could",
            "would", "summary", "report", "why", "how", "what",
        ]

        padded = f" {text} "
        pt_hits = sum(1 for m in pt_markers if m in padded)
        en_hits = sum(1 for m in en_markers if m in padded)

        # Strong lexical cues for short colloquial PT-BR messages.
        pt_strong_patterns = [
            r"\b(oi|olá|ola|opa|eai|blz|beleza)\b",
            r"\b(toca|tocar|reproduz|reproduzir|pausa|pausar|pr[oó]xima|proxima)\b",
            r"\b(m[uú]sica|musica|faixa|cantor|artista)\b",
            r"\b(me passa|me manda|quero|pode|por favor)\b",
        ]
        en_strong_patterns = [
            r"\b(hello|hi|hey)\b",
            r"\b(play|pause|resume|next)\b",
            r"\b(song|track|artist)\b",
            r"\b(please|can you|could you|would you)\b",
        ]
        if any(re.search(pattern, text) for pattern in pt_strong_patterns):
            pt_hits += 2
        if any(re.search(pattern, text) for pattern in en_strong_patterns):
            en_hits += 2

        if pt_hits > en_hits:
            return "pt-BR"
        if en_hits > pt_hits:
            return "en"
        return fallback

    @staticmethod
    def _normalize_locale(language: str, fallback: str = "en") -> str:
        value = str(language or fallback or "en").strip().replace("_", "-")
        lowered = value.lower()
        if lowered.startswith("pt"):
            return "pt-BR"
        if lowered.startswith("en"):
            return "en"
        return fallback

    def _session_locale(self, session: Optional[Session], fallback: str = "en") -> str:
        if not session or not isinstance(getattr(session, "context", None), dict):
            return fallback
        return self._normalize_locale(str(session.context.get("user_language") or fallback), fallback=fallback)

    def _t(self, session: Optional[Session], key: str, **kwargs: Any) -> str:
        return self.i18n.t(key, locale=self._session_locale(session), **kwargs)

    @staticmethod
    def _looks_like_technical_text(text: str) -> bool:
        value = (text or "").strip().lower()
        if not value:
            return False
        if re.search(
            r"\b(?:system|browser|youtube|deezer|spotify|weather|maps|memory|task|vision|web)\.[a-z0-9_]+\.[a-z0-9_]+\b",
            value,
        ):
            return True
        markers = (
            "executed successfully",
            "completed with status",
            "status=success",
            "result of action",
            "browser media control",
        )
        return any(marker in value for marker in markers)

    def _build_contextual_start_ack(self, session: Optional[Session], action_id: str, action_args: Optional[Dict[str, Any]] = None) -> str:
        args = action_args if isinstance(action_args, dict) else {}
        action = str(action_id or "").strip().lower()


        if action in {"system.control.screenshot", "vision.analyze"}:
            return "Understood, capturing the screen now."

        return self._t(session, "ack.work_started")

    def build_work_start_ack(
        self,
        session: Optional[Session],
        action_id: str,
        explicit_text: str = "",
        action_args: Optional[Dict[str, Any]] = None,
    ) -> str:
        cleaned = str(explicit_text or "").strip()
        if cleaned and not self._looks_like_success_claim(cleaned) and not self._looks_like_technical_text(cleaned):
            return self._enforce_response_language(session, cleaned)
        return self._enforce_response_language(
            session,
            self._build_contextual_start_ack(session, action_id, action_args=action_args),
        )

    def _build_proactive_reasoning_chunk(self, session: Optional[Session], plan: ActionPlan) -> str:
        action = str(getattr(plan, "action_id", "") or "").strip()
        if not action:
            return "Processing next step."

        locale = self._session_locale(session, fallback="en")
        is_pt = locale.lower().startswith("pt")

        if action == "reply":
            return "Preparando resposta final." if is_pt else "Preparing final response."
        if action == "error":
            return "Tratando erro e ajustando plano." if is_pt else "Handling error and adjusting plan."

        if is_pt:
            return f"Executando: {action}"
        return f"Executing: {action}"

    def get_initial_intent(self, user_input: str, session_id: str = "default", user_data: dict = None, context: PrincipalContext = None, attachments: List[str] = None, name: str = "") -> tuple[Optional[ActionPlan], Optional[str], Any]:
        """
        Runs initial intent resolution using the configured chain (LLM-only).
        Returns (ActionPlan, ReflexResponse_DEPRECATED, Session).
        """
        lock = self._get_or_create_session_lock(session_id)

        # 1. Session Retrieval & Initialization
        with lock:
            session = self.get_session_robust(session_id)
            if not session:
                # Infer interface from session_id
                interface = "web"
                if session_id.startswith("telegram"): interface = "telegram"
                elif session_id.startswith("voice"): interface = "voice"
                session = self.create_session(session_id, interface=interface, name=name)

            if user_data:
                session.context.update(user_data)

            session.context["user_language"] = self._detect_user_language(
                user_input,
                fallback=str(session.context.get("user_language") or "en"),
            )

            # Persist principal identity context on session to drive per-user prompt filtering.
            if context:
                session.context["principal_context"] = context.model_dump()
            
            # Save attachments to session context for prompt visibility
            session.context['last_attachments'] = attachments or []
            
            # Fresh Start: If previous turn was a reply, ensure state is clean
            if session.state_summary.get('goal') == "Standby/Listening" or not session.history:
                self._cleanup_session_state(session)
        
        # 2. Access Control: Pre-LLM Gate (Outside lock where possible if it's only read-only or doesn't mutate session)
        if context:
            allowed, reason = self.access_controller.pre_llm_gate(context)
            if not allowed:
                # Return a special plan for blocked access
                return ActionPlan(action_id='reply', args={}, response_text=reason, source='access_control'), None, session
        
        # 3. Resolution Chain (LLM-only) - NO LOCK HELD
        with lock:
            allowed_actions = self._get_allowed_actions_for_session(session)
        
        res_context = {
            "session": session,
            "system_prompt": self._construct_system_prompt(session, user_input=user_input),
            "attachments": attachments,
            "allowed_actions": allowed_actions,
            "skill_registry": self.skill_registry,
        }
        
        try:
            # LLM CALL - NO LOCK HELD
            plan = self.intent_resolver_chain.resolve(user_input, res_context)
            return plan, None, session
        except Exception as e:
            logger.error(f"Error in initial resolution: {e}")
            return None, None, session

    def _auto_name_session(self, session: Session, first_user_input: str):
        """Asynchronously generates a name for a new web session using the LLM."""
        try:
            logger.info(f"Generating auto-name for session {session.session_id} based on: '{first_user_input[:50]}...'")
            prompt = f"Generate a VERY SHORT title (2 to 4 words maximum) summarizing what the user wants to discuss. Reply ONLY with the title and nothing else.\n\nUser: {first_user_input}"
            
            # Use generate_intent from Kernel's LLM Manager
            intent = self.llm_manager.generate_intent(
                user_input=prompt,
                history=[],
                system_prompt="You are an assistant that assigns titles to conversations based on the user's first input. Keep the title very short. Reply ONLY with a 2-to-4-word title."
            )
            
            generated_name = intent.response_text or intent.thought or ""
            
            # Clean up potential quotes
            generated_name = generated_name.replace('"', '').replace("'", "").strip()
            
            if generated_name and len(generated_name) < 40:
                session.name = generated_name
                session.name_generated = True
                
                # Persist
                self._save_session(session)
                
                # Notify UI of the update
                global_event_bus.emit_threadsafe({
                    "type": "session_updated",
                    "session_id": session.session_id,
                    "name": session.name
                })
                logger.info(f"Auto-named session {session.session_id} to: {session.name}")
        except Exception as e:
            logger.error(f"Error auto-naming session {session.session_id}: {e}")

    def process(self, user_input: str, session_id: str = "default", on_partial_response=None, user_data: dict = None, callbacks: dict = None, cancel_check: Callable[[], bool] = None, initial_plan: ActionPlan = None, context: PrincipalContext = None, attachments: List[str] = None, work_id: str = None):
        """
        Agentic Loop: Input -> Loop [Reason -> Act -> Observe] -> Response
        """
        run_id = f"run-{str(uuid.uuid4())[:8]}"
        if not work_id:
            work_id = f"work-{str(uuid.uuid4())[:8]}"
            
        log_extra = {
            "session_id": session_id,
            "job_id": work_id,
            "run_id": run_id,
            "step_id": 0
        }

        logger.debug(f"Processing input in session '{session_id}' [Work: {work_id}, Run: {run_id}]: {user_input}", extra=log_extra)
        turn_started_at = time.perf_counter()
        lock_wait_ms = 0
        loops = 0
        last_action_id = None

        # Get or Create Session
        session = self.get_session_robust(session_id)
        
        # Get or create session lock (reentrant).
        lock = self._get_or_create_session_lock(session_id)
        
        # P1: Session turn-level lock removed to prevent blocking main thread / looping locks.
        # We now use granular 'with lock' blocks for state updates inside the loop.
        
        try:
            # Check for cancellation before starting the loop (cooperative)
            if cancel_check and cancel_check():
                logger.info(f"Task for session {session_id} was cancelled before starting.")
                return None
            
                # 1. Protect session initialization
                with lock:
                    # Re-fetch session ensuring it's not None
                    if not session:
                        transient_requested = bool((user_data or {}).get("transient_session"))
                        worker_run = bool((user_data or {}).get("__worker_run"))
                        if transient_requested:
                            session = Session(session_id, source="system")
                            session.context["__transient_session"] = True
                        elif worker_run:
                            logger.error(
                            "Worker attempted to process without existing session '%s'. Blocking implicit session creation.",
                            session_id,
                            )
                            return self.i18n.t("reply.worker_session_missing", locale="en")
                        else:
                            interface = "web"
                            if session_id.startswith("telegram"): interface = "telegram"
                        elif session_id.startswith("voice"): interface = "voice"
                        session = self.create_session(session_id, interface=interface)

                        session.last_interaction = time.time()
                        if user_data:
                            session.context.update(user_data)
                            session.context["user_language"] = self._detect_user_language(
                            user_input,
                            fallback=str(session.context.get("user_language") or "en"),
                            )
                            if context:
                                session.context["principal_context"] = context.model_dump()
                    
                                # Trigger auto-naming for web sessions on first user messages
                                if session.source == "web" and not session.name_generated and len(session.history) <= 3:
                                    threading.Thread(target=self._auto_name_session, args=(session, user_input), daemon=True).start()
                
                                    plan = initial_plan

                                    # HITL pending action resumption
                                    if session.pending_action:
                                        pending = session.pending_action if isinstance(session.pending_action, dict) else {}
                                        pending_work_id = str(pending.get("work_id") or "").strip()
                                        normalized = (user_input or "").strip().lower()
                                        is_yes = normalized in {"yes", "y", "ok", "approve", "autorizo", "sim", "s", "pode", "confirm"}
                                        is_no = normalized in {"no", "n", "deny", "deny.", "cancel", "cancelar", "nao", "não", "recusar"}

                                        if pending_work_id:
                                            kernel = getattr(self, "kernel", None)
                                            scheduler = getattr(kernel, "scheduler", None)
                                            if scheduler and (is_yes or is_no):
                                                scheduler.push_work_command(
                                                pending_work_id,
                                                "approve" if is_yes else "deny",
                                                payload={"note": user_input},
                                                source_session_id=session_id,
                                                )
                                                session.pending_action = None
                                                session.add_message("user", user_input, work_id=work_id)
                                                self._save_session(session)
                                                return self._t(session, "reply.decision_forwarded")
                                                if scheduler:
                                                    return self._t(session, "reply.waiting_approval_yes_no")

                                                    if is_yes:
                                                        resumed_action_id = str(pending.get("action") or "").strip()
                                                        resumed_params = pending.get("params") if isinstance(pending.get("params"), dict) else {}
                                                        if resumed_action_id:
                                                            logger.info(f"User authorized pending action: {resumed_action_id}")
                                                            session.pending_action = None
                                                            session.add_message("user", user_input, work_id=work_id)
                                                            plan = ActionPlan(
                                                            action_id=resumed_action_id,
                                                            args=resumed_params,
                                                            confidence=1.0,
                                                            source="internal",
                                                            thought=f"User approved pending sensitive action '{resumed_action_id}'.",
                                                            )
                                                        elif is_no:
                                                            session.pending_action = None
                                                            session.add_message("user", user_input, work_id=work_id)
                                                            return self._t(session, "reply.canceled_sensitive_action")

                                                            planner_cfg = self._get_planner_config()
                                                            prompt_cfg = self.config_manager.get("prompt_context", {}) if hasattr(self, "config_manager") else {}
                                                            max_steps = self._compute_dynamic_max_steps(user_input, plan)
                                                            replan_budget = max(1, min(2, planner_cfg.get("replan_budget", 2)))
                                                            replans_used = 0
        
                                                            # 1. Start dynamic reasoning loop (supports long tasks with replanning).
                                                            # User message persistence is now handled by Kernel.process_input
                                                            # to cover all paths (Quick and Worker).
                
                                                            loops = 0
                                                            previous_actions = []
                                                            repeated_failure_count = 0
                                                            last_failure_signature = None
                                                            last_action_status = None
                                                            last_action_reason = None
                                                            last_action_id = None
                                                            last_action_output = None
                                                            last_action_structured: Optional[Dict[str, Any]] = None
                                                            last_success_action_id = None
                                                            last_success_output = None
                                                            last_success_structured: Optional[Dict[str, Any]] = None
                                                            last_generated_attachment_paths: List[str] = []
                                                            browser_open_recovery_attempts = 0
                                                            browser_control_recovery_attempts = 0
                                                            no_plan_global_retry_attempts = 0
                                                            final_response = self._t(session, "reply.step_budget_exceeded")
                                                            final_structured_attachments = None
                                                            final_response_persisted = False
                                                            final_response_streamed = False
                                                            stream_completed = False
                                                            paused = False
                                                            actions_used: List[str] = []
                                                            skills_used: List[str] = []
                                                            media_used: List[str] = []
                                                            sources_used: List[Dict[str, Any]] = []
                                                            queued_messages: List[str] = []
                                                            feedback_cfg = self.config_manager.get("work_feedback", {}) if hasattr(self, "config_manager") else {}
                                                            progress_feedback_enabled = bool(feedback_cfg.get("progress_updates_enabled", False))
                                                            emitted_progress_events: set[str] = set()
        
                                                            def current_step_title() -> str:
                                                                if not planner_tree:
                                                                    return "current step"
                                                                    current = next((s for s in planner_tree if s.get("status") == "in_progress"), None)
                                                                    title = str((current or {}).get("title") or "").strip()
                                                                    if title:
                                                                        return title
                                                                        return "current step"

                                                                        def has_unfinished_planner_steps() -> bool:
                                                                            return self._planner_has_unfinished(planner_tree)
        
                                                                            def progress_note(event: str, action_id: Optional[str] = None) -> str:
                                                                                step = current_step_title()
                                                                                if event == "replan":
                                                                                    return f"Detected repetition in step '{step}'. Adjusting strategy with an alternate path."
                                                                                    if event == "failure_recovery":
                                                                                        return f"I found an issue in step '{step}' and applied a fix."
                                                                                        if event == "fallback":
                                                                                            label = action_id or "fallback action"
                                                                                            return f"Fallback triggered at step '{step}' via '{label}'."
                                                                                            return ""
        
                                                                                            def emit_user_progress(note: str, event_key: Optional[str] = None):
                                                                                                if not progress_feedback_enabled:
                                                                                                    return
                                                                                                    if session.pending_action:
                                                                                                        return
                                                                                                        if event_key:
                                                                                                            if event_key in emitted_progress_events:
                                                                                                                return
                                                                                                                emitted_progress_events.add(event_key)
                                                                                                                text = str(note or "").strip()
                                                                                                                if not text:
                                                                                                                    return
                                                                                                                    if callbacks and "send_status" in callbacks:
                                                                                                                        callbacks["send_status"]("thinking", {"message": text, "kind": "progress"})
        
                                                                                                                        planner_tree = self._normalize_plan_tree(plan.metadata.get("plan")) if (plan and isinstance(plan.metadata, dict)) else []
                                                                                                                        if planner_tree:
                                                                                                                            with lock:
                                                                                                                                session.context["planner_tree"] = planner_tree
                                                                                                                                session.plan = self._flatten_plan_lines(planner_tree)
                                                                                                                                session.state_summary["cursor"] = self._progress_cursor(planner_tree, loops, max_steps)
        
                                                                                                                                self._touch_work_context(
                                                                                                                                work_id,
                                                                                                                                {
                                                                                                                                "summary": {
                                                                                                                                "goal": session.state_summary.get("goal") or "Task execution",
                                                                                                                                "status": "running",
                                                                                                                                "cursor": session.state_summary.get("cursor"),
                                                                                                                                },
                                                                                                                                "planner": {
                                                                                                                                "max_steps": max_steps,
                                                                                                                                "replan_budget": replan_budget,
                                                                                                                                "replans_used": replans_used,
                                                                                                                                "steps": session.context.get("planner_tree", []),
                                                                                                                                },
                                                                                                                                "data": {
                                                                                                                                "actions_used": [],
                                                                                                                                "skills_used": [],
                                                                                                                                "media_used": [],
                                                                                                                                "sources_used": [],
                                                                                                                                "queued_messages": [],
                                                                                                                                },
                                                                                                                                },
                                                                                                                                )
        
                                                                                                                                # 2. Start dynamic reasoning loop (supports long tasks with replanning).
                                                                                                                                # LLM calls (resolution) happen OUTSIDE the session lock.
                                                                                                                                while loops < max_steps:
                                                                                                                                    if cancel_check and cancel_check():
                                                                                                                                        logger.info(f"Process cancelled for session {session_id}")
                                                                                                                                        self._touch_work_context(work_id, {"summary": {"status": "cancelled"}})
                                                                                                                                        return "Task canceled by user."
                                                                                                                                        if work_id:
                                                                                                                                            kernel = getattr(self, "kernel", None)
                                                                                                                                            scheduler = getattr(kernel, "scheduler", None) if kernel else None
                                                                                                                                            if scheduler:
                                                                                                                                                pending_commands = scheduler.pop_work_commands(work_id)
                                                                                                                                                for cmd in pending_commands:
                                                                                                                                                    name = str(cmd.get("command") or "").strip().lower()
                                                                                                                                                    payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}
                                                                                                                                                    if name == "cancel":
                                                                                                                                                        logger.info(f"Received cancel command for work {work_id}")
                                                                                                                                                        self._touch_work_context(work_id, {"summary": {"status": "cancelled"}})
                                                                                                                                                        return "Task canceled by external command."
                                                                                                                                                        if name == "pause":
                                                                                                                                                            paused = True
                                                                                                                                                            scheduler.update_work_status(work_id, WorkStatus.PAUSED)
                                                                                                                                                            self._touch_work_context(work_id, {"summary": {"status": "paused"}})
                                                                                                                                                            if name == "resume":
                                                                                                                                                                paused = False
                                                                                                                                                                scheduler.update_work_status(work_id, WorkStatus.RUNNING)
                                                                                                                                                                self._touch_work_context(work_id, {"summary": {"status": "running"}})
                                                                                                                                                                if name == "inject_message":
                                                                                                                                                                    note = str(payload.get("message") or "").strip()
                                                                                                                                                                    if note:
                                                                                                                                                                        queued_messages.append(note)
                                                                                                                                                                        session.add_message("user", f"[Injected message] {note}", work_id=work_id)
                                                                                                                                                                        plan = None
                                                                                                                                                                        if name == "update_context":
                                                                                                                                                                            patch = payload.get("patch")
                                                                                                                                                                            if isinstance(patch, dict):
                                                                                                                                                                                with lock:
                                                                                                                                                                                    session.context.update(patch)
                                                                                                                                                                                    self._touch_work_context(work_id, {"data": {"last_context_patch": patch}})
                                                                                                                                                                                    if paused:
                                                                                                                                                                                        if callbacks and 'send_status' in callbacks:
                                                                                                                                                                                            callbacks['send_status']('thinking', {'code': 'paused', 'message': 'Work is paused. Waiting for resume command.'})
                                                                                                                                                                                            time.sleep(0.8)
                                                                                                                                                                                            continue
                                                                                                                                                                                            loops += 1
                                                                                                                                                                                            log_extra["step_id"] = loops
                                                                                                                                                                                            logger.info(f"--- Session {session_id} | Loop {loops}/{max_steps} ---")
                
                                                                                                                                                                                            if on_partial_response and loops % 3 == 0: 
                                                                                                                                                                                            on_partial_response(f"Refining reasoning (Step {loops}/{max_steps})...")
                                                                                                                                                                                            if not plan:
                                                                                                                                                                                                thinking_label = self.i18n.t("status.thinking_next_action", locale=self._session_locale(session))
                                                                                                                                                                                                if callbacks and 'send_status' in callbacks:
                                                                                                                                                                                                    callbacks['send_status']('thinking', {'step': loops, 'max_steps': max_steps, 'label': thinking_label})
                    
                                                                                                                                                                                                    # Emit global event for real-time synchronization
                                                                                                                                                                                                    global_event_bus.emit_threadsafe({
                                                                                                                                                                                                    "type": "status",
                                                                                                                                                                                                    "session_id": session_id,
                                                                                                                                                                                                    "phase": "thinking",
                                                                                                                                                                                                    "message": thinking_label,
                                                                                                                                                                                                    "payload": {'step': loops, 'max_steps': max_steps}
                                                                                                                                                                                                    })
                                                                                                                                                                                                    # Apply dynamic context limits for history retrieval
                                                                                                                                                                                                    active_config = self.llm_manager.get_active_config()
                                                                                                                                                                                                    max_context = int(active_config.get("max_context", 8000))
                                                                                                                                                                                                    # For reasoning loops, we reserve more space for reasoning/output (50%)
                                                                                                                                                                                                    reasoning_history_budget = int(max_context * 0.5)
                                                                                                                                                                                                    with lock:
                                                                                                                                                                                                        reasoning_context = {
                                                                                                                                                                                                        "session": session,
                                                                                                                                                                                                        "system_prompt": self._construct_system_prompt(session, user_input=user_input),
                                                                                                                                                                                                        "attachments": attachments if loops == 1 else None, # Only send attachments on first reasoning step
                                                                                                                                                                                                        "history": session.get_context_for_llm(limit_msgs=20, limit_tokens=reasoning_history_budget),
                                                                                                                                                                                                        "allowed_actions": self._get_allowed_actions_for_session(session),
                                                                                                                                                                                                        "skill_registry": self.skill_registry,
                                                                                                                                                                                                        }
                    
                                                                                                                                                                                                        # LLM CALL - NO LOCK HELD
                                                                                                                                                                                                        plan = self.intent_resolver_chain.resolve(user_input, reasoning_context)
                                                                                                                                                                                                        if not plan:
                                                                                                                                                                                                            logger.warning("No plan resolved. Breaking loop.")
                                                                                                                                                                                                            if has_unfinished_planner_steps() and no_plan_global_retry_attempts < 1:
                                                                                                                                                                                                                no_plan_global_retry_attempts += 1
                                                                                                                                                                                                                logger.warning(
                                                                                                                                                                                                                "No-plan with unfinished global steps. Retrying planning once before concluding."
                                                                                                                                                                                                                )
                                                                                                                                                                                                                continue
                                                                                                                                                                                                                recovered_reply = self._reply_from_last_success(
                                                                                                                                                                                                                action_id=last_action_id,
                                                                                                                                                                                                                structured_result=last_action_structured,
                                                                                                                                                                                                                raw_output=last_action_output,
                                                                                                                                                                                                                language=self._session_locale(session),
                                                                                                                                                                                                                ) if last_action_status == "success" else None
                                                                                                                                                                                                                if not recovered_reply and last_success_action_id:
                                                                                                                                                                                                                    recovered_reply = self._reply_from_last_success(
                                                                                                                                                                                                                    action_id=last_success_action_id,
                                                                                                                                                                                                                    structured_result=last_success_structured,
                                                                                                                                                                                                                    raw_output=last_success_output,
                                                                                                                                                                                                                    language=self._session_locale(session),
                                                                                                                                                                                                                    )
                                                                                                                                                                                                                    final_response = recovered_reply or self.i18n.t("reply.no_plan_resolved", locale="en")
                                                                                                                                                                                                                    if callbacks and 'send_status' in callbacks:
                                                                                                                                                                                                                        callbacks['send_status'](
                                                                                                                                                                                                                        'error',
                                                                                                                                                                                                                        {
                                                                                                                                                                                                                        'code': 'no_plan',
                                                                                                                                                                                                                        'message': final_response,
                                                                                                                                                                                                                        'action': last_action_id or "",
                                                                                                                                                                                                                        }
                                                                                                                                                                                                                        )
                                                                                                                                                                                                                        break
                                                                                                                                                                                                                        if isinstance(plan.metadata, dict) and plan.metadata.get("plan"):
                                                                                                                                                                                                                            candidate = self._normalize_plan_tree(plan.metadata.get("plan"))
                                                                                                                                                                                                                            if candidate:
                                                                                                                                                                                                                                with lock:
                                                                                                                                                                                                                                    planner_tree = candidate
                                                                                                                                                                                                                                    session.context["planner_tree"] = planner_tree
                                                                                                                                                                                                                                    session.plan = self._flatten_plan_lines(planner_tree)
                                                                                                                                                                                                                                    session.state_summary["cursor"] = self._progress_cursor(planner_tree, loops, max_steps)
                                                                                                                                                                                                                                    # Update state from plan metadata if available
                                                                                                                                                                                                                                    if plan.metadata and 'state_summary' in plan.metadata:
                                                                                                                                                                                                                                        with lock:
                                                                                                                                                                                                                                            session.state_summary.update(plan.metadata['state_summary'])
                                                                                                                                                                                                                                            if planner_tree:
                                                                                                                                                                                                                                                with lock:
                                                                                                                                                                                                                                                    active = next((s for s in planner_tree if s.get("status") == "in_progress"), None)
                                                                                                                                                                                                                                                    if not active:
                                                                                                                                                                                                                                                        pending = next((s for s in planner_tree if s.get("status") == "pending"), None)
                                                                                                                                                                                                                                                        if pending:
                                                                                                                                                                                                                                                            pending["status"] = "in_progress"
                                                                                                                                                                                                                                                            session.plan = self._flatten_plan_lines(planner_tree)
                                                                                                                                                                                                                                                            session.state_summary["cursor"] = self._progress_cursor(planner_tree, loops, max_steps)
                                                                                                                                                                                                                                                        else:
                                                                                                                                                                                                                                                            if not session.state_summary.get("cursor"):
                                                                                                                                                                                                                                                                with lock:
                                                                                                                                                                                                                                                                    session.state_summary["cursor"] = f"{loops}/{max_steps} (loop: executing)"
                                                                                                                                                                                                                                                                    # Always keep overwatch metadata updated, even when no explicit planner tree is returned.
                                                                                                                                                                                                                                                                    self._touch_work_context(
                                                                                                                                                                                                                                                                    work_id,
                                                                                                                                                                                                                                                                    {
                                                                                                                                                                                                                                                                    "planner": {
                                                                                                                                                                                                                                                                    "max_steps": max_steps,
                                                                                                                                                                                                                                                                    "replan_budget": replan_budget,
                                                                                                                                                                                                                                                                    "replans_used": replans_used,
                                                                                                                                                                                                                                                                    "steps": planner_tree or [],
                                                                                                                                                                                                                                                                    },
                                                                                                                                                                                                                                                                    "summary": {
                                                                                                                                                                                                                                                                    "status": "running",
                                                                                                                                                                                                                                                                    "cursor": session.state_summary.get("cursor"),
                                                                                                                                                                                                                                                                    "last_action": plan.action_id,
                                                                                                                                                                                                                                                                    "last_thought": plan.thought or "",
                                                                                                                                                                                                                                                                    },
                                                                                                                                                                                                                                                                    "data": {
                                                                                                                                                                                                                                                                    "actions_used": actions_used[-80:],
                                                                                                                                                                                                                                                                    "skills_used": skills_used[-40:],
                                                                                                                                                                                                                                                                    "media_used": media_used[-80:],
                                                                                                                                                                                                                                                                    "sources_used": sources_used[-120:],
                                                                                                                                                                                                                                                                    "queued_messages": queued_messages[-40:],
                                                                                                                                                                                                                                                                    },
                                                                                                                                                                                                                                                                    },
                                                                                                                                                                                                                                                                    )
                                                                                                                                                                                                                                                                    # Normalize/repair action IDs to reduce "unknown action" loops.
                                                                                                                                                                                                                                                                    if plan.action_id not in ("reply", "error"):
                                                                                                                                                                                                                                                                        resolved_action = self.skill_registry.resolve_action_id(plan.action_id)
                                                                                                                                                                                                                                                                        if resolved_action and resolved_action != plan.action_id:
                                                                                                                                                                                                                                                                            logger.info(f"Resolved action alias: {plan.action_id} -> {resolved_action}")
                                                                                                                                                                                                                                                                            plan.action_id = resolved_action
                                                                                                                                                                                                                                                                        elif not self.skill_registry.get_skill_for_action(plan.action_id):
                                                                                                                                                                                                                                                                            parts = str(plan.action_id or "").strip().lower().split(".")
                                                                                                                                                                                                                                                                            legacy_removed = len(parts) >= 3 and parts[0] == "browser" and parts[1] in {"automator", "controller"}
                                                                                                                                                                                                                                                                            if legacy_removed:
                                                                                                                                                                                                                                                                                final_response = "Skill removed."
                                                                                                                                                                                                                                                                                logger.warning(
                                                                                                                                                                                                                                                                                "Removed browser skill requested: %s | returning SKILL_REMOVED_USE_BROWSER_CONTROL",
                                                                                                                                                                                                                                                                                plan.action_id,
                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                session.add_message(
                                                                                                                                                                                                                                                                                "system",
                                                                                                                                                                                                                                                                                "ERROR_CODE: SKILL_REMOVED_USE_BROWSER_CONTROL",
                                                                                                                                                                                                                                                                                msg_type="reasoning",
                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                plan = ActionPlan(
                                                                                                                                                                                                                                                                                action_id="error",
                                                                                                                                                                                                                                                                                args={"error_code": "SKILL_REMOVED_USE_BROWSER_CONTROL"},
                                                                                                                                                                                                                                                                                response_text=final_response,
                                                                                                                                                                                                                                                                                source="internal",
                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                continue
                                                                                                                                                                                                                                                                                suggestions = self.skill_registry.suggest_actions(plan.action_id, limit=3)
                                                                                                                                                                                                                                                                                suggestion_text = ", ".join(suggestions) if suggestions else "no suggestions"
                                                                                                                                                                                                                                                                                logger.warning(
                                                                                                                                                                                                                                                                                f"Unknown action from resolver: {plan.action_id} | suggestions: {suggestion_text}"
                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                final_response = (
                                                                                                                                                                                                                                                                                self._t(
                                                                                                                                                                                                                                                                                session,
                                                                                                                                                                                                                                                                                "reply.unknown_action_template",
                                                                                                                                                                                                                                                                                action_id=plan.action_id,
                                                                                                                                                                                                                                                                                suggestions=suggestion_text,
                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                plan = ActionPlan(
                                                                                                                                                                                                                                                                                action_id="reply",
                                                                                                                                                                                                                                                                                args={},
                                                                                                                                                                                                                                                                                response_text=final_response,
                                                                                                                                                                                                                                                                                source="internal",
                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                plan = self._apply_media_decision_policy(
                                                                                                                                                                                                                                                                                session=session,
                                                                                                                                                                                                                                                                                user_input=user_input,
                                                                                                                                                                                                                                                                                plan=plan,
                                                                                                                                                                                                                                                                                last_action_id=last_action_id,
                                                                                                                                                                                                                                                                                last_action_structured=last_action_structured,
                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                logger.info(f"Action: {plan.action_id} | Confidence: {plan.confidence}")
                                                                                                                                                                                                                                                                                if plan.action_id not in {"reply", "error"}:
                                                                                                                                                                                                                                                                                    actions_used.append(plan.action_id)
                                                                                                                                                                                                                                                                                    namespace = ".".join(plan.action_id.split(".")[:2]) if "." in plan.action_id else plan.action_id
                                                                                                                                                                                                                                                                                    if namespace not in skills_used:
                                                                                                                                                                                                                                                                                        skills_used.append(namespace)
                                                                                                                                                                                                                                                                                        # Short-circuit repeated semantic fallback loops:
                                                                                                                                                                                                                                                                                            # if the planner proposes the exact same one-shot action right
                                                                                                                                                                                                                                                                                            # after a successful execution, consolidate immediately instead
                                                                                                                                                                                                                                                                                            # of re-running the tool.
                                                                                                                                                                                                                                                                                            if (
                                                                                                                                                                                                                                                                                            last_action_status == "success"
                                                                                                                                                                                                                                                                                            and last_action_id == plan.action_id
                                                                                                                                                                                                                                                                                            and plan.action_id in {
                                                                                                                                                                                                                                                                                            "system.control.screenshot",
                                                                                                                                                                                                                                                                                            "system.control.time",
                                                                                                                                                                                                                                                                                            }
                                                                                                                                                                                                                                                                                            ):
                                                                                                                                                                                                                                                                                                last_ctx = session.context if isinstance(session.context, dict) else {}
                                                                                                                                                                                                                                                                                                last_plan = last_ctx.get("last_action_plan") if isinstance(last_ctx.get("last_action_plan"), dict) else {}
                                                                                                                                                                                                                                                                                                last_args = last_plan.get("args") if isinstance(last_plan.get("args"), dict) else {}
                                                                                                                                                                                                                                                                                                curr_args = plan.args if isinstance(plan.args, dict) else {}
                                                                                                                                                                                                                                                                                                same_args = (
                                                                                                                                                                                                                                                                                                json.dumps(last_args, sort_keys=True) == json.dumps(curr_args, sort_keys=True)
                                                                                                                                                                                                                                                                                                or not curr_args
                                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                                if same_args:
                                                                                                                                                                                                                                                                                                    recovered_reply = self._reply_from_last_success(
                                                                                                                                                                                                                                                                                                    action_id=last_action_id,
                                                                                                                                                                                                                                                                                                    structured_result=last_action_structured,
                                                                                                                                                                                                                                                                                                    raw_output=last_action_output,
                                                                                                                                                                                                                                                                                                    language=self._session_locale(session),
                                                                                                                                                                                                                                                                                                    )
                                                                                                                                                                                                                                                                                                    if recovered_reply:
                                                                                                                                                                                                                                                                                                        final_response = recovered_reply
                                                                                                                                                                                                                                                                                                        final_structured_attachments = self._standardize_attachments(
                                                                                                                                                                                                                                                                                                        session,
                                                                                                                                                                                                                                                                                                        last_generated_attachment_paths,
                                                                                                                                                                                                                                                                                                        ) if last_generated_attachment_paths else None
                                                                                                                                                                                                                                                                                                        session.add_message("assistant", final_response, attachments=final_structured_attachments, work_id=work_id)
                                                                                                                                                                                                                                                                                                        final_response_persisted = True
                                                                                                                                                                                                                                                                                                        with lock:
                                                                                                                                                                                                                                                                                                            session.scratchpad = ""
                                                                                                                                                                                                                                                                                                            session.plan = []
                                                                                                                                                                                                                                                                                                            if callbacks and 'send_response' in callbacks:
                                                                                                                                                                                                                                                                                                                callbacks['send_response'](
                                                                                                                                                                                                                                                                                                                final_response,
                                                                                                                                                                                                                                                                                                                is_chunk=True,
                                                                                                                                                                                                                                                                                                                attachments=final_structured_attachments,
                                                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                                                final_response_streamed = True
                                                                                                                                                                                                                                                                                                                if callbacks and 'send_complete' in callbacks:
                                                                                                                                                                                                                                                                                                                    callbacks['send_complete']()
                                                                                                                                                                                                                                                                                                                    stream_completed = True
                                                                                                                                                                                                                                                                                                                    break
                
                                                                                                                                                                                                                                                                                                                    # Notify Reasoning Chunk
                                                                                                                                                                                                                                                                                                                    ui_reasoning = self._build_proactive_reasoning_chunk(session, plan)
                                                                                                                                                                                                                                                                                                                    if callbacks and 'send_reasoning_chunk' in callbacks:
                                                                                                                                                                                                                                                                                                                        callbacks['send_reasoning_chunk'](ui_reasoning)
                
                                                                                                                                                                                                                                                                                                                        # Emit global event for real-time synchronization
                                                                                                                                                                                                                                                                                                                        global_event_bus.emit_threadsafe({
                                                                                                                                                                                                                                                                                                                        "type": "reasoning_chunk",
                                                                                                                                                                                                                                                                                                                        "session_id": session_id,
                                                                                                                                                                                                                                                                                                                        "content": ui_reasoning,
                                                                                                                                                                                                                                                                                                                        "timestamp": time.time()
                                                                                                                                                                                                                                                                                                                        })
                                                                                                                                                                                                                                                                                                                        # --- Repetitiveness Detection (Enhanced) ---
                                                                                                                                                                                                                                                                                                                        param_str = json.dumps(plan.args, sort_keys=True)
                                                                                                                                                                                                                                                                                                                        current_signature = (plan.action_id, param_str)
                                                                                                                                                                                                                                                                                                                        previous_actions.append(current_signature)
                                                                                                                                                                                                                                                                                                                        if len(previous_actions) > 5: previous_actions.pop(0)
                                                                                                                                                                                                                                                                                                                        if len(previous_actions) >= 3 and all(s == current_signature for s in previous_actions[-3:]):
                                                                                                                                                                                                                                                                                                                            if replans_used < replan_budget:
                                                                                                                                                                                                                                                                                                                                replans_used += 1
                                                                                                                                                                                                                                                                                                                                previous_actions = []
                                                                                                                                                                                                                                                                                                                                if callbacks and 'send_status' in callbacks:
                                                                                                                                                                                                                                                                                                                                    callbacks['send_status'](
                                                                                                                                                                                                                                                                                                                                    'executing',
                                                                                                                                                                                                                                                                                                                                    {
                                                                                                                                                                                                                                                                                                                                    'code': 'replan',
                                                                                                                                                                                                                                                                                                                                    'message': "Replanning due to repeated action with no progress.",
                                                                                                                                                                                                                                                                                                                                    'action': plan.action_id
                                                                                                                                                                                                                                                                                                                                    }
                                                                                                                                                                                                                                                                                                                                    )
                                                                                                                                                                                                                                                                                                                                    emit_user_progress(
                                                                                                                                                                                                                                                                                                                                    progress_note("replan", action_id=plan.action_id),
                                                                                                                                                                                                                                                                                                                                    event_key=f"replan:{plan.action_id}",
                                                                                                                                                                                                                                                                                                                                    )
                                                                                                                                                                                                                                                                                                                                    self._touch_work_context(
                                                                                                                                                                                                                                                                                                                                    work_id,
                                                                                                                                                                                                                                                                                                                                    {
                                                                                                                                                                                                                                                                                                                                    "planner": {
                                                                                                                                                                                                                                                                                                                                    "replans_used": replans_used,
                                                                                                                                                                                                                                                                                                                                    "replan_budget": replan_budget,
                                                                                                                                                                                                                                                                                                                                    "steps": planner_tree,
                                                                                                                                                                                                                                                                                                                                    },
                                                                                                                                                                                                                                                                                                                                    "summary": {"status": "replanning"},
                                                                                                                                                                                                                                                                                                                                    },
                                                                                                                                                                                                                                                                                                                                    )
                                                                                                                                                                                                                                                                                                                                    plan = None
                                                                                                                                                                                                                                                                                                                                    continue
                                                                                                                                                                                                                                                                                                                                    logger.warning(f"Loop detected (3 identical actions/params): {current_signature}. Breaking.")
                                                                                                                                                                                                                                                                                                                                    recovered_reply = self._reply_from_last_success(
                                                                                                                                                                                                                                                                                                                                    action_id=plan.action_id,
                                                                                                                                                                                                                                                                                                                                    structured_result=last_action_structured,
                                                                                                                                                                                                                                                                                                                                    raw_output=last_action_output,
                                                                                                                                                                                                                                                                                                                                    language=self._session_locale(session),
                                                                                                                                                                                                                                                                                                                                    ) if last_action_status == "success" else None
                                                                                                                                                                                                                                                                                                                                    if recovered_reply:
                                                                                                                                                                                                                                                                                                                                        if callbacks and 'send_status' in callbacks:
                                                                                                                                                                                                                                                                                                                                            loop_success_msg = (
                                                                                                                                                                                                                                                                                                                                            f"Repeated action detected in {plan.action_id}; consolidating final response using the latest valid result."
                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                            callbacks['send_status'](
                                                                                                                                                                                                                                                                                                                                            'executing',
                                                                                                                                                                                                                                                                                                                                            {
                                                                                                                                                                                                                                                                                                                                            'code': 'loop_break_success',
                                                                                                                                                                                                                                                                                                                                            'message': loop_success_msg,
                                                                                                                                                                                                                                                                                                                                            'action': plan.action_id
                                                                                                                                                                                                                                                                                                                                            }
                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                            final_response = recovered_reply
                                                                                                                                                                                                                                                                                                                                        else:
                                                                                                                                                                                                                                                                                                                                            loop_break_msg = (
                                                                                                                                                                                                                                                                                                                                            "Exact repetition detected without progress. Please rephrase your request or provide more details."
                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                            if callbacks and 'send_status' in callbacks:
                                                                                                                                                                                                                                                                                                                                                callbacks['send_status'](
                                                                                                                                                                                                                                                                                                                                                'error',
                                                                                                                                                                                                                                                                                                                                                {
                                                                                                                                                                                                                                                                                                                                                'code': 'loop_break',
                                                                                                                                                                                                                                                                                                                                                'message': loop_break_msg,
                                                                                                                                                                                                                                                                                                                                                'action': plan.action_id
                                                                                                                                                                                                                                                                                                                                                }
                                                                                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                                                                                final_response = loop_break_msg
                                                                                                                                                                                                                                                                                                                                                plan = ActionPlan(
                                                                                                                                                                                                                                                                                                                                                action_id='reply',
                                                                                                                                                                                                                                                                                                                                                args={},
                                                                                                                                                                                                                                                                                                                                                response_text=final_response,
                                                                                                                                                                                                                                                                                                                                                source='internal',
                                                                                                                                                                                                                                                                                                                                                attachments=(last_generated_attachment_paths or None),
                                                                                                                                                                                                                                                                                                                                                )
                
                                                                                                                                                                                                                                                                                                                                                # 2. Action Repetition (3 times in last 5 steps) - Soft Warning
                                                                                                                                                                                                                                                                                                                                                action_history = [s[0] for s in previous_actions]
                                                                                                                                                                                                                                                                                                                                                if action_history.count(plan.action_id) >= 3:
                                                                                                                                                                                                                                                                                                                                                    logger.info(f"Loop tendency detected for action '{plan.action_id}'.")
                                                                                                                                                                                                                                                                                                                                                    # 3. Action Repetition (4 times in last 5 steps) - Hard Break
                                                                                                                                                                                                                                                                                                                                                    if action_history.count(plan.action_id) >= 4:
                                                                                                                                                                                                                                                                                                                                                        if replans_used < replan_budget:
                                                                                                                                                                                                                                                                                                                                                            replans_used += 1
                                                                                                                                                                                                                                                                                                                                                            previous_actions = []
                                                                                                                                                                                                                                                                                                                                                            self._touch_work_context(
                                                                                                                                                                                                                                                                                                                                                            work_id,
                                                                                                                                                                                                                                                                                                                                                            {
                                                                                                                                                                                                                                                                                                                                                            "planner": {
                                                                                                                                                                                                                                                                                                                                                            "replans_used": replans_used,
                                                                                                                                                                                                                                                                                                                                                            "replan_budget": replan_budget,
                                                                                                                                                                                                                                                                                                                                                            "steps": planner_tree,
                                                                                                                                                                                                                                                                                                                                                            },
                                                                                                                                                                                                                                                                                                                                                            "summary": {"status": "replanning"},
                                                                                                                                                                                                                                                                                                                                                            },
                                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                                            emit_user_progress(
                                                                                                                                                                                                                                                                                                                                                            progress_note("replan", action_id=plan.action_id),
                                                                                                                                                                                                                                                                                                                                                            event_key=f"replan:{plan.action_id}:hard",
                                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                                            plan = None
                                                                                                                                                                                                                                                                                                                                                            continue
                                                                                                                                                                                                                                                                                                                                                            logger.warning(f"Action loop detected (Action '{plan.action_id}' repeated 4/5 times). Breaking.")
                                                                                                                                                                                                                                                                                                                                                            recovered_reply = self._reply_from_last_success(
                                                                                                                                                                                                                                                                                                                                                            action_id=plan.action_id,
                                                                                                                                                                                                                                                                                                                                                            structured_result=last_action_structured,
                                                                                                                                                                                                                                                                                                                                                            raw_output=last_action_output,
                                                                                                                                                                                                                                                                                                                                                            language=self._session_locale(session),
                                                                                                                                                                                                                                                                                                                                                            ) if last_action_status == "success" else None
                                                                                                                                                                                                                                                                                                                                                            if callbacks and 'send_status' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                callbacks['send_status'](
                                                                                                                                                                                                                                                                                                                                                                'error',
                                                                                                                                                                                                                                                                                                                                                                {
                                                                                                                                                                                                                                                                                                                                                                'code': 'loop_break',
                                                                                                                                                                                                                                                                                                                                                                'message': (
                                                                                                                                                                                                                                                                                                                                                                f"I seem to be stuck trying to use action '{plan.action_id}' repeatedly."
                                                                                                                                                                                                                                                                                                                                                                if recovered_reply else
                                                                                                                                                                                                                                                                                                                                                                f"I seem to be stuck trying to use action '{plan.action_id}' repeatedly without success. I will stop to avoid an infinite loop."
                                                                                                                                                                                                                                                                                                                                                                ),
                                                                                                                                                                                                                                                                                                                                                                'action': plan.action_id
                                                                                                                                                                                                                                                                                                                                                                }
                                                                                                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                                                                                                final_response = recovered_reply or f"I seem to be stuck trying to use action '{plan.action_id}' repeatedly without success. I will stop to avoid an infinite loop."
                                                                                                                                                                                                                                                                                                                                                                # For a hard break, we force a valid reply object for internal history consistency
                                                                                                                                                                                                                                                                                                                                                                plan = ActionPlan(
                                                                                                                                                                                                                                                                                                                                                                action_id='reply',
                                                                                                                                                                                                                                                                                                                                                                args={},
                                                                                                                                                                                                                                                                                                                                                                response_text=final_response,
                                                                                                                                                                                                                                                                                                                                                                source='internal',
                                                                                                                                                                                                                                                                                                                                                                attachments=(last_generated_attachment_paths or None),
                                                                                                                                                                                                                                                                                                                                                                )
                                                                                                                                                                                                                                                                                                                                                                plan.thought = "Action loop detected. Stopping to avoid excessive token and time usage."
                
                                                                                                                                                                                                                                                                                                                                                                # Add current turn to history for context.
                                                                                                                                                                                                                                                                                                                                                                # Prefer TOON compact encoding to reduce prompt footprint.
                                                                                                                                                                                                                                                                                                                                                                reasoning_mode = str(prompt_cfg.get("reasoning_history_mode", "toon")).strip().lower()
                                                                                                                                                                                                                                                                                                                                                                history_data = {
                                                                                                                                                                                                                                                                                                                                                                "thought": plan.thought,
                                                                                                                                                                                                                                                                                                                                                                "plan": plan.metadata.get('plan', []),
                                                                                                                                                                                                                                                                                                                                                                "action": plan.action_id,
                                                                                                                                                                                                                                                                                                                                                                "params": plan.args
                                                                                                                                                                                                                                                                                                                                                                }
                                                                                                                                                                                                                                                                                                                                                                if reasoning_mode in {"legacy", "json"}:
                                                                                                                                                                                                                                                                                                                                                                    history_entry = json.dumps(history_data, ensure_ascii=False, separators=(",", ":"))
                                                                                                                                                                                                                                                                                                                                                                else:
                                                                                                                                                                                                                                                                                                                                                                    history_entry = dumps_toon(
                                                                                                                                                                                                                                                                                                                                                                    encode_reasoning_step(
                                                                                                                                                                                                                                                                                                                                                                    thought=history_data.get("thought"),
                                                                                                                                                                                                                                                                                                                                                                    plan=history_data.get("plan"),
                                                                                                                                                                                                                                                                                                                                                                    action=history_data.get("action"),
                                                                                                                                                                                                                                                                                                                                                                    params=history_data.get("params"),
                                                                                                                                                                                                                                                                                                                                                                    )
                                                                                                                                                                                                                                                                                                                                                                    )
                                                                                                                                                                                                                                                                                                                                                                    session.add_message("assistant", history_entry, msg_type="reasoning", work_id=work_id)
                                                                                                                                                                                                                                                                                                                                                                    if plan.action_id == 'reply':
                                                                                                                                                                                                                                                                                                                                                                        final_response = self._ground_reply_against_last_result(
                                                                                                                                                                                                                                                                                                                                                                        response_text=plan.response_text or "",
                                                                                                                                                                                                                                                                                                                                                                        last_action_status=last_action_status,
                                                                                                                                                                                                                                                                                                                                                                        last_action_id=last_action_id,
                                                                                                                                                                                                                                                                                                                                                                        last_action_reason=last_action_reason,
                                                                                                                                                                                                                                                                                                                                                                        last_action_output=last_action_output,
                                                                                                                                                                                                                                                                                                                                                                        language=self._session_locale(session),
                                                                                                                                                                                                                                                                                                                                                                        )
                                                                                                                                                                                                                                                                                                                                                                        normalized_response = self._normalize_context_reset_reply(
                                                                                                                                                                                                                                                                                                                                                                        final_response,
                                                                                                                                                                                                                                                                                                                                                                        language=self._session_locale(session),
                                                                                                                                                                                                                                                                                                                                                                        )
                                                                                                                                                                                                                                                                                                                                                                        if normalized_response != final_response:
                                                                                                                                                                                                                                                                                                                                                                            with lock:
                                                                                                                                                                                                                                                                                                                                                                                if isinstance(session.context, dict):
                                                                                                                                                                                                                                                                                                                                                                                    metrics = session.context.get("metrics")
                                                                                                                                                                                                                                                                                                                                                                                    if not isinstance(metrics, dict):
                                                                                                                                                                                                                                                                                                                                                                                        metrics = {}
                                                                                                                                                                                                                                                                                                                                                                                        session.context["metrics"] = metrics
                                                                                                                                                                                                                                                                                                                                                                                        current = metrics.get("context_reset_reply_blocked", 0)
                                                                                                                                                                                                                                                                                                                                                                                        try:
                                                                                                                                                                                                                                                                                                                                                                                            current_value = int(current)
                                                                                                                                                                                                                                                                                                                                                                                        except Exception:
                                                                                                                                                                                                                                                                                                                                                                                            current_value = 0
                                                                                                                                                                                                                                                                                                                                                                                            metrics["context_reset_reply_blocked"] = current_value + 1
                                                                                                                                                                                                                                                                                                                                                                                            logger.info(
                                                                                                                                                                                                                                                                                                                                                                                            "Normalized context-reset reply for session %s (action=%s).",
                                                                                                                                                                                                                                                                                                                                                                                            session.session_id,
                                                                                                                                                                                                                                                                                                                                                                                            plan.action_id,
                                                                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                                                                            final_response = normalized_response
                                                                                                                                                                                                                                                                                                                                                                                            final_response = self.apply_conversation_coaching(session, user_input, final_response)
                    
                                                                                                                                                                                                                                                                                                                                                                                            # Process attachments
                                                                                                                                                                                                                                                                                                                                                                                            attachment_inputs = plan.attachments or last_generated_attachment_paths
                                                                                                                                                                                                                                                                                                                                                                                            structured_attachments = self._standardize_attachments(session, attachment_inputs) if attachment_inputs else None
                                                                                                                                                                                                                                                                                                                                                                                            if not final_response and structured_attachments:
                                                                                                                                                                                                                                                                                                                                                                                                final_response = "Here is the requested file."
                    
                                                                                                                                                                                                                                                                                                                                                                                                session.add_message("assistant", final_response, attachments=structured_attachments, work_id=work_id)
                                                                                                                                                                                                                                                                                                                                                                                                final_structured_attachments = structured_attachments
                                                                                                                                                                                                                                                                                                                                                                                                final_response_persisted = True
                                                                                                                                                                                                                                                                                                                                                                                                with lock:
                                                                                                                                                                                                                                                                                                                                                                                                    session.scratchpad = ""
                                                                                                                                                                                                                                                                                                                                                                                                    session.plan = []
                                                                                                                                                                                                                                                                                                                                                                                                    if callbacks and 'send_response' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                                                        callbacks['send_response'](final_response, is_chunk=True, attachments=structured_attachments)
                                                                                                                                                                                                                                                                                                                                                                                                        final_response_streamed = True
                            
                                                                                                                                                                                                                                                                                                                                                                                                        if callbacks and 'send_complete' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                                                            callbacks['send_complete']()
                                                                                                                                                                                                                                                                                                                                                                                                            stream_completed = True
                                                                                                                                                                                                                                                                                                                                                                                                            break
                                                                                                                                                                                                                                                                                                                                                                                                            if plan.action_id == 'error':
                                                                                                                                                                                                                                                                                                                                                                                                                if callbacks and 'send_status' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                                                                    callbacks['send_status'](
                                                                                                                                                                                                                                                                                                                                                                                                                    'error',
                                                                                                                                                                                                                                                                                                                                                                                                                    {
                                                                                                                                                                                                                                                                                                                                                                                                                    'code': 'action_error',
                                                                                                                                                                                                                                                                                                                                                                                                                    'message': self._t(
                                                                                                                                                                                                                                                                                                                                                                                                                    session,
                                                                                                                                                                                                                                                                                                                                                                                                                    "reply.error_during_processing",
                                                                                                                                                                                                                                                                                                                                                                                                                    details=(plan.thought or "unknown"),
                                                                                                                                                                                                                                                                                                                                                                                                                    ),
                                                                                                                                                                                                                                                                                                                                                                                                                    },
                                                                                                                                                                                                                                                                                                                                                                                                                    )
                    
                                                                                                                                                                                                                                                                                                                                                                                                                    # Break loop on planning error
                                                                                                                                                                                                                                                                                                                                                                                                                    final_response = self._t(session, "reply.error_during_processing", details=(plan.thought or "unknown"))
                                                                                                                                                                                                                                                                                                                                                                                                                    break
                                                                                                                                                                                                                                                                                                                                                                                                                    # --- Action Execution ---
                                                                                                                                                                                                                                                                                                                                                                                                                    if callbacks and 'send_status' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                                                                        callbacks['send_status']('executing', {'action': plan.action_id, 'label': f"Executing {plan.action_id}..."})
                                                                                                                                                                                                                                                                                                                                                                                                                        global_event_bus.emit_threadsafe({
                                                                                                                                                                                                                                                                                                                                                                                                                        "type": "status",
                                                                                                                                                                                                                                                                                                                                                                                                                        "session_id": session_id,
                                                                                                                                                                                                                                                                                                                                                                                                                        "phase": "executing",
                                                                                                                                                                                                                                                                                                                                                                                                                        "message": f"Executing {plan.action_id}...",
                                                                                                                                                                                                                                                                                                                                                                                                                        "payload": {'action': plan.action_id}
                                                                                                                                                                                                                                                                                                                                                                                                                        })
                                                                                                                                                                                                                                                                                                                                                                                                                        exec_context = {
                                                                                                                                                                                                                                                                                                                                                                                                                        "session": session,
                                                                                                                                                                                                                                                                                                                                                                                                                        "callbacks": callbacks,
                                                                                                                                                                                                                                                                                                                                                                                                                        "browser_driver": self.browser_driver,
                                                                                                                                                                                                                                                                                                                                                                                                                        "web_automation_driver": self.browser_driver,
                                                                                                                                                                                                                                                                                                                                                                                                                        "session_id": session_id,
                                                                                                                                                                                                                                                                                                                                                                                                                        "work_id": work_id,
                                                                                                                                                                                                                                                                                                                                                                                                                        "run_id": run_id,
                                                                                                                                                                                                                                                                                                                                                                                                                        "step_id": loops,
                                                                                                                                                                                                                                                                                                                                                                                                                        "touch_work_context": self._touch_work_context,
                                                                                                                                                                                                                                                                                                                                                                                                                        "user_input": user_input,
                                                                                                                                                                                                                                                                                                                                                                                                                        "allowed_actions": self._get_allowed_actions_for_session(session),
                                                                                                                                                                                                                                                                                                                                                                                                                        "skill_registry": self.skill_registry,
                                                                                                                                                                                                                                                                                                                                                                                                                        "playback_service": getattr(self, "playback_service", None),
                                                                                                                                                                                                                                                                                                                                                                                                                        }
                
                                                                                                                                                                                                                                                                                                                                                                                                                        # Skill execution outside session lock
                                                                                                                                                                                                                                                                                                                                                                                                                        if context:
                                                                                                                                                                                                                                                                                                                                                                                                                            allowed, reason = self.access_controller.pre_dispatch_gate(
                                                                                                                                                                                                                                                                                                                                                                                                                            context,
                                                                                                                                                                                                                                                                                                                                                                                                                            plan.action_id,
                                                                                                                                                                                                                                                                                                                                                                                                                            plan.args,
                                                                                                                                                                                                                                                                                                                                                                                                                            self.skill_registry,
                                                                                                                                                                                                                                                                                                                                                                                                                            self.config_manager
                                                                                                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                                                                                                            if not allowed:
                                                                                                                                                                                                                                                                                                                                                                                                                                result = f"NEGADO: {reason}"
                                                                                                                                                                                                                                                                                                                                                                                                                            else:
                                                                                                                                                                                                                                                                                                                                                                                                                                result = self.skill_registry.dispatch(plan.action_id, plan.args, exec_context)
                                                                                                                                                                                                                                                                                                                                                                                                                            else:
                                                                                                                                                                                                                                                                                                                                                                                                                                result = self.skill_registry.dispatch(plan.action_id, plan.args, exec_context)
                
                                                                                                                                                                                                                                                                                                                                                                                                                                # Observation
                                                                                                                                                                                                                                                                                                                                                                                                                                raw_result = self._serialize_action_result(result)
                                                                                                                                                                                                                                                                                                                                                                                                                                obs_limits = self._observation_limits()
                                                                                                                                                                                                                                                                                                                                                                                                                                result_max_chars = obs_limits["max_chars"]
                                                                                                                                                                                                                                                                                                                                                                                                                                if isinstance(result, (dict, list)):
                                                                                                                                                                                                                                                                                                                                                                                                                                    compact_result = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                                                                                                                                                                                                                                                                                                                                                                                                                                else:
                                                                                                                                                                                                                                                                                                                                                                                                                                    compact_result = raw_result
                                                                                                                                                                                                                                                                                                                                                                                                                                    truncated_result = (
                                                                                                                                                                                                                                                                                                                                                                                                                                    compact_result[:result_max_chars] + "..."
                                                                                                                                                                                                                                                                                                                                                                                                                                    if len(compact_result) > result_max_chars
                                                                                                                                                                                                                                                                                                                                                                                                                                    else compact_result
                                                                                                                                                                                                                                                                                                                                                                                                                                    )
                                                                                                                                                                                                                                                                                                                                                                                                                                    result_status, result_reason = self._assess_action_result(result, raw_result)
                                                                                                                                                                                                                                                                                                                                                                                                                                    structured_result = self._extract_structured_result(result, raw_result)
                
                                                                                                                                                                                                                                                                                                                                                                                                                                    last_action_status = result_status
                                                                                                                                                                                                                                                                                                                                                                                                                                    last_action_reason = result_reason
                                                                                                                                                                                                                                                                                                                                                                                                                                    last_action_id = plan.action_id
                                                                                                                                                                                                                                                                                                                                                                                                                                    last_action_output = truncated_result
                                                                                                                                                                                                                                                                                                                                                                                                                                    last_action_structured = structured_result
                
                                                                                                                                                                                                                                                                                                                                                                                                                                    # Process results (lock only for state updates)
                                                                                                                                                                                                                                                                                                                                                                                                                                    with lock:
                                                                                                                                                                                                                                                                                                                                                                                                                                        last_generated_attachment_paths = self._extract_attachment_paths_from_result(structured_result)
                                                                                                                                                                                                                                                                                                                                                                                                                                        if last_generated_attachment_paths:
                                                                                                                                                                                                                                                                                                                                                                                                                                            standardized_runtime_attachments = self._standardize_attachments(
                                                                                                                                                                                                                                                                                                                                                                                                                                            session,
                                                                                                                                                                                                                                                                                                                                                                                                                                            last_generated_attachment_paths,
                                                                                                                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                                                                                                                            last_generated_attachment_paths = [
                                                                                                                                                                                                                                                                                                                                                                                                                                            str(item.get("path")).strip()
                                                                                                                                                                                                                                                                                                                                                                                                                                            for item in standardized_runtime_attachments
                                                                                                                                                                                                                                                                                                                                                                                                                                            if isinstance(item, dict) and str(item.get("path") or "").strip()
                                                                                                                                                                                                                                                                                                                                                                                                                                            ]
                    
                                                                                                                                                                                                                                                                                                                                                                                                                                            extracted_sources = self._extract_sources_from_result(
                                                                                                                                                                                                                                                                                                                                                                                                                                            structured_result=structured_result,
                                                                                                                                                                                                                                                                                                                                                                                                                                            raw_result=raw_result,
                                                                                                                                                                                                                                                                                                                                                                                                                                            action_id=plan.action_id,
                                                                                                                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                                                                                                                            for media_path in last_generated_attachment_paths:
                                                                                                                                                                                                                                                                                                                                                                                                                                                if media_path not in media_used:
                                                                                                                                                                                                                                                                                                                                                                                                                                                    media_used.append(media_path)
                                                                                                                                                                                                                                                                                                                                                                                                                                                    for source in extracted_sources:
                                                                                                                                                                                                                                                                                                                                                                                                                                                        source_url = str(source.get("url") or "").strip()
                                                                                                                                                                                                                                                                                                                                                                                                                                                        if not source_url:
                                                                                                                                                                                                                                                                                                                                                                                                                                                            continue
                                                                                                                                                                                                                                                                                                                                                                                                                                                            if not any(str(existing.get("url") or "").strip() == source_url for existing in sources_used):
                                                                                                                                                                                                                                                                                                                                                                                                                                                                sources_used.append(source)
                            
                                                                                                                                                                                                                                                                                                                                                                                                                                                                if plan.action_id not in {"reply", "error"}:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                    session.context["last_action_plan"] = {
                                                                                                                                                                                                                                                                                                                                                                                                                                                                    "action_id": plan.action_id,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                    "args": plan.args if isinstance(plan.args, dict) else {},
                                                                                                                                                                                                                                                                                                                                                                                                                                                                    "status": result_status,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                    "reason": result_reason,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                    "ts": time.time(),
                                                                                                                                                                                                                                                                                                                                                                                                                                                                    }
                                                                                                                                                                                                                                                                                                                                                                                                                                                                    if result_status == "failure":
                                                                                                                                                                                                                                                                                                                                                                                                                                                                        # Handle non-retriable failures
                                                                                                                                                                                                                                                                                                                                                                                                                                                                        if (
                                                                                                                                                                                                                                                                                                                                                                                                                                                                        plan.action_id == "system.control.screenshot"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                        and result_reason in {"SYSTEM_DRIVER_UNAVAILABLE", "SCREENSHOT_FAILED"}
                                                                                                                                                                                                                                                                                                                                                                                                                                                                        ):
                                                                                                                                                                                                                                                                                                                                                                                                                                                                            logger.warning(
                                                                                                                                                                                                                                                                                                                                                                                                                                                                            "Screenshot failure detected (%s). Ending turn.",
                                                                                                                                                                                                                                                                                                                                                                                                                                                                            result_reason,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                                                                                                                                                            is_pt = self._session_locale(session).startswith("pt")
                                                                                                                                                                                                                                                                                                                                                                                                                                                                            details = str(structured_result.get("message") or truncated_result or "").strip() if isinstance(structured_result, dict) else str(truncated_result or "").strip()
                                                                                                                                                                                                                                                                                                                                                                                                                                                                            if len(details) > 220:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                details = details[:220] + "..."
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                if is_pt:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    final_response = f"Não consegui capturar a tela. Detalhe técnico: {details or result_reason}."
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                else:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    final_response = f"I could not capture the screen. Technical detail: {details or result_reason}."
                        
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    with lock:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        session.state_summary["last_error"] = result_reason
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        session.add_message("assistant", final_response, work_id=work_id)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        final_response_persisted = True
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        if callbacks and 'send_response' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            callbacks['send_response'](final_response, is_chunk=True)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            final_response_streamed = True
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            if callbacks and 'send_complete' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                callbacks['send_complete']()
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                stream_completed = True
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                break
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                failure_signature = (plan.action_id, param_str, self._signature_from_result(raw_result))
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                if failure_signature == last_failure_signature:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    repeated_failure_count += 1
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                else:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    repeated_failure_count = 1
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    last_failure_signature = failure_signature
                    
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    with lock:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        session.state_summary["last_error"] = result_reason
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        if planner_tree:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            self._mark_planner_blocked(planner_tree)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            session.plan = self._flatten_plan_lines(planner_tree)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            session.state_summary["cursor"] = self._progress_cursor(planner_tree, loops, max_steps)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        else:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            last_success_action_id = plan.action_id
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            last_success_output = truncated_result
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            last_success_structured = structured_result
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            repeated_failure_count = 0
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            last_failure_signature = None
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            with lock:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                if planner_tree:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    self._advance_planner_on_success(planner_tree)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    session.plan = self._flatten_plan_lines(planner_tree)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    session.state_summary["cursor"] = self._progress_cursor(planner_tree, loops, max_steps)
                
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    # Log Observation
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    summary = None
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    exemptions = ["vision.", "browser.", "youtube.", "web.", "system.control.skills."]
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    is_exempt = any(plan.action_id.startswith(ext) for ext in exemptions)
                
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    if len(raw_result) > obs_limits["summarize_threshold"] and not is_exempt:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        logger.info(f"Large output detected ({len(raw_result)} chars). Summarizing...")
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        summary = self._clip_text(self.llm_manager.summarize_output(raw_result), 900)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        observation = f"RESULT OF ACTION {plan.action_id} [status={result_status}; reason={result_reason}] (Summarized): {summary}"
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    else:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        observation = f"RESULT OF ACTION {plan.action_id} [status={result_status}; reason={result_reason}]: {truncated_result}"
                
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        with lock:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            session.add_message("system", observation, msg_type="reasoning", summary=summary, work_id=work_id)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            session.state_summary['last_outcome'] = summary if summary else truncated_result[:300]
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            self._touch_work_context(
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            work_id,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            {
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            "summary": {
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            "status": "running",
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            "last_action": plan.action_id,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            "last_result_status": result_status,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            "last_error": result_reason if result_status == "failure" else "",
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            "cursor": session.state_summary.get("cursor"),
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            },
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            "planner": {
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            "steps": planner_tree,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            },
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            },
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            )
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            # Hard guard for repeated failures
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            if repeated_failure_count >= 2:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                logger.warning(f"Repeated failure detected for action '{plan.action_id}'. Breaking loop.")
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                final_response = self.i18n.t("reply.loop_stuck", locale=self._session_locale(session), action_id=plan.action_id)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                with lock:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    session.add_message("assistant", final_response, work_id=work_id)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    final_response_persisted = True
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    if callbacks and 'send_response' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        callbacks['send_response'](final_response, is_chunk=True)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        final_response_streamed = True
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        if callbacks and 'send_complete' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            callbacks['send_complete']()
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            stream_completed = True
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            break
                
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            plan = None
        
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            if final_response is None:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                logger.warning("Reasoning loop ended without a final response.")
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                final_response = self.i18n.t("reply.no_plan_resolved", locale="en")
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                if callbacks and 'send_response' in callbacks:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    callbacks['send_response'](final_response, is_chunk=True)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    final_response_streamed = True
    
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    # Guarantee final response lifecycle (persist -> stream -> complete) in all loop exit paths.
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    if final_response and not final_response_persisted and not session.pending_action:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        session.add_message("assistant", final_response, attachments=final_structured_attachments, work_id=work_id)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        final_response_persisted = True
    
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        if callbacks and 'send_response' in callbacks and final_response and not final_response_streamed and not session.pending_action:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            callbacks['send_response'](final_response, is_chunk=True, attachments=final_structured_attachments)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            final_response_streamed = True
    
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            if callbacks and 'send_complete' in callbacks and not stream_completed and not session.pending_action:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                callbacks['send_complete']()
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                stream_completed = True
    
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                # Persist final assistant output before optional history pruning/consolidation.
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                # This guarantees reload consistency even if session context is compressed.
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                if final_response_persisted:
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    self._save_session(session)
    
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    # 5. Check for Memory Consolidation (Token-based)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    # Threshold is configurable and intentionally lower to trigger earlier compaction.
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    self._append_toon_delta(
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    session=session,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    user_input=user_input,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    last_action_id=last_action_id,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    last_action_status=last_action_status,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    last_action_reason=last_action_reason,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    final_response=final_response,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    )

                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    total_tokens = sum(m.get("tokens", 0) for m in session.history)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    if total_tokens > self._memory_consolidation_threshold():
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        self._consolidate_memory(session)
    
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        # 6. Persist and Return
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        self._save_session(session)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        self._touch_work_context(
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        work_id,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        {
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        "summary": {
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        "status": "completed",
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        "cursor": session.state_summary.get("cursor"),
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        "final_response": (final_response or "")[:400],
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        },
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        "planner": {
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        "steps": planner_tree,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        "max_steps": max_steps,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        "replan_budget": replan_budget,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        "replans_used": replans_used,
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        },
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        },
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        )
        
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        # 7. Adaptive Formatting
            channel = session.context.get('channel', 'Web')
            return self._format_response(final_response, channel)
        except Exception as e:
            logger.error(f"Error in reasoning loop: {e}")
            
            if callbacks and 'send_status' in callbacks:
                callbacks['send_status'](
                'error',
                {
                'code': 'system_error',
                'message': self._t(session, "reply.technical_issue", details=str(e)),
                },
                )
                
                final_response = self._t(session, "reply.technical_issue", details=str(e))
                self._touch_work_context(
                work_id,
                {
                "summary": {
                "status": "failed",
                "last_error": str(e),
                "cursor": session.state_summary.get("cursor"),
                },
                "planner": {"steps": planner_tree, "max_steps": max_steps},
            },
            )
    
        finally:
            total_ms = int((time.perf_counter() - turn_started_at) * 1000)
            self._capture_turn_metrics(
            session_id=session_id,
            total_ms=total_ms,
            lock_wait_ms=lock_wait_ms,
            loops=loops,
            last_action_id=last_action_id or "-",
            )
            logger.info(
            "Turn Metrics | Session: %s | DurationMs: %d | LockWaitMs: %d | Loops: %d | LastAction: %s",
            session_id,
            total_ms,
            lock_wait_ms,
            loops,
                last_action_id or "-",
            )


    def _consolidate_memory(self, session: Session, force: bool = False):
        """
        Asks the LLM to summarize the session if it's getting too heavy in tokens.
        Threshold: configurable via memory.consolidation_threshold_tokens
        (default ~1600 to trigger earlier and keep context compact).
        """
        try:
            total_tokens = sum(m.get("tokens", 0) for m in session.history)
            threshold = self._memory_consolidation_threshold()
            
            # Check threshold
            if total_tokens < threshold and not force:
                return

            logger.info(
                "Consolidating memory for session %s (Total tokens: %d, Threshold: %d)",
                session.session_id,
                total_tokens,
                threshold,
            )
            
            # Context window for summarization: existing summary + new messages
            existing_summary = session.summary or "No previous summary."
            history_to_summarize = session.get_history()
            
            prompt = (
                f"Your conversation reached the token limit. Update the session's RECURSIVE SUMMARY.\n"
                f"CURRENT SUMMARY: {existing_summary}\n\n"
                "INSTRUCTIONS:\n"
                "1. Integrate new facts from history into the current summary densely.\n"
                "2. Use TOON format (Token-Oriented Object Notation): short keys, direct values, no redundancy.\n"
                "3. Keep critical information: user name, preferences, long-term goals, and important file paths.\n"
                "4. The final output must be one UNIFIED and REFINED summary, not an appendix.\n"
                "5. Contract: Reply ONLY with a JSON object in the format:\n"
                "{\"thought\": \"Internal compression analysis\", \"response_text\": \"The new summary in TOON format\", \"action\": \"reply\"}"
            )
            
            summary_intent = self.llm_manager.generate_intent(prompt, history_to_summarize, "You are a recursive memory compression specialist. USE TOON FORMAT.")
            
            if summary_intent and summary_intent.response_text:
                # Update with the newly refined summary
                session.summary = summary_intent.response_text.strip()
                logger.info(f"Recursive TOON consolidation successful. Pruning history for session {session.session_id}.")
                # Keep only the newest deltas after consolidation to avoid prompt bloat.
                toon_deltas = session.context.get("toon_deltas")
                if isinstance(toon_deltas, list):
                    session.context["toon_deltas"] = toon_deltas[-2:]
                
                # History Rotation: Keep only the latest messages to prevent context bloat
                # We keep the last 10 messages (approx 5 turns) to maintain immediate context
                if len(session.history) > 10:
                    # Find the last User message to avoid cutting off the current turn
                    last_user_idx = -1
                    for i in range(len(session.history) - 1, -1, -1):
                        if session.history[i].get("role") == "user":
                            last_user_idx = i
                            break
                    
                    if last_user_idx != -1:
                        # Keep from the last user message onwards, plus up to 5 messages before it for context
                        start_idx = max(0, last_user_idx - 5)
                        session.history = session.history[start_idx:]
                    else:
                        # Fallback to simple slice if no user message found
                        session.history = session.history[-10:]
                    
                    logger.info(f"Pruned history for {session.session_id}. New size: {len(session.history)} messages.")
        except Exception as e:
            logger.error(f"Error during memory consolidation: {e}")

    def _memory_consolidation_threshold(self) -> int:
        cfg = self.config_manager.get("memory", {}) if hasattr(self, "config_manager") else {}
        raw = cfg.get("consolidation_threshold_tokens", 1600)
        try:
            value = int(raw)
        except Exception:
            value = 1600
        return max(800, min(6000, value))

    def _memory_toon_delta_limits(self) -> Dict[str, int]:
        cfg = self.config_manager.get("memory", {}) if hasattr(self, "config_manager") else {}
        try:
            max_entries = int(cfg.get("toon_delta_max_entries", 8))
        except Exception:
            max_entries = 8
        try:
            text_limit = int(cfg.get("toon_delta_text_limit", 96))
        except Exception:
            text_limit = 96
        return {
            "max_entries": max(2, min(32, max_entries)),
            "text_limit": max(48, min(240, text_limit)),
        }

    def _observation_limits(self) -> Dict[str, int]:
        prompt_cfg = self.config_manager.get("prompt_context", {}) if hasattr(self, "config_manager") else {}
        try:
            max_chars = int(prompt_cfg.get("observation_result_max_chars", 900))
        except Exception:
            max_chars = 900
        try:
            summarize_threshold = int(prompt_cfg.get("observation_summarize_threshold_chars", 1800))
        except Exception:
            summarize_threshold = 1800
        return {
            "max_chars": max(300, min(2400, max_chars)),
            "summarize_threshold": max(900, min(6000, summarize_threshold)),
        }

    @staticmethod
    def _clip_toon_text(value: Any, limit: int) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    def _append_toon_delta(
        self,
        *,
        session: Session,
        user_input: str,
        last_action_id: Optional[str],
        last_action_status: Optional[str],
        last_action_reason: Optional[str],
        final_response: Optional[str],
    ) -> None:
        if not session or not isinstance(session.context, dict):
            return

        limits = self._memory_toon_delta_limits()
        text_limit = limits["text_limit"]
        status_map = {"success": "ok", "failure": "er"}
        status_code = status_map.get(str(last_action_status or "").lower(), "na")

        delta = {
            "t": int(time.time()),
            "u": self._clip_toon_text(user_input, text_limit),
            "a": self._clip_toon_text(last_action_id, text_limit),
            "s": status_code,
            "c": self._clip_toon_text(session.state_summary.get("cursor"), text_limit),
            "o": self._clip_toon_text(
                session.state_summary.get("last_outcome") or final_response,
                text_limit,
            ),
        }
        reason = self._clip_toon_text(last_action_reason, text_limit)
        if reason:
            delta["r"] = reason

        # Skip empty/no-op deltas.
        if not delta["u"] and not delta["a"] and not delta["o"]:
            return

        current = session.context.get("toon_deltas")
        entries = list(current) if isinstance(current, list) else []

        # De-duplicate with last entry by semantic payload.
        if entries:
            last = entries[-1]
            if isinstance(last, dict):
                same = (
                    str(last.get("u") or "") == delta["u"]
                    and str(last.get("a") or "") == delta["a"]
                    and str(last.get("s") or "") == delta["s"]
                    and str(last.get("o") or "") == delta["o"]
                )
                if same:
                    return

        entries.append(delta)
        session.context["toon_deltas"] = entries[-limits["max_entries"] :]

    @staticmethod
    def _serialize_action_result(result: Any) -> str:
        """Serializes tool output preserving structured payloads when possible."""
        if isinstance(result, (dict, list)):
            try:
                return json.dumps(result, ensure_ascii=False)
            except Exception:
                return str(result)
        return str(result)

    @staticmethod
    def _extract_structured_result(result: Any, raw_result: str) -> Optional[Dict[str, Any]]:
        if isinstance(result, dict):
            return result

        for candidate in [result, raw_result]:
            if not isinstance(candidate, str):
                continue
            text = candidate.strip()
            if not text.startswith("{") or not text.endswith("}"):
                continue
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
        return None

    @classmethod
    def _assess_action_result(cls, result: Any, raw_result: Optional[str] = None) -> tuple[str, str]:
        """Classifies tool output for loop/delirium guards."""
        serialized = raw_result if raw_result is not None else cls._serialize_action_result(result)
        structured = cls._extract_structured_result(result, serialized)

        if structured:
            ok = structured.get("ok")
            status = str(structured.get("status") or "").strip().lower()
            error_code = structured.get("error")

            if ok is False:
                return "failure", str(error_code or status or "ok_false")

            if status in {"error", "failed", "failure"}:
                return "failure", str(error_code or status)

            if status in {"empty", "success", "ok"}:
                return "success", status

            if ok is True:
                return "success", "ok"

        text = (serialized or "").strip().lower()
        if not text:
            return "unknown", "empty_output"

        failure_markers = [
            "unknown action",
            "fatal tool error",
            "traceback",
            "exception",
            "error executing",
            "unexpected error",
            "timed out",
            "timeout",
            "missing ",
            "negado:",
            "denied",
            "permission denied",
            "unauthorized",
        ]
        if any(marker in text for marker in failure_markers):
            return "failure", "failure_marker_detected"

        if text.startswith("erro") or text.startswith("error"):
            return "failure", "explicit_error_prefix"

        return "success", "ok"

    @staticmethod
    def _signature_from_result(raw_result: str) -> str:
        """Returns a compact signature string used to detect repeated failures."""
        cleaned = re.sub(r"\s+", " ", (raw_result or "").strip().lower())
        return cleaned[:240]

    @staticmethod
    def _reply_from_last_success(
        *,
        action_id: Optional[str],
        structured_result: Optional[Dict[str, Any]],
        raw_output: Optional[str],
        language: str = "en",
    ) -> Optional[str]:
        """
        Builds a user-facing reply from the latest successful tool output.
        Used when loop guard triggers after repeated successful actions.
        """
        payload = structured_result if isinstance(structured_result, dict) else {}
        is_pt = str(language or "").lower().startswith("pt")
        action = (action_id or "").strip().lower()

        def _log_reply_source(source_key: str, **extra: Any) -> None:
            try:
                details = " ".join(f"{k}={v}" for k, v in extra.items() if v is not None and v != "")
                suffix = f" {details}" if details else ""
                logger.debug(
                    "reply_consolidation_source action=%s key=%s%s",
                    action or "-",
                    source_key,
                    suffix,
                )
            except Exception:
                pass


        if action == "system.control.screenshot":
            path = str(payload.get("path") or "").strip()
            if path:
                return f"Pronto, capturei a tela: {path}" if is_pt else f"Done, I captured the screen: {path}"
            return "Pronto, capturei a tela e já anexei para você." if is_pt else "Done, I captured the screen and attached it for you."


        text = payload.get("text")
        if (
            action.startswith("vision.")
            and isinstance(text, str)
            and text.strip()
            and not AgentOrchestrator._looks_like_technical_text(text)
        ):
            return text.strip()

        if action == "weather.control.get":
            location = str(payload.get("location") or "").strip()
            current = payload.get("current") if isinstance(payload.get("current"), dict) else {}
            temp = current.get("temp")
            desc = str(current.get("description") or "").strip()
            feels = current.get("feels_like")
            if temp is not None or desc or location:
                place = location or ("sua região" if is_pt else "your region")
                head = (
                    f"Clima atual em {place}:"
                    if is_pt
                    else f"Current weather in {place}:"
                )
                details = []
                if temp is not None:
                    details.append(f"temperatura {temp}°C" if is_pt else f"temperature {temp}°C")
                if feels is not None:
                    details.append(f"sensação {feels}°C" if is_pt else f"feels like {feels}°C")
                if desc:
                    details.append(f"condição: {desc}" if is_pt else f"condition: {desc}")
                if details:
                    return f"{head} " + " | ".join(details)
                return head

        if action == "weather.control.forecast":
            location = str(payload.get("location") or "").strip()
            forecast = payload.get("forecast")
            if isinstance(forecast, list) and forecast:
                lines = [
                    f"Previsão para {location or 'sua região'}:"
                    if is_pt
                    else f"Forecast for {location or 'your region'}:"
                ]
                for day in forecast[:5]:
                    if not isinstance(day, dict):
                        continue
                    date = str(day.get("date") or "").strip() or "?"
                    desc = str(day.get("description") or "").strip()
                    tmin = day.get("temp_min")
                    tmax = day.get("temp_max")
                    line = date
                    if desc:
                        line += f": {desc}"
                    temps = []
                    if tmin is not None:
                        temps.append(f"min {tmin}°C")
                    if tmax is not None:
                        temps.append(f"max {tmax}°C")
                    if temps:
                        line += " | " + " | ".join(temps)
                    lines.append(f"- {line}")
                if len(lines) > 1:
                    return "\n".join(lines)

        if action == "wikipedia.search":
            results = payload.get("results")
            if isinstance(results, list) and results:
                first = results[0] if isinstance(results[0], dict) else {}
                title = str(first.get("title") or "Wikipedia")
                url = str(first.get("url") or "").strip()
                raw_summary = str(first.get("content") or first.get("excerpt") or "").strip()
                raw_summary = re.sub(r"\s+", " ", raw_summary)
                summary = raw_summary
                if raw_summary:
                    parts = re.split(r"(?<=[.!?])\s+", raw_summary)
                    summary = (" ".join(parts[:2]).strip() or raw_summary)
                if len(summary) > 420:
                    summary = summary[:420].rstrip() + "..."
                if summary:
                    if is_pt:
                        message = f"Resumo rápido sobre {title}:\n{summary}"
                        return f"{message}\n\nFonte: {url}" if url else message
                    message = f"Quick summary about {title}:\n{summary}"
                    return f"{message}\n\nSource: {url}" if url else message

        if action == "maps.search":
            places = payload.get("places")
            if isinstance(places, list) and places:
                lines = []
                if is_pt:
                    if str(payload.get("status") or "").strip().lower() == "fallback":
                        lines.append("A API de mapas está indisponível no momento. Usei fallback de busca web.")
                    lines.append("Encontrei estes locais:")
                else:
                    if str(payload.get("status") or "").strip().lower() == "fallback":
                        lines.append("Maps API is currently unavailable. I used a web-search fallback.")
                    lines.append("I found these places:")
                for idx, item in enumerate(places[:6], start=1):
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item.get("title") or "Place").strip()
                    address = str(item.get("address") or "").strip()
                    url = str(item.get("url") or "").strip()
                    source_url = str(item.get("source_url") or "").strip()
                    line = f"{idx}. {name}"
                    if address:
                        line += f" — {address}"
                    if url:
                        line += f"\n{url}"
                    if source_url and source_url != url:
                        line += f"\n{source_url}"
                    lines.append(line)
                if len(lines) > 1:
                    return "\n\n".join(lines)

        if action == "research.retrieve.run":
            answer_md = str(payload.get("answer_md") or payload.get("text") or "").strip()
            if answer_md:
                return answer_md

        # Generic list summarization for actions not explicitly mapped above.
        generic_list_keys = (
            "items",
            "entries",
            "records",
            "rows",
            "tasks",
            "triggers",
            "matches",
            "documents",
            "docs",
            "memories",
            "logs",
            "files",
        )
        for list_key in generic_list_keys:
            entries = payload.get(list_key)
            if not isinstance(entries, list):
                continue
            total = len(entries)
            if total == 0:
                continue
            header = (
                f"Encontrei {total} item(ns)."
                if is_pt
                else f"I found {total} item(s)."
            )
            lines = [header]
            for idx, item in enumerate(entries[:6], start=1):
                if isinstance(item, dict):
                    title = str(
                        item.get("title")
                        or item.get("name")
                        or item.get("label")
                        or item.get("id")
                        or item.get("task_id")
                        or item.get("trigger_id")
                        or item.get("work_id")
                        or ""
                    ).strip()
                    status = str(item.get("status") or "").strip()
                    line = f"{idx}. {title or 'item'}"
                    if status:
                        line += f" ({status})"
                    lines.append(line)
                else:
                    lines.append(f"{idx}. {str(item)}")
            if len(lines) > 1:
                _log_reply_source(f"list:{list_key}", count=total)
                return "\n".join(lines)

        works = payload.get("works")
        if isinstance(works, list):
            count = payload.get("count")
            total = int(count) if isinstance(count, int) else len(works)
            if total <= 0:
                return "Nenhum worker encontrado." if is_pt else "No workers found."
            lines = [
                (
                    f"Encontrei {total} worker(s):"
                    if is_pt
                    else f"I found {total} worker(s):"
                )
            ]
            for idx, item in enumerate(works[:8], start=1):
                if not isinstance(item, dict):
                    continue
                work_id = str(item.get("work_id") or "").strip() or "?"
                status = str(item.get("status") or "").strip() or "unknown"
                label = str(item.get("label") or "").strip()
                input_text = str(item.get("input_text") or "").strip()
                summary = label or input_text
                line = f"{idx}. {work_id} ({status})"
                if summary:
                    line += f": {summary[:90]}"
                lines.append(line)
            if len(lines) > 1:
                _log_reply_source("works", count=total)
                return "\n".join(lines)

        generic_text = str(payload.get("text") or payload.get("message") or "").strip()
        if generic_text:
            _log_reply_source("text_or_message", length=len(generic_text))
            return generic_text

        results = payload.get("results")
        if isinstance(results, list) and results:
            lines = ["Encontrei estes resultados:" if is_pt else "I found these results:"]
            for idx, item in enumerate(results[:8], start=1):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("name") or item.get("label") or "Resultado")
                url = str(item.get("url") or item.get("link") or "").strip()
                channel = str(item.get("channel") or item.get("artist") or "").strip()
                line = f"{idx}. {title}"
                if channel:
                    line += f" ({channel})"
                if url:
                    line += f"\n{url}"
                lines.append(line)
            if len(lines) > 1:
                _log_reply_source("results", count=len(results))
                return "\n\n".join(lines)

        best = payload.get("best")
        if isinstance(best, dict):
            best_url = str(best.get("url") or "").strip()
            best_title = str(best.get("title") or best.get("name") or "").strip()
            if best_url or best_title:
                if best_url and best_title:
                    _log_reply_source("best", fields="title+url")
                    if is_pt:
                        return f"Melhor resultado encontrado: {best_title}\n{best_url}"
                    return f"Best result found: {best_title}\n{best_url}"
                _log_reply_source("best", fields="single")
                if is_pt:
                    return f"Melhor resultado encontrado:\n{best_url or best_title}"
                return f"Best result found:\n{best_url or best_title}"

        # Last resort: avoid dumping huge JSON to user.
        raw = (raw_output or "").strip()
        if raw and not raw.startswith("{"):
            excerpt = raw if len(raw) <= 700 else raw[:700] + "..."
            _log_reply_source("raw_output_excerpt", length=len(excerpt))
            return excerpt

        action = action_id or "the requested action"
        _log_reply_source("terminal_fallback")
        if is_pt:
            return f"Concluí {action} com sucesso, mas não consegui consolidar automaticamente a resposta final."
        return f"I completed {action} successfully, but could not automatically consolidate the final response."

    @staticmethod
    def _extract_attachment_paths_from_result(structured_result: Optional[Dict[str, Any]]) -> List[str]:
        if not isinstance(structured_result, dict):
            return []

        candidates: List[str] = []

        direct_path = structured_result.get("path")
        if isinstance(direct_path, str) and direct_path.strip():
            candidates.append(direct_path.strip())

        file_obj = structured_result.get("file")
        if isinstance(file_obj, dict):
            for key in ("path", "file_path", "url", "name"):
                value = file_obj.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())

        files = structured_result.get("files")
        if isinstance(files, list):
            for item in files:
                if isinstance(item, str) and item.strip():
                    candidates.append(item.strip())
                elif isinstance(item, dict):
                    for key in ("path", "file_path", "url", "name"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            candidates.append(value.strip())
                            break

        unique_existing: List[str] = []
        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if os.path.isfile(candidate):
                unique_existing.append(candidate)

        return unique_existing

    @staticmethod
    def _extract_sources_from_result(
        structured_result: Optional[Dict[str, Any]],
        raw_result: Optional[str],
        action_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        url_pattern = re.compile(r"https?://[^\s<>)\"'\]]+")
        url_keys = {
            "url",
            "link",
            "source_url",
            "canonical_url",
            "webpage_url",
            "href",
        }
        title_keys = {"title", "name", "label", "source_title"}
        seen: set[str] = set()
        sources: List[Dict[str, Any]] = []

        def add_source(url_value: Any, title_value: Optional[Any] = None):
            url = str(url_value or "").strip().rstrip(".,;:!?)]}\"'")
            if not url.lower().startswith(("http://", "https://")):
                return
            if url in seen:
                return
            seen.add(url)
            title = str(title_value or "").strip()
            entry: Dict[str, Any] = {"url": url}
            if title:
                entry["title"] = title
            if action_id:
                entry["action"] = action_id
            sources.append(entry)

        def walk(node: Any, inherited_title: Optional[str] = None):
            if isinstance(node, dict):
                local_title = inherited_title
                if not local_title:
                    for key in title_keys:
                        value = node.get(key)
                        if isinstance(value, str) and value.strip():
                            local_title = value.strip()
                            break
                for key, value in node.items():
                    key_lower = str(key).strip().lower()
                    if key_lower in url_keys and isinstance(value, str):
                        add_source(value, local_title)
                    walk(value, local_title)
                return
            if isinstance(node, list):
                for item in node:
                    walk(item, inherited_title)
                return
            if isinstance(node, str):
                for match in url_pattern.findall(node):
                    add_source(match, inherited_title)

        if isinstance(structured_result, dict):
            walk(structured_result)
        if isinstance(raw_result, str) and raw_result.strip():
            walk(raw_result)

        return sources

    @staticmethod
    def _looks_like_success_claim(text: str) -> bool:
        t = (text or "").lower()
        success_markers = (
            "conclu",
            "finaliz",
            "feito",
            "pronto",
            "sucesso",
            "deu certo",
            "done",
            "completed",
            "finished",
            "resolved",
            "successfully",
        )
        return any(marker in t for marker in success_markers)

    @staticmethod
    def _looks_like_failure_ack(text: str) -> bool:
        t = (text or "").lower()
        failure_markers = (
            "falh",
            "erro",
            "i could not",
            "nao consegui",
            "it was not possible",
            "nao foi possivel",
            "failed",
            "error",
            "unable",
            "cannot",
            "could not",
        )
        return any(marker in t for marker in failure_markers)

    @staticmethod
    def _looks_like_context_reset_request(text: str) -> bool:
        t = (text or "").lower()
        markers = (
            "new context",
            "send a new context",
            "send new context",
            "cannot continue with this context",
            "can't continue with this context",
            "context window",
            "token limit",
            "limite de contexto",
            "janela de contexto",
            "não posso continuar com esse contexto",
            "nao posso continuar com esse contexto",
            "não consigo continuar com esse contexto",
            "nao consigo continuar com esse contexto",
            "envie um novo contexto",
            "mandar novo contexto",
        )
        return any(marker in t for marker in markers)

    @classmethod
    def _normalize_context_reset_reply(cls, response_text: str, language: str = "en") -> str:
        text = (response_text or "").strip()
        if not text:
            return text
        if not cls._looks_like_context_reset_request(text):
            return text

        is_pt = str(language or "").lower().startswith("pt")
        if is_pt:
            return (
                "Consigo continuar sem reiniciar o contexto. "
                "Se faltar algo essencial, eu vou pedir so os dados especificos (ex.: arquivo, erro ou objetivo)."
            )
        return (
            "I can continue without resetting context. "
            "If anything essential is missing, I will ask only for the specific missing data (for example file, error, or target)."
        )

    @classmethod
    def _should_autocomplete_after_success_action(
        cls,
        user_input: str,
        action_id: str,
        args: Optional[Dict[str, Any]] = None,
        structured_result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Finalize early for informational searches to avoid repeated identical actions.
        """
        action = (action_id or "").strip().lower()
        if not action:
            return False

        # Wikipedia requests are informational in this orchestrator flow.
        if action == "wikipedia.search":
            return True

        # Skills catalog lookups are informational and should conclude after one success.
        if action in {
            "system.control.skills.list",
            "system.control.skills.list.ai",
            "system.control.skills.list.ui",
            "system.control.skills.describe",
            "system.control.skills.describe.ai",
            "system.control.skills.describe.ui",
        }:
            return True

        # Screenshot is a one-shot operational action. After success, we should
        # immediately consolidate response + attachment and finish the turn.
        if action == "system.control.screenshot":
            return True

        # Time/date is also a one-shot query and should not loop.
        if action == "system.control.time":
            return True

        # Browser executor can be multi-step. Autocomplete only on explicit one-shot cases.
        if action in {"browser.control.run"}:
            params = args if isinstance(args, dict) else {}
            payload = structured_result if isinstance(structured_result, dict) else {}
            control_action = str(params.get("action") or payload.get("action") or "").strip().lower()
            has_explicit_url = bool(str(params.get("url") or "").strip())
            has_task_prompt = bool(str(params.get("task") or "").strip())
            playback_confirmed = bool(payload.get("playback_confirmed"))

            # Never finalize early for generic task-based browser flows.
            if has_task_prompt:
                return False

            # Explicit browser media controls can conclude after success.
            if control_action in {"pause", "next", "mute", "fullscreen"}:
                return True
            if control_action == "play":
                return playback_confirmed

            # Non-media one-shot opens by URL can conclude after success.
            if has_explicit_url:
                return True
            return False

        # Search actions are informational and can conclude after one successful call.
        if action in {
            "youtube.search.find",
            "deezer.search.search",
            "spotify.search.search",
            "research.retrieve.run",
            "maps.search",
        }:
            return True

        return False

    @classmethod
    def _ground_reply_against_last_result(
        cls,
        *,
        response_text: str,
        last_action_status: Optional[str],
        last_action_id: Optional[str],
        last_action_reason: Optional[str],
        last_action_output: Optional[str],
        language: str = "en",
    ) -> str:
        """
        Prevents success hallucinations when the last tool observation was a failure.
        """
        if last_action_status != "failure":
            return response_text or ""
        is_pt = str(language or "").lower().startswith("pt")

        reply = (response_text or "").strip()
        if not reply:
            if is_pt:
                return (
                    f"A última ação `{last_action_id or 'unknown'}` falhou "
                    f"({last_action_reason or 'sem motivo detalhado'}). "
                    "Preciso ajustar a estratégia para concluir com segurança."
                )
            return (
                f"The last action `{last_action_id or 'unknown'}` failed "
                f"({last_action_reason or 'no detailed reason'}). "
                "I need to adjust the strategy to finish safely."
            )

        if cls._looks_like_failure_ack(reply):
            return reply

        if cls._looks_like_success_claim(reply):
            output_excerpt = (last_action_output or "").strip()
            if len(output_excerpt) > 220:
                output_excerpt = output_excerpt[:220] + "..."
            if is_pt:
                return (
                    f"Não consegui concluir porque a ação `{last_action_id or 'unknown'}` falhou "
                    f"({last_action_reason or 'erro'}). "
                    f"Última saída: {output_excerpt or 'sem detalhes'}."
                )
            return (
                f"I could not complete because action `{last_action_id or 'unknown'}` failed "
                f"({last_action_reason or 'error'}). "
                f"Last output: {output_excerpt or 'no details'}."
            )

        return reply

    @staticmethod
    def _clip_text(value: Any, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    def _build_instruction_pack(
        self,
        *,
        agent_name: str,
        personality: str,
        specialist_hint: str = "",
        user_language: str,
        presentation_mode: str,
        markdown_supported: bool,
        voice_interaction: bool = False,
    ) -> str:
        prompt_cfg = self.config_manager.get("prompt_context", {}) if hasattr(self, "config_manager") else {}
        style = str(prompt_cfg.get("instruction_pack_style", "compact_json")).strip().lower()
        if style == "off":
            return ""

        personality_limit = int(prompt_cfg.get("personality_max_chars", 220) or 220)
        policy_compact = [
            "full_namespaced_actions",
            "read_before_destructive",
            "browser_only_for_ui",
            "failure_honesty_and_alternative",
            "reply_only_when_done_or_blocked",
            "non_reply_must_be_progress_ack",
            "stop_after_3_same_failures",
        ]
        pack = {
            "v": "ip.v1",
            "n": self._clip_text(agent_name, 40),
            "p": self._clip_text(personality, max(80, personality_limit)),
            "lang": {"think": "en", "actions": "en", "reply": user_language or "auto", "single_reply_lang": True},
            "present": {
                "mode": presentation_mode,
                "markdown": bool(markdown_supported),
            },
            "policy": policy_compact,
            "output": {
                "format": "json_only",
                "schema_keys": ["thought", "plan", "state_summary", "action", "params", "task_label", "response_text", "attachments"],
            },
        }
        if voice_interaction:
            pack["reply_constraints"] = {
                "apply_to": "response_text_only",
                "style": "ultra_brief",
                "max_sentences": 2,
                "prefer_one_sentence": True,
                "allow_detail_only_if_user_asks": True,
                "do_not_limit": ["thought", "plan", "action", "params"],
            }
        if specialist_hint:
            pack["sp"] = self._clip_text(specialist_hint, 180)
        cache_key = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        cached = self._instruction_pack_cache.get(cache_key)
        if cached:
            return cached
        serialized = json.dumps(pack, ensure_ascii=False, separators=(",", ":"))
        # Keep a tiny cache to avoid unbounded growth.
        if len(self._instruction_pack_cache) > 32:
            self._instruction_pack_cache.clear()
        self._instruction_pack_cache[cache_key] = serialized
        return serialized

    @staticmethod
    def _prompt_section_span(prompt: str, header: str, next_headers: List[str]) -> int:
        start = prompt.find(header)
        if start < 0:
            return 0
        end = len(prompt)
        for h in next_headers:
            idx = prompt.find(h, start + 1)
            if idx != -1 and idx < end:
                end = idx
        return max(0, end - start)

    def _capture_prompt_metrics(self, session_id: str, prompt: str) -> None:
        headers = [
            "[INSTRUCTION PACK]",
            "[INTERNAL STATE (TOON)]",
            "[DYNAMIC CONTEXT]",
            "[AVAILABLE ACTIONS]",
            "[STRUCTURED OUTPUT CONTRACT]",
        ]
        sizes: Dict[str, int] = {}
        for i, header in enumerate(headers):
            sizes[header] = self._prompt_section_span(prompt, header, headers[i + 1 :])

        metrics = {
            "prompt_chars": len(prompt),
            "prompt_tokens_approx": len(prompt) // 4,
            "block_chars": sizes,
            "block_tokens_approx": {k: v // 4 for k, v in sizes.items()},
        }
        self._prompt_metrics_cache[session_id] = metrics
        logger.info(
            "Prompt Metrics | Session: %s | TotalTok~%d | InstrTok~%d | StateTok~%d | DynTok~%d | ActionsTok~%d | ContractTok~%d",
            session_id,
            metrics["prompt_tokens_approx"],
            metrics["block_tokens_approx"].get("[INSTRUCTION PACK]", 0),
            metrics["block_tokens_approx"].get("[INTERNAL STATE (TOON)]", 0),
            metrics["block_tokens_approx"].get("[DYNAMIC CONTEXT]", 0),
            metrics["block_tokens_approx"].get("[AVAILABLE ACTIONS]", 0),
            metrics["block_tokens_approx"].get("[STRUCTURED OUTPUT CONTRACT]", 0),
        )

    def _capture_observation_metrics(
        self,
        session_id: str,
        action_id: str,
        raw_result: str,
        truncated_result: str,
        summarized: bool,
    ) -> None:
        bucket = self._observation_metrics_cache.get(session_id)
        if bucket is None:
            bucket = deque(maxlen=20)
            self._observation_metrics_cache[session_id] = bucket

        bucket.append(
            {
                "ts": time.time(),
                "action": action_id,
                "raw_tokens_approx": len(raw_result) // 4,
                "truncated_tokens_approx": len(truncated_result) // 4,
                "summarized": bool(summarized),
            }
        )

    def _capture_turn_metrics(
        self,
        session_id: str,
        total_ms: int,
        lock_wait_ms: int,
        loops: int,
        last_action_id: str,
    ) -> None:
        self._turn_metrics_cache[session_id] = {
            "ts": time.time(),
            "duration_ms": int(total_ms),
            "lock_wait_ms": int(lock_wait_ms),
            "loops": int(loops),
            "last_action": last_action_id or "-",
        }

    def get_runtime_metrics(self, session_id: str) -> Dict[str, Any]:
        prompt = self._prompt_metrics_cache.get(session_id) or {}
        turn = self._turn_metrics_cache.get(session_id) or {}
        observations = list(self._observation_metrics_cache.get(session_id) or [])
        latest_observation = observations[-1] if observations else {}
        context_reset_reply_blocked = 0
        llm_reply_without_text_recovered = 0
        session = self.sessions.get(session_id)
        if session and isinstance(getattr(session, "context", None), dict):
            metrics = session.context.get("metrics")
            if isinstance(metrics, dict):
                raw_value = metrics.get("context_reset_reply_blocked", 0)
                try:
                    context_reset_reply_blocked = int(raw_value)
                except Exception:
                    context_reset_reply_blocked = 0
                raw_llm_recovered = metrics.get("llm_reply_without_text_recovered", 0)
                try:
                    llm_reply_without_text_recovered = int(raw_llm_recovered)
                except Exception:
                    llm_reply_without_text_recovered = 0
        return {
            "prompt": prompt,
            "turn": turn,
            "latest_observation": latest_observation,
            "observation_count": len(observations),
            "context_reset_reply_blocked": context_reset_reply_blocked,
            "llm_reply_without_text_recovered": llm_reply_without_text_recovered,
        }

    def _compact_specialist_prompt(self, specialist_name: str, specialist_prompt: str) -> str:
        text = str(specialist_prompt or "").strip()
        if not text:
            return ""
        prompt_cfg = self.config_manager.get("prompt_context", {}) if hasattr(self, "config_manager") else {}
        mode = str(prompt_cfg.get("specialist_prompt_mode", "compact")).strip().lower()
        if mode in {"off", "raw"}:
            return text

        try:
            max_chars = int(prompt_cfg.get("specialist_prompt_max_chars", 320) or 320)
        except Exception:
            max_chars = 320

        lines = []
        for line in text.splitlines():
            cleaned = line.strip().lstrip("-").strip()
            if not cleaned:
                continue
            if cleaned.startswith("###"):
                cleaned = cleaned.replace("###", "").strip()
            lines.append(cleaned)
        if not lines:
            return self._clip_text(text, max_chars)

        # Keep semantic essence in a compact single line.
        compact = " | ".join(lines[:6])
        if specialist_name:
            compact = f"Specialist={specialist_name}; {compact}"
        return self._clip_text(compact, max_chars)

    def _should_include_toon_deltas(self, session: Session, user_input: str) -> bool:
        if not session or not isinstance(session.context, dict):
            return False
        raw = session.context.get("toon_deltas")
        if not isinstance(raw, list) or not raw:
            return False

        prompt_cfg = self.config_manager.get("prompt_context", {}) if hasattr(self, "config_manager") else {}
        mode = str(prompt_cfg.get("toon_deltas_mode", "adaptive")).strip().lower()
        if mode in {"off", "false", "0", "never"}:
            return False
        if mode in {"on", "always", "true", "1"}:
            return True

        # Adaptive mode: include only when continuity signal is strong.
        if session.pending_action:
            return True

        planner_tree = session.context.get("planner_tree")
        if isinstance(planner_tree, list) and any(
            isinstance(step, dict) and str(step.get("status") or "") in {"pending", "in_progress"}
            for step in planner_tree
        ):
            return True

        last_error = str((session.state_summary or {}).get("last_error") or "").strip().lower()
        if last_error and last_error not in {"none", "null", "n/a"}:
            return True

        text = str(user_input or "").strip().lower()
        if not text:
            return False
        continuity_markers = (
            "continue",
            "conseguiu",
            "deu certo",
            "e ai",
            "e aí",
            "agora",
            "depois",
            "entao",
            "então",
            "isso",
            "essa",
            "esse",
            "ela",
            "ele",
            "it",
            "that",
            "those",
            "abre ela",
            "open it",
            "open that",
            "first music",
            "primeira musica",
            "primeira música",
            "qual foi a primeira",
            "remember",
            "lembra",
        )
        return any(marker in text for marker in continuity_markers)

    def _construct_system_prompt(self, session: Session, user_input: str = "") -> str:
        """Builds the provider-agnostic system prompt with dynamic sections."""
        now = datetime.datetime.now()
        sys_info = {
            "time": now.strftime("%H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "os": platform.system(),
            "dist": platform.release(),
            "user": os.getlogin() if hasattr(os, 'getlogin') else "unknown"
        }
        
        prompt_cfg = self.config_manager.get("prompt_context", {}) if hasattr(self, "config_manager") else {}
        state_mode = str(prompt_cfg.get("state_summary_mode", "toon")).strip().lower()
        if state_mode in {"legacy", "json"}:
            toon_state = json.dumps(session.state_summary, ensure_ascii=False, separators=(",", ":"))
        else:
            toon_state = dumps_toon(encode_state_summary(session.state_summary))
        toon_deltas_raw = session.context.get("toon_deltas", [])
        toon_deltas = toon_deltas_raw if isinstance(toon_deltas_raw, list) else []
        if not self._should_include_toon_deltas(session, user_input):
            toon_deltas = []

        # Get naming and personality
        agent_config = self.config_manager.get("agent", {})
        agent_name = agent_config.get("agent_name", "Assistant")
        personality = agent_config.get("personality", "You are a proactive Reasoning Agent.")
        active_specialist = str(session.context.get("active_specialist", "") or "").strip()
        specialist_prompt_raw = self.specialist_manager.get_specialist_prompt(active_specialist) or ""
        specialist_mode = str(prompt_cfg.get("specialist_prompt_mode", "ultra_compact")).strip().lower()
        if specialist_mode == "raw":
            specialist_prompt = specialist_prompt_raw
            specialist_hint = ""
        elif specialist_mode == "off":
            specialist_prompt = ""
            specialist_hint = ""
        else:
            specialist_prompt = ""
            if specialist_mode == "ultra_compact":
                specialist_hint = self.specialist_manager.get_specialist_ultra_compact(active_specialist)
            else:
                specialist_hint = self.specialist_manager.get_specialist_compact(active_specialist)
            if not specialist_hint:
                specialist_hint = self._compact_specialist_prompt(active_specialist, specialist_prompt_raw)

        caps = session.context.get('driver_capabilities', {})
        markdown_supported = caps.get('markdown', True)
        voice_only = caps.get('voice_only', False)
        voice_interaction = bool(
            voice_only
            or session.context.get("is_voice_interaction")
            or str(session.context.get("interaction_mode", "")).strip().lower() == "voice"
        )

        presentation_mode = "markdown"
        presentation_directive = "[PRESENTATION DIRECTIVE]\n"
        if voice_only:
            presentation_mode = "voice"
            presentation_directive += "- Voice mode: plain conversational text only; no markdown.\n"
        elif not markdown_supported:
            presentation_mode = "plain_text"
            presentation_directive += "- Plain text only; keep structure simple.\n"
        else:
            presentation_mode = "markdown"
            presentation_directive += "- Markdown preferred for structured outputs (tables/code/lists).\n"
            presentation_directive += "- Show concrete result snippets; avoid generic completion lines.\n"
        if voice_interaction:
            presentation_directive += "- Voice interaction: keep replies short and direct (1-3 brief sentences by default).\n"
            presentation_directive += "- IMPORTANT: this brevity constraint applies to FINAL USER RESPONSE (`response_text`) only; keep internal `thought` and `plan` complete.\n"

        instruction_pack = self._build_instruction_pack(
            agent_name=agent_name,
            personality=personality,
            specialist_hint=specialist_hint,
            user_language=session.context.get("user_language", "en"),
            presentation_mode=presentation_mode,
            markdown_supported=bool(markdown_supported and not voice_only),
            voice_interaction=voice_interaction,
        )

        allowed_actions = self._get_allowed_actions_for_session(session)
        skills_summary = self._build_prompt_actions_block(user_input=user_input, allowed_actions=allowed_actions)
        skill_scope = "principal-filtered" if allowed_actions is not None else "global"

        # Apply dynamic budgets based on active model limits
        active_config = self.llm_manager.get_active_config()
        max_context = int(active_config.get("max_context", 8000))
        
        # Scaling logic: if context is small (< 8k), reduce budgets proportionally
        if max_context < 8000:
            scale_factor = max_context / 8000
            new_budgets = {k: int(v * scale_factor) for k, v in self.prompt_composer._BLOCK_BUDGETS.items()}
            self.prompt_composer.update_budgets(new_budgets)
        else:
            # Reset to defaults if context is large enough
            self.prompt_composer.update_budgets(self.prompt_composer._BLOCK_BUDGETS)

        location_payload = self.location_service.get_current_location(session.context)
        prompt_location = self._format_prompt_location(location_payload)

        prompt = self.prompt_composer.compose(
            agent_name=agent_name,
            personality=personality,
            specialist_prompt=specialist_prompt,
            presentation_directive=presentation_directive,
            instruction_pack=instruction_pack,
            sys_info=sys_info,
            location=prompt_location,
            channel=session.context.get("channel", "Unknown"),
            user_name=session.context.get("user_name", "Unknown"),
            user_language=session.context.get("user_language", "en"),
            toon_state=toon_state,
            toon_deltas=toon_deltas,
            user_input=user_input,
            project_path=os.getcwd(),
            workspace_path=self.workspace_service.base_dir,
            venv_python=os.path.join(os.getcwd(), "env", "bin", "python3"),
            venv_pip=os.path.join(os.getcwd(), "env", "bin", "pip"),
            browser_pages=[],
            session_summary=session.summary or "",
            scratchpad=self.scratchpad_service.read(session.session_id),
            attachments=session.context.get("last_attachments", []),
            skills_summary=skills_summary,
            skill_scope=skill_scope,
        )
        self._capture_prompt_metrics(session.session_id, prompt)
        return prompt

    @staticmethod
    def _format_prompt_location(location_payload: Any) -> str:
        if not isinstance(location_payload, dict):
            return "Unknown"

        city = str(location_payload.get("city") or "").strip()
        state = str(location_payload.get("state") or "").strip()
        country = str(location_payload.get("country") or "").strip()
        lat = location_payload.get("latitude")
        lon = location_payload.get("longitude")

        parts = [p for p in (city, state, country) if p and p.lower() != "unknown"]
        if parts:
            if lat is not None and lon is not None:
                return f"{', '.join(parts)} [{lat},{lon}]"
            return ", ".join(parts)

        if lat is not None and lon is not None:
            try:
                return f"{float(lat):.6f},{float(lon):.6f}"
            except Exception:
                return f"{lat},{lon}"

        return "Unknown"

    def _build_prompt_actions_block(self, user_input: str, allowed_actions: Optional[List[str]]) -> str:
        """
        Builds a compact, low-token action catalog for prompt injection.
        """
        prompt_cfg = self.config_manager.get("prompt_context", {}) or {}
        mode = str(prompt_cfg.get("actions_mode", "on_demand")).strip().lower()
        pack_style = str(prompt_cfg.get("actions_pack_style", "compact_json")).strip().lower()

        def _pack(payload: Dict[str, Any], header: str) -> str:
            if pack_style == "off":
                return header
            return header + "\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

        # Legacy compatibility mode
        if mode == "full":
            return self.skill_registry.get_summary(allowed_actions)

        if mode in {"on_demand", "catalog_on_demand"}:
            allowed_set = set(allowed_actions) if allowed_actions is not None else set(self.skill_registry.list_actions())
            bootstrap = [
                action_id
                for action_id in (
                    "system.control.skills.list.ai",
                    "system.control.skills.describe.ai",
                    "system.control.skills.list",
                    "system.control.skills.describe",
                )
                if action_id in allowed_set
            ]
            if not bootstrap:
                # Fallback safely when discovery actions are unavailable.
                mode = "compact_hybrid"
            else:
                base_payload = {
                    "v": "ac.v2",
                    "m": "on_demand",
                    "discover": bootstrap,
                    "rules": [
                        "discover_if_unknown",
                        "prefer_ai_over_ui",
                        "skills_catalog_only_not_content_search",
                    ],
                }
                if self._is_conversational_turn(user_input):
                    return _pack(
                        {
                            **base_payload,
                            "m": "on_demand_chat",
                            "prefer_reply": True,
                        },
                        "Catalog mode: on_demand_chat",
                    )
                return _pack(base_payload, "Catalog mode: on_demand")

        manifest = self.skill_registry.get_compact_manifest(allowed_actions)
        focus_limit = int(prompt_cfg.get("focus_limit", 8))
        focus = self.skill_registry.get_focus_actions(
            user_input=user_input or "",
            allowed_actions=allowed_actions,
            limit=focus_limit,
        )

        if self._is_conversational_turn(user_input):
            short_focus_ids = [str(row.get("id") or "") for row in focus[:4] if str(row.get("id") or "").strip()]
            return _pack(
                {
                    "v": "ac.v2",
                    "m": "compact_chat",
                    "prefer_reply": True,
                    "focus": short_focus_ids,
                },
                "Catalog mode: compact_chat",
            )

        focus_ids = [str(row.get("id") or "") for row in focus if str(row.get("id") or "").strip()]
        payload = {
            "v": "ac.v2",
            "m": mode,
            "c": int(manifest.get("count", 0) or 0),
            "h": str(manifest.get("hash", "none") or "none"),
            "ns": list(manifest.get("namespaces", [])[:12]),
            "a": list(manifest.get("actions", [])),
            "f": focus_ids,
        }
        return _pack(payload, f"Catalog mode: {mode}")


    @staticmethod
    def _first_url_from_text(text: str) -> str:
        m = re.search(r"https?://\S+", str(text or ""), flags=re.IGNORECASE)
        return m.group(0).strip() if m else ""

    @staticmethod
    def _clip_goal(text: str, max_len: int = 220) -> str:
        value = str(text or "").strip()
        if len(value) <= max_len:
            return value
        return value[:max_len].rstrip()


    @staticmethod
    def _is_conversational_turn(user_input: str) -> bool:
        text = str(user_input or "").strip().lower()
        if not text:
            return False

        # Keep this strict to avoid downgrading operational turns.
        greetings = {
            "oi",
            "ola",
            "olá",
            "hello",
            "hi",
            "hey",
            "bom dia",
            "boa tarde",
            "boa noite",
            "e ai",
            "e aí",
        }
        normalized = re.sub(r"[!?.,;:]+", "", text).strip()
        if normalized in greetings:
            return True

        if len(normalized) <= 12 and any(g in normalized for g in ("oi", "olá", "ola", "hello", "hi", "hey")):
            return True
        return False

    def apply_conversation_coaching(self, session: Session, user_input: str, response_text: str) -> str:
        """
        Optional post-processing follow-up.
        By default we keep the LLM-native final response untouched to avoid
        artificial template endings that break conversational flow.
        """
        text = (response_text or "").strip()
        if not text:
            return text

        cfg = self.config_manager.get("conversation_coaching", {})
        if not bool(cfg.get("enabled", True)):
            return text
        mode = str(cfg.get("mode", "llm_native")).strip().lower()
        if mode != "template":
            return text

        if "?" in text:
            return text

        max_len = int(cfg.get("max_response_chars_for_followup", 1200))
        if len(text) > max_len:
            return text

        lower_input = (user_input or "").lower()
        locale = self._session_locale(session, fallback="en")
        if locale.startswith("pt"):
            return text
        pt_markers = ("você", "voce", "relatorio", "relatório", "pode", "quero", "ajuda")
        is_pt = False
        tone = str(cfg.get("tone", "consultative")).strip().lower()

        followup = ""
        if any(k in lower_input for k in ("report", "relatorio", "relatório", "html")):
            if tone == "direct":
                followup = "Can I generate the HTML version now?"
            elif tone == "subtle":
                followup = "If helpful, I can turn this into HTML."
            else:
                followup = "Would you like me to generate a professional HTML version now?"
        elif any(k in lower_input for k in ("plan", "planner", "roadmap", "plano")):
            if tone == "direct":
                followup = "Can I break this into milestones now?"
            elif tone == "subtle":
                followup = "If useful, I can organize this into milestones."
            else:
                followup = "Would you like me to break this into an implementation plan with milestones?"
        else:
            if tone == "direct":
                followup = "Can I proceed to the next step?"
            elif tone == "subtle":
                followup = "If useful, I can continue with the next step."
            else:
                followup = "Would you like me to proceed with the next practical step?"

        joiner = "\n\n" if "\n" in text else " "
        return f"{text}{joiner}{followup}"

    def _enforce_response_language(self, session: Session, response_text: str) -> str:
        """
        Lightweight guardrail to reduce mixed PT/EN user-facing replies.
        This does not translate full text; it normalizes recurrent cross-language fragments.
        """
        text = (response_text or "").strip()
        if not text:
            return text

        locale = self._session_locale(session, fallback="en")
        if locale.startswith("pt"):
            replacements = {
                "Feels like:": "Sensação térmica:",
                "Would you like me to proceed with the next practical step?": "Quer que eu já avance com o próximo passo prático?",
                "Would you like me to proceed with the next step?": "Quer que eu já avance com o próximo passo?",
                "Would you like me to break this into an implementation plan with milestones?": "Quer que eu quebre isso em um plano de implementação com milestones?",
                "Would you like me to generate a professional HTML version now?": "Quer que eu já gere uma versão HTML com estrutura profissional?",
                "Can I proceed to the next step?": "Posso avançar para o próximo passo?",
                "Can I generate the HTML version now?": "Posso gerar a versão HTML agora?",
                "Sorry,": "Desculpe,",
            }
            for src, dst in replacements.items():
                text = text.replace(src, dst)
            return text
        else:
            replacements = {
                "Sensação térmica:": "Feels like:",
                "Quer que eu já avance com o próximo passo prático?": "Would you like me to proceed with the next practical step?",
                "Quer que eu já avance com o próximo passo?": "Would you like me to proceed with the next step?",
                "Quer que eu quebre isso em um plano de implementação com milestones?": "Would you like me to break this into an implementation plan with milestones?",
                "Quer que eu já gere uma versão HTML com estrutura profissional?": "Would you like me to generate a professional HTML version now?",
                "Posso avançar para o próximo passo?": "Can I proceed to the next step?",
                "Posso gerar a versão HTML agora?": "Can I generate the HTML version now?",
                "Desculpe,": "Sorry,",
            }
            for src, dst in replacements.items():
                text = text.replace(src, dst)
            text = re.sub(
                r"Pronto, apliquei o controle de mídia \(([^)]+)\)\.",
                r"Done, I applied media control (\1).",
                text,
                flags=re.IGNORECASE,
            )

        return text

    def _get_principal_context(self, session: Session) -> Optional[PrincipalContext]:
        """Reconstructs PrincipalContext from persisted session context."""
        data = session.context.get("principal_context")
        if not data:
            return None
        try:
            return PrincipalContext.model_validate(data)
        except Exception as e:
            logger.debug(f"Failed to parse principal_context from session {session.session_id}: {e}")
            return None

    def _get_allowed_actions_for_session(self, session: Session) -> Optional[List[str]]:
        """Computes the action scope for the current principal/session."""
        principal = self._get_principal_context(session)
        if not principal:
            return None
        return self.access_controller.get_allowed_actions(
            principal,
            self.skill_registry,
            self.config_manager,
        )


    def _scan_system_triggers(self) -> Optional[str]:
        """
        Scans the system for anomalies or events that require proactive attention.
        """
        if not self.system_driver:
            return None
            
        status = self.system_driver.get_status()
        
        # 1. High CPU check
        if status.get("cpu_usage_percent", 0) > 95:
            return "Extremely high CPU usage detected (95%+). Would you like me to analyze which processes are consuming the most resources?"

            
        # 2. Filesystem Trigger (Demo)
        trigger_path = os.path.expanduser("~/.proactive_trigger")
        if os.path.exists(trigger_path):
            try:
                with open(trigger_path, 'r') as f:
                    content = f.read().strip()
                os.remove(trigger_path) # Consume the trigger
                return f"Trigger signal detected via file: {content}"

            except:
                pass

        return None

    @staticmethod
    def _is_youtube_playback_request(text: str) -> bool:
        value = str(text or "").strip().lower()
        if not value:
            return False
        mentions_youtube = bool(re.search(r"\b(youtube|yt|youtube music|music\.youtube)\b", value))
        playback_verb = bool(
            re.search(
                r"\b(play|start|listen|stream|tocar|toque|reproduz|reproduza|ouvir|escutar|inicia|iniciar)\b",
                value,
            )
        )
        has_music_hint = bool(re.search(r"\b(lofi|music|musica|m[uú]sica|song|track|playlist)\b", value))
        return mentions_youtube and playback_verb and has_music_hint

    def _apply_media_decision_policy(
        self,
        *,
        session: Session,
        user_input: str,
        plan: ActionPlan,
        last_action_id: Optional[str],
        last_action_structured: Optional[Dict[str, Any]],
    ) -> ActionPlan:
        decision_cfg = self.config_manager.get("decision_policy", {}) if hasattr(self, "config_manager") else {}
        mode = str(decision_cfg.get("media_override_mode", "off")).strip().lower()
        if mode not in {"hard", "on", "strict"}:
            return plan

        if not self._is_youtube_playback_request(user_input):
            return plan

        metadata_actions = {
            "youtube.search.find",
            "youtube.retrieve.get",
            "web.search.discover",
            "web.retrieve.read",
            "web.retrieve.extract",
            "research.retrieve.run",
        }
        if plan.action_id in metadata_actions and self.skill_registry.get_skill_for_action("browser.control.run"):
            logger.info(
                "Decision policy override: %s -> browser.control.run for YouTube playback request.",
                plan.action_id,
            )
            return ActionPlan(
                action_id="browser.control.run",
                args={"goal": (user_input or "").strip()},
                confidence=max(float(plan.confidence or 0.0), 0.75),
                source=f"{plan.source}_policy",
                response_text=plan.response_text,
                thought=plan.thought,
                metadata=dict(plan.metadata or {}),
                attachments=plan.attachments,
            )

        if plan.action_id == "youtube.retrieve.get":
            args = plan.args if isinstance(plan.args, dict) else {}
            has_url = bool(str(args.get("url") or "").strip())
            has_video_id = bool(str(args.get("video_id") or "").strip())
            if not has_url and not has_video_id and last_action_id == "youtube.search.find":
                candidate = last_action_structured if isinstance(last_action_structured, dict) else {}
                best = candidate.get("best") if isinstance(candidate.get("best"), dict) else None
                first = None
                results = candidate.get("results")
                if isinstance(results, list) and results and isinstance(results[0], dict):
                    first = results[0]
                chosen = best or first or {}
                repaired_url = str(chosen.get("url") or "").strip()
                repaired_video_id = str(chosen.get("videoId") or "").strip()
                if repaired_url or repaired_video_id:
                    repaired_args = dict(args)
                    if repaired_url:
                        repaired_args["url"] = repaired_url
                    if repaired_video_id:
                        repaired_args["video_id"] = repaired_video_id
                    logger.info(
                        "Auto-repaired youtube.retrieve.get args from previous search result (url=%s, video_id=%s).",
                        bool(repaired_url),
                        bool(repaired_video_id),
                    )
                    return ActionPlan(
                        action_id=plan.action_id,
                        args=repaired_args,
                        confidence=plan.confidence,
                        source=plan.source,
                        response_text=plan.response_text,
                        thought=plan.thought,
                        metadata=dict(plan.metadata or {}),
                        attachments=plan.attachments,
                    )

        return plan

    def _get_param(self, params: dict, keys: list, default=None):
        """Helper to get a parameter from a dictionary, trying multiple keys."""
        for key in keys:
            if key in params:
                return params[key]
        return default
