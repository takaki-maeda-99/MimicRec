from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.fault_profile import FaultProfile
from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.types import RobotState


class MockRobotAdapter:
    name = "mock"
    dof = 2
    joint_names = ["j1", "j2"]

    def __init__(self, dt_ns: int = 5_000_000, fault: FaultProfile | None = None):
        self._q = np.zeros(self.dof, dtype=np.float32)
        self._mode = RobotMode.POSITION
        self._dt_ns = dt_ns
        self._fault = fault
        self._last_state: RobotState | None = None
        self.sent_commands: list[np.ndarray] = []

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_state(self) -> RobotState:
        await asyncio.sleep(self._dt_ns / 1e9)
        if self._fault:
            if self._fault.roll_drop():
                raise TimeoutError("mock robot drop")
            await asyncio.sleep(self._fault.sample_delay_s())
            if self._fault.stuck_for_n_calls > 0 and self._last_state is not None:
                self._fault.stuck_for_n_calls -= 1
                return self._last_state
        state = RobotState(
            joint_pos=self._q.copy(),
            joint_vel=np.zeros(self.dof, dtype=np.float32),
            joint_effort=np.zeros(self.dof, dtype=np.float32),
        )
        self._last_state = state
        return state

    async def send_joint_command(self, q: np.ndarray) -> None:
        self.sent_commands.append(q.copy())
        self._q = q.astype(np.float32)

    async def set_mode(self, mode: RobotMode) -> None:
        self._mode = mode

    def supports_mode(self, mode: RobotMode) -> bool:
        return True

    @classmethod
    def default_gripper_convention(cls) -> GripperConvention:
        """Stub convention used in tests; gripper sourced from joint_pos[1]."""
        return GripperConvention(closed_at=0.0, open_at=1.0)

    @classmethod
    def proprio_layout(cls) -> ProprioLayout:
        """Stub layout: joint_pos only, gripper taken from joint_pos[1]."""
        return ProprioLayout(
            columns=("observation.state.joint_pos",),
            output_names=("j1", "j2"),
            gripper_via_column="observation.state.joint_pos",
            gripper_index_in_column=1,
        )
