"""Kinematics utilities for end-effector pose computation.

Wraps lerobot's `RobotKinematics` (placo-based). Lazy-imported so MimicRec
runs fine without `placo` when EE recording is not used.
"""
from mimicrec.kinematics.fk import KinematicsConfig, FKService, load_kinematics

__all__ = ["KinematicsConfig", "FKService", "load_kinematics"]
