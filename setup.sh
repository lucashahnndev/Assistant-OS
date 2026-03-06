#!/bin/bash

# AOSD Setup Script
# This script prepares the environment for the AOSD project.

set -e

echo "🚀 Starting AOSD Setup..."

APT_INSTALL_CMD=""
MISSING_SYSTEM_DEPS=()
NODE_MIN_MAJOR=20
NODE_MIN_MINOR=19

node_version_ok() {
    if ! command -v node >/dev/null 2>&1; then
        return 1
    fi
    local ver major minor
    ver="$(node -v 2>/dev/null | sed 's/^v//')"
    major="${ver%%.*}"
    minor="$(echo "$ver" | cut -d. -f2)"
    major="${major:-0}"
    minor="${minor:-0}"
    if [ "$major" -gt "$NODE_MIN_MAJOR" ]; then
        return 0
    fi
    if [ "$major" -eq "$NODE_MIN_MAJOR" ] && [ "$minor" -ge "$NODE_MIN_MINOR" ]; then
        return 0
    fi
    return 1
}

can_use_apt() {
    command -v apt-get &> /dev/null
}

configure_apt_install_cmd() {
    if ! can_use_apt; then
        APT_INSTALL_CMD=""
        return
    fi

    if [ "$(id -u)" -eq 0 ]; then
        APT_INSTALL_CMD="apt-get"
        return
    fi

    if command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
        APT_INSTALL_CMD="sudo apt-get"
        return
    fi

    APT_INSTALL_CMD=""
}

try_install_system_deps() {
    if [ "${#MISSING_SYSTEM_DEPS[@]}" -eq 0 ]; then
        return
    fi

    local unique_deps=()
    local dep
    for dep in "${MISSING_SYSTEM_DEPS[@]}"; do
        if [[ ! " ${unique_deps[*]} " =~ " ${dep} " ]]; then
            unique_deps+=("$dep")
        fi
    done
    MISSING_SYSTEM_DEPS=("${unique_deps[@]}")

    configure_apt_install_cmd

    if [ -z "$APT_INSTALL_CMD" ]; then
        echo "⚠️  Missing system dependencies: ${MISSING_SYSTEM_DEPS[*]}"
        echo "   Install manually and rerun setup:"
        echo "   sudo apt-get update && sudo apt-get install -y ${MISSING_SYSTEM_DEPS[*]}"
        return
    fi

    echo "📦 Installing system dependencies: ${MISSING_SYSTEM_DEPS[*]}"
    $APT_INSTALL_CMD update
    $APT_INSTALL_CMD install -y "${MISSING_SYSTEM_DEPS[@]}"
}

# 1. Check for Python 3
if ! command -v python3 &> /dev/null; then
    MISSING_SYSTEM_DEPS+=("python3")
fi

# 2. Check for Node.js
if ! command -v node &> /dev/null; then
    MISSING_SYSTEM_DEPS+=("nodejs" "npm")
else
    echo "✅ Node.js is already installed ($(node -v))."
fi

# 3. Ensure venv + ensurepip support is available
if command -v python3 &> /dev/null && ! python3 -m venv -h >/dev/null 2>&1; then
    MISSING_SYSTEM_DEPS+=("python3-venv")
fi
if command -v python3 &> /dev/null && ! python3 -m ensurepip --version >/dev/null 2>&1; then
    MISSING_SYSTEM_DEPS+=("python3-venv")
fi
if ! command -v openssl &> /dev/null; then
    MISSING_SYSTEM_DEPS+=("openssl")
fi

# 3.1 Qt runtime dependency for assistive overlay backend (PySide6 on X11)
# Required to load the Qt xcb platform plugin correctly.
if can_use_apt; then
    MISSING_SYSTEM_DEPS+=("libxcb-cursor0")
fi

try_install_system_deps

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required."
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "❌ Node.js is required for frontend setup."
    exit 1
fi

if ! node_version_ok; then
    echo "❌ Node.js $(node -v) is not supported by this frontend."
    echo "   Required: >= v${NODE_MIN_MAJOR}.${NODE_MIN_MINOR}"
    echo "   Upgrade (recommended): nvm install 20.19.0 && nvm use 20.19.0"
    exit 1
fi

