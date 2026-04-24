from __future__ import annotations
import time
from typing import Protocol


class Clock(Protocol):
    def monotonic_ns(self) -> int: ...
    async def sleep_until(self, t_mono_ns: int) -> None: ...


class RealClock:
    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    async def sleep_until(self, t_mono_ns: int) -> None:
        import asyncio
        now = time.monotonic_ns()
        delta = (t_mono_ns - now) / 1e9
        if delta > 0:
            await asyncio.sleep(delta)


class FakeClock:
    def __init__(self, start_ns: int = 0):
        import asyncio
        self._now = start_ns
        self._waiters: list[tuple[int, asyncio.Future[None]]] = []

    def monotonic_ns(self) -> int:
        return self._now

    def set(self, t_mono_ns: int) -> None:
        assert t_mono_ns >= self._now, "FakeClock only moves forward"
        self._now = t_mono_ns
        still_waiting = []
        for due, fut in self._waiters:
            if due <= t_mono_ns and not fut.done():
                fut.set_result(None)
            else:
                still_waiting.append((due, fut))
        self._waiters = still_waiting

    def advance(self, delta_ns: int) -> None:
        self.set(self._now + delta_ns)

    async def sleep_until(self, t_mono_ns: int) -> None:
        import asyncio
        if t_mono_ns <= self._now:
            return
        fut: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        self._waiters.append((t_mono_ns, fut))
        await fut
