import asyncio
import tempfile

from src.capabilities.browser_control.browser_control_capability import BrowserControlCapability
from src.capabilities.browser_control.session_policy import BrowserSessionPolicy
from src.capabilities.browser_control.session_registry import BrowserSessionRegistry


class _FakeRuntime:
    def __init__(self):
        self.remote_debugging_port = 9555
        self.ws_url = "ws://localhost:9555/devtools/page/abc"
        self.target_id = "target-abc"
        self.headless = True
        self.muted = False
        self._attached = []

    def get_connection_metadata(self):
        return {
            "debug_port": self.remote_debugging_port,
            "ws_url": self.ws_url,
            "target_id": self.target_id,
            "app_mode": False,
            "launch_url": "https://example.com",
        }

    async def _get_current_url(self):
        return "https://example.com"

    async def _get_current_title(self):
        return "Example"

    async def attach_to_target(self, target_id: str):
        self._attached.append(target_id)
        self.target_id = target_id
        return True

    async def close(self):
        return None


class _FakeRuntimeRecover(_FakeRuntime):
    async def attach_to_target(self, target_id: str):
        _ = target_id
        return False

    async def attach_to_any_page(self, preferred_target_ids=None):
        _ = preferred_target_ids or []
        self.target_id = "target-recovered"
        return self.target_id


class _FakeResponse:
    def model_dump(self, mode="json"):
        _ = mode
        return {"status": "success"}


class _FakeSubagent:
    async def run_to_goal(self, goal, playback_service=None, run_id="default", session_id="default", **kwargs):
        _ = (goal, playback_service, run_id, session_id, kwargs)
        return _FakeResponse()

    def get_last_vision_observation(self):
        return {
            "schema": "browser_control.vision.v1",
            "summary": "Botao pular anuncio visivel",
            "coordinates": [{"x": 812, "y": 134}],
            "prompt_view": "Vision: Botao pular anuncio visivel | Coords: (812,134)",
        }


class _FakeKernel:
    def __init__(self, base_data_dir: str):
        self.browser_session_registry = BrowserSessionRegistry(base_data_dir=base_data_dir)
        self.llm_manager = object()


def test_session_policy_media_upgrade():
    policy = BrowserSessionPolicy({"app_mode_enabled": True})
    decision = policy.decide(
        intent_class="controlar_midia",
        goal="tocar musica",
        owner_session_id="s1",
        current_owner_session_id="s1",
        current_intent_class="realizar_pesquisa",
        has_runtime=True,
    )
    assert decision.route == "reuse_tab"
    assert decision.force_new_instance is False
    assert decision.use_app_mode is True


def test_session_policy_cross_domain_prefers_new_tab():
    policy = BrowserSessionPolicy({"app_mode_enabled": True})
    decision = policy.decide(
        intent_class="realizar_pesquisa",
        goal="pesquisar",
        owner_session_id="s1",
        current_owner_session_id="s1",
        current_intent_class="realizar_pesquisa",
        has_runtime=True,
        launch_url="https://github.com",
        current_url="https://www.google.com/search?q=test",
    )
    assert decision.route == "new_tab"
    assert decision.force_new_instance is False


def test_registry_tab_and_media_singleton():
    with tempfile.TemporaryDirectory() as tmp:
        registry = BrowserSessionRegistry(base_data_dir=tmp)
        i1 = registry.register_instance(
            owner_session_id="sess-media",
            work_id="w1",
            intent_class="controlar_midia",
            debug_port=9001,
            cdp_ws_url="ws://x/1",
        )
        i2 = registry.register_instance(
            owner_session_id="sess-media",
            work_id="w2",
            intent_class="controlar_midia",
            debug_port=9002,
            cdp_ws_url="ws://x/2",
        )
        tab = registry.register_tab(
            instance_id=i2,
            target_id="target-2",
            url="https://youtube.com",
            title="YouTube",
            role="media",
        )
        assert tab is not None
        assert registry.get_tab(i2, tab) is not None

        closed = registry.close_other_media_instances("sess-media", keep_instance_id=i2)
        assert closed == 1
        details = registry.close_other_media_instances_detailed("sess-media", keep_instance_id=i2)
        assert isinstance(details, dict)
        assert "instances" in details

        by_id = {row["instance_id"]: row for row in registry.list_instances()}
        assert by_id[i1]["status"] == "closed"
        assert by_id[i2]["status"] == "active"


