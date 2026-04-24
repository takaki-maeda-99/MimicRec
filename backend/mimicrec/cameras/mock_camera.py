from __future__ import annotations
import asyncio
import numpy as np

from mimicrec.adapters.fault_profile import FaultProfile
from mimicrec.types import Frame


class MockCamera:
    def __init__(
        self,
        name: str,
        width: int = 64,
        height: int = 48,
        dt_ns: int = 33_000_000,
        fault: FaultProfile | None = None,
    ):
        self.name = name
        self._w, self._h = width, height
        self._dt_ns = dt_ns
        self._fault = fault
        self._last_frame: Frame | None = None
        self._counter = 0
        self.drop_next = 0

    async def read(self) -> Frame:
        await asyncio.sleep(self._dt_ns / 1e9)
        if self.drop_next > 0:
            self.drop_next -= 1
            raise TimeoutError("mock camera drop (drop_next)")
        if self._fault:
            if self._fault.roll_drop():
                raise TimeoutError("mock camera drop (fault)")
            await asyncio.sleep(self._fault.sample_delay_s())
            if self._fault.stuck_for_n_calls > 0 and self._last_frame is not None:
                self._fault.stuck_for_n_calls -= 1
                return self._last_frame
        img = np.full((self._h, self._w, 3), self._counter % 255, dtype=np.uint8)
        self._counter += 1
        frame = Frame(image=img)
        self._last_frame = frame
        return frame
