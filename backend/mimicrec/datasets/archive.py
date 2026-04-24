from __future__ import annotations
from pathlib import Path
from typing import Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.datasets.reader import iter_episodes
from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk


def build_archive_stream(ds_root: Path) -> Iterator[tuple[str, bytes | Path]]:
    p = dataset_paths(ds_root)
    live_rows = list(iter_episodes(ds_root, include_deleted=False))
    live_indices = {r["episode_index"] for r in live_rows}

    info = p.meta_dir / "info.json"
    if info.exists():
        yield "meta/info.json", info

    tasks_pq = p.tasks_parquet
    if tasks_pq.exists():
        yield "meta/tasks.parquet", tasks_pq

    # Rewrite episodes parquet with only live rows
    if live_rows:
        table = pa.Table.from_pylist(live_rows)
        import io
        buf = io.BytesIO()
        pq.write_table(table, buf)
        yield "meta/episodes/chunk-000/file-000.parquet", buf.getvalue()

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