def test_run_goal_emits_execution_context_and_touches_work_context():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-a"
        capability._runtime_intent_class = "realizar_pesquisa"

        async def _fake_apply_session_policy(**kwargs):
            _ = kwargs
            return {
                "route": "reuse_tab",
                "reason": "same_session_reuse",
                "use_app_mode": False,
                "force_new_instance": False,
                "launch_url": "https://example.com",
            }

        capability._apply_session_policy = _fake_apply_session_policy  # type: ignore[method-assign]
        capability._is_browser_launch_authorized = lambda _ctx: True  # type: ignore[method-assign]

        touched = []

        def _touch(work_id, patch):
            touched.append((work_id, patch))

        async def _run():
            return await capability.run_goal(
                goal="abrir example",
                intent_class="realizar_pesquisa",
                context={
                    "session_id": "sess-a",
                    "work_id": "work-123",
                    "touch_work_context": _touch,
                    "callbacks": {"send_status": lambda phase, payload=None: None},
                },
            )

        result = asyncio.run(_run())
        assert result.get("ok") is True
        exec_ctx = result.get("execution_context") or {}
        assert str(exec_ctx.get("browser_instance_id", "")).startswith("chrome_")
        assert str(exec_ctx.get("tab_id", "")).startswith("tab_")
        assert exec_ctx.get("debug_port") == 9555
        assert exec_ctx.get("cdp_target_id") == "target-abc"
        assert isinstance(exec_ctx.get("last_vision_observation"), dict)
        assert (exec_ctx.get("last_vision_observation") or {}).get("schema") == "browser_control.vision.v1"
        assert isinstance(exec_ctx.get("policy_decision"), dict)
        snap = result.get("registry_snapshot") or {}
        assert snap.get("count_instances", 0) >= 1
        assert snap.get("count_tabs", 0) >= 1
        assert touched and touched[-1][0] == "work-123"


def test_run_goal_with_policy_and_registry_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(
            kernel,
            {
                "policy_enabled": False,
                "registry_enabled": False,
                "media_singleton_enforced": False,
                "app_mode_enabled": False,
            },
        )
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-disabled"
        capability._runtime_intent_class = "realizar_pesquisa"
        capability._is_browser_launch_authorized = lambda _ctx: True  # type: ignore[method-assign]
        
        async def _noop_ensure_runtime(**kwargs):
            _ = kwargs
            return None
        capability._ensure_runtime = _noop_ensure_runtime  # type: ignore[method-assign]

        async def _run():
            return await capability.run_goal(
                goal="abrir example",
                intent_class="realizar_pesquisa",
                context={
                    "session_id": "sess-disabled",
                    "work_id": "work-disabled",
                    "callbacks": {"send_status": lambda phase, payload=None: None},
                },
            )

        result = asyncio.run(_run())
        assert result.get("ok") is True
        exec_ctx = result.get("execution_context") or {}
        assert exec_ctx.get("browser_instance_id") == ""
        assert exec_ctx.get("tab_id") == ""
        assert exec_ctx.get("policy_decision", {}).get("route") == "policy_disabled"


def test_media_singleton_flag_disabled_omits_media_counter():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(
            kernel,
            {
                "media_singleton_enforced": False,
                "policy_enabled": True,
                "registry_enabled": True,
            },
        )
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-media-off"
        capability._runtime_intent_class = "controlar_midia"

        async def _fake_apply_session_policy(**kwargs):
            _ = kwargs
            return {
                "route": "reuse_tab",
                "reason": "same_session_reuse",
                "use_app_mode": False,
                "force_new_instance": False,
                "launch_url": "https://example.com",
            }

        capability._apply_session_policy = _fake_apply_session_policy  # type: ignore[method-assign]

        async def _run():
            return await capability.run_goal(
                goal="tocar musica",
                intent_class="controlar_midia",
                context={
                    "session_id": "sess-media-off",
                    "work_id": "work-media-off",
                    "callbacks": {"send_status": lambda phase, payload=None: None},
                },
            )

        result = asyncio.run(_run())
        exec_ctx = result.get("execution_context") or {}
        pd = exec_ctx.get("policy_decision") or {}
        assert "media_singleton_closed" not in pd


