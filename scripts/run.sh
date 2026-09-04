#!/bin/bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Starting MimicRec..."
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo "  Remote browser: use a Network URL printed by Vite below"
echo ""

# Run backend in background
"$REPO_ROOT/scripts/run_backend.sh" &
BACKEND_PID=$!

# Run frontend in foreground
"$REPO_ROOT/scripts/run_frontend.sh" &
FRONTEND_PID=$!

cleanup() {
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# If either half fails, stop the other half too instead of leaving a backend-
# only process that makes the printed frontend link look mysteriously broken.
set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
STATUS=$?
set -e
exit "$STATUS"
