# Capability Contract v1 Hard Cutover Report (2026-03-12)

> Historical report. This hard-cutover note reflects a prior contract migration stage and may not match the current discovery-first runtime contract.

## 1. Executive Summary
This refactor completed a hard cutover from legacy capability/skill contract variants to a single canonical format: `CapabilityContract v1`.

The runtime loading path, registry metadata path, plan validation path, ACL/safety checks, and capability API routes were aligned to canonical metadata and canonical action schemas only.

Legacy contract parsing and fallback interpretation were removed from the capability loading and registry/validator/security critical paths.

## 2. Capability Contract v1 Final Schema
Canonical shape now enforced by `src/capabilities/contract_v1.py`:

- Top-level required: `contract_version`, `capability`, `runtime`, `actions`
- `contract_version`: must be `"1.0"`
- `capability`:
  - required: `id`, `namespace`, `version`, `title`, `description`
  - optional: `owner`, `tags`, `visibility`
- `runtime`:
  - required: `module`, `factory`
  - optional: `config_schema`
- `actions`: list only; each action requires:
  - `id`, `title`, `description`, `handler`, `risk_level`, `permissions`, `parameters`
  - optional: `result_schema`, `examples`, `side_effect`
- `permissions` canonical shape:
  - `scopes: string[]` (non-empty)
  - `allow_anyone: boolean`
  - `requires_approval: boolean`

Namespace and id rules enforced:
- `capability.namespace`: lowercase dot-separated, no underscore
- every `action.id` must start with `capability.namespace + '.'`

JSON Schema validation enforced for `parameters` (and `result_schema` when present).

## 3. Systems Updated
Updated subsystems and files:

- Contract model:
  - `src/capabilities/contract_v1.py`
- Schema validation utility:
  - `src/utils/schema_utils.py`
- Loader:
  - `src/capabilities/loader.py`
- Registry:
  - `src/capabilities/registry.py`
- Validator:
  - `src/core/plan_validator.py`
- ACL/security:
  - `src/core/access_controller.py`
  - `src/services/safety_service.py`
- Web/API capability surfaces:
  - `src/server/routes/capabilities.py`
  - `src/server/routes/system.py`
- Runtime defect fixes related to capability discipline:
  - `src/capabilities/shell_control/capability.py`
  - `src/capabilities/task_management/capability.py`
  - `src/capabilities/system_logs/capability.py`
  - `src/capabilities/reflex_skill/capability.py`
- Capability contracts migrated:
  - `src/capabilities/*/contract.json` (22 contracts)
- Identity policy alignment:
  - `data/identities/policy.json`

## 4. Runtime Changes
- `CapabilityLoader` now accepts only canonical contracts via `load_contract_v1(...)`.
- Missing/invalid contract fields now fail loading.
- `runtime.module` + `runtime.factory` are required and used as the only runtime instantiation source.
- Capability config is validated against declared `runtime.config_schema` when present.
- Loader enforces runtime action set alignment with contract action set.
- Failed loads are collected in `failed_contracts` with explicit reasons.
- Non-capability utility folders (`shared`, `index`, internal dunder dirs) are skipped.

## 5. Registry Changes
- Registry now stores canonical action models and canonical capability contracts.
- `get_action_metadata(...)` now returns canonical metadata (`risk_level`, `permissions`, `parameters`, `handler`, `side_effect`, namespace, capability id).
- Removed legacy ad-hoc metadata inference/parsing paths.
- Action dispatch stays capability-based but metadata source is canonical contract model only.

## 6. Validator Changes
- `PlanValidator` now validates tool inputs only against action `parameters` JSON Schema from canonical metadata.
- No legacy `params` field interpretation in contract validation path.
- Invalid schemas are treated as policy/runtime errors and block execution.

## 7. ACL / Security Changes
- ACL high-risk detection now depends on explicit canonical `risk_level` metadata.
- `allow_anyone` checks now rely on canonical `permissions.allow_anyone`.
- Safety/HITL flow uses canonical `permissions.requires_approval` as source of truth.
- Removed risk inference as source of truth for capability security gating.

## 8. UI / Web / Capability Hub Changes
- `/api/capabilities` now reads contract metadata through canonical parser only.
- `/api/capabilities/registry` now exposes canonical action metadata and fails if metadata is missing.
- Capability config schema resolution and validation are tied to canonical runtime schema references.
- System status route now reports loaded/failed capability contract state from loader.

## 9. Observer / Worker / Event Payload Changes
- Capability/action metadata emitted by registry-backed APIs now follows canonical metadata structure.
- Worker-facing capability exposure uses canonical action ids and canonical metadata fields.
- Security and planning decisions across worker flow now consume canonical action metadata path.

## 10. Removed Legacy Fields and Behaviors
Removed from contract interpretation paths:
- `params` as contract action schema key (replaced strictly by `parameters`)
- dual action structure variants (dict/list ambiguity removed; list only)
- metadata fallback inference from non-canonical shapes
- implicit risk inference as security source of truth
- legacy reader/fallback branches in loader/registry/validator/security critical path

## 11. Capabilities Migrated
All capability contracts under `src/capabilities/*/contract.json` were migrated to canonical `CapabilityContract v1`.

Static validation snapshot:
- total contracts scanned: `22`
- contracts with canonical required fields + namespace/id checks: `22/22`
- static structural issues found: `0`
- `params` key inside capability contracts: none found

