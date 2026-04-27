"""ZMQ REQ client adapter for the reBotArm safety daemon.

The daemon runs in a separate Python 3.10 venv and owns the motor
connection + 500 Hz control loop + all safety. This adapter just
exchanges JSON messages with it.
"""
from __future__ import annotations

import asyncio

import numpy as np
import zmq

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.rebotarm_protocol import (
    CMD_CONNECT, CMD_DISCONNECT, CMD_READ_STATE, CMD_SEND_COMMAND,
    CMD_SEND_GRIPPER_COMMAND,
    CMD_SET_MODE, CMD_HEARTBEAT, CMD_ESTOP, CMD_CLEAR_ESTOP,
    DEFAULT_ZMQ_ADDRESS,
)
from mimicrec.errors import HardwareError
from mimicrec.types import RobotState


class ReBotArmZmqAdapter:
    name = "rebotarm"
    dof = 6                     # finalized in connect() from daemon reply
    joint_names: list[str] = [f"j{i}" for i in range(1, 7)]

    def __init__(
        self,
        address: str = DEFAULT_ZMQ_ADDRESS,
        heartbeat_interval_ms: int = 200,
        request_timeout_ms: int = 1000,
    ):
        self._address = address
        self._heartbeat_interval_ms = heartbeat_interval_ms
        self._request_timeout_ms = request_timeout_ms
        self._ctx: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        # half-duplex REQ socket — one outstanding request at a time
        self._bus_lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task | None = None

    # ---- bus helpers ------------------------------------------------

    def _send_recv_sync(self, msg: dict) -> dict:
        assert self._socket is not None
        self._socket.send_json(msg)
        return self._socket.recv_json()

    async def _request(self, msg: dict) -> dict:
        loop = asyncio.get_running_loop()
        async with self._bus_lock:
            return await loop.run_in_executor(None, self._send_recv_sync, msg)

    # ---- lifecycle --------------------------------------------------

    async def connect(self) -> None:
        if self._socket is not None:
            raise HardwareError("ReBotArmZmqAdapter is already connected; call disconnect() first")
        self._ctx = zmq.Context()
        self._socket = self._ctx.socket(zmq.REQ)
        self._socket.setsockopt(zmq.RCVTIMEO, self._request_timeout_ms)
        self._socket.setsockopt(zmq.SNDTIMEO, self._request_timeout_ms)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.connect(self._address)
        try:
            reply = await self._request({"cmd": CMD_CONNECT})
        except Exception as e:
            self._teardown_socket()
            raise HardwareError(f"reBotArm daemon connect failed: {e}") from e
        if not reply.get("ok"):
            self._teardown_socket()
            raise HardwareError(f"reBotArm daemon refused connect: {reply}")
        # daemon authoritative about dof / joint_names
        self.dof = int(reply.get("dof", self.dof))
        self.joint_names = list(reply.get("joint_names", self.joint_names))
        # spawn heartbeat
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

    def _teardown_socket(self) -> None:
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None
        if self._ctx is not None:
            self._ctx.term()
            self._ctx = None

    async def _run_heartbeat(self) -> None:
        interval = self._heartbeat_interval_ms / 1000.0
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._request({"cmd": CMD_HEARTBEAT})
                except Exception:
                    # network blip; daemon's own heartbeat watchdog handles it
                    pass
        except asyncio.CancelledError:
            return

    # ---- state / command --------------------------------------------

    async def read_state(self) -> RobotState:
        reply = await self._request({"cmd": CMD_READ_STATE})
        return RobotState(
            joint_pos=np.asarray(reply["joint_pos"], dtype=np.float32),
            joint_vel=np.asarray(reply["joint_vel"], dtype=np.float32),
            joint_effort=np.asarray(reply["joint_effort"], dtype=np.float32),
            ee_pos=(np.asarray(reply["ee_pos"], dtype=np.float32)
                    if reply.get("ee_pos") is not None else None),
            ee_rotvec=(np.asarray(reply["ee_rotvec"], dtype=np.float32)
                       if reply.get("ee_rotvec") is not None else None),
            gripper_pos=(float(reply["gripper_pos"])
                         if reply.get("gripper_pos") is not None else None),
        )

    async def send_joint_command(self, q: np.ndarray) -> None:
        if q.shape != (self.dof,):
            raise HardwareError(f"command shape {q.shape} != ({self.dof},)")
        if not np.isfinite(q).all():
            raise HardwareError("non-finite joint command")
        reply = await self._request({"cmd": CMD_SEND_COMMAND, "q": q.tolist()})
        if not reply.get("ok"):
            raise HardwareError(f"daemon rejected send_command: {reply}")

    async def send_gripper_command(self, gripper: float) -> None:
        """Send a gripper position target (radians).

        The daemon's gripper position controller takes over from the
        compliance loop while the daemon is in POSITION mode and tracks
        this target with kp/kd from ``configs/rebotarm_daemon.yaml``'s
        ``gripper.position_kp/position_kd``. Calling this in GRAVITY_COMP
        mode raises HardwareError (matches send_joint_command's contract).
        """
        if not np.isfinite(gripper):
            raise HardwareError("non-finite gripper command")
        reply = await self._request(
            {"cmd": CMD_SEND_GRIPPER_COMMAND, "gripper": float(gripper)}
        )
        if not reply.get("ok"):
            raise HardwareError(f"daemon rejected send_gripper_command: {reply}")

    async def set_mode(self, mode: RobotMode) -> None:
        reply = await self._request({"cmd": CMD_SET_MODE, "mode": mode.value})
        if not reply.get("ok"):
            raise HardwareError(f"daemon rejected set_mode: {reply}")

    def supports_mode(self, mode: RobotMode) -> bool:
        return True  # both POSITION and GRAVITY_COMP supported

    # ---- safety ------------------------------------------------------

    async def estop(self) -> dict:
        """Trigger E-stop on the daemon. Raises HardwareError if the daemon
        refuses (e.g. socket dead or daemon-side fault)."""
        reply = await self._request({"cmd": CMD_ESTOP})
        if not reply.get("ok"):
            raise HardwareError(f"daemon refused estop: {reply}")
        return reply

    async def clear_estop(self) -> dict:
        """Try to clear all latched faults. Returns the daemon reply
        (callers may need to inspect ``ok`` and ``reason`` because clear
        gates on temperature / heartbeat / torque). Raises HardwareError
        only on a transport / unknown-cmd failure (i.e. ``ok`` absent)."""
        reply = await self._request({"cmd": CMD_CLEAR_ESTOP})
        if "ok" not in reply:
            raise HardwareError(f"malformed clear_estop reply: {reply}")
        return reply
