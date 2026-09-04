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


def load_motion_replay_trajectory(ds_root: Path, episode_idx: int):
    """Load authoritative namespaced SE3Delta streams for remapped replay."""
    import numpy as np
    import pyarrow.parquet as pq

    from mimicrec.motion.se3 import SE3Delta
    from mimicrec.motion.types import MotionStep
    from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk
    from mimicrec.session.motion_replay import MotionReplayTrajectory

    require_live_episode(ds_root, episode_idx)
    info = read_dataset_info(ds_root)
    schema = info.get("motion_schema")
    if not isinstance(schema, dict):
        raise ValueError("dataset has no motion_schema")
    groups = schema.get("motion_groups") or {}
    path = dataset_paths(ds_root).episode_parquet(
        resolve_chunk(episode_idx), episode_idx
    )
    table = pq.read_table(path)
    frames: list[dict[str, MotionStep]] = []
    for row_index in range(table.num_rows):
        frame: dict[str, MotionStep] = {}
        for group_name, group_spec in groups.items():
            prefix = f"action.motion.{group_name}"
            delta_key = f"{prefix}.se3_delta"
            if delta_key not in table.column_names:
                raise ValueError(f"motion replay column is missing: {delta_key}")
            tangent_value = table[delta_key][row_index].as_py()
            if tangent_value is None:
                continue
            duration_key = f"{prefix}.duration_sec"
            mask_key = f"{prefix}.active_mask"
            frame_key = f"{prefix}.frame"
            stamp_key = f"{prefix}.t_mono_ns"
            duration = (
                float(table[duration_key][row_index].as_py())
                if duration_key in table.column_names
                else 1.0 / float(info["fps"])
            )
            mask = (
                np.asarray(table[mask_key][row_index].as_py(), dtype=bool)
                if mask_key in table.column_names
                else np.ones(6, dtype=bool)
            )
            frame_name = (
                str(table[frame_key][row_index].as_py())
                if frame_key in table.column_names
                else str(schema.get("default_frame", "ee_local"))
            )
            stamp = (
                int(table[stamp_key][row_index].as_py())
                if stamp_key in table.column_names
                else 0
            )
            auxiliary = {}
            for key in group_spec.get("auxiliary", []):
                column = f"{prefix}.aux.{key}"
                if column in table.column_names:
                    value = table[column][row_index].as_py()
                    if value is not None:
                        auxiliary[str(key)] = float(value)
            frame[str(group_name)] = MotionStep(
                delta=SE3Delta(
                    np.asarray(tangent_value, dtype=np.float64),
                    frame=frame_name,
                    duration_sec=duration,
                    active_mask=mask,
                ),
                auxiliary=auxiliary,
                t_mono_ns=stamp,
            )
        frames.append(frame)
    return MotionReplayTrajectory(frames=frames, fps=int(info["fps"]))
