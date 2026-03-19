# Capability System Audit and Standardization Plan (2026-03-12)

## 1. Executive Summary

The current capability system is functional but contract governance is inconsistent and partially broken at runtime integration points.

High-impact findings:

1. Registry action resolution is broken by recursive self-call in `CapabilityRegistry.get_capability_for_action` (`src/capabilities/registry.py:79-84`).
2. Validator schema extraction only supports `params`, while many contracts use `parameters` (`src/core/plan_validator.py:76-85`).
3. Contract shape is mixed (`actions` as `dict` vs `list`; `params` vs `parameters`).
4. Risk metadata is incomplete in many capabilities, forcing heuristic fallbacks in ACL/UI/safety flows.
5. Capability package artifacts are inconsistent (missing `version`, uneven `README`, `manifest`, `config.schema`).

The system is ready for standardization if a compatibility layer is introduced first, then runtime alignment, then contract migration.

---

## 2. Capability System Overview

### Runtime loading and registration

- Loader discovers folder-based modules and imports `create_capability` (`src/capabilities/loader.py:78-89`).
- If `contract.json` exists, loader injects it into `_contract` and sets `_namespace` from `contract.name` (`src/capabilities/loader.py:102-131`).
- Registry registers `capability.actions`, prepending namespace when needed (`src/capabilities/registry.py:62-77`).

### Dispatch and validation path

- Planner emits `ActionPlan` (`action_id`, `args`), validator checks existence and schema.
- Orchestrator executes through registry and applies ACL and safety checks.
- Safety/HITL approval is enforced for sensitive operations (`src/core/orchestrator.py:2539-2689`, `src/services/safety_service.py:61-131`).

### Prompt exposure path

- Prompt receives capabilities through `capabilities_summary` and `capability_scope` (`src/core/orchestrator.py:5004-5053`).
- Catalog generation modes: `full`, `on_demand`, `compact_*` with `ac.v2` payloads (`src/core/orchestrator.py:5130-5214`).
- Prompt budget clips capability payload (`src/services/llm/prompt_composer.py:81-90`, `:266-270`).

---

## 3. Capability Package Structure

Capability directories analyzed under `src/capabilities/*`.

Observed package artifact pattern:

- Common: `__init__.py`, `contract.json`, runtime module (`capability.py` or equivalent).
- Optional and inconsistent: `config.schema.json`, `README.md`, `manifest.json`, support assets.
- Special case: `browser_control` runtime file is `browser_control_capability.py` (no `capability.py`).

Notable non-capability folders present in same root:

- `src/capabilities/index` (docs/manifest index artifact).
- `src/capabilities/__pycache__`.

---

## 4. Capability Contract Audit

### 4.1 Contract format split

- `actions` as **dict + params** (legacy-style custom schema):
  - `assistive_overlay`, `browser_control`, `data_analysis`, `deezer_search`, `maps_search`, `research_retrieve`, `spotify_search`, `vision`, `weather_control`, `web_retrieve`, `web_search`, `wikipedia_search`, `youtube_retrieve`, `youtube_search`.
- `actions` as **list + parameters** (JSON-Schema-like):
  - `deep_memory`, `memory_management`, `reflex_skill`, `shell_control`, `system_apps`, `system_control`, `system_logs`, `task_management`.

### 4.2 Missing core metadata

- Missing `version`: `assistive_overlay`, `deep_memory`, `memory_management`, `reflex_skill`, `shell_control`, `system_apps`, `system_control`, `task_management`, `vision`.
- Missing/partial `risk_level` in many action entries (especially list/parameters contracts).

### 4.3 Per-capability contract matrix

| Capability | Action IDs | Parameter Schema Format | Fields Missing | Schema/Risk Notes |
|---|---|---|---|---|
| assistive_overlay | `overlay.assist.*` (10) | `actions: dict`, `params` | `version` | consistent low risk |
| browser_control | `browser.control.*` (9) | `actions: dict`, `params` | none | low/medium risk complete |
| data_analysis | `data.analysis.summarize` | dict + `params` | none | complete |
| deep_memory | `deep.memory.recall_memory`, `deep.memory.store_memory` | list + `parameters` | `version` | risk missing on both actions |
| deezer_search | `deezer.search.search` | dict + `params` | none | risk missing |
| maps_search | `maps.search.search` | dict + `params` | none | risk missing |
| memory_management | `memory.recall`, `memory.store` | list + `parameters` | `version` | risk missing |
| reflex_skill | `reflex.status`, `reflex.cancel` | list + `parameters` | `version` | risk missing |
| research_retrieve | `research.retrieve.run` | dict + `params` | none | complete |
| shell_control | `shell.control.execute` | list + `parameters` | `version` | high risk present |
| spotify_search | `spotify.search.search` | dict + `params` | none | risk missing |
| system_apps | `system.apps.open/close/find` | list + `parameters` | `version` | risk missing |
| system_control | `system.control.*` (23) | list + `parameters` | `version` | many actions missing risk; some missing schema |
| system_logs | `system_logs.list/read` | list + `parameters` | none | namespace style inconsistent (`_`); `list` missing schema |
| task_management | `task.*` (8) | list + `parameters` | `version` | risk missing on all actions |
| vision | `vision.analyze/search_screen/locate_screen` | dict + `params` | `version` | risk missing |
| weather_control | `weather.control.get/forecast` | dict + `params` | none | complete |
| web_retrieve | `web.retrieve.read/extract` | dict + `params` | none | complete |
| web_search | `web.search.discover` | dict + `params` | none | complete |
| wikipedia_search | `wikipedia.search` | dict + `params` | none | complete |
| youtube_retrieve | `youtube.get` | dict + `params` | none | complete |
| youtube_search | `youtube.find` | dict + `params` | none | risk missing |

