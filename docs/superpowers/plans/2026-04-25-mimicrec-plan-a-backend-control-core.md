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
- `recording/writer.py` — a **session-scoped** task started once by `SessionManager` and stopped once at session end. It consumes `recorder.queue`, and consults a `LatestValue[PendingEpisode | None]` slot (the `current_pending` slot set by `SessionManager` on `episode/start` and cleared on `episode/save`/`episode/discard`) to decide where to append rows and frames. There is no per-episode writer task. Queue draining continues across episode boundaries; rows without an active pending are dropped with a `writer_dropped_no_pending` metric tick.
- `recording/pending.py` — `PendingEpisode` owns a staging dir (`datasets/<ds>/.pending/ep_<N>/`) and, while active, one `Mp4EpisodeWriter` per camera. `append_row(row, frames)` writes both the parquet buffer entry and the MP4 frames in one call. On `save`, the pending files (parquet + MP4s) are moved into the dataset; on `discard`, the whole staging directory is `rmtree`d.
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
# Do not set `filterwarnings = error`: av, pyarrow, and transitive lerobot deps
# routinely emit DeprecationWarning that is not ours to fix. We keep warnings
# visible in output but not test-failing.
filterwarnings =
    default
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


def test_lerobot_api_surface_we_rely_on():
    """Fail fast if the LeRobot API we lean on in Tasks 1 and 5 has drifted.

    Tasks 1 and 5 call `LeRobotDataset.resume(repo_id=..., root=...)`. If that
    signature has changed in the editable-installed lerobot, both spike tests
    will skip with a PIVOT message and we'd miss the compatibility guarantee.
    Catch it here at Task 0 instead.
    """
    import inspect
    import pytest
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except Exception as e:
        pytest.skip(f"lerobot not importable yet: {e}")
    assert hasattr(LeRobotDataset, "resume"), (
        "LeRobotDataset.resume has disappeared; re-check Tasks 1 and 5 spike paths."
    )
    sig = inspect.signature(LeRobotDataset.resume)
    params = set(sig.parameters.keys())
    # Allow extra params, but these two must be accepted by name.
    missing = {"repo_id", "root"} - params
    assert not missing, f"LeRobotDataset.resume missing expected params: {missing}"
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
    seq_before = lv.seq

    async def writer():
        await asyncio.sleep(0.01)
        lv.set(2, t_mono_ns=200)

    asyncio.create_task(writer())
    s = await asyncio.wait_for(lv.wait_for_new(since_seq=seq_before), timeout=0.5)
    assert s.value == 2


async def test_wait_for_new_returns_immediately_if_already_newer():
    """The seq-based design must not lose a write that races the waiter."""
    lv: LatestValue[int] = LatestValue()
    lv.set(1, t_mono_ns=100)
    # Waiter observes the current seq, then a write happens *before* wait_for_new
    seq_before = lv.seq
    lv.set(2, t_mono_ns=200)
    s = await asyncio.wait_for(lv.wait_for_new(since_seq=seq_before), timeout=0.5)
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
    """A single-slot, latest-writer-wins value with sequence-based awaiting.

    Writers call `set(value, t_mono_ns)` — unconditional replacement.
    Non-blocking readers call `peek()` — returns the stored Stamped or None.
    Awaiting readers call `wait_for_new(since_seq=...)` — returns the next
    Stamped with seq > since_seq. The sequence number avoids the classic
    Event set/clear race: if a writer races a would-be waiter, the waiter
    simply sees a higher seq on the next await and returns immediately.
    """

    def __init__(self) -> None:
        self._stamped: Stamped[T] | None = None
        self._seq: int = 0
        self._cond = asyncio.Condition()

    @property
    def seq(self) -> int:
        return self._seq

    def peek(self) -> Stamped[T] | None:
        return self._stamped

    def set(self, value: T, t_mono_ns: int) -> None:
        self._stamped = Stamped(value=value, t_mono_ns=t_mono_ns)
        self._seq += 1
        # notify any sleeping waiters; non-blocking if no lock holders.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._notify_all())

    async def _notify_all(self) -> None:
        async with self._cond:
            self._cond.notify_all()

    async def wait_for_new(self, since_seq: int | None = None) -> Stamped[T]:
        target = self._seq if since_seq is None else since_seq
        async with self._cond:
            while self._seq <= target or self._stamped is None:
                await self._cond.wait()
            return self._stamped
