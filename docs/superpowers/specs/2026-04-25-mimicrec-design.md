---
title: MimicRec — Imitation Learning Data Collection Web App
date: 2026-04-25
status: approved
---

# MimicRec Design Spec

## 1. Purpose

A local-first web application that helps a single user collect imitation-learning datasets from physical robot arms. The user can:

- teleoperate a follower robot using a leader arm (SO-Leader style) and record the resulting trajectories,
- hand-teach a robot by moving it under gravity compensation with the actuators detorqued, and record the resulting trajectories,
- review, replay, and visualize recorded episodes,
- download recorded datasets in native LeRobot format for downstream use.

The app targets two robots initially:

- **SO-101** (via HuggingFace `lerobot`),
- **reBot Arm B601-DM** (via `reBotArm_control_py`).

The design is explicitly *single-user, single-active-session, local-machine*. Multi-tenant, multi-session, and remote-production concerns are out of scope.

## 2. Scope

### In scope (MVP)

- Web UI for session setup, episode recording (start/stop/review/save/discard), episode list, and single-episode replay with time-series and video visualization.
- Teleoperation via leader arm for both SO-101 and reBot Arm B601-DM.
- Hand-teaching via gravity compensation mode for both robots.
- Config-driven composition of Robot × Teleop × Mapper × Cameras.
- Live preview of camera streams and joint state during a session.
- Episode replay on the robot (replaying recorded joint-space trajectories on a real arm).
- Dataset download as a LeRobot-format archive (zip of the dataset directory).
- Local disk storage. No auth.

### Out of scope (MVP)

- Multi-user or remote access with authentication.
- Simultaneous multi-session or multi-user recording.
- Bimanual setups (two follower arms in one session). The abstraction should not actively prevent this, but it is not a target.
- Annotation tooling beyond success/failure label + free-text comment.
- URDF 3D viewer in the replay page (time-series plots + video are sufficient for MVP).
- Web-based calibration workflows. Calibration is assumed to happen out-of-band via the underlying libraries' CLIs.

## 3. Constraints and assumptions

- The machine running the backend is physically connected to the robot(s) (USB/CAN/serial). The backend process is the only controller of the hardware.
- The user runs the frontend in a browser on the same machine (or a LAN peer); no authentication is required.
- The backend process owns **at most one active session** at a time. Attempts to start a second session return HTTP 409.
- `lerobot` and `reBotArm_control_py` are used as editable installs (cloned into the repo). We do not fork them.
- Teleop control loops and recording run at a single **fixed FPS** chosen per session (default 30 Hz). The *recording tick* is at this fixed FPS. Individual devices (robot, teleop, each camera) are read by independent producer tasks that may run at their own native rates; the control-loop tick consumes the most recent value from each. See §7.2.
- All timestamps are captured as `time.monotonic_ns()` at the point of capture for each stream (robot read, camera frame, action send, control-loop tick). See §8.
- During hand-teach mode, the teleop input is not used. The user moves the arm by hand; the backend only samples state.

## 4. High-level architecture

```
Browser (React + TypeScript, Vite)
   │  REST (control/commands)       WebSocket (state/video streams)
   ▼                                  ▼
FastAPI server (single process, asyncio)
   │
   ▼
┌─ Device reader tasks (independent asyncio tasks, each at its own native rate) ─┐
│   RobotStateReader   ── LatestValue[RobotState]                                │
│   TeleopReader       ── LatestValue[TeleopAction]                              │
│   CameraReader[cam]  ── LatestValue[Frame]   (one task per camera)             │
└─────────────────────────────────────────────────────────────────────────────── ┘
   │   (non-blocking reads from LatestValue slots)
   ▼
Control loop task (ticks at session fps)
   │   reads latest state + action, invokes TeleopMapper, writes a RobotCommand
   │   into command_goal_slot, enqueues a SampleBundle to recorder.queue
   ▼
Command dispatcher task ◄── command_goal_slot (LatestValue[RobotCommand])
   │   serialises sends to robot.send_joint_command; latest-writer-wins collapsing
   │   prevents queued backpressure across the CAN/USB link
   ▼
Writer task (consumes recorder.queue)
   ├── parquet row append (LeRobotDataset incremental)
   └── MP4 encoder append (per-camera, per-episode)
   │
   ▼
datasets/<dataset_name>/   (LeRobot on-disk layout)
```

Key properties:

