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


@dataclass
class RobotCommand:
    q: np.ndarray              # float32[dof]
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
