#!/bin/bash

# AOSD Setup Script
# This script prepares the environment for the AOSD project.

set -e

echo "🚀 Starting AOSD Setup..."

# 1. Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install it first."
    exit 1
fi

# 2. Check for Node.js
if ! command -v node &> /dev/null; then
    echo "⚠️  Node.js not found. Attempting to install..."
    if command -v apt-get &> /dev/null; then
        echo "📦 detected Debian/Ubuntu. Installing Node.js..."
        sudo apt-get update && sudo apt-get install -y nodejs npm
    else
        echo "❌ Node.js not found and couldn't auto-install. Please install Node.js manually: https://nodejs.org/"
        exit 1
    fi
else
    echo "✅ Node.js is already installed ($(node -v))."
fi

# 3. Setup Python Virtual Environment
echo "🐍 Creating Python virtual environment (env/)..."
rm -rf env
python3 -m venv env

echo "📦 Installing Python dependencies..."
./env/bin/pip install --upgrade pip
./env/bin/pip install -r requirements.txt

# 4. Setup Frontend Dependencies
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

# 5. Initialize Configuration Files
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

echo ""
echo "✨ Setup complete! ✨"
echo "Next steps:
1. Configure your API keys in the $DATA_DIR/.env file.
2. Start the full system (Backend + Frontend) with: ./start.sh
   (Or run separately with ./run_server.sh and 'npm run dev' in frontend/)
"