- **One process.** FastAPI + device I/O + control loop + writer live in one Python process with a single asyncio event loop. Blocking library calls (CAN I/O, camera reads, MP4 encode) run in `asyncio.to_thread` / `run_in_executor`.
- **Producer/consumer, not serial await.** Each device has its own reader task writing to a `LatestValue[T]` slot; the control loop never waits on I/O in the critical path. This keeps the recording tick rate stable even when a single device stalls (CAN timeout, camera hiccup) — a stall shows up as a repeated (stale) last value, not as a missed tick.
- **Single-in-flight command dispatcher.** `send_joint_command` is never called from the control loop directly. The control loop only updates `command_goal_slot`; a dedicated dispatcher task serialises one send at a time and collapses intermediate goals, so the robot link sees no out-of-order or piled-up commands.
- **Writer decoupled from control loop.** The control loop enqueues `SampleBundle` objects and returns immediately; the writer task drains the queue. Queue backpressure is surfaced as a recorder metric, not as control-loop latency.
- **LeRobot format is the source of truth** on disk. No RLDS writer in MVP (see §14).
- **No message broker, no Redis, no multi-process orchestration.** Single-user local app; YAGNI.
- **The server is the single source of truth for session state.** The browser subscribes to state changes via WebSocket; it does not maintain authoritative state.

A `LatestValue[T]` is a tiny wrapper holding `(value, t_mono_ns)`. Writes are unconditional replacement; `peek()` is a non-blocking read that returns the currently-stored tuple (or `None` if never written). `wait_for_new()` asynchronously awaits the next write. Concurrency safety comes from the single-threaded asyncio event loop: device readers use `to_thread` for the blocking I/O call, but the slot write happens back on the loop thread.

## 5. Device abstractions

### 5.1 `RobotAdapter`

```python
class RobotAdapter(Protocol):
    name: str                # "so101", "rebotarm_b601dm"
    dof: int
    joint_names: list[str]

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_state(self) -> RobotState:
        """joint_pos, joint_vel, joint_effort, optional ee_pose."""

    async def send_joint_command(self, q: np.ndarray) -> None: ...
    async def send_ee_command(self, pose: SE3) -> None: ...   # optional; NotImplementedError if unsupported

    async def set_mode(self, mode: RobotMode) -> None:
        """POSITION | TORQUE_OFF | GRAVITY_COMP."""
```

- `GRAVITY_COMP` is required for hand-teach. reBotArm supports it (`example/9_gravity_compensation.py`); SO-101 support to be verified, fall back to a minimal implementation or refuse the mode with a clear error if not feasible.
- `ee_command` is optional; adapters without IK raise `NotImplementedError`.
- Adapters hide vendor-specific control rate details; the session-level loop still drives at the configured FPS.

### 5.2 `Teleoperator`

```python
class Teleoperator(Protocol):
    name: str
    type: TeleopType  # LEADER_ARM | SPACEMOUSE | GAMEPAD | KEYBOARD

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_action(self) -> TeleopAction:
        """target_joint_pos (leader arm) | ee_delta (6-DoF device) | discrete (keyboard)."""
```

MVP ships only leader-arm adapters (SO-Leader, and a reBotArm leader if one is wired up). The protocol leaves room for other device types without redesign.

### 5.3 `Camera` and `CameraManager`

MimicRec does **not** fork or wrap individual camera driver classes: LeRobot's `OpenCVCamera`, `IntelRealSenseCamera`, etc. are used as-is as the underlying drivers. However, MimicRec owns a thin `CameraManager` layer that sits between those drivers and the rest of the system, because several session-level responsibilities are not covered by the drivers.

`CameraManager` responsibilities:

- Instantiate LeRobot camera classes from `configs/cameras/*.yaml`.
- Own connect/disconnect across all cameras in a session, including error aggregation if any one fails to connect.
- Own the per-camera `camera_reader` task (§7.2) that captures frames at the driver's native rate and populates `LatestValue[Frame]` slots.
- Fan out each captured frame to **two consumers**: the recorder (full-resolution, passed into the per-episode MP4 encoder) and the preview hub (downscaled + JPEG-encoded, published on `/ws/cameras/<name>`).
- Isolate slow preview clients from the recording path: the preview fan-out is non-blocking; a stalled WebSocket consumer drops frames for itself only, never back-pressures the recorder.
- Detect and report camera drops / read timeouts as hardware errors that the session-level error handler turns into an auto-discard (§7.3).

The driver is swappable, the manager is not: adding a new camera type means adding a driver class to the config layer, not modifying `CameraManager`.

### 5.4 `TeleopMapper`

```python
class TeleopMapper(Protocol):
    def map(self, action: TeleopAction, robot_state: RobotState) -> RobotCommand: ...
```

Implementations:

- `IdentityMapper` — pass leader joint positions straight through (same-kinematics pairing).
- `EEFollowMapper` — compute leader EE pose via FK, follow with follower IK (cross-kinematics pairing, e.g., SO-Leader → reBotArm).
- `DeltaMapper` — accumulate 6-DoF deltas onto the current robot target (SpaceMouse-like input; MVP stubs this for future use).

Mapper choice is declared in the session config, so Robot × Teleop × Mapper is a free 3-tuple.

## 6. Config system