def test_step_continues_active_runtime_and_returns_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-step"
        capability._runtime_intent_class = "realizar_pesquisa"

        touched = []

        def _touch(work_id, patch):
            touched.append((work_id, patch))

        async def _run():
            await capability._ensure_registry_instance({"session_id": "sess-step", "work_id": "work-step"}, "realizar_pesquisa")
            await capability._sync_registry_tab()
            return await capability.step(
                "clique no botão",
                context={
                    "session_id": "sess-step",
                    "work_id": "work-step",
                    "touch_work_context": _touch,
                    "callbacks": {"send_status": lambda phase, payload=None: None},
                },
            )

        result = asyncio.run(_run())
        assert result.get("ok") is True
        metadata = result.get("metadata") or {}
        assert isinstance(metadata.get("registry_gc"), dict)
        continuation = metadata.get("continuation") or {}
        assert isinstance(continuation, dict)
        assert "reattach_to_tab" in continuation
        exec_ctx = result.get("execution_context") or {}
        assert exec_ctx.get("cdp_target_id") == "target-abc"
        assert (exec_ctx.get("policy_decision") or {}).get("route") == "step_continue"
        assert isinstance(exec_ctx.get("last_vision_observation"), dict)
        snap = result.get("registry_snapshot") or {}
        assert snap.get("count_instances", 0) >= 1
        assert touched and touched[-1][0] == "work-step"


def test_step_recovery_when_primary_attach_fails():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        capability._runtime = _FakeRuntimeRecover()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-step-recover"
        capability._runtime_intent_class = "realizar_pesquisa"

        async def _run():
            await capability._ensure_registry_instance({"session_id": "sess-step-recover", "work_id": "work-step-recover"}, "realizar_pesquisa")
            await capability._sync_registry_tab()
            return await capability.step(
                "pule o anuncio",
                context={"session_id": "sess-step-recover", "work_id": "work-step-recover"},
            )

        result = asyncio.run(_run())
        assert result.get("ok") is True
        exec_ctx = result.get("execution_context") or {}
        pd = exec_ctx.get("policy_decision") or {}
        tr = pd.get("target_recovery") or {}
        assert tr.get("ok") is True
        assert tr.get("strategy") == "attach_to_any_page"
        assert exec_ctx.get("cdp_target_id") == "target-recovered"


def test_close_instance_blocks_cross_work_without_force():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        instance_id = kernel.browser_session_registry.register_instance(
            owner_session_id="sess-owner",
            work_id="work-owner",
            intent_class="realizar_pesquisa",
            debug_port=9001,
            cdp_ws_url="ws://x/1",
        )
        result = asyncio.run(
            capability.close_instance(
                instance_id=instance_id,
                context={"session_id": "sess-owner", "work_id": "work-other"},
                force=False,
            )
        )
        assert result.get("ok") is False
        assert "another work" in str(result.get("error", "")).lower()


def test_close_tab_allows_force_override():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        instance_id = kernel.browser_session_registry.register_instance(
            owner_session_id="sess-owner",
            work_id="work-owner",
            intent_class="realizar_pesquisa",
            debug_port=9001,
            cdp_ws_url="ws://x/1",
        )
        tab_id = kernel.browser_session_registry.register_tab(
            instance_id=instance_id,
            target_id="target-1",
            url="https://example.com",
            title="Example",
            role="generic",
        )
        assert tab_id
        blocked = asyncio.run(
            capability.close_tab(
                tab_id=tab_id,
                context={"session_id": "sess-owner", "work_id": "work-other"},
                force=False,
            )
        )
        assert blocked.get("ok") is False
        forced = asyncio.run(
            capability.close_tab(
                tab_id=tab_id,
                context={"session_id": "sess-owner", "work_id": "work-other"},
                force=True,
            )
        )
        assert forced.get("ok") is True


