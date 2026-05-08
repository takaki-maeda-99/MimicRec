from __future__ import annotations
import asyncio
import io
import json
import logging
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

import pyarrow.parquet as pq
from fastapi import APIRouter, Request, Query, HTTPException
from omegaconf import OmegaConf
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel as _BaseModel

from mimicrec.api.deps import get_datasets_root, get_configs_root, get_vla_dest_root
from mimicrec.api.schemas import (
    CreateDatasetRequest, CreateTaskRequest, DatasetSummary,
    EpisodeSummary, ExportFormat, ExportRequest, ExportResponse, TaskSummary,
    DEFAULT_INSTRUCTION_TEMPLATE,
)
from mimicrec.datasets.archive import build_archive_stream
from mimicrec.datasets.exporters.errors import DestinationExistsError
from mimicrec.datasets.exporters.orchestrator import export_dataset_to_local, ExportOverride
from mimicrec.datasets.reader import iter_episodes, read_dataset_info
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths, resolve_chunk
from mimicrec.recording.metadata import tombstone_episode, upsert_task

router = APIRouter()


@router.get("/datasets")
async def list_datasets(request: Request):
    root = get_datasets_root(request.app)
    if not root.exists():
        return []
    result = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "meta" / "info.json").exists():
            try:
                info = read_dataset_info(d)
                result.append(DatasetSummary(
                    name=d.name,
                    num_episodes=info.get("total_episodes", 0),
                    total_frames=info.get("total_frames", 0),
                ))
            except Exception:
                continue
    return result


@router.delete("/datasets/{ds}", status_code=204)
async def delete_dataset(request: Request, ds: str):
    import shutil
    from mimicrec.api.util import safe_dataset_path, UnsafePathError
    root = get_datasets_root(request.app)
    try:
        ds_root = safe_dataset_path(root, ds)
    except UnsafePathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ds_root.exists():
        raise HTTPException(status_code=404, detail=f"dataset '{ds}' not found")
    coord = request.app.state.push_coordinator
    if ds in coord.in_flight:
        raise HTTPException(status_code=409, detail="cannot delete: push in flight")
    save_lock = coord.get_save_lock(ds)
    with save_lock:
        shutil.rmtree(ds_root)
        coord.drop_dataset(ds)


@router.post("/datasets")
async def create_dataset(request: Request, body: CreateDatasetRequest):
    root = get_datasets_root(request.app)
    ds_root = root / body.name
    if ds_root.exists():
        raise HTTPException(status_code=409, detail=f"dataset '{body.name}' already exists")
    configs_root = get_configs_root(request.app)
    camera_resolutions: dict[str, tuple[int, int]] = {}
    for cam_name in body.camera_names:
        cam_path = configs_root / "cameras" / f"{cam_name}.yaml"
        if not cam_path.exists():
            continue
        try:
            cam_cfg = OmegaConf.to_container(OmegaConf.load(cam_path))
        except Exception as e:
            logger.warning(
                "camera config %s failed to parse: %s; skipping resolution override",
                cam_path, e,
            )
            continue
        if isinstance(cam_cfg, dict):
            camera_resolutions[cam_name] = (
                int(cam_cfg.get("width", 640)),
                int(cam_cfg.get("height", 480)),
            )
    try:
        init_dataset(
            ds_root,
            fps=body.fps,
            joint_names=body.joint_names,
            camera_names=body.camera_names,
            camera_resolutions=camera_resolutions,
        )
    except FileExistsError:
        raise HTTPException(status_code=409, detail=f"dataset '{body.name}' already exists")
    info = read_dataset_info(ds_root)
    return DatasetSummary(name=body.name, num_episodes=0, total_frames=0)


@router.get("/datasets/{ds}/episodes")
async def list_episodes(request: Request, ds: str, include_deleted: bool = False):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    episodes = list(iter_episodes(ds_root, include_deleted=include_deleted))
    return [
        EpisodeSummary(
            episode_index=ep.get("episode_index", 0),
            display_index=i + 1,
            task=ep.get("task", ""),
            duration_sec=ep.get("duration_sec", 0.0),
            num_frames=ep.get("num_frames", ep.get("length", 0)),
            success=ep.get("success"),
            robot=ep.get("robot", ""),
            teleop=ep.get("teleop"),
            mode=ep.get("mode", ""),
            recorded_at=ep.get("recorded_at"),
            cameras=ep.get("cameras", []),
        )
        for i, ep in enumerate(episodes)
    ]