- Config files live under `configs/` as YAML, loaded with **OmegaConf** only — Hydra is intentionally *not* used. Hydra's Python Compose API has long-running-process hazards (global `GlobalHydra` singleton, working-directory mutation, output-dir creation) that conflict with a FastAPI process that may compose configs many times over its lifetime. CLI overrides are not a core requirement for this app.
- Composition is done by a small (~15 line) in-repo merger that interprets a `defaults:` key at the top of a session config as references to sibling config folders. This is our own, limited subset of Hydra-style composition — enough for our use case and no more. Extended Hydra features (interpolations into the `defaults` list, package overrides, sweeps, etc.) are not supported.
- Configs are organized by concern:

```
configs/
  robots/         so101.yaml, rebotarm_b601dm.yaml, ...
  teleops/        so_leader.yaml, ...
  mappers/        identity.yaml, ee_follow.yaml, ...
  cameras/        front_c270.yaml, wrist_realsense.yaml, ...
  sessions/       so101_teleop.yaml, rebotarm_handteach.yaml, ...
```

- Each config has a `_target_`-style key pointing to the Python class to instantiate, plus parameters (ports, calibration paths, etc.).
- A session config composes references to the above using a `defaults:` key and adds task/recording metadata.

Example:

```yaml
# configs/sessions/rebotarm_teleop.yaml
defaults:
  robot: rebotarm_b601dm           # → configs/robots/rebotarm_b601dm.yaml
  teleop: so_leader                # → configs/teleops/so_leader.yaml
  mapper: ee_follow                # → configs/mappers/ee_follow.yaml
  cameras: [front, wrist]          # → configs/cameras/{front,wrist}.yaml
task:
  name: "pick_and_place_cube"
  instruction: "Pick up the red cube and place it in the green zone"
recording:
  fps: 30
```

Sketch of the merger:

```python
CONFIGS_ROOT = Path("configs")

def load_session_config(session_yaml: Path) -> DictConfig:
    cfg = OmegaConf.load(session_yaml)
    defaults = cfg.pop("defaults", {})
    for group, ref in defaults.items():
        folder = CONFIGS_ROOT / group
        if isinstance(ref, list):
            cfg[group] = {name: OmegaConf.load(folder / f"{name}.yaml") for name in ref}
        else:
            cfg[group] = OmegaConf.load(folder / f"{ref}.yaml")
    OmegaConf.resolve(cfg)
    return cfg
```

`/api/configs/*` enumerates available files in these folders and returns metadata the UI needs for selection menus. `GET /api/session/config` returns the fully-resolved `DictConfig` of the currently active session (for debugging and to let the Record UI display exactly what was loaded).

## 7. Session lifecycle and control loop

### 7.1 States

```
IDLE
 └─ POST /session/start ─► READY
                            │
                            ├─ POST /episode/start ─► RECORDING
                            │                          │
                            │                          └─ POST /episode/stop ─► REVIEW
                            │                                                    │
                            │                                     ┌──────────────┘
                            │                                     ▼
                            │                      POST /episode/save   → READY
                            │                      POST /episode/discard→ READY
                            │
                            └─ POST /session/end ─► IDLE
```

### 7.2 Control loop (per session)

Let `session.state` be the current `SessionState` enum value (see 11.3). The session runs several concurrent asyncio tasks (see §4): one reader per device writing to a `LatestValue` slot, a control-loop task that ticks at `fps`, and a writer task that drains the recorder queue.

**Task lifecycle.**

- All session tasks (device readers, control loop, command dispatcher, writer) are **started once on `session/start`** and **stopped once on `session/end`**. No task is restarted at episode boundaries (`episode/start`, `episode/stop`, `episode/save`, `episode/discard`).
- Stop is signalled by a shared `asyncio.Event` (`stopped`), used by the dispatcher (shown below) and by every reader/loop task. The `session.state != SessionState.IDLE` condition is a convenience derived from the same event and they are always consistent.
- The control loop is alive for the whole session; only what it *does* each tick depends on `session.state`.

**Per-tick behaviour by state:**

| `session.state` | Teleop-mode loop does… | Hand-teach-mode loop does… |
|---|---|---|
| `READY` | read state+action, map, write to `command_goal_slot` (unless replay active). No recording. | no-op tick (arm remains in `GRAVITY_COMP`). No recording. |
| `RECORDING` | same as `READY`, plus enqueue a `SampleBundle` to `recorder.queue`. | read state, enqueue a synthesised-action `SampleBundle`. |
| `REVIEW` | **hold**: do not generate new commands, do not enqueue samples. Do not write to `command_goal_slot` at all — the dispatcher retains its last target, so the robot holds its last commanded joint position. | **idle**: the arm stays in `GRAVITY_COMP`. Do not enqueue samples. |
| `IDLE` | loop has already exited. | loop has already exited. |

The loop does not follow teleop input during `REVIEW`. This prevents unintended motion between episodes: the user can take their hand off the leader arm, label/comment the just-recorded episode, and know the follower will not drift.

