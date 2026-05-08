from __future__ import annotations
from pathlib import Path
import pyarrow.parquet as pq
import pytest

from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.dataset_layout import init_dataset


def _init_dataset(root: Path) -> Path:
    init_dataset(root, fps=30, joint_names=["j0"], camera_names=[])
    return root


def test_save_no_partial_data_parquet(tmp_path: Path, monkeypatch):
    ds = _init_dataset(tmp_path / "ds")
    ep = PendingEpisode.open(ds, episode_index=0)
    ep.append_row({"action": [0.1], "observation.state": [0.0], "timestamp": 0.0,
                   "frame_index": 0, "episode_index": 0, "index": 0, "task_index": 0})
    ep.finalize()

    # save 中で os.replace が失敗する状況を作る
    real_replace = __import__("os").replace
    def boom(src, target):
        if str(target).endswith(".parquet") and "data/chunk" in str(target):
            raise RuntimeError("disk full")
        return real_replace(src, target)
    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(RuntimeError):
        ep.save({"episode_index": 0, "task": "t", "num_frames": 1,
                 "duration_sec": 0.0, "cameras": [], "fps": 30})

    # data/chunk-000/episode_000000.parquet が **存在しない**（半端ファイルなし）
    dst = ds / "data" / "chunk-000" / "episode_000000.parquet"
    assert not dst.exists()
    # tmp ファイルも残っていない
    assert not any(p.name.endswith(".tmp")
                   for p in (ds / "data" / "chunk-000").iterdir() if (ds / "data" / "chunk-000").exists())
