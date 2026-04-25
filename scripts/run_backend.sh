#!/bin/bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export PYTHONNOUSERSITE=1
unset PYTHONPATH
export MIMICREC_CONFIGS_ROOT="$REPO_ROOT/configs"
export MIMICREC_DATASETS_ROOT="$REPO_ROOT/datasets"

mkdir -p "$MIMICREC_DATASETS_ROOT"

exec "$REPO_ROOT/.venv/bin/python" -m uvicorn mimicrec.api.app:app \
    --host 0.0.0.0 --port 8000 \
    --app-dir "$REPO_ROOT/backend"
