from __future__ import annotations
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.types import RobotState


class ReBotArmAdapter:
    """Stub scaffolding; real reBotArm_control_py wiring deferred to Plan D."""
    name = "rebotarm_b601dm"
    dof = 6
    joint_names = [f"j{i}" for i in range(1, 7)]

    def __init__(self, serial_port: str):
        self._port = serial_port
        self._mode = RobotMode.POSITION

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def read_state(self) -> RobotState:
        z = np.zeros(self.dof, dtype=np.float32)
        return RobotState(joint_pos=z, joint_vel=z, joint_effort=z)

    async def send_joint_command(self, q: np.ndarray) -> None: ...

    async def set_mode(self, mode: RobotMode) -> None:
        self._mode = mode

    def supports_mode(self, mode: RobotMode) -> bool:
        return True
