# MimicRec

[English](README.md) | [日本語](README.ja.md)

Local-first web application for collecting imitation-learning datasets from physical robot arms. Teleoperate, hand-teach, record, review, replay, and export — all in the browser, all saved as LeRobot v3 datasets.

**🚀 Live demo: https://takaki-maeda-99.github.io/MimicRec/** — Record → Episodes → Replay in the browser (mock build, no hardware). Settings / Inference / Cloud / Export are stubbed out in the demo build; run locally for the full feature set.

---

## What it does

- **Teleoperation** — drive SO-101 / reBotArm / sim robots from a leader arm, keyboard, or simulator and record trajectories
- **Hand-teach** — move the robot under pure-compliance gravity compensation (reBotArm), with gripper friction compensation so the gripper feels light too
- **Record → review → save** — label episodes success / failure, or discard
- **Replay** — re-play recorded episodes on the robot (arm + gripper) with smooth setpoint interpolation between frames, under a safety watchdog
- **VLA inference** — run any HTTP-served Vision-Language-Action model against the live robot
- **Export** — LeRobot v3 zip / VLA-compat zip (download or local destination) / push to Hugging Face Hub
- **Settings UI** — device discovery, calibration status, adapter config editing (camera picker driven by V4L2 capabilities)

### Supported hardware

| Robot | Interface | Hand-teach | Status |
|-------|-----------|------------|--------|
| SO-101 | LeRobot `SOFollower` (Feetech STS3215) | — | Verified |
| SO Leader | LeRobot `SOLeader` teleoperator | — | Verified |
| reBot Arm B601-DM (+ gripper) | `reBotArm_control_py` via ZMQ daemon | Gravity comp + gripper friction comp | Verified |
| Isaac Sim (any robot) | ZMQ bridge | Supported | Verified (Franka) |
| Mock | Built-in mock adapter | Supported | For testing |

---

## How it's structured

```
Browser (React :5173)  ←→  FastAPI + WebSocket (:8000)  ←→  SessionManager  ←→  Hardware / Sim
                                                                ↓
                                                          LeRobot v3 dataset
```

- **Backend**: Python 3.12, FastAPI, asyncio control loop, LeRobot v3 writer
- **Frontend**: React 19, TypeScript, Vite, TailwindCSS, TanStack Query

```
MimicRec/
  backend/mimicrec/        FastAPI + control loop + dataset writer
    adapters/              Robot & teleop adapters
    api/                   FastAPI routes + WebSocket hubs
    cameras/               CameraManager, OpenCV / sim camera
    cloud/                 Hugging Face Hub push
    inference/             VLA HTTP client + control loop
    kinematics/            URDF-based forward kinematics (EE columns)
    mappers/               Teleop → robot command translation
    recording/             Writer, parquet, metadata
    session/               SessionManager, control loop, replay
  frontend/                React UI (Datasets / Record / Episodes / Replay / Inference / Settings)
  configs/                 Robot / teleop / mapper / camera / inference / rebotarm YAML
  scripts/                 Run scripts, calibration, sim bridges, rebotarm daemon
  lerobot/                 submodule (LeRobot fork with SO-101 support)
  reBotArm_control_py/     submodule (reBotArm control SDK)
  docs/                    Architecture notes, VLA server contract spec
  tests/                   unit / integration / API / exit-criteria
```

---

## Usage

### Setup

Verified on **Ubuntu 22.04**.

```bash
git clone --recurse-submodules git@github.com:takaki-maeda-99/MimicRec.git
cd MimicRec
bash scripts/setup.sh
```

(If you forget `--recurse-submodules`, `setup.sh` will fetch the submodules for you.)

The script is idempotent. It installs the apt prereqs, `uv`, Python 3.12, the backend + LeRobot dependencies, Node 20 + pnpm + frontend dependencies, and adds your user to the `dialout` / `video` groups.

Options: `--no-system` (skip apt + group changes, no sudo prompts) / `--no-frontend` (skip Node / pnpm / frontend).

### Run

```bash
bash scripts/run.sh
# Backend:  http://localhost:8000
# Frontend: http://localhost:5173
```

`scripts/run_backend.sh` / `scripts/run_frontend.sh` start them individually.

### SO-101 teleop

Calibrate each arm once. The `id` must match `id:` in `configs/robot/so101.yaml` and `configs/teleop/so_leader.yaml`:

```bash
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM0 --id my_follower --type follower
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM1 --id my_leader   --type leader
```

Move to the center position and press Enter, then move each joint through its full range and press Enter. Pass `--force` to overwrite an existing calibration. Calibrations are saved under `~/.cache/huggingface/lerobot/calibration/`.

