# MimicRec Quest ROS 2 bridge

This ROS 2 package closes the gap between
`leggedrobotics/unity_ros_teleoperation` and MimicRec:

- reads the right controller from `/tf` (`hand_right` by default);
- uses `/quest/joystick` right grip as a hold-to-move deadman;
- maps the right index trigger directly to gripper aperture;
- emits a one-shot home request after Quest A is held with the grip released;
- resolves controller TF into the configured world frame and publishes a
  clutch-relative absolute WORLD offset through a fixed-delay interpolator;
- lets MimicRec derive canonical per-step WORLD `SE3Delta` for recording
  while robot mappers retain the absolute target for lossless convergence;
- publishes a separate clutch-local rotation offset for live embodiment
  control, so robot-specific wrist axes do not alter the recorded WORLD data;
- stops on deadman release, stale ROS input, WebSocket loss, or node exit;
- republishes MimicRec JPEG previews as ROS `sensor_msgs/CompressedImage`.

The bridge expects an active MimicRec motion session using the
`quest_bimanual_rebot_so101` profile (or a compatible `quest_ros` input).

Build from a sourced ROS 2 Humble shell:

```bash
mkdir -p ros2_ws/src
ln -s "$PWD/integrations/ros2/mimicrec_quest_bridge" \
  ros2_ws/src/mimicrec_quest_bridge
cd ros2_ws
rosdep install --from-paths src --ignore-src --recursive --yes
colcon build --symlink-install
source install/setup.bash
ros2 launch mimicrec_quest_bridge mimicrec_quest_bridge.launch.py
```

The launch file starts both the TCP endpoint and the MimicRec bridge. Pass
`run_endpoint:=false` when an endpoint already runs elsewhere on the ROS graph.

Edit `config/quest3.yaml` before moving hardware. In particular, verify the
`world_frame` (normally Unity's `vr_origin`), `motion_frame` (`world`), and
`world_axis_rotation` and `controller_to_eef_rotation` one axis at a time at
low speed, and
keep the right grip released until the robot and Quest controller are both in
known poses. In WORLD mode, `world_axis_rotation` defines the canonical axes
used for recording and is normally identity. `controller_to_eef_rotation`
affects only clutch-local live rotation control; the left SO-101 configuration
maps controller-local X twist to EEF-local Z wrist roll. Robot WORLD-to-base
conversion still belongs in the Motion Group mapper. Any calibration matrix
must be a proper rotation.