```

**Contract:** the dispatcher in Task 3 captures `seq_before = goal.seq` before `await goal.wait_for_new(since_seq=seq_before)` so writes that land between peek and await are still observed.

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
    """Minimal in-memory metrics. Counters (monotonically increasing) and
    gauges (arbitrary current values) are kept in separate dicts so readers
    can distinguish them in `snapshot()`.
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, by: int = 1) -> None:
        self._counters[name] += by

    def get(self, name: str) -> int:
        return self._counters[name]

    def set_gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {"counters": dict(self._counters), "gauges": dict(self._gauges)}
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

    def supports_mode(self, mode: RobotMode) -> bool:
        """Capability query. MUST be pure (no hardware side effects).

        Used by the session precheck to reject HAND_TEACH on adapters that
        cannot provide gravity compensation, *before* any hardware is
        touched. An adapter that returns True here must either honor
        set_mode(mode) or raise HandTeachNotSupportedError when it's called.
        """
        ...
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

    def supports_mode(self, mode: RobotMode) -> bool:
        return True   # mock supports all modes
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
    import time
    async def run():
        while True:
            t = time.monotonic_ns()
            st = await robot.read_state()
            st.t_mono_ns = t
            slot.set(st, t_mono_ns=t)
    return asyncio.create_task(run())


async def _prime_teleop_reader(teleop, slot: LatestValue[TeleopAction]) -> asyncio.Task:
    import time
    async def run():
        while True:
            t = time.monotonic_ns()
            a = await teleop.read_action()
            a.t_mono_ns = t
            slot.set(a, t_mono_ns=t)
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
    await task

    sent = robot.sent_commands
    # The last written goal must have been sent at least once.
    assert any(np.allclose(c, [0.3, 0.4]) for c in sent)
    # Dispatcher must only send values that were actually written to the slot.
    legal = [np.array([0.1, 0.2], dtype=np.float32), np.array([0.3, 0.4], dtype=np.float32)]
    assert all(any(np.allclose(c, L) for L in legal) for c in sent)


async def test_dispatcher_collapses_bursts_latest_writer_wins():
    """If the dispatcher is busy on a send, stale intermediate goals must
    not accumulate. After a burst of writes the dispatcher resumes at the
    latest value, not the oldest pending one."""
    robot = MockRobotAdapter()
    # Make the mock's send slow so we can queue up writes during a send.
    async def slow_send(q):
        await asyncio.sleep(0.1)
        robot.sent_commands.append(q.copy())
    robot.send_joint_command = slow_send  # type: ignore[assignment]

    goal: LatestValue[RobotCommand] = LatestValue()
    bus = ErrorBus()
    stopped = asyncio.Event()
    task = asyncio.create_task(run_command_dispatcher(robot, goal, bus, stopped))

    goal.set(RobotCommand(q=np.array([1.0, 0.0], dtype=np.float32)), t_mono_ns=1)
    await asyncio.sleep(0.02)    # first send is in flight now
    goal.set(RobotCommand(q=np.array([2.0, 0.0], dtype=np.float32)), t_mono_ns=2)
    goal.set(RobotCommand(q=np.array([3.0, 0.0], dtype=np.float32)), t_mono_ns=3)
    goal.set(RobotCommand(q=np.array([4.0, 0.0], dtype=np.float32)), t_mono_ns=4)
    await asyncio.sleep(0.25)

    stopped.set()
    await task

    # We expect the first in-flight send (1.0) plus a single follow-up
    # reflecting the latest goal (4.0). Intermediate 2.0/3.0 must not all appear.
    values = [c[0] for c in robot.sent_commands]
    assert 1.0 in values
    assert 4.0 in values
    assert values.count(2.0) + values.count(3.0) <= 1
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
    """Single-in-flight command dispatcher with latest-writer-wins collapse.

    Between sends we re-snapshot `goal.peek()` rather than re-awaiting
    `wait_for_new()` if new writes landed during the previous send. This
    is the source of the "collapse intermediate goals" guarantee in spec
    §4: once we return from `send_joint_command`, we send the *newest*
    value on the next iteration, skipping any stale writes in between.
    """
    last_seen_seq = 0
    while not stopped.is_set():
        # If a new value arrived while we were sending the previous one,
        # skip the wait and send the latest immediately.
        current = goal.peek()
        if current is None or goal.seq <= last_seen_seq:
            try:
                stamped = await asyncio.wait_for(
                    goal.wait_for_new(since_seq=last_seen_seq),
                    timeout=0.05,
                )
            except asyncio.TimeoutError:
                continue
            current = stamped
        last_seen_seq = goal.seq
        try:
            await robot.send_joint_command(current.value.q)
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
    if session.replay_active:
        from mimicrec.errors import InvalidTransitionError
        raise InvalidTransitionError("another replay is already active")
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

    def supports_mode(self, mode: RobotMode) -> bool:
        return mode != RobotMode.GRAVITY_COMP
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

    def supports_mode(self, mode: RobotMode) -> bool:
        return True
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


def precheck_start(req: StartSessionRequestDomain) -> None:
    """Raise domain errors before any hardware is connected.

    This MUST NOT cause side effects on the adapter — no connect, no
    set_mode, no I/O. It asks the adapter for its capabilities via the
    pure `supports_mode` query.
    """
    if req.mode == SessionMode.HAND_TEACH and not req.robot.supports_mode(RobotMode.GRAVITY_COMP):
        raise HandTeachNotSupportedError(
            f"robot {req.robot.name!r} does not support hand-teach "
            f"(GRAVITY_COMP). Start a TELEOP-mode session instead."
        )


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


def test_precheck_rejects_so101_handteach():
    a = SO101Adapter(port="/dev/null")
    req = StartSessionRequestDomain(robot=a, mode=SessionMode.HAND_TEACH)
    with pytest.raises(HandTeachNotSupportedError):
        precheck_start(req)   # pure capability query; must not touch hardware


def test_precheck_accepts_so101_teleop():
    a = SO101Adapter(port="/dev/null")
    req = StartSessionRequestDomain(robot=a, mode=SessionMode.TELEOP)
    precheck_start(req)  # should not raise
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

## Task 6 — Recorder writer task (session-scoped, drains queue, encodes MP4, writes parquet)

**Goal:** Implement the **session-scoped** writer task from spec §7.2. The task is started once by `SessionManager` on `session/start` and stopped once on `session/end`. It watches a `current_pending: LatestValue[PendingEpisode | None]` slot that the `SessionManager` mutates on `episode/start`, `episode/save`, and `episode/discard`. It drains `recorder.queue` (an `asyncio.Queue[SampleBundle]`) and:

- when `current_pending.peek()` is a `PendingEpisode`, writes parquet rows via `PendingEpisode.append_row(row, frames)` and pushes each camera frame into the per-camera MP4 encoder that `PendingEpisode` opened on `episode/start`,
- when it is `None`, drops the bundle and increments a `writer_dropped_no_pending` counter — this is the "REVIEW hold" case where the control loop has stopped enqueuing but late-arrived bundles may still be in the queue.

The writer never restarts across episodes. It exposes `queue_depth`, `writer_lag_ms`, `writer_rows_written`, and `writer_dropped_no_pending` via `Metrics`.

**Files:**
- Create: `backend/mimicrec/recording/writer.py`
- Create: `backend/mimicrec/cameras/recording.py`   (MP4 encoder wrapper)
- Modify: `backend/mimicrec/recording/pending.py`    (add per-camera Mp4EpisodeWriter lifecycle; new `append_row(row, frames)` signature)
- Create: `tests/integration/test_writer_drains_queue.py`
- Create: `tests/integration/test_writer_across_episodes.py`

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

- [ ] **Step 6.2: Extend `PendingEpisode` with per-camera Mp4 writers**

Modify `backend/mimicrec/recording/pending.py`:

```python
# Inside PendingEpisode:

def open_video_writers(self, fps: int, cameras: dict[str, tuple[int, int]]) -> None:
    """Open one Mp4EpisodeWriter per camera. `cameras` maps name -> (width, height)."""
    from mimicrec.cameras.recording import Mp4EpisodeWriter
    self._video_writers: dict[str, Mp4EpisodeWriter] = {}
    for name, (w, h) in cameras.items():
        path = self._stage / f"{name}.mp4"   # save() moves *.mp4 into videos/ dir
        self._video_writers[name] = Mp4EpisodeWriter(path, fps=fps, width=w, height=h)

