import numpy as np
import pytest

from mimicrec.mappers.se3_delta_to_planar import SE3DeltaToPlanarBaseMapper
from mimicrec.motion.se3 import SE3Delta
from mimicrec.motion.types import MotionStep


def test_planar_mapper_converts_step_displacement_back_to_velocity():
    mapper = SE3DeltaToPlanarBaseMapper(
        holonomic=True,
        max_linear_velocity_m_s=10,
        max_angular_velocity_rad_s=10,
    )

    command = mapper.map(
        MotionStep(SE3Delta(
            np.array([0.02, -0.01, 0, 0, 0, 0.04]),
            duration_sec=0.02,
        )),
        {},
    )["mobile_base.drive"]

    assert command.velocity_xy_yaw == pytest.approx([1.0, -0.5, 2.0])


def test_differential_drive_discards_lateral_and_nonplanar_components():
    mapper = SE3DeltaToPlanarBaseMapper(
        holonomic=False,
        max_linear_velocity_m_s=10,
        max_angular_velocity_rad_s=10,
    )

    command = mapper.map(
        MotionStep(SE3Delta(
            np.array([0, 0.1, 0.2, 0.3, 0, 0]), duration_sec=0.1
        )),
        {},
    )["mobile_base.drive"]

    assert command.velocity_xy_yaw == pytest.approx([0, 0, 0])
    assert mapper.telemetry()["discarded_twist_velocity_norm"] > 0


def test_planar_mapper_clamps_linear_vector_norm_and_yaw_rate():
    mapper = SE3DeltaToPlanarBaseMapper(
        holonomic=True,
        max_linear_velocity_m_s=0.5,
        max_angular_velocity_rad_s=1.0,
    )

    command = mapper.map(
        MotionStep(SE3Delta(
            np.array([0.3, 0.4, 0, 0, 0, 2.0]), duration_sec=0.1
        )),
        {},
    )["mobile_base.drive"]

    assert np.linalg.norm(command.velocity_xy_yaw[:2]) == pytest.approx(0.5)
    assert command.velocity_xy_yaw[2] == pytest.approx(1.0)
