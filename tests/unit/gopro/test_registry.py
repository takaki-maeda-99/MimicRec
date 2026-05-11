import asyncio
from pathlib import Path

import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.registry import GoProDeviceRegistry
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus


@pytest.fixture
def paths(tmp_path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    return p


def test_duplicate_slot_raises(paths):
    a = MockGoProDevice(name="ga", usb_serial="S1")
    b = MockGoProDevice(name="gb", usb_serial="S2")
    with pytest.raises(ValueError, match="duplicate slot"):
        GoProDeviceRegistry(
            devices=[("g1", a), ("g1", b)],
            paths=paths,
            errors=ErrorBus(),
        )


def test_duplicate_serial_raises(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    b = MockGoProDevice(name="g2", usb_serial="S1")
    with pytest.raises(ValueError, match="duplicate usb_serial"):
        GoProDeviceRegistry(devices=[(a.name, a), (b.name, b)], paths=paths, errors=ErrorBus())


@pytest.mark.asyncio
async def test_start_connects_and_provides_preview_sources(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[(a.name, a)], paths=paths, errors=ErrorBus())
    await reg.start()
    sources = reg.preview_sources()
    assert "g1" in sources
    specs = reg.gopro_specs()
    assert "g1" in specs
    await reg.stop()


@pytest.mark.asyncio
async def test_one_failing_connect_does_not_block_others(paths):
    a = MockGoProDevice(name="g_ok", usb_serial="S1")
    b = MockGoProDevice(name="g_bad", usb_serial="S2")
    async def boom():
        raise RuntimeError("connect blew up")
    b.connect = boom  # type: ignore[assignment]

    errs = ErrorBus()
    sub = errs.subscribe()
    reg = GoProDeviceRegistry(devices=[(a.name, a), (b.name, b)], paths=paths, errors=errs)
    await reg.start()
    # b was disabled and an error was published.
    assert b.is_disabled
    assert not a.is_disabled
    found = False
    while not sub.empty():
        e = sub.get_nowait()
        if "g_bad" in str(e):
            found = True
    assert found
    await reg.stop()


@pytest.mark.asyncio
async def test_episode_lifecycle_propagates_errors(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    errs = ErrorBus()
    sub = errs.subscribe()
    reg = GoProDeviceRegistry(devices=[(a.name, a)], paths=paths, errors=errs)
    await reg.start()
    # Sabotage a's recorder by pinning an exception inside start_episode.
    real_recorder = reg._recorders["g1"]  # type: ignore[attr-defined]
    async def boom(*a, **kw):
        raise RuntimeError("recorder crash")
    real_recorder.start_episode = boom  # type: ignore[assignment]

    await reg.episode_start(0, t_host_mono_ns=0)
    found = False
    while not sub.empty():
        e = sub.get_nowait()
        if "recorder crash" in str(e):
            found = True
    assert found
    await reg.stop()


@pytest.mark.asyncio
async def test_commit_episode_moves_staged_to_dataset(paths, tmp_path):
    """When a job is in state=staged, commit_episode moves the file to
    paths.episode_video(...) and removes the sidecar."""
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[(a.name, a)], paths=paths, errors=ErrorBus())
    await reg.start()

    # Manually craft a staged job sidecar + staged file.
    from mimicrec.gopro.dl_queue import GoProDLJob
    staged_dir = paths.pending_dir / "gopro_staged"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_file = staged_dir / "abc.mp4"
    staged_file.write_bytes(b"\x00" * 64)
    job = GoProDLJob(
        job_id="abc", gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=0, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=0, episode_stop_mono_ns=0,
        state="staged", staged_path=str(staged_file),
    )
    # Pre-seed info.json so codec patch path doesn't blow up.
    import json as _json
    (paths.meta_dir / "info.json").write_text(_json.dumps({
        "features": {"observation.images.g1": {"info": {"video.codec": "libx264"}}},
    }))
    await reg._queue.enqueue(job)  # type: ignore[union-attr]
    await reg._queue.update_sidecar(job)  # ensure state="staged" in sidecar

    await reg.commit_episode(0)

    assert paths.episode_video(0, "g1", 0).exists()
    assert not (paths.pending_dir / "gopro_dl" / "abc.json").exists()
    assert not staged_file.exists()
    await reg.stop()


@pytest.mark.asyncio
async def test_discard_episode_removes_staged(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[(a.name, a)], paths=paths, errors=ErrorBus())
    await reg.start()

    from mimicrec.gopro.dl_queue import GoProDLJob
    staged_dir = paths.pending_dir / "gopro_staged"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_file = staged_dir / "xyz.mp4"
    staged_file.write_bytes(b"\x00" * 64)
    job = GoProDLJob(
        job_id="xyz", gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=1, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=0, episode_stop_mono_ns=0,
        state="staged", staged_path=str(staged_file),
    )
    await reg._queue.enqueue(job)  # type: ignore[union-attr]
    await reg._queue.update_sidecar(job)

    await reg.discard_episode(1)

    assert not staged_file.exists()
    assert not (paths.pending_dir / "gopro_dl" / "xyz.json").exists()
    assert not paths.episode_video(0, "g1", 1).exists()
    await reg.stop()


@pytest.mark.asyncio
async def test_commit_episode_on_pending_dl_flips_state(paths):
    """If the job is still pending_dl when commit fires, sidecar state flips
    to commit_pending (DLWorker will commit after ffmpeg)."""
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[(a.name, a)], paths=paths, errors=ErrorBus())
    await reg.start()

    from mimicrec.gopro.dl_queue import GoProDLJob
    job = GoProDLJob(
        job_id="ppp", gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=2, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=0, episode_stop_mono_ns=0,
        state="pending_dl",
    )
    await reg._queue.enqueue(job)  # type: ignore[union-attr]
    await reg.commit_episode(2)

    s = await reg._queue.read_sidecar("ppp")  # type: ignore[union-attr]
    assert s.state == "commit_pending"
    await reg.stop()
