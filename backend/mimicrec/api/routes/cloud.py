from __future__ import annotations
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from huggingface_hub import HfApi, get_token
from pydantic import BaseModel, Field

from mimicrec.api.deps import get_datasets_root
from mimicrec.api.util import safe_dataset_path, UnsafePathError
from mimicrec.cloud.hub_meta import HubMeta, read_hub_meta, write_hub_meta
from mimicrec.cloud.push_state import PushProgress

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
    username: str | None = None
    if token:
        try:
            who = HfApi().whoami(token=token)
            username = who.get("name") if isinstance(who, dict) else getattr(who, "name", None)
        except Exception:
            username = None
    value = {
        "authenticated": bool(token),
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
