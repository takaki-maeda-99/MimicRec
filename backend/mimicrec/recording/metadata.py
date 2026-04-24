from __future__ import annotations
import json
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from typing import Iterator


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


def append_episode(meta_dir: Path, row: dict) -> None:
    """Append an episode row to episodes parquet."""
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

    pq.write_table(table, pq_path)
    update_info_totals(meta_dir)


def read_episodes(meta_dir: Path, include_deleted: bool = False) -> Iterator[dict]:
    pq_path = _episodes_parquet(meta_dir)
    if not pq_path.exists():
        return
    table = pq.read_table(pq_path)
    for row in table.to_pylist():
        row = _deserialize_json_fields(row)
        if include_deleted or not row.get("deleted", False):
            yield row


def tombstone_episode(meta_dir: Path, episode_index: int, deleted_at_unix: int) -> None:
    pq_path = _episodes_parquet(meta_dir)
    rows = pq.read_table(pq_path).to_pylist()
    found = False
    for row in rows:
        if row["episode_index"] == episode_index:
            if row.get("deleted"):
                raise KeyError(f"episode {episode_index} already deleted")
            row["deleted"] = True
            row["deleted_at"] = deleted_at_unix
            found = True
            break
    if not found:
        raise KeyError(f"episode {episode_index} not found")
    pq.write_table(pa.Table.from_pylist(rows), pq_path)


def upsert_task(meta_dir: Path, task_name: str, instruction: str) -> None:
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
    pq.write_table(pa.Table.from_pylist(tasks), pq_path)


def update_info_totals(meta_dir: Path) -> None:
    """Update info.json totals from current episodes state."""
    info_path = meta_dir / "info.json"
    if not info_path.exists():
        return
    info = json.loads(info_path.read_text())
    episodes = list(read_episodes(meta_dir, include_deleted=False))
    total_episodes = len(episodes)
    total_frames = sum(e.get("length", e.get("num_frames", 0)) for e in episodes)
    info["total_episodes"] = total_episodes
    info["total_frames"] = total_frames
    info["splits"] = {"train": f"0:{total_episodes}"}
    info_path.write_text(json.dumps(info, indent=2))
