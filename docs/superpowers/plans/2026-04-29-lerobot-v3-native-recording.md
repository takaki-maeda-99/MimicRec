# LeRobot v3-Native Recording Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MimicRec write LeRobot v3-native parquet at recording time so the raw dataset is directly loadable by `LeRobotDataset` — and remove the `vla_compat` exporter as a side-effect. SO-101's gripper-duplication bug is resolved by construction.

**Architecture:** Single recording path emits the 8-column packed schema (`action`, `observation.state`, `language_instruction`, `timestamp`, `frame_index`, `episode_index`, `index`, `task_index`). SO-101 adapter is restructured to `dof=5` arm + a separate gripper field on `RobotState`/`RobotCommand`/`TeleopAction`. Replay reader splits the packed action column. All `exporters/` code, the `/api/datasets/{ds}/export` POST endpoint, and the frontend `ExportDatasetModal` are deleted.

**Tech Stack:** Python 3.10+ (FastAPI / pyarrow / numpy), pytest, React/TypeScript frontend.

**Spec:** `docs/superpowers/specs/2026-04-29-lerobot-v3-native-recording-design.md`

**Test runner:** `env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/...` from `backend/` cwd.

---

## Phase 1 — Type system + IdentityMapper (gripper plumbing)

### Task 1: Add `gripper` field to `TeleopAction`

**Files:**
- Modify: `backend/mimicrec/types.py:61-65`
- Test: `tests/unit/test_types_teleop_action.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_types_teleop_action.py`:

```python
import numpy as np

from mimicrec.types import TeleopAction


def test_teleop_action_carries_gripper():
    a = TeleopAction(target_joint_pos=np.zeros(5, dtype=np.float32), gripper=42.5)
    assert a.gripper == 42.5


def test_teleop_action_gripper_defaults_to_none():
    a = TeleopAction(target_joint_pos=np.zeros(5, dtype=np.float32))
    assert a.gripper is None
```

- [ ] **Step 2: Run test to verify it fails**

```
cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_types_teleop_action.py -v
```

Expected: `TypeError: __init__() got an unexpected keyword argument 'gripper'`

- [ ] **Step 3: Implement**

Edit `backend/mimicrec/types.py`:

```python
@dataclass
class TeleopAction:
    target_joint_pos: np.ndarray | None = None
    ee_delta: np.ndarray | None = None
    gripper: float | None = None
    t_mono_ns: int = 0
```

- [ ] **Step 4: Verify pass**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_types_teleop_action.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/types.py tests/unit/test_types_teleop_action.py
git commit -m "feat(types): add gripper field to TeleopAction"
```

---

### Task 2: `IdentityMapper` forwards gripper

**Files:**
- Modify: `backend/mimicrec/mappers/identity.py`
- Test: `tests/unit/test_mappers_identity.py`

- [ ] **Step 1: Add failing test**

Append to `tests/unit/test_mappers_identity.py`:

```python
def test_identity_mapper_forwards_gripper():
    import numpy as np
    from mimicrec.mappers.identity import IdentityMapper
    from mimicrec.types import RobotState, TeleopAction

    state = RobotState(
        joint_pos=np.zeros(5, dtype=np.float32),
        joint_vel=np.zeros(5, dtype=np.float32),
        joint_effort=np.zeros(5, dtype=np.float32),
    )
    action = TeleopAction(
        target_joint_pos=np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32),
        gripper=77.0,
    )
    cmd = IdentityMapper().map(action, state)
    assert cmd.gripper == 77.0
    np.testing.assert_allclose(cmd.q, [0.1, 0.2, 0.3, 0.4, 0.5])
```

- [ ] **Step 2: Verify fail**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_mappers_identity.py::test_identity_mapper_forwards_gripper -v
```

Expected: `AssertionError: assert None == 77.0` (current code drops gripper).

- [ ] **Step 3: Implement**

Replace `backend/mimicrec/mappers/identity.py`:

```python
from __future__ import annotations
from mimicrec.types import RobotCommand, RobotState, TeleopAction


class IdentityMapper:
    def map(self, action: TeleopAction, robot_state: RobotState) -> RobotCommand:
        assert action.target_joint_pos is not None, "IdentityMapper requires joint-pos teleop"
        return RobotCommand(
            q=action.target_joint_pos.copy(),
            gripper=action.gripper,
        )
```

- [ ] **Step 4: Verify pass**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_mappers_identity.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/mappers/identity.py tests/unit/test_mappers_identity.py
git commit -m "feat(mappers): IdentityMapper forwards TeleopAction.gripper"
```

---

## Phase 2 — SO-101 adapter restructure

### Task 3: SO-101 `read_state()` splits gripper out of joint_pos

**Files:**
- Modify: `backend/mimicrec/adapters/so101.py:9, 13-14, 63-73`
- Test: `tests/unit/test_so101_read_state.py` (new)

- [ ] **Step 1: Add failing test**

Create `tests/unit/test_so101_read_state.py`:

```python
import asyncio
import numpy as np
from unittest.mock import patch, MagicMock

from mimicrec.adapters.so101 import SO101Adapter, JOINT_NAMES


def test_dof_is_5_arm_only():
    a = SO101Adapter()
    assert a.dof == 5
    assert a.joint_names == ["shoulder_pan", "shoulder_lift", "elbow_flex",
                             "wrist_flex", "wrist_roll"]


def test_read_state_splits_gripper():
    a = SO101Adapter()
    fake_follower = MagicMock()
    fake_follower.get_observation.return_value = {
        "shoulder_pan.pos": 1.0, "shoulder_lift.pos": 2.0,
        "elbow_flex.pos": 3.0, "wrist_flex.pos": 4.0,
        "wrist_roll.pos": 5.0, "gripper.pos": 42.0,
    }
    a._follower = fake_follower
    state = asyncio.get_event_loop().run_until_complete(a.read_state())
    assert state.joint_pos.shape == (5,)
    np.testing.assert_allclose(state.joint_pos, [1.0, 2.0, 3.0, 4.0, 5.0])
    assert state.gripper_pos == 42.0