def test_registry_instance_lock_acquire_conflict_and_release():
    with tempfile.TemporaryDirectory() as tmp:
        registry = BrowserSessionRegistry(base_data_dir=tmp)
        instance_id = registry.register_instance(
            owner_session_id="sess-1",
            work_id="work-1",
            intent_class="realizar_pesquisa",
            debug_port=9555,
            cdp_ws_url="ws://localhost:9555/devtools/page/a",
        )
        a1 = registry.acquire_instance_lock(
            instance_id,
            owner_session_id="sess-1",
            work_id="work-1",
            lease_seconds=120,
        )
        assert a1.get("ok") is True

        a2 = registry.acquire_instance_lock(
            instance_id,
            owner_session_id="sess-1",
            work_id="work-2",
            lease_seconds=120,
        )
        assert a2.get("ok") is False
        assert a2.get("reason") == "locked_by_other_work"

        r1 = registry.release_instance_lock(
            instance_id,
            owner_session_id="sess-1",
            work_id="work-1",
            force=False,
        )
        assert r1.get("ok") is True

        a3 = registry.acquire_instance_lock(
            instance_id,
            owner_session_id="sess-1",
            work_id="work-2",
            lease_seconds=120,
        )
        assert a3.get("ok") is True


def test_step_denied_when_instance_locked_by_other_work():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-lock"
        capability._runtime_intent_class = "realizar_pesquisa"

        async def _run():
            await capability._ensure_registry_instance({"session_id": "sess-lock", "work_id": "work-a"}, "realizar_pesquisa")
            await capability._sync_registry_tab()
            assert capability._browser_instance_id
            reg = kernel.browser_session_registry
            lock = reg.acquire_instance_lock(
                capability._browser_instance_id,
                owner_session_id="sess-lock",
                work_id="work-b",
                lease_seconds=120,
            )
            assert lock.get("ok") is True
            return await capability.step(
                "clique no botao",
                context={"session_id": "sess-lock", "work_id": "work-a"},
            )

        result = asyncio.run(_run())
        assert result.get("ok") is False
        assert "locked_by_other_work" in str(result.get("error", ""))
        assert isinstance((result.get("metadata") or {}).get("registry_gc"), dict)
        assert isinstance(((result.get("metadata") or {}).get("continuation") or {}), dict)


def test_registry_tab_lock_acquire_conflict_and_release():
    with tempfile.TemporaryDirectory() as tmp:
        registry = BrowserSessionRegistry(base_data_dir=tmp)
        instance_id = registry.register_instance(
            owner_session_id="sess-1",
            work_id="work-1",
            intent_class="realizar_pesquisa",
            debug_port=9555,
            cdp_ws_url="ws://localhost:9555/devtools/page/a",
        )
        tab_id = registry.register_tab(
            instance_id=instance_id,
            target_id="target-1",
            url="https://example.com",
            title="Example",
            role="generic",
        )
        assert tab_id
        a1 = registry.acquire_tab_lock(
            instance_id,
            tab_id,
            owner_session_id="sess-1",
            work_id="work-1",
            lease_seconds=120,
        )
        assert a1.get("ok") is True
        a2 = registry.acquire_tab_lock(
            instance_id,
            tab_id,
            owner_session_id="sess-1",
            work_id="work-2",
            lease_seconds=120,
        )
        assert a2.get("ok") is False
        assert a2.get("reason") == "tab_locked_by_other_work"
        r1 = registry.release_tab_lock(
            instance_id,
            tab_id,
            owner_session_id="sess-1",
            work_id="work-1",
            force=False,
        )
        assert r1.get("ok") is True
        a3 = registry.acquire_tab_lock(
            instance_id,
            tab_id,
            owner_session_id="sess-1",
            work_id="work-2",
            lease_seconds=120,
        )
        assert a3.get("ok") is True


