# Skill to Capability Global Migration Report (2026-03-12)

## 1. Executive Summary
This report consolidates the end-to-end migration performed across the codebase from the former `skill` abstraction to the canonical `capability` architecture, including the later hard-cutover of capability contracts, authentication metadata, secret management, runtime consumers, UI/web flows, and configuration storage.

The final state achieved in active code is:
- `capability` is the canonical subsystem term
- `CapabilityContract v1` is the only accepted capability contract format
- capability auth metadata is canonical and mandatory
- secret management is centralized behind a backend-managed encrypted vault
- capability UI/API/runtime consume canonical metadata only
- legacy key patterns such as `params`, `api_key_ref`, `organization_id_ref`, `credentials_path_ref`, root `skills`, and `reflex_skill` were removed from active code/config
- non-Google OAuth providers were removed, reducing external account auth complexity
- `.env` is no longer the primary secrets store

This was not limited to loader/registry code. The migration covered backend runtime, API routes, ACL/security flows, UI management screens, intelligence/model surfaces, external account provider metadata, persisted configuration, and final secret-storage architecture.

## 2. Migration Scope
The migration evolved in multiple stages:
- terminology migration from `skills` to `capabilities`
- capability contract standardization
- runtime and registry alignment
- validator and ACL alignment
- capability configuration/auth standardization
- shared secret management standardization
- intelligence/model auth normalization
- OAuth/external account simplification
- active config and persisted artifact cleanup
- encrypted vault storage adoption for secrets

## 3. Architectural Migration: `skill` -> `capability`
The capability subsystem was standardized around `src/capabilities` as the canonical domain.

Major outcomes:
- active capability contracts live under `src/capabilities/*/contract.json`
- runtime loaders, registries, validators, ACL checks, and API surfaces reference capability semantics only
- the legacy lexical term `skill` was removed from active capability/config naming where it remained structurally relevant
- the last active semantic vestige `reflex_skill` was renamed to `reflex`

Key files involved:
- [contract_v1.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/contract_v1.py)
- [loader.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/loader.py)
- [registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py)
- [capabilities.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/capabilities.py)
- [reflex contract](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/reflex/contract.json)

## 4. Capability Contract Hard-Cutover
A strict `CapabilityContract v1` model was enforced.

Canonical rules now enforced:
- required top-level fields: `contract_version`, `capability`, `runtime`, `actions`, `auth`
- only `actions` as list is accepted
- only `parameters` is accepted for action input schema
- `params` was removed
- every action must explicitly define:
  - `id`
  - `title`
  - `description`
  - `handler`
  - `risk_level`
  - `permissions`
  - `parameters`
- namespace is explicit and deterministic
- invalid contracts fail loading
- no fallback interpretation remains active in the capability loading path

Key backend files:
- [contract_v1.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/contract_v1.py)
- [loader.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/loader.py)
- [registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py)
- [plan_validator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/plan_validator.py)
- [access_controller.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/access_controller.py)
- [safety_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/safety_service.py)

Result:
- all 22 capability contracts were migrated to the canonical format
- active capability contracts no longer contain `params`
- canonical action metadata is the only source of truth for runtime/validator/ACL/UI capability flows

## 5. Runtime, Registry, Validator, and ACL Alignment
The capability runtime path was normalized so that all critical consumers read the same canonical contract model.

### Runtime / Loader
- loader accepts only canonical contracts
- capability runtime factories are loaded from canonical runtime metadata
- config schema validation is tied to canonical runtime metadata
- loader rejects invalid contracts and stores explicit failure reasons

### Registry
- registry stores canonical capability/action models
- action metadata lookup is canonical-only
- removed ad-hoc metadata interpretation paths

### Plan Validator
- validates only against `actions[].parameters`
- no legacy `params` compatibility path remains

### ACL / Safety
- risk classification is explicit via `risk_level`
- approval requirements rely on canonical `permissions.requires_approval`
- `allow_anyone` relies on canonical permissions metadata
- removed risk heuristics as source of truth

Files:
- [loader.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/loader.py)
- [registry.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/registry.py)
- [plan_validator.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/plan_validator.py)
- [access_controller.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/core/access_controller.py)
- [safety_service.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/safety_service.py)

## 6. Capability Auth Standardization
After contract cutover, capability auth was elevated to a first-class canonical contract section.

Canonical `auth` model:
- `mode`
- `required`
- `fields[]`
- optional `oauth2`

Auth fields became typed and explicit:
- `secret_ref`
- `text`
- `username`
- `password`
- `client_id`

Important outcomes:
- `auth` is mandatory in capability contracts
- secret/auth semantics come from contract metadata, not from ad-hoc UI heuristics
- capability config validation enforces canonical auth bindings
- capabilities enabled without required auth now fail validation

