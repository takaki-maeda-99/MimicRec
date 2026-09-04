#!/usr/bin/env bash
# Build the pinned Unity ROS TCP endpoint and MimicRec Quest bridge in an
# isolated ROS 2 workspace. Targets Ubuntu 22.04 / ROS 2 Humble.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUEST_WS="$REPO_ROOT/.ros2_quest_ws"
DO_SYSTEM=1
if [[ "${1:-}" == "--no-system" ]]; then
    DO_SYSTEM=0
elif [[ -n "${1:-}" ]]; then
    echo "usage: $0 [--no-system]" >&2
    exit 2
fi

if [[ ! -f /opt/ros/humble/setup.bash ]]; then
    echo "error: ROS 2 Humble not found at /opt/ros/humble" >&2
    exit 1
fi
if [[ ! -d "$REPO_ROOT/third_party/ROS-TCP-Endpoint" ]]; then
    echo "error: initialize submodules first: git submodule update --init --recursive" >&2
    exit 1
fi

if [[ $DO_SYSTEM -eq 1 ]]; then
    missing=()
    for package in python3-colcon-common-extensions python3-rosdep python3-websockets; do
        dpkg -s "$package" >/dev/null 2>&1 || missing+=("$package")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        sudo apt-get update
        sudo apt-get install -y "${missing[@]}"
    fi
fi

mkdir -p "$QUEST_WS/src"
ln -sfn "$REPO_ROOT/third_party/ROS-TCP-Endpoint" \
    "$QUEST_WS/src/ROS-TCP-Endpoint"
ln -sfn "$REPO_ROOT/integrations/ros2/mimicrec_quest_bridge" \
    "$QUEST_WS/src/mimicrec_quest_bridge"

# ROS setup scripts read optional variables without guarding them and are not
# compatible with nounset while being sourced.
set +u
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
set -u
if [[ $DO_SYSTEM -eq 1 ]] && command -v rosdep >/dev/null 2>&1; then
    rosdep install --from-paths "$QUEST_WS/src" --ignore-src --recursive --yes
fi

cd "$QUEST_WS"
PYTHONNOUSERSITE=1 colcon build --symlink-install

echo "Quest ROS 2 workspace ready."
echo "Run: bash scripts/run_quest_ros2.sh"
