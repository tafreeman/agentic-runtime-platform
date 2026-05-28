#!/usr/bin/env bash
# dev.sh — Kill existing servers and start backend + frontend for local development.
# Usage: bash dev.sh [backend_port] [frontend_port]
#   Defaults: backend=8010, frontend=5173

set -e

BACKEND_PORT="${1:-8010}"
FRONTEND_PORT="${2:-5173}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Killing existing processes on ports $BACKEND_PORT and $FRONTEND_PORT..."

# Kill anything on the backend port
if command -v lsof &>/dev/null; then
  lsof -ti :"$BACKEND_PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  lsof -ti :"$FRONTEND_PORT" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
elif command -v netstat &>/dev/null; then
  # Windows/Git Bash fallback
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    pid=$(netstat -ano 2>/dev/null | grep ":${port} " | grep LISTENING | awk '{print $5}' | head -1)
    if [ -n "$pid" ] && [ "$pid" != "0" ]; then
      taskkill //F //PID "$pid" 2>/dev/null || true
    fi
  done
fi

echo "==> Starting backend on port $BACKEND_PORT..."
cd "$SCRIPT_DIR"
python -m uvicorn agentic_v2.server.app:app \
  --host 127.0.0.1 \
  --port "$BACKEND_PORT" \
  --app-dir src \
  --reload &
BACKEND_PID=$!

echo "==> Starting frontend on port $FRONTEND_PORT (proxying to backend:$BACKEND_PORT)..."
cd "$SCRIPT_DIR/ui"
VITE_API_PROXY_TARGET="http://localhost:$BACKEND_PORT" npx vite --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

echo ""
echo "========================================"
echo "  Backend:  http://127.0.0.1:$BACKEND_PORT"
echo "  Frontend: http://localhost:$FRONTEND_PORT"
echo "  Health:   http://127.0.0.1:$BACKEND_PORT/api/health"
echo "========================================"
echo ""
echo "Press Ctrl+C to stop both servers."

# Trap Ctrl+C to kill both processes
cleanup() {
  echo ""
  echo "==> Shutting down..."
  kill "$BACKEND_PID" 2>/dev/null || true
  kill "$FRONTEND_PID" 2>/dev/null || true
  wait
  echo "==> Done."
}
trap cleanup INT TERM

wait
