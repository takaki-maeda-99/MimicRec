import numpy as np
import pytest

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
    assert row["timestamp"] == 0.0005
    assert row["tick_t_mono_ns"] == 1_000_500_000
    assert row["observation.state.joint_pos"].tolist() == pytest.approx([0.1, 0.2])
    assert row["action.joint_pos"].tolist() == pytest.approx([0.11, 0.19])
    assert row["observation.images.front.video_frame_index"] == 0
    assert row["observation.images.wrist.video_frame_index"] == 0
