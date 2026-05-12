# MimicRec

[English](README.md) | [日本語](README.ja.md)

Local-first web application for collecting imitation-learning datasets from physical robot arms. Teleoperate, hand-teach, record, review, replay, and download — all in LeRobot format.

## Live demo

**🚀 https://takaki-maeda-99.github.io/MimicRec/**

A browser-only mock build of the **Record → Episodes → Replay** flow.
No hardware, no installation required. Recordings reset on page reload.
Settings, inference, cloud sync, and export are stubbed out in the demo
build — the full feature set requires a local install (see Quick start
below).

## What it does

- **Teleoperate** a follower arm with a leader arm, keyboard, or simulator and record trajectories
- **Hand-teach** by moving the robot under pure-compliance gravity compensation (reBotArm), with gripper friction compensation so the gripper feels light too
- **Review** recorded episodes: save, discard, or label (success/failure)
- **Replay** episodes on the robot — both arm and gripper follow the recorded trajectory with smooth setpoint interpolation between frames, under a safety watchdog
- **Run a VLA model** (Vision-Language-Action) against the live robot via an HTTP contract — see `configs/inference/`
- **Annotate** episodes with subtask segments via the in-app stub annotator
- **Configure** devices, calibrations, and adapter configs from a Settings page — including a capability-driven picker for camera pixel format / resolution / FPS
- **Export** datasets as LeRobot v3 archives or VLA-compat archives (downloadable zip or saved to a local destination)

## Supported hardware

| Robot | Interface | Hand-teach | Status |
|-------|-----------|------------|--------|
| SO-101 | LeRobot `SOFollower` via Feetech STS3215 | Not supported (no gravity comp) | Verified |
| SO Leader | LeRobot `SOLeader` teleoperator | — | Verified |
| reBot Arm B601-DM (+ gripper) | `reBotArm_control_py` via ZMQ daemon | Pure-compliance gravity comp + gripper friction comp | Verified |
| Mock | Built-in mock adapters | Supported | For testing |
| Isaac Sim (any robot) | ZMQ bridge | Supported | Verified (Franka) |

## Architecture

```
Browser (React)  ←→  FastAPI + WebSocket  ←→  SessionManager  ←→  Hardware / Sim
     :5173                 :8000                    ↓
                                              Recording → LeRobot v3 dataset
```

- **Backend**: Python 3.12, FastAPI, asyncio control loop, LeRobot v3 format
- **Frontend**: React 19, TypeScript, Vite, TailwindCSS, TanStack Query
- **~250 backend tests** (unit, integration, exit-criteria, API)

## Quick start

Tested on **Ubuntu 22.04 / 24.04**. Other Linux distros / WSL probably work
but require adapting the system-package step.

### One-shot setup

```bash
git clone --recurse-submodules <repo> && cd MimicRec
bash scripts/setup.sh
```

(If you forgot `--recurse-submodules`, `bash scripts/setup.sh` will fetch
them for you.)

That script is idempotent and does everything: pulls the `lerobot` and
`reBotArm_control_py` submodules, installs system packages, `uv`,
Python 3.12, the backend / LeRobot deps, Node 20 + pnpm + frontend deps,
and adds your user to `dialout` / `video` groups for hardware access.

> If groups were changed, **log out and back in** for the new membership to
> take effect (or `newgrp video` as a temporary one-shell fix).

Flags: `--no-system` (skip apt + group changes — no sudo prompts),
`--no-frontend` (skip Node / pnpm / frontend).

### Prerequisites (what setup.sh installs for you)

System (apt): `ffmpeg`, `v4l-utils`, `libudev-dev`, `pkg-config`,
`build-essential`, `git`, `git-lfs`, `curl`.

Toolchains:
- `uv` (installed via the official installer)
- Python 3.12 (uv pulls it automatically; Ubuntu 22.04 ships 3.10 by default)
- Node.js 20+ (via NodeSource) and `pnpm` (via `npm -g`)

