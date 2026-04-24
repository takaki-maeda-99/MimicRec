from __future__ import annotations
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import (
    DatasetPaths, dataset_paths, resolve_chunk,
)
from mimicrec.recording.metadata import append_episode


class PendingEpisode:
    """A staged, not-yet-committed episode."""

    def __init__(self, paths: DatasetPaths, episode_index: int):
        self._paths = paths
        self._episode_index = episode_index
        self._stage = paths.pending_dir / f"ep_{episode_index:06d}"
        self._rows: list[dict] = []
        self._finalized = False

    @classmethod
    def open(cls, ds_root: Path, episode_index: int) -> "PendingEpisode":
        p = dataset_paths(ds_root)
        p.pending_dir.mkdir(parents=True, exist_ok=True)
        inst = cls(p, episode_index)
        if inst._stage.exists():
            shutil.rmtree(inst._stage)
        inst._stage.mkdir(parents=True)
        return inst

    @property
    def stage_dir(self) -> Path:
        return self._stage

    @property
    def episode_index(self) -> int:
        return self._episode_index

    def append_row(self, row: dict) -> None:
        if self._finalized:
            raise RuntimeError("cannot append after finalize()")
        self._rows.append(row)

    def finalize(self) -> None:
        if self._finalized:
            return
        table = pa.Table.from_pylist(self._rows)
        pq.write_table(table, self._stage / f"episode_{self._episode_index:06d}.parquet")
        self._finalized = True

    def save(self, metadata_extra: dict) -> None:
        if not self._finalized:
            raise RuntimeError("call finalize() before save()")
        chunk_idx = resolve_chunk(self._episode_index)
        self._paths.chunk_dir(chunk_idx).mkdir(parents=True, exist_ok=True)
        src = self._stage / f"episode_{self._episode_index:06d}.parquet"
        dst = self._paths.episode_parquet(chunk_idx, self._episode_index)
        shutil.move(str(src), str(dst))
        for mp4 in self._stage.glob("*.mp4"):
            cam_name = mp4.stem
            vdst = self._paths.episode_video(chunk_idx, cam_name, self._episode_index)
            vdst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(mp4), str(vdst))
        append_episode(self._paths.meta_dir, metadata_extra)
        shutil.rmtree(self._stage)

    def discard(self) -> None:
        if self._stage.exists():
            shutil.rmtree(self._stage)
