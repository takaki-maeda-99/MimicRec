from pathlib import Path
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


def test_tombstone_filters_deleted(tmp_path: Path):
    meta = tmp_path / "meta"
    meta.mkdir()
    append_episode(meta, {"episode_index": 0, "task": "pick", "num_frames": 10})
    append_episode(meta, {"episode_index": 1, "task": "pick", "num_frames": 12})
    tombstone_episode(meta, 0, deleted_at_unix=1700000000)
    assert [e["episode_index"] for e in read_episodes(meta)] == [1]
    assert [e["episode_index"] for e in read_episodes(meta, include_deleted=True)] == [0, 1]
