#!/usr/bin/env bash
# MimicRec one-shot setup for Ubuntu 22.04 / 24.04.
#
# Idempotent: rerun any time. Each step checks before installing.
#
# Usage:
#     bash scripts/setup.sh                  # full setup
#     bash scripts/setup.sh --no-system      # skip apt + groups (no sudo prompt)
#     bash scripts/setup.sh --no-frontend    # skip Node / pnpm / frontend
#
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DO_SYSTEM=1
DO_FRONTEND=1
for arg in "$@"; do
    case "$arg" in
        --no-system) DO_SYSTEM=0 ;;
        --no-frontend) DO_FRONTEND=0 ;;
        -h|--help)
            sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown arg: $arg"; exit 2 ;;
    esac
done

# ---------- helpers ----------
have() { command -v "$1" >/dev/null 2>&1; }
log() { echo -e "\033[1;36m[setup]\033[0m $*"; }
warn() { echo -e "\033[1;33m[warn]\033[0m  $*" >&2; }
die() { echo -e "\033[1;31m[fail]\033[0m  $*" >&2; exit 1; }

# ---------- 0. OS sanity check ----------
if ! grep -qi ubuntu /etc/os-release 2>/dev/null; then
    warn "this script targets Ubuntu; other distros may need manual steps"
fi

# ---------- 1. System packages (apt) ----------
SYS_PKGS=(
    ffmpeg            # video encoding
    v4l-utils         # camera diagnostics
    libudev-dev       # serial device discovery
    pkg-config build-essential
    git git-lfs
    curl ca-certificates
)
if [[ $DO_SYSTEM -eq 1 ]]; then
    log "checking system packages: ${SYS_PKGS[*]}"
    MISSING=()
    for p in "${SYS_PKGS[@]}"; do
        dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p")
    done
    if [[ ${#MISSING[@]} -gt 0 ]]; then
        log "installing missing apt packages: ${MISSING[*]} (sudo)"
        sudo apt-get update
        sudo apt-get install -y "${MISSING[@]}"
    else
        log "system packages OK"
    fi
    if ! git lfs version >/dev/null 2>&1; then
        git lfs install --skip-repo
    fi
else
    log "skipping system package install (--no-system)"
fi

# ---------- 2. uv ----------
if ! have uv; then
    log "installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Make uv available in this session without re-sourcing the shell rc
    export PATH="$HOME/.local/bin:$PATH"
fi
have uv || die "uv install failed; install manually: https://docs.astral.sh/uv/"
log "uv $(uv --version)"

# ---------- 2b. Git submodules (lerobot, reBotArm) ----------
# Pinned via .gitmodules; idempotent — re-running is a no-op when up to date.
if [[ -f "$REPO_ROOT/.gitmodules" ]]; then
    log "syncing git submodules (lerobot, reBotArm_control_py)"
    git -C "$REPO_ROOT" submodule update --init --recursive
fi

# ---------- 3. Python venv + backend deps ----------
if [[ ! -d "$REPO_ROOT/.venv" ]]; then
    log "creating .venv with Python 3.12"
    uv venv "$REPO_ROOT/.venv" --python 3.12
else
    log ".venv already exists"
fi
PY="$REPO_ROOT/.venv/bin/python"

log "installing backend deps (mimicrec[dev,kinematics])"
uv pip install --python "$PY" -e "$REPO_ROOT/backend[dev,kinematics]"

log "installing lerobot + feetech extra"
uv pip install --python "$PY" -e "$REPO_ROOT/lerobot"
uv pip install --python "$PY" "lerobot[feetech]"

# ---------- 4. Frontend (Node + pnpm) ----------
if [[ $DO_FRONTEND -eq 1 ]]; then
    NEED_NODE=1
    if have node; then
        NODE_MAJOR=$(node -v | sed -E 's/^v([0-9]+)\..*/\1/')
        if [[ "$NODE_MAJOR" -ge 20 ]]; then
            NEED_NODE=0
            log "node $(node -v) OK"
        else
            warn "node $(node -v) < 20, will reinstall via NodeSource"
        fi
    fi
    if [[ $NEED_NODE -eq 1 ]]; then
        if [[ $DO_SYSTEM -eq 0 ]]; then
            warn "Node missing/old but --no-system specified; install Node 20+ manually"
        else
            log "installing Node 20 via NodeSource (sudo)"
            curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
            sudo apt-get install -y nodejs
        fi
    fi
    if ! have pnpm && have npm; then
        log "installing pnpm globally (sudo)"
        sudo npm install -g pnpm
    fi
    if have pnpm; then
        log "installing frontend deps"
        (cd "$REPO_ROOT/frontend" && pnpm install --frozen-lockfile 2>/dev/null || pnpm install)
    else
        warn "pnpm not available; skipping frontend deps"
    fi
else
    log "skipping frontend install (--no-frontend)"
fi

# ---------- 5. Hardware groups ----------
if [[ $DO_SYSTEM -eq 1 ]]; then
    NEEDED_GROUPS=()
    for g in dialout video; do
        if ! id -nG "$USER" | tr ' ' '\n' | grep -qx "$g"; then
            NEEDED_GROUPS+=("$g")
        fi
    done
    if [[ ${#NEEDED_GROUPS[@]} -gt 0 ]]; then
        log "adding $USER to groups: ${NEEDED_GROUPS[*]} (sudo)"
        sudo usermod -aG "$(IFS=,; echo "${NEEDED_GROUPS[*]}")" "$USER"
        warn "you must LOG OUT and BACK IN for new group membership to take effect"
        warn "(or run \`newgrp ${NEEDED_GROUPS[0]}\` for a temporary one-shell workaround)"
    else
        log "group memberships OK"
    fi
fi

# ---------- 6. Smoke test ----------
log "running quick import smoke test"
"$PY" - <<'PY'
import importlib
for mod in ("mimicrec", "fastapi", "uvicorn", "cv2", "pyarrow", "numpy", "av"):
    importlib.import_module(mod)
print("python deps import OK")
PY

cat <<EOF

------------------------------------------------------------------
✅ Setup complete.

Next steps:
  1. If groups changed, log out and back in.
  2. (Optional) Calibrate SO-101 arms:
       .venv/bin/python scripts/calibrate_so101.py \\
           --port /dev/ttyACM0 --id my_awesome_follower_arm --type follower
  3. Start the app:
       bash scripts/run.sh
       open http://localhost:5173
------------------------------------------------------------------
EOF
