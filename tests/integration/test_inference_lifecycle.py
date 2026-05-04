"""Integration tests for SessionMode.INFERENCE lifecycle.

These tests exercise start_inference_session, 409-on-active-session,
and pause/resume helpers. They depend on fixtures (fake_vla_server,
make_inference_session) defined in tests/conftest.py (Task 26).
"""
import asyncio
import pytest

from mimicrec.errors import InvalidTransitionError
from mimicrec.types import SessionMode, SessionState


async def _wait_for(predicate, timeout=5.0, step=0.02):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(step)
    return False


async def test_start_inference_against_mock_robot(make_inference_session):
    sm = await make_inference_session(instruction="pick X")
    assert sm.session.mode == SessionMode.INFERENCE
    assert sm.session.state == SessionState.READY
    assert sm._producer_task is not None and not sm._producer_task.done()
    assert sm._control_loop_task is not None and not sm._control_loop_task.done()
    assert sm._dispatcher_task is not None and not sm._dispatcher_task.done()
    assert sm._writer_task is not None and not sm._writer_task.done()


async def test_409_when_session_already_active(make_inference_session):
    sm = await make_inference_session(instruction="x")
    # Already in INFERENCE mode; another start_inference_session must fail.
    contract = sm._inference_client.spec
    with pytest.raises(InvalidTransitionError):
        await sm.start_inference_session(
            contract=contract, instruction="y",
            inference_config_name="test_contract",
        )


async def test_pause_and_resume_helpers(make_inference_session):
    sm = await make_inference_session(instruction="x")
    # Wait for producer to fill the buffer at least once.
    assert await _wait_for(lambda: sm._chunk_buffer.depth() > 0, timeout=5.0)
    # Pause + flush; depth must drop to 0 and flushed must reflect what was there.
    flushed = sm.pause_producer_and_flush()
    assert flushed > 0
    assert sm._chunk_buffer.depth() == 0
    assert sm.session.producer_paused is True
    # Resume; producer must re-arm and refill.
    sm.resume_producer()
    assert sm.session.producer_paused is False
    assert await _wait_for(lambda: sm._chunk_buffer.depth() > 0, timeout=5.0)
