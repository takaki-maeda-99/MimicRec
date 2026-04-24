from __future__ import annotations
from typing import Annotated, Union
from fastapi import APIRouter, Request
from pydantic import Field
from mimicrec.api.schemas import (
    TeleopSessionRequest, HandTeachSessionRequest, SessionStatePayload,
)
from mimicrec.api.deps import create_session_from_request, get_session_manager, get_session_manager_or_none
from mimicrec.errors import InvalidTransitionError

router = APIRouter()

StartSessionRequest = Annotated[
    Union[TeleopSessionRequest, HandTeachSessionRequest],
    Field(discriminator="mode"),
]


def build_state_payload(app) -> dict:
    sm = get_session_manager_or_none(app)
    meta = getattr(app.state, "session_meta", None) or {}
    if sm is None:
        return SessionStatePayload(state="idle").model_dump()
    return SessionStatePayload(
        state=sm.session.state.value,
        sub_state=sm.session.sub_state.value if sm.session.sub_state else None,
        mode=sm.session.mode.value if sm.session.mode else None,
        dataset=meta.get("dataset"),
        task=meta.get("task"),
        robot=meta.get("robot"),
        teleop=meta.get("teleop"),
        mapper=meta.get("mapper"),
        cameras=meta.get("cameras", []),
        fps=meta.get("fps"),
    ).model_dump()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/session/start")
async def session_start(request: Request, body: StartSessionRequest):
    if get_session_manager_or_none(request.app) is not None:
        raise InvalidTransitionError("a session is already active")
    sm = await create_session_from_request(request.app, body)
    await sm.start()
    request.app.state.session_manager = sm
    return build_state_payload(request.app)


@router.post("/session/end")
async def session_end(request: Request):
    sm = get_session_manager(request.app)
    await sm.end()
    request.app.state.session_manager = None
    request.app.state.session_meta = None
    request.app.state.resolved_config = None
    request.app.state.error_bus = None
    request.app.state.camera_manager = None
    return build_state_payload(request.app)


@router.get("/session/state")
async def session_state(request: Request):
    return build_state_payload(request.app)


@router.get("/session/config")
async def session_config(request: Request):
    cfg = getattr(request.app.state, "resolved_config", None)
    if cfg is None:
        raise InvalidTransitionError("no active session")
    return cfg
