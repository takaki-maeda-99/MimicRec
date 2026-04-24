from __future__ import annotations
import asyncio
from typing import Generic, TypeVar

from mimicrec.types import Stamped

T = TypeVar("T")


class LatestValue(Generic[T]):
    def __init__(self) -> None:
        self._stamped: Stamped[T] | None = None
        self._seq: int = 0
        self._cond = asyncio.Condition()

    @property
    def seq(self) -> int:
        return self._seq

    def peek(self) -> Stamped[T] | None:
        return self._stamped

    def set(self, value: T, t_mono_ns: int) -> None:
        self._stamped = Stamped(value=value, t_mono_ns=t_mono_ns)
        self._seq += 1
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._notify_all())

    async def _notify_all(self) -> None:
        async with self._cond:
            self._cond.notify_all()

    async def wait_for_new(self, since_seq: int | None = None) -> Stamped[T]:
        target = self._seq if since_seq is None else since_seq
        async with self._cond:
            while self._seq <= target or self._stamped is None:
                await self._cond.wait()
            return self._stamped