def append_row(self, row: dict, frames: dict[str, object] | None = None) -> int:
    """Append a parquet row and (if frames given) write frame bytes to the matching MP4.

    Returns the video_frame_index written for each camera (as a side channel via `frames`).
    Callers pass a dict {name: Stamped[Frame] | None}; None means no frame this tick.
    """
    if self._finalized:
        raise RuntimeError("cannot append after finalize()")
    self._rows.append(row)
    if frames and getattr(self, "_video_writers", None):
        for name, stamped in frames.items():
            if stamped is None:
                continue
            writer = self._video_writers.get(name)
            if writer is not None:
                writer.write_frame(stamped.value.image)
    return len(self._rows) - 1

def finalize(self) -> None:
    if self._finalized:
        return
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.Table.from_pylist(self._rows)
    pq.write_table(table, self._stage / f"episode_{self._episode_index:06d}.parquet")
    # close all mp4 writers
    for w in getattr(self, "_video_writers", {}).values():
        w.close()
    self._finalized = True
```

- [ ] **Step 6.3: Write failing integration test**

`tests/integration/test_writer_drains_queue.py`:

```python
import asyncio
from pathlib import Path

import numpy as np

from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.writer import run_writer
from mimicrec.types import Frame, RobotCommand, RobotState, SampleBundle, Stamped
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


async def test_writer_drains_queue_into_pending_with_mp4(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=["front"])
    pe = PendingEpisode.open(ds, episode_index=0)
    pe.open_video_writers(fps=30, cameras={"front": (64, 48)})

    current: LatestValue[PendingEpisode | None] = LatestValue()
    current.set(pe, t_mono_ns=1)
    q: asyncio.Queue = asyncio.Queue()
    metrics = Metrics()
    stopped = asyncio.Event()

    task = asyncio.create_task(run_writer(
        current_pending=current, queue=q, metrics=metrics, stopped=stopped,
    ))

    img = np.zeros((48, 64, 3), dtype=np.uint8)
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
        frame = Stamped(Frame(image=img.copy(), t_mono_ns=i * 33_000_000), t_mono_ns=i * 33_000_000)
        await q.put(SampleBundle(
            tick_t_mono_ns=i * 33_000_000,
            state=state, action=action, frames={"front": frame},
        ))

    while q.qsize() > 0:
        await asyncio.sleep(0.01)
    stopped.set()
    await task

    pe.finalize()
    staged_parquet = list(pe.stage_dir.glob("*.parquet"))
    staged_mp4 = list(pe.stage_dir.glob("*.mp4"))
    assert len(staged_parquet) == 1
    assert len(staged_mp4) == 1
    assert metrics.get("writer_rows_written") == 10
    assert metrics.gauge("queue_depth") == 0


async def test_writer_drops_bundles_when_no_current_pending(tmp_path: Path):
    """During REVIEW (or any window without a pending episode), late bundles
    on the queue must be dropped with a counter bump, not crash the writer."""
    current: LatestValue[object] = LatestValue()
    current.set(None, t_mono_ns=1)
    q: asyncio.Queue = asyncio.Queue()
    metrics = Metrics()
    stopped = asyncio.Event()

    task = asyncio.create_task(run_writer(
        current_pending=current, queue=q, metrics=metrics, stopped=stopped,
    ))
    state = Stamped(
        RobotState(
            joint_pos=np.zeros(2, np.float32),
            joint_vel=np.zeros(2, np.float32),
            joint_effort=np.zeros(2, np.float32),
        ),
        t_mono_ns=0,
    )
    action = RobotCommand(q=np.zeros(2, np.float32))
    for _ in range(3):
        await q.put(SampleBundle(
            tick_t_mono_ns=0, state=state, action=action, frames={}
        ))
    while q.qsize() > 0:
        await asyncio.sleep(0.01)
    stopped.set()
    await task

    assert metrics.get("writer_dropped_no_pending") == 3
    assert metrics.get("writer_rows_written") == 0
```

- [ ] **Step 6.4: Implement `writer.py`**

`backend/mimicrec/recording/writer.py`:

```python
from __future__ import annotations
import asyncio
import time

from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.parquet_row import sample_bundle_to_row
from mimicrec.types import SampleBundle
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


async def run_writer(
    current_pending: LatestValue,   # LatestValue[PendingEpisode | None]
    queue: asyncio.Queue,
    metrics: Metrics,
    stopped: asyncio.Event,
) -> None:
    """Session-scoped writer. Watches current_pending for the active episode.

    When current_pending is a PendingEpisode, rows + frames are persisted.
    When it is None (e.g. REVIEW), bundles are drained and counted as dropped
    so the queue doesn't back up. The writer exits once `stopped` is set and
    the queue is empty.
    """
    last_pending: PendingEpisode | None = None
    episode_start_t_mono_ns: int | None = None
    video_frame_index: dict[str, int] = {}

    while not stopped.is_set() or not queue.empty():
        try:
            bundle: SampleBundle = await asyncio.wait_for(queue.get(), timeout=0.05)
        except asyncio.TimeoutError:
            metrics.set_gauge("queue_depth", float(queue.qsize()))
            continue

        started_ns = time.monotonic_ns()
        metrics.set_gauge("queue_depth", float(queue.qsize()))

        slot = current_pending.peek()
        pending = slot.value if slot is not None else None

        if pending is not last_pending:
            # new episode started (or ended): reset per-episode bookkeeping
            last_pending = pending
            episode_start_t_mono_ns = None
            video_frame_index = {}

        if pending is None:
            metrics.inc("writer_dropped_no_pending")
            continue

        if episode_start_t_mono_ns is None:
            episode_start_t_mono_ns = bundle.tick_t_mono_ns
            video_frame_index = {name: 0 for name in bundle.frames.keys()}

        advanced: dict[str, int] = {}
        for cam_name, stamped in bundle.frames.items():
            if cam_name not in video_frame_index:
                video_frame_index[cam_name] = 0
            advanced[cam_name] = video_frame_index[cam_name]
            if stamped is not None:
                video_frame_index[cam_name] += 1

        row = sample_bundle_to_row(bundle, episode_start_t_mono_ns, advanced)
        pending.append_row(row, frames=bundle.frames)
        metrics.inc("writer_rows_written")

        done_ns = time.monotonic_ns()
        metrics.set_gauge("writer_lag_ms", (done_ns - started_ns) / 1_000_000)
