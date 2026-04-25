"""Web-based keyboard teleoperator.

Receives joint deltas from a browser WebSocket via an asyncio.Queue.
The frontend captures keyboard events and sends them as JSON:
    {"joint": 0, "delta": 0.05}  — increment joint 0 by 0.05 rad
    {"joint": 0, "delta": -0.05} — decrement

The adapter maintains a running target position and returns it on read_action().
"""
from __future__ import annotations

import asyncio

import numpy as np

from mimicrec.adapters.teleop import TeleopType
from mimicrec.types import TeleopAction


class WebTeleoperator:
    name = "web_keyboard"
    type = TeleopType.KEYBOARD

    def __init__(self, dof: int = 9):
        self._dof = dof
        self._target = np.zeros(dof, dtype=np.float32)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._initialized = False

    @property
    def input_queue(self) -> asyncio.Queue:
        """Queue for receiving teleop commands from WebSocket hub."""
        return self._queue

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def read_action(self) -> TeleopAction:
        # Drain all pending deltas (non-blocking)
        while not self._queue.empty():
            try:
                msg = self._queue.get_nowait()
                joint = msg.get("joint", 0)
                delta = msg.get("delta", 0.0)
                # "reset" command: set target to current robot state
                if msg.get("cmd") == "reset" and "pos" in msg:
                    self._target = np.array(msg["pos"], dtype=np.float32)
                    self._initialized = True
                elif self._initialized and 0 <= joint < self._dof:
                    self._target[joint] += delta
            except asyncio.QueueEmpty:
                break

        await asyncio.sleep(0.005)

        # Before browser connects and sends "reset", return None so control loop skips
        if not self._initialized:
            return TeleopAction(target_joint_pos=None)

        return TeleopAction(target_joint_pos=self._target.copy())
