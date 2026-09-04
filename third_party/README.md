# Third-party dependencies

This directory contains pinned Git submodules. MimicRec code lives outside
this directory; changes to a dependency should be made in its upstream fork
and then consumed here by updating the submodule commit.

| Directory | Upstream/fork | Purpose |
|---|---|---|
| `lerobot/` | `takaki-maeda-99/lerobot` | LeRobot datasets, SO-101 drivers, and kinematics |
| `reBotArm_control_py/` | `takaki-maeda-99/reBotArm_control_py` | reBotArm hardware, dynamics, and kinematics SDK |
| `ROS-TCP-Endpoint/` | `leggedrobotics/ROS-TCP-Endpoint` (`main-ros2`) | Unity-to-ROS 2 TCP endpoint |
| `unity_ros_teleoperation/` | `leggedrobotics/unity_ros_teleoperation` | Quest 3 XR visualization and ROS input application |

Run `git submodule update --init --recursive` after cloning.

MimicRec-authored Quest setup and integration material lives in
`docs/quest3/`, not in these upstream working trees.