Hardware (optional):
- SO-101 follower / leader on `/dev/ttyACM*` (needs `dialout` group)
- USB cameras on `/dev/video*` (needs `video` group)
- NVIDIA GPU + driver (only needed if you self-host a VLA inference
  server; the in-app stub annotator runs on CPU)
- Isaac Sim 5.0 for simulation (install separately via Omniverse Launcher)

### Manual install (if you skip setup.sh)

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Backend
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e "./backend[dev]"

# LeRobot (for SO-101 support)
uv pip install --python .venv/bin/python -e "./lerobot"
uv pip install --python .venv/bin/python "lerobot[feetech]"

# Frontend (Node 20+ and pnpm required)
cd frontend && pnpm install && cd ..

# Hardware groups (re-login required)
sudo usermod -aG dialout,video "$USER"
```

### Run

```bash
bash scripts/run.sh
# Backend:  http://localhost:8000
# Frontend: http://localhost:5173
```

Or separately:

```bash
bash scripts/run_backend.sh   # FastAPI on :8000
bash scripts/run_frontend.sh  # Vite on :5173
```

### Run tests

```bash
bash scripts/test.sh tests/ -q                 # Full suite
bash scripts/test.sh tests/ -k exit_criterion  # Plan A exit criteria (9)
bash scripts/test.sh tests/api/ -q             # API tests only
```

## Usage

### 1. Mock mode (no hardware)

Open `http://localhost:5173`, go to **Record** page:
- Robot: `mock`
- Teleop: `mock_leader`
- Mapper: `identity`
- Dataset: `my_dataset`
- Task: `pick`

Click **Start Session** → **Start Recording** (or `Space`) → **Stop** → **Save** (or `S`).

### 2. SO-101 teleop

First calibrate (one-time). The `id` you choose must match the `id:` field in
`configs/robot/so101.yaml` and `configs/teleop/so_leader.yaml`:

```bash
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM0 --id my_awesome_follower_arm --type follower
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM1 --id my_awesome_leader_arm --type leader
```

The script connects to the arm and runs LeRobot's interactive calibration
(move to mid-range → press Enter; sweep each joint → press Enter).

**Re-calibrating an already-calibrated arm**: by default LeRobot keeps the
existing calibration. Pass `--force` to delete the cached calibration file
first and run a fresh calibration:

```bash
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM0 --id my_awesome_follower_arm --type follower --force
```

> Calibrations are stored in `~/.cache/huggingface/lerobot/calibration/`
> under `robots/so_follower/<id>.json` and `teleoperators/so_leader/<id>.json`.

**Ports may swap on reconnect.** If the calibration was done on a different
port than the one currently in your config, you'll see weird behavior. Verify
which physical arm is on which port:

```bash
.venv/bin/python scripts/identify_arms.py
# Move ONE arm by hand; the port whose values change is that arm.
```

Then in the UI:
- Robot: `so101`
- Teleop: `so_leader`
- Mapper: `identity`
- Cameras: `front`, `wrist` (optional)

**End-effector pose in recordings.** `configs/robot/so101.yaml` ships with
a `kinematics:` block pointing at `configs/urdf/so101/so101.urdf`. When
present, the writer adds `observation.state.ee_pos / ee_rotvec` and
`action.ee_pos / ee_rotvec` (plus explicit `gripper_pos`) columns to each
parquet row via forward kinematics. Comment out the block to disable.
Requires the `kinematics` extra: `uv pip install --python .venv/bin/python -e "./backend[kinematics]"` (`setup.sh` installs it by default).

> Both diagnostic / calibration scripts refuse to run while the backend has
> an active session, since they would collide for the serial port. End the
> session first: `curl -X POST http://localhost:8000/api/session/end`.

### 3. Isaac Sim (simulation)

```bash
# Terminal 1: Start sim bridge
~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py --robot franka --headless

# Terminal 2: Start MimicRec
bash scripts/run.sh
```

In the UI:
- Robot: `sim_franka` or `sim_so101`
- Camera: `sim_front`

For testing without Isaac Sim:

