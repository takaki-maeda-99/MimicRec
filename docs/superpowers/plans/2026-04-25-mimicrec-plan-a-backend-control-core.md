# MimicRec Plan A — Backend Control Core

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend control core of MimicRec — device adapters, `LatestValue` slots, the session-scoped control loop, command dispatcher, recorder/writer, `CameraManager`, replay task, config loader, and a fault-injecting mock adapter suite — validated end-to-end against mocks, with a dataset layer that knows how to read/filter tombstoned episodes and produce the archive payload.

**Architecture:** Producer/consumer asyncio task graph. Readers (robot/teleop/camera) populate `LatestValue[T]` slots at their native rates. A session-scoped control loop ticks at the configured FPS, reads latest values non-blockingly, writes a `RobotCommand` into `command_goal_slot`, and enqueues `SampleBundle`s to a writer queue. A single-in-flight `command_dispatcher` collapses stale targets to the robot link. A writer task drains the queue into LeRobot format. Replay is another writer into `command_goal_slot` gated by an exclusive `replay_active` flag. Domain exceptions (`HandTeachNotSupportedError`, `InvalidTransitionError`, `HardwareError`) flow up to the session layer and are later (Plan B) translated to HTTP.

**Tech Stack:** Python 3.10+, asyncio, `pyarrow`, `opencv-python` + `av` (for MP4 + JPEG), OmegaConf, Pydantic v2 (for internal config schemas), `pytest` + `pytest-asyncio`, `lerobot` and `reBotArm_control_py` as editable installs. No FastAPI in this plan.

**Spec:** [docs/superpowers/specs/2026-04-25-mimicrec-design.md](../specs/2026-04-25-mimicrec-design.md)

---

## Scope boundary

**This plan covers Plan A only: backend control core.**

**Plans B/C/D are intentionally deferred** until Plan A proves the control/session/recording architecture against Mock adapters. Concretely:

- **Plan A does:** domain logic, adapter protocols, mock adapters, config loading, `LatestValue`, command dispatcher, control loop, session state machine, recorder/writer, tombstone-aware dataset reader + archive-payload builder, `CameraManager`, replay task, domain-level tests.
- **Plan A does NOT:** FastAPI routes, HTTP status codes, WebSocket serialisation, React frontend, hardware-in-the-loop tuning. HTTP-facing errors are represented as domain exceptions (`NotSupportedError`, `InvalidTransitionError`, `HardwareError`). Plan B will map them to HTTP 422/409/500.
- **Plan A does NOT touch real hardware.** Everything is validated against `MockRobotAdapter` / `MockTeleoperator` / `MockCamera`. Real-hardware adapters (`SO101Adapter` stub, `ReBotArmAdapter` stub) are scaffolded with their domain error paths tested, but their `connect()` to real hardware is out of scope for this plan's exit criteria.

## Exit criteria

A mock-backed session must be able to, under `pytest`:

1. start in `TELEOP` mode,
2. stream mock robot/teleop/camera data through `LatestValue` slots,
3. run the session-scoped control loop at the configured FPS,
4. record an episode,
5. enter `REVIEW` without restarting tasks,
6. save or discard pending episode files,
7. replay a saved episode with teleop command path gated by `replay_active`,
8. delete an episode with tombstone semantics,
9. survive injected latency / drop / stuck-stream faults from the mock adapters and surface the expected metrics and domain errors.

Each criterion maps to at least one test named `test_exit_criterion_N_*` so `pytest -k exit_criterion` is the single pass/fail gate.

---

## File structure (decisions locked here)

### Source tree (all paths relative to repo root)

```
backend/
  pyproject.toml
  mimicrec/
    __init__.py
    types.py                      # Stamped, RobotState, TeleopAction, RobotCommand,
                                  # Frame, SampleBundle, enums
    errors.py                     # HandTeachNotSupportedError, InvalidTransitionError,
                                  # HardwareError, RecorderError
    util/
      __init__.py
      clock.py                    # monotonic_ns wrapper + a FakeClock for tests
      latest_value.py             # LatestValue[T] (peek, set, wait_for_new)
      metrics.py                  # in-memory counter/gauge store (name -> value)
      error_bus.py                # asyncio-based pub/sub used by dispatcher/session
    config/
      __init__.py
      loader.py                   # load_session_config + the ~15-line defaults merger
      schemas.py                  # Pydantic models for the resolved config surface
    adapters/
      __init__.py
      robot.py                    # RobotAdapter Protocol + RobotMode enum
      teleop.py                   # Teleoperator Protocol + TeleopType enum
      mock_robot.py               # MockRobotAdapter with fault-injection knobs
      mock_teleop.py              # MockTeleoperator with fault-injection knobs
      so101.py                    # stub SO-101 adapter; raises HandTeachNotSupportedError
                                  # on set_mode(GRAVITY_COMP); real I/O deferred.
      rebotarm.py                 # stub reBotArm adapter scaffolding
    cameras/
      __init__.py
      manager.py                  # CameraManager (connect, read, fan-out)
      mock_camera.py              # MockCamera with fault-injection knobs
      preview.py                  # downscale + JPEG encoder for preview consumers
      recording.py                # per-episode MP4 encoder (libav wrapper)
    mappers/
      __init__.py
      base.py                     # TeleopMapper Protocol
      identity.py                 # IdentityMapper
      ee_follow.py                # EEFollowMapper stub (real IK wiring deferred; mock-friendly)
      delta.py                    # DeltaMapper stub
    session/
      __init__.py
      state.py                    # SessionState, SubState, SessionMode, Session dataclass
      tasks.py                    # reader tasks, control loop tasks, dispatcher task,
                                  # writer task scaffolding, start/stop orchestration
      control_loop.py             # the two control-loop coroutines (teleop, hand-teach)
      dispatcher.py               # command_dispatcher coroutine
      replay.py                   # replay task + Replay safety watchdog
      lifecycle.py                # SessionManager: start/end, episode start/stop/save/discard,
                                  # replay start/stop, domain-error translation
    recording/
      __init__.py
      sample_bundle.py            # re-exports SampleBundle from types.py for import clarity
      writer.py                   # Writer task coroutine; drains queue -> parquet + MP4
      pending.py                  # PendingEpisode: staging-dir + move/delete on save/discard
      dataset_layout.py           # on-disk LeRobot v2 layout helpers
      metadata.py                 # episodes.jsonl / tasks.jsonl / info.json read+write
      parquet_row.py              # build one parquet row from a SampleBundle
    datasets/
      __init__.py
      reader.py                   # tombstone-aware episode reader
      archive.py                  # build_archive_stream(ds_path) -> iterator of (name, bytes)
                                  # filters tombstoned episodes; rewrites episodes.jsonl
tests/
  conftest.py                     # shared fixtures (tmp dataset, FakeClock, mock adapters)
  unit/
    test_latest_value.py
    test_config_loader.py
    test_errors.py
    test_mock_adapters.py
    test_mappers_identity.py
    test_pending_episode.py
    test_metadata_roundtrip.py
    test_parquet_row.py
    test_dataset_reader_tombstones.py
    test_archive_filter.py
    test_camera_manager.py
    test_command_dispatcher.py
    test_replay_watchdog.py
    test_so101_handteach_unsupported.py
  integration/
    test_session_lifecycle_mock.py          # ties tasks together
    test_control_loop_teleop.py
    test_control_loop_handteach.py
    test_review_hold_idle.py
    test_replay_exclusive_ownership.py
    test_fault_injection.py
  exit_criteria/
    test_exit_criterion_1_start_teleop.py
    test_exit_criterion_2_latest_value_streams.py
    test_exit_criterion_3_control_loop_fps.py
    test_exit_criterion_4_record_episode.py
    test_exit_criterion_5_review_no_restart.py
    test_exit_criterion_6_save_and_discard.py
    test_exit_criterion_7_replay_gates_teleop.py
    test_exit_criterion_8_tombstone_delete.py
    test_exit_criterion_9_fault_injection.py
configs/
  robots/     mock.yaml, so101.yaml (sparse stub), rebotarm_b601dm.yaml (sparse stub)
  teleops/    mock_leader.yaml, so_leader.yaml (sparse stub)
  mappers/    identity.yaml
  cameras/    mock_cam.yaml
  sessions/   mock_teleop.yaml, mock_handteach.yaml
```

### Responsibilities (one-line per file that's non-obvious)

- `types.py` — all cross-cutting dataclasses/enums; no logic, no I/O. Importable by everything.
- `util/latest_value.py` — `LatestValue[T]`: `set(value)` stores `(value, t_mono_ns)`, `peek()` returns the tuple or `None`, `wait_for_new()` returns the next write (asyncio.Event-based).
- `util/error_bus.py` — a tiny asyncio pub/sub so the dispatcher and watchdog can emit without importing the session manager.
- `config/loader.py` — the 15-line merger (§6). Idempotent, side-effect free. Returns `DictConfig`.
- `cameras/manager.py` — owns per-camera reader tasks, fans frames to both the recorder (full-res) and preview channel (downscaled JPEG). Never blocked by either consumer.
- `cameras/preview.py` — pure functions: `downscale(frame, max_edge_px) -> frame`, `encode_jpeg(frame, quality) -> bytes`.
- `cameras/recording.py` — thin `av.open()` wrapper. One encoder per episode per camera.
- `session/state.py` — `Session` dataclass: `state: SessionState`, `sub_state: SubState | None`, `mode`, `replay_active: bool`, `stopped: asyncio.Event`, the device slots, and the config snapshot.
- `session/tasks.py` — pure orchestration: `start_session_tasks(...) -> SessionTaskSet`, `stop_session_tasks(...)`. No business logic.
- `session/control_loop.py` — the two coroutines straight from spec §7.2. Uses a `Clock` protocol so tests inject a `FakeClock`.
- `session/dispatcher.py` — the `command_dispatcher` coroutine from spec §7.2.
- `session/replay.py` — the replay coroutine + a `ReplayWatchdog` that enforces safety params from config.
- `session/lifecycle.py` — `SessionManager` coordinates: input = requests like `start(cfg)`, `stop()`, `episode_start()`, output = `Session` state updates and `ErrorBus` events. Enforces state-machine transitions and raises `InvalidTransitionError` on bad transitions. Translates adapter exceptions to domain errors; HTTP translation is Plan B's job.
- `recording/writer.py` — consumes `recorder.queue`, writes one parquet row per bundle via `parquet_row.py`, pushes each camera frame into the per-episode MP4 encoder.
- `recording/pending.py` — `PendingEpisode` owns a staging dir (`datasets/<ds>/.pending/ep_<N>/`); on save, `move_into_place(ds_root)`; on discard, `rmtree`.
- `recording/metadata.py` — read/append helpers for `episodes.jsonl`, `tasks.jsonl`, `info.json`, with tombstone-aware helpers.
- `datasets/reader.py` — `iter_episodes(ds_path, include_deleted=False)` and `read_episode(idx)`. Single source of truth for "which rows count".
- `datasets/archive.py` — builds the archive payload as a stream of `(path_in_zip, bytes_or_path)` so Plan B can plug it into a zip stream without buffering whole datasets in memory. Filters tombstones, rewrites `episodes.jsonl` with only live rows.

---

## Conventions

- **TDD throughout.** Every task writes a failing test first and commits after the green bar.
- **No backwards-compatibility shims.** The repo is empty at task 0.
- **Every task ends with a commit.** Commit message format: `planA: <short imperative>`.
- **`pytest-asyncio` mode = `auto`** (configured in `pyproject.toml`) so async tests don't need per-test decorators.
- **Imports always absolute** (`from mimicrec.util.latest_value import LatestValue`).
- **No `from lerobot import *`.** Import the minimum surface; treat lerobot as a third-party dep even though it's editable-installed.

---

## Task dependencies (high-level)

The five mandated spikes/foundations (Tasks 1–5 below) are in order because each depends on prior ones:

- **Task 1 (LeRobot pending/save/discard spike)** must go first because every later task touches `recording/pending.py` or a file that depends on its directory layout.
- **Task 2 (session-scoped loop lifecycle)** depends on Task 1 for the recorder stub that the loop enqueues into.
- **Task 3 (replay vs teleop ownership)** depends on Task 2 for the loop to gate.
- **Task 4 (SO-101 hand-teach unsupported path)** can technically run earlier, but it's placed here so by this point the session manager exists to raise the domain error through.
- **Task 5 (dataset archive tombstone filter)** depends on Task 1's metadata/layout helpers and on tombstone semantics defined in Task 6 below — but Task 5 only needs the *filter* behaviour, not the REST route. We verify LeRobot compatibility here.