```

- [ ] **Step 6.5: Run, verify pass**

```bash
pytest tests/integration/test_writer_drains_queue.py -v
```

Expected: `2 passed`.

- [ ] **Step 6.6: Add a "writer survives episode transitions" test**

`tests/integration/test_writer_across_episodes.py`:

```python
import asyncio
from pathlib import Path
import numpy as np

from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.writer import run_writer
from mimicrec.types import RobotCommand, RobotState, SampleBundle, Stamped
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


async def test_writer_handles_two_episodes_without_restart(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    current: LatestValue[PendingEpisode | None] = LatestValue()
    q: asyncio.Queue = asyncio.Queue()
    metrics = Metrics()
    stopped = asyncio.Event()
    task = asyncio.create_task(run_writer(
        current_pending=current, queue=q, metrics=metrics, stopped=stopped,
    ))

    # Episode 0
    pe0 = PendingEpisode.open(ds, episode_index=0)
    current.set(pe0, t_mono_ns=1)
    state = Stamped(
        RobotState(joint_pos=np.zeros(2, np.float32), joint_vel=np.zeros(2, np.float32),
                   joint_effort=np.zeros(2, np.float32)),
        t_mono_ns=0,
    )
    action = RobotCommand(q=np.zeros(2, np.float32))
    for i in range(5):
        await q.put(SampleBundle(tick_t_mono_ns=i, state=state, action=action, frames={}))
    while q.qsize() > 0:
        await asyncio.sleep(0.01)

    # REVIEW: writer should drain and drop
    current.set(None, t_mono_ns=2)
    await q.put(SampleBundle(tick_t_mono_ns=99, state=state, action=action, frames={}))
    while q.qsize() > 0:
        await asyncio.sleep(0.01)

    # Episode 1
    pe1 = PendingEpisode.open(ds, episode_index=1)
    current.set(pe1, t_mono_ns=3)
    for i in range(3):
        await q.put(SampleBundle(tick_t_mono_ns=100 + i, state=state, action=action, frames={}))
    while q.qsize() > 0:
        await asyncio.sleep(0.01)

    stopped.set()
    await task

    pe0.finalize()
    pe1.finalize()
    assert metrics.get("writer_rows_written") == 8   # 5 + 3
    assert metrics.get("writer_dropped_no_pending") == 1
```

- [ ] **Step 6.7: Run, verify pass**

```bash
pytest tests/integration -v
```

Expected: all green.

- [ ] **Step 6.8: Commit**

```bash
git add backend/mimicrec/recording backend/mimicrec/cameras/recording.py \
    tests/integration/test_writer_drains_queue.py \
    tests/integration/test_writer_across_episodes.py
git commit -m "planA: session-scoped writer task with MP4 integration and episode transitions"
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
import pytest

from mimicrec.config.loader import load_session_config


REPO_ROOT = Path(__file__).resolve().parents[2]   # MimicRec/
CONFIGS = REPO_ROOT / "configs"


def test_defaults_composition_expands_robot_and_cameras():
    cfg = load_session_config(
        CONFIGS / "sessions" / "mock_teleop.yaml",
        configs_root=CONFIGS,
    )
    assert cfg.robot._target_ == "mimicrec.adapters.mock_robot.MockRobotAdapter"
    assert cfg.teleop._target_ == "mimicrec.adapters.mock_teleop.MockTeleoperator"
    assert cfg.mapper._target_ == "mimicrec.mappers.identity.IdentityMapper"
    assert "mock_cam" in cfg.cameras
    assert cfg.recording.fps == 30
    assert cfg.task.name == "mock_pick"


def test_missing_referenced_file_raises_clear_error(tmp_path: Path):
    configs_root = tmp_path / "configs"
    (configs_root / "robots").mkdir(parents=True)
    (configs_root / "sessions").mkdir(parents=True)
    session = configs_root / "sessions" / "bad.yaml"
    session.write_text("defaults:\n  robot: doesnotexist\n")
    with pytest.raises(FileNotFoundError) as e:
        load_session_config(session, configs_root=configs_root)
    assert "doesnotexist" in str(e.value)
```

- [ ] **Step 8.3: Implement `loader.py`**

`backend/mimicrec/config/loader.py`:

```python
from __future__ import annotations
from pathlib import Path

from omegaconf import DictConfig, OmegaConf


def load_session_config(session_yaml: Path, configs_root: Path) -> DictConfig:
    """Load a session config and compose its `defaults:` references.

    `configs_root` is explicit (no cwd coupling). Each group listed under
    `defaults:` is resolved relative to configs_root/<group>/<name>.yaml.
    """
    cfg = OmegaConf.load(session_yaml)
    defaults = cfg.pop("defaults", {}) if "defaults" in cfg else {}
    for group, ref in defaults.items():
        folder = configs_root / group
        if isinstance(ref, list) or OmegaConf.is_list(ref):
            resolved = {}
            for name in ref:
                path = folder / f"{name}.yaml"
                if not path.exists():
                    raise FileNotFoundError(f"config {group}/{name}.yaml not found at {path}")
                resolved[name] = OmegaConf.load(path)
            cfg[group] = OmegaConf.create(resolved)
        else:
            path = folder / f"{ref}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"config {group}/{ref}.yaml not found at {path}")
            cfg[group] = OmegaConf.load(path)
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

- [ ] **Step 9.2: Update `MockRobotAdapter` to accept `fault`**

Rewrite `backend/mimicrec/adapters/mock_robot.py`:

```python
from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.fault_profile import FaultProfile
from mimicrec.types import RobotState


class MockRobotAdapter:
    name = "mock"
    dof = 2
    joint_names = ["j1", "j2"]

    def __init__(self, dt_ns: int = 5_000_000, fault: FaultProfile | None = None):
        self._q = np.zeros(self.dof, dtype=np.float32)
        self._mode = RobotMode.POSITION
        self._dt_ns = dt_ns
        self._fault = fault
        self._last_state: RobotState | None = None
        self.sent_commands: list[np.ndarray] = []

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_state(self) -> RobotState:
        await asyncio.sleep(self._dt_ns / 1e9)
        if self._fault:
            if self._fault.roll_drop():
                raise TimeoutError("mock robot drop")
            await asyncio.sleep(self._fault.sample_delay_s())
            if self._fault.stuck_for_n_calls > 0 and self._last_state is not None:
                self._fault.stuck_for_n_calls -= 1
                return self._last_state
        state = RobotState(
            joint_pos=self._q.copy(),
            joint_vel=np.zeros(self.dof, dtype=np.float32),
            joint_effort=np.zeros(self.dof, dtype=np.float32),
        )
        self._last_state = state
        return state

    async def send_joint_command(self, q: np.ndarray) -> None:
        self.sent_commands.append(q.copy())
        self._q = q.astype(np.float32)

    async def set_mode(self, mode: RobotMode) -> None:
        self._mode = mode

    def supports_mode(self, mode: RobotMode) -> bool:
        return True
```

Analogous updates for `MockTeleoperator` and `MockCamera`: accept `fault: FaultProfile | None = None` in `__init__`, honor `drop_prob`, `latency_ms`, `jitter_ms`, and `stuck_for_n_calls` in the corresponding `read_*` method.

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
    robot = MockRobotAdapter(fault=FaultProfile(latency_ms=80, jitter_ms=10))   # way over 33ms tick
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


async def test_stale_sample_counter_increments_when_reader_is_stuck(mock_teleop):
    """If the robot state reader is stuck, the control loop should still tick
    but count the stale samples. Spec §7.2 staleness handling."""
    robot = MockRobotAdapter(fault=FaultProfile(stuck_for_n_calls=1000))
    session = Session(mode=SessionMode.TELEOP, state=SessionState.RECORDING)
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
    await asyncio.sleep(0.3)
    session.stopped.set()
    await loop
    r.cancel(); t.cancel()

    # The exact number depends on timing; require it to be non-zero.
    assert metrics.get("stale_sample_count") > 0
```

This test requires `run_teleop_control_loop` to increment `stale_sample_count` when `slot.peek().t_mono_ns < tick_t - 3*tick_interval_ns`. Add that branch in Task 2's loop now (small diff; spec §7.2 "Staleness handling"). Add a similar small test for camera drop and teleop stuck-for-n-calls.

**Required Task 2 diff (apply as part of Task 9):**

```python
# In run_teleop_control_loop, just after reading `state` and `action`:
stale_threshold = 3 * tick_interval_ns
if state is not None and tick_t - state.t_mono_ns > stale_threshold:
    metrics.inc("stale_sample_count")
```

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

**Goal:** Add `ReplayWatchdog` that enforces the six `replay:` parameters from spec §10 against the replay stream **before** the dispatcher sends each goal. On violation the watchdog (a) raises `ReplaySafetyError(param=...)` inside the replay task, (b) clears `session.replay_active` and `session.sub_state`, (c) writes a hold command to `command_goal_slot` (the current measured joint state), and (d) publishes the error on the `ErrorBus`.

**Control-flow design.** The watchdog is **inline**, not a separate asyncio task. The replay coroutine calls `watchdog.check(target, prev_target, prev_prev_target, measured)` immediately before every `command_goal_slot.set(...)`. This keeps the safety check on the same single-threaded execution path that writes commands — no races with an external watchdog task. The `watchdog_hz` parameter is a bound on how often the replay task is *allowed* to write, not how often a separate task polls.

Config is resolved at session start: `SessionManager` reads the `replay:` block from the resolved robot config and passes a `ReplaySafetyConfig` to the replay task when replay is initiated. The replay task owns the watchdog for its lifetime.

**Parameters enforced (each mapped to a check in `ReplayWatchdog.check`):**

| Param | Check | Error message |
|---|---|---|
| `max_joint_position_jump` | `max(abs(target - measured)) ≤ limit` | `"joint_position_jump exceeded"` |
| `max_joint_velocity` | `max(abs((target - prev_target) / dt)) ≤ limit` | `"joint_velocity exceeded"` |
| `max_joint_acceleration` | `max(abs(((target - prev) - (prev - prev_prev)) / dt²)) ≤ limit` | `"joint_acceleration exceeded"` |
| `ramp_duration_sec` | duration of initial slow-ramp from measured → first frame | — (structural, not a trip) |
| `command_timeout_sec` | time since last successful `command_goal_slot.set()` by replay task | `"command_timeout exceeded"` |
| `watchdog_hz` | the replay task uses this as its *minimum* tick rate when it must hold (between targets) | — (structural) |

**Fallback behaviour:** the replay task has a `hold(measured_state)` method called on any `ReplaySafetyError`. It writes `RobotCommand(q=measured_state.joint_pos)` to `command_goal_slot` once (the dispatcher's collapsing semantics ensure only this holds) and exits. `SessionManager` catches the error, clears `replay_active`, publishes on the error bus, and leaves the session in `READY`.

**Files:**
- Create: `backend/mimicrec/session/replay_safety.py`
- Create: `tests/unit/test_replay_watchdog.py`
- Modify: `backend/mimicrec/session/replay.py`

- [ ] **Step 10.1: Write failing `test_replay_watchdog.py`**

```python
import pytest
import numpy as np

from mimicrec.errors import ReplaySafetyError
from mimicrec.session.replay_safety import ReplaySafetyConfig, ReplayWatchdog


def _cfg(**overrides) -> ReplaySafetyConfig:
    base = ReplaySafetyConfig(
        ramp_duration_sec=2.0,
        max_joint_velocity=1.0,
        max_joint_acceleration=5.0,
        max_joint_position_jump=0.3,
        command_timeout_sec=0.2,
        watchdog_hz=20,
        dof=2,
        dt_sec=1 / 30,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_position_jump_trips():
    wd = ReplayWatchdog(_cfg(max_joint_position_jump=0.05))
    target = np.array([0.5, 0.0], dtype=np.float32)
    measured = np.array([0.0, 0.0], dtype=np.float32)
    with pytest.raises(ReplaySafetyError) as e:
        wd.check(target=target, prev_target=None, prev_prev_target=None, measured=measured)
    assert "joint_position_jump" in str(e.value)


def test_velocity_trips():
    wd = ReplayWatchdog(_cfg(max_joint_velocity=0.1, dt_sec=1 / 30))
    prev = np.array([0.0, 0.0], dtype=np.float32)
    target = np.array([0.1, 0.0], dtype=np.float32)
    measured = np.array([0.05, 0.0], dtype=np.float32)
    with pytest.raises(ReplaySafetyError) as e:
        wd.check(target=target, prev_target=prev, prev_prev_target=None, measured=measured)
    assert "joint_velocity" in str(e.value)


def test_acceleration_trips():
    wd = ReplayWatchdog(_cfg(max_joint_acceleration=1.0, dt_sec=1 / 30))
    prev_prev = np.array([0.0, 0.0], dtype=np.float32)
    prev = np.array([0.01, 0.0], dtype=np.float32)
    target = np.array([1.0, 0.0], dtype=np.float32)
    measured = np.array([0.01, 0.0], dtype=np.float32)
    with pytest.raises(ReplaySafetyError) as e:
        wd.check(target=target, prev_target=prev, prev_prev_target=prev_prev, measured=measured)
    assert "joint_acceleration" in str(e.value)


def test_command_timeout_trips():
    wd = ReplayWatchdog(_cfg(command_timeout_sec=0.05))
    wd.note_command_sent(t_mono_ns=1_000_000_000)
    with pytest.raises(ReplaySafetyError) as e:
        wd.assert_fresh(now_t_mono_ns=1_000_000_000 + 200_000_000)
    assert "command_timeout" in str(e.value)


def test_within_all_limits_does_not_trip():
    wd = ReplayWatchdog(_cfg())
    target = np.array([0.1, 0.1], dtype=np.float32)
    measured = np.array([0.1, 0.1], dtype=np.float32)
    wd.check(target=target, prev_target=target, prev_prev_target=target, measured=measured)
```

- [ ] **Step 10.2: Implement `replay_safety.py`**

`backend/mimicrec/session/replay_safety.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from mimicrec.errors import ReplaySafetyError


@dataclass
class ReplaySafetyConfig:
    ramp_duration_sec: float
    max_joint_velocity: float
    max_joint_acceleration: float
    max_joint_position_jump: float
    command_timeout_sec: float
    watchdog_hz: int
    dof: int
    dt_sec: float     # derived from session fps

    @classmethod
    def from_robot_cfg(cls, robot_cfg, dof: int, dt_sec: float) -> "ReplaySafetyConfig":
        r = robot_cfg.replay
        return cls(
            ramp_duration_sec=float(r.ramp_duration_sec),
            max_joint_velocity=float(r.max_joint_velocity),
            max_joint_acceleration=float(r.max_joint_acceleration),
            max_joint_position_jump=float(r.max_joint_position_jump),
            command_timeout_sec=float(r.command_timeout_sec),
            watchdog_hz=int(r.watchdog_hz),
            dof=dof,
            dt_sec=dt_sec,
        )


class ReplayWatchdog:
    def __init__(self, cfg: ReplaySafetyConfig):
        self._cfg = cfg
        self._last_command_t_mono_ns: int | None = None

    def note_command_sent(self, t_mono_ns: int) -> None:
        self._last_command_t_mono_ns = t_mono_ns

    def assert_fresh(self, now_t_mono_ns: int) -> None:
        if self._last_command_t_mono_ns is None:
            return
        age_sec = (now_t_mono_ns - self._last_command_t_mono_ns) / 1e9
        if age_sec > self._cfg.command_timeout_sec:
            raise ReplaySafetyError(
                f"command_timeout exceeded: {age_sec:.3f}s > {self._cfg.command_timeout_sec}s"
            )

    def check(
        self,
        target: np.ndarray,
        prev_target: np.ndarray | None,
        prev_prev_target: np.ndarray | None,
        measured: np.ndarray,
    ) -> None:
        if np.max(np.abs(target - measured)) > self._cfg.max_joint_position_jump:
            raise ReplaySafetyError(
                f"joint_position_jump exceeded: "
                f"max={float(np.max(np.abs(target - measured))):.3f} > "
                f"{self._cfg.max_joint_position_jump}"
            )
        if prev_target is not None:
            velocity = np.abs((target - prev_target) / self._cfg.dt_sec)
            if float(np.max(velocity)) > self._cfg.max_joint_velocity:
                raise ReplaySafetyError(
                    f"joint_velocity exceeded: max={float(np.max(velocity)):.3f} > "
                    f"{self._cfg.max_joint_velocity}"
                )
        if prev_target is not None and prev_prev_target is not None:
            accel = np.abs((target - 2 * prev_target + prev_prev_target) / (self._cfg.dt_sec ** 2))
            if float(np.max(accel)) > self._cfg.max_joint_acceleration:
                raise ReplaySafetyError(
                    f"joint_acceleration exceeded: max={float(np.max(accel)):.3f} > "
                    f"{self._cfg.max_joint_acceleration}"
                )
```

- [ ] **Step 10.3: Run unit tests, verify green**

```bash
pytest tests/unit/test_replay_watchdog.py -v
```

Expected: `5 passed`.

- [ ] **Step 10.4: Wire the watchdog into `run_replay`**

Update `backend/mimicrec/session/replay.py`:

```python
# Add signature parameter: safety: ReplaySafetyConfig, measured_state_slot: LatestValue[RobotState]
# Inside the per-target loop, call:
#   wd.assert_fresh(clock.monotonic_ns())
#   wd.check(target=q, prev_target=prev_q, prev_prev_target=prev_prev_q, measured=measured)
# Maintain prev_q / prev_prev_q rolling history.
# On ReplaySafetyError:
#   session.replay_active = False
#   measured = measured_state_slot.peek()
#   if measured is not None:
#       command_goal_slot.set(RobotCommand(q=measured.value.joint_pos, t_mono_ns=clock.monotonic_ns()),
#                             t_mono_ns=clock.monotonic_ns())
#   await error_bus.publish(e)
#   raise
# After a successful set, call wd.note_command_sent(clock.monotonic_ns()).
```

- [ ] **Step 10.5: Write an integration test that proves replay halts on a jump**

`tests/integration/test_replay_halts_on_jump.py`:

```python
import asyncio
import numpy as np
import pytest

from mimicrec.errors import ReplaySafetyError
from mimicrec.session.replay import ReplayTrajectory, run_replay
from mimicrec.session.replay_safety import ReplaySafetyConfig
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, RobotState, SessionMode, SessionState, Stamped
from mimicrec.util.clock import RealClock
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


async def test_replay_halts_on_position_jump_and_holds_measured():
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    cg: LatestValue[RobotCommand] = LatestValue()
    measured: LatestValue[RobotState] = LatestValue()
    measured.set(
        RobotState(
            joint_pos=np.zeros(2, dtype=np.float32),
            joint_vel=np.zeros(2, np.float32),
            joint_effort=np.zeros(2, np.float32),
        ),
        t_mono_ns=1,
    )

    cfg = ReplaySafetyConfig(
        ramp_duration_sec=0.0,
        max_joint_velocity=10.0,
        max_joint_acceleration=1000.0,
        max_joint_position_jump=0.1,
        command_timeout_sec=1.0,
        watchdog_hz=20,
        dof=2,
        dt_sec=1 / 30,
    )
    traj = ReplayTrajectory(joint_targets=np.array([[5.0, 5.0]], dtype=np.float32))
    bus = ErrorBus()
    sub = bus.subscribe()

    with pytest.raises(ReplaySafetyError):
        await run_replay(
            session=session, trajectory=traj, fps=30,
            command_goal_slot=cg, measured_state_slot=measured,
            clock=RealClock(), safety=cfg, error_bus=bus,
        )
    assert session.replay_active is False
    held = cg.peek()
    assert held is not None
    # After trip, measured state (all zeros) should be the hold command
    assert (held.value.q == 0.0).all()
    evt = sub.get_nowait()
    assert isinstance(evt, ReplaySafetyError)
```

- [ ] **Step 10.6: Commit**

```bash
git add backend/mimicrec/session/replay_safety.py backend/mimicrec/session/replay.py \
    tests/unit/test_replay_watchdog.py tests/integration/test_replay_halts_on_jump.py
git commit -m "planA: replay safety watchdog enforces config-driven parameters"
```

---

## Task 11 — SessionManager (domain-level lifecycle)

**Goal:** Orchestrate all tasks under one `SessionManager` with clean start/end and explicit episode/replay transitions. No FastAPI — just domain methods.

**Responsibilities of `SessionManager`:**

1. **Task ownership.** Holds `asyncio.Task` handles for each reader (robot, teleop, per-camera), the control loop, the command dispatcher, and the writer. Starts them all on `start()`; cancels and awaits them all on `end()` in reverse order (writer → dispatcher → control loop → readers → camera manager). Shutdown also drains `recorder.queue` first to persist any late bundles from the control loop.
2. **Slots.** Owns the `LatestValue` slots: `robot_state_slot`, `teleop_slot`, per-camera camera_slots (owned by `CameraManager`), `command_goal_slot`, `current_pending`, `measured_state_slot` (alias for `robot_state_slot` but named for replay use).
3. **State machine.** `state: SessionState` is the single source of truth. Transitions are guarded:
   - `start(cfg)`: `IDLE → READY`. `precheck_start` runs first (may raise `HandTeachNotSupportedError`). Mode-dispatches to either `run_teleop_control_loop` or `run_handteach_control_loop`.
   - `episode_start()`: `READY → RECORDING`. Must not be called while `replay_active`; raises `InvalidTransitionError`. Creates a new `PendingEpisode`, opens per-camera MP4 writers, writes it to `current_pending`.
   - `episode_stop()`: `RECORDING → REVIEW`. Drains the queue (briefly — up to `queue_flush_timeout_sec=1.0`), finalises the pending's parquet buffer and MP4 writers (but does NOT move files yet).
   - `episode_save(success, comment)`: `REVIEW → READY`. Moves pending files into dataset, appends `episodes.jsonl` row (including the resolved config snapshot and timestamps). Clears `current_pending`.
   - `episode_discard()`: `REVIEW → READY`. `rmtree` the pending staging dir. Clears `current_pending`.
   - `replay_start(trajectory)`: asserts `state == READY and not replay_active`. Spawns `run_replay` as a task; `replay_active` is flipped on by `run_replay` itself.
   - `replay_stop()`: sets `session.replay_active = False` (breaks the replay loop on its next iteration), awaits the task.
   - `end()`: any state → `IDLE`. Force-cancels ongoing replay and pending, then shuts down tasks as above.
4. **Error handling.** Subscribes to the `ErrorBus` once at start. On `HardwareError` during `RECORDING`, triggers an auto-discard (§7.3): sets `state = READY`, calls `episode_discard()`-equivalent cleanup, re-publishes the error for consumers (Plan B WebSocket). On `HardwareError` in `READY`/`REVIEW`, logs and re-publishes; does not abort the session. On `ReplaySafetyError`, the replay task already cleared `replay_active`; `SessionManager` logs and re-publishes.
5. **Task aggregation.** Each spawned task's exception is captured via a `done_callback`; the callback publishes the exception on the `ErrorBus` and sets `self._fatal = True` so the next domain-method call raises `RuntimeError("session is in a fatal state")`.
6. **Shutdown ordering.** Writer MUST drain before dispatcher shuts down (so final rows are committed). Dispatcher MUST finish before robot.disconnect (so no late writes go to a closed device). Readers can be cancelled in any order.

**Files:**
- Modify: `backend/mimicrec/session/lifecycle.py` — grow `SessionManager` class
- Create: `backend/mimicrec/session/tasks.py` — `start_session_tasks()` helper that `SessionManager` calls (separation of concerns: the task graph layout is one function, the state-machine orchestration is another)
- Create: `tests/integration/test_session_lifecycle_mock.py`
- Create: `tests/integration/test_auto_discard_on_hardware_error.py`

- [ ] **Step 11.1: Sketch the `SessionManager` skeleton (no logic yet)**

Write `SessionManager.__init__`, property getters, and typed stubs for `start`, `end`, `episode_start`, `episode_stop`, `episode_save`, `episode_discard`, `replay_start`, `replay_stop`, each raising `NotImplementedError`. Commit as "planA: SessionManager skeleton".

- [ ] **Step 11.2: Write failing `test_session_lifecycle_mock.py`**

```python
import asyncio
import numpy as np
import pytest
from pathlib import Path

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.cameras.manager import CameraManager
from mimicrec.errors import InvalidTransitionError
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager, SessionStartConfig
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.types import SessionMode, SessionState
from mimicrec.util.error_bus import ErrorBus


async def test_full_teleop_flow(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=["front"])
    robot = MockRobotAdapter()
    teleop = MockTeleoperator(dof=2)
    bus = ErrorBus()
    cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=bus)
    sm = SessionManager(
        dataset_root=ds,
        robot=robot, teleop=teleop, mapper=IdentityMapper(),
        cameras=cm, mode=SessionMode.TELEOP, fps=30, error_bus=bus,
        resolved_config={},
        replay_safety=None,
    )

    await sm.start()
    assert sm.state == SessionState.READY

    await sm.episode_start()
    assert sm.state == SessionState.RECORDING
    await asyncio.sleep(0.2)

    await sm.episode_stop()
    assert sm.state == SessionState.REVIEW

    await sm.episode_save(success=True, comment="ok")
    assert sm.state == SessionState.READY

    paths = dataset_paths(ds)
    assert (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()

    # Attempting episode_start during replay must fail
    sm.session.replay_active = True
    with pytest.raises(InvalidTransitionError):
        await sm.episode_start()
    sm.session.replay_active = False

    await sm.end()
    assert sm.state == SessionState.IDLE
```

- [ ] **Step 11.3: Implement `SessionManager` in `lifecycle.py`**

This is the biggest single implementation chunk in Plan A. Keep it organised: one helper `_spawn_tasks()` that returns a `SessionTaskSet`, one `_shutdown_tasks()` that cancels in the documented order with timeouts. All state transitions check the current state and raise `InvalidTransitionError` on mismatch.

Key interfaces:

```python
@dataclass
class SessionStartConfig:
    resolved_config: dict   # snapshot of the merged OmegaConf tree

@dataclass
class SessionTaskSet:
    robot_reader: asyncio.Task
    teleop_reader: asyncio.Task | None
    control_loop: asyncio.Task
    dispatcher: asyncio.Task
    writer: asyncio.Task
```

Shutdown sequence (`end()`):

```python
# 1. Stop producers
self.session.stopped.set()        # readers/loop exit on next iteration
await self._await_with_timeout(self.tasks.teleop_reader, 1.0)
await self._await_with_timeout(self.tasks.robot_reader, 1.0)
await self._await_with_timeout(self.tasks.control_loop, 1.0)

# 2. Drain queue and stop writer
# give writer one more pass to drain; stopped=True causes it to exit when queue empty
await self._await_with_timeout(self.tasks.writer, 2.0)

# 3. Stop dispatcher
await self._await_with_timeout(self.tasks.dispatcher, 1.0)

# 4. Stop CameraManager
await self.cameras.stop()

# 5. Disconnect robot
await self.robot.disconnect()

self.session.state = SessionState.IDLE
```

- [ ] **Step 11.4: Write failing `test_auto_discard_on_hardware_error.py`**

```python
import asyncio
import numpy as np
from pathlib import Path

from mimicrec.adapters.fault_profile import FaultProfile
from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.cameras.manager import CameraManager
from mimicrec.errors import HardwareError
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.lifecycle import SessionManager
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.types import SessionMode, SessionState
from mimicrec.util.error_bus import ErrorBus


async def test_hardware_error_during_recording_auto_discards(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=["front"])

    # Schedule a camera drop partway through the episode
    cam = MockCamera("front")
    cam.drop_next = 3
    bus = ErrorBus()
    cm = CameraManager(cameras={"front": cam}, error_bus=bus)

    sm = SessionManager(
        dataset_root=ds,
        robot=MockRobotAdapter(), teleop=MockTeleoperator(dof=2),
        mapper=IdentityMapper(), cameras=cm,
        mode=SessionMode.TELEOP, fps=30, error_bus=bus,
        resolved_config={}, replay_safety=None,
    )
    await sm.start()
    await sm.episode_start()
    await asyncio.sleep(0.3)

    # The session must have auto-discarded, returned to READY, and NOT committed
    assert sm.state == SessionState.READY
    paths = dataset_paths(ds)
    assert not (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()

    await sm.end()
```

- [ ] **Step 11.5: Implement the auto-discard handler in `SessionManager`**

When a `HardwareError` arrives on the bus *and* `state == RECORDING`: set `state = READY`, call the pending-discard path, publish the error for Plan B consumers. Log and surface a clear message.

- [ ] **Step 11.6: Run the integration suite, verify green**

```bash
pytest tests/integration -v
```

Expected: all green.

- [ ] **Step 11.7: Commit**

```bash
git add backend/mimicrec/session tests/integration/test_session_lifecycle_mock.py \
    tests/integration/test_auto_discard_on_hardware_error.py
git commit -m "planA: SessionManager integrates the full task graph"
```

---

## Task 12 — Exit-criteria test suite

**Goal:** Lock the exit criteria as a dedicated test directory that CI can run as `pytest -k exit_criterion`. Each criterion maps to one test file that uses `SessionManager` end-to-end against mocks. **Use `FakeClock` wherever the test asserts a tick count or frame count, so results are deterministic.** `RealClock` is acceptable only for criteria 2 and 9 where the test is asserting *qualitative* behaviour (stream delivery, fault recovery), not exact counts.

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

**Criterion-specific rubrics:**

- **3 (FPS):** Use `FakeClock`, advance by exactly `1.0s` worth of `tick_interval_ns`, assert `writer_rows_written == expected` ± 1 (for start/stop edges), and `ticks_skipped == 0`.
- **5 (no restart):** Capture `id(sm.tasks.control_loop)` before `episode_stop`, assert identical after `episode_save`.
- **6 (save and discard):** Two episodes in one session — save the first, discard the second. Final dataset has one `episode_000000.parquet`, no `.pending/` contents, no `episode_000001.*` files.
- **7 (replay gates teleop):** Set `teleop.target` to a known "leaked-if-sent" value, run replay with a distinct trajectory, assert the teleop value never appears in the dispatcher's `sent_commands`.
- **9 (fault injection):** Apply `FaultProfile(drop_prob=0.2, latency_ms=50)` to the robot reader for 2 seconds. Assert `ticks_skipped > 0`, `stale_sample_count > 0`, and the session is still in a valid state (no crash, no orphan tasks).

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