def test_step_denied_when_tab_locked_by_other_work():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-tab-lock"
        capability._runtime_intent_class = "realizar_pesquisa"

        async def _run():
            await capability._ensure_registry_instance({"session_id": "sess-tab-lock", "work_id": "work-a"}, "realizar_pesquisa")
            await capability._sync_registry_tab()
            assert capability._browser_instance_id and capability._tab_id
            reg = kernel.browser_session_registry
            lock = reg.acquire_tab_lock(
                capability._browser_instance_id,
                capability._tab_id,
                owner_session_id="sess-tab-lock",
                work_id="work-b",
                lease_seconds=120,
            )
            assert lock.get("ok") is True
            return await capability.step(
                "clique no botao",
                context={"session_id": "sess-tab-lock", "work_id": "work-a"},
            )

        result = asyncio.run(_run())
        assert result.get("ok") is False
        assert "tab_locked_by_other_work" in str(result.get("error", ""))


def test_registry_cleanup_expired_locks_and_close_idle_instances():
    with tempfile.TemporaryDirectory() as tmp:
        registry = BrowserSessionRegistry(base_data_dir=tmp)
        instance_id = registry.register_instance(
            owner_session_id="sess-gc",
            work_id="work-gc",
            intent_class="realizar_pesquisa",
            debug_port=9555,
            cdp_ws_url="ws://localhost:9555/devtools/page/a",
        )
        tab_id = registry.register_tab(
            instance_id=instance_id,
            target_id="target-gc",
            url="https://example.com",
            title="Example",
            role="generic",
        )
        assert tab_id

        i_lock = registry.acquire_instance_lock(
            instance_id,
            owner_session_id="sess-gc",
            work_id="work-gc",
            lease_seconds=120,
        )
        t_lock = registry.acquire_tab_lock(
            instance_id,
            tab_id,
            owner_session_id="sess-gc",
            work_id="work-gc",
            lease_seconds=120,
        )
        assert i_lock.get("ok") is True and t_lock.get("ok") is True

        # Force lock expiry and run cleanup.
        registry._state["instances"][instance_id]["lock"]["expires_at"] = 1
        registry._state["instances"][instance_id]["tabs"][tab_id]["lock"]["expires_at"] = 1
        cleaned = registry.cleanup_expired_locks()
        assert cleaned.get("expired_instance_locks", 0) >= 1
        assert cleaned.get("expired_tab_locks", 0) >= 1

        # Make instance idle and old enough for GC close.
        registry.update_instance(
            instance_id,
            in_use=False,
            last_heartbeat_at="2000-01-01T00:00:00+00:00",
            status="active",
        )
        closed = registry.close_idle_instances(idle_seconds=60, keep_instance_ids=[])
        assert closed.get("closed_instances", 0) >= 1
        inst = registry.get_instance(instance_id) or {}
        assert str(inst.get("status", "")).lower() == "closed"


def test_inspect_can_include_last_vision():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-inspect"
        capability._runtime_intent_class = "realizar_pesquisa"

        async def _run():
            await capability._ensure_registry_instance({"session_id": "sess-inspect", "work_id": "work-inspect"}, "realizar_pesquisa")
            await capability._sync_registry_tab()
            return await capability.inspect(
                params={"only_current_session": True, "include_tabs": True, "include_last_vision": True},
                context={"session_id": "sess-inspect"},
            )

        result = asyncio.run(_run())
        assert result.get("ok") is True
        current = result.get("current_execution") or {}
        assert isinstance(current.get("last_vision_observation"), dict)
        assert (current.get("last_vision_observation") or {}).get("schema") == "browser_control.vision.v1"


def test_sync_registry_includes_last_vision():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-sync"
        capability._runtime_intent_class = "realizar_pesquisa"

        async def _run():
            return await capability.sync_registry(context={"session_id": "sess-sync", "work_id": "work-sync"})

        result = asyncio.run(_run())
        assert result.get("ok") is True
        assert isinstance(result.get("last_vision_observation"), dict)
        assert (result.get("last_vision_observation") or {}).get("schema") == "browser_control.vision.v1"


