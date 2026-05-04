from __future__ import annotations
import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel

from mimicrec.api.deps import get_configs_root, get_session_manager_or_none
from mimicrec.api.ws.inference_hub import get_inference_hub
from mimicrec.config.inference_loader import list_inference_configs, load_inference_config
from mimicrec.errors import InvalidTransitionError

logger = logging.getLogger(__name__)

router = APIRouter()


class StartInferenceRequest(BaseModel):
    # `config` is the contract name (configs/inference/<config>.yaml). The other
    # three fields are accepted for API completeness (frontend already sends them
    # per the spec); only `inference_config_ref`/`config` and `instruction` are
    # currently consulted. `session_config_ref` and `dataset_ref` are reserved
    # for future "create session from inference start" wiring (deferred).
    config: str | None = None
    inference_config_ref: str | None = None
    session_config_ref: str | None = None
    dataset_ref: str | None = None
    instruction: str = ""


class InstructionUpdateRequest(BaseModel):
    instruction: str


@router.post("/session/inference/start")
async def start_inference(request: Request, body: StartInferenceRequest):
    """Start an INFERENCE-mode session.

    Requires an existing session in READY state (loaded robot adapter). If no
    session exists, returns 503. Starting a session from scratch in inference
    mode (without a prior teleop/handteach start) is deferred to Task 26+.
    """
    sm = get_session_manager_or_none(request.app)
    if sm is None:
        raise InvalidTransitionError(
            "no active session adapter; start a teleop session first to load "
            "the robot then call /session/inference/start"
        )
    config_name = body.config or body.inference_config_ref
    if not config_name:
        raise InvalidTransitionError(
            "request must include `config` (or `inference_config_ref`) — the contract YAML name"
        )
    configs_root = get_configs_root(request.app)
    contract = load_inference_config(configs_root, config_name)
    sm.inference_hub = get_inference_hub(request.app)
    await sm.start_inference_session(
        contract=contract,
        instruction=body.instruction,
        inference_config_name=config_name,
    )
    return sm.inference_state_snapshot()


@router.post("/session/inference/stop")
async def stop_inference(request: Request):
    """Stop the current INFERENCE-mode session."""
    sm = get_session_manager_or_none(request.app)
    if sm is None:
        raise InvalidTransitionError("no active session")
    await sm.stop_inference_session()
    return {"status": "stopped"}


@router.put("/session/inference/instruction")
async def update_instruction(request: Request, body: InstructionUpdateRequest):
    """Update the instruction slot for the running inference session.

    Per spec §8.3, the instruction is **locked during RECORDING** — one episode,
    one task. Calling this endpoint while the session is RECORDING returns 409
    so an operator can't accidentally split an episode's instruction. The
    locked text is captured at episode_start and persisted to tasks.parquet
    on commit.

    Returns 409 if called outside of INFERENCE mode or during RECORDING.
    """
    from mimicrec.types import SessionMode, SessionState
    sm = get_session_manager_or_none(request.app)
    if sm is None:
        raise InvalidTransitionError("no active session")
    if sm.session.mode != SessionMode.INFERENCE:
        raise InvalidTransitionError(
            f"instruction update requires INFERENCE mode, got {sm.session.mode.value}"
        )
    if sm.session.state == SessionState.RECORDING:
        raise InvalidTransitionError(
            "instruction is locked during RECORDING; stop the episode first"
        )
    import time
    sm._instruction_slot.set(body.instruction, t_mono_ns=time.monotonic_ns())
    # Spec §8.1 Q17: PUT during READY flushes the chunk buffer so the producer
    # fetches a fresh chunk under the new instruction. The brief gap is
    # absorbed by safety.slow_stop until the next chunk arrives.
    flushed = sm._chunk_buffer.flush() if sm._chunk_buffer is not None else 0
    if sm.inference_hub is not None:
        await sm.inference_hub.publish({
            "type": "instruction_updated",
            "instruction": body.instruction,
            "flushed_steps": flushed,
        })
    return {"instruction": body.instruction, "flushed_steps": flushed}


@router.get("/session/inference/state")
async def inference_state(request: Request):
    """Return the current inference session state snapshot for polling clients."""
    sm = get_session_manager_or_none(request.app)
    if sm is None:
        return {"phase": "pre_start"}
    return sm.inference_state_snapshot()


@router.get("/configs/inference")
async def list_inference(request: Request):
    """List all inference contract configs available on disk."""
    configs_root = get_configs_root(request.app)
    return list_inference_configs(configs_root)


@router.get("/configs/inference/{name}")
async def get_inference_config(request: Request, name: str):
    """Return the full contract spec for a named inference config."""
    configs_root = get_configs_root(request.app)
    try:
        spec = load_inference_config(configs_root, name)
    except FileNotFoundError:
        raise InvalidTransitionError(f"inference config '{name}' not found")
    return spec.model_dump()
