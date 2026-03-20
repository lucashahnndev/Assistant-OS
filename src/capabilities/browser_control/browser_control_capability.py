import asyncio
import hashlib
import logging
import os
import re
import shutil
import threading
import time
from typing import List, Dict, Any, Optional, Union
from ..base import CapabilityBase
from .session_policy import BrowserSessionPolicy

logger = logging.getLogger("aosd.capabilities.browser_control")

class BrowserControlCapability(CapabilityBase):
    def __init__(self, kernel: Any, config: Dict[str, Any]):
        self.kernel = kernel
        self._config = config
        self._registry_enabled = self._cfg_bool("registry_enabled", True)
        self._policy_enabled = self._cfg_bool("policy_enabled", True)
        self._media_singleton_enforced = self._cfg_bool("media_singleton_enforced", True)
        self._app_mode_enabled = self._cfg_bool("app_mode_enabled", True)
        self._registry_gc_enabled = self._cfg_bool("registry_gc_enabled", False)
        self._registry_gc_idle_seconds = int(self._config.get("registry_gc_idle_seconds", 1800)) if isinstance(self._config, dict) else 1800
        self._humanize_input_enabled = self._cfg_bool("humanize_input_enabled", True)
        self._visual_cursor_enabled = self._cfg_bool("visual_cursor_enabled", True)
        self._tab_user_lock_enabled = self._cfg_bool("tab_user_lock_enabled", True)
        self._tab_control_bar_enabled = self._cfg_bool("tab_control_bar_enabled", True)
        self._require_delegated_executor_for_browser_launch = self._cfg_bool(
            "require_delegated_executor_for_browser_launch", True
        )
        self._run_failure_cooldown_seconds = self._cfg_int("run_failure_cooldown_seconds", 45)
        self._runtime_backend = self._cfg_str("runtime_backend", "playwright").lower()
        self._playwright_transport_mode = self._cfg_str("playwright_transport_mode", "mcp").lower()
        self._playwright_mcp_endpoint = self._cfg_str("playwright_mcp_endpoint", "")
        self._playwright_mcp_fallback_to_local = self._cfg_bool("playwright_mcp_fallback_to_local", False)
        self._max_new_tabs_per_session = self._cfg_int("max_new_tabs_per_session", 3)
        self._browser_engine_preference = self._cfg_str("browser_engine_preference", "managed_chromium")
        self._chrome_path_override = self._cfg_str("chrome_path", "")
        self._managed_chromium_path = self._cfg_path(
            "managed_chromium_path", "data/browser_bin/chromium/current/chrome"
        )
        self._profile_split_by_engine = self._cfg_bool("profile_split_by_engine", True)
        self._extension_install_mode = self._cfg_str("extension_install_mode", "auto")
        self._extension_fallback_enabled = self._cfg_bool("extension_fallback_enabled", True)
        self._perception_dom_weight = self._cfg_float("perception_dom_weight", 0.35)
        self._perception_vision_weight = self._cfg_float("perception_vision_weight", 0.65)
        self._perception_dom_timeout_s = self._cfg_float("perception_dom_timeout_s", 4.0)
        self._perception_vision_timeout_s = self._cfg_float("perception_vision_timeout_s", 7.5)
        self._perception_dom_max_nodes = self._cfg_int("perception_dom_max_nodes", 90)
        self._perception_cache_ttl_s = self._cfg_float("perception_cache_ttl_s", 3.5)
        self._perception_fast_screenshot_format = self._cfg_str("perception_fast_screenshot_format", "jpeg")
        self._perception_fast_screenshot_quality = self._cfg_int("perception_fast_screenshot_quality", 60)
        self._planner_max_same_action_repeats = self._cfg_int("planner_max_same_action_repeats", 3)
        self._planner_max_state_unchanged_loops = self._cfg_int("planner_max_state_unchanged_loops", 5)
        self._planner_max_forced_recovery_attempts = self._cfg_int("planner_max_forced_recovery_attempts", 2)
        
        agent_config = getattr(self.kernel, "config", {}).get("agent", {}) if self.kernel else {}
        self._agent_name = agent_config.get("agent_name", "Agent")
        self._base_profile_path = self._cfg_path("base_profile_path", "data/browser_data/profile")
        self._overlay_profile_parent = self._cfg_path("overlay_profile_parent", "data/browser_data/profile/sessions")
        self._desktop_cache_dir = self._cfg_path("desktop_cache_dir", "data/browser_data/desktop_cache")
        self._desktop_launch_enabled = self._cfg_bool("desktop_launch_enabled", True)
        self._legacy_profiles_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "profiles")
        )
        self._legacy_fixed_base_path = os.path.join(self._legacy_profiles_root, "fixed_base")
        self._bootstrap_profile_template_path = os.path.abspath(
            self._cfg_path("bootstrap_profile_template_path", "data/browser_data/profile_template")
        )
        self._runtime: Optional[Any] = None
        self._subagent: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._browser_instance_id: Optional[str] = None
        self._tab_id: Optional[str] = None
        self._owner_session_id: Optional[str] = None
        self._runtime_intent_class: Optional[str] = None
        self._new_tabs_opened_by_session: Dict[str, int] = {}
        self._active_run_by_session: Dict[str, float] = {}
        self._recent_failed_goal_by_session: Dict[str, Dict[str, Any]] = {}
        self._run_dispatch_lock = threading.Lock()
        self._runtime_init_lock: Optional[asyncio.Lock] = None
        self._policy = BrowserSessionPolicy({"app_mode_enabled": self._app_mode_enabled})
        self._initialize_global_browser_storage()

    def _get_new_tab_open_count(self, owner_session_id: str) -> int:
        key = str(owner_session_id or "default")
        return int(self._new_tabs_opened_by_session.get(key, 0))

    def _increment_new_tab_open_count(self, owner_session_id: str) -> int:
        key = str(owner_session_id or "default")
        count = self._get_new_tab_open_count(key) + 1
        self._new_tabs_opened_by_session[key] = count
        return count

    def _resolve_runtime_backend(self) -> str:
        backend = str(self._runtime_backend or "playwright").strip().lower()
        if backend != "playwright":
            logger.warning(
                "runtime_backend=%s is deprecated and ignored; forcing playwright backend.",
                backend,
            )
        return "playwright"

    def _resolve_runtime_class(self):
        from .runtime_playwright import BrowserRuntimePlaywright

        return BrowserRuntimePlaywright

    def _build_runtime_kwargs(
        self,
        *,
        resolved_browser_path: str,
        runtime_base_profile: str,
        runtime_overlay_parent: str,
        headless: bool,
        muted: bool,
        use_app_mode: bool,
        launch_url: str,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "chrome_path": resolved_browser_path,
            "base_profile_path": runtime_base_profile,
            "overlay_profile_parent": runtime_overlay_parent,
            "desktop_cache_dir": self._desktop_cache_dir,
            "desktop_launch_enabled": self._desktop_launch_enabled,
            "extension_install_mode": self._extension_install_mode,
            "extension_fallback_enabled": self._extension_fallback_enabled,
            "headless": headless,
            "muted": muted,
            "app_mode": use_app_mode,
            "launch_url": launch_url,
            "humanize_input_enabled": self._humanize_input_enabled,
            "visual_cursor_enabled": self._visual_cursor_enabled,
            "tab_user_lock_enabled": self._tab_user_lock_enabled,
            "tab_control_bar_enabled": self._tab_control_bar_enabled,
            "agent_name": self._agent_name,
        }
        kwargs["playwright_transport_mode"] = self._playwright_transport_mode
        kwargs["playwright_mcp_endpoint"] = self._playwright_mcp_endpoint
        kwargs["playwright_mcp_fallback_to_local"] = self._playwright_mcp_fallback_to_local
        return kwargs

    def _cfg_bool(self, key: str, default: bool) -> bool:
        if not isinstance(self._config, dict):
            return bool(default)
        if key not in self._config:
            return bool(default)
        return bool(self._config.get(key))

    def _cfg_path(self, key: str, default: str) -> str:
        if not isinstance(self._config, dict):
            return os.path.abspath(default)
        raw = str(self._config.get(key, default) or default).strip() or default
        return os.path.abspath(raw)

    def _cfg_str(self, key: str, default: str = "") -> str:
        if not isinstance(self._config, dict):
            return str(default or "")
        return str(self._config.get(key, default) or default).strip()

    def _cfg_int(self, key: str, default: int) -> int:
        if not isinstance(self._config, dict):
            return int(default)
        try:
            return int(self._config.get(key, default))
        except Exception:
            return int(default)

    def _cfg_float(self, key: str, default: float) -> float:
        if not isinstance(self._config, dict):
            return float(default)
        try:
            return float(self._config.get(key, default))
        except Exception:
            return float(default)

    def _detect_engine_key(self, browser_path: str) -> str:
        p = str(browser_path or "").lower()
        if "browser_bin/chromium" in p or p.endswith("/chrome-linux64/chrome"):
            return "managed_chromium"
        if "google-chrome" in p or p.endswith("/chrome"):
            return "google_chrome"
        if "chromium" in p:
            return "chromium"
        return "browser"

    def _resolve_runtime_profile_paths(self, browser_path: str) -> tuple[str, str]:
        if not self._profile_split_by_engine:
            return self._base_profile_path, self._overlay_profile_parent
        engine_key = self._detect_engine_key(browser_path)
        base_parent = os.path.dirname(self._base_profile_path.rstrip(os.sep)) or self._base_profile_path
        runtime_base = os.path.join(base_parent, f"profile_{engine_key}")
        runtime_overlay = os.path.join(runtime_base, "sessions")
        return os.path.abspath(runtime_base), os.path.abspath(runtime_overlay)

    def _ensure_runtime_profile_storage(self, base_profile: str, overlay_parent: str) -> None:
        try:
            os.makedirs(base_profile, exist_ok=True)
            os.makedirs(overlay_parent, exist_ok=True)
        except Exception as e:
            logger.warning("Failed to ensure runtime browser storage directories: %s", e)
            return
        try:
            base_has_content = bool(os.listdir(base_profile))
        except Exception:
            base_has_content = False
        if not base_has_content and os.path.isdir(self._bootstrap_profile_template_path):
            try:
                logger.info("Bootstrapping runtime browser profile from %s", self._bootstrap_profile_template_path)
                shutil.copytree(
                    self._bootstrap_profile_template_path,
                    base_profile,
                    dirs_exist_ok=True,
                )
            except Exception as e:
                logger.warning("Failed to bootstrap runtime browser profile: %s", e)

    def _resolve_browser_path(self) -> str:
        """
        Resolution order:
        1) explicit chrome_path in config
        2) managed chromium binary in data/
        3) system chromium/chrome binaries
        """
        if self._chrome_path_override:
            explicit = os.path.abspath(self._chrome_path_override)
            if os.path.exists(explicit):
                return explicit
            logger.warning("Configured chrome_path not found: %s", explicit)

        managed = os.path.abspath(self._managed_chromium_path)
        system_candidates = [
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome",
            "/opt/google/chrome/chrome",
        ]
        preference = str(self._browser_engine_preference or "").lower()
        if preference in {"google_chrome", "chrome"}:
            ordered = ["/usr/bin/google-chrome", "/opt/google/chrome/chrome", managed] + [
                p for p in system_candidates if p not in {"/usr/bin/google-chrome", "/opt/google/chrome/chrome"}
            ]
        else:
            ordered = [managed] + system_candidates

        for candidate in ordered:
            if candidate and os.path.exists(candidate):
                return os.path.abspath(candidate)

        # Last-resort default
        return "/usr/bin/google-chrome"

    def _initialize_global_browser_storage(self) -> None:
        """
        Initializes browser-control storage once at capability startup.
        This is global state (not per-session): base profile, session overlays root and desktop cache.
        """
        try:
            os.makedirs(self._base_profile_path, exist_ok=True)
            os.makedirs(self._overlay_profile_parent, exist_ok=True)
            os.makedirs(self._desktop_cache_dir, exist_ok=True)
        except Exception as e:
            logger.warning("Failed to ensure browser storage directories: %s", e)
            return

        self._migrate_legacy_profile_if_needed()

        # Bootstrap base profile only if empty/nonexistent content.
        try:
            base_has_content = bool(os.listdir(self._base_profile_path))
        except Exception:
            base_has_content = False

        if not base_has_content and os.path.isdir(self._bootstrap_profile_template_path):
            try:
                logger.info(
                    "Bootstrapping global browser base profile from %s",
                    self._bootstrap_profile_template_path,
                )
                shutil.copytree(
                    self._bootstrap_profile_template_path,
                    self._base_profile_path,
                    dirs_exist_ok=True,
                )
            except Exception as e:
                logger.warning("Failed to bootstrap browser base profile: %s", e)

        # Guardrail: overlay path nested inside base path is supported, but can be risky for misconfigured copy logic.
        try:
            base_real = os.path.realpath(self._base_profile_path)
            overlay_real = os.path.realpath(self._overlay_profile_parent)
            if os.path.commonpath([overlay_real, base_real]) == base_real:
                logger.info(
                    "Browser overlay root is nested under base profile (%s). Runtime copy guard is active.",
                    os.path.relpath(overlay_real, base_real),
                )
        except Exception:
            pass

    def _migrate_legacy_profile_if_needed(self) -> None:
        """
        One-way migration from legacy in-source profile location to data/.
        Never overwrites an already populated runtime profile.
        """
        legacy = self._legacy_fixed_base_path
        if not os.path.isdir(legacy):
            return
        try:
            base_has_content = bool(os.listdir(self._base_profile_path))
        except Exception:
            base_has_content = False
        if base_has_content:
            return
        try:
            logger.warning(
                "Migrating legacy browser profile from source tree to data directory: %s -> %s",
                legacy,
                self._base_profile_path,
            )
            shutil.copytree(legacy, self._base_profile_path, dirs_exist_ok=True)
        except Exception as e:
            logger.warning("Failed to migrate legacy browser profile: %s", e)

    @property
    def name(self) -> str:
        return "browser_control"

    @property
    def actions(self) -> List[str]:
        return ["run", "step", "close", "inspect", "close_tab", "close_instance", "sync_registry", "gc", "health"]

    def get_reflex_rules(self) -> List[Dict[str, Any]]:
        return [
            {
                "pattern": r"(?i)(?:abr[aei]|open|launch|inicie?)\s+(?:o\s+)?(?:navegador|browser|chrome|google\s+chrome)",
                "action_id": "browser.control.run",
                "handler": lambda m: {"goal": m.string},
            },
        ]

    def get_keywords(self) -> List[str]:
        return [
            "navegador", "browser", "chrome", "abra o google",
            "abra o navegador", "open browser", "clique", "click",
            "navegar", "navigate", "browser control",
        ]

    async def _ensure_runtime(
        self,
        headless: bool = False,
        muted: bool = False,
        force_new_instance: bool = False,
        use_app_mode: bool = False,
        launch_url: str = "about:blank",
    ):
        from .planner import BrowserSubagent
        from .perception_merger import PerceptionMerger
        from .dom_analyzer import DomAnalyzer
        from .image_analyzer import ImageAnalyzer
        RuntimeClass = self._resolve_runtime_class()
        current_loop = asyncio.get_running_loop()
        if self._runtime_init_lock is None or self._loop != current_loop:
            self._runtime_init_lock = asyncio.Lock()

        async with self._runtime_init_lock:
            should_recreate = force_new_instance
            loop_changed = False

            # Re-init if loop changed or launch options differ
            if self._runtime and self._loop != current_loop:
                logger.info("Event loop changed, re-initializing runtime")
                should_recreate = True
                loop_changed = True

            if should_recreate and self._runtime:
                try:
                    if loop_changed and hasattr(self._runtime, "force_close"):
                        # Cross-loop teardown must be synchronous to avoid "Future attached to a different loop".
                        self._runtime.force_close()
                    else:
                        await self._runtime.close()
                finally:
                    self._runtime = None
                    self._subagent = None
                    self._tab_id = None
                    self._runtime_intent_class = None

            if not self._runtime:
                if not self.kernel:
                    raise RuntimeError("Kernel not initialized in BrowserControlCapability")
                self._loop = current_loop
                resolved_browser_path = self._resolve_browser_path()
                logger.info("Browser runtime path resolved to %s", resolved_browser_path)
                runtime_base_profile, runtime_overlay_parent = self._resolve_runtime_profile_paths(resolved_browser_path)
                self._ensure_runtime_profile_storage(runtime_base_profile, runtime_overlay_parent)
                logger.info(
                    "Browser runtime profile resolved to base=%s overlay=%s",
                    runtime_base_profile,
                    runtime_overlay_parent,
                )
                logger.info("Browser runtime backend selected: %s", self._resolve_runtime_backend())
                runtime_kwargs = self._build_runtime_kwargs(
                    resolved_browser_path=resolved_browser_path,
                    runtime_base_profile=runtime_base_profile,
                    runtime_overlay_parent=runtime_overlay_parent,
                    headless=headless,
                    muted=muted,
                    use_app_mode=use_app_mode,
                    launch_url=launch_url,
                )
                self._runtime = RuntimeClass(**runtime_kwargs)
                await self._runtime.launch()
                dom_analyzer = DomAnalyzer()
                image_analyzer = ImageAnalyzer(self.kernel.llm_manager)
                perception_merger = PerceptionMerger(
                    dom_analyzer,
                    image_analyzer,
                    dom_weight=self._perception_dom_weight,
                    vision_weight=self._perception_vision_weight,
                    dom_timeout_s=self._perception_dom_timeout_s,
                    vision_timeout_s=self._perception_vision_timeout_s,
                )
                self._subagent = BrowserSubagent(
                    self._runtime,
                    self.kernel.llm_manager,
                    perception_merger,
                    dom_max_nodes=self._perception_dom_max_nodes,
                    perception_cache_ttl_s=self._perception_cache_ttl_s,
                    fast_screenshot_format=self._perception_fast_screenshot_format,
                    fast_screenshot_quality=self._perception_fast_screenshot_quality,
                    max_same_action_repeats=self._planner_max_same_action_repeats,
                    max_state_unchanged_loops=self._planner_max_state_unchanged_loops,
                    max_forced_recovery_attempts=self._planner_max_forced_recovery_attempts,
                )

    @staticmethod
    def _extract_first_url(text: str) -> str:
        match = re.search(r"https?://[^\s,]+", str(text or ""), re.IGNORECASE)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _contains_platform_hint(text: str) -> bool:
        value = str(text or "").lower()
        if not value:
            return False
        return any(
            token in value
            for token in (
                "spotify",
                "youtube",
                "music.youtube",
                "deezer",
                "amazon",
                "github",
                "google",
            )
        )

    def _resolve_launch_url(self, goal: str, intent_class: str, user_request: str = "") -> str:
        explicit = self._extract_first_url(goal) or self._extract_first_url(user_request)
        if explicit:
            return explicit
        basis = f"{str(goal or '')} {str(user_request or '')}".lower()
        if "music.youtube" in basis:
            return "https://music.youtube.com"
        if "youtube" in basis:
            return "https://www.youtube.com"
        if "spotify" in basis:
            return "https://www.spotify.com"
        if "github" in basis:
            return "https://www.github.com"
        if "google" in basis:
            return "https://www.google.com"
        if intent_class == "controlar_midia":
            return "https://www.youtube.com"
        return "about:blank"

    async def _close_registered_instance(self, reason: str = "replaced") -> None:
        if self._registry_enabled and self._browser_instance_id and self.kernel and hasattr(self.kernel, "browser_session_registry"):
            try:
                self.kernel.browser_session_registry.close_instance(self._browser_instance_id, reason=reason)
            except Exception:
                pass
        self._browser_instance_id = None
        self._tab_id = None

    async def _apply_session_policy(
        self,
        *,
        goal: str,
        user_request: str,
        intent_class: str,
        owner_session_id: str,
        headless: bool,
        muted: bool,
    ) -> Dict[str, Any]:
        launch_url = self._resolve_launch_url(goal, intent_class, user_request=user_request)
        if not self._policy_enabled:
            await self._ensure_runtime(
                headless=headless,
                muted=muted,
                force_new_instance=False,
                use_app_mode=False,
                launch_url=launch_url,
            )
            self._owner_session_id = owner_session_id
            self._runtime_intent_class = intent_class
            return {
                "route": "policy_disabled",
                "reason": "policy_feature_flag_off",
                "use_app_mode": False,
                "force_new_instance": False,
                "launch_url": launch_url,
            }

        current_url = ""
        if self._runtime and hasattr(self._runtime, "_get_current_url"):
            try:
                current_url = await self._runtime._get_current_url()
            except Exception:
                current_url = ""

        decision = self._policy.decide(
            intent_class=intent_class,
            goal=goal,
            owner_session_id=owner_session_id,
            current_owner_session_id=self._owner_session_id,
            current_intent_class=self._runtime_intent_class,
            has_runtime=self._runtime is not None,
            launch_url=launch_url,
            current_url=current_url,
        )

        if decision.force_new_instance and self._runtime:
            await self._close_registered_instance(reason=f"policy:{decision.reason}")

        await self._ensure_runtime(
            headless=headless,
            muted=muted,
            force_new_instance=decision.force_new_instance,
            use_app_mode=decision.use_app_mode,
            launch_url=launch_url,
        )
        self._owner_session_id = owner_session_id
        self._runtime_intent_class = intent_class
        decision_data: Dict[str, Any] = {**decision.as_dict(), "launch_url": launch_url, "current_url": current_url}
        if decision.route == "new_tab":
            # Side-effects (open tab/window) are deferred to the browser subagent action loop.
            # Session policy should only decide routing metadata, not execute browser mutations.
            decision_data["requested_route"] = "new_tab"
            decision_data["route"] = "reuse_tab"
            decision_data["reason"] = "new_tab_deferred_to_subagent"
            decision_data["new_tab_deferred_to_subagent"] = True
        return decision_data

    @staticmethod
    def _delegation_child_id(context: Dict[str, Any]) -> str:
        envelope = context.get("execution_context_envelope") if isinstance(context, dict) else None
        envelope = envelope if isinstance(envelope, dict) else {}
        delegation = envelope.get("delegation") if isinstance(envelope.get("delegation"), dict) else {}
        return str(delegation.get("child_agent_id") or "").strip().lower()

    def _is_browser_launch_authorized(self, context: Dict[str, Any]) -> bool:
        if not self._require_delegated_executor_for_browser_launch:
            return True
        if bool(context.get("allow_local_browser_launch", False)):
            return True
        envelope = context.get("execution_context_envelope") if isinstance(context, dict) else None
        if not isinstance(envelope, dict):
            return False
        child_id = self._delegation_child_id(context)
        return bool(child_id.startswith("browser_subagent"))

    @staticmethod
    def _goal_fingerprint(goal: str, intent_class: str) -> str:
        payload = f"{str(intent_class or '').strip().lower()}::{str(goal or '').strip().lower()}"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _should_block_run_by_cooldown(self, *, session_id: str, goal_fingerprint: str) -> Optional[Dict[str, Any]]:
        cooldown_s = int(max(0, self._run_failure_cooldown_seconds))
        if cooldown_s <= 0:
            return None
        record = self._recent_failed_goal_by_session.get(str(session_id or "default"))
        if not isinstance(record, dict):
            return None
        last_fp = str(record.get("goal_fingerprint") or "")
        last_ts = float(record.get("failed_at_ts") or 0.0)
        if not last_fp or not last_ts or last_fp != goal_fingerprint:
            return None
        elapsed = max(0, int(time.time() - last_ts))
        if elapsed >= cooldown_s:
            return None
        return {
            "ok": False,
            "error": (
                "Browser run blocked by cooldown after repeated failure for the same goal. "
                "Please wait before retrying."
            ),
            "error_code": "BROWSER_RUN_COOLDOWN",
            "cooldown_seconds": cooldown_s,
            "retry_after_seconds": max(0, cooldown_s - elapsed),
        }

    def _run_sync(self, coro):
        """Helper to run a coroutine from a synchronous context, 
        even if an event loop is already running in the current thread."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # We are in an async context. We must run in a separate thread to block.
                import threading
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(lambda: asyncio.run(coro)).result()
            return loop.run_until_complete(coro)
        except RuntimeError:
            # No loop running in this thread
            return asyncio.run(coro)

    def execute(self, action_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Any:
        action = action_id.split(".")[-1]
        ctx = context if isinstance(context, dict) else {}

        if action == "run":
            user_request = str(
                ctx.get("original_user_input")
                or ctx.get("user_input")
                or ctx.get("prompt")
                or ""
            ).strip()
            goal = (
                params.get("goal")
                or params.get("instruction")
                or params.get("query")
                or user_request
                or ""
            )
            # Preserve full user request when planner supplied a shortened query-like goal.
            if user_request and goal:
                goal_text = str(goal).strip()
                if (
                    len(goal_text) < len(user_request)
                    and self._contains_platform_hint(user_request)
                    and not self._contains_platform_hint(goal_text)
                ):
                    goal = user_request

            run_context = dict(ctx)
            if user_request:
                run_context["original_user_input"] = user_request
            # Optional launch params — agent can pass these or they default to sane values
            headless = bool(params.get("headless", self._config.get("headless", False)))
            muted = bool(params.get("muted", False))
            try:
                intent_class = self._resolve_intent_class(params.get("intent_class"))
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            completion_mode = str(params.get("completion_mode") or "").strip().lower()
            logger.info(f"Resolved goal for 'run': '{goal}' (from params keys: {list(params.keys())})")
            if not self._run_dispatch_lock.acquire(blocking=False):
                return {
                    "ok": False,
                    "error": (
                        "Another browser.control.run dispatch is in progress. "
                        "Wait for the delegated browser executor to finish."
                    ),
                    "error_code": "BROWSER_RUN_DISPATCH_BUSY",
                }
            try:
                return self._run_sync(
                    self.run_goal(
                        goal,
                        headless=headless,
                        muted=muted,
                        intent_class=intent_class,
                        completion_mode=completion_mode,
                        context=run_context,
                    )
                )
            finally:
                self._run_dispatch_lock.release()
        elif action == "step":
            instruction = (
                params.get("instruction")
                or params.get("goal")
                or params.get("query")
                or ctx.get("user_input")
                or ctx.get("prompt")
                or ""
            )
            return self._run_sync(self.step(instruction, context=ctx))
        elif action == "close":
            return self._run_sync(self.close())
        elif action == "inspect":
            return self._run_sync(self.inspect(params=params, context=ctx))
        elif action == "close_tab":
            tab_id = str(params.get("tab_id") or "").strip()
            force = bool(params.get("force", False))
            return self._run_sync(self.close_tab(tab_id=tab_id, context=ctx, force=force))
        elif action == "close_instance":
            instance_id = str(params.get("instance_id") or "").strip()
            force = bool(params.get("force", False))
            return self._run_sync(self.close_instance(instance_id=instance_id, context=ctx, force=force))
        elif action == "sync_registry":
            return self._run_sync(self.sync_registry(context=ctx))
        elif action == "gc":
            return self._run_sync(self.gc(params=params, context=ctx))
        elif action == "health":
            return self._run_sync(self.health(params=params, context=ctx))
        
        return {"error": f"Unknown action: {action_id}"}

    @staticmethod
    def _resolve_intent_class(raw: Any) -> str:
        allowed = [
            "controlar_midia",
            "realizar_pesquisa",
            "automacao_ui",
            "validacao_visual",
            "manutencao",
        ]
        value = str(raw or "").strip().lower()
        if value in allowed:
            return value
        joined = ", ".join(allowed)
        if not value:
            raise ValueError(f"intent_class is required for browser.control.run. Allowed values: {joined}")
        raise ValueError(f"Invalid intent_class '{value}'. Allowed values: {joined}")

    @staticmethod
    def _build_execution_context(
        *,
        browser_instance_id: Optional[str],
        tab_id: Optional[str],
        debug_port: Optional[int],
        cdp_target_id: Optional[str],
        runtime_backend: str,
        intent_class: str,
        reused: bool,
        policy_decision: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        target_id = cdp_target_id or ""
        return {
            "browser_instance_id": browser_instance_id or "",
            "tab_id": tab_id or "",
            "debug_port": debug_port,
            "runtime_backend": str(runtime_backend or "playwright"),
            "runtime_target_id": target_id,
            "cdp_target_id": target_id,
            "intent_class": intent_class,
            "reused_instance": bool(reused),
            "policy_decision": policy_decision or {},
        }

    @staticmethod
    def _emit_status(callbacks: Dict[str, Any], payload: Dict[str, Any]) -> None:
        try:
            if callbacks and "send_status" in callbacks:
                callbacks["send_status"]("executing", payload)
        except Exception:
            pass

    @staticmethod
    def _touch_work_context(context: Dict[str, Any], work_patch: Dict[str, Any]) -> None:
        touch = context.get("touch_work_context") if isinstance(context, dict) else None
        work_id = context.get("work_id") if isinstance(context, dict) else None
        if not callable(touch) or not work_id:
            return
        try:
            touch(work_id, work_patch)
        except Exception:
            pass

    @staticmethod
    def _build_planner_callbacks(context: Dict[str, Any], callbacks: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(callbacks or {})
        touch = context.get("touch_work_context") if isinstance(context, dict) else None
        work_id = context.get("work_id") if isinstance(context, dict) else None
        if callable(touch) and work_id:
            payload["touch_work_context"] = touch
            payload["work_id"] = work_id
        return payload

    async def _ensure_registry_instance(self, context: Dict[str, Any], intent_class: str) -> Optional[str]:
        if not self._registry_enabled:
            return None
        if self._browser_instance_id:
            return self._browser_instance_id
        if not self._runtime:
            return None
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry:
            return None
        try:
            session_id = str((context or {}).get("session_id", "default"))
            work_id = str((context or {}).get("work_id", ""))
            meta = self._runtime.get_connection_metadata() if hasattr(self._runtime, "get_connection_metadata") else {}
            self._browser_instance_id = registry.register_instance(
                owner_session_id=session_id,
                work_id=work_id,
                intent_class=intent_class,
                debug_port=meta.get("debug_port") or getattr(self._runtime, "remote_debugging_port", None),
                cdp_ws_url=meta.get("ws_url") or getattr(self._runtime, "ws_url", None),
                metadata={
                    "headless": bool(getattr(self._runtime, "headless", False)),
                    "muted": bool(getattr(self._runtime, "muted", False)),
                    "app_mode": bool(meta.get("app_mode", False)),
                    "launch_url": str(meta.get("launch_url") or ""),
                },
            )
            return self._browser_instance_id
        except Exception as e:
            logger.warning(f"Failed to register browser instance: {e}")
            return None

    async def _sync_registry_tab(self) -> Optional[str]:
        if not self._registry_enabled:
            return None
        if not self._runtime or not self._browser_instance_id or not self.kernel:
            return None
        registry = getattr(self.kernel, "browser_session_registry", None)
        if not registry:
            return None
        meta = self._runtime.get_connection_metadata() if hasattr(self._runtime, "get_connection_metadata") else {}
        target_id = str(meta.get("target_id") or "")
        if not target_id:
            return None
        try:
            url = await self._runtime._get_current_url()
            title = await self._runtime._get_current_title()
            role = "media" if self._runtime_intent_class == "controlar_midia" else "generic"
            self._tab_id = registry.register_tab(
                instance_id=self._browser_instance_id,
                target_id=target_id,
                url=url,
                title=title,
                role=role,
                metadata={"app_mode": bool(meta.get("app_mode", False))},
            )
            registry.update_instance(
                self._browser_instance_id,
                cdp_ws_url=str(meta.get("ws_url") or ""),
                debug_port=meta.get("debug_port"),
                intent_class=self._runtime_intent_class,
                owner_session_id=self._owner_session_id,
            )
            return self._tab_id
        except Exception as e:
            logger.warning(f"Failed to sync registry tab: {e}")
            return None

    async def _ensure_attached_to_registered_tab(self) -> bool:
        if not self._registry_enabled:
            return False
        if not self._runtime or not self._browser_instance_id or not self.kernel:
            return False
        if not hasattr(self._runtime, "attach_to_target"):
            return False
        registry = getattr(self.kernel, "browser_session_registry", None)
        if not registry:
            return False
        tab = None
        if self._tab_id:
            tab = registry.get_tab(self._browser_instance_id, self._tab_id)
        if not tab:
            active_tabs = [
                t
                for t in registry.list_tabs(self._browser_instance_id)
                if isinstance(t, dict) and str(t.get("status", "")).lower() in {"active", "open", "attached"}
            ]
            if active_tabs:
                active_tabs.sort(key=lambda t: str(t.get("last_seen_at") or t.get("created_at") or ""), reverse=True)
                tab = active_tabs[0]
                self._tab_id = str(tab.get("tab_id") or "") or self._tab_id
        if not tab:
            return False
        target_id = str(tab.get("target_id") or "").strip()
        if not target_id:
            return False
        return bool(await self._runtime.attach_to_target(target_id))

    async def _recover_target_binding(self) -> Dict[str, Any]:
        """
        Fallback recovery when the primary registered target cannot be reattached.
        Attempts:
        1. Attach to other active tab targets from this same instance.
        2. Attach to any available page target in the current runtime.
        """
        outcome: Dict[str, Any] = {"ok": False, "strategy": "none", "attached_target_id": ""}
        if not self._runtime or not self._browser_instance_id or not self.kernel:
            return outcome
        if not hasattr(self._runtime, "attach_to_any_page"):
            return outcome
        registry = getattr(self.kernel, "browser_session_registry", None)
        if not registry:
            return outcome

        preferred_targets: List[str] = []
        tabs = registry.list_tabs(self._browser_instance_id)
        if isinstance(tabs, list):
            tabs = sorted(
                [t for t in tabs if isinstance(t, dict)],
                key=lambda t: str(t.get("last_seen_at") or t.get("created_at") or ""),
                reverse=True,
            )
            for tab in tabs:
                if str(tab.get("status", "")).lower() in {"closed", "stale"}:
                    continue
                tid = str(tab.get("target_id") or "").strip()
                if tid:
                    preferred_targets.append(tid)

        attached_target = await self._runtime.attach_to_any_page(preferred_targets)
        if not attached_target:
            return outcome

        for tab in tabs:
            if str(tab.get("target_id") or "") == attached_target:
                self._tab_id = str(tab.get("tab_id") or "") or self._tab_id
                break
        await self._sync_registry_tab()
        return {"ok": True, "strategy": "attach_to_any_page", "attached_target_id": attached_target}

    async def _close_replaced_media_instances(self, instances: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Best-effort remote close for media instances replaced by singleton policy.
        Uses Chrome remote-debugging HTTP endpoints by debug_port.
        """
        attempted_instances = 0
        closed_targets = 0
        errors = 0
        if not instances:
            return {"attempted_instances": 0, "closed_targets": 0, "errors": 0}
        try:
            import httpx
        except Exception:
            return {"attempted_instances": 0, "closed_targets": 0, "errors": 1}

        async with httpx.AsyncClient() as client:
            for inst in instances:
                port = inst.get("debug_port")
                try:
                    port_num = int(port)
                except Exception:
                    continue
                if port_num <= 0:
                    continue
                attempted_instances += 1
                try:
                    # Close known tab targets first (from registry snapshot)
                    tabs = inst.get("tabs") if isinstance(inst.get("tabs"), list) else []
                    tab_target_ids = [str(t.get("target_id") or "").strip() for t in tabs if isinstance(t, dict)]
                    for tid in tab_target_ids:
                        if not tid:
                            continue
                        resp = await client.get(f"http://127.0.0.1:{port_num}/json/close/{tid}")
                        if resp.status_code in {200, 204}:
                            closed_targets += 1
                    # Fallback: close all remaining page targets
                    resp = await client.get(f"http://127.0.0.1:{port_num}/json/list")
                    if resp.status_code == 200:
                        targets = resp.json()
                        for t in targets if isinstance(targets, list) else []:
                            if not isinstance(t, dict) or t.get("type") != "page":
                                continue
                            tid = str(t.get("id") or "").strip()
                            if not tid:
                                continue
                            c = await client.get(f"http://127.0.0.1:{port_num}/json/close/{tid}")
                            if c.status_code in {200, 204}:
                                closed_targets += 1
                except Exception:
                    errors += 1
                    continue
        return {"attempted_instances": attempted_instances, "closed_targets": closed_targets, "errors": errors}

    def _current_target_id(self) -> str:
        if not self._runtime or not hasattr(self._runtime, "get_connection_metadata"):
            return ""
        try:
            meta = self._runtime.get_connection_metadata() or {}
            return str(meta.get("target_id") or "")
        except Exception:
            return ""

    def _runtime_connection_meta(self) -> Dict[str, Any]:
        if not self._runtime or not hasattr(self._runtime, "get_connection_metadata"):
            return {}
        try:
            meta = self._runtime.get_connection_metadata() or {}
            return meta if isinstance(meta, dict) else {}
        except Exception:
            return {}

    def _build_registry_snapshot(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._registry_enabled:
            return {"enabled": False, "instances": [], "open_tabs": [], "count_instances": 0, "count_tabs": 0}
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry:
            return {"enabled": True, "instances": [], "open_tabs": [], "count_instances": 0, "count_tabs": 0}
        ctx = context or {}
        session_id = str(ctx.get("session_id", "") or "")
        instances = []
        open_tabs = []
        for inst in registry.list_instances():
            if not isinstance(inst, dict):
                continue
            if session_id and str(inst.get("owner_session_id", "")) != session_id:
                continue
            tabs_obj = inst.get("tabs", {})
            tabs = list(tabs_obj.values()) if isinstance(tabs_obj, dict) else []
            instances.append(
                {
                    "instance_id": inst.get("instance_id"),
                    "owner_session_id": inst.get("owner_session_id"),
                    "intent_class": inst.get("intent_class"),
                    "debug_port": inst.get("debug_port"),
                    "status": inst.get("status"),
                    "tab_count": len(tabs),
                    "lock": inst.get("lock", {}),
                }
            )
            for tab in tabs:
                if not isinstance(tab, dict):
                    continue
                tab_status = str(tab.get("status", "")).lower()
                if tab_status in {"closed", "stale"}:
                    continue
                open_tabs.append(
                    {
                        "instance_id": inst.get("instance_id"),
                        "tab_id": tab.get("tab_id"),
                        "target_id": tab.get("target_id"),
                        "url": tab.get("url"),
                        "title": tab.get("title"),
                        "role": tab.get("role"),
                        "status": tab.get("status"),
                    }
                )
        return {
            "enabled": True,
            "session_id": session_id,
            "instances": instances,
            "open_tabs": open_tabs,
            "count_instances": len(instances),
            "count_tabs": len(open_tabs),
        }

    def _get_last_vision_observation(self) -> Dict[str, Any]:
        if not self._subagent or not hasattr(self._subagent, "get_last_vision_observation"):
            return {}
        try:
            obs = self._subagent.get_last_vision_observation()
            return obs if isinstance(obs, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _build_result_metadata(policy_decision: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pd = policy_decision or {}
        metadata: Dict[str, Any] = {}
        if "media_singleton_closed" in pd or "media_singleton_remote_close" in pd:
            metadata["media_singleton_cleanup"] = {
                "closed": int(pd.get("media_singleton_closed", 0) or 0),
                "remote_close": pd.get("media_singleton_remote_close", {}),
            }
        if "registry_gc" in pd:
            metadata["registry_gc"] = pd.get("registry_gc")
        if str(pd.get("route", "")).strip().lower() == "step_continue":
            metadata["continuation"] = {
                "reattach_to_tab": bool(pd.get("reattach_to_tab", False)),
                "target_recovery": pd.get("target_recovery", {}),
            }
        return metadata

    @staticmethod
    def _lock_owner_from_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        ctx = context or {}
        session_id = str(ctx.get("session_id", "default") or "default")
        work_id = str(ctx.get("work_id", "") or "").strip()
        if not work_id:
            work_id = f"inline_{session_id}"
        return {"owner_session_id": session_id, "work_id": work_id}

    async def _acquire_instance_execution_lock(self, instance_id: Optional[str], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._registry_enabled:
            return {"ok": True, "reason": "registry_disabled"}
        if not instance_id:
            return {"ok": True, "reason": "no_instance"}
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry or not hasattr(registry, "acquire_instance_lock"):
            return {"ok": True, "reason": "registry_lock_unavailable"}
        owner = self._lock_owner_from_context(context)
        return registry.acquire_instance_lock(
            instance_id,
            owner_session_id=owner["owner_session_id"],
            work_id=owner["work_id"],
            lease_seconds=300,
        )

    async def _release_instance_execution_lock(self, instance_id: Optional[str], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._registry_enabled:
            return {"ok": True, "reason": "registry_disabled"}
        if not instance_id:
            return {"ok": True, "reason": "no_instance"}
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry or not hasattr(registry, "release_instance_lock"):
            return {"ok": True, "reason": "registry_lock_unavailable"}
        owner = self._lock_owner_from_context(context)
        return registry.release_instance_lock(
            instance_id,
            owner_session_id=owner["owner_session_id"],
            work_id=owner["work_id"],
            force=False,
        )

    async def _acquire_tab_execution_lock(
        self,
        instance_id: Optional[str],
        tab_id: Optional[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._registry_enabled:
            return {"ok": True, "reason": "registry_disabled"}
        if not instance_id or not tab_id:
            return {"ok": True, "reason": "no_tab"}
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry or not hasattr(registry, "acquire_tab_lock"):
            return {"ok": True, "reason": "registry_tab_lock_unavailable"}
        owner = self._lock_owner_from_context(context)
        return registry.acquire_tab_lock(
            instance_id,
            tab_id,
            owner_session_id=owner["owner_session_id"],
            work_id=owner["work_id"],
            lease_seconds=300,
        )

    async def _release_tab_execution_lock(
        self,
        instance_id: Optional[str],
        tab_id: Optional[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._registry_enabled:
            return {"ok": True, "reason": "registry_disabled"}
        if not instance_id or not tab_id:
            return {"ok": True, "reason": "no_tab"}
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry or not hasattr(registry, "release_tab_lock"):
            return {"ok": True, "reason": "registry_tab_lock_unavailable"}
        owner = self._lock_owner_from_context(context)
        return registry.release_tab_lock(
            instance_id,
            tab_id,
            owner_session_id=owner["owner_session_id"],
            work_id=owner["work_id"],
            force=False,
        )

    def _run_registry_gc(
        self,
        *,
        context: Optional[Dict[str, Any]] = None,
        idle_seconds: Optional[int] = None,
        keep_current_instance: bool = True,
        enabled_required: bool = True,
    ) -> Dict[str, Any]:
        if not self._registry_enabled:
            return {"enabled": False, "ok": False, "reason": "registry_disabled"}
        if enabled_required and not self._registry_gc_enabled:
            return {"enabled": False}
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry:
            return {"enabled": True, "ok": False, "reason": "registry_unavailable"}
        keep_ids = [self._browser_instance_id] if keep_current_instance and self._browser_instance_id else []
        try:
            expired = registry.cleanup_expired_locks() if hasattr(registry, "cleanup_expired_locks") else {}
            closed = registry.close_idle_instances(
                idle_seconds=int(idle_seconds if idle_seconds is not None else self._registry_gc_idle_seconds),
                keep_instance_ids=keep_ids,
            ) if hasattr(registry, "close_idle_instances") else {}
            result = {"enabled": True, "ok": True, "expired_locks": expired, "closed_idle": closed}
            ctx = context or {}
            self._touch_work_context(ctx, {"data": {"browser_gc": result}})
            return result
        except Exception as e:
            return {"enabled": True, "ok": False, "reason": str(e)}

    def _maybe_run_registry_gc(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._run_registry_gc(context=context, enabled_required=True)

    def _apply_runtime_trace_context(self, ctx: Dict[str, Any]) -> None:
        runtime = self._runtime
        if not runtime or not hasattr(runtime, "set_trace_context"):
            return
        worker_ctx = ctx.get("worker_context") if isinstance(ctx.get("worker_context"), dict) else {}
        runtime.set_trace_context(
            session_id=str(ctx.get("session_id", "default")),
            work_id=str(ctx.get("work_id") or worker_ctx.get("work_id") or ""),
            interface=str(ctx.get("interface") or ctx.get("interface_name") or ctx.get("driver") or ""),
            channel=str(ctx.get("channel") or ctx.get("channel_type") or ctx.get("input_channel") or ""),
        )

    async def run_goal(
        self,
        goal: str,
        headless: bool = False,
        muted: bool = False,
        intent_class: str = "",
        completion_mode: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Capability executing run_goal with intent: '{goal}'")
        ctx = context or {}
        if not self._is_browser_launch_authorized(ctx):
            return {
                "ok": False,
                "error": (
                    "Browser launch denied: only delegated browser subagent executor can initialize browser runtime."
                ),
                "error_code": "BROWSER_LAUNCH_NOT_DELEGATED",
            }
        session_key = str(ctx.get("session_id", "default") or "default")
        now_ts = float(time.time())
        if session_key in self._active_run_by_session:
            return {
                "ok": False,
                "error": "Another browser run is already active for this session.",
                "error_code": "BROWSER_RUN_ALREADY_ACTIVE",
            }
        try:
            intent_class = self._resolve_intent_class(intent_class)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        goal_fp = self._goal_fingerprint(goal, intent_class)
        cooldown_block = self._should_block_run_by_cooldown(session_id=session_key, goal_fingerprint=goal_fp)
        if cooldown_block is not None:
            return cooldown_block
        self._active_run_by_session[session_key] = now_ts
        callbacks = ctx.get("callbacks") if isinstance(ctx.get("callbacks"), dict) else {}
        planner_callbacks = self._build_planner_callbacks(ctx, callbacks)
        gc_info = self._maybe_run_registry_gc(ctx)
        reused_instance = self._runtime is not None
        owner_session_id = str(ctx.get("session_id", "default"))
        user_request = str(ctx.get("original_user_input") or ctx.get("user_input") or "").strip()
        policy_decision = await self._apply_session_policy(
            goal=goal,
            user_request=user_request,
            intent_class=intent_class,
            owner_session_id=owner_session_id,
            headless=headless,
            muted=muted,
        )
        if not policy_decision.get("force_new_instance"):
            try:
                attached = await self._ensure_attached_to_registered_tab()
                policy_decision["reattach_to_tab"] = bool(attached)
                if not attached:
                    recovered = await self._recover_target_binding()
                    policy_decision["target_recovery"] = recovered
            except Exception:
                policy_decision["reattach_to_tab"] = False
                policy_decision["target_recovery"] = {"ok": False, "strategy": "exception"}
        policy_decision["registry_gc"] = gc_info
        browser_instance_id = await self._ensure_registry_instance(ctx, intent_class)
        if (
            self._media_singleton_enforced
            and intent_class == "controlar_midia"
            and browser_instance_id
            and self.kernel
            and hasattr(self.kernel, "browser_session_registry")
        ):
            try:
                registry = self.kernel.browser_session_registry
                if hasattr(registry, "close_other_media_instances_detailed"):
                    close_result = registry.close_other_media_instances_detailed(
                        owner_session_id=owner_session_id,
                        keep_instance_id=browser_instance_id,
                    )
                    policy_decision["media_singleton_closed"] = int(close_result.get("closed", 0))
                    remote = await self._close_replaced_media_instances(
                        close_result.get("instances") if isinstance(close_result.get("instances"), list) else []
                    )
                    policy_decision["media_singleton_remote_close"] = remote
                else:
                    closed_media = registry.close_other_media_instances(
                        owner_session_id=owner_session_id,
                        keep_instance_id=browser_instance_id,
                    )
                    policy_decision["media_singleton_closed"] = int(closed_media)
            except Exception as e:
                logger.warning(f"Failed to enforce media singleton: {e}")
                policy_decision["media_singleton_closed"] = 0
        tab_id = await self._sync_registry_tab()
        exec_ctx = self._build_execution_context(
            browser_instance_id=browser_instance_id,
            tab_id=tab_id,
            debug_port=getattr(self._runtime, "remote_debugging_port", None) if self._runtime else None,
            cdp_target_id=self._current_target_id(),
            runtime_backend=self._resolve_runtime_backend(),
            intent_class=intent_class,
            reused=reused_instance,
            policy_decision=policy_decision,
        )
        if user_request:
            exec_ctx["original_user_input"] = user_request[:500]
        if isinstance(policy_decision.get("media_singleton_remote_close"), dict):
            self._emit_status(
                callbacks,
                {
                    "action": "browser.control.run",
                    "code": "media_singleton_cleanup",
                    "label": "Media singleton cleanup applied.",
                    "media_cleanup": {
                        "closed": int(policy_decision.get("media_singleton_closed", 0) or 0),
                        "remote_close": policy_decision.get("media_singleton_remote_close"),
                    },
                    "browser": exec_ctx,
                },
            )

        # Playback integration
        playback_service = ctx.get("playback_service")
        session_id = ctx.get("session_id", "default")
        run_id = f"browser_{int(asyncio.get_running_loop().time() * 1000)}"
        run_status = "completed"
        
        if playback_service:
            playback_service.start_run(
                session_id=session_id,
                run_id=run_id,
                title=f"Browser: {goal[:50]}...",
                source={"capability": "browser_control", "action": "run_goal"}
            )
            
            # Notify frontend about the playback run so the card appears in the chat
            self._emit_status(callbacks, {
                "action": "browser.control.run",
                "label": f"Navegando: {goal[:50]}...",
                "playback": {
                    "run_id": run_id,
                    "session_id": session_id,
                    "status": "running",
                },
                "browser": exec_ctx,
            })

        lock_info = await self._acquire_instance_execution_lock(browser_instance_id, ctx)
        exec_ctx["instance_lock"] = lock_info
        if not lock_info.get("ok"):
            reason = str(lock_info.get("reason") or "instance lock denied")
            self._recent_failed_goal_by_session[session_key] = {
                "goal_fingerprint": goal_fp,
                "failed_at_ts": float(time.time()),
                "reason": reason,
            }
            self._touch_work_context(
                ctx,
                {
                    "data": {
                        "browser": exec_ctx,
                        "browser_registry_snapshot": self._build_registry_snapshot(ctx),
                        "browser_error": reason,
                    }
                },
            )
            return {"ok": False, "error": reason, "execution_context": exec_ctx}
        try:
            self._apply_runtime_trace_context(ctx)
            tab_lock_info = await self._acquire_tab_execution_lock(browser_instance_id, tab_id, ctx)
            exec_ctx["tab_lock"] = tab_lock_info
            if not tab_lock_info.get("ok"):
                reason = str(tab_lock_info.get("reason") or "tab lock denied")
                self._recent_failed_goal_by_session[session_key] = {
                    "goal_fingerprint": goal_fp,
                    "failed_at_ts": float(time.time()),
                    "reason": reason,
                }
                self._touch_work_context(
                    ctx,
                    {
                        "data": {
                            "browser": exec_ctx,
                            "browser_registry_snapshot": self._build_registry_snapshot(ctx),
                            "browser_error": reason,
                        }
                    },
                )
                return {"ok": False, "error": reason, "execution_context": exec_ctx}
            # subagent.run_to_goal returns a ToonResponse Pydantic model
            response = await self._subagent.run_to_goal(
                goal,
                playback_service=playback_service,
                run_id=run_id,
                session_id=session_id,
                callbacks=planner_callbacks,
                completion_mode=completion_mode,
            )

            # Prepare structured result with playback metadata if available
            response_payload: Dict[str, Any]
            if hasattr(response, "model_dump"):
                response_payload = response.model_dump(mode='json')
            else:
                response_payload = {"status": "unknown", "raw": str(response)}
            response_status = str(response_payload.get("status") or "").strip().lower()
            is_error_response = response_status in {"error", "failed", "failure"}
            if is_error_response:
                run_status = "failed"
                self._recent_failed_goal_by_session[session_key] = {
                    "goal_fingerprint": goal_fp,
                    "failed_at_ts": float(time.time()),
                    "reason": str(response_payload.get("error_details") or response_payload.get("error") or "planner_error"),
                }
            result_data = {
                "ok": not is_error_response,
                "status": "error" if is_error_response else "success",
                "result": response_payload,
            }
            final_tab_id = await self._sync_registry_tab()
            if final_tab_id:
                exec_ctx["tab_id"] = final_tab_id
            runtime_target_id = self._current_target_id()
            exec_ctx["runtime_target_id"] = runtime_target_id
            exec_ctx["cdp_target_id"] = runtime_target_id
            last_vision = self._get_last_vision_observation()
            if last_vision:
                exec_ctx["last_vision_observation"] = last_vision
            result_data["execution_context"] = exec_ctx
            result_data["registry_snapshot"] = self._build_registry_snapshot(ctx)
            metadata = self._build_result_metadata(policy_decision)
            if metadata:
                result_data["metadata"] = metadata
            
            if playback_service:
                result_data["playback"] = {
                    "run_id": run_id,
                    "session_id": session_id,
                    "status": run_status,
                }
            self._touch_work_context(
                ctx,
                {
                    "data": {
                        "browser": exec_ctx,
                        "browser_registry_snapshot": result_data["registry_snapshot"],
                        "browser_last_vision": last_vision if last_vision else {},
                    }
                },
            )
            if is_error_response:
                result_data["error"] = str(response_payload.get("error_details") or response_payload.get("error") or "planner_error")
            return result_data
        except Exception as e:
            logger.error(f"Error in run_goal: {e}")
            run_status = "failed"
            self._recent_failed_goal_by_session[session_key] = {
                "goal_fingerprint": goal_fp,
                "failed_at_ts": float(time.time()),
                "reason": str(e),
            }
            self._touch_work_context(
                ctx,
                {
                    "data": {
                        "browser": exec_ctx,
                        "browser_registry_snapshot": self._build_registry_snapshot(ctx),
                        "browser_error": str(e),
                    }
                },
            )
            fail_payload = {"ok": False, "error": str(e), "execution_context": exec_ctx}
            metadata = self._build_result_metadata(policy_decision)
            if metadata:
                fail_payload["metadata"] = metadata
            return fail_payload
        finally:
            self._active_run_by_session.pop(session_key, None)
            try:
                release_tab_info = await self._release_tab_execution_lock(browser_instance_id, tab_id, ctx)
                exec_ctx["tab_lock_release"] = release_tab_info
            except Exception:
                pass
            try:
                release_info = await self._release_instance_execution_lock(browser_instance_id, ctx)
                exec_ctx["instance_lock_release"] = release_info
            except Exception:
                pass
            if playback_service:
                playback_service.end_run(session_id, run_id, status=run_status)
                
                # Notify frontend about playback completion
                self._emit_status(callbacks, {
                    "action": "browser.control.run",
                    "label": "Gravado." if run_status == "completed" else "Falhou.",
                    "playback": {
                        "run_id": run_id,
                        "session_id": session_id,
                        "status": run_status,
                    },
                    "browser": exec_ctx,
                })
            if run_status == "completed":
                self._recent_failed_goal_by_session.pop(session_key, None)

    async def step(self, instruction: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ctx = context or {}
        callbacks = ctx.get("callbacks") if isinstance(ctx.get("callbacks"), dict) else {}
        planner_callbacks = self._build_planner_callbacks(ctx, callbacks)
        gc_info = self._maybe_run_registry_gc(ctx)
        if not self._runtime or not self._subagent:
            return {"ok": False, "error": "No active browser runtime. Run browser.control.run first."}
        if not str(instruction or "").strip():
            return {"ok": False, "error": "instruction is required"}

        reattach_ok = False
        recovery: Dict[str, Any] = {"ok": False, "strategy": "skipped"}
        try:
            reattach_ok = await self._ensure_attached_to_registered_tab()
            if not reattach_ok:
                recovery = await self._recover_target_binding()
                reattach_ok = bool(recovery.get("ok"))
        except Exception:
            reattach_ok = False
            recovery = {"ok": False, "strategy": "exception"}

        intent_class = str(self._runtime_intent_class or "").strip().lower()
        if not intent_class:
            return {
                "ok": False,
                "error": (
                    "Missing runtime intent_class for browser continuation. "
                    "Run browser.control.run again with explicit intent_class."
                ),
            }
        browser_instance_id = await self._ensure_registry_instance(ctx, intent_class)
        tab_id = await self._sync_registry_tab()
        step_policy_decision: Dict[str, Any] = {
            "route": "step_continue",
            "reason": "continuation",
            "reattach_to_tab": bool(reattach_ok),
            "target_recovery": recovery,
            "registry_gc": gc_info,
        }
        exec_ctx = self._build_execution_context(
            browser_instance_id=browser_instance_id,
            tab_id=tab_id,
            debug_port=getattr(self._runtime, "remote_debugging_port", None) if self._runtime else None,
            cdp_target_id=self._current_target_id(),
            runtime_backend=self._resolve_runtime_backend(),
            intent_class=intent_class,
            reused=True,
            policy_decision=step_policy_decision,
        )

        self._emit_status(
            callbacks,
            {"action": "browser.control.step", "label": f"Continuando: {instruction[:50]}...", "browser": exec_ctx},
        )
        lock_info = await self._acquire_instance_execution_lock(browser_instance_id, ctx)
        exec_ctx["instance_lock"] = lock_info
        if not lock_info.get("ok"):
            reason = str(lock_info.get("reason") or "instance lock denied")
            self._touch_work_context(
                ctx,
                {
                    "data": {
                        "browser": exec_ctx,
                        "browser_registry_snapshot": self._build_registry_snapshot(ctx),
                        "browser_error": reason,
                    }
                },
            )
            fail_payload = {"ok": False, "error": reason, "execution_context": exec_ctx}
            metadata = self._build_result_metadata(step_policy_decision)
            if metadata:
                fail_payload["metadata"] = metadata
            return fail_payload
        try:
            self._apply_runtime_trace_context(ctx)
            tab_lock_info = await self._acquire_tab_execution_lock(browser_instance_id, tab_id, ctx)
            exec_ctx["tab_lock"] = tab_lock_info
            if not tab_lock_info.get("ok"):
                reason = str(tab_lock_info.get("reason") or "tab lock denied")
                self._touch_work_context(
                    ctx,
                    {
                        "data": {
                            "browser": exec_ctx,
                            "browser_registry_snapshot": self._build_registry_snapshot(ctx),
                            "browser_error": reason,
                        }
                    },
                )
                fail_payload = {"ok": False, "error": reason, "execution_context": exec_ctx}
                metadata = self._build_result_metadata(step_policy_decision)
                if metadata:
                    fail_payload["metadata"] = metadata
                return fail_payload
            response = await self._subagent.run_to_goal(
                instruction,
                playback_service=ctx.get("playback_service"),
                run_id=f"browser_step_{int(asyncio.get_running_loop().time() * 1000)}",
                session_id=ctx.get("session_id", "default"),
                callbacks=planner_callbacks,
            )
            result_data: Dict[str, Any] = {"ok": True}
            if hasattr(response, "model_dump"):
                result_data["result"] = response.model_dump(mode="json")
            else:
                result_data["result"] = str(response)
            final_tab_id = await self._sync_registry_tab()
            if final_tab_id:
                exec_ctx["tab_id"] = final_tab_id
            runtime_target_id = self._current_target_id()
            exec_ctx["runtime_target_id"] = runtime_target_id
            exec_ctx["cdp_target_id"] = runtime_target_id
            last_vision = self._get_last_vision_observation()
            if last_vision:
                exec_ctx["last_vision_observation"] = last_vision
            result_data["execution_context"] = exec_ctx
            result_data["registry_snapshot"] = self._build_registry_snapshot(ctx)
            metadata = self._build_result_metadata(step_policy_decision)
            if metadata:
                result_data["metadata"] = metadata
            self._touch_work_context(
                ctx,
                {
                    "data": {
                        "browser": exec_ctx,
                        "browser_registry_snapshot": result_data["registry_snapshot"],
                        "browser_last_vision": last_vision if last_vision else {},
                    }
                },
            )
            return result_data
        except Exception as e:
            self._touch_work_context(
                ctx,
                {
                    "data": {
                        "browser": exec_ctx,
                        "browser_registry_snapshot": self._build_registry_snapshot(ctx),
                        "browser_error": str(e),
                    }
                },
            )
            fail_payload = {"ok": False, "error": str(e), "execution_context": exec_ctx}
            metadata = self._build_result_metadata(step_policy_decision)
            if metadata:
                fail_payload["metadata"] = metadata
            return fail_payload
        finally:
            try:
                release_tab_info = await self._release_tab_execution_lock(browser_instance_id, tab_id, ctx)
                exec_ctx["tab_lock_release"] = release_tab_info
            except Exception:
                pass
            try:
                release_info = await self._release_instance_execution_lock(browser_instance_id, ctx)
                exec_ctx["instance_lock_release"] = release_info
            except Exception:
                pass

    async def close(self) -> Dict[str, Any]:
        if self._runtime:
            await self._runtime.close()
            self._runtime = None
            self._subagent = None
        await self._close_registered_instance(reason="capability_close")
        self._owner_session_id = None
        self._runtime_intent_class = None
        self._new_tabs_opened_by_session = {}
        return {"ok": True}

    async def inspect(self, params: Optional[Dict[str, Any]] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p = params or {}
        ctx = context or {}
        if not self._registry_enabled:
            return {"ok": False, "error": "browser registry disabled by feature flag"}
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry:
            return {"ok": False, "error": "browser registry not available"}

        only_current_session = bool(p.get("only_current_session", False))
        include_tabs = bool(p.get("include_tabs", True))
        include_last_vision = bool(p.get("include_last_vision", False))
        session_filter = str(p.get("session_id") or (ctx.get("session_id") if only_current_session else "") or "").strip()

        rows = []
        for inst in registry.list_instances():
            if session_filter and str(inst.get("owner_session_id", "")) != session_filter:
                continue
            row = {
                "instance_id": inst.get("instance_id"),
                "owner_session_id": inst.get("owner_session_id"),
                "work_id": inst.get("work_id"),
                "intent_class": inst.get("intent_class"),
                "debug_port": inst.get("debug_port"),
                "status": inst.get("status"),
                "in_use": bool(inst.get("in_use", False)),
                "last_heartbeat_at": inst.get("last_heartbeat_at"),
            }
            if include_tabs:
                tabs = inst.get("tabs", {})
                if isinstance(tabs, dict):
                    row["tabs"] = list(tabs.values())
                else:
                    row["tabs"] = []
            rows.append(row)

        runtime_connection = self._runtime_connection_meta()

        return {
            "ok": True,
            "instances": rows,
            "count": len(rows),
            "current_execution": {
                "browser_instance_id": self._browser_instance_id,
                "tab_id": self._tab_id,
                "owner_session_id": self._owner_session_id,
                "runtime_backend": self._resolve_runtime_backend(),
                "runtime_connection": runtime_connection,
                "last_vision_observation": self._get_last_vision_observation() if include_last_vision else {},
            },
        }

    async def close_instance(self, instance_id: str, context: Optional[Dict[str, Any]] = None, force: bool = False) -> Dict[str, Any]:
        ctx = context or {}
        if not self._registry_enabled:
            return {"ok": False, "error": "browser registry disabled by feature flag"}
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry:
            return {"ok": False, "error": "browser registry not available"}
        target = str(instance_id or "").strip() or str(self._browser_instance_id or "")
        if not target:
            return {"ok": False, "error": "instance_id required"}
        inst = registry.get_instance(target)
        if not isinstance(inst, dict):
            return {"ok": False, "error": f"instance not found: {target}"}
        guard = self._validate_close_guard(inst, context=ctx, force=force)
        if not guard.get("allowed"):
            return {"ok": False, "error": str(guard.get("reason") or "close blocked by ownership/in_use guard")}

        if target == self._browser_instance_id and self._runtime:
            await self._runtime.close()
            self._runtime = None
            self._subagent = None
            self._tab_id = None
            self._owner_session_id = None
            self._runtime_intent_class = None
            self._browser_instance_id = None

        registry.close_instance(target, reason="close_instance_action")
        return {"ok": True, "closed_instance_id": target}

    @staticmethod
    def _validate_close_guard(instance: Dict[str, Any], context: Optional[Dict[str, Any]] = None, force: bool = False) -> Dict[str, Any]:
        ctx = context or {}
        if force:
            return {"allowed": True, "reason": "force"}
        session_id = str(ctx.get("session_id", "") or "")
        work_id = str(ctx.get("work_id", "") or "")
        owner_session_id = str(instance.get("owner_session_id", "") or "")
        owner_work_id = str(instance.get("work_id", "") or "")
        in_use = bool(instance.get("in_use", False))
        status = str(instance.get("status", "")).lower()

        if status in {"closed", "stale"}:
            return {"allowed": True, "reason": "already_not_active"}
        if owner_session_id and session_id and owner_session_id != session_id:
            return {"allowed": False, "reason": "instance belongs to another session; use force=true to override"}
        if in_use and owner_work_id and work_id and owner_work_id != work_id:
            return {"allowed": False, "reason": "instance is in use by another work; use force=true to override"}
        if in_use and owner_work_id and not work_id:
            return {"allowed": False, "reason": "instance is in use and caller work_id is missing; use force=true to override"}
        return {"allowed": True, "reason": "owner_or_idle"}

    async def close_tab(self, tab_id: str, context: Optional[Dict[str, Any]] = None, force: bool = False) -> Dict[str, Any]:
        ctx = context or {}
        if not self._registry_enabled:
            return {"ok": False, "error": "browser registry disabled by feature flag"}
        registry = getattr(self.kernel, "browser_session_registry", None) if self.kernel else None
        if not registry:
            return {"ok": False, "error": "browser registry not available"}
        wanted_tab = str(tab_id or "").strip() or str(self._tab_id or "")
        if not wanted_tab:
            return {"ok": False, "error": "tab_id required"}

        owner_instance_id = ""
        for inst in registry.list_instances():
            tabs = inst.get("tabs", {})
            if not isinstance(tabs, dict):
                continue
            if wanted_tab in tabs:
                owner_instance_id = str(inst.get("instance_id") or "")
                break
        if not owner_instance_id:
            return {"ok": False, "error": f"tab not found: {wanted_tab}"}
        inst = registry.get_instance(owner_instance_id)
        if not isinstance(inst, dict):
            return {"ok": False, "error": f"instance not found: {owner_instance_id}"}
        guard = self._validate_close_guard(inst, context=ctx, force=force)
        if not guard.get("allowed"):
            return {"ok": False, "error": str(guard.get("reason") or "close blocked by ownership/in_use guard")}

        # If this is the live bound tab, close the runtime target by closing runtime instance.
        if wanted_tab == self._tab_id and owner_instance_id == self._browser_instance_id and self._runtime:
            await self._runtime.close()
            self._runtime = None
            self._subagent = None
            self._tab_id = None
            self._owner_session_id = None
            self._runtime_intent_class = None
            self._browser_instance_id = None
            registry.close_instance(owner_instance_id, reason="close_tab_action_current_target")
            return {"ok": True, "closed_tab_id": wanted_tab, "closed_instance_id": owner_instance_id}

        registry.close_tab(owner_instance_id, wanted_tab, reason="close_tab_action")
        return {"ok": True, "closed_tab_id": wanted_tab, "instance_id": owner_instance_id}

    async def sync_registry(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._registry_enabled:
            return {"ok": False, "error": "browser registry disabled by feature flag"}
        ctx = context or {}
        intent_class = self._runtime_intent_class or self._resolve_intent_class(None)
        instance_id = await self._ensure_registry_instance(ctx, intent_class)
        tab_id = await self._sync_registry_tab()
        last_vision = self._get_last_vision_observation()
        runtime_meta = self._runtime_connection_meta()
        return {
            "ok": True,
            "browser_instance_id": instance_id,
            "tab_id": tab_id,
            "debug_port": getattr(self._runtime, "remote_debugging_port", None) if self._runtime else None,
            "runtime_backend": self._resolve_runtime_backend(),
            "transport_mode_configured": str(runtime_meta.get("transport_mode_configured", "") or ""),
            "transport_mode_effective": str(runtime_meta.get("transport_mode_effective", "") or ""),
            "mcp_endpoint": str(runtime_meta.get("mcp_endpoint", "") or ""),
            "runtime_target_id": self._current_target_id(),
            "cdp_target_id": self._current_target_id(),
            "mcp_calls_total": int((runtime_meta.get("mcp_calls_total", 0) or 0)),
            "registry_snapshot": self._build_registry_snapshot(ctx),
            "last_vision_observation": last_vision if last_vision else {},
        }

    async def gc(self, params: Optional[Dict[str, Any]] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p = params or {}
        ctx = context or {}
        idle_seconds_raw = p.get("idle_seconds")
        idle_seconds = int(idle_seconds_raw) if str(idle_seconds_raw or "").strip() else None
        keep_current = bool(p.get("keep_current_instance", True))
        run_gc = self._run_registry_gc(
            context=ctx,
            idle_seconds=idle_seconds,
            keep_current_instance=keep_current,
            enabled_required=False,
        )
        return {
            "ok": bool(run_gc.get("ok", False)),
            "gc": run_gc,
            "registry_snapshot": self._build_registry_snapshot(ctx),
        }

    async def health(self, params: Optional[Dict[str, Any]] = None, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p = params or {}
        ctx = context or {}
        run_gc = bool(p.get("run_gc", False))
        include_tabs = bool(p.get("include_tabs", True))
        include_last_vision = bool(p.get("include_last_vision", True))
        only_current_session = bool(p.get("only_current_session", True))

        inspect_result = await self.inspect(
            params={
                "only_current_session": only_current_session,
                "include_tabs": include_tabs,
                "include_last_vision": include_last_vision,
            },
            context=ctx,
        )
        sync_result = await self.sync_registry(context=ctx)
        gc_result: Dict[str, Any] = {"enabled": False, "ok": False}
        if run_gc:
            gc_result = (await self.gc(params=p.get("gc_params") if isinstance(p.get("gc_params"), dict) else {}, context=ctx)).get("gc", {})

        snapshot = self._build_registry_snapshot(ctx)
        issues: List[str] = []
        current_exec = inspect_result.get("current_execution") if isinstance(inspect_result, dict) else {}
        if not isinstance(current_exec, dict):
            current_exec = {}
        if not str(current_exec.get("browser_instance_id", "")).strip():
            issues.append("no_active_browser_instance_bound")
        transport_mode_configured = str(sync_result.get("transport_mode_configured", "") or "").strip().lower()
        transport_mode_effective = str(sync_result.get("transport_mode_effective", "") or "").strip().lower()
        if transport_mode_configured == "mcp":
            if transport_mode_effective and transport_mode_effective != "mcp":
                issues.append("mcp_transport_not_effective")
            if not str(sync_result.get("mcp_endpoint", "") or "").strip():
                issues.append("mcp_mode_without_endpoint")
        runtime_target = str(sync_result.get("runtime_target_id", "") or sync_result.get("cdp_target_id", "")).strip()
        if not runtime_target:
            issues.append("no_active_runtime_target")
            issues.append("no_active_cdp_target")
        if run_gc and not bool(gc_result.get("ok", False)):
            issues.append("gc_execution_failed")
        if isinstance(snapshot, dict) and int(snapshot.get("count_instances", 0) or 0) == 0:
            issues.append("no_registry_instances_for_scope")

        return {
            "ok": True,
            "health": {
                "status": "ok" if not issues else "degraded",
                "issues": issues,
            },
            "inspect": inspect_result,
            "sync": sync_result,
            "gc": gc_result,
            "registry_snapshot": snapshot,
        }
