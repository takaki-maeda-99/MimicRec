"""Forward-kinematics service for recording EE pose alongside joints.

Wraps lerobot's `RobotKinematics` (placo-based) so the writer can attach
end-effector pose (position + axis-angle) columns to each parquet row
without touching the realtime control loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class KinematicsConfig:
    urdf_path: str
    target_frame: str = "gripper_frame_link"
    # Subset of robot DoF whose joints actually move the end-effector. For SO-101
    # this is the 5 arm joints (shoulder/elbow/wrist), excluding `gripper`.
    joint_names: list[str] | None = None


class FKService:
    """Thin wrapper that computes (position, rotvec) for a joint vector.

    Joint values are interpreted in **degrees** (matches the SO-101 adapter and
    lerobot's RobotKinematics convention).
    """

    def __init__(self, cfg: KinematicsConfig):
        from lerobot.model.kinematics import RobotKinematics
        from lerobot.utils.rotation import Rotation

        self.cfg = cfg
        urdf = str(Path(cfg.urdf_path).resolve())
        self._k = RobotKinematics(
            urdf_path=urdf,
            target_frame_name=cfg.target_frame,
            joint_names=cfg.joint_names,
        )
        self._rotation = Rotation
        # Number of joints fed to FK (subset that drives the kinematic chain).
        self._n_kin_joints = len(self._k.joint_names)

    @property
    def n_kin_joints(self) -> int:
        return self._n_kin_joints

    def pose(self, joint_pos_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return (position[3], rotvec[3]) of the target frame in world coords."""
        # placo's set_joint requires Python float (C++ double); reject numpy
        # float32 with a Boost.Python.ArgumentError. Cast up front.
        T = self._k.forward_kinematics(np.asarray(joint_pos_deg, dtype=np.float64))
        pos = T[:3, 3].astype(np.float32)
        rotvec = self._rotation.from_matrix(T[:3, :3]).as_rotvec().astype(np.float32)
        return pos, rotvec

    def matrix(self, joint_pos_deg: np.ndarray) -> np.ndarray:
        """Return the 4x4 end-effector transform for joint_pos_deg (degrees).
        Convenience accessor for ActionDecoder; FK convention matches `pose()`."""
        return self._k.forward_kinematics(np.asarray(joint_pos_deg, dtype=np.float64))


def load_kinematics(cfg: KinematicsConfig | dict | None) -> FKService | None:
    """Build an FKService from config; return None if cfg is missing/empty."""
    if cfg is None:
        return None
    if isinstance(cfg, dict):
        if not cfg.get("urdf_path"):
            return None
        cfg = KinematicsConfig(
            urdf_path=cfg["urdf_path"],
            target_frame=cfg.get("target_frame", "gripper_frame_link"),
            joint_names=cfg.get("joint_names"),
        )
    return FKService(cfg)
