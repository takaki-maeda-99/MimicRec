# VLA-Compat Export EE-Delta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the VLA-compat exporter so its action label is `[ee_delta(6, m + axis-angle rad, ee_local), gripper(1, [0,1])]` and `observation.state` is per-robot verbatim, derived from a declarative `ProprioLayout` exposed by each adapter, with stats files (mean/std + q01/q99 + proprio q01/q99) the future X-VLA-Adapter loader can consume.

**Architecture:** Pure functions in `vla_compat.py` consume `observation.state.ee_pos / ee_rotvec` (already in every recorded parquet via daemon-side FK) and per-robot adapter declarations (`GripperConvention`, `ProprioLayout`) read from `info.json`. The recording-session bootstrap is patched to write those adapter declarations into `info.json` so the exporter is self-contained. Backwards compat for the 240 existing episodes (whose `info.json` has `robot_type=unknown`) goes through an explicit request-body override — no silent default.

**Tech Stack:** Python 3.10+, uv, pyarrow, numpy, scipy (`Rotation`), pytest. Existing modules: `backend/mimicrec/{adapters,recording,datasets/exporters,api}/`. Spec at `docs/superpowers/specs/2026-05-06-vla-export-ee-delta-design.md`.

**Note on "request-body override" terminology:** the spec uses "CLI / `--robot-type`" loosely. This codebase has **no standalone export CLI binary** (verified: `scripts/` has no exporter entry point). The override surfaces as a `robot_type` field on the export route's JSON request body (Task 9). Operators invoke export via `POST /datasets/<name>/export`.

**Test-fixture impact warning:** Task 7 changes `convert_episode_table`'s required input columns and rejects `n < 2`. The existing `_seed_dataset` helper in `tests/unit/test_exporter_orchestrator.py` does NOT write `observation.state.ee_pos / ee_rotvec`, several existing tests pass `num_frames=1`, and `test_export_cleans_up_partial_on_mid_loop_failure` monkeypatches `convert_episode_table` with the OLD signature (`def flaky(*, table, instruction_text)`). Task 8 Step 8.1 updates `_seed_dataset` AND the `flaky` monkeypatch signature; orchestrator tests do not run successfully until Task 8.

---

## File Structure

**New files:**
- `backend/mimicrec/adapters/types.py` — `GripperConvention`, `ProprioLayout` dataclasses with `__post_init__` structural validation.
- `tests/unit/test_adapter_types.py` — validation rules.
- `tests/unit/test_recording_info_json.py` — recording-session bootstrap writes the new fields.

