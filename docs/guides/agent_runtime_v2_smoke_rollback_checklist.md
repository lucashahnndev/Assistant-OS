# Agent Runtime V2 Smoke + Rollback Checklist

## Scope
- validate controlled activation of `runtime.agent_runtime_v2_enabled=true`
- confirm governance path works, including policy, gates, receipts and observability
- keep rollback under one config change

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
- receipt present with `engine=agent_runtime_v2`
- `tenant_id`, `qos_class`, `risk_level`, `policy_version` filled in receipt
- no unexpected `POLICY_DENIED` or `RUNTIME_RATE_LIMITED` errors in smoke path
- observability event written in `data/runtime_v2/governance_events.jsonl`

## Rollback (Fast Path)
1. Set `runtime.agent_runtime_v2_enabled=false`
2. Restart service or process
3. Re-run one control action and confirm metadata shows `runtime_v2_enabled=false`

## Incident Notes
- If observability fails, execution should continue as non-fatal telemetry.
- If rollout policy causes regressions, use the PolicyRollout rollback API or flow before a global disable.

## Relacionados

- [../overview.md](../overview.md): indice geral da documentacao humana.
- [../architecture/README.md](../architecture/README.md): contexto tecnico do runtime v2.
- [../policies/README.md](../policies/README.md): regras de governanca e rollback.
- [../reports/README.md](../reports/README.md): evidencias de smoke e observabilidade.
- [../../agent/specs/system_architecture.spec.md](../../agent/specs/system_architecture.spec.md): contrato arquitetural do sistema afetado.
