#!/bin/bash

# AOSD Remote Bootstrap Script
# This script is designed to be executed via:
# bash <(curl -fsSL https://raw.githubusercontent.com/<repo>/main/install.sh)

set -euo pipefail

# Configuration
REPO_URL="https://github.com/lucashahnndev/Assistant-OS.git"
DEFAULT_INSTALL_DIR="$HOME/.aosd"
INSTALL_DIR="${AOSD_INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"

echo "🚀 Assistant-OS Bootstrap Installer"
echo "-----------------------------------"

# 1. Environment Detection & Pre-flight
echo "🔍 Checking environment..."

CHECK_TOOLS=("git" "bash" "curl" "python3" "node" "npm")
MISSING_TOOLS=()

for tool in "${CHECK_TOOLS[@]}"; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        MISSING_TOOLS+=("$tool")
    fi
done

if [ ${#MISSING_TOOLS[@]} -ne 0 ]; then
    echo "❌ Missing required tools: ${MISSING_TOOLS[*]}"
    echo "   Please install them before running this script."
    echo "   Example: sudo apt-get update && sudo apt-get install -y git curl python3 nodejs npm"
    exit 1
fi

# 2. Target Directory Preparation
if [ ! -d "$INSTALL_DIR" ]; then
    echo "📦 Creating installation directory: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# 3. Retrieval (Clone or Pull)
if [ ! -d ".git" ]; then
    echo "📥 Cloning repository..."
    git clone "$REPO_URL" .
else
    echo "🔄 Repository already exists, checking for updates..."
    git fetch origin
    git pull
fi

# 4. Handoff to Internal Installer
echo "⚡ Handing off to internal installer..."
chmod +x scripts/install.sh
exec ./scripts/install.sh