def test_gc_action_closes_idle_instances_on_demand():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(
            kernel,
            {
                "registry_enabled": True,
                "registry_gc_enabled": False,  # explicit action should still run
            },
        )
        instance_id = kernel.browser_session_registry.register_instance(
            owner_session_id="sess-gc-action",
            work_id="work-gc-action",
            intent_class="realizar_pesquisa",
            debug_port=9555,
            cdp_ws_url="ws://localhost:9555/devtools/page/gc",
        )
        kernel.browser_session_registry.update_instance(
            instance_id,
            in_use=False,
            status="active",
            last_heartbeat_at="2000-01-01T00:00:00+00:00",
        )

        async def _run():
            return await capability.gc(
                params={"idle_seconds": 60, "keep_current_instance": False},
                context={"session_id": "sess-gc-action", "work_id": "work-gc-action"},
            )

        result = asyncio.run(_run())
        assert result.get("ok") is True
        gc = result.get("gc") or {}
        assert ((gc.get("closed_idle") or {}).get("closed_instances", 0)) >= 1
        inst = kernel.browser_session_registry.get_instance(instance_id) or {}
        assert str(inst.get("status", "")).lower() == "closed"


def test_health_action_returns_consolidated_diagnostics():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        capability = BrowserControlCapability(kernel, {})
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-health"
        capability._runtime_intent_class = "realizar_pesquisa"

        async def _run():
            await capability._ensure_registry_instance({"session_id": "sess-health", "work_id": "work-health"}, "realizar_pesquisa")
            await capability._sync_registry_tab()
            return await capability.health(
                params={"run_gc": False, "only_current_session": True},
                context={"session_id": "sess-health", "work_id": "work-health"},
            )

        result = asyncio.run(_run())
        assert result.get("ok") is True
        health = result.get("health") or {}
        assert health.get("status") in {"ok", "degraded"}
        assert isinstance(result.get("inspect"), dict)
        assert isinstance(result.get("sync"), dict)
        assert isinstance(result.get("registry_snapshot"), dict)


def test_run_goal_does_not_emit_media_singleton_cleanup_status():
    with tempfile.TemporaryDirectory() as tmp:
        kernel = _FakeKernel(tmp)
        # Existing media instance to be replaced by singleton policy.
        kernel.browser_session_registry.register_instance(
            owner_session_id="sess-media-status",
            work_id="work-old",
            intent_class="controlar_midia",
            debug_port=9111,
            cdp_ws_url="ws://x/old",
        )
        capability = BrowserControlCapability(kernel, {})
        capability._runtime = _FakeRuntime()
        capability._subagent = _FakeSubagent()
        capability._owner_session_id = "sess-media-status"
        capability._runtime_intent_class = "controlar_midia"

        async def _fake_apply_session_policy(**kwargs):
            _ = kwargs
            return {
                "route": "reuse_tab",
                "reason": "same_session_reuse",
                "use_app_mode": True,
                "force_new_instance": False,
                "launch_url": "https://www.youtube.com",
            }

        async def _fail_if_called(*args, **kwargs):
            _ = (args, kwargs)
            raise AssertionError("automatic media cleanup should not be triggered")

        capability._apply_session_policy = _fake_apply_session_policy  # type: ignore[method-assign]
        capability._close_replaced_media_instances = _fail_if_called  # type: ignore[method-assign]
        capability._is_browser_launch_authorized = lambda _ctx: True  # type: ignore[method-assign]

        statuses = []

        def _send_status(phase, payload=None):
            statuses.append((phase, payload or {}))

        async def _run():
            return await capability.run_goal(
                goal="tocar musica",
                intent_class="controlar_midia",
                context={
                    "session_id": "sess-media-status",
                    "work_id": "work-new",
                    "callbacks": {"send_status": _send_status},
                },
            )

        result = asyncio.run(_run())
        assert result.get("ok") is True
        metadata = result.get("metadata") or {}
        assert "media_singleton_cleanup" not in metadata
        found = [p for _, p in statuses if str((p or {}).get("code", "")) == "media_singleton_cleanup_disabled"]
        assert found
        cleanup = found[-1].get("media_cleanup") or {}
        assert cleanup.get("enabled") is False
        assert cleanup.get("reason") == "automatic_media_close_disabled"
        instances = kernel.browser_session_registry.list_instances()
        old_instances = [inst for inst in instances if int(inst.get("debug_port", 0) or 0) == 9111]
        assert old_instances
        assert str(old_instances[0].get("status", "")).lower() == "active"
        assert not any(str(inst.get("status", "")).lower() == "closed" for inst in instances)
