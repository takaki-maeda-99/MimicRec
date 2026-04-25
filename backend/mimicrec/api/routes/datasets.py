from __future__ import annotations
import io
import json
import time
import zipfile
from pathlib import Path

import pyarrow.parquet as pq
from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel as _BaseModel

from mimicrec.api.deps import get_datasets_root, get_configs_root
from mimicrec.api.schemas import (
    CreateDatasetRequest, CreateTaskRequest, DatasetSummary,
    EpisodeSummary, TaskSummary,
)
from mimicrec.datasets.archive import build_archive_stream
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
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    shutil.rmtree(ds_root)


@router.post("/datasets")
async def create_dataset(request: Request, body: CreateDatasetRequest):
    root = get_datasets_root(request.app)
    ds_root = root / body.name
    if ds_root.exists():
        raise ValueError(f"dataset '{body.name}' already exists")
    init_dataset(ds_root, fps=body.fps, joint_names=body.joint_names, camera_names=body.camera_names)
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
        for ep in episodes
    ]


@router.get("/datasets/{ds}/episodes/{idx}")
async def get_episode(request: Request, ds: str, idx: int):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    for ep in iter_episodes(ds_root, include_deleted=False):
        if ep.get("episode_index") == idx:
            return EpisodeSummary(
                episode_index=ep.get("episode_index", 0),
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
    tombstone_episode(ds_root / "meta", idx, deleted_at_unix=int(time.time()))


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
    upsert_task(ds_root / "meta", body.name, body.instruction)
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
async def download_archive(request: Request, ds: str):
    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")

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
    camera: str = "front"
    model: str = "google/gemma-4-E4B"
    sample_fps: float = 1.0
    prompt: str | None = None


class BatchAnnotateRequest(_BaseModel):
    camera: str = "front"
    model: str = "google/gemma-4-E4B"
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

    loop = asyncio.get_running_loop()
    segments = await loop.run_in_executor(
        None, annotate_episode, ds_root, idx, body.camera, body.model,
        body.sample_fps, "cuda", body.prompt,
    )

    save_annotations(ds_root, idx, segments)

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
    """Annotate ALL episodes in a dataset with subtask labels."""
    import asyncio
    from mimicrec.annotator.subtask import annotate_episode, save_annotations

    root = get_datasets_root(request.app)
    ds_root = root / ds
    if not ds_root.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")

    episodes = list(iter_episodes(ds_root, include_deleted=False))
    results = []

    for ep in episodes:
        ep_idx = ep.get("episode_index", 0)
        try:
            loop = asyncio.get_running_loop()
            segments = await loop.run_in_executor(
                None, annotate_episode, ds_root, ep_idx, body.camera, body.model,
                body.sample_fps, "cuda", body.prompt,
            )
            save_annotations(ds_root, ep_idx, segments)
            results.append({
                "episode_index": ep_idx,
                "status": "ok",
                "num_subtasks": len(segments),
                "subtasks": [s.name for s in segments],
            })
        except Exception as e:
            results.append({
                "episode_index": ep_idx,
                "status": "error",
                "error": str(e),
            })

    return {
        "dataset": ds,
        "total": len(episodes),
        "annotated": sum(1 for r in results if r["status"] == "ok"),
        "results": results,
    }