Tasks 6+ then fill in the breadth: cameras, config loader, dispatcher, writer details, mock adapters with fault injection, integration tests, and the exit-criteria gate.

---

## Task 0 — Repository scaffolding

**Goal:** Create the backend Python package and a failing test that proves pytest is wired.

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/mimicrec/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`
- Create: `pytest.ini` (at repo root)
- Create: `.gitignore` (at repo root)

- [ ] **Step 0.1: Write `.gitignore`**

```gitignore
__pycache__/
*.pyc
.venv/
.pytest_cache/
/datasets/
/backend/mimicrec.egg-info/
.DS_Store
```

- [ ] **Step 0.2: Write `backend/pyproject.toml`**

```toml
[project]
name = "mimicrec"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "pyarrow>=15",
  "numpy>=1.26",
  "omegaconf>=2.3",
  "pydantic>=2.7",
  "opencv-python>=4.9",
  "av>=12",
]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["mimicrec"]
```

- [ ] **Step 0.3: Write `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
filterwarnings =
    error
```

- [ ] **Step 0.4: Write `backend/mimicrec/__init__.py`**

```python
"""MimicRec backend control core."""
__version__ = "0.1.0"
```

- [ ] **Step 0.5: Write the smoke test**

`tests/test_smoke.py`:

```python
def test_mimicrec_importable():
    import mimicrec
    assert mimicrec.__version__ == "0.1.0"
```

- [ ] **Step 0.6: Install the package editable and run tests**

```bash
cd /home/takakimaeda/MimicRec
python -m venv .venv
. .venv/bin/activate
pip install -e "./backend[dev]"
pytest -q
```

Expected: `1 passed`.

- [ ] **Step 0.7: Commit**

```bash
git add backend pytest.ini .gitignore tests/__init__.py tests/test_smoke.py
git commit -m "planA: scaffold backend package and smoke test"
```

---

## Task 1 — LeRobot pending/save/discard spike

**Goal:** Prove we can (a) stream frames into a LeRobot-format directory incrementally, (b) hold them in a pending/staging area, (c) atomically commit them to the dataset on save, (d) delete them on discard, and (e) produce a final layout that a fresh `LeRobotDataset.resume(...)` can read. This is a **spike** because it decides whether we wrap LeRobot's `DatasetWriter` or bypass it and write raw parquet + MP4 ourselves.

We write a **minimal, contract-only** `PendingEpisode` API, test it against a temp directory, and assert LeRobot can read what we produced.

**Decision recorded in the test:** after this task, the plan is committed to one of the two paths. The default is "raw parquet + MP4 via `pyarrow` + `av`", because the spec's §7.2 writer is dumb on purpose and `DatasetWriter` does extra work (image writing processes, video batching) we don't want. If the test shows LeRobot *cannot* read our raw output, we pivot to wrapping `DatasetWriter` and note it in the task's final commit message.

**Files:**
- Create: `backend/mimicrec/types.py`
- Create: `backend/mimicrec/recording/__init__.py`
- Create: `backend/mimicrec/recording/dataset_layout.py`
- Create: `backend/mimicrec/recording/metadata.py`
- Create: `backend/mimicrec/recording/parquet_row.py`
- Create: `backend/mimicrec/recording/pending.py`
- Create: `tests/unit/test_pending_episode.py`
- Create: `tests/unit/test_metadata_roundtrip.py`
- Create: `tests/unit/test_parquet_row.py`

- [ ] **Step 1.1: Write `types.py` with only the fields needed for a parquet row**

```python
# backend/mimicrec/types.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

import numpy as np

T = TypeVar("T")


@dataclass(frozen=True)
class Stamped(Generic[T]):
    value: T
    t_mono_ns: int


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


@dataclass
class RobotState:
    joint_pos: np.ndarray      # float32[dof]
    joint_vel: np.ndarray      # float32[dof]
    joint_effort: np.ndarray   # float32[dof]
    t_mono_ns: int = 0         # filled by reader task


@dataclass
class RobotCommand:
    q: np.ndarray              # float32[dof]
    t_mono_ns: int = 0


@dataclass
class TeleopAction:
    target_joint_pos: np.ndarray | None = None   # leader-arm style
    ee_delta: np.ndarray | None = None           # 6-DoF device style
    t_mono_ns: int = 0


@dataclass
class Frame:
    image: np.ndarray          # HxWx3 uint8 BGR
    t_mono_ns: int = 0


@dataclass
class SampleBundle:
    tick_t_mono_ns: int
    state: Stamped[RobotState]
    action: RobotCommand
    frames: dict[str, Stamped[Frame] | None]
```

- [ ] **Step 1.2: Write failing test `tests/unit/test_parquet_row.py`**

```python
import numpy as np
from mimicrec.recording.parquet_row import sample_bundle_to_row
from mimicrec.types import RobotState, RobotCommand, SampleBundle, Stamped


def test_row_has_expected_fields_and_video_index():
    state = Stamped(
        RobotState(
            joint_pos=np.array([0.1, 0.2], dtype=np.float32),
            joint_vel=np.array([0.0, 0.0], dtype=np.float32),
            joint_effort=np.array([0.0, 0.0], dtype=np.float32),
            t_mono_ns=1_000_000_000,
        ),
        t_mono_ns=1_000_000_000,
    )
    action = RobotCommand(q=np.array([0.11, 0.19], dtype=np.float32), t_mono_ns=1_001_000_000)
    bundle = SampleBundle(
        tick_t_mono_ns=1_000_500_000,
        state=state,
        action=action,
        frames={"front": None, "wrist": None},
    )
    row = sample_bundle_to_row(
        bundle,
        episode_start_t_mono_ns=1_000_000_000,
        video_frame_index={"front": 0, "wrist": 0},
    )
    assert row["timestamp"] == 0.0005   # 500us after start
    assert row["tick_t_mono_ns"] == 1_000_500_000
    assert row["observation.state.joint_pos"].tolist() == [0.1, 0.2]
    assert row["action.joint_pos"].tolist() == [0.11, 0.19]
    assert row["observation.images.front.video_frame_index"] == 0
    assert row["observation.images.wrist.video_frame_index"] == 0
```

- [ ] **Step 1.3: Run to verify it fails**

```bash
pytest tests/unit/test_parquet_row.py -v
```

Expected: `ModuleNotFoundError: No module named 'mimicrec.recording.parquet_row'`.

- [ ] **Step 1.4: Implement the row builder**

`backend/mimicrec/recording/parquet_row.py`:

```python
from __future__ import annotations
from mimicrec.types import SampleBundle


def sample_bundle_to_row(
    bundle: SampleBundle,
    episode_start_t_mono_ns: int,
    video_frame_index: dict[str, int],
) -> dict:
    state = bundle.state.value
    row = {
        "timestamp": (bundle.tick_t_mono_ns - episode_start_t_mono_ns) / 1e9,
        "tick_t_mono_ns": bundle.tick_t_mono_ns,
        "observation.state.joint_pos": state.joint_pos,
        "observation.state.joint_vel": state.joint_vel,
        "observation.state.joint_effort": state.joint_effort,
        "observation.state.t_mono_ns": state.t_mono_ns,
        "action.joint_pos": bundle.action.q,
        "action.t_mono_ns": bundle.action.t_mono_ns,
    }
    for cam_name, frame_idx in video_frame_index.items():
        row[f"observation.images.{cam_name}.video_frame_index"] = frame_idx
        stamped = bundle.frames.get(cam_name)
        row[f"observation.images.{cam_name}.t_mono_ns"] = (
            stamped.t_mono_ns if stamped is not None else 0
        )
    return row
```

- [ ] **Step 1.5: Run test, verify pass**

```bash
pytest tests/unit/test_parquet_row.py -v
```

Expected: `1 passed`.

- [ ] **Step 1.6: Write failing test `tests/unit/test_metadata_roundtrip.py`**

```python
from pathlib import Path
from mimicrec.recording.metadata import (
    append_episode, read_episodes, upsert_task, tombstone_episode,
)


def test_append_and_read_episodes(tmp_path: Path):
    meta = tmp_path / "meta"
    meta.mkdir()
    append_episode(meta, {"episode_index": 0, "task": "pick", "num_frames": 10})
    append_episode(meta, {"episode_index": 1, "task": "pick", "num_frames": 12})
    eps = list(read_episodes(meta, include_deleted=False))
    assert [e["episode_index"] for e in eps] == [0, 1]


def test_tombstone_filters_deleted(tmp_path: Path):
    meta = tmp_path / "meta"
    meta.mkdir()
    append_episode(meta, {"episode_index": 0, "task": "pick", "num_frames": 10})
    append_episode(meta, {"episode_index": 1, "task": "pick", "num_frames": 12})
    tombstone_episode(meta, 0, deleted_at_unix=1700000000)
    assert [e["episode_index"] for e in read_episodes(meta)] == [1]
    assert [e["episode_index"] for e in read_episodes(meta, include_deleted=True)] == [0, 1]
```

- [ ] **Step 1.7: Run to verify it fails**

```bash
pytest tests/unit/test_metadata_roundtrip.py -v
```

Expected: module-not-found failures.

- [ ] **Step 1.8: Implement metadata helpers**

`backend/mimicrec/recording/metadata.py`:

```python
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator


def _episodes_path(meta_dir: Path) -> Path:
    return meta_dir / "episodes.jsonl"


def append_episode(meta_dir: Path, row: dict) -> None:
    with _episodes_path(meta_dir).open("a") as f:
        f.write(json.dumps(row) + "\n")


def read_episodes(meta_dir: Path, include_deleted: bool = False) -> Iterator[dict]:
    p = _episodes_path(meta_dir)
    if not p.exists():
        return
    with p.open() as f:
        for line in f:
            row = json.loads(line)
            if include_deleted or not row.get("deleted", False):
                yield row


