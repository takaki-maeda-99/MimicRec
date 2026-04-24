from __future__ import annotations
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.errors import HandTeachNotSupportedError
from mimicrec.types import RobotState


class SO101Adapter:
    name = "so101"
    dof = 6
    joint_names = [f"j{i}" for i in range(1, 7)]

    def __init__(self, port: str):
        self._port = port
        self._mode = RobotMode.POSITION

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def read_state(self) -> RobotState:
        zeros = np.zeros(self.dof, dtype=np.float32)
        return RobotState(joint_pos=zeros, joint_vel=zeros, joint_effort=zeros)

    async def send_joint_command(self, q: np.ndarray) -> None:
        pass

    async def set_mode(self, mode: RobotMode) -> None:
        if mode == RobotMode.GRAVITY_COMP:
            raise HandTeachNotSupportedError(
                "so101 does not support GRAVITY_COMP / hand-teach in MVP "
                "(see spec §15). Use teleop mode with a leader arm instead."
            )
        self._mode = mode

    def supports_mode(self, mode: RobotMode) -> bool:
        return mode != RobotMode.GRAVITY_COMP
