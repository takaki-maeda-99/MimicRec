import asyncio
import json
import shutil
import time
from pathlib import Path

import pytest

from mimicrec.errors import HardwareError
from mimicrec.gopro.dl_queue import DLQueue, GoProDLJob
from mimicrec.gopro.dl_worker import GoProDLWorker
from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus


FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "gopro" / "sample_episode.mp4"


@pytest.fixture
def paths(tmp_path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    # Pre-seed info.json so update_info_json_codec works.
    (p.meta_dir / "info.json").write_text(json.dumps({
        "features": {
            "observation.images.g1": {"info": {"video.codec": "libx264"}},
        },
    }))
    return p


def _job(job_id="j", episode_index=0):
    return GoProDLJob(
        job_id=job_id, gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=episode_index, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=time.monotonic_ns(),
        episode_stop_mono_ns=time.monotonic_ns() + 5_000_000_000,
    )


@pytest.mark.asyncio
async def test_normal_dl_stages_for_commit(paths):
    """DLWorker stages the file but does NOT move to dataset path. The move
    happens later via registry.commit_episode (covered in test_registry.py)."""
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    job = _job(job_id="j1")
    job.sd_filename = files[0].filename
    await queue.enqueue(job)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.5)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    # Sidecar still exists (state="staged"), staged file in place.
    sidecar = paths.pending_dir / "gopro_dl" / "j1.json"
    assert sidecar.exists()
    s = await queue.read_sidecar("j1")
    assert s.state == "staged"
    assert Path(s.staged_path).exists()
    # Dataset path NOT yet populated.
    assert not paths.episode_video(0, "g1", 0).exists()


@pytest.mark.asyncio
async def test_dl_with_commit_pending_set_during_processing(paths):
    """If sidecar.state becomes commit_pending while DL is happening, DLWorker
    must commit-then-finish instead of staging."""
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    job = _job(job_id="j_cp")
    job.sd_filename = files[0].filename
    await queue.enqueue(job)

    # Pre-flip sidecar state to commit_pending BEFORE worker dequeues.
    pre = await queue.read_sidecar("j_cp")
    pre.state = "commit_pending"
    await queue.update_sidecar(pre)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.5)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    # Worker should have committed: dataset path exists, sidecar gone.
    assert paths.episode_video(0, "g1", 0).exists()
    assert not (paths.pending_dir / "gopro_dl" / "j_cp.json").exists()
    info = json.loads((paths.meta_dir / "info.json").read_text())
    assert info["features"]["observation.images.g1"]["info"]["video.codec"] in {"h264", "hevc"}


@pytest.mark.asyncio
async def test_dl_with_discard_pending_skips_dl(paths):
    """If state is discard_pending when dequeued, no download happens."""
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    download_called = False
    async def boom(*a, **kw):
        nonlocal download_called
        download_called = True
    d.download_file = boom  # type: ignore[assignment]

    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    job = _job(job_id="j_dp")
    job.state = "discard_pending"
    await queue.enqueue(job)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.3)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    assert not download_called
    assert not (paths.pending_dir / "gopro_dl" / "j_dp.json").exists()


@pytest.mark.asyncio
async def test_concurrent_commit_episode_and_dlworker_serialize_via_lock(paths):
    """Race regression #2: both registry.commit_episode and the DLWorker's
    post-ffmpeg block do read-decide-write on the same sidecar. Without
    a per-job lock around the transaction they can interleave at file-IO
    granularity (DLQueue.update_sidecar uses asyncio.to_thread, which
    yields the event loop). The result is one party's write overwriting
    the other's, leaving state="staged" with the mp4 orphaned in
    pending_staged and never committed.

    Test: set state=pending_dl, then concurrently fire (a) the DLWorker
    post-ffmpeg block via real worker.run() and (b) commit_episode-style
    transition that flips pending_dl → commit_pending. Order isn't
    important — under proper locking the FINAL outcome must always be
    "file lives in dataset, sidecar gone".
    """
    from mimicrec.gopro.registry import GoProDeviceRegistry

    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    job = _job(job_id="j_concurrent", episode_index=7)
    job.sd_filename = files[0].filename
    await queue.enqueue(job)

    # Build a real registry whose commit_episode owns the job's sidecar
    # and would race with the DLWorker for the state transition.
    registry = GoProDeviceRegistry.__new__(GoProDeviceRegistry)
    registry._queue = queue
    registry._paths = paths
    registry._errors = errors
    registry._recorders = {}

    # Fire both concurrently so the asyncio scheduler interleaves their
    # read/write awaits at file-IO granularity.
    worker_task = asyncio.create_task(worker.run())
    commit_task = asyncio.create_task(registry.commit_episode(7))
    await asyncio.sleep(0.5)
    await worker.stop()
    try: await asyncio.wait_for(worker_task, timeout=2.0)
    except asyncio.CancelledError: pass
    await asyncio.wait_for(commit_task, timeout=2.0)

    # Invariant: regardless of who won the race, ep 7's mp4 must end up
    # in the dataset, sidecar must be cleaned up, and pending_staged
    # must not contain an orphan.
    assert paths.episode_video(0, "g1", 7).exists(), (
        "concurrent commit/DL race left mp4 orphaned in pending_staged"
    )
    assert not (paths.pending_dir / "gopro_dl" / "j_concurrent.json").exists()
    assert not (paths.pending_dir / "gopro_staged" / "j_concurrent.mp4").exists()


@pytest.mark.asyncio
async def test_resume_from_tmp_skips_redownload(paths):
    """When tmp_raw already matches SD-side size (i.e. previous DL completed
    but ffmpeg/staging failed), DLWorker should skip download and re-run ffmpeg.

    Note: MockGoProDevice reports a fixed MediaItem.size (12345). For this test
    to be correct, we override the mock's media_list to report the actual
    fixture size, and pre-place tmp_raw as a copy of the fixture so the size
    check passes AND ffmpeg can read it as a valid MP4."""
    import shutil as _sh
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()

    # Override media_list so reported size matches the actual fixture.
    real_size = FIXTURE.stat().st_size
    from mimicrec.gopro.types import MediaItem
    async def real_size_list():
        return [MediaItem(filename=files[0].filename, size=real_size, mtime_ns=0)]
    d.media_list = real_size_list  # type: ignore[assignment]

    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    job = _job(job_id="j_resume")
    job.sd_filename = files[0].filename
    job.state = "commit_pending"   # so worker commits to dataset on completion

    tmp_raw = paths.pending_dir / f"gopro_dl_{job.job_id}_raw.mp4"
    tmp_raw.parent.mkdir(parents=True, exist_ok=True)
    _sh.copy(str(FIXTURE), str(tmp_raw))   # valid MP4, real size

    download_called = False
    async def boom(*a, **kw):
        nonlocal download_called
        download_called = True
    d.download_file = boom  # type: ignore[assignment]

    await queue.enqueue(job)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.5)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    assert not download_called
    assert paths.episode_video(0, "g1", 0).exists()
