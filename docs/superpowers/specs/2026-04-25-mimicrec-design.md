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
- export the resulting datasets to LeRobot and RLDS formats.

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
- Dataset export: keep native LeRobot format, convert to RLDS.
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
- Teleop control loops and recording run at a single **fixed FPS** chosen per session (default 30 Hz); all devices are driven to match that rate. No internal high-rate / recorded-low-rate split.
- During hand-teach mode, the teleop input is not used. The user moves the arm by hand; the backend only samples state.

## 4. High-level architecture

```
Browser (React + TypeScript, Vite)
   │  REST (control/commands)     WebSocket (state/video streams)
   ▼                                ▼
FastAPI server (single process, asyncio)
   │  in-process async calls
   ▼
Device layer (pluggable adapters)
   ├── RobotAdapter     (SO-101, reBotArm B601-DM)
   ├── Teleoperator     (leader arms; SpaceMouse/Gamepad/Keyboard reserved for later)
   ├── Camera           (via LeRobot's existing camera classes)
   └── TeleopMapper     (Identity, EEFollow, Delta)
        │
        ▼
DataWriter
   ├── LeRobotDataset (primary, incremental writes during recording)
   └── RLDS exporter (post-hoc batch conversion)
        │
        ▼
datasets/<dataset_name>/   (LeRobot on-disk layout)
```

Key properties:

- **One process.** FastAPI + control loop + device I/O live in one Python process with a single asyncio event loop. Blocking library calls (CAN I/O, camera reads) run in `asyncio.to_thread` / `run_in_executor`.
- **LeRobot format is the source of truth** on disk. RLDS is a derived export, not a parallel write path.
- **No message broker, no Redis, no multi-process orchestration.** Single-user local app; YAGNI.
- **The server is the single source of truth for session state.** The browser subscribes to state changes via WebSocket; it does not maintain authoritative state.

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

### 5.3 `Camera`

Use LeRobot's existing `OpenCVCamera`, `IntelRealSenseCamera`, etc. unchanged. No wrapper.

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

- Config files live under `configs/` as YAML, loaded with **OmegaConf** (Hydra optional later if CLI overrides are needed).
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
- A session config composes references to the above using `defaults:` and adds task/recording metadata.

Example:

```yaml
# configs/sessions/rebotarm_teleop.yaml
defaults:
  - robot: rebotarm_b601dm
  - teleop: so_leader
  - mapper: ee_follow
  - cameras:
    - front
    - wrist
task:
  name: "pick_and_place_cube"
  instruction: "Pick up the red cube and place it in the green zone"
recording:
  fps: 30
  format: lerobot
```

`/api/configs/*` enumerates available files in these folders and returns metadata the UI needs for selection menus.

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

Teleop mode:

```python
while session.active:
    state = await robot.read_state()
    action = await teleop.read_action()
    command = mapper.map(action, state)
    await robot.send_joint_command(command.q)
    if session.state == RECORDING:
        recorder.append(state, command, cameras.frames(), t=now)
    await sleep_to_next_tick(fps)
```

Hand-teach mode:

```python
await robot.set_mode(GRAVITY_COMP)
while session.active:
    state = await robot.read_state()
    if session.state == RECORDING:
        recorder.append(state, action=None, cameras.frames(), t=now)
    await sleep_to_next_tick(fps)
```

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

Per-frame fields:

- `timestamp` (float32, seconds since episode start)
- `observation.state` (joint positions, velocities)
- `observation.images.<cam_name>` (indexed into MP4)
- `action` (commanded joint positions; filled with last-state for hand-teach rows so the schema is uniform)

Per-episode metadata (`episodes.jsonl`):

- `episode_index`, `task_name`, `instruction`
- `robot`, `teleop`, `mapper`, `cameras`, `mode`, `fps`
- `success: bool | null`, `comment: str | null`
- `start_time`, `end_time`, `duration_sec`, `num_frames`

The primary format is LeRobot. RLDS is produced on demand by an exporter that reads the LeRobot dataset and builds a TFDS-compatible RLDS shard.

## 9. Camera handling

- Recording path: full-resolution frames are encoded directly into per-episode MP4 files during recording. Memory buffering of full episodes is avoided.
- Preview path: the server downscales and JPEG-compresses frames, publishing them at ~10–15 Hz on `/ws/cameras/<cam_name>`. This keeps the recording path unaffected if the preview consumer is slow, and reduces LAN bandwidth.
- Each camera feed is an independent WebSocket channel so a stalled preview on one camera does not block others.

