"""Episode-table conversion to VLA-compat schema (pure)."""
from __future__ import annotations

from dataclasses import dataclass

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


def _normalize_gripper(raw: float) -> float:
    """Map lerobot RANGE_0_100 gripper (0=closed, 100=open) to VLA convention
    (-1=open, +1=close). vla = 1 - raw/50."""
    return 1.0 - float(raw) / 50.0


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
        out.append([float(x) for x in j] + [_normalize_gripper(g)])
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

    # LeRobot v3 spec: video features are referenced via mp4 + timestamp,
    # not via per-row data parquet columns. observation.images.* columns
    # (legacy from older recordings) are dropped so LeRobotDataset.load_hf_dataset
    # doesn't fail with arrow CastError.

    # info.json declares timestamp float32; ensure output matches even when input
    # came from older recordings written before pending.finalize cast.
    if "timestamp" in arrays:
        arrays["timestamp"] = arrays["timestamp"].cast(pa.float32())

    out = pa.table(arrays)
    return ConvertedEpisode(table=out)
