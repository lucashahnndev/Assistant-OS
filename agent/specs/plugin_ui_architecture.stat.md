# Stat: Frontend Plugin UI Architecture
# Updated: 2026-05-29

## Current State
- **Status:** Planning / Architecture Approved.
- **Frontend Core:** Currently contains hardcoded references (e.g. `Nexus.jsx` checking for weather or maps explicitly).
- **Backend Capabilities:** Do not yet expose standard JSON schemas for UI consumption.
- **Registry:** `frontend/src/plugins_ui` directory does not exist yet.

## Next Steps (Action Items)
1. **Refactoring Backend:** Update `CapabilityContractV1` to include `widget_schema` definitions.
2. **Setup Frontend Registry:** Create `frontend/src/plugins_ui` and standard `registry.js` with `React.lazy()` loading.
3. **Refactoring Nexus/Overview:** Replace hardcoded `claimAssistCardSlot` logic in `Nexus.jsx` and static welcome logic in `Overview.jsx` with `<DynamicPluginRenderer />`.
4. **Migrate Existing Plugins:** Move components like the Weather viewer or System Health charts out of the core components and into `plugins_ui`.
## Relacionados

- [plugin_ui_architecture.spec.md](plugin_ui_architecture.spec.md)
- [../README.md](../overview.md)
