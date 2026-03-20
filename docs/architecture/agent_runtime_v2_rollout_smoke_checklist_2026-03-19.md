# Agent Runtime V2 Smoke + Rollback Checklist

## Scope
- Validate controlled activation of `runtime.agent_runtime_v2_enabled=true`
- Confirm governance path works (policy, gates, receipts, observability)
- Keep rollback under 1 config change

## Pre-check
1. Confirm clean baseline:
   - `PYTHONPATH=src:. env/bin/python -m pytest -q tests/minimal/test_agent_runtime_v2_phase0.py tests/minimal/test_agent_runtime_v2_governance_phase1.py tests/minimal/test_agent_runtime_v2_phase2_contracts.py tests/minimal/test_agent_runtime_v2_phase3_policy_decision.py tests/minimal/test_agent_runtime_v2_phase4_qos_multitenant.py tests/minimal/test_agent_runtime_v2_phase5_sandbox.py tests/minimal/test_agent_runtime_v2_phase6_policy_simulation.py tests/minimal/test_agent_runtime_v2_phase7_policy_rollout.py tests/minimal/test_agent_runtime_v2_phase8_observability.py tests/minimal/test_agent_runtime_v2_phase9_operational_smoke.py`
2. Ensure no pending migration changes in production config.

## Controlled Activation
1. Set in config:
   - `runtime.agent_runtime_v2_enabled=true`
   - `runtime.agent_runtime_v2.policy_mode=log_only` for first activation
2. Keep `runtime.agent_runtime_v2.observability.enabled=true`
3. Execute one controlled action flow for a non-critical tenant.

## Smoke Acceptance
- Receipt present with `engine=agent_runtime_v2`
- `tenant_id`, `qos_class`, `risk_level`, `policy_version` filled in receipt
- No `POLICY_DENIED`/`RUNTIME_RATE_LIMITED` unexpected errors in smoke path
- Observability event written in `data/runtime_v2/governance_events.jsonl`

## Rollback (Fast Path)
1. Set `runtime.agent_runtime_v2_enabled=false`
2. Restart service/process
3. Re-run one control action and confirm metadata shows `runtime_v2_enabled=false`

## Incident Notes
- If observability fails, execution should continue (non-fatal telemetry).
- If rollout policy causes regressions, use PolicyRollout rollback API/flow before global disable.
