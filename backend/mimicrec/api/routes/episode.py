from __future__ import annotations
from fastapi import APIRouter, Request
from mimicrec.api.deps import get_session_manager
from mimicrec.api.routes.session import build_state_payload
from mimicrec.api.schemas import SaveEpisodeRequest

router = APIRouter()


@router.post("/episode/start")
async def episode_start(request: Request):
    sm = get_session_manager(request.app)
    await sm.episode_start()
    return build_state_payload(request.app)


@router.post("/episode/stop")
async def episode_stop(request: Request):
    sm = get_session_manager(request.app)
    await sm.episode_stop()
    return build_state_payload(request.app)


@router.post("/episode/save")
async def episode_save(request: Request, body: SaveEpisodeRequest = SaveEpisodeRequest()):
    sm = get_session_manager(request.app)
    await sm.episode_save(success=body.success, comment=body.comment)
    return build_state_payload(request.app)


@router.post("/episode/discard")
async def episode_discard(request: Request):
    sm = get_session_manager(request.app)
    await sm.episode_discard()
    return build_state_payload(request.app)
