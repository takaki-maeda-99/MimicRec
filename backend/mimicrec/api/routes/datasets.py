from __future__ import annotations
import asyncio
import io
import json
import logging
import shutil
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

from mimicrec.api.deps import get_datasets_root, get_configs_root, get_vla_dest_root
from mimicrec.api.schemas import (
    CreateDatasetRequest, CreateTaskRequest, DatasetSummary,
    EpisodeSummary, ExportFormat, ExportRequest, ExportResponse, TaskSummary,
    DEFAULT_INSTRUCTION_TEMPLATE,
)
from mimicrec.api.util import safe_dataset_path, UnsafePathError
from mimicrec.datasets.archive import build_archive_stream
from mimicrec.datasets.exporters.errors import DestinationExistsError
from mimicrec.datasets.exporters.orchestrator import export_dataset_to_local, ExportOverride
from mimicrec.datasets.reader import iter_episodes, read_dataset_info, require_live_episode
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
    root = get_datasets_root(request.app)
    try:
        ds_root = safe_dataset_path(root, ds)
    except UnsafePathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ds_root.exists():
        raise HTTPException(status_code=404, detail=f"dataset '{ds}' not found")
    coord = request.app.state.push_coordinator
    # Atomic check-and-reserve: blocks concurrent push
    if not coord.try_reserve_delete(ds):
        raise HTTPException(status_code=409, detail="cannot delete: push in flight")
    try:
        save_lock = coord.get_save_lock(ds)
        with save_lock:
            shutil.rmtree(ds_root)
            coord.drop_dataset(ds)
    except BaseException:
        coord.release(ds)
        raise


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
    require_live_episode(ds_root, idx)
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(idx)
    video_path = paths.episode_video(chunk, cam, idx)
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    return FileResponse(
        video_path,
        media_type="video/mp4",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.get("/datasets/{ds}/episodes/{idx}/frames")
async def get_episode_frames(request: Request, ds: str, idx: int):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    require_live_episode(ds_root, idx)
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


@router.get("/datasets/{ds}/schema")
async def dataset_schema(request: Request, ds: str) -> dict:
    """Returns the list of observation.images.* keys from this dataset's
    info.json. The keys are the slot names; the frontend uses this to
    pre-populate slot rows for existing datasets (works even when
    episodes/ is empty)."""
    root = get_datasets_root(request.app)
    ds_root = root / ds
    info_path = ds_root / "meta" / "info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    info = json.loads(info_path.read_text())
    image_keys = sorted(
        k.removeprefix("observation.images.")
        for k in info.get("features", {})
        if k.startswith("observation.images.")
    )
    return {"image_keys": image_keys}


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
