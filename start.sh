#!/bin/bash

# AOSD Startup Script

# Colores para el log
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}>>> Starting AOSD Integrated System...${NC}"

# Ensure we are in the project root
cd "$(dirname "$0")"

PYTHON_BIN="python3"
NODE_MIN_MAJOR=18
NODE_MIN_MINOR=0

# Try to load NVM automatically
if [ -s "$HOME/.nvm/nvm.sh" ]; then
    source "$HOME/.nvm/nvm.sh"
fi

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

# Auto-install or use Node 20 via NVM if current version is not OK
if ! node_version_ok; then
    if [ -s "$HOME/.nvm/nvm.sh" ]; then
        echo -e "${YELLOW}[System]${NC} Node version is below 20.19. Attempting to use NVM to fix..."
        nvm install 20
        nvm use 20
    fi
fi

# 0. Activate Virtual Environment
if [ -f "env/bin/activate" ]; then
    echo -e "${GREEN}[System]${NC} Activating Virtual Environment..."
    source env/bin/activate
    PYTHON_BIN="$(pwd)/env/bin/python"
else
    echo -e "${YELLOW}[Warning]${NC} Virtual environment 'env' not found. Continuing with system python..."
fi

if ! "$PYTHON_BIN" -c "import dotenv" >/dev/null 2>&1; then
    echo -e "${RED}[Error]${NC} Python dependencies not available for: $PYTHON_BIN"
    echo -e "${YELLOW}[Fix]${NC} Run ./setup.sh after installing system deps:"
    echo "      sudo apt-get update && sudo apt-get install -y python3-venv nodejs npm"
    exit 1
fi

# Optional privileged setup health check (sudo/NOPASSWD helper for approved shell commands)
CLI_ENTRY="agent.py"

if [ "${AOSD_SKIP_PRIVILEGED_CHECK:-0}" != "1" ] && [ -f "$CLI_ENTRY" ]; then
    if "$PYTHON_BIN" "$CLI_ENTRY" doctor --check-privileged >/dev/null 2>&1; then
        echo -e "${GREEN}[Security]${NC} Privileged sudo setup detected."
    else
        echo -e "${YELLOW}[Security]${NC} Privileged sudo setup not active."
        echo -e "${YELLOW}[Hint]${NC} Run once: $PYTHON_BIN $CLI_ENTRY doctor --setup-privileged"
        if [ "${AOSD_AUTO_PRIVILEGED_SETUP:-0}" = "1" ]; then
            echo -e "${BLUE}[Security]${NC} AOSD_AUTO_PRIVILEGED_SETUP=1 enabled. Attempting setup now..."
            "$PYTHON_BIN" "$CLI_ENTRY" doctor --setup-privileged || \
                echo -e "${YELLOW}[Security]${NC} Auto-setup failed or was cancelled."
        fi
    fi
fi

# 1. Read Configuration for Ports
echo -e "${GREEN}[System]${NC} Reading configuration..."
BACKEND_PORT=$("$PYTHON_BIN" -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('interfaces', {}).get('server', {}).get('port', 8000))")
FRONTEND_PORT=$("$PYTHON_BIN" -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('frontend', {}).get('port', 5173))")
BACKEND_HOST=$("$PYTHON_BIN" -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('interfaces', {}).get('server', {}).get('host', '0.0.0.0'))")
FRONTEND_PUBLIC=$("$PYTHON_BIN" -c "import json,os; conf=json.load(open('data/config.json')); print(str(conf.get('frontend', {}).get('public_mode', False)).lower())")
FRONTEND_HOST=$("$PYTHON_BIN" -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('frontend', {}).get('host', 'localhost'))")
BACKEND_TLS_ENABLED=$("$PYTHON_BIN" -c "import json,os; conf=json.load(open('data/config.json')); print(str(conf.get('interfaces', {}).get('server', {}).get('tls', {}).get('enabled', True)).lower())")
BACKEND_TLS_CERT=$("$PYTHON_BIN" -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('interfaces', {}).get('server', {}).get('tls', {}).get('certfile', 'data/certs/localhost.crt'))")
BACKEND_TLS_KEY=$("$PYTHON_BIN" -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('interfaces', {}).get('server', {}).get('tls', {}).get('keyfile', 'data/certs/localhost.key'))")
BACKEND_TLS_CERT_ABS=$("$PYTHON_BIN" -c "import os; print(os.path.abspath('$BACKEND_TLS_CERT'))")
BACKEND_TLS_KEY_ABS=$("$PYTHON_BIN" -c "import os; print(os.path.abspath('$BACKEND_TLS_KEY'))")

# If public mode is ON, we bind to 0.0.0.0 to allow external access
if [ "$FRONTEND_PUBLIC" = "true" ]; then
    echo -e "${YELLOW}[System]${NC} Public Mode detected. Binding Frontend to 0.0.0.0"
    FRONTEND_HOST="0.0.0.0"
fi

