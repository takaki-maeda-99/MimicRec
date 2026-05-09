from __future__ import annotations
import json
from contextlib import contextmanager
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from mimicrec.recording.atomic_io import _atomic_write_parquet, _atomic_write_text

if TYPE_CHECKING:
    from mimicrec.cloud.push_state import PushCoordinator


@contextmanager
def _maybe_lock(coordinator, ds_name):
    if coordinator is not None and ds_name is not None:
        lock = coordinator.get_save_lock(ds_name)
        with lock:
            yield
    else:
        yield


def _episodes_dir(meta_dir: Path) -> Path:
    return meta_dir / "episodes"


def _episodes_parquet(meta_dir: Path) -> Path:
    d = _episodes_dir(meta_dir) / "chunk-000"
    d.mkdir(parents=True, exist_ok=True)
    return d / "file-000.parquet"


def _tasks_parquet(meta_dir: Path) -> Path:
    return meta_dir / "tasks.parquet"


def _sanitize_for_parquet(record: dict) -> dict:
    """Ensure all values are parquet-safe: dicts/complex objects become JSON strings."""
    out = {}
    for k, v in record.items():
        if isinstance(v, dict):
            out[k] = json.dumps(v)
        else:
            out[k] = v
    return out


def _deserialize_json_fields(record: dict) -> dict:
    """Best-effort restore of JSON-encoded fields on read."""
    out = {}
    for k, v in record.items():
        if isinstance(v, str) and v.startswith("{"):
            try:
                out[k] = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                out[k] = v
        else:
            out[k] = v
    return out


def append_episode(
    meta_dir: Path,
    row: dict,
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    """Append an episode row to episodes parquet."""
    with _maybe_lock(coordinator, ds_name):
        pq_path = _episodes_parquet(meta_dir)

        # Build the episode record for v3 format
        ep_record = {
            "episode_index": row["episode_index"],
            "tasks": [row.get("task", "default")],
            "length": row.get("num_frames", 0),
            "data/chunk_index": 0,
            "data/file_index": row["episode_index"],
            "dataset_from_index": 0,  # will be recomputed
            "dataset_to_index": row.get("num_frames", 0),
        }
        # Per-video metadata columns required by LeRobot v3
        # (LeRobotDataset.get_video_file_path / _query_videos read these).
        duration_sec = float(row.get("duration_sec", 0.0))
        for cam in row.get("cameras") or []:
            key = f"videos/observation.images.{cam}"
            ep_record[f"{key}/chunk_index"] = 0
            ep_record[f"{key}/file_index"] = row["episode_index"]
            ep_record[f"{key}/from_timestamp"] = 0.0
            ep_record[f"{key}/to_timestamp"] = duration_sec
        # Keep all original fields too for our own use
        for k, v in row.items():
            if k not in ep_record:
                ep_record[k] = v

        ep_record = _sanitize_for_parquet(ep_record)

        if pq_path.exists():
            existing = pq.read_table(pq_path).to_pylist()
            existing.append(ep_record)
            # Recompute dataset_from/to indices
            offset = 0
            for e in sorted(existing, key=lambda x: x["episode_index"]):
                e["dataset_from_index"] = offset
                e["dataset_to_index"] = offset + e.get("length", 0)
                offset = e["dataset_to_index"]
            table = pa.Table.from_pylist(existing)
        else:
            table = pa.Table.from_pylist([ep_record])

        _atomic_write_parquet(table, pq_path)
        update_info_totals(meta_dir, coordinator=coordinator, ds_name=ds_name)


def read_episodes(meta_dir: Path, include_deleted: bool = False) -> Iterator[dict]:
    pq_path = _episodes_parquet(meta_dir)
    if not pq_path.exists():
        return
    table = pq.read_table(pq_path)
    for row in table.to_pylist():
        row = _deserialize_json_fields(row)
        if include_deleted or not row.get("deleted", False):
            yield row


def tombstone_episode(
    meta_dir: Path,
    episode_index: int,
    deleted_at_unix: int,
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    with _maybe_lock(coordinator, ds_name):
        pq_path = _episodes_parquet(meta_dir)
        rows = pq.read_table(pq_path).to_pylist()
        found = False
        for row in rows:
            # pa.Table.from_pylist infers the schema from row 0 only, so any column
            # missing from the first row is silently dropped on write. Pre-pad every
            # row so the deletion fields land in the schema regardless of which row
            # is being tombstoned.
            row.setdefault("deleted", False)
            row.setdefault("deleted_at", None)
            if row["episode_index"] == episode_index:
                if row["deleted"]:
                    raise KeyError(f"episode {episode_index} already deleted")
                row["deleted"] = True
                row["deleted_at"] = deleted_at_unix
                found = True
        if not found:
            raise KeyError(f"episode {episode_index} not found")
        _atomic_write_parquet(pa.Table.from_pylist(rows), pq_path)
        update_info_totals(meta_dir, coordinator=coordinator, ds_name=ds_name)


def upsert_task(
    meta_dir: Path,
    task_name: str,
    instruction: str,
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    with _maybe_lock(coordinator, ds_name):
        pq_path = _tasks_parquet(meta_dir)
        if pq_path.exists():
            tasks = pq.read_table(pq_path).to_pylist()
        else:
            tasks = []
        for t in tasks:
            if t.get("task") == task_name:
                t["instruction"] = instruction
                break
        else:
            task_index = len(tasks)
            tasks.append({"task": task_name, "task_index": task_index, "instruction": instruction})
        _atomic_write_parquet(pa.Table.from_pylist(tasks), pq_path)


def update_info_totals(
    meta_dir: Path,
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    """Update info.json totals from current episodes + tasks state."""
    with _maybe_lock(coordinator, ds_name):
        info_path = meta_dir / "info.json"
        if not info_path.exists():
            return
        info = json.loads(info_path.read_text())
        episodes = list(read_episodes(meta_dir, include_deleted=False))
        total_episodes = len(episodes)
        total_frames = sum(e.get("length", e.get("num_frames", 0)) for e in episodes)
        tasks_pq = _tasks_parquet(meta_dir)
        total_tasks = pq.read_table(tasks_pq).num_rows if tasks_pq.exists() else 0
        info["total_episodes"] = total_episodes
        info["total_frames"] = total_frames
        info["total_tasks"] = total_tasks
        info["splits"] = {"train": f"0:{total_episodes}"}
        _atomic_write_text(info_path, json.dumps(info, indent=2))
