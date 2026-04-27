# VLA-Compat Dataset Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "VLA-compatible" export format to MimicRec so that recorded SO-101 datasets can be consumed directly by `vla-gemma-4` training (and any other LeRobot-style VLA pipeline) without a hand-written re-packaging step. The user picks a format and presses Export from the Datasets page; the backend writes the converted dataset to a fixed local path that `vla-gemma-4` already watches.

**Architecture:**
- A pure-function exporter pipeline (`backend/mimicrec/datasets/exporters/`) takes one `pa.Table` per episode and the dataset's `tasks.parquet`, and emits a LeRobot-v2-compatible parquet:
  - `action: float32[7]` = concat of `action.joint_pos[6]` + `action.gripper_pos`
  - `observation.state: float32[7]` = same, from observation columns
  - `language_instruction: string` (per-row) = template `"What action should the robot take to {TASK}? A:"` expanded with `tasks.parquet.instruction` (fall back to `task` name when empty)
  - all `observation.images.*` keys, `frame_index`, `episode_index`, `index`, `task_index`, `timestamp` preserved
  - extra observation columns (`joint_vel/effort/ee_pos/ee_rotvec`) and action columns (`ee_pos/ee_rotvec/t_mono_ns`, `tick_t_mono_ns`) dropped
- `meta/info.json` is rewritten so `features.action.shape == [7]`, `features["observation.state"].shape == [7]`, plus a `language_instruction` feature entry. `meta/action_stats.json` is generated synchronously (mean/std over all kept action columns) in the format `Normalizer.load()` expects.
- A new `POST /api/datasets/{ds}/export` route orchestrates the conversion and writes the result tree under `<vla_dest_root>/<dataset_name>/`, where `vla_dest_root` defaults to `~/vla-gemma-4/data/local/` but is overridable via env var `MIMICREC_VLA_DEST_ROOT`. Existing dataset dir → 409; client retries with `force=true` to overwrite.
- The existing `GET /api/datasets/{ds}/archive` route gains a `format=lerobot_v3_native|vla_compat` query param. `vla_compat` is **not** offered through the zip path (returns 400 with a hint pointing at the new POST). The frontend Datasets page replaces the old `<a download>` button with a small Export modal that drives both code paths.
- Cloud upload (HF Hub etc.) is out of scope here; explicitly deferred to a Phase 2 plan.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, `pyarrow`, `pyarrow.parquet`, existing `mimicrec.datasets.archive` for the v3-native path, `pytest` + `httpx.AsyncClient` for tests.
- Frontend: React + TypeScript, TanStack Query (`useMutation`), shadcn-ui style components already used in `frontend/src/components/`.
- Spec source of truth: this document. The discussion thread that produced the design lives in the conversation that created this file (2026-04-27); decisions captured below override that thread when in conflict.

---

## File structure (locked in before tasks)

```
MimicRec/
  backend/mimicrec/
    api/
      deps.py                                 # MODIFY (add get_vla_dest_root)
      schemas.py                              # MODIFY (add ExportFormat, ExportRequest, ExportResponse)
      routes/
        datasets.py                           # MODIFY (add POST /export, format query on GET /archive)
    datasets/
      exporters/                              # NEW package
        __init__.py
        instructions.py                       # template expansion (pure)
        vla_compat.py                         # per-table conversion (pure)
        info_json.py                          # info.json rewrite (pure)
        stats.py                              # action_stats compute (pure)
        orchestrator.py                       # tree-level write + force/conflict handling
        errors.py                             # DestinationExistsError + DisallowedFormatError
  tests/
    unit/
      test_exporter_instructions.py           # NEW
      test_exporter_vla_compat.py             # NEW
      test_exporter_info_json.py              # NEW
      test_exporter_stats.py                  # NEW
      test_exporter_orchestrator.py           # NEW
    api/
      test_export_routes.py                   # NEW (POST /export)
      test_dataset_routes.py                  # MODIFY (add format query coverage)
    integration/
      test_vla_compat_roundtrip.py            # NEW (LeRobotDataset readback if installed)
  frontend/src/
    api/
      queries.ts                              # MODIFY (useExportDataset)
      types.ts                                # MODIFY (ExportFormat, ExportRequest, ExportResponse)
    components/
      ExportDatasetModal.tsx                  # NEW
    pages/
      DatasetsPage.tsx                        # MODIFY (replace Download <a> with Export button + modal)
```

**Decomposition rules followed:**
- Each pure file does one thing (template / table convert / info rewrite / stats / orchestrate). Tests are 1:1.
- The orchestrator depends on the four pure modules + the existing `dataset_layout` + the existing `archive.build_archive_stream`; nothing else in the backend changes shape.
- Routes stay thin — they validate Pydantic input, resolve the dest root, hand off to the orchestrator, and translate two custom exceptions into HTTP codes.
- Frontend additions follow the existing `useMutation` + `apiFetch` pattern in `queries.ts`.

---

## Conventions used in this plan

- Each task is **TDD red → green**. Steps inside a task: write failing test, run it, see it fail, implement, run it, see it pass, commit.
- Commit messages use the existing repo style (`feat:`, `test:`, `refactor:`, `docs:`).
- Run all tests from the repo root unless otherwise noted; the backend test alias is `bash scripts/test.sh tests/<path>`.
- All file paths in tasks are absolute from the repo root (`/home/takakimaeda/MimicRec/`); the agent may strip the prefix when invoking tools.
- "Pure module" means: no I/O, no mutation of inputs, deterministic. Tests construct `pa.Table` literals.

---

## Phase A — Foundations

### Task 1: Add `get_vla_dest_root` and `ExportFormat`/`ExportRequest`/`ExportResponse` Pydantic models

