import asyncio
import json
from pathlib import Path

import pytest

from mimicrec.gopro.dl_queue import DLQueue, GoProDLJob


def _job(job_id="j", episode_index=0) -> GoProDLJob:
    return GoProDLJob(
        job_id=job_id, gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=episode_index, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=1_000_000_000, episode_stop_mono_ns=2_000_000_000,
    )


@pytest.mark.asyncio
async def test_enqueue_writes_sidecar_via_executor(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="abc"))
    sidecar = tmp_path / "pending" / "gopro_dl" / "abc.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["job_id"] == "abc"


@pytest.mark.asyncio
async def test_dequeue_returns_enqueued(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="a", episode_index=0))
    await q.enqueue(_job(job_id="b", episode_index=1))
    j1 = await asyncio.wait_for(q.dequeue(), timeout=1.0)
    j2 = await asyncio.wait_for(q.dequeue(), timeout=1.0)
    assert {j1.job_id, j2.job_id} == {"a", "b"}


@pytest.mark.asyncio
async def test_mark_done_removes_sidecar(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="x"))
    await q.mark_done("x")
    assert not (tmp_path / "pending" / "gopro_dl" / "x.json").exists()


@pytest.mark.asyncio
async def test_mark_done_idempotent(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.mark_done("never_existed")  # no error


@pytest.mark.asyncio
async def test_restore_loads_sidecars(tmp_path):
    pdir = tmp_path / "pending" / "gopro_dl"
    pdir.mkdir(parents=True)
    j1 = _job(job_id="aaa", episode_index=2)
    j2 = _job(job_id="bbb", episode_index=3)
    (pdir / "aaa.json").write_text(json.dumps(j1.to_json()))
    (pdir / "bbb.json").write_text(json.dumps(j2.to_json()))
    q = DLQueue.restore(pdir)
    out = [await asyncio.wait_for(q.dequeue(), timeout=1.0) for _ in range(2)]
    assert sorted(j.job_id for j in out) == ["aaa", "bbb"]


@pytest.mark.asyncio
async def test_restore_creates_missing_dir(tmp_path):
    pdir = tmp_path / "never"
    q = DLQueue.restore(pdir)
    assert pdir.exists()
    assert q.pending_count == 0


def test_to_json_roundtrip():
    j = _job()
    assert GoProDLJob.from_json(j.to_json()) == j


def test_default_state_is_pending_dl():
    j = _job()
    assert j.state == "pending_dl"
    assert j.staged_path is None


def test_from_json_backward_compat_without_state():
    """Old sidecars (pre-state field) default to pending_dl."""
    j = _job()
    raw = j.to_json()
    raw.pop("state")
    raw.pop("staged_path")
    j2 = GoProDLJob.from_json(raw)
    assert j2.state == "pending_dl"
    assert j2.staged_path is None


@pytest.mark.asyncio
async def test_update_sidecar_changes_state(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    j = _job(job_id="u")
    await q.enqueue(j)
    j.state = "staged"
    j.staged_path = "/tmp/abc.mp4"
    await q.update_sidecar(j)
    j2 = await q.read_sidecar("u")
    assert j2.state == "staged"
    assert j2.staged_path == "/tmp/abc.mp4"


@pytest.mark.asyncio
async def test_find_jobs_for_episode(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="a", episode_index=0))
    await q.enqueue(_job(job_id="b", episode_index=1))
    await q.enqueue(_job(job_id="c", episode_index=0))
    found = await q.find_jobs_for_episode(0)
    assert sorted(j.job_id for j in found) == ["a", "c"]


@pytest.mark.asyncio
async def test_restore_skips_staged_jobs(tmp_path):
    pdir = tmp_path / "pending" / "gopro_dl"
    pdir.mkdir(parents=True)
    pending = _job(job_id="p", episode_index=0)
    staged = _job(job_id="s", episode_index=1)
    staged.state = "staged"
    staged.staged_path = "/tmp/staged.mp4"
    (pdir / "p.json").write_text(json.dumps(pending.to_json()))
    (pdir / "s.json").write_text(json.dumps(staged.to_json()))
    q = DLQueue.restore(pdir)
    # Only "p" is in the in-memory queue.
    j = await asyncio.wait_for(q.dequeue(), timeout=1.0)
    assert j.job_id == "p"
    assert q._q.qsize() == 0
    # But pending_count counts both sidecars.
    assert q.pending_count == 2
