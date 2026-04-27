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
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.api.schemas import ExportFormat
from mimicrec.datasets.archive import build_archive_stream
from mimicrec.datasets.exporters.errors import DestinationExistsError
from mimicrec.datasets.exporters.info_json import to_vla_info
from mimicrec.datasets.exporters.instructions import expand_instruction
from mimicrec.datasets.exporters.stats import compute_action_stats
from mimicrec.datasets.exporters.vla_compat import convert_episode_table
from mimicrec.datasets.reader import iter_episodes, read_dataset_info
from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk


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
) -> ExportResult:
    out_dir = dest_root / ds_root.name
    if out_dir.exists():
        if not force:
            raise DestinationExistsError(str(out_dir))
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)

    if format == ExportFormat.LEROBOT_V3_NATIVE:
        return _export_v3_native(ds_root=ds_root, out_dir=out_dir, format=format)
    if format == ExportFormat.VLA_COMPAT:
        return _export_vla_compat(
            ds_root=ds_root, out_dir=out_dir, format=format,
            instruction_template=instruction_template,
        )
    raise ValueError(f"unsupported export format: {format}")


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
) -> ExportResult:
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
        )
        out_pq_dir = out_data / f"chunk-{chunk:03d}"
        out_pq_dir.mkdir(parents=True, exist_ok=True)
        pq.write_table(out_episode.table, out_pq_dir / f"episode_{ep_idx:06d}.parquet")
        converted_tables.append(out_episode.table)
        num_episodes += 1
        num_frames += out_episode.table.num_rows

        # mp4 copy -- preserve full LeRobot video tree.
        videos_chunk = p.videos_dir / f"chunk-{chunk:03d}"
        if videos_chunk.exists():
            for cam_dir in videos_chunk.iterdir():
                src_mp4 = cam_dir / f"episode_{ep_idx:06d}.mp4"
                if src_mp4.exists():
                    dst_dir = out_videos / f"chunk-{chunk:03d}" / cam_dir.name
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_mp4, dst_dir / src_mp4.name)

    # info.json rewrite.
    src_info = read_dataset_info(ds_root)
    new_info = to_vla_info(src_info)
    new_info["total_episodes"] = num_episodes
    new_info["total_frames"] = num_frames
    (out_meta / "info.json").write_text(json.dumps(new_info, indent=2))

    # action_stats.json.
    if converted_tables:
        stats = compute_action_stats(converted_tables)
        (out_meta / "action_stats.json").write_text(json.dumps(stats))

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
