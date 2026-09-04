# SE3Delta Motion Graph

MimicRec's multi-device path is organized around motion intent rather than a
hard-coded robot combination. A Motion Group consumes one stream of SE(3)
increments and emits commands for one or more named hardware resources.

```text
Quest / replay / policy
        │
        ▼
SE3Delta MotionStep
        │
        ▼
Motion Group mapper
        │
        ├── right_robot.arm
        ├── right_robot.gripper
        ├── left_robot.arm
        └── mobile_base.drive
```

## SE3Delta convention

`SE3Delta.tangent` is ordered as:

```text
[rho_x, rho_y, rho_z, phi_x, phi_y, phi_z]
```

It is one step of displacement, not a velocity. The vector is the logarithm
of an SE(3) transform. `frame` records the coordinate basis used by that
step. Local/body increments use:

```text
T_next = T_current @ Exp(delta)
```

The included Quest bimanual profile instead records `frame: world`. Its
translation is the displacement of the tracked controller point and its
rotation is a spatial/world increment. Mappers rotate those two components
into each robot base immediately before embodiment projection. A WORLD
rotation is never implemented as `Exp(delta) @ T_current`, because that would
incorrectly orbit the EEF about the world origin.

Live Quest control also carries the clutch-relative absolute WORLD offset as
non-tokenized control metadata. Rotation control has a second, clutch-local
offset: the controller orientation at grip engagement is aligned with the
current robot EEF orientation, then controller-local axes are mapped to the
EEF's reachable axes. This lets an SO-101 controller twist command wrist roll
without changing the canonical WORLD rotation stored in the dataset. The
backend differentiates only the WORLD offset into the canonical `SE3Delta`
above for recording, replay, and policies.

Hardware mappers use the absolute offsets to retain rate-limited error across
ticks; joint limits or IK backtracking therefore slow convergence instead of
permanently deleting part of the operator's motion.

Velocity conversion is explicit:

```text
delta = velocity * duration_sec
velocity = delta / duration_sec
```

