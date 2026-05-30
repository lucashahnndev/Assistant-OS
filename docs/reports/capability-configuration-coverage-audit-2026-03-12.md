# Capability Configuration Coverage Audit (2026-03-12)

> Historical report. This audit predates the current discovery-first contract and reflects an earlier capability-configuration stage.

## Executive Summary
This audit reviewed all capabilities under `src/capabilities/*` and compared runtime configuration usage against exposed `runtime.config_schema` metadata.

Result:
- Capabilities with runtime config usage now expose configuration schema in the Capability Hub.
- Critical missing schema coverage for API-key-driven capabilities was fixed.
- Remaining capabilities without schema currently do not consume runtime config in `capability.py` (by design).

## Fixes Applied
1. Added `runtime.config_schema` + schema files for:
- `spotify_search`
- `maps_search`
- `youtube_search`
- `youtube_retrieve`
- `deezer_search`
- `web_search`
- `web_retrieve`
- `wikipedia_search`
- `vision`
- `system_logs`

2. Expanded `web_search` configuration schema with router/provider controls:
- `search_router.provider_order`
- `search_router.strict_location_when_query_mentions_city`
- `search_router.providers.*` (searxng, brave, ddg, openalex, commoncrawl)
- `search_router.providers.brave.api_key` as secret

3. Expanded `web_retrieve` behavior and schema:
- Added `defaults.mode` (`auto|main|all`) in schema
- Runtime now reads `defaults.mode` when action param `mode` is missing

4. Fixed overlay schema/runtime mismatch:
- Added `temp_artifacts_ttl_ms` to `assistive_overlay/config.schema.json`

5. Aligned weather config requirement with fallback behavior:
- Removed hard `required: ["api_key"]` from `weather_control/config.schema.json`

## Coverage Snapshot
### Capabilities with runtime config and schema present
- `assistive_overlay`
- `data_analysis`
- `deezer_search`
- `maps_search`
- `shell_control`
- `spotify_search`
- `system_logs`
- `vision`
- `weather_control`
- `web_retrieve`
- `web_search`
- `wikipedia_search`
- `youtube_retrieve`
- `youtube_search`

### Capabilities without `runtime.config_schema`
- `deep_memory`
- `memory_management`
- `reflex_skill`
- `research_retrieve`
- `task_management`

Observation: these currently do not read runtime config keys in their `capability.py` implementations.

## Remaining Bottlenecks (Non-blocking)
1. Environment-only precedence can still hide misconfiguration
- Some capabilities use env var fallback first/second. Hub now exposes fields, but operators may still configure env externally and expect UI parity.

2. Optional credential strategy differs by capability
- Some capabilities gracefully fallback without API key (e.g., weather/spotify via fallback paths), while others are quality-degraded without keys.

3. No explicit "credential health" indicator in Hub cards
- Hub currently exposes schema fields and validation, but not a provider-level "credentials ready" diagnostic badge.

## Validation
- JSON parse check for all capability contracts and config schemas: `0` errors.
- Python syntax check for modified runtime file `web_retrieve/capability.py`: passed.
