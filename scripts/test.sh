#!/bin/bash
# MimicRec pytest runner.
#
# Isolates the backend venv from the host environment:
#   - PYTHONNOUSERSITE=1 prevents ~/.local/lib site-packages from leaking in
#     (blocked an older global `lerobot` from shadowing the editable install).
#   - unset PYTHONPATH drops /opt/ros/humble's PYTHONPATH so ROS-side packages
#     don't get imported during test collection.
#
# Use this instead of `uv run pytest` or bare `pytest` for anything in this
# repo. Pass-through args are forwarded to pytest, e.g.:
#   scripts/test.sh -q tests/unit
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTEST="$REPO_ROOT/.venv/bin/pytest"

if [[ ! -x "$VENV_PYTEST" ]]; then
    echo "error: $VENV_PYTEST not found. Run 'uv venv .venv' and install -e ./backend[dev]." >&2
    exit 1
fi

export PYTHONNOUSERSITE=1
unset PYTHONPATH

exec "$VENV_PYTEST" "$@"
