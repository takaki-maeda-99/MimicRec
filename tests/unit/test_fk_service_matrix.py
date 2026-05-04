import numpy as np
from mimicrec.kinematics.fk import FKService, KinematicsConfig


def _cfg() -> KinematicsConfig:
    from pathlib import Path
    urdf = Path(__file__).resolve().parents[2] / "configs/urdf/so101/so101.urdf"
    return KinematicsConfig(
        urdf_path=str(urdf),
        target_frame="gripper_frame_link",
        joint_names=["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"],
    )


def test_fk_service_returns_4x4_matrix():
    fk = FKService(_cfg())
    T = fk.matrix(np.zeros(5))
    assert T.shape == (4, 4)
    assert np.allclose(T[3], [0, 0, 0, 1])


def test_fk_service_retains_cfg():
    cfg = _cfg()
    fk = FKService(cfg)
    assert fk.cfg is cfg            # public attribute — IKService(fk.cfg) is the supported call


def test_fk_service_pose_still_works():
    """Regression: existing pose() must continue to work after the edit
    (it depends on self._rotation, which is preserved alongside the new fields)."""
    fk = FKService(_cfg())
    pos, rotvec = fk.pose(np.zeros(5))
    assert pos.shape == (3,)
    assert rotvec.shape == (3,)
