from __future__ import annotations
from fastapi import APIRouter, Request
from mimicrec.api.deps import get_session_manager, get_datasets_root
from mimicrec.api.routes.session import build_state_payload
from mimicrec.api.schemas import ReplayStartRequest
from mimicrec.datasets.reader import (
    load_motion_replay_trajectory,
    load_replay_trajectory,
    read_dataset_info,
)

router = APIRouter()


@router.post("/replay/start")
async def replay_start(request: Request, body: ReplayStartRequest):
    sm = get_session_manager(request.app)
    datasets_root = get_datasets_root(request.app)
    ds_root = datasets_root / body.dataset
    info = read_dataset_info(ds_root)
    trajectory = (
        load_motion_replay_trajectory(ds_root, body.episode_idx)
        if info.get("robot_type") == "motion_graph"
        else load_replay_trajectory(ds_root, body.episode_idx)
    )
    if hasattr(trajectory, "frames"):
        trajectory.speed = body.speed
    await sm.replay_start(trajectory)
    return build_state_payload(request.app)


@router.post("/replay/stop")
async def replay_stop(request: Request):
    sm = get_session_manager(request.app)
    await sm.replay_stop()
    return build_state_payload(request.app)
