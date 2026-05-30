# Wegena Runtime Embedding Spec

## Overview

The Atlas frontend serves the Wegena runtime from files stored inside this repository instead of depending on an external workspace symlink.

## Layout

- `frontend/public/atlas-wegena/engine`
  - JavaScript runtime files loaded by `frontend/index.html`
- `frontend/public/presets`
  - Atlas-owned Wegena presets resolved by the runtime via `/presets/<id>/manifest.json`

## Sync Flow

To refresh the embedded runtime from the external Wegena repository:

```bash
./scripts/sync_wegena_runtime.sh
```

By default the script reads from:

```text
/home/lucas/Documentos/GitHub/Wegena
```

You can also pass a different source path:

```bash
./scripts/sync_wegena_runtime.sh /path/to/Wegena
```

## Scope

Only the Wegena engine runtime is synced from the external repository.

The Atlas default live panel scene stays local to this repository:

- `frontend/public/presets/atlas-live-default`

This keeps the user-facing default orb versioned with Atlas while preserving Wegena as the upstream engine source.

## Why

- removes hidden coupling through `frontend/public/wegena`
- makes Atlas behavior versionable and reviewable inside this repository
- keeps Wegena as a separate source project while giving Atlas a stable embedded runtime