Concrete missing-schema examples:

- `system.control.info`, `system.control.time`, `system.control.network.status` have no `parameters` block in contract.
- `system_logs.list` has no parameter schema.

---

## 5. Action Schema Inconsistencies

### 5.1 `params` vs `parameters` mismatch

Validator reads only `params` (`src/core/plan_validator.py:79`, `:84`), so `parameters`-based contracts bypass schema validation.

Impact:

- `shell.control.execute`, `task.*`, `system.control.*`, `memory.*` actions are often not validated by contract schema before execution.

### 5.2 Action record shape mismatch

- Dict-form contracts key by local action name.
- List-form contracts rely on `id` and optional `name` matching.
- Registry metadata parser accepts both (`src/capabilities/registry.py:169-203`) but downstream consumers are inconsistent.

### 5.3 Runtime handler vs contract discipline gaps

- `shell_control` ignores `action_id` and executes any call if `command` is present (`src/capabilities/shell_control/capability.py:81-83`).
- `task_management` helper methods `_ok`/`_err` reference undefined variable `message`, causing runtime failure (`src/capabilities/task_management/capability.py:34-41`).
- `system_logs` returns duplicated keys (`error_details`) where earlier values are overwritten (`src/capabilities/system_logs/capability.py:74-75`, `:82-83`).

### 5.4 Naming/namespace inconsistency

- `system_logs.*` uses underscore namespace instead of dot-delimited convention used by most capabilities.

---

## 6. Registry and Runtime Integration

### 6.1 Critical registry defect

`CapabilityRegistry` defines `get_capability_for_action` twice; second method calls itself recursively:

- `src/capabilities/registry.py:79-84`

This breaks all callers (`dispatch`, validator, ACL metadata lookups) unless patched elsewhere.

### 6.2 Contract-to-registry assumptions

- Loader maps namespace from `contract.name` lowercased and spaces to dots (`src/capabilities/loader.py:130`), not from explicit canonical namespace field.
- This can generate unstable namespaces when display names change.

### 6.3 Validator/dispatch mismatch

- Validator expects schemas in legacy `params` while execution receives `plan.args` agnostic to source style.
- Runtime safety and ACL rely on `get_action_metadata`; if risk metadata is absent, they fallback to prefix heuristics.

---

## 7. Prompt Exposure and Token Impact

### 7.1 Exposure mechanism

- Orchestrator builds action payload (`_build_prompt_actions_block`) and injects it into prompt (`src/core/orchestrator.py:5004-5053`, `:5130-5214`).
- Prompt composer inserts `[AVAILABLE ACTIONS]` with scope + clipped payload (`src/services/llm/prompt_composer.py:266-270`).

### 7.2 Catalog modes

- `full`: full text summary of every discoverable action.
- `on_demand`: only discovery actions (`system.control.capabilities.list/describe` variants) + rules.
- `compact_*`: manifest hash, namespaces, full action list (`a`), and focus subset (`f`).

### 7.3 Token inflation risks

1. `full` mode scales linearly with action count and descriptions.
2. `compact_hybrid` still embeds full action list in payload field `a` (`src/core/orchestrator.py:5211`).
3. `capabilities_summary` budget is fixed at 2200 chars (`src/services/llm/prompt_composer.py:88`) and may truncate catalog mid-structure.
4. Inconsistent metadata quality reduces usefulness per token (many `No description available`, unknown risk).

---

## 8. ACL and Permission Integration

### 8.1 Principal and group context

- `PrincipalContext` is reconstructed from session and drives `get_allowed_actions` filtering (`src/core/orchestrator.py:5373+`, `src/core/access_controller.py:719-759`).
- Layered allow/deny rules are merged across group/user/entity.

### 8.2 Risk-based restrictions

- `pre_dispatch_gate` blocks high-risk actions for non-approved users and anyone-mode (`src/core/access_controller.py:693-715`).
- High-risk classification first checks contract metadata, then prefixes (`src/core/access_controller.py:853-874`).
- UI route also infers risk heuristically when metadata is missing (`src/server/routes/capabilities.py:86-117`).

### 8.3 HITL approval

- Safety service determines sensitivity (`src/services/safety_service.py:61-95`) and orchestrator pauses for approval (`src/core/orchestrator.py:2539-2689`).
- Since many contracts omit `risk_level`, sensitivity frequently depends on prefix lists and legacy aliases.