BACKEND_SCHEME="http"
if [ "$BACKEND_TLS_ENABLED" = "true" ] && [ -f "$BACKEND_TLS_CERT_ABS" ] && [ -f "$BACKEND_TLS_KEY_ABS" ]; then
    BACKEND_SCHEME="https"
fi
FRONTEND_SCHEME="$BACKEND_SCHEME"

echo -e "${GREEN}[System]${NC} Configured Backend: $BACKEND_SCHEME://$BACKEND_HOST:$BACKEND_PORT"
echo -e "${GREEN}[System]${NC} Configured Frontend: $FRONTEND_SCHEME://$FRONTEND_HOST:$FRONTEND_PORT"

# 2. Start Backend (Agent Kernel + API)
echo -e "${GREEN}[Backend]${NC} Starting Agent Kernel and Portal API..."
export PYTHONPATH=$PYTHONPATH:$(pwd)/src
BOOT_LOG_DIR="$(pwd)/data/logs"
BOOT_LOG_FILE="$BOOT_LOG_DIR/start_backend.log"
mkdir -p "$BOOT_LOG_DIR"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting backend bootstrap..." >> "$BOOT_LOG_FILE"
"$PYTHON_BIN" src/main.py \
    > >(tee -a "$BOOT_LOG_FILE") \
    2> >(tee -a "$BOOT_LOG_FILE" >&2) &
BACKEND_PID=$!

# 3. Wait for Backend port to be ready
echo -e "${GREEN}[System]${NC} Waiting for Backend API to be ready on port $BACKEND_PORT..."
MAX_RETRIES=60
COUNT=0
while ! "$PYTHON_BIN" -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(1); s.connect(('127.0.0.1', $BACKEND_PORT)); s.close()" 2>/dev/null; do
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
        echo -e "${RED}[Error]${NC} Backend process exited before binding port $BACKEND_PORT."
        echo -e "${YELLOW}[Log]${NC} Last backend lines ($BOOT_LOG_FILE):"
        tail -n 80 "$BOOT_LOG_FILE" 2>/dev/null || true
        echo -e "${YELLOW}[Fix]${NC} Run in foreground for traceback:"
        echo "      PYTHONPATH=\$PYTHONPATH:$(pwd)/src $PYTHON_BIN src/main.py"
        exit 1
    fi
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo -e "${RED}[Error]${NC} Backend failed to start on port $BACKEND_PORT within ${MAX_RETRIES}s"
        echo -e "${YELLOW}[Log]${NC} Last backend lines ($BOOT_LOG_FILE):"
        tail -n 80 "$BOOT_LOG_FILE" 2>/dev/null || true
        if kill -0 $BACKEND_PID 2>/dev/null; then
            kill $BACKEND_PID
        fi
        exit 1
    fi
done
echo -e "${GREEN}[System]${NC} Backend is online!"

# 4. Start Frontend (Vite)
FRONTEND_PID=""
if node_version_ok; then
    echo -e "${GREEN}[Frontend]${NC} Starting React Developer Console..."
    cd frontend
    # Exporting vars for Vite
    export VITE_PORT=$FRONTEND_PORT
    export VITE_HOST=$FRONTEND_HOST
    export VITE_HTTPS=true
    export VITE_SSL_CERT_FILE="$BACKEND_TLS_CERT_ABS"
    export VITE_SSL_KEY_FILE="$BACKEND_TLS_KEY_ABS"
    export VITE_API_URL="$BACKEND_SCHEME://127.0.0.1:$BACKEND_PORT"
    npm run dev -- --host $VITE_HOST &
    FRONTEND_PID=$!
else
    echo -e "${YELLOW}[Frontend]${NC} Skipped: Node $(node -v 2>/dev/null || echo 'not installed') is below required >= v${NODE_MIN_MAJOR}.${NODE_MIN_MINOR}."
    echo -e "${YELLOW}[Fix]${NC} Upgrade Node (recommended nvm):"
    echo "      nvm install 20.19.0 && nvm use 20.19.0"
    echo -e "${YELLOW}[Info]${NC} Backend is running without frontend."
fi

# Handle shutdown
cleanup() {
    echo -e "\n${BLUE}>>> Shutting down AOSD...${NC}"
    if kill -0 $BACKEND_PID 2>/dev/null; then
        kill $BACKEND_PID
    fi
    if kill -0 $FRONTEND_PID 2>/dev/null; then
        kill $FRONTEND_PID
    fi
    exit
}

trap cleanup SIGINT

echo -e "${BLUE}>>> System is running!${NC}"
echo -e "${BLUE}>>> Backend API: $BACKEND_SCHEME://localhost:$BACKEND_PORT"
if [ -n "$FRONTEND_PID" ]; then
    echo -e "${BLUE}>>> Frontend Console: $FRONTEND_SCHEME://localhost:$FRONTEND_PORT"
else
    echo -e "${BLUE}>>> Frontend Console: skipped (Node upgrade required)"
fi

# Keep script alive
wait
