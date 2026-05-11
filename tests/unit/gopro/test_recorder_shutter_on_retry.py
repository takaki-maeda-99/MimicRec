"""Bug: shutter_on lacks retry while shutter_off retries 3×.

The HERO11 occasionally returns HTTP 500 Internal Server Error on
``set_shutter on`` (USB-CDC-NCM hiccup, mid-finalization of a previous
mp4, or a transient HTTP queue contention with preview/media_list).
``shutter_off`` already absorbs this with a 3-attempt retry loop at
0.2s intervals, but ``shutter_on`` had no retry — one transient error
silently dropped a whole episode of GoPro footage.

These tests pin the symmetric retry behavior so a future refactor
cannot regress it.
"""
from __future__ import annotations

import asyncio

import pytest

from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.recorder import GoProRecorder
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus


@pytest.fixture
def paths(tmp_path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def queue(paths):
    return DLQueue(paths.pending_dir / "gopro_dl")


def _make_flaky_shutter_on(fail_count: int, real):
    """Wrap a shutter_on that fails the first ``fail_count`` times, then
    succeeds. Mirrors the transient HTTP 500 behavior we see on hardware."""
    state = {"calls": 0}

    async def flaky():
        state["calls"] += 1
        if state["calls"] <= fail_count:
            raise RuntimeError(f"transient 500 (attempt {state['calls']})")
        await real()

    flaky.calls = state  # type: ignore[attr-defined]
    return flaky


@pytest.mark.asyncio
async def test_shutter_on_recovers_from_two_transient_failures(paths, queue):
    """One transient 500 must not lose the episode. Mirror shutter_off."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    real_on = d.shutter_on
    flaky = _make_flaky_shutter_on(fail_count=2, real=real_on)
    d.shutter_on = flaky  # type: ignore[assignment]

    errs = ErrorBus()
    sub = errs.subscribe()
    r = GoProRecorder(d, queue, paths, errs, slot="g1")

    await r.start_episode(0, t_host_mono_ns=10_000_000_000)
    await r.stop_episode(0)

    # The 3rd attempt should have succeeded → episode produced a job.
    job = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
    assert job.episode_index == 0
    # No HardwareError was published for the transient failures.
    assert sub.empty(), "transient retries must not surface as user-visible errors"
    assert flaky.calls["calls"] == 3  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_shutter_on_persistent_failure_publishes_hardware_error(paths, queue):
    """If all attempts fail, behavior must match the pre-fix path: error
    published, recorder state cleared, no DL job enqueued."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()

    async def always_fails():
        raise RuntimeError("hard 500")

    d.shutter_on = always_fails  # type: ignore[assignment]
    errs = ErrorBus()
    sub = errs.subscribe()
    r = GoProRecorder(d, queue, paths, errs, slot="g1")

    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    evt = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert "shutter_on" in str(evt)
    # No new file → no DL job enqueued.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.dequeue(), timeout=0.2)


@pytest.mark.asyncio
async def test_shutter_on_first_try_no_retry_overhead(paths, queue):
    """Happy path: 1 call, no extra latency."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    real_on = d.shutter_on
    calls = {"n": 0}

    async def counting():
        calls["n"] += 1
        await real_on()

    d.shutter_on = counting  # type: ignore[assignment]
    errs = ErrorBus()
    r = GoProRecorder(d, queue, paths, errs, slot="g1")

    t0 = asyncio.get_event_loop().time()
    await r.start_episode(0, t_host_mono_ns=0)
    elapsed = asyncio.get_event_loop().time() - t0
    assert calls["n"] == 1
    assert elapsed < 0.1, f"happy path must not sleep; got {elapsed:.3f}s"
