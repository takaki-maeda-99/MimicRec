from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.fault_profile import FaultProfile
from mimicrec.adapters.teleop import TeleopType
from mimicrec.types import TeleopAction


class MockTeleoperator:
    name = "mock_leader"
    type = TeleopType.LEADER_ARM

    def __init__(self, dof: int = 2, dt_ns: int = 5_000_000, fault: FaultProfile | None = None):
        self._dof = dof
        self._dt_ns = dt_ns
        self._fault = fault
        self._last_action: TeleopAction | None = None
        self.target = np.zeros(self._dof, dtype=np.float32)

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_action(self) -> TeleopAction:
        await asyncio.sleep(self._dt_ns / 1e9)
        if self._fault:
            if self._fault.roll_drop():
                raise TimeoutError("mock teleop drop")
            await asyncio.sleep(self._fault.sample_delay_s())
            if self._fault.stuck_for_n_calls > 0 and self._last_action is not None:
                self._fault.stuck_for_n_calls -= 1
                return self._last_action
        action = TeleopAction(target_joint_pos=self.target.copy())
        self._last_action = action
        return action
