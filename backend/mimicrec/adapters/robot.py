from __future__ import annotations
from enum import Enum
from typing import Protocol
import numpy as np

from mimicrec.types import RobotState


class RobotMode(str, Enum):
    POSITION = "position"
    TORQUE_OFF = "torque_off"
    GRAVITY_COMP = "gravity_comp"


class RobotAdapter(Protocol):
    name: str
    dof: int
    joint_names: list[str]

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def read_state(self) -> RobotState: ...
    async def send_joint_command(self, q: np.ndarray) -> None: ...
    async def set_mode(self, mode: RobotMode) -> None: ...

    def supports_mode(self, mode: RobotMode) -> bool: ...
