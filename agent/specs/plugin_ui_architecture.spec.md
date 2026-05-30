# Spec: Frontend Plugin UI Architecture
# Status: Approved
# Date: 2026-05-29

## 1. Goal
Decouple the frontend Core (Nexus, Overview Dashboard, Boot Sequence) from specific backend capabilities (Plugins). Ensure that disabling or removing a capability backend does not break the React frontend, while supporting both simple schema-driven widgets and complex custom components (e.g., 3D Maps, Interactive Terminals).

## 2. Core Rule
- The frontend Core **MUST NOT** contain hardcoded UI components or logic specific to individual plugins (e.g., `<CloudflareWidget>`, `if (weatherSignal)`).
- Capabilities **MUST** drive their UI dynamically via standard payloads.

## 3. Implementation Design

### 3.1. Standard Generic Widgets (Schema-Driven)
For standard data (metrics, simple status, lists), capabilities will return a `widget_schema` field in their execution output.
The frontend Core provides a set of generic, high-fidelity React components (e.g., `<GenericStatusCard>`, `<GenericBarChart>`) that blind-render the provided schema.

### 3.2. Modular Custom UIs (Plugin UI Registry)
If a capability requires a highly customized interface that cannot be represented by generic schemas, it must use the **Plugin UI Registry** pattern.

1. **Registry Directory:** The custom React code lives entirely inside `frontend/src/plugins_ui/[capability_id]/`.
2. **Lazy Loading:** A central `registry.js` file lazily exports these components using `React.lazy()`.
3. **Core Injection:** The frontend Core renders a `<DynamicPluginRenderer capability="id" />`. This component intercepts the capability payload, checks if the capability exists in the registry, and lazy-loads the custom component over the network. If missing, it falls back to a generic renderer.
4. **Context Inheritance:** Components inside `plugins_ui` natively inherit Global CSS, Glassmorphism design tokens, and Context APIs (like `AuthContext`), maintaining the institutional aesthetic without Shadow DOM isolation issues.

## 4. Operational Constraints
- No capability-specific logic should exist outside of `frontend/src/plugins_ui/`.
- Backend capabilities must be written assuming they might be interacting with a generic terminal; the frontend is just an advanced consumer of their schema.
