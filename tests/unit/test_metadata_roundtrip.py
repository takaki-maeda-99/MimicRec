import json
from pathlib import Path

import pytest

from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import (
    append_episode, read_episodes, upsert_task, tombstone_episode,
)


def test_append_and_read_episodes(tmp_path: Path):
    meta = tmp_path / "meta"
    meta.mkdir()
    append_episode(meta, {"episode_index": 0, "task": "pick", "num_frames": 10})
    append_episode(meta, {"episode_index": 1, "task": "pick", "num_frames": 12})
    eps = list(read_episodes(meta, include_deleted=False))
    assert [e["episode_index"] for e in eps] == [0, 1]


def test_episodes_parquet_has_per_video_metadata_columns(tmp_path: Path):
    """LeRobot v3 spec: meta/episodes parquet must carry per-video columns
    videos/{key}/{chunk_index,file_index,from_timestamp,to_timestamp} so
    LeRobotDataset.get_video_file_path / _query_videos can locate mp4 files."""
    import pyarrow.parquet as pq

    meta = tmp_path / "meta"
    meta.mkdir()
    append_episode(meta, {
        "episode_index": 0, "task": "pick", "num_frames": 5,
        "cameras": ["front", "wrist"], "duration_sec": 5 / 30,
    })

    table = pq.read_table(meta / "episodes" / "chunk-000" / "file-000.parquet")
    cols = set(table.column_names)
    for cam in ("front", "wrist"):
        for suffix in ("chunk_index", "file_index", "from_timestamp", "to_timestamp"):
            col = f"videos/observation.images.{cam}/{suffix}"
            assert col in cols, col

    row = table.to_pylist()[0]
    assert row["videos/observation.images.front/chunk_index"] == 0
    assert row["videos/observation.images.front/file_index"] == 0
    assert row["videos/observation.images.front/from_timestamp"] == 0.0
    assert row["videos/observation.images.front/to_timestamp"] == pytest.approx(5 / 30)


def test_update_info_totals_reflects_task_count(tmp_path: Path):
    """info.json total_tasks must reflect actual rows in tasks.parquet so the
    declared metadata matches reality (consumers / dataset cards rely on it)."""
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1"], camera_names=[])
    meta = ds / "meta"
    upsert_task(meta, "pick", "pick the block")
    upsert_task(meta, "place", "place the block")
    append_episode(meta, {"episode_index": 0, "task": "pick", "num_frames": 10})

    info = json.loads((meta / "info.json").read_text())
    assert info["total_tasks"] == 2


def test_tombstone_filters_deleted(tmp_path: Path):
    meta = tmp_path / "meta"
    meta.mkdir()
    append_episode(meta, {"episode_index": 0, "task": "pick", "num_frames": 10})
    append_episode(meta, {"episode_index": 1, "task": "pick", "num_frames": 12})
    tombstone_episode(meta, 0, deleted_at_unix=1700000000)
    assert [e["episode_index"] for e in read_episodes(meta)] == [1]
    assert [e["episode_index"] for e in read_episodes(meta, include_deleted=True)] == [0, 1]