## 10. Web UI

Five pages, sidebar navigation, shared header.

1. **Datasets** — list, create, select.
2. **Record** (core) — four sub-states matching the session machine: pre-session (choose configs), READY (previews + start episode), RECORDING (previews + stop), REVIEW (scrub preview + save/discard/label). Keyboard shortcuts: `Space` start/stop, `S` save, `D` discard, `1/2/3` success/failure/skip.
3. **Episodes** — filterable table of all episodes in a dataset.
4. **Replay** — per-episode viewer: synced camera videos, joint/vel/effort plots, metadata panel, "Replay on Robot" button that plays the recorded joint trajectory on the live arm.
5. **Export** — select dataset and target format (LeRobot/RLDS), filters, output path, asynchronous job with progress.

### Replay-on-robot safety

- Replay uses the current active-session robot.
- If no session is active, the button prompts the user to start one first (the same hardware path is used).
- Before motion, the robot is commanded to the first joint state of the episode via a slow ramp; only then is the recorded trajectory streamed.
- `Stop` button is always visible and immediately halts motion.

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

POST   /api/export                                 body: {dataset, format, filter?, output_path}
GET    /api/export/jobs/{job_id}

GET    /api/episodes/{ds}/{idx}/video/{cam}        # MP4 stream
GET    /api/episodes/{ds}/{idx}/frames             # time-series JSON
```

### 11.2 WebSocket channels

- `/ws/session` — low-rate, event-driven:
  - `session_state` on state transitions
  - `episode_progress` ~1 Hz during RECORDING (frames, duration)
  - `error` on hardware/recording errors
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

class StartSessionRequest(BaseModel):
    dataset: str
    task: str
    robot: str
    teleop: str | None = None        # must be None iff mode == HAND_TEACH
    mapper: str | None = None
    cameras: list[str]
    mode: SessionMode
    fps: int = 30

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
- OmegaConf (Hydra optional later)
- `lerobot` and `reBotArm_control_py` as editable installs
- HuggingFace `datasets` for RLDS export
- `uv` for dependency management

### Frontend

- React + TypeScript + Vite
- TailwindCSS + shadcn/ui
- TanStack Query (REST), native WebSocket (streams)
- Plotly.js or uPlot for time-series plots
- `pnpm` for dependency management

### Testing

- Backend: `pytest`; unit tests for adapters/mappers/recorder with mocks; integration tests via FastAPI `TestClient` with a `MockRobotAdapter` / `MockTeleoperator` / `MockCamera`. Hardware-in-the-loop tests are manual and documented.
- Frontend: `vitest` for components, `Playwright` for an end-to-end Record → Review → Save → Replay flow against a mock-adapter backend.

### Layout

Monorepo:

```
MimicRec/
  backend/
    mimicrec/
      adapters/        (so101, rebotarm, so_leader, mock)
      mappers/
      session/         (state machine, control loop)
      recording/       (LeRobotDataset writer, MP4 writers)
      export/          (RLDS exporter)
      api/             (FastAPI routes, WS hubs)
      config/          (OmegaConf loading)
    tests/
    pyproject.toml
  frontend/
    src/
      pages/           (Datasets, Record, Episodes, Replay, Export)
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

## 15. Open questions and risks

- **SO-101 gravity compensation** — to be verified against current `lerobot`. If unsupported, hand-teach on SO-101 ships as "torque off + friction compensation" or as an explicit "not supported" with a clear error until a workaround is added.
- **Cross-kinematics mapping quality** — `EEFollowMapper` for SO-Leader → reBotArm depends on FK/IK agreement and workspace overlap. Expected to need per-pairing calibration; out-of-scope for MVP beyond a functional reference implementation.
- **MP4 encoding latency** — recording at 30 Hz with 2+ cameras may stress the machine. Fallback: configurable lower recording FPS or frame-dropping with frame counts logged as a quality signal.
- **Replay-on-robot safety** — a bad trajectory can crash the arm into the environment. MVP relies on slow ramp to the first state and a software watchdog for discontinuities; full safety envelopes (workspace limits, velocity caps beyond the controller's own) are not in MVP.