Named joint resources use radians and radians/second. Hardware-native units
(for example the SO-101 daemon's degrees) are converted only at the Adapter
boundary. Gripper resources remain explicitly mechanism-native scalar values.

Do not add increments when combining steps. Compose `Exp(delta_i)` in order
and take `Log` of the result. `backend/mimicrec/motion/se3.py` provides the
authoritative implementation.

## Included bimanual profile

`configs/motion_profiles/quest_bimanual_rebot_so101.yaml` defines:

- right Quest controller → right reBotArm arm and gripper;
- left Quest controller → left SO-101 arm and gripper;
- independent 60 Hz Motion Groups;
- namespaced state and recording fields;
- exclusive resource claims, checked before hardware is opened.

Both controller streams are recorded as canonical WORLD `SE3Delta` values.
The profile's `world_to_base_rotation` values are the only required static
calibration while each robot base is fixed and axis-aligned. A future moving
base can replace that rotation with a timestamped TF lookup without changing
the dataset schema.

The SO-101 mapper uses hierarchical differential IK: EEF position is the
primary 3D task and orientation is solved only in its joint-space nullspace.
The unavailable rotational component is discarded per step and reported in
`ik_rotation_projection_residual_rad`; it cannot accumulate into an IK branch
jump or be exchanged for EEF translation. Position consumes the joint-step
budget first. Weak rotation singular directions and projections that point
mostly along a different axis are discarded before the remaining joint
budget is assigned to orientation. Position uses bounded least squares with
the SO-101 URDF joint limits, so when wrist flex is near its limit the solver
uses shoulder/elbow redundancy to continue moving along a feasible WORLD
direction instead of clipping the wrist and losing that Cartesian motion. A
joint metric penalizes wrist use in the redundant position solve: translation
is produced primarily by shoulder/elbow motion, leaving wrist flex/roll for
the controller's rotation request instead of spending wrist travel on the
small tool-frame offset.

The Record page's named-resource table exposes three joint values while a
Motion Graph is active: measured state, the target accepted by the daemon,
and the mapper target. This makes unit/order/sign or daemon clamping problems
distinguishable from IK output without adding a second hardware client.

Select **Motion Graph** and `quest_bimanual_rebot_so101` on the Record page,
or start it through the API:

```json
{
  "mode": "motion",
  "profile": "quest_bimanual_rebot_so101",
  "dataset": "bimanual_demo",
  "task": "pick",
  "fps": 30,
  "slot_assignments": [
    {"slot": "front", "device": "front"},
    {"slot": "wrist", "device": "wrist"}
  ]
}
```

## Visual profile editor

Open a Motion Profile from the Record screen or Settings → Motion Graph. The
visual editor treats adapters, inputs, and Motion Groups as cards and renders
the resulting `input → SE3Delta group → resource` connections before saving.

It supports single-arm, bimanual, and empty presets; named resource editing;
Home pose assignment; resource-claim conflict checks; missing config checks;
and five-DoF reachability warnings. Advanced JSON remains available for
mapper-specific arguments and future graph features. The backend builds the
profile without connecting hardware before it writes the YAML, so a diagram
that cannot become an executable runtime is rejected rather than saved.

## Hardware daemons

The daemon is the safety and physical-bus boundary. Mappers never open serial
or CAN devices.

- reBotArm: `tcp://localhost:5558`
- SO-101: `tcp://localhost:5559`

Install the allow-listed user services once:

```bash
bash scripts/install_user_services.sh
```

Start both hardware daemons from Settings → Managed services after clearing
the workspace. They are intentionally not enabled at login and do not restart
automatically after a crash.

The SO-101 daemon configuration is `configs/so101_daemon.yaml`. It owns the
Feetech serial bus, verifies calibration, clamps joint/gripper commands,
requires a live heartbeat, seeds the current position before torque enable,
and disables torque on disconnect or lease expiry.

LeRobot configures every STS3215 position-loop P coefficient to `16`. The
loaded arm used here could stop well before the daemon target at that value,
so the daemon applies the measured stable values from
`configs/so101_daemon.yaml`: `96` generally and `120` for shoulder/wrist
pitch. Gripper PID and its current/torque protection remain untouched. Do not
raise all arm joints to `128`; the hardware audit produced oscillation at that
setting. `configs/motion_profiles/so101_cartesian_audit.yaml` is the
single-arm/no-Quest profile for repeating an axis-at-a-time command-chain
check without another producer overwriting the left channel.

SO-101 has only two orientation directions after EEF position is held. With
the included left-controller mapping, controller-forward twist addresses
wrist roll, pitch addresses the remaining reachable direction, and yaw about
the controller-up axis is the unavailable component and is intentionally
dropped. Start each session with wrist flex away from its ±95° URDF limits;
near a limit, one pitch direction necessarily has little remaining travel.

## Quest bimanual bridge

The regular Quest service launches only the right controller. To launch the
right and left controller bridges together, set this environment variable for
the Quest service/process:

```bash
MIMICREC_QUEST_BIMANUAL=1 scripts/run_quest_ros2.sh
```

For the managed Quest service, put `MIMICREC_QUEST_BIMANUAL=1` in
`~/.config/mimicrec/quest.env`, then restart the Quest service from Settings.

The right bridge tags commands with `channel: right`; the left bridge uses
`channel: left`. The backend router releases every channel if an input socket
disconnects. Controller mappings are in:

- `integrations/ros2/mimicrec_quest_bridge/config/quest3.yaml`
- `integrations/ros2/mimicrec_quest_bridge/config/quest3_left.yaml`

## Recording and replay

Motion datasets retain the authoritative graph names:

```text
action.motion.right_hand.se3_delta
action.motion.left_hand.se3_delta
action.motion.<group>.duration_sec
action.motion.<group>.active_mask
action.motion.<group>.frame
action.motion.<group>.aux.gripper

observation.state.right_robot.arm.joint_pos
observation.state.left_robot.arm.joint_pos
action.resource.right_robot.arm.joint_pos
action.resource.left_robot.arm.joint_pos
diagnostic.motion.left_hand.ik_rotation_projection_residual_rad
```

`meta/info.json` includes `motion_schema`, resource ordering, joint names,
group outputs, the SE(3) convention, and the selected profile. Replay reads
the `action.motion.*.se3_delta` columns and sends them through the current
profile's mappers. It does not merely resend recorded joint positions.

The Home action only moves adapters that have an explicitly calibrated target
under the profile's `home.adapters` mapping. The included profile homes the
reBotArm; the SO-101 is held where it is until its own safe pose is captured
and added to the profile.

## Inference

Motion inference contracts set `motion_group` and use
`pose.units: se3_log_increment`. Examples:

- `configs/inference/motion_right_se3_example.yaml`
- `configs/inference/motion_left_se3_example.yaml`

Policy actions enter the same Motion Group input used by Teleop and Replay.
Live controller inputs are paused during inference and require a fresh clutch
engagement after inference stops.

## Mobile manipulators and whole-body IK

`SE3DeltaToPlanarBaseMapper` projects the common increment onto a holonomic or
differential-drive base. `SE3DeltaWholeBodyMapper` solves a weighted damped
whole-body Jacobian supplied by a robot-specific model and may emit commands
for several resources at once. A profile can therefore move from independent
base/arm Motion Groups to coupled whole-body IK without changing the tokenizer
or Adapter contracts.

Resource claims are exclusive. A profile cannot start if an independent base
mapper and a whole-body mapper both claim `mobile_base.drive`.
