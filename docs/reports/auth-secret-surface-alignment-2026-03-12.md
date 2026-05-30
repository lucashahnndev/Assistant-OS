# Auth and Secret Surface Alignment Audit

> Historical report. This audit reflects an earlier auth/secret alignment stage and may not match the current discovery-first runtime contract.

Date: 2026-03-12

## Executive Summary

The capability subsystem is already aligned to the canonical `CapabilityContract v1` auth model.

Outside the capability subsystem, the codebase still contains parallel auth/secret models. The main remaining non-canonical surfaces are:

- external account providers / OAuth provider config
- intelligence/model pool configuration
- selected runtime consumers that still accept inline values or legacy aliases in addition to `ENV_*` refs

This means the system is not yet globally unified under one auth contract, even though secret storage/transport is already reusable.

## Classification Matrix

### 1. Canonical / Aligned

#### Capabilities
- Contract parser and auth validation:
  - [contract_v1.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/contract_v1.py)
- Loader:
  - [loader.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/loader.py)
- Registry/API:
  - [capabilities.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/capabilities.py)
- Capabilities UI:
  - [Capabilities.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Capabilities.jsx)

Status:
- canonical `auth` block required
- canonical `secret_ref` fields enforced
- no legacy `x-secret` in capability config schemas

#### Shared Secret Management
- Secret API:
  - [secrets.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/secrets.py)
- Secret persistence:
  - [secret_manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/core/secret_manager.py)
- Secret transport crypto:
  - [secret_transport_crypto.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/core/secret_transport_crypto.py)
- Frontend reusable client:
  - [secretsApi.js](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/utils/secretsApi.js)

Status:
- reusable vault-like secret refs (`ENV_*`)
- reusable encrypted transport handshake
- reusable web flow for create/select/delete

## 2. Partially Aligned

### Intelligence / Models
- Model config API:
  - [models.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/models.py)
- Runtime manager:
  - [manager.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/services/llm/manager.py)
- Intelligence UI:
  - [Settings.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Settings.jsx)
  - [ModelPoolManager.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/components/ModelPoolManager.jsx)

Status after alignment pass:
- model provider catalogs now use canonical `auth` metadata plus `settings_fields`
- model UI now renders secret selection/creation from canonical catalog `auth.fields`
- special-case `/api/models/env-keys` routes were removed
- shared `/api/secrets` is now the only secret-management API path for models
- runtime still accepts `api_key_ref` as the persisted config key, but secret resolution now happens in providers instead of a router/manager shim

Concrete inconsistencies:
- persisted model pool config still uses provider-specific keys like `api_key_ref`, not a shared nested auth object

### Runtime Consumers
- Google shared auth helper:
  - [google_auth.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/shared/google_auth.py)
- Some capabilities:
  - [spotify_search/capability.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/spotify_search/capability.py)
  - [youtube_search/capability.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/youtube_search/capability.py)
  - [youtube_retrieve/capability.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/youtube_retrieve/capability.py)

Status:
- canonical contract now exists
- some runtime code still accepts legacy inline values or old aliases in addition to canonical refs

Concrete inconsistencies:
- [google_auth.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/shared/google_auth.py) still accepts both direct values and `*_ref` aliases.
- [spotify_search/capability.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/capabilities/spotify_search/capability.py) still falls back to raw process env names (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`) instead of depending only on contract-driven config.

## 3. Not Yet Canonical

### External Accounts / OAuth Providers
- Provider base metadata:
  - [base.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/integrations/external_accounts/base.py)
- Provider implementations:
  - [google.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/integrations/external_accounts/providers/google.py)
- API:
  - [external_accounts.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/external_accounts.py)
  - [auth.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/auth.py)
- UI:
  - [Settings.jsx](/home/lucas/Documentos/GitHub/Assistant-OS/frontend/src/pages/Settings.jsx)

Status after alignment pass:
- provider plugins now expose canonical auth metadata (`auth`) and extra config fields (`config_fields`)
- Settings UI now renders provider secret fields from provider metadata instead of hardcoded maps
- provider list API now exposes canonical auth metadata
- OAuth start/connect discovery now uses canonical provider metadata

Remaining inconsistency:
- persisted provider config is still a plain provider object (`client_id`, `client_secret`, `redirect_uri`, etc.), not a single nested shared auth object shape
- OAuth callback flow is still provider-specific in [auth.py](/home/lucas/Documentos/GitHub/Assistant-OS/src/server/routes/auth.py)

Concrete inconsistencies:
- external account storage shape is not yet unified under a nested canonical auth object
- OAuth callback implementation is still custom per provider

## Key Conclusion

The codebase is currently split into two auth-config worlds:

- canonical capability auth contract
- semi-canonical provider auth metadata for external accounts and intelligence

The shared secret transport and storage layer is already reusable across both worlds, which is good. The remaining work is contract standardization, not secret infrastructure.

## Recommended Next Refactor Target

The next hard-cutover should standardize:

1. external account providers onto a canonical provider auth contract
2. intelligence/model providers onto the same canonical auth field model
3. runtime consumers to stop accepting inline secret values and alias fields where canonical refs exist

## Proposed Compliance Labels

- `canonical`: capabilities, secrets transport/storage
- `hybrid`: intelligence/model pool, external accounts, some capability runtime consumers