**Device reader tasks** (one per device, each at its own native rate):

```python
async def robot_state_reader(
    robot: RobotAdapter,
    slot: LatestValue[RobotState],
    stopped: asyncio.Event,
):
    while not stopped.is_set():
        t = time.monotonic_ns()
        state = await robot.read_state()          # may internally use to_thread
        state.t_mono_ns = t                       # capture-time, set right after read
        slot.set(state)
```

Analogous tasks exist for `teleop_reader` (teleop mode only) and per-camera `camera_reader` tasks. Readers run throughout the session, including `REVIEW` — their data is still useful for live previews on `/ws/state` and `/ws/cameras/*`.

**Command dispatcher.** The robot accepts at most one in-flight `send_joint_command` at a time. A dedicated `command_dispatcher` task owns a `LatestValue[RobotCommand]` **goal slot**: the control loop writes the desired command into the slot, and the dispatcher awaits one send, reads the goal slot again (which already reflects the latest desired command), sends, and repeats. Stale intermediate commands are collapsed automatically — the robot never receives out-of-order joint targets. The control loop thus never calls `send_joint_command` directly and never spawns orphan tasks.

```python
async def command_dispatcher(robot, goal: LatestValue[RobotCommand], stopped: asyncio.Event):
    while not stopped.is_set():
        cmd = await goal.wait_for_new()       # resolves on each new write
        if cmd is None:
            continue
        try:
            await robot.send_joint_command(cmd.q)
        except HardwareError as e:
            await error_bus.publish(e)        # surfaces via /ws/session `error`
```

**Control loop task (teleop mode)**:

```python
tick_interval_ns = 1_000_000_000 // fps
next_tick_ns     = time.monotonic_ns() + tick_interval_ns

while not stopped.is_set():
    tick_t = time.monotonic_ns()

    # Tick drift recovery: if we've fallen behind by more than one tick (e.g., GC
    # pause, OS stall), skip to the next tick boundary instead of busy-catching-up.
    if tick_t >= next_tick_ns + tick_interval_ns:
        ticks_skipped = (tick_t - next_tick_ns) // tick_interval_ns
        metrics.inc("ticks_skipped", ticks_skipped)
        next_tick_ns = tick_t + tick_interval_ns

    phase = session.state

    if phase == SessionState.REVIEW:
        # Hold: do not regenerate commands, do not enqueue samples.
        # Dispatcher retains its last target, so the robot holds its last pose.
        await _sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns
        continue

    state  = robot_state_slot.peek()
    action = teleop_slot.peek()
    if state is None or action is None:
        await _sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns
        continue

    command = mapper.map(action.value, state.value)
    command.t_mono_ns = time.monotonic_ns()

    if not session.replay_active:              # replay owns the robot while active (see §10)
        command_goal_slot.set(command)

    if phase == SessionState.RECORDING:
        frames = {name: slot.peek() for name, slot in camera_slots.items()}
        recorder.enqueue(SampleBundle(
            tick_t_mono_ns=tick_t,
            state=state, action=command, frames=frames,
        ))

    await _sleep_until(next_tick_ns)
    next_tick_ns += tick_interval_ns
```

**Control loop task (hand-teach mode)**:

```python
await robot.set_mode(RobotMode.GRAVITY_COMP)

while not stopped.is_set():
    tick_t = time.monotonic_ns()

    if tick_t >= next_tick_ns + tick_interval_ns:
        ticks_skipped = (tick_t - next_tick_ns) // tick_interval_ns
        metrics.inc("ticks_skipped", ticks_skipped)
        next_tick_ns = tick_t + tick_interval_ns

    phase = session.state

    if phase == SessionState.REVIEW:
        # Idle: arm stays in GRAVITY_COMP; no samples enqueued.
        await _sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns
        continue

    state = robot_state_slot.peek()
    if state is None:
        await _sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns
        continue

    if phase == SessionState.RECORDING:
        # Action is filled *here*, in the control loop, before enqueue, so every
        # SampleBundle is complete and well-typed. The writer is dumb: it only
        # serialises. For hand-teach, action == measured state snapshotted at tick_t.
        synthesized_action = RobotCommand(
            q=state.value.joint_pos,
            t_mono_ns=tick_t,
        )
        frames = {name: slot.peek() for name, slot in camera_slots.items()}
        recorder.enqueue(SampleBundle(
            tick_t_mono_ns=tick_t,
            state=state, action=synthesized_action, frames=frames,
        ))

    await _sleep_until(next_tick_ns)
    next_tick_ns += tick_interval_ns
```

**Transitions `RECORDING → REVIEW → READY` do not restart the loop.** `episode/stop` flips `session.state` to `REVIEW`; the loop's next tick observes this and enters the hold/idle branch. `episode/save` and `episode/discard` flip back to `READY`; the next tick resumes the normal READY behaviour — with teleop mode this means the follower starts tracking the leader again from wherever it is *now*, without any catch-up animation. The UI surfaces a ready state on the Record page so the operator knows teleop will re-engage.

