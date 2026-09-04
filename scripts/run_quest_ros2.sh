#!/usr/bin/env bash
# Run the Unity ROS TCP endpoint and the MimicRec Quest bridge together.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUEST_WS="$REPO_ROOT/.ros2_quest_ws"
CONFIG="${MIMICREC_QUEST_CONFIG:-$REPO_ROOT/integrations/ros2/mimicrec_quest_bridge/config/quest3.yaml}"
LEFT_CONFIG="${MIMICREC_QUEST_LEFT_CONFIG:-$REPO_ROOT/integrations/ros2/mimicrec_quest_bridge/config/quest3_left.yaml}"

if [[ ! -f "$QUEST_WS/install/setup.bash" ]]; then
    echo "error: Quest ROS workspace is not built; run scripts/setup_quest_ros2.sh" >&2
    exit 1
fi

set +u
# shellcheck disable=SC1091
source /opt/ros/humble/setup.bash
# shellcheck disable=SC1091
source "$QUEST_WS/install/setup.bash"
set -u

# Both controller bridges are cheap while idle and MotionGraph routes their
# explicitly tagged channels independently. Default to bimanual so selecting a
# two-arm profile cannot silently launch only hand_right. Set the variable to 0
# in ~/.config/mimicrec/quest.env for an intentionally right-only deployment.
if [[ "${MIMICREC_QUEST_BIMANUAL:-1}" == "1" ]]; then
    exec ros2 launch mimicrec_quest_bridge mimicrec_quest_bimanual.launch.py \
        right_config:="$CONFIG" left_config:="$LEFT_CONFIG" \
        run_endpoint:=true endpoint_host:=0.0.0.0 endpoint_port:=10000
fi

exec ros2 launch mimicrec_quest_bridge mimicrec_quest_bridge.launch.py \
    config:="$CONFIG" run_endpoint:=true endpoint_host:=0.0.0.0 endpoint_port:=10000
