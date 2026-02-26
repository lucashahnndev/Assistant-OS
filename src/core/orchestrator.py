import os
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
from services.search.query_semantics import QuerySemantics
from utils.logging_config import get_logger, read_recent_logs
from utils.event_bus import global_event_bus
from utils.toon_codec import encode_reasoning_step, encode_state_summary, dumps_toon

# New Resolution and Skill imports
from core.resolution.chain_resolver import FallbackChainResolver
from core.resolution.llm_resolver import LLMResolver
from core.resolution.semantic_resolver import SemanticResolver
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
        self.reflex_registry = ReflexRegistry()
        for skill in self.skill_registry.skills.values():
            for rule in skill.get_reflex_rules():
                self.reflex_registry.register(
                    pattern=rule['pattern'], 
                    action_id=rule['action_id'], 
                    handler=rule.get('handler')
                )
        self.reflex_resolver = ReflexResolver(self.reflex_registry)

        # 3. Intent Resolution Chain
        res_config = self.config_manager.get('intent_resolution', {})
        self.llm_resolver = LLMResolver(
            self.llm_manager,
            threshold=res_config.get('llm_confidence_threshold', 0.65),
            skill_registry=self.skill_registry,
        )
        self.semantic_resolver = SemanticResolver(
            threshold=res_config.get('semantic_first_threshold', 0.92),
            skill_registry=self.skill_registry,
        )
        
        mode = res_config.get('mode', 'llm_first')
        if mode == 'llm_first':
            resolvers = [self.llm_resolver]
            if res_config.get('semantic_fallback', True):
                resolvers.append(self.semantic_resolver)
        else: # semantic_first
            resolvers = [self.semantic_resolver, self.llm_resolver]
        
        self.intent_resolver_chain = FallbackChainResolver(resolvers)
        
        logger.info("Agent Orchestrator Initialized with Skill-First Resolution")
        
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
            file_path = _resolve_existing_path(_extract_path(entry))
            if not file_path or not os.path.isfile(file_path):
                logger.warning(f"Attachment not found during standardization: {entry}")
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
            
            # Target directory: data/sessions/{session_id}/media/{file_type}
            target_dir = os.path.join(self.sessions_dir, session.session_id, "media", file_type)
            os.makedirs(target_dir, exist_ok=True)
            
            new_filename = f"{uuid.uuid4().hex[:8]}_{orig_name}"
            target_path = os.path.join(target_dir, new_filename)
            
            try:
                # If it's already in the target directory, don't copy again
                if os.path.abspath(file_path) != os.path.abspath(target_path):
                    shutil.copy2(file_path, target_path)
                    
                standardized.append({
                    "name": orig_name,
                    "path": target_path,
                    "type": file_type,
                    "mime": mime_type
                })
                logger.info(f"Standardized attachment: {new_filename} -> {file_type}")
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
                if name in {"approve", "deny", "cancel"}:
                    payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}
                    return {"decision": name, "note": payload.get("note")}
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
        """
        merged = list(disk_history or [])
        seen = set()

        for msg in merged:
            key = self._history_message_key(msg)
            if key is not None:
                seen.add(key)

        for msg in (memory_history or []):
            key = self._history_message_key(msg)
            if key is not None and key in seen:
                continue
            merged.append(msg)
            if key is not None:
                seen.add(key)

        return merged

    def _save_session(self, session: Session):
        try:
            if self._is_transient_runtime_session(session):
                return
            lock = self._get_or_create_session_lock(session.session_id)
            with lock:
                sess_dir = os.path.join(self.sessions_dir, session.session_id)
                os.makedirs(sess_dir, exist_ok=True)
                
                # chat.json is append-only timeline; session.history is mutable context for the AI.
                chat_file_path = os.path.join(sess_dir, "chat.json")
                context_history = session.history if isinstance(session.history, list) else []
                disk_history: List[Dict] = self._load_chat_history_resilient(chat_file_path, session.session_id)

                merged_chat_history = self._merge_chat_history_append_only(disk_history, context_history)
                if len(disk_history) > len(context_history):
                    logger.warning(
                        f"Append-only protection active for {session.session_id}: "
                        f"kept {len(disk_history)} disk messages while context has {len(context_history)}."
                    )

                self._atomic_write_json(chat_file_path, merged_chat_history)

                # Save recent mutable AI context to session.json (metadata + last 50 context messages)
                file_path = os.path.join(sess_dir, "session.json")
                session_data = session.to_dict()
                
                # Keep only the last 50 messages in session.json to keep it light
                session_data["history"] = context_history[-50:] if len(context_history) > 50 else context_history
                
                self._atomic_write_json(file_path, session_data)
                
                # Update Index
                if hasattr(self, 'index_manager'):
                    self.index_manager.register_session(session)
        except Exception as e:
            logger.error(f"Error saving session {session.session_id}: {e}")

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
        if re.search(r"\b[a-z]+\.[a-z0-9_]+\.[a-z0-9_]+\b", value):
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

        if action == "browser.automator.control":
            ctrl = str(args.get("action") or "").strip().lower()
            if ctrl == "pause":
                return "Understood, I will pause playback now."
            if ctrl == "play":
                return "Understood, resuming playback now."
            if ctrl == "next":
                return "Understood, I will skip to the next track now."
            if ctrl == "mute":
                return "Understood, I will mute the audio now."
            return "Understood, adjusting media controls now."

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

    def get_initial_intent(self, user_input: str, session_id: str = "default", user_data: dict = None, context: PrincipalContext = None, attachments: List[str] = None, name: str = "") -> tuple[Optional[ActionPlan], Optional[str], Any]:
        """
        Runs the first phase of resolution: Reflex followed by the configured chain.
        Returns (ActionPlan, ReflexResponse_DEPRECATED, Session).
        """
        # Get or Create Session
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
        
        # Access Control: Pre-LLM Gate
        if context:
            allowed, reason = self.access_controller.pre_llm_gate(context)
            if not allowed:
                # Return a special plan for blocked access
                return ActionPlan(action_id='reply', args={}, response_text=reason, source='access_control'), None, session
        
        # Fresh Start: If previous turn was a reply, ensure state is clean
        if session.state_summary.get('goal') == "Standby/Listening" or not session.history:
            self._cleanup_session_state(session)
        
        # 0. Reflex Path (High Priority)
        plan = self.reflex_resolver.resolve(user_input, {"session": session})
        if plan:
            # For reflex, we usually return immediately if there's no complex reasoning needed.
            # But the Orchestrator loop handles execution. 
            # If it's a "fast reflex" like greeting, we might want to just reply.
            return plan, None, session

        # 1. Register message in history (REMOVED - now handled by Kernel.process_input to avoid duplicates)
        
        # 2. Resolution Chain (LLM/Semantic)
        allowed_actions = self._get_allowed_actions_for_session(session)
        res_context = {
            "session": session,
            "system_prompt": self._construct_system_prompt(session, user_input=user_input),
            "attachments": attachments,
            "allowed_actions": allowed_actions,
            "skill_registry": self.skill_registry,
        }
        
        try:
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
        logger.debug(f"Processing input in session '{session_id}': {user_input}")
        turn_started_at = time.perf_counter()
        lock_wait_ms = 0
        loops = 0
        last_action_id = None

        # Get or Create Session
        session = self.get_session_robust(session_id)
        
        # Get or create session lock (reentrant to safely nest persistence calls).
        lock = self._get_or_create_session_lock(session_id)
        
        # Concurrency Guard
        # Increased timeout to 120s to accommodate long LLM turns/dashboard generation
        lock_wait_started_at = time.perf_counter()
        acquired = lock.acquire(blocking=True, timeout=120)
        lock_wait_ms = int((time.perf_counter() - lock_wait_started_at) * 1000)
        if not acquired:
            logger.warning(f"Timeout waiting for session lock: {session_id}")
            return "I am still processing your previous request. Please wait a moment or try again shortly."

        try:
            # Check for cancellation before starting the loop (cooperative)
            if cancel_check and cancel_check():
                logger.info(f"Task for session {session_id} was cancelled before starting.")
                return None
            
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
            
            # Reflex check if not already provided (Legacy support)
            if not plan:
                plan = self.reflex_resolver.resolve(user_input, {"session": session})
            
            if plan and plan.source == 'reflex' and plan.action_id == 'reply':
                 return plan.response_text

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
                        session.add_message("user", user_input)
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
                        session.add_message("user", user_input)
                        plan = ActionPlan(
                            action_id=resumed_action_id,
                            args=resumed_params,
                            confidence=1.0,
                            source="internal",
                            thought=f"User approved pending sensitive action '{resumed_action_id}'.",
                        )
                elif is_no:
                    session.pending_action = None
                    session.add_message("user", user_input)
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
            last_generated_attachment_paths: List[str] = []
            browser_open_recovery_attempts = 0
            browser_control_recovery_attempts = 0
            media_play_handoff_attempts = 0
            media_request = self._is_media_play_request(user_input)
            media_vision_fallback_attempts = 0
            maps_billing_fallback_attempts = 0
            final_response = self._t(session, "reply.step_budget_exceeded")
            final_structured_attachments = None
            final_response_persisted = False
            final_response_streamed = False
            stream_completed = False
            paused = False
            actions_used: List[str] = []
            skills_used: List[str] = []
            media_used: List[str] = []
            queued_messages: List[str] = []
            feedback_cfg = self.config_manager.get("work_feedback", {}) if hasattr(self, "config_manager") else {}
            progress_feedback_enabled = bool(feedback_cfg.get("progress_updates_enabled", True))
            emitted_progress_events: set[str] = set()
    
            def current_step_title() -> str:
                if not planner_tree:
                    return "current step"
                current = next((s for s in planner_tree if s.get("status") == "in_progress"), None)
                title = str((current or {}).get("title") or "").strip()
                if title:
                    return title
                return "current step"
    
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
                session.add_message("assistant", text)
                if callbacks and "send_status" in callbacks:
                    callbacks["send_status"]("thinking", {"message": text, "kind": "progress"})
                self._save_session(session)
    
            planner_tree = self._normalize_plan_tree(plan.metadata.get("plan")) if (plan and isinstance(plan.metadata, dict)) else []
            if planner_tree:
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
                        "queued_messages": [],
                    },
                },
            )
    
            try:
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
                                        session.add_message("user", f"[Injected message] {note}")
                                        plan = None
                                if name == "update_context":
                                    patch = payload.get("patch")
                                    if isinstance(patch, dict):
                                        session.context.update(patch)
                                        self._touch_work_context(work_id, {"data": {"last_context_patch": patch}})
                            if paused:
                                if callbacks and 'send_status' in callbacks:
                                    callbacks['send_status']('thinking', {'code': 'paused', 'message': 'Work is paused. Waiting for resume command.'})
                                time.sleep(0.8)
                                continue
    
                    loops += 1
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

                        reasoning_context = {
                            "session": session,
                            "system_prompt": self._construct_system_prompt(session, user_input=user_input),
                            "attachments": attachments if loops == 1 else None, # Only send attachments on first reasoning step
                            "history": session.get_context_for_llm(limit_msgs=20, limit_tokens=reasoning_history_budget),
                            "allowed_actions": self._get_allowed_actions_for_session(session),
                            "skill_registry": self.skill_registry,
                        }
                        plan = self.intent_resolver_chain.resolve(user_input, reasoning_context)
    
                    if not plan:
                        logger.warning("No plan resolved. Breaking loop.")
                        recovered_reply = self._reply_from_last_success(
                            action_id=last_action_id,
                            structured_result=last_action_structured,
                            raw_output=last_action_output,
                            language=self._session_locale(session),
                        ) if last_action_status == "success" else None
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
                            planner_tree = candidate
                            session.context["planner_tree"] = planner_tree
                            session.plan = self._flatten_plan_lines(planner_tree)
                            session.state_summary["cursor"] = self._progress_cursor(planner_tree, loops, max_steps)
    
                    # Update state from plan metadata if available
                    if plan.metadata and 'state_summary' in plan.metadata:
                        session.state_summary.update(plan.metadata['state_summary'])
    
                    if planner_tree:
                        active = next((s for s in planner_tree if s.get("status") == "in_progress"), None)
                        if not active:
                            pending = next((s for s in planner_tree if s.get("status") == "pending"), None)
                            if pending:
                                pending["status"] = "in_progress"
                        session.plan = self._flatten_plan_lines(planner_tree)
                        session.state_summary["cursor"] = self._progress_cursor(planner_tree, loops, max_steps)
                    else:
                        if not session.state_summary.get("cursor"):
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
                                "queued_messages": queued_messages[-40:],
                            },
                        },
                    )
    
                    # Normalize/repair action IDs to reduce "unknown action" loops.
                    if plan.action_id not in ("reply", "error"):
                        resolved_action = self.skill_registry.resolve_action_id(plan.action_id)
                        if resolved_action and resolved_action != plan.action_id:
                            logger.info(f"Resolved action alias: {plan.action_id} -> {resolved_action}")
                            session.add_message(
                                "system",
                                f"ACTION_RESOLVED: '{plan.action_id}' -> '{resolved_action}'",
                                msg_type="reasoning",
                            )
                            plan.action_id = resolved_action
                        elif not self.skill_registry.get_skill_for_action(plan.action_id):
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
    
                    logger.info(f"Action: {plan.action_id} | Confidence: {plan.confidence}")
                    if (
                        self._is_media_pronoun_open_request(user_input)
                        and plan.action_id in {"youtube.search.find", "deezer.search.search", "spotify.search.search"}
                    ):
                        recent_media_url = self._extract_recent_media_url_from_history(session)
                        if recent_media_url:
                            logger.info(
                                "Pronoun media override: %s -> browser.automator.play_url (%s)",
                                plan.action_id,
                                recent_media_url,
                            )
                            plan = ActionPlan(
                                action_id="browser.automator.play_url",
                                args={"url": recent_media_url},
                                confidence=1.0,
                                source="internal",
                                thought=(
                                    "Pronoun-based request to open previously found media. "
                                    "Reusing latest known media URL from session history."
                                ),
                            )

                    if plan.action_id not in {"reply", "error"}:
                        actions_used.append(plan.action_id)
                        namespace = ".".join(plan.action_id.split(".")[:2]) if "." in plan.action_id else plan.action_id
                        if namespace not in skills_used:
                            skills_used.append(namespace)

                    # On-demand catalog repair:
                    # If the model asks for skills.describe without target action(s),
                    # downgrade safely to skills.list to avoid a hard failure loop.
                    if plan.action_id == "system.control.skills.describe":
                        args_obj = plan.args if isinstance(plan.args, dict) else {}
                        has_one = bool(str(args_obj.get("action_id") or "").strip())
                        has_many = isinstance(args_obj.get("action_ids"), list) and len(args_obj.get("action_ids")) > 0
                        if not has_one and not has_many:
                            logger.warning(
                                "Auto-repair: '%s' missing action identifiers. Falling back to system.control.skills.list.",
                                plan.action_id,
                            )
                            plan.action_id = "system.control.skills.list"
                            plan.args = {
                                "limit": 40,
                                "include_descriptions": True,
                            }

                    if plan.action_id in {"system.control.skills.list", "system.control.skills.list.ai"}:
                        args_obj = plan.args if isinstance(plan.args, dict) else {}
                        query = str(args_obj.get("query") or "").strip()
                        if query and not self._looks_like_skill_discovery_query(query):
                            logger.warning(
                                "Auto-repair: '%s' received non-skill query '%s'. Clearing query to avoid empty catalog loop.",
                                plan.action_id,
                                query[:80],
                            )
                            plan.args = {
                                **args_obj,
                                "query": "",
                                "limit": int(args_obj.get("limit", 40) or 40),
                                "include_descriptions": bool(args_obj.get("include_descriptions", False)),
                            }

                    if plan.action_id == "wikipedia.search":
                        args_obj = plan.args if isinstance(plan.args, dict) else {}
                        current_query = str(args_obj.get("query") or "").strip()
                        if self._looks_like_instruction_only_query(current_query):
                            repaired_query = QuerySemantics.rewrite_for_wikipedia(user_input)
                            if repaired_query and not self._looks_like_instruction_only_query(repaired_query):
                                logger.warning(
                                    "Auto-repair: wikipedia.search query '%s' -> '%s'",
                                    current_query[:80],
                                    repaired_query[:80],
                                )
                                plan.args = {
                                    **args_obj,
                                    "query": repaired_query,
                                }
                    
                    # Notify Reasoning Chunk
                    if callbacks and 'send_reasoning_chunk' in callbacks:
                        ui_reasoning = plan.thought if plan.thought else f"Resolving intention ({plan.source})..."
                        callbacks['send_reasoning_chunk'](ui_reasoning)
                    
                    # Emit global event for real-time synchronization
                    global_event_bus.emit_threadsafe({
                        "type": "reasoning_chunk",
                        "session_id": session_id,
                        "content": plan.thought if plan.thought else f"Resolving intention ({plan.source})...",
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
                            session.add_message(
                                "system",
                                "REPLAN_TRIGGER: exact repetition detected. Generate an alternative strategy with different action or params.",
                                msg_type="reasoning",
                            )
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
                         logger.info(f"Loop tendency detected for action '{plan.action_id}'. Injecting warning.")
                         session.add_message("system", 
                             f"WARNING: You have attempted '{plan.action_id}' multiple times with similar results. "
                             "If this approach is not working, STOP and explain the blockage to the user in 'response_text' using 'action': 'reply'. "
                             "DO NOT repeat the same failing action more than 4 times.", 
                             msg_type="reasoning")
    
                    # 3. Action Repetition (4 times in last 5 steps) - Hard Break
                    if action_history.count(plan.action_id) >= 4:
                         if replans_used < replan_budget:
                             replans_used += 1
                             previous_actions = []
                             session.add_message(
                                 "system",
                                 "REPLAN_TRIGGER: action repeated too often. Change strategy before continuing.",
                                 msg_type="reasoning",
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
                    session.add_message("assistant", history_entry, msg_type="reasoning")
    
                    # Deterministic guard against "fake completion" in operational media requests.
                    # If first plan is reply for a playback request, force an actionable search first.
                    if (
                        plan.action_id == 'reply'
                        and plan.source != 'internal'
                        and last_action_id is None
                        and self._is_media_play_request(user_input)
                    ):
                        if self._is_media_pronoun_open_request(user_input):
                            recent_media_url = self._extract_recent_media_url_from_history(session)
                            if recent_media_url:
                                logger.info(
                                    "Reply-only media guard resolved pronoun reference -> browser.automator.play_url (%s)",
                                    recent_media_url,
                                )
                                plan = ActionPlan(
                                    action_id="browser.automator.play_url",
                                    args={"url": recent_media_url},
                                    confidence=1.0,
                                    source='internal',
                                    thought=(
                                        "Reply-only plan for pronoun-based media open request. "
                                        "Using latest known media URL."
                                    ),
                                )
                                continue
                        forced_action, forced_query = self._derive_media_search_action_and_query(user_input)
                        if forced_action and forced_query:
                            logger.info(
                                "Reply-only plan overridden by deterministic media handoff | action=%s query=%s",
                                forced_action,
                                forced_query,
                            )
                            plan = ActionPlan(
                                action_id=forced_action,
                                args={"query": forced_query},
                                confidence=1.0,
                                source='internal',
                                thought=(
                                    "User requested playback. Forcing media search action "
                                    "before accepting final textual reply."
                                ),
                            )
    
                    # Deterministic guard for first-step browser open with plain-text query in media requests.
                    # Prevents "open search page and stop" behavior and avoids unnecessary browser-use loops.
                    if (
                        plan.action_id == 'browser.automator.open'
                        and plan.source != 'internal'
                        and last_action_id is None
                        and self._is_media_play_request(user_input)
                    ):
                        open_url = ""
                        if isinstance(plan.args, dict):
                            open_url = str(
                                plan.args.get("url")
                                or plan.args.get("link")
                                or plan.args.get("uri")
                                or ""
                            ).strip()
                        if not (open_url.startswith("http://") or open_url.startswith("https://")):
                            if self._is_media_pronoun_open_request(user_input):
                                recent_media_url = self._extract_recent_media_url_from_history(session)
                                if recent_media_url:
                                    logger.info(
                                        "browser.automator.open guard resolved pronoun reference -> browser.automator.play_url (%s)",
                                        recent_media_url,
                                    )
                                    plan = ActionPlan(
                                        action_id="browser.automator.play_url",
                                        args={"url": recent_media_url},
                                        confidence=1.0,
                                        source='internal',
                                        thought=(
                                            "Pronoun-based media open request detected. "
                                            "Switching to direct play_url with the latest known media URL."
                                        ),
                                    )
                                    continue
                            forced_action, forced_query = self._derive_media_search_action_and_query(user_input)
                            if forced_action and forced_query:
                                logger.info(
                                    "browser.automator.open (query-like) overridden by media search | action=%s query=%s",
                                    forced_action,
                                    forced_query,
                                )
                                plan = ActionPlan(
                                    action_id=forced_action,
                                    args={"query": forced_query},
                                    confidence=1.0,
                                    source='internal',
                                    thought=(
                                        "Playback request detected. Running deterministic media search "
                                        "before any generic browser open step."
                                    ),
                                )
    
                    # Strong first-step gate for playback requests: avoid drifting to unrelated actions
                    # (e.g., web.search.discover) when deterministic media actions are available.
                    if (
                        plan.source != 'internal'
                        and last_action_id is None
                        and self._is_media_play_request(user_input)
                    ):
                        if (
                            plan.action_id in {"youtube.search.find", "deezer.search.search", "spotify.search.search"}
                            and self._is_media_pronoun_open_request(user_input)
                        ):
                            recent_media_url = self._extract_recent_media_url_from_history(session)
                            if recent_media_url:
                                logger.info(
                                    "First-step media gate upgraded search -> browser.automator.play_url using recent URL (%s)",
                                    recent_media_url,
                                )
                                plan = ActionPlan(
                                    action_id="browser.automator.play_url",
                                    args={"url": recent_media_url},
                                    confidence=1.0,
                                    source='internal',
                                    thought=(
                                        "Pronoun-based media open request resolved to the latest media URL "
                                        "from session history."
                                    ),
                                )
                                continue
                        allowed_first_step = False
                        if plan.action_id in {"youtube.search.find", "deezer.search.search", "spotify.search.search"}:
                            allowed_first_step = True
                        elif plan.action_id == "browser.automator.play_url":
                            raw_url = ""
                            if isinstance(plan.args, dict):
                                raw_url = str(
                                    plan.args.get("url")
                                    or plan.args.get("link")
                                    or plan.args.get("uri")
                                    or ""
                                ).strip()
                            if raw_url.startswith("http://") or raw_url.startswith("https://"):
                                allowed_first_step = True
    
                        if not allowed_first_step:
                            recent_media_url = ""
                            if self._is_media_pronoun_open_request(user_input):
                                recent_media_url = self._extract_recent_media_url_from_history(session)
                            if recent_media_url:
                                logger.info(
                                    "First-step media gate resolved pronoun reference with recent URL -> browser.automator.play_url (%s)",
                                    recent_media_url,
                                )
                                plan = ActionPlan(
                                    action_id="browser.automator.play_url",
                                    args={"url": recent_media_url},
                                    confidence=1.0,
                                    source='internal',
                                    thought=(
                                        "User requested to open previously found media. "
                                        "Using latest known media URL from session history."
                                    ),
                                )
                                continue
                            forced_action, forced_query = self._derive_media_search_action_and_query(user_input)
                            if forced_action and forced_query:
                                logger.info(
                                    "First-step media gate overriding action '%s' -> '%s' (query=%s)",
                                    plan.action_id,
                                    forced_action,
                                    forced_query,
                                )
                                plan = ActionPlan(
                                    action_id=forced_action,
                                    args={"query": forced_query},
                                    confidence=1.0,
                                    source='internal',
                                    thought=(
                                        "Playback request detected. Forcing deterministic media start "
                                        "action to avoid non-productive first-step drift."
                                    ),
                                )
    
                    if plan.action_id == 'reply':
                        final_response = self._ground_reply_against_last_result(
                            response_text=plan.response_text or "",
                            last_action_status=last_action_status,
                            last_action_id=last_action_id,
                            last_action_reason=last_action_reason,
                            last_action_output=last_action_output,
                            language=self._session_locale(session),
                        )
                        final_response = self.apply_conversation_coaching(session, user_input, final_response)
                        
                        # Process attachments
                        attachment_inputs = plan.attachments or last_generated_attachment_paths
                        structured_attachments = self._standardize_attachments(session, attachment_inputs) if attachment_inputs else None
    
                        if not final_response and structured_attachments:
                            final_response = "Here is the requested file."
                        
                        session.add_message("assistant", final_response, attachments=structured_attachments)
                        final_structured_attachments = structured_attachments
                        final_response_persisted = True
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
                            
                        final_response = self._t(
                            session,
                            "reply.error_during_processing",
                            details=(plan.thought or "unknown"),
                        )
                        session.add_message("assistant", final_response)
                        final_response_persisted = True
                        if callbacks and 'send_response' in callbacks:
                            callbacks['send_response'](final_response, is_chunk=True)
                            final_response_streamed = True
                        
                        if callbacks and 'send_complete' in callbacks:
                            callbacks['send_complete']()
                            stream_completed = True
                        break
                    
                    # Do not persist/send non-final response_text for action plans.
                    # Intermediate text belongs to status/reasoning, not final chat timeline.
                    if plan.response_text and callbacks and 'send_status' in callbacks:
                        callbacks['send_status'](
                            'executing',
                            {
                                'code': 'ack',
                                'message': str(plan.response_text)[:220],
                                'action': plan.action_id
                            }
                        )
    
                    # HITL Check
                    if self.safety_service.is_sensitive(plan.action_id, plan.args, self.skill_registry):
                        approval_msg = self.safety_service.get_approval_message(plan.action_id, plan.args)
                        work_record = self._get_work_record(work_id)
                        owner_session_id = work_record.owner_session_id if work_record else session_id
                        worker_run = bool((user_data or {}).get("__worker_run"))
    
                        target_session = self.get_session_robust(owner_session_id)
                        if not target_session:
                            if worker_run:
                                final_response = self.i18n.t("reply.approval_target_missing", locale=self._session_locale(session))
                                logger.error(
                                    "Worker cannot request approval because owner session '%s' does not exist.",
                                    owner_session_id,
                                )
                                if callbacks and 'send_status' in callbacks:
                                    callbacks['send_status'](
                                        'error',
                                        {
                                            'code': 'approval_target_missing',
                                            'message': final_response,
                                            'action': plan.action_id,
                                        },
                                    )
                                plan = ActionPlan(
                                    action_id='reply',
                                    args={},
                                    response_text=final_response,
                                    source='internal',
                                )
                                continue
                            interface = "web"
                            if str(owner_session_id).startswith("telegram"):
                                interface = "telegram"
                            elif str(owner_session_id).startswith("voice"):
                                interface = "voice"
                            target_session = self.create_session(owner_session_id, interface=interface)
    
                        target_session.pending_action = {
                            "action": plan.action_id,
                            "params": plan.args,
                            "work_id": work_id,
                            "requested_at": datetime.datetime.now().isoformat(),
                        }
                        target_session.add_message("assistant", approval_msg)
                        self._save_session(target_session)
    
                        self._touch_work_context(
                            work_id,
                            {
                                "summary": {
                                    "status": "waiting_user",
                                    "approval_prompt": approval_msg,
                                    "approval_target_session_id": owner_session_id,
                                }
                            },
                        )
    
                        kernel = getattr(self, "kernel", None)
                        scheduler = getattr(kernel, "scheduler", None) if kernel else None
                        if scheduler and work_id:
                            scheduler.update_work_status(work_id, WorkStatus.WAITING_USER)
    
                        if callbacks and 'send_status' in callbacks:
                            callbacks['send_status'](
                                'thinking',
                                {'code': 'waiting_user', 'message': approval_msg, 'action': plan.action_id}
                            )
    
                        if work_id and scheduler:
                            decision = self._wait_for_work_decision(work_id, cancel_check)
                            outcome = decision.get("decision")
                            if outcome == "approve":
                                if work_id:
                                    scheduler.update_work_status(work_id, WorkStatus.RUNNING)
                                target_session.pending_action = None
                                self._save_session(target_session)
                                note = (decision.get("note") or "").strip()
                                if note:
                                    session.add_message("user", f"[Approval note]: {note}")
                                logger.info(f"Approval received for work {work_id}; continuing sensitive action.")
                            elif outcome == "inject":
                                note = (decision.get("note") or "").strip()
                                if note:
                                    session.add_message("user", note)
                                if work_id:
                                    scheduler.update_work_status(work_id, WorkStatus.RUNNING)
                                continue
                            else:
                                if work_id:
                                    scheduler.update_work_status(work_id, WorkStatus.CANCELLED)
                                target_session.pending_action = None
                                self._save_session(target_session)
                                final_response = "Sensitive action was denied or timed out. I stopped this worker safely."
                                session.add_message("assistant", final_response)
                                final_response_persisted = True
                                if callbacks and 'send_response' in callbacks:
                                    callbacks['send_response'](final_response, is_chunk=True)
                                    final_response_streamed = True
                                if callbacks and 'send_complete' in callbacks:
                                    callbacks['send_complete']()
                                    stream_completed = True
                                break
                        else:
                            # No work channel available: keep classic in-session pending action.
                            session.pending_action = {"action": plan.action_id, "params": plan.args}
                            session.add_message("assistant", approval_msg)
                            if callbacks and 'send_complete' in callbacks:
                                callbacks['send_complete']()
                                stream_completed = True
                            return approval_msg
    
                    # Execute via SkillRegistry
                    if callbacks and 'send_status' in callbacks:
                        callbacks['send_status']('executing', {'action': plan.action_id, 'label': f"Executing {plan.action_id}..."})
    
                    # Emit global event for real-time synchronization
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
                        "session_id": session_id,
                        "user_input": user_input,
                        "allowed_actions": self._get_allowed_actions_for_session(session),
                        "skill_registry": self.skill_registry,
                    }
                    
                    # Access Control: Pre-Dispatch Gate
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
    
                    # Observe
                    # Truncate results in history to avoid bloating context
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
                    last_generated_attachment_paths = self._extract_attachment_paths_from_result(structured_result)
                    for media_path in last_generated_attachment_paths:
                        if media_path not in media_used:
                            media_used.append(media_path)
                    if plan.action_id not in {"reply", "error"}:
                        session.context["last_action_plan"] = {
                            "action_id": plan.action_id,
                            "args": plan.args if isinstance(plan.args, dict) else {},
                            "status": result_status,
                            "reason": result_reason,
                            "ts": time.time(),
                        }

                    if result_status == "failure":
                        if (
                            plan.action_id == "system.control.screenshot"
                            and result_reason in {"SYSTEM_DRIVER_UNAVAILABLE", "SCREENSHOT_FAILED"}
                        ):
                            logger.warning(
                                "Non-retriable screenshot failure detected (%s). Ending turn without retries.",
                                result_reason,
                            )
                            is_pt = self._session_locale(session).startswith("pt")
                            details = str(structured_result.get("message") or truncated_result or "").strip() if isinstance(structured_result, dict) else str(truncated_result or "").strip()
                            if len(details) > 220:
                                details = details[:220] + "..."
                            if is_pt:
                                final_response = (
                                    "Não consegui capturar a tela neste ambiente porque o recurso de screenshot não está disponível. "
                                    f"Detalhe técnico: {details or result_reason}."
                                )
                            else:
                                final_response = (
                                    "I could not capture the screen in this environment because screenshot tooling is unavailable. "
                                    f"Technical detail: {details or result_reason}."
                                )
                            session.state_summary["last_error"] = result_reason
                            session.add_message("assistant", final_response)
                            final_response_persisted = True
                            if callbacks and 'send_response' in callbacks:
                                callbacks['send_response'](final_response, is_chunk=True)
                                final_response_streamed = True
                            if callbacks and 'send_complete' in callbacks:
                                callbacks['send_complete']()
                                stream_completed = True
                            break

                        # Deterministic recovery: when Google Maps billing is disabled,
                        # fallback once to a web links search instead of retrying maps.
                        if (
                            plan.action_id == "maps.search.search"
                            and isinstance(structured_result, dict)
                            and maps_billing_fallback_attempts < 1
                        ):
                            fallback_action = str(structured_result.get("fallback_action") or "").strip()
                            fallback_params = structured_result.get("fallback_params")
                            if fallback_action and isinstance(fallback_params, dict):
                                maps_billing_fallback_attempts += 1
                                logger.warning(
                                    "Maps billing failure detected. Switching to fallback action '%s' with params=%s",
                                    fallback_action,
                                    fallback_params,
                                )
                                plan = ActionPlan(
                                    action_id=fallback_action,
                                    args=fallback_params,
                                    confidence=1.0,
                                    source="internal",
                                    thought=(
                                        "Google Maps unavailable due to billing. "
                                        "Running fallback to web search with semantic query."
                                    ),
                                )
                                emit_user_progress(
                                    progress_note("fallback", action_id=fallback_action),
                                    event_key=f"fallback:{plan.action_id}:{fallback_action}",
                                )
                                continue
    
                        failure_signature = (plan.action_id, param_str, self._signature_from_result(raw_result))
                        if failure_signature == last_failure_signature:
                            repeated_failure_count += 1
                        else:
                            repeated_failure_count = 1
                            last_failure_signature = failure_signature
                        if repeated_failure_count == 1:
                            emit_user_progress(
                                progress_note("failure_recovery", action_id=plan.action_id),
                                event_key=f"failure_recovery:{plan.action_id}:{loops}",
                            )
                        session.state_summary["last_error"] = result_reason
                        if planner_tree:
                            current_step = next((s for s in planner_tree if s.get("status") == "in_progress"), None)
                            if current_step:
                                current_step["status"] = "blocked"
                            session.plan = self._flatten_plan_lines(planner_tree)
                            session.state_summary["cursor"] = self._progress_cursor(planner_tree, loops, max_steps)
                    else:
                        repeated_failure_count = 0
                        last_failure_signature = None
                        if planner_tree:
                            current_step = next((s for s in planner_tree if s.get("status") == "in_progress"), None)
                            if current_step:
                                current_step["status"] = "done"
                                next_pending = next((s for s in planner_tree if s.get("status") == "pending"), None)
                                if next_pending:
                                    next_pending["status"] = "in_progress"
                            session.plan = self._flatten_plan_lines(planner_tree)
                            session.state_summary["cursor"] = self._progress_cursor(planner_tree, loops, max_steps)
                    
                    summary = None
                    # Logical Log Compression: If output > 2000 chars, summarize it
                    # EXEMPT: Vision results and search results should never be summarized as they contain vital semantic/structural data
                    exemptions = [
                        "vision.",
                        "youtube.",
                        "spotify.",
                        "web.",
                        "deezer.",
                        "maps.",
                        "wikipedia.",
                        "system.control.skills.",
                    ]
                    is_exempt = any(plan.action_id.startswith(ext) for ext in exemptions)
                    
                    if len(raw_result) > obs_limits["summarize_threshold"] and not is_exempt:
                        logger.info(f"Large output detected ({len(raw_result)} chars). Summarizing...")
                        summary = self._clip_text(self.llm_manager.summarize_output(raw_result), 900)
                        observation = (
                            f"RESULT OF ACTION {plan.action_id} "
                            f"[status={result_status}; reason={result_reason}] (Summarized): {summary}"
                        )
                    else:
                        observation = (
                            f"RESULT OF ACTION {plan.action_id} "
                            f"[status={result_status}; reason={result_reason}]: {truncated_result}"
                        )
                    logger.info(
                        "Observation Metrics | Session: %s | Action: %s | RawTok~%d | TruncTok~%d | Summarized: %s",
                        session_id,
                        plan.action_id,
                        len(raw_result) // 4,
                        len(truncated_result) // 4,
                        "yes" if summary else "no",
                    )
                    self._capture_observation_metrics(
                        session_id=session_id,
                        action_id=plan.action_id,
                        raw_result=raw_result,
                        truncated_result=truncated_result,
                        summarized=bool(summary),
                    )
                    
                    session.add_message("system", observation, msg_type="reasoning", summary=summary)
                    session.state_summary['last_outcome'] = summary if summary else truncated_result[:300]
    
                    # Persist reasoning/action episodes for future retrieval/debugging.
                    try:
                        self.episodic_memory.store_episode(
                            user_input=user_input,
                            thought=plan.thought or "",
                            action=plan.action_id,
                            observation=observation,
                            status=result_status,
                        )
                    except Exception as e:
                        logger.debug(f"Failed to store episodic memory: {e}")
                    
                    # Log the observation for diagnostic visibility (Professional CLI/assistant.log)
                    logger.info(observation)
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
                                "max_steps": max_steps,
                                "replan_budget": replan_budget,
                                "replans_used": replans_used,
                                "steps": planner_tree,
                            },
                            "data": {
                                "actions_used": actions_used[-80:],
                                "skills_used": skills_used[-40:],
                                "media_used": media_used[-80:],
                                "queued_messages": queued_messages[-40:],
                            },
                        },
                    )

                    # Deterministic completion for informational searches.
                    # If we already have a successful search result, consolidate to user reply
                    # instead of re-invoking the same action.
                    if (
                        result_status == "success"
                        and self._should_autocomplete_after_success_action(user_input, plan.action_id)
                    ):
                        recovered_reply = self._reply_from_last_success(
                            action_id=plan.action_id,
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
                            session.add_message("assistant", final_response, attachments=final_structured_attachments)
                            final_response_persisted = True
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

                    # Fast-path for vision outputs: avoid unnecessary re-reasoning loops.
                    # Vision skills already return user-facing text in "text".
                    if result_status == "success" and plan.action_id.startswith("vision."):
                        recovered_reply = self._reply_from_last_success(
                            action_id=plan.action_id,
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
                            session.add_message("assistant", final_response, attachments=final_structured_attachments)
                            final_response_persisted = True
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
    
                    # Deterministic media handoff: for "play/reproduzir" intents, do not wait for the LLM
                    # to decide the open/play step after a successful search.
                    if (
                        result_status == "success"
                        and plan.action_id in {"youtube.search.find", "deezer.search.search", "spotify.search.search"}
                        and isinstance(last_action_structured, dict)
                        and media_play_handoff_attempts < 2
                    ):
                        request_text = (user_input or "").lower()
                        wants_play = any(
                            cue in request_text
                            for cue in ("reproduz", "reproduzir", "reporduz", "toca", "tocar", "play", "ouvir")
                        )
                        best = last_action_structured.get("best") if isinstance(last_action_structured.get("best"), dict) else None
                        best_url = (best.get("url") if best else None) or last_action_structured.get("url")
                        if wants_play and isinstance(best_url, str) and best_url.strip():
                            media_play_handoff_attempts += 1
                            logger.info(
                                "Auto handoff to browser.automator.play_url using best search result: %s",
                                best_url,
                            )
                            plan = ActionPlan(
                                action_id="browser.automator.play_url",
                                args={"url": best_url.strip()},
                                confidence=1.0,
                                source="internal",
                                thought="Search succeeded and user requested playback. Handing off directly to browser playback.",
                            )
                            continue
    
                    # Fast-path for media open flows when playback is explicitly confirmed.
                    if result_status == "success" and plan.action_id in {"browser.automator.open", "browser.automator.play_url"}:
                        if isinstance(last_action_structured, dict) and last_action_structured.get("playback_confirmed") is True:
                            recovered_reply = self._reply_from_last_success(
                                action_id=plan.action_id,
                                structured_result=last_action_structured,
                                raw_output=last_action_output,
                                language=self._session_locale(session),
                            )
                            if recovered_reply:
                                final_response = recovered_reply
                                session.add_message("assistant", final_response)
                                final_response_persisted = True
                                session.scratchpad = ""
                                session.plan = []
                                if callbacks and 'send_response' in callbacks:
                                    callbacks['send_response'](final_response, is_chunk=True)
                                    final_response_streamed = True
                                if callbacks and 'send_complete' in callbacks:
                                    callbacks['send_complete']()
                                    stream_completed = True
                                break
    
                    # Strict completion gate for playback requests:
                    # only consider completed when browser/system exposes active playback.
                    if (
                        media_request
                        and plan.action_id in {"browser.automator.play_url", "browser.automator.control"}
                        and isinstance(last_action_structured, dict)
                    ):
                        if last_action_structured.get("playback_confirmed") is True:
                            final_response = "Playback started and confirmed in the browser player."
                            session.add_message("assistant", final_response)
                            final_response_persisted = True
                            if callbacks and 'send_response' in callbacks:
                                callbacks['send_response'](final_response, is_chunk=True)
                                final_response_streamed = True
                            if callbacks and 'send_complete' in callbacks:
                                callbacks['send_complete']()
                                stream_completed = True
                            break
    
                    # General completion-oriented recovery:
                    # when "open" reports partial completion, continue autonomously on the current page
                    # instead of stopping at "page opened".
                    if plan.action_id in {"browser.automator.open", "browser.automator.play_url"} and isinstance(last_action_structured, dict):
                        open_status = str(last_action_structured.get("status") or "").strip().lower()
                        playback_confirmed = last_action_structured.get("playback_confirmed")
                        is_partial = open_status == "partial" or playback_confirmed is False
                        if is_partial and browser_open_recovery_attempts < 2:
                            browser_open_recovery_attempts += 1
                            open_url = str(last_action_structured.get("url") or "").lower()
                            if "youtube.com" in open_url or "deezer.com" in open_url or "spotify.com" in open_url:
                                logger.info(
                                    "Open returned partial completion for media URL. Triggering browser.automator.control (play) attempt %s.",
                                    browser_open_recovery_attempts,
                                )
                                plan = ActionPlan(
                                    action_id="browser.automator.control",
                                    args={"action": "play"},
                                    confidence=1.0,
                                    source="internal",
                                    thought="Partial playback after open. Trying deterministic media play control before vision-based automation.",
                                )
                                continue
                            logger.info(
                                "Open returned partial completion. Triggering autonomous continuation attempt %s.",
                                browser_open_recovery_attempts,
                            )
                            continuation_task = (
                                f"You already opened the target page. Continue until the user request is actually completed: "
                                f"'{user_input}'. "
                                "On the current page, handle consent/cookie banners if present, click the primary action button "
                                "(play/start/confirm as appropriate), and verify outcome using visible page state. "
                                "If completion is blocked, stop and return a concise blocker explanation."
                            )
                            plan = ActionPlan(
                                action_id="browser.automator.automate",
                                args={"task": continuation_task},
                                confidence=1.0,
                                source="internal",
                                thought="Detected partial completion after opening page. Continuing autonomous execution to finish the task.",
                            )
                            media_vision_fallback_attempts += 1
                            continue
    
                    # If deterministic play control still can't confirm playback,
                    # escalate to vision automation on the same active tab.
                    if plan.action_id == "browser.automator.control" and isinstance(last_action_structured, dict):
                        control_action = str(last_action_structured.get("control_action") or "").lower()
                        control_status = str(last_action_structured.get("status") or "").lower()
                        playback_confirmed = last_action_structured.get("playback_confirmed")
                        needs_recovery = (
                            control_action == "play"
                            and (
                                control_status in {"error", "partial"}
                                or playback_confirmed is False
                            )
                        )
                        if needs_recovery and browser_control_recovery_attempts < 1:
                            browser_control_recovery_attempts += 1
                            logger.info(
                                "Play control could not confirm playback. Escalating to browser.automator.automate (attempt %s).",
                                browser_control_recovery_attempts,
                            )
                            continuation_task = (
                                f"You are already on the correct media page. Finish the user request: '{user_input}'. "
                                "Do not open a new tab. Reuse the current page, handle consent/cookie overlays, "
                                "click the visible play/start control, and verify playback using on-page media state. "
                                "If blocked, explain clearly what you see on screen and capture a screenshot path."
                            )
                            plan = ActionPlan(
                                action_id="browser.automator.automate",
                                args={"task": continuation_task},
                                confidence=1.0,
                                source="internal",
                                thought="Deterministic play control did not verify playback. Escalating to vision automation on current tab.",
                            )
                            media_vision_fallback_attempts += 1
                            continue
    
                    # Stop retry storm for media requests after vision fallback failure.
                    if (
                        media_request
                        and plan.action_id in {"browser.automator.automate", "browser.automator.internal_search"}
                        and result_status == "failure"
                    ):
                        failure_text = (last_action_output or "").lower()
                        quota_hit = any(
                            marker in failure_text
                            for marker in (
                                "402",
                                "429",
                                "free-models-per-day",
                                "rate limit exceeded",
                                "prompt tokens limit exceeded",
                                "requires more credits",
                                "resource_exhausted",
                                "out of credits",
                                "no fallback_llm configured",
                            )
                        )
                        if quota_hit or media_vision_fallback_attempts >= 1:
                            final_response = (
                                "Could not complete playback automatically. "
                                "The player was not confirmed as running and visual automation failed due to provider limit/quota. "
                                "The task was ended without success to avoid loops."
                            )
                            session.add_message("assistant", final_response)
                            final_response_persisted = True
                            if callbacks and 'send_response' in callbacks:
                                callbacks['send_response'](final_response, is_chunk=True)
                                final_response_streamed = True
                            if callbacks and 'send_complete' in callbacks:
                                callbacks['send_complete']()
                                stream_completed = True
                            break
    
                    # Hard guard for repeated identical failures.
                    if repeated_failure_count >= 2:
                        logger.warning(
                            f"Repeated failure detected for action '{plan.action_id}'. Breaking loop to avoid delirium."
                        )
                        final_response = self.i18n.t(
                            "reply.loop_stuck",
                            locale=self._session_locale(session),
                            action_id=plan.action_id,
                        )
                        self._touch_work_context(
                            work_id,
                            {
                                "summary": {
                                    "status": "blocked",
                                    "last_error": result_reason,
                                    "cursor": session.state_summary.get("cursor"),
                                },
                                "planner": {"steps": planner_tree},
                            },
                        )
                        session.add_message("assistant", final_response)
                        final_response_persisted = True
                        if callbacks and 'send_response' in callbacks:
                            callbacks['send_response'](final_response, is_chunk=True)
                            final_response_streamed = True
                        if callbacks and 'send_complete' in callbacks:
                            callbacks['send_complete']()
                            stream_completed = True
                        break
                    
                    # Reset plan for next iteration to allow re-reasoning
                    plan = None
                
                # Exit block for 'while'
                if final_response is None:
                    logger.warning("Reasoning loop ended without a final response.")
                    final_response = self.i18n.t("reply.no_plan_resolved", locale="en")
                    if callbacks and 'send_response' in callbacks:
                        callbacks['send_response'](final_response, is_chunk=True)
                        final_response_streamed = True
    
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
    
            # Guarantee final response lifecycle (persist -> stream -> complete) in all loop exit paths.
            if final_response and not final_response_persisted and not session.pending_action:
                session.add_message("assistant", final_response, attachments=final_structured_attachments)
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
            # Releasing lock
            if acquired:
                lock.release()

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

        if action == "browser.automator.control":
            ctrl = str(
                payload.get("control_action")
                or payload.get("action")
                or ""
            ).strip().lower()
            if ctrl == "pause":
                return "Pronto, pausei a música." if is_pt else "Done, I paused the music."
            if ctrl == "play":
                return "Pronto, retomei a reprodução." if is_pt else "Done, I resumed playback."
            if ctrl == "next":
                return "Pronto, passei para a próxima faixa." if is_pt else "Done, I skipped to the next track."
            if ctrl == "mute":
                return "Pronto, silenciei o áudio." if is_pt else "Done, I muted the audio."
            return "Pronto, apliquei o controle de mídia." if is_pt else "Done, I applied the media control."

        if action == "system.control.screenshot":
            path = str(payload.get("path") or "").strip()
            if path:
                return f"Pronto, capturei a tela: {path}" if is_pt else f"Done, I captured the screen: {path}"
            return "Pronto, capturei a tela e já anexei para você." if is_pt else "Done, I captured the screen and attached it for you."

        text = payload.get("text")
        if isinstance(text, str) and text.strip() and not AgentOrchestrator._looks_like_technical_text(text):
            return text.strip()

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
                return "\n\n".join(lines)

        best = payload.get("best")
        if isinstance(best, dict):
            best_url = str(best.get("url") or "").strip()
            best_title = str(best.get("title") or best.get("name") or "").strip()
            if best_url or best_title:
                if best_url and best_title:
                    if is_pt:
                        return f"Melhor resultado encontrado: {best_title}\n{best_url}"
                    return f"Best result found: {best_title}\n{best_url}"
                if is_pt:
                    return f"Melhor resultado encontrado:\n{best_url or best_title}"
                return f"Best result found:\n{best_url or best_title}"

        # Last resort: avoid dumping huge JSON to user.
        raw = (raw_output or "").strip()
        if raw and not raw.startswith("{"):
            excerpt = raw if len(raw) <= 700 else raw[:700] + "..."
            return excerpt

        action = action_id or "the requested action"
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
    def _is_media_play_request(user_input: str) -> bool:
        text = (user_input or "").lower()
        if not text:
            return False
        play_cues = (
            "reproduz",
            "reproduzir",
            "reproduza",
            "reporduz",
            "toca",
            "tocar",
            "play",
            "ouvir",
            "abre",
            "abrir",
        )
        provider_cues = ("youtube", "youtbe", "ytoutbe", "yt music", "youtube music", "deezer", "spotify")
        media_object_cues = ("musica", "música", "song", "faixa", "album", "álbum", "cantor", "artista")
        return any(c in text for c in play_cues) and (
            any(p in text for p in provider_cues) or any(m in text for m in media_object_cues)
        )

    @staticmethod
    def _is_media_pronoun_open_request(user_input: str) -> bool:
        text = (user_input or "").lower()
        if not text:
            return False
        open_cues = ("abre", "abrir", "open")
        pronoun_cues = ("ela", "ele", "isso", "essa", "esse", "it", "that", "this")
        provider_cues = ("youtube", "deezer", "spotify")
        return any(c in text for c in open_cues) and any(p in text for p in pronoun_cues) and any(
            s in text for s in provider_cues
        )

    @staticmethod
    def _extract_recent_media_url_from_history(session: Session) -> str:
        url_re = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
        providers = ("youtube.com", "youtu.be", "deezer.com", "spotify.com")
        history = session.history if isinstance(session.history, list) else []
        for msg in reversed(history):
            content = str(msg.get("content") or "").replace("\\/", "/")
            matches = url_re.findall(content)
            for url in reversed(matches):
                candidate = url.strip()
                if any(p in candidate.lower() for p in providers):
                    return candidate
        return ""

    @classmethod
    def _should_autocomplete_after_success_action(cls, user_input: str, action_id: str) -> bool:
        """
        Finalize early for informational searches to avoid repeated identical actions.
        """
        action = (action_id or "").strip().lower()
        if not action:
            return False

        # Wikipedia requests are informational in this orchestrator flow.
        if action == "wikipedia.search":
            return True

        # Screenshot is a one-shot operational action. After success, we should
        # immediately consolidate response + attachment and finish the turn.
        if action == "system.control.screenshot":
            return True

        # Media searches should only continue when user explicitly asked to play/open.
        if action in {"youtube.search.find", "deezer.search.search", "spotify.search.search"}:
            return not cls._is_media_play_request(user_input)

        return False

    @staticmethod
    def _looks_like_instruction_only_query(query: str) -> bool:
        q = QuerySemantics.sanitize(query).lower()
        if not q:
            return True
        if len(q) <= 3:
            return True
        if re.match(
            r"^(?:e\s+)?(?:forne[cç]a|fornecer|fa[cç]a|resuma|sumarize|summarize|traga|d[eê])\b",
            q,
            re.IGNORECASE,
        ):
            return True
        if any(token in q for token in ("resumo", "summary", "explicação", "explanation")) and len(q.split()) <= 4:
            return True
        return False

    @staticmethod
    def _derive_media_search_action_and_query(user_input: str) -> tuple[Optional[str], str]:
        text = (user_input or "").strip()
        lower = text.lower()

        action_id: Optional[str] = None
        if "deezer" in lower:
            action_id = "deezer.search.search"
        elif "spotify" in lower:
            action_id = "spotify.search.search"
        elif any(token in lower for token in ("youtube", "youtbe", "ytoutbe", "yt music", "youtube music")):
            action_id = "youtube.search.find"
        else:
            # Default media surface for generic playback requests without provider.
            action_id = "youtube.search.find"

        cleaned = lower
        patterns = [
            r"\b(reproduz|reproduzir|reporduz|toca|tocar|play|ouvir|abre|abrir)\b",
            r"\b(no|na|do|da|de|em|para|a|o|uma|um)\b",
            r"\b(youtube music|ytoutbe music|yt music|youtube|youtbe|ytoutbe|deezer|spotify)\b",
            r"\b(musica|música|music)\b",
            r"\s+",
        ]
        for p in patterns[:-1]:
            cleaned = re.sub(p, " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(patterns[-1], " ", cleaned).strip(" \"'")
        if not cleaned:
            cleaned = text.strip()

        return action_id, cleaned

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
        return {
            "prompt": prompt,
            "turn": turn,
            "latest_observation": latest_observation,
            "observation_count": len(observations),
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
        agent_name = agent_config.get("agent_name", "Atlas")
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

        instruction_pack = self._build_instruction_pack(
            agent_name=agent_name,
            personality=personality,
            specialist_hint=specialist_hint,
            user_language=session.context.get("user_language", "en"),
            presentation_mode=presentation_mode,
            markdown_supported=bool(markdown_supported and not voice_only),
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

        prompt = self.prompt_composer.compose(
            agent_name=agent_name,
            personality=personality,
            specialist_prompt=specialist_prompt,
            presentation_directive=presentation_directive,
            instruction_pack=instruction_pack,
            sys_info=sys_info,
            location=self.location_service.get_current_location(session.context).get("city", "Unknown"),
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
            browser_pages=session.drivers_state.get("browser", {}).get("active_pages", []),
            session_summary=session.summary or "",
            scratchpad=self.scratchpad_service.read(session.session_id),
            attachments=session.context.get("last_attachments", []),
            skills_summary=skills_summary,
            skill_scope=skill_scope,
        )
        self._capture_prompt_metrics(session.session_id, prompt)
        return prompt

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

    @staticmethod
    def _looks_like_skill_discovery_query(query: str) -> bool:
        text = str(query or "").strip().lower()
        if not text:
            return False
        markers = (
            "skill",
            "skills",
            "ação",
            "acoes",
            "ações",
            "action",
            "actions",
            "namespace",
            "catalog",
            "catálogo",
            "contract",
            "contrato",
        )
        if any(marker in text for marker in markers):
            return True
        if "." in text and len(text.split(".")) >= 2:
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

    def _get_param(self, params: dict, keys: list, default=None):
        """Helper to get a parameter from a dictionary, trying multiple keys."""
        for key in keys:
            if key in params:
                return params[key]
        return default
