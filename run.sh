#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# GDMTH Solar Analyzer — startup script
# Usage: bash run.sh
# ─────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"

# Install/upgrade deps
echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q

echo "Starting Streamlit app..."
streamlit run "$SCRIPT_DIR/app/main.py" \
    --server.port 8501 \
    --server.headless false \
    --theme.base "light" \
    --theme.primaryColor "#FFD400" \
    --theme.backgroundColor "#F5F0E1" \
    --theme.secondaryBackgroundColor "#FAF6EB" \
    --theme.textColor "#15151A"
