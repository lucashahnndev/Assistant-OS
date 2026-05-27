#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${1:-/home/lucas/Documentos/GitHub/Wegena}"
TARGET_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/frontend/public"

ENGINE_SRC="$SOURCE_ROOT/engine"
PRESETS_SRC="$SOURCE_ROOT/presets"
ENGINE_DST="$TARGET_ROOT/atlas-wegena/engine"

if [[ ! -d "$ENGINE_SRC" || ! -d "$PRESETS_SRC" ]]; then
  echo "Wegena source tree not found at: $SOURCE_ROOT" >&2
  exit 1
fi

mkdir -p "$ENGINE_DST"

cp "$ENGINE_SRC/weg_compiler.js" "$ENGINE_DST/weg_compiler.js"
cp "$ENGINE_SRC/profiler.js" "$ENGINE_DST/profiler.js"
cp "$ENGINE_SRC/simulators.js" "$ENGINE_DST/simulators.js"
cp "$ENGINE_SRC/engine.js" "$ENGINE_DST/engine.js"
cp "$ENGINE_SRC/controls.js" "$ENGINE_DST/controls.js"

echo "Wegena engine runtime synced from $SOURCE_ROOT"
