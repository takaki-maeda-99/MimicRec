from __future__ import annotations
import asyncio
import cv2
import numpy as np

from mimicrec.types import Frame


class OpenCVCamera:
    def __init__(self, name: str, device_id: int = 0, width: int = 640, height: int = 480):
        self.name = name
        self._device_id = device_id
        self._width = width
        self._height = height
        self._cap = None

    def _open(self):
        self._cap = cv2.VideoCapture(self._device_id)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open camera {self._device_id}")

    def _close(self):
        if self._cap:
            self._cap.release()
            self._cap = None

    async def connect(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._open)

    async def disconnect(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._close)

    async def read(self) -> Frame:
        loop = asyncio.get_running_loop()
        ret, frame = await loop.run_in_executor(None, self._cap.read)
        if not ret or frame is None:
            raise TimeoutError(f"camera {self.name} read failed")
        return Frame(image=frame)
