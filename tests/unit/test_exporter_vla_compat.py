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