Files:
- [contract_v1.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/contract_v1.py)
- [loader.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/loader.py)
- [capabilities.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/capabilities.py)
- [Capabilities.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Capabilities.jsx)

## 7. Secret Storage Final Architecture
Secret handling was consolidated into a backend-managed encrypted vault.

Final storage model:
- real secret values live in [secrets.json.enc](/home/lucas/Documentos/GitHub/Assistant-OS/data/secrets/secrets.json.enc)
- vault master key lives in [secret_vault.key](/home/lucas/Documentos/GitHub/Assistant-OS/data/secrets/secret_vault.key)
- `config.json` stores only references such as `ENV_*`
- runtime resolves `secret_ref` through the backend vault layer
- `.env` is only an import/audit source, not the primary store

Backend files:
- [secret_manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/core/secret_manager.py)
- [secrets.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/secrets.py)
- [setup.sh](/home/lucas/Documentos/GitHub/Assistant-OS/setup.sh)
- [.env.example](/home/lucas/Documentos/GitHub/Assistant-OS/.env.example)

Outcome:
- one canonical secret storage path
- no raw `.env` editing in the primary web flow
- no client-side secret decryption path
- vault is usable in development and production-like self-hosted deployments without an external secret product

## 8. Secret Management API and UI
The secret-management surface was simplified and normalized around vault CRUD plus `.env` import/audit.

Current API capabilities:
- list secret refs
- list vault entries
- create/update secret
- delete secret
- audit `data/.env`
- import missing entries from `data/.env`
- synchronize divergent entries from `data/.env`

Backend:
- [secrets.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/secrets.py)

Frontend:
- [secretsApi.js](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/utils/secretsApi.js)
- [Settings.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Settings.jsx)
- [Capabilities.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Capabilities.jsx)
- [ModelPoolManager.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/components/ModelPoolManager.jsx)

Final UX outcome:
- users create, rotate, link, audit, and delete secret refs
- the Settings security tab is now a vault management surface, not a raw `.env` editor
- capabilities and model/provider screens bind secret refs without exposing stored values

## 9. UI / Web Alignment
The capability management UI was updated to consume canonical capability/auth metadata.

Key outcomes:
- capability configuration modal derives secret fields from canonical contract auth metadata
- users can select existing secret refs or create new secrets inline
- capability auth/config UX follows the same secret-ref pattern used in settings and intelligence
- frontend no longer performs secret transport decryption or direct `.env` editing in the main management flow

Files:
- [Capabilities.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Capabilities.jsx)
- [Settings.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Settings.jsx)
- [capabilities.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/capabilities.py)

## 10. Intelligence / Model Pool Normalization
The intelligence/model subsystem was normalized toward the same auth/secret handling model.

Changes applied:
- provider catalogs declare canonical auth metadata
- model UI renders auth/secret fields from provider metadata
- special model secret routes were removed
- shared secret API is the only secret-management API path for models
- provider runtime consumers were aligned to `secret_ref`

Representative files:
- [models.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/models.py)
- [manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/manager.py)
- [ModelPoolManager.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/components/ModelPoolManager.jsx)
- [google provider catalog](/home/lucas/Documentos/GitHub/Assistant-OS/src/providers/google/index.json)
- [openai provider catalog](/home/lucas/Documentos/GitHub/Assistant-OS/src/providers/openai/index.json)
- [openrouter provider catalog](/home/lucas/Documentos/GitHub/Assistant-OS/src/providers/openrouter/index.json)
- [google LLM driver](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/gemini/llm.py)
- [openai LLM driver](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openai/llm.py)
- [openrouter LLM driver](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/providers/openrouter/llm.py)

Important normalization outcome:
- `api_key_ref` was removed from active intelligence paths in favor of `secret_ref`

## 11. External Accounts / OAuth Simplification
The external account provider layer was reduced and simplified.

Actions taken:
- non-Google OAuth providers were removed from active code
- settings UI no longer exposes arbitrary provider-add flows for removed providers
- provider metadata path was simplified around Google as the remaining OAuth provider

Removed providers:
- `/src/integrations/external_accounts/providers/aws.py`
- `/src/integrations/external_accounts/providers/cloudflare.py`
- `/src/integrations/external_accounts/providers/microsoft.py`

Remaining provider path:
- [google.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/integrations/external_accounts/providers/google.py)

UI file affected:
- [Settings.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Settings.jsx)

Outcome:
- lower auth/provider surface area
- less duplicated provider-specific secret/config logic

## 12. Config and Naming Cleanup
The active config surface was cleaned to remove remaining legacy keys and duplicated config structures.

