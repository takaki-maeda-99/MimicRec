import numpy as np
import pytest

from mimicrec.kinematics.fk import FKService, KinematicsConfig
from mimicrec.kinematics.ik import IKService


@pytest.fixture
def cfg() -> KinematicsConfig:
    # Build an absolute URDF path so the test passes regardless of pytest cwd
    # (existing FK tests run from `backend/` cwd; this protects future moves).
    from pathlib import Path
    urdf = Path(__file__).resolve().parents[2] / "configs/urdf/so101/so101.urdf"
    assert urdf.exists(), f"URDF not found at {urdf}"
    return KinematicsConfig(
        urdf_path=str(urdf),
        target_frame="gripper_frame_link",
        joint_names=[
            "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll",
        ],
    )


@pytest.fixture
def ik(cfg) -> IKService:
    return IKService(cfg)


@pytest.fixture
def fk(cfg) -> FKService:
    return FKService(cfg)


def test_ik_round_trip(ik, fk):
    """FK(q) -> T, IK(T, seed=q) -> q' should be close to q."""
    q = np.array([10.0, -20.0, 30.0, -10.0, 5.0])
    T = fk._k.forward_kinematics(q)  # access underlying RobotKinematics for the 4x4
    q2, ok = ik.solve(T, seed=q)
    assert ok
    assert np.allclose(q, q2, atol=0.5)


def test_ik_unreachable_returns_not_ok(ik):
    """A pose far outside the workspace should fail the FK round-trip check."""
    T_far = np.eye(4)
    T_far[:3, 3] = [10.0, 0.0, 0.0]  # 10 m away — clearly unreachable
    q_seed = np.zeros(5)
    q, ok = ik.solve(T_far, seed=q_seed)
    assert not ok
