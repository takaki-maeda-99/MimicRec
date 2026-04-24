from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.teleop import TeleopType
from mimicrec.types import TeleopAction


class MockTeleoperator:
    name = "mock_leader"
    type = TeleopType.LEADER_ARM

    def __init__(self, dof: int = 2, dt_ns: int = 5_000_000):
        self._dof = dof
        self._dt_ns = dt_ns
        self.target = np.zeros(self._dof, dtype=np.float32)

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_action(self) -> TeleopAction:
        await asyncio.sleep(self._dt_ns / 1e9)
        return TeleopAction(target_joint_pos=self.target.copy())