@router.get("/datasets/{ds}/episodes/{idx}")
async def get_episode(request: Request, ds: str, idx: int):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    for i, ep in enumerate(iter_episodes(ds_root, include_deleted=False)):
        if ep.get("episode_index") == idx:
            return EpisodeSummary(
                episode_index=ep.get("episode_index", 0),
                display_index=i + 1,
                task=ep.get("task", ""),
                duration_sec=ep.get("duration_sec", 0.0),
                num_frames=ep.get("num_frames", ep.get("length", 0)),
                success=ep.get("success"),
                robot=ep.get("robot", ""),
                teleop=ep.get("teleop"),
                mode=ep.get("mode", ""),
                recorded_at=ep.get("recorded_at"),
                cameras=ep.get("cameras", []),
            )
    raise FileNotFoundError(f"episode {idx} not found in dataset '{ds}'")


@router.delete("/datasets/{ds}/episodes/{idx}", status_code=204)
async def delete_episode(request: Request, ds: str, idx: int):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    coord = request.app.state.push_coordinator
    tombstone_episode(ds_root / "meta", idx, deleted_at_unix=int(time.time()), coordinator=coord, ds_name=ds)


@router.get("/datasets/{ds}/tasks")
async def list_tasks(request: Request, ds: str):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    tasks_path = ds_root / "meta" / "tasks.parquet"
    if not tasks_path.exists():
        return []
    table = pq.read_table(tasks_path)
    return [
        TaskSummary(
            task_index=row.get("task_index", 0),
            task=row.get("task", ""),
            instruction=row.get("instruction"),
        )
        for row in table.to_pylist()
    ]


@router.post("/datasets/{ds}/tasks")
async def create_task(request: Request, ds: str, body: CreateTaskRequest):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    coord = request.app.state.push_coordinator
    upsert_task(ds_root / "meta", body.name, body.instruction, coordinator=coord, ds_name=ds)
    # Re-read to get task_index
    tasks_path = ds_root / "meta" / "tasks.parquet"
    table = pq.read_table(tasks_path)
    for row in table.to_pylist():
        if row.get("task") == body.name:
            return TaskSummary(
                task_index=row.get("task_index", 0),
                task=row.get("task", ""),
                instruction=row.get("instruction"),
            )


