# Third-party dependencies

This directory contains pinned Git submodules. Their gitlinks always reference
commits available from the configured public remotes. MimicRec-specific local
changes are stored as reviewable files under `patches/` and applied by
`scripts/apply_third_party_patches.sh`; they are not pushed to these upstream
repositories.

| Directory | Upstream/fork | Purpose |
|---|---|---|
| `lerobot/` | `takaki-maeda-99/lerobot` | LeRobot datasets, SO-101 drivers, and kinematics |
| `reBotArm_control_py/` | `takaki-maeda-99/reBotArm_control_py` | reBotArm hardware, dynamics, and kinematics SDK |
| `ROS-TCP-Endpoint/` | `leggedrobotics/ROS-TCP-Endpoint` (`main-ros2`) | Unity-to-ROS 2 TCP endpoint |
| `unity_ros_teleoperation/` | `leggedrobotics/unity_ros_teleoperation` | Quest 3 XR visualization and ROS input application |

Run `bash scripts/setup.sh` after cloning. It initializes the submodules and
applies the portable overlays idempotently. To do only those two steps, run:

```bash
git submodule update --init --recursive
bash scripts/apply_third_party_patches.sh
```

The patched submodules intentionally appear as modified in `git status`.
Do not commit their dirty gitlinks. Generated ROS build directories, Unity's
selected deployment-device ID, and local Git-hook mode changes are excluded
from the overlays.

MimicRec-authored Quest setup and integration material lives in
`docs/quest3/`, not in these upstream working trees.
