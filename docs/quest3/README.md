# Meta Quest 3 / ROS 2 teleoperation

This integration uses the Quest right controller as a clutched 6-DoF
end-effector input for reBotArm and makes active MimicRec cameras available in
the Quest viewer.

```text
Quest 3/3S
  └─ unity_ros_teleoperation
       ├─ /tf: hand_right pose
       ├─ /quest/joystick: grip/trigger state
       └─ ROS-TCP → ROS-TCP-Endpoint
                         │
                         ▼
               mimicrec_quest_bridge
                 ├─ WS clutch-relative pose → MimicRec → IK → reBotArm
                 └─ MimicRec JPEG → ROS CompressedImage → Quest viewer
```

## Safety model

- Motion is enabled only while the right grip axis is held above 0.5.
- The right index trigger directly maps 0=open to 1=closed. MimicRec smooths
  the native gripper target before sending it to the daemon.
- Pressing the grip latches the current controller pose; it never jumps the
  robot to an absolute Quest pose.
- Releasing the grip, stale `/tf` or Joy data, a WebSocket disconnect, and
  bridge shutdown all command an immediate software stop.
- After a bridge connection change, the operator must release and re-press the
  grip; motion never resumes merely because a network connection returned.
- The bridge bounds the absolute translation/rotation offset. MimicRec then
  independently bounds workspace, IK error and each commanded joint step.
- Fast absolute controller gestures are divided into bounded Cartesian steps
  before local IK. The robot may briefly lag a fast hand motion, but it keeps
  converging to the exact held controller pose instead of dropping a large IK
  jump.
- A discontinuous joint solution is never approached by clipping each joint
  independently. MimicRec halves the Cartesian step and solves again, then
  sends only a complete continuous IK solution.
- The active URDF joint limits are duplicated at the mapper and daemon safety
  boundaries. A low-weight posture task keeps the solver near the last sent
  configuration, and explicit IK velocity limits suppress branch changes.
- EEF translation is a hard IK constraint while orientation is soft. A wrist
  rotation may slow or stop near a kinematic limit, but the solver cannot
  trade away the pivot position and create a large downward arc.
- Selected URDF collision meshes are checked along every short joint path
  against a configurable table plane. A path below its clearance is rejected;
  if the arm starts below the plane, only a non-worsening escape step is
  allowed.
- With both scales at `1.0`, controller rotation is preserved as the same
  axis-angle amount; ROS/WebSocket/control-loop timing does not change it.
- The bridge resamples the clutch-relative SE(3) pose at a fixed command rate
  through a short fixed-delay interpolator. Bursty TF delivery is smoothed
  without shrinking the held final translation or rotation; releasing the
  grip discards the interpolation state immediately.
- Begin with the robot clear of people and obstacles, low scaling, and an
  operator ready to use the hardware E-stop.
- To return home, release the right grip and hold Quest **A** for 0.5 seconds.
  It is accepted only in a READY teleop session, ramps over two seconds,
  and requires a fresh grip/reference afterward.

## 1. Initialize and build

```bash
git submodule update --init --recursive
bash scripts/setup.sh
bash scripts/setup_quest_ros2.sh
```

The ROS helper builds both pinned `ROS-TCP-Endpoint` and
`mimicrec_quest_bridge` under the ignored `.ros2_quest_ws/` directory.

## 2. Configure the bridge

Edit
[`integrations/ros2/mimicrec_quest_bridge/config/quest3.yaml`](../../integrations/ros2/mimicrec_quest_bridge/config/quest3.yaml).
The default input is `/tf` child `hand_right`; the default deadman is right
grip (`Joy.axes[7]`). The right index trigger directly controls gripper
aperture (`0=open`, `1=closed`).

With `world_frame: vr_origin` and `motion_frame: world`,
`world_axis_rotation` maps Quest tracking-world axes to MimicRec's canonical
WORLD axes and is normally identity. `controller_to_eef_rotation` is separate:
it maps rotation relative to the grip-engagement orientation into the robot's
EEF-local axes for live control. For example, `quest3_left.yaml` maps the
controller twist axis to SO-101 wrist roll without rotating the WORLD action
recorded in the dataset. Robot-specific WORLD-to-base conversion is handled
later by the Motion Group mapper. Verify one axis at a time with low
`translation_scale` and `rotation_scale`; any calibration matrix must be
orthonormal with determinant `+1` (no scale, shear, or reflection).

The WebSocket bridge sends the clutch-relative absolute WORLD offset plus the
separate clutch-local control rotation. MimicRec derives and records the
per-step `SE3Delta` only from consecutive WORLD offsets; the absolute values
are control metadata used so an IK or joint-rate limit delays a target rather
than dropping motion permanently.
Keep the Quest palm menu's **TF Decimator** at `1`. Disable Hand Publishing
when hand landmarks are not in use so those messages do not contend with TF
on the shared ROS-TCP connection.

## 3. Start MimicRec and a Quest session

```bash
bash scripts/run.sh
```

In the Record page start a teleop session with:

- Robot: `rebotarm`
- Teleop: `quest_ros`
- Mapper: `delta_ee_to_rebotarm`
- Cameras: the slots listed in the bridge config (`front`, `wrist` by default)
- Preview: enabled (required for Quest camera forwarding)

Equivalent API request:

```bash
curl -X POST http://127.0.0.1:8000/api/session/start \
  -H 'content-type: application/json' \
  -d '{
    "mode":"teleop", "dataset":"quest_demo", "task":"pick",
    "robot":"rebotarm", "teleop":"quest_ros",
    "mapper":"delta_ee_to_rebotarm",
    "cameras":["front","wrist"], "fps":30,
    "preview_enabled":true
  }'
```

## 4. Start ROS 2 and connect Quest

```bash
bash scripts/run_quest_ros2.sh
```

In the Quest palm menu, connect to the Ubuntu PC's LAN address on TCP port
`10000`. Do not use `localhost`. Confirm these inputs before holding the grip:

```bash
ros2 topic echo /tf --once
ros2 topic echo /quest/joystick --once
```

MimicRec camera topics appear as:

```text
/mimicrec/cameras/front/image_raw/compressed
/mimicrec/cameras/wrist/image_raw/compressed
```

Add either topic from the Quest Image Views menu. The Unity project supports
`sensor_msgs/CompressedImage` directly, so the JPEG is not decoded and
re-encoded by the bridge.

To diagnose whether control limits or IK accuracy are causing a mismatch,
inspect the current teleoperation gauges without starting another process:

```bash
curl http://127.0.0.1:8000/api/session/teleop-metrics
```

The response separates the controller's desired pose, the current slew-limited
IK target, the last command, and measured EEF pose. It also reports IK
residuals and whether either the Cartesian or joint-step limiter was active.

## Detailed guides

- [Ubuntu 22.04からQuestへビルド](ubuntu_build_ja.md)
- [Quest内の操作・ROS可視化](operation_ja.md)