Changes applied:
- root `skills` section removed from persisted config
- `logging.services.skills` renamed to `logging.services.capabilities`
- `api_key_ref` removed from active config
- `organization_id_ref` removed from active config
- `credentials_path_ref` removed from active config/runtime path
- duplicated legacy `src/config.py` removed
- `ConfigManager` legacy migration shims removed
- `/api/system/env` removed
- `SECRET_DECRYPTION_KEY` removed
- `/api/secrets/transport-key` removed
- `secret_transport_crypto.py` removed

Files:
- [config.json](/home/lucas/Documentos/GitHub/Assistant-OS/data/config.json)
- [manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/config/manager.py)
- [system.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/system.py)
- [secrets.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/secrets.py)

Outcome:
- active configuration reads only the current canonical structure
- no silent migration/fallback remains in the active config manager path
- no legacy `.env` editing route remains in the main management flow

## 13. Runtime Consumer Cleanup
Several runtime consumers still carrying old defensive or mixed-shape behavior were tightened.

Files updated:
- [LLMManager](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/manager.py)
- [TTSManager](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/tts/manager.py)
- [google TTS provider](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/tts/providers/google.py)
- [voice_driver.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/drivers/interfaces/voice/voice_driver.py)

Outcome:
- runtime paths expect the normalized active config shape rather than carrying compatibility branches for old shapes

## 14. Persisted Artifact Cleanup
Historical persisted browser artifacts pointing to old paths were cleaned where safe.

Actions applied:
- removed `LOG` and `LOG.old` files under `data/browser_data`
- removed stale extension entry from managed Chromium preferences that referenced the old extension/path state

File affected:
- [Preferences](/home/lucas/Documentos/GitHub/Assistant-OS/data/browser_data/profile_managed_chromium/Default/Preferences)

Outcome:
- reduced residual operational references to historical extension/path state

## 15. Defects Fixed Along the Way
Concrete defects fixed during the migration/cutover path included:
- capability action/runtime discipline issues in shell/task/system logs/reflex flows
- capability registry/validator mismatches against canonical schema shape
- capability configuration gaps for auth-required capabilities
- missing capability management secret UX consistency
- duplicate or parallel secret APIs for model/intelligence flows
- duplicated provider surface for unused OAuth providers
- legacy persisted config aliases that would reintroduce dual model behavior
- split secret-storage behavior between `ConfigManager` and secrets API

## 16. Validation Performed
Validation executed after the final cleanup:

### Legacy-pattern sweep
Command outcome:
- searched for:
  - `src/skills`
  - `reflex_skill`
  - `api_key_ref`
  - `organization_id_ref`
  - `credentials_path_ref`
  - `capabilities.reflex_skill`
  - root `"skills":`
- result: no matches in active `src`, `data`, and `frontend` surfaces for the tracked migration patterns

### Backend compile pass
- `PYTHONPATH=src ./env/bin/python -m compileall -q src`
- result: success

### Vault smoke test
- created a temporary secret in the vault
- listed refs and entries
- deleted the temporary secret
- result: success

### Frontend production build
- `cd frontend && npm run build`
- result: success
- note: bundle-size warning remains, but build integrity is clean

## 17. Final State
The active system is now substantially more predictable and professional in the areas touched by this migration:
- one canonical capability contract
- one canonical capability auth model
- one backend-managed encrypted vault
- one reusable secret-ref pattern across capabilities, settings, and intelligence
- one normalized naming direction around `capability`
- reduced external auth/provider surface
- reduced config aliasing and fallback behavior

## 18. Residual Risks / Follow-up
No active architectural dual-model issue from the tracked migration patterns remains in the scanned active code/config surfaces.

Remaining follow-up items are quality-oriented rather than architectural split issues:
- frontend bundle chunking optimization
- broader documentation cleanup if older reports/docs still mention intermediate secret transport phases or `skill`
- deeper runtime integration tests across all capability enable/disable/auth-required scenarios

## 19. Final Compliance Snapshot
- canonical capability contract only: true
- `params` removed from active capability contract path: true
- canonical `parameters` only: true
- capability auth canonicalized: true
- capability UI/API/runtime aligned: true
- secrets stored in encrypted vault: true
- `.env` no longer primary secret store: true
- `.env` limited to import/audit source: true
- frontend no longer edits raw `.env`: true
- intelligence/model secret path normalized: true
- non-Google OAuth providers removed: true
- root `skills` config removed: true
- `reflex_skill` removed from active code/config: true
- `api_key_ref` removed from active code/config: true
- `organization_id_ref` removed from active code/config: true
- `credentials_path_ref` removed from active code/config: true
- `/api/system/env` removed: true
- `/api/secrets/transport-key` removed: true
- `SECRET_DECRYPTION_KEY` removed: true