`SampleBundle` is an internal dataclass (not an API model):

```python
@dataclass
class SampleBundle:
    tick_t_mono_ns: int
    state: Stamped[RobotState]
    action: RobotCommand           # always non-None; hand-teach synthesizes from state
    frames: dict[str, Stamped[Frame] | None]   # None allowed for un-primed cameras
```

**Writer task** (runs concurrently, drains `recorder.queue` and writes parquet rows + MP4 frames). The writer is the only component that touches the on-disk dataset; it does *not* synthesize any fields — it only serialises the `SampleBundle` it receives. The recorder exposes `queue_depth`, `writer_lag_ms`, and `ticks_skipped` as live metrics broadcast on `/ws/session` (see §11.2). If the queue grows beyond a soft threshold the writer logs a warning; if it exceeds a hard cap the session auto-aborts with an error.

**Staleness handling.** If `slot.peek()` returns a value whose `t_mono_ns` is older than `tick_t − stale_threshold` (e.g., 3× `tick_interval_ns`), the control loop logs a `stale_sample` warning and increments a per-session metric. Frames are still recorded (with their actual capture timestamps) so downstream code can detect and filter stale samples.

Recording lifecycle:

- On `episode/start`, the recorder allocates a new episode buffer, begins incremental frame writes into the LeRobot dataset layout, and opens per-camera MP4 encoders.
- On `episode/stop`, writers are flushed and the episode enters `REVIEW`. The episode is *not* committed to the dataset yet; its files are held in a pending location.
- On `episode/save`, the pending files are moved into the dataset proper and metadata (success, comment) is appended.
- On `episode/discard`, the pending files are deleted.

### 7.3 Error handling

- Hardware error during recording (CAN timeout, camera drop, etc.) → auto-discard the in-progress episode, transition back to `READY`, broadcast an `error` event. Do not commit partial data.
- Invalid state transition from the client (e.g., `episode/start` while `IDLE`) → HTTP 409, client re-syncs via `GET /session/state`.

## 8. Data model and on-disk layout

A single MimicRec installation manages a set of datasets. Each dataset is an independent LeRobot v2 dataset. Tasks are attributes of episodes within a dataset, not separate directories.

```
datasets/
  <dataset_name>/
    meta/
      info.json
      tasks.jsonl
      episodes.jsonl
    data/
      chunk-000/
        episode_000000.parquet
        ...
    videos/
      chunk-000/
        observation.images.front/
          episode_000000.mp4
        observation.images.wrist/
          episode_000000.mp4
```

Per-frame fields (one row per control-loop tick):

