import numpy as np
import pytest

from mimicrec.mappers.se3_delta_whole_body import SE3DeltaWholeBodyMapper
from mimicrec.motion.se3 import SE3Delta
from mimicrec.motion.types import (
    JointPositionCommand,
    MotionStep,
    PlanarVelocityCommand,
)


class _MobileArmModel:
    def jacobian(self, states):
        # generalized velocity = [base_vx, base_wz, arm_joint_velocity]
        jacobian = np.zeros((6, 3))
        jacobian[0, 0] = 1.0
        jacobian[5, 1] = 1.0
        jacobian[2, 2] = 1.0
        return jacobian

    def commands(self, velocity, step, states):
        return {
            "base.drive": PlanarVelocityCommand(
                np.array([velocity[0], 0, velocity[1]])
            ),
            "arm.arm": JointPositionCommand(
                np.array([velocity[2] * step.delta.duration_sec])
            ),
        }


def test_whole_body_mapper_splits_one_se3_delta_across_base_and_arm():
    mapper = SE3DeltaWholeBodyMapper(
        model=_MobileArmModel(), damping=1e-6
    )

    commands = mapper.map(
        MotionStep(SE3Delta(
            np.array([0.02, 0, 0.01, 0, 0, 0.04]), duration_sec=0.02
        )),
        {},
    )

    assert commands["base.drive"].velocity_xy_yaw == pytest.approx([1, 0, 2])
    assert commands["arm.arm"].position == pytest.approx([0.01])
    assert mapper.telemetry()["whole_body_twist_residual_norm"] < 1e-8


def test_whole_body_mapper_respects_active_mask():
    mapper = SE3DeltaWholeBodyMapper(model=_MobileArmModel())

    commands = mapper.map(
        MotionStep(SE3Delta(
            np.ones(6) * 0.1,
            duration_sec=0.1,
            active_mask=np.array([1, 0, 0, 0, 0, 0]),
        )),
        {},
    )

    assert commands["base.drive"].velocity_xy_yaw[0] == pytest.approx(1, rel=1e-3)
    assert commands["base.drive"].velocity_xy_yaw[2] == pytest.approx(0)
    assert commands["arm.arm"].position == pytest.approx([0])


def test_whole_body_mapper_rejects_bad_jacobian_shape():
    model = _MobileArmModel()
    model.jacobian = lambda states: np.eye(3)
    mapper = SE3DeltaWholeBodyMapper(model=model)

    with pytest.raises(ValueError, match="shape"):
        mapper.map(MotionStep(SE3Delta.identity()), {})
