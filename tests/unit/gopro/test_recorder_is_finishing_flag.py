"""Bug: ``self.session.state = REVIEW`` flips BEFORE
``gopro_registry.episode_stop`` runs (the GoPro shutter_off + media_list
polling can take 0.5-3 s). For that whole window, no sidecar exists yet
and ``dl_in_flight_count`` returns 0 — so the operator can hit Space
the instant the UI shows REVIEW and the save gate lets them through,
defeating the whole point of the gate.

Fix: ``GoProRecorder`` exposes ``is_finishing`` (True between the start
of ``stop_episode`` and the moment a sidecar is enqueued / the no-file
warning is published). ``GoProDeviceRegistry.dl_in_flight_count``
adds the count of recorders currently in that state, so the gate sees
"DL imminent" even before the sidecar appears.
"""
from __future__ import annotations

import asyncio

import pytest

from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.recorder import GoProRecorder
from mimicrec.gopro.registry import GoProDeviceRegistry
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


@pytest.mark.asyncio
async def test_is_finishing_false_before_stop(paths, queue):
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    r = GoProRecorder(d, queue, paths, ErrorBus(), slot="g1")
    assert r.is_finishing is False


@pytest.mark.asyncio
async def test_is_finishing_true_during_stop_episode(paths, queue):
    """Observe is_finishing flip on/off across stop_episode. We slow down
    shutter_off so the test can sample the flag while it is held."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    real_off = d.shutter_off

    started = asyncio.Event()
    proceed = asyncio.Event()

    async def slow_off():
        started.set()
        await proceed.wait()
        await real_off()

    d.shutter_off = slow_off  # type: ignore[assignment]
    r = GoProRecorder(d, queue, paths, ErrorBus(), slot="g1")

    await r.start_episode(0, t_host_mono_ns=0)
    task = asyncio.create_task(r.stop_episode(0))
    await started.wait()
    # Mid-stop: flag should be True.
    assert r.is_finishing is True, "is_finishing must be True between shutter_off start and sidecar enqueue"
    proceed.set()
    await task
    # After stop completed: flag back to False.
    assert r.is_finishing is False


@pytest.mark.asyncio
async def test_registry_dl_in_flight_counts_finishing_recorders(paths):
    """The registry's dl_in_flight_count must include recorders that are
    mid-stop_episode, even before any sidecar is on disk."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    started = asyncio.Event()
    proceed = asyncio.Event()
    real_off = d.shutter_off

    async def slow_off():
        started.set()
        await proceed.wait()
        await real_off()

    d.shutter_off = slow_off  # type: ignore[assignment]

    reg = GoProDeviceRegistry(devices=[(d.name, d)], paths=paths, errors=ErrorBus())
    await reg.start()
    try:
        await reg.episode_start(0, t_host_mono_ns=0)
        # Baseline: no DL in flight before stop begins.
        assert reg.dl_in_flight_count == 0

        stop_task = asyncio.create_task(reg.episode_stop(0))
        await started.wait()
        # Mid-stop: registry must report >0 even though no sidecar is on disk yet.
        assert reg.dl_in_flight_count >= 1, (
            "registry must report dl_in_flight while a recorder is mid-stop_episode"
        )

        proceed.set()
        await stop_task
        # After stop: a sidecar is on disk → dl_in_flight_count is still ≥ 1
        # (now driven by the queue, not the recorder).
        assert reg.dl_in_flight_count >= 1
    finally:
        await reg.stop()
