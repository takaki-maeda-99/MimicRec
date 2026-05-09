from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.cloud.hf_pusher import push_dataset
from mimicrec.cloud.snapshot import make_push_snapshot, cleanup_snapshot, collect_tombstoned_files
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode, tombstone_episode


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


def test_push_after_tombstone_calls_delete_files(tmp_path):
    ds = _seed(tmp_path)
    tombstone_episode(ds / "meta", episode_index=0, deleted_at_unix=1234567890)
    tombstoned = collect_tombstoned_files(ds)
    assert "data/chunk-000/episode_000000.parquet" in tombstoned
    snap = make_push_snapshot(ds)
    try:
        api = MagicMock()
        api.list_repo_commits.side_effect = [
            [MagicMock(commit_id="up_sha")],
            [MagicMock(commit_id="del_sha")],
        ]
        with patch("mimicrec.cloud.hf_pusher.HfApi", return_value=api):
            result = push_dataset(snap, "u/d", private=True, tombstoned_files=tombstoned)
        api.delete_files.assert_called_once()
        kw = api.delete_files.call_args.kwargs
        assert kw["parent_commit"] == "up_sha"
        assert "data/chunk-000/episode_000000.parquet" in kw["delete_patterns"]
        assert result.commit_sha == "del_sha"
    finally:
        cleanup_snapshot(snap)
