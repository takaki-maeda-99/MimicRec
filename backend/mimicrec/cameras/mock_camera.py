from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.types import Frame


class MockCamera:
    def __init__(self, name: str, width: int = 64, height: int = 48, dt_ns: int = 33_000_000):
        self.name = name
        self._w, self._h = width, height
        self._dt_ns = dt_ns
        self._counter = 0
        self.drop_next = 0

    async def read(self) -> Frame:
        await asyncio.sleep(self._dt_ns / 1e9)
        if self.drop_next > 0:
            self.drop_next -= 1
            raise TimeoutError("mock camera simulated drop")
        img = np.full((self._h, self._w, 3), self._counter % 255, dtype=np.uint8)
        self._counter += 1
        return Frame(image=img)
