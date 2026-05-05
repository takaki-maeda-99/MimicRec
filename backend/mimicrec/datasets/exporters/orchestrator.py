"""Orchestrate dataset export to a local directory.

Two formats:

- ``ExportFormat.LEROBOT_V3_NATIVE`` -- write what ``build_archive_stream``
  yields straight to disk (same content as the existing zip download, just
  unpacked).
- ``ExportFormat.VLA_COMPAT`` -- convert each episode's parquet to the
  shape-7 action/state schema, embed expanded instructions, write
  ``info.json`` rewrite + ``action_stats.json``, copy mp4s.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.api.schemas import ExportFormat
from mimicrec.datasets.archive import build_archive_stream
from mimicrec.datasets.exporters.errors import DestinationExistsError
from mimicrec.datasets.exporters.info_json import to_vla_info
from mimicrec.datasets.exporters.instructions import expand_instruction
from mimicrec.datasets.exporters.stats import compute_stats
from mimicrec.datasets.exporters.vla_compat import convert_episode_table
from mimicrec.datasets.reader import iter_episodes, read_dataset_info
from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk


# Adapter-class lookup for request-body overrides on legacy datasets.
# Map robot_type string → (adapter_class_name, gc_factory, pl_factory).
_ROBOT_OVERRIDE_REGISTRY: dict[str, tuple] = {}


def _register_robot_override(robot_type: str):
    """Lazy import + registration to avoid a hard dependency on optional
    adapter modules at exporter import time."""
    if robot_type in _ROBOT_OVERRIDE_REGISTRY:
        return _ROBOT_OVERRIDE_REGISTRY[robot_type]
    if robot_type == "so101":
        from mimicrec.adapters.so101 import SO101Adapter
        cls = SO101Adapter
    elif robot_type == "rebot":
        from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter
        cls = ReBotArmZmqAdapter
    else:
        raise ValueError(
            f"unknown robot_type override {robot_type!r}; "
            f"supported: 'so101', 'rebot'"
        )
    entry = (
        cls.__name__,
        cls.default_gripper_convention,
        cls.proprio_layout,
    )
    _ROBOT_OVERRIDE_REGISTRY[robot_type] = entry
    return entry


@dataclass(frozen=True)
class ExportOverride:
    robot_type: str | None = None        # 'so101' / 'rebot'


@dataclass(frozen=True)
class ExportResult:
    dest_path: Path
    format: ExportFormat
    num_episodes: int
    num_frames: int
    warnings: list[str] = field(default_factory=list)


def export_dataset_to_local(
    *,
    ds_root: Path,
    dest_root: Path,
    format: ExportFormat,
    instruction_template: str,
    force: bool,
    override: ExportOverride | None = None,
) -> ExportResult:
    out_dir = dest_root / ds_root.name
    partial_dir = dest_root / (ds_root.name + ".partial")

    if out_dir.exists() and not force:
        raise DestinationExistsError(str(out_dir))

    # Always clean up any stale partial from a previous failed run.
    if partial_dir.exists():
        shutil.rmtree(partial_dir)
    partial_dir.mkdir(parents=True, exist_ok=False)

    try:
        if format == ExportFormat.LEROBOT_V3_NATIVE:
            result = _export_v3_native(
                ds_root=ds_root, out_dir=partial_dir, format=format,
            )
        elif format == ExportFormat.VLA_COMPAT:
            result = _export_vla_compat(
                ds_root=ds_root, out_dir=partial_dir, format=format,
                instruction_template=instruction_template,
                override=override,
            )
        else:
            raise ValueError(f"unsupported export format: {format}")
    except BaseException:
        shutil.rmtree(partial_dir, ignore_errors=True)
        raise

    # Success: swap in atomically.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    os.rename(partial_dir, out_dir)

    # The result was constructed with partial_dir as dest_path; rebuild with out_dir.
    return ExportResult(
        dest_path=out_dir,
        format=result.format,
        num_episodes=result.num_episodes,
        num_frames=result.num_frames,
        warnings=result.warnings,
    )


def _export_v3_native(*, ds_root: Path, out_dir: Path, format: ExportFormat) -> ExportResult:
    for path_in_zip, content in build_archive_stream(ds_root):
        target = out_dir / path_in_zip
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path):
            shutil.copy2(content, target)
        else:
            target.write_bytes(content)
    info = read_dataset_info(out_dir)
    return ExportResult(
        dest_path=out_dir,
        format=format,
        num_episodes=info.get("total_episodes", 0),
        num_frames=info.get("total_frames", 0),
    )


def _load_tasks_lookup(ds_root: Path) -> dict[int, dict]:
    p = dataset_paths(ds_root)
    if not p.tasks_parquet.exists():
        return {}
    rows = pq.read_table(p.tasks_parquet).to_pylist()
    return {int(r["task_index"]): r for r in rows}


def _export_vla_compat(
    *, ds_root: Path, out_dir: Path, format: ExportFormat,
    instruction_template: str,
    override: ExportOverride | None = None,
) -> ExportResult:
    # --- Step 1: resolve gripper_convention + proprio_layout ---
    src_info = read_dataset_info(ds_root)
    info_robot_type = src_info.get("robot_type", "unknown")
    info_gc = src_info.get("gripper_convention")
    info_pl = src_info.get("proprio_layout")

    needs_override = (
        info_robot_type == "unknown"
        or info_gc is None
        or info_pl is None
    )
    if needs_override:
        if override is None or override.robot_type is None:
            raise ValueError(
                "dataset's info.json declares robot_type='unknown' (or is missing "
                "gripper_convention/proprio_layout). Re-record after the "
                "recording-layer change in this PR, or pass robot_type='so101' "
                "(or 'rebot') in the export request body to override for one-off "
                "reprocessing of pre-existing data."
            )
        cls_name, gc_factory, pl_factory = _register_robot_override(override.robot_type)
        robot_type = cls_name
        gc: GripperConvention = gc_factory()
        pl: ProprioLayout = pl_factory()
        gc_dict = {"closed_at": gc.closed_at, "open_at": gc.open_at}
    else:
        robot_type = info_robot_type
        gc = GripperConvention(**info_gc)
        pl = ProprioLayout(
            columns=tuple(info_pl["columns"]),
            output_names=tuple(info_pl["output_names"]),
            gripper_via_column=info_pl["gripper_via_column"],
            gripper_index_in_column=int(info_pl["gripper_index_in_column"]),
        )
        gc_dict = {"closed_at": gc.closed_at, "open_at": gc.open_at}

    # --- Step 2: set up output dirs ---
    p = dataset_paths(ds_root)
    out_meta = out_dir / "meta"
    out_meta.mkdir(parents=True, exist_ok=True)
    out_data = out_dir / "data"
    out_data.mkdir(parents=True, exist_ok=True)
    out_videos = out_dir / "videos"
    out_videos.mkdir(parents=True, exist_ok=True)

    tasks_lookup = _load_tasks_lookup(ds_root)
    warnings: list[str] = []
    converted_tables: list[pa.Table] = []
    num_episodes = 0
    num_frames = 0
    n_proprio: int | None = None

    # --- Step 3: convert episodes ---
    live_eps = list(iter_episodes(ds_root, include_deleted=False))
    for ep in live_eps:
        ep_idx = int(ep["episode_index"])
        task_idx = int(ep.get("task_index", 0))
        task_row = tasks_lookup.get(task_idx, {"task": ep.get("task", "unknown"), "instruction": ""})
        rendered = expand_instruction(
            template=instruction_template,
            task_name=task_row.get("task", "unknown"),
            instruction=task_row.get("instruction") or None,
        )
        warnings.extend(f"episode={ep_idx} {w.value}" for w in rendered.warnings)

        chunk = resolve_chunk(ep_idx)
        in_pq = p.episode_parquet(chunk, ep_idx)
        in_table = pq.read_table(in_pq)
        out_episode = convert_episode_table(
            table=in_table, instruction_text=rendered.text,
            gripper_convention=gc, proprio_layout=pl,
        )

        # Derive n_proprio from first episode; validate consistency on subsequent.
        ep_col = out_episode.table.schema.field("observation.state")
        ep_n_proprio = ep_col.type.list_size
        if n_proprio is None:
            n_proprio = ep_n_proprio
        elif ep_n_proprio != n_proprio:
            raise ValueError(
                f"observation.state dim mismatch across episodes: "
                f"episode {ep_idx} has dim={ep_n_proprio}, expected {n_proprio}"
            )

        out_pq_dir = out_data / f"chunk-{chunk:03d}"
        out_pq_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(out_episode.table, out_pq_dir / f"episode_{ep_idx:06d}.parquet")
        converted_tables.append(out_episode.table)
        num_episodes += 1
        num_frames += out_episode.table.num_rows

        # mp4 copy -- LeRobot v3 layout: videos/observation.images.<cam>/chunk-XXX/...
        if p.videos_dir.exists():
            for cam_dir in p.videos_dir.iterdir():
                if not cam_dir.name.startswith("observation.images."):
                    continue
                src_mp4 = cam_dir / f"chunk-{chunk:03d}" / f"episode_{ep_idx:06d}.mp4"
                if src_mp4.exists():
                    dst_dir = out_videos / cam_dir.name / f"chunk-{chunk:03d}"
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_mp4, dst_dir / src_mp4.name)

    # --- Step 4: info.json rewrite ---
    new_info = to_vla_info(
        src_info,
        robot_type=robot_type,
        gripper_convention=gc_dict,
        proprio_layout=pl,
        n_proprio=int(n_proprio or 0),
    )
    new_info["total_episodes"] = num_episodes
    new_info["total_frames"] = num_frames
    (out_meta / "info.json").write_text(json.dumps(new_info, indent=2))

    # --- Step 5: triple stats files ---
    if converted_tables:
        action_stats, action_q99, proprio_q99 = compute_stats(converted_tables)
        (out_meta / "action_stats.json").write_text(json.dumps(action_stats))
        (out_meta / "action_stats_q99.json").write_text(json.dumps(action_q99))
        (out_meta / "proprio_stats_q99.json").write_text(json.dumps(proprio_q99))

    # tasks.parquet verbatim copy (tests/training read it).
    if p.tasks_parquet.exists():
        shutil.copy2(p.tasks_parquet, out_meta / "tasks.parquet")

    # episodes.parquet -- re-use build_archive_stream's filtered version so
    # tombstoned rows stay excluded.
    for path_in_zip, content in build_archive_stream(ds_root):
        if path_in_zip == "meta/episodes/chunk-000/file-000.parquet":
            target = out_meta / "episodes" / "chunk-000" / "file-000.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content if isinstance(content, bytes) else content.read_bytes())
            break

    return ExportResult(
        dest_path=out_dir,
        format=format,
        num_episodes=num_episodes,
        num_frames=num_frames,
        warnings=warnings,
    )
