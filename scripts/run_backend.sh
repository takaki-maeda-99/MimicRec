#!/bin/bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Created by install_user_services.sh. Keeping this outside the repository
# makes service control opt-in per host and avoids committing machine state.
SERVICE_CONTROL_ENV="${MIMICREC_SERVICE_CONTROL_ENV:-${XDG_CONFIG_HOME:-$HOME/.config}/mimicrec/service-control.env}"
if [[ -f "$SERVICE_CONTROL_ENV" ]]; then
    while IFS='=' read -r key value; do
        case "$key" in
            MIMICREC_SERVICE_CONTROL_ENABLED)
                export MIMICREC_SERVICE_CONTROL_ENABLED="$value"
                ;;
        esac
    done < "$SERVICE_CONTROL_ENV"
fi

export PYTHONNOUSERSITE=1
unset PYTHONPATH
export MIMICREC_CONFIGS_ROOT="$REPO_ROOT/configs"
export MIMICREC_DATASETS_ROOT="$REPO_ROOT/datasets"

mkdir -p "$MIMICREC_DATASETS_ROOT"

exec "$REPO_ROOT/.venv/bin/python" -m uvicorn mimicrec.api.app:app \
    --host 0.0.0.0 --port 8000 \
    --app-dir "$REPO_ROOT/backend"
