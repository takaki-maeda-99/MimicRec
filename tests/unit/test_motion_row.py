import numpy as np
import pytest

from mimicrec.motion.se3 import SE3Delta
from mimicrec.motion.types import (
    JointPositionCommand,
    JointResourceState,
    MotionSampleBundle,
    MotionStep,
    ScalarPositionCommand,
)
from mimicrec.recording.motion_row import motion_bundle_to_row


def test_motion_row_preserves_resource_and_group_namespaces():
    state = JointResourceState(
        position=np.array([1, 2]),
        velocity=np.array([3, 4]),
        effort=np.array([5, 6]),
        joint_names=("a", "b"),
        t_mono_ns=90,
    )
    bundle = MotionSampleBundle(
        tick_t_mono_ns=200,
        states={"left_robot.arm": state},
        commands={
            "left_robot.arm": JointPositionCommand(np.array([7, 8]), 190),
            "left_robot.gripper": ScalarPositionCommand(25, 191),
        },
        motion_steps={
            "left_hand": MotionStep(
                SE3Delta(
                    np.array([0.01, 0, 0, 0, 0, 0.02]),
                    duration_sec=0.02,
                    active_mask=np.array([1, 1, 1, 0, 0, 1]),
                ),
                auxiliary={"gripper": 0.75},
                t_mono_ns=180,
            )
        },
        mapper_telemetry={
            "left_hand": {"ik_rotation_projection_residual_rad": 0.12}
        },
    )

    row = motion_bundle_to_row(bundle, 100, frame_index=3, episode_index=2)

    assert row["observation.state.left_robot.arm.joint_pos"] == pytest.approx([1, 2])
    assert row["action.resource.left_robot.arm.joint_pos"] == pytest.approx([7, 8])
    assert row["action.resource.left_robot.gripper.position"] == pytest.approx(25)
    assert row["action.motion.left_hand.se3_delta"] == pytest.approx(
        [0.01, 0, 0, 0, 0, 0.02]
    )
    assert row["action.motion.left_hand.frame"] == "ee_local"
    assert row["action.motion.left_hand.duration_sec"] == pytest.approx(0.02)
    assert row["action.motion.left_hand.aux.gripper"] == pytest.approx(0.75)
    assert row[
        "diagnostic.motion.left_hand.ik_rotation_projection_residual_rad"
    ] == pytest.approx(0.12)
    assert row["frame_index"] == 3
    assert row["episode_index"] == 2
