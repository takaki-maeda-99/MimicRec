from __future__ import annotations
from pathlib import Path
from typing import Iterator

from mimicrec.recording.metadata import read_episodes


def iter_episodes(ds_root: Path, include_deleted: bool = False) -> Iterator[dict]:
    yield from read_episodes(ds_root / "meta", include_deleted=include_deleted)


def load_replay_trajectory(ds_root: Path, episode_idx: int):
    """Read episode parquet and extract joint trajectory for replay."""
    from mimicrec.session.replay import ReplayTrajectory
    from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk
    import pyarrow.parquet as pq
    import numpy as np
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(episode_idx)
    pq_path = paths.episode_parquet(chunk, episode_idx)
    if not pq_path.exists():
        raise FileNotFoundError(f"episode {episode_idx} parquet not found at {pq_path}")
    table = pq.read_table(pq_path)
    col = table.column("action.joint_pos")
    joint_pos = np.stack([np.array(row.as_py(), dtype=np.float32) for row in col])
    return ReplayTrajectory(joint_targets=joint_pos)


def read_dataset_info(ds_root: Path) -> dict:
    import json
    info_path = ds_root / "meta" / "info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"info.json not found at {info_path}")
    return json.loads(info_path.read_text())
