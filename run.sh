#!/usr/bin/env bash
# myforge — convenience launcher for dev.
# Starts FastAPI on :8000 and Streamlit on :8501.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "creating .venv..."
    python3 -m venv .venv
fi
source .venv/bin/activate

if ! python -c "import fastapi" 2>/dev/null; then
    echo "installing deps..."
    pip install -q -r requirements.txt
fi

if [ ! -f ".env" ]; then
    echo "copying .env.example -> .env (edit to add API keys)"
    cp .env.example .env
fi

# Start API in background
echo "starting FastAPI on :8000 ..."
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!

# Give API a moment to come up
sleep 2

# Start Streamlit in foreground
echo "starting Streamlit on :8501 ..."
streamlit run ui/app.py --server.port 8501 --server.headless true

# On exit, kill API
trap "kill $API_PID 2>/dev/null" EXIT