```bash
.venv/bin/python scripts/sim_bridge_dummy.py  # Fake sim on :5556
```

### 7. Push to Hugging Face Hub

After `huggingface-cli login`, open the Datasets tab and click "▸ Hub" to expand the
Hub section. Click "Configure Hub" and enter `<user-or-org>/<dataset-name>` (private
by default). Click "Push to HF Hub" to upload. Toggle "Auto-push" to push automatically
after each episode is saved.

The dataset is uploaded in LeRobot v3 native format and can be loaded as
`LeRobotDataset.from_pretrained("<user>/<dataset-name>")` from any other machine.

### 4. reBotArm (optional)

`reBotArm_control_py` requires Python 3.10 (cannot share the 3.12
backend venv). `setup.sh` creates `.venv-rebotarm` automatically when
the `reBotArm_control_py` submodule is present. Start the daemon in
a separate terminal:

    .venv-rebotarm/bin/python -m rebotarm_daemon \
        --config configs/rebotarm_daemon.yaml

Then in MimicRec UI choose `robot=rebotarm`. The Record page will
show a big red E-stop button.

The daemon owns the 500 Hz motor control loop and a 100 Hz gripper
loop, mirrors `reBotArm_control_py/data_collect/11_gravity_compensation_record.py`
for hand-teach, and stays in MIT mode throughout — POSITION mode for
replay/teleop is just MIT with strong kp + gravity feed-forward, so
mode swaps don't drop the arm under gravity. The daemon survives
session start/end cycles in the backend, so you typically launch it
once and leave it running.

#### Configuration

The daemon reads `configs/rebotarm_daemon.yaml` (top-level) and a
hardware-specific arm config + optional gripper config you copy from
the upstream submodule:

```bash
cp reBotArm_control_py/config/arm.yaml     configs/rebotarm/arm.yaml
cp reBotArm_control_py/config/gripper.yaml configs/rebotarm/gripper.yaml
```

Edit `configs/rebotarm/arm.yaml` to match your motor IDs / channel.
The MimicRec daemon config has these sections worth tuning:

- `gravity_in_base` — world gravity expressed in the arm's base frame
  (m/s²). Omit for upright/flat mounts (default `[0, 0, -9.81]`). For a
  tilted base, rotate world gravity into the base frame and put the
  result here, otherwise gravity comp will fight the operator. Examples
  in `configs/rebotarm_daemon.yaml` cover 45° side and forward tilts.
- `gravity_comp.kd` — per-joint damping during hand-teach. Higher on
  the proximal 4340P joints (1-3) which carry more reflected inertia.
  Default `[1.5, 1.5, 1.0, 0.6, 0.4, 0.2]`. Bump up if the arm "flies"
  when released, down if it feels too heavy to push.
- `position.kp / position.kd` — MIT gains used during replay. Defaults
  match `arm.yaml`'s MIT defaults (120/8 for proximal, 18/2 for distal).
  Bump up for tighter trajectory tracking, down for softer landings.
- `gripper.friction_tau_nm / vel_deadband_rad_s` — friction-comp torque
  applied when the operator pushes the gripper past the deadband.
  Increase if the gripper still feels sticky; decrease if it drifts.

