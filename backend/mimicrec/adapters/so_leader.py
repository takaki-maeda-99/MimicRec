from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.teleop import TeleopType
from mimicrec.types import TeleopAction

JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


class SOLeaderAdapter:
    name = "so_leader"
    type = TeleopType.LEADER_ARM

    def __init__(self, port: str = "/dev/ttyACM1", id: str = "my_awesome_leader_arm"):
        self._port = port
        self._id = id
        self._leader = None

    async def connect(self) -> None:
        import functools
        from mimicrec.errors import HardwareError
        from mimicrec.adapters.so101 import (
            _is_calibrated_safely,
            _so_calib_missing_message,
            _so_calib_mismatch_message,
        )
        from lerobot.teleoperators.so_leader.so_leader import SOLeader
        from lerobot.teleoperators.so_leader.config_so_leader import SOLeaderTeleopConfig
        cfg = SOLeaderTeleopConfig(port=self._port, id=self._id)
        self._leader = SOLeader(cfg)
        loop = asyncio.get_running_loop()

        # See SO101Adapter.connect for the rationale; the leader's lerobot
        # base class has the same calibrate=False blind spot.
        fpath = self._leader.calibration_fpath
        if not fpath.is_file():
            raise HardwareError(_so_calib_missing_message(
                role="SO leader", arm_id=self._id, port=self._port,
                file_path=fpath, calibrate_type="leader",
            ))

        await loop.run_in_executor(None, functools.partial(self._leader.connect, calibrate=False))

        if not await _is_calibrated_safely(loop, self._leader):
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self._leader.bus.write_calibration(self._leader.calibration),
                )
            except Exception:
                pass
            if not await _is_calibrated_safely(loop, self._leader):
                try:
                    await loop.run_in_executor(None, self._leader.disconnect)
                except Exception:
                    pass
                self._leader = None
                raise HardwareError(_so_calib_mismatch_message(
                    role="SO leader", arm_id=self._id, port=self._port,
                    file_path=fpath, calibrate_type="leader",
                ))

    async def disconnect(self) -> None:
        if self._leader:
            import logging
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, self._leader.disconnect)
            except Exception as e:
                # lerobot's bus.disconnect() runs disable_torque(num_retry=5)
                # before closing the port; an alarm-state or unplugged motor
                # returns no status packet and lerobot raises ConnectionError.
                # Letting that propagate makes /session/end return 500 and
                # leaves the operator unable to exit the session without
                # restarting the backend. Log it and clear state so the next
                # session can re-init cleanly.
                logging.getLogger(__name__).warning(
                    "SO leader disconnect failed (motors may be in fault state — "
                    "power-cycle the leader arm): %s", e,
                )
            finally:
                self._leader = None

    async def read_action(self) -> TeleopAction:
        assert self._leader is not None
        loop = asyncio.get_running_loop()
        state = await loop.run_in_executor(None, self._leader.get_action)
        joint_pos = np.array([state[f"{j}.pos"] for j in JOINT_NAMES], dtype=np.float32)
        return TeleopAction(target_joint_pos=joint_pos)