**Modified files:**
- `backend/mimicrec/adapters/so101.py` — add `default_gripper_convention()` and `proprio_layout()` classmethods.
- `backend/mimicrec/adapters/rebotarm_zmq.py` — same.
- `backend/mimicrec/recording/dataset_layout.py:init_dataset` — accept optional `gripper_convention_dict` / `proprio_layout_dict` and write them into `info.json` (replacing the current `robot_type: "unknown"` fixed string with the active adapter's class name).
- `backend/mimicrec/api/deps.py` — thread adapter info to `init_dataset`.
- `backend/mimicrec/api/routes/datasets.py` — same; expose request-body override for export route.
- `backend/mimicrec/api/schemas.py` — add export-route override fields.
- `backend/mimicrec/datasets/exporters/vla_compat.py` — full rewrite per spec §4.
- `backend/mimicrec/datasets/exporters/info_json.py` — rewrite per spec §5.
- `backend/mimicrec/datasets/exporters/stats.py` — triple-output `compute_stats` per spec §6.
- `backend/mimicrec/datasets/exporters/orchestrator.py:_export_vla_compat` — read convention/layout, derive `n_proprio`, write three stats files, support request-body override.

**Test files updated/replaced:**
- `tests/unit/test_exporter_vla_compat.py` — replace existing tests wholesale (the old joint-pos-action assertions no longer apply).
- `tests/unit/test_exporter_stats.py` — extend.
- `tests/unit/test_exporter_info_json.py` — extend.
- `tests/unit/test_exporter_orchestrator.py` — extend.
- `tests/unit/test_rebotarm_adapter.py` — extend with gripper convention / proprio layout tests.
- `tests/integration/test_vla_compat_roundtrip.py` — replace with both-robot fixtures + short-episode boundary.

**Docs:**
- `configs/inference/README.md` — short note about the `robot_type` request-body override for legacy datasets.

---

## Task 1: Adapter types module (`GripperConvention` + `ProprioLayout`)

**Files:**
- Create: `backend/mimicrec/adapters/types.py`
- Create: `tests/unit/test_adapter_types.py`

- [ ] **Step 1.1: Write failing tests for `GripperConvention.__post_init__` and `ProprioLayout.__post_init__`**

Create `tests/unit/test_adapter_types.py`:

```python
import pytest

from mimicrec.adapters.types import GripperConvention, ProprioLayout


def test_gripper_convention_zero_span_raises():
    with pytest.raises(ValueError, match="zero span"):
        GripperConvention(closed_at=42.0, open_at=42.0)


def test_gripper_convention_normal_span_ok():
    c = GripperConvention(closed_at=0.0, open_at=100.0)
    assert c.closed_at == 0.0 and c.open_at == 100.0


def test_gripper_convention_inverted_span_ok():
    # reBot has closed_at > open_at — must be allowed.
    c = GripperConvention(closed_at=1.0, open_at=0.0)
    assert c.closed_at == 1.0 and c.open_at == 0.0


def test_proprio_layout_gripper_via_column_must_be_in_columns():
    with pytest.raises(ValueError, match="not in columns"):
        ProprioLayout(
            columns=("observation.state.joint_pos",),
            output_names=("a", "b"),
            gripper_via_column="observation.state.gripper_pos",
            gripper_index_in_column=0,
        )


def test_proprio_layout_gripper_index_must_be_non_negative():
    with pytest.raises(ValueError, match="must be >= 0"):
        ProprioLayout(
            columns=("observation.state.joint_pos",),
            output_names=("a",),
            gripper_via_column="observation.state.joint_pos",
            gripper_index_in_column=-1,
        )


def test_proprio_layout_minimal_valid():
    p = ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("shoulder_pan",),
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=0,
    )
    assert p.columns == ("observation.state.joint_pos",)
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_adapter_types.py -v`
Expected: ImportError / ModuleNotFoundError because `mimicrec.adapters.types` does not exist yet.

- [ ] **Step 1.3: Implement `backend/mimicrec/adapters/types.py`**

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GripperConvention:
    """Per-robot raw-gripper → unit-gripper [0,1] mapping declaration.

    Forward map: action_gripper = clip((raw - closed_at) / (open_at - closed_at), 0, 1).
    Works for both closed_at < open_at (SO-101) and closed_at > open_at (reBot).
    """
    closed_at: float
    open_at: float

    def __post_init__(self):
        if abs(self.open_at - self.closed_at) < 1e-9:
            raise ValueError(f"GripperConvention has zero span: {self}")


@dataclass(frozen=True)
class ProprioLayout:
    """Declarative composition for observation.state at export time.

    `columns` is the ordered tuple of parquet column names whose values are
    concatenated row-by-row to form observation.state.

    `output_names` is the full per-dim name list for the resulting vector,
    in concat order. Length agreement with the actual concat dim is
    validated at runtime in _build_observation_state (cannot be checked
    here because list-column widths come from parquet data).

    `gripper_via_column` and `gripper_index_in_column` locate the raw
    gripper value the action label normalizes from. For SO-101 the gripper
    is at joint_pos[5] (offset 5 of the joint_pos list). For reBot it is
    the only entry of the scalar gripper_pos column (offset 0).
    """
    columns: tuple[str, ...]
    output_names: tuple[str, ...]
    gripper_via_column: str
    gripper_index_in_column: int

    def __post_init__(self):
        if self.gripper_via_column not in self.columns:
            raise ValueError(
                f"gripper_via_column {self.gripper_via_column!r} not in columns {self.columns}"
            )
        if self.gripper_index_in_column < 0:
            raise ValueError(
                f"gripper_index_in_column must be >= 0, got {self.gripper_index_in_column}"
            )
```

- [ ] **Step 1.4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_adapter_types.py -v`
Expected: 6 PASSED.

- [ ] **Step 1.5: Commit**

```bash
git add backend/mimicrec/adapters/types.py tests/unit/test_adapter_types.py
git commit -m "$(cat <<'EOF'
feat(adapters): add GripperConvention and ProprioLayout types

Declarative per-robot gripper-normalization and proprio-composition
specs used by the upcoming VLA-compat exporter rewrite.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: SO-101 adapter classmethods

**Files:**
- Modify: `backend/mimicrec/adapters/so101.py`
- Create: `tests/unit/test_so101_adapter_proprio.py`

- [ ] **Step 2.1: Write failing test**

Create `tests/unit/test_so101_adapter_proprio.py`:

```python
from mimicrec.adapters.so101 import SO101Adapter
from mimicrec.adapters.types import GripperConvention, ProprioLayout


def test_so101_default_gripper_convention():
    c = SO101Adapter.default_gripper_convention()
    assert isinstance(c, GripperConvention)
    assert c.closed_at == 0.0
    assert c.open_at == 100.0


def test_so101_proprio_layout():
    layout = SO101Adapter.proprio_layout()
    assert isinstance(layout, ProprioLayout)
    assert layout.columns == ("observation.state.joint_pos",)
    assert layout.output_names == (
        "shoulder_pan", "shoulder_lift", "elbow_flex",
        "wrist_flex", "wrist_roll", "gripper",
    )
    assert layout.gripper_via_column == "observation.state.joint_pos"
    assert layout.gripper_index_in_column == 5
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_so101_adapter_proprio.py -v`
Expected: AttributeError — methods don't exist yet.

- [ ] **Step 2.3: Add classmethods to `backend/mimicrec/adapters/so101.py`**

Add these imports near the top (after existing imports):

```python
from mimicrec.adapters.types import GripperConvention, ProprioLayout
```

Add these classmethods to `SO101Adapter` class (place them just below the class docstring or above `__init__`):

```python
    @classmethod
    def default_gripper_convention(cls) -> GripperConvention:
        """SO-101 gripper raw range: lerobot RANGE_0_100, 0=closed, 100=open."""
        return GripperConvention(closed_at=0.0, open_at=100.0)

    @classmethod
    def proprio_layout(cls) -> ProprioLayout:
        """SO-101's joint_pos already includes the packed gripper at index 5;
        no separate column needs concatenation."""
        return ProprioLayout(
            columns=("observation.state.joint_pos",),
            output_names=(
                "shoulder_pan", "shoulder_lift", "elbow_flex",
                "wrist_flex", "wrist_roll", "gripper",
            ),
            gripper_via_column="observation.state.joint_pos",
            gripper_index_in_column=5,
        )
```

- [ ] **Step 2.4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_so101_adapter_proprio.py -v`
Expected: 2 PASSED.

- [ ] **Step 2.5: Commit**

```bash
git add backend/mimicrec/adapters/so101.py tests/unit/test_so101_adapter_proprio.py
git commit -m "$(cat <<'EOF'
feat(adapters): SO101Adapter declares gripper convention + proprio layout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: reBot adapter classmethods

**Files:**
- Modify: `backend/mimicrec/adapters/rebotarm_zmq.py`
- Create: `tests/unit/test_rebotarm_adapter_proprio.py`

- [ ] **Step 3.1: Write failing test**

Create `tests/unit/test_rebotarm_adapter_proprio.py`:

```python
from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter
from mimicrec.adapters.types import GripperConvention, ProprioLayout


def test_rebot_default_gripper_convention():
    c = ReBotArmZmqAdapter.default_gripper_convention()
    assert isinstance(c, GripperConvention)
    # Inferred from configs/mapper/so_to_rebotarm_ee.yaml:
    # gripper_invert=true + out_min/max=0/1 → 1=closed, 0=open
    assert c.closed_at == 1.0
    assert c.open_at == 0.0


def test_rebot_proprio_layout():
    layout = ReBotArmZmqAdapter.proprio_layout()
    assert isinstance(layout, ProprioLayout)
    assert layout.columns == (
        "observation.state.joint_pos",
        "observation.state.gripper_pos",
    )
    # NOTE: 'join3' (no 't') intentional — reBotArm URDF spells it as 'join3'.
    assert layout.output_names == (
        "joint1", "joint2", "join3", "joint4", "joint5", "joint6", "gripper",
    )
    assert layout.gripper_via_column == "observation.state.gripper_pos"
    assert layout.gripper_index_in_column == 0
```

- [ ] **Step 3.2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_rebotarm_adapter_proprio.py -v`
Expected: AttributeError.

- [ ] **Step 3.3: Add classmethods to `backend/mimicrec/adapters/rebotarm_zmq.py`**

Add the import:

```python
from mimicrec.adapters.types import GripperConvention, ProprioLayout
```

Add classmethods to `ReBotArmZmqAdapter`:

```python
    @classmethod
    def default_gripper_convention(cls) -> GripperConvention:
        """Inferred from configs/mapper/so_to_rebotarm_ee.yaml:
        gripper_invert=true + out_min/max=0/1 → 1=closed, 0=open. This is
        a default; future per-session calibration override would replace it.
        """
        return GripperConvention(closed_at=1.0, open_at=0.0)

    @classmethod
    def proprio_layout(cls) -> ProprioLayout:
        """reBot stores arm joints in joint_pos (6-dim) and the gripper as a
        separate scalar gripper_pos column.

        NOTE: `join3` (no `t`) intentional — reBotArm URDF spells joint3 as
        `join3` upstream (tracked in configs/mapper/so_to_rebotarm_ee.yaml:12).
        """
        return ProprioLayout(
            columns=(
                "observation.state.joint_pos",
                "observation.state.gripper_pos",
            ),
            output_names=(
                "joint1", "joint2", "join3", "joint4", "joint5", "joint6", "gripper",
            ),
            gripper_via_column="observation.state.gripper_pos",
            gripper_index_in_column=0,
        )
```

- [ ] **Step 3.4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_rebotarm_adapter_proprio.py -v`
Expected: 2 PASSED.

- [ ] **Step 3.5: Commit**

```bash
git add backend/mimicrec/adapters/rebotarm_zmq.py tests/unit/test_rebotarm_adapter_proprio.py
git commit -m "$(cat <<'EOF'
feat(adapters): ReBotArmZmqAdapter declares gripper convention + proprio layout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Recording-session bootstrap writes adapter declarations to `info.json`

**Files:**
- Modify: `backend/mimicrec/recording/dataset_layout.py:init_dataset`
- Modify: `backend/mimicrec/api/deps.py:144` (caller)
- Modify: `backend/mimicrec/api/routes/datasets.py:65` (caller)
- Create: `tests/unit/test_recording_info_json.py`

- [ ] **Step 4.1: Write failing test**

Create `tests/unit/test_recording_info_json.py`:

```python
import json
from pathlib import Path

from mimicrec.recording.dataset_layout import init_dataset


def test_init_dataset_writes_robot_type_when_provided(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
        robot_type="SO101Adapter",
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert info["robot_type"] == "SO101Adapter"


def test_init_dataset_falls_back_to_unknown(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert info["robot_type"] == "unknown"


def test_init_dataset_writes_gripper_convention(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
        robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert info["gripper_convention"] == {"closed_at": 0.0, "open_at": 100.0}


def test_init_dataset_writes_proprio_layout(tmp_path):
    layout = {
        "columns": ["observation.state.joint_pos"],
        "output_names": ["shoulder_pan", "gripper"],
        "gripper_via_column": "observation.state.joint_pos",
        "gripper_index_in_column": 1,
    }
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
        robot_type="SO101Adapter",
        proprio_layout=layout,
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert info["proprio_layout"] == layout


def test_init_dataset_omits_optional_fields_when_not_supplied(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert "gripper_convention" not in info
    assert "proprio_layout" not in info
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_recording_info_json.py -v`
Expected: TypeError — `init_dataset` does not accept `robot_type` / `gripper_convention` / `proprio_layout` kwargs.

- [ ] **Step 4.3: Modify `init_dataset` signature in `backend/mimicrec/recording/dataset_layout.py`**

Replace the `init_dataset` function signature and body:

```python
def init_dataset(
    ds_root: Path,
    fps: int,
    joint_names: list[str],
    camera_names: list[str],
    *,
    robot_type: str | None = None,
    gripper_convention: dict | None = None,
    proprio_layout: dict | None = None,
) -> None:
    p = dataset_paths(ds_root)
    p.meta_dir.mkdir(parents=True, exist_ok=True)
    p.data_dir.mkdir(parents=True, exist_ok=True)
    p.videos_dir.mkdir(parents=True, exist_ok=True)
    p.episodes_dir.mkdir(parents=True, exist_ok=True)

    # (existing features dict construction unchanged) ...
    dof = len(joint_names)
    features = {}
    if dof > 0:
        features["action"] = {"dtype": "float32", "shape": [dof], "names": joint_names}
        features["observation.state"] = {"dtype": "float32", "shape": [dof], "names": joint_names}
    features["timestamp"] = {"dtype": "float32", "shape": [1], "names": None}
    features["frame_index"] = {"dtype": "int64", "shape": [1], "names": None}
    features["episode_index"] = {"dtype": "int64", "shape": [1], "names": None}
    features["index"] = {"dtype": "int64", "shape": [1], "names": None}
    features["task_index"] = {"dtype": "int64", "shape": [1], "names": None}

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

    info: dict = {
        "codebase_version": "v3.0",
        "robot_type": robot_type if robot_type is not None else "unknown",
        "total_episodes": 0,
        "total_frames": 0,
        "total_tasks": 0,
        "chunks_size": 1000,
        "data_files_size_in_mb": 0,
        "video_files_size_in_mb": 0,
        "fps": fps,
        "splits": {"train": "0:0"},
        "data_path": "data/chunk-{chunk_index:03d}/episode_{file_index:06d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{file_index:06d}.mp4",
        "features": features,
    }
    if gripper_convention is not None:
        info["gripper_convention"] = gripper_convention
    if proprio_layout is not None:
        info["proprio_layout"] = proprio_layout

    (p.meta_dir / "info.json").write_text(json.dumps(info, indent=2))

    # tasks.parquet write — unchanged
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = pa.schema([
        ("task", pa.string()),
        ("task_index", pa.int64()),
        ("instruction", pa.string()),
    ])
    pq.write_table(pa.table({"task": [], "task_index": [], "instruction": []}, schema=schema), p.tasks_parquet)
```

- [ ] **Step 4.4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_recording_info_json.py -v`
Expected: 5 PASSED.

- [ ] **Step 4.5: Update callers in `backend/mimicrec/api/deps.py:144` and `backend/mimicrec/api/routes/datasets.py:65`**

In `backend/mimicrec/api/deps.py`, replace the `init_dataset(...)` call with:

```python
        # Capture per-adapter declarations if available (None for mock adapters).
        rt = type(robot).__name__
        gc = (
            robot.default_gripper_convention()
            if hasattr(robot, "default_gripper_convention") else None
        )
        pl = (
            robot.proprio_layout()
            if hasattr(robot, "proprio_layout") else None
        )
        init_dataset(
            ds_root, fps=req.fps,
            joint_names=robot.joint_names,
            camera_names=list(req.cameras),
            robot_type=rt,
            gripper_convention=(
                {"closed_at": gc.closed_at, "open_at": gc.open_at} if gc else None
            ),
            proprio_layout=(
                {
                    "columns": list(pl.columns),
                    "output_names": list(pl.output_names),
                    "gripper_via_column": pl.gripper_via_column,
                    "gripper_index_in_column": pl.gripper_index_in_column,
                } if pl else None
            ),
        )
```

In `backend/mimicrec/api/routes/datasets.py:65`, the existing `init_dataset(ds_root, fps=body.fps, joint_names=body.joint_names, camera_names=body.camera_names)` call has no adapter context (it's a "create empty dataset" route used for tests / manual setup), so leave it as-is — it will write `robot_type: "unknown"` and the exporter's request-body override path covers re-export.

- [ ] **Step 4.6: Run full test suite to confirm no regressions**

Run: `.venv/bin/pytest tests/unit/test_recording_info_json.py tests/unit/test_so101_adapter_proprio.py tests/unit/test_rebotarm_adapter_proprio.py tests/unit/test_adapter_types.py -v`
Expected: ALL PASS.

- [ ] **Step 4.7: Commit**

```bash
git add backend/mimicrec/recording/dataset_layout.py backend/mimicrec/api/deps.py tests/unit/test_recording_info_json.py
git commit -m "$(cat <<'EOF'
feat(recording): write adapter gripper_convention/proprio_layout into info.json

init_dataset now accepts optional robot_type, gripper_convention, and
proprio_layout kwargs. The api/deps.py session-start path threads through
the active adapter so fresh datasets carry self-contained metadata for
the upcoming exporter rewrite. The /datasets create route (no adapter
context) still writes robot_type=unknown; export-time request-body override
covers it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Refactor `stats.py` to triple output

**Files:**
- Modify: `backend/mimicrec/datasets/exporters/stats.py`
- Modify: `tests/unit/test_exporter_stats.py`

- [ ] **Step 5.1: Replace tests in `tests/unit/test_exporter_stats.py`**

Read the existing file first to preserve any unrelated tests (run `.venv/bin/cat tests/unit/test_exporter_stats.py` if needed). Then replace the file contents with:

```python
import numpy as np
import pyarrow as pa

from mimicrec.datasets.exporters.stats import compute_stats


def _table(actions: list[list[float]], proprios: list[list[float]]) -> pa.Table:
    return pa.table({
        "action": pa.array(actions, type=pa.list_(pa.float32(), len(actions[0]))),
        "observation.state": pa.array(
            proprios, type=pa.list_(pa.float32(), len(proprios[0])),
        ),
    })


def _seven(action: list[float]) -> list[float]:
    assert len(action) == 7
    return action


def test_compute_stats_returns_three_blocks():
    actions = [[0.0]*7, [1.0]*7]
    proprios = [[0.0]*6, [1.0]*6]
    a_stats, a_q99, p_q99 = compute_stats([_table(actions, proprios)])
    assert "mean" in a_stats and "std" in a_stats and "convention" in a_stats
    assert "q01" in a_q99 and "q99" in a_q99 and "mask" in a_q99
    assert "q01" in p_q99 and "q99" in p_q99 and "mask" in p_q99


def test_action_stats_carries_convention_field():
    a_stats, _, _ = compute_stats([_table([[0.0]*7, [1.0]*7], [[0.0]*6])])
    assert a_stats["convention"] == "q99_derived_midpoint_halfrange"


def test_action_stats_mean_equals_midpoint_of_action_q99():
    rng = np.random.default_rng(0)
    actions = rng.normal(size=(200, 7)).tolist()
    a_stats, a_q99, _ = compute_stats([_table(actions, [[0.0]*6 for _ in actions])])
    midpoint = [(a + b) / 2 for a, b in zip(a_q99["q01"], a_q99["q99"])]
    np.testing.assert_allclose(a_stats["mean"], midpoint, atol=1e-9)


def test_action_stats_std_equals_half_range_of_action_q99():
    rng = np.random.default_rng(1)
    actions = rng.normal(size=(200, 7)).tolist()
    a_stats, a_q99, _ = compute_stats([_table(actions, [[0.0]*6 for _ in actions])])
    half_range = [max((b - a) / 2, 1e-6) for a, b in zip(a_q99["q01"], a_q99["q99"])]
    np.testing.assert_allclose(a_stats["std"], half_range, atol=1e-9)


def test_action_q99_mask_all_true_for_seven_dim_action():
    _, a_q99, _ = compute_stats([_table([[0.0]*7, [1.0]*7], [[0.0]*6])])
    assert a_q99["mask"] == [True] * 7


def test_proprio_q99_length_matches_per_robot_dim():
    rng = np.random.default_rng(2)
    proprios_so101 = rng.normal(size=(50, 6)).tolist()
    proprios_rebot = rng.normal(size=(50, 7)).tolist()
    actions = [[0.0]*7] * 50

    _, _, p_so101 = compute_stats([_table(actions, proprios_so101)])
    _, _, p_rebot = compute_stats([_table(actions, proprios_rebot)])
    assert len(p_so101["q01"]) == 6
    assert len(p_rebot["q01"]) == 7


def test_compute_stats_raises_on_no_rows():
    import pytest
    empty = pa.table({
        "action": pa.array([], type=pa.list_(pa.float32(), 7)),
        "observation.state": pa.array([], type=pa.list_(pa.float32(), 6)),
    })
    with pytest.raises(ValueError, match="no rows"):
        compute_stats([empty])
```

- [ ] **Step 5.2: Run test to verify failure**

Run: `.venv/bin/pytest tests/unit/test_exporter_stats.py -v`
Expected: ImportError or AttributeError — `compute_stats` does not exist (only `compute_action_stats`).

- [ ] **Step 5.3: Rewrite `backend/mimicrec/datasets/exporters/stats.py`**

```python
"""Compute action_stats / action_stats_q99 / proprio_stats_q99 over
VLA-compat episode tables (pure)."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pyarrow as pa

_STD_FLOOR = 1e-6
_ACTION_STATS_CONVENTION = "q99_derived_midpoint_halfrange"


def compute_stats(tables: Iterable[pa.Table]) -> tuple[dict, dict, dict]:
    """Return (action_stats, action_q99, proprio_q99).

    action_stats has `mean`, `std`, AND a `convention` metadata field. The
    mean/std are NOT the actual mean/std of the action distribution; they
    are derived from q01/q99 so the existing decoder's
    `physical = mean + arr * std` formula correctly inverts a model output
    `arr` in [-1,+1] that came from BOUNDS_Q99 normalization at training
    time. See spec §6 for the math.
    """
    action_rows: list[list[float]] = []
    proprio_rows: list[list[float]] = []
    for t in tables:
        action_rows.extend(t.column("action").to_pylist())
        proprio_rows.extend(t.column("observation.state").to_pylist())
    if not action_rows:
        raise ValueError("compute_stats: no rows across tables")

    arr_a = np.asarray(action_rows, dtype=np.float64)    # [N, 7]
    arr_p = np.asarray(proprio_rows, dtype=np.float64)   # [N, D_prop_robot]

    a_q01 = np.quantile(arr_a, 0.01, axis=0)
    a_q99 = np.quantile(arr_a, 0.99, axis=0)
    a_midpoint = (a_q99 + a_q01) / 2.0
    a_half_range = np.maximum((a_q99 - a_q01) / 2.0, _STD_FLOOR)

    p_q01 = np.quantile(arr_p, 0.01, axis=0)
    p_q99 = np.quantile(arr_p, 0.99, axis=0)

    action_stats = {
        "mean": a_midpoint.tolist(),
        "std": a_half_range.tolist(),
        "convention": _ACTION_STATS_CONVENTION,
    }
    action_q99 = {
        "q01": a_q01.tolist(),
        "q99": a_q99.tolist(),
        "mask": [True] * 7,
    }
    proprio_q99 = {
        "q01": p_q01.tolist(),
        "q99": p_q99.tolist(),
        "mask": [True] * arr_p.shape[1],
    }
    return action_stats, action_q99, proprio_q99
```

- [ ] **Step 5.4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_exporter_stats.py -v`
Expected: 7 PASSED.

- [ ] **Step 5.5: Commit**

```bash
git add backend/mimicrec/datasets/exporters/stats.py tests/unit/test_exporter_stats.py
git commit -m "$(cat <<'EOF'
feat(exporter): triple-output compute_stats (action mean/std + action q99 + proprio q99)

Replaces compute_action_stats. action_stats.mean/std is now q99-derived
midpoint/half_range, with a 'convention' metadata field so operators
cannot misread it as actual statistics. Proprio q99 enables the
future X-VLA loader's normalize_proprio_q99 path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Refactor `info_json.py` per spec §5

**Files:**
- Modify: `backend/mimicrec/datasets/exporters/info_json.py`
- Modify: `tests/unit/test_exporter_info_json.py`

- [ ] **Step 6.1: Replace tests in `tests/unit/test_exporter_info_json.py`**

Replace file contents with:

```python
import pytest

from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.datasets.exporters.info_json import to_vla_info, ACTION_NAMES


def _so101_layout() -> ProprioLayout:
    return ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("shoulder_pan", "shoulder_lift", "elbow_flex",
                      "wrist_flex", "wrist_roll", "gripper"),
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=5,
    )


def _rebot_layout() -> ProprioLayout:
    return ProprioLayout(
        columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
        output_names=("joint1", "joint2", "join3", "joint4", "joint5", "joint6", "gripper"),
        gripper_via_column="observation.state.gripper_pos",
        gripper_index_in_column=0,
    )


def test_action_names_are_ee_delta_components():
    assert ACTION_NAMES == ["ee_dx", "ee_dy", "ee_dz",
                            "ee_drx", "ee_dry", "ee_drz", "gripper"]


def test_to_vla_info_writes_action_feature_with_ee_delta_names():
    out = to_vla_info(
        {}, robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout=_so101_layout(), n_proprio=6,
    )
    assert out["features"]["action"] == {
        "dtype": "float32", "shape": [7], "names": ACTION_NAMES,
    }


def test_to_vla_info_observation_state_so101_shape_and_names():
    out = to_vla_info(
        {}, robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout=_so101_layout(), n_proprio=6,
    )
    assert out["features"]["observation.state"] == {
        "dtype": "float32",
        "shape": [6],
        "names": list(_so101_layout().output_names),
    }


def test_to_vla_info_observation_state_rebot_shape_and_names():
    out = to_vla_info(
        {}, robot_type="ReBotArmZmqAdapter",
        gripper_convention={"closed_at": 1.0, "open_at": 0.0},
        proprio_layout=_rebot_layout(), n_proprio=7,
    )
    assert out["features"]["observation.state"] == {
        "dtype": "float32",
        "shape": [7],
        "names": list(_rebot_layout().output_names),
    }


def test_to_vla_info_carries_robot_type_gripper_convention_proprio_layout():
    out = to_vla_info(
        {}, robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout=_so101_layout(), n_proprio=6,
    )
    assert out["robot_type"] == "SO101Adapter"
    assert out["gripper_convention"] == {"closed_at": 0.0, "open_at": 100.0}
    assert out["proprio_layout"] == {
        "columns": list(_so101_layout().columns),
        "output_names": list(_so101_layout().output_names),
        "gripper_via_column": "observation.state.joint_pos",
        "gripper_index_in_column": 5,
    }


def test_to_vla_info_raises_when_name_count_mismatches_n_proprio():
    with pytest.raises(ValueError, match="proprio name/shape mismatch"):
        to_vla_info(
            {}, robot_type="SO101Adapter",
            gripper_convention={"closed_at": 0.0, "open_at": 100.0},
            proprio_layout=_so101_layout(),    # 6 names
            n_proprio=7,                        # disagree
        )


def test_to_vla_info_does_not_mutate_input():
    src = {"features": {"existing": {"dtype": "string"}}}
    to_vla_info(
        src, robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout=_so101_layout(), n_proprio=6,
    )
    assert src == {"features": {"existing": {"dtype": "string"}}}
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_exporter_info_json.py -v`
Expected: TypeError on `to_vla_info` signature.

- [ ] **Step 6.3: Rewrite `backend/mimicrec/datasets/exporters/info_json.py`**

```python
"""Rewrite a LeRobot info.json for VLA-compat output (pure)."""
from __future__ import annotations

import copy
from typing import Any

from mimicrec.adapters.types import ProprioLayout

ACTION_NAMES = ["ee_dx", "ee_dy", "ee_dz", "ee_drx", "ee_dry", "ee_drz", "gripper"]


def to_vla_info(
    info: dict[str, Any],
    *,
    robot_type: str,
    gripper_convention: dict,
    proprio_layout: ProprioLayout,
    n_proprio: int,
) -> dict[str, Any]:
    """Return a deep-copied info dict with action/observation.state for the
    VLA-compat schema and the recording-time adapter declarations carried
    through to the export.

    The input `info` dict is not mutated.
    """
    new = copy.deepcopy(info)
    new["robot_type"] = robot_type
    new["gripper_convention"] = gripper_convention
    new["proprio_layout"] = {
        "columns": list(proprio_layout.columns),
        "output_names": list(proprio_layout.output_names),
        "gripper_via_column": proprio_layout.gripper_via_column,
        "gripper_index_in_column": proprio_layout.gripper_index_in_column,
    }
    features = new.setdefault("features", {})

    features["action"] = {
        "dtype": "float32", "shape": [7], "names": list(ACTION_NAMES),
    }

    obs_names = list(proprio_layout.output_names)
    if len(obs_names) != n_proprio:
        raise ValueError(
            f"proprio name/shape mismatch: layout.output_names has {len(obs_names)} "
            f"entries but n_proprio={n_proprio}"
        )
    features["observation.state"] = {
        "dtype": "float32", "shape": [n_proprio], "names": obs_names,
    }

    features["language_instruction"] = {
        "dtype": "string", "shape": [1], "names": None,
    }
    return new
```

- [ ] **Step 6.4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_exporter_info_json.py -v`
Expected: 7 PASSED.

- [ ] **Step 6.5: Commit**

```bash
git add backend/mimicrec/datasets/exporters/info_json.py tests/unit/test_exporter_info_json.py
git commit -m "$(cat <<'EOF'
feat(exporter): info_json carries adapter declarations + ee_delta action names

to_vla_info now requires robot_type, gripper_convention, proprio_layout,
and n_proprio. action.names is the canonical ee_delta+gripper list;
observation.state names come from proprio_layout.output_names with no
per-robot special-casing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Rewrite `vla_compat.py` exporter logic

**Files:**
- Modify: `backend/mimicrec/datasets/exporters/vla_compat.py`
- Modify: `tests/unit/test_exporter_vla_compat.py`

- [ ] **Step 7.1: Replace tests in `tests/unit/test_exporter_vla_compat.py`**

Replace file contents with:

```python
import math

import numpy as np
import pyarrow as pa
import pytest
from scipy.spatial.transform import Rotation as R

from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.datasets.exporters.vla_compat import (
    convert_episode_table,
    ConvertedEpisode,
)


SO101_LAYOUT = ProprioLayout(
    columns=("observation.state.joint_pos",),
    output_names=("shoulder_pan", "shoulder_lift", "elbow_flex",
                  "wrist_flex", "wrist_roll", "gripper"),
    gripper_via_column="observation.state.joint_pos",
    gripper_index_in_column=5,
)

REBOT_LAYOUT = ProprioLayout(
    columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
    output_names=("joint1", "joint2", "join3", "joint4", "joint5", "joint6", "gripper"),
    gripper_via_column="observation.state.gripper_pos",
    gripper_index_in_column=0,
)

SO101_CONV = GripperConvention(closed_at=0.0, open_at=100.0)
REBOT_CONV = GripperConvention(closed_at=1.0, open_at=0.0)


def _so101_table(
    n: int,
    *,
    ee_pos=None, ee_rot=None, joint_pos=None,
) -> pa.Table:
    if ee_pos is None:
        ee_pos = [[0.1 + 0.001 * i, 0.2, 0.3] for i in range(n)]
    if ee_rot is None:
        ee_rot = [[0.0, 0.0, 0.0] for _ in range(n)]
    if joint_pos is None:
        # last entry is the packed gripper raw [0, 100]
        joint_pos = [[0.1 * i, 0.2, 0.3, 0.4, 0.5, 50.0] for i in range(n)]
    return pa.table({
        "observation.state.ee_pos": ee_pos,
        "observation.state.ee_rotvec": ee_rot,
        "observation.state.joint_pos": joint_pos,
        "observation.state.gripper_pos": [j[5] for j in joint_pos],
        "frame_index": list(range(n)),
        "episode_index": [0] * n,
        "index": list(range(n)),
        "task_index": [0] * n,
        "timestamp": [i / 15.0 for i in range(n)],
    })


def _rebot_table(
    n: int,
    *,
    ee_pos=None, ee_rot=None, joint_pos=None, gripper_pos=None,
) -> pa.Table:
    if ee_pos is None:
        ee_pos = [[0.1 + 0.001 * i, 0.2, 0.3] for i in range(n)]
    if ee_rot is None:
        ee_rot = [[0.0, 0.0, 0.0] for _ in range(n)]
    if joint_pos is None:
        joint_pos = [[0.1, 0.2, 0.3, 0.4, 0.5, 0.6] for _ in range(n)]
    if gripper_pos is None:
        gripper_pos = [0.5 for _ in range(n)]
    return pa.table({
        "observation.state.ee_pos": ee_pos,
        "observation.state.ee_rotvec": ee_rot,
        "observation.state.joint_pos": joint_pos,
        "observation.state.gripper_pos": gripper_pos,
        "frame_index": list(range(n)),
        "episode_index": [0] * n,
        "index": list(range(n)),
        "task_index": [0] * n,
        "timestamp": [i / 15.0 for i in range(n)],
    })


def test_action_is_ee_delta_with_gripper_in_unit_range():
    table = _so101_table(n=4)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    actions = np.asarray(out.table.column("action").to_pylist())
    assert actions.shape == (3, 7)            # n-1 rows, 7 cols
    assert (actions[:, 6] >= 0).all() and (actions[:, 6] <= 1).all()


def test_action_uses_ee_local_frame_via_matrix_compose():
    # Construct two non-identity poses; assert T_curr @ T_delta reconstructs T_next.
    rng = np.random.default_rng(0)
    pos = rng.normal(scale=0.05, size=(2, 3))
    rot = rng.normal(scale=0.05, size=(2, 3))
    table = _so101_table(n=2, ee_pos=pos.tolist(), ee_rot=rot.tolist())
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    a = np.asarray(out.table.column("action").to_pylist())[0]   # only row
    T_curr = np.eye(4); T_curr[:3, 3] = pos[0]
    T_curr[:3, :3] = R.from_rotvec(rot[0]).as_matrix()
    T_next_expected = np.eye(4); T_next_expected[:3, 3] = pos[1]
    T_next_expected[:3, :3] = R.from_rotvec(rot[1]).as_matrix()
    T_delta = np.eye(4); T_delta[:3, 3] = a[0:3]
    T_delta[:3, :3] = R.from_rotvec(a[3:6]).as_matrix()
    T_next_actual = T_curr @ T_delta
    np.testing.assert_allclose(T_next_actual[:3, 3], T_next_expected[:3, 3], atol=1e-6)
    np.testing.assert_allclose(T_next_actual[:3, :3], T_next_expected[:3, :3], atol=1e-6)


def test_rotation_delta_above_one_rad_raises_sanity():
    # T_curr identity, T_next with a 1.1 rad rotation about z
    pos = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    rot = [[0.0, 0.0, 0.0], [0.0, 0.0, 1.1]]
    table = _so101_table(n=2, ee_pos=pos, ee_rot=rot)
    with pytest.raises(ValueError, match="exceeds .* sanity bound"):
        convert_episode_table(
            table=table, instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_rotation_delta_near_zero_returns_small_axisangle():
    pos = [[0.0]*3, [0.0]*3]
    rot = [[0.0]*3, [1e-10, 1e-10, 1e-10]]
    table = _so101_table(n=2, ee_pos=pos, ee_rot=rot)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    a = np.asarray(out.table.column("action").to_pylist())[0]
    assert np.linalg.norm(a[3:6]) < 1e-6


def test_export_drops_last_frame_episode_n_to_n_minus_1():
    out = convert_episode_table(
        table=_so101_table(n=10), instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    assert out.table.num_rows == 9


def test_episode_n_equals_2_outputs_one_row():
    out = convert_episode_table(
        table=_so101_table(n=2), instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    assert out.table.num_rows == 1


def test_episode_n_equals_1_raises():
    with pytest.raises(ValueError, match="too short"):
        convert_episode_table(
            table=_so101_table(n=1), instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_gripper_normalized_so101_convention():
    joint_pos = [[0.0]*5 + [0.0], [0.0]*5 + [50.0], [0.0]*5 + [100.0]]
    table = _so101_table(n=3, joint_pos=joint_pos)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    g = np.asarray(out.table.column("action").to_pylist())[:, 6]
    np.testing.assert_allclose(g, [0.0, 0.5])    # last frame dropped, only 2 rows


def test_gripper_normalized_rebot_inverted_convention():
    table = _rebot_table(n=3, gripper_pos=[1.0, 0.5, 0.0])
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=REBOT_CONV, proprio_layout=REBOT_LAYOUT,
    )
    g = np.asarray(out.table.column("action").to_pylist())[:, 6]
    # 1.0 (closed) -> 0; 0.5 -> 0.5; 0.0 (open) -> 1 (last frame dropped)
    np.testing.assert_allclose(g, [0.0, 0.5])


def test_gripper_clipped_when_raw_overshoots():
    joint_pos = [[0.0]*5 + [-10.0], [0.0]*5 + [120.0]]
    table = _so101_table(n=2, joint_pos=joint_pos)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    g = np.asarray(out.table.column("action").to_pylist())[:, 6]
    # only one row (n-1); raw=-10 → clipped to 0
    assert g[0] == 0.0


def test_observation_state_so101_is_joint_pos_verbatim():
    table = _so101_table(n=3)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    obs = np.asarray(out.table.column("observation.state").to_pylist())
    assert obs.shape == (2, 6)
    expected = np.asarray(table.column("observation.state.joint_pos").to_pylist())[:2]
    np.testing.assert_allclose(obs, expected)


def test_observation_state_rebot_concatenates_joint_pos_and_gripper_pos():
    table = _rebot_table(n=3)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=REBOT_CONV, proprio_layout=REBOT_LAYOUT,
    )
    obs = np.asarray(out.table.column("observation.state").to_pylist())
    assert obs.shape == (2, 7)
    np.testing.assert_allclose(obs[:, -1], [0.5, 0.5])


def test_observation_state_missing_layout_column_raises_value_error():
    table = _so101_table(n=3)
    table = table.drop_columns(["observation.state.joint_pos"])
    with pytest.raises(ValueError, match="not in parquet"):
        convert_episode_table(
            table=table, instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_observation_state_ragged_list_column_raises_value_error():
    # Hand-construct a ragged joint_pos column.
    n = 3
    ragged = [[0.0]*6, [0.0]*5, [0.0]*6]    # middle row is shorter
    table = pa.table({
        "observation.state.ee_pos": [[0.0]*3]*n,
        "observation.state.ee_rotvec": [[0.0]*3]*n,
        "observation.state.joint_pos": ragged,
        "observation.state.gripper_pos": [0.0]*n,
        "frame_index": list(range(n)),
        "episode_index": [0]*n, "index": list(range(n)), "task_index": [0]*n,
        "timestamp": [i/15.0 for i in range(n)],
    })
    with pytest.raises(ValueError, match="ragged widths"):
        convert_episode_table(
            table=table, instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_observation_state_dim_mismatch_with_output_names_raises_value_error():
    """SO-101 layout declares 6 output_names but a layout that promises
    only 5 names should fail at the concat-dim check."""
    bad_layout = ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("a", "b", "c", "d", "e"),    # 5 names, joint_pos is 6
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=4,
    )
    with pytest.raises(ValueError, match="!= len\\(output_names\\)"):
        convert_episode_table(
            table=_so101_table(n=3), instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=bad_layout,
        )


def test_resolve_gripper_index_out_of_bounds_raises_value_error():
    bad_layout = ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("a",) * 6,
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=99,    # way past list width
    )
    with pytest.raises(ValueError, match="missing or too short"):
        convert_episode_table(
            table=_so101_table(n=3), instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=bad_layout,
        )


def test_resolve_gripper_scalar_column_with_nonzero_index_raises_value_error():
    bad_layout = ProprioLayout(
        columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
        output_names=("j1","j2","join3","j4","j5","j6","gripper"),
        gripper_via_column="observation.state.gripper_pos",
        gripper_index_in_column=1,    # scalar column has no index 1
    )
    with pytest.raises(ValueError, match="cannot have gripper_index_in_column != 0"):
        convert_episode_table(
            table=_rebot_table(n=3), instruction_text="x",
            gripper_convention=REBOT_CONV, proprio_layout=bad_layout,
        )


def test_rotation_delta_below_sanity_bound_passes_reconstruction():
    """Construct a relative rotation just below the 1-rad sanity bound
    (well below π); verify it survives extraction + matrix reconstruction."""
    pos = [[0.0]*3, [0.0]*3]
    rot = [[0.0]*3, [0.0, 0.0, 0.9]]    # 0.9 rad < 1.0 rad bound
    table = _so101_table(n=2, ee_pos=pos, ee_rot=rot)
    out = convert_episode_table(
        table=table, instruction_text="x",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    a = np.asarray(out.table.column("action").to_pylist())[0]
    T_curr = np.eye(4)
    T_next_expected = np.eye(4); T_next_expected[:3, :3] = R.from_rotvec(rot[1]).as_matrix()
    T_delta = np.eye(4); T_delta[:3, 3] = a[0:3]
    T_delta[:3, :3] = R.from_rotvec(a[3:6]).as_matrix()
    T_next_actual = T_curr @ T_delta
    np.testing.assert_allclose(T_next_actual[:3, :3], T_next_expected[:3, :3], atol=1e-6)


def test_non_finite_inputs_raise():
    pos = [[float("nan"), 0, 0], [0, 0, 0]]
    rot = [[0.0]*3, [0.0]*3]
    table = _so101_table(n=2, ee_pos=pos, ee_rot=rot)
    with pytest.raises(ValueError, match="non-finite"):
        convert_episode_table(
            table=table, instruction_text="x",
            gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
        )


def test_output_carries_language_instruction_per_row():
    out = convert_episode_table(
        table=_so101_table(n=4), instruction_text="hello",
        gripper_convention=SO101_CONV, proprio_layout=SO101_LAYOUT,
    )
    li = out.table.column("language_instruction").to_pylist()
    assert li == ["hello"] * 3   # n-1
```

- [ ] **Step 7.2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_exporter_vla_compat.py -v`
Expected: TypeError on `convert_episode_table` signature mismatch (existing one does not accept `gripper_convention` or `proprio_layout`).

- [ ] **Step 7.3: Rewrite `backend/mimicrec/datasets/exporters/vla_compat.py`**

```python
"""Episode-table conversion to VLA-compat schema (pure)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyarrow as pa
from scipy.spatial.transform import Rotation as R

from mimicrec.adapters.types import GripperConvention, ProprioLayout


@dataclass(frozen=True)
class ConvertedEpisode:
    table: pa.Table


_PASSTHROUGH_COLUMNS = (
    "timestamp",
    "frame_index",
    "episode_index",
    "index",
    "task_index",
)

_REQUIRED_INPUT_COLUMNS = (
    "observation.state.ee_pos",
    "observation.state.ee_rotvec",
)

# Real per-step rotation deltas at 15-30 fps stay well below this. Hitting
# it indicates frame mismatch or bad input data — fail loudly rather than
# emit an axis-discontinuity sample.
_ROT_DELTA_SANITY_RAD = 1.0


def _to_T(pos: np.ndarray, rotvec: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = pos
    if np.linalg.norm(rotvec) > 1e-9:
        T[:3, :3] = R.from_rotvec(rotvec).as_matrix()
    return T


def _normalize_unit(raw: np.ndarray, conv: GripperConvention) -> np.ndarray:
    span = conv.open_at - conv.closed_at
    # span == 0 already rejected by GripperConvention.__post_init__
    return np.clip((raw - conv.closed_at) / span, 0.0, 1.0).astype(np.float32)


def _resolve_raw_gripper_column(table: pa.Table, layout: ProprioLayout) -> np.ndarray:
    if layout.gripper_via_column not in table.column_names:
        raise ValueError(
            f"layout names gripper_via_column={layout.gripper_via_column!r} "
            f"but parquet has no such column (have: {sorted(table.column_names)})"
        )
    col = table.column(layout.gripper_via_column)
    if pa.types.is_list(col.type) or pa.types.is_fixed_size_list(col.type):
        rows = col.to_pylist()
        idx = layout.gripper_index_in_column
        out = np.empty(len(rows), dtype=np.float64)
        for r, row in enumerate(rows):
            if row is None or len(row) <= idx:
                raise ValueError(
                    f"row {r} of {layout.gripper_via_column}: missing or too short "
                    f"for gripper_index_in_column={idx} (len="
                    f"{None if row is None else len(row)})"
                )
            out[r] = row[idx]
        return out
    if layout.gripper_index_in_column != 0:
        raise ValueError(
            f"scalar column {layout.gripper_via_column} cannot have "
            f"gripper_index_in_column != 0"
        )
    return np.asarray(col.to_pylist(), dtype=np.float64)


def _build_observation_state(table: pa.Table, layout: ProprioLayout) -> np.ndarray:
    """Concatenate the adapter-declared columns row-by-row, verbatim.

    Validates: every layout column exists in the table, list columns have
    consistent (non-ragged) widths, and concatenated dim matches
    len(layout.output_names).
    """
    cols: list[np.ndarray] = []
    for name in layout.columns:
        if name not in table.column_names:
            raise ValueError(
                f"layout column {name!r} not in parquet "
                f"(have: {sorted(table.column_names)})"
            )
        col = table.column(name)
        if pa.types.is_list(col.type) or pa.types.is_fixed_size_list(col.type):
            rows = col.to_pylist()
            if any(r is None for r in rows):
                raise ValueError(f"null row in list column {name}")
            widths = {len(r) for r in rows}
            if len(widths) != 1:
                raise ValueError(
                    f"ragged widths in list column {name}: {sorted(widths)}"
                )
            cols.append(np.asarray(rows, dtype=np.float32))
        else:
            cols.append(np.asarray(col.to_pylist(), dtype=np.float32)[:, None])
    out = np.concatenate(cols, axis=1)
    if out.shape[1] != len(layout.output_names):
        raise ValueError(
            f"concatenated proprio dim {out.shape[1]} != "
            f"len(output_names)={len(layout.output_names)} for layout "
            f"columns={layout.columns}"
        )
    return out


def convert_episode_table(
    *,
    table: pa.Table,
    instruction_text: str,
    gripper_convention: GripperConvention,
    proprio_layout: ProprioLayout,
) -> ConvertedEpisode:
    """Return a new pa.Table in VLA-compat schema.

    Output:
      - action: list<float32>[7] = [Δxyz(m), Δrxryrz(axis-angle rad), gripper([0,1])]
      - observation.state: list<float32>[N_proprio_robot] = adapter-declared concat
      - language_instruction: string repeated per row
      - passthrough columns (timestamp, frame_index, episode_index, index,
        task_index, observation.images.*.video_frame_index/t_mono_ns)

    Episode of n input rows produces n-1 output rows. The last frame is
    dropped (no obs[t]→obs[t+1] delta available); see spec §4.
    """
    n = table.num_rows
    if n < 2:
        raise ValueError(f"episode too short for delta computation: n={n}")
    missing = [c for c in _REQUIRED_INPUT_COLUMNS if c not in table.column_names]
    if missing:
        raise ValueError(
            f"convert_episode_table missing required columns: {missing}"
        )
    out_n = n - 1

    ee_pos = np.asarray(
        table.column("observation.state.ee_pos").to_pylist(), dtype=np.float64,
    )
    ee_rot = np.asarray(
        table.column("observation.state.ee_rotvec").to_pylist(), dtype=np.float64,
    )
    if not (np.isfinite(ee_pos).all() and np.isfinite(ee_rot).all()):
        raise ValueError("non-finite values in observation.state.ee_pos/ee_rotvec")

    actions = np.zeros((out_n, 7), dtype=np.float32)
    for t in range(out_n):
        T_curr = _to_T(ee_pos[t], ee_rot[t])
        T_next = _to_T(ee_pos[t + 1], ee_rot[t + 1])
        T_delta = np.linalg.inv(T_curr) @ T_next
        actions[t, 0:3] = T_delta[:3, 3]
        rotvec = R.from_matrix(T_delta[:3, :3]).as_rotvec()
        rmag = float(np.linalg.norm(rotvec))
        if rmag > _ROT_DELTA_SANITY_RAD:
            raise ValueError(
                f"per-step rotation delta {rmag:.3f} rad at t={t} exceeds "
                f"{_ROT_DELTA_SANITY_RAD} rad sanity bound — likely frame "
                f"mismatch or bad input data, not real motion"
            )
        actions[t, 3:6] = rotvec

    raw_gripper = _resolve_raw_gripper_column(table, proprio_layout)
    if not np.isfinite(raw_gripper).all():
        raise ValueError("non-finite values in gripper column")
    actions[:, 6] = _normalize_unit(raw_gripper[:out_n], gripper_convention)

    obs_state_full = _build_observation_state(table, proprio_layout).astype(np.float32)
    if not np.isfinite(obs_state_full).all():
        raise ValueError("non-finite values in observation.state columns")
    obs_state = obs_state_full[:out_n]

    arrays: dict[str, pa.Array] = {
        "action": pa.array(actions.tolist(), type=pa.list_(pa.float32(), 7)),
        "observation.state": pa.array(
            obs_state.tolist(),
            type=pa.list_(pa.float32(), obs_state.shape[1]),
        ),
        "language_instruction": pa.array(
            [instruction_text] * out_n, type=pa.string()
        ),
    }
    for col in _PASSTHROUGH_COLUMNS:
        if col in table.column_names:
            arrays[col] = table.column(col).slice(0, out_n)
    # Per-camera video frame index / t_mono_ns columns (passthrough, sliced).
    for name in table.column_names:
        if name.startswith("observation.images.") and (
            name.endswith(".video_frame_index") or name.endswith(".t_mono_ns")
        ):
            arrays[name] = table.column(name).slice(0, out_n)

    # info.json declares timestamp float32; ensure cast even when input came
    # from older recordings written before pending.finalize cast.
    if "timestamp" in arrays:
        arrays["timestamp"] = arrays["timestamp"].cast(pa.float32())

    return ConvertedEpisode(table=pa.table(arrays))
```

- [ ] **Step 7.4: Run vla_compat unit tests (orchestrator tests stay broken until Task 8)**

Run: `.venv/bin/pytest tests/unit/test_exporter_vla_compat.py -v`
Expected: ALL PASS (~20 tests).

Do NOT run `tests/unit/test_exporter_orchestrator.py` here — those will fail because the orchestrator still calls `convert_episode_table` with the old signature. Task 8 fixes that.

- [ ] **Step 7.5: Commit (vla_compat code + tests only)**

```bash
git add backend/mimicrec/datasets/exporters/vla_compat.py tests/unit/test_exporter_vla_compat.py
git commit -m "$(cat <<'EOF'
feat(exporter): rewrite vla_compat for ee_delta + per-robot proprio

action becomes [ee_delta(6, m + axis-angle rad, ee_local), gripper(1, [0,1])];
observation.state is per-robot verbatim from adapter ProprioLayout.
Episode of n rows exports n-1 rows (last frame dropped, no obs->obs+1
delta available). Runtime guards: per-step rotation > 1 rad raises;
non-finite inputs raise; missing/ragged columns raise; gripper index
out of bounds raises.

Orchestrator wiring + legacy fixture updates land in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Wire orchestrator (override + n_proprio derivation + 3 stats files) + update legacy `_seed_dataset`

**Files:**
- Modify: `backend/mimicrec/datasets/exporters/orchestrator.py`
- Modify: `tests/unit/test_exporter_orchestrator.py`

- [ ] **Step 8.1: Update `_seed_dataset` so existing tests keep working with the new exporter**

Two changes to `tests/unit/test_exporter_orchestrator.py:_seed_dataset`:

1. Add an optional `robot_type: str | None = "SO101Adapter"` kwarg. When non-None, also pass the matching `gripper_convention` and `proprio_layout` dicts to `init_dataset`. When None, omit them — produces the legacy `robot_type="unknown"` info.json that the override-path tests need.

2. Always emit `observation.state.ee_pos` and `observation.state.ee_rotvec` per row (synthetic, non-degenerate, so n→n-1 ee_delta computation succeeds and the rotation sanity bound is not tripped).

Replace `_seed_dataset` with:

```python
def _seed_dataset(ds_root: Path, *, num_episodes: int, num_frames: int,
                  task_name: str, instruction: str | None,
                  robot_type: str | None = "SO101Adapter") -> None:
    if robot_type == "SO101Adapter":
        gc_dict = {"closed_at": 0.0, "open_at": 100.0}
        pl_dict = {
            "columns": ["observation.state.joint_pos"],
            "output_names": ["shoulder_pan", "shoulder_lift", "elbow_flex",
                             "wrist_flex", "wrist_roll", "gripper"],
            "gripper_via_column": "observation.state.joint_pos",
            "gripper_index_in_column": 5,
        }
    else:
        gc_dict = None
        pl_dict = None
    init_dataset(
        ds_root, fps=15,
        joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
        camera_names=["front"],
        robot_type=robot_type,
        gripper_convention=gc_dict,
        proprio_layout=pl_dict,
    )
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, task_name, instruction or "")
    for idx in range(num_episodes):
        chunk_dir = p.chunk_dir(0)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for f in range(num_frames):
            rows.append({
                "timestamp": f * (1.0 / 15),
                "tick_t_mono_ns": 0,
                "observation.state.joint_pos": [0.1] * 6,
                "observation.state.joint_vel": [0.0] * 6,
                "observation.state.joint_effort": [0.0] * 6,
                "observation.state.t_mono_ns": 0,
                "observation.state.gripper_pos": 0.5,
                # Synthetic FK output — each frame advances 1 mm in x, zero
                # rotation. Gives obs->obs delta of (0.001, 0, 0, 0, 0, 0).
                "observation.state.ee_pos": [0.1 + 0.001 * f, 0.2, 0.3],
                "observation.state.ee_rotvec": [0.0, 0.0, 0.0],
                "action.joint_pos": [0.2] * 6,
                "action.t_mono_ns": 0,
                "action.gripper_pos": 0.7,
                "frame_index": f,
                "episode_index": idx,
                "index": idx * num_frames + f,
                "task_index": 0,
                "observation.images.front.video_frame_index": f,
                "observation.images.front.t_mono_ns": 0,
            })
        pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, idx))
        cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
        cam_dir.mkdir(parents=True, exist_ok=True)
        (cam_dir / f"episode_{idx:06d}.mp4").write_bytes(b"\x00fake\x00")
        append_episode(p.meta_dir, {
            "episode_index": idx, "task": task_name,
            "num_frames": num_frames, "robot": "so101", "mode": "teleop",
            "cameras": ["front"],
        })
```

Then **inspect every `_seed_dataset(..., num_frames=1, ...)` callsite** (greps to find them). For each:
- If the test calls `export_dataset_to_local(..., format=ExportFormat.VLA_COMPAT, ...)` and the failure path it covers happens AFTER `convert_episode_table` runs → bump `num_frames=1` to `num_frames=2`.
- If the test only exercises `LEROBOT_V3_NATIVE` format, or the failure path is BEFORE conversion (e.g. `DestinationExistsError` without `force=True`) → keep `num_frames=1`. Native-format export is a verbatim copy and tolerates 1-frame episodes.

Use the test's name + body to decide; do not bump blindly.

**ALSO update the `flaky` monkeypatch in `test_export_cleans_up_partial_on_mid_loop_failure`** (currently around line 205). Its current signature `def flaky(*, table, instruction_text)` will TypeError after Task 8.5's orchestrator change because the orchestrator now passes `gripper_convention` and `proprio_layout` too. Replace with:

```python
def flaky(*, table, instruction_text, gripper_convention, proprio_layout):
    call_count["n"] += 1
    if call_count["n"] == 2:
        raise RuntimeError("synthetic mid-loop failure")
    return real_convert(
        table=table, instruction_text=instruction_text,
        gripper_convention=gripper_convention, proprio_layout=proprio_layout,
    )
```

- [ ] **Step 8.2: Inspect existing orchestrator test file structure**

Run: `.venv/bin/cat tests/unit/test_exporter_orchestrator.py | head -60`

- [ ] **Step 8.3: Append new tests to `tests/unit/test_exporter_orchestrator.py`**

After Step 8.1 the helper now takes `robot_type=None` to produce a legacy unknown-robot dataset; the override-path test uses that. Append at the bottom of the file (do not delete existing tests):

```python


# === New tests for ee_delta refactor ===

from mimicrec.datasets.exporters.orchestrator import ExportOverride


def test_orchestrator_fails_when_robot_type_unknown_and_no_override(tmp_path):
    ds = tmp_path / "src"
    _seed_dataset(
        ds, num_episodes=1, num_frames=4,
        task_name="pick", instruction="pick up the bottle",
        robot_type=None,    # produces info.json with robot_type='unknown'
    )
    with pytest.raises(ValueError, match="robot_type='unknown'"):
        export_dataset_to_local(
            ds_root=ds, dest_root=tmp_path / "out",
            format=ExportFormat.VLA_COMPAT,
            instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
            force=True,
        )


def test_orchestrator_uses_override_when_provided(tmp_path):
    ds = tmp_path / "src"
    _seed_dataset(
        ds, num_episodes=1, num_frames=4,
        task_name="pick", instruction="pick up the bottle",
        robot_type=None,    # legacy unknown dataset
    )
    result = export_dataset_to_local(
        ds_root=ds, dest_root=tmp_path / "out",
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=True,
        override=ExportOverride(robot_type="so101"),
    )
    info = json.loads((result.dest_path / "meta" / "info.json").read_text())
    assert info["robot_type"] == "SO101Adapter"


def test_orchestrator_raises_on_inconsistent_proprio_dim_across_episodes(
    tmp_path, monkeypatch,
):
    """Force two synthetic episodes whose converted observation.state widths
    disagree by monkey-patching convert_episode_table to alternate per call."""
    ds = tmp_path / "src"
    _seed_dataset(
        ds, num_episodes=2, num_frames=4,
        task_name="pick", instruction="pick up the bottle",
    )

    import pyarrow as pa
    import itertools
    from mimicrec.datasets.exporters import orchestrator as orch_mod
    from mimicrec.datasets.exporters.vla_compat import ConvertedEpisode

    widths = itertools.cycle([6, 7])

    def fake_convert(*, table, instruction_text, gripper_convention, proprio_layout):
        n = max(table.num_rows - 1, 1)
        w = next(widths)
        out = pa.table({
            "action": pa.array([[0.0]*7]*n, type=pa.list_(pa.float32(), 7)),
            "observation.state": pa.array(
                [[0.0]*w]*n, type=pa.list_(pa.float32(), w),
            ),
            "language_instruction": pa.array([instruction_text]*n, type=pa.string()),
            "timestamp": pa.array([0.0]*n, type=pa.float32()),
            "frame_index": pa.array(list(range(n)), type=pa.int64()),
            "episode_index": pa.array([0]*n, type=pa.int64()),
            "index": pa.array(list(range(n)), type=pa.int64()),
            "task_index": pa.array([0]*n, type=pa.int64()),
        })
        return ConvertedEpisode(table=out)

    monkeypatch.setattr(orch_mod, "convert_episode_table", fake_convert)

    with pytest.raises(ValueError, match="observation.state dim"):
        export_dataset_to_local(
            ds_root=ds, dest_root=tmp_path / "out",
            format=ExportFormat.VLA_COMPAT,
            instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
            force=True,
            override=ExportOverride(robot_type="so101"),
        )
```

- [ ] **Step 8.4: Run new tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_exporter_orchestrator.py::test_orchestrator_fails_when_robot_type_unknown_and_no_override -v`
Expected: ImportError on `ExportOverride` (does not exist yet).

- [ ] **Step 8.5: Add `ExportOverride` dataclass + modify `_export_vla_compat` in `backend/mimicrec/datasets/exporters/orchestrator.py`**

Add at the top of `orchestrator.py`:

```python
from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.datasets.exporters.stats import compute_stats


# Adapter-class lookup for request-body overrides on legacy datasets.
# Map robot_type string → (GripperConvention factory, ProprioLayout factory).
_ROBOT_OVERRIDE_REGISTRY: dict[str, tuple] = {}


def _register_robot_override(robot_type: str):
    """Lazy import + registration to avoid a hard dependency on optional
    adapter modules at exporter import time."""
    if robot_type in _ROBOT_OVERRIDE_REGISTRY:
        return _ROBOT_OVERRIDE_REGISTRY[robot_type]
    if robot_type == "so101":
        from mimicrec.adapters.so101 import SO101Adapter
        cls = SO101Adapter
    elif robot_type == "rebot":
        from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter
        cls = ReBotArmZmqAdapter
    else:
        raise ValueError(
            f"unknown robot_type override {robot_type!r}; "
            f"supported: 'so101', 'rebot'"
        )
    entry = (
        cls.__name__,
        cls.default_gripper_convention,
        cls.proprio_layout,
    )
    _ROBOT_OVERRIDE_REGISTRY[robot_type] = entry
    return entry


@dataclass(frozen=True)
class ExportOverride:
    robot_type: str | None = None        # 'so101' / 'rebot'
    # Future: explicit gripper_convention / proprio_layout overrides,
    # not implemented in MVP (out of scope).
```

Modify `export_dataset_to_local` to accept the override:

```python
def export_dataset_to_local(
    *,
    ds_root: Path,
    dest_root: Path,
    format: ExportFormat,
    instruction_template: str,
    force: bool,
    override: ExportOverride | None = None,
) -> ExportResult:
    # ... (existing partial-dir setup unchanged) ...
    try:
        if format == ExportFormat.LEROBOT_V3_NATIVE:
            result = _export_v3_native(
                ds_root=ds_root, out_dir=partial_dir, format=format,
            )
        elif format == ExportFormat.VLA_COMPAT:
            result = _export_vla_compat(
                ds_root=ds_root, out_dir=partial_dir, format=format,
                instruction_template=instruction_template,
                override=override,
            )
        # ... (rest unchanged)
```

Replace the body of `_export_vla_compat`. Keep the per-episode iteration but:

```python
def _export_vla_compat(
    *, ds_root: Path, out_dir: Path, format: ExportFormat,
    instruction_template: str,
    override: ExportOverride | None = None,
) -> ExportResult:
    p = dataset_paths(ds_root)
    out_meta = out_dir / "meta"
    out_meta.mkdir(parents=True, exist_ok=True)
    out_data = out_dir / "data"
    out_data.mkdir(parents=True, exist_ok=True)
    out_videos = out_dir / "videos"
    out_videos.mkdir(parents=True, exist_ok=True)

    src_info = read_dataset_info(ds_root)
    robot_type = src_info.get("robot_type", "unknown")
    gripper_conv_dict = src_info.get("gripper_convention")
    proprio_layout_dict = src_info.get("proprio_layout")

    if (robot_type == "unknown" or gripper_conv_dict is None
            or proprio_layout_dict is None):
        if override is None or override.robot_type is None:
            raise ValueError(
                "dataset's info.json declares robot_type='unknown' (or is "
                "missing gripper_convention/proprio_layout). Re-record after "
                "the recording-layer change in this PR, or pass robot_type='so101' "
                "(or 'rebot') in the export request body to override for one-off "
                "reprocessing of pre-existing data."
            )
        rt_resolved, gc_factory, pl_factory = _register_robot_override(
            override.robot_type
        )
        robot_type = rt_resolved
        gc = gc_factory()
        pl = pl_factory()
    else:
        gc = GripperConvention(
            closed_at=float(gripper_conv_dict["closed_at"]),
            open_at=float(gripper_conv_dict["open_at"]),
        )
        pl = ProprioLayout(
            columns=tuple(proprio_layout_dict["columns"]),
            output_names=tuple(proprio_layout_dict["output_names"]),
            gripper_via_column=proprio_layout_dict["gripper_via_column"],
            gripper_index_in_column=int(
                proprio_layout_dict["gripper_index_in_column"]
            ),
        )

    tasks_lookup = _load_tasks_lookup(ds_root)
    warnings: list[str] = []
    converted_tables: list[pa.Table] = []
    num_episodes = 0
    num_frames = 0
    n_proprio: int | None = None

    live_eps = list(iter_episodes(ds_root, include_deleted=False))
    for ep in live_eps:
        ep_idx = int(ep["episode_index"])
        task_idx = int(ep.get("task_index", 0))
        task_row = tasks_lookup.get(
            task_idx, {"task": ep.get("task", "unknown"), "instruction": ""},
        )
        rendered = expand_instruction(
            template=instruction_template,
            task_name=task_row.get("task", "unknown"),
            instruction=task_row.get("instruction") or None,
        )
        warnings.extend(f"episode={ep_idx} {w.value}" for w in rendered.warnings)

        chunk = resolve_chunk(ep_idx)
        in_pq = p.episode_parquet(chunk, ep_idx)
        in_table = pq.read_table(in_pq)
        out_episode = convert_episode_table(
            table=in_table, instruction_text=rendered.text,
            gripper_convention=gc, proprio_layout=pl,
        )

        ep_n_proprio = out_episode.table.column("observation.state").type.list_size
        if n_proprio is None:
            n_proprio = ep_n_proprio
        elif ep_n_proprio != n_proprio:
            raise ValueError(
                f"episode {ep_idx} produced observation.state dim "
                f"{ep_n_proprio}, expected {n_proprio} from earlier episodes"
            )

        out_pq_dir = out_data / f"chunk-{chunk:03d}"
        out_pq_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            out_episode.table, out_pq_dir / f"episode_{ep_idx:06d}.parquet",
        )
        converted_tables.append(out_episode.table)
        num_episodes += 1
        num_frames += out_episode.table.num_rows

        # mp4 copy unchanged
        if p.videos_dir.exists():
            for cam_dir in p.videos_dir.iterdir():
                if not cam_dir.name.startswith("observation.images."):
                    continue
                src_mp4 = cam_dir / f"chunk-{chunk:03d}" / f"episode_{ep_idx:06d}.mp4"
                if src_mp4.exists():
                    dst_dir = out_videos / cam_dir.name / f"chunk-{chunk:03d}"
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_mp4, dst_dir / src_mp4.name)

    # info.json with declarations carried through
    new_info = to_vla_info(
        src_info,
        robot_type=robot_type,
        gripper_convention={"closed_at": gc.closed_at, "open_at": gc.open_at},
        proprio_layout=pl,
        n_proprio=int(n_proprio or 0),
    )
    new_info["total_episodes"] = num_episodes
    new_info["total_frames"] = num_frames
    (out_meta / "info.json").write_text(json.dumps(new_info, indent=2))

    # Triple stats output
    if converted_tables:
        action_stats, action_q99, proprio_q99 = compute_stats(converted_tables)
        (out_meta / "action_stats.json").write_text(json.dumps(action_stats))
        (out_meta / "action_stats_q99.json").write_text(json.dumps(action_q99))
        (out_meta / "proprio_stats_q99.json").write_text(json.dumps(proprio_q99))

    # tasks.parquet verbatim copy
    if p.tasks_parquet.exists():
        shutil.copy2(p.tasks_parquet, out_meta / "tasks.parquet")

    # episodes.parquet copy from build_archive_stream filtered version
    for path_in_zip, content in build_archive_stream(ds_root):
        if path_in_zip == "meta/episodes/chunk-000/file-000.parquet":
            target = out_meta / "episodes" / "chunk-000" / "file-000.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                content if isinstance(content, bytes) else content.read_bytes()
            )
            break

    return ExportResult(
        dest_path=out_dir,
        format=format,
        num_episodes=num_episodes,
        num_frames=num_frames,
        warnings=warnings,
    )
```

- [ ] **Step 8.6: Run all updated orchestrator + downstream tests to verify**

Run: `.venv/bin/pytest tests/unit/test_exporter_orchestrator.py tests/unit/test_exporter_vla_compat.py tests/unit/test_exporter_stats.py tests/unit/test_exporter_info_json.py -v`
Expected: ALL PASS. The three new tests (`test_orchestrator_fails_when_robot_type_unknown_and_no_override`, `test_orchestrator_uses_override_when_provided`, `test_orchestrator_raises_on_inconsistent_proprio_dim_across_episodes`) plus all pre-existing tests (now using the Step 8.1-updated `_seed_dataset` with default SO101 metadata).

- [ ] **Step 8.7: Commit**

```bash
git add backend/mimicrec/datasets/exporters/orchestrator.py tests/unit/test_exporter_orchestrator.py
git commit -m "$(cat <<'EOF'
feat(exporter): orchestrator wires gripper_convention + proprio_layout

Reads convention/layout from info.json or accepts ExportOverride
(robot_type='so101' or 'rebot' on the request body). Derives n_proprio from converted tables
and raises on per-episode mismatch. Writes three stats files
(action mean/std + action q99 + proprio q99) for the inference
contract decoder and the future X-VLA loader.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Expose `robot_type` override on the export API route

**Files:**
- Modify: `backend/mimicrec/api/schemas.py` (add field to export request schema)
- Modify: `backend/mimicrec/api/routes/datasets.py` (thread override into orchestrator call)
- Modify: `tests/api/test_export_routes.py` (extend; this file already exercises the export route per `find . -name test_export_routes.py`)

- [ ] **Step 9.1: Inspect existing export route + schema + test pattern**

Run these to get the concrete request-model class name, the route handler signature, and the existing test-route fixture pattern (TestClient setup + dataset-bootstrap helper):

```bash
.venv/bin/grep -n "ExportFormat\|class.*Export\|export_dataset" backend/mimicrec/api/schemas.py backend/mimicrec/api/routes/datasets.py
.venv/bin/cat tests/api/test_export_routes.py | head -100
```

Note the request-model class name (look for the model with `format: ExportFormat`) and any helper used to bootstrap a dataset for the route test; you will reuse both in Step 9.2.

- [ ] **Step 9.2: Write failing route test in `tests/api/test_export_routes.py`**

Append at the bottom of the file (replace `<ExistingFixture>` and `<ExistingBootstrap>` with whatever the file already uses — both names should be visible from the Step 9.1 `cat` output):

```python
def test_export_route_accepts_robot_type_override(<ExistingFixture>, tmp_path):
    """Legacy datasets (info.json robot_type=unknown) must export
    successfully when the request body carries robot_type='so101'."""
    # Bootstrap an unknown-robot dataset with two frames (n>=2 required).
    ds_name = "legacy_so101"
    <ExistingBootstrap>(ds_name, num_frames=2)
    resp = <ExistingFixture>.post(
        f"/datasets/{ds_name}/export",
        json={
            "format": "VLA_COMPAT",
            "instruction_template": "{task}",
            "force": True,
            "robot_type": "so101",
        },
    )
    assert resp.status_code == 200, resp.text
    # Resulting info.json should carry robot_type='SO101Adapter'
    import json
    from mimicrec.api.deps import get_vla_dest_root    # adjust if needed
    dest_root = get_vla_dest_root(<ExistingFixture>.app)
    info = json.loads((dest_root / ds_name / "meta" / "info.json").read_text())
    assert info["robot_type"] == "SO101Adapter"
```

- [ ] **Step 9.3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/api/test_export_routes.py::test_export_route_accepts_robot_type_override -v`
Expected: FAIL — either Pydantic rejects the unknown `robot_type` field (422) or the orchestrator raises ValueError because the route doesn't yet pass the override.

- [ ] **Step 9.4: Add `robot_type` field to the export request schema in `backend/mimicrec/api/schemas.py`**

Locate the export request model class (the one with the `format: ExportFormat` field) and add an optional `robot_type` field. Example (adapt the class name):

```python
class ExportDatasetRequest(BaseModel):
    # ... existing fields (format, instruction_template, force, etc.) ...
    robot_type: str | None = Field(
        default=None,
        description=(
            "Override for legacy datasets where info.json declares "
            "robot_type='unknown'. Allowed values: 'so101', 'rebot'."
        ),
    )
```

- [ ] **Step 9.5: Thread the override in `backend/mimicrec/api/routes/datasets.py`**

In the export-route handler that calls `export_dataset_to_local(...)`, construct `ExportOverride` from the request body:

```python
from mimicrec.datasets.exporters.orchestrator import (
    export_dataset_to_local, ExportOverride,
)

# inside the handler:
override = (
    ExportOverride(robot_type=body.robot_type) if body.robot_type else None
)
result = export_dataset_to_local(
    ds_root=ds_root,
    dest_root=dest_root,
    format=body.format,
    instruction_template=body.instruction_template,
    force=body.force,
    override=override,
)
```

- [ ] **Step 9.6: Run the route test to verify it passes**

Run: `.venv/bin/pytest tests/api/test_export_routes.py -v`
Expected: existing tests PASS; new override test PASSES.

- [ ] **Step 9.7: Commit**

```bash
git add backend/mimicrec/api/schemas.py backend/mimicrec/api/routes/datasets.py tests/api/test_export_routes.py
git commit -m "$(cat <<'EOF'
feat(api): expose robot_type override on export route

Lets operators re-export legacy datasets (info.json robot_type=unknown)
by passing 'so101' or 'rebot' on the export request body. Forwards to
ExportOverride at the orchestrator boundary.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Integration test (roundtrip + short-episode boundary)

**Files:**
- Modify: `tests/integration/test_vla_compat_roundtrip.py`

- [ ] **Step 10.1: Read existing roundtrip test**

Run: `.venv/bin/cat tests/integration/test_vla_compat_roundtrip.py`

- [ ] **Step 10.2: Replace test contents with the multi-fixture version**

```python
"""End-to-end roundtrip for the VLA-compat exporter.

Builds tiny synthetic datasets in tmp_path for both SO-101-like and
reBot-like adapter shapes, runs export_dataset_to_local, and verifies
the output info.json + parquet schema + stats files match what the
spec promises (and what the future X-VLA loader will need).
"""
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.api.schemas import ExportFormat
from mimicrec.datasets.exporters.orchestrator import (
    ExportOverride, export_dataset_to_local,
)
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths


def _write_so101_episode(ds_root: Path, episode_index: int, n: int = 16):
    p = dataset_paths(ds_root)
    chunk_dir = p.data_dir / "chunk-000"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table({
        "timestamp": [i / 15.0 for i in range(n)],
        "tick_t_mono_ns": [1_000_000_000 + i for i in range(n)],
        "observation.state.joint_pos": [
            [float(i), 0.0, 0.0, 0.0, 0.0, 50.0] for i in range(n)
        ],
        "observation.state.gripper_pos": [50.0] * n,
        "observation.state.ee_pos": [
            [0.1 + 0.001 * i, 0.2, 0.3] for i in range(n)
        ],
        "observation.state.ee_rotvec": [[0.0, 0.0, 0.0]] * n,
        "frame_index": list(range(n)),
        "episode_index": [episode_index] * n,
        "index": list(range(n)),
        "task_index": [0] * n,
    })
    pq.write_table(
        table, chunk_dir / f"episode_{episode_index:06d}.parquet",
    )


def _write_rebot_episode(ds_root: Path, episode_index: int, n: int = 16):
    p = dataset_paths(ds_root)
    chunk_dir = p.data_dir / "chunk-000"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table({
        "timestamp": [i / 15.0 for i in range(n)],
        "tick_t_mono_ns": [1_000_000_000 + i for i in range(n)],
        "observation.state.joint_pos": [
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.6] for _ in range(n)
        ],
        "observation.state.gripper_pos": [0.5] * n,
        "observation.state.ee_pos": [
            [0.1 + 0.001 * i, 0.2, 0.3] for i in range(n)
        ],
        "observation.state.ee_rotvec": [[0.0, 0.0, 0.0]] * n,
        "frame_index": list(range(n)),
        "episode_index": [episode_index] * n,
        "index": list(range(n)),
        "task_index": [0] * n,
    })
    pq.write_table(
        table, chunk_dir / f"episode_{episode_index:06d}.parquet",
    )


def _bootstrap_meta(ds_root: Path, *, robot_type: str | None = None,
                    gripper_convention: dict | None = None,
                    proprio_layout: dict | None = None):
    init_dataset(
        ds_root, fps=15, joint_names=[], camera_names=[],
        robot_type=robot_type,
        gripper_convention=gripper_convention,
        proprio_layout=proprio_layout,
    )
    # Minimal episodes.parquet so build_archive_stream doesn't blow up.
    p = dataset_paths(ds_root)
    p.episodes_dir.mkdir(parents=True, exist_ok=True)
    chunk0 = p.episodes_dir / "chunk-000"
    chunk0.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({"episode_index": [0], "tasks": [["pick up"]]}),
        chunk0 / "file-000.parquet",
    )


def test_roundtrip_so101_with_proper_metadata(tmp_path):
    ds = tmp_path / "so101_ds"
    _bootstrap_meta(
        ds,
        robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout={
            "columns": ["observation.state.joint_pos"],
            "output_names": ["shoulder_pan", "shoulder_lift", "elbow_flex",
                             "wrist_flex", "wrist_roll", "gripper"],
            "gripper_via_column": "observation.state.joint_pos",
            "gripper_index_in_column": 5,
        },
    )
    _write_so101_episode(ds, episode_index=0, n=16)

    dest = tmp_path / "out"
    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest, format=ExportFormat.VLA_COMPAT,
        instruction_template="pick up", force=True,
    )

    out_meta = result.dest_path / "meta"
    info = json.loads((out_meta / "info.json").read_text())
    assert info["features"]["action"]["shape"] == [7]
    assert info["features"]["observation.state"]["shape"] == [6]
    assert info["robot_type"] == "SO101Adapter"

    for fname in ("action_stats.json", "action_stats_q99.json",
                  "proprio_stats_q99.json"):
        assert (out_meta / fname).exists(), fname

    a_stats = json.loads((out_meta / "action_stats.json").read_text())
    assert a_stats["convention"] == "q99_derived_midpoint_halfrange"
    assert len(a_stats["mean"]) == 7

    p_q99 = json.loads((out_meta / "proprio_stats_q99.json").read_text())
    assert len(p_q99["q01"]) == 6


def test_roundtrip_rebot_via_override_on_unknown_dataset(tmp_path):
    ds = tmp_path / "rebot_ds"
    _bootstrap_meta(ds)    # robot_type=unknown, no convention/layout
    _write_rebot_episode(ds, episode_index=0, n=16)

    dest = tmp_path / "out"
    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest, format=ExportFormat.VLA_COMPAT,
        instruction_template="pick up", force=True,
        override=ExportOverride(robot_type="rebot"),
    )

    out_meta = result.dest_path / "meta"
    info = json.loads((out_meta / "info.json").read_text())
    assert info["robot_type"] == "ReBotArmZmqAdapter"
    assert info["features"]["observation.state"]["shape"] == [7]


def test_roundtrip_short_episode_n_equals_action_chunk_len(tmp_path):
    """Boundary: an n=8 input episode (matching X-VLA's action_chunk_len=8)
    exports out_n=7 rows successfully. The exporter is loader-agnostic;
    the future X-VLA loader is responsible for filtering exported episodes
    too short for a complete chunk (documented in spec §Goals item 6)."""
    ds = tmp_path / "short_ds"
    _bootstrap_meta(
        ds,
        robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout={
            "columns": ["observation.state.joint_pos"],
            "output_names": ["shoulder_pan", "shoulder_lift", "elbow_flex",
                             "wrist_flex", "wrist_roll", "gripper"],
            "gripper_via_column": "observation.state.joint_pos",
            "gripper_index_in_column": 5,
        },
    )
    _write_so101_episode(ds, episode_index=0, n=8)

    dest = tmp_path / "out"
    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest, format=ExportFormat.VLA_COMPAT,
        instruction_template="pick up", force=True,
    )
    out_pq = result.dest_path / "data" / "chunk-000" / "episode_000000.parquet"
    table = pq.read_table(out_pq)
    assert table.num_rows == 7
```

- [ ] **Step 10.3: Run integration tests**

Run: `.venv/bin/pytest tests/integration/test_vla_compat_roundtrip.py -v`
Expected: 3 PASSED.

If `build_archive_stream(ds_root)` (called from `_export_vla_compat` to copy `meta/episodes/chunk-000/file-000.parquet`) raises because the synthetic dataset is missing additional metadata not produced by `_bootstrap_meta`, run the existing pre-Task-10 roundtrip test once with `pytest -v -x` to see exactly what column or file it expects, then add it to `_bootstrap_meta`. The existing test in this file before the rewrite will tell you the minimal shape — diff against the helper above.

- [ ] **Step 10.4: Commit**

```bash
git add tests/integration/test_vla_compat_roundtrip.py
git commit -m "$(cat <<'EOF'
test(integration): roundtrip vla_compat for SO-101 / reBot + short-episode boundary

Covers: SO-101 with proper info.json metadata, reBot via request-body override
on a legacy unknown-robot dataset, and the n=action_chunk_len boundary
case where exporter outputs n-1=7 rows (loader's responsibility to
filter for full chunks).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Documentation note for legacy override

**Files:**
- Modify: `configs/inference/README.md`

- [ ] **Step 11.1: Read current README**

Run: `.venv/bin/cat configs/inference/README.md | head -80`

- [ ] **Step 11.2: Append a "Legacy datasets" section**

Add to the end of `configs/inference/README.md`:

```markdown

## Re-exporting legacy datasets recorded before the ee_delta refactor

Datasets recorded before the recording-layer change in this PR have
`info.json` `robot_type: "unknown"` and no `gripper_convention` /
`proprio_layout` fields. The exporter rejects these by default to
prevent silent gripper-polarity inversion.

Pass `robot_type=so101` or `robot_type=rebot` (the `robot_type`
field on the export API request) to override:

    POST /datasets/<name>/export
    {
      "format": "VLA_COMPAT",
      "instruction_template": "{task}",
      "robot_type": "so101"
    }

The override only adds the convention + layout the exporter would have
read from `info.json`. The output `info.json` is written with
`robot_type` set to the real adapter class name (e.g. `SO101Adapter`).
```

- [ ] **Step 11.3: Verify the appended section renders coherently**

Run: `.venv/bin/grep -A20 "Re-exporting legacy datasets" configs/inference/README.md`
Expected: shows the new section verbatim with the example POST body and the `robot_type='so101' / 'rebot'` description.

- [ ] **Step 11.4: Commit**

```bash
git add configs/inference/README.md
git commit -m "$(cat <<'EOF'
docs(inference): note legacy-dataset robot_type override for export

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step F.1: Run the full test suite**

Run: `.venv/bin/pytest tests/unit/ tests/integration/ -x --tb=short`
Expected: ALL PASS. If any unrelated test breaks, the most likely cause is the `init_dataset` signature change (Task 4) — check that the new kwargs were left optional and any test/fixture call site does not need to be updated.

- [ ] **Step F.2: Manual pre-merge checks (per spec §Validation)**

Re-export both real datasets:

```bash
# (assumes the dev backend is running with the new code; substitute
# the actual export endpoint if different)
curl -sX POST http://localhost:8000/datasets/SO101/export \
  -H "Content-Type: application/json" \
  -d '{"format":"VLA_COMPAT","instruction_template":"{task}","robot_type":"so101","force":true}'

curl -sX POST 'http://localhost:8000/datasets/learn%20data%20bottle/export' \
  -H "Content-Type: application/json" \
  -d '{"format":"VLA_COMPAT","instruction_template":"{task}","robot_type":"rebot","force":true}'
```

Spot-check stats:
- Open `<dest>/SO101/meta/action_stats_q99.json`. Position dims (0..2) `q01`/`q99` should be in single-digit cm range; rotation dims (3..5) under ~0.5 rad; gripper dim (6) `q01 ≈ 0`, `q99 ≈ 1`.
- Open `<dest>/learn data bottle/meta/action_stats_q99.json`. Confirm gripper dim `q01 ≈ 0` and `q99 ≈ 1`. **If not, the inferred reBot `(closed_at=1, open_at=0)` does not match the recorded distribution; the convention needs measured calibration, not the mapper-config inference.** File a follow-up issue.
- Open `<dest>/SO101/meta/proprio_stats_q99.json`: 6 dims, widths roughly match each SO-101 joint's operating range.
- Open `<dest>/learn data bottle/meta/proprio_stats_q99.json`: 7 dims; last dim (gripper_pos) within `[0, 1]` (normalized open-close command, NOT a hardware-measured radian angle).

Document any anomalies in the PR description.

- [ ] **Step F.3: Push branch and open PR**

```bash
git push -u origin feat/vla-inference
gh pr create --title "feat(exporter): VLA-compat export ee_delta + per-robot proprio" \
  --body "Implements docs/superpowers/specs/2026-05-06-vla-export-ee-delta-design.md.

## Summary
- Action label: \`[ee_delta(6, m + axis-angle rad, ee_local), gripper(1, [0,1])]\`
- observation.state: per-robot verbatim from adapter \`ProprioLayout\`
- Recording-session bootstrap writes adapter declarations into \`info.json\`
- Triple stats output (mean/std + q01/q99 + proprio q01/q99)
- Last frame dropped (n → n-1) to remove zero-pad chicken-and-egg with future loader
- \`robot_type\` request-body override for legacy datasets

## Hard prerequisites for downstream consumers
1. **Inference**: contract YAML follow-up (\`gemma_libero_v1.yaml\`) must declare \`normalization.method\` matching \`physical = mean + arr * std\` semantic and update operator-facing docs. Until then, do NOT deploy a model trained on this export to the live robot.
2. **Training**: X-VLA-Adapter side needs a new \`configs/data/lerobot_so101.yaml\` + dataset loader that consumes the exported parquets and wraps the stats files into \`data/norm_stats/<dataset>.json\` per-dataset-key format.

## Test plan
- [ ] \`pytest tests/unit/ tests/integration/ -v\` passes locally
- [ ] Manual re-export of \`datasets/SO101/\` and \`datasets/learn data bottle/\` with \`robot_type\` body-field overrides
- [ ] Spot-check stats files per \"Final verification\" section in the implementation plan
- [ ] Confirm reBot empirical gripper q01 ≈ 0 / q99 ≈ 1 (else open follow-up for measured calibration)

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
