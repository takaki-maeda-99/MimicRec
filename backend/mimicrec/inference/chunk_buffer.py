from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass, field

from mimicrec.inference.types import StepAction


@dataclass
class ChunkBuffer:
    """Action chunk buffer with half-prefetch trigger and instruction-flush.

    Concurrency contract: SINGLE producer (run_inference_producer), SINGLE
    consumer (run_inference_control_loop), BOTH on the same asyncio loop.
    """
    _steps: deque[StepAction]
    _origin_size: int = 0
    _refill_event: asyncio.Event = field(default_factory=asyncio.Event)
    _refill_in_flight: bool = False
    _generation: int = 0
    prefetch_threshold: float = 0.5

    @classmethod
    def create(cls, prefetch_threshold: float = 0.5) -> "ChunkBuffer":
        return cls(_steps=deque(), prefetch_threshold=prefetch_threshold)

    def pop_next(self) -> StepAction | None:
        if not self._steps:
            return None
        step = self._steps.popleft()
        consumed_ratio = 1 - len(self._steps) / max(1, self._origin_size)
        if consumed_ratio >= self.prefetch_threshold and not self._refill_in_flight:
            self._refill_in_flight = True
            self._refill_event.set()
        return step

    def try_push_chunk(self, chunk: list[StepAction], generation: int) -> bool:
        if generation != self._generation:
            return False
        self._steps.extend(chunk)
        self._origin_size = len(self._steps)
        self._refill_in_flight = False
        return True

    def current_generation(self) -> int:
        return self._generation

    def depth(self) -> int:
        return len(self._steps)

    def origin_size(self) -> int:
        return self._origin_size

    def flush(self) -> int:
        """Drop any queued steps, bump generation, re-arm the producer.
        Returns the number of steps that were dropped (used by
        callers that emit `instruction_updated.flushed_steps` on the WS)."""
        flushed = len(self._steps)
        self._steps.clear()
        self._origin_size = 0
        self._generation += 1
        self._refill_in_flight = False
        self._refill_event.set()
        return flushed

    def request_refill_now(self) -> None:
        """Producer-facing signal used at startup, on producer-driven re-arm,
        and by the lifecycle on REVIEW → READY transition."""
        self._refill_in_flight = False
        self._refill_event.set()

    async def wait_for_refill(self) -> None:
        """Producer-facing wait. Encapsulates the underlying Event so the
        producer never touches `_refill_event` directly — keeps the seam
        clean for tests that swap a fake buffer in."""
        await self._refill_event.wait()
        self._refill_event.clear()
