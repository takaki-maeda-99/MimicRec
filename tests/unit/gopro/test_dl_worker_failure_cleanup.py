"""Bug: DLWorker leaves sidecars on disk after permanent DL/ffmpeg failures.

When download_file raises (or hangs and we add a timeout) or ffmpeg fails
on a truncated mp4, the worker publishes a HardwareError and returns.
The sidecar stays at ``pending_dl`` / ``commit_pending`` forever, so
``pending_count`` never drops to zero, ``Bug B`` (block episode_start
while pending > 0) blocks indefinitely, and the operator perceives the
system as ``stuck — save can't be done``.

Fix: on a permanent failure that we have no path to recover from
(download or ffmpeg), mark_done the sidecar so the queue drains.
The episode's GoPro footage is lost but the session keeps moving.

Also pins ``download_file`` having a timeout so a hung GoPro doesn't
freeze the queue forever.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from mimicrec.gopro.dl_queue import DLQueue, GoProDLJob
from mimicrec.gopro.dl_worker import GoProDLWorker
from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus


@pytest.fixture
def paths(tmp_path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    return p


def _make_job(paths, job_id: str = "j1") -> GoProDLJob:
    return GoProDLJob(
        job_id=job_id,
        gopro_serial="S1",
        sd_filename="GX010001.MP4",
        episode_index=0,
        chunk_index=0,
        cam_name="g1",
        episode_start_mono_ns=0,
        episode_stop_mono_ns=10_000_000_000,
    )


async def _make_queue_with_job(paths, job) -> DLQueue:
    q = DLQueue(paths.pending_dir / "gopro_dl")
    await q.enqueue(job)
    return q


@pytest.mark.asyncio
async def test_dl_failure_removes_sidecar(paths):
    """download_file raises → sidecar must be cleaned up so pending_count drops."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()

    async def boom(filename: str, dest: Path) -> None:
        raise RuntimeError("simulated USB hang / 500 error")

    d.download_file = boom  # type: ignore[assignment]

    job = _make_job(paths)
    q = await _make_queue_with_job(paths, job)
    errs = ErrorBus()
    sub = errs.subscribe()
    worker = GoProDLWorker(q, {"S1": d}, paths, errs)

    # Drive a single job through _process_one directly.
    await worker._process_one(job)

    evt = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert "DL failed" in str(evt)
    assert q.pending_count == 0, "sidecar must be removed after permanent DL failure"


@pytest.mark.asyncio
async def test_dl_timeout_removes_sidecar(paths):
    """download_file hangs indefinitely → DLWorker enforces a timeout
    and cleans up so the queue is not blocked forever."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()

    async def hangs_forever(filename: str, dest: Path) -> None:
        await asyncio.sleep(3600)

    d.download_file = hangs_forever  # type: ignore[assignment]

    job = _make_job(paths)
    q = await _make_queue_with_job(paths, job)
    errs = ErrorBus()
    sub = errs.subscribe()
    worker = GoProDLWorker(q, {"S1": d}, paths, errs, download_timeout_sec=0.5)

    t0 = asyncio.get_event_loop().time()
    await worker._process_one(job)
    elapsed = asyncio.get_event_loop().time() - t0

    assert elapsed < 1.5, f"DL timeout must fire (got {elapsed:.2f}s)"
    evt = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert "DL failed" in str(evt) or "timeout" in str(evt).lower()
    assert q.pending_count == 0


@pytest.mark.asyncio
async def test_ffmpeg_failure_removes_sidecar(paths):
    """ffmpeg pass fails on a malformed mp4 → sidecar cleaned up."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()

    # Write a truncated/garbage 'mp4' so ffmpeg fails.
    async def fake_dl(filename: str, dest: Path) -> None:
        dest.write_bytes(b"not a real mp4")

    d.download_file = fake_dl  # type: ignore[assignment]

    job = _make_job(paths)
    q = await _make_queue_with_job(paths, job)
    errs = ErrorBus()
    sub = errs.subscribe()
    worker = GoProDLWorker(q, {"S1": d}, paths, errs)

    await worker._process_one(job)

    # An error should have been published (ffmpeg failure).
    evt: Any = None
    while not sub.empty():
        evt = sub.get_nowait()
    assert evt is not None
    assert "ffmpeg failed" in str(evt)
    assert q.pending_count == 0, "sidecar must be removed after ffmpeg failure"
