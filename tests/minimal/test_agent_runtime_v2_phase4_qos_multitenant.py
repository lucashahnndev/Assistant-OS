import sys
from pathlib import Path
import os
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from src.core.orchestrator import AgentOrchestrator
from src.core.scheduler import Scheduler
from src.services.agent_runtime_v2 import GlobalScheduler, RuntimeCostBudget, RuntimeRateLimiter
import queue


def test_global_scheduler_fairness_across_tenants():
    scheduler = GlobalScheduler()
    jobs = [
        {"tenant_id": "tenant-a", "agent_id": "a1", "qos_class": "HIGH", "waiting_ms": 50, "id": "a1"},
        {"tenant_id": "tenant-a", "agent_id": "a2", "qos_class": "HIGH", "waiting_ms": 40, "id": "a2"},
        {"tenant_id": "tenant-b", "agent_id": "b1", "qos_class": "NORMAL", "waiting_ms": 60, "id": "b1"},
    ]
    selected = scheduler.select_fair(jobs, slots=2)
    assert len(selected) == 2
    tenants = {row.get("tenant_id") for row in selected}
    assert "tenant-a" in tenants and "tenant-b" in tenants


def test_rate_limiter_enforces_parallel_per_agent():
    limiter = RuntimeRateLimiter()
    cfg = {
        "window_seconds": 60,
        "max_actions_per_minute_per_agent": 100,
        "max_actions_per_minute_per_tenant": 100,
        "max_parallel_actions_per_agent": 1,
    }
    first = limiter.acquire(tenant_id="tenant-a", agent_id="agent-a", cfg=cfg)
    second = limiter.acquire(tenant_id="tenant-a", agent_id="agent-a", cfg=cfg)
    assert first["allowed"] is True
    assert second["allowed"] is False
    limiter.release(first.get("lease"))
    third = limiter.acquire(tenant_id="tenant-a", agent_id="agent-a", cfg=cfg)
    assert third["allowed"] is True


def test_cost_budget_enforces_max_actions_per_goal():
    budget = RuntimeCostBudget()
    cfg = {
        "max_actions_per_goal": 2,
        "max_mcp_calls_per_step": 10,
        "max_actions_per_tenant_window": 10,
    }
    r1 = budget.consume(tenant_id="tenant-a", work_id="work-1", cfg=cfg, action_units=1)
    r2 = budget.consume(tenant_id="tenant-a", work_id="work-1", cfg=cfg, action_units=1)
    r3 = budget.consume(tenant_id="tenant-a", work_id="work-1", cfg=cfg, action_units=1)
    assert r1["allowed"] is True
    assert r2["allowed"] is True
    assert r3["allowed"] is False


def test_orchestrator_operational_gate_blocks_rate_limit():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._runtime_v2_rate_limiter = RuntimeRateLimiter()
    orchestrator._runtime_v2_cost_budget = RuntimeCostBudget()
    orchestrator.config_manager = type(
        "_Cfg",
        (),
        {
            "get": staticmethod(
                lambda key, default=None: {
                    "agent_runtime_v2": {
                        "governance": {
                            "rate_limit": {
                                "max_actions_per_minute_per_agent": 100,
                                "max_actions_per_minute_per_tenant": 100,
                                "max_parallel_actions_per_agent": 1,
                            },
                            "cost_budget": {
                                "max_actions_per_goal": 100,
                                "max_mcp_calls_per_step": 10,
                                "max_actions_per_tenant_window": 100,
                            },
                        }
                    }
                }
                if key == "runtime"
                else default
            )
        },
    )()

    exec_context = {
        "execution_context_envelope": {
            "tenant_id": "tenant-a",
            "agent_id": "agent-a",
        },
        "runtime_v2_governance": {
            "tenant_governance": {"allowed": True, "mode": "log_only"}
        },
    }

    first = orchestrator._apply_runtime_v2_operational_gate(exec_context=exec_context, work_id="work-1")
    assert first is None
    # Keep lease to force parallel contention.
    second = orchestrator._apply_runtime_v2_operational_gate(exec_context=exec_context, work_id="work-1")
    assert isinstance(second, dict)
    assert second.get("error_code") == "RUNTIME_RATE_LIMITED"
    orchestrator._release_runtime_v2_operational_leases(exec_context)


def test_scheduler_list_works_fair_balances_tenants():
    previous = os.environ.get("AOSD_DATA_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["AOSD_DATA_DIR"] = tmp
            scheduler = Scheduler(queue.Queue())
            w1 = scheduler.create_work(session_id="s-a", input_text="a", initial_context={"data": {"runtime_v2": {"last_receipt": {"tenant_id": "tenant-a", "qos_class": "HIGH"}}}})
            w2 = scheduler.create_work(session_id="s-a2", input_text="a2", initial_context={"data": {"runtime_v2": {"last_receipt": {"tenant_id": "tenant-a", "qos_class": "HIGH"}}}})
            w3 = scheduler.create_work(session_id="s-b", input_text="b", initial_context={"data": {"runtime_v2": {"last_receipt": {"tenant_id": "tenant-b", "qos_class": "NORMAL"}}}})
            _ = (w1, w2, w3)
            selected = scheduler.list_works_fair(slots=2, include_completed=False)
            tenants = {
                str((((row.get("context") or {}).get("data") or {}).get("runtime_v2") or {}).get("last_receipt", {}).get("tenant_id", "default"))
                for row in selected
            }
            assert "tenant-a" in tenants and "tenant-b" in tenants
    finally:
        if previous is None:
            os.environ.pop("AOSD_DATA_DIR", None)
        else:
            os.environ["AOSD_DATA_DIR"] = previous
