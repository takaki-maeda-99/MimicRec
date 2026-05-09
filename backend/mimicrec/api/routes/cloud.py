from __future__ import annotations
import asyncio
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from huggingface_hub import HfApi, get_token
from pydantic import BaseModel, Field

from mimicrec.api.deps import get_datasets_root
from mimicrec.api.util import safe_dataset_path, UnsafePathError
from mimicrec.cloud.hf_pusher import push_dataset
from mimicrec.cloud.hub_meta import HubMeta, read_hub_meta, write_hub_meta, compute_manifest_hash
from mimicrec.cloud.push_state import PushProgress
from mimicrec.cloud.snapshot import (
    make_push_snapshot, cleanup_snapshot, collect_tombstoned_files,
)

router = APIRouter()

_REPO_ID_RE = re.compile(r"^[\w][\w.-]*\/[\w][\w.-]*$")
_AUTH_TTL_SEC = 60.0


class HubConfig(BaseModel):
    repo_id: str = Field(..., min_length=3)
    private: bool = True
    auto_push: bool = False


class AuthStatus(BaseModel):
    authenticated: bool
    username: str | None
    checked_at: str


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_ds(request: Request, ds: str) -> Path:
    root = get_datasets_root(request.app)
    try:
        ds_root = safe_dataset_path(root, ds)
    except UnsafePathError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ds_root.exists():
        raise HTTPException(status_code=404, detail=f"dataset '{ds}' not found")
    return ds_root


@router.get("/cloud/auth-status")
async def auth_status(request: Request, refresh: int = 0) -> AuthStatus:
    cache = getattr(request.app.state, "auth_cache", None)
    now = time.monotonic()
    if not refresh and cache is not None and now - cache["t"] < _AUTH_TTL_SEC:
        return AuthStatus(**cache["value"])

    token = get_token()
    authenticated = False
    username: str | None = None
    if token:
        try:
            who = HfApi().whoami(token=token)
            username = who.get("name") if isinstance(who, dict) else getattr(who, "name", None)
            # Only consider authenticated if whoami succeeded
            authenticated = username is not None
        except Exception:
            authenticated = False
    value = {
        "authenticated": authenticated,
        "username": username,
        "checked_at": _iso_now(),
    }
    request.app.state.auth_cache = {"t": now, "value": value}
    return AuthStatus(**value)


@router.get("/datasets/{ds}/hub")
async def get_hub(request: Request, ds: str):
    ds_root = _resolve_ds(request, ds)
    meta = read_hub_meta(ds_root)
    coord = request.app.state.push_coordinator
    progress = coord.progress.get(ds, PushProgress())
    return {
        "config": (
            None if meta is None else
            {"repo_id": meta.repo_id, "private": meta.private, "auto_push": meta.auto_push}
        ),
        "state": (
            None if meta is None else
            {
                "last_pushed_at": meta.last_pushed_at,
                "last_pushed_commit_sha": meta.last_pushed_commit_sha,
                "last_pushed_manifest_hash": meta.last_pushed_manifest_hash,
                "last_push_error": meta.last_push_error,
            }
        ),
        "progress": {
            "status": progress.status,
            "started_at": progress.started_at,
            "ended_at": progress.ended_at,
            "error": progress.error,
        },
    }


@router.put("/datasets/{ds}/hub")
async def put_hub(request: Request, ds: str, body: HubConfig):
    ds_root = _resolve_ds(request, ds)
    if not _REPO_ID_RE.match(body.repo_id):
        raise HTTPException(status_code=400, detail=f"invalid repo_id: {body.repo_id!r}")
    existing = read_hub_meta(ds_root)
    new = HubMeta(
        repo_id=body.repo_id,
        private=body.private,
        auto_push=body.auto_push,
        last_pushed_at=existing.last_pushed_at if existing else None,
        last_pushed_commit_sha=existing.last_pushed_commit_sha if existing else None,
        last_pushed_manifest_hash=existing.last_pushed_manifest_hash if existing else None,
        last_push_error=existing.last_push_error if existing else None,
    )
    write_hub_meta(ds_root, new)
    return await get_hub(request, ds)


