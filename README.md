# MimicRec

[English](README.md) | [日本語](README.ja.md)

Local-first web application for collecting imitation-learning datasets from physical robot arms. Teleoperate, hand-teach, record, review, replay, and download — all in LeRobot format.

## What it does

- **Teleoperate** a follower arm with a leader arm, keyboard, or simulator and record trajectories
- **Hand-teach** by moving the robot under gravity compensation (reBotArm)
- **Review** recorded episodes: save, discard, or label (success/failure)
- **Replay** episodes on the robot with safety watchdog
- **Annotate** episodes with subtask segments (Gemma 4 VLM; full pipeline lives in `MimicAno/`)
- **Configure** devices, calibrations, and adapter configs from a Settings page
- **Download** datasets as LeRobot v3 compatible zip archives

## Supported hardware

| Robot | Interface | Hand-teach | Status |
|-------|-----------|------------|--------|
| SO-101 | LeRobot `SOFollower` via Feetech STS3215 | Not supported (no gravity comp) | Verified |
| SO Leader | LeRobot `SOLeader` teleoperator | — | Verified |
| reBot Arm B601-DM | `reBotArm_control_py` | Supported | Stub (Python 3.10 req) |
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
- **88 backend tests**, all passing

## Quick start

Tested on **Ubuntu 22.04 / 24.04**. Other Linux distros / WSL probably work
but require adapting the system-package step.

### One-shot setup

```bash
git clone <repo> && cd MimicRec
bash scripts/setup.sh
```

That script is idempotent and does everything: installs system packages,
`uv`, Python 3.12, the backend / LeRobot deps, Node 20 + pnpm + frontend
deps, and adds your user to `dialout` / `video` groups for hardware access.

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
- NVIDIA GPU + driver (only needed once MimicAno's real VLM lands;
  current stub annotator runs on CPU)
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
bash scripts/test.sh tests/ -q        # All 88 tests
bash scripts/test.sh tests/ -k exit_criterion  # Plan A exit criteria (9)
bash scripts/test.sh tests/api/ -q     # API tests only (33)
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
| **Settings** | `/settings` | Device discovery, adapter configs, calibration status |

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
| `GET` | `/api/datasets/:ds/archive` | Download as zip |
| `POST` | `/api/datasets/:ds/episodes/:idx/annotate` | Run subtask annotation on one episode |
| `POST` | `/api/datasets/:ds/annotate-all` | Annotate every episode in the dataset |
| `GET` | `/api/datasets/:ds/annotate-progress` | Poll annotation progress |

### Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/settings/devices/serial` | Detected serial ports |
| `GET` | `/api/settings/devices/cameras` | Detected cameras |
| `GET` | `/api/settings/configs/:group` | List configs in a group |
| `GET` | `/api/settings/configs/:group/:name` | Read a config |
| `POST` | `/api/settings/configs/:group/:name` | Write a config |
| `DELETE` | `/api/settings/configs/:group/:name` | Delete a config |
| `GET` | `/api/settings/calibration` | List calibration files |
| `GET` | `/api/settings/calibration/:category/:type/:id` | Read a calibration |

## WebSocket channels

| Path | Rate | Content |
|------|------|---------|
| `/ws/session` | Event-driven | State transitions, episode progress, errors |
| `/ws/state` | ~15 Hz | Robot joint positions, velocities |
| `/ws/cameras/:cam` | ~15 Hz | JPEG binary frames |
| `/ws/teleop` | Event-driven | Browser keyboard teleoperator input |

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
    api/          # FastAPI routes + WebSocket hubs
    cameras/      # CameraManager, OpenCV, sim camera
    config/       # OmegaConf loader
    datasets/     # Reader, archive builder
    mappers/      # Teleop → robot command mapping
    recording/    # Writer, pending episodes, parquet, metadata
    session/      # SessionManager, control loop, dispatcher, replay
    util/         # LatestValue, metrics, clock, error bus
  frontend/src/
    api/          # REST client, WebSocket, TanStack Query hooks
    components/   # UI components (shadcn/ui style)
    pages/        # Datasets, Record, Episodes, Replay, Settings
    state/        # Zustand session store
  configs/        # Robot, teleop, mapper, camera YAMLs
  scripts/        # Run scripts, calibration, sim bridges
  tests/          # 88 tests (unit, integration, exit criteria, API)
  MimicAno/       # Standalone subtask annotator package (in development)
    docs/design.md  # Pipeline design spec
    sam3/           # SAM 3 (text-prompted segmentation) clone
```

## MimicAno — subtask annotator

`MimicAno/` is a standalone Python package (also usable from MimicRec) that
turns recorded episodes into reviewed subtask segments.

Pipeline: signal-based boundary detection → SAM3 object tracking → clip
segmentation → Gemma 4 VLM labeling (allowed labels only) → temporal
smoothing → human review UI.

See `MimicAno/docs/design.md` for the full design. Implementation is in
progress; the existing in-app annotation endpoints under `/api/datasets/...`
are the bridge until MimicAno is wired in.

## License

TBD
