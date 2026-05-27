import sys
import os
import time
import asyncio
import signal
import threading
import re
from dotenv import load_dotenv
load_dotenv()
from drivers.interfaces.internal_driver import InternalDriver
from core.orchestrator import AgentOrchestrator
from core.identity import PrincipalContext
# Drivers are imported dynamically in Kernel.__init__
from core.scheduler import Scheduler, WorkStatus, SYSTEM_WORKER_ANCHOR_SESSION_ID
from core.worker import WorkerManager
import queue
import time
import json
import datetime
from typing import Dict, Any, List, Tuple, Optional
from utils.logging_config import setup_logging, get_logger
from utils.event_bus import global_event_bus

# Setup Logging
setup_logging()
logger = get_logger("Kernel")

PID_FILE = "kernel.pid"

def check_single_instance():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # Check if process actually exists
            os.kill(old_pid, 0)
            logger.error(f"❌ Another assistant instance is already running (PID: {old_pid}). Exiting.")
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

        from capabilities.browser_control.session_registry import BrowserSessionRegistry
        self.browser_session_registry = BrowserSessionRegistry(base_data_dir=self.base_data_dir)
        reset_stats = self.browser_session_registry.reset_active_indexes_on_boot()
        logger.info(
            "Browser session registry reset on boot | stale_instances=%s stale_tabs=%s",
            reset_stats.get("stale_instances", 0),
            reset_stats.get("stale_tabs", 0),
        )
        
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
        self.llm_manager = self.orchestrator.llm_manager # Expose for easier capability access
        self.capability_registry = self.orchestrator.capability_registry
        self.principal_context = None # To be set by drivers/commands
        
        # 4. Storage paths used during runtime
        self.logs_dir = os.path.join(self.base_data_dir, 'logs')
        os.makedirs(self.logs_dir, exist_ok=True)
        
        from core.access_controller import IdentityService
        self.identity_service = IdentityService(self.base_data_dir)
        
        interfaces_config = self.config_manager.get_interfaces_config()

        # Initialize Drivers Dynamically
        if interfaces_config.get('voice', {}).get('enabled', True):
            from drivers.interfaces.voice.voice_driver import VoiceDriver
            logger.info("Initializing Voice Driver...")
            self.voice_driver = VoiceDriver(self, parent_dir)
            self.drivers.append(self.voice_driver)
        
        if interfaces_config.get('telegram', {}).get('enabled', True):
             from drivers.interfaces.telegram.telegram_driver import TelegramDriver
             logger.info("Initializing Telegram Driver...")
             self.telegram_driver = TelegramDriver(self, parent_dir)
             self.drivers.append(self.telegram_driver)

        if interfaces_config.get('server', {}).get('enabled', True):
             from drivers.interfaces.server_driver import ServerDriver
             logger.info("Initializing Server Driver (IPC/Web)...")
             self.server_driver = ServerDriver(self, parent_dir)
             self.drivers.append(self.server_driver)
             
        # Initialize System Driver (Host control)
        from drivers.interfaces.system_driver import SystemDriver
        logger.info("Initializing System Driver (Host Control)...")
        self.system_driver = SystemDriver(self)
        self.drivers.append(self.system_driver)

        self.browser_driver = None
        self.web_automation_driver = None
        
        
        self.sessions = {} # Dict[str, Session]
        self.session_locks = {} # Concurrency guards
        self.start_time = time.time()
        self.pending_approval_queue: Dict[str, List[Dict[str, Any]]] = {}
        self.last_approval_notification_ts: Dict[str, float] = {}
        self.permission_grants: Dict[str, Any] = {
            "global": {},
            "session": {},
            "worker": {},
        }

        # Give Orchestrator access to drivers it might need to control
        self.orchestrator.set_system_driver(self.system_driver)

    @staticmethod
    def _normalize_interface_name(interface: str) -> str:
        value = str(interface or "").strip().lower()
        if value in {"browser", "server"}:
            return "web"
        if value in {"telegram_bot"}:
            return "telegram"
        if value in {"wa", "wpp"}:
            return "whatsapp"
        return value or "unknown"

    def _infer_interface_from_session_id(self, session_id: str) -> str:
        sid = str(session_id or "").strip().lower()
        if not sid:
            return "unknown"
        if sid.startswith("telegram_"):
            return "telegram"
        if sid.startswith("voice"):
            return "voice"
        if sid.startswith("whatsapp_") or sid.startswith("wa_"):
            return "whatsapp"
        return "web"

    def _resolve_session_interface(self, session_id: str) -> str:
        session = self.orchestrator.get_session_robust(session_id) if session_id else None
        if session and getattr(session, "source", None):
            return self._normalize_interface_name(str(session.source))
        return self._normalize_interface_name(self._infer_interface_from_session_id(session_id))

    @staticmethod
    def _build_message_actor(context: Optional[PrincipalContext], is_internal: bool) -> Dict[str, Any]:
        if is_internal:
            source_name = str(getattr(context, "sender_name", "") or "System") if isinstance(context, PrincipalContext) else "System"
            source_roles = list(getattr(context, "roles", []) or []) if isinstance(context, PrincipalContext) else []
            return {
                "kind": "system_event",
                "id": "system",
                "display_name": source_name,
                "interface": "system",
                "roles": source_roles or ["system_event"],
            }
        if not isinstance(context, PrincipalContext):
            return {"kind": "human_user", "id": "unknown"}
        kind = "group_participant" if bool(getattr(context, "is_group", False)) else "human_user"
        return {
            "kind": kind,
            "id": str(getattr(context, "sender_id", "") or ""),
            "display_name": str(getattr(context, "sender_name", "") or ""),
            "chat_id": str(getattr(context, "chat_id", "") or ""),
            "chat_name": str(getattr(context, "chat_name", "") or ""),
            "interface": str(getattr(context, "interface", "") or ""),
            "roles": list(getattr(context, "roles", []) or []),
        }

    def can_interface_control_permissions(self, interface: str) -> bool:
        normalized = self._normalize_interface_name(interface)
        try:
            service = self.orchestrator.access_controller.identity_service
            interface_conf = service.get_interface_config(normalized)
            approval_cfg = interface_conf.get("approval_decisions")
            if isinstance(approval_cfg, dict):
                # Per-interface policy: interface always eligible; group gating is checked later.
                return True
        except Exception:
            pass

        # Backward compatibility with older global policy.
        cfg = self.config_manager.get("permission_controls", {}) if hasattr(self, "config_manager") else {}
        if not isinstance(cfg, dict):
            cfg = {}
        approval_cfg = cfg.get("approval_decisions", {})
        if not isinstance(approval_cfg, dict):
            return True
        allowed = approval_cfg.get("allowed_interfaces", ["*"])
        denied = approval_cfg.get("denied_interfaces", [])
        allowed_set = {self._normalize_interface_name(v) for v in (allowed or []) if str(v or "").strip()}
        denied_set = {self._normalize_interface_name(v) for v in (denied or []) if str(v or "").strip()}
        if normalized in denied_set:
            return False
        if "*" in allowed_set or "all" in allowed_set:
            return True
        return normalized in allowed_set

    def can_principal_control_permissions(self, context: PrincipalContext) -> tuple[bool, str]:
        interface = self._normalize_interface_name(getattr(context, "interface", "unknown"))
        if not self.can_interface_control_permissions(interface):
            return False, f"interface:{interface}"

        approval_cfg = None
        try:
            service = self.orchestrator.access_controller.identity_service
            interface_conf = service.get_interface_config(interface)
            local_cfg = interface_conf.get("approval_decisions")
            if isinstance(local_cfg, dict):
                approval_cfg = local_cfg
        except Exception:
            approval_cfg = None

        if not isinstance(approval_cfg, dict):
            # Backward compatibility with older global policy.
            cfg = self.config_manager.get("permission_controls", {}) if hasattr(self, "config_manager") else {}
            global_cfg = cfg.get("approval_decisions", {}) if isinstance(cfg, dict) else {}
            approval_cfg = global_cfg if isinstance(global_cfg, dict) else {}

        if not bool(approval_cfg.get("enabled", True)):
            return True, "policy_disabled"

        allowed_groups = approval_cfg.get("allowed_groups", ["*"])
        denied_groups = approval_cfg.get("denied_groups", [])
        allowed_group_set = {str(v or "").strip().lower() for v in (allowed_groups or []) if str(v or "").strip()}
        denied_group_set = {str(v or "").strip().lower() for v in (denied_groups or []) if str(v or "").strip()}

        group_id = ""
        try:
            group_id = str(self.orchestrator.access_controller.resolve_principal_group_id(context) or "").strip().lower()
        except Exception as e:
            logger.debug(f"Failed to resolve principal group for approval policy: {e}")

        if group_id and group_id in denied_group_set:
            return False, f"group:{group_id}"

        if "*" in allowed_group_set or "all" in allowed_group_set:
            return True, "ok"

        if not allowed_group_set:
            # Empty allow-list means unrestricted by group.
            return True, "ok"

        if group_id and group_id in allowed_group_set:
            return True, "ok"
        return False, f"group:{group_id or 'unknown'}"

    @staticmethod
    def _permission_signature(action_id: str, args: Dict[str, Any]) -> str:
        action = str(action_id or "").strip().lower()
        if not action:
            return ""
        safe_args = args if isinstance(args, dict) else {}
        try:
            payload = json.dumps(safe_args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            payload = str(safe_args)
        return f"{action}|{payload}"

    def has_permission_grant(
        self,
        *,
        action_id: str,
        args: Dict[str, Any],
        session_id: Optional[str],
        work_id: Optional[str],
    ) -> bool:
        sig = self._permission_signature(action_id, args)
        if not sig:
            return False
        if sig in (self.permission_grants.get("global") or {}):
            return True
        if work_id:
            by_worker = self.permission_grants.get("worker") or {}
            if sig in ((by_worker.get(str(work_id)) or {})):
                return True
        if session_id:
            by_session = self.permission_grants.get("session") or {}
            if sig in ((by_session.get(str(session_id)) or {})):
                return True
        return False

    def grant_permission(
        self,
        *,
        scope: str,
        action_id: str,
        args: Dict[str, Any],
        session_id: Optional[str],
        work_id: Optional[str],
        granted_by_session_id: Optional[str],
        granted_by_sender_id: Optional[str],
    ) -> None:
        sig = self._permission_signature(action_id, args)
        if not sig:
            return
        tz_name = self.config_manager.get_timezone()
        from zoneinfo import ZoneInfo
        try:
            now_str = datetime.datetime.now(ZoneInfo(tz_name)).isoformat()
        except Exception:
            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
        record = {
            "granted_at": now_str,
            "scope": str(scope or "worker"),
            "action_id": str(action_id or ""),
            "session_id": session_id,
            "work_id": work_id,
            "granted_by_session_id": granted_by_session_id,
            "granted_by_sender_id": granted_by_sender_id,
        }
        normalized_scope = str(scope or "worker").strip().lower()
        if normalized_scope == "global":
            self.permission_grants.setdefault("global", {})[sig] = record
            return
        if normalized_scope == "session" and session_id:
            bucket = self.permission_grants.setdefault("session", {}).setdefault(str(session_id), {})
            bucket[sig] = record
            return
        if work_id:
            bucket = self.permission_grants.setdefault("worker", {}).setdefault(str(work_id), {})
            bucket[sig] = record
            return

    def _expose_reasoning_to_ui(self) -> bool:
        ui_cfg = self.config_manager.get("ui", {}) if hasattr(self, "config_manager") else {}
        return bool(ui_cfg.get("expose_reasoning_chunks", False))

    @staticmethod
    def _is_media_action(action_id: str) -> bool:
        action = str(action_id or "").strip().lower()
        if not action:
            return False
        media_prefixes = (
            "browser.control.run",
            "browser.control.step",
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
        # 1. Bypass gate for control/interrupt signals
        if action_id in {"cancel", "stop", "clear"}:
            return "allow", []
        # Internal system sessions carry platform events (calendar, alerts, etc.).
        # They must not be blocked by conversational admission gating, otherwise
        # reflex actions (e.g., notifications.send) can be dropped with session_busy.
        sid = str(session_id or "").strip().lower()
        if sid.startswith("system."):
            return "allow", []

        active = self.scheduler.get_active_works(session_id=session_id)
        if not active:
            return "allow", []

        if self._is_media_action(action_id):
            blockers = [w for w in active if self._is_media_action(w.key or "")]
        else:
            blockers = active

        # Isolate recovery/replanning tasks: they don't block new conversational input
        # unless strict serial execution is required (not typical for recovery)
        blockers = [
            w for w in blockers 
            if w.status not in {WorkStatus.RECOVERY, WorkStatus.REPLANNING}
        ]

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
        if policy in {"allow", "parallel"}:
            return "allow", blocker_ids
        if policy == "queue":
            # Queueing for chat-initiated works is not implemented yet.
            # To avoid lock contention and stuck loops, reject new work while another is active.
            return "reject", blocker_ids
        if policy == "reject":
            return "reject", blocker_ids
        return "allow", blocker_ids

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

    def resolve_interface_for_session(self, session_id: str) -> str:
        """
        Resolves the interface ID (e.g., 'telegram', 'voice', 'web') for a given session.
        Uses the active driver registry or session ID prefixes.
        """
        driver = self._resolve_driver_for_session(session_id)
        if driver:
            return driver.get_interface_id()
        
        # Fallback to known prefixes if driver is not currently matched in driver_instances
        if session_id.startswith("telegram"):
            return "telegram"
        if session_id.startswith("voice"):
            return "voice"
        return "web"

    def _send_to_session(self, session_id: str, text: str, phase: str = "thinking", attachments: Optional[List[Dict]] = None):
        driver = self._resolve_driver_for_session(session_id)
        if not driver:
            return False
        try:
            if hasattr(driver, "send_status"):
                driver.send_status(session_id, phase, {"message": text})
            if hasattr(driver, "send_response"):
                driver.send_response(text, target=session_id, is_chunk=True, attachments=attachments)
            if hasattr(driver, "send_complete"):
                driver.send_complete(session_id)
            return True
        except Exception as e:
            logger.debug(f"Failed sending routed message to {session_id}: {e}")
            return False

    def _enqueue_approval_request(self, owner_session_id: str, work_id: str, prompt: str):
        tz_name = self.config_manager.get_timezone()
        from zoneinfo import ZoneInfo
        try:
            now_str = datetime.datetime.now(ZoneInfo(tz_name)).isoformat()
        except Exception:
            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

        bucket = self.pending_approval_queue.setdefault(owner_session_id, [])
        for item in bucket:
            if item.get("work_id") == work_id:
                item["prompt"] = prompt
                item["updated_at"] = now_str
                return
        bucket.append(
            {
                "work_id": work_id,
                "prompt": prompt,
                "created_at": now_str,
                "updated_at": now_str,
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

        source_interface = self._resolve_session_interface(session_id)
        sender_id = str(session.context.get("last_sender_id") or "").strip() if isinstance(session.context, dict) else ""
        if not sender_id:
            sender_id = session_id
        approval_context = PrincipalContext(
            interface=source_interface,
            sender_id=sender_id,
            sender_name=str(session.context.get("last_sender_name") or "") if isinstance(session.context, dict) else None,
            chat_id=str(session.context.get("last_chat_id") or "") if isinstance(session.context, dict) else None,
            chat_name=str(session.context.get("last_chat_name") or "") if isinstance(session.context, dict) else None,
            is_group=bool(session.context.get("last_is_group")) if isinstance(session.context, dict) else False,
            session_id=session_id,
        )
        can_decide, deny_reason = self.can_principal_control_permissions(approval_context)

        if self._is_affirmative(text):
            if not can_decide:
                driver_instance.send_response(
                    f"This principal is not allowed to approve sensitive permission requests ({deny_reason}).",
                    target=session_id,
                    is_chunk=True,
                )
                if hasattr(driver_instance, "send_complete"):
                    driver_instance.send_complete(session_id)
                return True
            ok = self.scheduler.push_work_command(
                work_id,
                "approve",
                payload={"note": text, "scope": "worker"},
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
            if not can_decide:
                driver_instance.send_response(
                    f"This principal is not allowed to deny sensitive permission requests ({deny_reason}).",
                    target=session_id,
                    is_chunk=True,
                )
                if hasattr(driver_instance, "send_complete"):
                    driver_instance.send_complete(session_id)
                return True
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

    def _handle_explicit_approval_command(self, text: str, session_id: str, driver_instance, context: Optional[PrincipalContext]) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        match = re.match(r"^!approval\s+([a-zA-Z0-9_-]+)\s+(approve|deny)(?:\s+(worker|session|global))?\s*$", raw, flags=re.IGNORECASE)
        if not match:
            return False

        work_id, decision, scope = match.group(1), match.group(2).lower(), (match.group(3) or "worker").lower()
        work_row = self.scheduler.get_work_snapshot(work_id, include_context=True) if hasattr(self.scheduler, "get_work_snapshot") else None
        if not work_row:
            driver_instance.send_response(
                f"Worker {work_id} was not found.",
                target=session_id,
                is_chunk=True,
            )
            if hasattr(driver_instance, "send_complete"):
                driver_instance.send_complete(session_id)
            return True

        current_status = str(work_row.get("status") or "").strip().lower()
        if current_status != "waiting_user":
            driver_instance.send_response(
                f"Worker {work_id} is no longer waiting for approval (status: {current_status or 'unknown'}).",
                target=session_id,
                is_chunk=True,
            )
            if hasattr(driver_instance, "send_complete"):
                driver_instance.send_complete(session_id)
            return True

        principal = context if isinstance(context, PrincipalContext) else PrincipalContext(
            interface=self._resolve_session_interface(session_id),
            sender_id=session_id,
            session_id=session_id,
        )
        can_decide, deny_reason = self.can_principal_control_permissions(principal)
        if not can_decide:
            driver_instance.send_response(
                f"This principal is not allowed to control sensitive permission requests ({deny_reason}).",
                target=session_id,
                is_chunk=True,
            )
            if hasattr(driver_instance, "send_complete"):
                driver_instance.send_complete(session_id)
            return True

        cmd = "approve" if decision == "approve" else "deny"
        ok = self.scheduler.push_work_command(
            work_id=work_id,
            command=cmd,
            payload={"scope": scope, "note": f"explicit:{raw}"},
            source_session_id=session_id,
        )
        # Clear pending approval queue/session marker for this work to avoid stale reminders.
        owner_session_id = str((work_row or {}).get("owner_session_id") or (work_row or {}).get("session_id") or session_id)

        self._remove_approval_request(owner_session_id, work_id)
        owner_session = self.orchestrator.get_session_robust(owner_session_id)
        if owner_session and isinstance(owner_session.pending_action, dict):
            pending_work_id = str(owner_session.pending_action.get("work_id") or "").strip()
            if pending_work_id == str(work_id):
                owner_session.pending_action = None
                self.orchestrator._save_session(owner_session)

        if ok:
            driver_instance.send_response(
                f"Decision sent to worker {work_id}: {decision.upper()} ({scope}).",
                target=session_id,
                is_chunk=True,
            )
        else:
            driver_instance.send_response(
                f"Worker {work_id} was not found.",
                target=session_id,
                is_chunk=True,
            )
        if hasattr(driver_instance, "send_complete"):
            driver_instance.send_complete(session_id)
        return True

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
                    if self._expose_reasoning_to_ui() and hasattr(driver, 'send_reasoning_chunk'):
                        driver.send_reasoning_chunk(target_session, msg)
                    elif hasattr(driver, 'send_status'):
                        driver.send_status(target_session, 'thinking', msg)
                    elif hasattr(driver, 'send_response'):
                        driver.send_response(msg, target=target_session)

                
                elif event_type == "work_status_change":
                    status = event.get("status")
                    snapshot = self.scheduler.get_work_snapshot(work_id, include_context=True)
                    summary = (snapshot or {}).get("context", {}).get("summary", {}) if snapshot else {}
                    prompt = summary.get("approval_prompt") or "This worker needs your approval to continue."
                    approval_action_id = str(summary.get("approval_action_id") or "").strip()
                    approval_args = summary.get("approval_args") if isinstance(summary.get("approval_args"), dict) else {}
                    status_text = {
                        "queued": "Task queued.",
                        "running": "Task running.",
                        "paused": "Task paused.",
                        "waiting_user": prompt,
                        "succeeded": "Task completed successfully.",
                        "failed": "Task failed.",
                        "cancelled": "Task cancelled.",
                    }.get(str(status or "").lower(), f"Task status: {status}")

                    if hasattr(driver, "send_status"):
                        try:
                            driver.send_status(
                                target_session,
                                "thinking" if status in {"queued", "running", "paused", "waiting_user"} else "complete",
                                {
                                    "status": status,
                                    "message": status_text,
                                    "work_id": work_id,
                                    "approval_request": (
                                        {
                                            "prompt": prompt,
                                            "action_id": approval_action_id,
                                            "args": approval_args,
                                            "options": [
                                                {"id": "deny", "label": "Deny"},
                                                {"id": "approve_worker", "label": "Allow this worker"},
                                                {"id": "approve_session", "label": "Allow this session"},
                                                {"id": "approve_global", "label": "Allow global"},
                                            ],
                                        }
                                        if status == "waiting_user"
                                        else None
                                    ),
                                },
                            )
                        except Exception as e:
                            logger.debug(f"Failed to forward work status to session {target_session}: {e}")

                    if status == "succeeded":
                        work = self.scheduler.get_work(work_id)
                        if work and work.result:
                            # Server-side drivers handle their own streaming via callbacks to avoid duplicates
                            if not hasattr(driver, 'send_reasoning_chunk') and not bool(getattr(driver, "streams_worker_responses", False)):
                                driver.send_response(work.result, target=target_session)
                        self._remove_approval_request(target_session, work_id)
                    elif status == "failed":
                        driver.send_response(f"❌ Task error {work_id}: An internal problem occurred.", target=target_session)
                        self._remove_approval_request(target_session, work_id)
                    elif status == "waiting_user":
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

    def process_input(self, text, driver_instance, user_id=None, user_data: dict = None, context: PrincipalContext = None, attachments: List[str] = None, is_internal: bool = False):
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
        if self._handle_explicit_approval_command(text, session_id, driver_instance, context):
            return session_id

        effective_text = text
        
        # Configurable preemption policy: keep main conversation responsive without
        # automatically canceling active background work unless explicitly enabled.
        work_cfg = self.config_manager.get("work_execution", {})
        preempt_on_new_input = bool(work_cfg.get("preempt_on_new_input", False))
        if preempt_on_new_input:
            self.scheduler.cancel_session_work(session_id)
        
        # Map session to driver for back-routing responses.
        # Internal injections must not clobber the real user-channel routing
        # (e.g., telegram session being temporarily mapped to InternalDriver).
        if not is_internal or session_id.startswith("system."):
            self.driver_instances[session_id] = driver_instance

        # IMMEDIATE FEEDBACK: Let the user know we're working (Only for non-internal)
        if not is_internal:
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
            # Use SESSION_TYPE_SYSTEM if internal
            from core.session import SESSION_TYPE_SYSTEM, SESSION_TYPE_USER
            session_type = SESSION_TYPE_SYSTEM if is_internal else SESSION_TYPE_USER
            
            plan, _, session = self.orchestrator.get_initial_intent(
                effective_text, 
                session_id=session_id, 
                user_data=user_data, 
                context=context, 
                attachments=attachments, 
                name=user_name,
                session_type=session_type
            )

            if session and isinstance(context, PrincipalContext):
                session.context["last_interface"] = str(context.interface or "web")
                session.context["last_sender_id"] = str(context.sender_id or session_id)
                if context.sender_name:
                    session.context["last_sender_name"] = str(context.sender_name)
                if context.chat_id:
                    session.context["last_chat_id"] = str(context.chat_id)
                if context.chat_name:
                    session.context["last_chat_name"] = str(context.chat_name)
                session.context["last_is_group"] = bool(context.is_group)
            
            # ENSURE PERSISTENCE: Add user message to history before processing the plan
            if session:
                inbound_role = "notification" if is_internal else "user"
                inbound_type = "internal_event" if is_internal else "default"
                session.add_message(
                    inbound_role,
                    text,
                    attachments=attachments,
                    silent=is_internal,
                    msg_type=inbound_type,
                    actor=self._build_message_actor(context, is_internal),
                )
                self.orchestrator._save_session(session)
                
                # Trigger auto-naming for web sessions on first user messages
                if not is_internal and session.source == "web" and not session.name_generated and len(session.history) <= 3:
                    threading.Thread(target=self.orchestrator._auto_name_session, args=(session, text), daemon=True).start()

            if not plan:
                if is_internal:
                    return None # No plan for internal is fine
                
                caps = user_data.get("driver_capabilities", {}) if isinstance(user_data, dict) else {}
                is_voice_interaction = bool(caps.get("voice_only")) or (bool(context) and str(getattr(context, "interface", "")).lower() == "voice")
                no_plan_key = "reply.voice_rephrase" if is_voice_interaction else "reply.no_plan_resolved"
                return driver_instance.send_response(
                    self.orchestrator.i18n.t(
                        no_plan_key,
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
                session.add_message("assistant", coached_response, model_info=plan.model_used)
                self.orchestrator._save_session(session)

                # Keep thought/protocol hidden from user chat by default.
                if self._expose_reasoning_to_ui() and hasattr(driver_instance, 'send_reasoning_chunk') and plan.thought:
                    driver_instance.send_reasoning_chunk(session_id, plan.thought)

                # Internal events targeted to a user session must be routed through the
                # real channel driver (telegram/web/voice), not the InternalDriver itself.
                if is_internal and not session_id.startswith("system."):
                    self._send_to_session(
                        session_id,
                        coached_response,
                        phase="notification",
                        attachments=plan.attachments,
                    )
                else:
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
                prompt = self.orchestrator._generate_recovery_reply(
                    session=session,
                    user_input=text,
                    reason="media_busy_takeover",
                )
                tz_name = self.config_manager.get_timezone()
                from zoneinfo import ZoneInfo
                try:
                    now_str = datetime.datetime.now(ZoneInfo(tz_name)).isoformat()
                except Exception:
                    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                
                session.pending_action = {
                    "type": "media_takeover",
                    "blocked_work_ids": blocked_work_ids,
                    "original_text": text,
                    "original_user_data": user_data if isinstance(user_data, dict) else {},
                    "requested_action": plan.action_id,
                    "requested_at": now_str,
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
                            "model_info": plan.model_used if plan and hasattr(plan, "model_used") else None,
                        },
                    )
                driver_instance.send_response(prompt, target=session_id, is_chunk=True)
                if hasattr(driver_instance, "send_complete"):
                    driver_instance.send_complete(session_id)
                return session_id

            if admission_decision == "reject":
                busy_msg = self.orchestrator._generate_recovery_reply(
                    session=session,
                    user_input=text,
                    reason="session_busy",
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
            
            callbacks['send_status'] = lambda phase, payload=None, model_info=None: driver_instance.send_status(session_id, phase, payload, model_info=model_info)
            if self._expose_reasoning_to_ui():
                callbacks['send_reasoning_chunk'] = lambda content: driver_instance.send_reasoning_chunk(session_id, content)
            callbacks['send_complete'] = lambda: driver_instance.send_complete(session_id)
            callbacks['send_response'] = lambda text, is_chunk=False, attachments=None, model_info=None: driver_instance.send_response(text, target=session_id, is_chunk=is_chunk, attachments=attachments, model_info=model_info)
            callbacks['emit_event'] = lambda event: global_event_bus.emit_threadsafe({
                **(event if isinstance(event, dict) else {}),
                "session_id": session_id,
            })

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
                attachments=attachments,
                is_internal=is_internal
            )

            # 4. Immediate technical receipt (Status only)
            if not is_internal:
                driver_instance.send_status(
                    session_id,
                    "thinking",
                    {
                        "message": self.orchestrator.i18n.t("status.task_started", locale=self.orchestrator._session_locale(session)),
                        "work_id": work.work_id,
                        "code": "receipt",
                    },
                )
            
            # Persist an empty placeholder or technical record if needed, 
            # but do NOT add a conversational assistant message here.
            # Commitment will be handled by the Orchestrator/Worker after validation.
            
            return work.work_id
        
        except Exception as e:
            logger.error(f"Kernel Error spawning work: {e}", exc_info=True)

if __name__ == "__main__":
    kernel = Kernel()
    kernel.start()
