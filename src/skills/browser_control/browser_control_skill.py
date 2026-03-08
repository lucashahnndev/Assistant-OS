import asyncio
import logging
import re
from typing import List, Dict, Any, Optional, Union
from ..base import SkillBase
from .session_policy import BrowserSessionPolicy

logger = logging.getLogger("aosd.skills.browser_control")

class BrowserControlSkill(SkillBase):
    def __init__(self, kernel: Any, config: Dict[str, Any]):
        self.kernel = kernel
        self._config = config
        self._registry_enabled = self._cfg_bool("registry_enabled", True)
        self._policy_enabled = self._cfg_bool("policy_enabled", True)
        self._media_singleton_enforced = self._cfg_bool("media_singleton_enforced", True)
        self._app_mode_enabled = self._cfg_bool("app_mode_enabled", True)
        self._registry_gc_enabled = self._cfg_bool("registry_gc_enabled", False)
        self._registry_gc_idle_seconds = int(self._config.get("registry_gc_idle_seconds", 1800)) if isinstance(self._config, dict) else 1800
        self._runtime: Optional[Any] = None
        self._subagent: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._browser_instance_id: Optional[str] = None
        self._tab_id: Optional[str] = None
        self._owner_session_id: Optional[str] = None
        self._runtime_intent_class: Optional[str] = None
        self._policy = BrowserSessionPolicy({"app_mode_enabled": self._app_mode_enabled})

    def _cfg_bool(self, key: str, default: bool) -> bool:
        if not isinstance(self._config, dict):
            return bool(default)
        if key not in self._config:
            return bool(default)
        return bool(self._config.get(key))

    @property
    def name(self) -> str:
        return "browser_control"

    @property
    def actions(self) -> List[str]:
        return ["run", "step", "close", "inspect", "close_tab", "close_instance", "sync_registry", "gc"]

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
        from .runtime import BrowserRuntime
        from .planner import BrowserSubagent
        current_loop = asyncio.get_running_loop()
        should_recreate = force_new_instance

        # Re-init if loop changed or launch options differ
        if self._runtime and self._loop != current_loop:
            logger.info("Event loop changed, re-initializing runtime")
            should_recreate = True

        if should_recreate and self._runtime:
            try:
                await self._runtime.close()
            finally:
                self._runtime = None
                self._subagent = None
                self._tab_id = None
                self._runtime_intent_class = None

        if not self._runtime:
            if not self.kernel:
                raise RuntimeError("Kernel not initialized in BrowserControlSkill")
            self._loop = current_loop
            self._runtime = BrowserRuntime(
                headless=headless,
                muted=muted,
                app_mode=use_app_mode,
                launch_url=launch_url,
            )
            await self._runtime.launch()
            self._subagent = BrowserSubagent(self._runtime, self.kernel.llm_manager)

    @staticmethod
    def _extract_first_url(text: str) -> str:
        match = re.search(r"https?://[^\s,]+", str(text or ""), re.IGNORECASE)
        return match.group(0).strip() if match else ""

    def _resolve_launch_url(self, goal: str, intent_class: str) -> str:
        explicit = self._extract_first_url(goal)
        if explicit:
            return explicit
        goal_lower = str(goal or "").lower()
        if "music.youtube" in goal_lower:
            return "https://music.youtube.com"
        if "youtube" in goal_lower:
            return "https://www.youtube.com"
        if "spotify" in goal_lower:
            return "https://www.spotify.com"
        if "github" in goal_lower:
            return "https://www.github.com"
        if "google" in goal_lower:
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
        intent_class: str,
        owner_session_id: str,
        headless: bool,
        muted: bool,
    ) -> Dict[str, Any]:
        launch_url = self._resolve_launch_url(goal, intent_class)
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
        if decision.route == "new_tab" and self._runtime and hasattr(self._runtime, "open_new_tab"):
            try:
                new_target = await self._runtime.open_new_tab(launch_url)
                decision_data["new_tab_opened"] = bool(new_target)
                if new_target:
                    self._tab_id = None
                    decision_data["new_tab_target_id"] = str(new_target)
            except Exception as e:
                decision_data["new_tab_opened"] = False
                decision_data["new_tab_error"] = str(e)
        return decision_data

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

        if action == "run":
            goal = (
                params.get("goal")
                or params.get("instruction")
                or params.get("query")
                or context.get("user_input")
                or context.get("prompt")
                or ""
            )
            # Optional launch params — agent can pass these or they default to sane values
            headless = bool(params.get("headless", self._config.get("headless", False)))
            muted = bool(params.get("muted", False))
            intent_class = self._resolve_intent_class(params.get("intent_class"))
            logger.info(f"Resolved goal for 'run': '{goal}' (from params keys: {list(params.keys())})")
            return self._run_sync(self.run_goal(goal, headless=headless, muted=muted, intent_class=intent_class, context=context))
        elif action == "step":
            instruction = (
                params.get("instruction")
                or params.get("goal")
                or params.get("query")
                or context.get("user_input")
                or context.get("prompt")
                or ""
            )
            return self._run_sync(self.step(instruction, context=context))
        elif action == "close":
            return self._run_sync(self.close())
        elif action == "inspect":
            return self._run_sync(self.inspect(params=params, context=context))
        elif action == "close_tab":
            tab_id = str(params.get("tab_id") or "").strip()
            force = bool(params.get("force", False))
            return self._run_sync(self.close_tab(tab_id=tab_id, context=context, force=force))
        elif action == "close_instance":
            instance_id = str(params.get("instance_id") or "").strip()
            force = bool(params.get("force", False))
            return self._run_sync(self.close_instance(instance_id=instance_id, context=context, force=force))
        elif action == "sync_registry":
            return self._run_sync(self.sync_registry(context=context))
        elif action == "gc":
            return self._run_sync(self.gc(params=params, context=context))
        
        return {"error": f"Unknown action: {action_id}"}

    @staticmethod
    def _resolve_intent_class(raw: Any) -> str:
        allowed = {
            "controlar_midia",
            "realizar_pesquisa",
            "automacao_ui",
            "validacao_visual",
            "manutencao",
        }
        value = str(raw or "").strip().lower()
        if value in allowed:
            return value
        return "realizar_pesquisa"

    @staticmethod
    def _build_execution_context(
        *,
        browser_instance_id: Optional[str],
        tab_id: Optional[str],
        debug_port: Optional[int],
        cdp_target_id: Optional[str],
        intent_class: str,
        reused: bool,
        policy_decision: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "browser_instance_id": browser_instance_id or "",
            "tab_id": tab_id or "",
            "debug_port": debug_port,
            "cdp_target_id": cdp_target_id or "",
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

    async def run_goal(
        self,
        goal: str,
        headless: bool = False,
        muted: bool = False,
        intent_class: str = "realizar_pesquisa",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Skill executing run_goal with intent: '{goal}'")
        ctx = context or {}
        callbacks = ctx.get("callbacks") if isinstance(ctx.get("callbacks"), dict) else {}
        gc_info = self._maybe_run_registry_gc(ctx)
        reused_instance = self._runtime is not None
        owner_session_id = str(ctx.get("session_id", "default"))
        policy_decision = await self._apply_session_policy(
            goal=goal,
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
            intent_class=intent_class,
            reused=reused_instance,
            policy_decision=policy_decision,
        )
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
                source={"skill": "browser_control", "action": "run_goal"}
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
                return {"ok": False, "error": reason, "execution_context": exec_ctx}
            # subagent.run_to_goal returns a ToonResponse Pydantic model
            response = await self._subagent.run_to_goal(goal, playback_service=playback_service, run_id=run_id, session_id=session_id)

            # Prepare structured result with playback metadata if available
            result_data = {"ok": True}
            if hasattr(response, "model_dump"):
                result_data["result"] = response.model_dump(mode='json')
            else:
                result_data["result"] = str(response)
            final_tab_id = await self._sync_registry_tab()
            if final_tab_id:
                exec_ctx["tab_id"] = final_tab_id
            exec_ctx["cdp_target_id"] = self._current_target_id()
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
                    "status": "completed"
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
            return result_data
        except Exception as e:
            logger.error(f"Error in run_goal: {e}")
            run_status = "failed"
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

    async def step(self, instruction: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ctx = context or {}
        callbacks = ctx.get("callbacks") if isinstance(ctx.get("callbacks"), dict) else {}
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

        intent_class = self._runtime_intent_class or self._resolve_intent_class(None)
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
            )
            result_data: Dict[str, Any] = {"ok": True}
            if hasattr(response, "model_dump"):
                result_data["result"] = response.model_dump(mode="json")
            else:
                result_data["result"] = str(response)
            final_tab_id = await self._sync_registry_tab()
            if final_tab_id:
                exec_ctx["tab_id"] = final_tab_id
            exec_ctx["cdp_target_id"] = self._current_target_id()
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
        await self._close_registered_instance(reason="skill_close")
        self._owner_session_id = None
        self._runtime_intent_class = None
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

        return {
            "ok": True,
            "instances": rows,
            "count": len(rows),
            "current_execution": {
                "browser_instance_id": self._browser_instance_id,
                "tab_id": self._tab_id,
                "owner_session_id": self._owner_session_id,
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
        return {
            "ok": True,
            "browser_instance_id": instance_id,
            "tab_id": tab_id,
            "debug_port": getattr(self._runtime, "remote_debugging_port", None) if self._runtime else None,
            "cdp_target_id": self._current_target_id(),
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
