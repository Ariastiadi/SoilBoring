#!/usr/bin/env bash
# Start backend (Uvicorn, auto-reload) and frontend (Vite) together for development.
#   ./dev.sh
#   BACKEND_PORT=9000 FRONTEND_PORT=5180 ./dev.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
# The Vite dev server forwards /api to the backend; keep it in sync with BACKEND_PORT.
export VITE_BACKEND_URL="${VITE_BACKEND_URL:-http://127.0.0.1:$BACKEND_PORT}"

if [[ -z "${UVICORN_CMD:-}" ]]; then
  if [[ -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
    UVICORN_CMD="$ROOT_DIR/.venv/bin/uvicorn"
  else
    UVICORN_CMD="uvicorn"
  fi
fi

log() {
  printf '[dev] %s\n' "$*"
}

BACKEND_PID=""
FRONTEND_PID=""

stop_pid() {
  local name=$1 pid=$2
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    log "Stopping $name (pid: $pid)…"
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
  fi
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  set +e
  stop_pid backend "$BACKEND_PID"
  stop_pid frontend "$FRONTEND_PID"
  exit "$exit_code"
}

trap cleanup EXIT
trap cleanup INT TERM

if ! command -v "$UVICORN_CMD" >/dev/null 2>&1; then
  log "Could not find uvicorn command: $UVICORN_CMD"
  log "Install the backend first: pip install -r backend/requirements.txt"
  log "(or set UVICORN_CMD=/path/to/uvicorn when it lives in another venv)."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  log "npm is required to run the frontend (Node.js 20.19+)."
  exit 1
fi

if [[ ! -x frontend/node_modules/.bin/vite ]]; then
  log "Installing frontend dependencies (npm ci)…"
  (cd frontend && npm ci)
fi

log "Starting backend on http://$BACKEND_HOST:$BACKEND_PORT"
"$UVICORN_CMD" backend.app.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
BACKEND_PID=$!

log "Starting frontend on http://$FRONTEND_HOST:$FRONTEND_PORT (API proxied to $VITE_BACKEND_URL)"
# exec: the PID we keep is Vite itself, so stopping it really stops the dev server.
(cd frontend && exec ./node_modules/.bin/vite --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort) &
FRONTEND_PID=$!

log "Press Ctrl+C to stop both services."

# When either process exits, the EXIT trap stops the other one.
wait -n "$BACKEND_PID" "$FRONTEND_PID"
