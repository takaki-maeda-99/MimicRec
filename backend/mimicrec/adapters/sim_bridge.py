"""ZMQ-based simulator bridge adapter.

Connects to any simulator (Isaac Sim, MuJoCo, PyBullet, etc.) via a
lightweight ZMQ request-reply protocol. The simulator side runs a
bridge server that translates between ZMQ messages and the sim API.

Protocol (JSON over ZMQ REQ/REP):

    MimicRec → Bridge:
        {"cmd": "connect"}                          → {"ok": true, "dof": 6, "joint_names": [...]}
        {"cmd": "read_state"}                       → {"joint_pos": [...], "joint_vel": [...], "joint_effort": [...]}
        {"cmd": "send_command", "q": [...]}          → {"ok": true}
        {"cmd": "set_mode", "mode": "position"}     → {"ok": true}
        {"cmd": "disconnect"}                        → {"ok": true}

    Camera bridge (separate PUB socket):
        Publishes JPEG bytes on topic "{cam_name}"

Usage in config YAML:
    _target_: mimicrec.adapters.sim_bridge.SimBridgeAdapter
    address: tcp://localhost:5556
    dof: 6
    joint_names: [shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper]
"""
from __future__ import annotations

import asyncio
import json

import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.types import RobotState


class SimBridgeAdapter:
    """Robot adapter that communicates with a simulator via ZMQ."""

    name = "sim_bridge"

    def __init__(
        self,
        address: str = "tcp://localhost:5556",
        dof: int = 6,
        joint_names: list[str] | None = None,
    ):
        self._address = address
        self.dof = dof
        self.joint_names = joint_names or [f"j{i}" for i in range(dof)]
        self._ctx = None
        self._mode = RobotMode.POSITION

    async def _send_recv(self, msg: dict) -> dict:
        """Send a message and wait for reply with timeout.

        Uses a fresh REQ socket per call to avoid ZMQ state machine issues
        (REQ sockets cannot send again if a previous recv timed out).
        """
        import zmq
        import zmq.asyncio

        sock = self._ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(self._address)
        try:
            await sock.send_json(msg)
            return await asyncio.wait_for(sock.recv_json(), timeout=10.0)
        finally:
            sock.close()

    async def connect(self) -> None:
        import zmq
        import zmq.asyncio

        self._ctx = zmq.asyncio.Context()

        # Handshake with retry
        for attempt in range(5):
            try:
                reply = await self._send_recv({"cmd": "connect"})
                break
            except (asyncio.TimeoutError, Exception):
                if attempt == 4:
                    raise
                await asyncio.sleep(1.0)
        if reply.get("dof"):
            self.dof = reply["dof"]
        if reply.get("joint_names"):
            self.joint_names = reply["joint_names"]

    async def disconnect(self) -> None:
        if self._ctx:
            try:
                await self._send_recv({"cmd": "disconnect"})
            except Exception:
                pass
            self._ctx.term()
            self._ctx = None

    async def read_state(self) -> RobotState:
        assert self._ctx is not None
        reply = await self._send_recv({"cmd": "read_state"})
        return RobotState(
            joint_pos=np.array(reply["joint_pos"], dtype=np.float32),
            joint_vel=np.array(reply.get("joint_vel", [0.0] * self.dof), dtype=np.float32),
            joint_effort=np.array(reply.get("joint_effort", [0.0] * self.dof), dtype=np.float32),
        )

    async def send_joint_command(self, q: np.ndarray) -> None:
        assert self._ctx is not None
        await self._send_recv({"cmd": "send_command", "q": q.tolist()})

    async def set_mode(self, mode: RobotMode) -> None:
        assert self._ctx is not None
        await self._send_recv({"cmd": "set_mode", "mode": mode.value})
        self._mode = mode

    def supports_mode(self, mode: RobotMode) -> bool:
        return True  # Sim supports all modes
