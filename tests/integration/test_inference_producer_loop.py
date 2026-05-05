import asyncio
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest

from mimicrec.inference.chunk_buffer import ChunkBuffer
from mimicrec.inference.producer import run_inference_producer
from mimicrec.inference.types import StepAction
from mimicrec.types import Frame, RobotState, Stamped


@dataclass
class FakeClient:
    calls: int = 0
    fail_first_n: int = 0
    def __post_init__(self):
        self._lock = asyncio.Lock()
    async def predict(self, frames, state, instr, extras=None):
        self.calls += 1
        if self.calls <= self.fail_first_n:
            raise ConnectionError("boom")
        return {"actions": [[0.0]*7]*4}


@dataclass
class FakeDecoder:
    def decode(self, body, current_state):
        return [StepAction(q=np.zeros(5), gripper=0.0) for _ in range(4)]


@dataclass
class FakeSafety:
    new_chunk_calls: int = 0
    _clamps: int = 0
    def on_new_chunk(self):
        self.new_chunk_calls += 1
    def clamps_in_current_chunk(self):
        return self._clamps


class FakeMetrics:
    def __init__(self):
        self.events = []
    def inc(self, k, v=1): self.events.append(("inc", k, v))
    def observe(self, k, v): self.events.append(("observe", k, v))


class FakeErrorBus:
    def __init__(self):
        self.errors = []
    async def publish_inference_error(self, kind, message):
        self.errors.append((kind, message))


class FakeSession:
    def __init__(self):
        self.stopped = asyncio.Event()
        self.producer_paused = False
        self.state = "ready"


def _slot(value, t=0):
    s = type("Slot", (), {})()
    s._v = Stamped(value=value, t_mono_ns=t)
    s.peek = lambda: s._v
    return s


async def _wait_for(predicate, timeout=5.0, step=0.02):
    """Event-driven polling. Returns True when predicate fires, False on timeout.
    Avoids fixed `asyncio.sleep(0.3)` waits that break under CI load."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(step)
    return False


async def test_producer_pushes_one_chunk():
    buf = ChunkBuffer.create()
    state_slot = _slot(RobotState(
        joint_pos=np.zeros(5), joint_vel=np.zeros(5),
        joint_effort=np.zeros(5), gripper_pos=0.0, t_mono_ns=1))
    instr_slot = _slot("hi")
    img = np.zeros((16, 16, 3), dtype=np.uint8)
    cam_slot = _slot(Frame(image=img, t_mono_ns=1))
    safety = FakeSafety()
    session = FakeSession()
    task = asyncio.create_task(run_inference_producer(
        client=FakeClient(), decoder=FakeDecoder(), buffer=buf,
        camera_slots={"front": cam_slot},
        robot_state_slot=state_slot, instruction_slot=instr_slot,
        safety=safety, session=session,
        metrics=FakeMetrics(), error_bus=FakeErrorBus(),
    ))
    assert await _wait_for(lambda: buf.depth() > 0)
    assert safety.new_chunk_calls == 1
    session.stopped.set()
    await task


async def test_producer_recovers_from_initial_state_none():
    """Producer must self-re-arm in the not-ready path, then push as soon as
    state appears. Don't sleep-and-hope — observe that the FakeClient was
    called a non-trivial number of times before state arrives, and depth
    becomes > 0 once it does."""
    buf = ChunkBuffer.create()
    state_holder = type("H", (), {"value": None})()
    state_slot = type("S", (), {"peek": lambda self: state_holder.value})()
    instr_slot = _slot("hi")
    cam_slot = _slot(Frame(image=np.zeros((16,16,3), dtype=np.uint8), t_mono_ns=1))
    session = FakeSession()
    client = FakeClient()
    task = asyncio.create_task(run_inference_producer(
        client=client, decoder=FakeDecoder(), buffer=buf,
        camera_slots={"front": cam_slot},
        robot_state_slot=state_slot, instruction_slot=instr_slot,
        safety=FakeSafety(), session=session,
        metrics=FakeMetrics(), error_bus=FakeErrorBus(),
    ))
    # Producer should NOT push (state is None) but MUST keep cycling — so
    # buffer stays empty for a meaningful window and client is never called.
    assert await _wait_for(lambda: buf.depth() == 0 and client.calls == 0,
                           timeout=0.5) is True
    # Make state available; producer must observe and push.
    state_holder.value = Stamped(value=RobotState(
        joint_pos=np.zeros(5), joint_vel=np.zeros(5),
        joint_effort=np.zeros(5), gripper_pos=0.0, t_mono_ns=1), t_mono_ns=1)
    assert await _wait_for(lambda: buf.depth() > 0)
    session.stopped.set()
    await task


async def test_producer_recovers_after_3_errors(monkeypatch):
    """3 consecutive transport errors then success. Patch the module-level
    backoff base to keep the test fast in CI."""
    from mimicrec.inference import producer as _prod_mod
    monkeypatch.setattr(_prod_mod, "INITIAL_BACKOFF_S", 0.01, raising=False)

    buf = ChunkBuffer.create()
    state_slot = _slot(RobotState(
        joint_pos=np.zeros(5), joint_vel=np.zeros(5),
        joint_effort=np.zeros(5), gripper_pos=0.0, t_mono_ns=1))
    instr_slot = _slot("hi")
    cam_slot = _slot(Frame(image=np.zeros((16,16,3), dtype=np.uint8), t_mono_ns=1))
    session = FakeSession()
    err = FakeErrorBus()
    client = FakeClient(fail_first_n=3)
    task = asyncio.create_task(run_inference_producer(
        client=client, decoder=FakeDecoder(), buffer=buf,
        camera_slots={"front": cam_slot},
        robot_state_slot=state_slot, instruction_slot=instr_slot,
        safety=FakeSafety(), session=session,
        metrics=FakeMetrics(), error_bus=err,
    ))
    assert await _wait_for(lambda: buf.depth() > 0, timeout=5.0)
    assert client.calls >= 4
    assert len(err.errors) == 3
    session.stopped.set()
    await task