```

- [ ] **Step 2: Verify fail**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_so101_read_state.py -v
```

Expected: `assert 6 == 5` on `dof`.

- [ ] **Step 3: Implement**

Edit `backend/mimicrec/adapters/so101.py`:

```python
JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
_GRIPPER_KEY = "gripper"


class SO101Adapter:
    name = "so101"
    dof = 5
    joint_names = JOINT_NAMES
    # ... __init__ unchanged ...

    async def read_state(self) -> RobotState:
        assert self._follower is not None
        loop = asyncio.get_running_loop()
        async with self._bus_lock:
            obs = await loop.run_in_executor(None, self._follower.get_observation)
        joint_pos = np.array([obs[f"{j}.pos"] for j in JOINT_NAMES], dtype=np.float32)
        gripper_pos = float(obs[f"{_GRIPPER_KEY}.pos"])
        return RobotState(
            joint_pos=joint_pos,
            joint_vel=np.zeros(self.dof, dtype=np.float32),
            joint_effort=np.zeros(self.dof, dtype=np.float32),
            gripper_pos=gripper_pos,
        )
```

- [ ] **Step 4: Verify pass + suite**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_so101_read_state.py ../tests/unit/test_so101_handteach_unsupported.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/adapters/so101.py tests/unit/test_so101_read_state.py
git commit -m "feat(so101): dof=5, split gripper out of joint_pos"
```

---

### Task 4: SO-101 `send_joint_command(q, *, gripper=None)`

**Files:**
- Modify: `backend/mimicrec/adapters/so101.py:75-80`
- Test: `tests/unit/test_so101_send_joint_command.py` (new)

- [ ] **Step 1: Add failing test**

Create `tests/unit/test_so101_send_joint_command.py`:

```python
import asyncio
import numpy as np
from unittest.mock import MagicMock

from mimicrec.adapters.so101 import SO101Adapter


def test_send_joint_command_packs_gripper_into_action_dict():
    a = SO101Adapter()
    a._follower = MagicMock()
    q = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
    asyncio.get_event_loop().run_until_complete(
        a.send_joint_command(q, gripper=88.0)
    )
    sent = a._follower.send_action.call_args.args[0]
    assert sent["shoulder_pan.pos"] == 0.1
    assert sent["wrist_roll.pos"] == 0.5
    assert sent["gripper.pos"] == 88.0


def test_send_joint_command_holds_gripper_when_none():
    """When gripper kwarg is None, the adapter must still produce a 6-key
    dict so lerobot's send_action accepts it. Reads current gripper position
    via get_observation and re-sends that value (gripper holds)."""
    a = SO101Adapter()
    a._follower = MagicMock()
    a._follower.get_observation.return_value = {
        "shoulder_pan.pos": 0.0, "shoulder_lift.pos": 0.0,
        "elbow_flex.pos": 0.0, "wrist_flex.pos": 0.0,
        "wrist_roll.pos": 0.0, "gripper.pos": 33.3,
    }
    q = np.zeros(5, dtype=np.float32)
    asyncio.get_event_loop().run_until_complete(a.send_joint_command(q))
    sent = a._follower.send_action.call_args.args[0]
    assert sent["gripper.pos"] == 33.3
```

- [ ] **Step 2: Verify fail**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_so101_send_joint_command.py -v
```

Expected: `TypeError: send_joint_command() got an unexpected keyword argument 'gripper'`.

- [ ] **Step 3: Implement**

Replace `send_joint_command` in `backend/mimicrec/adapters/so101.py`:

```python
async def send_joint_command(self, q: np.ndarray, *, gripper: float | None = None) -> None:
    assert self._follower is not None
    loop = asyncio.get_running_loop()
    if gripper is None:
        # lerobot's send_action requires all 6 keys; hold current gripper.
        async with self._bus_lock:
            obs = await loop.run_in_executor(None, self._follower.get_observation)
        gripper = float(obs[f"{_GRIPPER_KEY}.pos"])
    action = {f"{j}.pos": float(q[i]) for i, j in enumerate(JOINT_NAMES)}
    action[f"{_GRIPPER_KEY}.pos"] = float(gripper)
    async with self._bus_lock:
        await loop.run_in_executor(None, self._follower.send_action, action)
```

- [ ] **Step 4: Verify pass**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_so101_send_joint_command.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/adapters/so101.py tests/unit/test_so101_send_joint_command.py
git commit -m "feat(so101): send_joint_command(q, gripper=...) inline contract"
```

---

### Task 5: SO-101 leader splits gripper into `TeleopAction.gripper`

**Files:**
- Modify: `backend/mimicrec/adapters/so_leader.py`
- Test: `tests/unit/test_so_leader.py` (new — read_action only)

- [ ] **Step 1: Add failing test**

Create `tests/unit/test_so_leader.py`. The class is `SOLeaderAdapter` (the unqualified `SOLeader` symbol in this module is the upstream lerobot teleop class). The internal teleop handle is `self._leader` and reads happen through `self._leader.get_action()`:

```python
import asyncio
import numpy as np
from unittest.mock import MagicMock

from mimicrec.adapters.so_leader import SOLeaderAdapter


def test_leader_read_action_splits_gripper():
    leader = SOLeaderAdapter()
    leader._leader = MagicMock()
    leader._leader.get_action.return_value = {
        "shoulder_pan.pos": 1.0, "shoulder_lift.pos": 2.0,
        "elbow_flex.pos": 3.0, "wrist_flex.pos": 4.0,
        "wrist_roll.pos": 5.0, "gripper.pos": 75.0,
    }
    a = asyncio.get_event_loop().run_until_complete(leader.read_action())
    assert a.target_joint_pos.shape == (5,)
    np.testing.assert_allclose(a.target_joint_pos, [1.0, 2.0, 3.0, 4.0, 5.0])
    assert a.gripper == 75.0