@router.post("/datasets/{ds}/hub/push", status_code=202)
async def post_push(request: Request, ds: str):
    ds_root = _resolve_ds(request, ds)   # path 400 / 存在 404
    if not get_token():
        raise HTTPException(status_code=401, detail="not authenticated; run `huggingface-cli login`")
    meta = read_hub_meta(ds_root)
    if meta is None:
        raise HTTPException(status_code=400, detail="hub not configured for this dataset")
    coord = request.app.state.push_coordinator
    if not coord.try_reserve(ds):
        raise HTTPException(status_code=409, detail="push already in flight")
    coord.progress[ds] = PushProgress(
        status="queued", repo_id=meta.repo_id, started_at=_iso_now()
    )
    asyncio.create_task(_run_push_with_release(request.app, ds, ds_root))
    return {"status": "queued"}


async def _run_push_with_release(app, ds_name: str, ds_root: Path):
    coord = app.state.push_coordinator
    try:
        await _push_task(app, ds_name, ds_root)
    finally:
        coord.release(ds_name)


async def _push_task(app, ds_name: str, ds_root: Path):
    coord = app.state.push_coordinator
    save_lock = coord.get_save_lock(ds_name)
    coord.progress[ds_name].status = "uploading"

    snap: Path | None = None
    meta_at_start = None
    tombstoned: list[str] = []
    start_hash: str | None = None
    push_error: BaseException | None = None
    result = None

    def _take_snapshot():
        with save_lock:
            m = read_hub_meta(ds_root)
            if m is None:
                raise RuntimeError("hub config disappeared during push")
            t = collect_tombstoned_files(ds_root)
            sh = compute_manifest_hash(ds_root)
            s = make_push_snapshot(ds_root)
            return m, t, sh, s

    try:
        meta_at_start, tombstoned, start_hash, snap = await asyncio.to_thread(_take_snapshot)
    except Exception as e:
        await asyncio.to_thread(_finalize_with_error, app, ds_name, ds_root, e)
        return

    inner = asyncio.create_task(asyncio.to_thread(
        push_dataset, snap, meta_at_start.repo_id,
        private=meta_at_start.private, tombstoned_files=tombstoned,
    ))
    try:
        result = await asyncio.shield(inner)
    except asyncio.CancelledError:
        try:
            result = await inner
        except BaseException as e:
            push_error = e
    except Exception as e:
        push_error = e

    def _finalize():
        try:
            with save_lock:
                current = read_hub_meta(ds_root) or meta_at_start
                end_hash = compute_manifest_hash(ds_root)
                if push_error or result is None:
                    msg = str(push_error) if push_error else "push aborted"
                    current.last_push_error = msg
                    coord.progress[ds_name].status = "error"
                    coord.progress[ds_name].error = msg
                else:
                    current.last_pushed_commit_sha = result.commit_sha
                    current.last_pushed_at = _iso_now()
                    current.last_pushed_manifest_hash = (
                        start_hash if end_hash == start_hash else None
                    )
                    current.last_push_error = None
                    coord.progress[ds_name].status = "done"
                    coord.progress[ds_name].error = None
                    coord.progress[ds_name].last_pushed_commit_sha = result.commit_sha
                coord.progress[ds_name].ended_at = _iso_now()
                write_hub_meta(ds_root, current)
        finally:
            if snap is not None:
                cleanup_snapshot(snap)

    await asyncio.to_thread(_finalize)


def _finalize_with_error(app, ds_name: str, ds_root: Path, error: BaseException):
    coord = app.state.push_coordinator
    save_lock = coord.get_save_lock(ds_name)
    with save_lock:
        existing = read_hub_meta(ds_root)
        if existing is not None:
            existing.last_push_error = str(error)
            write_hub_meta(ds_root, existing)
        coord.progress[ds_name].status = "error"
        coord.progress[ds_name].error = str(error)
        coord.progress[ds_name].ended_at = _iso_now()