@router.get("/datasets/{ds}/archive")
async def download_archive(
    request: Request, ds: str,
    format: ExportFormat = ExportFormat.LEROBOT_V3_NATIVE,
    instruction_template: str = DEFAULT_INSTRUCTION_TEMPLATE,
    robot_type: Literal["so101", "rebot"] | None = None,
):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")

    if format == ExportFormat.LEROBOT_V3_NATIVE:
        def generate():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for path_in_zip, content in build_archive_stream(ds_root):
                    if isinstance(content, Path):
                        zf.write(content, arcname=path_in_zip)
                    else:
                        zf.writestr(path_in_zip, content)
            buf.seek(0)
            yield buf.read()

        return StreamingResponse(
            generate(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{ds}.zip"'},
        )

    # format == VLA_COMPAT: convert into tempdir + build the zip eagerly so
    # ValueError translates to a real 400 (a generator-raised HTTPException
    # would fire after StreamingResponse already committed 200 OK headers).
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        override = ExportOverride(robot_type=robot_type) if robot_type else None
        try:
            export_dataset_to_local(
                ds_root=ds_root,
                dest_root=tmp_root,
                format=ExportFormat.VLA_COMPAT,
                instruction_template=instruction_template,
                force=True,
                override=override,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        converted_root = tmp_root / ds
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in sorted(converted_root.rglob("*")):
                if fp.is_file():
                    arcname = fp.relative_to(converted_root).as_posix()
                    zf.write(fp, arcname=arcname)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{ds}_vla.zip"'},
    )


@router.get("/datasets/{ds}/episodes/{idx}/video/{cam}")
async def get_episode_video(request: Request, ds: str, idx: int, cam: str):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(idx)
    video_path = paths.episode_video(chunk, cam, idx)
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    return FileResponse(video_path, media_type="video/mp4")


@router.get("/datasets/{ds}/episodes/{idx}/frames")
async def get_episode_frames(request: Request, ds: str, idx: int):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(idx)
    pq_path = paths.episode_parquet(chunk, idx)
    if not pq_path.exists():
        raise FileNotFoundError(f"parquet not found: {pq_path}")
    table = pq.read_table(pq_path)
    # Convert to JSON-safe format
    rows = []
    for row in table.to_pylist():
        clean = {}
        for k, v in row.items():
            if hasattr(v, 'tolist'):
                clean[k] = v.tolist()
            else:
                clean[k] = v
        rows.append(clean)
    return rows


class AnnotateRequest(_BaseModel):
    camera: str | None = None  # Auto-detect from episode metadata
    model: str = "google/gemma-4-E2B-it"
    sample_fps: float = 1.0
    prompt: str | None = None


class BatchAnnotateRequest(_BaseModel):
    camera: str | None = None  # Auto-detect from episode metadata
    model: str = "google/gemma-4-E2B-it"
    sample_fps: float = 1.0
    prompt: str | None = None


@router.post("/datasets/{ds}/episodes/{idx}/annotate")
async def annotate_episode_subtasks(
    request: Request, ds: str, idx: int,
    body: AnnotateRequest = AnnotateRequest(),
):
    """Annotate an episode with subtask labels using Gemma 4 VLM."""
    import asyncio
    from mimicrec.annotator.subtask import annotate_episode, save_annotations

    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")

    # Auto-detect camera from episode metadata if not specified
    camera = body.camera
    if not camera:
        for ep in iter_episodes(ds_root):
            if ep.get("episode_index") == idx:
                cams = ep.get("cameras", [])
                camera = cams[0] if cams else "front"
                break
        else:
            camera = "front"

    loop = asyncio.get_running_loop()
    segments = await loop.run_in_executor(
        None, annotate_episode, ds_root, idx, camera, body.model,
        body.sample_fps, "auto", body.prompt,
    )

    save_annotations(ds_root, idx, segments, coordinator=request.app.state.push_coordinator, ds_name=ds)

    return {
        "episode_index": idx,
        "num_subtasks": len(segments),
        "subtasks": [
            {
                "name": s.name,
                "start_frame": s.start_frame,
                "end_frame": s.end_frame,
                "description": s.description,
            }
            for s in segments
        ],
    }


@router.post("/datasets/{ds}/annotate-all")
async def annotate_all_episodes(
    request: Request, ds: str,
    body: BatchAnnotateRequest = BatchAnnotateRequest(),
):
    """Start batch annotation. Returns immediately, progress via GET."""
    from mimicrec.annotator.subtask import annotate_episode, save_annotations
    import threading

    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")

    episodes = list(iter_episodes(ds_root, include_deleted=False))

    # Store progress on app.state
    progress = {
        "dataset": ds,
        "total": len(episodes),
        "done": 0,
        "current_episode": None,
        "status": "running",
        "results": [],
    }
    request.app.state.annotate_progress = progress

    coord = request.app.state.push_coordinator

    def run():
        for ep in episodes:
            ep_idx = ep.get("episode_index", 0)
            progress["current_episode"] = ep_idx
            try:
                cam = body.camera
                if not cam:
                    cams = ep.get("cameras", [])
                    cam = cams[0] if cams else "front"
                segments = annotate_episode(
                    ds_root, ep_idx, cam, body.model,
                    body.sample_fps, "auto", body.prompt,
                )
                save_annotations(ds_root, ep_idx, segments, coordinator=coord, ds_name=ds)
                progress["results"].append({
                    "episode_index": ep_idx, "status": "ok",
                    "num_subtasks": len(segments),
                    "subtasks": [s.name for s in segments],
                })
            except Exception as e:
                progress["results"].append({
                    "episode_index": ep_idx, "status": "error", "error": str(e),
                })
            progress["done"] += 1
        progress["status"] = "done"
        progress["current_episode"] = None

    threading.Thread(target=run, daemon=True).start()

    return {"message": "started", "total": len(episodes)}


@router.get("/datasets/{ds}/annotate-progress")
async def get_annotate_progress(request: Request, ds: str):
    """Get batch annotation progress."""
    progress = getattr(request.app.state, "annotate_progress", None)
    if not progress or progress.get("dataset") != ds:
        return {"status": "idle", "total": 0, "done": 0}
    return progress


@router.post("/datasets/{ds}/export")
async def export_dataset(request: Request, ds: str, body: ExportRequest) -> ExportResponse:
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise HTTPException(status_code=404, detail=f"dataset '{ds}' not found")
    dest_root = get_vla_dest_root(request.app)
    dest_root.mkdir(parents=True, exist_ok=True)
    try:
        override = ExportOverride(robot_type=body.robot_type) if body.robot_type else None
        result = await asyncio.to_thread(
            export_dataset_to_local,
            ds_root=ds_root,
            dest_root=dest_root,
            format=body.format,
            instruction_template=body.instruction_template,
            force=body.force,
            override=override,
        )
    except DestinationExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ExportResponse(
        dest_path=str(result.dest_path),
        format=result.format,
        num_episodes=result.num_episodes,
        num_frames=result.num_frames,
        warnings=result.warnings,
    )
