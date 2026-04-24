from __future__ import annotations
import json
from pathlib import Path
from typing import Iterator

from mimicrec.datasets.reader import iter_episodes
from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk


def build_archive_stream(ds_root: Path) -> Iterator[tuple[str, bytes | Path]]:
    p = dataset_paths(ds_root)
    live_rows = list(iter_episodes(ds_root, include_deleted=False))
    live_indices = {r["episode_index"] for r in live_rows}

    info = p.meta_dir / "info.json"
    if info.exists():
        yield "meta/info.json", info
    tasks = p.meta_dir / "tasks.jsonl"
    if tasks.exists():
        yield "meta/tasks.jsonl", tasks

    rewritten = "\n".join(json.dumps(r) for r in live_rows) + ("\n" if live_rows else "")
    yield "meta/episodes.jsonl", rewritten.encode("utf-8")

    for idx in sorted(live_indices):
        chunk = resolve_chunk(idx)
        parquet = p.episode_parquet(chunk, idx)
        if parquet.exists():
            rel = parquet.relative_to(ds_root).as_posix()
            yield rel, parquet

        videos_chunk = p.videos_dir / f"chunk-{chunk:03d}"
        if videos_chunk.exists():
            for cam_dir in videos_chunk.iterdir():
                mp4 = cam_dir / f"episode_{idx:06d}.mp4"
                if mp4.exists():
                    rel = mp4.relative_to(ds_root).as_posix()
                    yield rel, mp4