```

- [ ] **Step 2: Verify fail**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_so_leader.py -v
```

Expected: target_joint_pos has shape (6,) (current behavior).

- [ ] **Step 3: Implement**

Modify `backend/mimicrec/adapters/so_leader.py`'s `read_action()` to:
- Read all 6 motor positions from the teleop bus via `self._leader.get_action()`
- Pack 5 arm values into `target_joint_pos: np.ndarray[5]`
- Set `gripper = float(obs["gripper.pos"])` on the returned `TeleopAction`

- [ ] **Step 4: Verify pass**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_so_leader.py -v
```

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/adapters/so_leader.py tests/unit/test_so_leader.py
git commit -m "feat(so_leader): split gripper into TeleopAction.gripper"
```

---

## Phase 3 — Universal `send_joint_command(q, *, gripper=None)` contract

### Task 6: reBotArm adapter accepts `gripper` kwarg; dispatcher uses it

**Files:**
- Modify: `backend/mimicrec/adapters/rebotarm_zmq.py` (find `send_joint_command` and `send_gripper_command`)
- Modify: `backend/mimicrec/session/dispatcher.py:34-46`
- Test: `tests/unit/test_dispatcher_passes_gripper.py` (new)

- [ ] **Step 1: Inspect**

```
grep -n "send_joint_command\|send_gripper_command" backend/mimicrec/adapters/rebotarm_zmq.py backend/mimicrec/session/dispatcher.py
```

- [ ] **Step 2: Add failing test**

Create `tests/unit/test_dispatcher_passes_gripper.py`:

```python
import asyncio
from unittest.mock import AsyncMock

import numpy as np

from mimicrec.session.dispatcher import run_command_dispatcher
from mimicrec.types import RobotCommand
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


def test_dispatcher_calls_send_joint_command_with_gripper_kwarg():
    robot = AsyncMock()
    goal = LatestValue()
    cmd = RobotCommand(q=np.zeros(5, dtype=np.float32), gripper=42.0)
    goal.set(cmd, t_mono_ns=1)
    stopped = asyncio.Event()
    errors = ErrorBus()

    async def _run():
        task = asyncio.create_task(run_command_dispatcher(robot, goal, errors, stopped))
        await asyncio.sleep(0.05)
        stopped.set()
        await task

    asyncio.get_event_loop().run_until_complete(_run())
    robot.send_joint_command.assert_called()
    kwargs = robot.send_joint_command.call_args.kwargs
    assert kwargs.get("gripper") == 42.0
    # The legacy send_gripper_command path should no longer be called.
    assert not robot.method_calls or not any(
        c[0] == "send_gripper_command" for c in robot.method_calls
    )
```

- [ ] **Step 3: Verify fail**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_dispatcher_passes_gripper.py -v
```

Expected: `kwargs.get("gripper")` is None — dispatcher today doesn't pass gripper through.

- [ ] **Step 4: Implement dispatcher change**

Edit `backend/mimicrec/session/dispatcher.py`:

```python
try:
    await robot.send_joint_command(current.value.q, gripper=current.value.gripper)
    consecutive_errors = 0
except HardwareError as e:
    logger.warning("dispatcher HardwareError: %s", e)
    await errors.publish(e)
```

(Delete the entire `# Forward the gripper target ...` block including the `hasattr(robot, "send_gripper_command")` branch.)

- [ ] **Step 5: Implement reBotArm change**

In `backend/mimicrec/adapters/rebotarm_zmq.py`:

1. Rename the existing `async def send_gripper_command(self, gripper: float) -> None` method to `async def _send_gripper(self, gripper: float) -> None`. Body preserved verbatim (ZMQ envelope, HardwareError raises, etc).
2. Update the `send_joint_command` signature to:
   ```python
   async def send_joint_command(self, q: np.ndarray, *, gripper: float | None = None) -> None:
       # ... existing q-send body unchanged ...
       if gripper is not None:
           await self._send_gripper(float(gripper))
   ```

The rename + delegation keeps the gripper implementation intact while collapsing the dispatcher's call surface to one method.

- [ ] **Step 6: Verify pass + suite**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_dispatcher_passes_gripper.py ../tests/unit/test_command_dispatcher.py -v
```

Other dispatcher tests may break if they assert on the legacy gripper path; update them in this commit.

- [ ] **Step 7: Commit**

```
git add backend/mimicrec/adapters/rebotarm_zmq.py backend/mimicrec/session/dispatcher.py tests/unit/test_dispatcher_passes_gripper.py tests/unit/test_command_dispatcher.py
git commit -m "feat(dispatcher): universal send_joint_command(q, gripper=...) contract; drop send_gripper_command branch"
```

---

## Phase 4 — Recording schema rewrite

### Task 7: `init_dataset` writes new features dict

**Files:**
- Modify: `backend/mimicrec/recording/dataset_layout.py:42-99`
- Test: `tests/unit/test_dataset_layout_init.py` (new)

- [ ] **Step 1: Add failing test**

Create `tests/unit/test_dataset_layout_init.py`:

```python
import json
from pathlib import Path

from mimicrec.recording.dataset_layout import init_dataset