---

## 9. Contract Standardization Requirements

A standardized contract must enforce:

1. Single canonical schema shape (`actions` as object map or list, not both).
2. Single parameter schema field (`parameters`) aligned with JSON Schema.
3. Mandatory action metadata: `id`, `description`, `risk_level`, `permissions`, `handler`.
4. Mandatory capability metadata: `id`, `namespace`, `version`, `title`, `description`.
5. Deterministic namespace/action ID rules.
6. Explicit backward-compatibility fields under dedicated `legacy` section only.
7. Validation contract that matches runtime validator exactly.

---

## 10. Proposed Capability Contract v1

```json
{
  "$schema": "https://assistant-os.dev/schemas/capability-contract-v1.json",
  "contract_version": "1.0",
  "capability": {
    "id": "system_control",
    "namespace": "system.control",
    "version": "1.2.0",
    "title": "System Control",
    "description": "System operations and capability discovery",
    "owner": "core",
    "tags": ["system", "admin"],
    "visibility": "public"
  },
  "runtime": {
    "module": "capabilities.system_control.capability",
    "factory": "create_capability",
    "config_schema": "./config.schema.json"
  },
  "actions": [
    {
      "id": "system.control.process.kill",
      "title": "Kill process",
      "description": "Terminate a process by PID",
      "handler": "process.kill",
      "risk_level": "high",
      "side_effect": "destructive",
      "permissions": {
        "scopes": ["system:process:kill"],
        "allow_anyone": false,
        "requires_approval": true
      },
      "parameters": {
        "type": "object",
        "properties": {
          "pid": { "type": "integer", "minimum": 1 }
        },
        "required": ["pid"],
        "additionalProperties": false
      },
      "result_schema": {
        "type": "object"
      },
      "examples": [
        { "pid": 1234 }
      ]
    }
  ],
  "policy_hints": {
    "default_timeout_ms": 30000,
    "idempotency": "mixed"
  },
  "legacy": {
    "aliases": ["process_kill"],
    "deprecated_fields": ["params"],
    "sunset_at": "2026-09-30"
  }
}
```

### Namespace rules

- `capability.namespace`: lowercase dot-separated (`^[a-z][a-z0-9]*(\.[a-z0-9]+)+$`).
- `action.id`: must start with capability namespace and include operation segment.
- No underscores at namespace segment boundaries for new IDs.

---

## 11. Migration Plan for Existing Capabilities

### Phase 1: Contract normalization layer

Goal: keep runtime stable while introducing canonical read model.

1. Add `ContractNormalizer` in loader/registry pipeline.
2. Normalize both legacy shapes into canonical in-memory `CapabilityContractV1Model`.
3. Map `params -> parameters` automatically.
4. Derive missing `risk_level` temporarily via fallback and mark as `inferred=true`.
5. Emit structured warnings per capability/action.

Exit criteria:

- Every loaded capability yields normalized contract object.
- Diagnostics report produced at startup.

### Phase 2: Validator alignment

Goal: runtime validator and ACL read same canonical fields.

1. Update `PlanValidator` to consume normalized `parameters` (JSON Schema).
2. Remove direct reads of raw `_contract` legacy keys.
3. Update ACL/Safety/UI risk reads to canonical `risk_level` only; keep fallback behind feature flag.
4. Add regression tests for `params` and `parameters` compatibility via normalizer.

Exit criteria:

- Validation coverage includes all capabilities regardless of original contract style.

### Phase 3: Capability contract refactor

Goal: migrate source contracts to CapabilityContract v1.

1. Refactor each `contract.json` to v1 shape.
2. Fill mandatory metadata (`version`, namespace, action titles/descriptions, risk, permissions).
3. Standardize action IDs (`system_logs.*` -> dot namespace migration plan with aliases).
4. Align runtime handlers with explicit action ID checks.
5. Add `result_schema` where useful.

Exit criteria:

- All contracts pass strict schema validation.
- No inferred metadata in production load logs.

### Phase 4: Remove legacy fields/modes

Goal: hard cutover.

1. Remove support for `params` and mixed action structures in runtime.
2. Remove legacy alias-only APIs after sunset window.
3. Delete fallback risk inference paths (ACL/UI/Safety), keep only explicit metadata.
4. Enable CI gate: fail build if any contract misses mandatory fields.

Exit criteria:

- No legacy contract fields accepted.
- Deterministic policy/risk behavior fully metadata-driven.

---

## Appendix A: Concrete Defects to Fix Before Migration

1. Recursive registry method:
   - `src/capabilities/registry.py:82-84`
2. Validator ignores `parameters`:
   - `src/core/plan_validator.py:79`, `:84`
3. Task capability helper bug (`message` undefined):
   - `src/capabilities/task_management/capability.py:35`, `:41`
4. Shell capability executes without action ID enforcement:
   - `src/capabilities/shell_control/capability.py:81-83`
5. Duplicate dict keys in system logs errors:
   - `src/capabilities/system_logs/capability.py:74-75`, `:82-83`

These should be treated as preconditions for safe contract migration.
