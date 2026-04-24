from __future__ import annotations
from enum import Enum
from typing import Protocol

from mimicrec.types import TeleopAction


class TeleopType(str, Enum):
    LEADER_ARM = "leader_arm"
    SPACEMOUSE = "spacemouse"
    GAMEPAD = "gamepad"
    KEYBOARD = "keyboard"


class Teleoperator(Protocol):
    name: str
    type: TeleopType

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def read_action(self) -> TeleopAction: ...
