from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator


def _episodes_path(meta_dir: Path) -> Path:
    return meta_dir / "episodes.jsonl"


def append_episode(meta_dir: Path, row: dict) -> None:
    with _episodes_path(meta_dir).open("a") as f:
        f.write(json.dumps(row) + "\n")


def read_episodes(meta_dir: Path, include_deleted: bool = False) -> Iterator[dict]:
    p = _episodes_path(meta_dir)
    if not p.exists():
        return
    with p.open() as f:
        for line in f:
            row = json.loads(line)
            if include_deleted or not row.get("deleted", False):
                yield row


def tombstone_episode(meta_dir: Path, episode_index: int, deleted_at_unix: int) -> None:
    p = _episodes_path(meta_dir)
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
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
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def upsert_task(meta_dir: Path, task_name: str, instruction: str) -> None:
    p = meta_dir / "tasks.jsonl"
    tasks = [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []
    for t in tasks:
        if t["task"] == task_name:
            t["instruction"] = instruction
            break
    else:
        tasks.append({"task": task_name, "instruction": instruction})
    p.write_text("\n".join(json.dumps(t) for t in tasks) + "\n")
