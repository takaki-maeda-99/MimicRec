import asyncio
import pytest
from mimicrec.util.latest_value import LatestValue


async def test_peek_returns_none_before_first_write():
    lv: LatestValue[int] = LatestValue()
    assert lv.peek() is None


async def test_peek_returns_last_write():
    lv: LatestValue[int] = LatestValue()
    lv.set(5, t_mono_ns=100)
    lv.set(7, t_mono_ns=200)
    stamped = lv.peek()
    assert stamped is not None
    assert stamped.value == 7
    assert stamped.t_mono_ns == 200


async def test_wait_for_new_resolves_on_next_write():
    lv: LatestValue[int] = LatestValue()
    lv.set(1, t_mono_ns=100)
    seq_before = lv.seq

    async def writer():
        await asyncio.sleep(0.01)
        lv.set(2, t_mono_ns=200)

    asyncio.create_task(writer())
    s = await asyncio.wait_for(lv.wait_for_new(since_seq=seq_before), timeout=0.5)
    assert s.value == 2


async def test_wait_for_new_returns_immediately_if_already_newer():
    lv: LatestValue[int] = LatestValue()
    lv.set(1, t_mono_ns=100)
    seq_before = lv.seq
    lv.set(2, t_mono_ns=200)
    s = await asyncio.wait_for(lv.wait_for_new(since_seq=seq_before), timeout=0.5)
    assert s.value == 2
