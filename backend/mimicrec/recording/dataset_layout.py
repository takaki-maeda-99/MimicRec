from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

from mimicrec.recording.atomic_io import _atomic_write_parquet, _atomic_write_text


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
) -> None:
    # ds_root may already exist if the caller pre-created subdirs (e.g.
    # api/deps.py creates `.pending/` before init_dataset is invoked).
    # Tolerate an empty pre-existing ds_root.
    ds_root.mkdir(parents=True, exist_ok=True)
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
    _atomic_write_text(p.meta_dir / "info.json", json.dumps(info, indent=2))

    # Create empty tasks.parquet with proper schema
    import pyarrow as pa
    schema = pa.schema([
        ("task", pa.string()),
        ("task_index", pa.int64()),
        ("instruction", pa.string()),
    ])
    _atomic_write_parquet(pa.table({"task": [], "task_index": [], "instruction": []}, schema=schema), p.tasks_parquet)


def init_motion_dataset(
    ds_root: Path,
    fps: int,
    *,
    resources: dict[str, dict],
    motion_groups: dict[str, dict],
    camera_names: list[str],
    camera_resolutions: dict[str, tuple[int, int]] | None = None,
    profile_name: str | None = None,
) -> None:
    """Initialize a namespaced multi-resource dataset.

    The ordinary LeRobot bookkeeping fields and videos remain unchanged. The
    action/observation features are added per named resource and Motion Group,
    avoiding an embodiment-specific concatenation in the authoritative data.
    """

    init_dataset(
        ds_root,
        fps,
        joint_names=[],
        camera_names=camera_names,
        robot_type="motion_graph",
        camera_resolutions=camera_resolutions,
    )
    info_path = dataset_paths(ds_root).meta_dir / "info.json"
    info = json.loads(info_path.read_text())
    features = info["features"]
    for resource_name, spec in resources.items():
        kind = str(spec.get("kind", "joint"))
        if kind == "joint":
            names = [str(name) for name in spec.get("joint_names", [])]
            if not names:
                raise ValueError(
                    f"joint resource {resource_name!r} requires joint_names"
                )
            for suffix in ("joint_pos", "joint_vel", "joint_effort"):
                features[f"observation.state.{resource_name}.{suffix}"] = {
                    "dtype": "float32",
                    "shape": [len(names)],
                    "names": names,
                    "unit": (
                        "rad_s" if suffix == "joint_vel"
                        else "rad" if suffix == "joint_pos"
                        else "native"
                    ),
                }
            features[f"action.resource.{resource_name}.joint_pos"] = {
                "dtype": "float32",
                "shape": [len(names)],
                "names": names,
                "unit": "rad",
            }
        elif kind == "scalar":
            for suffix in ("position", "velocity", "effort"):
                features[f"observation.state.{resource_name}.{suffix}"] = {
                    "dtype": "float32", "shape": [1], "names": [resource_name]
                }
            features[f"action.resource.{resource_name}.position"] = {
                "dtype": "float32", "shape": [1], "names": [resource_name]
            }
        elif kind == "planar":
            features[f"observation.state.{resource_name}.pose_xy_yaw"] = {
                "dtype": "float32", "shape": [3], "names": ["x", "y", "yaw"]
            }
            features[f"action.resource.{resource_name}.velocity_xy_yaw"] = {
                "dtype": "float32", "shape": [3], "names": ["vx", "vy", "wyaw"]
            }
        else:
            raise ValueError(f"unknown resource kind {kind!r}")

    for group_name, spec in motion_groups.items():
        prefix = f"action.motion.{group_name}"
        features[f"{prefix}.se3_delta"] = {
            "dtype": "float32",
            "shape": [6],
            "names": ["dx", "dy", "dz", "dRx", "dRy", "dRz"],
        }
        features[f"{prefix}.duration_sec"] = {
            "dtype": "float32", "shape": [1], "names": None
        }
        features[f"{prefix}.active_mask"] = {
            "dtype": "bool", "shape": [6], "names": None
        }
        for auxiliary in spec.get("auxiliary", []):
            features[f"{prefix}.aux.{auxiliary}"] = {
                "dtype": "float32", "shape": [1], "names": [str(auxiliary)]
            }

    info["motion_schema"] = {
        "version": 1,
        "representation": "se3_log_increment",
        "default_frame": "ee_local",
        "tangent_order": ["dx", "dy", "dz", "dRx", "dRy", "dRz"],
        "composition": "T_next = T_current @ Exp(delta)",
        "resources": resources,
        "motion_groups": motion_groups,
        "profile": profile_name,
    }
    _atomic_write_text(info_path, json.dumps(info, indent=2))


def resolve_chunk(episode_index: int, episodes_per_chunk: int = 1000) -> int:
    return episode_index // episodes_per_chunk