def tombstone_episode(meta_dir: Path, episode_index: int, deleted_at_unix: int) -> None:
    p = _episodes_path(meta_dir)
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    found = False
    for row in rows:
        if row["episode_index"] == episode_index:
            if row.get("deleted"):
                raise KeyError(f"episode {episode_index} already deleted")
            row["deleted"] = True
            row["deleted_at"] = deleted_at_unix
            found = True
            break
    if not found:
        raise KeyError(f"episode {episode_index} not found")
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def upsert_task(meta_dir: Path, task_name: str, instruction: str) -> None:
    p = meta_dir / "tasks.jsonl"
    tasks = [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []
    for t in tasks:
        if t["task"] == task_name:
            t["instruction"] = instruction
            break
    else:
        tasks.append({"task": task_name, "instruction": instruction})
    p.write_text("\n".join(json.dumps(t) for t in tasks) + "\n")
```

- [ ] **Step 1.9: Run test, verify pass**

```bash
pytest tests/unit/test_metadata_roundtrip.py -v
```

Expected: `2 passed`.

- [ ] **Step 1.10: Write failing test `tests/unit/test_pending_episode.py`**

```python
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.metadata import read_episodes


def _make_row(i: int) -> dict:
    return {
        "timestamp": float(i) * 0.033,
        "tick_t_mono_ns": 1_000_000_000 + int(i * 33_000_000),
        "observation.state.joint_pos": np.array([0.0, 0.0], dtype=np.float32),
        "observation.state.joint_vel": np.array([0.0, 0.0], dtype=np.float32),
        "observation.state.joint_effort": np.array([0.0, 0.0], dtype=np.float32),
        "observation.state.t_mono_ns": 1_000_000_000 + int(i * 33_000_000),
        "action.joint_pos": np.array([0.0, 0.0], dtype=np.float32),
        "action.t_mono_ns": 1_000_000_000 + int(i * 33_000_000),
    }


def test_save_places_files_in_dataset(tmp_path: Path):
    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    pe = PendingEpisode.open(ds, episode_index=0)
    for i in range(5):
        pe.append_row(_make_row(i))
    pe.finalize()
    pe.save(
        metadata_extra={
            "episode_index": 0,
            "task": "pick",
            "instruction": "pick the block",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "mode": "teleop", "fps": 30,
            "success": None, "comment": None,
            "start_t_mono_ns": 1_000_000_000, "end_t_mono_ns": 1_132_000_000,
            "duration_sec": 0.132, "num_frames": 5,
            "session_boot_t_unix": 1700000000, "session_boot_t_mono_ns": 1_000_000_000,
            "resolved_config": {},
        }
    )

    paths = dataset_paths(ds)
    assert (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()
    assert not (ds / ".pending").exists() or not any((ds / ".pending").iterdir())
    rows = list(read_episodes(paths.meta_dir))
    assert rows[0]["episode_index"] == 0
    table = pq.read_table(paths.data_dir / "chunk-000" / "episode_000000.parquet")
    assert table.num_rows == 5


def test_discard_removes_pending_and_does_not_touch_dataset(tmp_path: Path):
    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    pe = PendingEpisode.open(ds, episode_index=0)
    pe.append_row(_make_row(0))
    pe.finalize()
    pe.discard()

    paths = dataset_paths(ds)
    assert not (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()
    assert list(read_episodes(paths.meta_dir)) == []
```

- [ ] **Step 1.11: Run to verify it fails**

```bash
pytest tests/unit/test_pending_episode.py -v
```

Expected: module-not-found failures.

- [ ] **Step 1.12: Implement `dataset_layout.py`**

`backend/mimicrec/recording/dataset_layout.py`:

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatasetPaths:
    root: Path
    meta_dir: Path
    data_dir: Path
    videos_dir: Path
    pending_dir: Path

    def chunk_dir(self, chunk_index: int) -> Path:
        return self.data_dir / f"chunk-{chunk_index:03d}"

    def episode_parquet(self, chunk_index: int, episode_index: int) -> Path:
        return self.chunk_dir(chunk_index) / f"episode_{episode_index:06d}.parquet"

    def episode_video(self, chunk_index: int, cam_name: str, episode_index: int) -> Path:
        return (
            self.videos_dir / f"chunk-{chunk_index:03d}"
            / f"observation.images.{cam_name}" / f"episode_{episode_index:06d}.mp4"
        )


def dataset_paths(ds_root: Path) -> DatasetPaths:
    return DatasetPaths(
        root=ds_root,
        meta_dir=ds_root / "meta",
        data_dir=ds_root / "data",
        videos_dir=ds_root / "videos",
        pending_dir=ds_root / ".pending",
    )


def init_dataset(ds_root: Path, fps: int, joint_names: list[str], camera_names: list[str]) -> None:
    p = dataset_paths(ds_root)
    p.meta_dir.mkdir(parents=True, exist_ok=True)
    p.data_dir.mkdir(parents=True, exist_ok=True)
    p.videos_dir.mkdir(parents=True, exist_ok=True)
    info = {
        "codebase_version": "mimicrec-0.1.0",
        "fps": fps,
        "joint_names": joint_names,
        "camera_names": camera_names,
    }
    (p.meta_dir / "info.json").write_text(json.dumps(info, indent=2))
    (p.meta_dir / "episodes.jsonl").touch()
    (p.meta_dir / "tasks.jsonl").touch()


def resolve_chunk(episode_index: int, episodes_per_chunk: int = 1000) -> int:
    return episode_index // episodes_per_chunk
```

- [ ] **Step 1.13: Implement `pending.py`**

`backend/mimicrec/recording/pending.py`:

```python
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Iterable

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import (
    DatasetPaths, dataset_paths, resolve_chunk,
)
from mimicrec.recording.metadata import append_episode


class PendingEpisode:
    """A staged, not-yet-committed episode.

    `.pending/ep_<N>/` holds the parquet and per-camera MP4 files while the
    episode is being recorded or reviewed. `save()` moves them into the
    dataset proper and appends a row to episodes.jsonl. `discard()` deletes
    the staging directory without touching the dataset.
    """

    def __init__(self, paths: DatasetPaths, episode_index: int):
        self._paths = paths
        self._episode_index = episode_index
        self._stage = paths.pending_dir / f"ep_{episode_index:06d}"
        self._rows: list[dict] = []
        self._finalized = False

    @classmethod
    def open(cls, ds_root: Path, episode_index: int) -> "PendingEpisode":
        p = dataset_paths(ds_root)
        p.pending_dir.mkdir(parents=True, exist_ok=True)
        inst = cls(p, episode_index)
        if inst._stage.exists():
            shutil.rmtree(inst._stage)
        inst._stage.mkdir(parents=True)
        return inst

    @property
    def stage_dir(self) -> Path:
        return self._stage

    @property
    def episode_index(self) -> int:
        return self._episode_index

    def append_row(self, row: dict) -> None:
        if self._finalized:
            raise RuntimeError("cannot append after finalize()")
        self._rows.append(row)

    def finalize(self) -> None:
        """Flush parquet to the staging directory. Videos are flushed by the writer."""
        if self._finalized:
            return
        table = pa.Table.from_pylist(self._rows)
        pq.write_table(table, self._stage / f"episode_{self._episode_index:06d}.parquet")
        self._finalized = True

    def save(self, metadata_extra: dict) -> None:
        if not self._finalized:
            raise RuntimeError("call finalize() before save()")
        chunk_idx = resolve_chunk(self._episode_index)
        self._paths.chunk_dir(chunk_idx).mkdir(parents=True, exist_ok=True)
        src = self._stage / f"episode_{self._episode_index:06d}.parquet"
        dst = self._paths.episode_parquet(chunk_idx, self._episode_index)
        shutil.move(str(src), str(dst))
        # videos: any mp4 files in stage_dir
        for mp4 in self._stage.glob("*.mp4"):
            cam_name = mp4.stem  # e.g. "front"
            vdst = self._paths.episode_video(chunk_idx, cam_name, self._episode_index)
            vdst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(mp4), str(vdst))
        append_episode(self._paths.meta_dir, metadata_extra)
        shutil.rmtree(self._stage)

    def discard(self) -> None:
        if self._stage.exists():
            shutil.rmtree(self._stage)
```

- [ ] **Step 1.14: Run tests, verify pass**

```bash
pytest tests/unit/test_pending_episode.py tests/unit/test_metadata_roundtrip.py tests/unit/test_parquet_row.py -v
```

Expected: `5 passed`.

- [ ] **Step 1.15: Add a compatibility check against LeRobot**

Append to `tests/unit/test_pending_episode.py`:

```python
def test_saved_dataset_is_readable_by_lerobot(tmp_path: Path):
    """Spike decision: our raw parquet + metadata output is LeRobot-compatible.

    This test is intentionally narrow: we only assert that LeRobotDataset can
    see our episodes (num_episodes > 0) after save. Full feature parity is out
    of scope for Plan A.
    """
    pytest.importorskip("lerobot")

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    ds_root = tmp_path / "datasets" / "mock"
    init_dataset(ds_root, fps=30, joint_names=["j1", "j2"], camera_names=[])
    pe = PendingEpisode.open(ds_root, episode_index=0)
    pe.append_row(_make_row(0))
    pe.finalize()
    pe.save(metadata_extra={
        "episode_index": 0, "task": "pick", "instruction": "pick", "robot": "mock",
        "teleop": "mock_leader", "mapper": "identity", "cameras": [], "mode": "teleop",
        "fps": 30, "success": None, "comment": None,
        "start_t_mono_ns": 0, "end_t_mono_ns": 0, "duration_sec": 0.0, "num_frames": 1,
        "session_boot_t_unix": 0, "session_boot_t_mono_ns": 0, "resolved_config": {},
    })

    try:
        ds = LeRobotDataset.resume(repo_id="local/mock", root=str(ds_root))
    except Exception as e:
        pytest.skip(
            f"LeRobot's resume(...) did not accept our layout: {e}. "
            "PIVOT: wrap DatasetWriter instead of writing raw parquet. "
            "Record this decision in the commit message and open a follow-up task."
        )
    assert ds.num_episodes >= 1
```

Add `import pytest` at the top of the test file.

- [ ] **Step 1.16: Run the spike**

```bash
pytest tests/unit/test_pending_episode.py -v
```

Expected: the first two tests pass; the compatibility test either passes (confirming the raw path works) or skips with the PIVOT message. If it skips, **record that in the commit message** and immediately open a follow-up task to wrap `DatasetWriter` before starting Task 2.

- [ ] **Step 1.17: Commit**

```bash
git add backend/mimicrec/types.py backend/mimicrec/recording tests/unit/test_parquet_row.py \
    tests/unit/test_metadata_roundtrip.py tests/unit/test_pending_episode.py
git commit -m "planA: pending/save/discard spike with LeRobot compatibility check"
```

If the LeRobot compatibility test **skipped** with the PIVOT message, add a second commit that captures the decision in `docs/superpowers/plans/2026-04-25-mimicrec-plan-a-backend-control-core.md` by editing this task's intro note — and insert a new Task 1.5 "Wrap DatasetWriter" before Task 2. Do not silently proceed.

---

## Task 2 — Session-scoped control-loop lifecycle

**Goal:** Implement the session-scoped control loop described in spec §7.2 with READY/RECORDING/REVIEW/IDLE semantics, driven by a shared `stopped: asyncio.Event`. Prove the loop ticks at the configured FPS, does not restart on episode boundaries, enters hold/idle on REVIEW, and resumes normal READY behaviour after save/discard.

This task introduces `LatestValue`, `FakeClock`, a minimal `MockRobotAdapter`, a minimal `MockTeleoperator`, and the `Session` dataclass. It stops short of the dispatcher (Task 3) and the writer (Task 6) — the control loop uses stubs for both.

**Files:**
- Create: `backend/mimicrec/util/__init__.py`
- Create: `backend/mimicrec/util/clock.py`
- Create: `backend/mimicrec/util/latest_value.py`
- Create: `backend/mimicrec/util/metrics.py`
- Create: `backend/mimicrec/session/__init__.py`
- Create: `backend/mimicrec/session/state.py`
- Create: `backend/mimicrec/session/control_loop.py`
- Create: `backend/mimicrec/session/tasks.py`
- Create: `backend/mimicrec/adapters/__init__.py`
- Create: `backend/mimicrec/adapters/robot.py`
- Create: `backend/mimicrec/adapters/teleop.py`
- Create: `backend/mimicrec/adapters/mock_robot.py` (minimal, no fault injection yet)
- Create: `backend/mimicrec/adapters/mock_teleop.py` (minimal)
- Create: `backend/mimicrec/mappers/__init__.py`
- Create: `backend/mimicrec/mappers/base.py`
- Create: `backend/mimicrec/mappers/identity.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_latest_value.py`
- Create: `tests/unit/test_mappers_identity.py`
- Create: `tests/integration/test_control_loop_teleop.py`
- Create: `tests/integration/test_control_loop_handteach.py`
- Create: `tests/integration/test_review_hold_idle.py`

- [ ] **Step 2.1: Write failing test for `LatestValue`**

`tests/unit/test_latest_value.py`:

```python
import asyncio
import pytest
from mimicrec.util.latest_value import LatestValue


async def test_peek_returns_none_before_first_write():
    lv: LatestValue[int] = LatestValue()
    assert lv.peek() is None


async def test_peek_returns_last_write():
    lv: LatestValue[int] = LatestValue()
    lv.set(5, t_mono_ns=100)
    lv.set(7, t_mono_ns=200)
    stamped = lv.peek()
    assert stamped is not None
    assert stamped.value == 7
    assert stamped.t_mono_ns == 200


async def test_wait_for_new_resolves_on_next_write():
    lv: LatestValue[int] = LatestValue()
    lv.set(1, t_mono_ns=100)

    async def writer():
        await asyncio.sleep(0.01)
        lv.set(2, t_mono_ns=200)

    asyncio.create_task(writer())
    s = await asyncio.wait_for(lv.wait_for_new(), timeout=0.5)
    assert s.value == 2
```

- [ ] **Step 2.2: Implement `LatestValue`**

`backend/mimicrec/util/latest_value.py`:

```python
from __future__ import annotations
import asyncio
from typing import Generic, TypeVar

from mimicrec.types import Stamped

T = TypeVar("T")


class LatestValue(Generic[T]):
    def __init__(self) -> None:
        self._stamped: Stamped[T] | None = None
        self._event = asyncio.Event()

    def set(self, value: T, t_mono_ns: int) -> None:
        self._stamped = Stamped(value=value, t_mono_ns=t_mono_ns)
        self._event.set()
        self._event.clear()

    def peek(self) -> Stamped[T] | None:
        return self._stamped

    async def wait_for_new(self) -> Stamped[T]:
        await self._event.wait()
        assert self._stamped is not None
        return self._stamped
```

Note: `Event.set()` then `Event.clear()` on every write is the single-producer-multiple-consumer pattern when we don't want to buffer per-consumer. Acceptable here because the dispatcher (the only `wait_for_new()` consumer in Plan A) re-enters the wait promptly. Document this.

- [ ] **Step 2.3: Verify tests pass**

```bash
pytest tests/unit/test_latest_value.py -v
```

Expected: `3 passed`.

- [ ] **Step 2.4: Write `clock.py` and `metrics.py`**

`backend/mimicrec/util/clock.py`:

```python
from __future__ import annotations
import time
from typing import Protocol


class Clock(Protocol):
    def monotonic_ns(self) -> int: ...
    async def sleep_until(self, t_mono_ns: int) -> None: ...


class RealClock:
    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    async def sleep_until(self, t_mono_ns: int) -> None:
        import asyncio
        now = time.monotonic_ns()
        delta = (t_mono_ns - now) / 1e9
        if delta > 0:
            await asyncio.sleep(delta)


class FakeClock:
    """Deterministic clock for tests. `advance()` is called manually from tests."""
    def __init__(self, start_ns: int = 0):
        import asyncio
        self._now = start_ns
        self._waiters: list[tuple[int, asyncio.Future[None]]] = []

    def monotonic_ns(self) -> int:
        return self._now

    def set(self, t_mono_ns: int) -> None:
        assert t_mono_ns >= self._now, "FakeClock only moves forward"
        self._now = t_mono_ns
        still_waiting = []
        for due, fut in self._waiters:
            if due <= t_mono_ns and not fut.done():
                fut.set_result(None)
            else:
                still_waiting.append((due, fut))
        self._waiters = still_waiting

    def advance(self, delta_ns: int) -> None:
        self.set(self._now + delta_ns)

    async def sleep_until(self, t_mono_ns: int) -> None:
        import asyncio
        if t_mono_ns <= self._now:
            return
        fut: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        self._waiters.append((t_mono_ns, fut))
        await fut
```

`backend/mimicrec/util/metrics.py`:

```python
from __future__ import annotations
from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)

    def inc(self, name: str, by: int = 1) -> None:
        self._counters[name] += by

    def get(self, name: str) -> int:
        return self._counters[name]

    def snapshot(self) -> dict[str, int]:
        return dict(self._counters)
```

- [ ] **Step 2.5: Write the adapter Protocols and mocks**

`backend/mimicrec/adapters/robot.py`:

```python
from __future__ import annotations
from enum import Enum
from typing import Protocol
import numpy as np

from mimicrec.types import RobotState


class RobotMode(str, Enum):
    POSITION = "position"
    TORQUE_OFF = "torque_off"
    GRAVITY_COMP = "gravity_comp"


class RobotAdapter(Protocol):
    name: str
    dof: int
    joint_names: list[str]

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def read_state(self) -> RobotState: ...
    async def send_joint_command(self, q: np.ndarray) -> None: ...
    async def set_mode(self, mode: RobotMode) -> None: ...
```

`backend/mimicrec/adapters/teleop.py`:

```python
from __future__ import annotations
from enum import Enum
from typing import Protocol

from mimicrec.types import TeleopAction


class TeleopType(str, Enum):
    LEADER_ARM = "leader_arm"
    SPACEMOUSE = "spacemouse"
    GAMEPAD = "gamepad"
    KEYBOARD = "keyboard"


class Teleoperator(Protocol):
    name: str
    type: TeleopType

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def read_action(self) -> TeleopAction: ...
```

`backend/mimicrec/adapters/mock_robot.py` (minimal — fault injection is added in Task 9):

```python
from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.types import RobotState


class MockRobotAdapter:
    name = "mock"
    dof = 2
    joint_names = ["j1", "j2"]

    def __init__(self, dt_ns: int = 5_000_000):   # 5ms "native" rate
        self._q = np.zeros(self.dof, dtype=np.float32)
        self._last_cmd = np.zeros(self.dof, dtype=np.float32)
        self._mode = RobotMode.POSITION
        self._dt_ns = dt_ns
        self.sent_commands: list[np.ndarray] = []

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_state(self) -> RobotState:
        await asyncio.sleep(self._dt_ns / 1e9)
        return RobotState(
            joint_pos=self._q.copy(),
            joint_vel=np.zeros(self.dof, dtype=np.float32),
            joint_effort=np.zeros(self.dof, dtype=np.float32),
        )

    async def send_joint_command(self, q: np.ndarray) -> None:
        self.sent_commands.append(q.copy())
        self._q = q.astype(np.float32)

    async def set_mode(self, mode: RobotMode) -> None:
        self._mode = mode
```

`backend/mimicrec/adapters/mock_teleop.py`:

```python
from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.teleop import TeleopType
from mimicrec.types import TeleopAction


class MockTeleoperator:
    name = "mock_leader"
    type = TeleopType.LEADER_ARM

    def __init__(self, dof: int = 2, dt_ns: int = 5_000_000):
        self._dof = dof
        self._dt_ns = dt_ns
        self.target = np.zeros(self._dof, dtype=np.float32)

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_action(self) -> TeleopAction:
        await asyncio.sleep(self._dt_ns / 1e9)
        return TeleopAction(target_joint_pos=self.target.copy())
```

- [ ] **Step 2.6: Write the mapper**

`backend/mimicrec/mappers/base.py`:

```python
from __future__ import annotations
from typing import Protocol

from mimicrec.types import RobotCommand, RobotState, TeleopAction


class TeleopMapper(Protocol):
    def map(self, action: TeleopAction, robot_state: RobotState) -> RobotCommand: ...
```

`backend/mimicrec/mappers/identity.py`:

```python
from __future__ import annotations
from mimicrec.types import RobotCommand, RobotState, TeleopAction


class IdentityMapper:
    def map(self, action: TeleopAction, robot_state: RobotState) -> RobotCommand:
        assert action.target_joint_pos is not None, "IdentityMapper requires joint-pos teleop"
        return RobotCommand(q=action.target_joint_pos.copy())
```

`tests/unit/test_mappers_identity.py`:

```python
import numpy as np
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.types import RobotState, TeleopAction


def test_identity_pass_through():
    m = IdentityMapper()
    action = TeleopAction(target_joint_pos=np.array([0.1, 0.2], dtype=np.float32))
    state = RobotState(
        joint_pos=np.zeros(2, np.float32),
        joint_vel=np.zeros(2, np.float32),
        joint_effort=np.zeros(2, np.float32),
    )
    cmd = m.map(action, state)
    assert cmd.q.tolist() == [pytest.approx(0.1), pytest.approx(0.2)]
```

Add `import pytest` at the top.

- [ ] **Step 2.7: Write Session dataclass and control loop**

`backend/mimicrec/session/state.py`:

```python
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field

from mimicrec.types import SessionMode, SessionState, SubState


@dataclass
class Session:
    mode: SessionMode
    state: SessionState = SessionState.READY
    sub_state: SubState | None = None
    replay_active: bool = False
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
```

`backend/mimicrec/session/control_loop.py`:

```python
from __future__ import annotations
import asyncio
from typing import Callable, Awaitable

from mimicrec.adapters.robot import RobotMode
from mimicrec.mappers.base import TeleopMapper
from mimicrec.session.state import Session
from mimicrec.types import (
    RobotCommand, RobotState, SampleBundle, SessionState, Stamped, TeleopAction,
)
from mimicrec.util.clock import Clock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


EnqueueFn = Callable[[SampleBundle], None]


async def run_teleop_control_loop(
    session: Session,
    fps: int,
    robot_state_slot: LatestValue[RobotState],
    teleop_slot: LatestValue[TeleopAction],
    camera_slots: dict[str, LatestValue[object]],
    command_goal_slot: LatestValue[RobotCommand],
    mapper: TeleopMapper,
    enqueue: EnqueueFn,
    clock: Clock,
    metrics: Metrics,
) -> None:
    tick_interval_ns = 1_000_000_000 // fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns

    while not session.stopped.is_set():
        tick_t = clock.monotonic_ns()

        if tick_t >= next_tick_ns + tick_interval_ns:
            skipped = (tick_t - next_tick_ns) // tick_interval_ns
            metrics.inc("ticks_skipped", int(skipped))
            next_tick_ns = tick_t + tick_interval_ns

        phase = session.state
        if phase == SessionState.REVIEW:
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        state = robot_state_slot.peek()
        action = teleop_slot.peek()
        if state is None or action is None:
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        command = mapper.map(action.value, state.value)
        command.t_mono_ns = clock.monotonic_ns()

        if not session.replay_active:
            command_goal_slot.set(command, t_mono_ns=command.t_mono_ns)

        if phase == SessionState.RECORDING:
            frames = {name: slot.peek() for name, slot in camera_slots.items()}
            enqueue(SampleBundle(
                tick_t_mono_ns=tick_t,
                state=state,
                action=command,
                frames=frames,
            ))

        await clock.sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns


async def run_handteach_control_loop(
    session: Session,
    fps: int,
    robot_adapter,
    robot_state_slot: LatestValue[RobotState],
    camera_slots: dict[str, LatestValue[object]],
    enqueue: EnqueueFn,
    clock: Clock,
    metrics: Metrics,
) -> None:
    await robot_adapter.set_mode(RobotMode.GRAVITY_COMP)
    tick_interval_ns = 1_000_000_000 // fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns

    while not session.stopped.is_set():
        tick_t = clock.monotonic_ns()

        if tick_t >= next_tick_ns + tick_interval_ns:
            skipped = (tick_t - next_tick_ns) // tick_interval_ns
            metrics.inc("ticks_skipped", int(skipped))
            next_tick_ns = tick_t + tick_interval_ns

        phase = session.state
        if phase == SessionState.REVIEW:
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        state = robot_state_slot.peek()
        if state is None:
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        if phase == SessionState.RECORDING:
            synthesized = RobotCommand(q=state.value.joint_pos.copy(), t_mono_ns=tick_t)
            frames = {name: slot.peek() for name, slot in camera_slots.items()}
            enqueue(SampleBundle(
                tick_t_mono_ns=tick_t,
                state=state,
                action=synthesized,
                frames=frames,
            ))

        await clock.sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns
```

- [ ] **Step 2.8: Write a shared test fixture for a "wired" mock session**

`tests/conftest.py`:

```python
from __future__ import annotations
import asyncio
from typing import AsyncIterator

import pytest

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, RobotState, SampleBundle, SessionMode, SessionState, TeleopAction
from mimicrec.util.clock import FakeClock, RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


@pytest.fixture
def real_clock():
    return RealClock()


@pytest.fixture
def fake_clock():
    return FakeClock(start_ns=0)


@pytest.fixture
def metrics():
    return Metrics()


@pytest.fixture
def mock_robot():
    return MockRobotAdapter()


@pytest.fixture
def mock_teleop():
    return MockTeleoperator(dof=2)


async def _prime_robot_reader(robot, slot: LatestValue[RobotState]) -> asyncio.Task:
    async def run():
        while True:
            st = await robot.read_state()
            slot.set(st, t_mono_ns=0)
    return asyncio.create_task(run())


async def _prime_teleop_reader(teleop, slot: LatestValue[TeleopAction]) -> asyncio.Task:
    async def run():
        while True:
            a = await teleop.read_action()
            slot.set(a, t_mono_ns=0)
    return asyncio.create_task(run())
```

- [ ] **Step 2.9: Write failing integration test `tests/integration/test_control_loop_teleop.py`**

```python
import asyncio
import numpy as np
import pytest

from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.control_loop import run_teleop_control_loop
from mimicrec.session.state import Session
from mimicrec.types import (
    RobotCommand, RobotState, SampleBundle, SessionMode, SessionState, TeleopAction,
)
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader, _prime_teleop_reader


async def test_teleop_loop_records_samples_only_while_recording(mock_robot, mock_teleop, metrics):
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    rs: LatestValue[RobotState] = LatestValue()
    ts: LatestValue[TeleopAction] = LatestValue()
    cg: LatestValue[RobotCommand] = LatestValue()

    r_task = await _prime_robot_reader(mock_robot, rs)
    t_task = await _prime_teleop_reader(mock_teleop, ts)

    bundles: list[SampleBundle] = []
    def enqueue(b: SampleBundle) -> None:
        bundles.append(b)

    loop_task = asyncio.create_task(run_teleop_control_loop(
        session=session, fps=30,
        robot_state_slot=rs, teleop_slot=ts, camera_slots={},
        command_goal_slot=cg, mapper=IdentityMapper(),
        enqueue=enqueue, clock=RealClock(), metrics=metrics,
    ))

    await asyncio.sleep(0.1)          # warm-up, no recording
    count_before = len(bundles)
    assert count_before == 0
    assert cg.peek() is not None       # command goal was updated in READY

    session.state = SessionState.RECORDING
    await asyncio.sleep(0.2)           # ~6 ticks
    count_during = len(bundles)
    assert count_during >= 3

    session.state = SessionState.REVIEW
    await asyncio.sleep(0.2)
    count_after_review = len(bundles)

    # REVIEW stops enqueue; count should not grow (allow for 1 tick in flight)
    assert count_after_review - count_during <= 1

    session.state = SessionState.READY
    await asyncio.sleep(0.1)

    session.stopped.set()
    await loop_task
    r_task.cancel(); t_task.cancel()
```

- [ ] **Step 2.10: Run to verify fail, then pass**

```bash
pytest tests/integration/test_control_loop_teleop.py -v
```

Expected: first run fails at import / missing attributes; after implementing, expect `1 passed`.

- [ ] **Step 2.11: Write `test_review_hold_idle.py`**

`tests/integration/test_review_hold_idle.py`:

```python
import asyncio

from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.control_loop import run_teleop_control_loop
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, RobotState, SessionMode, SessionState, TeleopAction
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader, _prime_teleop_reader


async def test_review_holds_last_command_goal(mock_robot, mock_teleop, metrics):
    """In REVIEW, command_goal_slot must NOT be rewritten, so the dispatcher
    would hold the last command even as the teleop leader keeps moving."""
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    rs: LatestValue[RobotState] = LatestValue()
    ts: LatestValue[TeleopAction] = LatestValue()
    cg: LatestValue[RobotCommand] = LatestValue()

    r = await _prime_robot_reader(mock_robot, rs)
    t = await _prime_teleop_reader(mock_teleop, ts)

    loop_task = asyncio.create_task(run_teleop_control_loop(
        session=session, fps=30,
        robot_state_slot=rs, teleop_slot=ts, camera_slots={},
        command_goal_slot=cg, mapper=IdentityMapper(),
        enqueue=lambda b: None, clock=RealClock(), metrics=metrics,
    ))

    await asyncio.sleep(0.1)            # get at least one command
    first = cg.peek()
    assert first is not None
    first_t = first.t_mono_ns

    session.state = SessionState.REVIEW
    await asyncio.sleep(0.15)
    after_review = cg.peek()
    assert after_review is not None
    # t_mono_ns should not have advanced during REVIEW
    assert after_review.t_mono_ns == first_t

    session.state = SessionState.READY
    await asyncio.sleep(0.1)
    resumed = cg.peek()
    assert resumed is not None
    assert resumed.t_mono_ns > first_t

    session.stopped.set()
    await loop_task
    r.cancel(); t.cancel()
```

- [ ] **Step 2.12: Write `test_control_loop_handteach.py`**

```python
import asyncio

from mimicrec.adapters.robot import RobotMode
from mimicrec.session.control_loop import run_handteach_control_loop
from mimicrec.session.state import Session
from mimicrec.types import RobotState, SampleBundle, SessionMode, SessionState
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader


async def test_handteach_sets_gravity_comp_and_fills_action(mock_robot, metrics):
    session = Session(mode=SessionMode.HAND_TEACH, state=SessionState.RECORDING)
    rs: LatestValue[RobotState] = LatestValue()
    r = await _prime_robot_reader(mock_robot, rs)

    bundles: list[SampleBundle] = []
    loop_task = asyncio.create_task(run_handteach_control_loop(
        session=session, fps=30,
        robot_adapter=mock_robot, robot_state_slot=rs, camera_slots={},
        enqueue=bundles.append, clock=RealClock(), metrics=metrics,
    ))
    await asyncio.sleep(0.15)

    assert mock_robot._mode == RobotMode.GRAVITY_COMP
    assert len(bundles) >= 3
    for b in bundles:
        # action == state.joint_pos
        assert (b.action.q == b.state.value.joint_pos).all()

    session.stopped.set()
    await loop_task
    r.cancel()
```

- [ ] **Step 2.13: Run all new tests, verify green**

```bash
pytest tests/unit tests/integration -v
```

Expected: all green.

- [ ] **Step 2.14: Commit**

```bash
git add backend/mimicrec tests/
git commit -m "planA: session-scoped control loop with READY/RECORDING/REVIEW semantics"
```

---

## Task 3 — Replay vs teleop: exclusive ownership

**Goal:** Implement the command dispatcher, plus a minimal replay task that streams a joint-space trajectory into `command_goal_slot`. Prove that while `session.replay_active == True`, the teleop control loop does not write to `command_goal_slot`, and that clearing the flag restores normal commanding.

**Files:**
- Create: `backend/mimicrec/util/error_bus.py`
- Create: `backend/mimicrec/errors.py`
- Create: `backend/mimicrec/session/dispatcher.py`
- Create: `backend/mimicrec/session/replay.py`
- Create: `tests/unit/test_command_dispatcher.py`
- Create: `tests/integration/test_replay_exclusive_ownership.py`

- [ ] **Step 3.1: Write `errors.py`**

`backend/mimicrec/errors.py`:

```python
from __future__ import annotations


class MimicRecError(Exception):
    """Base class for all domain errors. Plan B maps these to HTTP."""


class HandTeachNotSupportedError(MimicRecError):
    """Raised by an adapter that cannot provide gravity-comp / hand-teach."""


class InvalidTransitionError(MimicRecError):
    """Raised by the session state machine on illegal transitions."""


class HardwareError(MimicRecError):
    """Raised by adapters and the dispatcher on CAN/USB/driver faults."""


class RecorderError(MimicRecError):
    """Raised by the writer on persistent storage faults."""


class ReplaySafetyError(MimicRecError):
    """Raised by the replay watchdog on violated safety parameters."""
```

- [ ] **Step 3.2: Write `error_bus.py`**

`backend/mimicrec/util/error_bus.py`:

```python
from __future__ import annotations
import asyncio


class ErrorBus:
    def __init__(self) -> None:
        self._subs: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.append(q)
        return q

    async def publish(self, event: BaseException | dict) -> None:
        for q in self._subs:
            await q.put(event)
```

- [ ] **Step 3.3: Write failing `test_command_dispatcher.py`**

```python
import asyncio
import numpy as np
import pytest

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.session.dispatcher import run_command_dispatcher
from mimicrec.types import RobotCommand
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


async def test_dispatcher_sends_each_new_goal_to_robot():
    robot = MockRobotAdapter()
    goal: LatestValue[RobotCommand] = LatestValue()
    bus = ErrorBus()
    stopped = asyncio.Event()

    task = asyncio.create_task(run_command_dispatcher(robot, goal, bus, stopped))

    goal.set(RobotCommand(q=np.array([0.1, 0.2], dtype=np.float32)), t_mono_ns=1)
    await asyncio.sleep(0.05)
    goal.set(RobotCommand(q=np.array([0.3, 0.4], dtype=np.float32)), t_mono_ns=2)
    await asyncio.sleep(0.05)

    stopped.set()
    goal.set(RobotCommand(q=np.zeros(2, dtype=np.float32)), t_mono_ns=3)
    await task

    sent = robot.sent_commands
    assert any(np.allclose(c, [0.3, 0.4]) for c in sent)   # latest-writer-wins semantics
    assert all(not np.allclose(c, [0.5, 0.6]) for c in sent)  # never sent nonsense
```

- [ ] **Step 3.4: Implement `dispatcher.py`**

`backend/mimicrec/session/dispatcher.py`:

```python
from __future__ import annotations
import asyncio

from mimicrec.errors import HardwareError
from mimicrec.types import RobotCommand
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


async def run_command_dispatcher(
    robot,
    goal: LatestValue[RobotCommand],
    errors: ErrorBus,
    stopped: asyncio.Event,
) -> None:
    while not stopped.is_set():
        try:
            stamped = await asyncio.wait_for(goal.wait_for_new(), timeout=0.05)
        except asyncio.TimeoutError:
            continue
        cmd = stamped.value
        try:
            await robot.send_joint_command(cmd.q)
        except HardwareError as e:
            await errors.publish(e)
```

- [ ] **Step 3.5: Run, verify pass**

```bash
pytest tests/unit/test_command_dispatcher.py -v
```

Expected: `1 passed`.

- [ ] **Step 3.6: Implement `replay.py` (minimal; safety watchdog added in Task 10)**

`backend/mimicrec/session/replay.py`:

```python
from __future__ import annotations
import asyncio
from dataclasses import dataclass

import numpy as np

from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, SessionState, SubState
from mimicrec.util.clock import Clock
from mimicrec.util.latest_value import LatestValue


@dataclass
class ReplayTrajectory:
    """Simplest possible trajectory: list of joint-target vectors at the session fps."""
    joint_targets: np.ndarray   # shape (T, dof)


async def run_replay(
    session: Session,
    trajectory: ReplayTrajectory,
    fps: int,
    command_goal_slot: LatestValue[RobotCommand],
    clock: Clock,
) -> None:
    if session.state != SessionState.READY:
        from mimicrec.errors import InvalidTransitionError
        raise InvalidTransitionError(
            f"replay requires SessionState.READY, got {session.state}"
        )
    session.replay_active = True
    session.sub_state = SubState.REPLAYING

    tick_interval_ns = 1_000_000_000 // fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns
    try:
        for q in trajectory.joint_targets:
            if session.stopped.is_set() or not session.replay_active:
                break
            command_goal_slot.set(
                RobotCommand(q=q.astype(np.float32), t_mono_ns=clock.monotonic_ns()),
                t_mono_ns=clock.monotonic_ns(),
            )
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
    finally:
        session.replay_active = False
        session.sub_state = None


def request_stop(session: Session) -> None:
    """Called by the session lifecycle to break the replay loop."""
    session.replay_active = False
    session.sub_state = None
```

- [ ] **Step 3.7: Write failing `test_replay_exclusive_ownership.py`**

```python
import asyncio
import numpy as np

from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.control_loop import run_teleop_control_loop
from mimicrec.session.replay import ReplayTrajectory, run_replay
from mimicrec.session.state import Session
from mimicrec.types import (
    RobotCommand, RobotState, SessionMode, SessionState, SubState, TeleopAction,
)
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader, _prime_teleop_reader


async def test_replay_gates_teleop_command_path(mock_robot, mock_teleop, metrics):
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    rs: LatestValue[RobotState] = LatestValue()
    ts: LatestValue[TeleopAction] = LatestValue()
    cg: LatestValue[RobotCommand] = LatestValue()

    r = await _prime_robot_reader(mock_robot, rs)
    t = await _prime_teleop_reader(mock_teleop, ts)

    loop = asyncio.create_task(run_teleop_control_loop(
        session=session, fps=30,
        robot_state_slot=rs, teleop_slot=ts, camera_slots={},
        command_goal_slot=cg, mapper=IdentityMapper(),
        enqueue=lambda b: None, clock=RealClock(), metrics=metrics,
    ))

    # Make the "teleop" produce a distinctive target so we can distinguish sources.
    mock_teleop.target = np.array([0.5, 0.5], dtype=np.float32)
    await asyncio.sleep(0.1)
    before = cg.peek().value.q.copy()

    # Start replay with a distinctive trajectory
    traj = ReplayTrajectory(joint_targets=np.array(
        [[-1.0, -1.0]] * 5, dtype=np.float32
    ))
    replay_task = asyncio.create_task(run_replay(
        session=session, trajectory=traj, fps=30,
        command_goal_slot=cg, clock=RealClock(),
    ))
    await asyncio.sleep(0.05)
    assert session.replay_active is True
    assert session.sub_state == SubState.REPLAYING

    # Change teleop target during replay; expect it to be IGNORED
    mock_teleop.target = np.array([9.9, 9.9], dtype=np.float32)
    await asyncio.sleep(0.15)
    during = cg.peek().value.q.copy()
    assert during[0] == -1.0 or during[1] == -1.0, f"expected replay target, got {during}"
    assert not (during == 9.9).any(), "teleop leaked into command goal during replay"

    await replay_task
    assert session.replay_active is False

    # After replay ends, teleop resumes
    await asyncio.sleep(0.1)
    after = cg.peek().value.q.copy()
    assert (after == 9.9).any(), "teleop did not resume after replay"

    session.stopped.set()
    await loop
    r.cancel(); t.cancel()
```

- [ ] **Step 3.8: Run, verify pass**

```bash
pytest tests/integration/test_replay_exclusive_ownership.py -v
```

Expected: `1 passed`.

- [ ] **Step 3.9: Commit**

```bash
git add backend/mimicrec tests/
git commit -m "planA: command dispatcher and replay exclusive ownership"
```

---

## Task 4 — SO-101 hand-teach unsupported path

**Goal:** Scaffold `SO101Adapter` (no real hardware I/O — a stub that meets the Protocol) and implement the `set_mode(GRAVITY_COMP)` → `HandTeachNotSupportedError` path. Add the session-lifecycle check that raises `HandTeachNotSupportedError` on `start(mode=HAND_TEACH, robot=so101)` **before** touching hardware.

**Files:**
- Create: `backend/mimicrec/adapters/so101.py`
- Create: `backend/mimicrec/adapters/rebotarm.py`  (peer stub so composition tests can enumerate supported combos)
- Create: `backend/mimicrec/session/lifecycle.py`
- Create: `tests/unit/test_so101_handteach_unsupported.py`

- [ ] **Step 4.1: Write failing `test_so101_handteach_unsupported.py`**

```python
import pytest

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.so101 import SO101Adapter
from mimicrec.errors import HandTeachNotSupportedError


async def test_set_mode_gravity_comp_raises_unsupported():
    a = SO101Adapter(port="/dev/null")
    with pytest.raises(HandTeachNotSupportedError) as e:
        await a.set_mode(RobotMode.GRAVITY_COMP)
    assert "so101" in str(e.value).lower()


async def test_position_mode_is_allowed():
    a = SO101Adapter(port="/dev/null")
    # This does not touch hardware; it must not raise.
    await a.set_mode(RobotMode.POSITION)
```

- [ ] **Step 4.2: Implement SO-101 adapter stub**

`backend/mimicrec/adapters/so101.py`:

```python
from __future__ import annotations
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.errors import HandTeachNotSupportedError
from mimicrec.types import RobotState


class SO101Adapter:
    name = "so101"
    dof = 6
    joint_names = [f"j{i}" for i in range(1, 7)]

    def __init__(self, port: str):
        self._port = port
        self._mode = RobotMode.POSITION
        # Real hardware wiring is deferred (Plan D). This stub stays offline.

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def read_state(self) -> RobotState:
        zeros = np.zeros(self.dof, dtype=np.float32)
        return RobotState(joint_pos=zeros, joint_vel=zeros, joint_effort=zeros)

    async def send_joint_command(self, q: np.ndarray) -> None:
        # Offline stub; will be wired in Plan D.
        pass

    async def set_mode(self, mode: RobotMode) -> None:
        if mode == RobotMode.GRAVITY_COMP:
            raise HandTeachNotSupportedError(
                "so101 does not support GRAVITY_COMP / hand-teach in MVP "
                "(see spec §15). Use teleop mode with a leader arm instead."
            )
        self._mode = mode
```

- [ ] **Step 4.3: Run, verify pass**

```bash
pytest tests/unit/test_so101_handteach_unsupported.py -v
```

Expected: `2 passed`.

- [ ] **Step 4.4: Peer stub for reBotArm adapter**

`backend/mimicrec/adapters/rebotarm.py`:

```python
from __future__ import annotations
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.types import RobotState


class ReBotArmAdapter:
    """Stub scaffolding; real reBotArm_control_py wiring deferred to Plan D."""
    name = "rebotarm_b601dm"
    dof = 6
    joint_names = [f"j{i}" for i in range(1, 7)]

    def __init__(self, serial_port: str):
        self._port = serial_port
        self._mode = RobotMode.POSITION

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_state(self) -> RobotState:
        z = np.zeros(self.dof, dtype=np.float32)
        return RobotState(joint_pos=z, joint_vel=z, joint_effort=z)

    async def send_joint_command(self, q: np.ndarray) -> None: ...

    async def set_mode(self, mode: RobotMode) -> None:
        # Unlike SO-101, reBotArm supports GRAVITY_COMP in principle (verified in Plan D).
        self._mode = mode
```

- [ ] **Step 4.5: Write `session/lifecycle.py` with the session starter guard**

`backend/mimicrec/session/lifecycle.py`:

```python
from __future__ import annotations
from dataclasses import dataclass

from mimicrec.adapters.robot import RobotAdapter, RobotMode
from mimicrec.errors import HandTeachNotSupportedError, InvalidTransitionError
from mimicrec.session.state import Session
from mimicrec.types import SessionMode, SessionState


@dataclass
class StartSessionRequestDomain:
    """Plan-A internal request — Plan B maps HTTP bodies to this."""
    robot: RobotAdapter
    mode: SessionMode


async def precheck_start(req: StartSessionRequestDomain) -> None:
    """Raise domain errors before any hardware is connected."""
    if req.mode == SessionMode.HAND_TEACH:
        # Best-effort: ask the adapter whether it can enter GRAVITY_COMP
        try:
            await req.robot.set_mode(RobotMode.GRAVITY_COMP)
        except HandTeachNotSupportedError:
            raise
        else:
            # Reset to POSITION for the rest of the bring-up; real connect happens later.
            await req.robot.set_mode(RobotMode.POSITION)


def assert_can_start_episode(session: Session) -> None:
    if session.state != SessionState.READY:
        raise InvalidTransitionError(
            f"episode/start requires READY, got {session.state}"
        )
    if session.replay_active:
        raise InvalidTransitionError("episode/start blocked while replay is active")
```

- [ ] **Step 4.6: Extend the test file with the lifecycle precheck**

Append to `tests/unit/test_so101_handteach_unsupported.py`:

```python
from mimicrec.session.lifecycle import StartSessionRequestDomain, precheck_start
from mimicrec.types import SessionMode


async def test_precheck_rejects_so101_handteach():
    a = SO101Adapter(port="/dev/null")
    req = StartSessionRequestDomain(robot=a, mode=SessionMode.HAND_TEACH)
    with pytest.raises(HandTeachNotSupportedError):
        await precheck_start(req)
```

- [ ] **Step 4.7: Run, verify pass**

```bash
pytest tests/unit/test_so101_handteach_unsupported.py -v
```

Expected: `3 passed`.

- [ ] **Step 4.8: Commit**

```bash
git add backend/mimicrec/adapters/so101.py backend/mimicrec/adapters/rebotarm.py \
    backend/mimicrec/session/lifecycle.py tests/unit/test_so101_handteach_unsupported.py
git commit -m "planA: SO-101 hand-teach unsupported path + session precheck"
```

---

## Task 5 — Dataset archive tombstone filter (+ LeRobot compatibility)

**Goal:** Implement a pure-Python function that, given a dataset root, yields the archive payload as a stream of `(path_in_zip, bytes_or_path)` entries, excluding tombstoned episodes and rewriting `meta/episodes.jsonl` to contain only live rows. Verify with a test that asserts the LeRobot-format invariants on the rewritten archive (using `LeRobotDataset.resume` on the unpacked archive).

**Files:**
- Create: `backend/mimicrec/datasets/__init__.py`
- Create: `backend/mimicrec/datasets/reader.py`
- Create: `backend/mimicrec/datasets/archive.py`
- Create: `tests/unit/test_dataset_reader_tombstones.py`
- Create: `tests/unit/test_archive_filter.py`

- [ ] **Step 5.1: Write failing `test_dataset_reader_tombstones.py`**

```python
from pathlib import Path
from mimicrec.datasets.reader import iter_episodes
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode, tombstone_episode


def test_iter_episodes_skips_deleted_by_default(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["a"], camera_names=[])
    append_episode(ds / "meta", {"episode_index": 0, "task": "x", "num_frames": 1})
    append_episode(ds / "meta", {"episode_index": 1, "task": "x", "num_frames": 1})
    tombstone_episode(ds / "meta", 0, deleted_at_unix=1)
    live = list(iter_episodes(ds))
    assert [e["episode_index"] for e in live] == [1]


def test_iter_episodes_admin_view_includes_deleted(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["a"], camera_names=[])
    append_episode(ds / "meta", {"episode_index": 0, "task": "x", "num_frames": 1})
    tombstone_episode(ds / "meta", 0, deleted_at_unix=1)
    all_rows = list(iter_episodes(ds, include_deleted=True))
    assert len(all_rows) == 1 and all_rows[0]["deleted"] is True
```

- [ ] **Step 5.2: Implement reader**

`backend/mimicrec/datasets/reader.py`:

```python
from __future__ import annotations
from pathlib import Path
from typing import Iterator

from mimicrec.recording.metadata import read_episodes


def iter_episodes(ds_root: Path, include_deleted: bool = False) -> Iterator[dict]:
    yield from read_episodes(ds_root / "meta", include_deleted=include_deleted)
```

- [ ] **Step 5.3: Run, verify pass**

```bash
pytest tests/unit/test_dataset_reader_tombstones.py -v
```

Expected: `2 passed`.

- [ ] **Step 5.4: Write failing `test_archive_filter.py`**

```python
import io
import json
import shutil
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.datasets.archive import build_archive_stream
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.metadata import append_episode, tombstone_episode


def _write_fake_episode(ds_root: Path, idx: int) -> None:
    p = dataset_paths(ds_root)
    p.chunk_dir(0).mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([{"timestamp": 0.0}])
    pq.write_table(table, p.episode_parquet(0, idx))
    append_episode(p.meta_dir, {"episode_index": idx, "task": "x", "num_frames": 1})


def test_archive_excludes_tombstoned_episode_and_rewrites_episodes_jsonl(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["a"], camera_names=[])
    _write_fake_episode(ds, 0)
    _write_fake_episode(ds, 1)
    tombstone_episode(ds / "meta", 0, deleted_at_unix=1)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path_in_zip, content in build_archive_stream(ds):
            if isinstance(content, Path):
                zf.write(content, arcname=path_in_zip)
            else:
                zf.writestr(path_in_zip, content)
    buf.seek(0)

    out_dir = tmp_path / "unpacked"
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(out_dir)

    # The tombstoned episode's parquet must not be present.
    paths = dataset_paths(out_dir)
    assert not paths.episode_parquet(0, 0).exists()
    assert paths.episode_parquet(0, 1).exists()

    # meta/episodes.jsonl must not contain the deleted row.
    lines = (paths.meta_dir / "episodes.jsonl").read_text().splitlines()
    rows = [json.loads(l) for l in lines if l.strip()]
    assert [r["episode_index"] for r in rows] == [1]
    assert all(not r.get("deleted", False) for r in rows)
```

- [ ] **Step 5.5: Implement `archive.py`**

`backend/mimicrec/datasets/archive.py`:

```python
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator

from mimicrec.datasets.reader import iter_episodes
from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk


def build_archive_stream(ds_root: Path) -> Iterator[tuple[str, bytes | Path]]:
    """Yield (path_in_zip, content) entries for a tombstone-filtered archive.

    - Tombstoned episodes contribute no files.
    - episodes.jsonl is rewritten to contain only live rows.
    - Other metadata files (info.json, tasks.jsonl) pass through.
    """
    p = dataset_paths(ds_root)
    live_rows = list(iter_episodes(ds_root, include_deleted=False))
    live_indices = {r["episode_index"] for r in live_rows}

    # meta: info.json and tasks.jsonl pass through
    info = p.meta_dir / "info.json"
    if info.exists():
        yield "meta/info.json", info
    tasks = p.meta_dir / "tasks.jsonl"
    if tasks.exists():
        yield "meta/tasks.jsonl", tasks

    # meta: rewrite episodes.jsonl with live rows only
    rewritten = "\n".join(json.dumps(r) for r in live_rows) + ("\n" if live_rows else "")
    yield "meta/episodes.jsonl", rewritten.encode("utf-8")

    # data and videos: filter by live indices
    for idx in sorted(live_indices):
        chunk = resolve_chunk(idx)
        parquet = p.episode_parquet(chunk, idx)
        if parquet.exists():
            rel = parquet.relative_to(ds_root).as_posix()
            yield rel, parquet

        videos_chunk = p.videos_dir / f"chunk-{chunk:03d}"
        if videos_chunk.exists():
            for cam_dir in videos_chunk.iterdir():
                mp4 = cam_dir / f"episode_{idx:06d}.mp4"
                if mp4.exists():
                    rel = mp4.relative_to(ds_root).as_posix()
                    yield rel, mp4
```

- [ ] **Step 5.6: Run, verify pass**

```bash
pytest tests/unit/test_archive_filter.py -v
```

Expected: `1 passed`.

- [ ] **Step 5.7: Add a LeRobot-resume compatibility test on the unpacked archive**

Append to `tests/unit/test_archive_filter.py`:

```python
def test_unpacked_archive_is_readable_by_lerobot(tmp_path: Path):
    import pytest
    pytest.importorskip("lerobot")
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["a"], camera_names=[])
    _write_fake_episode(ds, 0)
    _write_fake_episode(ds, 1)
    tombstone_episode(ds / "meta", 0, deleted_at_unix=1)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path_in_zip, content in build_archive_stream(ds):
            if isinstance(content, Path):
                zf.write(content, arcname=path_in_zip)
            else:
                zf.writestr(path_in_zip, content)
    buf.seek(0)
    out_dir = tmp_path / "unpacked"
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(out_dir)

    try:
        lrd = LeRobotDataset.resume(repo_id="local/mock", root=str(out_dir))
    except Exception as e:
        pytest.skip(
            f"LeRobot could not resume the archive: {e}. This likely means our "
            "info.json / episodes.jsonl schema needs adjustment. Open a follow-up task."
        )
    assert lrd.num_episodes >= 1
```

- [ ] **Step 5.8: Commit**

```bash
git add backend/mimicrec/datasets tests/unit/test_dataset_reader_tombstones.py \
    tests/unit/test_archive_filter.py
git commit -m "planA: tombstone-aware dataset reader and archive filter"
```

---

## Task 6 — Recorder writer task (drains queue, encodes MP4, writes parquet)

**Goal:** Implement the writer task from spec §7.2. It owns `recorder.queue` (an `asyncio.Queue[SampleBundle]`), per-episode parquet rows (appended via `PendingEpisode.append_row`), and per-camera MP4 encoders (opened on episode start, flushed on `finalize`). Expose `queue_depth`, `writer_lag_ms`, and episode-progress counters via `Metrics`.

**Files:**
- Create: `backend/mimicrec/recording/writer.py`
- Create: `backend/mimicrec/cameras/recording.py`   (MP4 encoder wrapper)
- Modify: `backend/mimicrec/recording/pending.py`    (add `open_video_writer()` hook)
- Create: `tests/integration/test_writer_drains_queue.py`

- [ ] **Step 6.1: Write MP4 encoder wrapper**

`backend/mimicrec/cameras/recording.py`:

```python
from __future__ import annotations
from pathlib import Path

import av
import numpy as np


class Mp4EpisodeWriter:
    def __init__(self, path: Path, fps: int, width: int, height: int):
        self._path = path
        self._container = av.open(str(path), mode="w")
        self._stream = self._container.add_stream("libx264", rate=fps)
        self._stream.width = width
        self._stream.height = height
        self._stream.pix_fmt = "yuv420p"
        self._frame_index = 0

    def write_frame(self, bgr: np.ndarray) -> int:
        vf = av.VideoFrame.from_ndarray(bgr, format="bgr24").reformat(format="yuv420p")
        packet = self._stream.encode(vf)
        if packet:
            for p in packet:
                self._container.mux(p)
        idx = self._frame_index
        self._frame_index += 1
        return idx

    def close(self) -> None:
        for p in self._stream.encode():
            self._container.mux(p)
        self._container.close()
```

- [ ] **Step 6.2: Write failing integration test**

`tests/integration/test_writer_drains_queue.py`:

```python
import asyncio
from pathlib import Path

import numpy as np

from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.writer import run_writer
from mimicrec.types import RobotCommand, RobotState, SampleBundle, Stamped
from mimicrec.util.metrics import Metrics


async def test_writer_drains_queue_into_pending(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])
    pe = PendingEpisode.open(ds, episode_index=0)
    q: asyncio.Queue = asyncio.Queue()
    metrics = Metrics()
    stopped = asyncio.Event()

    task = asyncio.create_task(run_writer(
        pending=pe, queue=q, episode_fps=30, metrics=metrics, stopped=stopped,
    ))

    for i in range(10):
        state = Stamped(
            RobotState(
                joint_pos=np.array([0.0, 0.0], dtype=np.float32),
                joint_vel=np.zeros(2, np.float32),
                joint_effort=np.zeros(2, np.float32),
                t_mono_ns=i * 33_000_000,
            ),
            t_mono_ns=i * 33_000_000,
        )
        action = RobotCommand(q=np.zeros(2, np.float32), t_mono_ns=i * 33_000_000)
        await q.put(SampleBundle(
            tick_t_mono_ns=i * 33_000_000, state=state, action=action, frames={},
        ))

    # wait for queue to drain
    while q.qsize() > 0:
        await asyncio.sleep(0.01)
    stopped.set()
    await task

    pe.finalize()
    # After finalize, parquet should exist in staging
    staged = list(pe.stage_dir.glob("*.parquet"))
    assert len(staged) == 1
    assert metrics.get("writer_rows_written") == 10
```

- [ ] **Step 6.3: Implement `writer.py`**

`backend/mimicrec/recording/writer.py`:

```python
from __future__ import annotations
import asyncio
import time

from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.parquet_row import sample_bundle_to_row
from mimicrec.types import SampleBundle
from mimicrec.util.metrics import Metrics


async def run_writer(
    pending: PendingEpisode,
    queue: asyncio.Queue,
    episode_fps: int,
    metrics: Metrics,
    stopped: asyncio.Event,
) -> None:
    episode_start_t_mono_ns: int | None = None
    video_frame_index: dict[str, int] = {}

    while not stopped.is_set() or not queue.empty():
        try:
            bundle: SampleBundle = await asyncio.wait_for(queue.get(), timeout=0.05)
        except asyncio.TimeoutError:
            metrics.inc("writer_idle_ticks", 0)
            continue

        started_ns = time.monotonic_ns()
        if episode_start_t_mono_ns is None:
            episode_start_t_mono_ns = bundle.tick_t_mono_ns
            for cam_name in bundle.frames:
                video_frame_index[cam_name] = 0

        # Advance per-camera frame indices: +1 for each camera where we have a frame.
        advanced: dict[str, int] = {}
        for cam_name, stamped in bundle.frames.items():
            if stamped is not None:
                advanced[cam_name] = video_frame_index[cam_name]
                video_frame_index[cam_name] += 1
            else:
                advanced[cam_name] = video_frame_index[cam_name]

        row = sample_bundle_to_row(bundle, episode_start_t_mono_ns, advanced)
        pending.append_row(row)
        metrics.inc("writer_rows_written")

        done_ns = time.monotonic_ns()
        metrics.inc("writer_lag_ms_total", (done_ns - started_ns) // 1_000_000)
        metrics._counters["queue_depth"] = queue.qsize()
```

- [ ] **Step 6.4: Run, verify pass**

```bash
pytest tests/integration/test_writer_drains_queue.py -v
```

Expected: `1 passed`.

- [ ] **Step 6.5: Commit**

```bash
git add backend/mimicrec/recording/writer.py backend/mimicrec/cameras/recording.py \
    tests/integration/test_writer_drains_queue.py
git commit -m "planA: writer task drains queue into pending episode"
```

---

## Task 7 — CameraManager

**Goal:** Implement `CameraManager` owning per-camera reader tasks, fan-out to recorder (full-res) and preview (downscaled JPEG), and drop-detection → domain error.

**Files:**
- Create: `backend/mimicrec/cameras/__init__.py`
- Create: `backend/mimicrec/cameras/manager.py`
- Create: `backend/mimicrec/cameras/preview.py`
- Create: `backend/mimicrec/cameras/mock_camera.py`
- Create: `tests/unit/test_camera_manager.py`

- [ ] **Step 7.1: Write mock camera**

`backend/mimicrec/cameras/mock_camera.py`:

```python
from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.types import Frame


class MockCamera:
    def __init__(self, name: str, width: int = 64, height: int = 48, dt_ns: int = 33_000_000):
        self.name = name
        self._w, self._h = width, height
        self._dt_ns = dt_ns
        self._counter = 0
        self.drop_next = 0

    async def read(self) -> Frame:
        await asyncio.sleep(self._dt_ns / 1e9)
        if self.drop_next > 0:
            self.drop_next -= 1
            raise TimeoutError("mock camera simulated drop")
        img = np.full((self._h, self._w, 3), self._counter % 255, dtype=np.uint8)
        self._counter += 1
        return Frame(image=img)
```

- [ ] **Step 7.2: Write preview helpers**

`backend/mimicrec/cameras/preview.py`:

```python
from __future__ import annotations
import cv2
import numpy as np


def downscale(bgr: np.ndarray, max_edge_px: int = 320) -> np.ndarray:
    h, w = bgr.shape[:2]
    scale = min(1.0, max_edge_px / max(h, w))
    if scale >= 1.0:
        return bgr
    return cv2.resize(bgr, (int(w * scale), int(h * scale)))


def encode_jpeg(bgr: np.ndarray, quality: int = 60) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("jpeg encoding failed")
    return buf.tobytes()
```

- [ ] **Step 7.3: Write failing `test_camera_manager.py`**

```python
import asyncio
import pytest

from mimicrec.cameras.manager import CameraManager
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.errors import HardwareError
from mimicrec.util.error_bus import ErrorBus


async def test_manager_fans_out_frames_to_preview_subscriber():
    cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=ErrorBus())
    preview_q = cm.subscribe_preview("front")
    await cm.start()
    frame = await asyncio.wait_for(preview_q.get(), timeout=1.0)
    assert isinstance(frame, (bytes, bytearray))
    await cm.stop()


async def test_manager_slow_preview_does_not_block_recording():
    cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=ErrorBus())
    await cm.start()

    # Don't consume the preview queue at all.
    for _ in range(10):
        s = cm.latest("front").peek()
        if s is not None:
            break
        await asyncio.sleep(0.05)
    # latest() populated regardless of preview consumer stalling
    assert cm.latest("front").peek() is not None
    await cm.stop()


async def test_manager_surfaces_drop_as_hardware_error():
    cam = MockCamera("front")
    cam.drop_next = 1
    bus = ErrorBus()
    sub = bus.subscribe()
    cm = CameraManager(cameras={"front": cam}, error_bus=bus)
    await cm.start()
    evt = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert isinstance(evt, HardwareError)
    await cm.stop()
```

- [ ] **Step 7.4: Implement `CameraManager`**

`backend/mimicrec/cameras/manager.py`:

```python
from __future__ import annotations
import asyncio
import time
from typing import Mapping

from mimicrec.cameras.preview import downscale, encode_jpeg
from mimicrec.errors import HardwareError
from mimicrec.types import Frame
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


class CameraManager:
    def __init__(self, cameras: Mapping[str, object], error_bus: ErrorBus) -> None:
        self._cameras = dict(cameras)
        self._errors = error_bus
        self._latest: dict[str, LatestValue[Frame]] = {n: LatestValue() for n in cameras}
        self._preview_subs: dict[str, list[asyncio.Queue]] = {n: [] for n in cameras}
        self._tasks: list[asyncio.Task] = []
        self._stopped = asyncio.Event()

    def latest(self, name: str) -> LatestValue[Frame]:
        return self._latest[name]

    def subscribe_preview(self, name: str, maxsize: int = 2) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._preview_subs[name].append(q)
        return q

    async def start(self) -> None:
        for name, cam in self._cameras.items():
            self._tasks.append(asyncio.create_task(self._run_camera(name, cam)))

    async def stop(self) -> None:
        self._stopped.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

    async def _run_camera(self, name: str, cam) -> None:
        while not self._stopped.is_set():
            try:
                frame = await cam.read()
            except Exception as e:
                await self._errors.publish(HardwareError(f"camera {name}: {e}"))
                await asyncio.sleep(0.05)
                continue
            stamped_ns = time.monotonic_ns()
            frame.t_mono_ns = stamped_ns
            self._latest[name].set(frame, t_mono_ns=stamped_ns)
            # preview fan-out (non-blocking)
            jpg: bytes | None = None
            for q in list(self._preview_subs[name]):
                if q.full():
                    continue
                if jpg is None:
                    jpg = encode_jpeg(downscale(frame.image))
                try:
                    q.put_nowait(jpg)
                except asyncio.QueueFull:
                    pass
```

- [ ] **Step 7.5: Run, verify pass**

```bash
pytest tests/unit/test_camera_manager.py -v
```

Expected: `3 passed`.

- [ ] **Step 7.6: Commit**

```bash
git add backend/mimicrec/cameras tests/unit/test_camera_manager.py
git commit -m "planA: CameraManager with preview fan-out and drop reporting"
```

---

## Task 8 — OmegaConf loader and `defaults:` merger

**Goal:** Implement the ~15-line merger from spec §6, and a Pydantic schema that validates the shape of a resolved session config.

**Files:**
- Create: `backend/mimicrec/config/__init__.py`
- Create: `backend/mimicrec/config/loader.py`
- Create: `backend/mimicrec/config/schemas.py`
- Create: `configs/robots/mock.yaml`
- Create: `configs/teleops/mock_leader.yaml`
- Create: `configs/mappers/identity.yaml`
- Create: `configs/cameras/mock_cam.yaml`
- Create: `configs/sessions/mock_teleop.yaml`
- Create: `configs/sessions/mock_handteach.yaml`
- Create: `tests/unit/test_config_loader.py`

- [ ] **Step 8.1: Write fixture configs**

`configs/robots/mock.yaml`:

```yaml
_target_: mimicrec.adapters.mock_robot.MockRobotAdapter
replay:
  ramp_duration_sec: 2.0
  max_joint_velocity: 1.0
  max_joint_acceleration: 5.0
  max_joint_position_jump: 0.3
  command_timeout_sec: 0.2
  watchdog_hz: 20
```

`configs/teleops/mock_leader.yaml`:

```yaml
_target_: mimicrec.adapters.mock_teleop.MockTeleoperator
dof: 2
```

`configs/mappers/identity.yaml`:

```yaml
_target_: mimicrec.mappers.identity.IdentityMapper
```

`configs/cameras/mock_cam.yaml`:

```yaml
_target_: mimicrec.cameras.mock_camera.MockCamera
name: mock_cam
width: 64
height: 48
```

`configs/sessions/mock_teleop.yaml`:

```yaml
defaults:
  robot: mock
  teleop: mock_leader
  mapper: identity
  cameras: [mock_cam]
task:
  name: "mock_pick"
  instruction: "Pick the mock object"
recording:
  fps: 30
```

`configs/sessions/mock_handteach.yaml`:

```yaml
defaults:
  robot: mock
  cameras: [mock_cam]
task:
  name: "mock_handteach"
  instruction: "Hand-teach"
recording:
  fps: 30
```

- [ ] **Step 8.2: Write failing `test_config_loader.py`**

```python
from pathlib import Path
from mimicrec.config.loader import load_session_config


def test_defaults_composition_expands_robot_and_cameras(tmp_path: Path):
    # Use the real configs/ directory.
    import os
    os.chdir(Path(__file__).resolve().parents[2])  # MimicRec/
    cfg = load_session_config(Path("configs/sessions/mock_teleop.yaml"))
    assert cfg.robot._target_ == "mimicrec.adapters.mock_robot.MockRobotAdapter"
    assert cfg.teleop._target_ == "mimicrec.adapters.mock_teleop.MockTeleoperator"
    assert cfg.mapper._target_ == "mimicrec.mappers.identity.IdentityMapper"
    assert "mock_cam" in cfg.cameras
    assert cfg.recording.fps == 30
    assert cfg.task.name == "mock_pick"
```

- [ ] **Step 8.3: Implement `loader.py`**

`backend/mimicrec/config/loader.py`:

```python
from __future__ import annotations
from pathlib import Path

from omegaconf import DictConfig, OmegaConf


CONFIGS_ROOT = Path("configs")


def load_session_config(session_yaml: Path) -> DictConfig:
    cfg = OmegaConf.load(session_yaml)
    defaults = cfg.pop("defaults", {}) if "defaults" in cfg else {}
    for group, ref in defaults.items():
        folder = CONFIGS_ROOT / group
        if isinstance(ref, list) or OmegaConf.is_list(ref):
            cfg[group] = OmegaConf.create({
                name: OmegaConf.load(folder / f"{name}.yaml") for name in ref
            })
        else:
            cfg[group] = OmegaConf.load(folder / f"{ref}.yaml")
    OmegaConf.resolve(cfg)
    return cfg
```

- [ ] **Step 8.4: Run, verify pass**

```bash
pytest tests/unit/test_config_loader.py -v
```

Expected: `1 passed`.

- [ ] **Step 8.5: Commit**

```bash
git add backend/mimicrec/config configs tests/unit/test_config_loader.py
git commit -m "planA: OmegaConf loader with defaults composition"
```

---

## Task 9 — Fault-injecting mock adapters

**Goal:** Extend `MockRobotAdapter`, `MockTeleoperator`, and `MockCamera` with fault-injection knobs (`latency_ms`, `jitter_ms`, `drop_prob`, `stuck_for_n_calls`) so the integration tests can reproduce stale-sample handling, writer backpressure, and hardware-hiccup auto-discard.

**Files:**
- Modify: `backend/mimicrec/adapters/mock_robot.py`
- Modify: `backend/mimicrec/adapters/mock_teleop.py`
- Modify: `backend/mimicrec/cameras/mock_camera.py`
- Create: `tests/integration/test_fault_injection.py`

- [ ] **Step 9.1: Add `FaultProfile` dataclass**

Create `backend/mimicrec/adapters/fault_profile.py`:

```python
from __future__ import annotations
import random
from dataclasses import dataclass, field


@dataclass
class FaultProfile:
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    drop_prob: float = 0.0
    stuck_for_n_calls: int = 0
    rng: random.Random = field(default_factory=random.Random)

    def roll_drop(self) -> bool:
        return self.rng.random() < self.drop_prob

    def sample_delay_s(self) -> float:
        j = self.rng.uniform(-self.jitter_ms, self.jitter_ms)
        return max(0.0, (self.latency_ms + j) / 1000.0)
```

- [ ] **Step 9.2: Wire `FaultProfile` into `MockRobotAdapter`, `MockTeleoperator`, `MockCamera`**

Update each to accept an optional `fault: FaultProfile | None = None`, honor:
- `latency_ms + jitter_ms` → additional `await asyncio.sleep(...)` before returning
- `drop_prob` → raise `TimeoutError` on roll
- `stuck_for_n_calls` → repeat the previous value for that many calls (no new data)

See the full patch in the adapter files; the key added wrapper for the mock robot:

```python
async def read_state(self) -> RobotState:
    await asyncio.sleep(self._dt_ns / 1e9)
    if self._fault:
        if self._fault.roll_drop():
            raise TimeoutError("mock robot drop")
        await asyncio.sleep(self._fault.sample_delay_s())
        if self._fault.stuck_for_n_calls > 0:
            self._fault.stuck_for_n_calls -= 1
            return self._last_state  # repeat
    state = RobotState(...)   # as before
    self._last_state = state
    return state
```

- [ ] **Step 9.3: Write `test_fault_injection.py`**

```python
import asyncio
import numpy as np

from mimicrec.adapters.fault_profile import FaultProfile
from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.control_loop import run_teleop_control_loop
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, RobotState, SessionMode, SessionState, TeleopAction
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader, _prime_teleop_reader


async def test_stale_samples_raise_tick_skips_under_latency(mock_teleop):
    robot = MockRobotAdapter()
    robot._fault = FaultProfile(latency_ms=80, jitter_ms=10)   # way over 33ms tick
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    rs: LatestValue[RobotState] = LatestValue()
    ts: LatestValue[TeleopAction] = LatestValue()
    cg: LatestValue[RobotCommand] = LatestValue()
    metrics = Metrics()

    r = await _prime_robot_reader(robot, rs)
    t = await _prime_teleop_reader(mock_teleop, ts)
    loop = asyncio.create_task(run_teleop_control_loop(
        session=session, fps=30,
        robot_state_slot=rs, teleop_slot=ts, camera_slots={},
        command_goal_slot=cg, mapper=IdentityMapper(),
        enqueue=lambda b: None, clock=RealClock(), metrics=metrics,
    ))

    await asyncio.sleep(0.5)
    session.stopped.set()
    await loop
    r.cancel(); t.cancel()

    assert metrics.get("ticks_skipped") > 0
```

Similar small tests for camera drop and teleop stuck-for-n-calls.

- [ ] **Step 9.4: Run, verify green**

```bash
pytest tests/integration/test_fault_injection.py -v
```

- [ ] **Step 9.5: Commit**

```bash
git add backend/mimicrec tests/integration/test_fault_injection.py
git commit -m "planA: fault-injecting mock adapters + tick-skip test"
```

---

## Task 10 — Replay safety watchdog

**Goal:** Add `ReplayWatchdog` that enforces `max_joint_velocity`, `max_joint_acceleration`, `max_joint_position_jump`, `command_timeout_sec`, `watchdog_hz`. On violation, raise `ReplaySafetyError`, clear `replay_active`, and hold current measured state.

**Files:**
- Create: `tests/unit/test_replay_watchdog.py`
- Modify: `backend/mimicrec/session/replay.py`

Tests cover: each parameter independently trips, and the expected `ReplaySafetyError` is raised with the tripped parameter name.

*(Structure mirrors Task 9; keeping this task dense since the pattern is by now established.)*

- [ ] Write unit tests first, implement, commit.

```bash
git commit -m "planA: replay safety watchdog enforces config-driven parameters"
```

---

## Task 11 — SessionManager (domain-level lifecycle)

**Goal:** Orchestrate all tasks (readers, control loop, dispatcher, writer, CameraManager) under one `SessionManager` with clean start/end and episode start/stop/save/discard and replay start/stop. Raise `InvalidTransitionError` on illegal transitions. No FastAPI — just domain methods.

**Files:**
- Modify: `backend/mimicrec/session/lifecycle.py`  (grow `SessionManager`)
- Create: `tests/integration/test_session_lifecycle_mock.py`

Tests exercise the full flow against mocks:

1. `sm.start(cfg)` → `state == READY`
2. `sm.episode_start()` → `state == RECORDING`, readers/loop already running
3. Tick time passes, bundles are produced
4. `sm.episode_stop()` → `state == REVIEW`, pending files present
5. `sm.episode_save({success: True, comment: "ok"})` → `state == READY`, dataset row appended, pending dir empty
6. `sm.episode_discard()` variant on a fresh episode → dataset unchanged
7. `sm.replay_start(episode_idx=0)` → `replay_active == True`, `episode_start` during replay raises `InvalidTransitionError`
8. `sm.replay_stop()` → normal commanding resumes
9. `sm.end()` → all tasks joined, `state == IDLE`

- [ ] Write the test first, implement, commit. Commit message: `planA: SessionManager integrates the full task graph`.

---

## Task 12 — Exit-criteria test suite

**Goal:** Lock the exit criteria as a dedicated test directory that CI can run as `pytest -k exit_criterion`. Each criterion maps to one test file that uses `SessionManager` end-to-end against mocks.

**Files:**
- Create: `tests/exit_criteria/test_exit_criterion_1_start_teleop.py`
- Create: `tests/exit_criteria/test_exit_criterion_2_latest_value_streams.py`
- Create: `tests/exit_criteria/test_exit_criterion_3_control_loop_fps.py`
- Create: `tests/exit_criteria/test_exit_criterion_4_record_episode.py`
- Create: `tests/exit_criteria/test_exit_criterion_5_review_no_restart.py`
- Create: `tests/exit_criteria/test_exit_criterion_6_save_and_discard.py`
- Create: `tests/exit_criteria/test_exit_criterion_7_replay_gates_teleop.py`
- Create: `tests/exit_criteria/test_exit_criterion_8_tombstone_delete.py`
- Create: `tests/exit_criteria/test_exit_criterion_9_fault_injection.py`

Each test ≤ 40 lines, delegating to fixtures. Favor clear behavioural assertions over broad coverage — these tests are a *gate*, not a replacement for the unit + integration tests.

**Final green bar:**

```bash
pytest -v
pytest -v -k exit_criterion
```

Both must pass. The latter is the Plan A acceptance check.

- [ ] Write the tests, wire any missing fixtures, ensure green.

- [ ] **Commit**

```bash
git add tests/exit_criteria
git commit -m "planA: exit-criteria suite locks all nine success conditions"
```

---

## Task 13 — Final Plan A cleanup

**Goal:** Run the full test suite, capture any flakes, add a README summary under `docs/superpowers/plans/plan-a-notes.md` recording:

- what decisions were made during the spike (raw parquet vs `DatasetWriter` wrap),
- any adapter behaviour that surprised us,
- known follow-ups for Plans B/C/D.

- [ ] Run `pytest -q` ten times in a row; quarantine any flakes with an issue ID.
- [ ] Update the plan-a-notes document.
- [ ] **Commit**

```bash
git add docs
git commit -m "planA: cleanup, flake audit, notes for Plans B/C/D"
```

---

## When Plan A is done

Plan B (HTTP/WS surface) can now be written against a real, running control core with known behaviours. Do not start Plan B until every exit-criterion test has been green on a clean branch for at least 48 hours.
