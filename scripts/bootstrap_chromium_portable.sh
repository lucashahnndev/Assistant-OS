#!/usr/bin/env bash

set -euo pipefail

DATA_DIR="${1:-${AOSD_DATA_DIR:-}}"
if [ -z "${DATA_DIR}" ]; then
  if [ -d "data" ]; then
    DATA_DIR="$(pwd)/data"
  else
    DATA_DIR="$HOME/aosd"
  fi
fi

INSTALL_ROOT="${DATA_DIR}/browser_bin/chromium"
CURRENT_LINK="${INSTALL_ROOT}/current"
CURRENT_CHROME="${CURRENT_LINK}/chrome"

if [ -x "${CURRENT_CHROME}" ]; then
  echo "✅ Managed Chromium already available at ${CURRENT_CHROME}"
  exit 0
fi

for cmd in curl unzip python3; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "❌ Missing dependency: ${cmd}"
    exit 1
  fi
done

mkdir -p "${INSTALL_ROOT}"

DOWNLOAD_URL=""
VERSION=""

if [ -n "${AOSD_CHROMIUM_DOWNLOAD_URL:-}" ]; then
  DOWNLOAD_URL="${AOSD_CHROMIUM_DOWNLOAD_URL}"
fi

if [ -z "${DOWNLOAD_URL}" ]; then
  echo "🌐 Resolving latest Chrome for Testing (linux64) URL..."
  readarray -t _resolved < <(python3 - <<'PY'
import json
import urllib.request

url = "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json"
with urllib.request.urlopen(url, timeout=20) as resp:
    data = json.loads(resp.read().decode("utf-8"))

stable = data.get("channels", {}).get("Stable", {})
version = str(stable.get("version") or "")
downloads = stable.get("downloads", {}).get("chrome", [])
target = ""
for item in downloads:
    if isinstance(item, dict) and item.get("platform") == "linux64":
        target = str(item.get("url") or "")
        break
print(version)
print(target)
PY
)
  VERSION="${_resolved[0]:-}"
  DOWNLOAD_URL="${_resolved[1]:-}"
fi

if [ -z "${DOWNLOAD_URL}" ]; then
  echo "❌ Could not resolve Chromium download URL."
  exit 1
fi

if [ -z "${VERSION}" ]; then
  VERSION="$(date +%Y%m%d%H%M%S)"
fi

TARGET_DIR="${INSTALL_ROOT}/${VERSION}"
ZIP_PATH="${INSTALL_ROOT}/chromium-${VERSION}.zip"

mkdir -p "${TARGET_DIR}"

echo "⬇️  Downloading Chromium (${VERSION})..."
curl -fsSL "${DOWNLOAD_URL}" -o "${ZIP_PATH}"

echo "📦 Extracting to ${TARGET_DIR}..."
unzip -q -o "${ZIP_PATH}" -d "${TARGET_DIR}"
rm -f "${ZIP_PATH}"

BIN_PATH="${TARGET_DIR}/chrome-linux64/chrome"
if [ ! -x "${BIN_PATH}" ]; then
  echo "❌ Chromium binary not found after extraction: ${BIN_PATH}"
  exit 1
fi

ln -sfn "${TARGET_DIR}/chrome-linux64" "${CURRENT_LINK}"
echo "✅ Managed Chromium installed:"
echo "   Binary: ${CURRENT_CHROME}"
echo "   Version: ${VERSION}"