# 4. Setup Python Virtual Environment
echo "🐍 Preparing Python virtual environment (env/)..."

if [ "${FORCE_RECREATE_ENV:-0}" = "1" ] && [ -d "env" ]; then
    echo "🧹 FORCE_RECREATE_ENV=1 set. Removing existing env/..."
    rm -rf env
fi

if [ -x "./env/bin/pip" ] && [ -f "./env/bin/activate" ]; then
    echo "✅ Reusing existing virtual environment."
else
    rm -rf env
    if ! python3 -m venv env; then
        echo "❌ Failed to create virtual environment."
        echo "   On Debian/Ubuntu install: sudo apt-get install -y python3-venv"
        exit 1
    fi
fi

if [ ! -x "./env/bin/pip" ]; then
    echo "❌ Virtual environment created without pip (ensurepip unavailable)."
    echo "   On Debian/Ubuntu install: sudo apt-get install -y python3-venv"
    exit 1
fi

echo "📦 Installing Python dependencies..."
./env/bin/pip install --upgrade pip

TMP_REQUIREMENTS="$(mktemp)"
if command -v rg >/dev/null 2>&1; then
    rg -v '^\s*pyaudio\s*$' requirements.txt > "$TMP_REQUIREMENTS"
else
    grep -vi '^\s*pyaudio\s*$' requirements.txt > "$TMP_REQUIREMENTS"
fi

./env/bin/pip install -r "$TMP_REQUIREMENTS"
rm -f "$TMP_REQUIREMENTS"

echo "🎤 Installing optional voice dependency (pyaudio)..."
if ! ./env/bin/pip install pyaudio; then
    echo "⚠️  Could not install optional dependency: pyaudio"
    echo "   Voice capture may be unavailable until system headers are installed."
    echo "   On Debian/Ubuntu try: sudo apt-get install -y portaudio19-dev python3-dev build-essential"
fi

if ! ./env/bin/python -c "import dotenv" >/dev/null 2>&1; then
    echo "❌ Core Python dependencies are incomplete."
    echo "   Check internet access for pip and rerun: ./setup.sh"
    exit 1
fi

# 5. Setup Frontend Dependencies
if [ -d "frontend" ]; then
    echo "⚛️  Installing Frontend dependencies..."
    cd frontend
    if [ -f "package-lock.json" ]; then
        npm ci
    else
        npm install
    fi
    cd ..
else
    echo "⚠️  Frontend directory not found. Skipping frontend setup."
fi

# 6. Initialize Configuration Files
echo "⚙️  Initializing configuration files..."

# Determine data dir: 1. ENV, 2. Local ./data, 3. Default ~/aosd
if [ -n "$AOSD_DATA_DIR" ]; then
    DATA_DIR="$AOSD_DATA_DIR"
elif [ -d "data" ]; then
    DATA_DIR="$(pwd)/data"
else
    DATA_DIR="$HOME/aosd"
fi

echo "📂 Using data directory: $DATA_DIR"
mkdir -p "$DATA_DIR"

if [ ! -f "$DATA_DIR/config.json" ]; then
    if [ -f "config.json.example" ]; then
        echo "📝 Creating $DATA_DIR/config.json from example..."
        cp config.json.example "$DATA_DIR/config.json"
    else
        echo "⚠️  config.json.example not found."
    fi
else
    echo "✅ $DATA_DIR/config.json already exists."
fi

if [ ! -f "$DATA_DIR/.env" ]; then
    if [ -f ".env.example" ]; then
        echo "📝 Creating $DATA_DIR/.env from example..."
        cp .env.example "$DATA_DIR/.env"
    else
        echo "⚠️  .env.example not found."
    fi
else
    echo "✅ $DATA_DIR/.env already exists."
fi

