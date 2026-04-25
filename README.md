# MimicRec

Local-first web application for collecting imitation-learning datasets from physical robot arms. Teleoperate, hand-teach, record, review, replay, and download — all in LeRobot format.

## What it does

- **Teleoperate** a follower arm with a leader arm and record trajectories
- **Hand-teach** by moving the robot under gravity compensation (reBotArm)
- **Review** recorded episodes: save, discard, or label (success/failure)
- **Replay** episodes on the robot with safety watchdog
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

### Prerequisites

- Python 3.12+ with `uv`
- Node.js 20+ with `pnpm`
- (Optional) SO-101 arms on `/dev/ttyACM*`
- (Optional) Isaac Sim 5.0 for simulation

### Install

```bash
git clone <repo> && cd MimicRec

# Backend
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e "./backend[dev]"

# LeRobot (for SO-101 support)
uv pip install --python .venv/bin/python -e "./lerobot"
uv pip install --python .venv/bin/python "lerobot[feetech]"

# Frontend
cd frontend && pnpm install && cd ..
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

First calibrate (one-time):

```bash
.venv/bin/python scripts/calibrate_so101.py --port /dev/ttyACM0 --id my_follower --type follower
.venv/bin/python scripts/calibrate_so101.py --port /dev/ttyACM1 --id my_leader --type leader
```

Then in the UI:
- Robot: `so101`
- Teleop: `so_leader`
- Cameras: `front`, `wrist` (optional)

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
| `Space` | Start / Stop recording |
| `S` | Save episode |
| `D` | Discard episode |
| `1` | Label: Success |
| `2` | Label: Failure |
| `3` | Label: Skip |

## Web UI pages

| Page | Path | Description |
|------|------|-------------|
| **Datasets** | `/datasets` | List, create, download datasets |
| **Record** | `/record` | Session config → record → review → save |
| **Episodes** | `/datasets/:ds/episodes` | Episode table, delete |
| **Replay** | `/datasets/:ds/episodes/:idx/replay` | Video playback, replay on robot |

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/session/start` | Start a session |
| `POST` | `/api/session/end` | End session |
| `GET` | `/api/session/state` | Current session state |
| `POST` | `/api/episode/start` | Start recording |
| `POST` | `/api/episode/stop` | Stop recording |
| `POST` | `/api/episode/save` | Save episode |
| `POST` | `/api/episode/discard` | Discard episode |
| `POST` | `/api/replay/start` | Replay episode on robot |
| `POST` | `/api/replay/stop` | Stop replay |
| `GET` | `/api/datasets` | List datasets |
| `POST` | `/api/datasets` | Create dataset |
| `GET` | `/api/datasets/:ds/episodes` | List episodes |
| `DELETE` | `/api/datasets/:ds/episodes/:idx` | Delete (tombstone) |
| `GET` | `/api/datasets/:ds/archive` | Download as zip |
| `GET` | `/api/configs/:group` | List config options |

## WebSocket channels

| Path | Rate | Content |
|------|------|---------|
| `/ws/session` | Event-driven | State transitions, episode progress, errors |
| `/ws/state` | ~15 Hz | Robot joint positions, velocities |
| `/ws/cameras/:cam` | ~15 Hz | JPEG binary frames |

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
    adapters/     # Robot & teleop adapters (SO-101, mock, sim bridge)
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
    pages/        # Datasets, Record, Episodes, Replay
    state/        # Zustand session store
  configs/        # Robot, teleop, mapper, camera YAMLs
  scripts/        # Run scripts, calibration, sim bridges
  tests/          # 88 tests (unit, integration, exit criteria, API)
```

## License

TBD
