"""ZMQ-based simulator camera that receives JPEG frames from a sim bridge.

The simulator bridge publishes camera frames as raw JPEG bytes on a ZMQ
PUB socket. This camera subscribes and decodes each frame.

Usage in config YAML:
    _target_: mimicrec.cameras.sim_camera.SimCamera
    name: front
    address: tcp://localhost:5557
"""
from __future__ import annotations

import asyncio

import cv2
import numpy as np

from mimicrec.types import Frame


class SimCamera:
    def __init__(self, name: str, address: str = "tcp://localhost:5557"):
        self.name = name
        self._address = address
        self._socket = None
        self._ctx = None

    async def connect(self):
        import zmq
        import zmq.asyncio

        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.SUB)
        self._socket.connect(self._address)
        self._socket.subscribe(self.name.encode())

    async def disconnect(self):
        if self._socket:
            self._socket.close()
            self._socket = None
        if self._ctx:
            self._ctx.term()
            self._ctx = None

    async def read(self) -> Frame:
        assert self._socket is not None
        # Receive multipart: [topic, jpeg_bytes]
        parts = await self._socket.recv_multipart()
        jpeg_bytes = parts[-1]
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise TimeoutError(f"sim camera {self.name}: failed to decode frame")
        return Frame(image=bgr)
