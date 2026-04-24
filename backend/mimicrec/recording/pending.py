from __future__ import annotations
import shutil
from pathlib import Path

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

    def open_video_writers(self, fps: int, cameras: dict[str, tuple[int, int]]) -> None:
        """Open one Mp4EpisodeWriter per camera. `cameras` maps name -> (width, height)."""
        from mimicrec.cameras.recording import Mp4EpisodeWriter
        self._video_writers: dict[str, Mp4EpisodeWriter] = {}
        for name, (w, h) in cameras.items():
            path = self._stage / f"{name}.mp4"
            self._video_writers[name] = Mp4EpisodeWriter(path, fps=fps, width=w, height=h)

    def append_row(self, row: dict, frames: dict[str, object] | None = None) -> int:
        if self._finalized:
            raise RuntimeError("cannot append after finalize()")
        self._rows.append(row)
        if frames and getattr(self, "_video_writers", None):
            for name, stamped in frames.items():
                if stamped is None:
                    continue
                writer = self._video_writers.get(name)
                if writer is not None:
                    writer.write_frame(stamped.value.image)
        return len(self._rows) - 1

    def finalize(self) -> None:
        if self._finalized:
            return
        import pyarrow as pa
        import pyarrow.parquet as pq
        table = pa.Table.from_pylist(self._rows)
        pq.write_table(table, self._stage / f"episode_{self._episode_index:06d}.parquet")
        for w in getattr(self, "_video_writers", {}).values():
            w.close()
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
