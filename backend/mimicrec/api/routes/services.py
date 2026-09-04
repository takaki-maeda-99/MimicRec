"""Local operator endpoints for allow-listed systemd user services."""
from __future__ import annotations

import ipaddress
import os

from fastapi import APIRouter, Header, HTTPException, Request, Response
from omegaconf import OmegaConf
from pydantic import BaseModel

from mimicrec.adapters.rebotarm_protocol import DEFAULT_ZMQ_ADDRESS
from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter
from mimicrec.api.deps import get_configs_root
from mimicrec.services.systemd import ServiceCommandError, SystemdUserServiceManager

router = APIRouter()


class ServiceActionRequest(BaseModel):
    confirm_hardware_ready: bool = False


def get_service_manager(app) -> SystemdUserServiceManager:
    manager = getattr(app.state, "service_manager", None)
    if manager is None:
        manager = SystemdUserServiceManager()
        app.state.service_manager = manager
    return manager


def _request_is_local(request: Request) -> bool:
    if request.client is None:
        return True
    host = request.client.host
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _active_session(app) -> bool:
    sm = getattr(app.state, "session_manager", None)
    if sm is None:
        return False
    session = getattr(sm, "session", None)
    state = getattr(session, "state", None)
    state_value = getattr(state, "value", state)
    stopped = getattr(session, "stopped", None)
    return state_value != "idle" and not (stopped and stopped.is_set())


def _authorize_mutation(request: Request, control_header: str | None) -> None:
    # This is a CSRF marker, not authentication. A browser cannot attach this
    # non-simple header until the restricted CORS preflight has succeeded.
    if control_header != "1":
        raise HTTPException(status_code=403, detail="missing service-control header")
    require_local = os.environ.get(
        "MIMICREC_SERVICE_CONTROL_REQUIRE_LOCAL", "1"
    ).strip().lower() not in {"0", "false", "no", "off"}
    if require_local and not _request_is_local(request):
        raise HTTPException(
            status_code=403,
            detail="service control is restricted to the local UI proxy",
        )


async def _clear_rebotarm_fault(app) -> dict:
    """Use a short-lived ZMQ client so recovery works without a session."""
    robot_cfg_path = get_configs_root(app) / "robot" / "rebotarm.yaml"
    address = DEFAULT_ZMQ_ADDRESS
    if robot_cfg_path.exists():
        robot_cfg = OmegaConf.load(robot_cfg_path)
        address = str(robot_cfg.get("address", DEFAULT_ZMQ_ADDRESS))

    adapter = ReBotArmZmqAdapter(
        address=address,
        heartbeat_interval_ms=200,
        request_timeout_ms=10_000,
    )
    try:
        await adapter.connect()
        return await adapter.clear_fault(confirm_hardware_ready=True)
    finally:
        await adapter.disconnect()


@router.get("/services")
async def list_services(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    manager = get_service_manager(request.app)
    return [status.model_dict() for status in await manager.list_status()]


@router.post("/services/{service_id}/{action}")
async def service_action(
    request: Request,
    service_id: str,
    action: str,
    body: ServiceActionRequest,
    response: Response,
    x_mimicrec_control: str | None = Header(default=None),
):
    response.headers["Cache-Control"] = "no-store"
    _authorize_mutation(request, x_mimicrec_control)
    manager = get_service_manager(request.app)

    try:
        definition = manager.definition(service_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if action not in {"start", "stop", "restart", "clear-fault"}:
        raise HTTPException(status_code=404, detail="unsupported service action")
    if action == "clear-fault" and service_id != "rebotarm":
        raise HTTPException(status_code=404, detail="unsupported service action")
    if _active_session(request.app):
        raise HTTPException(
            status_code=409,
            detail="end the active recording, replay, or inference session first",
        )
    if definition.safety_critical and action in {"start", "restart", "clear-fault"}:
        if not body.confirm_hardware_ready:
            raise HTTPException(
                status_code=409,
                detail="explicit hardware-ready confirmation is required",
            )

    if action == "clear-fault":
        try:
            result = await _clear_rebotarm_fault(request.app)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not result.get("ok"):
            raise HTTPException(
                status_code=503,
                detail=f"one or more motors rejected clear_fault: {result}",
            )
        return result

    try:
        status = await manager.act(service_id, action)
    except ServiceCommandError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return status.model_dict()
