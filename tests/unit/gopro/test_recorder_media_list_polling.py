"""Bug: media_list polled immediately after shutter_off can race the
GoPro's mp4 finalization, returning no new file. The recorder publishes
'no new file detected — orphan or no recording' and never enqueues a DL
job. Result: ``pending_count`` stays 0 even though the camera IS still
finalizing the file, so Bug B (block episode_start while pending > 0)
never fires and the user's next shutter overlaps with the previous
episode's finalization on the same SD bus.

Fix: poll media_list a few times (up to ~1.5s) before giving up. Real
HERO11 finalization typically takes 0.5-1.0s for a 30s 1080p clip.
"""
from __future__ import annotations

import asyncio

import pytest

from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.recorder import GoProRecorder
from mimicrec.gopro.types import MediaItem
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
async def test_media_list_late_finalization_still_detects_new_file(paths, queue):
    """Simulate HERO11 finalizing the mp4 a few media_list polls late.
    The recorder must wait, see the file, and enqueue a DL job."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()

    # Drop the synchronous shutter_off-creates-file behavior of the mock,
    # then schedule the file to appear on the *3rd* media_list call —
    # mimicking the camera taking a moment to flush the moov atom.
    real_shutter_off = d.shutter_off

    async def shutter_off_no_file():
        # Skip the mock's synchronous file generation. The file appears
        # later via the media_list spy below.
        if d._disabled or not d._connected:
            return

    d.shutter_off = shutter_off_no_file  # type: ignore[assignment]

    real_media_list = d.media_list
    call_count = {"n": 0}
    pending_file = MediaItem(filename="GX010001.MP4", size=12345, mtime_ns=0)

    async def media_list_late():
        call_count["n"] += 1
        # First two calls return empty; the third reveals the file.
        if call_count["n"] >= 3:
            return [pending_file]
        return await real_media_list()

    d.media_list = media_list_late  # type: ignore[assignment]

    errs = ErrorBus()
    sub = errs.subscribe()
    r = GoProRecorder(d, queue, paths, errs, slot="g1")
    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    # The recorder must have polled media_list multiple times.
    assert call_count["n"] >= 3, (
        f"expected media_list to be polled until file appeared, got "
        f"{call_count['n']} calls"
    )
    # A DL job should have been enqueued — pending_count > 0 now.
    job = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
    assert job.episode_index == 0
    assert "GX010001" in job.sd_filename
    # No HardwareError should have surfaced for the late finalization.
    assert sub.empty(), (
        "transient media_list polling must not surface as user-visible errors"
    )


@pytest.mark.asyncio
async def test_media_list_never_returns_file_publishes_warning(paths, queue):
    """If polling exhausts without finding a new file, the existing
    'no new file detected' warning is preserved."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()

    async def shutter_off_no_file():
        return

    d.shutter_off = shutter_off_no_file  # type: ignore[assignment]
    # media_list always empty — simulate the case where shutter_on
    # actually failed earlier and no file was ever recorded.

    errs = ErrorBus()
    sub = errs.subscribe()
    r = GoProRecorder(d, queue, paths, errs, slot="g1")
    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    evt = await asyncio.wait_for(sub.get(), timeout=2.5)
    assert "no new file detected" in str(evt)


@pytest.mark.asyncio
async def test_media_list_first_try_no_polling_overhead(paths, queue):
    """Happy path: file visible on first media_list — no extra latency."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    errs = ErrorBus()
    r = GoProRecorder(d, queue, paths, errs, slot="g1")

    t0 = asyncio.get_event_loop().time()
    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)
    elapsed = asyncio.get_event_loop().time() - t0
    # Mock generates file synchronously; stop should be fast.
    assert elapsed < 0.3, f"happy path must not poll/sleep; got {elapsed:.3f}s"
    job = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
    assert job.episode_index == 0
