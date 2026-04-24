import pytest
from pathlib import Path
import json
import numpy as np
import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.metadata import read_episodes


def _make_row(i: int, episode_index: int = 0, global_index: int = 0) -> dict:
    return {
        "timestamp": float(i) * 0.033,
        "tick_t_mono_ns": 1_000_000_000 + int(i * 33_000_000),
        "observation.state.joint_pos": np.array([0.0, 0.0], dtype=np.float32),
        "observation.state.joint_vel": np.array([0.0, 0.0], dtype=np.float32),
        "observation.state.joint_effort": np.array([0.0, 0.0], dtype=np.float32),
        "observation.state.t_mono_ns": 1_000_000_000 + int(i * 33_000_000),
        "action.joint_pos": np.array([0.0, 0.0], dtype=np.float32),
        "action.t_mono_ns": 1_000_000_000 + int(i * 33_000_000),
        "frame_index": i,
        "episode_index": episode_index,
        "index": global_index + i,
        "task_index": 0,
    }


def test_save_places_files_in_dataset(tmp_path: Path):
    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    pe = PendingEpisode.open(ds, episode_index=0)
    for i in range(5):
        pe.append_row(_make_row(i))
    pe.finalize()
    pe.save(
        metadata_extra={
            "episode_index": 0,
            "task": "pick",
            "instruction": "pick the block",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "mode": "teleop", "fps": 30,
            "success": None, "comment": None,
            "start_t_mono_ns": 1_000_000_000, "end_t_mono_ns": 1_132_000_000,
            "duration_sec": 0.132, "num_frames": 5,
            "session_boot_t_unix": 1700000000, "session_boot_t_mono_ns": 1_000_000_000,
            "resolved_config": {},
        }
    )

    paths = dataset_paths(ds)
    assert (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()
    assert not (ds / ".pending").exists() or not any((ds / ".pending").iterdir())
    rows = list(read_episodes(paths.meta_dir))
    assert rows[0]["episode_index"] == 0
    table = pq.read_table(paths.data_dir / "chunk-000" / "episode_000000.parquet")
    assert table.num_rows == 5


def test_discard_removes_pending_and_does_not_touch_dataset(tmp_path: Path):
    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    pe = PendingEpisode.open(ds, episode_index=0)
    pe.append_row(_make_row(0))
    pe.finalize()
    pe.discard()

    paths = dataset_paths(ds)
    assert not (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()
    assert list(read_episodes(paths.meta_dir)) == []


def test_saved_dataset_is_readable_by_lerobot(tmp_path: Path):
    """Spike decision: our raw parquet + metadata output is LeRobot-compatible."""
    pytest.importorskip("lerobot")

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    ds_root = tmp_path / "datasets" / "mock"
    init_dataset(ds_root, fps=30, joint_names=["j1", "j2"], camera_names=[])
    pe = PendingEpisode.open(ds_root, episode_index=0)
    for i in range(5):
        pe.append_row(_make_row(i))
    pe.finalize()
    pe.save(metadata_extra={
        "episode_index": 0, "task": "pick", "instruction": "pick", "robot": "mock",
        "teleop": "mock_leader", "mapper": "identity", "cameras": [], "mode": "teleop",
        "fps": 30, "success": None, "comment": None,
        "start_t_mono_ns": 0, "end_t_mono_ns": 0, "duration_sec": 0.0, "num_frames": 5,
        "session_boot_t_unix": 0, "session_boot_t_mono_ns": 0, "resolved_config": {},
    })

    ds = LeRobotDataset.resume(repo_id="local/mock", root=str(ds_root))
    assert ds.num_episodes >= 1
