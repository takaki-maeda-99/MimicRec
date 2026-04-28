from pathlib import Path
from mimicrec.datasets.reader import iter_episodes
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode, tombstone_episode


def test_iter_episodes_skips_deleted_by_default(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["a"], camera_names=[])
    append_episode(ds / "meta", {"episode_index": 0, "task": "x", "num_frames": 1})
    append_episode(ds / "meta", {"episode_index": 1, "task": "x", "num_frames": 1})
    tombstone_episode(ds / "meta", 0, deleted_at_unix=1)
    live = list(iter_episodes(ds))
    assert [e["episode_index"] for e in live] == [1]


def test_iter_episodes_admin_view_includes_deleted(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["a"], camera_names=[])
    append_episode(ds / "meta", {"episode_index": 0, "task": "x", "num_frames": 1})
    tombstone_episode(ds / "meta", 0, deleted_at_unix=1)
    all_rows = list(iter_episodes(ds, include_deleted=True))
    assert len(all_rows) == 1 and all_rows[0]["deleted"] is True


def test_tombstone_persists_when_target_is_not_first_row(tmp_path: Path):
    """Regression: pa.Table.from_pylist infers schema from row 0 only.
    If row 0 has no `deleted` key but a later row does, the field was silently dropped."""
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["a"], camera_names=[])
    for i in range(3):
        append_episode(ds / "meta", {"episode_index": i, "task": "x", "num_frames": 1})
    tombstone_episode(ds / "meta", 2, deleted_at_unix=1700000000)
    live = [e["episode_index"] for e in iter_episodes(ds)]
    assert live == [0, 1], f"episode 2 should be tombstoned but got live={live}"