def test_init_dataset_features_match_lerobot_v3_packed_schema(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2", "j3", "j4", "j5"], camera_names=["front"])
    info = json.loads((ds / "meta" / "info.json").read_text())
    f = info["features"]

    # action / observation.state packed: Narm + 1 gripper
    assert f["action"]["dtype"] == "float32"
    assert f["action"]["shape"] == [6]
    assert f["action"]["names"] == ["j1", "j2", "j3", "j4", "j5", "gripper"]
    assert f["observation.state"]["shape"] == [6]
    assert f["observation.state"]["names"] == ["j1", "j2", "j3", "j4", "j5", "gripper"]

    # language_instruction declared
    assert f["language_instruction"]["dtype"] == "string"

    # ancillary observation columns NOT declared
    for forbidden in (
        "observation.state.joint_pos",
        "observation.state.joint_vel",
        "observation.state.joint_effort",
        "observation.state.t_mono_ns",
        "action.joint_pos",
        "action.gripper_pos",
        "action.t_mono_ns",
    ):
        assert forbidden not in f, forbidden

    # video features stay
    assert f["observation.images.front"]["dtype"] == "video"

    # placeholders use file_index
    assert "{file_index" in info["data_path"]
    assert "{file_index" in info["video_path"]
```

- [ ] **Step 2: Verify fail**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_dataset_layout_init.py -v
```

Expected: `f["action"]["shape"] == [6]` fails (currently `[5]` because joint_names alone, no gripper appended), and `language_instruction` missing.

- [ ] **Step 3: Implement**

Replace the `features` block in `init_dataset` (`backend/mimicrec/recording/dataset_layout.py:50-72`):

```python
dof = len(joint_names)
N = dof + 1  # arm joints + gripper
packed_names = list(joint_names) + ["gripper"]

features: dict = {
    "action": {"dtype": "float32", "shape": [N], "names": packed_names},
    "observation.state": {"dtype": "float32", "shape": [N], "names": packed_names},
    "language_instruction": {"dtype": "string", "shape": [1], "names": None},
    "timestamp": {"dtype": "float32", "shape": [1], "names": None},
    "frame_index": {"dtype": "int64", "shape": [1], "names": None},
    "episode_index": {"dtype": "int64", "shape": [1], "names": None},
    "index": {"dtype": "int64", "shape": [1], "names": None},
    "task_index": {"dtype": "int64", "shape": [1], "names": None},
}

for cam in camera_names:
    features[f"observation.images.{cam}"] = {
        "dtype": "video",
        "shape": [480, 640, 3],
        "names": ["height", "width", "channels"],
        "info": {
            "video.height": 480, "video.width": 640,
            "video.codec": "libx264", "video.pix_fmt": "yuv420p",
            "video.is_depth_map": False, "video.fps": fps,
            "video.channels": 3, "has_audio": False,
        },
    }
```

- [ ] **Step 4: Verify pass**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_dataset_layout_init.py -v
```

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/recording/dataset_layout.py tests/unit/test_dataset_layout_init.py
git commit -m "feat(dataset_layout): init_dataset writes packed v3-native features"
```

---

### Task 8: `parquet_row.sample_bundle_to_row` emits packed schema

**Files:**
- Modify: `backend/mimicrec/recording/parquet_row.py`
- Test: rewrite `tests/unit/test_parquet_row.py`
- Test: delete `tests/unit/test_parquet_row_ee_pref.py` (asserts on dropped columns)

- [ ] **Step 1: Replace tests**

Replace `tests/unit/test_parquet_row.py` entirely:

```python
import numpy as np
import pytest

from mimicrec.recording.parquet_row import sample_bundle_to_row
from mimicrec.types import RobotState, RobotCommand, SampleBundle, Stamped


def _bundle(joint_pos, gripper_pos, action_q, action_gripper):
    state = Stamped(
        RobotState(
            joint_pos=np.asarray(joint_pos, dtype=np.float32),
            joint_vel=np.zeros_like(joint_pos, dtype=np.float32),
            joint_effort=np.zeros_like(joint_pos, dtype=np.float32),
            gripper_pos=gripper_pos,
        ),
        t_mono_ns=1_000_000_000,
    )
    cmd = RobotCommand(q=np.asarray(action_q, dtype=np.float32), gripper=action_gripper, t_mono_ns=1_001_000_000)
    return SampleBundle(
        tick_t_mono_ns=1_000_000_000,
        state=state,
        action=cmd,
        frames={},
    )


def test_row_has_exactly_eight_keys():
    bundle = _bundle([0.1] * 5, 50.0, [0.2] * 5, 60.0)
    row = sample_bundle_to_row(bundle, episode_start_t_mono_ns=1_000_000_000,
                               instruction="pick the block")
    assert set(row.keys()) == {
        "action", "observation.state", "language_instruction",
        "timestamp", "frame_index", "episode_index", "index", "task_index",
    }


def test_action_packed_arm_plus_gripper():
    bundle = _bundle([0.0] * 5, 0.0, [0.1, 0.2, 0.3, 0.4, 0.5], 77.0)
    row = sample_bundle_to_row(bundle, 1_000_000_000, instruction="x")
    assert row["action"].dtype == np.float32
    assert row["action"].shape == (6,)
    np.testing.assert_allclose(row["action"], [0.1, 0.2, 0.3, 0.4, 0.5, 77.0])


def test_observation_state_packed():
    bundle = _bundle([0.1, 0.2, 0.3, 0.4, 0.5], 88.0, [0.0] * 5, 0.0)
    row = sample_bundle_to_row(bundle, 1_000_000_000, instruction="x")
    assert row["observation.state"].shape == (6,)
    np.testing.assert_allclose(row["observation.state"], [0.1, 0.2, 0.3, 0.4, 0.5, 88.0])


def test_language_instruction_passthrough():
    bundle = _bundle([0.0] * 5, 0.0, [0.0] * 5, 0.0)
    row = sample_bundle_to_row(bundle, 1_000_000_000, instruction="pick the red block")
    assert row["language_instruction"] == "pick the red block"


def test_indices_passthrough():
    bundle = _bundle([0.0] * 5, 0.0, [0.0] * 5, 0.0)
    row = sample_bundle_to_row(bundle, 1_000_000_000, instruction="x",
                               frame_index=7, episode_index=3, global_index=42, task_index=2)
    assert row["frame_index"] == 7
    assert row["episode_index"] == 3
    assert row["index"] == 42
    assert row["task_index"] == 2


def test_raises_when_gripper_missing():
    """Both gripper_pos AND fallback joint_pos[Narm] are absent — raise."""
    bundle = _bundle([0.0] * 5, None, [0.0] * 5, None)
    with pytest.raises(ValueError, match="gripper"):
        sample_bundle_to_row(bundle, 1_000_000_000, instruction="x")


def test_falls_back_to_joint_pos_slack_when_gripper_pos_missing():
    """Legacy adapters pack gripper into joint_pos[5]; bundle.state.gripper_pos
    is None but joint_pos has 6 elements. Use index 5 as gripper."""
    bundle = _bundle([1.0, 2.0, 3.0, 4.0, 5.0, 99.0], None,
                     [0.1, 0.2, 0.3, 0.4, 0.5, 88.0], None)
    row = sample_bundle_to_row(bundle, 1_000_000_000, instruction="x", fk_n_kin_joints=5)
    assert row["observation.state"][-1] == 99.0
    assert row["action"][-1] == 88.0
```

- [ ] **Step 2: Delete EE-preference test**

```
git rm tests/unit/test_parquet_row_ee_pref.py
```

(That test asserts on `observation.state.ee_pos` columns which no longer exist.)

- [ ] **Step 3: Verify fail**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_parquet_row.py -v
```

Expected: every test fails (current `sample_bundle_to_row` returns the verbose schema).

- [ ] **Step 4: Rewrite implementation**

Replace `backend/mimicrec/recording/parquet_row.py`:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

import numpy as np

from mimicrec.types import SampleBundle

if TYPE_CHECKING:
    pass


def sample_bundle_to_row(
    bundle: SampleBundle,
    episode_start_t_mono_ns: int,
    *,
    instruction: str,
    fk_n_kin_joints: int | None = None,
    frame_index: int = 0,
    episode_index: int = 0,
    global_index: int = 0,
    task_index: int = 0,
) -> dict:
    s = bundle.state.value
    Narm = fk_n_kin_joints if fk_n_kin_joints is not None else s.joint_pos.shape[0]
    obs_arm = s.joint_pos[:Narm]
    if s.gripper_pos is not None:
        obs_grip = float(s.gripper_pos)
    elif s.joint_pos.shape[0] > Narm:
        obs_grip = float(s.joint_pos[Narm])
    else:
        raise ValueError("missing gripper_pos and no slack joint to derive from")
    observation_state = np.concatenate([obs_arm, [obs_grip]]).astype(np.float32)

    a_arm = bundle.action.q[:Narm]
    if bundle.action.gripper is not None:
        a_grip = float(bundle.action.gripper)
    elif bundle.action.q.shape[0] > Narm:
        a_grip = float(bundle.action.q[Narm])
    else:
        raise ValueError("missing action.gripper and no slack joint to derive from")
    action = np.concatenate([a_arm, [a_grip]]).astype(np.float32)

    return {
        "action": action,
        "observation.state": observation_state,
        "language_instruction": instruction,
        "timestamp": 0.0,  # rewritten in pending.save()
        "frame_index": frame_index,
        "episode_index": episode_index,
        "index": global_index,  # rewritten in pending.save()
        "task_index": task_index,
    }
```

- [ ] **Step 5: Verify pass**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_parquet_row.py -v
```

Expected: all 7 pass.

- [ ] **Step 6: Commit**

```
git add backend/mimicrec/recording/parquet_row.py tests/unit/test_parquet_row.py tests/unit/test_parquet_row_ee_pref.py
git commit -m "feat(parquet_row): emit packed v3-native 8-column schema"
```

---

### Task 9: `writer.run_writer` plumbs `instruction_provider`

**Files:**
- Modify: `backend/mimicrec/recording/writer.py:16-23, 57-65`
- Modify: `backend/mimicrec/session/lifecycle.py:322-328` (and wherever `episode_start` resolves the instruction)
- Test: `tests/unit/test_writer_instruction_propagation.py` (new)

- [ ] **Step 1: Add failing test**

Create `tests/unit/test_writer_instruction_propagation.py`:

```python
"""Writer must call sample_bundle_to_row with the instruction_provider's
current value, so each row carries the correct language_instruction."""
import asyncio
import numpy as np
from unittest.mock import MagicMock, patch

from mimicrec.recording.writer import run_writer
from mimicrec.types import RobotState, RobotCommand, SampleBundle, Stamped
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


def _bundle(t):
    return SampleBundle(
        tick_t_mono_ns=t,
        state=Stamped(RobotState(
            joint_pos=np.zeros(5, dtype=np.float32),
            joint_vel=np.zeros(5, dtype=np.float32),
            joint_effort=np.zeros(5, dtype=np.float32),
            gripper_pos=0.0,
        ), t_mono_ns=t),
        action=RobotCommand(q=np.zeros(5, dtype=np.float32), gripper=0.0, t_mono_ns=t),
        frames={},
    )


def test_run_writer_passes_instruction_to_row():
    pending = MagicMock()
    pending.episode_index = 0
    pending.append_row = MagicMock()

    current = LatestValue()
    current.set(pending, t_mono_ns=1)
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(_bundle(1_000_000_000))
    stopped = asyncio.Event()

    captured: list[dict] = []
    def fake_row(*args, **kwargs):
        captured.append(kwargs)
        return {}
    async def _drive():
        with patch("mimicrec.recording.writer.sample_bundle_to_row", side_effect=fake_row):
            task = asyncio.create_task(run_writer(
                current_pending=current, queue=queue, metrics=Metrics(),
                stopped=stopped, instruction_provider=lambda: "pick the block",
            ))
            await asyncio.sleep(0.1)
            stopped.set()
            await asyncio.wait_for(task, timeout=1.0)

    asyncio.get_event_loop().run_until_complete(_drive())
    assert captured and captured[0].get("instruction") == "pick the block"
```

- [ ] **Step 2: Verify fail**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_writer_instruction_propagation.py -v
```

Expected: `TypeError: run_writer() got an unexpected keyword argument 'instruction_provider'`.

- [ ] **Step 3: Implement writer change**

Edit `backend/mimicrec/recording/writer.py`:

```python
async def run_writer(
    current_pending: LatestValue,
    queue: asyncio.Queue,
    metrics: Metrics,
    stopped: asyncio.Event,
    instruction_provider: Callable[[], str],
    fk: "FKService | None" = None,
) -> None:
    ...
    row = sample_bundle_to_row(
        bundle,
        episode_start_t_mono_ns,
        instruction=instruction_provider(),
        fk_n_kin_joints=(fk.n_kin_joints if fk is not None else None),
        frame_index=frame_counter,
        episode_index=pending.episode_index,
        global_index=0,
        task_index=0,
    )
    ...
```

(Add `from typing import Callable` at the top.)

- [ ] **Step 4: Update lifecycle to provide instruction**

The lifecycle already stores the instruction at `self._instruction` (set from the API caller in `__init__`, lines 75-88). Pass it directly:

Edit `backend/mimicrec/session/lifecycle.py:322-328`:

```python
self._writer_task = asyncio.create_task(run_writer(
    current_pending=self._current_pending,
    queue=self._recorder_queue,
    metrics=self._metrics,
    stopped=self.session.stopped,
    instruction_provider=lambda: self._instruction or "",
    fk=self._fk,
))
```

No new instance attributes or methods needed. (If `self._instruction` is empty, the row gets `""` — consistent with falling back to "no instruction".)

- [ ] **Step 5: Verify pass + suite**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/ -q
```

Several tests under `tests/unit/test_pending_episode.py` and integration tests will need updating because their fake `_make_row()` helpers built the old verbose schema. Update those helpers to produce the new 8-column dict shape (or have them call `sample_bundle_to_row`).

- [ ] **Step 6: Commit**

```
git add backend/mimicrec/recording/writer.py backend/mimicrec/session/lifecycle.py tests/unit/test_writer_instruction_propagation.py tests/unit/test_pending_episode.py
git commit -m "feat(writer): instruction_provider closure for per-episode language_instruction"
```

---

## Phase 5 — Replay reader

### Task 10: `reader.load_replay_trajectory` reads packed action

**Files:**
- Modify: `backend/mimicrec/datasets/reader.py:12-55`
- Test: `tests/unit/test_dataset_reader_packed_action.py` (new)
- Modify: `tests/unit/test_dataset_reader_tombstones.py` (data fixture: switch to packed schema)

- [ ] **Step 1: Add failing test**

Create `tests/unit/test_dataset_reader_packed_action.py`:

```python
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.datasets.reader import load_replay_trajectory


def test_load_replay_trajectory_splits_packed_action(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1","j2","j3","j4","j5"], camera_names=[])

    p = dataset_paths(ds)
    p.chunk_dir(0).mkdir(parents=True, exist_ok=True)
    n = 4
    table = pa.table({
        "action": pa.array(
            [[0.1, 0.2, 0.3, 0.4, 0.5, 50.0]] * n,
            type=pa.list_(pa.float32(), 6),
        ),
        "observation.state": pa.array(
            [[0.0]*6] * n, type=pa.list_(pa.float32(), 6),
        ),
        "language_instruction": pa.array(["x"]*n, type=pa.string()),
        "timestamp": pa.array([i/30 for i in range(n)], type=pa.float32()),
        "frame_index": pa.array(list(range(n)), type=pa.int64()),
        "episode_index": pa.array([0]*n, type=pa.int64()),
        "index": pa.array(list(range(n)), type=pa.int64()),
        "task_index": pa.array([0]*n, type=pa.int64()),
    })
    pq.write_table(table, p.episode_parquet(0, 0))

    # Episode metadata so reader can find the parquet
    from mimicrec.recording.metadata import append_episode
    append_episode(p.meta_dir, {"episode_index": 0, "task": "x", "num_frames": n,
                                "cameras": [], "fps": 30, "duration_sec": n/30})

    traj = load_replay_trajectory(ds, episode_idx=0)
    assert traj.joint_targets.shape == (n, 5)
    np.testing.assert_allclose(traj.joint_targets[0], [0.1, 0.2, 0.3, 0.4, 0.5])
    assert traj.gripper_targets is not None
    assert traj.gripper_targets.shape == (n,)
    np.testing.assert_allclose(traj.gripper_targets, [50.0]*n)
```

- [ ] **Step 2: Verify fail**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_dataset_reader_packed_action.py -v
```

Expected: `KeyError: 'action.joint_pos'` — current reader expects the verbose schema.

- [ ] **Step 3: Implement**

Replace the joint/gripper extraction in `load_replay_trajectory`:

```python
table = pq.read_table(parquet)
action_col = np.array(table.column("action").to_pylist(), dtype=np.float32)  # (n, N)
joint_targets = action_col[:, :-1]
gripper_targets = action_col[:, -1].astype(np.float32)
```

Remove the legacy fallback branch (`elif joint_pos.shape[1] > 6:`) — old data is discarded.

- [ ] **Step 4: Update tombstone test fixture**

In `tests/unit/test_dataset_reader_tombstones.py`, the synthetic parquet helper currently writes the verbose schema. Update to the packed 8-column schema (model after the new `test_dataset_reader_packed_action.py` fixture).

- [ ] **Step 5: Verify pass + suite**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/ -q
```

- [ ] **Step 6: Commit**

```
git add backend/mimicrec/datasets/reader.py tests/unit/test_dataset_reader_packed_action.py tests/unit/test_dataset_reader_tombstones.py
git commit -m "feat(reader): load_replay_trajectory reads packed action column"
```

---

## Phase 6 — Cleanup (vla_compat removal)

### Task 11: Delete `exporters/` and the `/api/datasets/{ds}/export` POST endpoint

**Retained (do NOT delete):** `backend/mimicrec/datasets/archive.py` is the zip-streaming primitive. It does NOT live under `exporters/` and stays — the GET archive route depends on it. The `?format=` query param on that GET route is dropped along with `ExportFormat` (the route always streams the v3-native tree).

**Files:**
- Delete: `backend/mimicrec/datasets/exporters/vla_compat.py`
- Delete: `backend/mimicrec/datasets/exporters/info_json.py`
- Delete: `backend/mimicrec/datasets/exporters/instructions.py`
- Delete: `backend/mimicrec/datasets/exporters/stats.py`
- Delete: `backend/mimicrec/datasets/exporters/orchestrator.py`
- Delete: `backend/mimicrec/datasets/exporters/errors.py`
- Delete: `backend/mimicrec/datasets/exporters/__init__.py` (and the directory itself if empty)
- Delete: `tests/unit/test_exporter_vla_compat.py`
- Delete: `tests/unit/test_exporter_info_json.py`
- Delete: `tests/unit/test_exporter_instructions.py`
- Delete: `tests/unit/test_exporter_stats.py`
- Delete: `tests/unit/test_exporter_orchestrator.py`
- Delete: `tests/integration/test_vla_compat_roundtrip.py`
- Delete: `tests/api/test_export_routes.py` (entire file — exercises the removed POST endpoint)
- Modify: `backend/mimicrec/api/schemas.py` (drop `ExportFormat`, `ExportRequest`, `ExportResponse`, `DEFAULT_INSTRUCTION_TEMPLATE`)
- Modify: `backend/mimicrec/api/routes/datasets.py` (drop `export_dataset` POST handler + imports; drop the `?format=vla_compat → 400` branch in the GET archive handler at lines 170-174 along with the `format` query param)
- Modify: `backend/mimicrec/api/deps.py` (drop `get_vla_dest_root`)
- Modify: `tests/api/test_dataset_routes.py` (drop `test_archive_with_vla_compat_format_returns_400` at line 139, plus any other vla_compat-format expectations)
- Modify: `tests/api/conftest.py` (drop any `MIMICREC_VLA_DEST_ROOT` fixtures / monkeypatches if present — `grep MIMICREC_VLA_DEST_ROOT tests/`)

- [ ] **Step 1: Inventory removable references**

```
grep -rn "ExportFormat\|ExportRequest\|ExportResponse\|VLA_COMPAT\|vla_compat\|export_dataset_to_local\|DestinationExistsError\|get_vla_dest_root\|DEFAULT_INSTRUCTION_TEMPLATE" backend tests --include='*.py' | grep -v __pycache__
```

Note every hit. The list above should cover them; cross-check.

- [ ] **Step 2: Delete files**

```
git rm backend/mimicrec/datasets/exporters/vla_compat.py \
       backend/mimicrec/datasets/exporters/info_json.py \
       backend/mimicrec/datasets/exporters/instructions.py \
       backend/mimicrec/datasets/exporters/stats.py \
       backend/mimicrec/datasets/exporters/orchestrator.py \
       backend/mimicrec/datasets/exporters/errors.py \
       backend/mimicrec/datasets/exporters/__init__.py \
       tests/unit/test_exporter_vla_compat.py \
       tests/unit/test_exporter_info_json.py \
       tests/unit/test_exporter_instructions.py \
       tests/unit/test_exporter_stats.py \
       tests/unit/test_exporter_orchestrator.py \
       tests/integration/test_vla_compat_roundtrip.py \
       tests/api/test_export_routes.py
```

(`backend/mimicrec/datasets/archive.py` is preserved — that's the zip primitive.)

- [ ] **Step 3: Strip schemas**

Edit `backend/mimicrec/api/schemas.py`: remove `ExportFormat` enum, `ExportRequest`, `ExportResponse`, `DEFAULT_INSTRUCTION_TEMPLATE`. Leave `EpisodeSummary.task_index` alone (it's unrelated).

- [ ] **Step 4: Strip route**

Edit `backend/mimicrec/api/routes/datasets.py`:
1. Delete the `export_dataset` POST handler and its imports (`export_dataset_to_local`, `DestinationExistsError`, `ExportRequest`, `ExportResponse`, `ExportFormat`).
2. In the GET archive handler, delete the `format: ExportFormat = ...` query param and the `?format=vla_compat → HTTPException(400)` branch (lines 170-174). The route now always streams `lerobot_v3_native`.

`backend/mimicrec/datasets/archive.py` (the underlying `build_archive_stream` primitive) is unchanged.

- [ ] **Step 5: Strip deps**

Edit `backend/mimicrec/api/deps.py`: remove `get_vla_dest_root` and any `MIMICREC_VLA_DEST_ROOT` env var handling. Then verify nothing else references it:

```
grep -rn "MIMICREC_VLA_DEST_ROOT\|get_vla_dest_root" backend tests --include='*.py'
```

Should return zero hits. Update / drop any test fixtures that monkeypatch the env var.

- [ ] **Step 6: Update API tests**

Edit `tests/api/test_dataset_routes.py`:
- Drop `test_archive_with_vla_compat_format_returns_400` (line 139) and any other test that asserts on the dropped `?format=` behavior.
- Keep tests for the GET archive endpoint (the default v3-native stream).
- Drop any tests that import `ExportFormat` / `ExportRequest` / `ExportResponse`.

`tests/api/test_export_routes.py` is deleted whole in Step 2.

- [ ] **Step 7: Verify suite**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/ -q
```

Expected: full suite green. If any reference still slips through, fix it now.

- [ ] **Step 8: Commit**

```
git add -A
git commit -m "refactor: remove vla_compat exporter, /export POST endpoint, related tests"
```

---

### Task 12: Remove `ExportDatasetModal` from frontend

**Files:**
- Delete: `frontend/src/components/ExportDatasetModal.tsx` (and any sibling `.test.tsx`/`.css`)
- Modify: `frontend/src/api/types.ts` (drop `ExportFormat`)
- Modify: `frontend/src/api/queries.ts` (drop `useExportDataset`)
- Modify: `frontend/src/pages/DatasetsPage.tsx` (or wherever the Export button is rendered) — restore plain "Download" anchor pointing at the existing `archive` GET endpoint

- [ ] **Step 1: Inventory**

```
grep -rn "ExportDatasetModal\|useExportDataset\|ExportFormat" frontend/src
```

- [ ] **Step 2: Delete component**

```
git rm frontend/src/components/ExportDatasetModal.tsx
```

(If a test or stylesheet sits beside it, remove those too.)

- [ ] **Step 3: Trim queries / types**

Edit `frontend/src/api/queries.ts`: delete the `useExportDataset` mutation hook.
Edit `frontend/src/api/types.ts`: delete the `ExportFormat` type.

- [ ] **Step 4: Restore Download link in DatasetsPage**

In `DatasetsPage.tsx`, replace whatever button opens `ExportDatasetModal` with an anchor:

```tsx
<a href={`/api/datasets/${ds.name}/archive`} download>
  Download
</a>
```

(Or follow whatever URL helper the rest of the page uses.)

- [ ] **Step 5: Build & smoke check**

```
cd frontend && npm run typecheck && npm run build
```

- [ ] **Step 6: Commit**

```
git add -A
git commit -m "refactor(frontend): remove ExportDatasetModal; Datasets page uses zip download directly"
```

---

## Phase 7 — End-to-end verification

### Task 13: LeRobotDataset roundtrip integration test

**Files:**
- Create: `tests/integration/test_lerobot_roundtrip.py`

- [ ] **Step 1: Write the test**

```python
"""Record one mock episode end-to-end and verify LeRobotDataset can construct
its catalog from the resulting tree (no CastError). Skips if lerobot isn't
importable in this environment."""
from pathlib import Path
import numpy as np
import pytest


def test_recording_loads_in_lerobot_dataset(tmp_path: Path):
    pytest.importorskip("lerobot")
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    from mimicrec.recording.dataset_layout import init_dataset
    from mimicrec.recording.pending import PendingEpisode
    from mimicrec.recording.metadata import upsert_task
    from mimicrec.recording.parquet_row import sample_bundle_to_row
    from mimicrec.types import RobotState, RobotCommand, SampleBundle, Stamped

    ds = tmp_path / "ds"
    fps = 15
    init_dataset(ds, fps=fps, joint_names=["j1","j2","j3","j4","j5"], camera_names=["front"])
    upsert_task(ds / "meta", "pick", "pick the block")

    pe = PendingEpisode.open(ds, episode_index=0)
    pe.open_video_writers(fps=fps, cameras={"front": (64, 48)})
    n = 10
    for i in range(n):
        pe._video_writers["front"].write_frame(np.zeros((48, 64, 3), dtype=np.uint8))
        bundle = SampleBundle(
            tick_t_mono_ns=int(i * 1e9 / fps),
            state=Stamped(RobotState(
                joint_pos=np.zeros(5, dtype=np.float32),
                joint_vel=np.zeros(5, dtype=np.float32),
                joint_effort=np.zeros(5, dtype=np.float32),
                gripper_pos=0.0,
            ), t_mono_ns=int(i * 1e9 / fps)),
            action=RobotCommand(q=np.zeros(5, dtype=np.float32), gripper=0.0,
                                t_mono_ns=int(i * 1e9 / fps)),
            frames={},
        )
        row = sample_bundle_to_row(bundle, 0, instruction="pick the block",
                                   frame_index=i, episode_index=0)
        pe.append_row(row)
    pe.finalize()
    pe.save(metadata_extra={
        "episode_index": 0, "task": "pick", "instruction": "pick the block",
        "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
        "cameras": ["front"], "mode": "teleop", "fps": fps,
        "success": None, "comment": None,
        "start_t_mono_ns": 0, "end_t_mono_ns": int(n * 1e9 / fps),
        "duration_sec": n / fps, "num_frames": n,
        "session_boot_t_unix": 0, "session_boot_t_mono_ns": 0,
        "resolved_config": {},
    })

    lds = LeRobotDataset("local/mock", root=str(ds), episodes=[0], download_videos=False)
    assert lds.num_episodes == 1
```

- [ ] **Step 2: Run**

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/integration/test_lerobot_roundtrip.py -v
```

Expected: PASS (or SKIP if lerobot is not importable in CI env).

- [ ] **Step 3: Commit**

```
git add tests/integration/test_lerobot_roundtrip.py
git commit -m "test(integration): LeRobotDataset roundtrip on packed v3-native recording"
```

---

## Acceptance gate

- [ ] `env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/ -q` → all green
- [ ] `find backend/mimicrec/datasets/exporters` returns nothing (or `__init__.py` only if intentionally kept)
- [ ] `grep -r "vla_compat\|ExportFormat\|VLA_COMPAT" backend frontend tests --include='*.py' --include='*.ts' --include='*.tsx'` returns nothing
- [ ] Recording one mock episode + manual verification:
  ```
  env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python tests/integration/test_lerobot_roundtrip.py
  ```
  produces a parquet with exactly 8 columns matching Section 4 of the spec.
- [ ] Manual hardware verification (out of scope for CI): SO-101 replay drives both arm and gripper correctly.

---

## Rollback plan

If a phase blocks beyond reasonable effort, the boundaries are clean:
- Phases 1-3 (types/adapter/dispatcher) can land independently — they're a strict prerequisite for the rest but don't change file formats.
- Phase 4 (parquet_row + writer) is the schema flip; revert this commit + Phase 5/6/7 to roll back to verbose-with-vla_compat.
- Phase 6 (deletion) is the cleanest rollback: `git revert` restores everything.

The 33 existing episodes are already discarded per user direction; no data migration to undo.
