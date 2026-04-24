from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatasetPaths:
    root: Path
    meta_dir: Path
    data_dir: Path
    videos_dir: Path
    pending_dir: Path

    def chunk_dir(self, chunk_index: int) -> Path:
        return self.data_dir / f"chunk-{chunk_index:03d}"

    def episode_parquet(self, chunk_index: int, episode_index: int) -> Path:
        return self.chunk_dir(chunk_index) / f"episode_{episode_index:06d}.parquet"

    def episode_video(self, chunk_index: int, cam_name: str, episode_index: int) -> Path:
        return (
            self.videos_dir / f"chunk-{chunk_index:03d}"
            / f"observation.images.{cam_name}" / f"episode_{episode_index:06d}.mp4"
        )


def dataset_paths(ds_root: Path) -> DatasetPaths:
    return DatasetPaths(
        root=ds_root,
        meta_dir=ds_root / "meta",
        data_dir=ds_root / "data",
        videos_dir=ds_root / "videos",
        pending_dir=ds_root / ".pending",
    )


def init_dataset(ds_root: Path, fps: int, joint_names: list[str], camera_names: list[str]) -> None:
    p = dataset_paths(ds_root)
    p.meta_dir.mkdir(parents=True, exist_ok=True)
    p.data_dir.mkdir(parents=True, exist_ok=True)
    p.videos_dir.mkdir(parents=True, exist_ok=True)
    info = {
        "codebase_version": "mimicrec-0.1.0",
        "fps": fps,
        "joint_names": joint_names,
        "camera_names": camera_names,
    }
    (p.meta_dir / "info.json").write_text(json.dumps(info, indent=2))
    (p.meta_dir / "episodes.jsonl").touch()
    (p.meta_dir / "tasks.jsonl").touch()


def resolve_chunk(episode_index: int, episodes_per_chunk: int = 1000) -> int:
    return episode_index // episodes_per_chunk
