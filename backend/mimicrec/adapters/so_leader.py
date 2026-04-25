from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.teleop import TeleopType
from mimicrec.types import TeleopAction

JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


class SOLeaderAdapter:
    name = "so_leader"
    type = TeleopType.LEADER_ARM

    def __init__(self, port: str = "/dev/ttyACM1"):
        self._port = port
        self._leader = None

    async def connect(self) -> None:
        from lerobot.teleoperators.so_leader import SOLeader, SOLeaderTeleopConfig
        cfg = SOLeaderTeleopConfig(port=self._port)
        self._leader = SOLeader(cfg)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._leader.connect)

    async def disconnect(self) -> None:
        if self._leader:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._leader.disconnect)
            self._leader = None

    async def read_action(self) -> TeleopAction:
        assert self._leader is not None
        loop = asyncio.get_running_loop()
        state = await loop.run_in_executor(None, self._leader.get_action)
        joint_pos = np.array([state[f"{j}.pos"] for j in JOINT_NAMES], dtype=np.float32)
        return TeleopAction(target_joint_pos=joint_pos)
