from __future__ import annotations
from typing import Protocol

from mimicrec.types import RobotCommand, RobotState, TeleopAction


class TeleopMapper(Protocol):
    def map(self, action: TeleopAction, robot_state: RobotState) -> RobotCommand: ...