# 7. Ensure encryption key for external OAuth token vault
ensure_external_accounts_key() {
    local env_file="$1"
    [ -f "$env_file" ] || return 0

    local existing_line existing_value generated_key
    existing_line="$(grep -E '^EXTERNAL_ACCOUNTS_ENCRYPTION_KEY=' "$env_file" 2>/dev/null || true)"
    existing_value="${existing_line#EXTERNAL_ACCOUNTS_ENCRYPTION_KEY=}"

    if [ -n "$existing_line" ] && [ -n "$existing_value" ]; then
        echo "✅ EXTERNAL_ACCOUNTS_ENCRYPTION_KEY already set in $env_file"
        return 0
    fi

    generated_key="$(python3 - <<'PY'
import os, base64
print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
)"

    if [ -z "$generated_key" ]; then
        echo "⚠️  Could not generate EXTERNAL_ACCOUNTS_ENCRYPTION_KEY for $env_file"
        return 0
    fi

    if [ -n "$existing_line" ]; then
        # Replace empty/invalid existing line
        sed -i "s|^EXTERNAL_ACCOUNTS_ENCRYPTION_KEY=.*$|EXTERNAL_ACCOUNTS_ENCRYPTION_KEY=$generated_key|g" "$env_file"
    else
        printf "\nEXTERNAL_ACCOUNTS_ENCRYPTION_KEY=%s\n" "$generated_key" >> "$env_file"
    fi

    echo "🔐 Generated EXTERNAL_ACCOUNTS_ENCRYPTION_KEY in $env_file"
}

ensure_external_accounts_key "$DATA_DIR/.env"
if [ -f ".env" ]; then
    ensure_external_accounts_key ".env"
fi

ensure_local_https_cert() {
    local cert_dir="$1"
    local cert_file="$cert_dir/localhost.crt"
    local key_file="$cert_dir/localhost.key"
    local openssl_cfg

    if [ -s "$cert_file" ] && [ -s "$key_file" ]; then
        echo "✅ HTTPS certificate already exists in $cert_dir"
        return 0
    fi

    if ! command -v openssl >/dev/null 2>&1; then
        echo "⚠️  openssl not found. Skipping HTTPS certificate generation."
        return 0
    fi

    mkdir -p "$cert_dir"
    openssl_cfg="$(mktemp)"
    cat > "$openssl_cfg" <<'EOF'
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = localhost

[v3_req]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
EOF

    if openssl req -x509 -nodes -newkey rsa:2048 \
        -days 825 \
        -keyout "$key_file" \
        -out "$cert_file" \
        -config "$openssl_cfg" >/dev/null 2>&1; then
        chmod 600 "$key_file"
        chmod 644 "$cert_file"
        echo "🔒 Generated self-signed HTTPS certificate:"
        echo "   Cert: $cert_file"
        echo "   Key:  $key_file"
    else
        echo "⚠️  Failed to generate HTTPS certificate in $cert_dir"
    fi

    rm -f "$openssl_cfg"
}

ensure_local_https_cert "$DATA_DIR/certs"

echo ""
echo "✨ Setup complete! ✨"

CLI_ENTRY="agent.py"

if [ "${AOSD_SKIP_PRIVILEGED_SETUP:-0}" != "1" ] && [ -x "./env/bin/python" ] && [ -f "$CLI_ENTRY" ]; then
    echo ""
    echo "🔐 Optional: enable safe sudo execution for approved commands."
    if [ -t 0 ]; then
        read -r -p "Configure now? [y/N]: " _priv_setup_ans
        case "${_priv_setup_ans}" in
            y|Y|yes|YES)
                echo "Running privileged setup..."
                ./env/bin/python "$CLI_ENTRY" doctor --setup-privileged || echo "⚠️  Privileged setup was not completed."
                ;;
            *)
                echo "Skipped privileged setup. You can run later:"
                echo "  ./env/bin/python $CLI_ENTRY doctor --setup-privileged"
                ;;
        esac
    elif [ "${AOSD_AUTO_PRIVILEGED_SETUP:-0}" = "1" ]; then
        echo "Non-interactive mode: running privileged setup (AOSD_AUTO_PRIVILEGED_SETUP=1)..."
        ./env/bin/python "$CLI_ENTRY" doctor --setup-privileged || echo "⚠️  Privileged setup was not completed."
    else
        echo "Tip: run this once to allow approved sudo commands without password prompt:"
        echo "  ./env/bin/python $CLI_ENTRY doctor --setup-privileged"
    fi
fi

echo "Next steps:
1. Configure your API keys in the $DATA_DIR/.env file.
2. Start the full system (Backend + Frontend) with: ./start.sh
   (Or run separately with ./run_server.sh and 'npm run dev' in frontend/)
"