USB ports can swap on reconnect. To map physical arms to ports, run `scripts/identify_arms.py` and wiggle one arm — the port whose readings change is that arm.

In the UI, pick Robot: `so101` / Teleop: `so_leader` / Mapper: `identity` / Cameras: `front`, `wrist` (optional).

> Diagnostic and calibration scripts refuse to run while the backend has an active session (to avoid serial-port contention). End it first: `curl -X POST http://localhost:8000/api/session/end`.

### reBotArm

`reBotArm_control_py` requires Python 3.10, so it can't share the 3.12 backend venv. `setup.sh` creates `.venv-rebotarm` automatically when the submodule is present. Start the daemon in a separate terminal:

```bash
.venv-rebotarm/bin/python -m rebotarm_daemon \
    --config configs/rebotarm_daemon.yaml
```

Select `robot=rebotarm` in the UI — a big red E-stop appears on the Record page. The daemon runs a 500 Hz arm loop + 100 Hz gripper loop and keeps motors in MIT mode at all times (the replay / teleop POSITION mode is just MIT with a strong kp + gravity feedforward). It survives across session start/end, so launch it once and leave it running.

Config files and tuning parameters: see [reBotArm daemon config](#rebotarm-daemon-config).

### Isaac Sim

```bash
# Terminal 1: start the sim bridge
~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py --robot franka --headless

# Terminal 2: start MimicRec
bash scripts/run.sh
```

In the UI, pick Robot: `sim_franka` / `sim_so101`, Camera: `sim_front`. For testing without Isaac Sim, run `scripts/sim_bridge_dummy.py` (dummy sim on :5556).

### Keyboard shortcuts (Record page)

| Key | Action |
|-----|--------|
| `Space` | `ready` → start / `recording` → stop / `review` → **save as success** |
| `F` | `review` → **save as failure** |
| `D` | `review` → discard |
| `Esc` | Cancel auto-cycle |

Auto-cycle mode (toggled in the Record form): record for *Duration* seconds → *Review window* seconds for intervention (`F` to fail, `D` to discard) → auto-start the next episode.

### Web UI pages

| Path | Description |
|------|-------------|
| `/datasets` | Dataset list, creation, download |
| `/record` | Session config → record → review → save |
| `/datasets/:ds/episodes` | Episode table, deletion, annotation |
| `/datasets/:ds/episodes/:idx/replay` | Video playback + on-robot replay |
| `/inference` | Run a VLA model on the live robot (start/stop, instruction, status) |
| `/settings` | Device discovery, config editing, calibration status |

---

## Reference

### Recording EE coordinates

The `kinematics:` block in `configs/robot/so101.yaml` computes forward kinematics from `configs/urdf/so101/so101.urdf`, adding `observation.state.ee_pos / ee_rotvec`, `action.ee_pos / ee_rotvec`, and `gripper_pos` columns to every parquet row. Comment out the block to disable it. The `kinematics` extra is required (installed by default via `setup.sh`):

```bash
uv pip install --python .venv/bin/python -e "./backend[kinematics]"
```

### Dataset layout (LeRobot v3)

```
datasets/my_dataset/
  meta/
    info.json                              # v3 schema with features
    tasks.parquet
    episodes/chunk-000/file-000.parquet
  data/chunk-000/
    episode_000000.parquet
    episode_000001.parquet
  videos/chunk-000/observation.images.front/
    episode_000000.mp4
```

### Pushing to Hugging Face Hub

Run `huggingface-cli login` to set a token, then expand "▸ Hub" on the Datasets tab and "Configure Hub" with `<user-or-org>/<dataset-name>` (private by default). "Push to HF Hub" pushes manually; toggling Auto-push pushes after every episode save.

Datasets are uploaded as LeRobot v3 native format and load directly elsewhere:

```python
from lerobot.datasets.lerobot_dataset import LeRobotDataset
ds = LeRobotDataset.from_pretrained("<user>/<dataset-name>")
```

### VLA inference

MimicRec can drive the robot from any HTTP-served Vision-Language-Action model. The contracts in `configs/inference/*.yaml` describe how requests are built (cameras, proprio state, instruction) and how chunked action responses are interpreted (frame, units, normalization stats).

- Schema: [`configs/inference/README.md`](configs/inference/README.md)
- Reference contract: [`configs/inference/gemma_libero_v1.yaml`](configs/inference/gemma_libero_v1.yaml)
- Server-side contract spec: [`docs/vla-server-contract-prompt.md`](docs/vla-server-contract-prompt.md)

The MVP supports `ee_delta` actions (6-DoF EE delta + gripper) with `mean_std` or `minmax_neg1_pos1` normalization, half-prefetch of the next chunk, and an optional `done` signal that auto-stops recording.

### reBotArm daemon config

Edit the top-level `configs/rebotarm_daemon.yaml`, plus the hardware-specific configs copied from the upstream submodule:

```bash
cp reBotArm_control_py/config/arm.yaml     configs/rebotarm/arm.yaml
cp reBotArm_control_py/config/gripper.yaml configs/rebotarm/gripper.yaml
```

Set motor IDs / channels in `configs/rebotarm/arm.yaml` to match your hardware. Main daemon-side tuning knobs:

- `gravity_in_base` — world gravity expressed in the base frame (m/s²). Omit for upright / horizontal mounts (defaults to `[0, 0, -9.81]`). For a tilted mount, put the world gravity rotated into the base frame here. **If unset, gravity comp will fight the operator.** `configs/rebotarm_daemon.yaml` has 45° tilt examples.
- `gravity_comp.kd` — per-joint hand-teach damping. Higher on the high-inertia proximal joints. Default `[1.5, 1.5, 1.0, 0.6, 0.4, 0.2]`. Raise it if the arm "flies away" on release; lower it if the arm feels heavy.
- `position.kp / position.kd` — MIT-mode gains used during replay. Raise for tighter tracking, lower for a softer landing.
- `gripper.friction_tau_nm / vel_deadband_rad_s` — gripper friction compensation. Raise if it sticks, lower if it drifts.

Replay re-plays both arm and gripper (the `action.gripper_pos` column is read and dispatched via a separate path). Recordings / hardware without a gripper just replay the arm.

### Extending

#### New robot

1. Implement a `RobotAdapter`-compliant adapter under `backend/mimicrec/adapters/`
2. Write `configs/robot/your_robot.yaml` with `_target_: your.module.YourAdapter`
3. (Optional) Add a `Teleoperator`-compliant teleop class
4. Your robot appears in the UI dropdown automatically

#### Cameras

`configs/cameras/*.yaml` — only `OpenCVCamera` goes through V4L2 (`MockCamera` / `SimCamera` take their own kwargs):

```yaml
_target_: mimicrec.cameras.opencv_camera.OpenCVCamera
name: wrist
device_id: 0
width: 1280
height: 720
pixel_format: MJPG    # optional — V4L2 fourcc (MJPG, YUYV, H264, …)
capture_fps: 30       # optional — V4L2 capture rate (independent of session fps)
```

#### Simulator bridge

ZMQ REQ/REP on port 5556, JSON payloads:

```python
{"cmd": "connect"}                  → {"ok": true, "dof": 6, "joint_names": [...]}
{"cmd": "read_state"}               → {"joint_pos": [...], "joint_vel": [...]}
{"cmd": "send_command", "q": [...]} → {"ok": true}
{"cmd": "disconnect"}               → {"ok": true}
```

Reference implementation: [`scripts/sim_bridge_isaacsim.py`](scripts/sim_bridge_isaacsim.py)

---

## License

### MimicRec itself

Apache License 2.0 — see [`LICENSE`](LICENSE).

### Submodules / vendored assets

| Path | Upstream | License |
|------|----------|---------|
| `lerobot/` | Fork of [huggingface/lerobot](https://github.com/huggingface/lerobot) (`takaki-maeda-99/lerobot`) | Apache 2.0 (Hugging Face). Incorporates MIT-licensed derived code (Diffusion Policy / FOWM / simxarm / ALOHA) and Apache 2.0-licensed derived code (DETR). |
| `reBotArm_control_py/` | Fork of `vectorBH6/reBotArm_control_py` (`takaki-maeda-99/reBotArm_control_py`) | **No LICENSE file** (defaults to all rights reserved). The underlying hardware, [Seeed-Projects/reBot-DevArm](https://github.com/Seeed-Projects/reBot-DevArm), is CERN-OHL-W-2.0. Redistribution or modification of the Python control SDK requires coordination with upstream. |
| `configs/urdf/so101/` | Generated from TheRobotStudio SO-ARM100 via [onshape-to-robot](https://github.com/Rhoban/onshape-to-robot) | Apache 2.0 (original design) |

### Major runtime dependencies

**Backend (Python)**: FastAPI / Pydantic (MIT); Uvicorn / PyAV / NumPy / SciPy / OmegaConf (BSD-3-Clause); PyArrow / OpenCV-Python / huggingface_hub (Apache 2.0); placo (MIT, `kinematics` extra only)

**Frontend (Node)**: React / React Router / Vite / TailwindCSS / TanStack Query / Zustand / Recharts / clsx / tailwind-merge / msw (MIT); lucide-react (ISC); class-variance-authority / TypeScript (Apache 2.0)

For the full transitive dependency tree, see `backend/pyproject.toml` / `backend/uv.lock` / `frontend/package.json` / `frontend/pnpm-lock.yaml`.