- `timestamp` (float32, seconds since episode start; derived from `tick_t_mono_ns` for LeRobot-format compatibility)
- `tick_t_mono_ns` (int64, control-loop tick time in `monotonic_ns()` units)
- `observation.state.joint_pos` (float32[dof])
- `observation.state.joint_vel` (float32[dof])
- `observation.state.joint_effort` (float32[dof]) — included because it carries the human-applied force signal during hand-teach and is useful for admittance-style downstream policies
- `observation.state.t_mono_ns` (int64, capture time of the joint-state read)
- `observation.images.<cam_name>.video_frame_index` (int32, 0-based row index into the corresponding MP4; matches the MP4 encoder's frame numbering one-to-one)
- `observation.images.<cam_name>.t_mono_ns` (int64, capture time of the frame)
- `action.joint_pos` (float32[dof]) — commanded joint positions. For hand-teach rows, filled with the **current measured `observation.state.joint_pos`** so the schema is uniform and action≈state holds along the trajectory.
- `action.t_mono_ns` (int64, time the command was dispatched; for hand-teach rows, equals `tick_t_mono_ns`)

**Clock model.** All `t_mono_ns` values come from a single `time.monotonic_ns()` source captured inside the backend process. They are monotonically increasing and **continuous across episodes within a single backend-process lifetime**. To convert to wall-clock time, each episode's metadata records `session_boot_t_unix` (Unix seconds) and `session_boot_t_mono_ns`; `unix = session_boot_t_unix + (t_mono_ns − session_boot_t_mono_ns) / 1e9`.

**MP4 correspondence.** Per-row `video_frame_index` is the authoritative mapping from parquet rows to MP4 frames. MP4 PTS is *not* mirrored into parquet (avoiding duplicate time data). MP4 files are written at the session `fps` with fixed-rate PTS, so the `video_frame_index` fully determines the frame to display.

Per-episode metadata (`episodes.jsonl`):

- `episode_index`, `task_name`, `instruction`
- `robot`, `teleop`, `mapper`, `cameras`, `mode`, `fps`
- `success: bool | null`, `comment: str | null`
- `start_t_mono_ns`, `end_t_mono_ns`, `duration_sec`, `num_frames`
- `session_boot_t_unix`, `session_boot_t_mono_ns` (for wall-clock reconstruction)
- `resolved_config`: the fully-merged session config as JSON, for reproducibility

The on-disk format is LeRobot. Conversions to other formats (e.g., RLDS) are not provided by MVP; see §14.

### 8.1 Episode deletion policy

`DELETE /api/datasets/{ds}/episodes/{idx}` does **not renumber episodes**. Deletion behaviour:

- Remove the episode's parquet file and all per-camera MP4 files from disk.
- Update the episode's row in `episodes.jsonl` with a tombstone marker: `deleted: true` and `deleted_at: <unix_ts>`. The row is **kept**, not physically removed from the jsonl, so other episodes' byte offsets and any external tooling holding indices remain valid.
- Episode indices are **stable and may contain gaps** after deletion. Readers and the `/api/datasets/{ds}/archive` zip stream must filter out rows where `deleted == true`.
- `GET /api/datasets/{ds}/episodes` filters tombstoned rows by default and accepts `include_deleted=true` for administrative views (not exposed in the UI in MVP).
- Attempting to `DELETE` an already-deleted index returns HTTP 404.

This avoids the complexity of re-indexing and re-writing the full jsonl/parquet/video tree on every deletion, at the cost of allowing gappy indices downstream. A future compaction job can physically re-pack a dataset if needed; it is out of MVP scope.

## 9. Camera handling

`CameraManager` (§5.3) owns this layer. Behaviour:

- **Recording path.** Full-resolution frames are encoded directly into per-episode MP4 files during recording. Memory buffering of full episodes is avoided.
- **Preview path.** The manager downscales and JPEG-compresses frames, publishing them at ~10–15 Hz on `/ws/cameras/<cam_name>`. This keeps the recording path unaffected if the preview consumer is slow, and reduces LAN bandwidth.
- Each camera feed is an independent WebSocket channel so a stalled preview on one camera does not block others.
- Per-camera capture failures (read timeout, driver error) are surfaced to the session-level error handler; during `RECORDING` this triggers an auto-discard (§7.3), during `READY`/`REVIEW` it is logged and emitted on `/ws/session` `error` without aborting the session.

## 10. Web UI

Four pages, sidebar navigation, shared header. (No separate Export page — see §14. Dataset download is a single-click "Download as zip" button on the Datasets page.)

1. **Datasets** — list, create, select. Each row has a **Download** button that streams a zip of the dataset directory via `GET /api/datasets/{ds}/archive`.
2. **Record** (core) — four sub-states matching the session machine: pre-session (choose configs), READY (previews + start episode), RECORDING (previews + stop), REVIEW (scrub preview + save/discard/label). Keyboard shortcuts: `Space` start/stop, `S` save, `D` discard, `1/2/3` success/failure/skip. A small "Replaying…" badge appears during replay-on-robot (see §11.2).
3. **Episodes** — filterable table of all episodes in a dataset.
4. **Replay** — per-episode viewer: synced camera videos, joint/vel/effort plots, metadata panel, "Replay on Robot" button that plays the recorded joint trajectory on the live arm.

### Replay-on-robot safety

- Replay uses the current active-session robot.
- Replay requires the session to be in `READY`. Replay is forbidden during `RECORDING` or `REVIEW`. While replay is streaming joint commands, the session remains in `READY`; replay does not introduce a new top-level session state. A transient internal `REPLAYING` flag (`session.replay_active`) on the session object gates new `/episode/start` requests (they return HTTP 409 until replay finishes or is stopped).
- **Exclusive robot ownership during replay.** When `replay_active` is true, the control loop (§7.2) explicitly **does not write** to `command_goal_slot`. The replay task is the sole writer during replay, writing successive joint targets from the episode trajectory into the same `command_goal_slot` that the command dispatcher consumes. When replay ends (completed or stopped), `replay_active` is cleared and the control loop resumes commanding. Teleop readers and robot-state readers keep running throughout — only commanding ownership changes.
- **Leader-arm input during replay.** Leader-arm (and any other teleop) input continues to be read for monitoring/preview but **never reaches the robot command path**. It is dropped at the control-loop level by the `replay_active` guard. The UI displays a *"Replaying… leader-arm input ignored"* notice on the Record and Replay pages so the operator is not surprised by the lack of follower response.
- If no session is active, the button prompts the user to start one first (the same hardware path is used).
- Before motion, the robot is commanded to the first joint state of the episode via a slow ramp; only then is the recorded trajectory streamed. The slow-ramp and trajectory-streaming both go through `command_goal_slot`; the dispatcher's collapsing semantics are harmless here because the replay task writes at most once per tick.
- **`Stop` is always visible and immediately halts motion.** It stops streaming replay commands, clears `replay_active`, and writes the currently-measured joint state into `command_goal_slot` as a hold command. Control returns to `READY`; the teleop command path remains gated until the stop cleanup completes (one tick).

#### Replay-safety configuration

The replay task enforces a set of safety parameters, all configurable per-robot in `configs/robots/<name>.yaml` under a `replay:` key. Numeric defaults live in config; the parameter names are part of the spec:

```yaml
# configs/robots/<name>.yaml (fragment)
replay:
  ramp_duration_sec: 2.0            # slow-ramp from current pose to episode frame 0
  max_joint_velocity: <rad/s>        # hard cap on |Δq / Δt| between consecutive targets
  max_joint_acceleration: <rad/s²>   # hard cap on finite-difference Δ² of targets
  max_joint_position_jump: <rad>     # per-tick |target − measured| cap (discontinuity guard)
  command_timeout_sec: 0.2           # how long without a new dispatched command before stop
  watchdog_hz: 20                    # rate at which the watchdog verifies the above
```

On any safety-parameter violation the replay task triggers the same behaviour as `Stop` and emits an `error` event on `/ws/session` with the parameter that tripped. Adapters that expose a native emergency-stop API should wire it in here; adapters without one rely on the hold-command fallback.

## 11. REST and WebSocket contract

### 11.1 REST endpoints

```
GET    /api/datasets
POST   /api/datasets                               body: {name}
GET    /api/datasets/{ds}/tasks
POST   /api/datasets/{ds}/tasks                    body: {name, instruction}
GET    /api/datasets/{ds}/episodes                 query: task?, success?, from?, to?
GET    /api/datasets/{ds}/episodes/{idx}
DELETE /api/datasets/{ds}/episodes/{idx}

GET    /api/configs/robots
GET    /api/configs/teleops
GET    /api/configs/mappers
GET    /api/configs/cameras

POST   /api/session/start                          body: StartSessionRequest
POST   /api/session/end
GET    /api/session/state

POST   /api/episode/start
POST   /api/episode/stop
POST   /api/episode/save                           body: SaveEpisodeRequest
POST   /api/episode/discard

POST   /api/replay/start                           body: {dataset, episode_idx, speed?}
POST   /api/replay/stop

GET    /api/session/config                         # resolved DictConfig of the active session

GET    /api/datasets/{ds}/archive                  # streamed zip of the dataset directory;
                                                   #   tombstoned episodes are excluded
                                                   #   (files omitted, episodes.jsonl
                                                   #   rewritten without deleted rows).
                                                   #   See §8.1.

GET    /api/episodes/{ds}/{idx}/video/{cam}        # MP4 stream
GET    /api/episodes/{ds}/{idx}/frames             # time-series JSON
```

### 11.2 WebSocket channels

- `/ws/session` — low-rate, event-driven:
  - `session_state` on state transitions (payload shape in §11.3).
  - `replay_progress` ~2 Hz while `sub_state == SubState.REPLAYING`: `{frame_index, total_frames, speed}`.
  - `episode_progress` ~1 Hz during RECORDING: `{num_frames, duration_sec, stale_sample_count, writer_queue_depth, writer_lag_ms, ticks_skipped}`.
  - `error` on hardware/recording errors.
- `/ws/state` — robot joint state at 10–15 Hz (server decimates from loop rate)
- `/ws/cameras/{cam_name}` — one channel per camera, JPEG binary frames at 10–15 Hz

### 11.3 Key Pydantic models

```python
class SessionMode(str, Enum):
    TELEOP = "teleop"
    HAND_TEACH = "hand_teach"

class SessionState(str, Enum):
    IDLE = "idle"
    READY = "ready"
    RECORDING = "recording"
    REVIEW = "review"

class SubState(str, Enum):
    REPLAYING = "replaying"
    # Extend only when a new transient flag appears. Start minimal.

class SessionStatePayload(BaseModel):
    state: SessionState
    sub_state: SubState | None = None        # only non-null during replay for now
    mode: SessionMode | None = None          # null when state == IDLE
    dataset: str | None = None
    task: str | None = None
    robot: str | None = None
    teleop: str | None = None
    mapper: str | None = None

class _BaseSessionRequest(BaseModel):
    dataset: str
    task: str
    robot: str
    cameras: list[str]
    fps: int = 30

class TeleopSessionRequest(_BaseSessionRequest):
    mode: Literal[SessionMode.TELEOP] = SessionMode.TELEOP
    teleop: str
    mapper: str

class HandTeachSessionRequest(_BaseSessionRequest):
    mode: Literal[SessionMode.HAND_TEACH] = SessionMode.HAND_TEACH
    # no teleop, no mapper — their absence is enforced by the type system.

StartSessionRequest = Annotated[
    TeleopSessionRequest | HandTeachSessionRequest,
    Field(discriminator="mode"),
]
# FastAPI deserialises the correct variant based on `mode`. Violations return HTTP 422
# automatically; no custom model_validator needed.

class SaveEpisodeRequest(BaseModel):
    success: bool | None = None
    comment: str | None = None

class EpisodeSummary(BaseModel):
    index: int
    task: str
    duration_sec: float
    num_frames: int
    success: bool | None
    recorded_at: datetime
    robot: str
    teleop: str | None
    mode: SessionMode
```

## 12. Technology stack

### Backend

- Python 3.10+
- FastAPI + Uvicorn
- Pydantic v2
- OmegaConf (Hydra explicitly not used; see §6)
- `lerobot` and `reBotArm_control_py` as editable installs
- `pyarrow` for parquet writes (used directly — `datasets`/HuggingFace is *not* a backend dependency)
- `uv` for dependency management

### Frontend

- React + TypeScript + Vite
- TailwindCSS + shadcn/ui
- TanStack Query (REST), native WebSocket (streams)
- Plotly.js or uPlot for time-series plots
- `pnpm` for dependency management

### Testing

- Backend: `pytest`; unit tests for adapters/mappers/recorder with mocks; integration tests via FastAPI `TestClient` with a `MockRobotAdapter` / `MockTeleoperator` / `MockCamera`. The mocks accept **fault-injection parameters** (per-call `latency_ms` distribution, `jitter_ms`, `drop_prob`, `stuck_for_n_calls`) so tests can reproduce stale-sample handling, writer backpressure, and hardware-hiccup auto-discard without touching real hardware. Hardware-in-the-loop tests are manual and documented.
- Frontend: `vitest` for components, `Playwright` for an end-to-end Record → Review → Save → Replay flow against a mock-adapter backend.

### Layout

Monorepo:

```
MimicRec/
  backend/
    mimicrec/
      adapters/        (so101, rebotarm, so_leader, mock)
      mappers/
      cameras/         (CameraManager; LeRobot driver classes are imported, not wrapped)
      session/         (state machine, control loop, LatestValue, command dispatcher)
      recording/       (parquet writer, MP4 writers)
      api/             (FastAPI routes, WS hubs)
      config/          (OmegaConf loading + defaults merger)
    tests/
    pyproject.toml
  frontend/
    src/
      pages/           (Datasets, Record, Episodes, Replay)
      components/
      api/             (REST client, WS clients)
      state/           (session store)
    package.json
  configs/
    robots/ teleops/ mappers/ cameras/ sessions/
  datasets/            (gitignored)
  docs/
  lerobot/             (existing clone, editable install)
  reBotArm_control_py/ (existing clone, editable install)
```

## 13. Logging and observability

- Standard Python `logging` with rotating file handlers, plus stderr in dev.
- Log levels: `DEBUG` for control-loop timing on request, `INFO` for state transitions, `WARNING` for transient hardware hiccups, `ERROR` for session-aborting faults.
- No Prometheus / structured JSON logging in MVP.

## 14. Non-goals (explicit reminders)

- No authentication or multi-user support.
- No cloud deployment story.
- No automatic hyperparameter tuning of control gains from the UI.
- No on-the-fly URDF rendering in MVP.
- No bimanual coordination logic in MVP.
- **No RLDS export or any non-LeRobot format in MVP.** The on-disk format is LeRobot only. Downstream conversion to RLDS (or other formats) is deferred to a future sprint; converter requirements will be driven by actual downstream consumers rather than designed upfront. Dataset download is a plain zip of the dataset directory.
- **No simulation backend.** All adapters target physical hardware (or a fault-injecting Mock). A MuJoCo / Isaac / PyBullet simulator adapter is out of scope; do not add one even if tempting.

## 15. Open questions and risks

- **SO-101 gravity compensation** — SO-101's Feetech STS servos do not expose torque-sensing or current-control primitives, so true gravity compensation is not physically feasible on this hardware. MVP strategy: expose `GRAVITY_COMP` on SO-101 as **"not supported"** with a clear error at session start. A future-work direction is an admittance-like approximation (a light PID that tracks current position so external force moves the arm and releasing hands stops it); explicitly deferred beyond MVP until there is demand and we have tuned it on real hardware.
- **Cross-kinematics mapping quality** — `EEFollowMapper` for SO-Leader → reBotArm depends on FK/IK agreement and workspace overlap. Expected to need per-pairing calibration; out-of-scope for MVP beyond a functional reference implementation.
- **MP4 encoding latency** — recording at 30 Hz with 2+ cameras may stress the machine even with the writer-task architecture from §7.2. The writer-queue and tick-skip metrics (`writer_queue_depth`, `writer_lag_ms`, `ticks_skipped`, broadcast on `/ws/session`) make this observable during a session. Fallback knobs: configurable lower recording FPS per session, per-camera resolution caps, or frame-dropping with frame counts logged as a quality signal.
- **Replay-on-robot safety** — a bad trajectory can crash the arm into the environment. MVP relies on slow ramp to the first state and a software watchdog for discontinuities; full safety envelopes (workspace limits, velocity caps beyond the controller's own) are not in MVP.
