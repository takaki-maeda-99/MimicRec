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
    joint_pos: np.ndarray      # float32[dof]
    joint_vel: np.ndarray      # float32[dof]
    joint_effort: np.ndarray   # float32[dof]
    t_mono_ns: int = 0
    # Optional EE pose carried alongside joints. Adapters that compute EE
    # locally (e.g. a ZMQ daemon holding its own FK) populate these; for
    # adapters that don't, the writer / state_hub falls back to FKService.
    ee_pos: np.ndarray | None = None       # float32[3]
    ee_rotvec: np.ndarray | None = None    # float32[3] axis-angle
    gripper_pos: float | None = None


@dataclass
class RobotCommand:
    q: np.ndarray              # float32[dof] — arm joints only
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
    t_mono_ns: int = 0


@dataclass
class Frame:
    image: np.ndarray          # HxWx3 uint8 BGR
    t_mono_ns: int = 0


@dataclass
class SampleBundle:
    tick_t_mono_ns: int
    state: Stamped[RobotState]
    action: RobotCommand
    frames: dict[str, Stamped[Frame] | None]
