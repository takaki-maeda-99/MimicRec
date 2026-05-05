import numpy as np
import pytest

from mimicrec.recording.parquet_row import sample_bundle_to_row
from mimicrec.types import RobotState, RobotCommand, SampleBundle, Stamped


def test_row_has_expected_fields():
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
    )
    assert row["timestamp"] == 0.0005
    assert row["tick_t_mono_ns"] == 1_000_500_000
    assert row["observation.state.joint_pos"].tolist() == pytest.approx([0.1, 0.2])
    assert row["action.joint_pos"].tolist() == pytest.approx([0.11, 0.19])
    assert row["frame_index"] == 0
    assert row["episode_index"] == 0
    assert row["index"] == 0
    assert row["task_index"] == 0


def test_row_omits_video_metadata_columns():
    """LeRobot v3 spec: data parquet must not carry per-row video metadata
    (video_frame_index, t_mono_ns) - mp4 + timestamp is the spec'd sync mechanism.
    Extra columns make LeRobotDataset.load_hf_dataset() fail with arrow CastError."""
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
    )
    for cam in ("front", "wrist"):
        assert f"observation.images.{cam}.video_frame_index" not in row
        assert f"observation.images.{cam}.t_mono_ns" not in row


def test_row_with_explicit_indices():
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
        frames={},
    )
    row = sample_bundle_to_row(
        bundle,
        episode_start_t_mono_ns=1_000_000_000,
        frame_index=7,
        episode_index=2,
        global_index=107,
        task_index=1,
    )
    assert row["frame_index"] == 7
    assert row["episode_index"] == 2
    assert row["index"] == 107
    assert row["task_index"] == 1
