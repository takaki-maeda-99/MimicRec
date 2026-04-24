from __future__ import annotations
import asyncio


class ErrorBus:
    def __init__(self) -> None:
        self._subs: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.append(q)
        return q

    async def publish(self, event: BaseException | dict) -> None:
        for q in self._subs:
            await q.put(event)