**Files:**
- Modify: `backend/mimicrec/api/deps.py`
- Modify: `backend/mimicrec/api/schemas.py`
- Test: `tests/unit/test_exporter_orchestrator.py` (we'll start it here just for the dep getter; the orchestrator tests come in Task 6)

The dest-root accessor mirrors the pattern of `get_configs_root` / `get_datasets_root` (env var first, then `app.state` override for tests).

- [ ] **Step 1.1: Write the failing tests for `get_vla_dest_root`**

Create `tests/unit/test_exporter_orchestrator.py` with this content (only this test for now — orchestrator tests will be appended in Task 6):

```python
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mimicrec.api.deps import get_vla_dest_root


def _fake_app(state_value=None):
    app = MagicMock()
    app.state = MagicMock()
    app.state.vla_dest_root = state_value
    return app


def test_vla_dest_root_default(monkeypatch):
    monkeypatch.delenv("MIMICREC_VLA_DEST_ROOT", raising=False)
    app = _fake_app(state_value=None)
    assert get_vla_dest_root(app) == Path("~/vla-gemma-4/data/local").expanduser()


def test_vla_dest_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    app = _fake_app(state_value=None)
    assert get_vla_dest_root(app) == tmp_path.expanduser()


def test_vla_dest_root_state_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", "/should/be/ignored")
    app = _fake_app(state_value=tmp_path)
    assert get_vla_dest_root(app) == tmp_path
```

- [ ] **Step 1.2: Run the tests — expect ImportError**

```bash
bash scripts/test.sh tests/unit/test_exporter_orchestrator.py -q
```
Expected: `ImportError: cannot import name 'get_vla_dest_root' from 'mimicrec.api.deps'`.

- [ ] **Step 1.3: Implement `get_vla_dest_root` in `backend/mimicrec/api/deps.py`**

Add this function next to the existing `get_datasets_root`:

```python
def get_vla_dest_root(app) -> Path:
    root = getattr(app.state, "vla_dest_root", None)
    if root is None:
        import os
        root = Path(os.environ.get("MIMICREC_VLA_DEST_ROOT", "~/vla-gemma-4/data/local"))
    return Path(root).expanduser()
```

Also extend `app.state` initialization in `backend/mimicrec/api/app.py` (`create_app`) to declare the new field for test fixtures:

```python
app.state.vla_dest_root = None
```

- [ ] **Step 1.4: Run the tests — expect green**

```bash
bash scripts/test.sh tests/unit/test_exporter_orchestrator.py -q
```
Expected: 3 passed.

- [ ] **Step 1.5: Add the export Pydantic models in `backend/mimicrec/api/schemas.py`**

Append at the bottom of the file:

```python
from enum import Enum


class ExportFormat(str, Enum):
    LEROBOT_V3_NATIVE = "lerobot_v3_native"
    VLA_COMPAT = "vla_compat"


DEFAULT_INSTRUCTION_TEMPLATE = "What action should the robot take to {TASK}? A:"


class ExportRequest(BaseModel):
    format: ExportFormat
    instruction_template: str = DEFAULT_INSTRUCTION_TEMPLATE
    force: bool = False


class ExportResponse(BaseModel):
    dest_path: str
    format: ExportFormat
    num_episodes: int
    num_frames: int
    warnings: list[str] = []
```

No tests for the schemas themselves — they get exercised in Task 7 (the route).

- [ ] **Step 1.6: Commit**

```bash
git add backend/mimicrec/api/deps.py backend/mimicrec/api/app.py backend/mimicrec/api/schemas.py tests/unit/test_exporter_orchestrator.py
git commit -m "feat(api): add get_vla_dest_root and ExportFormat/ExportRequest/ExportResponse"
```

---

## Phase B — Pure exporter modules

### Task 2: Instruction template expansion (`exporters/instructions.py`)

Pure function that takes a template plus a single `tasks.parquet` row and produces the per-frame instruction string. Falls back to the `task` name when `instruction` is empty/None.

**Files:**
- Create: `backend/mimicrec/datasets/exporters/__init__.py` (empty)
- Create: `backend/mimicrec/datasets/exporters/instructions.py`
- Test: `tests/unit/test_exporter_instructions.py`

- [ ] **Step 2.1: Write failing tests**

Create `tests/unit/test_exporter_instructions.py`:

```python
import pytest

from mimicrec.datasets.exporters.instructions import (
    expand_instruction,
    InstructionWarning,
)


def test_expand_with_instruction_filled():
    out = expand_instruction(
        template="What action should the robot take to {TASK}? A:",
        task_name="tape_on_bottle",
        instruction="Pick up the tape and place it on top of the bottle",
    )
    assert out.text == (
        "What action should the robot take to "
        "Pick up the tape and place it on top of the bottle? A:"
    )
    assert out.warnings == []


def test_expand_falls_back_to_task_name_when_instruction_empty():
    out = expand_instruction(
        template="What action should the robot take to {TASK}? A:",
        task_name="tape_on_bottle",
        instruction="",
    )
    assert "tape_on_bottle" in out.text
    assert out.warnings == [
        InstructionWarning.MISSING_INSTRUCTION_FALLBACK_TO_TASK_NAME
    ]


def test_expand_falls_back_when_instruction_is_none():
    out = expand_instruction(
        template="do {TASK}",
        task_name="x",
        instruction=None,
    )
    assert out.text == "do x"
    assert out.warnings == [
        InstructionWarning.MISSING_INSTRUCTION_FALLBACK_TO_TASK_NAME
    ]


def test_template_without_task_placeholder_is_used_verbatim():
    out = expand_instruction(
        template="static prompt",
        task_name="anything",
        instruction="anything",
    )
    assert out.text == "static prompt"
    assert out.warnings == []


def test_template_with_multiple_placeholders_replaces_all():
    out = expand_instruction(
        template="{TASK} then {TASK}",
        task_name="x",
        instruction="grab the cube",
    )
    assert out.text == "grab the cube then grab the cube"
```

- [ ] **Step 2.2: Run — expect ImportError**

```bash
bash scripts/test.sh tests/unit/test_exporter_instructions.py -q
```
Expected: ImportError.

- [ ] **Step 2.3: Implement**

Create `backend/mimicrec/datasets/exporters/__init__.py` empty, then create `backend/mimicrec/datasets/exporters/instructions.py`:

```python
"""Instruction-template expansion for VLA-compat export.

Pure: no I/O, deterministic, inputs not mutated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InstructionWarning(str, Enum):
    MISSING_INSTRUCTION_FALLBACK_TO_TASK_NAME = (
        "missing_instruction_fallback_to_task_name"
    )


@dataclass(frozen=True)
class ExpandedInstruction:
    text: str
    warnings: list[InstructionWarning] = field(default_factory=list)


def expand_instruction(
    *,
    template: str,
    task_name: str,
    instruction: str | None,
) -> ExpandedInstruction:
    """Expand ``{TASK}`` in ``template`` using ``instruction`` (preferred) or
    ``task_name`` (fallback). Returns the rendered string plus any warnings.
    """
    warnings: list[InstructionWarning] = []
    chosen = instruction if instruction else None
    if chosen is None:
        chosen = task_name
        warnings.append(
            InstructionWarning.MISSING_INSTRUCTION_FALLBACK_TO_TASK_NAME
        )
    text = template.replace("{TASK}", chosen)
    return ExpandedInstruction(text=text, warnings=warnings)
```

- [ ] **Step 2.4: Run — expect green**

```bash
bash scripts/test.sh tests/unit/test_exporter_instructions.py -q
```
Expected: 5 passed.

- [ ] **Step 2.5: Commit**

```bash
git add backend/mimicrec/datasets/exporters/__init__.py backend/mimicrec/datasets/exporters/instructions.py tests/unit/test_exporter_instructions.py
git commit -m "feat(exporters): instruction template expansion with task-name fallback"
```

---

### Task 3: Per-episode `pa.Table` conversion (`exporters/vla_compat.py`)

Takes one episode `pa.Table` (the existing schema written by `parquet_row.py`) plus the already-expanded per-row `language_instruction` strings, and returns a new `pa.Table` with the VLA-compat schema. Pure.

**Files:**
- Create: `backend/mimicrec/datasets/exporters/vla_compat.py`
- Test: `tests/unit/test_exporter_vla_compat.py`

- [ ] **Step 3.1: Write failing tests**

Create `tests/unit/test_exporter_vla_compat.py`:

```python
import numpy as np
import pyarrow as pa
import pytest

from mimicrec.datasets.exporters.vla_compat import (
    convert_episode_table,
    ConvertedEpisode,
)


def _fake_input_table(num_frames: int = 3) -> pa.Table:
    """Mimic the schema produced by recording.parquet_row.sample_bundle_to_row."""
    return pa.table({
        "timestamp": [i * 1.0 / 15 for i in range(num_frames)],
        "tick_t_mono_ns": [1_000_000_000 + i for i in range(num_frames)],
        "observation.state.joint_pos": [[0.1] * 6 for _ in range(num_frames)],
        "observation.state.joint_vel": [[0.0] * 6 for _ in range(num_frames)],
        "observation.state.joint_effort": [[0.0] * 6 for _ in range(num_frames)],
        "observation.state.t_mono_ns": [0 for _ in range(num_frames)],
        "observation.state.ee_pos": [[0.1, 0.2, 0.3] for _ in range(num_frames)],
        "observation.state.ee_rotvec": [[0.0, 0.0, 0.0] for _ in range(num_frames)],
        "observation.state.gripper_pos": [0.5 for _ in range(num_frames)],
        "action.joint_pos": [[0.2] * 6 for _ in range(num_frames)],
        "action.t_mono_ns": [0 for _ in range(num_frames)],
        "action.ee_pos": [[0.1, 0.2, 0.3] for _ in range(num_frames)],
        "action.ee_rotvec": [[0.0, 0.0, 0.0] for _ in range(num_frames)],
        "action.gripper_pos": [0.7 for _ in range(num_frames)],
        "frame_index": list(range(num_frames)),
        "episode_index": [0] * num_frames,
        "index": list(range(num_frames)),
        "task_index": [0] * num_frames,
        "observation.images.front.video_frame_index": list(range(num_frames)),
        "observation.images.front.t_mono_ns": [0] * num_frames,
        "observation.images.wrist.video_frame_index": list(range(num_frames)),
        "observation.images.wrist.t_mono_ns": [0] * num_frames,
    })


def test_convert_produces_action_and_state_as_fixed7_columns():
    table = _fake_input_table(num_frames=3)
    out = convert_episode_table(
        table=table, instruction_text="prompt-x",
    )
    assert isinstance(out, ConvertedEpisode)
    cols = set(out.table.column_names)
    assert "action" in cols
    assert "observation.state" in cols
    # Extra observation columns are dropped.
    assert "observation.state.joint_vel" not in cols
    assert "observation.state.joint_effort" not in cols
    assert "observation.state.ee_pos" not in cols
    assert "observation.state.ee_rotvec" not in cols
    # Extra action columns are dropped.
    assert "action.ee_pos" not in cols
    assert "action.ee_rotvec" not in cols
    assert "action.t_mono_ns" not in cols
    assert "tick_t_mono_ns" not in cols
    # The per-axis "raw" joint/gripper columns are dropped too — we keep only
    # the unified action/observation.state vectors per the spec.
    assert "observation.state.joint_pos" not in cols
    assert "observation.state.gripper_pos" not in cols
    assert "action.joint_pos" not in cols
    assert "action.gripper_pos" not in cols


def test_convert_action_values_are_joint6_concat_gripper():
    table = pa.table({
        "timestamp": [0.0, 0.1],
        "observation.state.joint_pos": [[1, 2, 3, 4, 5, 6], [10, 20, 30, 40, 50, 60]],
        "observation.state.gripper_pos": [0.5, 0.7],
        "action.joint_pos": [[7, 8, 9, 10, 11, 12], [70, 80, 90, 100, 110, 120]],
        "action.gripper_pos": [0.1, 0.9],
        "frame_index": [0, 1],
        "episode_index": [0, 0],
        "index": [0, 1],
        "task_index": [0, 0],
    })
    out = convert_episode_table(table=table, instruction_text="x")
    actions = np.array(out.table.column("action").to_pylist(), dtype=np.float32)
    states = np.array(out.table.column("observation.state").to_pylist(), dtype=np.float32)
    np.testing.assert_array_equal(
        actions,
        np.array([[7, 8, 9, 10, 11, 12, 0.1], [70, 80, 90, 100, 110, 120, 0.9]],
                 dtype=np.float32),
    )
    np.testing.assert_array_equal(
        states,
        np.array([[1, 2, 3, 4, 5, 6, 0.5], [10, 20, 30, 40, 50, 60, 0.7]],
                 dtype=np.float32),
    )


def test_convert_writes_language_instruction_per_row():
    table = _fake_input_table(num_frames=4)
    out = convert_episode_table(table=table, instruction_text="hello")
    li = out.table.column("language_instruction").to_pylist()
    assert li == ["hello"] * 4


def test_convert_preserves_video_frame_index_and_indexing_columns():
    table = _fake_input_table(num_frames=3)
    out = convert_episode_table(table=table, instruction_text="x")
    cols = set(out.table.column_names)
    for must_have in (
        "frame_index", "episode_index", "index", "task_index", "timestamp",
        "observation.images.front.video_frame_index",
        "observation.images.wrist.video_frame_index",
    ):
        assert must_have in cols, must_have


def test_convert_raises_when_required_input_column_missing():
    table = pa.table({"timestamp": [0.0]})
    with pytest.raises(ValueError, match="action.joint_pos"):
        convert_episode_table(table=table, instruction_text="x")
```

- [ ] **Step 3.2: Run — expect ImportError**

```bash
bash scripts/test.sh tests/unit/test_exporter_vla_compat.py -q
```

- [ ] **Step 3.3: Implement**

Create `backend/mimicrec/datasets/exporters/vla_compat.py`:

```python
"""Episode-table conversion to VLA-compat schema (pure)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyarrow as pa


@dataclass(frozen=True)
class ConvertedEpisode:
    table: pa.Table


_REQUIRED_INPUT_COLUMNS = (
    "observation.state.joint_pos",
    "observation.state.gripper_pos",
    "action.joint_pos",
    "action.gripper_pos",
    "frame_index",
    "episode_index",
    "index",
    "task_index",
)

# Columns that flow straight through unchanged.
_PASSTHROUGH_COLUMNS = (
    "timestamp",
    "frame_index",
    "episode_index",
    "index",
    "task_index",
)

# Columns to drop entirely from the output.
_DROP_COLUMNS = frozenset({
    "tick_t_mono_ns",
    "observation.state.joint_pos",
    "observation.state.joint_vel",
    "observation.state.joint_effort",
    "observation.state.t_mono_ns",
    "observation.state.ee_pos",
    "observation.state.ee_rotvec",
    "observation.state.gripper_pos",
    "action.joint_pos",
    "action.t_mono_ns",
    "action.ee_pos",
    "action.ee_rotvec",
    "action.gripper_pos",
})


def _stack_with_gripper(joint_col: pa.ChunkedArray, gripper_col: pa.ChunkedArray) -> list[list[float]]:
    joints = joint_col.to_pylist()
    grippers = gripper_col.to_pylist()
    if len(joints) != len(grippers):
        raise ValueError("joint and gripper columns must have the same length")
    out: list[list[float]] = []
    for j, g in zip(joints, grippers):
        if j is None or g is None:
            raise ValueError("null entries are not supported in joint/gripper columns")
        if len(j) != 6:
            raise ValueError(f"expected 6 joint values per row, got {len(j)}")
        out.append([float(x) for x in j] + [float(g)])
    return out


def convert_episode_table(*, table: pa.Table, instruction_text: str) -> ConvertedEpisode:
    """Return a new pa.Table in VLA-compat schema.

    The input ``table`` follows the schema written by
    ``mimicrec.recording.parquet_row.sample_bundle_to_row``; the output:

    - ``action: list<float32>[7]`` = joint_pos[0..5] + gripper_pos
    - ``observation.state: list<float32>[7]`` = same shape from observation
    - ``language_instruction: string`` = ``instruction_text`` repeated per row
    - all ``observation.images.<cam>.video_frame_index`` and per-camera
      ``t_mono_ns`` columns are preserved verbatim
    - all "raw" split columns and rotvec/ee_pos/joint_vel/joint_effort/
      ``tick_t_mono_ns`` are dropped
    """
    missing = [c for c in _REQUIRED_INPUT_COLUMNS if c not in table.column_names]
    if missing:
        raise ValueError(f"convert_episode_table missing required columns: {missing}")

    n = table.num_rows
    arrays: dict[str, pa.Array | list] = {}

    # action / observation.state vectors.
    arrays["action"] = pa.array(
        _stack_with_gripper(
            table.column("action.joint_pos"),
            table.column("action.gripper_pos"),
        ),
        type=pa.list_(pa.float32(), 7),
    )
    arrays["observation.state"] = pa.array(
        _stack_with_gripper(
            table.column("observation.state.joint_pos"),
            table.column("observation.state.gripper_pos"),
        ),
        type=pa.list_(pa.float32(), 7),
    )

    # language_instruction.
    arrays["language_instruction"] = pa.array([instruction_text] * n, type=pa.string())

    # passthrough scalar columns.
    for col in _PASSTHROUGH_COLUMNS:
        if col in table.column_names:
            arrays[col] = table.column(col)

    # camera columns: preserve every ``observation.images.<cam>.<suffix>`` column.
    for col in table.column_names:
        if col.startswith("observation.images.") and col not in arrays:
            arrays[col] = table.column(col)

    # Anything else not in _DROP_COLUMNS and not already added stays too.
    # (Defensive — current schema has nothing else, but future fields shouldn't
    # silently disappear.)
    for col in table.column_names:
        if col in arrays or col in _DROP_COLUMNS:
            continue
        arrays[col] = table.column(col)

    out = pa.table(arrays)
    return ConvertedEpisode(table=out)
```

- [ ] **Step 3.4: Run — expect green**

```bash
bash scripts/test.sh tests/unit/test_exporter_vla_compat.py -q
```
Expected: 5 passed.

- [ ] **Step 3.5: Commit**

```bash
git add backend/mimicrec/datasets/exporters/vla_compat.py tests/unit/test_exporter_vla_compat.py
git commit -m "feat(exporters): per-episode table conversion to VLA-compat schema"
```

---

### Task 4: `info.json` rewrite (`exporters/info_json.py`)

Pure rewrite of the LeRobot `info.json` so its `features` block matches the new on-disk shape. Keeps everything else (codebase_version, fps, video_path templates, splits, total_episodes, total_frames, tasks count) verbatim.

**Files:**
- Create: `backend/mimicrec/datasets/exporters/info_json.py`
- Test: `tests/unit/test_exporter_info_json.py`

- [ ] **Step 4.1: Write failing tests**

Create `tests/unit/test_exporter_info_json.py`:

```python
import json

import pytest

from mimicrec.datasets.exporters.info_json import to_vla_info


def _make_input_info(joint_names: list[str]) -> dict:
    dof = len(joint_names)
    return {
        "codebase_version": "v3.0",
        "robot_type": "so101_follower",
        "total_episodes": 9,
        "total_frames": 1183,
        "total_tasks": 1,
        "chunks_size": 1000,
        "fps": 15,
        "splits": {"train": "0:9"},
        "data_path": "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{episode_index:06d}.mp4",
        "features": {
            "action": {"dtype": "float32", "shape": [dof], "names": joint_names},
            "observation.state": {"dtype": "float32", "shape": [dof], "names": joint_names},
            "timestamp": {"dtype": "float32", "shape": [1], "names": None},
            "frame_index": {"dtype": "int64", "shape": [1], "names": None},
            "episode_index": {"dtype": "int64", "shape": [1], "names": None},
            "index": {"dtype": "int64", "shape": [1], "names": None},
            "task_index": {"dtype": "int64", "shape": [1], "names": None},
            "observation.images.front": {
                "dtype": "video",
                "shape": [480, 640, 3],
                "names": ["height", "width", "channels"],
                "info": {"video.height": 480, "video.width": 640, "video.fps": 15},
            },
        },
    }


def test_action_and_observation_state_become_shape_7():
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    out = to_vla_info(info)
    assert out["features"]["action"]["shape"] == [7]
    assert out["features"]["action"]["names"] == ["j1", "j2", "j3", "j4", "j5", "j6", "gripper"]
    assert out["features"]["observation.state"]["shape"] == [7]
    assert out["features"]["observation.state"]["names"] == ["j1", "j2", "j3", "j4", "j5", "j6", "gripper"]


def test_language_instruction_feature_added():
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    out = to_vla_info(info)
    li = out["features"]["language_instruction"]
    assert li["dtype"] == "string"
    assert li["shape"] == [1]


def test_video_and_pass_through_keys_unchanged():
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    out = to_vla_info(info)
    assert out["fps"] == 15
    assert out["splits"] == {"train": "0:9"}
    assert out["features"]["observation.images.front"] == \
        info["features"]["observation.images.front"]


def test_input_dict_is_not_mutated():
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    original_action_shape = info["features"]["action"]["shape"]
    _ = to_vla_info(info)
    assert info["features"]["action"]["shape"] == original_action_shape


def test_works_when_input_action_already_has_extra_columns_definition():
    """info.json shipped by the SO-101 v3 collector declares action shape=[6]
    even though the parquet has been split. We accept either."""
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    out = to_vla_info(info)
    assert out["features"]["action"]["shape"] == [7]
```

- [ ] **Step 4.2: Run — expect ImportError**

- [ ] **Step 4.3: Implement**

Create `backend/mimicrec/datasets/exporters/info_json.py`:

```python
"""Rewrite a LeRobot info.json for VLA-compat output (pure)."""
from __future__ import annotations

import copy
from typing import Any

GRIPPER_AXIS_NAME = "gripper"


def to_vla_info(info: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied info dict with action/observation.state at shape [7]
    and a ``language_instruction`` feature added.

    The input dict is not mutated.
    """
    new = copy.deepcopy(info)
    features = new.setdefault("features", {})

    for key in ("action", "observation.state"):
        spec = features.get(key)
        if spec is None:
            spec = {"dtype": "float32", "shape": [7], "names": []}
            features[key] = spec
        names = list(spec.get("names") or [])
        # Ensure exactly 6 joint names + "gripper" — if input listed 6, append gripper;
        # if input already listed 7 with gripper at the end, leave it.
        if names and names[-1] != GRIPPER_AXIS_NAME:
            names = names[:6] + [GRIPPER_AXIS_NAME]
        elif not names:
            names = [f"joint_{i}" for i in range(6)] + [GRIPPER_AXIS_NAME]
        spec["names"] = names
        spec["shape"] = [7]
        spec["dtype"] = "float32"

    features["language_instruction"] = {
        "dtype": "string",
        "shape": [1],
        "names": None,
    }

    return new
```

- [ ] **Step 4.4: Run — expect green**

```bash
bash scripts/test.sh tests/unit/test_exporter_info_json.py -q
```
Expected: 5 passed.

- [ ] **Step 4.5: Commit**

```bash
git add backend/mimicrec/datasets/exporters/info_json.py tests/unit/test_exporter_info_json.py
git commit -m "feat(exporters): rewrite info.json for shape-7 action/state + language_instruction"
```

---

### Task 5: `action_stats.json` computation (`exporters/stats.py`)

Single-pass mean/std over all kept episode tables, written in the format `vla_gemma4.data.normalizer.Normalizer.load()` reads (`{"mean": [...], "std": [...]}`). Pure compute over already-converted `pa.Table` objects.

**Files:**
- Create: `backend/mimicrec/datasets/exporters/stats.py`
- Test: `tests/unit/test_exporter_stats.py`

- [ ] **Step 5.1: Write failing tests**

```python
import json

import numpy as np
import pyarrow as pa
import pytest

from mimicrec.datasets.exporters.stats import compute_action_stats


def _converted(action_rows: list[list[float]]) -> pa.Table:
    return pa.table({
        "action": pa.array(action_rows, type=pa.list_(pa.float32(), 7)),
    })


def test_mean_and_std_over_single_episode():
    t = _converted([[0, 0, 0, 0, 0, 0, 0], [2, 2, 2, 2, 2, 2, 2]])
    out = compute_action_stats([t])
    np.testing.assert_allclose(out["mean"], [1.0] * 7, atol=1e-6)
    np.testing.assert_allclose(out["std"], [1.0] * 7, atol=1e-6)


def test_combined_across_episodes():
    a = _converted([[0]*7, [2]*7])
    b = _converted([[4]*7, [6]*7])
    out = compute_action_stats([a, b])
    np.testing.assert_allclose(out["mean"], [3.0]*7, atol=1e-6)
    # population std for [0,2,4,6] = sqrt(5) ≈ 2.236
    np.testing.assert_allclose(out["std"], [np.std([0,2,4,6])]*7, atol=1e-6)


def test_returns_serializable_floats():
    t = _converted([[1]*7, [2]*7])
    out = compute_action_stats([t])
    s = json.dumps(out)
    assert isinstance(s, str)
    assert "mean" in s and "std" in s


def test_empty_input_raises():
    with pytest.raises(ValueError):
        compute_action_stats([])


def test_std_floor_avoids_zero_division():
    # All identical rows — std would be 0; we floor at 1e-6 to match Normalizer.fit.
    t = _converted([[1]*7] * 5)
    out = compute_action_stats([t])
    assert all(s >= 1e-6 for s in out["std"])
```

- [ ] **Step 5.2: Run — expect ImportError**

- [ ] **Step 5.3: Implement**

```python
"""Compute action_stats.json over VLA-compat episode tables (pure)."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pyarrow as pa

_STD_FLOOR = 1e-6


def compute_action_stats(tables: Iterable[pa.Table]) -> dict[str, list[float]]:
    """Compute population mean/std over the ``action`` column across tables.

    Returns ``{"mean": [...], "std": [...]}`` (length-7 list[float]).
    Matches the format ``vla_gemma4.data.normalizer.Normalizer.load`` expects.
    """
    rows: list[list[float]] = []
    for t in tables:
        rows.extend(t.column("action").to_pylist())
    if not rows:
        raise ValueError("compute_action_stats: no rows across tables")
    arr = np.asarray(rows, dtype=np.float64)
    mean = arr.mean(axis=0)
    std = arr.std(axis=0)
    std = np.maximum(std, _STD_FLOOR)
    return {"mean": [float(x) for x in mean], "std": [float(x) for x in std]}
```

- [ ] **Step 5.4: Run — expect green**

```bash
bash scripts/test.sh tests/unit/test_exporter_stats.py -q
```
Expected: 5 passed.

- [ ] **Step 5.5: Commit**

```bash
git add backend/mimicrec/datasets/exporters/stats.py tests/unit/test_exporter_stats.py
git commit -m "feat(exporters): compute action_stats.json (mean/std with std floor)"
```

---

## Phase C — Orchestrator

### Task 6: Tree-level orchestrator (`exporters/orchestrator.py` + `errors.py`)

Drives the full export:
- For `format="lerobot_v3_native"`: write the existing `build_archive_stream` output into a directory (no zip).
- For `format="vla_compat"`: load `tasks.parquet`, iterate live episodes, expand instruction per task, convert each `pa.Table`, write parquet + copy mp4 + write `info.json` + write `action_stats.json` + write `tasks.parquet` verbatim.
- Refuse if dest exists, unless `force=True` (then atomic-replace via temp dir + rename).

**Files:**
- Create: `backend/mimicrec/datasets/exporters/errors.py`
- Create: `backend/mimicrec/datasets/exporters/orchestrator.py`
- Test: `tests/unit/test_exporter_orchestrator.py` (extend the file from Task 1)

- [ ] **Step 6.1: Write failing tests** (append to existing file)

Append to `tests/unit/test_exporter_orchestrator.py`:

```python
import json
import shutil
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.api.schemas import ExportFormat, DEFAULT_INSTRUCTION_TEMPLATE
from mimicrec.datasets.exporters.errors import (
    DestinationExistsError,
    DisallowedFormatError,
)
from mimicrec.datasets.exporters.orchestrator import export_dataset_to_local
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.metadata import append_episode, upsert_task


def _seed_dataset(ds_root: Path, *, num_episodes: int, num_frames: int,
                  task_name: str, instruction: str | None) -> None:
    init_dataset(
        ds_root, fps=15,
        joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
        camera_names=["front"],
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
        # Also create a tiny mp4 placeholder so the orchestrator can copy it.
        cam_dir = p.videos_dir / "chunk-000" / "observation.images.front"
        cam_dir.mkdir(parents=True, exist_ok=True)
        (cam_dir / f"episode_{idx:06d}.mp4").write_bytes(b"\x00fake\x00")
        append_episode(p.meta_dir, {
            "episode_index": idx, "task": task_name,
            "num_frames": num_frames, "robot": "so101", "mode": "teleop",
            "cameras": ["front"],
        })


def test_vla_compat_export_writes_full_tree(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=2, num_frames=4,
                  task_name="tape_on_bottle",
                  instruction="Pick up the tape and place it on the bottle")

    result = export_dataset_to_local(
        ds_root=ds,
        dest_root=dest_root,
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=False,
    )

    out = dest_root / "ds_in"
    assert (out / "meta" / "info.json").exists()
    assert (out / "meta" / "action_stats.json").exists()
    assert (out / "meta" / "tasks.parquet").exists()
    assert (out / "data" / "chunk-000" / "episode_000000.parquet").exists()
    assert (out / "data" / "chunk-000" / "episode_000001.parquet").exists()
    assert (out / "videos" / "chunk-000" / "observation.images.front" / "episode_000000.mp4").exists()

    info = json.loads((out / "meta" / "info.json").read_text())
    assert info["features"]["action"]["shape"] == [7]
    assert info["features"]["language_instruction"]["dtype"] == "string"

    stats = json.loads((out / "meta" / "action_stats.json").read_text())
    assert len(stats["mean"]) == 7 and len(stats["std"]) == 7

    table = pq.read_table(out / "data" / "chunk-000" / "episode_000000.parquet")
    assert "action" in table.column_names
    assert "language_instruction" in table.column_names
    li = table.column("language_instruction").to_pylist()
    assert all("Pick up the tape and place it on the bottle" in row for row in li)

    assert result.num_episodes == 2
    assert result.num_frames == 8
    assert result.dest_path == out
    assert result.warnings == []


def test_vla_compat_export_warns_when_instruction_missing(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=1, num_frames=2,
                  task_name="t1", instruction="")
    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest_root,
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=False,
    )
    assert any("missing_instruction" in w for w in result.warnings)


def test_export_refuses_when_dest_exists_without_force(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=1, num_frames=1,
                  task_name="t1", instruction="i")
    (dest_root / "ds_in").mkdir(parents=True)
    with pytest.raises(DestinationExistsError):
        export_dataset_to_local(
            ds_root=ds, dest_root=dest_root,
            format=ExportFormat.VLA_COMPAT,
            instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
            force=False,
        )


def test_export_overwrites_when_force_true(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=1, num_frames=1,
                  task_name="t1", instruction="i")
    out = dest_root / "ds_in"
    out.mkdir(parents=True)
    (out / "leftover.txt").write_text("stale")

    export_dataset_to_local(
        ds_root=ds, dest_root=dest_root,
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=True,
    )
    assert not (out / "leftover.txt").exists()
    assert (out / "meta" / "info.json").exists()


def test_lerobot_v3_native_format_also_supported_via_local_path(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=1, num_frames=1,
                  task_name="t1", instruction="i")
    export_dataset_to_local(
        ds_root=ds, dest_root=dest_root,
        format=ExportFormat.LEROBOT_V3_NATIVE,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=False,
    )
    out = dest_root / "ds_in"
    assert (out / "meta" / "info.json").exists()
    assert (out / "data" / "chunk-000" / "episode_000000.parquet").exists()
```

- [ ] **Step 6.2: Run — expect ImportError**

- [ ] **Step 6.3: Implement `errors.py` and `orchestrator.py`**

`backend/mimicrec/datasets/exporters/errors.py`:

```python
"""Custom exceptions raised by the exporter pipeline."""
from __future__ import annotations


class DestinationExistsError(Exception):
    """Raised when the export destination already exists and force=False."""


class DisallowedFormatError(Exception):
    """Raised when an export channel does not support the requested format."""
```

`backend/mimicrec/datasets/exporters/orchestrator.py`:

```python
"""Orchestrate dataset export to a local directory.

Two formats:

- ``ExportFormat.LEROBOT_V3_NATIVE`` — write what ``build_archive_stream``
  yields straight to disk (same content as the existing zip download, just
  unpacked).
- ``ExportFormat.VLA_COMPAT`` — convert each episode's parquet to the
  shape-7 action/state schema, embed expanded instructions, write
  ``info.json`` rewrite + ``action_stats.json``, copy mp4s.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.api.schemas import ExportFormat
from mimicrec.datasets.archive import build_archive_stream
from mimicrec.datasets.exporters.errors import DestinationExistsError
from mimicrec.datasets.exporters.info_json import to_vla_info
from mimicrec.datasets.exporters.instructions import expand_instruction
from mimicrec.datasets.exporters.stats import compute_action_stats
from mimicrec.datasets.exporters.vla_compat import convert_episode_table
from mimicrec.datasets.reader import iter_episodes, read_dataset_info
from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk


@dataclass(frozen=True)
class ExportResult:
    dest_path: Path
    format: ExportFormat
    num_episodes: int
    num_frames: int
    warnings: list[str] = field(default_factory=list)


def export_dataset_to_local(
    *,
    ds_root: Path,
    dest_root: Path,
    format: ExportFormat,
    instruction_template: str,
    force: bool,
) -> ExportResult:
    out_dir = dest_root / ds_root.name
    if out_dir.exists():
        if not force:
            raise DestinationExistsError(str(out_dir))
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)

    if format == ExportFormat.LEROBOT_V3_NATIVE:
        return _export_v3_native(ds_root=ds_root, out_dir=out_dir, format=format)
    if format == ExportFormat.VLA_COMPAT:
        return _export_vla_compat(
            ds_root=ds_root, out_dir=out_dir, format=format,
            instruction_template=instruction_template,
        )
    raise ValueError(f"unsupported export format: {format}")


def _export_v3_native(*, ds_root: Path, out_dir: Path, format: ExportFormat) -> ExportResult:
    num_episodes = 0
    num_frames = 0
    for path_in_zip, content in build_archive_stream(ds_root):
        target = out_dir / path_in_zip
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path):
            shutil.copy2(content, target)
        else:
            target.write_bytes(content)
    info = read_dataset_info(out_dir)
    return ExportResult(
        dest_path=out_dir,
        format=format,
        num_episodes=info.get("total_episodes", 0),
        num_frames=info.get("total_frames", 0),
    )


def _load_tasks_lookup(ds_root: Path) -> dict[int, dict]:
    p = dataset_paths(ds_root)
    if not p.tasks_parquet.exists():
        return {}
    rows = pq.read_table(p.tasks_parquet).to_pylist()
    return {int(r["task_index"]): r for r in rows}


def _export_vla_compat(
    *, ds_root: Path, out_dir: Path, format: ExportFormat,
    instruction_template: str,
) -> ExportResult:
    p = dataset_paths(ds_root)
    out_meta = out_dir / "meta"
    out_meta.mkdir(parents=True, exist_ok=True)
    out_data = out_dir / "data"
    out_data.mkdir(parents=True, exist_ok=True)
    out_videos = out_dir / "videos"
    out_videos.mkdir(parents=True, exist_ok=True)

    tasks_lookup = _load_tasks_lookup(ds_root)
    warnings: list[str] = []
    converted_tables: list[pa.Table] = []
    num_episodes = 0
    num_frames = 0

    live_eps = list(iter_episodes(ds_root, include_deleted=False))
    for ep in live_eps:
        ep_idx = int(ep["episode_index"])
        task_idx = int(ep.get("task_index", 0))
        task_row = tasks_lookup.get(task_idx, {"task": ep.get("task", "unknown"), "instruction": ""})
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
        )
        out_pq_dir = out_data / f"chunk-{chunk:03d}"
        out_pq_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(out_episode.table, out_pq_dir / f"episode_{ep_idx:06d}.parquet")
        converted_tables.append(out_episode.table)
        num_episodes += 1
        num_frames += out_episode.table.num_rows

        # mp4 copy — preserve full LeRobot video tree.
        videos_chunk = p.videos_dir / f"chunk-{chunk:03d}"
        if videos_chunk.exists():
            for cam_dir in videos_chunk.iterdir():
                src_mp4 = cam_dir / f"episode_{ep_idx:06d}.mp4"
                if src_mp4.exists():
                    dst_dir = out_videos / f"chunk-{chunk:03d}" / cam_dir.name
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_mp4, dst_dir / src_mp4.name)

    # info.json rewrite.
    src_info = read_dataset_info(ds_root)
    new_info = to_vla_info(src_info)
    new_info["total_episodes"] = num_episodes
    new_info["total_frames"] = num_frames
    (out_meta / "info.json").write_text(json.dumps(new_info, indent=2))

    # action_stats.json.
    if converted_tables:
        stats = compute_action_stats(converted_tables)
        (out_meta / "action_stats.json").write_text(json.dumps(stats))

    # tasks.parquet verbatim copy (tests/training read it).
    if p.tasks_parquet.exists():
        shutil.copy2(p.tasks_parquet, out_meta / "tasks.parquet")

    # episodes.parquet — re-use build_archive_stream's filtered version so
    # tombstoned rows stay excluded.
    for path_in_zip, content in build_archive_stream(ds_root):
        if path_in_zip == "meta/episodes/chunk-000/file-000.parquet":
            target = out_meta / "episodes" / "chunk-000" / "file-000.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else content.read_bytes())
            break

    return ExportResult(
        dest_path=out_dir,
        format=format,
        num_episodes=num_episodes,
        num_frames=num_frames,
        warnings=warnings,
    )
```

- [ ] **Step 6.4: Run — expect green**

```bash
bash scripts/test.sh tests/unit/test_exporter_orchestrator.py -q
```
Expected: 8 passed (3 from Task 1 + 5 new).

- [ ] **Step 6.5: Commit**

```bash
git add backend/mimicrec/datasets/exporters/errors.py backend/mimicrec/datasets/exporters/orchestrator.py tests/unit/test_exporter_orchestrator.py
git commit -m "feat(exporters): orchestrator with force/conflict + v3-native and vla-compat paths"
```

---

## Phase D — API surface

### Task 7: `POST /api/datasets/{ds}/export` route

Translates `ExportRequest` into an orchestrator call. Maps `DestinationExistsError → 409`, `FileNotFoundError → 404`, `ValueError → 400`.

**Files:**
- Modify: `backend/mimicrec/api/routes/datasets.py` (add new route at the bottom)
- Test: `tests/api/test_export_routes.py`

- [ ] **Step 7.1: Write failing tests**

Create `tests/api/test_export_routes.py`:

```python
from __future__ import annotations
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_export_vla_compat_writes_to_state_override(tmp_path: Path, app: FastAPI, monkeypatch):
    # Arrange dataset and dest paths via app state.
    from mimicrec.recording.dataset_layout import init_dataset
    ds_root = tmp_path / "datasets" / "ds7"
    init_dataset(ds_root, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=["front"])
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/ds7/export", json={
            "format": "vla_compat",
            "instruction_template": "What action should the robot take to {TASK}? A:",
            "force": False,
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "vla_compat"
    assert Path(body["dest_path"]).is_absolute()
    assert (Path(body["dest_path"]) / "meta" / "info.json").exists()


@pytest.mark.asyncio
async def test_export_returns_404_when_dataset_missing(app: FastAPI, tmp_path: Path):
    app.state.datasets_root = tmp_path
    app.state.vla_dest_root = tmp_path / "vla"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/nope/export", json={"format": "vla_compat"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_returns_409_when_dest_exists_no_force(app: FastAPI, tmp_path: Path):
    from mimicrec.recording.dataset_layout import init_dataset
    ds_root = tmp_path / "datasets" / "ds_existing"
    init_dataset(ds_root, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=[])
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"
    (tmp_path / "vla" / "ds_existing").mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/ds_existing/export", json={"format": "vla_compat"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_export_with_force_overwrites(app: FastAPI, tmp_path: Path):
    from mimicrec.recording.dataset_layout import init_dataset
    ds_root = tmp_path / "datasets" / "ds_force"
    init_dataset(ds_root, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=[])
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"
    (tmp_path / "vla" / "ds_force").mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/ds_force/export",
                          json={"format": "vla_compat", "force": True})
    assert r.status_code == 200
```

- [ ] **Step 7.2: Run — expect 404 / route-missing failures**

- [ ] **Step 7.3: Implement the route**

Update the existing `from fastapi import APIRouter, Request, Query` line at the top of `backend/mimicrec/api/routes/datasets.py` to also import `HTTPException`:

```python
from fastapi import APIRouter, Request, Query, HTTPException
```

Then append the rest of the imports and the new route to the bottom of the same file:

```python
from mimicrec.api.deps import get_vla_dest_root
from mimicrec.api.schemas import ExportRequest, ExportResponse, ExportFormat
from mimicrec.datasets.exporters.errors import DestinationExistsError
from mimicrec.datasets.exporters.orchestrator import export_dataset_to_local


@router.post("/datasets/{ds}/export")
async def export_dataset(request: Request, ds: str, body: ExportRequest) -> ExportResponse:
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise HTTPException(status_code=404, detail=f"dataset '{ds}' not found")
    dest_root = get_vla_dest_root(request.app)
    dest_root.mkdir(parents=True, exist_ok=True)
    try:
        result = export_dataset_to_local(
            ds_root=ds_root,
            dest_root=dest_root,
            format=body.format,
            instruction_template=body.instruction_template,
            force=body.force,
        )
    except DestinationExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ExportResponse(
        dest_path=str(result.dest_path),
        format=result.format,
        num_episodes=result.num_episodes,
        num_frames=result.num_frames,
        warnings=result.warnings,
    )
```

Also extend the existing `tests/api/conftest.py` `app` fixture so `app.state.vla_dest_root = None` is set for tests that don't override it. (The fixture already sets `datasets_root = None`; mirror it.)

```python
@pytest.fixture
def app():
    a = create_app()
    a.state.configs_root = REPO_ROOT / "configs"
    a.state.datasets_root = None
    a.state.vla_dest_root = None
    return a
```

- [ ] **Step 7.4: Run — expect green**

```bash
bash scripts/test.sh tests/api/test_export_routes.py -q
```
Expected: 4 passed.

- [ ] **Step 7.5: Commit**

```bash
git add backend/mimicrec/api/routes/datasets.py tests/api/test_export_routes.py tests/api/conftest.py
git commit -m "feat(api): POST /datasets/{ds}/export with conflict/force semantics"
```

---

### Task 8: `format` query on existing `GET /archive`

`format=lerobot_v3_native` → existing zip behaviour. `format=vla_compat` → 400 with a hint pointing at `POST /export`.

**Files:**
- Modify: `backend/mimicrec/api/routes/datasets.py` (`download_archive`)
- Test: `tests/api/test_dataset_routes.py` (extend)

- [ ] **Step 8.1: Add a failing test**

Append to `tests/api/test_dataset_routes.py`:

```python
@pytest.mark.asyncio
async def test_archive_with_vla_compat_format_returns_400(tmp_path: Path):
    from mimicrec.api.app import create_app
    from mimicrec.recording.dataset_layout import init_dataset
    a = create_app()
    a.state.datasets_root = tmp_path
    init_dataset(tmp_path / "ds_vla", fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=[])
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/api/datasets/ds_vla/archive?format=vla_compat")
    assert r.status_code == 400
    assert "POST" in r.json()["detail"]


@pytest.mark.asyncio
async def test_archive_with_v3_native_format_succeeds(tmp_path: Path):
    from mimicrec.api.app import create_app
    from mimicrec.recording.dataset_layout import init_dataset
    a = create_app()
    a.state.datasets_root = tmp_path
    init_dataset(tmp_path / "ds_native", fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=[])
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/api/datasets/ds_native/archive?format=lerobot_v3_native")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
```

- [ ] **Step 8.2: Run — expect 200 returned for vla_compat (because the param is ignored today)**

- [ ] **Step 8.3: Implement the query param**

Modify `download_archive` in `backend/mimicrec/api/routes/datasets.py` to accept `format`:

```python
@router.get("/datasets/{ds}/archive")
async def download_archive(
    request: Request, ds: str,
    format: ExportFormat = ExportFormat.LEROBOT_V3_NATIVE,
):
    if format != ExportFormat.LEROBOT_V3_NATIVE:
        raise HTTPException(
            status_code=400,
            detail=(
                "format=vla_compat is not supported via the archive download. "
                "Use POST /api/datasets/{ds}/export instead."
            ),
        )
    root = get_datasets_root(request.app)
    ds_root = root / ds
    # ... (existing body unchanged)
```

(Keep the rest of the function body identical.)

- [ ] **Step 8.4: Run — expect green**

```bash
bash scripts/test.sh tests/api/test_dataset_routes.py -q
```

- [ ] **Step 8.5: Commit**

```bash
git add backend/mimicrec/api/routes/datasets.py tests/api/test_dataset_routes.py
git commit -m "feat(api): /archive accepts format=lerobot_v3_native; rejects vla_compat with 400"
```

---

## Phase E — Frontend

### Task 9: TypeScript types and `useExportDataset` mutation

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/queries.ts`

- [ ] **Step 9.1: Append types**

Add to `frontend/src/api/types.ts`:

```typescript
export type ExportFormat = "lerobot_v3_native" | "vla_compat";

export interface ExportRequest {
  format: ExportFormat;
  instruction_template?: string;
  force?: boolean;
}

export interface ExportResponse {
  dest_path: string;
  format: ExportFormat;
  num_episodes: number;
  num_frames: number;
  warnings: string[];
}
```

- [ ] **Step 9.2: Add mutation**

Append to `frontend/src/api/queries.ts`:

```typescript
import type { ExportRequest, ExportResponse } from "./types.ts";

export function useExportDataset(ds: string) {
  return useMutation<ExportResponse, ApiError, ExportRequest>({
    mutationFn: (body: ExportRequest) =>
      apiFetch<ExportResponse>(`/api/datasets/${ds}/export`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  });
}
```

(Make sure `ApiError` is imported in `queries.ts` — if it isn't already, add `import { ApiError } from "./client.ts";`.)

- [ ] **Step 9.3: Verify type-check**

```bash
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 9.4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/queries.ts
git commit -m "feat(frontend): ExportFormat types + useExportDataset mutation"
```

---

### Task 10: `ExportDatasetModal` component

A small modal: format radio (LeRobot v3 native / VLA compat (joint 7-D)), instruction template textarea (only shown when VLA compat is picked), live "tasks preview" showing each task's `instruction` (warning marker when empty), `force` checkbox (only relevant when a previous attempt returned 409 — the UI re-shows the modal after a 409 with the checkbox highlighted).

**Files:**
- Create: `frontend/src/components/ExportDatasetModal.tsx`

- [ ] **Step 10.1: Implement the component**

```tsx
import { useState } from "react";
import { useExportDataset, useTasks } from "@/api/queries";
import { ApiError } from "@/api/client";
import type { ExportFormat } from "@/api/types";

const DEFAULT_TEMPLATE = "What action should the robot take to {TASK}? A:";

interface Props {
  ds: string;
  onClose: () => void;
}

export function ExportDatasetModal({ ds, onClose }: Props) {
  const [format, setFormat] = useState<ExportFormat>("vla_compat");
  const [template, setTemplate] = useState<string>(DEFAULT_TEMPLATE);
  const [force, setForce] = useState<boolean>(false);
  const [needsForce, setNeedsForce] = useState<boolean>(false);
  const exportMutation = useExportDataset(ds);
  const { data: tasks } = useTasks(ds);

  const handleSubmit = () => {
    setNeedsForce(false);
    exportMutation.mutate(
      { format, instruction_template: template, force },
      {
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            setNeedsForce(true);
            setForce(true);
          }
        },
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-[640px] rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold">Export "{ds}"</h2>

        <fieldset className="mb-4">
          <legend className="mb-2 text-sm font-medium">Format</legend>
          <label className="mb-1 flex items-center gap-2">
            <input type="radio" checked={format === "lerobot_v3_native"}
                   onChange={() => setFormat("lerobot_v3_native")} />
            LeRobot v3 native (raw recorded columns)
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" checked={format === "vla_compat"}
                   onChange={() => setFormat("vla_compat")} />
            VLA-compat (joint 7-D, instruction-conditioned)
          </label>
        </fieldset>

        {format === "vla_compat" && (
          <>
            <label className="mb-1 block text-sm font-medium">Instruction template</label>
            <textarea className="mb-2 w-full rounded border border-gray-300 p-2 text-sm"
                      rows={2} value={template}
                      onChange={(e) => setTemplate(e.target.value)} />
            <p className="mb-4 text-xs text-gray-500">
              <code>{"{TASK}"}</code> is replaced per episode with each task's instruction
              (or task name when instruction is empty).
            </p>

            <div className="mb-4 max-h-32 overflow-auto rounded border border-gray-200 p-2 text-xs">
              <div className="mb-1 font-medium">Tasks in this dataset:</div>
              {tasks?.map((t) => (
                <div key={t.task_index} className="flex justify-between gap-3 py-0.5">
                  <span className="font-mono">{t.task}</span>
                  <span className={t.instruction ? "text-gray-700" : "text-amber-600"}>
                    {t.instruction || "(no instruction — will fall back to task name)"}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {needsForce && (
          <div className="mb-3 rounded bg-amber-50 p-2 text-sm text-amber-800">
            Destination already exists. Tick "Overwrite" and submit again to replace it.
          </div>
        )}
        <label className="mb-4 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={force}
                 onChange={(e) => setForce(e.target.checked)} />
          Overwrite existing destination
        </label>

        {exportMutation.isSuccess && (
          <div className="mb-3 rounded bg-green-50 p-2 text-sm text-green-800">
            Exported {exportMutation.data.num_episodes} episodes
            ({exportMutation.data.num_frames} frames) to{" "}
            <code>{exportMutation.data.dest_path}</code>
            {exportMutation.data.warnings.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-xs text-amber-700">
                {exportMutation.data.warnings.map((w) => <li key={w}>{w}</li>)}
              </ul>
            )}
          </div>
        )}
        {exportMutation.isError && !needsForce && (
          <div className="mb-3 rounded bg-red-50 p-2 text-sm text-red-800">
            {exportMutation.error.message}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button className="rounded border border-gray-300 px-3 py-1 text-sm" onClick={onClose}>
            Close
          </button>
          <button className="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                  disabled={exportMutation.isPending} onClick={handleSubmit}>
            {exportMutation.isPending ? "Exporting…" : "Export"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 10.2: Verify type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 10.3: Commit**

```bash
git add frontend/src/components/ExportDatasetModal.tsx
git commit -m "feat(frontend): ExportDatasetModal with format/template/force + task preview"
```

---

### Task 11: Wire modal into `DatasetsPage`

Replace the existing `<a href={...}/api/datasets/${ds.name}/archive download>Download</a>` with an `Export` button that opens the modal for the picked dataset.

**Files:**
- Modify: `frontend/src/pages/DatasetsPage.tsx`

- [ ] **Step 11.1: Edit the page**

In `frontend/src/pages/DatasetsPage.tsx`:

1. Add the import at the top:
   ```tsx
   import { ExportDatasetModal } from "@/components/ExportDatasetModal";
   ```
2. Add state above the table:
   ```tsx
   const [exportingDataset, setExportingDataset] = useState<string | null>(null);
   ```
3. Replace the `<a href={...}>Download</a>` block (the `<a>` element rendering "Download") with:
   ```tsx
   <button
     className="text-sm text-gray-600 hover:text-gray-900"
     onClick={() => setExportingDataset(ds.name)}
   >
     Export
   </button>
   ```
4. Append, just before the closing component return:
   ```tsx
   {exportingDataset && (
     <ExportDatasetModal
       ds={exportingDataset}
       onClose={() => setExportingDataset(null)}
     />
   )}
   ```

- [ ] **Step 11.2: Verify type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 11.3: Manual smoke (optional but recommended)**

```bash
bash scripts/run.sh
```
Open `http://localhost:5173/datasets`, click `Export`, pick `vla_compat`, submit. Verify a folder appears under `~/vla-gemma-4/data/local/<ds>/`.

- [ ] **Step 11.4: Commit**

```bash
git add frontend/src/pages/DatasetsPage.tsx
git commit -m "feat(frontend): replace dataset Download link with Export modal trigger"
```

---

## Phase F — End-to-end integration

### Task 12: End-to-end exporter readback test (pyarrow only)

Confirms the exported parquet is well-formed at the schema level (column names, shapes, dtypes, language_instruction string content) by reading it back with plain `pyarrow`. We deliberately do **not** depend on `lerobot.datasets.LeRobotDataset` here — the consuming repo (`vla-gemma-4`) has its own integration tests that exercise the loader, and those should evolve with whatever LeRobot version it pins. Coupling MimicRec's tests to a specific `LeRobotDataset` constructor signature creates churn without value.

**Files:**
- Create: `tests/integration/test_vla_compat_roundtrip.py`

- [ ] **Step 12.1: Write the test**

```python
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.api.schemas import ExportFormat, DEFAULT_INSTRUCTION_TEMPLATE
from mimicrec.datasets.exporters.orchestrator import export_dataset_to_local
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.metadata import append_episode, upsert_task


def _seed(ds: Path):
    init_dataset(ds, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=["front"])
    p = dataset_paths(ds)
    upsert_task(p.meta_dir, "tape_on_bottle",
                "Pick up the tape and place it on the bottle")
    rows = []
    for f in range(8):
        rows.append({
            "timestamp": f / 15.0,
            "tick_t_mono_ns": 0,
            "observation.state.joint_pos": [0.1] * 6,
            "observation.state.joint_vel": [0.0] * 6,
            "observation.state.joint_effort": [0.0] * 6,
            "observation.state.t_mono_ns": 0,
            "observation.state.gripper_pos": 0.5,
            "action.joint_pos": [0.2] * 6,
            "action.t_mono_ns": 0,
            "action.gripper_pos": 0.7,
            "frame_index": f, "episode_index": 0, "index": f, "task_index": 0,
            "observation.images.front.video_frame_index": f,
            "observation.images.front.t_mono_ns": 0,
        })
    p.chunk_dir(0).mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "chunk-000" / "observation.images.front"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00")
    append_episode(p.meta_dir, {
        "episode_index": 0, "task": "tape_on_bottle",
        "num_frames": 8, "robot": "so101", "mode": "teleop",
        "cameras": ["front"],
    })


def test_vla_compat_export_produces_loadable_parquet_and_metadata(tmp_path: Path):
    ds = tmp_path / "ds"
    dest = tmp_path / "dest"
    _seed(ds)

    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest,
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=False,
    )

    out = dest / "ds"
    pq_path = out / "data" / "chunk-000" / "episode_000000.parquet"
    table = pq.read_table(pq_path)

    # Schema invariants the VLA loader cares about.
    assert "action" in table.column_names
    assert "observation.state" in table.column_names
    assert "language_instruction" in table.column_names

    actions = np.array(table.column("action").to_pylist(), dtype=np.float32)
    states = np.array(table.column("observation.state").to_pylist(), dtype=np.float32)
    assert actions.shape == (8, 7)
    assert states.shape == (8, 7)

    # language_instruction expanded from template + tasks.parquet.instruction.
    li = table.column("language_instruction").to_pylist()
    assert all("Pick up the tape and place it on the bottle" in s for s in li)
    assert all(s.startswith("What action should the robot take to ") for s in li)

    # info.json reflects the new shapes.
    info = json.loads((out / "meta" / "info.json").read_text())
    assert info["features"]["action"]["shape"] == [7]
    assert info["features"]["observation.state"]["shape"] == [7]
    assert info["features"]["language_instruction"]["dtype"] == "string"

    # action_stats.json present and well-shaped.
    stats = json.loads((out / "meta" / "action_stats.json").read_text())
    assert len(stats["mean"]) == 7
    assert len(stats["std"]) == 7
    assert all(s > 0 for s in stats["std"])

    # Video copied verbatim.
    assert (out / "videos" / "chunk-000" / "observation.images.front" / "episode_000000.mp4").exists()

    # Tasks.parquet preserved.
    tasks_table = pq.read_table(out / "meta" / "tasks.parquet")
    assert "tape_on_bottle" in tasks_table.column("task").to_pylist()

    # Result fields.
    assert result.num_episodes == 1
    assert result.num_frames == 8
    assert result.warnings == []
```

- [ ] **Step 12.2: Run**

```bash
bash scripts/test.sh tests/integration/test_vla_compat_roundtrip.py -q
```
Expected: 1 passed.

- [ ] **Step 12.3: Commit**

```bash
git add tests/integration/test_vla_compat_roundtrip.py
git commit -m "test(integration): vla_compat export produces a schema-valid parquet tree"
```

**Note:** End-to-end verification that the exported tree is consumable by `vla_gemma4.data.dataset.VLADataset` (which wraps `LeRobotDataset`) is the responsibility of the consuming repo; that test should live in `vla-gemma-4` and be added when the consumer side is wired up.

---

### Task 13: Final cleanup — full suite green + lint + types

- [ ] **Step 13.1: Run all backend tests**

```bash
bash scripts/test.sh tests/ -q
```
Expected: all green (88 prior + 1 from Task 7's conftest tweak + 4 from Task 7 + 2 from Task 8 + 5 from Task 6 + 5 from Task 5 + 5 from Task 4 + 5 from Task 3 + 5 from Task 2 + 3 from Task 1 + 1 (or skip) from Task 12 = ~124 tests).

- [ ] **Step 13.2: Lint backend (if ruff configured)**

```bash
ruff check backend/mimicrec/datasets/exporters
ruff check backend/mimicrec/api/routes/datasets.py
```

- [ ] **Step 13.3: Type-check frontend**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 13.4: Commit any final fixes**

```bash
git add -A
git commit -m "chore: pass full suite + lint + types for vla_compat export"
```

- [ ] **Step 13.5: Manual smoke (golden path)**

If the SO-101 (1).zip is unpacked at `~/datasets/so101_v1/`:

```bash
export MIMICREC_DATASETS_ROOT=~/datasets
bash scripts/run.sh
```

Browser: open `http://localhost:5173/datasets`, click `Export` on `so101_v1`, pick `vla_compat`, submit. Confirm:
- `~/vla-gemma-4/data/local/so101_v1/meta/info.json` has `action.shape: [7]`
- `~/vla-gemma-4/data/local/so101_v1/meta/action_stats.json` exists with `mean`/`std` length 7
- A spot-check parquet (`data/chunk-000/episode_000000.parquet`) opens with `pyarrow.parquet.read_table` and has `action`, `observation.state`, `language_instruction` columns
- mp4 files copied under `videos/chunk-000/observation.images.{front,wrist}/`
- `tasks.parquet` carried over verbatim

---

## Done

The Datasets page now exports recorded MimicRec datasets in two formats: the existing LeRobot v3 native layout (still available as a zip download via the API for backward compatibility) and a new VLA-compatible joint-7-D layout written directly to `~/vla-gemma-4/data/local/<dataset>/`. Cloud upload (HF Hub etc.) is intentionally out of scope — see the conversation thread of 2026-04-27 for the deferred Phase 2 task list.
