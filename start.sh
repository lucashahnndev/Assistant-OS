#!/bin/bash

# AOSD Startup Script

# Colores para el log
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}>>> Starting AOSD Integrated System...${NC}"

# Ensure we are in the project root
cd "$(dirname "$0")"

# 0. Activate Virtual Environment
if [ -f "env/bin/activate" ]; then
    echo -e "${GREEN}[System]${NC} Activating Virtual Environment..."
    source env/bin/activate
else
    echo -e "${YELLOW}[Warning]${NC} Virtual environment 'env' not found. Continuing with system python..."
fi

# 1. Read Configuration for Ports
echo -e "${GREEN}[System]${NC} Reading configuration..."
BACKEND_PORT=$(python3 -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('interfaces', {}).get('server', {}).get('port', 8000))")
FRONTEND_PORT=$(python3 -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('frontend', {}).get('port', 5173))")
BACKEND_HOST=$(python3 -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('interfaces', {}).get('server', {}).get('host', '0.0.0.0'))")
FRONTEND_PUBLIC=$(python3 -c "import json,os; conf=json.load(open('data/config.json')); print(str(conf.get('frontend', {}).get('public_mode', False)).lower())")
FRONTEND_HOST=$(python3 -c "import json,os; conf=json.load(open('data/config.json')); print(conf.get('frontend', {}).get('host', 'localhost'))")

# If public mode is ON, we bind to 0.0.0.0 to allow external access
if [ "$FRONTEND_PUBLIC" = "true" ]; then
    echo -e "${YELLOW}[System]${NC} Public Mode detected. Binding Frontend to 0.0.0.0"
    FRONTEND_HOST="0.0.0.0"
fi

echo -e "${GREEN}[System]${NC} Configured Backend: http://$BACKEND_HOST:$BACKEND_PORT"
echo -e "${GREEN}[System]${NC} Configured Frontend: http://$FRONTEND_HOST:$FRONTEND_PORT"

# 2. Start Backend (Agent Kernel + API)
echo -e "${GREEN}[Backend]${NC} Starting Agent Kernel and Portal API..."
export PYTHONPATH=$PYTHONPATH:$(pwd)/src
python3 src/main.py &
BACKEND_PID=$!

# 3. Wait for Backend port to be ready
echo -e "${GREEN}[System]${NC} Waiting for Backend API to be ready on port $BACKEND_PORT..."
MAX_RETRIES=60
COUNT=0
while ! python3 -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(1); s.connect(('127.0.0.1', $BACKEND_PORT)); s.close()" 2>/dev/null; do
    sleep 1
    COUNT=$((COUNT+1))
    if [ $COUNT -ge $MAX_RETRIES ]; then
        echo -e "${RED}[Error]${NC} Backend failed to start on port $BACKEND_PORT within ${MAX_RETRIES}s"
        kill $BACKEND_PID
        exit 1
    fi
done
echo -e "${GREEN}[System]${NC} Backend is online!"

# 4. Start Frontend (Vite)
echo -e "${GREEN}[Frontend]${NC} Starting React Developer Console..."
cd frontend
# Exporting vars for Vite
export VITE_PORT=$FRONTEND_PORT
export VITE_HOST=$FRONTEND_HOST
export VITE_API_URL="http://127.0.0.1:$BACKEND_PORT"
npm run dev -- --host $VITE_HOST &
FRONTEND_PID=$!

# Handle shutdown
cleanup() {
    echo -e "\n${BLUE}>>> Shutting down AOSD...${NC}"
    kill $BACKEND_PID
    kill $FRONTEND_PID
    exit
}

trap cleanup SIGINT

echo -e "${BLUE}>>> System is running!${NC}"
echo -e "${BLUE}>>> Backend API: http://localhost:$BACKEND_PORT"
echo -e "${BLUE}>>> Frontend Console: http://localhost:$FRONTEND_PORT"

# Keep script alive
wait
