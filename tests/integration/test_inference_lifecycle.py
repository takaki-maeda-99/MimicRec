"""Integration tests for SessionMode.INFERENCE lifecycle.

These tests exercise start_inference_session, 409-on-active-session,
and pause/resume helpers. They depend on fixtures (fake_vla_server,
make_inference_session) that land in Task 26.

Each test is currently a pytest.skip placeholder. Replace skips with
real bodies when Task 26 fixture is available.
"""
import asyncio
import pytest

from mimicrec.types import SessionMode, SessionState


async def test_start_inference_against_mock_robot():
    """Start inference session, give it a brief moment, then stop. Expect:
    - control_loop and producer tasks spawned
    - SessionMode = INFERENCE, SessionState = READY
    - dispatcher + writer present
    """
    pytest.skip("complete after Task 26 (fake_vla_server fixture + make_session_manager)")


async def test_409_when_session_already_active():
    """Starting an inference session while one is active must raise InvalidTransitionError."""
    pytest.skip("complete after Task 26")


async def test_pause_and_resume_helpers():
    """Sequence (per Task 26 Step 4 sub-requirements):
    1. make_inference_session(...)
    2. _wait_for(buffer.depth() > 0) — let producer fill once
    3. flushed = pause_producer_and_flush(); assert flushed > 0; assert producer_paused
    4. resume_producer()
    5. _wait_for(buffer.depth() > 0) — proves resume re-armed and producer fetched fresh
    """
    pytest.skip("complete after Task 26")
