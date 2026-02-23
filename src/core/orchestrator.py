import os
import json
import logging
import threading
import re
import time
import datetime
import platform
import shutil
from typing import Optional, List, Dict, Callable, Any
from services.llm.manager import LLMManager
from core.intent import AgentIntent
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
from services.llm.prompt_composer import PromptComposer
from config.manager import ConfigManager
from services.location.location_service import LocationService
from utils.logging_config import get_logger, read_recent_logs
from utils.event_bus import global_event_bus

# New Resolution and Skill imports
from core.resolution.chain_resolver import FallbackChainResolver
from core.resolution.llm_resolver import LLMResolver
from core.resolution.semantic_resolver import SemanticResolver
from core.reflex.registry import ReflexRegistry
from core.reflex.resolver import ReflexResolver
from core.resolution.action_plan import ActionPlan
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
        self.access_controller = AccessController(self.config_manager.base_data_dir)
        self.location_service = LocationService()
        self.sessions = {} # Dict[str, Session]
        self.session_locks = {} # Concurrency guards + persistence serialization (RLock per session)
        self.browser_driver = None
        self.system_driver = None
        # Persistence Path
        self.base_data_dir = self.config_manager.base_data_dir
        self.sessions_dir = os.path.join(self.base_data_dir, 'sessions')
        if not os.path.exists(self.sessions_dir):
            os.makedirs(self.sessions_dir)

        # Start GC for Playback
        self._start_playback_gc()
        
        self.initialized = True

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
        self.skill_loader.kernel = kernel

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
            prompt = f"Gere um título MUITO CURTO (2 a 4 palavras no máximo) resumindo o assunto que o usuário quer tratar. Responda APENAS com o título e nada mais.\n\nUsuário: {first_user_input}"
            
            # Use generate_intent from Kernel's LLM Manager
            intent = self.llm_manager.generate_intent(
                user_input=prompt,
                history=[],
                system_prompt="Você é um assistente que dá títulos às conversas baseadas no primeiro input do usuário. Mantenha o título bem curto. Responda APENAS E EXCLUSIVAMENTE com o título em 2 a 4 palavras."
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

    def process(self, user_input: str, session_id: str = "default", on_partial_response=None, user_data: dict = None, callbacks: dict = None, cancel_check: Callable[[], bool] = None, initial_plan: ActionPlan = None, context: PrincipalContext = None, attachments: List[str] = None):
        """
        Agentic Loop: Input -> Loop [Reason -> Act -> Observe] -> Response
        """
        logger.debug(f"Processing input in session '{session_id}': {user_input}")

        # Get or Create Session
        session = self.get_session_robust(session_id)
        
        # Get or create session lock (reentrant to safely nest persistence calls).
        lock = self._get_or_create_session_lock(session_id)
        
        # Concurrency Guard
        # Increased timeout to 120s to accommodate long LLM turns/dashboard generation
        acquired = lock.acquire(blocking=True, timeout=120)
        if not acquired:
            logger.warning(f"Timeout waiting for session lock: {session_id}")
            return "Ainda estou processando sua solicitação anterior. Por favor, aguarde mais um momento ou tente novamente em breve."

        try:
            # Check for cancellation before starting the loop (cooperative)
            if cancel_check and cancel_check():
                logger.info(f"Task for session {session_id} was cancelled before starting.")
                return None
            
            # Re-fetch session ensuring it's not None
            if not session:
                interface = "web"
                if session_id.startswith("telegram"): interface = "telegram"
                elif session_id.startswith("voice"): interface = "voice"
                session = self.create_session(session_id, interface=interface)

            session.last_interaction = time.time()
            if user_data:
                session.context.update(user_data)
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

            # HITL: Handle resumed pending action
            resumed_intent = None
            if session.pending_action:
                if any(confirm in user_input.lower() for confirm in ["sim", "yes", "autorizo", "ok", "pode", "manda"]):
                    logger.info(f"User authorized pending action: {session.pending_action['action']}")
                    resumed_action = session.pending_action
                    session.pending_action = None
                    session.add_message("user", user_input)
                    # Create the intent to execute
                    resumed_intent = AgentIntent(
                        thought=f"Usuário autorizou a ação {resumed_action['action']}. Executando agora conforme solicitado.",
                        action=resumed_action['action'],
                        params=resumed_action['params']
                    )
                else:
                    session.pending_action = None
                    session.add_message("user", user_input)
                    return "Entendi. Cancelei a ação e não prosseguirei com esse passo."

            # 1. Start Reasoning Loop (Max 15 steps)
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
            final_response = "Desculpe, não consegui processar sua solicitação após o limite de passos."
            final_structured_attachments = None
            final_response_persisted = False
            final_response_streamed = False
            stream_completed = False

            try:
                while loops < 15:
                    if cancel_check and cancel_check():
                        logger.info(f"Process cancelled for session {session_id}")
                        return "Tarefa cancelada pelo usuário."

                    loops += 1
                    logger.info(f"--- Session {session_id} | Loop {loops}/15 ---")
                    
                    if on_partial_response and loops % 3 == 0: 
                        on_partial_response(f"Refining reasoning (Step {loops}/15)...")

                    if not plan:
                        if callbacks and 'send_status' in callbacks:
                            callbacks['send_status']('thinking', {'step': loops, 'max_steps': 15, 'label': 'Thinking about next action...'})
                        
                        # Emit global event for real-time synchronization
                        global_event_bus.emit_threadsafe({
                            "type": "status",
                            "session_id": session_id,
                            "phase": "thinking",
                            "message": "Thinking about next action...",
                            "payload": {'step': loops, 'max_steps': 15}
                        })

                        reasoning_context = {
                            "session": session,
                            "system_prompt": self._construct_system_prompt(session, user_input=user_input),
                            "attachments": attachments if loops == 1 else None, # Only send attachments on first reasoning step
                            "history": session.get_context_for_llm(limit_msgs=20, limit_tokens=6000),
                            "allowed_actions": self._get_allowed_actions_for_session(session),
                            "skill_registry": self.skill_registry,
                        }
                        plan = self.intent_resolver_chain.resolve(user_input, reasoning_context)

                    if not plan:
                        logger.warning("No plan resolved. Breaking loop.")
                        break

                    # Update state from plan metadata if available
                    if plan.metadata and 'state_summary' in plan.metadata:
                        session.state_summary.update(plan.metadata['state_summary'])

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
                            suggestion_text = ", ".join(suggestions) if suggestions else "nenhuma sugestão"
                            logger.warning(
                                f"Unknown action from resolver: {plan.action_id} | suggestions: {suggestion_text}"
                            )
                            final_response = (
                                f"A ação '{plan.action_id}' não existe no runtime atual. "
                                f"Sugestões próximas: {suggestion_text}. "
                                "Tente reformular o pedido com mais contexto."
                            )
                            plan = ActionPlan(
                                action_id="reply",
                                args={},
                                response_text=final_response,
                                source="internal",
                            )

                    logger.info(f"Action: {plan.action_id} | Confidence: {plan.confidence}")
                    
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
                        logger.warning(f"Loop detected (3 identical actions/params): {current_signature}. Breaking.")
                        recovered_reply = self._reply_from_last_success(
                            action_id=plan.action_id,
                            structured_result=last_action_structured,
                            raw_output=last_action_output,
                        ) if last_action_status == "success" else None

                        if recovered_reply:
                            if callbacks and 'send_status' in callbacks:
                                callbacks['send_status'](
                                    'executing',
                                    {
                                        'code': 'loop_break_success',
                                        'message': f"Ação repetida detectada em {plan.action_id}; consolidando resposta final com o último resultado válido.",
                                        'action': plan.action_id
                                    }
                                )
                            final_response = recovered_reply
                        else:
                            if callbacks and 'send_status' in callbacks:
                                callbacks['send_status'](
                                    'error',
                                    {
                                        'code': 'loop_break',
                                        'message': 'Detectei repetitividade exata sem progresso. Por favor, tente reformular o pedido ou fornecer mais detalhes.',
                                        'action': plan.action_id
                                    }
                                )
                            final_response = "Detectei repetitividade exata sem progresso. Por favor, tente reformular o pedido ou fornecer mais detalhes."
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
                         logger.warning(f"Action loop detected (Action '{plan.action_id}' repeated 4/5 times). Breaking.")
                         recovered_reply = self._reply_from_last_success(
                             action_id=plan.action_id,
                             structured_result=last_action_structured,
                             raw_output=last_action_output,
                         ) if last_action_status == "success" else None

                         if callbacks and 'send_status' in callbacks:
                             callbacks['send_status'](
                                 'error',
                                 {
                                     'code': 'loop_break',
                                     'message': (
                                         f"Parece que estou travado tentando usar a ação '{plan.action_id}' repetidamente."
                                         if recovered_reply else
                                         f"Parece que estou travado tentando usar a ação '{plan.action_id}' repetidamente sem sucesso. Vou parar para evitar loop infinito."
                                     ),
                                     'action': plan.action_id
                                 }
                             )

                         final_response = recovered_reply or f"Parece que estou travado tentando usar a ação '{plan.action_id}' repetidamente sem sucesso. Vou parar para evitar loop infinito."
                         # For a hard break, we force a valid reply object for internal history consistency
                         plan = ActionPlan(
                             action_id='reply',
                             args={},
                             response_text=final_response,
                             source='internal',
                             attachments=(last_generated_attachment_paths or None),
                         )
                         plan.thought = "Loop de ações detectado. Interrompendo para evitar gasto excessivo de tokens e tempo."
                    
                    # Add current turn to history for context
                    # Use JSON to reinforce the pattern the LLM must follow
                    history_data = {
                        "thought": plan.thought,
                        "plan": plan.metadata.get('plan', []),
                        "action": plan.action_id,
                        "params": plan.args
                    }
                    history_entry = json.dumps(history_data, ensure_ascii=False)
                    session.add_message("assistant", history_entry, msg_type="reasoning")

                    # Deterministic guard against "fake completion" in operational media requests.
                    # If first plan is reply for a playback request, force an actionable search first.
                    if (
                        plan.action_id == 'reply'
                        and plan.source != 'internal'
                        and last_action_id is None
                        and self._is_media_play_request(user_input)
                    ):
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
                        )
                        
                        # Process attachments
                        attachment_inputs = plan.attachments or last_generated_attachment_paths
                        structured_attachments = self._standardize_attachments(session, attachment_inputs) if attachment_inputs else None

                        if not final_response and structured_attachments:
                            final_response = "Aqui está o arquivo solicitado."
                        
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
                            callbacks['send_status']('error', {'code': 'action_error', 'message': f"Desculpe, ocorreu um erro durante o processamento: {plan.thought}"})
                            
                        final_response = f"Desculpe, ocorreu um erro durante o processamento: {plan.thought}"
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
                        session.pending_action = {"action": plan.action_id, "params": plan.args}
                        approval_msg = self.safety_service.get_approval_message(plan.action_id, plan.args)
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
                    truncated_result = raw_result[:2000] + "..." if len(raw_result) > 2000 else raw_result
                    result_status, result_reason = self._assess_action_result(result, raw_result)
                    structured_result = self._extract_structured_result(result, raw_result)
                    last_action_status = result_status
                    last_action_reason = result_reason
                    last_action_id = plan.action_id
                    last_action_output = truncated_result
                    last_action_structured = structured_result
                    last_generated_attachment_paths = self._extract_attachment_paths_from_result(structured_result)

                    if result_status == "failure":
                        failure_signature = (plan.action_id, param_str, self._signature_from_result(raw_result))
                        if failure_signature == last_failure_signature:
                            repeated_failure_count += 1
                        else:
                            repeated_failure_count = 1
                            last_failure_signature = failure_signature
                        session.state_summary["last_error"] = result_reason
                    else:
                        repeated_failure_count = 0
                        last_failure_signature = None
                    
                    summary = None
                    # Logical Log Compression: If output > 2000 chars, summarize it
                    # EXEMPT: Vision results and search results should never be summarized as they contain vital semantic/structural data
                    exemptions = ["vision.", "youtube.", "spotify.", "web.", "deezer.", "maps.", "wikipedia."]
                    is_exempt = any(plan.action_id.startswith(ext) for ext in exemptions)
                    
                    if len(raw_result) > 2000 and not is_exempt:
                        logger.info(f"Large output detected ({len(raw_result)} chars). Summarizing...")
                        summary = self.llm_manager.summarize_output(raw_result)
                        observation = (
                            f"RESULT OF ACTION {plan.action_id} "
                            f"[status={result_status}; reason={result_reason}] (Summarized): {summary}"
                        )
                    else:
                        observation = (
                            f"RESULT OF ACTION {plan.action_id} "
                            f"[status={result_status}; reason={result_reason}]: {truncated_result}"
                        )
                    
                    session.add_message("system", observation, msg_type="reasoning", summary=summary)
                    session.state_summary['last_outcome'] = summary if summary else truncated_result[:300]
                    
                    # Log the observation for diagnostic visibility (Professional CLI/assistant.log)
                    logger.info(observation)

                    # Fast-path for vision outputs: avoid unnecessary re-reasoning loops.
                    # Vision skills already return user-facing text in "text".
                    if result_status == "success" and plan.action_id.startswith("vision."):
                        recovered_reply = self._reply_from_last_success(
                            action_id=plan.action_id,
                            structured_result=last_action_structured,
                            raw_output=last_action_output,
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
                            final_response = "Reprodução iniciada e confirmada no player do navegador."
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
                                "prompt tokens limit exceeded",
                                "requires more credits",
                                "resource_exhausted",
                                "falta de créditos",
                            )
                        )
                        if quota_hit or media_vision_fallback_attempts >= 1:
                            final_response = (
                                "Não foi possível concluir a reprodução automaticamente. "
                                "O player não foi confirmado em execução e a automação visual falhou por limite/cota do provedor. "
                                "A tarefa foi encerrada sem sucesso para evitar loops."
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
                    if repeated_failure_count >= 3:
                        logger.warning(
                            f"Repeated failure detected for action '{plan.action_id}'. Breaking loop to avoid delirium."
                        )
                        final_response = (
                            f"Estou travado na ação '{plan.action_id}' sem progresso real. "
                            "Preciso que você refine o objetivo ou autorize uma estratégia diferente."
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
                    final_response = "Concluí as operações internas, mas não gerei uma resposta final. Tudo parece estar em ordem."
                    if callbacks and 'send_response' in callbacks:
                        callbacks['send_response'](final_response, is_chunk=True)
                        final_response_streamed = True

            except Exception as e:
                logger.error(f"Error in reasoning loop: {e}")
                
                if callbacks and 'send_status' in callbacks:
                    callbacks['send_status']('error', {'code': 'system_error', 'message': f"Desculpe, tive um problema técnico ao processar sua solicitação: {str(e)}"})
                    
                final_response = f"Desculpe, tive um problema técnico ao processar sua solicitação: {str(e)}"

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
            # Threshold check: > 3500 tokens
            total_tokens = sum(m.get("tokens", 0) for m in session.history)
            if total_tokens > 3500:
                self._consolidate_memory(session)

            # 6. Persist and Return
            self._save_session(session)
            
            # 7. Adaptive Formatting
            channel = session.context.get('channel', 'Web')
            return self._format_response(final_response, channel)
        finally:
            # Releasing lock
            if acquired:
                lock.release()

    def _consolidate_memory(self, session: Session, force: bool = False):
        """
        Asks the LLM to summarize the session if it's getting too heavy in tokens.
        Threshold: ~3500 tokens (leaving space for system prompt and current turn).
        """
        try:
            total_tokens = sum(m.get("tokens", 0) for m in session.history)
            
            # Check threshold (e.g., 3500 tokens)
            if total_tokens < 3500 and not force:
                return

            logger.info(f"Consolidating memory for session {session.session_id} (Total tokens: {total_tokens})")
            
            # Context window for summarization: existing summary + new messages
            existing_summary = session.summary or "Nenhum resumo anterior."
            history_to_summarize = session.get_history()
            
            prompt = (
                f"Sua conversa atingiu o limite de tokens. Atualize o RESUMO RECURSIVO da sessão.\n"
                f"RESUMO ATUAL: {existing_summary}\n\n"
                "INSTRUÇÕES:\n"
                "1. Integre os fatos novos do histórico ao resumo atual de forma densa.\n"
                "2. Use formato TOON (Token-Oriented Object Notation): chaves curtas, valores diretos, sem redundância.\n"
                "3. Mantenha informações críticas: nome do usuário, preferências, metas de longo prazo e caminhos de arquivos importantes.\n"
                "4. O resultado final deve ser um UNIFICADO e REFINADO resumo, não um anexo.\n"
                "5. Contrato: Responda APENAS com um objeto JSON no formato:\n"
                "{\"thought\": \"Análise interna da compressão\", \"response_text\": \"O novo resumo em formato TOON\", \"action\": \"reply\"}"
            )
            
            summary_intent = self.llm_manager.generate_intent(prompt, history_to_summarize, "You are a recursive memory compression specialist. USE TOON FORMAT.")
            
            if summary_intent and summary_intent.response_text:
                # Update with the newly refined summary
                session.summary = summary_intent.response_text.strip()
                logger.info(f"Recursive TOON consolidation successful. Pruning history for session {session.session_id}.")
                
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
            "erro inesperado",
            "timed out",
            "timeout",
            "missing ",
            "negado:",
            "denied",
            "permission denied",
            "não autorizado",
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
    ) -> Optional[str]:
        """
        Builds a user-facing reply from the latest successful tool output.
        Used when loop guard triggers after repeated successful actions.
        """
        payload = structured_result if isinstance(structured_result, dict) else {}

        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

        results = payload.get("results")
        if isinstance(results, list) and results:
            lines = ["Encontrei estes resultados:"]
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
                    return f"Melhor resultado encontrado: {best_title}\n{best_url}"
                return f"Melhor resultado encontrado:\n{best_url or best_title}"

        # Last resort: avoid dumping huge JSON to user.
        raw = (raw_output or "").strip()
        if raw and not raw.startswith("{"):
            excerpt = raw if len(raw) <= 700 else raw[:700] + "..."
            return excerpt

        action = action_id or "a ação solicitada"
        return f"Concluí {action} com sucesso, mas não consegui consolidar automaticamente a resposta final."

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
            "não consegui",
            "nao consegui",
            "não foi possível",
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
    ) -> str:
        """
        Prevents success hallucinations when the last tool observation was a failure.
        """
        if last_action_status != "failure":
            return response_text or ""

        reply = (response_text or "").strip()
        if not reply:
            return (
                f"A última ação `{last_action_id or 'desconhecida'}` falhou "
                f"({last_action_reason or 'sem motivo detalhado'}). "
                "Preciso ajustar a estratégia para concluir com segurança."
            )

        if cls._looks_like_failure_ack(reply):
            return reply

        if cls._looks_like_success_claim(reply):
            output_excerpt = (last_action_output or "").strip()
            if len(output_excerpt) > 220:
                output_excerpt = output_excerpt[:220] + "..."
            return (
                f"Não consegui concluir porque a ação `{last_action_id or 'desconhecida'}` falhou "
                f"({last_action_reason or 'erro'}). "
                f"Último retorno: {output_excerpt or 'sem detalhes'}."
            )

        return reply

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
        
        # Serialize state_summary to simulated TOON format
        toon_state = json.dumps(session.state_summary, indent=2, ensure_ascii=False)

        # Get naming and personality
        agent_config = self.config_manager.get("agent", {})
        agent_name = agent_config.get("agent_name", "Atlas")
        personality = agent_config.get("personality", "You are a proactive Reasoning Agent.")

        caps = session.context.get('driver_capabilities', {})
        markdown_supported = caps.get('markdown', True)
        voice_only = caps.get('voice_only', False)

        presentation_directive = "[PRESENTATION DIRECTIVE]\n"
        if voice_only:
            presentation_directive += "- You are speaking to the user via voice. DO NOT use markdown, asterisks, hashes, or complex structural formatting.\n"
            presentation_directive += "- Keep responses conversational, brief, natural, and easy to listen to.\n"
        elif not markdown_supported:
            presentation_directive += "- Use plain text only. Do not use markdown like **bold** or *italics*.\n"
            presentation_directive += "- Use simple text structure to respond.\n"
        else:
            presentation_directive += "- ALWAYS provide a visual summary in 'response_text' if a tool returns data (tables, lists, code).\n"
            presentation_directive += "- PREFER Markdown tables and code blocks for readability.\n"
            presentation_directive += "- ALWAYS use rich Markdown formatting (e.g., **bold** for emphasis, *italics*, bullet points for lists, and numbered lists) in your `response_text` by default. Do not output plain text blocks when you can structure them.\n"
            presentation_directive += "- DO NOT just say 'task complete'. SHOW the result or a snippet of what was found.\n"

        principal = self._get_principal_context(session)
        allowed_actions = self._get_allowed_actions_for_session(session)
        skills_summary = self.skill_registry.get_summary(allowed_actions)
        skill_scope = "principal-filtered" if allowed_actions is not None else "global"

        return self.prompt_composer.compose(
            agent_name=agent_name,
            personality=personality,
            specialist_prompt=self.specialist_manager.get_specialist_prompt(
                session.context.get("active_specialist", "")
            )
            or "",
            presentation_directive=presentation_directive,
            sys_info=sys_info,
            location=self.location_service.get_current_location(session.context).get("city", "Unknown"),
            channel=session.context.get("channel", "Unknown"),
            user_name=session.context.get("user_name", "Unknown"),
            toon_state=toon_state,
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
