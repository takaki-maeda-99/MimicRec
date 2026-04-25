from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.errors import HandTeachNotSupportedError
from mimicrec.types import RobotState

JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


class SO101Adapter:
    name = "so101"
    dof = 6
    joint_names = JOINT_NAMES

    def __init__(self, port: str = "/dev/ttyACM0", id: str = "my_awesome_follower_arm"):
        self._port = port
        self._id = id
        self._mode = RobotMode.POSITION
        self._follower = None

    async def connect(self) -> None:
        import functools
        from mimicrec.errors import HardwareError
        from lerobot.robots.so_follower.so_follower import SO101Follower
        from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
        cfg = SOFollowerRobotConfig(port=self._port, id=self._id)
        self._follower = SO101Follower(cfg)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, functools.partial(self._follower.connect, calibrate=False))
        except RuntimeError as e:
            if "no calibration" in str(e).lower():
                raise HardwareError(
                    f"SO-101 follower '{self._id}' on {self._port} has no calibration. "
                    f"Run: python scripts/calibrate_so101.py --port {self._port} --id {self._id} --type follower"
                ) from e
            raise

    async def disconnect(self) -> None:
        if self._follower:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._follower.disconnect)
            self._follower = None

    async def read_state(self) -> RobotState:
        assert self._follower is not None
        loop = asyncio.get_running_loop()
        obs = await loop.run_in_executor(None, self._follower.get_observation)
        joint_pos = np.array([obs[f"{j}.pos"] for j in JOINT_NAMES], dtype=np.float32)
        return RobotState(
            joint_pos=joint_pos,
            joint_vel=np.zeros(self.dof, dtype=np.float32),  # SO101 doesn't provide velocity
            joint_effort=np.zeros(self.dof, dtype=np.float32),
        )

    async def send_joint_command(self, q: np.ndarray) -> None:
        assert self._follower is not None
        action = {f"{j}.pos": float(q[i]) for i, j in enumerate(JOINT_NAMES)}
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._follower.send_action, action)

    async def set_mode(self, mode: RobotMode) -> None:
        if mode == RobotMode.GRAVITY_COMP:
            raise HandTeachNotSupportedError(
                "so101 does not support GRAVITY_COMP / hand-teach in MVP. "
                "Use teleop mode with a leader arm instead."
            )
        self._mode = mode

    def supports_mode(self, mode: RobotMode) -> bool:
        return mode != RobotMode.GRAVITY_COMP
