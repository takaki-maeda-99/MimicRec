from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

import numpy as np

T = TypeVar("T")


@dataclass(frozen=True)
class Stamped(Generic[T]):
    value: T
    t_mono_ns: int


class SessionMode(str, Enum):
    TELEOP = "teleop"
    HAND_TEACH = "hand_teach"
    INFERENCE = "inference"


class SessionState(str, Enum):
    IDLE = "idle"
    READY = "ready"
    RECORDING = "recording"
    REVIEW = "review"


class SubState(str, Enum):
    REPLAYING = "replaying"


@dataclass
class RobotState:
    joint_pos: np.ndarray  # float32[dof]
    joint_vel: np.ndarray  # float32[dof]
    joint_effort: np.ndarray  # float32[dof]
    t_mono_ns: int = 0
    # Optional EE pose carried alongside joints. Adapters that compute EE
    # locally (e.g. a ZMQ daemon holding its own FK) populate these; for
    # adapters that don't, the writer / state_hub falls back to FKService.
    ee_pos: np.ndarray | None = None  # float32[3]
    ee_rotvec: np.ndarray | None = None  # float32[3] axis-angle
    gripper_pos: float | None = None
    # Latest position target after the daemon's safety ramp. When present,
    # telemetry can split mapper-to-daemon lag from motor tracking lag.
    daemon_target_joint_pos: np.ndarray | None = None  # float32[dof]


@dataclass
class RobotCommand:
    q: np.ndarray  # float32[dof] — arm joints only
    # Optional gripper target in radians. None = "no gripper command this
    # tick" (typical for arms with no gripper / for adapters that don't
    # support it). Adapters that do support it (e.g. ReBotArmZmqAdapter
    # talking to the daemon's gripper position controller) read this and
    # forward via send_gripper_command. Keeping the gripper out of ``q``
    # means the existing 6-DoF send path stays unchanged for arm-only
    # adapters and code paths that introspect dof.
    gripper: float | None = None
    t_mono_ns: int = 0


@dataclass
class TeleopAction:
    target_joint_pos: np.ndarray | None = None
    ee_delta: np.ndarray | None = None
    # Literal Cartesian step [translation column, spatial rotvec]. The motion
    # bridge converts it into a strict SE(3) logarithm in the configured frame.
    ee_cartesian_delta: np.ndarray | None = None
    # Absolute Cartesian offset from the clutch anchor, expressed as a
    # literal translation column plus spatial rotvec in WORLD. It is carried
    # alongside the canonical per-step delta so controllers can converge to
    # a target instead of permanently losing rate-limited increments.
    ee_world_pose_offset: np.ndarray | None = None
    # Clutch-local rotation mapped into the intended EEF-local convention.
    # This is control metadata; datasets remain canonical WORLD SE3Delta.
    ee_control_rotation_offset: np.ndarray | None = None
    # Optional relative gripper motion in the adapter's native gripper
    # coordinate. Cartesian mappers integrate it from the live gripper state.
    gripper_delta: float | None = None
    t_mono_ns: int = 0
    # Absolute EE offset from the pose captured when a clutch/deadman was
    # pressed. This avoids differentiating controller poses into velocities
    # and integrating them again at a transport-dependent rate.
    ee_pose_offset: np.ndarray | None = None
    ee_pose_active: bool | None = None
    # Normalized gripper aperture from the Quest index trigger:
    # 0=open, 1=closed. The robot mapper converts it to native units.
    gripper_fraction: float | None = None
    # One-shot request consumed by SessionManager, never by a mapper.
    home_requested: bool = False


@dataclass
class Frame:
    image: np.ndarray  # HxWx3 uint8 BGR
    t_mono_ns: int = 0
    preview_only: bool = False


@dataclass
class SampleBundle:
    tick_t_mono_ns: int
    state: Stamped[RobotState]
    action: RobotCommand
    frames: dict[str, Stamped[Frame] | None]
