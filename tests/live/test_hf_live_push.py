from __future__ import annotations
import os
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.cloud.hf_pusher import push_dataset
from mimicrec.cloud.snapshot import make_push_snapshot, cleanup_snapshot
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode


pytestmark = pytest.mark.skipif(
    not os.environ.get("HF_TOKEN"),
    reason="HF_TOKEN not set; skipping live HF push test",
)


def _seed(tmp_path: Path) -> Path:
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j0"], camera_names=[])
    (ds / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({"frame_index": [0], "episode_index": [0],
                  "action": [[0.0]], "observation.state": [[0.0]],
                  "timestamp": [0.0], "index": [0], "task_index": [0]}),
        ds / "data" / "chunk-000" / "episode_000000.parquet",
    )
    append_episode(ds / "meta", {"episode_index": 0, "task": "t",
                                 "num_frames": 1, "duration_sec": 0.1, "cameras": []})
    return ds


def test_live_round_trip(tmp_path: Path):
    """Push to a temporary repo and verify it shows up on HF Hub. Cleans up the repo at the end."""
    from huggingface_hub import HfApi
    api = HfApi(token=os.environ["HF_TOKEN"])
    who = api.whoami()
    user = who["name"] if isinstance(who, dict) else who.name
    repo_id = f"{user}/mimicrec_test_{int(time.time())}"

    ds = _seed(tmp_path)
    snap = make_push_snapshot(ds)
    try:
        result = push_dataset(snap, repo_id, private=True)
        assert result.commit_sha
        info = api.repo_info(repo_id, repo_type="dataset")
        assert info is not None

        try:
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
            ds_loaded = LeRobotDataset(repo_id=repo_id)
            assert ds_loaded is not None
        except ImportError:
            pytest.skip("lerobot not installed; skipping LeRobotDataset round-trip check")
    finally:
        cleanup_snapshot(snap)
        try:
            api.delete_repo(repo_id, repo_type="dataset")
        except Exception:
            pass
