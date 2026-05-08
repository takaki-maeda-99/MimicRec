from __future__ import annotations
import asyncio
from pathlib import Path
import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.errors import HandTeachNotSupportedError
from mimicrec.types import RobotState

JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def _so_calibrate_command(*, port: str, arm_id: str, calibrate_type: str) -> str:
    return (
        f"python scripts/calibrate_so101.py --port {port} --id {arm_id} "
        f"--type {calibrate_type}"
    )


def _so_calib_missing_message(
    *, role: str, arm_id: str, port: str, file_path: Path, calibrate_type: str,
) -> str:
    cmd = _so_calibrate_command(port=port, arm_id=arm_id, calibrate_type=calibrate_type)
    return (
        f"{role} '{arm_id}' on {port} has no calibration.\n\n"
        f"If you already have a calibration file for this arm, place it at:\n"
        f"  {file_path}\n\n"
        f"Otherwise, run calibration:\n"
        f"  {cmd}"
    )


def _so_calib_mismatch_message(
    *, role: str, arm_id: str, port: str, file_path: Path, calibrate_type: str,
) -> str:
    cmd = _so_calibrate_command(port=port, arm_id=arm_id, calibrate_type=calibrate_type)
    return (
        f"{role} '{arm_id}' on {port} motors do not match the calibration file at:\n"
        f"  {file_path}\n\n"
        f"The motors may have been swapped, power-cycled, or the file is for a "
        f"different arm. If you have the correct calibration file for these motors, "
        f"place it at the path above.\n\n"
        f"Otherwise, re-run calibration:\n"
        f"  {cmd}"
    )


async def _is_calibrated_safely(loop, hw) -> bool:
    """Read ``is_calibrated`` off-thread (lerobot's getter does motor I/O).

    Treat any exception as 'not calibrated' so we surface a clean
    HardwareError rather than crashing inside connect()."""
    try:
        return await loop.run_in_executor(None, lambda: hw.is_calibrated)
    except Exception:
        return False


class SO101Adapter:
    name = "so101"
    dof = 6
    joint_names = JOINT_NAMES

    @classmethod
    def default_gripper_convention(cls) -> GripperConvention:
        """SO-101 gripper raw range: lerobot RANGE_0_100, 0=closed, 100=open."""
        return GripperConvention(closed_at=0.0, open_at=100.0)

    @classmethod
    def proprio_layout(cls) -> ProprioLayout:
        """SO-101's joint_pos already includes the packed gripper at index 5;
        no separate column needs concatenation."""
        return ProprioLayout(
            columns=("observation.state.joint_pos",),
            output_names=(
                "shoulder_pan", "shoulder_lift", "elbow_flex",
                "wrist_flex", "wrist_roll", "gripper",
            ),
            gripper_via_column="observation.state.joint_pos",
            gripper_index_in_column=5,
        )

    def __init__(self, port: str = "/dev/ttyACM0", id: str = "my_awesome_follower_arm"):
        self._port = port
        self._id = id
        self._mode = RobotMode.POSITION
        self._follower = None
        # Feetech serial bus is half-duplex; concurrent read+write from different
        # threads produces "[TxRxResult] Port is in use!". Serialize bus access.
        self._bus_lock = asyncio.Lock()

    async def connect(self) -> None:
        import functools
        from mimicrec.errors import HardwareError
        from lerobot.robots.so_follower.so_follower import SO101Follower
        from lerobot.robots.so_follower.config_so_follower import SOFollowerRobotConfig
        cfg = SOFollowerRobotConfig(port=self._port, id=self._id)
        self._follower = SO101Follower(cfg)
        loop = asyncio.get_running_loop()

        # Two things lerobot's connect(calibrate=False) does NOT do, both of
        # which leave the session limping into READY only to fail downstream:
        #   1. raise when the calibration JSON is missing
        #   2. write the loaded JSON to the motors when they're out of sync
        # Without these guards, the reader loop hits "has no calibration
        # registered" tens of seconds later, declares a FatalHardwareError,
        # and the operator is bounced back to the settings screen with no
        # actionable context. Catch both here at startup.
        fpath = self._follower.calibration_fpath
        if not fpath.is_file():
            raise HardwareError(_so_calib_missing_message(
                role="SO-101 follower", arm_id=self._id, port=self._port,
                file_path=fpath, calibrate_type="follower",
            ))

        async with self._bus_lock:
            await loop.run_in_executor(None, functools.partial(self._follower.connect, calibrate=False))

        # File loaded into self._follower.calibration but the motors may
        # still hold stale (or zero) calibration from a power cycle / arm
        # swap. Apply the file values to the motors — the same recovery
        # lerobot performs when an operator presses ENTER at its prompt —
        # then verify, and fail with an actionable message if it didn't
        # take.
        if not await _is_calibrated_safely(loop, self._follower):
            try:
                async with self._bus_lock:
                    await loop.run_in_executor(
                        None,
                        lambda: self._follower.bus.write_calibration(self._follower.calibration),
                    )
            except Exception:
                pass
            if not await _is_calibrated_safely(loop, self._follower):
                # Disconnect cleanly so the serial port isn't left held by a
                # half-initialized adapter — otherwise the operator can't
                # even retry without yanking the cable.
                try:
                    async with self._bus_lock:
                        await loop.run_in_executor(None, self._follower.disconnect)
                except Exception:
                    pass
                self._follower = None
                raise HardwareError(_so_calib_mismatch_message(
                    role="SO-101 follower", arm_id=self._id, port=self._port,
                    file_path=fpath, calibrate_type="follower",
                ))

    async def disconnect(self) -> None:
        if self._follower:
            import logging
            loop = asyncio.get_running_loop()
            try:
                async with self._bus_lock:
                    await loop.run_in_executor(None, self._follower.disconnect)
            except Exception as e:
                # Motors may be unresponsive (alarm state, loose cable, etc.).
                # Don't let a torque-off failure block session teardown — log
                # it and clear state so the next session can re-init cleanly.
                logging.getLogger(__name__).warning(
                    "SO101 disconnect failed (motors may be in fault state — "
                    "power-cycle the arm): %s", e,
                )
            finally:
                self._follower = None

    async def read_state(self) -> RobotState:
        assert self._follower is not None
        loop = asyncio.get_running_loop()
        async with self._bus_lock:
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
        async with self._bus_lock:
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
