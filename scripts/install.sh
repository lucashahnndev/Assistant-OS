#!/bin/bash

# AOSD Internal Installer
# This script is called by the remote bootstrap or run manually from the repo root.

set -euo pipefail

echo "⚙️ Starting Assistant-OS internal installation..."

# 1. Directory Validation
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# 2. Environment Variables Mapping
# Map bootstrap flags to setup.sh flags
export AOSD_SKIP_PRIVILEGED_SETUP="${AOSD_SKIP_PRIVILEGED_SETUP:-0}"
export AOSD_AUTO_INSTALL_SERVICES="${AOSD_AUTO_INSTALL_SERVICES:-${AOSD_INSTALL_SERVICES:-0}}"

# If non-interactive mode is requested, ensure sub-scripts respect it
if [ "${AOSD_NONINTERACTIVE:-0}" = "1" ]; then
    echo "🤖 Non-interactive mode detected."
    export AOSD_AUTO_PRIVILEGED_SETUP=1
    export AOSD_AUTO_INSTALL_SERVICES=1
fi

# 3. Call setup.sh
# setup.sh handles: venv, backend dependencies, frontend dependencies, and service prompt.
chmod +x setup.sh
./setup.sh

# 4. Final Service Activation (if installed)
if [ "${AOSD_AUTO_INSTALL_SERVICES:-0}" = "1" ]; then
    echo "🚀 Activating services..."
    systemctl --user daemon-reload
    systemctl --user enable aosd.target
    systemctl --user start aosd.target
    echo "✅ AOSD Integrated Stack is now running!"
fi

echo ""
echo "✨ Installation steps complete."
if [ "${AOSD_NONINTERACTIVE:-0}" != "1" ]; then
    echo "You can check service status with: ./env/bin/python agent.py doctor --status-services"
fi
