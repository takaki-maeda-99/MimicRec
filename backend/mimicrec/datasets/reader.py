from __future__ import annotations
from pathlib import Path
from typing import Iterator

from mimicrec.recording.metadata import read_episodes


def iter_episodes(ds_root: Path, include_deleted: bool = False) -> Iterator[dict]:
    yield from read_episodes(ds_root / "meta", include_deleted=include_deleted)


def require_live_episode(ds_root: Path, episode_idx: int) -> dict:
    """Return metadata for a non-deleted episode, or raise FileNotFoundError."""
    for ep in iter_episodes(ds_root, include_deleted=False):
        if int(ep.get("episode_index", -1)) == episode_idx:
            return ep
    raise FileNotFoundError(
        f"episode {episode_idx} not found in dataset '{ds_root.name}'"
    )


def load_replay_trajectory(ds_root: Path, episode_idx: int):
    """Read episode parquet and extract joint trajectory + native fps for replay.

    The native fps is derived from the parquet's timestamp column, not from
    info.json (which can be stale if the dataset was created at one fps but
    later sessions changed to another). Replay should iterate at the rate
    the data was actually captured, otherwise the playback tempo is off.
    """
    from mimicrec.session.replay import ReplayTrajectory
    from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk
    import pyarrow.parquet as pq
    import numpy as np
    require_live_episode(ds_root, episode_idx)
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(episode_idx)
    pq_path = paths.episode_parquet(chunk, episode_idx)
    if not pq_path.exists():
        raise FileNotFoundError(f"episode {episode_idx} parquet not found at {pq_path}")
    table = pq.read_table(pq_path)
    col = table.column("action.joint_pos")
    joint_pos = np.stack([np.array(row.as_py(), dtype=np.float32) for row in col])
    # Some hand-teach recordings made before the gripper field was split out
    # of RobotCommand wrote the gripper as the 7th column of action.joint_pos
    # rather than into action.gripper_pos. Detect that case and split.
    gripper_targets: np.ndarray | None = None
    if "action.gripper_pos" in table.column_names:
        col_g = table.column("action.gripper_pos")
        gripper_targets = np.array(
            [float(r.as_py()) for r in col_g], dtype=np.float32
        )
    elif joint_pos.shape[1] > 6:
        gripper_targets = joint_pos[:, 6].astype(np.float32)
        joint_pos = joint_pos[:, :6]
    # Derive fps from consecutive timestamps (in seconds, since episode start).
    fps: int | None = None
    if "timestamp" in table.column_names and table.num_rows >= 2:
        ts = np.array([float(r.as_py()) for r in table.column("timestamp")])
        dt = float(np.median(np.diff(ts)))
        if dt > 0:
            fps = int(round(1.0 / dt))
    return ReplayTrajectory(
        joint_targets=joint_pos, fps=fps, gripper_targets=gripper_targets,
    )


def read_dataset_info(ds_root: Path) -> dict:
    import json
    info_path = ds_root / "meta" / "info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"info.json not found at {info_path}")
    return json.loads(info_path.read_text())
