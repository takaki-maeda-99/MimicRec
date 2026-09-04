"""Backend and named-resource adapter for the SO-101 safety daemon."""
from __future__ import annotations

import asyncio
from typing import Mapping

import numpy as np
import zmq

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.so101 import JOINT_NAMES
from mimicrec.adapters.so101_protocol import (
    CMD_CONNECT,
    CMD_DISCONNECT,
    CMD_HEARTBEAT,
    CMD_READ_STATE,
    CMD_SEND_COMMAND,
    CMD_SEND_GRIPPER_COMMAND,
    CMD_SET_MODE,
    DEFAULT_ZMQ_ADDRESS,
    MODE_POSITION,
    MODE_TORQUE_OFF,
    validate_reply,
)
from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.errors import HandTeachNotSupportedError, HardwareError
from mimicrec.motion.types import (
    JointPositionCommand,
    JointResourceState,
    ResourceCommand,
    ResourceState,
    ScalarResourceState,
    ScalarPositionCommand,
)
from mimicrec.types import RobotState

ARM_JOINT_NAMES = JOINT_NAMES[:5]


class SO101ZmqAdapter:
    name = "so101"
    dof = 5
    joint_names = list(ARM_JOINT_NAMES)
    resource_names = ("arm", "gripper")

    @classmethod
    def default_gripper_convention(cls) -> GripperConvention:
        return GripperConvention(closed_at=0.0, open_at=100.0)

    @classmethod
    def proprio_layout(cls) -> ProprioLayout:
        return ProprioLayout(
            columns=(
                "observation.state.joint_pos",
                "observation.state.gripper_pos",
            ),
            output_names=(*ARM_JOINT_NAMES, "gripper"),
            gripper_via_column="observation.state.gripper_pos",
            gripper_index_in_column=0,
        )

    def __init__(
        self,
        address: str = DEFAULT_ZMQ_ADDRESS,
        heartbeat_interval_ms: int = 200,
        request_timeout_ms: int = 1000,
    ) -> None:
        self._address = address
        self._heartbeat_interval_ms = int(heartbeat_interval_ms)
        self._request_timeout_ms = int(request_timeout_ms)
        self._ctx: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        self._bus_lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task | None = None

    def _send_recv_sync(self, message: dict) -> dict:
        assert self._socket is not None
        self._socket.send_json(message)
        return self._socket.recv_json()

    async def _request(self, message: dict) -> dict:
        loop = asyncio.get_running_loop()
        async with self._bus_lock:
            try:
                reply = await loop.run_in_executor(
                    None, self._send_recv_sync, message
                )
            except Exception as exc:
                raise HardwareError(
                    f"SO-101 daemon request failed at {self._address}: {exc}"
                ) from exc
        try:
            return validate_reply(reply)
        except ValueError as exc:
            raise HardwareError(str(exc)) from exc

    async def connect(self) -> None:
        if self._socket is not None:
            raise HardwareError("SO101ZmqAdapter is already connected")
        self._ctx = zmq.Context()
        self._socket = self._ctx.socket(zmq.REQ)
        self._socket.setsockopt(zmq.RCVTIMEO, self._request_timeout_ms)
        self._socket.setsockopt(zmq.SNDTIMEO, self._request_timeout_ms)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.connect(self._address)
        try:
            reply = await self._request({"cmd": CMD_CONNECT})
            if not reply["ok"]:
                raise HardwareError(f"SO-101 daemon refused connect: {reply}")
            self.dof = int(reply.get("dof", self.dof))
            self.joint_names = list(reply.get("joint_names", self.joint_names))
        except Exception:
            self._teardown_socket()
            raise
        self._heartbeat_task = asyncio.create_task(self._run_heartbeat())

    async def disconnect(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None
        if self._socket is not None:
            try:
                await self._request({"cmd": CMD_DISCONNECT})
            except Exception:
                pass
        self._teardown_socket()

    async def activate(self) -> None:
        """Seed the measured pose and enable torque for graph control.

        The daemon performs the hold-current operation atomically before it
        enters POSITION, so graph startup cannot snap toward a stale target.
        """
        await self.set_mode(RobotMode.POSITION)

    def _teardown_socket(self) -> None:
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None
        if self._ctx is not None:
            self._ctx.term()
            self._ctx = None

    async def _run_heartbeat(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval_ms / 1000.0)
                try:
                    await self._request({"cmd": CMD_HEARTBEAT})
                except HardwareError:
                    # The daemon independently enforces its lease timeout.
                    pass
        except asyncio.CancelledError:
            return

    async def read_state(self) -> RobotState:
        reply = await self._request({"cmd": CMD_READ_STATE})
        if not reply["ok"]:
            raise HardwareError(f"SO-101 daemon read failed: {reply}")
        return RobotState(
            joint_pos=np.asarray(reply["joint_pos"], dtype=np.float32),
            joint_vel=np.asarray(reply["joint_vel"], dtype=np.float32),
            joint_effort=np.asarray(reply["joint_effort"], dtype=np.float32),
            t_mono_ns=int(reply.get("t_mono_ns", 0)),
            gripper_pos=(
                float(reply["gripper_pos"])
                if reply.get("gripper_pos") is not None
                else None
            ),
            daemon_target_joint_pos=(
                np.asarray(reply["target_joint_pos"], dtype=np.float32)
                if reply.get("target_joint_pos") is not None
                else None
            ),
        )

    async def send_joint_command(self, q: np.ndarray) -> None:
        values = np.asarray(q, dtype=np.float64)
        if values.shape != (self.dof,) or not np.isfinite(values).all():
            raise HardwareError(
                f"SO-101 command must be a finite ({self.dof},) vector"
            )
        reply = await self._request({"cmd": CMD_SEND_COMMAND, "q": values.tolist()})
        if not reply["ok"]:
            raise HardwareError(f"SO-101 daemon rejected command: {reply}")

    async def send_gripper_raw(self, position: float) -> None:
        value = float(position)
        if not np.isfinite(value):
            raise HardwareError("non-finite SO-101 gripper command")
        reply = await self._request({
            "cmd": CMD_SEND_GRIPPER_COMMAND,
            "gripper": value,
        })
        if not reply["ok"]:
            raise HardwareError(f"SO-101 daemon rejected gripper: {reply}")

    async def send_gripper_command(self, gripper: float) -> None:
        """Legacy normalized command: 0=closed and 1=open."""

        normalized = float(np.clip(gripper, 0.0, 1.0))
        convention = self.default_gripper_convention()
        await self.send_gripper_raw(
            convention.closed_at
            + normalized * (convention.open_at - convention.closed_at)
        )

    async def set_mode(self, mode: RobotMode) -> None:
        if mode == RobotMode.GRAVITY_COMP:
            raise HandTeachNotSupportedError(
                "SO-101 does not support gravity compensation"
            )
        daemon_mode = (
            MODE_POSITION if mode == RobotMode.POSITION else MODE_TORQUE_OFF
        )
        reply = await self._request({"cmd": CMD_SET_MODE, "mode": daemon_mode})
        if not reply["ok"]:
            raise HardwareError(f"SO-101 daemon rejected mode: {reply}")

    def supports_mode(self, mode: RobotMode) -> bool:
        return mode != RobotMode.GRAVITY_COMP

    async def read_resources(self) -> Mapping[str, ResourceState]:
        state = await self.read_state()
        return {
            "arm": JointResourceState(
                # The daemon/Feetech boundary uses degrees. MotionRuntime is
                # embodiment-independent and always exposes revolute joints
                # in SI units.
                position=np.deg2rad(state.joint_pos),
                velocity=np.deg2rad(state.joint_vel),
                effort=state.joint_effort,
                joint_names=tuple(self.joint_names),
                t_mono_ns=state.t_mono_ns,
                target_position=(
                    np.deg2rad(state.daemon_target_joint_pos)
                    if state.daemon_target_joint_pos is not None
                    else None
                ),
            ),
            "gripper": ScalarResourceState(
                position=(state.gripper_pos or 0.0),
                t_mono_ns=state.t_mono_ns,
            ),
        }

    async def send_commands(
        self, commands: Mapping[str, ResourceCommand]
    ) -> None:
        unknown = set(commands) - set(self.resource_names)
        if unknown:
            raise ValueError(f"unknown SO-101 resources: {sorted(unknown)}")
        arm = commands.get("arm")
        gripper = commands.get("gripper")
        if arm is not None:
            if not isinstance(arm, JointPositionCommand):
                raise TypeError("SO-101 arm requires JointPositionCommand")
            values = np.rad2deg(np.asarray(arm.position, dtype=np.float64))
            if values.shape != (self.dof,) or not np.isfinite(values).all():
                raise HardwareError(
                    f"SO-101 command must be a finite ({self.dof},) vector"
                )
            message = {"cmd": CMD_SEND_COMMAND, "q": values.tolist()}
            if gripper is not None:
                if not isinstance(gripper, ScalarPositionCommand):
                    raise TypeError("SO-101 gripper requires ScalarPositionCommand")
                value = float(gripper.position)
                if not np.isfinite(value):
                    raise HardwareError("non-finite SO-101 gripper command")
                # One daemon request and one Feetech sync-write keeps arm and
                # gripper traffic from doubling the serial bus load at 60 Hz.
                message["gripper"] = value
            reply = await self._request(message)
            if not reply["ok"]:
                raise HardwareError(f"SO-101 daemon rejected command: {reply}")
            return
        if gripper is not None:
            if not isinstance(gripper, ScalarPositionCommand):
                raise TypeError("SO-101 gripper requires ScalarPositionCommand")
            await self.send_gripper_raw(gripper.position)

    async def safe_stop(self) -> None:
        await self.set_mode(RobotMode.TORQUE_OFF)

    async def estop(self) -> dict:
        await self.safe_stop()
        return {"ok": True, "mode": MODE_TORQUE_OFF}

    async def clear_estop(self) -> dict:
        # Re-entering POSITION seeds the current measured pose daemon-side,
        # so clearing cannot snap toward a stale target.
        await self.set_mode(RobotMode.POSITION)
        return {"ok": True, "mode": MODE_POSITION}
