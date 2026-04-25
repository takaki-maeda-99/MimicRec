#!/bin/bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Starting MimicRec..."
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:5173"
echo ""

# Run backend in background
"$REPO_ROOT/scripts/run_backend.sh" &
BACKEND_PID=$!

# Run frontend in foreground
"$REPO_ROOT/scripts/run_frontend.sh" &
FRONTEND_PID=$!

# Handle Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

wait