Replay drives both arm and gripper from the recorded trajectory. The
parquet `action.gripper_pos` column is read alongside `action.joint_pos`
and forwarded via a separate gripper-command path; recordings made
without a gripper (or on hardware that doesn't have one) just play
back the arm.

#### If recording stalls or replay aborts

Replay aborts are usually safety-watchdog trips. Look for `[replay] SAFETY TRIP`
in the backend log; the message tells you which gate fired
(`joint_position_jump` / `joint_velocity` / `joint_acceleration`) and at
what value. Bump the matching threshold in `configs/robot/rebotarm.yaml`'s
`replay:` block if the recording's natural motion exceeds it. Daemon-side
clamps in `configs/rebotarm_daemon.yaml`'s `safety:` block then smooth
whatever you send before it reaches the motors.

Recording cadence (per-episode jitter) can be checked from the parquet:

```python
import pyarrow.parquet as pq, numpy as np
ts = np.array([float(r.as_py()) for r in pq.read_table(
    "datasets/<ds>/data/chunk-000/episode_000000.parquet"
).column("timestamp")])
dt = np.diff(ts)
print(f"median {np.median(dt)*1000:.1f}ms  std {np.std(dt)*1000:.2f}ms  "
      f"min {dt.min()*1000:.1f}ms  max {dt.max()*1000:.1f}ms")
```

Healthy 30 fps recording: median ~33 ms, std < 1 ms. If you see std
comparable to median (heavy jitter), the H.264 encoder is likely
falling behind — the writer already runs encodes off the asyncio loop
and uses `preset=ultrafast` by default, but slower hardware may need
a lighter codec.

## Keyboard shortcuts (Record page)

| Key | Action |
|-----|--------|
| `Space` | `ready` → start, `recording` → stop, `review` → save as **success** |
| `F` | `review` → save as **failure** |
| `D` | `review` → discard |
| `Esc` | Cancel auto-cycle (if running) |
| `1` / `2` / `3` | Manually set label: success / failure / skip |

Auto-cycle mode (toggle in the Record form): records for *Duration* seconds,
then opens a *Review window* of N seconds during which `F` / `D` overrides
the default save-as-success, then automatically starts the next episode.

## Web UI pages

| Page | Path | Description |
|------|------|-------------|
| **Datasets** | `/datasets` | List, create, download datasets |
| **Record** | `/record` | Session config → record → review → save |
| **Episodes** | `/datasets/:ds/episodes` | Episode table, delete, annotate |
| **Replay** | `/datasets/:ds/episodes/:idx/replay` | Video playback, replay on robot |
| **Inference** | `/inference` | Run a VLA model against the live robot (start/stop, instruction, status) |
| **Settings** | `/settings` | Device discovery, adapter configs, calibration status. Each subsection has its own Refresh button. Editing an OpenCVCamera config opens a structured form with cascading dropdowns sourced from `v4l2-ctl --list-formats-ext`; Save is validated by opening the camera and reading back the negotiated parameters before writing the YAML. |

## REST API

### Session / recording / replay

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/session/start` | Start a session |
| `POST` | `/api/session/end` | End session |
| `GET` | `/api/session/state` | Current session state |
| `GET` | `/api/session/config` | Active session config |
| `POST` | `/api/episode/start` | Start recording |
| `POST` | `/api/episode/stop` | Stop recording |
| `POST` | `/api/episode/save` | Save episode |
| `POST` | `/api/episode/discard` | Discard episode |
| `POST` | `/api/replay/start` | Replay episode on robot |
| `POST` | `/api/replay/stop` | Stop replay |
| `GET` | `/api/configs/:group` | List config options |

### Datasets / episodes / annotation

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/datasets` | List datasets |
| `POST` | `/api/datasets` | Create dataset |
| `DELETE` | `/api/datasets/:ds` | Delete dataset |
| `GET` | `/api/datasets/:ds/episodes` | List episodes |
| `GET` | `/api/datasets/:ds/episodes/:idx` | Episode detail |
| `DELETE` | `/api/datasets/:ds/episodes/:idx` | Delete (tombstone) |
| `GET` | `/api/datasets/:ds/episodes/:idx/video/:cam` | Stream episode video |
| `GET` | `/api/datasets/:ds/episodes/:idx/frames` | Sampled frames for annotation |
| `GET` | `/api/datasets/:ds/tasks` | List task names |
| `POST` | `/api/datasets/:ds/tasks` | Add a task |
| `GET` | `/api/datasets/:ds/archive` | Download as zip — `?format=lerobot` (default) or `format=vla_compat` (with `output_destination=download` or `local`) |
| `POST` | `/api/datasets/:ds/episodes/:idx/annotate` | Run subtask annotation on one episode |
| `POST` | `/api/datasets/:ds/annotate-all` | Annotate every episode in the dataset |
| `GET` | `/api/datasets/:ds/annotate-progress` | Poll annotation progress |

### Inference (VLA)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/configs/inference` | List available inference contracts |
| `GET` | `/api/configs/inference/:name` | Read a parsed/validated contract (env vars elided) |
| `POST` | `/api/session/inference/start` | Start an inference session against the active robot |
| `POST` | `/api/session/inference/stop` | Stop the inference session |
| `PUT` | `/api/session/inference/instruction` | Set the natural-language instruction (READY only) |
| `GET` | `/api/session/inference/state` | Current inference state |

Contracts live in `configs/inference/*.yaml`; see `configs/inference/README.md` for the full schema (endpoint, request/response shape, action format, normalization stats).

### Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/settings/devices/serial` | Detected serial ports |
| `GET` | `/api/settings/devices/cameras` | Detected cameras |
| `GET` | `/api/settings/devices/cameras/:device_id/capabilities` | V4L2 formats × discrete resolutions × discrete FPS for `/dev/video<device_id>` (via `v4l2-ctl`) |
| `GET` | `/api/settings/configs/:group` | List configs in a group |
| `GET` | `/api/settings/configs/:group/:name` | Read a config |
| `PUT` | `/api/settings/configs/:group/:name` | Update a config. For OpenCVCamera configs, validated by opening the camera and reading back negotiated params: 409 on mismatch (YAML untouched), 200 + `X-Validation-Skipped: device-busy` if the camera is in use (re-checked at session start). |
| `POST` | `/api/settings/configs/:group/:name` | Create a new config |
| `DELETE` | `/api/settings/configs/:group/:name` | Delete a config |
| `GET` | `/api/settings/calibration` | List calibration files |
| `GET` | `/api/settings/calibration/:category/:type/:id` | Read a calibration |

All `/api/settings/*` GETs return `Cache-Control: no-store` so the browser doesn't serve stale device / config data after USB hot-plug or external YAML edits.

## WebSocket channels

| Path | Rate | Content |
|------|------|---------|
| `/ws/session` | Event-driven | State transitions, episode progress, errors |
| `/ws/state` | ~15 Hz | Robot joint positions, velocities |
| `/ws/cameras/:cam` | ~15 Hz | JPEG binary frames |
| `/ws/teleop` | Event-driven | Browser keyboard teleoperator input |
| `/ws/inference` | Event-driven | Inference session state, chunk events, errors |

## Dataset format

LeRobot v3 compatible:

```
datasets/my_dataset/
  meta/
    info.json              # v3 schema with features
    tasks.parquet
    episodes/chunk-000/file-000.parquet
  data/
    chunk-000/
      episode_000000.parquet
      episode_000001.parquet
  videos/
    chunk-000/
      observation.images.front/
        episode_000000.mp4
```

## Adding a new robot

1. Create an adapter implementing `RobotAdapter` protocol (`backend/mimicrec/adapters/robot.py`)
2. Create a config YAML in `configs/robot/your_robot.yaml` with `_target_: your.module.YourAdapter`
3. (Optional) Create a teleoperator implementing `Teleoperator` protocol
4. The adapter appears in the UI's robot dropdown automatically

### Camera config

`configs/cameras/*.yaml` — only `_target_: mimicrec.cameras.opencv_camera.OpenCVCamera` is V4L2-driven; `MockCamera` and `SimCamera` use their own kwargs.

```yaml
_target_: mimicrec.cameras.opencv_camera.OpenCVCamera
name: wrist
device_id: 0
width: 1280
height: 720
pixel_format: MJPG    # optional — V4L2 fourcc (e.g. MJPG, YUYV, H264)
capture_fps: 30       # optional — V4L2 capture rate (independent of session fps)
```

`pixel_format` and `capture_fps` are optional; YAMLs without them keep the previous behavior (cv2 picks a default fourcc/fps). When set, `OpenCVCamera._open()` reads back the negotiated parameters and raises `RuntimeError` if the V4L2 driver clamped to a different format/size/fps — `CameraManager.start()` propagates that as a session-start failure rather than silently continuing without the camera. Pick combinations from the camera's actual capabilities via the `/settings` Edit modal.

The session's recording rate is `fps:` in the session config, not `capture_fps:`. `init_dataset()` writes the per-camera (width, height) into `info.json` so downstream tools see the real resolution rather than the historical 480×640 default.

### Simulator bridge

Any simulator can be connected via the ZMQ bridge protocol:

```python
# Your simulator sends/receives JSON on ZMQ REQ/REP (port 5556):
{"cmd": "connect"}           → {"ok": true, "dof": 6, "joint_names": [...]}
{"cmd": "read_state"}        → {"joint_pos": [...], "joint_vel": [...]}
{"cmd": "send_command", "q": [...]} → {"ok": true}
{"cmd": "disconnect"}        → {"ok": true}
```

See `scripts/sim_bridge_isaacsim.py` for a reference implementation.

## Project structure

```
MimicRec/
  backend/mimicrec/
    adapters/     # Robot & teleop adapters (SO-101, mock, sim bridge, web teleop)
    annotator/    # In-app subtask annotator (stub today)
    api/          # FastAPI routes + WebSocket hubs
    cameras/      # CameraManager, OpenCV, sim camera
    config/       # OmegaConf loader
    datasets/     # Reader, archive builder
    inference/    # VLA HTTP client, contract loader, control loop
    kinematics/   # URDF-based forward kinematics for EE columns
    mappers/      # Teleop → robot command mapping
    recording/    # Writer, pending episodes, parquet, metadata
    session/      # SessionManager, control loop, dispatcher, replay
    util/         # LatestValue, metrics, clock, error bus
  frontend/src/
    api/          # REST client, WebSocket, TanStack Query hooks
    components/   # UI components (shadcn/ui style)
    pages/        # Datasets, Record, Episodes, Replay, Inference, Settings
    state/        # Zustand session / inference stores
  configs/        # Robot, teleop, mapper, camera, inference, rebotarm YAMLs
  docs/           # Architecture notes, VLA server contract spec
  scripts/        # Run scripts, calibration, sim bridges, rebotarm daemon
  tests/          # Unit, integration, exit criteria, API
```

## VLA inference

MimicRec can drive the live robot from any HTTP-served Vision-Language-Action
model. A YAML contract under `configs/inference/` describes how to pack each
request (cameras, proprio state, instruction) and how to interpret the chunked
action response (frame, units, normalization stats).

- Contract schema: `configs/inference/README.md`
- Reference contract: `configs/inference/gemma_libero_v1.yaml`
- Server-side requirements (for someone implementing a VLA server): `docs/vla-server-contract-prompt.md`

The MVP supports `ee_delta` actions (6-DoF EE delta + gripper) with `mean_std`
or `minmax_neg1_pos1` normalization, half-prefetch of the next chunk, and
optional `done` auto-stop when running during RECORDING.

## GoPro Hero 11 integration

Record alongside USB UVC cameras with full GPMF (IMU/GPS) preservation.

### Setup

- Hero 11 firmware H22.01.02.32.00 or later
- USB-C cable (GoPro genuine recommended)
- Linux with `cdc_ncm` driver (kernel default), `NetworkManager`, `avahi-daemon`
- `ffmpeg` ≥ 4.4 + `ffprobe`
- Python deps: `open-gopro==0.22.0` (pinned in `backend/pyproject.toml`)

### YAML config

`configs/gopros/<name>.yaml`:

```yaml
_target_: mimicrec.gopro.device.GoProDevice
name: gopro_external
usb_serial: "<your serial>"
width: 1280       # YAML target — downscaled from native if needed
height: 720
fps: 30
aspect_mode: crop
```

### Run hardware integration test

```bash
cd backend
GOPRO_SERIAL=<serial> env -u PYTHONPATH .venv/bin/python -m pytest \
  ../tests/integration/test_gopro_hardware.py -v -m gopro_hardware
```

Default `pytest` runs do NOT include hardware tests (`addopts = -m "not gopro_hardware"`).

## License

TBD
