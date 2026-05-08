import asyncio
from pathlib import Path

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


@pytest.mark.asyncio
async def test_normal_lifecycle_enqueues_one_job(paths, queue):
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    errs = ErrorBus()
    r = GoProRecorder(d, queue, paths, errs)

    await r.start_episode(0, t_host_mono_ns=10_000_000_000)
    await r.stop_episode(0)

    job = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
    assert job.episode_index == 0
    assert job.cam_name == "g1"
    assert job.gopro_serial == "S1"
    assert job.sd_filename.startswith("GX")


@pytest.mark.asyncio
async def test_chapter_split_only_first_chapter_enqueued(paths, queue):
    d = MockGoProDevice(name="g1", usb_serial="S1", chapters_per_episode=3)
    await d.connect()
    errs = ErrorBus()
    sub = errs.subscribe()
    r = GoProRecorder(d, queue, paths, errs)

    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    job = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
    # First chapter has chapter==01
    assert "01" in job.sd_filename[:4]

    # Warning was published
    found_warn = False
    while not sub.empty():
        e = sub.get_nowait()
        if "chapter split" in str(e).lower():
            found_warn = True
    assert found_warn


@pytest.mark.asyncio
async def test_disabled_device_is_noop(paths, queue):
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    d.disable("test")
    errs = ErrorBus()
    r = GoProRecorder(d, queue, paths, errs)

    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.dequeue(), timeout=0.2)


@pytest.mark.asyncio
async def test_no_new_files_at_stop_skips_enqueue(paths, queue):
    """Mocked shutter that doesn't create files (= no recording happened)."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    async def _no_op():
        return None
    d.shutter_off = _no_op  # type: ignore[assignment]

    errs = ErrorBus()
    r = GoProRecorder(d, queue, paths, errs)
    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.dequeue(), timeout=0.2)
