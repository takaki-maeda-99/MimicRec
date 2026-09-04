from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "integrations/ros2/mimicrec_quest_bridge/mimicrec_quest_bridge/motion.py"
)
SPEC = importlib.util.spec_from_file_location("mimicrec_quest_motion", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
motion = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = motion
SPEC.loader.exec_module(motion)


def pose(x=0.0, y=0.0, z=0.0, q=(0.0, 0.0, 0.0, 1.0)):
    return motion.Pose(position=(x, y, z), orientation_xyzw=q)


def test_deadman_latches_first_pose_then_emits_offset_from_reference():
    mapper = motion.QuestMotionMapper(
        max_linear_offset_m=1.0,
        linear_deadband_m=0.0,
        angular_deadband_rad=0.0,
    )
    mapper.set_active(True)
    initial = mapper.update_pose(pose())
    command = mapper.update_pose(pose(x=0.01, y=-0.02))

    assert initial.as_list() == pytest.approx([0.0] * 6)
    assert command.translation == pytest.approx((0.01, -0.02, 0.0))
    assert command.rotation_rotvec == pytest.approx((0.0, 0.0, 0.0))


def test_pose_deadband_is_continuous_at_threshold():
    mapper = motion.QuestMotionMapper(
        linear_deadband_m=0.0005,
        angular_deadband_rad=0.005,
    )
    mapper.set_active(True)
    mapper.update_pose(pose())

    below = mapper.update_pose(pose(x=0.00049))
    above = mapper.update_pose(pose(x=0.00051))

    assert below.translation == pytest.approx((0.0, 0.0, 0.0))
    assert above.translation == pytest.approx((0.00001, 0.0, 0.0))


def test_deadman_release_requires_a_fresh_reference_pose():
    mapper = motion.QuestMotionMapper(linear_deadband_m=0.0)
    mapper.set_active(True)
    mapper.update_pose(pose(x=0.0))
    mapper.set_active(False)
    assert mapper.update_pose(pose(x=1.0)) is None
    mapper.set_active(True)
    assert mapper.update_pose(pose(x=1.0)).translation == (0.0, 0.0, 0.0)


def test_axis_mapping_scaling_and_offset_limit():
    mapper = motion.QuestMotionMapper(
        controller_to_eef_rotation=(0, 1, 0, -1, 0, 0, 0, 0, 1),
        translation_scale=2.0,
        max_linear_offset_m=0.5,
        linear_deadband_m=0.0,
    )
    mapper.set_active(True)
    mapper.update_pose(pose())
    command = mapper.update_pose(pose(x=0.4))
    assert command.translation == pytest.approx((0.0, -0.5, 0.0))


def test_so101_axis_mapping_preserves_physical_forward_lateral_and_up():
    mapper = motion.QuestMotionMapper(
        controller_to_eef_rotation=(0, 0, -1, 0, 1, 0, 1, 0, 0),
        linear_deadband_m=0.0,
        angular_deadband_rad=0.0,
    )
    mapper.set_active(True)
    mapper.update_pose(pose())

    command = mapper.update_pose(pose(x=0.1, y=0.2, z=0.3))

    assert command.translation == pytest.approx((-0.3, 0.2, 0.1))


def test_translation_is_expressed_in_clutch_controller_frame():
    # Reference controller is yawed +90 degrees in world. A +world-Y move is
    # therefore +controller-X and must become +EEF-X.
    half_angle = math.pi / 4
    reference_q = (0.0, 0.0, math.sin(half_angle), math.cos(half_angle))
    mapper = motion.QuestMotionMapper(
        linear_deadband_m=0.0,
        angular_deadband_rad=0.0,
    )
    mapper.set_active(True)
    mapper.update_pose(pose(q=reference_q))
    command = mapper.update_pose(pose(y=0.1, q=reference_q))
    assert command.translation == pytest.approx((0.1, 0.0, 0.0), abs=1e-8)


def test_world_output_keeps_translation_in_tracking_world():
    half_angle = math.pi / 4
    reference_q = (0.0, 0.0, math.sin(half_angle), math.cos(half_angle))
    mapper = motion.QuestMotionMapper(
        output_frame="world",
        linear_deadband_m=0.0,
        angular_deadband_rad=0.0,
    )
    mapper.set_active(True)
    mapper.update_pose(pose(q=reference_q))

    command = mapper.update_pose(pose(y=0.1, q=reference_q))

    assert command.translation == pytest.approx((0.0, 0.1, 0.0), abs=1e-8)


def test_world_output_uses_spatial_rotation_increment():
    reference_q = motion._rotvec_to_quaternion((0.0, 0.0, math.pi / 2))
    world_x = motion._rotvec_to_quaternion((0.2, 0.0, 0.0))
    current_q = motion._quaternion_multiply(world_x, reference_q)
    mapper = motion.QuestMotionMapper(
        output_frame="world",
        linear_deadband_m=0.0,
        angular_deadband_rad=0.0,
    )
    mapper.set_active(True)
    mapper.update_pose(pose(q=reference_q))

    command = mapper.update_pose(pose(q=current_q))

    assert command.rotation_rotvec == pytest.approx((0.2, 0.0, 0.0), abs=1e-8)


def test_world_recording_axes_are_separate_from_local_eef_control_axes():
    mapper = motion.QuestMotionMapper(
        output_frame="world",
        controller_to_eef_rotation=(0, 0, -1, 0, 1, 0, 1, 0, 0),
        world_axis_rotation=(1, 0, 0, 0, 1, 0, 0, 0, 1),
        linear_deadband_m=0.0,
        angular_deadband_rad=0.0,
    )
    mapper.set_active(True)
    mapper.update_pose(pose())
    q = motion._rotvec_to_quaternion((0.2, 0.0, 0.0))

    command = mapper.update_pose(pose(q=q))

    # Dataset stays in WORLD X; SO-101 control maps controller-forward X to
    # the gripper-local Z wrist axis.
    assert command.rotation_rotvec == pytest.approx((0.2, 0.0, 0.0))
    assert command.control_rotation_rotvec == pytest.approx((0.0, 0.0, 0.2))


def test_world_offset_step_does_not_orbit_translation_on_pure_rotation():
    previous = motion.PoseOffset((0.4, -0.2, 0.3), (0.0, 0.0, 0.0))
    current = motion.PoseOffset((0.4, -0.2, 0.3), (0.0, 0.3, 0.0))

    step = motion.world_offset_step(previous, current)

    assert step.translation == pytest.approx((0.0, 0.0, 0.0))
    assert step.rotation_rotvec == pytest.approx((0.0, 0.3, 0.0))


def test_compose_pose_resolves_controller_into_world():
    parent = pose(x=1.0, q=motion._rotvec_to_quaternion((0, 0, math.pi / 2)))
    child = pose(x=0.2)

    composed = motion.compose_pose(parent, child)

    assert composed.position == pytest.approx((1.0, 0.2, 0.0), abs=1e-8)


def test_axis_calibration_must_be_a_proper_rotation():
    with pytest.raises(ValueError, match="orthonormal"):
        motion.QuestMotionMapper(
            controller_to_eef_rotation=(2, 0, 0, 0, 1, 0, 0, 0, 1)
        )
    with pytest.raises(ValueError, match="determinant"):
        motion.QuestMotionMapper(
            controller_to_eef_rotation=(-1, 0, 0, 0, 1, 0, 0, 0, 1)
        )


def test_quaternion_rotation_preserves_controller_rotation_amount():
    controller_angle = math.pi / 4
    half_angle = controller_angle / 2
    q = (0.0, 0.0, math.sin(half_angle), math.cos(half_angle))
    mapper = motion.QuestMotionMapper(
        max_angular_offset_rad=math.pi,
        angular_deadband_rad=0.0,
    )
    mapper.set_active(True)
    mapper.update_pose(pose())
    command = mapper.update_pose(pose(q=q))
    assert command.rotation_rotvec == pytest.approx((0.0, 0.0, controller_angle))


def test_absolute_offset_does_not_depend_on_intermediate_sample_count():
    sparse = motion.QuestMotionMapper(linear_deadband_m=0.0)
    dense = motion.QuestMotionMapper(linear_deadband_m=0.0)
    sparse.set_active(True)
    dense.set_active(True)
    sparse.update_pose(pose())
    dense.update_pose(pose())
    dense.update_pose(pose(x=0.03))
    dense.update_pose(pose(x=0.07))

    assert sparse.update_pose(pose(x=0.1)).as_list() == pytest.approx(
        dense.update_pose(pose(x=0.1)).as_list()
    )


def test_fault_stop_requires_deadman_release_before_rearming():
    mapper = motion.QuestMotionMapper()
    mapper.set_active(True)
    mapper.update_pose(pose())
    mapper.fault_stop()

    mapper.set_active(True)
    assert not mapper.active
    assert mapper.update_pose(pose(x=1.0)) is None

    mapper.set_active(False)
    mapper.set_active(True)
    assert mapper.active
    assert mapper.update_pose(pose(x=1.0)).translation == (0.0, 0.0, 0.0)


def test_home_hold_fires_once_and_only_without_deadman():
    latch = motion.HoldActionLatch(hold_sec=0.5)
    assert not latch.update(pressed=True, allowed=True, now=10.0)
    assert not latch.update(pressed=True, allowed=True, now=10.4)
    assert latch.update(pressed=True, allowed=True, now=10.5)
    assert not latch.update(pressed=True, allowed=True, now=12.0)

    # Release resets it, while holding the motion deadman disallows it.
    assert not latch.update(pressed=False, allowed=True, now=12.1)
    assert not latch.update(pressed=True, allowed=False, now=13.0)
    assert not latch.update(pressed=True, allowed=True, now=14.0)
    assert latch.update(pressed=True, allowed=True, now=14.5)


def test_fixed_delay_interpolates_translation_and_rotation():
    interpolator = motion.PoseOffsetInterpolator(delay_sec=0.025)
    interpolator.add(
        1.000,
        motion.PoseOffset((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    )
    interpolator.add(
        1.050,
        motion.PoseOffset((0.1, 0.0, 0.0), (0.0, 0.0, math.pi / 2)),
    )

    halfway = interpolator.sample(1.050)
    assert halfway.translation == pytest.approx((0.05, 0.0, 0.0))
    assert halfway.rotation_rotvec == pytest.approx((0.0, 0.0, math.pi / 4))
    assert interpolator.sample(1.100).as_list() == pytest.approx(
        [0.1, 0.0, 0.0, 0.0, 0.0, math.pi / 2]
    )


def test_output_smoothing_softens_a_bursty_pose_jump_and_resets():
    interpolator = motion.PoseOffsetInterpolator(
        delay_sec=0.0,
        smoothing_time_constant_sec=0.1,
    )
    zero = motion.PoseOffset((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    jump = motion.PoseOffset((0.1, 0.0, 0.0), (0.0, 0.0, math.pi / 2))
    interpolator.add(1.0, zero)
    assert interpolator.sample(1.0) == zero
    interpolator.add(1.1, jump)

    smoothed = interpolator.sample(1.1)
    alpha = 1.0 - math.exp(-1.0)
    assert smoothed.translation[0] == pytest.approx(0.1 * alpha)
    assert smoothed.rotation_rotvec[2] == pytest.approx(
        (math.pi / 2) * alpha
    )

    interpolator.reset()
    interpolator.add(2.0, jump)
    assert interpolator.sample(2.0) == jump
