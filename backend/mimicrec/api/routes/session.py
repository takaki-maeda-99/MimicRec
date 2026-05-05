from __future__ import annotations
import logging
from typing import Annotated, Union
from fastapi import APIRouter, Request
from pydantic import Field
from mimicrec.api.schemas import (
    TeleopSessionRequest, HandTeachSessionRequest, SessionStatePayload,
)
from mimicrec.api.deps import create_session_from_request, get_session_manager, get_session_manager_or_none
from mimicrec.errors import InvalidTransitionError
from mimicrec.types import SessionState

logger = logging.getLogger(__name__)


def _clear_session_state(app) -> None:
    """Drop every per-session reference held in ``app.state``.

    Used by both ``/session/end`` (operator-initiated) and
    ``/session/start`` when it finds a stale manager left over from a
    session that ended on its own (e.g., FatalHardwareError → end() ran
    in the background but app.state still pointed at the old instance).
    """
    app.state.session_manager = None
    app.state.session_meta = None
    app.state.resolved_config = None
    app.state.error_bus = None
    app.state.camera_manager = None

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
    existing = get_session_manager_or_none(request.app)
    if existing is not None:
        # A FatalHardwareError (daemon died, robot bus unresponsive, etc.)
        # spawns ``end()`` in the background, which transitions state →
        # IDLE but does not clear ``app.state.session_manager``. Treat a
        # manager in IDLE — or one that has signalled stop and is past
        # all the client-visible states — as logically gone, so the
        # operator can start a fresh session without first calling
        # /session/end manually. Anything else is a live session and we
        # refuse to clobber it.
        stopped = existing.session.stopped.is_set()
        is_idle = existing.session.state == SessionState.IDLE
        if not (is_idle or stopped):
            raise InvalidTransitionError("a session is already active")
        if not is_idle and stopped:
            # ``end()`` is still running but the caller has signalled
            # shutdown. Wait briefly for state to settle before clobbering.
            import asyncio
            for _ in range(50):  # up to ~5 s
                if existing.session.state == SessionState.IDLE:
                    break
                await asyncio.sleep(0.1)
            if existing.session.state != SessionState.IDLE:
                raise InvalidTransitionError(
                    "previous session is still ending; try again in a moment"
                )
        logger.info(
            "session_start: dropping stale manager (state=%s); starting fresh",
            existing.session.state.value,
        )
        _clear_session_state(request.app)
    sm = await create_session_from_request(request.app, body)
    await sm.start()
    request.app.state.session_manager = sm
    return build_state_payload(request.app)


@router.post("/session/end")
async def session_end(request: Request):
    sm = get_session_manager(request.app)
    await sm.end()
    _clear_session_state(request.app)
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


@router.post("/robot/estop")
async def robot_estop(request: Request):
    """Emergency stop. Hardware torque-off + software abort.

    For an INFERENCE-mode session, hardware E-stop alone is not enough:
    the producer keeps generating chunks and the dispatcher keeps trying
    to send commands (logging HardwareError each time). After
    `clear_estop`, the same in-flight inference stream would resume,
    which is surprising. So we also halt the software side here:
    `stop_inference_session` cancels producer/control/dispatcher/writer,
    closes the HTTP client, and resets session.mode → TELEOP. The
    operator must explicitly start a new inference session to resume.
    """
    from mimicrec.types import SessionMode
    sm = get_session_manager_or_none(request.app)
    if sm is None:
        raise InvalidTransitionError("no active session")
    adapter = sm._robot
    if not hasattr(adapter, "estop"):
        raise InvalidTransitionError("active robot adapter has no estop()")
    # Halt software-side command production FIRST so the dispatcher
    # doesn't keep retrying through the E-stop window.
    if sm.session.mode == SessionMode.INFERENCE:
        await sm.stop_inference_session()
    return await adapter.estop()


@router.post("/robot/clear_estop")
async def robot_clear_estop(request: Request):
    sm = get_session_manager_or_none(request.app)
    if sm is None:
        raise InvalidTransitionError("no active session")
    adapter = sm._robot
    if not hasattr(adapter, "clear_estop"):
        raise InvalidTransitionError("active robot adapter has no clear_estop()")
    return await adapter.clear_estop()
