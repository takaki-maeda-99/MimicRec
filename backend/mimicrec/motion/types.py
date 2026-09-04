"""Typed motion, resource-state, and resource-command messages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, TypeAlias, Any

import numpy as np

from mimicrec.motion.se3 import SE3Delta, se3_log


def _finite_vector(value: np.ndarray, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float32).copy()
    if result.ndim != 1 or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite one-dimensional vector")
    return result


@dataclass(frozen=True)
class MotionStep:
    delta: SE3Delta
    auxiliary: Mapping[str, float] = field(default_factory=dict)
    t_mono_ns: int = 0
    absolute_offset: np.ndarray | None = None
    control_rotation_offset: np.ndarray | None = None
    reset_reference: bool = False

    def __post_init__(self) -> None:
        auxiliary = {str(key): float(value) for key, value in self.auxiliary.items()}
        if any(not np.isfinite(value) for value in auxiliary.values()):
            raise ValueError("MotionStep auxiliary values must be finite")
        object.__setattr__(self, "auxiliary", auxiliary)
        object.__setattr__(self, "t_mono_ns", int(self.t_mono_ns))
        absolute = self.absolute_offset
        if absolute is not None:
            absolute = np.asarray(absolute, dtype=np.float64).copy()
            # se3_log performs homogeneous-row and proper-rotation checks.
            se3_log(absolute)
            absolute.setflags(write=False)
        object.__setattr__(self, "absolute_offset", absolute)
        control_rotation = self.control_rotation_offset
        if control_rotation is not None:
            control_rotation = np.asarray(
                control_rotation, dtype=np.float64
            ).copy()
            transform = np.eye(4)
            transform[:3, :3] = control_rotation
            se3_log(transform)
            control_rotation.setflags(write=False)
        object.__setattr__(self, "control_rotation_offset", control_rotation)
        object.__setattr__(self, "reset_reference", bool(self.reset_reference))


@dataclass(frozen=True)
class JointResourceState:
    """Canonical joint state; revolute positions/velocities use rad and rad/s."""
    position: np.ndarray
    velocity: np.ndarray
    effort: np.ndarray
    joint_names: tuple[str, ...]
    t_mono_ns: int = 0
    ee_transform: np.ndarray | None = None
    # Target actually accepted by the hardware adapter/daemon, in the same
    # canonical units and joint order as ``position``.
    target_position: np.ndarray | None = None

    def __post_init__(self) -> None:
        position = _finite_vector(self.position, "position")
        velocity = _finite_vector(self.velocity, "velocity")
        effort = _finite_vector(self.effort, "effort")
        if position.shape != velocity.shape or position.shape != effort.shape:
            raise ValueError("joint position, velocity, and effort shapes must match")
        names = tuple(str(name) for name in self.joint_names)
        if len(names) != position.size:
            raise ValueError("joint_names length must match joint state length")
        transform = self.ee_transform
        if transform is not None:
            transform = np.asarray(transform, dtype=np.float64).copy()
            if transform.shape != (4, 4) or not np.isfinite(transform).all():
                raise ValueError("ee_transform must be a finite 4x4 matrix")
        target = self.target_position
        if target is not None:
            target = _finite_vector(target, "target position")
            if target.shape != position.shape:
                raise ValueError("target position shape must match joint state")
        object.__setattr__(self, "position", position)
        object.__setattr__(self, "velocity", velocity)
        object.__setattr__(self, "effort", effort)
        object.__setattr__(self, "joint_names", names)
        object.__setattr__(self, "ee_transform", transform)
        object.__setattr__(self, "target_position", target)


@dataclass(frozen=True)
class PlanarResourceState:
    pose_xy_yaw: np.ndarray
    velocity_xy_yaw: np.ndarray
    t_mono_ns: int = 0

    def __post_init__(self) -> None:
        pose = _finite_vector(self.pose_xy_yaw, "pose_xy_yaw")
        velocity = _finite_vector(self.velocity_xy_yaw, "velocity_xy_yaw")
        if pose.shape != (3,) or velocity.shape != (3,):
            raise ValueError("planar pose and velocity must have shape (3,)")
        object.__setattr__(self, "pose_xy_yaw", pose)
        object.__setattr__(self, "velocity_xy_yaw", velocity)


@dataclass(frozen=True)
class ScalarResourceState:
    position: float
    velocity: float = 0.0
    effort: float = 0.0
    t_mono_ns: int = 0

    def __post_init__(self) -> None:
        values = (float(self.position), float(self.velocity), float(self.effort))
        if not np.isfinite(values).all():
            raise ValueError("scalar resource state values must be finite")
        object.__setattr__(self, "position", values[0])
        object.__setattr__(self, "velocity", values[1])
        object.__setattr__(self, "effort", values[2])


ResourceState: TypeAlias = (
    JointResourceState | PlanarResourceState | ScalarResourceState
)


@dataclass(frozen=True)
class JointPositionCommand:
    """Canonical joint target; revolute positions use radians."""
    position: np.ndarray
    t_mono_ns: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "position", _finite_vector(self.position, "joint position command")
        )


@dataclass(frozen=True)
class ScalarPositionCommand:
    position: float
    t_mono_ns: int = 0

    def __post_init__(self) -> None:
        value = float(self.position)
        if not np.isfinite(value):
            raise ValueError("scalar position command must be finite")
        object.__setattr__(self, "position", value)


@dataclass(frozen=True)
class PlanarVelocityCommand:
    velocity_xy_yaw: np.ndarray
    t_mono_ns: int = 0

    def __post_init__(self) -> None:
        velocity = _finite_vector(self.velocity_xy_yaw, "planar velocity command")
        if velocity.shape != (3,):
            raise ValueError("planar velocity command must have shape (3,)")
        object.__setattr__(self, "velocity_xy_yaw", velocity)


ResourceCommand: TypeAlias = (
    JointPositionCommand | ScalarPositionCommand | PlanarVelocityCommand
)


@dataclass(frozen=True)
class MotionSampleBundle:
    """One synchronized recording snapshot of the full resource graph."""

    tick_t_mono_ns: int
    states: Mapping[str, ResourceState]
    commands: Mapping[str, ResourceCommand]
    motion_steps: Mapping[str, MotionStep]
    frames: Mapping[str, Any] = field(default_factory=dict)
    mapper_telemetry: Mapping[str, Mapping[str, float]] = field(
        default_factory=dict
    )