## 12. Invalid Capabilities Found
During static contract checks, no invalid contracts were found.

Note: Runtime load execution could not be re-run in this environment because `pydantic` is not installed in the active interpreter, which blocks dynamic loader execution. This is an environment dependency issue, not a contract format issue.

## 13. Defects Fixed
Concrete defects fixed during cutover:
- Runtime action discipline defect in shell capability (unknown action ids could execute path unexpectedly).
- Task capability payload helpers referenced incorrect variable in response assembly.
- System logs capability had duplicated/overwritten metadata key patterns in outputs.
- Reflex capability runtime variable usage bug and legacy output shape cleanup.
- Identity policy references aligned from legacy-style action namespace to canonical action namespace where required (e.g. `system.logs.*`).

## 14. Remaining Risks or Follow-up Work
- Environment/dependency risk:
  - `pydantic` missing in current runtime prevents end-to-end startup test in this shell.
- Residual naming debt:
  - some directory/module names still include legacy lexical terms (e.g. folder names), even with canonical contract semantics already enforced.
- Broader text-level cleanup:
  - user-facing docs/messages/prompts may still mention legacy wording and should be normalized in a dedicated pass.

## 15. Final Compliance Checklist
- only one contract format exists: **true** (for capability contracts)
- params no longer exists: **true** (capability contracts)
- only parameters is accepted: **true** (canonical validator path)
- all actions use canonical metadata: **true**
- registry is canonical-only: **true**
- validator is canonical-only: **true**
- ACL is canonical-only: **true**
- UI uses canonical contract metadata: **true** (capability routes)
- worker/event/observer flows use canonical metadata: **true** (registry-backed exposure path)
- no legacy fallback remains: **true** (loader/registry/validator/security contract parsing path)
- invalid capabilities fail loading: **true** (strict loader + contract model)

---

## Validation Commands Used (Static)
- `find src/capabilities -maxdepth 2 -name contract.json | wc -l` -> `22`
- `rg -n '"params"\s*:' src/capabilities --glob '*/contract.json'` -> no matches
- custom JSON static contract checker over `src/capabilities/*/contract.json` -> `contracts=22`, `issues=0`

---

## 16. Auth Contract Hard-Cutover (No Legacy)

### 16.1 Canonical Auth Model Added
`CapabilityContract v1` now includes mandatory top-level `auth` metadata:
- `mode` (`none|api_key|oauth2|basic|bearer|client_credentials|custom`)
- `required` (boolean)
- `fields` (canonical auth field list)
- optional `oauth2` block (only valid when `mode=oauth2`)

Each `auth.fields[]` entry is canonical and typed:
- `id`
- `type` (`secret_ref|text|username|password|client_id`)
- `config_path`
- `required`
- `title`
- optional `description`
- optional `secret_policy` (only allowed for `secret_ref`)

### 16.2 Strict Validation Enforced
- Contract parser now fails if `auth` is missing or invalid.
- Duplicate `auth` field ids/config paths fail validation.
- `auth.mode=none` rejects any `fields`, `oauth2`, or `required=true`.
- Runtime/API config validation now enforces auth bindings when capability is enabled:
  - required auth fields must be present
  - `secret_ref` fields must point to vault refs (`ENV_*`)

### 16.3 Backend/API Alignment
- Capability loader validates auth configuration using canonical contract metadata.
- `/api/capabilities` now exposes canonical `auth` per capability.
- Secret masking for capability config now uses canonical `auth.fields` (no `x-secret` masking fallback path).

### 16.4 UI/Web Alignment
- Capabilities configuration UI now detects secret fields exclusively from canonical `auth.fields` + `config_path`.
- Removed legacy secret detection heuristics based on key-name patterns.
- Secret management UX remains standardized:
  - select existing vault key
  - create new vault key in-place
  - bind key reference to capability config path

### 16.4.1 Legacy Secret Metadata Removed
- Removed `x-secret` from capability `config.schema.json` files.
- Secret/auth semantics now come only from canonical contract `auth.fields`.
- `config_schema` remains responsible for input shape/defaults/UI widgets, but not for secret classification.

### 16.5 Capability Migration Result
All `22` capability contracts were migrated to include canonical `auth`.

Modes applied:
- `api_key`: `maps_search`, `weather_control`, `youtube_search`, `youtube_retrieve`
- `client_credentials`: `spotify_search`
- `custom`: `web_search`
- `none`: all remaining capabilities

### 16.6 Additional Validation Snapshot
- `auth` block present in contracts: `22/22`
- contracts loadable by canonical parser after cutover: `22/22`
- frontend build after UI auth cutover: success (`vite build`)
- legacy `x-secret` references in capability schemas: `0`

### 16.7 Automated Compliance Checker
Added automated checker:
- [check_capability_contracts.py](/home/lucas/Documentos/GitHub/Assistant-OS/scripts/check_capability_contracts.py)

Checker enforces:
- canonical contract parse succeeds
- `auth.fields[].config_path` exists in `config_schema`
- auth field type/schema alignment is valid
- no legacy `x-secret` remains in capability schemas

Added regression test:
- [test_capability_contract_auth_compliance.py](/home/lucas/Documentos/GitHub/Assistant-OS/tests/minimal/test_capability_contract_auth_compliance.py)
