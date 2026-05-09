from __future__ import annotations
import json
import os
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.cloud.snapshot import make_push_snapshot, cleanup_snapshot
from mimicrec.cloud.hub_meta import compute_manifest_hash, write_hub_meta, HubMeta
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode, tombstone_episode
from mimicrec.recording.atomic_io import _atomic_write_text


def _seed(tmp_path: Path) -> Path:
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j0"], camera_names=["front"])
    for i in range(2):
        (ds / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.table({"frame_index": [0], "episode_index": [i],
                      "action": [[0.0]], "observation.state": [[0.0]],
                      "timestamp": [0.0], "index": [i], "task_index": [0]}),
            ds / "data" / "chunk-000" / f"episode_{i:06d}.parquet",
        )
        (ds / "videos" / "observation.images.front" / "chunk-000").mkdir(parents=True, exist_ok=True)
        (ds / "videos" / "observation.images.front" / "chunk-000" / f"episode_{i:06d}.mp4").write_bytes(b"\x00")
        append_episode(ds / "meta", {"episode_index": i, "task": "t",
                                     "num_frames": 1, "duration_sec": 0.1, "cameras": ["front"]})
    return ds


def test_snapshot_inode_frozen_after_atomic_replace(tmp_path: Path):
    ds = _seed(tmp_path)
    snap = make_push_snapshot(ds)
    try:
        snap_info = (snap / "meta" / "info.json").stat()
        _atomic_write_text(ds / "meta" / "info.json", json.dumps({"changed": True}))
        snap_info_after = (snap / "meta" / "info.json").stat()
        assert snap_info.st_ino == snap_info_after.st_ino
        snap_content = json.loads((snap / "meta" / "info.json").read_text())
        assert "changed" not in snap_content
    finally:
        cleanup_snapshot(snap)


def test_dirty_when_save_runs_during_push(tmp_path: Path):
    ds = _seed(tmp_path)
    start_hash = compute_manifest_hash(ds)
    snap = make_push_snapshot(ds)
    try:
        append_episode(ds / "meta", {"episode_index": 99, "task": "t",
                                     "num_frames": 1, "duration_sec": 0.1, "cameras": []})
        end_hash = compute_manifest_hash(ds)
        assert start_hash != end_hash
    finally:
        cleanup_snapshot(snap)


def test_snapshot_excludes_ignored_dirs(tmp_path: Path):
    ds = _seed(tmp_path)
    (ds / ".pending").mkdir(exist_ok=True)
    (ds / ".pending" / "junk").write_bytes(b"x")
    (ds / ".cache").mkdir(exist_ok=True)
    (ds / ".cache" / "blob").write_bytes(b"x")
    write_hub_meta(ds, HubMeta(repo_id="u/d"))
    snap = make_push_snapshot(ds)
    try:
        assert not (snap / ".pending").exists()
        assert not (snap / ".cache").exists()
    finally:
        cleanup_snapshot(snap)
