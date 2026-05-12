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
import threading

import numpy as np

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.types import RobotState


class SimBridgeAdapter:
    """Robot adapter that communicates with a simulator via ZMQ.

    Uses a synchronous ZMQ REQ socket on a dedicated thread to avoid
    asyncio + ZMQ interaction issues. The adapter's async methods
    delegate to this thread via run_in_executor.
    """

    name = "sim_bridge"

    @classmethod
    def default_gripper_convention(cls) -> GripperConvention:
        """SimBridge mirrors SO-101's gripper convention by default (0..100,
        0=closed, 100=open). Override via subclassing if pointed at a sim with
        different units."""
        return GripperConvention(closed_at=0.0, open_at=100.0)

    @classmethod
    def proprio_layout(cls) -> ProprioLayout:
        """Mirrors SO-101: joint_pos column already includes the packed
        gripper at the last index (index 5 for the default 6-DoF config)."""
        return ProprioLayout(
            columns=("observation.state.joint_pos",),
            output_names=(
                "shoulder_pan", "shoulder_lift", "elbow_flex",
                "wrist_flex", "wrist_roll", "gripper",
            ),
            gripper_via_column="observation.state.joint_pos",
            gripper_index_in_column=5,
        )

    def __init__(
        self,
        address: str = "tcp://localhost:5556",
        dof: int = 6,
        joint_names: list[str] | None = None,
    ):
        self._address = address
        self.dof = dof
        self.joint_names = joint_names or [f"j{i}" for i in range(dof)]
        self._socket = None
        self._ctx = None
        self._lock = threading.Lock()
        self._mode = RobotMode.POSITION

    def _send_recv_sync(self, msg: dict) -> dict:
        """Thread-safe synchronous send/recv via DEALER socket.

        DEALER sends [empty, data] and receives [empty, data] from ROUTER.
        """
        import json
        with self._lock:
            self._socket.send_multipart([b"", json.dumps(msg).encode()])
            frames = self._socket.recv_multipart()
            return json.loads(frames[-1])

    async def connect(self) -> None:
        import zmq

        self._ctx = zmq.Context()
        self._socket = self._ctx.socket(zmq.DEALER)
        self._socket.setsockopt(zmq.RCVTIMEO, 10000)
        self._socket.setsockopt(zmq.SNDTIMEO, 5000)
        self._socket.connect(self._address)

        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, self._send_recv_sync, {"cmd": "connect"})
        if reply.get("dof"):
            self.dof = reply["dof"]
        if reply.get("joint_names"):
            self.joint_names = reply["joint_names"]

    async def disconnect(self) -> None:
        if self._socket:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, self._send_recv_sync, {"cmd": "disconnect"})
            except Exception:
                pass
            self._socket.close()
            self._socket = None
        if self._ctx:
            self._ctx.term()
            self._ctx = None

    async def read_state(self) -> RobotState:
        assert self._socket is not None
        loop = asyncio.get_running_loop()
        reply = await loop.run_in_executor(None, self._send_recv_sync, {"cmd": "read_state"})
        return RobotState(
            joint_pos=np.array(reply["joint_pos"], dtype=np.float32),
            joint_vel=np.array(reply.get("joint_vel", [0.0] * self.dof), dtype=np.float32),
            joint_effort=np.array(reply.get("joint_effort", [0.0] * self.dof), dtype=np.float32),
        )

    async def send_joint_command(self, q: np.ndarray) -> None:
        assert self._socket is not None
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._send_recv_sync, {"cmd": "send_command", "q": q.tolist()})

    async def set_mode(self, mode: RobotMode) -> None:
        assert self._socket is not None
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._send_recv_sync, {"cmd": "set_mode", "mode": mode.value})
        self._mode = mode

    def supports_mode(self, mode: RobotMode) -> bool:
        return True  # Sim supports all modes
