# Browser Control Playwright MCP Rollout Guide (2026-03-20)

## Objective
Enable `browser_control` with `runtime_backend=playwright` and `playwright_transport_mode=mcp` with safe rollback.

## Required Config
Set in `config.json` under `capabilities.browser_control`:

```json
{
  "runtime_backend": "playwright",
  "playwright_transport_mode": "mcp",
  "playwright_mcp_endpoint": "http://127.0.0.1:8787",
  "playwright_mcp_fallback_to_local": true,
  "max_new_tabs_per_session": 3
}
```

Notes:
- Keep `playwright_mcp_fallback_to_local=true` during first rollout.
- If you want strict fail-fast (no local fallback), set `false` only after endpoint validation.
- Keep `max_new_tabs_per_session` low in production to prevent runaway tab storms.

## Smoke Flow
1. Start service with the config above.
2. Run preflight before first traffic:

```bash
./env/bin/python scripts/browser_control_mcp_preflight.py --config-file data/config.json check-config
```

If the output has `browser_control.ready=false`, fix config before continuing.
For CI gate (strict mode), use:

```bash
./env/bin/python scripts/browser_control_mcp_preflight.py --config-file data/config.json check-config --require-ready --fail-on-warnings
```
3. Trigger a simple browser action (`browser.control.run` with a basic navigation goal).
4. Validate `inspect` output:
   - `current_execution.runtime_backend=playwright`
   - `current_execution.runtime_connection.transport_mode_configured=mcp`
   - `current_execution.runtime_connection.transport_mode_effective=mcp` (or `local` if fallback happened)
5. Validate `sync_registry` output:
   - `runtime_backend=playwright`
   - `runtime_target_id` present
   - `mcp_calls_total > 0` after a few actions
6. Validate `health`:
   - no `no_active_runtime_target` issue

Optional full smoke runner (preflight + probe + run + inspect/sync/health):

```bash
./env/bin/python scripts/browser_control_mcp_smoke.py \
  --config-file data/config.json \
  --goal "Abra https://example.com e valide o título da página." \
  --intent-class automacao_ui \
  --require-ready
```

CI gate (fails pipeline if checks are not met):

```bash
./env/bin/python scripts/browser_control_mcp_ci_gate.py \
  --config-file data/config.json \
  --goal "Abra https://example.com e valide o título da página." \
  --intent-class automacao_ui \
  --require-ready \
  --min-mcp-calls 1 \
  --markdown-report-file data/reports/browser_control_mcp_ci_gate.md \
  --json-report-file data/reports/browser_control_mcp_ci_gate.json
```

For compact CI logs, add `--summary-only` (keeps full artifacts in files):

```bash
./env/bin/python scripts/browser_control_mcp_ci_gate.py --config-file data/config.json --summary-only --json-report-file data/reports/browser_control_mcp_ci_gate.json
```

## Fallback and Rollback
- Immediate fallback (same deploy):
  - Keep `runtime_backend=playwright`
  - Set `playwright_transport_mode=local`
- Full rollback to CDP is no longer supported in runtime migration mode.

## Operational Signals
- If MCP endpoint is missing and fallback is enabled:
  - runtime logs warning and uses local transport
- If endpoint is missing and fallback is disabled:
  - runtime fails fast on launch (intended)

## Minimum Acceptance
- Browser action succeeds on Playwright runtime
- `inspect`/`health` clearly show active transport mode
- No infinite loop on repeated unchanged state
