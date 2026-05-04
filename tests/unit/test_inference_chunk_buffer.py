import asyncio

import numpy as np
import pytest

from mimicrec.inference.chunk_buffer import ChunkBuffer
from mimicrec.inference.types import StepAction


def _step(i: int) -> StepAction:
    return StepAction(q=np.full(5, float(i)), gripper=0.0)


def _make_buffer(prefetch_threshold: float = 0.5) -> ChunkBuffer:
    return ChunkBuffer.create(prefetch_threshold=prefetch_threshold)


def test_pop_empty_returns_none():
    b = _make_buffer()
    assert b.pop_next() is None


def test_push_then_pop():
    b = _make_buffer()
    b.try_push_chunk([_step(0), _step(1), _step(2)], generation=b.current_generation())
    assert b.pop_next().q[0] == 0.0
    assert b.pop_next().q[0] == 1.0


def test_half_prefetch_fires_event_once():
    b = _make_buffer(prefetch_threshold=0.5)
    b.try_push_chunk([_step(i) for i in range(4)], generation=b.current_generation())
    # consume first two = 50%
    b.pop_next(); b.pop_next()
    assert b._refill_event.is_set()
    b._refill_event.clear()
    # consuming third must NOT re-fire (already in_flight)
    b.pop_next()
    assert not b._refill_event.is_set()
