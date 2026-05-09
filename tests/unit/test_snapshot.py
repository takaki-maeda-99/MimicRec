from __future__ import annotations
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.cloud.snapshot import (
    detect_symlinks, make_push_snapshot, cleanup_snapshot,
    collect_tombstoned_files, SnapshotError,
)
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode, tombstone_episode


def _seed_dataset(tmp_path: Path, n_eps: int = 2) -> Path:
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j0"], camera_names=["front"])
    for i in range(n_eps):
        # data parquet
        (ds / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.table({"frame_index": [0], "episode_index": [i],
                      "action": [[0.0]], "observation.state": [[0.0]],
                      "timestamp": [0.0], "index": [i], "task_index": [0]}),
            ds / "data" / "chunk-000" / f"episode_{i:06d}.parquet",
        )
        # mp4 stub
        (ds / "videos" / "observation.images.front" / "chunk-000").mkdir(parents=True, exist_ok=True)
        (ds / "videos" / "observation.images.front" / "chunk-000" / f"episode_{i:06d}.mp4").write_bytes(b"\x00\x00")
        append_episode(
            ds / "meta",
            {"episode_index": i, "task": "t", "num_frames": 1,
             "duration_sec": 0.1, "cameras": ["front"]},
        )
    return ds


def test_make_snapshot_creates_hardlinks(tmp_path: Path):
    ds = _seed_dataset(tmp_path)
    snap = make_push_snapshot(ds)
    try:
        info_orig = (ds / "meta" / "info.json").stat()
        info_snap = (snap / "meta" / "info.json").stat()
        assert info_orig.st_ino == info_snap.st_ino
        assert info_orig.st_nlink >= 2
        ep_orig = (ds / "data" / "chunk-000" / "episode_000000.parquet").stat()
        ep_snap = (snap / "data" / "chunk-000" / "episode_000000.parquet").stat()
        assert ep_orig.st_ino == ep_snap.st_ino
    finally:
        cleanup_snapshot(snap)


def test_snapshot_excludes_pending(tmp_path: Path):
    ds = _seed_dataset(tmp_path)
    pending_file = ds / ".pending" / "tmp.parquet"
    pending_file.parent.mkdir(parents=True, exist_ok=True)
    pending_file.write_bytes(b"x")
    snap = make_push_snapshot(ds)
    try:
        assert not (snap / ".pending").exists()
    finally:
        cleanup_snapshot(snap)


def test_snapshot_fails_on_symlink(tmp_path: Path):
    ds = _seed_dataset(tmp_path)
    target = tmp_path / "external.txt"
    target.write_text("x")
    (ds / "meta" / "evil.txt").symlink_to(target)
    with pytest.raises(SnapshotError):
        make_push_snapshot(ds)


def test_snapshot_strips_tombstoned_episode(tmp_path: Path):
    ds = _seed_dataset(tmp_path, n_eps=2)
    tombstone_episode(ds / "meta", episode_index=0, deleted_at_unix=1234567890)
    snap = make_push_snapshot(ds)
    try:
        assert not (snap / "data" / "chunk-000" / "episode_000000.parquet").exists()
        assert not (snap / "videos" / "observation.images.front" / "chunk-000" / "episode_000000.mp4").exists()
        assert (snap / "data" / "chunk-000" / "episode_000001.parquet").exists()
        rows = pq.read_table(snap / "meta" / "episodes" / "chunk-000" / "file-000.parquet").to_pylist()
        assert all(not r.get("deleted") for r in rows)
        assert len(rows) == 1
        info = json.loads((snap / "meta" / "info.json").read_text())
        assert info["total_episodes"] == 1
    finally:
        cleanup_snapshot(snap)


def test_cleanup_snapshot_only_removes_marked_dirs(tmp_path: Path):
    other = tmp_path / "not-a-snapshot"
    other.mkdir()
    cleanup_snapshot(other)
    assert other.exists()


def test_collect_tombstoned_files_returns_hub_paths(tmp_path: Path):
    ds = _seed_dataset(tmp_path, n_eps=2)
    tombstone_episode(ds / "meta", episode_index=0, deleted_at_unix=1234567890)
    files = collect_tombstoned_files(ds)
    assert "data/chunk-000/episode_000000.parquet" in files
    assert "videos/observation.images.front/chunk-000/episode_000000.mp4" in files


def test_detect_symlinks_skips_ignored_dirs(tmp_path: Path):
    ds = _seed_dataset(tmp_path)
    pending = ds / ".pending"
    pending.mkdir(exist_ok=True)
    target = tmp_path / "external.txt"
    target.write_text("x")
    (pending / "link").symlink_to(target)
    syms = detect_symlinks(ds)
    assert syms == []


def test_make_snapshot_cleans_up_on_strip_failure(tmp_path: Path, monkeypatch):
    """If _strip_tombstoned fails, the partial snapshot dir is removed."""
    ds = _seed_dataset(tmp_path)

    from mimicrec.cloud import snapshot as snap_mod
    def boom(snapshot):
        raise RuntimeError("simulated mid-snapshot crash")
    monkeypatch.setattr(snap_mod, "_strip_tombstoned", boom)

    with pytest.raises(RuntimeError):
        make_push_snapshot(ds)

    # No partial snapshot dirs left
    snaps = [p for p in ds.parent.iterdir() if p.name.startswith(".push-snapshot-")]
    assert snaps == [], f"unexpected leftover snapshots: {snaps}"
