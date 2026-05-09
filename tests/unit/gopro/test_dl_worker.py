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
async def test_commit_pending_set_during_staging_window_is_not_overwritten(paths):
    """Race regression: if registry.commit_episode flips state pending_dl →
    commit_pending AFTER the DLWorker's pre-stage read but BEFORE its
    update_sidecar(staged) write, the worker must NOT clobber the
    commit_pending state with staged.

    Symptom (the bug this fix targets): the staged mp4 sits in
    .pending/gopro_staged/ forever and the dataset's
    videos/.../episode_NNNNNN.mp4 never appears. /api/session/gopro_pending
    keeps reporting nonzero.

    Simulation: patch read_sidecar so the FIRST call (line 143 of
    _process_one) returns the on-disk pending_dl value but ALSO writes
    commit_pending to disk as a side effect. This models the asyncio
    interleaving where commit_episode lands its update during the
    yield in read_sidecar.
    """
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    job = _job(job_id="j_race")
    job.sd_filename = files[0].filename
    await queue.enqueue(job)

    # Race injector: replace read_sidecar so that on its FIRST invocation,
    # after returning the cached pending_dl object, it commits a
    # commit_pending state to disk before the worker can write staged.
    real_read = queue.read_sidecar
    real_update = queue.update_sidecar
    race_fired = {"v": False}

    async def racing_read(job_id):
        result = await real_read(job_id)
        if not race_fired["v"] and result is not None and result.state == "pending_dl":
            race_fired["v"] = True
            flipped = GoProDLJob(**{**result.to_json(), "state": "commit_pending"})
            await real_update(flipped)
        return result

    queue.read_sidecar = racing_read  # type: ignore[assignment]

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.5)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    # Invariant: the race-flipped commit_pending must result in a
    # committed dataset video, NOT an orphaned staged file.
    assert paths.episode_video(0, "g1", 0).exists(), (
        "DLWorker overwrote commit_pending with staged — staged mp4 is "
        "now stuck in pending dir and dataset video is missing"
    )
    assert not (paths.pending_dir / "gopro_dl" / "j_race.json").exists(), (
        "Sidecar should be marked done after commit"
    )
    # Staged file should be gone (moved into dataset).
    assert not (paths.pending_dir / "gopro_staged" / "j_race.mp4").exists()


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
