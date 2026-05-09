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
    episodes_dir: Path
    tasks_parquet: Path

    def chunk_dir(self, chunk_index: int) -> Path:
        return self.data_dir / f"chunk-{chunk_index:03d}"

    def episode_parquet(self, chunk_index: int, episode_index: int) -> Path:
        return self.chunk_dir(chunk_index) / f"episode_{episode_index:06d}.parquet"

    def episode_video(self, chunk_index: int, cam_name: str, episode_index: int) -> Path:
        return (
            self.videos_dir / f"observation.images.{cam_name}"
            / f"chunk-{chunk_index:03d}" / f"episode_{episode_index:06d}.mp4"
        )


def dataset_paths(ds_root: Path) -> DatasetPaths:
    return DatasetPaths(
        root=ds_root,
        meta_dir=ds_root / "meta",
        data_dir=ds_root / "data",
        videos_dir=ds_root / "videos",
        pending_dir=ds_root / ".pending",
        episodes_dir=ds_root / "meta" / "episodes",
        tasks_parquet=ds_root / "meta" / "tasks.parquet",
    )


def init_dataset(
    ds_root: Path,
    fps: int,
    joint_names: list[str],
    camera_names: list[str],
    *,
    robot_type: str | None = None,
    gripper_convention: dict | None = None,
    proprio_layout: dict | None = None,
    camera_resolutions: dict[str, tuple[int, int]] | None = None,
    gopro_specs: "dict[str, object] | None" = None,
) -> None:
    p = dataset_paths(ds_root)
    p.meta_dir.mkdir(parents=True, exist_ok=True)
    p.data_dir.mkdir(parents=True, exist_ok=True)
    p.videos_dir.mkdir(parents=True, exist_ok=True)
    p.episodes_dir.mkdir(parents=True, exist_ok=True)

    # Build features dict
    dof = len(joint_names)
    features = {}
    if dof > 0:
        features["action"] = {"dtype": "float32", "shape": [dof], "names": joint_names}
        features["observation.state"] = {"dtype": "float32", "shape": [dof], "names": joint_names}
    features["timestamp"] = {"dtype": "float32", "shape": [1], "names": None}
    features["frame_index"] = {"dtype": "int64", "shape": [1], "names": None}
    features["episode_index"] = {"dtype": "int64", "shape": [1], "names": None}
    features["index"] = {"dtype": "int64", "shape": [1], "names": None}
    features["task_index"] = {"dtype": "int64", "shape": [1], "names": None}

    for cam in camera_names:
        if camera_resolutions and cam in camera_resolutions:
            w, h = camera_resolutions[cam]
        else:
            w, h = 640, 480
        features[f"observation.images.{cam}"] = {
            "dtype": "video",
            "shape": [h, w, 3],
            "names": ["height", "width", "channels"],
            "info": {
                "video.height": h, "video.width": w,
                "video.codec": "libx264", "video.pix_fmt": "yuv420p",
                "video.is_depth_map": False, "video.fps": fps,
                "video.channels": 3, "has_audio": False,
            },
        }

    if gopro_specs:
        for name, spec in gopro_specs.items():
            features[f"observation.images.{name}"] = {
                "dtype": "video",
                "shape": [spec.height, spec.width, 3],
                "names": ["height", "width", "channels"],
                "info": {
                    "video.height": spec.height,
                    "video.width": spec.width,
                    "video.codec": spec.codec,
                    "video.pix_fmt": "yuv420p",
                    "video.is_depth_map": False,
                    "video.fps": spec.fps,
                    "video.channels": 3,
                    "has_audio": False,
                    "has_gpmf": True,
                },
            }

    info: dict = {
        "codebase_version": "v3.0",
        "robot_type": robot_type if robot_type is not None else "unknown",
        "total_episodes": 0,
        "total_frames": 0,
        "total_tasks": 0,
        "chunks_size": 1000,
        "data_files_size_in_mb": 0,
        "video_files_size_in_mb": 0,
        "fps": fps,
        "splits": {"train": "0:0"},
        "data_path": "data/chunk-{chunk_index:03d}/episode_{file_index:06d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{file_index:06d}.mp4",
        "features": features,
    }
    if gripper_convention is not None:
        info["gripper_convention"] = gripper_convention
    if proprio_layout is not None:
        info["proprio_layout"] = proprio_layout
    (p.meta_dir / "info.json").write_text(json.dumps(info, indent=2))

    # Create empty tasks.parquet with proper schema
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = pa.schema([
        ("task", pa.string()),
        ("task_index", pa.int64()),
        ("instruction", pa.string()),
    ])
    pq.write_table(pa.table({"task": [], "task_index": [], "instruction": []}, schema=schema), p.tasks_parquet)


def resolve_chunk(episode_index: int, episodes_per_chunk: int = 1000) -> int:
    return episode_index // episodes_per_chunk
