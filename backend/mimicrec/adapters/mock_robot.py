from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.types import RobotState


class MockRobotAdapter:
    name = "mock"
    dof = 2
    joint_names = ["j1", "j2"]

    def __init__(self, dt_ns: int = 5_000_000):
        self._q = np.zeros(self.dof, dtype=np.float32)
        self._last_cmd = np.zeros(self.dof, dtype=np.float32)
        self._mode = RobotMode.POSITION
        self._dt_ns = dt_ns
        self.sent_commands: list[np.ndarray] = []

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_state(self) -> RobotState:
        await asyncio.sleep(self._dt_ns / 1e9)
        return RobotState(
            joint_pos=self._q.copy(),
            joint_vel=np.zeros(self.dof, dtype=np.float32),
            joint_effort=np.zeros(self.dof, dtype=np.float32),
        )

    async def send_joint_command(self, q: np.ndarray) -> None:
        self.sent_commands.append(q.copy())
        self._q = q.astype(np.float32)

    async def set_mode(self, mode: RobotMode) -> None:
        self._mode = mode

    def supports_mode(self, mode: RobotMode) -> bool:
        return True
